"""MusicBrainz source adapter — canonicalize (title, artist) → recording MBID.

The literal "MB search top-hit" is unreliable: MB's highest-text-score recording
for a title is frequently a *different version* than the one a provider serves
(radio edit vs album cut, a 9-minute live take vs the 5-minute studio cut). So
canonicalization is provider-informed (validated on real data):

  * ISRC-anchored — find the MB recording carrying the Deezer track's ISRC. An
    ISRC names exactly one recording, so this lands the right version directly,
    even when MB's text-relevance top hit (and its ISRC list) would not.
  * nearest-duration fallback — among the title/artist cluster recordings that
    string-match the query, pick the one whose length is nearest the provider's
    full-track duration.

Calls are paced with an aiolimiter to honor MB's ~1 req/sec hard limit, and every
request carries the descriptive User-Agent MB requires. See DECISIONS.md.
"""
from __future__ import annotations

import httpx
from aiolimiter import AsyncLimiter
from rapidfuzz import fuzz
from rapidfuzz.utils import default_process

from doppel.config import (
    MUSICBRAINZ_API,
    MUSICBRAINZ_CLUSTER_LIMIT,
    MUSICBRAINZ_MIN_INTERVAL_S,
    SEARCH_RELEVANCE_MIN,
    USER_AGENT,
)
from doppel.matching.verify import SeedRecording


def _artist_credit_name(rec: dict) -> str:
    return (rec.get("artist-credit") or [{}])[0].get("name", "")


def _clean_isrc(isrc: str) -> str:
    return "".join(ch for ch in isrc if ch.isalnum()).upper()


def _escape_lucene_phrase(text: str) -> str:
    """Escape the two chars special inside a quoted Lucene phrase: ``\\`` and ``"``."""
    return text.replace("\\", "\\\\").replace('"', '\\"')


def _title_sim(title: str, rec: dict) -> float:
    return fuzz.token_set_ratio(title, rec.get("title", ""), processor=default_process)


def _strings_match(title: str, artist: str, rec: dict) -> bool:
    return (
        _title_sim(title, rec) >= SEARCH_RELEVANCE_MIN
        and fuzz.token_set_ratio(artist, _artist_credit_name(rec), processor=default_process) >= SEARCH_RELEVANCE_MIN
    )


class MusicBrainzClient:
    """Async MusicBrainz adapter; paces itself to MB's ~1 req/sec limit."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        limiter: AsyncLimiter | None = None,
        cluster_limit: int = MUSICBRAINZ_CLUSTER_LIMIT,
    ) -> None:
        self._client = client
        # One shared limiter paces all MB calls across the app: 1 request / interval.
        self._limiter = limiter or AsyncLimiter(1, MUSICBRAINZ_MIN_INTERVAL_S)
        self._cluster_limit = cluster_limit

    async def canonicalize(
        self,
        title: str,
        artist: str,
        *,
        isrc: str | None = None,
        target_duration_ms: int | None = None,
    ) -> SeedRecording | None:
        """Resolve a candidate to a recording-level :class:`SeedRecording`, or ``None``.

        ``title``/``artist`` are the *query* strings (carried onto the seed so
        verification scores the provider track against the user's intent). The
        MBID, duration, and matched ISRC come from MusicBrainz.
        """
        rec: dict | None = None
        matched_isrc: str | None = None

        # Path A — ISRC-anchored: the exact recording for the provider's ISRC.
        if isrc:
            recs = await self._search(f"isrc:{_clean_isrc(isrc)}", limit=5)
            if recs:
                rec, matched_isrc = recs[0], _clean_isrc(isrc)

        # Path B — nearest-duration within the string-matching title/artist cluster.
        if rec is None:
            query = f'recording:"{_escape_lucene_phrase(title)}" AND artist:"{_escape_lucene_phrase(artist)}"'
            cluster = await self._search(query, limit=self._cluster_limit)
            candidates = [r for r in cluster if r.get("length") and _strings_match(title, artist, r)]
            if candidates and target_duration_ms:
                rec = min(candidates, key=lambda r: abs(r["length"] - target_duration_ms))
            elif candidates:
                rec = max(candidates, key=lambda r: _title_sim(title, r))

        if rec is None:
            return None
        return SeedRecording(
            title=title,
            artist=artist,
            duration_ms=rec.get("length"),
            isrcs=frozenset({matched_isrc}) if matched_isrc else frozenset(),
            mbid=rec.get("id"),
        )

    async def _search(self, query: str, *, limit: int) -> list[dict]:
        """Paced MB recording search; HTTP errors propagate to the caller."""
        async with self._limiter:
            r = await self._client.get(
                f"{MUSICBRAINZ_API}/recording",
                params={"query": query, "fmt": "json", "limit": limit},
                headers={"User-Agent": USER_AGENT},
            )
        r.raise_for_status()
        return r.json().get("recordings", [])
