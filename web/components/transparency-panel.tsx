import { Check, CircleAlert } from "lucide-react";

import { RawJsonDialog } from "@/components/raw-json-dialog";
import { cn } from "@/lib/utils";
import type { SeedDocument } from "@/types/recommendation";

/** Format the export timestamp deterministically (no locale/timezone drift on static build). */
function formatExportedAt(iso: string): string {
  return iso.replace("T", " ").replace("+00:00", " UTC").replace("Z", " UTC");
}

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
          <Check className="size-4 text-emerald-400" aria-hidden />
        ) : (
          <CircleAlert className="text-cultural size-4" aria-hidden />
        )}
        <span className="text-sm">{label}</span>
      </div>
      <span
        className={cn(
          "font-mono text-sm tabular-nums",
          ok ? "text-foreground" : "text-cultural",
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

  return (
    <div className="rounded-xl border p-5">
      <div className="grid gap-6 md:grid-cols-2">
        <div>
          <h3 className="text-muted-foreground mb-2 text-xs font-semibold tracking-wide uppercase">
            System status
          </h3>
          <div className="divide-border divide-y">
            <StatusRow
              ok={d.seed_audio_scored}
              label="Seed audio-scored"
              value={d.seed_audio_scored ? "yes" : "no (cultural-only)"}
            />
            <StatusRow
              ok={d.cultural_backfill_count === 0}
              label="Cultural backfill"
              value={`${d.cultural_backfill_count} rows`}
            />
            <StatusRow
              ok={d.rationales_available}
              label="LLM rationales"
              value={d.rationales_available ? "available" : "unavailable"}
            />
            <StatusRow
              ok={degradedKeys.length === 0}
              label="Degraded sources"
              value={degradedKeys.length === 0 ? "none" : degradedKeys.join(", ")}
            />
          </div>
        </div>

        <div>
          <h3 className="text-muted-foreground mb-2 text-xs font-semibold tracking-wide uppercase">
            Snapshot provenance
          </h3>
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 font-mono text-xs">
            <dt className="text-muted-foreground">exported</dt>
            <dd className="tabular-nums">{formatExportedAt(m.exported_at)}</dd>
            <dt className="text-muted-foreground">git</dt>
            <dd>
              {m.git_sha}
              {m.git_dirty && (
                <span className="text-cultural" title="Exported from a dirty working tree">
                  {" "}
                  (dirty)
                </span>
              )}
            </dd>
            <dt className="text-muted-foreground">model</dt>
            <dd className="break-all">{m.clap_model_version}</dd>
            <dt className="text-muted-foreground">fusion</dt>
            <dd>
              α={m.alpha} · β={m.beta} · N={m.resolve_candidate_limit}
            </dd>
          </dl>
        </div>
      </div>

      <div className="mt-5 flex justify-end border-t pt-3">
        <RawJsonDialog
          data={doc}
          title={`${doc.seed.title} — full response`}
          description="The entire frozen seed document: the recommendation response body plus the export-only coverage and meta keys."
          triggerLabel="View full response JSON"
        />
      </div>
    </div>
  );
}
