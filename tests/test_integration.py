"""Live end-to-end resolve against real Deezer + MusicBrainz.

Skipped unless ``--run-integration`` is passed (see conftest). One test, one
shared client + MB limiter, seeds resolved sequentially so the ~1 req/sec MB
pacing holds globally. This is the real proof the matcher resolves known tracks;
the offline suites cover the logic.
"""
from __future__ import annotations

import httpx
import pytest

from doppel.aggregation.aggregator import aggregate
from doppel.aggregation.candidates import normalized_key
from doppel.config import HTTP_TIMEOUT_S, LASTFM_API_KEY, USER_AGENT
from doppel.matching.resolver import ResolveStatus, resolve
from doppel.sources.deezer import DeezerClient
from doppel.sources.lastfm import LastFmClient
from doppel.sources.listenbrainz import ListenBrainzClient
from doppel.sources.musicbrainz import MusicBrainzClient

SEEDS = [
    ("Blinding Lights", "The Weeknd"),
    ("HUMBLE.", "Kendrick Lamar"),
    ("The Less I Know the Better", "Tame Impala"),
    ("One More Time", "Daft Punk"),
    ("Take Five", "The Dave Brubeck Quartet"),
]


@pytest.mark.integration
async def test_resolve_real_seeds() -> None:
    async with httpx.AsyncClient(
        http2=True, timeout=HTTP_TIMEOUT_S, follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    ) as client:
        deezer = DeezerClient(client)
        musicbrainz = MusicBrainzClient(client)  # shared limiter paces all MB calls
        for title, artist in SEEDS:
            result = await resolve(deezer, musicbrainz, title, artist)
            assert result.status is ResolveStatus.FOUND, f"{title!r}: {result.status.value} ({result.detail})"
            assert result.confidence >= 0.75, f"{title!r}: confidence {result.confidence:.3f}"
            assert result.mbid is not None, f"{title!r}: no MBID"
            assert result.preview_url and result.preview_url.startswith("http"), f"{title!r}: no preview URL"


@pytest.mark.integration
async def test_lastfm_real_similar() -> None:
    """Direct Last.fm hit — surfaces a bad/missing key loudly (no aggregator degradation)."""
    if not LASTFM_API_KEY:
        pytest.skip("LASTFM_API_KEY not set — set it to validate the Last.fm source live")
    async with httpx.AsyncClient(
        http2=True, timeout=HTTP_TIMEOUT_S, follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    ) as client:
        cands = await LastFmClient(client).similar_candidates("HUMBLE.", "Kendrick Lamar")
    assert cands, "Last.fm returned no similar tracks for a well-known seed"
    assert all(c.source == "lastfm" for c in cands)
    assert cands[0].rank == 1 and cands[-1].rank == len(cands)  # dense 1-based ranks


@pytest.mark.integration
async def test_aggregate_real_seed() -> None:
    """End-to-end cultural aggregation against the live sources (Last.fm joins if a key is set)."""
    async with httpx.AsyncClient(
        http2=True, timeout=HTTP_TIMEOUT_S, follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    ) as client:
        sources = [ListenBrainzClient(client)]
        if LASTFM_API_KEY:
            sources.append(LastFmClient(client))
        result = await aggregate(sources, "HUMBLE.", "Kendrick Lamar")

    assert result.candidates, "no cultural candidates for a well-known seed"
    seed_key = normalized_key("HUMBLE.", "Kendrick Lamar")
    assert all(normalized_key(c.title, c.artist) != seed_key for c in result.candidates), "seed leaked into results"
    scores = [c.cultural_score for c in result.candidates]
    assert scores == sorted(scores, reverse=True), "candidates not in descending RRF order"
    if LASTFM_API_KEY:
        assert any("lastfm" in c.sources for c in result.candidates), "Last.fm contributed nothing despite a key"
