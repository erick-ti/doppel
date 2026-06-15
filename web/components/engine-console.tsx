"use client";

import { useId, useMemo, useState } from "react";
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
    } else if (e.key === "Enter" && matches[active]) {
      e.preventDefault();
      go(matches[active].slug);
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  };

  return (
    <div className="mt-8 max-w-2xl">
      <div className="text-muted-foreground mb-2 flex flex-wrap items-center gap-x-2 gap-y-1 font-mono text-[11px] tracking-[0.16em] uppercase">
        <span className="bg-seam size-1.5 rounded-full" aria-hidden />
        <label htmlFor={`${listId}-input`} className="text-seam/90">
          seed input
        </label>
        <span className="text-muted-foreground/50">·</span>
        <span className="tracking-normal normal-case">replay any of {seeds.length} recorded runs</span>
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
                  "flex cursor-pointer items-center gap-3 rounded-lg px-2.5 py-2 text-sm",
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
                  {s.title} <span className="text-muted-foreground">— {s.artist}</span>
                </span>
                <span className="flex shrink-0 items-center gap-1.5">
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
