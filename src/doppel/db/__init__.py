"""Database layer — Postgres 16 + pgvector caching corpus.

Re-exports the connection pool and the repository functions. Import-cheap (asyncpg + rapidfuzz,
no torch), so ``import doppel.db`` stays free of the heavy ``clap`` group. The schema lives in
``migrations/`` and is applied by ``python -m doppel.db.migrate up``.
"""
from __future__ import annotations

from doppel.db.pool import close_pool, create_pool, get_pool
from doppel.db.repository import (
    fetch_embeddings,
    get_canonical_lookup,
    get_embedding,
    insert_query_log,
    knn,
    needs_reembed,
    persist_resolved_match,
    upsert_canonical_lookup,
    upsert_embedding,
)

__all__ = [
    "close_pool",
    "create_pool",
    "get_pool",
    "fetch_embeddings",
    "get_canonical_lookup",
    "get_embedding",
    "insert_query_log",
    "knn",
    "needs_reembed",
    "persist_resolved_match",
    "upsert_canonical_lookup",
    "upsert_embedding",
]
