"""Live db tests for the recommendation pipeline (gated by ``--run-db``).

Drives ``run_pipeline`` / ``enqueue_recommendation`` against real Postgres with **fake** external
sources (Deezer / MusicBrainz / CLAP / LLM), so the orchestration, the two-gate handoff, the
in-flight-dedup lifecycle, and the degraded paths are tested without live APIs or the heavy model.

Locks in the two Codex adversarial-review fixes:
  * **Finding 1** — a *terminal* query_logs row never blocks a fresh identical request (the dedup
    key is decoupled from the per-request id), while two *concurrent* identical requests still share
    one in-flight job.
  * **Finding 2** — an httpx preview error (expired Deezer URL / CDN 5xx) degrades (seed →
    cultural-only; candidate → skipped + backfilled) instead of aborting the request.
"""
from __future__ import annotations

import asyncio
import uuid

import asyncpg
import httpx
import numpy as np
import pytest

from doppel import db
from doppel.aggregation.aggregator import Gate
from doppel.aggregation.ranking import RankedCandidate
from doppel.config import CLAP_EMBED_DIM, DATABASE_URL, GATE2_ASYNC_THRESHOLD
from doppel.db import QueryLogFields, migrate
from doppel.db.pool import create_pool
from doppel.matching.verify import ProviderTrack, SeedRecording
from doppel.pipeline.recommend import (
    Deferred,
    Gate1Meta,
    PipelineDeps,
    Recommendation,
    _pool_payload,
    enqueue_recommendation,
    parse_handle,
    request_key_for,
    run_pipeline,
)
from doppel.worker.worker import recommend_job

pytestmark = pytest.mark.db

_DATA_TABLES = "tracks, audio_assets, canonical_lookups, embeddings, query_logs"  # CASCADE clears results


@pytest.fixture
async def pool():
    """A migrated pool over freshly truncated tables. (run_pipeline commits on its own pool
    connections, so unlike the repository tests we can't roll back — we truncate at setup instead.)"""
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


def _preview(title: str) -> str:
    return f"https://cdnt-preview.dzcdn.net/{title}.mp3"


def _mbid(title: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"doppel-fake-{title}"))


class FakeFinder:
    """TrackFinder: a Deezer-shaped hit (preview + ISRC) for known titles, ``None`` otherwise."""

    def __init__(self, found_titles):
        self._found = set(found_titles)

    async def find_track(self, title: str, artist: str) -> ProviderTrack | None:
        if title not in self._found:
            return None
        return ProviderTrack(title, artist, 180000, f"ISRC{title}", _preview(title),
                             abs(hash(title)) % 10**9)


class FakeCanonicalizer:
    """RecordingCanonicalizer: a SeedRecording with a deterministic MBID + the candidate's ISRC, so
    score_match short-circuits to FOUND."""

    async def canonicalize(self, title, artist, *, isrc, target_duration_ms):
        return SeedRecording(title, artist, target_duration_ms or 180000,
                             frozenset({isrc}) if isrc else frozenset(), _mbid(title))


class FakeEmbedder:
    """ClapEmbedder stand-in: deterministic unit vectors, no model. ``embed_preview`` can be told to
    raise httpx errors for specific preview URLs (to exercise the resilience path)."""

    def __init__(self, *, http_fail_titles=()):
        self._fail = {_preview(t) for t in http_fail_titles}

    async def embed_preview(self, url, client):
        if url in self._fail:
            raise httpx.ConnectError("simulated CDN failure")
        return self._vec(url)

    def embed_text(self, text):
        return self._vec(text)

    @staticmethod
    def _vec(seed: str) -> np.ndarray:
        rng = np.random.default_rng(abs(hash(seed)) % (2**32))
        v = rng.standard_normal(CLAP_EMBED_DIM).astype(np.float32)
        return v / (float(np.linalg.norm(v)) or 1.0)


def _deps(pool, *, finder, embedder=None, enqueue_job=None) -> PipelineDeps:
    return PipelineDeps(
        pool=pool, finder=finder, canonicalizer=FakeCanonicalizer(),
        embedder=embedder or FakeEmbedder(), http=None, explainer=None, enqueue_job=enqueue_job,
    )


def _warm_gate1(n: int) -> Gate1Meta:
    return Gate1Meta(gate=Gate.WARM, threshold=15, uncached_count=0, candidate_count=n)


def _cand(title: str, rank: int, score: float) -> RankedCandidate:
    return RankedCandidate(title, f"Artist {title}", score, {"lastfm": rank}, frozenset())


async def test_warm_path_scores_embeds_and_persists(pool):
    cands = [_cand("SongA", 1, 0.05), _cand("SongB", 2, 0.04)]
    deps = _deps(pool, finder=FakeFinder(["Seed", "SongA", "SongB"]))
    rec = await run_pipeline(deps, "Seed", "Artist", None, cands, _warm_gate1(2), execution_mode="inline")

    assert isinstance(rec, Recommendation)
    assert rec.degradation.seed_audio_scored is True
    assert [r.was_audio_scored for r in rec.results] == [True, True]
    assert rec.query_log_id is not None
    async with pool.acquire() as conn:
        log = await db.get_query_log(conn, rec.query_log_id)
        assert log["status"] == "succeeded" and log["audio_scored_count"] == 2 and log["gate1"] == "warm"
        rows = await db.get_query_log_results(conn, rec.query_log_id)
        assert len(rows) == 2 and rows[0]["combined_score"] is not None


async def test_seed_preview_http_error_degrades_to_cultural_only(pool):
    """Finding 2 (seed): an httpx error fetching the seed preview ⇒ cultural-only, not a 500."""
    cands = [_cand("SongA", 1, 0.05)]
    deps = _deps(pool, finder=FakeFinder(["Seed", "SongA"]),
                 embedder=FakeEmbedder(http_fail_titles=["Seed"]))
    rec = await run_pipeline(deps, "Seed", "Artist", None, cands, _warm_gate1(1), execution_mode="inline")

    assert isinstance(rec, Recommendation)  # did NOT raise
    assert rec.degradation.seed_audio_scored is False
    assert rec.results and all(not r.was_audio_scored for r in rec.results)


async def test_candidate_preview_http_error_is_skipped_and_backfilled(pool):
    """Finding 2 (candidate): one bad preview is skipped + backfilled; the run still completes."""
    cands = [_cand("SongA", 1, 0.05), _cand("SongB", 2, 0.04)]
    deps = _deps(pool, finder=FakeFinder(["Seed", "SongA", "SongB"]),
                 embedder=FakeEmbedder(http_fail_titles=["SongA"]))
    rec = await run_pipeline(deps, "Seed", "Artist", None, cands, _warm_gate1(2), execution_mode="inline")

    assert isinstance(rec, Recommendation)  # did NOT raise
    scored = {r.title: r.was_audio_scored for r in rec.results}
    assert scored["SongB"] is True   # good preview → audio-scored
    assert scored["SongA"] is False  # failed preview → cultural backfill
    assert rec.degradation.seed_audio_scored is True


async def test_terminal_row_does_not_block_fresh_request(pool):
    """Finding 1: in-flight requests dedup to one job; a *terminal* row never blocks a fresh repeat."""
    cands = [_cand("SongA", 1, 0.05)]
    enqueued: list[str] = []

    async def fake_enqueue(query_log_id, st, sa, vibe, payload, *, _job_id):
        enqueued.append(_job_id)

    deps = _deps(pool, finder=FakeFinder(["Seed", "SongA"]), enqueue_job=fake_enqueue)
    rk = request_key_for("Seed", "Artist", None)
    queued = QueryLogFields(seed_title="Seed", seed_artist="Artist", status="queued", request_key=rk,
                            gate1="cold", gate1_threshold=15, uncached_count=20, candidate_count=1)
    kw = dict(seed_title="Seed", seed_artist="Artist", vibe=None, pool=cands)

    handle1 = await enqueue_recommendation(deps, fields=queued, **kw)
    handle2 = await enqueue_recommendation(deps, fields=queued, **kw)  # identical, still in flight
    assert handle1 == handle2 and len(enqueued) == 1  # shared the in-flight job

    async with pool.acquire() as conn:  # the worker finishes the first job
        await db.update_query_log(conn, parse_handle(handle1),
                                  QueryLogFields(seed_title="Seed", seed_artist="Artist", status="succeeded"))

    handle3 = await enqueue_recommendation(deps, fields=queued, **kw)  # repeat AFTER terminal
    assert handle3 != handle1 and len(enqueued) == 2  # a FRESH row + job, not the stale result
    async with pool.acquire() as conn:
        assert await conn.fetchval("SELECT count(*) FROM query_logs WHERE request_key = $1", rk) == 2


async def test_gate2_cold_inline_defers_and_creates_queued_row(pool):
    """The inline Gate-2-COLD path creates a queued row + enqueues exactly one job, returning Deferred."""
    n = GATE2_ASYNC_THRESHOLD + 2
    cands = [_cand(f"S{i}", i + 1, 0.05 - i * 0.001) for i in range(n)]
    enqueued: list[str] = []

    async def fake_enqueue(query_log_id, st, sa, vibe, payload, *, _job_id):
        enqueued.append(_job_id)

    deps = _deps(pool, finder=FakeFinder(["Seed"] + [f"S{i}" for i in range(n)]), enqueue_job=fake_enqueue)
    out = await run_pipeline(deps, "Seed", "Artist", None, cands, _warm_gate1(n), execution_mode="inline")

    assert isinstance(out, Deferred)
    assert enqueued == [out.job_id]
    async with pool.acquire() as conn:
        row = await db.get_query_log(conn, parse_handle(out.job_id))
        assert row["status"] == "queued" and row["gate2"] == "cold"
        assert row["missing_embeddings_count"] >= GATE2_ASYNC_THRESHOLD


async def _queue_row(pool, *, candidate_count=1) -> int:
    """Insert the `queued` row the worker finalizes (as the API/inline path would)."""
    async with pool.acquire() as conn:
        return await db.insert_query_log(conn, QueryLogFields(
            seed_title="Seed", seed_artist="Artist", status="queued",
            request_key=request_key_for("Seed", "Artist", None), gate1="cold",
            gate1_threshold=15, uncached_count=20, candidate_count=candidate_count))


async def test_worker_job_finalizes_queued_row_to_succeeded(pool):
    cands = [_cand("SongA", 1, 0.05)]
    deps = _deps(pool, finder=FakeFinder(["Seed", "SongA"]))
    qid = await _queue_row(pool)

    returned = await recommend_job({"deps": deps}, qid, "Seed", "Artist", None, _pool_payload(cands))

    assert returned == qid
    async with pool.acquire() as conn:
        row = await db.get_query_log(conn, qid)
        assert row["status"] == "succeeded" and row["completed_at"] is not None
        assert row["gate1"] == "cold" and row["uncached_count"] == 20  # create-time telemetry preserved
        assert row["audio_scored_count"] == 1
        results = await db.get_query_log_results(conn, qid)
        assert len(results) == 1 and results[0]["was_audio_scored"] is True


class _FailingFinder:
    """A TrackFinder whose lookups raise a non-degradable error (to exercise finding-3 failure path)."""

    async def find_track(self, title, artist):
        raise RuntimeError("upstream exploded")


async def test_worker_job_marks_row_failed_on_error(pool):
    """Finding 3: an uncaught error → the row becomes terminal `failed`, not a stuck `running`."""
    deps = _deps(pool, finder=_FailingFinder())
    qid = await _queue_row(pool)

    with pytest.raises(RuntimeError):
        await recommend_job({"deps": deps}, qid, "Seed", "Artist", None, _pool_payload([_cand("SongA", 1, 0.05)]))

    async with pool.acquire() as conn:
        row = await db.get_query_log(conn, qid)
        assert row["status"] == "failed" and row["completed_at"] is not None
        assert "RuntimeError" in row["error"]


class _HttpFailingFinder:
    """A TrackFinder whose lookups raise httpx.ConnectError for given titles (transient provider down)."""

    def __init__(self, *, fail_titles, found_titles=()):
        self._fail = set(fail_titles)
        self._found = set(found_titles)

    async def find_track(self, title, artist):
        if title in self._fail:
            raise httpx.ConnectError("provider down")
        if title not in self._found:
            return None
        return ProviderTrack(title, artist, 180000, f"ISRC{title}", _preview(title), 1234)


async def test_enqueue_failure_does_not_wedge_future_requests(pool):
    """Finding 1: a failed job-enqueue removes the queued row, so it neither polls 202 forever nor
    dedup-wedges future identical requests onto a stuck handle."""
    rk = request_key_for("Seed", "Artist", None)
    fields = QueryLogFields(seed_title="Seed", seed_artist="Artist", status="queued", request_key=rk,
                            gate1="cold", gate1_threshold=15, uncached_count=20, candidate_count=1)
    kw = dict(seed_title="Seed", seed_artist="Artist", vibe=None, pool=[_cand("SongA", 1, 0.05)])

    async def failing_enqueue(query_log_id, seed_title, seed_artist, vibe, payload, *, _job_id):
        raise RuntimeError("redis down")

    with pytest.raises(RuntimeError):
        await enqueue_recommendation(_deps(pool, finder=FakeFinder([]), enqueue_job=failing_enqueue),
                                     fields=fields, **kw)

    async with pool.acquire() as conn:  # no stuck active/queued row remains
        assert await db.get_active_query_log(conn, rk) is None
        assert await conn.fetchval("SELECT count(*) FROM query_logs WHERE request_key = $1", rk) == 0

    enqueued: list[str] = []

    async def ok_enqueue(query_log_id, seed_title, seed_artist, vibe, payload, *, _job_id):
        enqueued.append(_job_id)

    handle = await enqueue_recommendation(_deps(pool, finder=FakeFinder([]), enqueue_job=ok_enqueue),
                                          fields=fields, **kw)
    assert enqueued == [handle]  # a FRESH job, not deduped onto the (deleted) stuck row
    async with pool.acquire() as conn:
        row = await db.get_active_query_log(conn, rk)
        assert row is not None and row["status"] == "queued"


async def test_seed_resolve_http_error_degrades_to_cultural_only(pool):
    """Finding 2 (seed): a transient Deezer/MB error resolving the seed → cultural-only, not a 500."""
    deps = _deps(pool, finder=_HttpFailingFinder(fail_titles=["Seed"], found_titles=["SongA"]))
    rec = await run_pipeline(deps, "Seed", "Artist", None, [_cand("SongA", 1, 0.05)],
                             _warm_gate1(1), execution_mode="inline")
    assert isinstance(rec, Recommendation)  # did NOT raise
    assert rec.degradation.seed_audio_scored is False
    assert rec.results and all(not r.was_audio_scored for r in rec.results)


async def test_candidate_resolve_http_error_is_skipped_and_backfilled(pool):
    """Finding 2 (candidate): one candidate's transient resolve error is skipped + backfilled; the run
    completes and the other candidate is still audio-scored."""
    deps = _deps(pool, finder=_HttpFailingFinder(fail_titles=["SongA"], found_titles=["Seed", "SongB"]))
    rec = await run_pipeline(deps, "Seed", "Artist", None, [_cand("SongA", 1, 0.05), _cand("SongB", 2, 0.04)],
                             _warm_gate1(2), execution_mode="inline")
    assert isinstance(rec, Recommendation)  # did NOT raise
    scored = {r.title: r.was_audio_scored for r in rec.results}
    assert scored["SongB"] is True and scored["SongA"] is False
    assert rec.degradation.seed_audio_scored is True


class _CancellingFinder:
    """A TrackFinder that raises asyncio.CancelledError (simulates an ARQ timeout/shutdown cancel)."""

    async def find_track(self, title, artist):
        raise asyncio.CancelledError


async def test_worker_job_marks_row_failed_on_cancellation(pool):
    """Round-3 finding 1: CancelledError is a BaseException the bare `except Exception` missed, so a
    cancelled COLD job used to leave a stuck `running` row. It must now reach a terminal `failed`."""
    deps = _deps(pool, finder=_CancellingFinder())
    qid = await _queue_row(pool)

    with pytest.raises(asyncio.CancelledError):
        await recommend_job({"deps": deps}, qid, "Seed", "Artist", None, _pool_payload([_cand("SongA", 1, 0.05)]))

    async with pool.acquire() as conn:
        row = await db.get_query_log(conn, qid)
        assert row["status"] == "failed" and row["completed_at"] is not None
