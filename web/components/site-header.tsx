import Link from "next/link";

import { cn, linkFocus } from "@/lib/utils";

/** The Doppel mark — the seam motif in miniature: two legs converging into a fused rail. */
function SeamMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 16 16" className={className} aria-hidden fill="none">
      <path d="M1 4 C5 4, 6 8, 8 8" className="stroke-cultural" strokeWidth="1.5" strokeLinecap="round" />
      <path d="M15 4 C11 4, 10 8, 8 8" className="stroke-audio" strokeWidth="1.5" strokeLinecap="round" />
      <line x1="8" y1="8" x2="8" y2="14" className="stroke-seam" strokeWidth="1.5" strokeLinecap="round" />
      <circle cx="8" cy="8" r="1.8" className="fill-seam" />
    </svg>
  );
}

export function SiteHeader() {
  return (
    <header className="border-border/60 bg-background/80 sticky top-0 z-40 border-b backdrop-blur">
      <div className="mx-auto flex h-14 w-full max-w-6xl items-center justify-between gap-3 px-5">
        <Link href="/" className={cn("group flex items-center gap-2", linkFocus)}>
          <SeamMark className="size-4 shrink-0" />
          {/* Below 360px the brand wordmark + 3 nav links don't fit; drop to the mark only so no nav
              link gets clipped (and unreachable, since the page is overflow-x:clip). */}
          <span className="font-display text-lg font-semibold tracking-tight max-[359px]:hidden">
            Doppel
          </span>
          <span className="text-muted-foreground hidden font-mono text-xs sm:inline">
            songs that feel like the one you love
          </span>
        </Link>
        <nav className="flex items-center gap-2.5 sm:gap-3" aria-label="Primary">
          <Link
            href="/how-it-works"
            className={cn(
              "text-muted-foreground hover:text-foreground text-sm font-medium whitespace-nowrap transition-colors",
              linkFocus,
            )}
          >
            How it works
          </Link>
          <span className="text-muted-foreground/30 hidden select-none sm:inline" aria-hidden>
            |
          </span>
          <Link
            href="/deep-dive"
            className={cn(
              "text-muted-foreground hover:text-foreground text-sm font-medium whitespace-nowrap transition-colors",
              linkFocus,
            )}
          >
            Deep dive
          </Link>
          <span className="text-muted-foreground/30 hidden select-none sm:inline" aria-hidden>
            |
          </span>
          <Link
            href="/status"
            className={cn(
              "text-muted-foreground hover:text-foreground text-sm font-medium whitespace-nowrap transition-colors",
              linkFocus,
            )}
          >
            Status
          </Link>
          {/* Changelog is gated to md+: below 768px the wordmark + tagline + a 4th link overflow, and
              the header is overflow-x:clip, so an overflowed link would be unreachable. The footer
              carries the changelog link on narrower screens. (Mobile-header fit — DECISIONS 2026-06-18.) */}
          <span className="text-muted-foreground/30 hidden select-none md:inline" aria-hidden>
            |
          </span>
          <Link
            href="/changelog"
            className={cn(
              "text-muted-foreground hover:text-foreground hidden text-sm font-medium whitespace-nowrap transition-colors md:inline",
              linkFocus,
            )}
          >
            Changelog
          </Link>
        </nav>
      </div>
    </header>
  );
}
