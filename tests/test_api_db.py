"""Db-gated HTTP-level tests for the /recommend API (``--run-db``), with fake sources + model.

Drives the real route handlers via ``httpx.ASGITransport`` against real Postgres, injecting fake
cultural sources / Deezer / MusicBrainz / CLAP straight into ``app.state`` — so the WARM request chain
(aggregate → Gate 1 → run_pipeline → response) and the poll's three states (queued / succeeded /
failed) are verified end-to-end without live APIs or the model. Async throughout (the pool fixture is
async), so it uses the ASGI transport rather than the sync TestClient.
"""
from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import asyncpg
import httpx
import numpy as np
import pytest

from doppel import db
from doppel.aggregation.candidates import Candidate
from doppel.api.app import create_app
from doppel.config import CLAP_EMBED_DIM, DATABASE_URL, GATE1_ASYNC_THRESHOLD
from doppel.db import QueryLogFields, QueryLogResultRow, migrate
from doppel.db.pool import create_pool
from doppel.matching.verify import ProviderTrack, SeedRecording
from doppel.pipeline.recommend import PipelineDeps, parse_handle, request_key_for

pytestmark = pytest.mark.db

_DATA_TABLES = "tracks, audio_assets, canonical_lookups, embeddings, query_logs"


@pytest.fixture
async def pool():
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


class _FakeSource:
    source = "fake"

    def __init__(self, candidates: list[Candidate]) -> None:
        self._candidates = candidates

    async def similar_candidates(self, title: str, artist: str) -> list[Candidate]:
        return self._candidates


class _FakeFinder:
    def __init__(self, found_titles) -> None:
        self._found = set(found_titles)

    async def find_track(self, title: str, artist: str) -> ProviderTrack | None:
        if title not in self._found:
            return None
        return ProviderTrack(title, artist, 180000, f"ISRC{title}", _preview(title), 1000 + abs(hash(title)) % 9000)


class _FakeCanonicalizer:
    async def canonicalize(self, title, artist, *, isrc, target_duration_ms):
        return SeedRecording(title, artist, target_duration_ms or 180000,
                             frozenset({isrc}) if isrc else frozenset(),
                             str(uuid.uuid5(uuid.NAMESPACE_URL, f"fake-{title}")))


class _FakeEmbedder:
    def _vec(self, seed: str) -> np.ndarray:
        rng = np.random.default_rng(abs(hash(seed)) % (2**32))
        v = rng.standard_normal(CLAP_EMBED_DIM).astype(np.float32)
        return v / (float(np.linalg.norm(v)) or 1.0)

    async def embed_preview(self, url, client):
        return self._vec(url)

    def embed_text(self, text):
        return self._vec(text)


@asynccontextmanager
async def _noop_lifespan(app) -> AsyncIterator[None]:
    yield  # state is injected directly; ASGITransport doesn't fire lifespan anyway


def _app(pool, *, sources, finder, enqueue_job=None):
    app = create_app(lifespan=_noop_lifespan)
    app.state.deps = PipelineDeps(pool=pool, finder=finder, canonicalizer=_FakeCanonicalizer(),
                                  embedder=_FakeEmbedder(), http=None, explainer=None, enqueue_job=enqueue_job)
    app.state.sources = sources
    app.state.arq = None
    return app


def _client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def _candidate(title: str, rank: int) -> Candidate:
    return Candidate(title=title, artist=f"Artist {title}", source="fake", rank=rank)


async def test_warm_post_returns_200_with_results(pool):
    candidates = [_candidate("SongA", 1), _candidate("SongB", 2)]
    app = _app(pool, sources=[_FakeSource(candidates)], finder=_FakeFinder(["Seed", "SongA", "SongB"]))
    async with _client(app) as client:
        resp = await client.post("/recommend", json={"seed_title": "Seed", "seed_artist": "Artist"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "succeeded" and body["seed"]["title"] == "Seed"
    assert len(body["results"]) == 2
    top = body["results"][0]
    assert top["was_audio_scored"] is True
    assert top["deezer_url"].startswith("https://www.deezer.com/track/")  # invariant #2: a link, not audio
    assert body["degradation"]["seed_audio_scored"] is True


async def test_cold_post_returns_202_and_enqueues(pool):
    # Many candidates → all uncached on a fresh DB → Gate 1 COLD → 202 + a pollable queued job.
    candidates = [_candidate(f"S{i}", i + 1) for i in range(GATE1_ASYNC_THRESHOLD + 2)]
    enqueued: list[str] = []

    async def fake_enqueue(query_log_id, st, sa, vibe, payload, *, _job_id):
        enqueued.append(_job_id)

    app = _app(pool, sources=[_FakeSource(candidates)], finder=_FakeFinder([]), enqueue_job=fake_enqueue)
    async with _client(app) as client:
        resp = await client.post("/recommend", json={"seed_title": "Seed", "seed_artist": "Artist"})

    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == "queued" and body["job_id"].startswith("rec-")
    assert body["status_url"] == f"/recommend/{body['job_id']}"
    assert enqueued == [body["job_id"]]
    async with pool.acquire() as conn:
        row = await db.get_query_log(conn, parse_handle(body["job_id"]))
        assert row["status"] == "queued" and row["gate1"] == "cold"


async def test_poll_unknown_id_returns_404(pool):
    app = _app(pool, sources=[_FakeSource([])], finder=_FakeFinder([]))
    async with _client(app) as client:
        assert (await client.get("/recommend/rec-999999")).status_code == 404


async def test_poll_reflects_queued_succeeded_and_failed(pool):
    async with pool.acquire() as conn:
        queued_id = await db.insert_query_log(conn, QueryLogFields(
            seed_title="Q", seed_artist="A", status="queued", request_key=request_key_for("Q", "A", None)))
        done_id = await db.insert_query_log(conn, QueryLogFields(
            seed_title="Done", seed_artist="A", status="succeeded", seed_audio_scored=True,
            rationales_available=True, backfill_count=0))
        await db.insert_query_log_results(conn, done_id, [QueryLogResultRow(
            position=1, title="Hit", artist="HitArtist", cultural_score=0.04, was_audio_scored=True,
            provider_track_id="555", audio_score=0.8, combined_score=0.9, sources=["lastfm"],
            rationale="because it fits")])
        failed_id = await db.insert_query_log(conn, QueryLogFields(
            seed_title="Bad", seed_artist="A", status="failed", error="RuntimeError: boom"))

    app = _app(pool, sources=[_FakeSource([])], finder=_FakeFinder([]))
    async with _client(app) as client:
        r_queued = await client.get(f"/recommend/rec-{queued_id}")
        assert r_queued.status_code == 202 and r_queued.json()["status"] == "queued"

        r_done = await client.get(f"/recommend/rec-{done_id}")
        assert r_done.status_code == 200
        done_body = r_done.json()
        assert done_body["status"] == "succeeded" and len(done_body["results"]) == 1
        assert done_body["results"][0]["deezer_url"] == "https://www.deezer.com/track/555"
        assert done_body["results"][0]["rationale"] == "because it fits"

        r_failed = await client.get(f"/recommend/rec-{failed_id}")
        assert r_failed.status_code == 200
        assert r_failed.json()["status"] == "failed" and "RuntimeError" in r_failed.json()["error"]
