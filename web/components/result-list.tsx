import { ResultCard } from "@/components/result-card";
import { batchStats } from "@/lib/scores";
import type { ResultItem } from "@/types/recommendation";

/**
 * The ranked result board. Results are audio-first ordered by the pipeline, so any cultural
 * backfill rows (not CLAP-reranked) sit at the tail — a visible divider marks that boundary,
 * faithful to the pipeline's ordering. With the current clean exports there is no backfill, so
 * the divider does not render; the logic is correct if a degraded export is added later.
 */
export function ResultList({ results }: { results: ResultItem[] }) {
  const batch = batchStats(results);
  // findIndex gives the first non-audio-scored row; > 0 means audio-scored rows precede it
  // (every row before the first false is true), so that index is exactly the divider boundary.
  const firstBackfillIdx = results.findIndex((r) => !r.was_audio_scored);
  const dividerIdx = firstBackfillIdx > 0 ? firstBackfillIdx : -1;

  return (
    <div className="flex flex-col gap-3">
      {results.map((item, i) => (
        <div key={`${item.position}-${item.mbid ?? item.title}`}>
          {i === dividerIdx && (
            <div className="my-4 flex items-center gap-3">
              <div className="bg-border h-px flex-1" />
              <span className="text-muted-foreground text-xs font-medium tracking-wide uppercase">
                From the crowd, not scored by sound
              </span>
              <div className="bg-border h-px flex-1" />
            </div>
          )}
          <ResultCard item={item} batch={batch} />
        </div>
      ))}
    </div>
  );
}
