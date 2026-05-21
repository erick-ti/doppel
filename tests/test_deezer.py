"""DeezerClient adapter tests — offline, via httpx.MockTransport.

Exercises the real request/parse paths: relevance gating against the query, the
advanced→plain query fallback, seconds→milliseconds duration conversion, and
ISRC enrichment via /track/{id} (including its failure and disabled modes).
"""
from __future__ import annotations

import httpx

from doppel.sources.deezer import DeezerClient

PREVIEW = "https://cdns-preview.deezer.com/stream/x.mp3"


def _hit(track_id: int, title: str, artist: str, duration: int, preview: str = PREVIEW) -> dict:
    return {"id": track_id, "title": title, "artist": {"name": artist},
            "duration": duration, "preview": preview}


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_find_track_returns_enriched_candidate() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/search":
            return httpx.Response(200, json={"data": [_hit(916424, "Blinding Lights", "The Weeknd", 200)]})
        if request.url.path == "/track/916424":
            return httpx.Response(200, json={"id": 916424, "title": "Blinding Lights",
                                             "artist": {"name": "The Weeknd"}, "duration": 200,
                                             "isrc": "USUG11904206", "preview": PREVIEW})
        return httpx.Response(404, json={"error": {"code": 800}})

    async with _client(handler) as c:
        cand = await DeezerClient(c).find_track("Blinding Lights", "The Weeknd")

    assert cand is not None
    assert cand.title == "Blinding Lights"
    assert cand.artist == "The Weeknd"
    assert cand.provider_track_duration_ms == 200_000  # seconds → milliseconds
    assert cand.isrc == "USUG11904206"
    assert cand.preview_url == PREVIEW
    assert cand.provider_track_id == 916424


async def test_irrelevant_top_hit_is_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [_hit(1, "Totally Different Song", "Some Other Artist", 180)]})

    async with _client(handler) as c:
        assert await DeezerClient(c).find_track("Blinding Lights", "The Weeknd") is None


async def test_falls_back_to_plain_query() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/search":
            if 'track:"' in request.url.params["q"]:  # advanced query → empty
                return httpx.Response(200, json={"data": []})
            return httpx.Response(200, json={"data": [_hit(5, "HUMBLE.", "Kendrick Lamar", 177)]})
        return httpx.Response(200, json={"id": 5, "title": "HUMBLE.", "artist": {"name": "Kendrick Lamar"},
                                         "duration": 177, "isrc": "USUM71703085", "preview": PREVIEW})

    async with _client(handler) as c:
        cand = await DeezerClient(c).find_track("HUMBLE.", "Kendrick Lamar")

    assert cand is not None and cand.isrc == "USUM71703085"


async def test_hit_without_preview_is_skipped() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/search":
            return httpx.Response(200, json={"data": [
                _hit(1, "Blinding Lights", "The Weeknd", 200, preview=""),       # no preview → skip
                _hit(2, "Blinding Lights", "The Weeknd", 200, preview=PREVIEW),  # usable
            ]})
        return httpx.Response(200, json={"id": 2, "title": "Blinding Lights", "artist": {"name": "The Weeknd"},
                                         "duration": 200, "isrc": "USUG11904206", "preview": PREVIEW})

    async with _client(handler) as c:
        cand = await DeezerClient(c).find_track("Blinding Lights", "The Weeknd")

    assert cand is not None and cand.provider_track_id == 2


async def test_no_results_returns_none() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": []})

    async with _client(handler) as c:
        assert await DeezerClient(c).find_track("Nonexistent Track", "Nobody At All") is None


async def test_inband_error_returns_none() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"error": {"type": "Exception", "code": 4, "message": "Quota exceeded"}})

    async with _client(handler) as c:
        assert await DeezerClient(c).find_track("X", "Y") is None


async def test_isrc_disabled_skips_enrichment() -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path == "/search":
            return httpx.Response(200, json={"data": [_hit(9, "One More Time", "Daft Punk", 320)]})
        return httpx.Response(200, json={"id": 9, "title": "One More Time", "artist": {"name": "Daft Punk"},
                                         "duration": 320, "isrc": "GBDUW0000053", "preview": PREVIEW})

    async with _client(handler) as c:
        cand = await DeezerClient(c, isrc_enabled=False).find_track("One More Time", "Daft Punk")

    assert cand is not None
    assert cand.isrc is None
    assert cand.provider_track_duration_ms == 320_000  # taken from the search hit
    assert not any(p.startswith("/track/") for p in paths)  # no enrichment call made


async def test_isrc_enrichment_failure_still_returns_candidate() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/search":
            return httpx.Response(200, json={"data": [_hit(7, "Take Five", "The Dave Brubeck Quartet", 324)]})
        return httpx.Response(200, json={"error": {"code": 800, "message": "no data"}})  # /track fails in-band

    async with _client(handler) as c:
        cand = await DeezerClient(c).find_track("Take Five", "The Dave Brubeck Quartet")

    assert cand is not None
    assert cand.isrc is None
    assert cand.provider_track_duration_ms == 324_000  # falls back to the search-hit duration
    assert cand.preview_url == PREVIEW
