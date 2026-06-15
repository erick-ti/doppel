import Link from "next/link";
import { SlidersHorizontal } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Fingerprint } from "@/components/fingerprint";
import { fingerprintData } from "@/lib/fingerprint";
import { isVibeSteered } from "@/lib/seeds";
import type { SeedDocument } from "@/types/recommendation";

/** A gallery tile. The "cover" is the seed's earned signal fingerprint (lib/fingerprint.ts) — its
 *  real audio/cultural/fused telemetry rendered as the convergence motif, so every tile is distinct
 *  and the imagery is earned by the engine, not a letter on a generic gradient. */
export function SeedCard({ doc }: { doc: SeedDocument }) {
  const vibe = isVibeSteered(doc);
  const fp = fingerprintData(doc);

  return (
    <Link
      href={`/seed/${doc.meta.slug}`}
      className="group focus-visible:ring-ring rounded-xl focus-visible:ring-2 focus-visible:outline-none"
    >
      <Card className="hover:border-seam/40 gap-0 overflow-hidden py-0 transition-colors">
        <div className="bg-background/40 relative aspect-[16/10] overflow-hidden border-b">
          <Fingerprint data={fp} variant="cover" />
          <Badge
            variant="muted"
            className="bg-background/70 absolute top-3 left-3 font-mono text-[10px] backdrop-blur"
          >
            {doc.meta.genre}
          </Badge>
          {vibe && (
            <Badge
              variant="audio"
              className="bg-background/70 absolute top-3 right-3 backdrop-blur"
            >
              <SlidersHorizontal aria-hidden />
              vibe-steered
            </Badge>
          )}
        </div>

        <div className="flex flex-col gap-1 p-4">
          <h3 className="group-hover:text-seam truncate font-display font-semibold tracking-tight transition-colors">
            {doc.seed.title}
          </h3>
          <p className="text-muted-foreground truncate text-sm">
            {doc.seed.artist}
          </p>
          {vibe && (
            <p className="text-cultural mt-0.5 truncate text-xs italic">
              &ldquo;{doc.vibe}&rdquo;
            </p>
          )}
          <p className="text-muted-foreground mt-2 font-mono text-[11px] tabular-nums">
            {doc.coverage.audio_scored} audio-scored ·{" "}
            {doc.coverage.found_ratio != null
              ? `${(doc.coverage.found_ratio * 100).toFixed(0)}% resolved`
              : "n/a resolved"}
          </p>
        </div>
      </Card>
    </Link>
  );
}
