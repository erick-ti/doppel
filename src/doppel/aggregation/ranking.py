"""Cultural ranking via Reciprocal Rank Fusion.

The cultural sources (Last.fm, ListenBrainz) each return their *own* ranked list, and
their native similarity scores are not comparable across sources (a Last.fm 0..1
"match" and a ListenBrainz integer "score" measure different things on different
scales). RRF sidesteps calibration entirely by fusing on **rank** alone:

    cultural_score(track) = Σ_source  1 / (k + rank_source(track))

with rank 1-based and ``k`` = :data:`~doppel.config.RRF_K` (60, the standard value).
A track both sources rank highly outscores one that only a single source ranks #1, so
cross-source consensus rises to the top — exactly what we want for the degraded /
backfill cultural ordering.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from doppel.aggregation.candidates import Candidate, dedupe
from doppel.config import RRF_K


@dataclass(frozen=True)
class RankedCandidate:
    """A deduped candidate with its fused cultural score and source provenance."""

    title: str
    artist: str
    cultural_score: float
    ranks: Mapping[str, int]  # source -> best (1-based) rank; the RRF inputs
    mbids: frozenset[str]

    @property
    def sources(self) -> tuple[str, ...]:
        """Sources that surfaced this candidate, sorted for stable provenance."""
        return tuple(sorted(self.ranks))

    @property
    def source_count(self) -> int:
        return len(self.ranks)


def rrf_score(ranks: Mapping[str, int], *, k: int = RRF_K) -> float:
    """Reciprocal Rank Fusion score from per-source 1-based ranks."""
    return sum(1.0 / (k + rank) for rank in ranks.values())


def rank(candidates: Iterable[Candidate], *, k: int = RRF_K) -> list[RankedCandidate]:
    """Dedupe, then order candidates by descending RRF cultural score.

    Ties break by title then artist (case-insensitive), so the order is deterministic.
    """
    ranked = [
        RankedCandidate(m.title, m.artist, rrf_score(m.ranks, k=k), m.ranks, m.mbids)
        for m in dedupe(candidates)
    ]
    ranked.sort(key=lambda c: (-c.cultural_score, c.title.casefold(), c.artist.casefold()))
    return ranked
