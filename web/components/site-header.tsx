import Link from "next/link";

export function SiteHeader() {
  return (
    <header className="border-border/60 bg-background/80 sticky top-0 z-40 border-b backdrop-blur">
      <div className="mx-auto flex h-14 w-full max-w-6xl items-center justify-between px-5">
        <Link href="/" className="flex items-baseline gap-2">
          <span className="text-lg font-bold tracking-tight">Doppel</span>
          <span className="text-muted-foreground hidden font-mono text-xs sm:inline">
            vibe-matched song recommendations
          </span>
        </Link>
        <span className="text-muted-foreground rounded-md border px-2 py-0.5 font-mono text-[11px]">
          static showcase · no live backend
        </span>
      </div>
    </header>
  );
}
