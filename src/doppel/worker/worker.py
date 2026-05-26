"""ARQ worker — the COLD path. Runs ``run_pipeline(execution_mode="job")`` off the Redis queue.

``recommend_job`` is enqueued by the API (Gate-1-COLD) or by ``run_pipeline`` inline (Gate-2-COLD),
under ARQ ``_job_id = "rec-<query_logs.id>"``. It re-runs the whole pipeline against the DB cache —
already-resolved candidates and cached embeddings are cheap hits the second time — and finalizes the
pre-created ``query_logs`` row by id.

**Finding 3 (Codex review): the pollable row never stalls.** The job marks the row ``running`` at the
start and, on any uncaught error, writes ``status='failed'`` + a sanitized message + ``completed_at``
before re-raising — so a COLD poll always sees a terminal state instead of a forever-``queued`` /
``running`` row. ARQ records the failure too; the durable, user-facing status lives in Postgres.

Run it with: ``arq doppel.worker.worker.WorkerSettings`` (Redis must be up — ``docker compose`` serves
it under the ``worker`` profile). Migrations are applied as a separate deploy step, never here.
"""
from __future__ import annotations

import asyncio
import contextlib
from typing import Any

from arq import cron
from arq.connections import RedisSettings

from doppel import db
from doppel.config import JOB_TIMEOUT_S, REDIS_URL, STALE_JOB_RECLAIM_S, WORKER_MAX_JOBS
from doppel.db import QueryLogFields
from doppel.pipeline.deps import build_deps, close_deps
from doppel.pipeline.recommend import pool_from_payload, run_pipeline


def _sanitized_error(exc: Exception) -> str:
    """A short, single-line ``type: message`` summary for the API-visible ``error`` — no tracebacks."""
    message = next((line for line in str(exc).strip().splitlines() if line), "")
    summary = f"{type(exc).__name__}: {message}" if message else type(exc).__name__
    return summary[:500]


async def recommend_job(
    ctx: dict[str, Any], query_log_id: int, seed_title: str, seed_artist: str,
    vibe: str | None, pool_payload: list[dict],
) -> int:
    """Finalize a COLD recommendation: mark running, run the pipeline (job mode), persist; on error
    or cancellation mark the row failed and re-raise. Returns the ``query_logs.id`` (the poll row)."""
    deps = ctx["deps"]
    pool = pool_from_payload(pool_payload)
    await _set_status(deps, query_log_id, seed_title, seed_artist, status="running")
    try:
        await run_pipeline(
            deps, seed_title, seed_artist, vibe, pool,
            execution_mode="job", query_log_id=query_log_id,
        )
    except (Exception, asyncio.CancelledError) as exc:
        # CancelledError (ARQ job_timeout / worker shutdown) is a BaseException, so a bare
        # `except Exception` would skip this write and leave the row stuck `running` — polling 202
        # forever and dedup-wedging future identical requests onto the stuck handle. asyncio.shield
        # lets the failure write finish despite the cancellation tearing this task down; best-effort
        # on a hard loop shutdown — the stale-running-row reaper (reap_stale_jobs, below) backstops that
        # and the SIGKILL/OOM/reboot case where no in-process handler runs at all.
        with contextlib.suppress(Exception):
            await asyncio.shield(_set_status(
                deps, query_log_id, seed_title, seed_artist,
                status="failed", error=_sanitized_error(exc),
            ))
        raise
    return query_log_id


async def _set_status(
    deps, query_log_id: int, seed_title: str, seed_artist: str, *,
    status: str, error: str | None = None,
) -> None:
    """Write a lifecycle status (+ optional sanitized error) to the COLD row by id."""
    async with deps.pool.acquire() as conn:
        await db.update_query_log(
            conn, query_log_id,
            QueryLogFields(seed_title=seed_title, seed_artist=seed_artist, status=status, error=error),
        )


async def startup(ctx: dict[str, Any]) -> None:
    ctx["deps"] = await build_deps(enqueue_job=None)  # the worker's gates never enqueue


async def shutdown(ctx: dict[str, Any]) -> None:
    deps = ctx.get("deps")
    if deps is not None:
        await close_deps(deps)


async def reap_stale_jobs(ctx: dict[str, Any]) -> int:
    """Recover query_logs rows orphaned when recommend_job's in-process failure handler never ran — a
    worker SIGKILL/OOM or VPS reboot mid-job. Marks stale 'running' rows (last transition older than
    ``STALE_JOB_RECLAIM_S``) failed, clearing the in-flight dedup so the seed/vibe stops wedging and the
    poll terminates. ('queued' rows are left to their ARQ job — see reap_stale_active_query_logs.)
    Registered to run at worker startup AND on a cron, so an orphan is reclaimed promptly on restart and
    bounded even while the worker stays up. Returns the count (ARQ logs it)."""
    deps = ctx["deps"]
    async with deps.pool.acquire() as conn:
        return await db.reap_stale_active_query_logs(conn, STALE_JOB_RECLAIM_S)


class WorkerSettings:
    """ARQ entrypoint: ``arq doppel.worker.worker.WorkerSettings``."""

    functions = [recommend_job]
    # Reap stale 'running' rows at startup (covers a crash/OOM/reboot restart) and every 5 minutes
    # (bounds a 'running' orphan whose failure-write was lost while the worker stayed up). See
    # reap_stale_jobs; STALE_JOB_RECLAIM_S > JOB_TIMEOUT_S guarantees a live job is never reclaimed.
    cron_jobs = [cron(reap_stale_jobs, minute=set(range(0, 60, 5)), run_at_startup=True)]
    redis_settings = RedisSettings.from_dsn(REDIS_URL)
    on_startup = startup
    on_shutdown = shutdown
    # ARQ is liveness/dedup only — the durable result is in Postgres, and the poll reads it from
    # there, so a short Redis result TTL is fine. WORKER_MAX_JOBS=1 (cold work is MB-bound; all jobs
    # share one ~1 req/s limiter, so concurrency only multiplies latency + embed memory, never MB
    # throughput). job_timeout (JOB_TIMEOUT_S) covers a COLD run whose top-N resolve waits on
    # MusicBrainz; RESOLVE_CANDIDATE_LIMIT bounds that work so the run finishes well inside it.
    keep_result = 3600
    max_jobs = WORKER_MAX_JOBS
    job_timeout = JOB_TIMEOUT_S
