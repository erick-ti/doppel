"""Live end-to-end resolve against real Deezer + MusicBrainz.

Skipped unless ``--run-integration`` is passed (see conftest). One test, one
shared client + MB limiter, seeds resolved sequentially so the ~1 req/sec MB
pacing holds globally. This is the real proof the matcher resolves known tracks;
the offline suites cover the logic.
"""
from __future__ import annotations

import httpx
import pytest

from doppel.config import HTTP_TIMEOUT_S, USER_AGENT
from doppel.matching.resolver import ResolveStatus, resolve
from doppel.sources.deezer import DeezerClient
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
