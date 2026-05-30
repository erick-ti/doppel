import Link from "next/link";
import { ArrowLeft, ExternalLink, Wand2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import type { SeedDocument } from "@/types/recommendation";

/** Header for a results view: seed identity, echoed vibe, MusicBrainz deep-link, pair cross-link. */
export function SeedHeader({
  doc,
  pair,
}: {
  doc: SeedDocument;
  /** The paired run (plain <-> vibe-steered), if one was exported. */
  pair: { slug: string; label: string } | null;
}) {
  const vibe = doc.vibe != null && doc.vibe.trim().length > 0;
  const mbUrl = doc.seed.mbid
    ? `https://musicbrainz.org/recording/${doc.seed.mbid}`
    : null;

  return (
    <div className="flex flex-col gap-4">
      <Link
        href="/"
        className="text-muted-foreground hover:text-foreground inline-flex w-fit items-center gap-1.5 text-sm transition-colors"
      >
        <ArrowLeft className="size-4" aria-hidden />
        All seeds
      </Link>

      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="muted">{doc.meta.genre}</Badge>
        {vibe && (
          <Badge variant="audio">
            <Wand2 aria-hidden />
            vibe-steered
          </Badge>
        )}
      </div>

      <div>
        <h1 className="text-3xl font-bold tracking-tight sm:text-4xl">
          {doc.seed.title}
        </h1>
        <p className="text-muted-foreground mt-1 text-lg">{doc.seed.artist}</p>
      </div>

      {vibe && (
        <div className="border-audio/40 bg-audio/5 rounded-lg border-l-2 px-4 py-2">
          <span className="text-muted-foreground text-xs tracking-wide uppercase">
            Vibe steer
          </span>
          <p className="text-audio text-sm italic">&ldquo;{doc.vibe}&rdquo;</p>
        </div>
      )}

      <div className="text-muted-foreground flex flex-wrap items-center gap-x-4 gap-y-2 text-sm">
        {mbUrl ? (
          <a
            href={mbUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="hover:text-foreground inline-flex items-center gap-1.5 transition-colors"
          >
            MusicBrainz recording
            <ExternalLink className="size-3.5" aria-hidden />
          </a>
        ) : (
          <span>No MBID resolved for the seed</span>
        )}

        {pair && (
          <Link
            href={`/seed/${pair.slug}`}
            className="text-audio hover:text-audio/80 inline-flex items-center gap-1.5 font-medium transition-colors"
          >
            <Wand2 className="size-3.5" aria-hidden />
            {pair.label}
          </Link>
        )}
      </div>
    </div>
  );
}
