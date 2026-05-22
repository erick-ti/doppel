"""Resolver orchestration tests — fake adapters, no HTTP.

Verifies the status machine (FOUND / REJECTED / NOT_FOUND), that the candidate's
ISRC + duration are forwarded to canonicalization, and that the convenience
properties (mbid / preview_url / confidence) reflect the right state.
"""
from __future__ import annotations

import pytest

from doppel.matching.resolver import ResolveStatus, resolve
from doppel.matching.verify import ProviderTrack, SeedRecording


class FakeFinder:
    def __init__(self, result: ProviderTrack | None) -> None:
        self._result = result
        self.calls: list[tuple[str, str]] = []

    async def find_track(self, title: str, artist: str) -> ProviderTrack | None:
        self.calls.append((title, artist))
        return self._result


class FakeCanonicalizer:
    def __init__(self, result: SeedRecording | None) -> None:
        self._result = result
        self.calls: list[tuple] = []

    async def canonicalize(self, title, artist, *, isrc, target_duration_ms):
        self.calls.append((title, artist, isrc, target_duration_ms))
        return self._result


async def test_found_when_candidate_verifies() -> None:
    cand = ProviderTrack("Blinding Lights", "The Weeknd", 200_000, "USUG11904206", "https://prev.mp3", 916424)
    seed = SeedRecording("Blinding Lights", "The Weeknd", 200_000, frozenset({"USUG11904206"}), "mbid-1")
    r = await resolve(FakeFinder(cand), FakeCanonicalizer(seed), "Blinding Lights", "The Weeknd")
    assert r.status is ResolveStatus.FOUND
    assert r.confidence == 1.0  # ISRC match
    assert r.mbid == "mbid-1"
    assert r.preview_url == "https://prev.mp3"
    assert r.candidate is cand and r.seed is seed


async def test_weighted_acceptance_without_isrc() -> None:
    # No ISRC anywhere; perfect strings + matching duration clear the bar via the blend.
    cand = ProviderTrack("One More Time", "Daft Punk", 320_000, None, "p", 9)
    seed = SeedRecording("One More Time", "Daft Punk", 320_000, frozenset(), "mbid-omt")
    r = await resolve(FakeFinder(cand), FakeCanonicalizer(seed), "One More Time", "Daft Punk")
    assert r.status is ResolveStatus.FOUND
    assert r.confidence == pytest.approx(1.0)
    assert r.match is not None and r.match.reason.value == "weighted"


async def test_rejected_when_verification_fails() -> None:
    # A live take: identical strings but +120 s and no shared ISRC → duration hard reject.
    cand = ProviderTrack("Blinding Lights", "The Weeknd", 320_000, None, "https://prev.mp3", 1)
    seed = SeedRecording("Blinding Lights", "The Weeknd", 200_000, frozenset(), "mbid-1")
    r = await resolve(FakeFinder(cand), FakeCanonicalizer(seed), "Blinding Lights", "The Weeknd")
    assert r.status is ResolveStatus.REJECTED
    assert r.confidence < 0.75
    assert r.mbid == "mbid-1"  # we still canonicalized; only the audio match failed
    assert "below threshold" in r.detail


async def test_not_found_when_no_provider_track() -> None:
    r = await resolve(FakeFinder(None), FakeCanonicalizer(None), "X", "Y")
    assert r.status is ResolveStatus.NOT_FOUND
    assert r.candidate is None and r.seed is None
    assert r.mbid is None and r.preview_url is None and r.confidence == 0.0


async def test_not_found_when_no_canonical_recording() -> None:
    cand = ProviderTrack("X", "Y", 200_000, "ZZ0000000000", "https://prev.mp3", 1)
    r = await resolve(FakeFinder(cand), FakeCanonicalizer(None), "X", "Y")
    assert r.status is ResolveStatus.NOT_FOUND
    assert r.candidate is cand          # got a preview...
    assert r.seed is None and r.mbid is None  # ...but no canonical MBID
    assert r.preview_url == "https://prev.mp3"


async def test_cover_candidate_is_rejected() -> None:
    # If a cover that names the original artist reaches verification (it would normally
    # be stopped at the Deezer gate), score_match's cover guard still rejects it.
    cand = ProviderTrack("Blinding Lights", "The Weeknd Karaoke", 200_000, None, "https://prev.mp3", 1)
    seed = SeedRecording("Blinding Lights", "The Weeknd", 200_000, frozenset(), "mbid-1")
    r = await resolve(FakeFinder(cand), FakeCanonicalizer(seed), "Blinding Lights", "The Weeknd")
    assert r.status is ResolveStatus.REJECTED
    assert r.match is not None and r.match.reason.value == "cover-mismatch"


async def test_candidate_isrc_and_duration_forwarded_to_canonicalizer() -> None:
    cand = ProviderTrack("HUMBLE.", "Kendrick Lamar", 177_000, "USUM71703085", "p", 5)
    seed = SeedRecording("HUMBLE.", "Kendrick Lamar", 177_000, frozenset({"USUM71703085"}), "m")
    canon = FakeCanonicalizer(seed)
    await resolve(FakeFinder(cand), canon, "HUMBLE.", "Kendrick Lamar")
    assert canon.calls == [("HUMBLE.", "Kendrick Lamar", "USUM71703085", 177_000)]
