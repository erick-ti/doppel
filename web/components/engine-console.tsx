"use client";

import { useId, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ChevronRight, CornerDownLeft } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Fingerprint } from "@/components/fingerprint";
import { cn } from "@/lib/utils";
import type { FingerprintData } from "@/lib/fingerprint";

/** Compact seed facts the server page passes down (lib/seeds is server-only). */
export interface ConsoleSeed {
  slug: string;
  title: string;
  artist: string;
  genre: string;
  vibe: string | null;
  /** The seed's earned signal fingerprint, precomputed server-side for the option spark. */
  fp: FingerprintData;
}

/**
 * The curated picker — the instrument's input slot. Each option carries its own signal-fingerprint
 * spark, so choosing a run is choosing between visibly distinct waveforms. Honest by design: picking
 * a seed REPLAYS the recorded pipeline run for that exact request (`/run/[slug]`, real persisted
 * telemetry); free-text stays a filter over the analyzed library — there is no public live endpoint.
 */
export function EngineConsole({ seeds }: { seeds: ConsoleSeed[] }) {
  const router = useRouter();
  const listId = useId();
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  // Holds the close-on-blur timer so re-focusing (before it fires) can cancel it — otherwise a late
  // timer could close a list the user just re-opened.
  const blurTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

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
    } else if (e.key === "Home") {
      e.preventDefault();
      reveal(0);
    } else if (e.key === "End") {
      e.preventDefault();
      reveal(Math.max(0, matches.length - 1));
    } else if (e.key === "Enter" && matches[active]) {
      e.preventDefault();
      go(matches[active].slug);
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  };

  return (
    <div className="mx-auto mt-8 max-w-2xl">
      <div className="text-muted-foreground mb-2 flex flex-wrap items-center justify-center gap-x-2 gap-y-1 font-mono text-[11px] tracking-[0.16em] uppercase">
        <span className="relative inline-flex size-1.5" aria-hidden>
          <span className="bg-seam/60 absolute inline-flex h-full w-full rounded-full motion-safe:animate-ping" />
          <span className="bg-seam relative inline-flex size-1.5 rounded-full" />
        </span>
        <label htmlFor={`${listId}-input`} className="text-seam/90">
          pick a song
        </label>
        <span className="text-muted-foreground/50">·</span>
        <span className="tracking-normal normal-case">{seeds.length} saved runs to try</span>
      </div>

      <div className="relative">
        <div className="bg-card/50 focus-within:border-seam/60 focus-within:ring-ring/50 border-seam/25 flex items-center gap-3 rounded-xl border px-4 py-3.5 transition-colors focus-within:ring-[3px]">
          {/* the ignition glyph — the seam motif marking the engine's input slot */}
          <span className="bg-seam/15 text-seam inline-flex size-6 shrink-0 items-center justify-center rounded">
            <ChevronRight className="size-4" aria-hidden />
          </span>
          <input
            id={`${listId}-input`}
            type="text"
            role="combobox"
            aria-label="Search the saved songs"
            // Only advertise an expanded, controlled listbox when one actually renders. With zero
            // matches the listbox is replaced by a sibling role="status" message (announced on its
            // own), so reporting "collapsed" here keeps aria-controls from dangling at a missing id.
            aria-expanded={open && matches.length > 0}
            aria-controls={open && matches.length > 0 ? listId : undefined}
            aria-autocomplete="list"
            aria-activedescendant={open && matches[active] ? `${listId}-${matches[active].slug}` : undefined}
            placeholder="Pick a song to play back…"
            className="placeholder:text-muted-foreground w-full bg-transparent text-sm outline-none"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setActive(0);
              setOpen(true);
            }}
            onFocus={() => {
              if (blurTimer.current) clearTimeout(blurTimer.current);
              setOpen(true);
            }}
            onBlur={() => {
              blurTimer.current = setTimeout(() => setOpen(false), 120);
            }}
            onKeyDown={onKeyDown}
          />
          <span className="text-muted-foreground/80 inline-flex items-center gap-1 rounded-md border px-2 py-0.5 font-mono text-[11px] whitespace-nowrap">
            <CornerDownLeft className="size-3" aria-hidden />
            play
          </span>
        </div>

        {/* z-50 so the open list wins over the sticky header (z-40); capped to ~half the viewport so
            it never runs far below the fold on a phone (it scrolls internally). */}
        {open && matches.length === 0 && (
          <p
            role="status"
            className="bg-popover text-muted-foreground absolute z-50 mt-2 w-full rounded-xl border p-3 text-sm shadow-lg motion-safe:animate-in motion-safe:fade-in-0 motion-safe:slide-in-from-top-1 motion-safe:duration-150"
          >
            That song isn&rsquo;t saved here. Typing just filters the ones Doppel has already analyzed.
          </p>
        )}
        {open && matches.length > 0 && (
          <ul
            id={listId}
            role="listbox"
            aria-label="Saved songs"
            className="bg-popover absolute z-50 mt-2 max-h-[min(20rem,55vh)] w-full overflow-y-auto rounded-xl border p-1.5 shadow-lg motion-safe:animate-in motion-safe:fade-in-0 motion-safe:slide-in-from-top-1 motion-safe:duration-150"
          >
            {matches.map((s, i) => (
              <li
                key={s.slug}
                id={`${listId}-${s.slug}`}
                role="option"
                aria-selected={i === active}
                className={cn(
                  "flex cursor-pointer items-center gap-3 rounded-lg px-2.5 py-2 text-sm transition-colors hover:bg-accent/60",
                  i === active && "bg-accent",
                )}
                onMouseEnter={() => setActive(i)}
                onMouseDown={(e) => {
                  e.preventDefault(); // beat the input's onBlur
                  go(s.slug);
                }}
              >
                <span className="bg-background/40 shrink-0 overflow-hidden rounded border">
                  <Fingerprint data={s.fp} variant="spark" />
                </span>
                <span className="min-w-0 flex-1 truncate">
                  {s.title} <span className="text-muted-foreground">by {s.artist}</span>
                </span>
                <span className="flex shrink-0 items-center gap-1.5">
                  {s.vibe && (
                    <Badge variant="audio" className="font-mono text-[10px]">
                      mood
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

      <p className="text-muted-foreground mt-2 text-center text-xs leading-relaxed">
        Each song here is a real run you can play back, step by step. Running a fresh one makes a real
        Anthropic API call, roughly a cent or two each, so these are saved playbacks rather than live
        runs to keep the costs down.{" "}
        <Link href="/deep-dive" className="text-foreground underline decoration-dotted underline-offset-2">
          The deep dive
        </Link>{" "}
        has the details.
      </p>
    </div>
  );
}
