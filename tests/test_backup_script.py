"""Offline regression for scripts/backup_db.sh.

Two safety boundaries the script defends:
- the KEEP retention guard runs in **pre-flight** (a 0 / negative / non-numeric KEEP would make the
  prune step's `tail -n +$((KEEP + 1))` resolve to `+1` and select EVERY archive for deletion — a
  config typo turning into total backup loss; KEEP governs LOCAL state mutation, so the guard MUST
  run before any state is touched);
- the off-box validation (`OFFSITE_KEEP_DAYS` is a positive integer; rclone is on PATH when
  `BACKUP_REMOTE` is set) runs **inside the off-box phase, AFTER the local dump is durable** — so a
  misconfigured optional add-on can never disable the core local backup (Codex adversarial review,
  2026-05-27).

And the off-box behavior itself, exercised end-to-end with stubbed `docker` (fakes the pg_dump
stream) and stubbed `rclone` (records args, configurable exit):
- BACKUP_REMOTE unset → rclone is never invoked (today's backwards-compatible default);
- happy path → rclone copy + age-bounded delete fire with the right args;
- copy failure → script exits non-zero, the local dump is preserved, the remote prune is skipped;
- misconfigured off-box (bad days / missing rclone) → script exits non-zero, the local dump still
  lands; rclone is never invoked.

These run offline. The KEEP-guard fast path bypasses docker (the pre-flight aborts first); every
other path uses PATH-stubbed docker so no real container is needed. Self-skips without bash.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "backup_db.sh"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")


def _make_stub(bindir: Path, name: str, body: str) -> Path:
    """Write a `name` shim in `bindir` with body, make it executable, return its path."""
    stub = bindir / name
    stub.write_text("#!/usr/bin/env bash\n" + textwrap.dedent(body))
    stub.chmod(0o755)
    return stub


def _run(script_env: dict, repo_dir: Path, backup_dir: Path, bindir: Path | None = None):
    """Invoke backup_db.sh with the given env + a PATH that puts `bindir` ahead of the system path.

    Inheriting the host PATH means real `mkdir`/`ls`/`tail`/`du` work; the stubs in bindir (when
    given) shadow `docker`/`rclone`.
    """
    path = f"{bindir}:{os.environ.get('PATH', '')}" if bindir else os.environ.get("PATH", "")
    env = {
        **os.environ,
        "PATH": path,
        "REPO_DIR": str(repo_dir),
        "BACKUP_DIR": str(backup_dir),
        **script_env,
    }
    return subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True)


# ---- KEEP retention guard --------------------------------------------------------------------


@pytest.mark.parametrize("bad", ["0", "-1", "foo", "3.5"])
def test_invalid_keep_fails_closed_and_deletes_nothing(tmp_path, bad):
    backups = tmp_path / "backups"
    backups.mkdir()
    existing = [backups / f"doppel-2026010{i}-000000.dump" for i in range(1, 4)]
    for f in existing:
        f.write_bytes(b"PGDMP-fake")

    result = _run({"KEEP": bad}, repo_dir=tmp_path, backup_dir=backups)

    assert result.returncode != 0, f"KEEP={bad!r} should fail closed, got exit 0"
    assert "KEEP" in result.stderr
    # The pre-existing archives must all survive — the guard aborts before the prune step.
    assert all(f.exists() for f in existing)


# ---- Misconfigured off-box must not block the core local backup -----------------------------
# (Codex adversarial review, 2026-05-27: an optional add-on must never disable the core feature.)


@pytest.mark.parametrize("bad", ["0", "-1", "foo", "3.5"])
def test_invalid_offsite_keep_days_skips_offsite_but_preserves_local_dump(tmp_path, bad):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    _make_docker_dump_stub(bindir)
    # rclone is loud here: validation must reject the OFFSITE_KEEP_DAYS value BEFORE invoking rclone.
    log = tmp_path / "rclone.log"
    _make_stub(bindir, "rclone", f'echo "$@" >> "{log}"\nexit 99\n')
    backups = tmp_path / "backups"
    backups.mkdir()

    result = _run(
        {"BACKUP_REMOTE": "r2-crypt:", "OFFSITE_KEEP_DAYS": bad},
        repo_dir=tmp_path,
        backup_dir=backups,
        bindir=bindir,
    )

    assert result.returncode != 0, f"OFFSITE_KEEP_DAYS={bad!r} should exit non-zero for cron visibility"
    assert "OFFSITE_KEEP_DAYS" in result.stderr
    # The CORE behavior — a fresh local dump must land despite the off-box misconfig.
    dumps = list(backups.glob("doppel-*.dump"))
    assert len(dumps) == 1, f"local dump must be retained on off-box misconfig, got: {dumps}"
    # And rclone is never invoked — validation rejected the config first.
    assert not log.exists() or log.read_text() == ""


def test_rclone_missing_skips_offsite_but_preserves_local_dump(tmp_path):
    # Empty bindir for rclone: PATH = bindir + system, so `command -v rclone` fails iff the system
    # also lacks rclone. Skip rather than assert when the host has rclone installed for other reasons.
    bindir = tmp_path / "bin"
    bindir.mkdir()
    _make_docker_dump_stub(bindir)
    if shutil.which("rclone") is not None:
        pytest.skip("rclone is installed system-wide; can't isolate the missing-rclone case")
    backups = tmp_path / "backups"
    backups.mkdir()

    result = _run(
        {"BACKUP_REMOTE": "r2-crypt:"},
        repo_dir=tmp_path,
        backup_dir=backups,
        bindir=bindir,
    )

    assert result.returncode != 0
    assert "rclone" in result.stderr
    # The CORE behavior — local dump still produced despite missing optional tooling.
    dumps = list(backups.glob("doppel-*.dump"))
    assert len(dumps) == 1, f"local dump must be retained on missing rclone, got: {dumps}"


# ---- Off-box mirror behavior ----------------------------------------------------------------


def _make_docker_dump_stub(bindir: Path) -> Path:
    """Stub `docker` so `docker compose ... pg_dump ...` writes plausible -Fc bytes to stdout."""
    return _make_stub(
        bindir,
        "docker",
        # Any argv — just emit something non-empty (the script rejects an empty archive).
        'printf "PGDMP-fake-backup-content\\n"\nexit 0\n',
    )


def _make_rclone_logging_stub(bindir: Path, log: Path, *, copy_exit: int = 0, delete_exit: int = 0) -> Path:
    """Stub `rclone` that records `$@` per-invocation to `log` and exits with subcommand-specific code."""
    body = f"""
        echo "$@" >> "{log}"
        case "$1" in
            copy)   exit {copy_exit} ;;
            delete) exit {delete_exit} ;;
            *)      exit 0 ;;
        esac
    """
    return _make_stub(bindir, "rclone", body)


def test_unset_remote_skips_offsite_phase(tmp_path):
    """BACKUP_REMOTE unset is the no-op default — rclone must never be called."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    _make_docker_dump_stub(bindir)
    log = tmp_path / "rclone.log"
    # Stub rclone but make it loud: any invocation fails the test.
    _make_stub(bindir, "rclone", f'echo "$@" >> "{log}"\nexit 1\n')
    backups = tmp_path / "backups"
    backups.mkdir()

    result = _run({}, repo_dir=tmp_path, backup_dir=backups, bindir=bindir)

    assert result.returncode == 0, result.stderr
    assert list(backups.glob("doppel-*.dump"))  # local dump still written
    assert not log.exists() or log.read_text() == ""  # rclone never invoked


def test_remote_happy_path_uploads_and_prunes_by_age(tmp_path):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    _make_docker_dump_stub(bindir)
    log = tmp_path / "rclone.log"
    _make_rclone_logging_stub(bindir, log)
    backups = tmp_path / "backups"
    backups.mkdir()

    result = _run(
        {"BACKUP_REMOTE": "r2-crypt:", "OFFSITE_KEEP_DAYS": "30"},
        repo_dir=tmp_path,
        backup_dir=backups,
        bindir=bindir,
    )

    assert result.returncode == 0, f"stderr: {result.stderr}\nstdout: {result.stdout}"
    dumps = list(backups.glob("doppel-*.dump"))
    assert len(dumps) == 1
    dump = dumps[0]

    invocations = [line for line in log.read_text().splitlines() if line]
    assert len(invocations) == 2, f"expected copy+delete, got: {invocations}"

    copy_args, delete_args = invocations
    # `rclone copy --no-traverse <dump> <remote>`
    assert "copy" in copy_args and "--no-traverse" in copy_args
    assert str(dump) in copy_args
    assert "r2-crypt:" in copy_args
    # `rclone delete --min-age 30d --include "doppel-*.dump" <remote>`
    assert "delete" in delete_args
    assert "--min-age" in delete_args and "30d" in delete_args
    assert "--include" in delete_args and "doppel-*.dump" in delete_args
    assert "r2-crypt:" in delete_args


def test_remote_copy_failure_exits_nonzero_and_preserves_local_dump(tmp_path):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    _make_docker_dump_stub(bindir)
    log = tmp_path / "rclone.log"
    _make_rclone_logging_stub(bindir, log, copy_exit=7)
    backups = tmp_path / "backups"
    backups.mkdir()

    result = _run(
        {"BACKUP_REMOTE": "r2-crypt:"},
        repo_dir=tmp_path,
        backup_dir=backups,
        bindir=bindir,
    )

    assert result.returncode != 0
    assert "rclone copy" in result.stderr
    # Local dump survives so a future re-run still has the data.
    dumps = list(backups.glob("doppel-*.dump"))
    assert len(dumps) == 1, f"local dump must be retained on upload failure, got: {dumps}"
    # Only the failed copy was attempted; remote prune must not run on a failed upload.
    invocations = [line for line in log.read_text().splitlines() if line]
    assert len(invocations) == 1
    assert invocations[0].startswith("copy")


# ---- Healthcheck notifier (passive dead-man's switch) ----------------------------------------
# /start fires AFTER pre-flight (config-error → /fail without phantom /start); success fires AFTER
# the off-box block (so BACKUP_REMOTE failures still alert); an EXIT trap pings /fail on any
# non-zero exit. URL is the credential — never echoed. curl errors are intentionally swallowed: a
# notifier outage must never fail an otherwise-good backup.


def _make_curl_logging_stub(bindir: Path, log: Path, *, exit_code: int = 0) -> Path:
    """Stub `curl` that records `$@` per-invocation to `log` and exits with `exit_code`."""
    return _make_stub(
        bindir,
        "curl",
        f'echo "$@" >> "{log}"\nexit {exit_code}\n',
    )


def test_no_healthcheck_url_skips_all_pings(tmp_path):
    """BACKUP_HEALTHCHECK_URL unset is the no-op default — curl must never be called."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    _make_docker_dump_stub(bindir)
    log = tmp_path / "curl.log"
    # Stub curl loud: any invocation fails the test.
    _make_stub(bindir, "curl", f'echo "$@" >> "{log}"\nexit 1\n')
    backups = tmp_path / "backups"
    backups.mkdir()

    # Explicit empty string defeats any leaked host env (the script treats "" as unset via [[ -z ]]).
    result = _run({"BACKUP_HEALTHCHECK_URL": ""}, repo_dir=tmp_path, backup_dir=backups, bindir=bindir)

    assert result.returncode == 0, result.stderr
    assert not log.exists() or log.read_text() == "", "curl must not be invoked when URL is unset"


def test_healthcheck_happy_path_pings_start_then_success(tmp_path):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    _make_docker_dump_stub(bindir)
    log = tmp_path / "curl.log"
    _make_curl_logging_stub(bindir, log)
    backups = tmp_path / "backups"
    backups.mkdir()
    url = "https://hc-ping.example/abc-123"

    result = _run({"BACKUP_HEALTHCHECK_URL": url}, repo_dir=tmp_path, backup_dir=backups, bindir=bindir)

    assert result.returncode == 0, result.stderr
    invocations = [line for line in log.read_text().splitlines() if line]
    # Two pings: /start, then success (bare URL, no suffix).
    assert len(invocations) == 2, f"expected /start + success, got: {invocations}"
    start_args, success_args = invocations
    assert f"{url}/start" in start_args
    assert url in success_args
    assert "/start" not in success_args and "/fail" not in success_args


def test_healthcheck_pings_fail_on_pg_dump_failure(tmp_path):
    """pg_dump failure pings /fail via the EXIT trap (after /start already fired)."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    # Failing docker stub — pg_dump appears to break.
    _make_stub(bindir, "docker", 'echo "pg_dump simulated failure" >&2\nexit 1\n')
    log = tmp_path / "curl.log"
    _make_curl_logging_stub(bindir, log)
    backups = tmp_path / "backups"
    backups.mkdir()
    url = "https://hc-ping.example/abc-123"

    result = _run({"BACKUP_HEALTHCHECK_URL": url}, repo_dir=tmp_path, backup_dir=backups, bindir=bindir)

    assert result.returncode != 0
    invocations = [line for line in log.read_text().splitlines() if line]
    # /start was sent (after pre-flight), then trap fired /fail.
    assert len(invocations) == 2, f"expected /start + /fail, got: {invocations}"
    assert f"{url}/start" in invocations[0]
    assert f"{url}/fail" in invocations[1]


def test_healthcheck_pings_fail_without_start_on_keep_guard_failure(tmp_path):
    """KEEP guard fails BEFORE /start fires — only /fail is pinged, no phantom 'started' state."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    # docker/rclone must not be reached; if they are, the test catches the regression.
    _make_stub(bindir, "docker", "exit 99\n")
    _make_stub(bindir, "rclone", "exit 99\n")
    log = tmp_path / "curl.log"
    _make_curl_logging_stub(bindir, log)
    backups = tmp_path / "backups"
    backups.mkdir()
    url = "https://hc-ping.example/abc-123"

    result = _run(
        {"BACKUP_HEALTHCHECK_URL": url, "KEEP": "0"},
        repo_dir=tmp_path,
        backup_dir=backups,
        bindir=bindir,
    )

    assert result.returncode != 0
    assert "KEEP" in result.stderr
    invocations = [line for line in log.read_text().splitlines() if line]
    assert len(invocations) == 1, f"expected /fail only (no /start), got: {invocations}"
    assert f"{url}/fail" in invocations[0]
    assert "/start" not in invocations[0]


def test_healthcheck_pings_fail_on_rclone_copy_failure(tmp_path):
    """Off-box failures still alert: rclone copy fails → trap pings /fail after /start."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    _make_docker_dump_stub(bindir)
    _make_rclone_logging_stub(bindir, tmp_path / "rclone.log", copy_exit=7)
    log = tmp_path / "curl.log"
    _make_curl_logging_stub(bindir, log)
    backups = tmp_path / "backups"
    backups.mkdir()
    url = "https://hc-ping.example/abc-123"

    result = _run(
        {"BACKUP_HEALTHCHECK_URL": url, "BACKUP_REMOTE": "r2-crypt:"},
        repo_dir=tmp_path,
        backup_dir=backups,
        bindir=bindir,
    )

    assert result.returncode != 0
    invocations = [line for line in log.read_text().splitlines() if line]
    assert len(invocations) == 2, f"expected /start + /fail, got: {invocations}"
    assert f"{url}/start" in invocations[0]
    assert f"{url}/fail" in invocations[1]


def test_healthcheck_curl_failure_does_not_fail_backup(tmp_path):
    """A notifier outage (curl returns non-zero) must not fail an otherwise-good backup."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    _make_docker_dump_stub(bindir)
    log = tmp_path / "curl.log"
    _make_curl_logging_stub(bindir, log, exit_code=7)  # 7 = "Failed to connect to host"
    backups = tmp_path / "backups"
    backups.mkdir()
    url = "https://hc-ping.example/abc-123"

    result = _run({"BACKUP_HEALTHCHECK_URL": url}, repo_dir=tmp_path, backup_dir=backups, bindir=bindir)

    assert result.returncode == 0, f"notifier outage must not fail backup; stderr: {result.stderr}"
    dumps = list(backups.glob("doppel-*.dump"))
    assert len(dumps) == 1, "local dump must land even when notifier is unreachable"
    invocations = [line for line in log.read_text().splitlines() if line]
    # Both /start and success were attempted, even though each curl call failed.
    assert len(invocations) == 2


def test_healthcheck_url_is_not_echoed_in_logs(tmp_path):
    """The URL is the credential — log lines must refer to the ping type, not paste the URL."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    _make_docker_dump_stub(bindir)
    _make_curl_logging_stub(bindir, tmp_path / "curl.log")
    backups = tmp_path / "backups"
    backups.mkdir()
    # A unique marker that can't appear anywhere else by coincidence — low-entropy on purpose so
    # the secret scanner doesn't mistake the fixture for a real credential.
    unique_marker = "fake-ping-id-for-redaction-test"
    url = f"https://hc-ping.example/{unique_marker}"

    result = _run({"BACKUP_HEALTHCHECK_URL": url}, repo_dir=tmp_path, backup_dir=backups, bindir=bindir)

    assert result.returncode == 0, result.stderr
    assert unique_marker not in result.stdout, "URL token must not be echoed to stdout"
    assert unique_marker not in result.stderr, "URL token must not be echoed to stderr"
