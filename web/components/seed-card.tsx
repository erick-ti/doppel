import Link from "next/link";
import { Wand2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { isVibeSteered } from "@/lib/seeds";
import type { SeedDocument } from "@/types/recommendation";

/** Consistent two-leg gradient "cover" (cultural -> audio) — branded, art-free, invariant-safe. */
const COVER_STYLE: React.CSSProperties = {
  background:
    "linear-gradient(135deg, color-mix(in oklab, var(--cultural) 26%, var(--card)), color-mix(in oklab, var(--audio) 26%, var(--card)))",
};

/** A gallery tile. Clicking navigates instantly to the frozen results view (no round-trip). */
export function SeedCard({ doc }: { doc: SeedDocument }) {
  const vibe = isVibeSteered(doc);
  const initial = doc.seed.title.trim().charAt(0).toUpperCase() || "?";

  return (
    <Link
      href={`/seed/${doc.meta.slug}`}
      className="group focus-visible:ring-ring rounded-xl focus-visible:ring-2 focus-visible:outline-none"
    >
      <Card className="hover:border-foreground/25 gap-0 overflow-hidden py-0 transition-colors">
        <div
          className="relative flex aspect-[16/10] items-center justify-center"
          style={COVER_STYLE}
        >
          <span className="font-sans text-6xl font-bold text-white/85 mix-blend-overlay select-none">
            {initial}
          </span>
          <Badge
            variant="muted"
            className="bg-background/70 absolute top-3 left-3 backdrop-blur"
          >
            {doc.meta.genre}
          </Badge>
          {vibe && (
            <Badge
              variant="audio"
              className="bg-background/70 absolute top-3 right-3 backdrop-blur"
            >
              <Wand2 aria-hidden />
              vibe-steered
            </Badge>
          )}
        </div>

        <div className="flex flex-col gap-1 p-4">
          <h3 className="group-hover:text-audio truncate font-semibold tracking-tight transition-colors">
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
