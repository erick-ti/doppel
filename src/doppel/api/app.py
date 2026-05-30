"""FastAPI application — the ``/recommend`` API.

``POST /recommend`` aggregates the cultural pool, applies **Gate 1** (the *uncached* canonicalization
count), and either runs the pipeline inline (WARM → 200 with results) or enqueues the worker (COLD →
202 with a poll handle). ``run_pipeline`` may itself defer at Gate 2 (also → 202). ``GET
/recommend/{job_id}`` polls the durable status from Postgres (the worker keeps it terminal — see the
worker's finding-3 handling), returning the same result body on success.

Run with ``uvicorn doppel.api.app:app``. The lifespan opens the shared deps (pool, HTTP client, CLAP,
Anthropic, the ARQ enqueue handle) + the cultural sources; ``create_app(lifespan=...)`` lets tests
inject a no-op lifespan and their own ``app.state``. Migrations run as a separate deploy step, never here.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from arq.connections import RedisSettings, create_pool
from fastapi import FastAPI, HTTPException, Request, Response

from doppel import db
from doppel.aggregation.aggregator import Gate, aggregate, gate_for
from doppel.api.responses import response_from_recommendation, response_from_rows
from doppel.api.schemas import (
    JobAccepted,
    JobFailed,
    RecommendRequest,
)
from doppel.config import GATE1_ASYNC_THRESHOLD, REDIS_URL, RESOLVE_CANDIDATE_LIMIT
from doppel.db import QueryLogFields
from doppel.pipeline.deps import build_deps, close_deps
from doppel.pipeline.recommend import (
    Deferred,
    Gate1Meta,
    enqueue_recommendation,
    parse_handle,
    request_key_for,
    run_pipeline,
)
from doppel.sources.lastfm import LastFmClient
from doppel.sources.listenbrainz import ListenBrainzClient

_PENDING_STATUSES = {"queued", "running"}


@asynccontextmanager
async def _production_lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Open the shared pipeline deps, cultural sources, and the ARQ enqueue handle; close on shutdown."""
    arq = await create_pool(RedisSettings.from_dsn(REDIS_URL))

    async def enqueue_job(query_log_id, seed_title, seed_artist, vibe, pool_payload, *, _job_id):
        await arq.enqueue_job(
            "recommend_job", query_log_id, seed_title, seed_artist, vibe, pool_payload, _job_id=_job_id
        )

    deps = await build_deps(enqueue_job=enqueue_job)
    app.state.deps = deps
    app.state.sources = [ListenBrainzClient(deps.http), LastFmClient(deps.http)]
    app.state.arq = arq
    try:
        yield
    finally:
        await close_deps(deps)
        await arq.aclose()


def create_app(*, lifespan=_production_lifespan) -> FastAPI:
    app = FastAPI(title="Doppel", version="0.1.0", lifespan=lifespan)

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    @app.post("/recommend", response_model=None)
    async def recommend(req: RecommendRequest, request: Request, response: Response):
        deps = request.app.state.deps
        result = await aggregate(request.app.state.sources, req.seed_title, req.seed_artist)
        # Only the top-N candidates by cultural rank are resolved (RESOLVE_CANDIDATE_LIMIT — the MB
        # ~1 req/s bound), so Gate 1 counts the uncached lookups among *those*, matching the real
        # MusicBrainz work. candidate_count below stays the full pool (the cultural-recall yield).
        async with deps.pool.acquire() as conn:
            uncached = await db.count_uncached_candidates(
                conn, [(c.title, c.artist) for c in result.candidates[:RESOLVE_CANDIDATE_LIMIT]]
            )
        # Gate 1 is now the *uncached* count (the lookups that would actually hit MusicBrainz).
        if gate_for(uncached, threshold=GATE1_ASYNC_THRESHOLD) is Gate.COLD:
            handle = await enqueue_recommendation(
                deps,
                fields=QueryLogFields(
                    seed_title=req.seed_title, seed_artist=req.seed_artist, vibe_text=req.vibe,
                    status="queued", request_key=request_key_for(req.seed_title, req.seed_artist, req.vibe),
                    candidate_count=len(result.candidates), degraded=result.degraded,
                    failed_sources=result.failed_sources, gate1="cold",
                    gate1_threshold=GATE1_ASYNC_THRESHOLD, uncached_count=uncached,
                ),
                seed_title=req.seed_title, seed_artist=req.seed_artist, vibe=req.vibe,
                pool=result.candidates,
            )
            response.status_code = 202
            return _accepted(handle)

        meta = Gate1Meta(
            gate=Gate.WARM, threshold=GATE1_ASYNC_THRESHOLD, uncached_count=uncached,
            candidate_count=len(result.candidates), failed_sources=result.failed_sources,
            degraded=result.degraded,
        )
        outcome = await run_pipeline(
            deps, req.seed_title, req.seed_artist, req.vibe, result.candidates, meta,
            execution_mode="inline",
        )
        if isinstance(outcome, Deferred):  # Gate 2 deferred to the worker
            response.status_code = 202
            return _accepted(outcome.job_id)
        return response_from_recommendation(outcome)

    @app.get("/recommend/{job_id}", response_model=None)
    async def poll(job_id: str, request: Request, response: Response):
        try:
            query_log_id = parse_handle(job_id)
        except (ValueError, TypeError):
            raise HTTPException(status_code=404, detail="unknown job") from None
        async with request.app.state.deps.pool.acquire() as conn:
            row = await db.get_query_log(conn, query_log_id)
            if row is None:
                raise HTTPException(status_code=404, detail="unknown job")
            status = row["status"]
            if status in _PENDING_STATUSES:
                response.status_code = 202
                return JobAccepted(status=status, job_id=job_id, status_url=f"/recommend/{job_id}")
            if status == "failed":
                return JobFailed(job_id=job_id, error=row["error"])
            results = await db.get_query_log_results(conn, query_log_id)
        return response_from_rows(row, results)

    return app


app = create_app()


# --- response builders ------------------------------------------------------------------------- #


def _accepted(handle: str) -> JobAccepted:
    return JobAccepted(status="queued", job_id=handle, status_url=f"/recommend/{handle}")
