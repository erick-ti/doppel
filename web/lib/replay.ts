/**
 * Pure helpers for the replay console (client-safe — no server-only imports).
 *
 * Everything here renders RECORDED telemetry (types/trace.ts) — the v1.2 cardinal rule
 * (DECISIONS.md 2026-06-12) is that the UI never implies a live run: timings come from the trace
 * verbatim, playback speed is always labeled, and a doc/trace pair captured at different times is
 * dual-stamped (`pairProvenance`), never presented under one frame-accuracy claim.
 */
import type { ExportMeta } from "@/types/recommendation";
import type { RunTrace, TraceStage } from "@/types/trace";

/** Same Leg vocabulary as architecture-dag: cultural = recall, audio = CLAP/vector, neutral = glue. */
export type StageLeg = "cultural" | "audio" | "neutral";

export interface StageSpec {
  id: string;
  label: string;
  leg: StageLeg;
  /** One mono line of measured facts for the stage row, built from the trace's counters. */
  describe: (c: Record<string, number | string | boolean>) => string;
}

const n = (v: number | string | boolean | undefined): number => (typeof v === "number" ? v : 0);

/**
 * Display specs for the known stage ids, in pipeline order. Unknown ids (a future schema) render
 * with a generic spec rather than crashing — mirror of types/trace.ts "render known, ignore unknown".
 */
export const STAGE_SPECS: readonly StageSpec[] = [
  {
    id: "aggregate",
    label: "Cultural retrieval",
    leg: "cultural",
    describe: (c) => `${n(c.candidates)} candidates · Last.fm + ListenBrainz`,
  },
  {
    id: "gate1",
    label: "Gate 1 — resolve budget",
    leg: "neutral",
    describe: (c) => `${n(c.uncached)} uncached vs threshold ${n(c.threshold)} → ${String(c.verdict ?? "?")}`,
  },
  {
    id: "seed",
    label: "Seed resolve + embed",
    leg: "audio",
    describe: (c) =>
      `${c.audio_scored ? "seed audio-scored" : "no usable preview — cultural-only"}${c.vibe_present ? " · vibe embedded" : ""}`,
  },
  {
    id: "resolve",
    label: "Resolve candidates (MusicBrainz)",
    leg: "cultural",
    describe: (c) => {
      const live = n(c.attempted) - n(c.cache_hits);
      return `${n(c.attempted)} attempted · ${n(c.cache_hits)} cached · ${live} live${live > 0 ? " (~1 req/s)" : ""} · ${n(c.found)} found`;
    },
  },
  {
    id: "gate2",
    label: "Gate 2 — embed budget",
    leg: "neutral",
    describe: (c) => `${n(c.missing)} unembedded vs threshold ${n(c.threshold)} → ${String(c.verdict ?? "?")}`,
  },
  {
    id: "embed",
    label: "Embed previews (CLAP)",
    leg: "audio",
    describe: (c) =>
      n(c.attempted) === 0
        ? "0 to embed — every candidate already in the corpus cache"
        : `${n(c.computed)} embedded · ${n(c.failed)} previews failed${n(c.failed) > 0 ? " (degrade, never sink)" : ""}`,
  },
  {
    id: "hnsw_lane",
    label: "Vibe lane (HNSW over corpus)",
    leg: "audio",
    describe: (c) => `knn(vibe) k=${n(c.k)} → ${n(c.hydrated)} corpus tracks join scoring`,
  },
  {
    id: "results",
    label: "Score, fuse + rank",
    leg: "audio",
    describe: (c) => `top ${n(c.top)} · ${n(c.audio_scored)} audio-scored · ${n(c.backfill)} backfill`,
  },
  {
    id: "explain",
    label: "Explain (LLM — never ranks)",
    leg: "neutral",
    describe: (c) => (c.rationales_available ? "one batched call · a rationale per row" : "degraded — results without rationales"),
  },
] as const;

const SPEC_BY_ID = new Map(STAGE_SPECS.map((s) => [s.id, s]));

export function specFor(stage: TraceStage): StageSpec {
  return (
    SPEC_BY_ID.get(stage.stage) ?? {
      id: stage.stage,
      label: stage.stage,
      leg: "neutral",
      describe: () => "",
    }
  );
}

/** Playback presets: a warm trace (~12–14 s) replays in real time; a cold one defaults compressed. */
export function speedOptions(mode: string): number[] {
  return mode === "cold" ? [8, 20, 40] : [1, 2, 4];
}

export function defaultSpeed(mode: string): number {
  return mode === "cold" ? 20 : 1;
}

export function speedLabel(speed: number): string {
  return speed === 1 ? "real time" : `compressed ${speed}×`;
}

export function formatClock(ms: number): string {
  const total = Math.max(0, Math.round(ms / 1000));
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

export interface PairProvenance {
  /** True when doc + trace come from the same export batch (same sha and same capture day). */
  sameCapture: boolean;
  docSha: string;
  docDirty: boolean;
  docDate: string; // YYYY-MM-DD
  traceSha: string;
  traceDirty: boolean;
  traceDate: string; // YYYY-MM-DD
}

/**
 * The dual-stamp rule: a `--trace-only` refresh pairs a frozen doc with newer telemetry. When the
 * captures differ the banner must show BOTH ("results frozen X · telemetry captured Y") — never one
 * frame-accuracy claim spanning two runs.
 *
 * Pairing identity is the exporter's own `paired_export` flag (exact — written by the only code
 * that knows whether doc and trace came from one run). The sha+date heuristic survives only as the
 * fallback for sidecars captured before the flag existed; it cannot distinguish a same-day,
 * same-commit refresh (Codex review 2026-06-12), which is why the flag replaced it.
 */
export function pairProvenance(meta: ExportMeta, trace: RunTrace): PairProvenance {
  const docDate = meta.exported_at.slice(0, 10);
  const traceDate = trace.captured_at.slice(0, 10);
  const sameSha = meta.git_sha === trace.git_sha;
  return {
    sameCapture:
      trace.paired_export === undefined
        ? sameSha && docDate === traceDate // legacy sidecars only
        : trace.paired_export && sameSha,
    docSha: meta.git_sha,
    docDirty: meta.git_dirty,
    docDate,
    traceSha: trace.git_sha,
    traceDirty: trace.git_dirty,
    traceDate,
  };
}

/** A sha stamp that carries the exporter's dirty flag — never present a dirty capture as clean. */
export function shaStamp(sha: string, dirty: boolean): string {
  return dirty ? `${sha}-dirty` : sha;
}
