import Link from "next/link";

import { SeamRule } from "@/components/seam-rule";
import { cn, linkFocus } from "@/lib/utils";

export function SiteFooter() {
  return (
    <footer className="mt-20">
      <div className="text-muted-foreground mx-auto w-full max-w-6xl px-5 py-8 text-center text-xs leading-relaxed">
        <SeamRule className="mb-8" />
        <p className="mx-auto max-w-3xl">
          Everything here comes from <strong>real</strong> runs of the engine:
          real sound scores, real Deezer links, real write-ups. No audio is
          stored or played here, and the live engine never runs from this site.
          Each page is a saved snapshot of exactly what produced it.
        </p>
        <p className="mt-3 font-mono">
          Doppel · songs that sound like the one you love.
        </p>
        <p className="mt-3">
          <Link
            href="/status"
            className={cn(
              "hover:text-foreground underline-offset-4 transition-colors hover:underline",
              linkFocus,
            )}
          >
            System status
          </Link>
        </p>
      </div>
    </footer>
  );
}
