"""Resolver — orchestrate Deezer fetch + MusicBrainz canonicalization + verify.

The matcher's entry point: given a messy ``(title, artist)`` candidate, produce a
recording-level MBID, a verified preview URL, and a match confidence — or an
explicit non-match status. It composes a track finder (Deezer) and a recording
canonicalizer (MusicBrainz) behind small Protocols, so the orchestration is
unit-testable without live HTTP.

Order is provider-first: Deezer reliably yields the preview + ISRC + full-track
duration, which then *inform* canonicalization (ISRC-anchored, else
nearest-duration). The identity check stays in :func:`score_match`.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from doppel.matching.verify import MatchScore, ProviderTrack, SeedRecording, score_match


class ResolveStatus(str, Enum):
    """Terminal outcome of a resolve, aligned with the eventual ``audio_assets.asset_status``."""

    FOUND = "found"          # canonicalized + a verified preview
    REJECTED = "rejected"    # provider track found, but failed verification
    NOT_FOUND = "not_found"  # no relevant provider track, or no MB recording


class TrackFinder(Protocol):
    async def find_track(self, title: str, artist: str) -> ProviderTrack | None: ...


class RecordingCanonicalizer(Protocol):
    async def canonicalize(
        self, title: str, artist: str, *, isrc: str | None, target_duration_ms: int | None
    ) -> SeedRecording | None: ...


@dataclass(frozen=True)
class ResolvedMatch:
    """Resolve outcome plus the evidence behind it (for persistence + logging)."""

    status: ResolveStatus
    seed: SeedRecording | None
    candidate: ProviderTrack | None
    match: MatchScore | None
    detail: str = ""

    @property
    def mbid(self) -> str | None:
        return self.seed.mbid if self.seed else None

    @property
    def preview_url(self) -> str | None:
        return self.candidate.preview_url if self.candidate else None

    @property
    def confidence(self) -> float:
        return self.match.confidence if self.match else 0.0


async def resolve(
    finder: TrackFinder,
    canonicalizer: RecordingCanonicalizer,
    title: str,
    artist: str,
) -> ResolvedMatch:
    """Resolve a ``(title, artist)`` candidate to a verified preview + MBID."""
    candidate = await finder.find_track(title, artist)
    if candidate is None:
        return ResolvedMatch(ResolveStatus.NOT_FOUND, None, None, None,
                             "no relevant provider track with a preview")

    seed = await canonicalizer.canonicalize(
        title, artist, isrc=candidate.isrc,
        target_duration_ms=candidate.provider_track_duration_ms,
    )
    if seed is None:
        return ResolvedMatch(ResolveStatus.NOT_FOUND, None, candidate, None,
                             "no MusicBrainz recording for candidate")

    match = score_match(seed, candidate)
    if match.accepted:
        return ResolvedMatch(ResolveStatus.FOUND, seed, candidate, match)
    return ResolvedMatch(
        ResolveStatus.REJECTED, seed, candidate, match,
        f"verification {match.confidence:.2f} below threshold ({match.reason.value})",
    )
