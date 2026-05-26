"""Database layer — Postgres 16 + pgvector caching corpus.

Re-exports the connection pool and the repository functions. Import-cheap (asyncpg + rapidfuzz,
no torch), so ``import doppel.db`` stays free of the heavy ``clap`` group. The schema lives in
``migrations/`` and is applied by ``python -m doppel.db.migrate up``.
"""
from __future__ import annotations

from doppel.db.pool import close_pool, create_pool, get_pool
from doppel.db.repository import (
    QueryLogFields,
    QueryLogResultRow,
    count_uncached_candidates,
    delete_query_log,
    fetch_embeddings,
    get_active_query_log,
    get_canonical_lookup,
    get_embedding,
    get_query_log,
    get_query_log_results,
    get_servable_track,
    insert_query_log,
    insert_query_log_results,
    knn,
    needs_reembed,
    persist_resolved_match,
    reap_stale_active_query_logs,
    update_query_log,
    upsert_canonical_lookup,
    upsert_embedding,
)

__all__ = [
    "close_pool",
    "create_pool",
    "get_pool",
    "QueryLogFields",
    "QueryLogResultRow",
    "count_uncached_candidates",
    "delete_query_log",
    "fetch_embeddings",
    "get_active_query_log",
    "get_canonical_lookup",
    "get_embedding",
    "get_query_log",
    "get_query_log_results",
    "get_servable_track",
    "insert_query_log",
    "insert_query_log_results",
    "knn",
    "needs_reembed",
    "persist_resolved_match",
    "reap_stale_active_query_logs",
    "update_query_log",
    "upsert_canonical_lookup",
    "upsert_embedding",
]
