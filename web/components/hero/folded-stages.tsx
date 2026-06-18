"use client";

/**
 * The above-the-fold mini-replay: the recorded run's 8 stages folded into the THREE legs
 * (cultural retrieval -> audio rerank -> fuse + rank), driven by the parent's single clock so the
 * rows and the seam can never disagree. Every duration and counter is real trace telemetry; the
 * long LLM `explain` step is noted as a fact on the fuse row rather than animated (it never ranks,
 * and would otherwise dominate the teaser's pacing — the full /run replay shows it on the timeline).
 *
 * Two layouts: `strip` (compact 3-column pipeline readout above the convergence) and `list` (stacked).
 */
import { useMemo } from "react";

import { formatClock } from "@/lib/replay";
import { cn } from "@/lib/utils";
import type { TraceStage } from "@/types/trace";

type Leg = "cultural" | "audio" | "fuse";

const LEG_RING: Record<Leg, string> = {
  cultural: "border-cultural/40 bg-cultural/[0.06]",
  audio: "border-audio/40 bg-audio/[0.06]",
  fuse: "border-seam/40 bg-seam/[0.06]",
};
const LEG_FILL: Record<Leg, string> = {
  cultural: "bg-cultural",
  audio: "bg-audio",
  fuse: "bg-seam",
};
const LEG_DOT: Record<Leg, string> = {
  cultural: "bg-cultural",
  audio: "bg-audio",
  fuse: "bg-seam",
};

interface Fold {
  leg: Leg;
  label: string;
  ids: string[];
  describe: (by: Map<string, TraceStage>) => string;
}

const num = (s: TraceStage | undefined, k: string): number => Number(s?.counters[k] ?? 0);

const FOLDS: Fold[] = [
  {
    leg: "cultural",
    label: "The crowd",
    ids: ["aggregate", "gate1", "resolve"],
    describe: (by) =>
      `${num(by.get("aggregate"), "candidates")} to consider · ${num(by.get("resolve"), "found")} we could hear`,
  },
  {
    leg: "audio",
    label: "The sound",
    ids: ["seed", "gate2", "embed", "hnsw_lane"],
    describe: (by) => {
      const ready = num(by.get("embed"), "computed") + num(by.get("gate2"), "embedding_cache_hits");
      return ready > 0 ? `listened to ${ready}` : "no audio this time";
    },
  },
  {
    leg: "fuse",
    label: "The final list",
    ids: ["results"],
    describe: (by) => {
      const base = `top ${num(by.get("results"), "top")} picked`;
      // Disclose the long LLM write-up step's real duration even though the teaser doesn't animate it,
      // so the "quick preview" never reads as the whole recorded run (recorded-replay honesty).
      const explain = by.get("explain");
      return explain ? `${base} · +${formatClock(explain.t1_ms - explain.t0_ms)} write-up` : base;
    },
  },
];

function windowFor(ids: string[], by: Map<string, TraceStage>): [number, number] | null {
  const present = ids.map((id) => by.get(id)).filter(Boolean) as TraceStage[];
  if (present.length === 0) return null;
  return [Math.min(...present.map((s) => s.t0_ms)), Math.max(...present.map((s) => s.t1_ms))];
}

interface FoldWindow {
  fold: Fold;
  start: number;
  end: number;
}

/** The time-INVARIANT part: the stage lookup Map and each fold's [start, end] window. Pure in
 *  `stages`, so it's memoized once and never rebuilt per RAF frame (only fill/done depend on clockMs). */
function staticFolds(stages: TraceStage[]): { by: Map<string, TraceStage>; windows: FoldWindow[] } {
  const by = new Map(stages.map((s) => [s.stage, s] as const));
  const windows: FoldWindow[] = [];
  for (const fold of FOLDS) {
    const win = windowFor(fold.ids, by);
    if (!win) continue;
    windows.push({ fold, start: win[0], end: win[1] });
  }
  return { by, windows };
}

/** The folded mini-replay as a compact 3-column strip — the only layout used (above the convergence). */
export function FoldedStages({ stages, clockMs }: { stages: TraceStage[]; clockMs: number }) {
  const { by, windows } = useMemo(() => staticFolds(stages), [stages]);
  const states = windows.map(({ fold, start, end }) => {
    const span = Math.max(1, end - start);
    return {
      fold,
      start,
      end,
      fill: Math.min(1, Math.max(0, (clockMs - start) / span)),
      done: clockMs >= end,
    };
  });

  return (
    <ol className="grid grid-cols-1 gap-2 sm:grid-cols-3">
      {states.map(({ fold, fill, done, start, end }) => (
        <li key={fold.leg} className={cn("rounded-lg border px-3 py-2", LEG_RING[fold.leg], fill <= 0 && "opacity-45")}>
          <div className="flex items-baseline justify-between gap-2">
            <span className="flex items-center gap-1.5 text-xs font-medium">
              <span className={cn("size-1.5 rounded-full", LEG_DOT[fold.leg])} aria-hidden />
              {fold.label}
            </span>
            <span className="text-muted-foreground font-mono text-[10px] tabular-nums">
              {done ? formatClock(end - start) : fill > 0 ? formatClock(clockMs - start) : "·"}
            </span>
          </div>
          <div className="bg-border/60 mt-1.5 h-1 overflow-hidden rounded-full">
            <div className={cn("h-full rounded-full", LEG_FILL[fold.leg])} style={{ width: `${fill * 100}%` }} />
          </div>
          <p className="text-muted-foreground mt-1.5 min-h-3.5 truncate font-mono text-[10px] tabular-nums">
            {fill > 0 ? fold.describe(by) : ""}
          </p>
        </li>
      ))}
    </ol>
  );
}
