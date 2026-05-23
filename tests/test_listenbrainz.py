"""ListenBrainzClient adapter tests — offline, via httpx.MockTransport.

Covers the two-call flow (recording-search → similar-recordings), canonical-MBID
resolution plus its seed-similarity gate, candidate parsing (1-based dense ranks,
attached MBID/score), the seed-drop and unusable-row filters, the empty paths
(unresolved seed; resolved but no similar set), and that HTTP errors propagate.
"""
from __future__ import annotations

import httpx
import pytest

from doppel.config import LISTENBRAINZ_ALGORITHM
from doppel.sources.errors import SourceResponseError
from doppel.sources.listenbrainz import ListenBrainzClient

SEED_MBID = "398bf241-7d57-4993-860b-1f9ef496c97f"


def _search_row(name: str, artist: str, mbid: str) -> dict:
    return {"recording_name": name, "artist_credit_name": artist, "recording_mbid": mbid}


def _similar_row(name: str, artist: str, mbid: str, score: int) -> dict:
    return {"recording_name": name, "artist_credit_name": artist,
            "recording_mbid": mbid, "score": score, "reference_mbid": SEED_MBID}


def _lb(handler) -> ListenBrainzClient:
    # polite_delay_s=0 keeps the suite fast (no real inter-call sleep).
    return ListenBrainzClient(httpx.AsyncClient(transport=httpx.MockTransport(handler)), polite_delay_s=0)


async def test_resolves_then_returns_ranked_candidates() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/recording-search/json":
            assert request.url.params["query"] == "HUMBLE. Kendrick Lamar"
            return httpx.Response(200, json=[_search_row("HUMBLE.", "Kendrick Lamar", SEED_MBID)])
        if request.url.path == "/similar-recordings/json":
            assert request.url.params["recording_mbids"] == SEED_MBID
            assert request.url.params["algorithm"] == LISTENBRAINZ_ALGORITHM
            return httpx.Response(200, json=[
                _similar_row("Mask Off", "Future", "09a613f7-5f9d-414a-9c4a-5c318dfe6b9a", 785),
                _similar_row("XO TOUR Llif3", "Lil Uzi Vert", "82a56563-aa5f-4b8a-9c5b-fa193d9246c7", 768),
            ])
        return httpx.Response(404)

    cands = await _lb(handler).similar_candidates("HUMBLE.", "Kendrick Lamar")

    assert [(c.title, c.artist, c.rank) for c in cands] == [
        ("Mask Off", "Future", 1),
        ("XO TOUR Llif3", "Lil Uzi Vert", 2),
    ]
    assert all(c.source == "listenbrainz" for c in cands)
    assert cands[0].mbid == "09a613f7-5f9d-414a-9c4a-5c318dfe6b9a"
    assert cands[0].score == 785.0


async def test_unresolved_seed_returns_empty_and_skips_similar() -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path == "/recording-search/json":
            # a hit, but it's a different song → fails the seed-similarity gate
            return httpx.Response(200, json=[_search_row("Totally Other Song", "Nobody At All", "x")])
        return httpx.Response(200, json=[])

    cands = await _lb(handler).similar_candidates("HUMBLE.", "Kendrick Lamar")

    assert cands == []
    assert "/similar-recordings/json" not in paths  # never resolved → never queried


async def test_empty_recording_search_returns_empty() -> None:
    cands = await _lb(lambda r: httpx.Response(200, json=[])).similar_candidates("X", "Y")
    assert cands == []


async def test_resolved_but_no_similar_set_returns_empty() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/recording-search/json":
            return httpx.Response(200, json=[_search_row("Take Five", "The Dave Brubeck Quartet", SEED_MBID)])
        return httpx.Response(200, json=[])  # resolved, but thin data → no similar recordings

    cands = await _lb(handler).similar_candidates("Take Five", "The Dave Brubeck Quartet")
    assert cands == []


async def test_drops_seed_and_unusable_rows_with_dense_ranks() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/recording-search/json":
            return httpx.Response(200, json=[_search_row("HUMBLE.", "Kendrick Lamar", SEED_MBID)])
        return httpx.Response(200, json=[
            _similar_row("Mask Off", "Future", "mbid-1", 785),
            _similar_row("HUMBLE.", "Kendrick Lamar", SEED_MBID, 999),  # the seed itself → drop
            {"recording_name": "", "artist_credit_name": "Ghost", "recording_mbid": "mbid-x", "score": 5},  # no title
            _similar_row("DNA.", "Kendrick Lamar", "mbid-2", 700),
        ])

    cands = await _lb(handler).similar_candidates("HUMBLE.", "Kendrick Lamar")

    # seed + the title-less row removed; survivors renumbered 1..N (no rank gaps)
    assert [(c.title, c.rank) for c in cands] == [("Mask Off", 1), ("DNA.", 2)]


async def test_skips_non_matching_recording_search_rows() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/recording-search/json":
            return httpx.Response(200, json=[
                _search_row("HUMBLE.", "Some Tribute Band", "wrong-mbid"),  # right title, wrong artist → skip
                _search_row("HUMBLE.", "Kendrick Lamar", SEED_MBID),        # the correct row
            ])
        assert request.url.params["recording_mbids"] == SEED_MBID  # resolved to the correct row's MBID
        return httpx.Response(200, json=[_similar_row("Mask Off", "Future", "mbid-1", 785)])

    cands = await _lb(handler).similar_candidates("HUMBLE.", "Kendrick Lamar")
    assert len(cands) == 1 and cands[0].title == "Mask Off"


async def test_http_error_propagates() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/recording-search/json":
            return httpx.Response(200, json=[_search_row("HUMBLE.", "Kendrick Lamar", SEED_MBID)])
        return httpx.Response(503)  # similar-recordings upstream error

    with pytest.raises(httpx.HTTPStatusError):
        await _lb(handler).similar_candidates("HUMBLE.", "Kendrick Lamar")


async def test_does_not_anchor_on_title_variant() -> None:
    # token_set scores "HUMBLE." vs "HUMBLE. (Live)" at 100; the exact-title gate must reject
    # the live row and anchor on the real recording (Codex adversarial finding #1).
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/recording-search/json":
            return httpx.Response(200, json=[
                _search_row("HUMBLE. (Live)", "Kendrick Lamar", "live-mbid"),  # variant → reject
                _search_row("HUMBLE.", "Kendrick Lamar", SEED_MBID),           # the studio cut
            ])
        assert request.url.params["recording_mbids"] == SEED_MBID  # anchored on the studio cut
        return httpx.Response(200, json=[_similar_row("Mask Off", "Future", "m1", 785)])

    cands = await _lb(handler).similar_candidates("HUMBLE.", "Kendrick Lamar")
    assert len(cands) == 1 and cands[0].title == "Mask Off"


async def test_does_not_anchor_on_cover_artist() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/recording-search/json":
            return httpx.Response(200, json=[
                _search_row("HUMBLE.", "Kendrick Lamar Karaoke", "karaoke-mbid"),  # cover marker → reject
                _search_row("HUMBLE.", "Kendrick Lamar", SEED_MBID),
            ])
        assert request.url.params["recording_mbids"] == SEED_MBID
        return httpx.Response(200, json=[_similar_row("Mask Off", "Future", "m1", 785)])

    cands = await _lb(handler).similar_candidates("HUMBLE.", "Kendrick Lamar")
    assert len(cands) == 1 and cands[0].title == "Mask Off"


async def test_unresolved_when_only_a_variant_is_available() -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path == "/recording-search/json":
            return httpx.Response(200, json=[_search_row("HUMBLE. (Live)", "Kendrick Lamar", "live-mbid")])
        return httpx.Response(200, json=[])

    cands = await _lb(handler).similar_candidates("HUMBLE.", "Kendrick Lamar")
    assert cands == []
    assert "/similar-recordings/json" not in paths  # no exact-title anchor → no similar query


async def test_malformed_recording_search_body_raises_source_error() -> None:
    # A 200 with a non-JSON body (the experimental Labs endpoint can do this) is an outage,
    # not no-data → raises so the aggregator records it as degraded, not a clean empty.
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>503 Service Unavailable</html>")

    with pytest.raises(SourceResponseError):
        await _lb(handler).similar_candidates("HUMBLE.", "Kendrick Lamar")


async def test_non_list_similar_body_raises_source_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/recording-search/json":
            return httpx.Response(200, json=[_search_row("HUMBLE.", "Kendrick Lamar", SEED_MBID)])
        return httpx.Response(200, json={"error": "unexpected object"})  # a dict, not a list

    with pytest.raises(SourceResponseError):
        await _lb(handler).similar_candidates("HUMBLE.", "Kendrick Lamar")


async def test_shape_drift_similar_rows_are_skipped() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/recording-search/json":
            return httpx.Response(200, json=[_search_row("HUMBLE.", "Kendrick Lamar", SEED_MBID)])
        return httpx.Response(200, json=[
            {"recording_name": {"x": "dict"}, "artist_credit_name": "X", "recording_mbid": "m0", "score": 1},
            _similar_row("Mask Off", "Future", "m1", 785),
        ])

    cands = await _lb(handler).similar_candidates("HUMBLE.", "Kendrick Lamar")
    assert [c.title for c in cands] == ["Mask Off"]  # non-string title skipped, no crash
