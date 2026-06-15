/**
 * The above-the-fold mini-replay: the recorded run's 8 stages folded into the THREE legs
 * (cultural retrieval -> audio rerank -> fuse + rank), driven by the parent's single clock so the
 * rows and the seam can never disagree. Every duration and counter is real trace telemetry; the
 * long LLM `explain` step is noted as a fact on the fuse row rather than animated (it never ranks,
 * and would otherwise dominate the teaser's pacing — the full /run replay shows it on the timeline).
 *
 * Two layouts: `strip` (compact 3-column pipeline readout above the convergence) and `list` (stacked).
 */
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
    label: "Cultural retrieval",
    ids: ["aggregate", "gate1", "resolve"],
    describe: (by) =>
      `${num(by.get("aggregate"), "candidates")} candidates · ${num(by.get("resolve"), "found")} resolved`,
  },
  {
    leg: "audio",
    label: "Audio rerank",
    ids: ["seed", "gate2", "embed", "hnsw_lane"],
    describe: (by) => {
      const ready = num(by.get("embed"), "computed") + num(by.get("gate2"), "embedding_cache_hits");
      return ready > 0 ? `${ready} embeddings · CLAP cosine` : "cultural-only — no preview";
    },
  },
  {
    leg: "fuse",
    label: "Fuse + rank",
    ids: ["results"],
    describe: (by) => {
      const r = by.get("results");
      const explain = by.get("explain");
      const base = `top ${num(r, "top")} · ${num(r, "audio_scored")} audio-scored`;
      return explain ? `${base} · +${formatClock(explain.t1_ms - explain.t0_ms)} rationales` : base;
    },
  },
];

function windowFor(ids: string[], by: Map<string, TraceStage>): [number, number] | null {
  const present = ids.map((id) => by.get(id)).filter(Boolean) as TraceStage[];
  if (present.length === 0) return null;
  return [Math.min(...present.map((s) => s.t0_ms)), Math.max(...present.map((s) => s.t1_ms))];
}

interface FoldState {
  fold: Fold;
  fill: number;
  done: boolean;
  start: number;
  end: number;
}

function computeFolds(stages: TraceStage[], clockMs: number): { by: Map<string, TraceStage>; states: FoldState[] } {
  const by = new Map(stages.map((s) => [s.stage, s] as const));
  const states: FoldState[] = [];
  for (const fold of FOLDS) {
    const win = windowFor(fold.ids, by);
    if (!win) continue;
    const [start, end] = win;
    const span = Math.max(1, end - start);
    states.push({
      fold,
      start,
      end,
      fill: Math.min(1, Math.max(0, (clockMs - start) / span)),
      done: clockMs >= end,
    });
  }
  return { by, states };
}

/** The folded mini-replay as a compact 3-column strip — the only layout used (above the convergence). */
export function FoldedStages({ stages, clockMs }: { stages: TraceStage[]; clockMs: number }) {
  const { by, states } = computeFolds(stages, clockMs);

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
