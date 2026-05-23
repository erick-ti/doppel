"""ListenBrainz Labs source adapter — cultural candidates via similar-recordings.

Given a seed ``(title, artist)``, returns the recordings ListenBrainz considers
similar, as ranked :class:`~doppel.aggregation.candidates.Candidate` objects. Two
Labs calls:

  1. ``recording-search`` — resolve the seed to a ListenBrainz-*canonical* recording
     MBID. This step is mandatory: ``similar-recordings`` is keyed on these canonical
     MBIDs, and an arbitrary MusicBrainz recording MBID returns ``[]`` (validated
     Day 0; see DECISIONS.md). The chosen row must be the seed *itself* — exact
     normalized title (so live / remaster / edit variants are rejected) and a matching
     artist, with cover / karaoke / tribute markers rejected — because the entire
     similar set is generated from it and ``resolve()`` later verifies the *candidates*,
     never this anchor (:func:`_is_seed_recording`).
  2. ``similar-recordings`` — the similar set, already ordered by descending score.
     Each row carries ``recording_name`` / ``artist_credit_name`` / ``recording_mbid``,
     so candidates arrive ready for the matcher's ``resolve(title, artist)`` with a
     canonical MBID already attached — no extra lookup hop.

similar-recordings is experimental and can be thin for older / niche seeds (some
return no similar set at all); that surfaces here as an empty list, and the
aggregator degrades to its other sources. Transport / HTTP errors propagate (the
aggregator's per-source isolation catches them); a malformed 200 body (the
experimental endpoint occasionally answers with a non-JSON page) raises
``SourceResponseError``, which the aggregator records as a degraded source —
distinct from a genuine empty similar set.
"""
from __future__ import annotations

import asyncio

import httpx
from rapidfuzz import fuzz
from rapidfuzz.utils import default_process

from doppel.aggregation.candidates import Candidate, normalize_text
from doppel.config import (
    LISTENBRAINZ_ALGORITHM,
    LISTENBRAINZ_LABS,
    LISTENBRAINZ_POLITE_DELAY_S,
    LISTENBRAINZ_SIMILAR_LIMIT,
    SEARCH_RELEVANCE_MIN,
    USER_AGENT,
)
from doppel.matching.verify import cover_mismatch
from doppel.sources.errors import SourceResponseError

#: Provenance tag stamped onto every candidate this adapter emits.
SOURCE = "listenbrainz"


def _text(value: object) -> str:
    """A trimmed string, or '' for any non-string value (shape-drift-safe)."""
    return value.strip() if isinstance(value, str) else ""


def _artist_matches(seed_artist: str, row_artist: str) -> bool:
    """Looser artist gate — token_set absorbs 'feat.' / '&' credit differences."""
    return fuzz.token_set_ratio(seed_artist, row_artist, processor=default_process) >= SEARCH_RELEVANCE_MIN


def _is_seed_recording(seed_title: str, seed_artist: str, row_title: str, row_artist: str) -> bool:
    """Whether a recording-search row is the seed *itself* — not a variant, cover, or tribute.

    The title must match exactly under the conservative normalization, so a row that adds a
    variant token ("Song (Live)", "Song - Remaster") yields a different normalized title and
    is rejected — ``token_set_ratio`` alone can't separate these, since it scores "Song"
    against "Song (Live)" at 100. The artist keeps the looser token_set gate so "feat." / "&"
    credit differences still match, and an added cover / karaoke / tribute marker is rejected
    outright. Residual: a bare artist superset ("The Weeknd Experience") still passes here —
    separating it from a real band / collaboration needs the MusicBrainz artist-MBID signal
    the matcher uses, which the seed path deliberately avoids (it would add unpaced MB calls).
    The blast radius is bounded: a wrong anchor only skews this query's candidate pool, and
    every candidate is still independently verified by ``resolve()``.
    """
    if normalize_text(seed_title) != normalize_text(row_title):
        return False
    if not _artist_matches(seed_artist, row_artist):
        return False
    return not cover_mismatch(seed_title, seed_artist, row_title, row_artist)


class ListenBrainzClient:
    """Async ListenBrainz Labs adapter over a shared ``httpx.AsyncClient``."""

    source = SOURCE  # provenance name the aggregator uses to report a failed source

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        algorithm: str = LISTENBRAINZ_ALGORITHM,
        polite_delay_s: float = LISTENBRAINZ_POLITE_DELAY_S,
        limit: int = LISTENBRAINZ_SIMILAR_LIMIT,
    ) -> None:
        self._client = client
        self._algorithm = algorithm
        self._polite_delay_s = polite_delay_s
        self._limit = limit

    async def similar_candidates(self, title: str, artist: str) -> list[Candidate]:
        """Resolve the seed to a canonical MBID, then return its similar recordings.

        Empty when the seed can't be resolved or has no similar set (both expected
        for niche / older catalogue), so the aggregator can fall back to other
        sources.
        """
        seed_mbid = await self._resolve_canonical_mbid(title, artist)
        if seed_mbid is None:
            return []
        await asyncio.sleep(self._polite_delay_s)  # polite spacing between the two Labs calls
        rows = await self._similar_recordings(seed_mbid)
        return self._to_candidates(rows, seed_mbid=seed_mbid)

    async def _resolve_canonical_mbid(self, title: str, artist: str) -> str | None:
        """First recording-search row (of the top 5) that is the seed itself, not a variant/cover."""
        rows = await self._recording_search(f"{title} {artist}")
        for row in rows[:5]:
            if not isinstance(row, dict):
                continue
            if _is_seed_recording(
                title, artist, _text(row.get("recording_name")), _text(row.get("artist_credit_name"))
            ):
                mbid = row.get("recording_mbid")
                if isinstance(mbid, str) and mbid:
                    return mbid
        return None

    def _to_candidates(self, rows: list[dict], *, seed_mbid: str) -> list[Candidate]:
        """Parse similar-recordings rows into ranked candidates (1-based, dense).

        Skips unusable rows (missing / non-string name or artist) and the seed itself,
        then numbers ranks over what survives so RRF sees a contiguous 1..N ordering.
        """
        candidates: list[Candidate] = []
        for row in rows[: self._limit]:
            if not isinstance(row, dict):
                continue
            name = _text(row.get("recording_name"))
            credit = _text(row.get("artist_credit_name"))
            if not name or not credit:
                continue
            mbid_raw = row.get("recording_mbid")
            mbid = mbid_raw if isinstance(mbid_raw, str) and mbid_raw else None
            if mbid and mbid == seed_mbid:  # don't recommend the seed back to itself
                continue
            score = row.get("score")
            candidates.append(
                Candidate(
                    title=name,
                    artist=credit,
                    source=SOURCE,
                    rank=len(candidates) + 1,
                    mbid=mbid,
                    score=float(score) if isinstance(score, (int, float)) else None,
                )
            )
        return candidates

    async def _recording_search(self, query: str) -> list[dict]:
        """Labs recording-search used to resolve the seed's canonical MBID."""
        return await self._get_json_list("/recording-search/json", {"query": query})

    async def _similar_recordings(self, recording_mbid: str) -> list[dict]:
        """Labs similar-recordings for a canonical MBID."""
        return await self._get_json_list(
            "/similar-recordings/json",
            {"recording_mbids": recording_mbid, "algorithm": self._algorithm},
        )

    async def _get_json_list(self, path: str, params: dict) -> list[dict]:
        """GET a Labs endpoint; HTTP errors propagate, a malformed / non-list 200 body raises.

        A genuine empty result is a 200 with an empty JSON *list* (the normal no-data path).
        A non-JSON body (the experimental endpoint occasionally answers with an HTML gateway
        / maintenance page) or a non-list shape is an outage / schema drift, not no-data — it
        raises :class:`SourceResponseError` so the aggregator records the source as degraded
        instead of mistaking it for an empty similar set.
        """
        r = await self._client.get(
            f"{LISTENBRAINZ_LABS}{path}", params=params, headers={"User-Agent": USER_AGENT}
        )
        r.raise_for_status()
        try:
            body = r.json()
        except ValueError as exc:
            raise SourceResponseError(f"ListenBrainz {path} returned a non-JSON body") from exc
        if not isinstance(body, list):
            raise SourceResponseError(f"ListenBrainz {path} returned a {type(body).__name__}, expected a list")
        return body
