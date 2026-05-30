import { Users } from "lucide-react";

import { Badge } from "@/components/ui/badge";

/** Human-readable labels for the cultural candidate sources. */
const SOURCE_LABELS: Record<string, string> = {
  lastfm: "Last.fm",
  listenbrainz: "ListenBrainz",
};

function labelFor(source: string): string {
  return SOURCE_LABELS[source] ?? source;
}

/**
 * Cultural-source chips (color-keyed to the cultural accent). When both sources surfaced a
 * candidate, a "high consensus" badge marks the cross-source agreement.
 */
export function SourceChips({ sources }: { sources: string[] }) {
  if (!sources || sources.length === 0) {
    return (
      <Badge variant="muted" title="No cultural source recorded for this row">
        no source
      </Badge>
    );
  }

  const highConsensus = sources.length >= 2;

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {sources.map((s) => (
        <Badge key={s} variant="cultural">
          {labelFor(s)}
        </Badge>
      ))}
      {highConsensus && (
        <Badge
          variant="cultural"
          className="bg-cultural/25"
          title="Surfaced by both cultural sources — strong cross-source listener agreement"
        >
          <Users aria-hidden />
          high consensus
        </Badge>
      )}
    </div>
  );
}
