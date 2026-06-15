import Link from "next/link";

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
        <Link href="/" className="group flex items-center gap-2">
          <SeamMark className="size-4 shrink-0" />
          <span className="font-display text-lg font-semibold tracking-tight">Doppel</span>
          <span className="text-muted-foreground hidden font-mono text-xs sm:inline">
            vibe-matched song recommendations
          </span>
        </Link>
        <nav className="flex items-center gap-3 sm:gap-4" aria-label="Primary">
          <Link
            href="/how-it-works"
            className="text-muted-foreground hover:text-foreground text-sm font-medium whitespace-nowrap transition-colors"
          >
            How it works
          </Link>
          <Link
            href="/deep-dive"
            className="text-muted-foreground hover:text-foreground text-sm font-medium whitespace-nowrap transition-colors"
          >
            Deep dive
          </Link>
          <span className="text-muted-foreground hidden rounded-md border px-2 py-0.5 font-mono text-[11px] whitespace-nowrap md:inline">
            static showcase
            <span className="hidden lg:inline"> · no live backend</span>
          </span>
        </nav>
      </div>
    </header>
  );
}
