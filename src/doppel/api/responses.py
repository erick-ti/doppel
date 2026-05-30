"""Wire-format builders mapping pipeline results to the ``/recommend`` response schema.

The single source of truth for the ``Recommendation`` → :class:`RecommendationResponse` mapping. Used
by the API (the WARM 200 body and the COLD poll-success body) **and** by
``scripts/export_showcase.py`` (the v1.1 static-showcase export), so the exported JSON is
byte-identical to what the live API serves — change the mapping in one place and both follow.

``deezer_url`` builds a track-*page* link from the provider id — never the ephemeral preview-audio
URL (invariant #2).
"""
from __future__ import annotations

import json

from doppel.api.schemas import (
    DegradationInfo,
    RecommendationResponse,
    ResultItem,
    SeedInfo,
)
from doppel.pipeline.recommend import Recommendation

DEEZER_TRACK_URL = "https://www.deezer.com/track/"


def deezer_url(provider_track_id) -> str | None:
    """Deezer track-PAGE link from the provider id (invariant #2: a link, never preview audio)."""
    return f"{DEEZER_TRACK_URL}{provider_track_id}" if provider_track_id else None


def response_from_recommendation(rec: Recommendation) -> RecommendationResponse:
    """Build the WARM 200 body (and the showcase export) from the in-hand :class:`Recommendation`."""
    return RecommendationResponse(
        query_id=rec.query_log_id if rec.query_log_id is not None else 0,
        seed=SeedInfo(title=rec.seed_title, artist=rec.seed_artist, mbid=rec.seed_mbid),
        vibe=rec.vibe,
        results=[
            ResultItem(
                position=r.position, title=r.title, artist=r.artist, mbid=r.mbid,
                deezer_url=deezer_url(r.provider_track_id), was_audio_scored=r.was_audio_scored,
                audio_score=r.audio_score, vibe_text_score=r.vibe_text_score,
                combined_score=r.combined_score, cultural_score=r.cultural_score,
                sources=list(r.sources), rationale=r.rationale,
            )
            for r in rec.results
        ],
        degradation=DegradationInfo(
            seed_audio_scored=rec.degradation.seed_audio_scored,
            cultural_backfill_count=rec.degradation.cultural_backfill_count,
            rationales_available=rec.degradation.rationales_available,
            degraded_sources=dict(rec.degradation.degraded_sources),
        ),
    )


def response_from_rows(row, results) -> RecommendationResponse:
    """Reconstruct the success body from the durable query_logs + query_log_results rows (COLD poll)."""
    return RecommendationResponse(
        query_id=row["id"],
        seed=SeedInfo(
            title=row["seed_title"], artist=row["seed_artist"],
            mbid=str(row["seed_mbid"]) if row["seed_mbid"] else None,
        ),
        vibe=row["vibe_text"],
        results=[
            ResultItem(
                position=r["position"], title=r["title"], artist=r["artist"],
                mbid=str(r["mbid"]) if r["mbid"] else None, deezer_url=deezer_url(r["provider_track_id"]),
                was_audio_scored=r["was_audio_scored"], audio_score=r["audio_score"],
                vibe_text_score=r["vibe_text_score"], combined_score=r["combined_score"],
                cultural_score=r["cultural_score"], sources=list(r["sources"]), rationale=r["rationale"],
            )
            for r in results
        ],
        degradation=DegradationInfo(
            seed_audio_scored=bool(row["seed_audio_scored"]),
            cultural_backfill_count=row["backfill_count"] or 0,
            rationales_available=bool(row["rationales_available"]),
            degraded_sources=decode_failed_sources(row["failed_sources"]),
        ),
    )


def decode_failed_sources(value) -> dict[str, str]:
    """``query_logs.failed_sources`` is JSONB; asyncpg returns it as text without a JSON codec."""
    if value is None:
        return {}
    if isinstance(value, str):
        try:
            return dict(json.loads(value))
        except (ValueError, TypeError):
            return {}
    return dict(value)
