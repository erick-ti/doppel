"""asyncpg connection pool, with the pgvector ``vector`` codec registered per connection.

A lazy, process-wide singleton so the FastAPI app (warm path) and the ARQ worker (cold path)
each share one pool. The per-connection ``init`` registers this module's codec for the ``vector``
column type, so every connection encodes ndarrays / lists / ``Vector`` values on the way in and
decodes stored vectors to float32 ndarrays on the way out. The embedder hands its float32 arrays
straight to :func:`repository.upsert_embedding`, and every reader of an ``embedding`` column (the
pipeline's cache hits, Gate 2, the mood lane, the eval scripts) gets an ndarray back.

Why this module owns the codec instead of calling ``pgvector.asyncpg.register_vector``:
pgvector-python 0.5.0 changed that decoder to return a ``Vector`` object (no ``len``, indexing or
implicit NumPy conversion), which broke every ``np.asarray(row["embedding"])`` in the pipeline.
Registering the codec here pins the contract to this codebase, independent of the library's
default, and the same code is correct on 0.4.x and 0.5.x (both expose ``Vector.to_binary`` /
``from_binary`` / ``to_numpy``).

Tests pass an explicit DSN to :func:`create_pool` to get an isolated pool they own and close.
"""
from __future__ import annotations

import asyncio
from typing import Any

import asyncpg
import numpy as np
from numpy.typing import NDArray
from pgvector import Vector

from doppel.config import DATABASE_URL, DB_PASSWORD, DB_POOL_MAX_SIZE, DB_POOL_MIN_SIZE

_pool: asyncpg.Pool | None = None
_pool_lock = asyncio.Lock()


def encode_vector(value: Any) -> bytes:
    """Encode an array-like of floats (ndarray, list, tuple) or a ``Vector`` into pgvector's binary
    wire format. A ``Vector`` passes through unchanged: ``Vector(Vector)`` raises in every version."""
    vec = value if isinstance(value, Vector) else Vector(np.asarray(value, dtype=np.float32))
    return vec.to_binary()


def decode_vector(buf: bytes | bytearray | memoryview) -> NDArray[np.float32]:
    """Decode pgvector's binary wire format into an owned, native float32 ndarray of shape ``(dim,)``.

    ``np.array`` copies, so callers may mutate the result without touching the wire buffer, and
    ``len`` / indexing / ``np.asarray`` behave exactly as they did with pgvector 0.4.x decoding.
    """
    return np.array(Vector.from_binary(buf).to_numpy(), dtype=np.float32)


async def _init_connection(conn: asyncpg.Connection) -> None:
    """Per-connection setup: register the ``vector`` codec (array-like → binary → float32 ndarray).

    Only ``vector`` is registered; ``halfvec`` / ``sparsevec`` are unused by the schema. The binary
    format is pgvector's own, produced and parsed by its ``Vector`` class, never hand-rolled here.
    """
    await conn.set_type_codec(
        "vector", schema="public", encoder=encode_vector, decoder=decode_vector, format="binary"
    )


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
