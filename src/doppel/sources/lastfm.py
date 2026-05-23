"""Last.fm source adapter — cultural candidates via track.getSimilar.

Last.fm's scrobble-powered similar tracks are the aggregator's primary cultural
recall layer (taste-based; strong on indie / rock / electronic deep cuts). Given a
seed ``(title, artist)``, returns the similar tracks Last.fm surfaces as ranked
:class:`~doppel.aggregation.candidates.Candidate` objects — each row carries name +
artist (plus a best-effort MBID and a 0..1 match score), so candidates are
``resolve()``-ready with no extra hop.

track.getSimilar is read-only, so only an API key is needed (no request signing).
The key comes from ``LASTFM_API_KEY``: when it is **unset** the adapter yields
nothing and the aggregator degrades to its other sources, but a configured-but-
**invalid** key raises :class:`LastFmError` so a misconfiguration is loud rather
than silently empty. A "track not found" is a normal empty (the seed simply has no
similar set); a malformed 200 body raises ``SourceResponseError`` (recorded as a
degraded source); transport / HTTP errors propagate — per-source degradation is
otherwise the aggregator's job.
"""
from __future__ import annotations

import httpx

from doppel.aggregation.candidates import Candidate
from doppel.config import LASTFM_API, LASTFM_API_KEY, LASTFM_SIMILAR_LIMIT
from doppel.sources.errors import SourceError, SourceResponseError

#: Provenance tag stamped onto every candidate this adapter emits.
SOURCE = "lastfm"

#: Last.fm in-band error 6 ("Track not found" / missing param) → no candidates, not a raise.
_NOT_FOUND_ERROR = 6


class LastFmError(SourceError):
    """A Last.fm in-band error that isn't a plain not-found (bad/suspended key, outage, rate limit).

    Surfaced as an exception so a misconfigured key or upstream outage is loud
    instead of masquerading as an empty similar set; the aggregator may catch it to
    degrade to its other sources.
    """

    def __init__(self, code: int | None, message: str) -> None:
        super().__init__(f"Last.fm error {code}: {message}")
        self.code = code
        self.message = message


def _text(value: object) -> str:
    """A trimmed string, or '' for any non-string value (shape-drift-safe)."""
    return value.strip() if isinstance(value, str) else ""


def _as_float(value: object) -> float | None:
    """Parse Last.fm's match score, which the JSON API serializes as a string."""
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


class LastFmClient:
    """Async Last.fm adapter over a shared ``httpx.AsyncClient``."""

    source = SOURCE  # provenance name the aggregator uses to report a failed source

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        api_key: str | None = LASTFM_API_KEY,
        limit: int = LASTFM_SIMILAR_LIMIT,
    ) -> None:
        self._client = client
        self._api_key = api_key
        self._limit = limit

    async def similar_candidates(self, title: str, artist: str) -> list[Candidate]:
        """Return Last.fm's similar tracks for the seed as ranked candidates.

        Empty when no API key is configured (graceful degradation) or the seed has
        no similar set; raises :class:`LastFmError` on a non-not-found API error.
        """
        if not self._api_key:
            return []  # degraded mode: Last.fm contributes nothing; the aggregator carries on
        rows = await self._get_similar(title, artist)
        return self._to_candidates(rows)

    async def _get_similar(self, title: str, artist: str) -> list[dict]:
        r = await self._client.get(
            LASTFM_API,
            params={
                "method": "track.getsimilar",
                "artist": artist,
                "track": title,
                "api_key": self._api_key,
                "format": "json",
                "autocorrect": 1,  # let Last.fm canonicalize a messy seed before matching
                "limit": self._limit,
            },
        )
        r.raise_for_status()
        try:
            body = r.json()
        except ValueError as exc:
            raise SourceResponseError("Last.fm returned a non-JSON body") from exc
        if not isinstance(body, dict):
            raise SourceResponseError(f"Last.fm returned a {type(body).__name__}, expected an object")
        if "error" in body:
            try:
                code = int(body.get("error"))
            except (TypeError, ValueError):
                code = None
            if code == _NOT_FOUND_ERROR:
                return []  # seed not found / no similar set → no candidates
            raise LastFmError(code, str(body.get("message", "")))
        similar = body.get("similartracks")
        tracks = similar.get("track", []) if isinstance(similar, dict) else []
        # Last.fm returns a bare object (not a list) when there is exactly one result.
        if isinstance(tracks, dict):
            return [tracks]
        return tracks if isinstance(tracks, list) else []

    def _to_candidates(self, rows: list[dict]) -> list[Candidate]:
        candidates: list[Candidate] = []
        for row in rows[: self._limit]:
            if not isinstance(row, dict):
                continue
            name = _text(row.get("name"))
            artist_obj = row.get("artist")
            artist = _text(artist_obj.get("name")) if isinstance(artist_obj, dict) else ""
            if not name or not artist:
                continue
            candidates.append(
                Candidate(
                    title=name,
                    artist=artist,
                    source=SOURCE,
                    rank=len(candidates) + 1,
                    mbid=_text(row.get("mbid")) or None,
                    score=_as_float(row.get("match")),
                )
            )
        return candidates
