import { Check, CircleAlert } from "lucide-react";

import { LocalStamp } from "@/components/local-stamp";
import { RawJsonDialog } from "@/components/raw-json-dialog";
import { cn } from "@/lib/utils";
import type { SeedDocument } from "@/types/recommendation";

function StatusRow({
  ok,
  label,
  value,
}: {
  ok: boolean;
  label: string;
  value: string;
}) {
  return (
    <div className="flex items-center justify-between gap-3 py-1.5">
      <div className="flex items-center gap-2">
        {ok ? (
          // --seam (the recorded/fused register), NOT --ok green: this is a recorded RESULTS surface,
          // and the ops-status tokens (--ok / --warning) must never appear off the live ops panel
          // (invariant #8 token register — green here would borrow the live-up vocabulary).
          <Check className="text-seam size-4" aria-hidden />
        ) : (
          <CircleAlert className="text-muted-foreground size-4" aria-hidden />
        )}
        <span className="text-sm">{label}</span>
      </div>
      <span
        className={cn(
          "font-mono text-sm tabular-nums",
          ok ? "text-foreground" : "text-muted-foreground",
        )}
      >
        {value}
      </span>
    </div>
  );
}

/**
 * The honest "system status" readout — renders the response's `degradation` block and the
 * snapshot's provenance stamp, plus a one-click view of the entire raw response.
 */
export function TransparencyPanel({ doc }: { doc: SeedDocument }) {
  const d = doc.degradation;
  const m = doc.meta;
  const degradedKeys = Object.keys(d.degraded_sources);
  // The mood weight (β) only does anything when a mood was actually given; on a plain run the score
  // is all sound, so don't assert a mood split that wasn't applied.
  const hasMood = !!doc.vibe?.trim();

  return (
    <div className="rounded-xl border p-5">
      <div className="grid gap-6 md:grid-cols-2">
        <div>
          <h3 className="text-muted-foreground mb-2 text-xs font-semibold tracking-wide uppercase">
            What ran, what didn&rsquo;t
          </h3>
          <div className="divide-border divide-y">
            <StatusRow
              ok={d.seed_audio_scored}
              label="Listened to your song"
              value={d.seed_audio_scored ? "yes" : "no"}
            />
            <StatusRow
              ok={d.cultural_backfill_count === 0}
              label="Crowd-only picks"
              value={`${d.cultural_backfill_count}`}
            />
            <StatusRow
              ok={d.rationales_available}
              label="Write-ups"
              value={d.rationales_available ? "yes" : "no"}
            />
            <StatusRow
              ok={degradedKeys.length === 0}
              label="Any sources down"
              value={degradedKeys.length === 0 ? "none" : degradedKeys.join(", ")}
            />
          </div>
        </div>

        <div>
          <h3 className="text-muted-foreground mb-2 text-xs font-semibold tracking-wide uppercase">
            About this snapshot
          </h3>
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 font-mono text-xs">
            <dt className="text-muted-foreground">saved</dt>
            <dd className="tabular-nums">
              <LocalStamp iso={m.exported_at} mode="datetime" />
            </dd>
            <dt className="text-muted-foreground">build</dt>
            <dd>
              {m.git_sha}
              {m.git_dirty && (
                <span
                  className="text-muted-foreground"
                  title="Saved from a work-in-progress build (uncommitted changes)"
                >
                  {" "}
                  (work in progress)
                </span>
              )}
            </dd>
            <dt className="text-muted-foreground">audio model</dt>
            <dd className="break-all">{m.clap_model_version}</dd>
            <dt className="text-muted-foreground">blend</dt>
            <dd>
              {hasMood
                ? `${Math.round(m.alpha * 100)}% sound · ${Math.round(m.beta * 100)}% mood`
                : "all sound (no mood added)"}
            </dd>
          </dl>
        </div>
      </div>

      <div className="mt-5 flex justify-end border-t pt-3">
        <RawJsonDialog
          data={doc}
          title={`${doc.seed.title} by ${doc.seed.artist}`}
          description="Everything behind this page, exactly as it was saved."
          triggerLabel="See the raw data"
        />
      </div>
    </div>
  );
}
