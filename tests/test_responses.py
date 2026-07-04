"""Offline tests for the shared ``/recommend`` wire-format builders (``doppel.api.responses``).

``response_from_rows`` is the source of truth for the COLD-poll body **and** the v1.1 showcase export,
so its fidelity matters. The headline regression: it must carry the durable ``failed_sources`` into
``degradation.degraded_sources`` — the export switched to this builder precisely because the in-memory
job-mode ``Recommendation`` reports ``degraded_sources={}`` and would otherwise publish a clean-looking
degradation block over a degraded run.
"""
from __future__ import annotations

import json

from doppel.api.responses import (
    DEEZER_TRACK_URL,
    decode_failed_sources,
    deezer_url,
    response_from_rows,
)


def _row(**over):
    base = {
        "id": 42, "seed_title": "Seed", "seed_artist": "Artist", "seed_mbid": None,
        "vibe_text": None, "seed_audio_scored": True, "backfill_count": 0,
        "rationales_available": True, "failed_sources": None,
    }
    base.update(over)
    return base


def _result(**over):
    base = {
        "position": 1, "title": "T", "artist": "A", "mbid": None, "provider_track_id": "123",
        "was_audio_scored": True, "audio_score": 0.9, "vibe_text_score": None,
        "combined_score": 1.0, "cultural_score": 0.01, "sources": ["lastfm"], "rationale": "because",
    }
    base.update(over)
    return base


def test_deezer_url_is_a_page_link_or_none():
    assert deezer_url("69122368") == f"{DEEZER_TRACK_URL}69122368"
    assert deezer_url(None) is None
    assert deezer_url("") is None  # a missing provider id is never a link


def test_decode_failed_sources_handles_dict_json_and_none():
    assert decode_failed_sources(None) == {}
    assert decode_failed_sources({"lastfm": "timeout"}) == {"lastfm": "timeout"}
    assert decode_failed_sources(json.dumps({"lastfm": "timeout"})) == {"lastfm": "timeout"}
    assert decode_failed_sources("not json") == {}  # malformed text degrades to empty, never raises


def test_response_from_rows_preserves_failed_sources_as_degraded_sources():
    # The regression this guards: a degraded cultural source must surface in the response body.
    resp = response_from_rows(_row(failed_sources={"listenbrainz": "503"}), [_result()])
    assert resp.degradation.degraded_sources == {"listenbrainz": "503"}


def test_response_from_rows_decodes_jsonb_text_failed_sources():
    # asyncpg returns JSONB as text without a codec — the builder must still decode it.
    resp = response_from_rows(_row(failed_sources=json.dumps({"lastfm": "timeout"})), [_result()])
    assert resp.degradation.degraded_sources == {"lastfm": "timeout"}


def test_response_from_rows_clean_run_has_empty_degraded_sources():
    resp = response_from_rows(_row(failed_sources=None), [_result()])
    assert resp.degradation.degraded_sources == {}
    assert resp.degradation.seed_audio_scored is True


def test_response_from_rows_maps_result_and_builds_deezer_page_link():
    resp = response_from_rows(_row(id=7), [_result(provider_track_id="555", title="Neighbor")])
    assert resp.query_id == 7
    assert len(resp.results) == 1
    item = resp.results[0]
    assert item.title == "Neighbor"
    assert item.deezer_url == f"{DEEZER_TRACK_URL}555"  # a track-PAGE link, never preview audio
    assert item.was_audio_scored is True
