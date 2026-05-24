"""Pydantic request/response models for the ``/recommend`` API.

The result item carries a Deezer track-*page* link (``deezer_url``) built from the provider track id —
never the ephemeral preview-audio URL (invariant #2). The ``degradation`` block makes the three
degraded paths (no seed preview → cultural-only, cultural backfill, LLM unavailable) observable to
callers, the same data Day-7 evaluation buckets results by.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from doppel.config import MAX_VIBE_TEXT_CHARS


class RecommendRequest(BaseModel):
    """A ``/recommend`` request: a seed track and an optional natural-language vibe."""

    seed_title: str = Field(min_length=1, max_length=500)
    seed_artist: str = Field(min_length=1, max_length=500)
    # Outer bound on the vibe (the CLAP text encoder also caps internally); rejects pathological input.
    vibe: str | None = Field(default=None, max_length=MAX_VIBE_TEXT_CHARS)


class SeedInfo(BaseModel):
    title: str
    artist: str
    mbid: str | None = None


class ResultItem(BaseModel):
    """One recommended track. ``deezer_url`` is a track-PAGE link (not preview audio)."""

    position: int
    title: str
    artist: str
    mbid: str | None = None
    deezer_url: str | None = None
    was_audio_scored: bool
    audio_score: float | None = None
    vibe_text_score: float | None = None
    combined_score: float | None = None
    cultural_score: float
    sources: list[str] = Field(default_factory=list)
    rationale: str | None = None


class DegradationInfo(BaseModel):
    seed_audio_scored: bool
    cultural_backfill_count: int
    rationales_available: bool
    degraded_sources: dict[str, str] = Field(default_factory=dict)


class RecommendationResponse(BaseModel):
    """A completed recommendation — the WARM 200 body and the COLD poll-success body."""

    status: str = "succeeded"
    query_id: int
    seed: SeedInfo
    vibe: str | None = None
    results: list[ResultItem]
    degradation: DegradationInfo


class JobAccepted(BaseModel):
    """A COLD handoff (202) or an in-flight poll: the job_id to poll and where to poll it."""

    status: str  # "queued" | "running"
    job_id: str
    status_url: str | None = None


class JobFailed(BaseModel):
    """A failed COLD job, surfaced by the poll with a sanitized error."""

    status: str = "failed"
    job_id: str
    error: str | None = None
