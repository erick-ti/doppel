"""Aggregator — fan out to cultural sources, dedupe, rank, and gate.

Given a seed ``(title, artist)``:

  1. fan out to every :class:`CandidateSource` concurrently, with **per-source
     isolation** — a source that errors *or* runs past its timeout contributes nothing
     rather than sinking the run, so Last.fm carries recall when ListenBrainz is down
     and vice versa (degraded mode is a first-class feature). A failed source
     is recorded in :attr:`AggregateResult.failed_sources` so a broken/slow *primary*
     source is observable, not silently erased;
  2. drop any candidate that is the seed itself (never recommend a track back to
     itself), using the same conservative key the dedupe groups by;
  3. conservatively dedupe and Reciprocal-Rank-Fusion-rank the survivors;
  4. apply **Gate 1** — a count threshold deciding whether MusicBrainz
     canonicalization should run inline (warm) or be deferred to the async path
     (cold), since MB is ~1 req/sec and a large pool would stall a warm request.

The ranked candidates are ``(title, artist)`` pairs ready for the matcher's
``resolve(finder, canonicalizer, title, artist)`` — every :class:`RankedCandidate`
exposes ``.title`` / ``.artist``. Driving the actual resolve loop and the async / ARQ
machinery behind the gate is the pipeline's job (Day 6); this module stops at the
ranked pool + the gate decision + the degraded-source report.
"""
from __future__ import annotations

import asyncio
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol

import httpx

from doppel.aggregation.candidates import Candidate, normalized_key
from doppel.aggregation.ranking import RankedCandidate, rank
from doppel.config import GATE1_ASYNC_THRESHOLD, SOURCE_TIMEOUT_S
from doppel.sources.errors import SourceError


class CandidateSource(Protocol):
    """A cultural source: maps a seed ``(title, artist)`` to ranked candidates.

    ``source`` names the provider (e.g. ``"lastfm"``) so the aggregator can report a
    *failed* source — which contributes no candidates to read a name from — in
    :attr:`AggregateResult.failed_sources`.
    """

    source: str

    async def similar_candidates(self, title: str, artist: str) -> list[Candidate]: ...


class Gate(str, Enum):
    """Gate-1 outcome: resolve canonicalization inline, or defer to the async path."""

    WARM = "warm"  # small pool — canonicalize inline within the request
    COLD = "cold"  # large pool — hand off to the async worker (MB is ~1 req/sec)


@dataclass(frozen=True)
class AggregateResult:
    """The ranked cultural pool, the Gate-1 decision, and any degraded-source report."""

    candidates: list[RankedCandidate]
    gate: Gate
    #: source name -> error summary, for the sources that failed (empty when all succeeded).
    failed_sources: Mapping[str, str] = field(default_factory=dict)

    @property
    def count(self) -> int:
        return len(self.candidates)

    @property
    def degraded(self) -> bool:
        """True when a source failed or timed out — recall may be incomplete."""
        return bool(self.failed_sources)


def gate_for(count: int, *, threshold: int = GATE1_ASYNC_THRESHOLD) -> Gate:
    """Gate-1: COLD at or above ``threshold`` candidates needing canonicalization, else WARM.

    ``count`` is the deduped candidate count today; once the ``canonical_lookups``
    cache exists (Day 5) it becomes the count of *uncached* candidates — the lookups
    that would actually hit MusicBrainz.
    """
    return Gate.COLD if count >= threshold else Gate.WARM


async def aggregate(
    sources: Sequence[CandidateSource],
    title: str,
    artist: str,
    *,
    gate_threshold: int = GATE1_ASYNC_THRESHOLD,
    source_timeout_s: float = SOURCE_TIMEOUT_S,
) -> AggregateResult:
    """Fan out to ``sources``, drop the seed, dedupe + RRF-rank, and apply Gate 1.

    A source that hits a documented degradable failure (transport/HTTP error, Last.fm's
    non-not-found in-band error, a malformed upstream body, or running past
    ``source_timeout_s``) contributes nothing but is recorded in ``failed_sources``, so a
    broken or slow *primary* source is observable rather than silently erased.
    """
    seed_key = normalized_key(title, artist)
    per_source = await asyncio.gather(
        *(_safe(src, title, artist, source_timeout_s) for src in sources)
    )
    candidates = [
        c
        for _, source_candidates, _ in per_source
        for c in source_candidates
        if normalized_key(c.title, c.artist) != seed_key  # never recommend the seed back
    ]
    failed_sources = {name: error for name, _, error in per_source if error is not None}
    ranked = rank(candidates)
    return AggregateResult(ranked, gate_for(len(ranked), threshold=gate_threshold), failed_sources)


_URL_RE = re.compile(r"https?://\S+")


def _redact_error(exc: Exception) -> str:
    """A safe one-line summary of a degradable source failure for ``failed_sources``.

    Never include the request URL: a source may carry a credential as a query param (Last.fm's
    ``api_key``), and httpx embeds the full request URL in ``HTTPStatusError`` messages — so a raw
    ``str(exc)`` would leak the key into ``failed_sources``, which flows to the API degradation block,
    the persisted ``query_logs`` row (and its backups), and the showcase export. HTTP-status errors
    collapse to the status code; any other message has URLs scrubbed defensively.
    """
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTPStatusError: HTTP {exc.response.status_code}"
    return f"{type(exc).__name__}: {_URL_RE.sub('<url>', str(exc))}"


async def _safe(
    source: CandidateSource, title: str, artist: str, timeout_s: float
) -> tuple[str, list[Candidate], str | None]:
    """Per-source isolation: returns ``(source name, candidates, error summary or None)``.

    Bounds the source by ``timeout_s`` (so one slow/hung source can't hold the whole
    fan-out) and catches the adapters' documented degradable failures — transport/HTTP
    errors and :class:`SourceError` (a malformed response, or Last.fm's in-band errors).
    Each contributes no candidates but is reported as a failed source, so a broken/slow
    primary source is visible in the result. Anything else propagates, so a genuine bug
    surfaces rather than hiding as an empty cultural pool.
    """
    try:
        return source.source, await asyncio.wait_for(source.similar_candidates(title, artist), timeout_s), None
    except TimeoutError:
        return source.source, [], f"timeout after {timeout_s:g}s"
    except (httpx.HTTPError, SourceError) as exc:
        return source.source, [], _redact_error(exc)
