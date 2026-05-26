"""Forward-only SQL migration runner for Doppel's Postgres schema.

Applies the numbered ``.sql`` files in ``migrations/`` in filename order, each in its own
transaction, recording the applied version + a checksum in a ``schema_migrations`` table. The
checksum is the enforcement behind the "never edit an applied migration" rule: if a file changes
after it was applied, :func:`up` raises rather than silently diverging environments — add a new,
higher-numbered migration instead.

Run migrations as an **explicit deploy step** (``python -m doppel.db.migrate up``); never auto-run
them from a FastAPI / ARQ entrypoint. N workers would race on boot, and a bad migration would take
down every instance on restart with a harder rollback. The ``pg_advisory_lock`` below serializes
concurrent migrators as defense-in-depth — not a license to migrate-on-start.

CLI: ``python -m doppel.db.migrate up`` (apply pending) · ``... status`` (list applied / pending).
"""
from __future__ import annotations

import asyncio
import hashlib
import sys
from pathlib import Path

import asyncpg

from doppel.config import DATABASE_URL, DB_PASSWORD

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
# Stable 64-bit key so only one migrator holds the advisory lock at a time (ASCII "dopplmig").
_ADVISORY_LOCK_KEY = 0x646F70706C6D6967


class MigrationError(RuntimeError):
    """A migration could not be applied safely (e.g. an applied file was modified)."""


def _discover() -> list[tuple[str, str, str]]:
    """Return ``[(version, sql, checksum)]`` for every migration, sorted by filename.

    Pure (filesystem only). ``version`` is the file stem (zero-padded numeric prefixes sort
    correctly lexicographically); ``checksum`` is the sha256 of the file's bytes.
    """
    out: list[tuple[str, str, str]] = []
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        sql = path.read_text(encoding="utf-8")
        checksum = hashlib.sha256(sql.encode("utf-8")).hexdigest()
        out.append((path.stem, sql, checksum))
    return out


def _plan(
    applied: dict[str, str], discovered: list[tuple[str, str, str]]
) -> list[tuple[str, str, str]]:
    """Pure decision core: the pending migrations to apply, in order.

    Raises :class:`MigrationError` for the two ways migration history can drift without the
    checksum catching it: an already-applied migration whose file was *edited* (checksum differs),
    and an applied migration whose file was *deleted* (present in ``applied``, absent from disk — a
    fresh database would silently never get that DDL). This is the testable heart of the runner.
    """
    discovered_versions = {version for version, _, _ in discovered}
    missing = sorted(v for v in applied if v not in discovered_versions)
    if missing:
        raise MigrationError(
            f"applied migration(s) {missing} are missing from {MIGRATIONS_DIR.name}/ — a file was "
            f"deleted after being applied, so a fresh database would never get that DDL (schema "
            f"drift). Restore it; never remove an applied migration."
        )
    pending: list[tuple[str, str, str]] = []
    for version, sql, checksum in discovered:
        if version in applied:
            if applied[version] != checksum:
                raise MigrationError(
                    f"migration {version!r} was modified after being applied "
                    f"(stored {applied[version][:12]}…, file {checksum[:12]}…). "
                    f"Never edit an applied migration — add a new one."
                )
            continue
        pending.append((version, sql, checksum))
    return pending


async def _ensure_table(conn: asyncpg.Connection) -> None:
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version    TEXT PRIMARY KEY,
            checksum   TEXT NOT NULL,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )


async def _applied(conn: asyncpg.Connection) -> dict[str, str]:
    rows = await conn.fetch("SELECT version, checksum FROM schema_migrations")
    return {r["version"]: r["checksum"] for r in rows}


async def up(conn: asyncpg.Connection) -> list[str]:
    """Apply all pending migrations and return the versions applied (empty when up to date)."""
    await conn.execute("SELECT pg_advisory_lock($1)", _ADVISORY_LOCK_KEY)
    try:
        await _ensure_table(conn)
        pending = _plan(await _applied(conn), _discover())
        for version, sql, checksum in pending:
            async with conn.transaction():
                await conn.execute(sql)
                await conn.execute(
                    "INSERT INTO schema_migrations (version, checksum) VALUES ($1, $2)",
                    version,
                    checksum,
                )
        return [version for version, _, _ in pending]
    finally:
        await conn.execute("SELECT pg_advisory_unlock($1)", _ADVISORY_LOCK_KEY)


async def status(conn: asyncpg.Connection) -> tuple[list[str], list[str]]:
    """Return ``(applied_versions, pending_versions)`` without modifying anything."""
    await _ensure_table(conn)
    applied = await _applied(conn)
    discovered = [version for version, _, _ in _discover()]
    return sorted(v for v in discovered if v in applied), [
        v for v in discovered if v not in applied
    ]


async def _main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else "up"
    conn = await asyncpg.connect(DATABASE_URL, password=DB_PASSWORD)
    try:
        if cmd == "up":
            applied = await up(conn)
            print(f"applied {len(applied)} migration(s): {', '.join(applied) or '(none — up to date)'}")
        elif cmd == "status":
            done, pending = await status(conn)
            print(f"applied: {', '.join(done) or '(none)'}")
            print(f"pending: {', '.join(pending) or '(none)'}")
        else:
            print(f"unknown command {cmd!r} (use: up | status)", file=sys.stderr)
            return 2
    finally:
        await conn.close()
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(_main(sys.argv)))


if __name__ == "__main__":
    main()
