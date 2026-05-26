"""Offline regression for scripts/backup_db.sh's retention guard.

A 0 / negative / non-numeric KEEP would make the prune step's `tail -n +$((KEEP + 1))` resolve to
`+1` and select EVERY archive for deletion — a config typo turning into total backup loss. The script
must validate KEEP up front and fail closed, *before* touching the backup dir. These run offline (the
validation aborts before the pg_dump, so no Postgres/Docker is needed); they self-skip without bash.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "backup_db.sh"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")


@pytest.mark.parametrize("bad", ["0", "-1", "foo", "3.5"])
def test_invalid_keep_fails_closed_and_deletes_nothing(tmp_path, bad):
    backups = tmp_path / "backups"
    backups.mkdir()
    existing = [backups / f"doppel-2026010{i}-000000.dump" for i in range(1, 4)]
    for f in existing:
        f.write_bytes(b"PGDMP-fake")

    result = subprocess.run(
        ["bash", str(SCRIPT)],
        env={**os.environ, "KEEP": bad, "BACKUP_DIR": str(backups)},
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0, f"KEEP={bad!r} should fail closed, got exit 0"
    assert "KEEP" in result.stderr
    # The pre-existing archives must all survive — the guard aborts before the prune step.
    assert all(f.exists() for f in existing)
