"""Offline unit tests for pipeline result-building (no DB / model).

Locks in the Codex round-2 finding-3 fix: a cultural-backfill row's identity comes from the VERIFIED
resolver match (when the candidate resolved FOUND, even if its preview later failed to embed) or is
``None`` — never the unverified, possibly-conflicting source MBID carried on the candidate.
"""
from __future__ import annotations

import numpy as np

from doppel.aggregation.ranking import RankedCandidate
from doppel.pipeline.recommend import _build_results, _Resolved


def _cand(title: str, rank: int, score: float, mbids=frozenset()) -> RankedCandidate:
    return RankedCandidate(title, f"Artist {title}", score, {"lastfm": rank}, mbids)


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
