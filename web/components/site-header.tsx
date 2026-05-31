import Link from "next/link";

export function SiteHeader() {
  return (
    <header className="border-border/60 bg-background/80 sticky top-0 z-40 border-b backdrop-blur">
      <div className="mx-auto flex h-14 w-full max-w-6xl items-center justify-between gap-3 px-5">
        <Link href="/" className="flex items-baseline gap-2">
          <span className="text-lg font-bold tracking-tight">Doppel</span>
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
