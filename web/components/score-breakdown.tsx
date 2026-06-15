import {
  AXES,
  axisFill,
  axisValue,
  formatScore,
  type AxisSpec,
  type BatchStats,
  type Leg,
} from "@/lib/scores";
import { cn } from "@/lib/utils";
import type { ResultItem } from "@/types/recommendation";

/** Accent color classes per retrieval leg (the two-accent duality + the fused --seam output). */
const LEG_TEXT: Record<Leg, string> = {
  audio: "text-audio",
  cultural: "text-cultural",
  fused: "text-seam",
};

const LEG_BAR: Record<Leg, string> = {
  audio: "bg-audio",
  cultural: "bg-cultural",
  // The fused axis IS the two legs resolving into one — a gradient from cultural through the --seam
  // (the same fused color as the hero's convergence rail) to audio.
  fused: "bg-gradient-to-r from-cultural via-seam to-audio",
};

function AxisRow({
  spec,
  item,
  batch,
}: {
  spec: AxisSpec;
  item: ResultItem;
  batch: BatchStats;
}) {
  const value = axisValue(item, spec.key);
  const fill = axisFill(spec.key, value, batch);

  return (
    <div className="grid grid-cols-[1fr_auto] items-baseline gap-x-4 gap-y-1.5">
      <div className="flex items-center gap-2">
        <span className="text-sm font-medium">{spec.label}</span>
        <span className="text-muted-foreground text-[10px] font-medium tracking-wide uppercase">
          {spec.unit}
        </span>
      </div>
      <span
        className={cn(
          "font-mono text-sm tabular-nums",
          value == null ? "text-muted-foreground" : LEG_TEXT[spec.leg],
        )}
      >
        {formatScore(spec.key, value)}
      </span>

      <div className="bg-muted col-span-2 h-1.5 w-full overflow-hidden rounded-full">
        {fill == null ? (
          <div
            className="h-full w-full opacity-40"
            style={{
              background:
                "repeating-linear-gradient(45deg, var(--muted-foreground) 0 2px, transparent 2px 6px)",
            }}
            aria-hidden
          />
        ) : (
          <div
            className={cn("h-full rounded-full", LEG_BAR[spec.leg])}
            style={{ width: `${Math.max(fill * 100, 1.5)}%` }}
            aria-hidden
          />
        )}
      </div>

      <p className="text-muted-foreground col-span-2 text-xs leading-relaxed">
        {spec.caption}
      </p>
    </div>
  );
}

/**
 * The four-axis score breakdown. Each axis renders with its own correct semantics — a uniform
 * 0-100% bar would lie on every one (see `lib/scores.ts`). The displayed number is always the
 * real value; the bar is a captioned visual aid only.
 */
export function ScoreBreakdown({
  item,
  batch,
}: {
  item: ResultItem;
  batch: BatchStats;
}) {
  return (
    <div className="flex flex-col gap-5">
      {AXES.map((spec) => (
        <AxisRow key={spec.key} spec={spec} item={item} batch={batch} />
      ))}
    </div>
  );
}
