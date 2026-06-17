import { ArrowDown, ArrowUp, AudioLines, ExternalLink } from "lucide-react";

import { RawJsonDialog } from "@/components/raw-json-dialog";
import { ScoreBreakdown } from "@/components/score-breakdown";
import { SourceChips } from "@/components/source-chips";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import type { RankDelta } from "@/lib/rank-delta";
import { axisFill, axisValue, type AxisKey, type BatchStats } from "@/lib/scores";
import { cn, linkFocus } from "@/lib/utils";
import type { ResultItem } from "@/types/recommendation";

/**
 * How this row moved once you add a mood — shown only on the mood side of the toggle. The visible
 * glyph is aria-hidden; the full phrase rides on role="img" + aria-label so screen readers announce
 * e.g. "Up 6 places with the mood" rather than a bare "6".
 */
function RankDeltaBadge({ delta }: { delta: RankDelta }) {
  if (delta.kind === "same") {
    return (
      <span
        role="img"
        aria-label="Same spot, with or without the mood"
        title="Same spot, with or without the mood"
        className="text-muted-foreground inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 font-mono text-[11px] tabular-nums"
      >
        <span aria-hidden>no change</span>
      </span>
    );
  }
  if (delta.kind === "new") {
    return (
      <span
        role="img"
        aria-label="New when you add the mood"
        title="New when you add the mood"
        className="bg-audio/15 text-audio inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] font-semibold tracking-wide uppercase"
      >
        <span aria-hidden>New</span>
      </span>
    );
  }
  const up = delta.kind === "up";
  const label = `${up ? "Up" : "Down"} ${delta.by} ${delta.by === 1 ? "place" : "places"} with the mood`;
  return (
    <span
      role="img"
      aria-label={label}
      title={label}
      className={cn(
        "inline-flex items-center gap-0.5 rounded-md px-1.5 py-0.5 font-mono text-[11px] font-medium tabular-nums",
        up ? "bg-seam/15 text-seam" : "bg-muted text-muted-foreground",
      )}
    >
      {up ? (
        <ArrowUp className="size-3" aria-hidden />
      ) : (
        <ArrowDown className="size-3" aria-hidden />
      )}
      <span aria-hidden>{delta.by}</span>
    </span>
  );
}

/** A compact per-row score profile — the row's own axes (audio · vibe · fused · cultural) as tiny
 *  leg-colored bars from the real values, so every result carries an earned glyph (the fingerprint
 *  motif at row scale), not just the seed gallery. */
function RowSpark({ item, batch }: { item: ResultItem; batch: BatchStats }) {
  const bars: { key: AxisKey; cls: string }[] = [
    { key: "audio", cls: "bg-audio" },
    ...(item.vibe_text_score != null ? [{ key: "vibe" as const, cls: "bg-audio-deep" }] : []),
    { key: "combined", cls: "bg-seam" },
    { key: "cultural", cls: "bg-cultural" },
  ];
  return (
    <div className="flex h-7 items-end gap-[3px]" aria-hidden title="Sound, blend, and crowd scores">
      {bars.map((b) => {
        const f = axisFill(b.key, axisValue(item, b.key), batch);
        // A null axis (audio/fused on a cultural-backfill row) has NO real value — render a faint
        // neutral stub, never a colored bar, so the glyph can't imply a score that doesn't exist.
        if (f == null) {
          return <div key={b.key} className="bg-muted-foreground/25 h-[6%] w-[3px] rounded-full" />;
        }
        return (
          <div
            key={b.key}
            className={cn("w-[3px] rounded-full", b.cls)}
            style={{ height: `${Math.max(10, f * 100)}%` }}
          />
        );
      })}
    </div>
  );
}

/**
 * One recommended track. Renders only real `ResultItem` fields, every nullable one guarded:
 * `deezer_url`, `rationale`, and all four scores can be null and degrade gracefully here.
 * The Deezer affordance is a track-PAGE link, never inline audio (invariant #2).
 */
export function ResultCard({
  item,
  batch,
  delta,
}: {
  item: ResultItem;
  batch: BatchStats;
  /** Rank movement vs the plain run — only supplied on the vibe-steered side of the toggle. */
  delta?: RankDelta | null;
}) {
  return (
    <Card className="gap-0 overflow-hidden py-0">
      <div className="flex flex-col gap-4 p-5">
        {/* Header: rank + title/artist + audio-scored badge. On narrow phones the badge column wraps
            to its own full-width line (max-sm:basis-full) so a long title keeps the row; from sm up it
            returns to the right-aligned column. */}
        <div className="flex flex-wrap items-start gap-x-4 gap-y-3">
          <div
            className={cn(
              "flex size-9 shrink-0 items-center justify-center rounded-md font-mono text-sm font-semibold tabular-nums",
              item.position === 1
                ? "bg-audio/15 text-audio"
                : "bg-muted text-muted-foreground",
            )}
            aria-label={`Rank ${item.position}`}
          >
            {item.position}
          </div>

          <div className="min-w-0 flex-1">
            <h3 className="font-display leading-tight font-semibold tracking-tight">
              {item.title}
            </h3>
            <p className="text-muted-foreground text-sm">{item.artist}</p>
          </div>

          <div className="flex shrink-0 items-center gap-2 max-sm:basis-full sm:flex-col sm:items-end sm:gap-1.5">
            <RowSpark item={item} batch={batch} />
            {item.was_audio_scored ? (
              <Badge variant="audio" title="Ranked by how it actually sounds">
                <AudioLines aria-hidden />
                scored by sound
              </Badge>
            ) : (
              <Badge
                variant="muted"
                title="A pick from the crowd that we couldn't score by sound"
              >
                crowd pick
              </Badge>
            )}
            {delta && <RankDeltaBadge delta={delta} />}
          </div>
        </div>

        {/* Cultural source chips */}
        <SourceChips sources={item.sources} />

        {/* LLM rationale — null-checked per row (degrades per-row on a partial LLM response) */}
        {item.rationale ? (
          <p className="text-foreground/90 text-sm leading-relaxed">
            {item.rationale}
          </p>
        ) : (
          <p className="text-muted-foreground text-sm italic">
            No write-up for this one.
          </p>
        )}

        {/* Deezer track-PAGE link (never inline audio) */}
        {item.deezer_url ? (
          <a
            href={item.deezer_url}
            target="_blank"
            rel="noopener noreferrer"
            className={cn(
              linkFocus,
              "border-border hover:border-audio/60 hover:text-audio inline-flex w-fit items-center gap-1.5 rounded-md border px-3 py-1.5 text-sm font-medium transition-colors",
            )}
          >
            Listen on Deezer
            <span className="sr-only"> (opens in a new tab)</span>
            <ExternalLink className="size-3.5" aria-hidden />
          </a>
        ) : (
          <span className="text-muted-foreground text-xs">
            No Deezer link for this one.
          </span>
        )}
      </div>

      {/* Expandable four-axis score breakdown + raw JSON */}
      <div className="border-border bg-background/40 border-t px-5">
        <Accordion type="single" collapsible>
          <AccordionItem value="scores" className="border-b-0">
            <AccordionTrigger>See the numbers</AccordionTrigger>
            <AccordionContent>
              <ScoreBreakdown item={item} batch={batch} />
              <div className="mt-4 flex justify-end">
                <RawJsonDialog
                  data={item}
                  title={`${item.title} by ${item.artist}`}
                  description="The raw data behind this row. Every number you see comes from here."
                />
              </div>
            </AccordionContent>
          </AccordionItem>
        </Accordion>
      </div>
    </Card>
  );
}
