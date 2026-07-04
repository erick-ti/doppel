"""Db-gated regression for the eval harness's query_logs lifecycle (``eval/harness.py:run_seed``).

Locks the fix: a failure after the queued row is inserted must not leave an
active ``request_key`` that wedges the in-flight dedup. The harness omits ``request_key`` entirely (so
an orphaned row can't wedge — the active-request unique index treats NULLs as distinct) and
terminalizes the row to ``failed`` on error.
"""
from __future__ import annotations

import asyncpg
import pytest

from doppel import db
from doppel.aggregation.aggregator import AggregateResult, Gate
from doppel.aggregation.ranking import RankedCandidate
from doppel.config import DATABASE_URL
from doppel.db import migrate
from doppel.db.pool import create_pool
from doppel.pipeline.recommend import PipelineDeps, request_key_for

import eval.harness as harness
from eval.seeds import Seed

pytestmark = pytest.mark.db

_DATA_TABLES = "tracks, audio_assets, canonical_lookups, embeddings, query_logs"


@pytest.fixture
async def pool():
    """A migrated pool over freshly truncated tables (run_seed commits, so we truncate at setup)."""
    raw = await asyncpg.connect(DATABASE_URL)
    try:
        await migrate.up(raw)
        await raw.execute(f"TRUNCATE {_DATA_TABLES} RESTART IDENTITY CASCADE")
    finally:
        await raw.close()
    p = await create_pool(DATABASE_URL)
    try:
        yield p
    finally:
        await p.close()


def _cand(title: str) -> RankedCandidate:
    return RankedCandidate(title, f"Artist {title}", 0.05, {"lastfm": 1}, frozenset())


async def test_run_seed_failure_leaves_no_active_dedup_wedge(pool, monkeypatch):
    # A seed whose pipeline raises AFTER the queued row is inserted is exactly the orphan-row risk:
    # the row must end terminal ('failed') with a NULL request_key, so it can never wedge the
    # in-flight dedup, and a re-run of the same seed must insert cleanly.
    seed = Seed("Seed", "Artist", "test")
    deps = PipelineDeps(pool=pool, finder=None, canonicalizer=None, embedder=None,
                        http=None, explainer=None, enqueue_job=None)

    async def fake_aggregate(sources, title, artist, **kwargs):
        return AggregateResult(candidates=[_cand("A"), _cand("B")], gate=Gate.WARM)

    async def boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(harness, "aggregate", fake_aggregate)
    monkeypatch.setattr(harness, "run_pipeline", boom)

    out = await harness.run_seed(deps, [], seed)
    assert out["ok"] is False and "boom" in out["error"]

    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT status, request_key FROM query_logs WHERE seed_title = $1", seed.title)
        assert len(rows) == 1
        assert rows[0]["status"] == "failed"   # terminalized, not left 'queued'
        assert rows[0]["request_key"] is None  # never joined the in-flight dedup
        # no active (queued/running) row holds the seed's would-be dedup key → nothing is wedged
        key = request_key_for(seed.title, seed.artist, seed.vibe)
        assert await db.get_active_query_log(conn, key) is None

    # a re-run of the same seed inserts cleanly (no UniqueViolation wedge) and also terminalizes
    out2 = await harness.run_seed(deps, [], seed)
    assert out2["ok"] is False and "boom" in out2["error"]
    async with pool.acquire() as conn:
        n = await conn.fetchval("SELECT count(*) FROM query_logs WHERE seed_title = $1", seed.title)
        assert n == 2  # two distinct rows, not a dedup collision
