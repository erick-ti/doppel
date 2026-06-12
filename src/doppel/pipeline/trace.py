"""Per-stage trace capture for the showcase replay (v1.2 — DECISIONS.md 2026-06-12).

:class:`TraceRecorder` is an **export-only** seam: ``PipelineDeps.trace_recorder`` defaults to
``None`` and production paths (API lifespan / ARQ worker) never construct one, so ``run_pipeline``'s
guarded ``stage()`` / ``event()`` calls are no-ops everywhere except ``scripts/export_showcase.py``.
The recorder turns one pipeline run into the ``web/public/seeds/<slug>.trace.json`` sidecar that
drives the replay console — real measured timings and counters, never reconstructed ones.

Stage model: ``run_pipeline``'s stages are strictly sequential, so a single ``stage(name, …)`` call
closes the segment that started when the previous stage closed (or at construction). ``event(kind)``
adds coarse intra-stage ticks (e.g. resolve cache-hit pulses) bucketed into the next-closed stage —
animation texture only, never track-level detail beyond what the seed doc already publishes.

The reconciliation gate (:func:`reconcile_top_identity`) enforces the v1.2 cardinal rule at export
time: a trace whose produced top-10 differs from the frozen seed doc's must not ship — the replay
always animates the run that produced the cards it shows.
"""
from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

TRACE_SCHEMA_VERSION = 1


def identity_of(mbid: str | None, title: str, artist: str) -> str:
    """One result row's stable identity for trace↔doc reconciliation: the verified MBID when present,
    else a whitespace-folded lowercase ``title::artist`` key (a cultural-backfill row has no MBID)."""
    if mbid:
        return mbid
    return f"{' '.join(title.lower().split())}::{' '.join(artist.lower().split())}"


@dataclass
class StageRecord:
    """One closed pipeline segment: ``[t0_ms, t1_ms)`` on the recorder's shared timeline."""

    stage: str
    t0_ms: int
    t1_ms: int
    counters: dict[str, Any] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)
    top_mbids: list[str] | None = None  # results stage only — feeds the reconciliation gate


class TraceRecorder:
    """Sequential stage recorder. Construct at run start; one shared monotonic timeline ms-origin."""

    def __init__(self) -> None:
        self._origin = time.monotonic()
        self._prev_end_ms = 0
        self._pending_events: list[dict[str, Any]] = []
        self.stages: list[StageRecord] = []

    def _now_ms(self) -> int:
        return int((time.monotonic() - self._origin) * 1000)

    def event(self, kind: str) -> None:
        """A coarse tick inside the currently-open segment (bucketed into the next ``stage()``)."""
        self._pending_events.append({"t_ms": self._now_ms(), "kind": kind})

    def stage(self, name: str, *, top_mbids: Sequence[str] | None = None, **counters: Any) -> None:
        """Close the open segment as ``name``: t0 = previous stage's end, t1 = now. Counter values
        must be JSON-serializable (the exporter dumps them verbatim into the sidecar)."""
        t1 = self._now_ms()
        self.stages.append(StageRecord(
            stage=name, t0_ms=self._prev_end_ms, t1_ms=t1, counters=dict(counters),
            events=self._pending_events, top_mbids=list(top_mbids) if top_mbids is not None else None,
        ))
        self._prev_end_ms = t1
        self._pending_events = []

    @property
    def total_ms(self) -> int:
        return self.stages[-1].t1_ms if self.stages else 0

    def result_identity(self) -> list[str] | None:
        """The recorded top-N identity (from the ``results`` stage), or ``None`` if never recorded."""
        for record in reversed(self.stages):
            if record.top_mbids is not None:
                return list(record.top_mbids)
        return None


def build_trace_document(
    recorder: TraceRecorder, *, slug: str, mode: str, captured_at: str, git_sha: str,
    git_dirty: bool, config: Mapping[str, Any],
) -> dict[str, Any]:
    """Assemble the ``<slug>.trace.json`` sidecar body from a completed recorder.

    ``mode`` is the run's **measured** Gate-1 verdict (``"warm"``/``"cold"``), not an assumption.
    Empty ``events`` and absent ``top_mbids`` are omitted per stage to keep the public file lean.
    """
    stages: list[dict[str, Any]] = []
    for record in recorder.stages:
        entry: dict[str, Any] = {
            "stage": record.stage, "t0_ms": record.t0_ms, "t1_ms": record.t1_ms,
            "counters": record.counters,
        }
        if record.events:
            entry["events"] = record.events
        if record.top_mbids is not None:
            entry["top_mbids"] = record.top_mbids
        stages.append(entry)
    return {
        "schema_version": TRACE_SCHEMA_VERSION,
        "slug": slug,
        "mode": mode,
        "captured_at": captured_at,
        "git_sha": git_sha,
        "git_dirty": git_dirty,
        "config": dict(config),
        "total_ms": recorder.total_ms,
        "stages": stages,
    }


def reconcile_top_identity(
    trace_identity: Sequence[str] | None, doc_results: Sequence[Mapping[str, Any]]
) -> list[str]:
    """The v1.2 reconciliation gate: the traced run's ordered top-N identity must equal the frozen
    seed doc's. Returns problems (empty = reconciled). A divergence means the corpus moved since the
    doc froze — the documented reason to re-export that seed *together with* its trace, never to ship
    a trace animating results it did not produce."""
    if trace_identity is None:
        return ["trace recorded no results stage"]
    doc_identity = [identity_of(r.get("mbid"), r["title"], r["artist"]) for r in doc_results]
    if list(trace_identity) == doc_identity:
        return []
    # Name the first divergence precisely — the operator decides re-export from this message.
    for pos, (got, expected) in enumerate(zip(trace_identity, doc_identity), start=1):
        if got != expected:
            return [f"top-{len(doc_identity)} diverges at position {pos}: trace={got!r} doc={expected!r}"]
    return [f"top-N length differs: trace={len(trace_identity)} doc={len(doc_identity)}"]
