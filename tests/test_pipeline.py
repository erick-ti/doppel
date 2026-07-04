"""Offline unit tests for pipeline result-building (no DB / model).

Locks in the fix: a cultural-backfill row's identity comes from the VERIFIED
resolver match (when the candidate resolved FOUND, even if its preview later failed to embed) or is
``None`` — never the unverified, possibly-conflicting source MBID carried on the candidate.
"""
from __future__ import annotations

import numpy as np

from doppel.aggregation.ranking import RankedCandidate
from doppel.pipeline import recommend
from doppel.pipeline.recommend import _build_results, _Resolved


def _cand(title: str, rank: int, score: float, mbids=frozenset()) -> RankedCandidate:
    return RankedCandidate(title, f"Artist {title}", score, {"lastfm": rank}, mbids)


class _FakeConn:
    """Minimal asyncpg-conn stand-in: returns a fixed tracks rowset for the title/artist fetch."""

    def __init__(self, track_rows):
        self._track_rows = track_rows

    async def fetch(self, sql, *args):
        return self._track_rows


class _FakeAcquire:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *exc):
        return False


class _FakeDeps:
    """deps.pool.acquire() yields the fake conn (the only thing _hnsw_lane needs from deps)."""

    def __init__(self, conn):
        self.pool = self
        self._conn = conn

    def acquire(self):
        return _FakeAcquire(self._conn)


async def test_hnsw_lane_hydrates_distinct_mbids_by_exact_identity(monkeypatch):
    # The redesigned lane: knn hits become pre-resolved, MBID-keyed scoring inputs.
    # Two distinct corpus recordings that SHARE a title/artist stay distinct by exact MBID (no title
    # dedupe); the seed and already-scorable MBIDs are excluded; an unservable hit is skipped.
    knn_hits = [{"mbid": "seed"}, {"mbid": "m1"}, {"mbid": "m2"}, {"mbid": "dup"}, {"mbid": "unservable"}]

    async def _knn(conn, vec, k, *, model_version):
        return knn_hits

    async def _fetch_emb(conn, mbids, model_version):
        return [{"mbid": m, "embedding": [float(i)]} for i, m in enumerate(mbids) if m in {"m1", "m2"}]

    async def _servable(conn, mbid):
        m = str(mbid)
        return ({"mbid": m, "asset_id": 1, "preview_url": "u", "provider_track_id": f"p-{m}",
                 "match_confidence": 0.9} if m in {"m1", "m2"} else None)

    monkeypatch.setattr(recommend.db, "knn", _knn)
    monkeypatch.setattr(recommend.db, "fetch_embeddings", _fetch_emb)
    monkeypatch.setattr(recommend.db, "get_servable_track", _servable)
    track_rows = [{"mbid": "m1", "title": "Intro", "artist": "The xx"},   # same displayed title/artist,
                  {"mbid": "m2", "title": "Intro", "artist": "The xx"}]   # distinct recordings
    deps = _FakeDeps(_FakeConn(track_rows))

    resolved, vectors = await recommend._hnsw_lane(deps, np.zeros(4), seed_mbid="seed", already={"dup"})

    assert sorted(r.mbid for r in resolved) == ["m1", "m2"]   # same-title recordings kept distinct
    assert set(vectors) == {"m1", "m2"}
    # identity is the exact corpus MBID (not a title-deduped union), tagged hnsw, with NO fabricated
    # cultural consensus (cultural_score=0 — an hnsw-only hit has no Last.fm/ListenBrainz backing)
    assert all(r.ranked.mbids == frozenset({r.mbid}) and r.ranked.sources == ("hnsw",)
               and r.ranked.cultural_score == 0.0 for r in resolved)
    assert {"seed", "dup", "unservable"}.isdisjoint(r.mbid for r in resolved)


async def test_hnsw_lane_empty_on_no_hits(monkeypatch):
    async def _knn(conn, vec, k, *, model_version):
        return []
    monkeypatch.setattr(recommend.db, "knn", _knn)
    resolved, vectors = await recommend._hnsw_lane(_FakeDeps(_FakeConn([])), np.zeros(4), "seed", set())
    assert resolved == [] and vectors == {}


def test_backfill_uses_verified_mbid_never_source_mbid():
    # A resolved FOUND (verified mbid + Deezer id) but its preview failed to embed → it is in
    # `resolved` yet not in `vectors`, so it falls to backfill. B/C never resolved; B carries
    # conflicting source MBIDs that must NOT become its served identity.
    a = _cand("A", 1, 0.05, frozenset({"source-mbid-A", "conflicting-mbid-A"}))
    b = _cand("B", 2, 0.04, frozenset({"source-mbid-B"}))
    c = _cand("C", 3, 0.03)
    resolved = [_Resolved(ranked=a, mbid="verified-A", asset_id=1, preview_url="x",
                          provider_track_id="deezer-A", match_confidence=0.9)]

    # Seed vector present, but nothing embedded (A's preview failed) → every row is cultural backfill.
    results = _build_results(resolved, {}, np.array([1.0, 0.0]), None, [a, b, c])

    by_title = {r.title: r for r in results}
    assert all(not r.was_audio_scored for r in results)
    # A: the verified resolver identity + its Deezer link — NOT its source MBIDs.
    assert by_title["A"].mbid == "verified-A" and by_title["A"].provider_track_id == "deezer-A"
    # B: unresolved cultural-only → no identity, despite carrying a (conflicting) source MBID.
    assert by_title["B"].mbid is None and by_title["B"].provider_track_id is None
    assert by_title["C"].mbid is None


def test_audio_scored_row_keeps_verified_identity():
    a = _cand("A", 1, 0.05, frozenset({"source-mbid-A"}))
    resolved = [_Resolved(ranked=a, mbid="verified-A", asset_id=1, preview_url="x",
                          provider_track_id="deezer-A", match_confidence=0.9)]
    results = _build_results(resolved, {"verified-A": np.array([0.9, 0.1])},
                             np.array([1.0, 0.0]), None, [a])
    assert len(results) == 1 and results[0].was_audio_scored is True
    assert results[0].mbid == "verified-A" and results[0].provider_track_id == "deezer-A"


def test_dedup_collapses_results_sharing_a_verified_mbid():
    # Two cultural candidates with different credits resolve to the SAME recording (one mbid, one
    # vector) — the live rec-3 "My Little Brown Book" ×2 case. Only one row should survive.
    a = _cand("Song (feat. X)", 1, 0.05)
    b = _cand("Song", 2, 0.04)
    ra = _Resolved(ranked=a, mbid="dup-mbid", asset_id=1, preview_url="x",
                   provider_track_id="d1", match_confidence=0.9)
    rb = _Resolved(ranked=b, mbid="dup-mbid", asset_id=2, preview_url="y",
                   provider_track_id="d2", match_confidence=0.9)
    results = _build_results([ra, rb], {"dup-mbid": np.array([0.9, 0.1])},
                             np.array([1.0, 0.0]), None, [a, b])
    assert len(results) == 1 and results[0].mbid == "dup-mbid"


def test_seed_mbid_is_excluded_from_results():
    # The seed re-appears as a candidate under a different credit (live rec-3 "Take Five" alias); its
    # verified mbid equals the seed's, so it must be dropped, not recommended back to the user.
    seed_alias = _cand("Take Five", 1, 0.05)
    other = _cand("Other", 2, 0.04)
    r_seed = _Resolved(ranked=seed_alias, mbid="seed-mbid", asset_id=1, preview_url="x",
                       provider_track_id="d1", match_confidence=0.9)
    r_other = _Resolved(ranked=other, mbid="other-mbid", asset_id=2, preview_url="y",
                        provider_track_id="d2", match_confidence=0.9)
    results = _build_results(
        [r_seed, r_other], {"seed-mbid": np.array([0.9, 0.1]), "other-mbid": np.array([0.5, 0.5])},
        np.array([1.0, 0.0]), None, [seed_alias, other], seed_mbid="seed-mbid",
    )
    assert all(r.mbid != "seed-mbid" for r in results)
    assert "Take Five" not in [r.title for r in results] and "Other" in [r.title for r in results]


def test_dedup_collapses_results_sharing_a_provider_track_id():
    # Two candidates with DIFFERENT credits and DIFFERENT verified MBIDs resolve to the SAME Deezer
    # track (one provider_track_id, hence identical audio + score) — the live "Three to Get Ready" ×2
    # / /track/69122368 case. The MBID dedup can't catch it (MBIDs differ); provider_track_id must,
    # and across BOTH phases: the second copy is dropped in the audio loop, then must NOT re-enter as
    # a cultural-backfill row. Only one row survives.
    a = _cand("Three to Get Ready", 1, 0.05)
    b = _cand("Three to Get Ready (alt take)", 2, 0.04)
    ra = _Resolved(ranked=a, mbid="mbid-A", asset_id=1, preview_url="x",
                   provider_track_id="69122368", match_confidence=0.9)
    rb = _Resolved(ranked=b, mbid="mbid-B", asset_id=2, preview_url="y",
                   provider_track_id="69122368", match_confidence=0.9)
    vec = np.array([0.9, 0.1])  # same audio → same embedding for both MBIDs
    results = _build_results([ra, rb], {"mbid-A": vec, "mbid-B": vec},
                             np.array([1.0, 0.0]), None, [a, b])
    assert len(results) == 1
    assert results[0].provider_track_id == "69122368" and results[0].was_audio_scored is True


def test_distinct_results_without_provider_track_id_are_kept():
    # A None provider_track_id means "no Deezer track", not a collision: two distinct recordings that
    # both lack one must both survive (a naive `ptid in used_ptids` that swallowed None would wrongly
    # collapse them to one).
    a = _cand("A", 1, 0.05)
    b = _cand("B", 2, 0.04)
    ra = _Resolved(ranked=a, mbid="mbid-A", asset_id=1, preview_url="x",
                   provider_track_id=None, match_confidence=0.9)
    rb = _Resolved(ranked=b, mbid="mbid-B", asset_id=2, preview_url="y",
                   provider_track_id=None, match_confidence=0.9)
    results = _build_results(
        [ra, rb], {"mbid-A": np.array([0.9, 0.1]), "mbid-B": np.array([0.4, 0.6])},
        np.array([1.0, 0.0]), None, [a, b],
    )
    assert {r.mbid for r in results} == {"mbid-A", "mbid-B"}


def test_seed_provider_track_id_suppresses_same_track_alias():
    # The seed re-enters as a candidate under a DIFFERENT MBID but the SAME Deezer track (a multi-MBID
    # / one-provider-track alias of the seed). seed_mbid can't catch it (the MBID differs); seeding
    # used_ptids with the seed's own provider_track_id must — otherwise the seed is recommended back as
    # its own ~1.0-scoring top result. Exercises both phases: the alias is dropped from the audio loop
    # AND must not re-enter as backfill.
    alias = _cand("Take Five (Remastered)", 1, 0.05)
    other = _cand("Other", 2, 0.04)
    r_alias = _Resolved(ranked=alias, mbid="alias-mbid", asset_id=1, preview_url="x",
                        provider_track_id="seed-ptid", match_confidence=0.9)
    r_other = _Resolved(ranked=other, mbid="other-mbid", asset_id=2, preview_url="y",
                        provider_track_id="other-ptid", match_confidence=0.9)
    results = _build_results(
        [r_alias, r_other],
        {"alias-mbid": np.array([1.0, 0.0]), "other-mbid": np.array([0.5, 0.5])},
        np.array([1.0, 0.0]), None, [alias, other],
        seed_mbid="seed-mbid", seed_provider_track_id="seed-ptid",
    )
    titles = [r.title for r in results]
    assert "Take Five (Remastered)" not in titles and "Other" in titles
    assert all(r.provider_track_id != "seed-ptid" for r in results)


def test_seed_equivalence_drops_near_identical_master_of_the_seed():
    # The seed re-appears as a DIFFERENT master (distinct MBID + Deezer track, so identity dedup can't
    # catch it) at near-identical audio — the live Take Five → "Take Five — Dave Brubeck" (0.988) case.
    # The audio≥0.98 + seed-title-match heuristic drops it. Two near-misses MUST be kept: a high-audio
    # but differently-titled track, and a same-title LIVE version (lower audio) — the heuristic must not
    # drop legitimate versions (Day-7 eval follow-up).
    equiv = _cand("Take Five", 1, 0.05)                 # same title as seed, near-identical audio
    other = _cand("Different Song", 2, 0.04)            # high audio, different title → keep
    live = _cand("Take Five (Live Acoustic)", 3, 0.03)  # same title family, lower audio → keep
    r_equiv = _Resolved(ranked=equiv, mbid="tf-alt-mbid", asset_id=1, preview_url="x",
                        provider_track_id="tf-alt-ptid", match_confidence=0.9)
    r_other = _Resolved(ranked=other, mbid="other-mbid", asset_id=2, preview_url="y",
                        provider_track_id="other-ptid", match_confidence=0.9)
    r_live = _Resolved(ranked=live, mbid="live-mbid", asset_id=3, preview_url="z",
                       provider_track_id="live-ptid", match_confidence=0.9)
    results = _build_results(
        [r_equiv, r_other, r_live],
        {"tf-alt-mbid": np.array([1.0, 0.0]),   # cosine 1.0 vs seed → ≥ 0.98
         "other-mbid": np.array([1.0, 0.0]),    # cosine 1.0 vs seed → ≥ 0.98
         "live-mbid": np.array([0.6, 0.8])},    # cosine 0.6 vs seed → < 0.98
        np.array([1.0, 0.0]), None, [equiv, other, live],
        seed_mbid="seed-mbid", seed_provider_track_id="seed-ptid", seed_title="Take Five",
    )
    titles = [r.title for r in results]
    assert "Take Five" not in titles              # the seed's own master — suppressed (audio + title)
    assert "Different Song" in titles             # high audio but different title — kept
    assert "Take Five (Live Acoustic)" in titles  # same title family, lower audio — preserved
