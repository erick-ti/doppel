/**
 * TypeScript mirror of the v1.2 replay-trace sidecar (`public/seeds/<slug>.trace.json`), written by
 * `scripts/export_showcase.py` from a pipeline `TraceRecorder` run (src/doppel/pipeline/trace.py —
 * keep field-for-field in sync with `build_trace_document`).
 *
 * Every timing/counter is REAL measured telemetry from the recorded run the sidecar stamps
 * (`captured_at` + `git_sha`) — the replay console renders it as a recorded replay, never as a live
 * run (the v1.2 cardinal rule, DECISIONS.md 2026-06-12). `mode` is the run's measured Gate-1 verdict.
 * Stages a run never reached (e.g. resolve/embed on a degraded, cultural-only capture) are simply
 * absent — render what is there, honestly.
 */

/** One closed pipeline segment on the run's shared ms timeline. */
export interface TraceStage {
  /**
   * "aggregate" | "gate1" | "seed" | "resolve" | "gate2" | "embed" | "hnsw_lane" | "results"
   * | "explain" — left as string: render known stages, ignore unknown ones (schema may grow).
   */
  stage: string;
  t0_ms: number;
  t1_ms: number;
  /** Stage-specific measured counters (e.g. resolve: attempted/cache_hits/found/rejected/not_found). */
  counters: Record<string, number | string | boolean>;
  /** Coarse intra-stage ticks for animation texture (e.g. "resolve.cache_hit"). Omitted when empty. */
  events?: { t_ms: number; kind: string }[];
  /** Results stage only: the traced top-N identity the export-time reconciliation gate verified
   *  against the frozen seed doc (mbid, or a normalized "title::artist" fallback). */
  top_mbids?: string[];
}

/** The `<slug>.trace.json` document. */
export interface RunTrace {
  schema_version: number;
  slug: string;
  /**
   * The Gate-1 verdict ("warm" | "cold") of the run that produced THIS trace. A `--trace-only`
   * refresh re-measures it, so it can differ from the run that froze the seed doc (e.g. a doc
   * narrating a cold first export, paired with a later warm-mode trace). The replay narrates the
   * trace's own run, stamped by `captured_at` + `git_sha`.
   */
  mode: string;
  captured_at: string;
  git_sha: string;
  git_dirty: boolean;
  /**
   * True when this trace came from the SAME export run that wrote the seed doc beside it; false for
   * a `--trace-only` refresh (the banner must dual-stamp those, even on the same sha/day). Absent on
   * sidecars captured before the field existed — consumers fall back to a sha+date heuristic.
   */
  paired_export?: boolean;
  /** Config snapshot the run executed under (alpha/beta, gate thresholds, hnsw lane state). */
  config: Record<string, number | string | boolean>;
  /**
   * Span of the recorded timeline: aggregate → explain close. NOT comparable to the seed doc's
   * `coverage.latency_ms` (run_pipeline-internal: excludes aggregate/Gate-1, includes persistence).
   */
  total_ms: number;
  stages: TraceStage[];
}
