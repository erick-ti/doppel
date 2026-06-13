"use client";

import { useId, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { CornerDownLeft, Search } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

/** Compact seed facts the server page passes down (lib/seeds is server-only). */
export interface ConsoleSeed {
  slug: string;
  title: string;
  artist: string;
  genre: string;
  vibe: string | null;
}

/**
 * The active curated picker — the inversion of the old disabled seed box (same silhouette, real
 * input). Honest by design: picking a seed REPLAYS the recorded pipeline run for that exact request
 * (`/run/[slug]`, real persisted telemetry); free-text stays a filter over the analyzed library, not
 * a live request — there is still no public live endpoint, and the copy says so.
 */
export function EngineConsole({
  seeds,
  latestCapture,
}: {
  seeds: ConsoleSeed[];
  latestCapture: string | null;
}) {
  const router = useRouter();
  const listId = useId();
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);

  const matches = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return seeds;
    return seeds.filter((s) =>
      [s.title, s.artist, s.genre, s.vibe ?? ""].some((field) => field.toLowerCase().includes(q)),
    );
  }, [seeds, query]);

  const go = (slug: string) => {
    setOpen(false);
    router.push(`/run/${slug}`);
  };

  const reveal = (i: number) => {
    setActive(i);
    // Keep the keyboard-highlighted option visible inside the max-h listbox.
    document.getElementById(`${listId}-${matches[i]?.slug}`)?.scrollIntoView({ block: "nearest" });
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (!open && (e.key === "ArrowDown" || e.key === "Enter")) {
      setOpen(true);
      return;
    }
    if (e.key === "ArrowDown") {
      e.preventDefault();
      reveal(Math.min(active + 1, Math.max(0, matches.length - 1)));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      reveal(Math.max(active - 1, 0));
    } else if (e.key === "Enter" && matches[active]) {
      e.preventDefault();
      go(matches[active].slug);
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  };

  return (
    <div className="mt-10 max-w-xl">
      {/* Console status line — every fact is real and frozen (no live backend to poll). */}
      <div className="text-muted-foreground mb-2 flex flex-wrap items-center gap-x-2 gap-y-1 font-mono text-[11px]">
        {/* motion-safe: the ping collapses to the static dot under prefers-reduced-motion */}
        <span className="relative flex size-2" aria-hidden>
          <span className="bg-audio/60 absolute inline-flex h-full w-full rounded-full opacity-60 motion-safe:animate-ping" />
          <span className="bg-audio relative inline-flex size-2 rounded-full" />
        </span>
        <span className="text-foreground/80">replay console</span>
        <span className="text-muted-foreground/50">·</span>
        <span>{seeds.length} recorded runs</span>
        {latestCapture && (
          <>
            <span className="text-muted-foreground/50">·</span>
            <span>latest capture {latestCapture.slice(0, 10)}</span>
          </>
        )}
        <span className="text-muted-foreground/50">·</span>
        <span>no live backend</span>
      </div>

      <div className="relative">
        <div className="bg-card/40 focus-within:border-audio/40 flex items-center gap-3 rounded-xl border px-4 py-3 transition-colors">
          <Search className="text-muted-foreground size-4 shrink-0" aria-hidden />
          <input
            type="text"
            role="combobox"
            aria-label="Search the analyzed seed library"
            aria-expanded={open}
            aria-controls={listId}
            aria-autocomplete="list"
            aria-activedescendant={open && matches[active] ? `${listId}-${matches[active].slug}` : undefined}
            placeholder="Pick a seed from the analyzed library…"
            className="placeholder:text-muted-foreground w-full bg-transparent text-sm outline-none"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setActive(0);
              setOpen(true);
            }}
            onFocus={() => setOpen(true)}
            onBlur={() => setTimeout(() => setOpen(false), 120)}
            onKeyDown={onKeyDown}
          />
          <span className="text-muted-foreground/80 inline-flex items-center gap-1 rounded-md border px-2 py-0.5 font-mono text-[11px] whitespace-nowrap">
            <CornerDownLeft className="size-3" aria-hidden />
            replay
          </span>
        </div>

        {open && (
          <ul
            id={listId}
            role="listbox"
            aria-label="Analyzed seeds"
            className="bg-popover absolute z-20 mt-2 max-h-80 w-full overflow-y-auto rounded-xl border p-1.5 shadow-lg"
          >
            {matches.length === 0 && (
              <li className="text-muted-foreground px-3 py-2 text-sm" role="presentation">
                Not in the analyzed library — free-text input stays offline (no public live endpoint).
              </li>
            )}
            {matches.map((s, i) => (
              <li
                key={s.slug}
                id={`${listId}-${s.slug}`}
                role="option"
                aria-selected={i === active}
                className={cn(
                  "flex cursor-pointer items-center gap-2 rounded-lg px-3 py-2 text-sm",
                  i === active && "bg-accent",
                )}
                onMouseEnter={() => setActive(i)}
                onMouseDown={(e) => {
                  e.preventDefault(); // beat the input's onBlur
                  go(s.slug);
                }}
              >
                <span className="truncate">
                  {s.title} <span className="text-muted-foreground">— {s.artist}</span>
                </span>
                <span className="ml-auto flex shrink-0 items-center gap-1.5">
                  {s.vibe && (
                    <Badge variant="audio" className="font-mono text-[10px]">
                      vibe
                    </Badge>
                  )}
                  <Badge variant="muted" className="font-mono text-[10px]">
                    {s.genre}
                  </Badge>
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>

      <p className="text-muted-foreground mt-2 text-xs leading-relaxed">
        Picking a seed replays the <em>recorded</em> pipeline run for that exact request —
        stage-by-stage, from real persisted telemetry. Arbitrary live input takes ~12&nbsp;min cold,
        so the engine never runs on this site;{" "}
        <Link href="/deep-dive" className="text-foreground underline decoration-dotted underline-offset-2">
          the deep dive
        </Link>{" "}
        walks the cold→warm story in prose.
      </p>
    </div>
  );
}
