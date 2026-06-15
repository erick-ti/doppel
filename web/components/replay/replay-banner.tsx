import { CircleDot } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { shaStamp, type PairProvenance } from "@/lib/replay";

/**
 * The always-visible honesty banner above a replay (v1.2 cardinal rule): this is a RECORDED run,
 * never a live request. When the seed doc and the trace were captured in different export batches
 * (a `--trace-only` refresh) the stamps are shown SEPARATELY — "results frozen X · telemetry
 * captured Y" — never one frame-accuracy claim spanning two runs.
 */
export function ReplayBanner({
  provenance,
  mode,
  speedLabel,
}: {
  provenance: PairProvenance;
  mode: string;
  speedLabel: string;
}) {
  const p = provenance;
  return (
    <div className="bg-card/40 flex flex-wrap items-center gap-x-3 gap-y-1.5 rounded-xl border px-4 py-2.5 font-mono text-xs">
      <span className="text-foreground inline-flex items-center gap-1.5 font-semibold tracking-wide uppercase">
        <CircleDot className="text-seam size-3.5" aria-hidden />
        Recorded run
      </span>
      {/* outline, not a leg accent — cold/warm is a cache state, not the cultural/audio duality */}
      <Badge variant="outline" className="font-mono uppercase">
        {mode}
      </Badge>
      <span className="text-muted-foreground">
        {p.sameCapture ? (
          <>
            captured {p.traceDate} · commit{" "}
            <span className="text-foreground/80">{shaStamp(p.traceSha, p.traceDirty)}</span>
          </>
        ) : (
          <>
            results frozen {p.docDate} (
            <span className="text-foreground/80">{shaStamp(p.docSha, p.docDirty)}</span>) · telemetry
            captured {p.traceDate} (
            <span className="text-foreground/80">{shaStamp(p.traceSha, p.traceDirty)}</span>)
          </>
        )}
      </span>
      <span className="text-muted-foreground/50" aria-hidden>
        ·
      </span>
      <span className="text-muted-foreground">{speedLabel}</span>
      <span className="text-muted-foreground/50" aria-hidden>
        ·
      </span>
      <span className="text-muted-foreground">replay of persisted telemetry — not a live request</span>
    </div>
  );
}
