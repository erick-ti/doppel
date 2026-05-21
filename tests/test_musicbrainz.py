"""MusicBrainzClient canonicalization tests — offline, via httpx.MockTransport.

Covers the two paths from DECISIONS.md: ISRC-anchored selection and the
nearest-duration fallback within a string-matching cluster, plus ISRC
normalization and the carry-through of query strings onto the seed. A fast
limiter is injected so the ~1 req/sec pacing doesn't slow the suite.
"""
from __future__ import annotations

import httpx
import pytest
from aiolimiter import AsyncLimiter

from doppel.sources.musicbrainz import MusicBrainzClient


@pytest.fixture
def no_pace() -> AsyncLimiter:
    return AsyncLimiter(10**6, 1)  # effectively unthrottled, for tests only


def _rec(mbid: str, title: str, artist: str, length: int) -> dict:
    return {"id": mbid, "title": title, "artist-credit": [{"name": artist}], "length": length}


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_canonicalize_isrc_anchored(no_pace: AsyncLimiter) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params["query"].startswith("isrc:"):
            return httpx.Response(200, json={"recordings": [_rec("mbid-isrc", "Blinding Lights", "The Weeknd", 200046)]})
        return httpx.Response(200, json={"recordings": []})

    async with _client(handler) as c:
        seed = await MusicBrainzClient(c, limiter=no_pace).canonicalize(
            "Blinding Lights", "The Weeknd", isrc="USUG11904206", target_duration_ms=200_000)

    assert seed is not None
    assert seed.mbid == "mbid-isrc"
    assert seed.duration_ms == 200046
    assert "USUG11904206" in seed.isrcs
    assert seed.title == "Blinding Lights" and seed.artist == "The Weeknd"


async def test_canonicalize_nearest_duration(no_pace: AsyncLimiter) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params["query"].startswith("isrc:"):
            return httpx.Response(200, json={"recordings": []})
        return httpx.Response(200, json={"recordings": [
            _rec("long", "Blinding Lights", "The Weeknd", 262000),
            _rec("right", "Blinding Lights", "The Weeknd", 200000),
            _rec("edit", "Blinding Lights", "The Weeknd", 215000),
        ]})

    async with _client(handler) as c:
        seed = await MusicBrainzClient(c, limiter=no_pace).canonicalize(
            "Blinding Lights", "The Weeknd", isrc=None, target_duration_ms=200_000)

    assert seed is not None and seed.mbid == "right" and seed.duration_ms == 200000
    assert not seed.isrcs  # nearest-duration path carries no ISRC anchor


async def test_nearest_duration_filters_wrong_strings(no_pace: AsyncLimiter) -> None:
    # A same-duration but wrong-title recording must be filtered out before the
    # nearest-duration pick, even though its duration is closer.
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params["query"].startswith("isrc:"):
            return httpx.Response(200, json={"recordings": []})
        return httpx.Response(200, json={"recordings": [
            _rec("wrong-song", "Save Your Tears", "The Weeknd", 200000),
            _rec("right", "Blinding Lights", "The Weeknd", 201000),
        ]})

    async with _client(handler) as c:
        seed = await MusicBrainzClient(c, limiter=no_pace).canonicalize(
            "Blinding Lights", "The Weeknd", isrc=None, target_duration_ms=200_000)

    assert seed is not None and seed.mbid == "right"


async def test_no_recording_returns_none(no_pace: AsyncLimiter) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"recordings": []})

    async with _client(handler) as c:
        seed = await MusicBrainzClient(c, limiter=no_pace).canonicalize(
            "No Such Song", "Nobody", isrc="XX0000000000", target_duration_ms=200_000)

    assert seed is None


async def test_isrc_empty_falls_back_to_cluster(no_pace: AsyncLimiter) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params["query"].startswith("isrc:"):
            return httpx.Response(200, json={"recordings": []})  # ISRC not in MB
        return httpx.Response(200, json={"recordings": [_rec("by-dur", "HUMBLE.", "Kendrick Lamar", 177000)]})

    async with _client(handler) as c:
        seed = await MusicBrainzClient(c, limiter=no_pace).canonicalize(
            "HUMBLE.", "Kendrick Lamar", isrc="USUM71703085", target_duration_ms=177_000)

    assert seed is not None and seed.mbid == "by-dur"
    assert not seed.isrcs  # fell through to nearest-duration, so no ISRC anchor


async def test_isrc_hyphens_normalized(no_pace: AsyncLimiter) -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        q = request.url.params["query"]
        if q.startswith("isrc:"):
            seen["isrc_query"] = q
            return httpx.Response(200, json={"recordings": [
                _rec("m", "The Less I Know the Better", "Tame Impala", 217000)]})
        return httpx.Response(200, json={"recordings": []})

    async with _client(handler) as c:
        seed = await MusicBrainzClient(c, limiter=no_pace).canonicalize(
            "The Less I Know the Better", "Tame Impala", isrc="au-um7-15-00303", target_duration_ms=217_000)

    assert seen["isrc_query"] == "isrc:AUUM71500303"  # hyphens stripped, upper-cased
    assert seed is not None and "AUUM71500303" in seed.isrcs


async def test_no_duration_target_uses_string_match(no_pace: AsyncLimiter) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params["query"].startswith("isrc:"):
            return httpx.Response(200, json={"recordings": []})
        return httpx.Response(200, json={"recordings": [
            _rec("a", "Take Five", "The Dave Brubeck Quartet", 324000),
            _rec("b", "Blue Rondo a la Turk", "The Dave Brubeck Quartet", 400000),  # different song → filtered
        ]})

    async with _client(handler) as c:
        seed = await MusicBrainzClient(c, limiter=no_pace).canonicalize(
            "Take Five", "The Dave Brubeck Quartet", isrc=None, target_duration_ms=None)

    assert seed is not None and seed.mbid == "a"


async def test_query_strings_carried_onto_seed(no_pace: AsyncLimiter) -> None:
    # The seed carries the *query* strings (user intent), not MB's canonical title.
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params["query"].startswith("isrc:"):
            return httpx.Response(200, json={"recordings": [_rec("m", "HUMBLE", "Kendrick Lamar", 177000)]})
        return httpx.Response(200, json={"recordings": []})

    async with _client(handler) as c:
        seed = await MusicBrainzClient(c, limiter=no_pace).canonicalize(
            "HUMBLE.", "Kendrick Lamar", isrc="USUM71703085", target_duration_ms=177_000)

    assert seed is not None
    assert seed.title == "HUMBLE." and seed.artist == "Kendrick Lamar"
