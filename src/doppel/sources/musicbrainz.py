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

Both paths additionally require the recording to be *credited to the query's artist*
by MusicBrainz artist MBID (the query artist is resolved to an MBID once per call). A
tribute or sound-alike ("The Weeknd Experience") scores ~1.0 by name but carries a
different MBID, so this — not any string heuristic — is what distinguishes it from a
real collaboration ("Calvin Harris, Rihanna"), and the MBID comparison is order-
independent so a collaborator credited second still matches. It degrades to a name match
against any credit when the artist can't be resolved or the recording has no credited
MBIDs; and because the artist lookup is non-essential hardening, a transient failure of
it degrades rather than aborting the resolve.

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
from doppel.matching.verify import DURATION_HARD_REJECT_DELTA_S, SeedRecording


def _artist_credit_mbids(rec: dict) -> set[str]:
    return {
        (credit.get("artist") or {}).get("id")
        for credit in (rec.get("artist-credit") or [])
        if (credit.get("artist") or {}).get("id")
    }


def _artist_match(artist: str, rec: dict, artist_mbid: str | None) -> bool:
    """Whether the recording is by the query's artist.

    When the query artist resolved to an MBID *and* the recording carries credited MBIDs,
    that comparison is decisive and order-independent: a tribute/sound-alike ("The Weeknd
    Experience") has a different MBID and is rejected even though its name scores ~1.0,
    while a collaboration is accepted as long as the query artist's MBID is among the
    credits — wherever it sits. Otherwise (artist unresolved, or no credited MBIDs) it
    falls back to a name match against *any* credited artist, so credit order never
    decides (a "Calvin Harris, Rihanna" credit still matches a "Rihanna" query).
    """
    mbids = _artist_credit_mbids(rec)
    if artist_mbid is not None and mbids:
        return artist_mbid in mbids
    return any(
        fuzz.token_set_ratio(artist, (credit.get("name") or ""), processor=default_process) >= SEARCH_RELEVANCE_MIN
        for credit in (rec.get("artist-credit") or [])
    )


def _clean_isrc(isrc: str) -> str:
    return "".join(ch for ch in isrc if ch.isalnum()).upper()


def _escape_lucene_phrase(text: str) -> str:
    """Escape the two chars special inside a quoted Lucene phrase: ``\\`` and ``"``."""
    return text.replace("\\", "\\\\").replace('"', '\\"')


def _title_sim(title: str, rec: dict) -> float:
    return fuzz.token_set_ratio(title, rec.get("title", ""), processor=default_process)


def _title_match(title: str, rec: dict) -> bool:
    return _title_sim(title, rec) >= SEARCH_RELEVANCE_MIN


def _isrc_consistent(rec: dict, query_title: str, target_duration_ms: int | None) -> bool:
    """Whether an ISRC-anchored recording's title + duration corroborate the candidate.

    The recording's title must match the query, and — when the provider gave a duration —
    the MB recording must have a ``length`` within the duration window of it. A provider
    duration with *no* MB length to check against is treated as a failure, not a pass:
    otherwise a title-only match would carry the provider-supplied ISRC into the seed,
    where ``score_match`` short-circuits that same ISRC to 1.0 — circular self-proof. Only
    when the provider gives no duration at all do we accept on the title match alone.
    Artist identity is checked separately by :func:`_artist_match`.
    """
    if not _title_match(query_title, rec):
        return False
    if target_duration_ms:
        length = rec.get("length")
        if not length:
            return False  # provider duration present but uncorroborated → don't grant ISRC trust
        return abs(length - target_duration_ms) / 1000.0 <= DURATION_HARD_REJECT_DELTA_S
    return True


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
        # The decisive identity signal: which MB artist the query names. Recordings are
        # then required to be credited to it — tributes/sound-alikes are not (their names
        # score ~1.0 by token_set_ratio but carry a different artist MBID).
        artist_mbid = await self._resolve_artist_mbid(artist)

        # Path A — ISRC-anchored: the recording carrying the provider's ISRC, but only
        # if its own metadata independently corroborates the candidate (see
        # _isrc_consistent) and it is credited to the query artist. Otherwise the
        # provider-derived ISRC is circular self-proof.
        if isrc:
            recs = await self._search(f"isrc:{_clean_isrc(isrc)}", limit=5)
            anchored = next(
                (
                    r for r in recs
                    if _isrc_consistent(r, title, target_duration_ms)
                    and _artist_match(artist, r, artist_mbid)
                ),
                None,
            )
            if anchored is not None:
                rec, matched_isrc = anchored, _clean_isrc(isrc)

        # Path B — nearest-duration within the title-matching, correctly-credited cluster.
        if rec is None:
            query = f'recording:"{_escape_lucene_phrase(title)}" AND artist:"{_escape_lucene_phrase(artist)}"'
            cluster = await self._search(query, limit=self._cluster_limit)
            candidates = [
                r for r in cluster
                if r.get("length") and _title_match(title, r) and _artist_match(artist, r, artist_mbid)
            ]
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

    async def _resolve_artist_mbid(self, name: str) -> str | None:
        """Resolve an artist name to a MusicBrainz artist MBID (best-effort).

        Prefers an exact normalized-name match — so "The Weeknd" picks the artist, not a
        "The Weeknd Experience" tribute that ``token_set_ratio`` also scores 100 — then
        falls back to a high fuzzy match, else ``None`` (callers skip the MBID check).

        This is a best-effort hardening lookup, so a transient/​rate-limit failure of the
        artist search must NOT abort canonicalization: on any HTTP error we return ``None``
        and let the title/duration/ISRC paths decide. (The essential *recording* search,
        by contrast, still propagates — a failure there genuinely blocks canonicalization.)
        """
        try:
            rows = await self._artist_search(name)
        except httpx.HTTPError:
            return None
        norm = default_process(name)
        for row in rows:
            if default_process(row.get("name", "")) == norm:
                return row.get("id")
        for row in rows[:5]:
            if fuzz.token_set_ratio(name, row.get("name", ""), processor=default_process) >= SEARCH_RELEVANCE_MIN:
                return row.get("id")
        return None

    async def _artist_search(self, name: str) -> list[dict]:
        """Paced MB artist search; HTTP errors propagate to the caller."""
        async with self._limiter:
            r = await self._client.get(
                f"{MUSICBRAINZ_API}/artist",
                params={"query": f'artist:"{_escape_lucene_phrase(name)}"', "fmt": "json", "limit": 10},
                headers={"User-Agent": USER_AGENT},
            )
        r.raise_for_status()
        return r.json().get("artists", [])
