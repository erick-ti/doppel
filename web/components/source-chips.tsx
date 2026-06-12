import { Globe, Users } from "lucide-react";

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
 * Provenance chips for the sources that surfaced a result.
 *
 * Cultural sources (Last.fm / ListenBrainz) are color-keyed to the warm cultural accent; when both
 * surfaced a candidate, a "high consensus" badge marks the cross-source listener agreement.
 *
 * The v2 HNSW lane tags a result `["hnsw"]` — it was retrieved by global vibe/acoustic similarity
 * over the whole library, NOT by cultural co-listening. It gets the cool audio accent (the CLAP side
 * of the engine) and an honest "global vibe match" label, so it is never miscolored as, or counted
 * toward consensus with, a cultural source.
 */
export function SourceChips({ sources }: { sources: string[] }) {
  if (!sources || sources.length === 0) {
    return (
      <Badge variant="muted" title="No source recorded for this row">
        no source
      </Badge>
    );
  }

  // High consensus is a CULTURAL claim (cross-source listener agreement); the hnsw lane is a single
  // acoustic-retrieval source and never contributes to it.
  const highConsensus = sources.filter((s) => s !== "hnsw").length >= 2;

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {sources.map((s) =>
        s === "hnsw" ? (
          <Badge
            key={s}
            variant="audio"
            title="Retrieved by vibe/acoustic similarity across the whole library — not cultural co-listening"
          >
            <Globe aria-hidden />
            global vibe match
          </Badge>
        ) : (
          <Badge key={s} variant="cultural">
            {labelFor(s)}
          </Badge>
        ),
      )}
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
