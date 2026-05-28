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
