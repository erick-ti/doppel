"""MusicBrainzClient canonicalization tests — offline, via httpx.MockTransport.

Covers ISRC-anchored selection, the nearest-duration fallback, ISRC normalization,
query-string carry-through, the ISRC-consistency guards (duration / strings /
missing-length), and the artist-identity (MBID) check that rejects tributes while
accepting collaborations. A fast limiter is injected so the ~1 req/sec pacing
doesn't slow the suite.
"""
from __future__ import annotations

import re

import httpx
import pytest
from aiolimiter import AsyncLimiter

from doppel.sources.musicbrainz import MusicBrainzClient

ARTIST_MBID = "artist-mbid-query"  # the MBID the query artist resolves to


@pytest.fixture
def no_pace() -> AsyncLimiter:
    return AsyncLimiter(10**6, 1)  # effectively unthrottled, for tests only


def _rec(mbid: str, title: str, artist: str, length: int | None, *, artist_mbid: str | None = ARTIST_MBID) -> dict:
    credit: dict = {"name": artist}
    if artist_mbid:
        credit["artist"] = {"id": artist_mbid, "name": artist}
    rec: dict = {"id": mbid, "title": title, "artist-credit": [credit]}
    if length is not None:
        rec["length"] = length
    return rec


def _artist_name_from_query(query: str) -> str:
    m = re.search(r'artist:"([^"]*)"', query)
    return m.group(1) if m else ""


def _handler(*, isrc_recs=(), cluster_recs=(), artist_mbid: str | None = ARTIST_MBID):
    """Path-aware MB mock: ``/artist`` resolves the query artist to ``artist_mbid`` (or
    nothing, to exercise the degraded path); ``/recording`` serves the isrc vs cluster
    results based on the query."""
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/artist"):
            name = _artist_name_from_query(request.url.params["query"])
            artists = [{"id": artist_mbid, "name": name, "score": 100}] if artist_mbid else []
            return httpx.Response(200, json={"artists": artists})
        recs = isrc_recs if request.url.params["query"].startswith("isrc:") else cluster_recs
        return httpx.Response(200, json={"recordings": list(recs)})
    return handle


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_canonicalize_isrc_anchored(no_pace: AsyncLimiter) -> None:
    handler = _handler(isrc_recs=[_rec("mbid-isrc", "Blinding Lights", "The Weeknd", 200046)])
    async with _client(handler) as c:
        seed = await MusicBrainzClient(c, limiter=no_pace).canonicalize(
            "Blinding Lights", "The Weeknd", isrc="USUG11904206", target_duration_ms=200_000)

    assert seed is not None
    assert seed.mbid == "mbid-isrc"
    assert seed.duration_ms == 200046
    assert "USUG11904206" in seed.isrcs
    assert seed.title == "Blinding Lights" and seed.artist == "The Weeknd"


async def test_canonicalize_nearest_duration(no_pace: AsyncLimiter) -> None:
    handler = _handler(cluster_recs=[
        _rec("long", "Blinding Lights", "The Weeknd", 262000),
        _rec("right", "Blinding Lights", "The Weeknd", 200000),
        _rec("edit", "Blinding Lights", "The Weeknd", 215000),
    ])
    async with _client(handler) as c:
        seed = await MusicBrainzClient(c, limiter=no_pace).canonicalize(
            "Blinding Lights", "The Weeknd", isrc=None, target_duration_ms=200_000)

    assert seed is not None and seed.mbid == "right" and seed.duration_ms == 200000
    assert not seed.isrcs  # nearest-duration path carries no ISRC anchor


async def test_nearest_duration_filters_wrong_strings(no_pace: AsyncLimiter) -> None:
    # A same-duration but wrong-title recording must be filtered out before the
    # nearest-duration pick, even though its duration is closer.
    handler = _handler(cluster_recs=[
        _rec("wrong-song", "Save Your Tears", "The Weeknd", 200000),
        _rec("right", "Blinding Lights", "The Weeknd", 201000),
    ])
    async with _client(handler) as c:
        seed = await MusicBrainzClient(c, limiter=no_pace).canonicalize(
            "Blinding Lights", "The Weeknd", isrc=None, target_duration_ms=200_000)

    assert seed is not None and seed.mbid == "right"


async def test_no_recording_returns_none(no_pace: AsyncLimiter) -> None:
    async with _client(_handler()) as c:
        seed = await MusicBrainzClient(c, limiter=no_pace).canonicalize(
            "No Such Song", "Nobody", isrc="XX0000000000", target_duration_ms=200_000)

    assert seed is None


async def test_isrc_empty_falls_back_to_cluster(no_pace: AsyncLimiter) -> None:
    handler = _handler(isrc_recs=[], cluster_recs=[_rec("by-dur", "HUMBLE.", "Kendrick Lamar", 177000)])
    async with _client(handler) as c:
        seed = await MusicBrainzClient(c, limiter=no_pace).canonicalize(
            "HUMBLE.", "Kendrick Lamar", isrc="USUM71703085", target_duration_ms=177_000)

    assert seed is not None and seed.mbid == "by-dur"
    assert not seed.isrcs  # fell through to nearest-duration, so no ISRC anchor


async def test_isrc_hyphens_normalized(no_pace: AsyncLimiter) -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/artist"):
            name = _artist_name_from_query(request.url.params["query"])
            return httpx.Response(200, json={"artists": [{"id": ARTIST_MBID, "name": name, "score": 100}]})
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
    handler = _handler(cluster_recs=[
        _rec("a", "Take Five", "The Dave Brubeck Quartet", 324000),
        _rec("b", "Blue Rondo a la Turk", "The Dave Brubeck Quartet", 400000),  # different song → filtered
    ])
    async with _client(handler) as c:
        seed = await MusicBrainzClient(c, limiter=no_pace).canonicalize(
            "Take Five", "The Dave Brubeck Quartet", isrc=None, target_duration_ms=None)

    assert seed is not None and seed.mbid == "a"


async def test_query_strings_carried_onto_seed(no_pace: AsyncLimiter) -> None:
    # The seed carries the *query* strings (user intent), not MB's canonical title.
    handler = _handler(isrc_recs=[_rec("m", "HUMBLE", "Kendrick Lamar", 177000)])
    async with _client(handler) as c:
        seed = await MusicBrainzClient(c, limiter=no_pace).canonicalize(
            "HUMBLE.", "Kendrick Lamar", isrc="USUM71703085", target_duration_ms=177_000)

    assert seed is not None
    assert seed.title == "HUMBLE." and seed.artist == "Kendrick Lamar"


async def test_isrc_anchor_trusted_when_consistent(no_pace: AsyncLimiter) -> None:
    # ISRC search returns a recording whose strings + duration corroborate the
    # candidate → trusted, and the ISRC is carried onto the seed.
    handler = _handler(isrc_recs=[_rec("isrc-good", "Take Five", "The Dave Brubeck Quartet", 326000)])  # Δ2 s
    async with _client(handler) as c:
        seed = await MusicBrainzClient(c, limiter=no_pace).canonicalize(
            "Take Five", "The Dave Brubeck Quartet", isrc="USSM15900108", target_duration_ms=324_000)

    assert seed is not None and seed.mbid == "isrc-good"
    assert "USSM15900108" in seed.isrcs


async def test_isrc_anchor_rejected_on_duration_mismatch(no_pace: AsyncLimiter) -> None:
    # The ISRC anchors to a 9-minute recording but the candidate is ~5 min → not
    # trusted (would otherwise be circular self-proof); falls back to nearest-duration.
    handler = _handler(
        isrc_recs=[_rec("isrc-bad", "Take Five", "The Dave Brubeck Quartet", 540000)],  # Δ216 s
        cluster_recs=[_rec("by-dur", "Take Five", "The Dave Brubeck Quartet", 324000)],
    )
    async with _client(handler) as c:
        seed = await MusicBrainzClient(c, limiter=no_pace).canonicalize(
            "Take Five", "The Dave Brubeck Quartet", isrc="USSM15900108", target_duration_ms=324_000)

    assert seed is not None and seed.mbid == "by-dur"
    assert not seed.isrcs  # the inconsistent ISRC anchor was rejected


async def test_isrc_anchor_rejected_on_string_mismatch(no_pace: AsyncLimiter) -> None:
    # The ISRC anchors to a recording whose title/artist don't match the query → fall back.
    handler = _handler(
        isrc_recs=[_rec("isrc-wrong", "Some Other Song", "A Different Artist", 324000, artist_mbid="other-mbid")],
        cluster_recs=[_rec("by-dur", "Take Five", "The Dave Brubeck Quartet", 324000)],
    )
    async with _client(handler) as c:
        seed = await MusicBrainzClient(c, limiter=no_pace).canonicalize(
            "Take Five", "The Dave Brubeck Quartet", isrc="USSM15900108", target_duration_ms=324_000)

    assert seed is not None and seed.mbid == "by-dur"
    assert not seed.isrcs


async def test_isrc_anchor_rejected_when_mb_length_missing(no_pace: AsyncLimiter) -> None:
    # Provider gave a duration but the ISRC-anchored MB record has no length to
    # corroborate it → a string-only match must not carry the ISRC (it would become
    # circular 1.0 self-proof). Falls back to nearest-duration.
    handler = _handler(
        isrc_recs=[_rec("no-len", "Take Five", "The Dave Brubeck Quartet", None)],
        cluster_recs=[_rec("by-dur", "Take Five", "The Dave Brubeck Quartet", 324000)],
    )
    async with _client(handler) as c:
        seed = await MusicBrainzClient(c, limiter=no_pace).canonicalize(
            "Take Five", "The Dave Brubeck Quartet", isrc="USSM15900108", target_duration_ms=324_000)

    assert seed is not None and seed.mbid == "by-dur"
    assert not seed.isrcs  # uncorroborated ISRC anchor was rejected


# --------------------------------------------------------------------------- #
# Artist-identity (MBID) check — the non-string signal that separates tributes
# from collaborations (3rd adversarial review).
# --------------------------------------------------------------------------- #

async def test_tribute_recording_rejected_by_artist_mbid(no_pace: AsyncLimiter) -> None:
    # A tribute scores ~1.0 by name and has its own ISRC + matching duration, but its MB
    # recording is credited to a different artist MBID → rejected on both paths → None.
    tribute = _rec("trib", "Blinding Lights", "The Weeknd Experience", 200000, artist_mbid="tribute-mbid")
    async with _client(_handler(isrc_recs=[tribute], cluster_recs=[tribute])) as c:
        seed = await MusicBrainzClient(c, limiter=no_pace).canonicalize(
            "Blinding Lights", "The Weeknd", isrc="USTRIB000001", target_duration_ms=200_000)

    assert seed is None


async def test_collaboration_accepted_when_query_artist_credited(no_pace: AsyncLimiter) -> None:
    # A recording credited to several artists is accepted as long as the query artist's
    # MBID is among them (unlike a tribute, whose MBID differs).
    collab = {
        "id": "collab", "title": "We Found Love", "length": 215000,
        "artist-credit": [
            {"name": "Rihanna", "artist": {"id": ARTIST_MBID, "name": "Rihanna"}},
            {"name": "Calvin Harris", "artist": {"id": "calvin-mbid", "name": "Calvin Harris"}},
        ],
    }
    async with _client(_handler(isrc_recs=[collab])) as c:
        seed = await MusicBrainzClient(c, limiter=no_pace).canonicalize(
            "We Found Love", "Rihanna", isrc="USCOLLAB0001", target_duration_ms=215_000)

    assert seed is not None and seed.mbid == "collab"
    assert "USCOLLAB0001" in seed.isrcs


async def test_unresolvable_artist_degrades_to_string_check(no_pace: AsyncLimiter) -> None:
    # If the artist can't be resolved to an MBID, the MBID check abstains and the
    # string + duration checks still resolve the recording.
    rec = _rec("by-str", "Obscure Song", "Obscure Artist", 180000, artist_mbid=None)
    async with _client(_handler(isrc_recs=[rec], artist_mbid=None)) as c:
        seed = await MusicBrainzClient(c, limiter=no_pace).canonicalize(
            "Obscure Song", "Obscure Artist", isrc="USOBS0000001", target_duration_ms=180_000)

    assert seed is not None and seed.mbid == "by-str"
    assert "USOBS0000001" in seed.isrcs


async def test_collaboration_accepted_regardless_of_credit_order(no_pace: AsyncLimiter) -> None:
    # The query artist credited SECOND must still match — the MBID comparison is
    # order-independent, and the artist gate must not short-circuit on artist-credit[0].
    collab = {
        "id": "collab2", "title": "This Is What You Came For", "length": 222000,
        "artist-credit": [
            {"name": "Calvin Harris", "artist": {"id": "calvin-mbid", "name": "Calvin Harris"}},
            {"name": "Rihanna", "artist": {"id": ARTIST_MBID, "name": "Rihanna"}},
        ],
    }
    async with _client(_handler(isrc_recs=[collab])) as c:
        seed = await MusicBrainzClient(c, limiter=no_pace).canonicalize(
            "This Is What You Came For", "Rihanna", isrc="USCOLLAB0002", target_duration_ms=222_000)

    assert seed is not None and seed.mbid == "collab2"
    assert "USCOLLAB0002" in seed.isrcs


async def test_artist_lookup_failure_degrades_not_aborts(no_pace: AsyncLimiter) -> None:
    # A transient 5xx on the (non-essential) /artist lookup must not abort the resolve;
    # canonicalization proceeds via the title/duration/ISRC path (degraded, no MBID check).
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/artist"):
            return httpx.Response(503, text="upstream error")
        return httpx.Response(200, json={"recordings": [
            _rec("by-str", "Take Five", "The Dave Brubeck Quartet", 324000, artist_mbid=None)]})

    async with _client(handler) as c:
        seed = await MusicBrainzClient(c, limiter=no_pace).canonicalize(
            "Take Five", "The Dave Brubeck Quartet", isrc="USSM15900108", target_duration_ms=324_000)

    assert seed is not None and seed.mbid == "by-str"
    assert "USSM15900108" in seed.isrcs
