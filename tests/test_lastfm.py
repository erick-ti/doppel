"""LastFmClient adapter tests — offline, via httpx.MockTransport.

Covers the track.getSimilar parse path (name/artist/mbid/match → Candidate, 1-based
ranks), the single-result dict-not-list quirk, missing-key degradation (no request
made), not-found (error 6) → empty, a non-not-found API error → LastFmError, empty
sets, and unusable-row skipping.
"""
from __future__ import annotations

import traceback

import httpx
import pytest

from doppel.sources.errors import SourceResponseError
from doppel.sources.lastfm import LastFmClient, LastFmError


def _track(name: str, artist: str, match: float, mbid: str = "") -> dict:
    # Last.fm serializes `match` as a string in JSON ("1", "0.83").
    return {"name": name, "artist": {"name": artist}, "match": str(match), "mbid": mbid}


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _lf(handler, *, api_key: str | None = "k") -> LastFmClient:
    return LastFmClient(_client(handler), api_key=api_key)


async def test_parses_similar_into_ranked_candidates() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["method"] == "track.getsimilar"
        assert request.url.params["api_key"] == "k"
        assert request.url.params["autocorrect"] == "1"
        return httpx.Response(200, json={"similartracks": {"track": [
            _track("Mask Off", "Future", 1.0, "09a613f7-5f9d-414a-9c4a-5c318dfe6b9a"),
            _track("XO TOUR Llif3", "Lil Uzi Vert", 0.83),  # no mbid
        ]}})

    cands = await _lf(handler).similar_candidates("HUMBLE.", "Kendrick Lamar")

    assert [(c.title, c.artist, c.rank) for c in cands] == [
        ("Mask Off", "Future", 1),
        ("XO TOUR Llif3", "Lil Uzi Vert", 2),
    ]
    assert all(c.source == "lastfm" for c in cands)
    assert cands[0].mbid == "09a613f7-5f9d-414a-9c4a-5c318dfe6b9a" and cands[0].score == 1.0
    assert cands[1].mbid is None and cands[1].score == 0.83


async def test_single_result_dict_is_normalized_to_list() -> None:
    # Last.fm returns a bare object (not a list) when there's exactly one similar track.
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"similartracks": {"track": _track("Only One", "Solo", 0.5)}})

    cands = await _lf(handler).similar_candidates("X", "Y")
    assert len(cands) == 1 and cands[0].title == "Only One" and cands[0].rank == 1


async def test_no_api_key_returns_empty_without_request() -> None:
    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json={})

    cands = await _lf(handler, api_key=None).similar_candidates("X", "Y")
    assert cands == []
    assert called is False  # degraded mode short-circuits before any HTTP call


async def test_track_not_found_returns_empty() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"error": 6, "message": "Track not found"})

    assert await _lf(handler).similar_candidates("Nope", "Nobody") == []


async def test_invalid_key_raises_lastfm_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"error": 10, "message": "Invalid API key"})

    with pytest.raises(LastFmError) as exc:
        await _lf(handler).similar_candidates("X", "Y")
    assert exc.value.code == 10


async def test_empty_similar_set_returns_empty() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"similartracks": {"track": []}})

    assert await _lf(handler).similar_candidates("X", "Y") == []


async def test_skips_rows_missing_name_or_artist() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"similartracks": {"track": [
            {"name": "", "artist": {"name": "Ghost"}, "match": "0.9"},  # no name → skip
            _track("Good Track", "Good Artist", 0.7),
            {"name": "No Artist", "artist": {}, "match": "0.6"},        # no artist → skip
        ]}})

    cands = await _lf(handler).similar_candidates("X", "Y")
    assert [(c.title, c.rank) for c in cands] == [("Good Track", 1)]


async def test_http_error_surfaces_sanitized_status_not_url() -> None:
    # A non-2xx is re-raised as a degradable SourceError carrying only the status — never httpx's
    # URL-bearing message, which embeds our api_key query param (it would leak via failed_sources).
    with pytest.raises(SourceResponseError) as ei:
        await _lf(lambda r: httpx.Response(503)).similar_candidates("X", "Y")
    msg = str(ei.value)
    assert "503" in msg
    assert "api_key" not in msg and "audioscrobbler" not in msg


async def test_http_error_does_not_chain_the_url_bearing_cause() -> None:
    # `from None` must drop the HTTPStatusError cause — otherwise a full traceback of the sanitized
    # error would still print the api_key-bearing request URL via the exception chain.
    with pytest.raises(SourceResponseError) as ei:
        await _lf(lambda r: httpx.Response(403)).similar_candidates("X", "Y")
    exc = ei.value
    assert exc.__cause__ is None and exc.__suppress_context__ is True
    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    assert "api_key" not in tb and "audioscrobbler" not in tb


async def test_malformed_json_body_raises_source_error() -> None:
    # A 200 with a non-JSON body is an outage, not no-data → raises so the aggregator
    # records it as degraded rather than a clean empty.
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>gateway error</html>")

    with pytest.raises(SourceResponseError):
        await _lf(handler).similar_candidates("X", "Y")


async def test_non_dict_body_raises_source_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=["unexpected", "list"])  # a list, not an object

    with pytest.raises(SourceResponseError):
        await _lf(handler).similar_candidates("X", "Y")


async def test_shape_drift_rows_are_skipped() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"similartracks": {"track": [
            _track("Good Track", "Good Artist", 0.9),
            {"name": "Bad", "artist": "not-a-dict", "match": "0.8"},        # artist not a dict → skip
            {"name": {"x": "dict"}, "artist": {"name": "Y"}, "match": "0.7"},  # non-str name → skip
        ]}})

    cands = await _lf(handler).similar_candidates("X", "Y")
    assert [c.title for c in cands] == ["Good Track"]
