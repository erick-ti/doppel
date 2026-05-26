"""Data access for the caching corpus — hand-written async SQL over asyncpg.

These functions are the seam the Day-6 resolve loop calls; their signatures are pinned by the
existing matcher dataclasses (:class:`SeedRecording`, :class:`ProviderTrack`, :class:`MatchScore`,
:class:`ResolvedMatch`), so nothing here is speculative. Each takes an ``asyncpg.Connection`` —
the caller acquires one from :func:`doppel.db.pool.get_pool` (so transactions and the connection
lifetime stay the caller's concern).

Two facts shape the persistence mapping (see DECISIONS.md):
  * the resolver is Deezer-first, so ``NOT_FOUND`` never has an MBID and is recorded only in
    ``canonical_lookups`` — ``FOUND`` and ``REJECTED`` both carry an MBID + a verified asset;
  * the cache key reuses :func:`aggregation.candidates.normalized_key` verbatim, so a lookup hit
    aligns with the aggregator's dedupe (and Gate-1's uncached count).
"""
from __future__ import annotations

import json
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import asyncpg

from doppel.aggregation.candidates import normalized_key
from doppel.config import REEMBED_CONFIDENCE_DELTA, RESOLVER_VERSION
from doppel.matching.resolver import ResolvedMatch, ResolveStatus
from doppel.matching.verify import MatchScore, ProviderTrack, SeedRecording


def _as_uuid(value: str | uuid.UUID) -> uuid.UUID:
    """Coerce an MBID string to ``uuid.UUID`` (asyncpg's native UUID type); validates it too."""
    return value if isinstance(value, uuid.UUID) else uuid.UUID(value)


# --- canonical_lookups (resolve cache + negative cache) ---------------------- #


async def get_canonical_lookup(
    conn: asyncpg.Connection, title: str, artist: str
) -> asyncpg.Record | None:
    """The *current-version* cached resolve outcome for a candidate string, or ``None`` on a miss.

    Filters on ``RESOLVER_VERSION``, so a row written by older matcher / canonicalization logic reads
    as a miss — the caller simply re-resolves and upserts (which overwrites the stale row on the
    ``(norm_title, norm_artist)`` unique key), self-healing the cache without every caller having to
    remember a version check. (A version-agnostic read belongs in a separate diagnostics helper if
    one is ever needed.)
    """
    norm_title, norm_artist = normalized_key(title, artist)
    return await conn.fetchrow(
        "SELECT * FROM canonical_lookups "
        "WHERE norm_title = $1 AND norm_artist = $2 AND resolver_version = $3",
        norm_title,
        norm_artist,
        RESOLVER_VERSION,
    )


async def upsert_canonical_lookup(
    conn: asyncpg.Connection,
    *,
    query_title: str,
    query_artist: str,
    status: ResolveStatus,
    mbid: str | uuid.UUID | None,
    match_confidence: float | None,
) -> None:
    """Record (or refresh) a candidate string's resolve outcome, stamped with ``RESOLVER_VERSION``."""
    norm_title, norm_artist = normalized_key(query_title, query_artist)
    await conn.execute(
        """
        INSERT INTO canonical_lookups (
            norm_title, norm_artist, query_title, query_artist,
            status, mbid, match_confidence, resolver_version, last_resolved_at
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, now())
        ON CONFLICT (norm_title, norm_artist) DO UPDATE SET
            query_title      = EXCLUDED.query_title,
            query_artist     = EXCLUDED.query_artist,
            status           = EXCLUDED.status,
            mbid             = EXCLUDED.mbid,
            match_confidence = EXCLUDED.match_confidence,
            resolver_version = EXCLUDED.resolver_version,
            last_resolved_at = now()
        """,
        norm_title,
        norm_artist,
        query_title,
        query_artist,
        status.value,
        _as_uuid(mbid) if mbid is not None else None,
        match_confidence,
        RESOLVER_VERSION,
    )


async def count_uncached_candidates(
    conn: asyncpg.Connection,
    pairs: Sequence[tuple[str, str]],
    *,
    resolver_version: str = RESOLVER_VERSION,
) -> int:
    """How many of ``pairs`` (candidate ``(title, artist)``) are NOT cached at the current resolver
    version — Gate-1's *uncached count*, the lookups that would actually hit MusicBrainz (~1 req/s).

    One round trip: each pair is normalized exactly as the cache stores it (:func:`normalized_key`)
    and counted via a version-filtered ``NOT EXISTS`` — mirroring :func:`get_canonical_lookup`'s
    own ``resolver_version`` filter, so a stale-version row counts as uncached (it will re-resolve).
    Assumes ``pairs`` is already deduped (the aggregator's pool is), so each is one distinct key.
    """
    if not pairs:
        return 0
    norm = [normalized_key(title, artist) for title, artist in pairs]
    return await conn.fetchval(
        """
        SELECT count(*)
        FROM unnest($1::text[], $2::text[]) AS k(norm_title, norm_artist)
        WHERE NOT EXISTS (
            SELECT 1 FROM canonical_lookups cl
            WHERE cl.norm_title = k.norm_title
              AND cl.norm_artist = k.norm_artist
              AND cl.resolver_version = $3
        )
        """,
        [n[0] for n in norm],
        [n[1] for n in norm],
        resolver_version,
    )


# --- tracks + audio_assets (identity + provider evidence) -------------------- #


async def _upsert_track(conn: asyncpg.Connection, seed: SeedRecording) -> None:
    await conn.execute(
        """
        INSERT INTO tracks (mbid, title, artist, duration_ms, isrcs)
        VALUES ($1, $2, $3, $4, $5)
        ON CONFLICT (mbid) DO UPDATE SET
            title       = EXCLUDED.title,
            artist      = EXCLUDED.artist,
            duration_ms = EXCLUDED.duration_ms,
            isrcs       = EXCLUDED.isrcs
        """,
        _as_uuid(seed.mbid),
        seed.title,
        seed.artist,
        seed.duration_ms,
        sorted(seed.isrcs),
    )


async def _upsert_audio_asset(
    conn: asyncpg.Connection,
    mbid: str | uuid.UUID,
    candidate: ProviderTrack,
    match: MatchScore,
    status: ResolveStatus,
) -> int:
    """Insert/refresh the provider asset and return its surrogate id (for the embedding FK)."""
    row = await conn.fetchrow(
        """
        INSERT INTO audio_assets (
            mbid, provider, provider_track_id, preview_url, provider_track_duration_ms,
            isrc, asset_status, match_confidence, match_reason, isrc_match
        )
        VALUES ($1, 'deezer', $2, $3, $4, $5, $6, $7, $8, $9)
        ON CONFLICT (mbid, provider, provider_track_id) DO UPDATE SET
            preview_url                = EXCLUDED.preview_url,
            provider_track_duration_ms = EXCLUDED.provider_track_duration_ms,
            isrc                       = EXCLUDED.isrc,
            asset_status               = EXCLUDED.asset_status,
            match_confidence           = EXCLUDED.match_confidence,
            match_reason               = EXCLUDED.match_reason,
            isrc_match                 = EXCLUDED.isrc_match
        RETURNING id
        """,
        _as_uuid(mbid),
        None if candidate.provider_track_id is None else str(candidate.provider_track_id),
        candidate.preview_url,
        candidate.provider_track_duration_ms,
        candidate.isrc,
        status.value,
        match.confidence,
        match.reason.value,
        match.isrc_match,
    )
    return row["id"]


async def persist_resolved_match(
    conn: asyncpg.Connection,
    query_title: str,
    query_artist: str,
    resolved: ResolvedMatch,
) -> int | None:
    """Persist a resolver outcome in one transaction; return the **embeddable** asset id.

    NOT_FOUND has no MBID, so it writes only the negative-cache row in ``canonical_lookups``.
    FOUND/REJECTED both carry a canonicalized seed + a candidate, so they upsert the track, the
    provider asset, and the lookup (pointing at the MBID). The return value is FOUND-only: a
    REJECTED asset is still persisted (audit/negative evidence) but its id is *withheld* (``None``),
    so a caller can't mistake "an asset was written" for "embed this" and store a verification
    failure under the canonical MBID — the corpus-poisoning this layer exists to prevent.
    """
    async with conn.transaction():
        if resolved.status is ResolveStatus.NOT_FOUND:
            await upsert_canonical_lookup(
                conn,
                query_title=query_title,
                query_artist=query_artist,
                status=resolved.status,
                mbid=None,
                match_confidence=None,
            )
            return None

        seed, candidate, match = resolved.seed, resolved.candidate, resolved.match
        assert seed is not None and candidate is not None and match is not None  # FOUND/REJECTED invariant
        await _upsert_track(conn, seed)
        asset_id = await _upsert_audio_asset(conn, seed.mbid, candidate, match, resolved.status)
        if resolved.status is ResolveStatus.REJECTED:
            # A prior resolve may have marked this same provider asset FOUND and embedded it; now
            # that it's rejected, purge any vector sourced from it in the *same* transaction — else
            # fetch_embeddings would keep serving a preview the matcher no longer trusts (corpus
            # poisoning surviving a correction). Vectors from other, still-found assets are untouched.
            await conn.execute("DELETE FROM embeddings WHERE asset_id = $1", asset_id)
        await upsert_canonical_lookup(
            conn,
            query_title=query_title,
            query_artist=query_artist,
            status=resolved.status,
            mbid=seed.mbid,
            match_confidence=match.confidence,
        )
        # FOUND-only: a REJECTED asset is evidence, not embeddable — withhold its id (see docstring).
        return asset_id if resolved.status is ResolveStatus.FOUND else None


async def get_servable_track(conn: asyncpg.Connection, mbid: str | uuid.UUID) -> asyncpg.Record | None:
    """Track identity + its best FOUND asset for an MBID — the cache-hit path's read.

    When a candidate is a ``canonical_lookups`` hit (already resolved FOUND), the resolve loop has no
    :class:`ResolvedMatch` in hand, so it reads the persisted evidence here: the display
    ``title``/``artist`` (from ``tracks``) plus the ``preview_url`` + ``asset_id`` needed to re-embed a
    missing/stale vector and the ``provider_track_id`` that builds the Deezer link. Joined found-only
    (highest ``match_confidence`` wins if several assets exist), so a FOUND lookup whose asset has
    since flipped to rejected returns ``None`` — the candidate degrades to cultural rather than
    serving a vector from a preview the matcher no longer trusts.
    """
    return await conn.fetchrow(
        """
        SELECT t.mbid, t.title, t.artist, t.duration_ms,
               a.id AS asset_id, a.preview_url, a.provider_track_id, a.match_confidence
        FROM tracks t
        JOIN audio_assets a ON a.mbid = t.mbid
        WHERE t.mbid = $1 AND a.asset_status = 'found'
        ORDER BY a.match_confidence DESC
        LIMIT 1
        """,
        _as_uuid(mbid),
    )


# --- embeddings (the cached corpus) ------------------------------------------ #


async def get_embedding(
    conn: asyncpg.Connection, mbid: str | uuid.UUID, model_version: str
) -> asyncpg.Record | None:
    """The cached vector for ``(mbid, model_version)``, or ``None``.

    Reads the ``servable_embeddings`` view, so a row whose source asset is no longer ``found``
    reads as a miss (re-embed / re-resolve) rather than a usable cache hit — the same found-only
    guarantee as :func:`fetch_embeddings` / :func:`knn`, since all three share the view.
    """
    return await conn.fetchrow(
        "SELECT * FROM servable_embeddings WHERE mbid = $1 AND model_version = $2",
        _as_uuid(mbid),
        model_version,
    )


async def upsert_embedding(
    conn: asyncpg.Connection,
    *,
    mbid: str | uuid.UUID,
    model_version: str,
    embedding: Any,  # numpy float32 array (or list); pgvector codec encodes it
    source_confidence: float,
    asset_id: int,
) -> bool:
    """Store or refresh a CLAP vector for a FOUND asset; return ``True`` if written, ``False`` if an
    existing equal/higher-confidence vector was kept (a refused downgrade).

    Two DB-side guards make corpus poisoning structural rather than caller-dependent:
      * **found-only** — raises ``ValueError`` unless ``asset_id`` is a ``found`` asset for ``mbid``;
        embedding a rejected/foreign asset under the canonical MBID is the exact failure this layer
        prevents (the composite FK guarantees mbid-consistency, but *not* match success).
      * **no-downgrade** — the ON CONFLICT branch overwrites only when the incoming
        ``source_confidence`` is ``>=`` the stored one, so a late lower-confidence write (a Day-6
        retry / concurrent ARQ job) can't silently downgrade the corpus. The upgrade-worthiness
        decision (``REEMBED_CONFIDENCE_DELTA``) stays with the caller via :func:`needs_reembed`;
        this only blocks strict downgrades and stays idempotent on an equal-confidence rewrite.
    """
    mbid_u = _as_uuid(mbid)
    async with conn.transaction():
        status = await conn.fetchval(
            "SELECT asset_status FROM audio_assets WHERE id = $1 AND mbid = $2", asset_id, mbid_u
        )
        if status != "found":
            raise ValueError(
                f"refusing to embed asset {asset_id} for mbid {mbid}: "
                f"asset_status={status!r} (expected 'found')"
            )
        written = await conn.fetchval(
            """
            INSERT INTO embeddings (mbid, model_version, embedding, source_confidence, asset_id)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (mbid, model_version) DO UPDATE SET
                embedding         = EXCLUDED.embedding,
                source_confidence = EXCLUDED.source_confidence,
                asset_id          = EXCLUDED.asset_id
            WHERE EXCLUDED.source_confidence >= embeddings.source_confidence
            RETURNING 1
            """,
            mbid_u,
            model_version,
            embedding,
            source_confidence,
            asset_id,
        )
    return written is not None


async def fetch_embeddings(
    conn: asyncpg.Connection, mbids: Iterable[str | uuid.UUID], model_version: str
) -> list[asyncpg.Record]:
    """Bulk-fetch cached vectors for a candidate pool by MBID — the lazy-corpus hot path.

    Reads ``servable_embeddings`` (found-asset only), so a vector from a no-longer-trusted preview
    can never re-enter recommendations even if its row lingers past a reclassification.
    """
    return await conn.fetch(
        """
        SELECT mbid, embedding, source_confidence, asset_id
        FROM servable_embeddings
        WHERE model_version = $1 AND mbid = ANY($2::uuid[])
        """,
        model_version,
        [_as_uuid(m) for m in mbids],
    )


def needs_reembed(existing_source_conf: float, new_conf: float) -> bool:
    """Whether a newly matched asset is good enough to justify refreshing an existing embedding."""
    return new_conf - existing_source_conf >= REEMBED_CONFIDENCE_DELTA


async def knn(
    conn: asyncpg.Connection, query_vector: Any, k: int, *, model_version: str
) -> list[asyncpg.Record]:
    """Cosine-nearest embeddings to ``query_vector`` (forward-looking ANN lane; v1 fetches by MBID).

    ``<=>`` is pgvector's cosine distance; vectors are L2-normalized so it ranks like inner product.
    Reads ``servable_embeddings`` (found-asset only) — the same guard as :func:`fetch_embeddings`.
    """
    return await conn.fetch(
        """
        SELECT mbid, embedding <=> $1 AS distance
        FROM servable_embeddings
        WHERE model_version = $2
        ORDER BY embedding <=> $1
        LIMIT $3
        """,
        query_vector,
        model_version,
        k,
    )


# --- query_logs + query_log_results (request telemetry + the durable result snapshot) ------- #
#
# Day 6 turns Day 5's request log into the system's empirical feedback loop: every /recommend request
# — WARM (inline) and COLD (worker) alike — writes one query_logs row plus one query_log_results row
# per returned track. A COLD request inserts a ``queued`` row at enqueue (so the poll finds it
# immediately), which the worker finalizes; a WARM request inserts a terminal row in one shot. The
# result rows are the durable record the COLD poll reconstructs from and Day-7 eval reads — a child
# table, not a JSONB blob, so per-result analytics are plain SQL (see DECISIONS.md / migration 0002).

_TERMINAL_STATUSES = frozenset({"succeeded", "failed"})


@dataclass(frozen=True)
class QueryLogFields:
    """The full query_logs telemetry, one attribute per column.

    Most fields are optional because a COLD row is written in two phases: the API inserts what it
    knows (request + the gate decision that deferred it) as ``queued``, and the worker fills the
    downstream counts on completion. WARM writes everything at once. In :func:`update_query_log` a
    ``None`` field means *leave the stored value unchanged*, so the worker's finalize can never null
    the gate fields the API set at create time.
    """

    seed_title: str
    seed_artist: str
    status: str = "succeeded"  # queued | running | succeeded | failed
    request_key: str | None = None  # deterministic seed+vibe key, for in-flight dedup (NOT the row id)
    vibe_text: str | None = None
    seed_mbid: str | uuid.UUID | None = None
    candidate_count: int | None = None
    degraded: bool | None = None
    failed_sources: Mapping[str, str] | None = None
    latency_ms: int | None = None
    error: str | None = None
    gate1: str | None = None  # warm | cold
    gate2: str | None = None
    gate1_threshold: int | None = None
    gate2_threshold: int | None = None
    uncached_count: int | None = None
    missing_embeddings_count: int | None = None
    resolved_found: int | None = None
    resolved_rejected: int | None = None
    resolved_not_found: int | None = None
    embeddings_computed: int | None = None
    embeddings_cache_hits: int | None = None
    audio_scored_count: int | None = None
    backfill_count: int | None = None
    seed_audio_scored: bool | None = None
    rationales_available: bool | None = None


# Telemetry columns in table order; drives both insert and update so they can't drift apart.
_QUERY_LOG_COLUMNS = (
    "seed_title", "seed_artist", "status", "request_key", "vibe_text", "seed_mbid",
    "candidate_count", "degraded", "failed_sources", "latency_ms", "error",
    "gate1", "gate2", "gate1_threshold", "gate2_threshold", "uncached_count",
    "missing_embeddings_count", "resolved_found", "resolved_rejected", "resolved_not_found",
    "embeddings_computed", "embeddings_cache_hits", "audio_scored_count", "backfill_count",
    "seed_audio_scored", "rationales_available",
)


def _query_log_cell(fields: QueryLogFields, column: str) -> Any:
    """One column's bind value — coercing the MBID to UUID and the failed-sources map to JSON."""
    if column == "seed_mbid":
        return _as_uuid(fields.seed_mbid) if fields.seed_mbid is not None else None
    if column == "failed_sources":
        return None if fields.failed_sources is None else json.dumps(dict(fields.failed_sources))
    return getattr(fields, column)


def _present_columns(fields: QueryLogFields) -> tuple[list[str], list[Any]]:
    """``(columns, bind values)`` for the telemetry fields that are set.

    A ``None`` field is omitted, which means *apply the DB default* on INSERT (so the Day-5 NOT NULL
    columns ``degraded`` / ``failed_sources`` take their defaults) and *leave the stored value
    unchanged* on UPDATE (so the worker's finalize can't null the API's create-time gate fields).
    ``status`` is always included.
    """
    cols: list[str] = []
    values: list[Any] = []
    for column in _QUERY_LOG_COLUMNS:
        if column == "status" or getattr(fields, column) is not None:
            cols.append(column)
            values.append(_query_log_cell(fields, column))
    return cols, values


async def insert_query_log(conn: asyncpg.Connection, fields: QueryLogFields) -> int:
    """Insert a query_logs row and return its id.

    WARM passes a terminal status with the full telemetry; COLD passes ``queued`` plus only what the
    API knows at enqueue, and :func:`update_query_log` finalizes it. ``completed_at`` is stamped when
    ``status`` is terminal.
    """
    cols, values = _present_columns(fields)
    placeholders = ", ".join(f"${i}" for i in range(1, len(values) + 1))
    completed_at = "now()" if fields.status in _TERMINAL_STATUSES else "NULL"
    row = await conn.fetchrow(
        f"INSERT INTO query_logs ({', '.join(cols)}, completed_at) "
        f"VALUES ({placeholders}, {completed_at}) RETURNING id",
        *values,
    )
    return row["id"]


async def update_query_log(
    conn: asyncpg.Connection, query_log_id: int, fields: QueryLogFields
) -> None:
    """Finalize the row identified by ``query_log_id`` with the worker's downstream telemetry.

    Only the set fields are written (``None`` = leave unchanged), so the worker can't clobber the
    gate fields the API recorded at create time. ``status`` is always written; ``completed_at`` is
    stamped when the new status is terminal. (``seed_title`` / ``seed_artist`` are stable, so
    re-writing them is a harmless no-op.)
    """
    cols, values = _present_columns(fields)
    sets = [f"{col} = ${i}" for i, col in enumerate(cols, start=1)]
    if fields.status in _TERMINAL_STATUSES:
        sets.append("completed_at = now()")
    values.append(query_log_id)
    await conn.execute(
        f"UPDATE query_logs SET {', '.join(sets)} WHERE id = ${len(values)}", *values
    )


@dataclass(frozen=True)
class QueryLogResultRow:
    """One returned track, denormalized for the durable snapshot so it renders without a join.

    ``mbid`` is ``None`` for an unresolved cultural-backfill track; the cosines / ``combined_score``
    are ``None`` for a non-audio-scored (backfill) row, while ``cultural_score`` (RRF) is always
    present (every result came from the cultural pool). ``provider_track_id`` builds the Deezer
    track-*page* link in the response — never the ephemeral preview-audio URL (invariant #2).
    """

    position: int
    title: str
    artist: str
    cultural_score: float
    was_audio_scored: bool
    mbid: str | uuid.UUID | None = None
    provider_track_id: str | None = None
    audio_score: float | None = None
    vibe_text_score: float | None = None
    combined_score: float | None = None
    sources: Sequence[str] = ()
    rationale: str | None = None


async def insert_query_log_results(
    conn: asyncpg.Connection, query_log_id: int, rows: Sequence[QueryLogResultRow]
) -> None:
    """Bulk-insert the per-track result snapshot for a query_logs row (no-op on an empty list)."""
    if not rows:
        return
    await conn.executemany(
        """
        INSERT INTO query_log_results (
            query_log_id, position, mbid, title, artist, provider_track_id,
            audio_score, vibe_text_score, combined_score, cultural_score,
            was_audio_scored, sources, rationale
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
        """,
        [
            (
                query_log_id, r.position,
                _as_uuid(r.mbid) if r.mbid is not None else None,
                r.title, r.artist, r.provider_track_id,
                r.audio_score, r.vibe_text_score, r.combined_score, r.cultural_score,
                r.was_audio_scored, list(r.sources), r.rationale,
            )
            for r in rows
        ],
    )


async def get_query_log(conn: asyncpg.Connection, query_log_id: int) -> asyncpg.Record | None:
    """The query_logs row by id — the COLD poll's status + telemetry, or ``None`` if unknown."""
    return await conn.fetchrow("SELECT * FROM query_logs WHERE id = $1", query_log_id)


async def get_active_query_log(
    conn: asyncpg.Connection, request_key: str
) -> asyncpg.Record | None:
    """The in-flight (queued/running) row for ``request_key``, or ``None`` — for in-flight dedup.

    Backs the enqueue path: when inserting a queued row conflicts on the active-request_key partial
    unique index, an identical request is already running, so the caller returns *its* handle rather
    than starting a second job. A terminal row never matches, so a repeat after completion gets a
    fresh row + run.
    """
    return await conn.fetchrow(
        "SELECT * FROM query_logs WHERE request_key = $1 AND status IN ('queued', 'running')",
        request_key,
    )


async def delete_query_log(conn: asyncpg.Connection, query_log_id: int) -> None:
    """Remove a query_logs row by id (CASCADE drops its results).

    Used to clean up a just-created ``queued`` row whose job-enqueue then failed — otherwise the row
    stays non-terminal with no worker behind it, polls ``202`` forever, and (via the active
    ``request_key`` index) wedges every future identical request onto the same stuck handle.
    """
    await conn.execute("DELETE FROM query_logs WHERE id = $1", query_log_id)


async def reap_stale_active_query_logs(conn: asyncpg.Connection, older_than_s: int) -> int:
    """Mark **running** rows whose last transition is older than ``older_than_s`` as ``failed`` —
    recovering rows orphaned when a worker died mid-job (SIGKILL/OOM/reboot) without its in-process
    handler running. Returns the number reaped.

    Only ``running`` rows are reaped, deliberately NOT ``queued``: a ``queued`` row's ``updated_at`` is
    its enqueue time, so age alone can't distinguish a genuine orphan from a job merely waiting behind a
    backlog (queue wait scales with depth under ``WORKER_MAX_JOBS``), and its ARQ job will still run (in
    prod, Redis AOF persists the queue across restarts). Age-reaping queued rows would falsely fail
    valid work and clear its dedup. A ``running`` row older than ``older_than_s`` (> ``JOB_TIMEOUT_S``,
    enforced by ``config._validate_tuning``) instead outlived ARQ's ``job_timeout`` cancellation without
    reaching a terminal status — a hard kill — so its job is dead and reaping cannot resurrect it.

    Flipping ``status`` to ``failed`` clears the partial unique index ``query_logs_active_request_key``,
    so the seed/vibe stops dedup-wedging future requests (``get_active_query_log`` then misses) and the
    poll reaches a terminal state instead of a forever-202. (A ``queued`` orphan — its ARQ job lost
    *after* a successful enqueue, e.g. the sub-second AOF-fsync window on a hard Redis crash or a
    volume loss — is NOT reaped here; reconciling queued rows against ARQ job existence is a deferred
    v1 residual, tracked in ROADMAP.)
    """
    reaped = await conn.fetch(
        """
        UPDATE query_logs
           SET status = 'failed',
               error = $2,
               completed_at = now()
         WHERE status = 'running'
           AND updated_at < now() - ($1::int * interval '1 second')
        RETURNING id
        """,
        older_than_s,
        f"reclaimed by stale-job reaper: running row had no terminal status within {older_than_s}s "
        "(worker crash/OOM/reboot mid-job)",
    )
    return len(reaped)


async def get_query_log_results(
    conn: asyncpg.Connection, query_log_id: int
) -> list[asyncpg.Record]:
    """The ordered per-track result snapshot for a query_logs row (the poll's payload on success)."""
    return await conn.fetch(
        "SELECT * FROM query_log_results WHERE query_log_id = $1 ORDER BY position",
        query_log_id,
    )
