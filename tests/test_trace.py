"""Offline tests for the v1.2 replay-trace capture (doppel.pipeline.trace).

Covers the recorder's sequential stage/timeline model, the sidecar document builder, the trace↔doc
reconciliation gate (the export-time guard behind the "replay always animates the run that produced
the cards it shows" rule), and the step-level pipeline wiring
(_resolve_pool cache counters/events; _embed_missing's once-bound recorder). The full run_pipeline
stage SEQUENCE is not asserted offline — it is exercised end-to-end by every real export run, and
the seam is a no-op (``trace_recorder is None``) on all production paths.
"""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from doppel.aggregation.ranking import RankedCandidate
from doppel.pipeline import recommend
from doppel.pipeline.trace import (
    TRACE_SCHEMA_VERSION,
    TraceRecorder,
    build_trace_document,
    identity_of,
    reconcile_top_identity,
)


# --- TraceRecorder ------------------------------------------------------------------------------ #


def test_stages_chain_on_one_timeline():
    rec = TraceRecorder()
    rec.stage("aggregate", candidates=153)
    rec.stage("gate1", uncached=3, verdict="warm")
    rec.stage("resolve", found=69)

    names = [s.stage for s in rec.stages]
    assert names == ["aggregate", "gate1", "resolve"]
    # Each stage starts where the previous ended; the timeline is monotonic from t=0.
    assert rec.stages[0].t0_ms == 0
    for prev, cur in zip(rec.stages, rec.stages[1:]):
        assert cur.t0_ms == prev.t1_ms
        assert cur.t1_ms >= cur.t0_ms
    assert rec.total_ms == rec.stages[-1].t1_ms
    assert rec.stages[0].counters == {"candidates": 153}


def test_events_bucket_into_the_next_closed_stage():
    rec = TraceRecorder()
    rec.stage("gate1", verdict="warm")
    rec.event("resolve.cache_hit")
    rec.event("resolve.live")
    rec.stage("resolve", found=2)
    rec.stage("gate2", verdict="warm")

    assert [e["kind"] for e in rec.stages[1].events] == ["resolve.cache_hit", "resolve.live"]
    assert rec.stages[0].events == []  # emitted after gate1 closed — never retro-bucketed
    assert rec.stages[2].events == []  # consumed by the resolve stage, not leaked forward


def test_result_identity_comes_from_the_results_stage():
    rec = TraceRecorder()
    assert rec.result_identity() is None  # no results stage recorded (e.g. a failed run)
    rec.stage("results", top=2, top_mbids=["m1", "m2"])
    assert rec.result_identity() == ["m1", "m2"]


def test_empty_recorder_total_is_zero():
    assert TraceRecorder().total_ms == 0


# --- identity / reconciliation gate ------------------------------------------------------------- #


def test_identity_prefers_mbid_and_falls_back_normalized():
    assert identity_of("mbid-1", "Title", "Artist") == "mbid-1"
    # A backfill row (no MBID) keys on whitespace-folded lowercase title::artist.
    assert identity_of(None, "  Take  FIVE ", "Dave  Brubeck") == "take five::dave brubeck"


def _doc_rows(*ids):
    """Seed-doc result rows for reconcile tests: ('mbid' or None, title, artist)."""
    return [{"mbid": m, "title": t, "artist": a} for m, t, a in ids]


def test_reconcile_passes_on_identical_top_n():
    doc = _doc_rows(("m1", "A", "X"), (None, "B", "Y"))
    assert reconcile_top_identity(["m1", "b::y"], doc) == []


def test_reconcile_names_the_first_divergent_position():
    doc = _doc_rows(("m1", "A", "X"), ("m2", "B", "Y"))
    problems = reconcile_top_identity(["m1", "m9"], doc)
    assert len(problems) == 1
    assert "position 2" in problems[0] and "m9" in problems[0] and "m2" in problems[0]


def test_reconcile_fails_on_length_mismatch_and_missing_results_stage():
    doc = _doc_rows(("m1", "A", "X"), ("m2", "B", "Y"))
    assert reconcile_top_identity(["m1"], doc)  # shorter trace → problem
    assert reconcile_top_identity(None, doc) == ["trace recorded no results stage"]


# --- document builder --------------------------------------------------------------------------- #


def test_build_trace_document_shape_and_lean_omissions():
    rec = TraceRecorder()
    rec.stage("gate1", verdict="warm")
    rec.event("resolve.cache_hit")
    rec.stage("resolve", found=1)
    rec.stage("results", top=1, top_mbids=["m1"])

    doc = build_trace_document(
        rec, slug="take-five", mode="warm", captured_at="2026-06-12T00:00:00+00:00",
        git_sha="abc1234", git_dirty=False, config={"alpha": 0.7, "beta": 0.3},
        paired_export=False,
    )
    assert doc["schema_version"] == TRACE_SCHEMA_VERSION
    assert (doc["slug"], doc["mode"], doc["git_sha"]) == ("take-five", "warm", "abc1234")
    # Exact pairing provenance, recorded at the source: False here = a --trace-only refresh, so the
    # frontend must dual-stamp this trace against its frozen doc even on a same-sha/same-day pair.
    assert doc["paired_export"] is False
    assert doc["total_ms"] == rec.total_ms
    by_name = {s["stage"]: s for s in doc["stages"]}
    assert "events" not in by_name["gate1"]  # empty events omitted (lean public file)
    assert "top_mbids" not in by_name["gate1"]  # absent identity omitted
    assert [e["kind"] for e in by_name["resolve"]["events"]] == ["resolve.cache_hit"]
    assert by_name["results"]["top_mbids"] == ["m1"]


# --- pipeline wiring (step level) --------------------------------------------------------------- #


class _Acquire:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *exc):
        return False


class _Pool:
    def __init__(self, conn=None):
        self._conn = conn

    def acquire(self):
        return _Acquire(self._conn)


def _cand(title, mbid):
    return RankedCandidate(title, "Artist", 1.0, {"lastfm": 1}, frozenset({mbid}))


@pytest.mark.asyncio
async def test_resolve_pool_counts_and_ticks_cache_hits(monkeypatch):
    """Every cached outcome (found / rejected / not_found) increments counts.cached and emits one
    resolve.cache_hit tick — the replay's 'no live MB call' pulse."""
    lookups = {
        "A": {"status": "found", "mbid": "m1"},
        "B": {"status": "rejected", "mbid": "m2"},
        "C": {"status": "not_found", "mbid": None},
    }

    async def fake_lookup(conn, title, artist):
        return lookups[title]

    async def fake_servable(conn, mbid):
        return {"mbid": mbid, "asset_id": 1, "preview_url": "u",
                "provider_track_id": None, "match_confidence": 0.9}

    monkeypatch.setattr(recommend.db, "get_canonical_lookup", fake_lookup)
    monkeypatch.setattr(recommend.db, "get_servable_track", fake_servable)

    rec = TraceRecorder()
    deps = SimpleNamespace(trace_recorder=rec, finder=None, canonicalizer=None)
    resolved, counts = await recommend._resolve_pool(
        deps, None, [_cand("A", "m1"), _cand("B", "m2"), _cand("C", "m3")]
    )
    assert (counts.cached, counts.found, counts.rejected, counts.not_found) == (3, 1, 1, 1)
    rec.stage("resolve")
    assert [e["kind"] for e in rec.stages[0].events] == ["resolve.cache_hit"] * 3


@pytest.mark.asyncio
async def test_embed_missing_events_bind_to_the_run_recorder(monkeypatch):
    """_embed_missing binds the recorder at entry: even if deps.trace_recorder is swapped mid-flight
    (the exporter moving to the next seed while an orphaned task finishes), embed.computed ticks land
    in the ORIGINAL run's recorder — never polluting another run's trace (review 2026-06-12)."""
    run_recorder, next_recorder = TraceRecorder(), TraceRecorder()
    deps = SimpleNamespace(trace_recorder=run_recorder, http=None, pool=_Pool())

    class _Embedder:
        async def embed_preview(self, url, http):
            deps.trace_recorder = next_recorder  # the exporter has "moved on" mid-embed
            return np.ones(4)

    deps.embedder = _Embedder()

    async def fake_upsert(conn, **kw):
        return True

    monkeypatch.setattr(recommend.db, "upsert_embedding", fake_upsert)

    item = recommend._Resolved(ranked=_cand("A", "m1"), mbid="m1", asset_id=1, preview_url="u",
                               provider_track_id=None, match_confidence=0.9)
    vectors = await recommend._embed_missing(deps, [item])
    assert set(vectors) == {"m1"}
    run_recorder.stage("embed")
    next_recorder.stage("embed")
    assert [e["kind"] for e in run_recorder.stages[0].events] == ["embed.computed"]
    assert next_recorder.stages[0].events == []  # the later run's trace stays clean


# --- the run_pipeline seam stays a production no-op --------------------------------------------- #


def test_pipeline_deps_trace_recorder_defaults_none():
    """The seam contract: production constructors never set it, so the field MUST default None —
    a non-None default would silently turn tracing on for the API and worker."""
    assert recommend.PipelineDeps.__dataclass_fields__["trace_recorder"].default is None


@pytest.mark.asyncio
async def test_build_results_unaffected_by_trace_field():
    """_build_results (pure) is independent of the recorder — sanity that the seam added no coupling."""
    cand = recommend.RankedCandidate("A", "X", 1.0, {"lastfm": 1}, frozenset({"m1"}))
    item = recommend._Resolved(ranked=cand, mbid="m1", asset_id=1, preview_url="u",
                               provider_track_id="p1", match_confidence=0.9)
    results = recommend._build_results(
        [item], {"m1": np.array([1.0, 0.0])}, np.array([1.0, 0.0]), None, [cand],
    )
    assert [r.mbid for r in results] == ["m1"]
