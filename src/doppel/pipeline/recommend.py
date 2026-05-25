"""Pipeline orchestration — the one coroutine that turns a seed into ranked, explained results.

:func:`run_pipeline` is the heart of ``/recommend``, and it runs unchanged on both paths: inline in
the FastAPI request (WARM) and inside the ARQ ``recommend_job`` (COLD). The only difference is
``execution_mode`` — in ``"inline"`` a tripped Gate 2 may enqueue the job and return :class:`Deferred`;
in ``"job"`` the gates never enqueue (they fall through and keep processing in the current worker).
That asymmetry is the guardrail against a job re-enqueueing itself forever.

The shared cache (Day 5) is what lets one coroutine serve both paths. A COLD job re-runs the same
steps, and everything an inline attempt already persisted — ``canonical_lookups``, ``audio_assets``,
``embeddings`` — is a cheap cache hit the second time. So the job is idempotent and needs only the
request plus the cultural pool as input; no partial state crosses the boundary.

**Division of labor.** Gate 1 (the uncached-canonicalization count) is decided by the *caller* (the
API), because it must know the count before deciding whether to run this inline at all — so the API
either calls :func:`run_pipeline` inline (WARM) or :func:`enqueue_recommendation` (COLD). This module
owns Gate 2 (the missing-embedding count) and every step from the seed onward: seed resolve+embed,
the candidate resolve loop, embedding cache-misses, audio(+vibe) scoring, cultural backfill, LLM
explanation, and persistence.
"""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Literal, Protocol

import asyncpg
import httpx
import numpy as np

from doppel import db
from doppel.aggregation.aggregator import Gate, gate_for
from doppel.aggregation.candidates import normalized_key
from doppel.aggregation.ranking import RankedCandidate
from doppel.config import (
    CLAP_MODEL_VERSION,
    EMBED_CONCURRENCY,
    GATE2_ASYNC_THRESHOLD,
    RECOMMENDATION_LIMIT,
    RESOLVE_CANDIDATE_LIMIT,
)
from doppel.db import QueryLogFields, QueryLogResultRow
from doppel.embedding.embedder import ClapEmbedder, EmbeddingError
from doppel.embedding.scoring import score_candidates
from doppel.matching.resolver import RecordingCanonicalizer, ResolveStatus, TrackFinder, resolve

ExecutionMode = Literal["inline", "job"]


# --- public result types (the API serializes these; the worker returns them) ----------------- #


@dataclass(frozen=True)
class RecommendationResult:
    """One returned track. ``was_audio_scored`` False ⇒ a cultural-only backfill row (its cosines /
    ``combined_score`` are ``None``); ``mbid`` may be ``None`` for an unresolved backfill track.
    ``provider_track_id`` builds the Deezer track-*page* link in the API — never preview audio."""

    position: int
    title: str
    artist: str
    cultural_score: float
    was_audio_scored: bool
    sources: tuple[str, ...]
    mbid: str | None = None
    provider_track_id: str | None = None
    audio_score: float | None = None
    vibe_text_score: float | None = None
    combined_score: float | None = None
    rationale: str | None = None


@dataclass(frozen=True)
class Degradation:
    """Which of the three degraded paths fired — surfaced to the caller and stored for Day-7 eval."""

    seed_audio_scored: bool  # False ⇒ the seed had no usable preview (cultural-only results)
    cultural_backfill_count: int  # results that are cultural-only (not audio-scored)
    rationales_available: bool  # False ⇒ the LLM explainer was absent or failed
    degraded_sources: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Recommendation:
    """A completed ``/recommend`` outcome — the WARM 200 body and the COLD poll-success payload."""

    seed_title: str
    seed_artist: str
    vibe: str | None
    seed_mbid: str | None
    results: list[RecommendationResult]
    degradation: Degradation
    query_log_id: int | None = None


@dataclass(frozen=True)
class Deferred:
    """A gate handed the request to the worker; the caller returns 202 + this job_id."""

    job_id: str


@dataclass(frozen=True)
class Gate1Meta:
    """What the API decided/measured at Gate 1 — recorded into the query_log by this module."""

    gate: Gate
    threshold: int
    uncached_count: int
    candidate_count: int
    failed_sources: Mapping[str, str] = field(default_factory=dict)
    degraded: bool = False


class Explainer(Protocol):
    """The LLM explainer seam: a rationale per result *position* (never a ranking). Optional.

    Keyed by position (not mbid) so a partial/truncated model response degrades per-row instead of
    shifting, and so a backfill row that has no mbid can still be explained.
    """

    async def explain(
        self,
        *,
        seed_title: str,
        seed_artist: str,
        vibe: str | None,
        results: Sequence[RecommendationResult],
    ) -> Mapping[int, str]: ...


@dataclass
class PipelineDeps:
    """Everything :func:`run_pipeline` needs, injected by the API lifespan / worker startup.

    The same deps serve WARM and COLD. ``enqueue_job`` is set only on the inline (API) path — it is
    how a Gate-2-COLD decision hands the rest of the work to the worker; in the worker it is ``None``
    (with ``execution_mode="job"``), so a gate can't re-enqueue.
    """

    pool: asyncpg.Pool
    finder: TrackFinder
    canonicalizer: RecordingCanonicalizer
    embedder: ClapEmbedder
    http: httpx.AsyncClient  # preview fetches for embed_preview
    explainer: Explainer | None = None
    enqueue_job: Callable[..., Awaitable[object]] | None = None


def request_key_for(seed_title: str, seed_artist: str, vibe: str | None) -> str:
    """Deterministic in-flight dedup key for a request (``query_logs.request_key``).

    Identical concurrent submissions of the same seed+vibe share one queued/running row (the
    active-request_key partial unique index) instead of racing on the cache upserts. Normalized like
    the cache key (:func:`normalized_key`), with whitespace-folded lowercased vibe, so trivial
    formatting differences map to the same key. **Not** the poll handle — that is the per-request
    ``query_logs.id`` (:func:`_handle`), so a *completed* request never blocks a fresh repeat.
    """
    norm_title, norm_artist = normalized_key(seed_title, seed_artist)
    norm_vibe = " ".join((vibe or "").lower().split())
    digest = hashlib.sha256("\x1f".join((norm_title, norm_artist, norm_vibe)).encode()).hexdigest()
    return f"req-{digest[:24]}"


def _handle(query_log_id: int) -> str:
    """The opaque poll handle / ARQ ``_job_id`` for a request — its per-request ``query_logs.id``."""
    return f"rec-{query_log_id}"


def parse_handle(handle: str) -> int:
    """Inverse of :func:`_handle`: the ``query_logs.id`` a poll handle refers to (raises on garbage)."""
    return int(handle.removeprefix("rec-"))


# --- internal step types ----------------------------------------------------------------------- #


@dataclass(frozen=True)
class _Resolved:
    """A FOUND candidate ready for embedding/display — from a fresh resolve or a cache hit."""

    ranked: RankedCandidate
    mbid: str
    asset_id: int
    preview_url: str
    provider_track_id: str | None
    match_confidence: float


@dataclass
class _ResolveCounts:
    found: int = 0
    rejected: int = 0
    not_found: int = 0


# --- steps ------------------------------------------------------------------------------------- #


async def _resolve_and_embed_seed(
    deps: PipelineDeps, conn: asyncpg.Connection, title: str, artist: str
) -> tuple[str | None, np.ndarray | None]:
    """Resolve the seed (cache-first) and embed its preview → the query vector.

    Returns ``(mbid, vector)``; ``vector`` is ``None`` when the seed has no usable preview (→
    cultural-only results) and ``mbid`` is whatever identity we have (possibly ``None``). Persists
    the seed like any candidate, so its embedding joins the corpus.
    """
    hit = await db.get_canonical_lookup(conn, title, artist)
    if hit is not None:
        if hit["status"] != "found":
            return (str(hit["mbid"]) if hit["mbid"] else None, None)
        track = await db.get_servable_track(conn, hit["mbid"])
        if track is None:
            return (str(hit["mbid"]), None)
        mbid, asset_id = str(track["mbid"]), track["asset_id"]
        preview_url, confidence = track["preview_url"], track["match_confidence"]
    else:
        try:
            match = await resolve(deps.finder, deps.canonicalizer, title, artist)
        except httpx.HTTPError:
            return (None, None)  # transient Deezer/MusicBrainz failure on the seed → cultural-only
        asset_id = await db.persist_resolved_match(conn, title, artist, match)
        if match.status is not ResolveStatus.FOUND or asset_id is None:
            return (match.mbid, None)
        assert match.seed is not None and match.candidate is not None and match.match is not None
        mbid, preview_url = match.seed.mbid, match.candidate.preview_url
        confidence = match.match.confidence

    cached = await db.get_embedding(conn, mbid, CLAP_MODEL_VERSION)
    if cached is not None:
        return (mbid, np.asarray(cached["embedding"]))
    try:
        vector = await deps.embedder.embed_preview(preview_url, deps.http)
    except (EmbeddingError, httpx.HTTPError):
        # embed_preview raises EmbeddingError (undecodable/capped/rejected host) AND propagates raw
        # httpx errors (an expired Deezer URL → 404, a CDN 5xx/timeout). Both degrade the seed to
        # cultural-only rather than sinking the request (invariant: one bad input never sinks the run).
        return (mbid, None)
    await db.upsert_embedding(
        conn, mbid=mbid, model_version=CLAP_MODEL_VERSION, embedding=vector,
        source_confidence=confidence, asset_id=asset_id,
    )
    return (mbid, vector)


async def _embed_vibe(deps: PipelineDeps, vibe: str | None) -> np.ndarray | None:
    """Embed the vibe description into the CLAP text space, or ``None`` (no vibe / degraded)."""
    if not vibe or not vibe.strip():
        return None
    try:
        return await asyncio.to_thread(deps.embedder.embed_text, vibe)
    except Exception:
        return None  # a bad vibe degrades to audio-only scoring, never sinks the request


async def _resolve_pool(
    deps: PipelineDeps, conn: asyncpg.Connection, pool: Sequence[RankedCandidate]
) -> tuple[list[_Resolved], _ResolveCounts]:
    """Resolve each candidate cache-first; sequential, since MusicBrainz is ~1 req/s (the caller caps
    the pool length at RESOLVE_CANDIDATE_LIMIT so this can't run unbounded). A cache hit reads the
    persisted asset; a miss resolves + persists."""
    resolved: list[_Resolved] = []
    counts = _ResolveCounts()
    for cand in pool:
        hit = await db.get_canonical_lookup(conn, cand.title, cand.artist)
        if hit is not None:
            if hit["status"] == "found":
                track = await db.get_servable_track(conn, hit["mbid"])
                if track is not None:
                    resolved.append(_Resolved(
                        ranked=cand, mbid=str(track["mbid"]), asset_id=track["asset_id"],
                        preview_url=track["preview_url"], provider_track_id=track["provider_track_id"],
                        match_confidence=track["match_confidence"],
                    ))
                    counts.found += 1
                else:
                    counts.rejected += 1  # FOUND lookup whose asset has since flipped → not servable
            elif hit["status"] == "rejected":
                counts.rejected += 1
            else:
                counts.not_found += 1
            continue

        try:
            match = await resolve(deps.finder, deps.canonicalizer, cand.title, cand.artist)
        except httpx.HTTPError:
            continue  # transient provider failure → skip this candidate; it falls to cultural backfill
        asset_id = await db.persist_resolved_match(conn, cand.title, cand.artist, match)
        if match.status is ResolveStatus.FOUND and asset_id is not None:
            assert match.seed is not None and match.candidate is not None and match.match is not None
            ptid = match.candidate.provider_track_id
            resolved.append(_Resolved(
                ranked=cand, mbid=match.seed.mbid, asset_id=asset_id,
                preview_url=match.candidate.preview_url,
                provider_track_id=None if ptid is None else str(ptid),
                match_confidence=match.match.confidence,
            ))
            counts.found += 1
        elif match.status is ResolveStatus.REJECTED:
            counts.rejected += 1
        else:
            counts.not_found += 1
    return resolved, counts


async def _embed_missing(deps: PipelineDeps, missing: Sequence[_Resolved]) -> dict[str, np.ndarray]:
    """Embed the cache-miss FOUND candidates (bounded concurrency) and persist each to the corpus.

    Returns ``{mbid: vector}`` for those that embedded; a preview that fails (undecodable, over a
    cap, rejected host, or an HTTP / expired-URL error) is skipped, and the candidate falls back to
    cultural ranking — one bad external preview never sinks the batch.
    """
    semaphore = asyncio.Semaphore(EMBED_CONCURRENCY)

    async def embed_one(item: _Resolved) -> tuple[str, np.ndarray] | None:
        async with semaphore:
            try:
                vector = await deps.embedder.embed_preview(item.preview_url, deps.http)
            except (EmbeddingError, httpx.HTTPError):
                return None  # bad/expired preview or CDN error → skip this one; it falls to backfill
            async with deps.pool.acquire() as conn:
                await db.upsert_embedding(
                    conn, mbid=item.mbid, model_version=CLAP_MODEL_VERSION, embedding=vector,
                    source_confidence=item.match_confidence, asset_id=item.asset_id,
                )
            return (item.mbid, vector)

    vectors: dict[str, np.ndarray] = {}
    for finished in asyncio.as_completed([embed_one(item) for item in missing]):
        pair = await finished
        if pair is not None:
            vectors[pair[0]] = pair[1]
    return vectors


def _build_results(
    resolved: Sequence[_Resolved],
    vectors: Mapping[str, np.ndarray],
    seed_vector: np.ndarray | None,
    vibe_vector: np.ndarray | None,
    pool: Sequence[RankedCandidate],
    *,
    seed_mbid: str | None = None,
) -> list[RecommendationResult]:
    """Audio-rank the embedded candidates, then backfill cultural (RRF) order up to the limit.

    Audio-scored results (ordered by fused score) always precede cultural backfill — CLAP reranks,
    backfill only tops up to :data:`RECOMMENDATION_LIMIT`. Handles cultural-only (no seed vector /
    nothing embedded) by producing pure backfill. Dedups on the verified resolver MBID (and drops
    ``seed_mbid``) so two credits for one recording don't both appear and the seed can't recommend
    itself — string ``(title, artist)`` alone misses these (Codex review).
    """
    scorable = [item for item in resolved if item.mbid in vectors]
    ordered: list[RecommendationResult] = []
    # Identity dedup is on the VERIFIED resolver MBID, not the (title, artist) string: two cultural
    # candidates with different credits can resolve to the SAME recording (live Day-7: "My Little
    # Brown Book" ×2), and the seed itself can re-enter under an alias ("Take Five"). Seeding the
    # seed's MBID drops it from its own results; tracking each placed MBID collapses duplicates across
    # the audio-scored and backfill phases alike.
    used_mbids: set[str] = {seed_mbid} if seed_mbid else set()
    if scorable and seed_vector is not None:
        scored = score_candidates(
            seed_vector, [vectors[item.mbid] for item in scorable], vibe_text=vibe_vector
        )
        for sc in scored:
            item = scorable[sc.index]
            if item.mbid in used_mbids:  # the seed alias, or a recording already placed
                continue
            used_mbids.add(item.mbid)
            ordered.append(RecommendationResult(
                position=0, title=item.ranked.title, artist=item.ranked.artist, mbid=item.mbid,
                provider_track_id=item.provider_track_id, cultural_score=item.ranked.cultural_score,
                was_audio_scored=True, sources=item.ranked.sources, audio_score=sc.audio_similarity,
                vibe_text_score=sc.text_similarity, combined_score=sc.combined_score,
            ))

    used = {(r.title, r.artist) for r in ordered}
    # A backfill row's identity comes from the VERIFIED resolver match when the candidate resolved
    # FOUND — including one that resolved but failed to embed (so we keep its mbid + Deezer link) —
    # NEVER the unverified, possibly-conflicting source MBID carried on the cultural candidate (Codex
    # review). An unresolved cultural-only row gets mbid=None: we never verified its identity.
    resolved_by_key = {(item.ranked.title, item.ranked.artist): item for item in resolved}
    for cand in pool:
        if len(ordered) >= RECOMMENDATION_LIMIT:
            break
        if (cand.title, cand.artist) in used:
            continue
        found = resolved_by_key.get((cand.title, cand.artist))
        mbid = found.mbid if found else None
        if mbid is not None and mbid in used_mbids:
            continue  # a verified duplicate of an already-placed recording (or the seed) — drop it
        used.add((cand.title, cand.artist))
        if mbid is not None:
            used_mbids.add(mbid)
        ordered.append(RecommendationResult(
            position=0, title=cand.title, artist=cand.artist,
            mbid=mbid,
            provider_track_id=found.provider_track_id if found else None,
            cultural_score=cand.cultural_score, was_audio_scored=False, sources=cand.sources,
        ))

    ordered = ordered[:RECOMMENDATION_LIMIT]
    return [replace(r, position=i) for i, r in enumerate(ordered, start=1)]


async def _explain(
    deps: PipelineDeps, seed_title: str, seed_artist: str, vibe: str | None,
    results: list[RecommendationResult],
) -> tuple[list[RecommendationResult], bool]:
    """Attach LLM rationales by position; fully degradable (absent/failed/empty ⇒ no rationales)."""
    if deps.explainer is None or not results:
        return results, False
    try:
        rationales = await deps.explainer.explain(
            seed_title=seed_title, seed_artist=seed_artist, vibe=vibe, results=results
        )
    except Exception:
        return results, False
    if not rationales:
        return results, False
    return [replace(r, rationale=rationales.get(r.position)) for r in results], True


def _result_rows(results: Sequence[RecommendationResult]) -> list[QueryLogResultRow]:
    return [
        QueryLogResultRow(
            position=r.position, title=r.title, artist=r.artist, cultural_score=r.cultural_score,
            was_audio_scored=r.was_audio_scored, mbid=r.mbid, provider_track_id=r.provider_track_id,
            audio_score=r.audio_score, vibe_text_score=r.vibe_text_score,
            combined_score=r.combined_score, sources=r.sources, rationale=r.rationale,
        )
        for r in results
    ]


async def enqueue_recommendation(
    deps: PipelineDeps, *, fields: QueryLogFields, seed_title: str, seed_artist: str,
    vibe: str | None, pool: Sequence[RankedCandidate],
) -> str:
    """Create the ``queued`` query_log row + enqueue ``recommend_job``; return the poll handle.

    Shared by the API (Gate-1-COLD) and :func:`run_pipeline` inline (Gate-2-COLD). In-flight dedup is
    the active-request_key partial unique index: if an identical request is already queued/running,
    the insert conflicts and we return *its* handle instead of starting a second job. A **terminal**
    row never blocks — a later identical request inserts a fresh row and runs a fresh job, so
    per-request telemetry is preserved and a completed result is never reused. ``fields`` must carry
    ``status="queued"`` (covered by the active index) and a ``request_key``; the handle and ARQ
    ``_job_id`` are ``"rec-<id>"`` for the new row.
    """
    assert fields.request_key is not None and deps.enqueue_job is not None
    async with deps.pool.acquire() as conn:
        try:
            query_log_id = await db.insert_query_log(conn, fields)
        except asyncpg.UniqueViolationError:
            active = await db.get_active_query_log(conn, fields.request_key)
            if active is not None:
                return _handle(active["id"])  # an identical request is in flight — share its handle
            # The active row terminated between our failed insert and this lookup (a rare TOCTOU):
            # it's now a fresh repeat, so insert again — no active row stands in the way this time.
            query_log_id = await db.insert_query_log(conn, fields)
    handle = _handle(query_log_id)
    try:
        await deps.enqueue_job(
            query_log_id, seed_title, seed_artist, vibe, _pool_payload(pool), _job_id=handle
        )
    except Exception:
        # The `queued` row is committed but no worker job was enqueued (e.g. Redis down). Remove it
        # (best-effort) so it doesn't poll 202 forever and wedge every future identical request onto
        # the same stuck handle via the active-request_key dedup. Re-raise the original failure.
        with contextlib.suppress(Exception):
            async with deps.pool.acquire() as conn:
                await db.delete_query_log(conn, query_log_id)
        raise
    return handle


def _pool_payload(pool: Sequence[RankedCandidate]) -> list[dict]:
    """Serialize the cultural pool for the ARQ job (JSON-safe, so it survives any job serializer)."""
    return [
        {"title": c.title, "artist": c.artist, "cultural_score": c.cultural_score,
         "ranks": dict(c.ranks), "mbids": sorted(c.mbids)}
        for c in pool
    ]


def pool_from_payload(payload: Sequence[Mapping]) -> list[RankedCandidate]:
    """Rebuild the cultural pool the worker received from :func:`_pool_payload`."""
    return [
        RankedCandidate(p["title"], p["artist"], p["cultural_score"], dict(p["ranks"]),
                        frozenset(p["mbids"]))
        for p in payload
    ]


async def _persist(
    deps: PipelineDeps, fields: QueryLogFields, results: Sequence[RecommendationResult], *,
    execution_mode: ExecutionMode, query_log_id: int | None, gate1: Gate1Meta | None,
) -> int:
    """Write the query_log + result snapshot. The worker (job mode) finalizes its pre-created row by
    id and replaces its results (idempotent re-run); WARM inserts a fresh complete row."""
    rows = _result_rows(results)
    if execution_mode == "job" and query_log_id is not None:
        async with deps.pool.acquire() as conn, conn.transaction():
            await db.update_query_log(conn, query_log_id, fields)
            await conn.execute("DELETE FROM query_log_results WHERE query_log_id = $1", query_log_id)
            await db.insert_query_log_results(conn, query_log_id, rows)
        return query_log_id

    # Pure WARM: insert a complete row, adding the Gate-1 fields the API measured.
    assert gate1 is not None  # only reached on the inline WARM path, where gate1 is provided
    fields = replace(
        fields, candidate_count=gate1.candidate_count, degraded=gate1.degraded,
        failed_sources=gate1.failed_sources, gate1=gate1.gate.value,
        gate1_threshold=gate1.threshold, uncached_count=gate1.uncached_count,
    )
    async with deps.pool.acquire() as conn, conn.transaction():
        new_id = await db.insert_query_log(conn, fields)
        await db.insert_query_log_results(conn, new_id, rows)
    return new_id


async def run_pipeline(
    deps: PipelineDeps, seed_title: str, seed_artist: str, vibe: str | None,
    pool: Sequence[RankedCandidate], gate1: Gate1Meta | None = None, *,
    execution_mode: ExecutionMode, query_log_id: int | None = None,
) -> Recommendation | Deferred:
    """Resolve → embed → score → backfill → explain → persist a recommendation.

    Returns a :class:`Recommendation`, or — only in ``execution_mode="inline"`` when Gate 2 trips —
    a :class:`Deferred` after handing the work to the worker. In ``"job"`` mode the gates never
    enqueue, so a :class:`Recommendation` always comes back. ``query_log_id`` is set in ``"job"``
    mode — the pre-created row the worker finalizes; WARM leaves it ``None`` and inserts a fresh row.
    ``gate1`` carries the API's Gate-1 telemetry: required for ``inline``, omitted for ``job`` (the
    queued row already records it, and the job-mode update preserves it via skip-``None``).
    """
    if execution_mode == "inline" and gate1 is None:
        raise ValueError("run_pipeline(execution_mode='inline') requires gate1 metadata")
    started = time.monotonic()
    request_key = request_key_for(seed_title, seed_artist, vibe)

    # 1. Seed → query vector (cache-first). No preview ⇒ cultural-only (skip resolve/embed/score).
    async with deps.pool.acquire() as conn:
        seed_mbid, seed_vector = await _resolve_and_embed_seed(deps, conn, seed_title, seed_artist)
    vibe_vector = await _embed_vibe(deps, vibe)

    resolved: list[_Resolved] = []
    counts = _ResolveCounts()
    vectors: dict[str, np.ndarray] = {}
    cache_hits = 0
    missing: list[_Resolved] = []
    gate2 = Gate.WARM

    if seed_vector is not None:
        # 2. Resolve the top-N cultural candidates (cache-first, sequential). Capped at
        #    RESOLVE_CANDIDATE_LIMIT because MusicBrainz's ~1 req/s makes resolving a full 100-200
        #    pool overrun the job timeout; the rest of `pool` still reaches cultural backfill below.
        async with deps.pool.acquire() as conn:
            resolved, counts = await _resolve_pool(deps, conn, pool[:RESOLVE_CANDIDATE_LIMIT])

        # 3. Gate 2 — how many FOUND candidates still lack a servable vector?
        async with deps.pool.acquire() as conn:
            embedded = await db.fetch_embeddings(conn, [r.mbid for r in resolved], CLAP_MODEL_VERSION)
        vectors = {str(row["mbid"]): np.asarray(row["embedding"]) for row in embedded}
        cache_hits = len(vectors)
        missing = [r for r in resolved if r.mbid not in vectors]
        gate2 = gate_for(len(missing), threshold=GATE2_ASYNC_THRESHOLD)

        if gate2 is Gate.COLD and execution_mode == "inline":
            assert gate1 is not None  # inline guarantees gate1 (checked at entry)
            queued = QueryLogFields(
                seed_title=seed_title, seed_artist=seed_artist, vibe_text=vibe, seed_mbid=seed_mbid,
                status="queued", request_key=request_key, candidate_count=gate1.candidate_count,
                degraded=gate1.degraded, failed_sources=gate1.failed_sources, gate1=gate1.gate.value,
                gate1_threshold=gate1.threshold, uncached_count=gate1.uncached_count,
                resolved_found=counts.found, resolved_rejected=counts.rejected,
                resolved_not_found=counts.not_found, gate2="cold",
                gate2_threshold=GATE2_ASYNC_THRESHOLD, missing_embeddings_count=len(missing),
                embeddings_cache_hits=cache_hits, seed_audio_scored=True,
            )
            return Deferred(await enqueue_recommendation(
                deps, fields=queued, seed_title=seed_title, seed_artist=seed_artist, vibe=vibe, pool=pool
            ))

        # 4. Embed the misses (bounded concurrency) and merge with the cache hits.
        vectors.update(await _embed_missing(deps, missing))

    # 5. Score + cultural backfill.
    results = _build_results(resolved, vectors, seed_vector, vibe_vector, pool, seed_mbid=seed_mbid)
    audio_scored = sum(1 for r in results if r.was_audio_scored)

    # 6. Explain (rationale only; degradable).
    results, rationales_available = await _explain(deps, seed_title, seed_artist, vibe, results)

    # 7. Persist the query_log + result snapshot.
    audio_path = seed_vector is not None
    fields = QueryLogFields(
        seed_title=seed_title, seed_artist=seed_artist, vibe_text=vibe, seed_mbid=seed_mbid,
        status="succeeded", request_key=request_key,
        latency_ms=int((time.monotonic() - started) * 1000),
        resolved_found=counts.found, resolved_rejected=counts.rejected,
        resolved_not_found=counts.not_found,
        gate2=(gate2.value if audio_path else None),
        gate2_threshold=(GATE2_ASYNC_THRESHOLD if audio_path else None),
        missing_embeddings_count=(len(missing) if audio_path else None),
        embeddings_computed=(len(vectors) - cache_hits if audio_path else None),
        embeddings_cache_hits=(cache_hits if audio_path else None),
        audio_scored_count=audio_scored, backfill_count=len(results) - audio_scored,
        seed_audio_scored=audio_path, rationales_available=rationales_available,
    )
    result_log_id = await _persist(
        deps, fields, results, execution_mode=execution_mode, query_log_id=query_log_id, gate1=gate1
    )

    return Recommendation(
        seed_title=seed_title, seed_artist=seed_artist, vibe=vibe, seed_mbid=seed_mbid,
        results=results, query_log_id=result_log_id,
        degradation=Degradation(
            seed_audio_scored=audio_path, cultural_backfill_count=len(results) - audio_scored,
            rationales_available=rationales_available,
            degraded_sources=dict(gate1.failed_sources) if gate1 is not None else {},
        ),
    )
