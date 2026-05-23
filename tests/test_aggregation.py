"""Aggregation tests — conservative dedupe, RRF ranking, and the aggregator.

Pins the behaviors that matter most: the dedupe collapses pure formatting noise but
preserves recording variants (a false merge permanently drops a candidate), RRF
rewards cross-source consensus on 1-based ranks, and the aggregator fans out with
per-source isolation, drops the seed, and gates on candidate count. A final test
walks the seam from a ranked candidate into the matcher's resolve().
"""
from __future__ import annotations

import asyncio

import httpx
import pytest

from doppel.aggregation.aggregator import Gate, aggregate, gate_for
from doppel.aggregation.candidates import Candidate, dedupe
from doppel.aggregation.ranking import rank, rrf_score
from doppel.config import GATE1_ASYNC_THRESHOLD, RRF_K
from doppel.matching.resolver import ResolveStatus, resolve
from doppel.matching.verify import ProviderTrack, SeedRecording
from doppel.sources.errors import SourceResponseError
from doppel.sources.lastfm import LastFmError


# --------------------------------------------------------------------------- #
# Conservative dedupe
# --------------------------------------------------------------------------- #

def _titles(merged) -> list[str]:
    return sorted(m.title for m in merged)


def test_dedupe_collapses_formatting_noise() -> None:
    merged = dedupe([
        Candidate("HUMBLE.", "Kendrick Lamar", "lastfm", 1),
        Candidate("humble", "KENDRICK LAMAR", "listenbrainz", 4),  # case + punctuation only
    ])
    assert len(merged) == 1
    assert merged[0].ranks == {"lastfm": 1, "listenbrainz": 4}


def test_dedupe_preserves_recording_variants() -> None:
    # The core safety property: variant tokens must NOT collapse into the base title.
    merged = dedupe([
        Candidate("Song", "A", "lastfm", 1),
        Candidate("Song (Live)", "A", "lastfm", 2),
        Candidate("Song (Acoustic)", "A", "lastfm", 3),
        Candidate("Song - Remaster", "A", "lastfm", 4),
    ])
    assert _titles(merged) == ["Song", "Song (Acoustic)", "Song (Live)", "Song - Remaster"]


def test_dedupe_merges_whitespace_and_punctuation_variants() -> None:
    merged = dedupe([
        Candidate("Song (Live)", "A", "lastfm", 5),
        Candidate("Song(Live)", "A", "listenbrainz", 2),  # only spacing/punctuation differs → merge
    ])
    assert len(merged) == 1 and merged[0].ranks == {"lastfm": 5, "listenbrainz": 2}


def test_dedupe_keeps_accents_distinct() -> None:
    # Conservative: don't fold accents — collapsing risks losing a genuinely distinct track.
    merged = dedupe([
        Candidate("Beyoncé", "X", "lastfm", 1),
        Candidate("Beyonce", "X", "lastfm", 2),
    ])
    assert len(merged) == 2


def test_dedupe_symbol_only_strings_do_not_collapse() -> None:
    # "!!!" (a real band) and "❤" both normalize to "" — the fallback keeps them apart.
    merged = dedupe([
        Candidate("Intro", "!!!", "lastfm", 1),
        Candidate("Intro", "❤", "lastfm", 2),
    ])
    assert len(merged) == 2


def test_dedupe_unions_mbids_and_keeps_first_display() -> None:
    merged = dedupe([
        Candidate("Mask Off", "Future", "listenbrainz", 1, mbid="mb-1"),
        Candidate("mask off", "future", "lastfm", 2, mbid="mb-2"),
        Candidate("MASK OFF", "Future", "lastfm", 5),  # within-source dup, worse rank, no mbid
    ])
    assert len(merged) == 1
    m = merged[0]
    assert (m.title, m.artist) == ("Mask Off", "Future")   # first-seen display preserved
    assert m.mbids == frozenset({"mb-1", "mb-2"})
    assert m.ranks == {"listenbrainz": 1, "lastfm": 2}      # best (lowest) rank per source


# --------------------------------------------------------------------------- #
# Reciprocal Rank Fusion
# --------------------------------------------------------------------------- #

def test_rrf_score_is_one_based_with_k() -> None:
    assert rrf_score({"a": 1}) == pytest.approx(1 / (RRF_K + 1))
    assert rrf_score({"a": 1, "b": 1}) == pytest.approx(2 / (RRF_K + 1))
    assert rrf_score({"a": 2}, k=10) == pytest.approx(1 / 12)


def test_rank_orders_by_consensus_then_breaks_ties_by_name() -> None:
    ranked = rank([
        Candidate("Solo", "Z", "lastfm", 1),          # single source @1
        Candidate("Both", "Y", "lastfm", 9),          # two sources at worse individual ranks…
        Candidate("Both", "Y", "listenbrainz", 9),    # …but consensus wins
        Candidate("Alpha", "X", "listenbrainz", 1),   # ties Solo's score
    ])
    assert ranked[0].title == "Both"                  # 2/(k+9) > 1/(k+1)
    assert [c.title for c in ranked[1:]] == ["Alpha", "Solo"]  # equal score → alphabetical


def test_rank_exposes_source_provenance() -> None:
    ranked = rank([
        Candidate("T", "A", "lastfm", 1),
        Candidate("T", "A", "listenbrainz", 2),
    ])
    assert ranked[0].sources == ("lastfm", "listenbrainz") and ranked[0].source_count == 2


# --------------------------------------------------------------------------- #
# Gate 1
# --------------------------------------------------------------------------- #

def test_gate_for_threshold() -> None:
    assert gate_for(GATE1_ASYNC_THRESHOLD - 1) is Gate.WARM
    assert gate_for(GATE1_ASYNC_THRESHOLD) is Gate.COLD
    assert gate_for(0) is Gate.WARM
    assert gate_for(3, threshold=3) is Gate.COLD


# --------------------------------------------------------------------------- #
# Aggregator
# --------------------------------------------------------------------------- #

class FakeSource:
    def __init__(
        self, candidates=None, *, raises: Exception | None = None, source: str = "fake", delay: float = 0.0
    ) -> None:
        self._candidates = candidates or []
        self._raises = raises
        self.source = source
        self._delay = delay
        self.calls: list[tuple[str, str]] = []

    async def similar_candidates(self, title: str, artist: str) -> list[Candidate]:
        self.calls.append((title, artist))
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._raises is not None:
            raise self._raises
        return list(self._candidates)


async def test_aggregate_merges_across_sources_and_drops_seed() -> None:
    lb = FakeSource([
        Candidate("Mask Off", "Future", "listenbrainz", 1),
        Candidate("HUMBLE.", "Kendrick Lamar", "listenbrainz", 2),  # the seed itself
    ])
    lf = FakeSource([Candidate("Mask Off", "Future", "lastfm", 1)])
    res = await aggregate([lb, lf], "humble", "kendrick lamar")  # seed given in other casing
    assert [c.title for c in res.candidates] == ["Mask Off"]      # seed dropped despite casing diff
    assert res.candidates[0].source_count == 2
    assert res.gate is Gate.WARM


async def test_aggregate_degrades_on_documented_source_failures() -> None:
    good = FakeSource([Candidate("A", "B", "listenbrainz", 1)], source="listenbrainz")
    http_down = FakeSource(raises=httpx.ConnectError("boom"), source="flaky")
    bad_key = FakeSource(raises=LastFmError(10, "Invalid API key"), source="lastfm")
    res = await aggregate([good, http_down, bad_key], "S", "T")
    assert [c.title for c in res.candidates] == ["A"]       # survivors only; no crash
    assert res.degraded is True
    assert set(res.failed_sources) == {"flaky", "lastfm"}   # both failures recorded and named
    assert "10" in res.failed_sources["lastfm"]             # the bad-key error is captured, not erased


async def test_aggregate_clean_run_reports_no_failed_sources() -> None:
    res = await aggregate([FakeSource([Candidate("A", "B", "lastfm", 1)], source="lastfm")], "S", "T")
    assert res.failed_sources == {} and res.degraded is False


async def test_aggregate_times_out_slow_source() -> None:
    # A slow/hung source must not hold the warm path hostage — it's dropped past the
    # per-source budget and recorded, while the fast source's candidates still come through.
    slow = FakeSource([Candidate("Slow", "X", "listenbrainz", 1)], source="listenbrainz", delay=1.0)
    fast = FakeSource([Candidate("Fast", "Y", "lastfm", 1)], source="lastfm")
    res = await aggregate([slow, fast], "S", "T", source_timeout_s=0.01)
    assert [c.title for c in res.candidates] == ["Fast"]
    assert res.degraded is True
    assert "timeout" in res.failed_sources["listenbrainz"]


async def test_aggregate_records_malformed_source() -> None:
    ok = FakeSource([Candidate("A", "B", "listenbrainz", 1)], source="listenbrainz")
    broken = FakeSource(raises=SourceResponseError("non-JSON body"), source="lastfm")
    res = await aggregate([ok, broken], "S", "T")
    assert [c.title for c in res.candidates] == ["A"]                       # survivor still ranked
    assert "SourceResponseError" in res.failed_sources["lastfm"]            # malformed → observable


async def test_aggregate_propagates_unexpected_errors() -> None:
    boom = FakeSource(raises=ValueError("a bug, not a degradable upstream failure"))
    with pytest.raises(ValueError):
        await aggregate([boom], "S", "T")


async def test_aggregate_gate_cold_when_pool_large() -> None:
    many = FakeSource([Candidate(f"T{i}", "A", "lastfm", i + 1) for i in range(GATE1_ASYNC_THRESHOLD)])
    res = await aggregate([many], "S", "T")
    assert res.count == GATE1_ASYNC_THRESHOLD and res.gate is Gate.COLD


async def test_aggregate_empty_with_no_sources() -> None:
    res = await aggregate([], "S", "T")
    assert res.candidates == [] and res.gate is Gate.WARM


# --------------------------------------------------------------------------- #
# Seam: a ranked candidate flows into the matcher's resolve()
# --------------------------------------------------------------------------- #

class _Finder:
    async def find_track(self, title: str, artist: str) -> ProviderTrack:
        return ProviderTrack(title, artist, 200_000, "ISRCAAA", "https://p.mp3", 1)


class _Canon:
    async def canonicalize(self, title, artist, *, isrc, target_duration_ms) -> SeedRecording:
        return SeedRecording(title, artist, 200_000, frozenset({"ISRCAAA"}), "mbid-seam")


async def test_ranked_candidate_feeds_resolve() -> None:
    res = await aggregate([FakeSource([Candidate("Mask Off", "Future", "lastfm", 1)])], "S", "T")
    top = res.candidates[0]
    resolved = await resolve(_Finder(), _Canon(), top.title, top.artist)
    assert resolved.status is ResolveStatus.FOUND
    assert resolved.mbid == "mbid-seam" and resolved.confidence == 1.0
