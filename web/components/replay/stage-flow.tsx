"use client";

import { Check } from "lucide-react";

import { formatClock, specFor, type StageLeg } from "@/lib/replay";
import { cn } from "@/lib/utils";
import type { TraceStage } from "@/types/trace";

/** Same leg→ring vocabulary as the how-it-works ArchitectureDag (its map is module-private). */
const LEG_RING: Record<StageLeg, string> = {
  cultural: "border-cultural/40 bg-cultural/5",
  audio: "border-audio/40 bg-audio/5",
  neutral: "border-border bg-card/40",
};

const LEG_FILL: Record<StageLeg, string> = {
  cultural: "bg-cultural",
  audio: "bg-audio",
  neutral: "bg-muted-foreground",
};

type Status = "pending" | "running" | "done";

function statusOf(stage: TraceStage, t: number): Status {
  if (t >= stage.t1_ms) return "done";
  if (t >= stage.t0_ms && stage.t1_ms > stage.t0_ms) return "running";
  return "pending";
}

/** Counts of fired event ticks at playback time t — the honest mid-stage count-up (real events). */
function firedEvents(stage: TraceStage, t: number): Map<string, number> {
  const fired = new Map<string, number>();
  for (const e of stage.events ?? []) {
    if (e.t_ms <= t) fired.set(e.kind, (fired.get(e.kind) ?? 0) + 1);
  }
  return fired;
}

function runningLine(stage: TraceStage, t: number): string {
  const fired = firedEvents(stage, t);
  if (stage.stage === "resolve") {
    const cached = fired.get("resolve.cache_hit") ?? 0;
    const live = fired.get("resolve.live") ?? 0;
    return `${cached + live} candidates · ${cached} cached · ${live} live MusicBrainz lookups`;
  }
  if (stage.stage === "embed") {
    const computed = fired.get("embed.computed") ?? 0;
    return `${computed} previews embedded…`;
  }
  return `running… ${formatClock(t - stage.t0_ms)} elapsed`;
}

function StageRow({ stage, t }: { stage: TraceStage; t: number }) {
  const spec = specFor(stage);
  const status = statusOf(stage, t);
  const durationMs = stage.t1_ms - stage.t0_ms;
  const progress = status === "done" ? 1 : status === "running" ? (t - stage.t0_ms) / Math.max(1, durationMs) : 0;

  return (
    <li
      className={cn(
        "rounded-lg border p-3 transition-opacity",
        LEG_RING[spec.leg],
        status === "pending" && "opacity-40",
      )}
      aria-current={status === "running" ? "step" : undefined}
    >
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-sm font-medium">{spec.label}</span>
        <span className="text-muted-foreground font-mono text-[11px] tabular-nums">
          {status === "done" ? (
            <span className="inline-flex items-center gap-1">
              <Check className="size-3" aria-hidden />
              {formatClock(durationMs)}
            </span>
          ) : status === "running" ? (
            formatClock(t - stage.t0_ms)
          ) : (
            "·"
          )}
        </span>
      </div>
      {/* measured-progress fill: width is playback-time-derived from the recorded segment, so the
          bar's pace IS the run's pace (compressed by the labeled speed factor, never re-eased) */}
      <div className="bg-border/60 mt-2 h-1 overflow-hidden rounded-full">
        <div
          className={cn("h-full rounded-full", LEG_FILL[spec.leg])}
          style={{ width: `${Math.min(100, progress * 100)}%` }}
        />
      </div>
      <p className="text-muted-foreground mt-2 min-h-4 font-mono text-xs tabular-nums">
        {status === "done" ? spec.describe(stage.counters) : status === "running" ? runningLine(stage, t) : ""}
      </p>
    </li>
  );
}

/**
 * The animated pipeline flow: one row per RECORDED stage (a stage the run never reached is simply
 * absent — degraded runs render honestly short). Driven entirely by the parent's playback clock.
 */
export function StageFlow({ stages, t }: { stages: TraceStage[]; t: number }) {
  return (
    <ol className="flex flex-col gap-2">
      {stages.map((stage) => (
        <StageRow key={stage.stage} stage={stage} t={t} />
      ))}
    </ol>
  );
}
