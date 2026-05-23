"""Candidate model + conservative dedupe — the unit a source emits and how the
aggregator collapses duplicates across sources.

A :class:`Candidate` is one similar-track suggestion from a single cultural source
(Last.fm, ListenBrainz), carrying that source's own ranking of it. :func:`dedupe`
collapses candidates that name the *same recording* — across sources and within one —
into a :class:`MergedCandidate` that remembers each source's best rank (the input
Reciprocal Rank Fusion needs) and the union of source-supplied MBIDs.

The dedupe is deliberately **conservative**. Its grouping key normalizes only pure
formatting noise — case, punctuation, unicode composition, whitespace — and never
strips recording-variant tokens ("live", "acoustic", "remaster", "remix", "edit",
"version", "demo", "mix", "instrumental"). So "Song" and "Song (Live)" stay separate
candidates while "HUMBLE." and "humble" merge. The asymmetry is intentional: a false
negative (two entries for one recording) costs one extra MusicBrainz lookup, but a
false positive (collapsing two different recordings) permanently loses a candidate —
so we bias toward keeping both. See DECISIONS.md / BRAINDUMP "conservative dedupe".
"""
from __future__ import annotations

import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from rapidfuzz.utils import default_process


@dataclass(frozen=True)
class Candidate:
    """One similar-track suggestion from a single cultural source.

    ``rank`` is 1-based — the source's top suggestion is rank 1 — which is exactly
    what Reciprocal Rank Fusion consumes (``1 / (k + rank)``). ``mbid`` is the
    source's recording MBID when it supplies one (ListenBrainz returns its canonical
    MBID; Last.fm's is best-effort and often absent), carried for provenance and
    possible reuse downstream. ``score`` is the source's native similarity, kept for
    logging only — RRF ranks by position, not by these cross-source-incomparable
    numbers.
    """

    title: str
    artist: str
    source: str
    rank: int
    mbid: str | None = None
    score: float | None = None


@dataclass(frozen=True)
class MergedCandidate:
    """One unique recording after dedupe, with per-source ranks merged.

    ``ranks`` maps each source that surfaced this recording to its best (lowest) rank
    there — the Reciprocal Rank Fusion inputs. ``title`` / ``artist`` are the display
    strings of the *first* candidate seen for the group (the aggregator decides source
    order), and ``mbids`` is the union of any source-supplied MBIDs.
    """

    title: str
    artist: str
    ranks: Mapping[str, int]
    mbids: frozenset[str]


def normalize_text(text: str) -> str:
    """Normalize *only* formatting noise — never recording identity (dedupe key + seed anchor).

    NFKC-normalizes unicode, lowercases + drops punctuation (RapidFuzz
    ``default_process``, which is unicode-aware — it keeps accented and CJK letters),
    and collapses internal whitespace. Variant tokens survive as ordinary words, so
    "Song" and "Song (Live)" produce different keys. When the result is empty — a
    title/artist made only of symbols, e.g. the band "!!!" — it falls back to the
    casefolded raw text so two such distinct strings never collapse to one empty key.
    """
    folded = " ".join(default_process(unicodedata.normalize("NFKC", text)).split())
    if folded:
        return folded
    return " ".join(unicodedata.normalize("NFKC", text).split()).casefold()


def normalized_key(title: str, artist: str) -> tuple[str, str]:
    """The conservative dedupe key for a ``(title, artist)`` pair.

    Public so the aggregator can drop the seed from its own results using the exact
    same normalization the dedupe groups by.
    """
    return (normalize_text(title), normalize_text(artist))


def dedupe(candidates: Iterable[Candidate]) -> list[MergedCandidate]:
    """Collapse same-recording candidates (across and within sources), conservatively.

    Groups by the formatting-normalized ``(title, artist)`` key, keeps the best rank
    per source, unions the MBIDs, and preserves the first-seen display strings. Output
    is in first-appearance order; :func:`~doppel.aggregation.ranking.rank` orders by RRF.

    The key is text only — MBIDs are merged as provenance, *not* used to split. That is
    deliberate (see DECISIONS.md): the vibe-relevant variants already differ by title
    token, Last.fm's MBIDs are unreliable (splitting would false-split the same recording
    and defeat RRF consensus), and ``resolve()`` keys on ``(title, artist)`` anyway.
    """
    groups: dict[tuple[str, str], dict] = {}
    for c in candidates:
        key = normalized_key(c.title, c.artist)
        group = groups.get(key)
        if group is None:
            group = {"title": c.title, "artist": c.artist, "ranks": {}, "mbids": set()}
            groups[key] = group
        ranks = group["ranks"]
        if c.source not in ranks or c.rank < ranks[c.source]:
            ranks[c.source] = c.rank  # best (lowest = most similar) rank per source
        if c.mbid:
            group["mbids"].add(c.mbid)
    return [
        MergedCandidate(g["title"], g["artist"], dict(g["ranks"]), frozenset(g["mbids"]))
        for g in groups.values()
    ]
