"""Deezer source adapter — find a track, its full duration, preview, and ISRC.

Deezer is the matcher's reliable anchor: ``/search`` returns the full-track
duration (seconds) and a 30 s preview URL, and ``/track/{id}`` adds the ISRC that
search omits. A relevance gate against the *query* strings ensures a wrong-song
hit never anchors canonicalization downstream.

Preview audio is never fetched or persisted here — only the preview URL is
carried. Audio is streamed and discarded at embed time (ephemeral-audio rule).
"""
from __future__ import annotations

import httpx
from rapidfuzz import fuzz
from rapidfuzz.utils import default_process

from doppel.config import DEEZER_API, DEEZER_ISRC_ENABLED, SEARCH_RELEVANCE_MIN
from doppel.matching.verify import ProviderTrack


def _hit_artist(hit: dict) -> str:
    return (hit.get("artist") or {}).get("name", "")


def _relevant(query_title: str, query_artist: str, hit: dict) -> bool:
    """True if a search hit matches the query well enough to be the right song."""
    title_sim = fuzz.token_set_ratio(query_title, hit.get("title", ""), processor=default_process)
    artist_sim = fuzz.token_set_ratio(query_artist, _hit_artist(hit), processor=default_process)
    return title_sim >= SEARCH_RELEVANCE_MIN and artist_sim >= SEARCH_RELEVANCE_MIN


class DeezerClient:
    """Async Deezer adapter over a shared ``httpx.AsyncClient``."""

    def __init__(self, client: httpx.AsyncClient, *, isrc_enabled: bool = DEEZER_ISRC_ENABLED) -> None:
        self._client = client
        self._isrc_enabled = isrc_enabled

    async def find_track(self, title: str, artist: str) -> ProviderTrack | None:
        """Return the best relevant track that has a preview, or ``None``.

        Tries a field-scoped query first, then a plain one; within each, takes the
        first hit that has a preview and clears the relevance gate.
        """
        for query in (f'artist:"{artist}" track:"{title}"', f"{artist} {title}"):
            data = await self._search(query)
            hit = next((h for h in data if h.get("preview") and _relevant(title, artist, h)), None)
            if hit is not None:
                return await self._build(hit)
        return None

    async def _search(self, query: str) -> list[dict]:
        """Run a Deezer search; HTTP errors propagate, empty/in-band errors → []."""
        r = await self._client.get(f"{DEEZER_API}/search", params={"q": query})
        r.raise_for_status()
        body = r.json()
        if not isinstance(body, dict) or body.get("error"):
            return []
        data = body.get("data")
        return data if isinstance(data, list) else []

    async def _get_track(self, track_id: int) -> dict | None:
        r = await self._client.get(f"{DEEZER_API}/track/{track_id}")
        r.raise_for_status()
        body = r.json()
        if isinstance(body, dict) and not body.get("error"):
            return body
        return None

    async def _build(self, hit: dict) -> ProviderTrack:
        track_id = hit.get("id")
        duration_s = hit.get("duration")
        isrc: str | None = None
        # Search omits the ISRC; the documented /track/{id} carries it (and the
        # authoritative duration). Skipped entirely when ISRC anchoring is off.
        if self._isrc_enabled and track_id is not None:
            full = await self._get_track(track_id)
            if full:
                isrc = full.get("isrc") or None
                duration_s = full.get("duration") or duration_s
        return ProviderTrack(
            title=hit.get("title", ""),
            artist=_hit_artist(hit),
            # Deezer reports duration in SECONDS; verify_match compares milliseconds.
            provider_track_duration_ms=int(duration_s) * 1000 if duration_s else None,
            isrc=isrc,
            preview_url=hit.get("preview") or None,
            provider_track_id=track_id,
        )
