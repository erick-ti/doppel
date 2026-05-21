"""Match verification — decide whether a provider track is the *same recording*.

Given a canonical recording (the **seed**, resolved from MusicBrainz) and a
provider track (the **candidate**, from Deezer), score how confident we are that
they are the same recording — not a cover, karaoke, live take, remix, or remaster.

This is the matcher's safety net, and the project's single most important quality
gate. A bad match poisons the corpus *silently*: a karaoke cover embedded under
the studio recording's MBID produces wrong recommendations forever, and nothing
surfaces the error. So the logic here is deliberately conservative and exhaustively
tested (see ``tests/test_verify_match.py``).

Three signals, combined:

* **ISRC** — an exact ISRC match is definitive (an ISRC names exactly one
  recording), so it short-circuits to 1.0. A *non*-matching ISRC proves nothing
  (a recording can have several ISRCs / releases), so it never penalizes.
* **duration** — MusicBrainz recording length vs the provider's *full track
  duration* (NOT the 30 s preview clip — see ``provider_track_duration_ms``).
  A delta within 3 s scores 1.0, decays linearly to 0.0 at 15 s, and beyond 15 s
  is a hard reject regardless of the string signals (this is what separates a
  studio cut from its longer live/remix siblings, since their titles are identical).
* **title / artist** — RapidFuzz ``token_set_ratio``, which absorbs "feat."
  reorderings and suffix noise without bespoke parsing.

    confidence = duration*0.40 + title*0.35 + artist*0.25      (each in [0, 1])

A confidence below ``MATCH_ACCEPT_THRESHOLD`` (0.75) is a reject. The weights and
threshold are decision-grade (see DECISIONS.md): change them only together with
the test suite, which is calibrated against them.

Known residual gap: a cover/karaoke that shares the seed's *exact* title and
duration but credits a different artist can still clear 0.75, because artist's
0.25 weight cannot override a perfect title+duration. The test suite marks those
cases ``xfail``. See DECISIONS.md / SESSION_NOTES.md "artist floor" open question.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from rapidfuzz import fuzz
from rapidfuzz.utils import default_process

# --------------------------------------------------------------------------- #
# Tunables — decision-grade. Keep in sync with DECISIONS.md and the test suite.
# --------------------------------------------------------------------------- #

DURATION_WEIGHT = 0.40
TITLE_WEIGHT = 0.35
ARTIST_WEIGHT = 0.25

#: A combined confidence at or above this is a match; below it is a reject.
MATCH_ACCEPT_THRESHOLD = 0.75

#: Duration delta (seconds) → score: at or under FULL_SCORE is a clean 1.0; the
#: score decays linearly to 0.0 at HARD_REJECT; beyond HARD_REJECT is rejected
#: outright (a different recording — live take, remix, edit).
DURATION_FULL_SCORE_DELTA_S = 3.0
DURATION_HARD_REJECT_DELTA_S = 15.0

#: When either side has no usable duration we can neither confirm nor deny on that
#: axis, so we score it neutrally rather than rewarding or hard-rejecting the pair.
DURATION_UNKNOWN_SCORE = 0.5


class MatchReason(str, Enum):
    """Why ``score_match`` returned the confidence it did."""

    ISRC = "isrc"                                  # exact ISRC match → 1.0
    WEIGHTED = "weighted"                          # the duration/title/artist blend
    DURATION_HARD_REJECT = "duration-hard-reject"  # |Δduration| beyond the threshold → 0.0


@dataclass(frozen=True)
class SeedRecording:
    """The canonical recording we want a preview for (resolved from MusicBrainz).

    ``duration_ms`` is the recording's length; ``isrcs`` is MusicBrainz's ISRC list
    for *this* recording. Because canonicalization is recording-level, each variant
    (live / remaster / remix) carries its own duration and ISRCs.
    """

    title: str
    artist: str
    duration_ms: int | None = None
    isrcs: frozenset[str] = field(default_factory=frozenset)
    mbid: str | None = None  # canonical identity; carried, not used by scoring


@dataclass(frozen=True)
class ProviderTrack:
    """A provider (Deezer) track being verified against a :class:`SeedRecording`.

    ``provider_track_duration_ms`` is the provider's *full track duration* — NOT
    the 30-second preview clip. The field is named explicitly because an earlier
    design used ``preview_duration_ms`` (~30 s), which made the duration check
    reject every candidate. ``preview_url`` / ``provider_track_id`` are the payload
    we keep when a match is verified; they are carried, not used by scoring.
    """

    title: str
    artist: str
    provider_track_duration_ms: int | None = None
    isrc: str | None = None
    preview_url: str | None = None
    provider_track_id: int | None = None


@dataclass(frozen=True)
class MatchScore:
    """A verification result with the per-signal breakdown, for logging + tests.

    ``duration_score`` is ``None`` when duration was hard-rejected; ``reason`` and
    ``duration_delta_ms`` disambiguate that from the missing-duration case (where
    the score is :data:`DURATION_UNKNOWN_SCORE` and the delta is ``None``).
    """

    confidence: float
    accepted: bool
    reason: MatchReason
    title_score: float
    artist_score: float
    duration_score: float | None
    duration_delta_ms: int | None
    isrc_match: bool


def _normalize_isrc(isrc: str | None) -> str | None:
    """Canonicalize an ISRC for comparison: keep alphanumerics, upper-case.

    ISRCs are formatted ``CC-XXX-YY-NNNNN`` but get reported with or without the
    hyphens and in either case, so both sides are normalized before comparison.
    """
    if not isrc:
        return None
    cleaned = "".join(ch for ch in isrc if ch.isalnum()).upper()
    return cleaned or None


def _string_score(a: str, b: str) -> float:
    """``token_set_ratio`` in [0, 1] with default normalization.

    Token *set* comparison absorbs reordering and extra tokens ("Daft Punk" vs
    "Daft Punk, Romanthony" → 1.0), and ``default_process`` lowercases and drops
    punctuation so "HUMBLE." == "humble". Note this means title alone cannot tell
    a studio cut from "<title> (Live)" / "(Remix)" — that is duration's job.
    """
    return fuzz.token_set_ratio(a, b, processor=default_process) / 100.0


def _duration_delta_ms(seed_ms: int | None, provider_ms: int | None) -> int | None:
    """Absolute duration delta in ms, or ``None`` if either side is unusable."""
    if seed_ms is None or provider_ms is None or seed_ms <= 0 or provider_ms <= 0:
        return None
    return abs(seed_ms - provider_ms)


def _duration_score(delta_ms: int | None) -> float | None:
    """Map a duration delta to [0, 1]; ``None`` in → neutral, hard-reject → ``None`` out.

    Returns :data:`DURATION_UNKNOWN_SCORE` when the delta is unknown, and ``None``
    to signal a hard reject when the delta exceeds the hard-reject threshold.
    """
    if delta_ms is None:
        return DURATION_UNKNOWN_SCORE
    delta_s = delta_ms / 1000.0
    if delta_s > DURATION_HARD_REJECT_DELTA_S:
        return None
    if delta_s <= DURATION_FULL_SCORE_DELTA_S:
        return 1.0
    span = DURATION_HARD_REJECT_DELTA_S - DURATION_FULL_SCORE_DELTA_S
    return 1.0 - (delta_s - DURATION_FULL_SCORE_DELTA_S) / span


def score_match(seed: SeedRecording, candidate: ProviderTrack) -> MatchScore:
    """Verify ``candidate`` against ``seed`` and return the full breakdown.

    Evaluation order encodes precedence: a definitive ISRC match wins outright; a
    duration delta beyond the hard-reject threshold sinks the match regardless of
    how well the strings agree; otherwise the weighted blend decides.
    """
    title_score = _string_score(seed.title, candidate.title)
    artist_score = _string_score(seed.artist, candidate.artist)
    delta_ms = _duration_delta_ms(seed.duration_ms, candidate.provider_track_duration_ms)

    # 1. ISRC is definitive — an ISRC names exactly one recording.
    seed_isrcs = {n for n in (_normalize_isrc(i) for i in seed.isrcs) if n}
    cand_isrc = _normalize_isrc(candidate.isrc)
    if cand_isrc and cand_isrc in seed_isrcs:
        return MatchScore(1.0, True, MatchReason.ISRC, title_score, artist_score,
                          None, delta_ms, isrc_match=True)

    # 2. Duration hard reject — a big delta means a different recording.
    duration_score = _duration_score(delta_ms)
    if duration_score is None:
        return MatchScore(0.0, False, MatchReason.DURATION_HARD_REJECT, title_score,
                          artist_score, None, delta_ms, isrc_match=False)

    # 3. Weighted blend.
    confidence = (
        duration_score * DURATION_WEIGHT
        + title_score * TITLE_WEIGHT
        + artist_score * ARTIST_WEIGHT
    )
    return MatchScore(confidence, confidence >= MATCH_ACCEPT_THRESHOLD,
                      MatchReason.WEIGHTED, title_score, artist_score,
                      duration_score, delta_ms, isrc_match=False)


def verify_match(seed: SeedRecording, candidate: ProviderTrack) -> float:
    """Confidence in [0, 1] that ``candidate`` is the same recording as ``seed``.

    1.0 on an exact ISRC match; 0.0 on a duration hard reject; otherwise the
    weighted blend of duration / title / artist agreement. A value below
    :data:`MATCH_ACCEPT_THRESHOLD` should be treated as a reject (the eventual
    ``audio_assets.asset_status`` becomes ``'rejected'``); call :func:`score_match`
    for the per-signal breakdown.
    """
    return score_match(seed, candidate).confidence
