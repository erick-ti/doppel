import { ExternalLink, Sparkles } from "lucide-react";

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
import type { BatchStats } from "@/lib/scores";
import { cn } from "@/lib/utils";
import type { ResultItem } from "@/types/recommendation";

/**
 * One recommended track. Renders only real `ResultItem` fields, every nullable one guarded:
 * `deezer_url`, `rationale`, and all four scores can be null and degrade gracefully here.
 * The Deezer affordance is a track-PAGE link, never inline audio (invariant #2).
 */
export function ResultCard({
  item,
  batch,
}: {
  item: ResultItem;
  batch: BatchStats;
}) {
  return (
    <Card className="gap-0 overflow-hidden py-0">
      <div className="flex flex-col gap-4 p-5">
        {/* Header: rank + title/artist + audio-scored badge */}
        <div className="flex items-start gap-4">
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
            <h3 className="leading-tight font-semibold tracking-tight">
              {item.title}
            </h3>
            <p className="text-muted-foreground text-sm">{item.artist}</p>
          </div>

          {item.was_audio_scored ? (
            <Badge variant="audio" title="Reranked by the CLAP audio embedding">
              <Sparkles aria-hidden />
              CLAP-reranked
            </Badge>
          ) : (
            <Badge
              variant="muted"
              title="Surfaced by cultural retrieval only — not audio-reranked"
            >
              cultural backfill
            </Badge>
          )}
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
            No rationale generated for this row.
          </p>
        )}

        {/* Deezer track-PAGE link (never inline audio) */}
        {item.deezer_url ? (
          <a
            href={item.deezer_url}
            target="_blank"
            rel="noopener noreferrer"
            className="border-border hover:border-audio/60 hover:text-audio inline-flex w-fit items-center gap-1.5 rounded-md border px-3 py-1.5 text-sm font-medium transition-colors"
          >
            Listen on Deezer
            <ExternalLink className="size-3.5" aria-hidden />
          </a>
        ) : (
          <span className="text-muted-foreground text-xs">
            No Deezer link available for this track.
          </span>
        )}
      </div>

      {/* Expandable four-axis score breakdown + raw JSON */}
      <div className="border-border bg-background/40 border-t px-5">
        <Accordion type="single" collapsible>
          <AccordionItem value="scores" className="border-b-0">
            <AccordionTrigger>Score breakdown</AccordionTrigger>
            <AccordionContent>
              <ScoreBreakdown item={item} batch={batch} />
              <div className="mt-4 flex justify-end">
                <RawJsonDialog
                  data={item}
                  title={`${item.title} — ${item.artist}`}
                  description="The raw ResultItem row from the recommendation response — every rendered number is a field here."
                />
              </div>
            </AccordionContent>
          </AccordionItem>
        </Accordion>
      </div>
    </Card>
  );
}
