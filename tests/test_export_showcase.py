"""Offline tests for the v1.1 showcase exporter's gate logic (``scripts/export_showcase.py``).

Guards against gate failures being advisory-only. Curated seeds must pass *every* gate
(they back the showcase's public claims); the intentionally-degraded capture runs the inverse profile
— it MUST come back cultural-only. (``scripts`` is on the pytest ``pythonpath``, so the module imports
by its bare name.)
"""
from __future__ import annotations

import export_showcase as ex

_ALL_GATES = ("seed_audio_scored", "no_cultural_backfill", "rationales_available",
              "no_degraded_sources", "no_self_master_leak")

CURATED_SEED = ex.ShowcaseSeed("s", "Take Five", "The Dave Brubeck Quartet", "jazz")
DEGRADED_SEED = ex.ShowcaseSeed("degraded", "Obscure", "Nobody", "degraded-demo", expect_degraded=True)


def _payload(degradation=None, results=None):
    deg = {"seed_audio_scored": True, "cultural_backfill_count": 0,
           "rationales_available": True, "degraded_sources": {}}
    if degradation:
        deg.update(degradation)
    return {"degradation": deg, "results": results if results is not None else [{"title": "Neighbor"}]}


def test_gate_report_clean_payload_all_true():
    assert all(ex._gate_report(CURATED_SEED, _payload()).values())


def test_gate_report_flags_self_master_leak_case_insensitively():
    payload = _payload(results=[{"title": "take five"}, {"title": "Other"}])
    assert ex._gate_report(CURATED_SEED, payload)["no_self_master_leak"] is False


def test_gate_report_flags_degraded_sources_backfill_and_missing_rationales():
    payload = _payload(degradation={"degraded_sources": {"lastfm": "x"}, "cultural_backfill_count": 2,
                                    "rationales_available": False, "seed_audio_scored": False})
    gates = ex._gate_report(CURATED_SEED, payload)
    assert gates["no_degraded_sources"] is False
    assert gates["no_cultural_backfill"] is False
    assert gates["rationales_available"] is False
    assert gates["seed_audio_scored"] is False


def test_gates_pass_curated_requires_every_gate():
    ok = {k: True for k in _ALL_GATES}
    passed, problems = ex._gates_pass(CURATED_SEED, ok)
    assert passed and problems == []

    passed, problems = ex._gates_pass(CURATED_SEED, dict(ok, no_degraded_sources=False))
    assert not passed and problems == ["no_degraded_sources"]


def test_gates_pass_degraded_profile_requires_cultural_only_and_clean_sources():
    # The degraded capture must be cultural-only AND carry no degraded source (whose raw error string
    # could leak a provider URL/credential). The OTHER curated gates (backfill, rationales) don't apply.
    audio = {"seed_audio_scored": True, "no_degraded_sources": True}
    passed, problems = ex._gates_pass(DEGRADED_SEED, audio)
    assert not passed and problems  # audio-scored => failed to capture a degraded state

    clean = {"seed_audio_scored": False, "no_degraded_sources": True}
    passed, problems = ex._gates_pass(DEGRADED_SEED, clean)
    assert passed and problems == []

    leaky = {"seed_audio_scored": False, "no_degraded_sources": False}
    passed, problems = ex._gates_pass(DEGRADED_SEED, leaky)
    assert not passed and "no_degraded_sources" in problems  # never publish raw provider errors


def test_select_filters_by_only_and_marks_degraded_profile():
    only = ex._select("humble,take-five", None)
    assert {s.slug for s in only} == {"humble", "take-five"}

    with_degraded = ex._select("humble", "No Preview Track::Nobody")
    degraded = [s for s in with_degraded if s.slug == "degraded"]
    assert len(degraded) == 1
    assert degraded[0].expect_degraded is True
    assert degraded[0].title == "No Preview Track" and degraded[0].artist == "Nobody"


def test_round_scores_rounds_floats_and_preserves_nulls():
    payload = {"results": [
        {"audio_score": 0.91920905709575, "vibe_text_score": None,
         "combined_score": 1.0, "cultural_score": 0.016129032258064516},
        {"audio_score": None, "vibe_text_score": None, "combined_score": None, "cultural_score": 0.0105},
    ]}
    out = ex._round_scores(payload)
    # full-precision float noise collapses to a stable 6-dp value
    assert out["results"][0]["audio_score"] == 0.919209
    assert out["results"][0]["cultural_score"] == 0.016129
    assert out["results"][0]["combined_score"] == 1.0
    # nulls (no-vibe / cultural-backfill rows) are left untouched — rounding them would raise
    assert out["results"][0]["vibe_text_score"] is None
    assert out["results"][1]["audio_score"] is None
    assert out["results"][1]["combined_score"] is None


def test_should_write_only_overrides_cosmetic_gates():
    assert ex._should_write(True, [], allow_gate_warnings=False) is True   # a passing seed always writes
    # with no override, any failure blocks the write
    assert ex._should_write(False, ["no_cultural_backfill"], allow_gate_warnings=False) is False
    # --allow-gate-warnings force-writes a seed whose only failures are cosmetic
    assert ex._should_write(False, ["no_cultural_backfill", "rationales_available", "no_self_master_leak"],
                            allow_gate_warnings=True) is True
    # ...but a MATERIAL failure is never overridable, even mixed with a cosmetic one
    for material in ("seed_audio_scored", "no_degraded_sources",
                     "expected a cultural-only (no-preview) capture, but the seed WAS audio-scored"):
        assert ex._should_write(False, ["rationales_available", material], allow_gate_warnings=True) is False


def test_remove_stale_unlinks_existing_target(tmp_path):
    # Fail-closed: a blocked/errored seed must not leave a prior run's JSON in the public set.
    p = tmp_path / "humble.json"
    p.write_text("{}")
    assert ex._remove_stale(p) is True
    assert not p.exists()
    assert ex._remove_stale(p) is False  # idempotent no-op when already absent
