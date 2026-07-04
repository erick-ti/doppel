"use client";

/**
 * The vibe-steer toggle (v1.1 Phase 2 marquee surface).
 *
 * One seed has two REAL precomputed runs — a plain rerank and the same seed reshaped by a free-text
 * vibe. This client component owns every run-specific surface so they all track the toggle together
 * (funnel counts are run-invariant, but latency and the raw response body are not — keeping them in
 * here is what stops the transparency panel from disagreeing with the visible list):
 *
 *   toggle  ->  coverage funnel  ->  ranked list (FLIP reorder)  ->  transparency panel
 *
 * Toggling swaps the result list with a Framer-Motion FLIP reorder: tracks shared by both runs slide
 * to their new rank, dropped tracks fade out, newly-surfaced tracks fade in. Each vibe-side row shows
 * a delta badge (NEW / up N / down N / even) versus the plain baseline. The vibe-text score axis only
 * carries a value on the steered run, so the score breakdown "lights up" that axis exactly when
 * steering is active.
 *
 * Honest framing is a design invariant: the copy states this is directional steering, not a hard
 * filter, and is careful not to overclaim (within-batch normalization means a strong text match can
 * reorder — even flip — the top rows, which is exactly what the HUMBLE marquee shows). The whole
 * thing collapses to an instant, motion-free swap under `prefers-reduced-motion`.
 */
import { useId, useMemo, useState } from "react";
import Link from "next/link";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { Play, SlidersHorizontal } from "lucide-react";

import { CoverageStrip } from "@/components/coverage-strip";
import { ResultCard } from "@/components/result-card";
import { TransparencyPanel } from "@/components/transparency-panel";
import { computeRankDelta, rankMap, resultIdentity } from "@/lib/rank-delta";
import { batchStats } from "@/lib/scores";
import { cn } from "@/lib/utils";
import type { SeedDocument } from "@/types/recommendation";

type Mode = "plain" | "vibe";

function ToggleButton({
  active,
  onClick,
  controls,
  ariaLabel,
  children,
}: {
  active: boolean;
  onClick: () => void;
  controls: string;
  ariaLabel: string;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      aria-label={ariaLabel}
      aria-controls={controls}
      onClick={onClick}
      className={cn(
        "focus-visible:border-ring focus-visible:ring-ring/50 inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium outline-none transition-colors focus-visible:ring-[3px]",
        active
          ? "bg-audio/15 text-audio"
          : "text-muted-foreground hover:text-foreground",
      )}
    >
      {children}
    </button>
  );
}

export function VibeSteer({
  plain,
  vibe,
  initialMode = "plain",
  replayHrefs,
}: {
  plain: SeedDocument;
  vibe: SeedDocument;
  /** Which side the toggle opens on — driven by the slug the visitor navigated to. */
  initialMode?: Mode;
  /** v1.2: per-run replay routes (null = that run has no trace sidecar). Rendered IN here — a
   *  run-specific surface must track the toggle like every other one, or the link can point at a
   *  different recorded run than the visible results. */
  replayHrefs?: { plain: string | null; vibe: string | null };
}) {
  const [mode, setMode] = useState<Mode>(initialMode);
  const reduce = useReducedMotion();
  const groupId = useId();
  const listId = `${groupId}-results`;

  const active = mode === "vibe" ? vibe : plain;
  const results = active.results;
  const batch = batchStats(results);

  // The plain run is the baseline every delta reads against ("where this track sat before steering").
  const plainRanks = rankMap(plain.results);

  // Summarize the reorder so the live region conveys the SUBSTANCE of the switch (how many tracks
  // moved / are new), not just which mode is active — AT won't re-read the reordered cards.
  const vibeChangeSummary = useMemo(() => {
    let reordered = 0;
    let added = 0;
    vibe.results.forEach((item, i) => {
      const d = computeRankDelta(item, i + 1, plainRanks);
      if (d.kind === "new") added += 1;
      else if (d.kind === "up" || d.kind === "down") reordered += 1;
    });
    return { reordered, added };
  }, [vibe.results, plainRanks]);

  // Cultural-backfill divider: first non-audio-scored row, if audio-scored rows precede it. The
  // HUMBLE pair is fully audio-scored so this stays inert, but the logic is preserved for a future
  // degraded vibe pair (faithful to the pipeline's audio-first ordering). The divider is rendered
  // as its OWN keyed sibling below — never inside a card's motion.div — so it sits at a stable
  // boundary during the FLIP reorder instead of riding a moving row.
  const firstBackfillIdx = results.findIndex((r) => !r.was_audio_scored);
  const dividerIdx = firstBackfillIdx > 0 ? firstBackfillIdx : -1;

  const vibeText = vibe.vibe ?? "";

  // Motion config — fully neutralized under prefers-reduced-motion (no slide, no fade, no spring).
  const layoutProp = reduce ? false : ("position" as const);
  const transition = reduce
    ? { duration: 0 }
    : ({ type: "spring", stiffness: 420, damping: 38, mass: 0.9 } as const);

  // Build the list children so the backfill divider is a sibling of the cards, not a child of one.
  const listChildren: React.ReactElement[] = [];
  results.forEach((item, i) => {
    if (i === dividerIdx) {
      listChildren.push(
        <motion.div
          key="backfill-divider"
          layout={layoutProp}
          initial={reduce ? false : { opacity: 0 }}
          animate={reduce ? {} : { opacity: 1 }}
          exit={reduce ? {} : { opacity: 0 }}
          transition={transition}
          className="my-4 flex items-center gap-3"
        >
          <div className="bg-border h-px flex-1" />
          <span className="text-muted-foreground text-xs font-medium tracking-wide uppercase">
            From the crowd, not scored by sound
          </span>
          <div className="bg-border h-px flex-1" />
        </motion.div>,
      );
    }
    // Use the 1-based array index on both sides (the baseline map keys on index too) so the delta
    // math is self-consistent regardless of how `position` was assigned at export time.
    const delta =
      mode === "vibe" ? computeRankDelta(item, i + 1, plainRanks) : null;
    listChildren.push(
      <motion.div
        key={resultIdentity(item)}
        layout={layoutProp}
        initial={reduce ? false : { opacity: 0, scale: 0.98 }}
        animate={reduce ? {} : { opacity: 1, scale: 1 }}
        exit={reduce ? {} : { opacity: 0, scale: 0.98 }}
        transition={transition}
      >
        <ResultCard item={item} batch={batch} delta={delta} />
      </motion.div>,
    );
  });

  const activeReplayHref = mode === "vibe" ? replayHrefs?.vibe : replayHrefs?.plain;

  return (
    <div className="flex flex-col gap-8">
      {activeReplayHref && (
        <Link
          href={activeReplayHref}
          className="text-muted-foreground hover:text-foreground -mb-4 inline-flex w-fit items-center gap-1.5 font-mono text-xs transition-colors"
        >
          <Play className="size-3" aria-hidden />
          watch this run play back, step by step
        </Link>
      )}
      {/* Funnel + everything below reflect the ACTIVE run (only latency differs across the pair). */}
      <CoverageStrip coverage={active.coverage} meta={active.meta} />

      <section className="flex flex-col gap-5">
        <h2 className="font-display flex items-baseline gap-2 text-xl font-semibold tracking-tight">
          The picks
          <span className="text-muted-foreground text-sm font-normal">
            top {results.length}, best sound matches first
          </span>
        </h2>

        {/* Segmented toggle */}
        <div className="flex flex-wrap items-center gap-3">
          <div
            role="group"
            aria-label="Mood"
            className="bg-card/40 inline-flex w-fit gap-1 rounded-lg border p-1"
          >
            <ToggleButton
              active={mode === "plain"}
              onClick={() => setMode("plain")}
              controls={listId}
              ariaLabel="Show the results without a mood"
            >
              Plain
            </ToggleButton>
            <ToggleButton
              active={mode === "vibe"}
              onClick={() => setMode("vibe")}
              controls={listId}
              ariaLabel={`Show the results with the mood: ${vibeText}`}
            >
              <SlidersHorizontal className="size-3.5" aria-hidden />
              With a mood
            </ToggleButton>
          </div>
          {/* Polite announcement of the active list for screen readers — the mood message carries the
              substance of the reorder, since AT won't re-read the FLIP-reordered cards. */}
          <span className="sr-only" aria-live="polite">
            {mode === "vibe"
              ? `Showing the results with the mood: ${vibeChangeSummary.reordered} songs reordered, ${vibeChangeSummary.added} new.`
              : "Showing the results without a mood."}
          </span>
        </div>

        {/* Active-vibe context: the steer text + the honest "what this is / isn't" framing. */}
        <AnimatePresence initial={false}>
          {mode === "vibe" && (
            <motion.div
              key="vibe-context"
              initial={reduce ? false : { opacity: 0, height: 0 }}
              animate={reduce ? {} : { opacity: 1, height: "auto" }}
              exit={reduce ? {} : { opacity: 0, height: 0 }}
              transition={{ duration: reduce ? 0 : 0.25 }}
              className="overflow-hidden"
            >
              <div className="border-audio/40 bg-audio/5 rounded-lg border-l-2 px-4 py-3">
                <span className="text-muted-foreground text-xs tracking-wide uppercase">
                  Your mood
                </span>
                <p className="text-audio text-sm italic">&ldquo;{vibeText}&rdquo;</p>
                <p className="text-muted-foreground mt-2 text-xs leading-relaxed">
                  This nudges the picks toward your mood. It&rsquo;s a gentle lean, not a hard filter.
                  Sound still matters most, but a strong mood match can shuffle the top of the list
                  around. The badges show how far each song moved compared to no mood at all.
                </p>
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        {/* FLIP-reordering result list */}
        <div id={listId} className="flex flex-col gap-3">
          <AnimatePresence initial={false} mode="popLayout">
            {listChildren}
          </AnimatePresence>
        </div>
      </section>

      <TransparencyPanel doc={active} />
    </div>
  );
}
