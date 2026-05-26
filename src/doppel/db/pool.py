"""asyncpg connection pool, with the pgvector codec registered per connection.

A lazy, process-wide singleton so the FastAPI app (warm path) and the ARQ worker (cold path)
each share one pool. ``register_vector`` runs as the pool's per-connection ``init`` so every
connection encodes/decodes ``vector`` columns to and from numpy arrays transparently — the
embedder hands its float32 arrays straight to :func:`repository.upsert_embedding`.

Tests pass an explicit DSN to :func:`create_pool` to get an isolated pool they own and close.
"""
from __future__ import annotations

import asyncio

import asyncpg
from pgvector.asyncpg import register_vector

from doppel.config import DATABASE_URL, DB_PASSWORD, DB_POOL_MAX_SIZE, DB_POOL_MIN_SIZE

_pool: asyncpg.Pool | None = None
_pool_lock = asyncio.Lock()


async def _init_connection(conn: asyncpg.Connection) -> None:
    """Per-connection setup: register the pgvector codec (vector ↔ numpy/list)."""
    await register_vector(conn)


async def create_pool(
    dsn: str = DATABASE_URL,
    *,
    password: str | None = DB_PASSWORD,
    min_size: int = DB_POOL_MIN_SIZE,
    max_size: int = DB_POOL_MAX_SIZE,
) -> asyncpg.Pool:
    """Create a *new* pool (independent of the singleton); the caller owns closing it.

    ``password`` is passed as a discrete asyncpg argument rather than embedded in ``dsn`` so an
    arbitrary secret connects safely; ``None`` (dev/tests) falls back to the DSN's own password.
    """
    return await asyncpg.create_pool(
        dsn, password=password, min_size=min_size, max_size=max_size, init=_init_connection
    )


async def get_pool() -> asyncpg.Pool:
    """Return the process-wide pool, creating it on first use (double-checked under a lock)."""
    global _pool
    if _pool is None:
        async with _pool_lock:
            if _pool is None:
                _pool = await create_pool()
    return _pool


async def close_pool() -> None:
    """Close the process-wide pool (app/worker shutdown). Safe to call when none exists."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
