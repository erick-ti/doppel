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

/** Same Leg vocabulary as architecture-dag: cultural = recall, audio = CLAP/vector, fused = the
 *  --seam output (score/fuse/rank), neutral = glue. */
export type StageLeg = "cultural" | "audio" | "fused" | "neutral";

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
    label: "Find songs the crowd pairs",
    leg: "cultural",
    describe: (c) => `${n(c.candidates)} from Last.fm + ListenBrainz, merged by rank`,
  },
  {
    id: "gate1",
    label: "Quick path or slow path?",
    leg: "neutral",
    describe: (c) => `${n(c.uncached)} new to look up, so going ${String(c.verdict ?? "?")}`,
  },
  {
    id: "seed",
    label: "Listen to your song",
    leg: "audio",
    describe: (c) =>
      `${c.audio_scored ? "CLAP listened to it" : "no preview to listen to"}${c.vibe_present ? " · mood added" : ""}`,
  },
  {
    id: "resolve",
    label: "Look each one up",
    leg: "cultural",
    describe: (c) => {
      const live = n(c.attempted) - n(c.cache_hits);
      return `${n(c.attempted)} looked up · ${n(c.cache_hits)} already known · ${live} fresh · ${n(c.found)} found`;
    },
  },
  {
    id: "gate2",
    label: "Listen now or later?",
    leg: "neutral",
    describe: (c) => `${n(c.missing)} still to hear, so going ${String(c.verdict ?? "?")}`,
  },
  {
    id: "embed",
    label: "Listen to each one",
    leg: "audio",
    describe: (c) =>
      n(c.attempted) === 0
        ? "already knew them all, nothing new to hear"
        : `CLAP listened to ${n(c.computed)}${n(c.failed) > 0 ? ` · ${n(c.failed)} had no preview` : ""}`,
  },
  {
    id: "hnsw_lane",
    label: "Search by your mood",
    leg: "audio",
    describe: (c) => `matched your mood against the library, pulled in ${n(c.hydrated)} more`,
  },
  {
    id: "results",
    label: "Put the list together",
    leg: "fused",
    describe: (c) => `top ${n(c.top)} · ${n(c.audio_scored)} scored by sound`,
  },
  {
    id: "explain",
    label: "Write the why",
    leg: "neutral",
    describe: (c) => (c.rationales_available ? "one LLM call, a note per pick" : "skipped the notes this time"),
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
  docDate: string; // YYYY-MM-DD (UTC-sliced — drives sameCapture; display uses docIso in local TZ)
  /** Raw ISO instants, so the display can render them in the viewer's timezone (<LocalStamp>). */
  docIso: string;
  traceSha: string;
  traceDirty: boolean;
  traceDate: string; // YYYY-MM-DD (UTC-sliced)
  traceIso: string;
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
    docIso: meta.exported_at,
    traceSha: trace.git_sha,
    traceDirty: trace.git_dirty,
    traceDate,
    traceIso: trace.captured_at,
  };
}

/** A sha stamp that carries the exporter's dirty flag — never present a dirty capture as clean. */
export function shaStamp(sha: string, dirty: boolean): string {
  return dirty ? `${sha}-dirty` : sha;
}
