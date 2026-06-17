"use client";

import { motion } from "motion/react";

import { ResultCard } from "@/components/result-card";
import { ResultList } from "@/components/result-list";
import { batchStats } from "@/lib/scores";
import type { ResultItem } from "@/types/recommendation";

/** House spring (vibe-steer.tsx). */
const SPRING = { type: "spring", stiffness: 420, damping: 38, mass: 0.9 } as const;

/**
 * The staggered reveal at the end of a replay. `animateIn` is the player's client-only "a playback
 * actually ran" flag: false covers SSR, no-JS, and reduced motion in one branch (autoplay is
 * reduce-gated upstream), and those all get the plain, fully-visible ResultList — the idle=final
 * invariant. Only a genuinely-played replay earns the entrance animation, so motion `initial`
 * styles never reach the static HTML.
 *
 * The animated branch re-implements ResultList's thin wrapper (it is a server component with no
 * entrance hook): same key scheme, same backfill-divider, batch stats over the FULL final list so
 * cultural bars never rescale mid-cascade. Stagger is by emitted-row slot, so the divider gets its
 * own beat instead of sharing the next card's.
 */
export function ResultsCascade({
  results,
  runId,
  animateIn,
}: {
  results: ResultItem[];
  runId: number;
  animateIn: boolean;
}) {
  if (!animateIn) return <ResultList results={results} />;

  const batch = batchStats(results);
  const firstBackfillIdx = results.findIndex((r) => !r.was_audio_scored);

  const rows: React.ReactNode[] = [];
  results.forEach((item, i) => {
    if (i === firstBackfillIdx && i > 0) {
      rows.push(
        <motion.div
          key={`divider-${runId}`}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ ...SPRING, delay: rows.length * 0.07 }}
          className="text-muted-foreground my-4 flex items-center gap-3 text-xs"
        >
          <span className="bg-border h-px flex-1" aria-hidden />
          <span className="font-medium tracking-wide uppercase">
            From the crowd, not scored by sound
          </span>
          <span className="bg-border h-px flex-1" aria-hidden />
        </motion.div>,
      );
    }
    rows.push(
      <motion.div
        key={`${runId}-${item.position}-${item.mbid ?? item.title}`}
        initial={{ opacity: 0, y: 10, scale: 0.98 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ ...SPRING, delay: rows.length * 0.07 }}
      >
        <ResultCard item={item} batch={batch} />
      </motion.div>,
    );
  });

  return <div className="flex flex-col gap-3">{rows}</div>;
}
