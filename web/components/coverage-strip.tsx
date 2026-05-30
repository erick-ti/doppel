import { ChevronRight } from "lucide-react";

import type { Coverage, ExportMeta } from "@/types/recommendation";

/**
 * Static retrieve -> rerank funnel summary, driven by this seed's real `coverage` counts. A
 * single readable pass: cultural candidates -> resolved -> found -> audio-scored. (The animated
 * narrowing version is Phase 2; this is the honest static foundation.)
 */
export function CoverageStrip({
  coverage,
  meta,
}: {
  coverage: Coverage;
  meta: ExportMeta;
}) {
  const stages = [
    {
      value: coverage.candidate_count,
      label: "cultural candidates",
      note: "Last.fm + ListenBrainz, deduped + RRF-fused (k=60)",
    },
    {
      value: coverage.resolve_attempted,
      label: "resolve attempts",
      note: `top ${meta.resolve_candidate_limit} by rank · MusicBrainz + Deezer verify`,
    },
    {
      value: coverage.resolved_found,
      label: "found",
      note:
        coverage.resolved_not_found > 0
          ? `${coverage.resolved_not_found} not found`
          : "full coverage",
    },
    {
      value: coverage.audio_scored,
      label: "audio-scored",
      note: "CLAP rerank → top 10",
    },
  ];

  return (
    <div className="rounded-xl border p-5">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-stretch">
        {stages.map((stage, i) => (
          <div key={stage.label} className="flex flex-1 items-center gap-4">
            <div className="flex-1">
              <div className="font-mono text-2xl font-semibold tabular-nums">
                {stage.value}
              </div>
              <div className="text-sm font-medium">{stage.label}</div>
              <div className="text-muted-foreground mt-0.5 text-xs leading-snug">
                {stage.note}
              </div>
            </div>
            {i < stages.length - 1 && (
              <ChevronRight
                className="text-muted-foreground hidden size-5 shrink-0 sm:block"
                aria-hidden
              />
            )}
          </div>
        ))}
      </div>

      <div className="text-muted-foreground mt-4 border-t pt-3 font-mono text-[11px] tabular-nums">
        {coverage.embeddings_cache_hits ?? 0} embeddings from cache ·{" "}
        {coverage.embeddings_computed ?? 0} computed · {coverage.latency_ms} ms
        total
        <span className="text-muted-foreground">
          {" "}
          (cache-first: warm runs skip re-embedding)
        </span>
      </div>
    </div>
  );
}
