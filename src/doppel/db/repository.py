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
from collections.abc import Iterable, Mapping
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


# --- query_logs (request telemetry; Day-6 enriches the shape) ---------------- #


async def insert_query_log(
    conn: asyncpg.Connection,
    *,
    seed_title: str,
    seed_artist: str,
    vibe_text: str | None = None,
    seed_mbid: str | uuid.UUID | None = None,
    candidate_count: int | None = None,
    degraded: bool = False,
    failed_sources: Mapping[str, str] | None = None,
    latency_ms: int | None = None,
) -> int:
    row = await conn.fetchrow(
        """
        INSERT INTO query_logs (
            seed_title, seed_artist, vibe_text, seed_mbid,
            candidate_count, degraded, failed_sources, latency_ms
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        RETURNING id
        """,
        seed_title,
        seed_artist,
        vibe_text,
        _as_uuid(seed_mbid) if seed_mbid is not None else None,
        candidate_count,
        degraded,
        json.dumps(dict(failed_sources or {})),
        latency_ms,
    )
    return row["id"]
