"use client";

import { useEffect, useId, useLayoutEffect, useState } from "react";
import {
  animate,
  motion,
  useMotionValue,
  useReducedMotion,
  useTransform,
} from "motion/react";
import { RotateCcw, SkipForward } from "lucide-react";

import { cn } from "@/lib/utils";
import type { Coverage, ExportMeta } from "@/types/recommendation";

/**
 * The retrieve -> rerank funnel (v1.1 Phase 2). A single, clean, skippable narrowing pass driven by
 * this seed's REAL `coverage` counts: cultural candidates -> resolve attempts -> found -> audio-reranked
 * top 10. Each stage's bar width encodes its share of the widest stage, so the visual narrowing IS the
 * data — the cultural-recall legs are amber, the final CLAP rerank is the audio-blue accent, making the
 * two-leg hand-off legible. Numbers roll up from zero; the pass is skippable and replayable.
 *
 * Honesty + robustness invariants:
 *  - The displayed numbers are always the real export values; an `sr-only` copy carries the true value
 *    so the count-up is purely decorative to assistive tech.
 *  - "idle" is the safe resting state and renders the real, final strip. It is what the server / no-JS /
 *    reduced-motion / never-scrolled-into-view render shows, so the data is NEVER stranded at zero.
 *  - `prefers-reduced-motion` collapses the whole thing to that instant final strip (no motion, no
 *    controls). `useReducedMotion()` reads the OS preference once at mount and is NOT reactive: it
 *    yields `false` during SSR and the real value (`true` for a reduced-motion user) from the client's
 *    first render on. The run only ever starts from the client-only `onViewportEnter` callback, so
 *    gating it on `reduce === false` means a reduced-motion user never animates, and SSR's `false` is
 *    harmless because `idle` renders the final strip regardless of `reduce`.
 *  - Rendered in TWO contexts: server-side for lone seeds (a client boundary) and inside the client
 *    `VibeSteer` for paired seeds. Funnel counts are run-invariant across a plain<->vibe pair, so toggling
 *    just updates the values in place; the pass plays once on first view, not per toggle.
 */

const useIsoLayoutEffect =
  typeof window !== "undefined" ? useLayoutEffect : useEffect;

// easeOutExpo-ish: fast out of the gate, gentle settle — reads as "narrowing."
const EASE: [number, number, number, number] = [0.22, 1, 0.36, 1];
const STAGGER = 0.16; // delay between successive stages (s)
const RUN = 0.7; // per-stage count-up + bar-grow duration (s)
// candidates → resolve → found → audio-reranked. The last leg starts at (STAGE_COUNT-1)*STAGGER and
// runs for RUN, so the whole pass settles then; +80ms buffer before we drop back to the static state.
const STAGE_COUNT = 4;
const TOTAL_MS = (STAGGER * (STAGE_COUNT - 1) + RUN) * 1000 + 80;

type Leg = "cultural" | "audio";
type Status = "idle" | "running" | "done";

interface Stage {
  value: number;
  label: string;
  note: string;
  leg: Leg;
}

/** Count-up number. Rests at the final value (idle/done); resets to 0 and animates while running. */
function StageCount({
  value,
  status,
  runId,
  delay,
}: {
  value: number;
  status: Status;
  runId: number;
  delay: number;
}) {
  const mv = useMotionValue(value);
  const text = useTransform(mv, (v) => Math.round(v).toString());

  useIsoLayoutEffect(() => {
    if (status !== "running") {
      mv.set(value); // idle + done rest at the real value (also the SSR / no-JS state)
      return;
    }
    mv.set(0); // pre-paint reset, so the count-up starts from zero, not the final value
    const controls = animate(mv, value, { duration: RUN, delay, ease: EASE });
    return () => controls.stop();
  }, [status, runId, value, delay, mv]);

  return (
    <>
      {/* Plain wrapper guarantees aria-hidden lands (motion.span drops the boolean prop), so the
          animated count-up is invisible to assistive tech while the sr-only copy carries the truth. */}
      <span aria-hidden="true">
        <motion.span>{text}</motion.span>
      </span>
      <span className="sr-only">{value}</span>
    </>
  );
}

/** Proportional narrowing bar. Width encodes the stage's share of the widest stage; scaleX animates. */
function StageBar({
  pct,
  leg,
  status,
  runId,
  delay,
}: {
  pct: number;
  leg: Leg;
  status: Status;
  runId: number;
  delay: number;
}) {
  const scaleX = useMotionValue(1);

  useIsoLayoutEffect(() => {
    if (status !== "running") {
      scaleX.set(1); // full target width when at rest (and on the server / no-JS render)
      return;
    }
    scaleX.set(0);
    const controls = animate(scaleX, 1, { duration: RUN, delay, ease: EASE });
    return () => controls.stop();
  }, [status, runId, delay, scaleX]);

  return (
    <div className="bg-muted/50 h-2.5 w-full overflow-hidden rounded-full">
      <motion.div
        className={cn(
          "h-full rounded-full",
          leg === "audio" ? "bg-audio" : "bg-cultural",
        )}
        style={{ width: `${pct}%`, scaleX, originX: 0 }}
        aria-hidden
      />
    </div>
  );
}

export function CoverageStrip({
  coverage,
  meta,
}: {
  coverage: Coverage;
  meta: ExportMeta;
}) {
  const reduce = useReducedMotion();
  const [status, setStatus] = useState<Status>("idle");
  const [runId, setRunId] = useState(0);
  const stagesId = useId();

  // Play once when the strip scrolls into view (fires ~immediately when already visible). This is a
  // viewport callback, not an effect, so the start does not cascade renders; `idle` stays the safe
  // final state until it fires, and reduced-motion (reduce !== false) simply never starts.
  const handleEnter = () => {
    if (reduce === false) setStatus((s) => (s === "idle" ? "running" : s));
  };

  // Settle to the final static state once the staggered sequence has finished.
  useEffect(() => {
    if (status !== "running") return;
    const t = setTimeout(() => setStatus("done"), TOTAL_MS);
    return () => clearTimeout(t);
  }, [status, runId]);

  const replay = () => {
    setRunId((n) => n + 1);
    setStatus("running");
  };
  const skip = () => setStatus("done");

  // The attempted -> found drop has two honest causes: candidates MusicBrainz/Deezer couldn't locate
  // (resolved_not_found) and candidates resolved but rejected by the matcher (resolved_rejected). Name
  // both so the funnel arithmetic always reconciles (e.g. Take Five: 75 attempts - 5 not found - 2
  // rejected = 68 found); "full coverage" only when neither dropped a candidate.
  const foundReasons: string[] = [];
  if (coverage.resolved_not_found > 0)
    foundReasons.push(`${coverage.resolved_not_found} not found`);
  if (coverage.resolved_rejected > 0)
    foundReasons.push(`${coverage.resolved_rejected} rejected`);
  const foundNote = foundReasons.length ? foundReasons.join(" · ") : "full coverage";

  // CLAP scores only the found candidates that actually have an embedding (cache hit + freshly
  // computed) — a found candidate whose preview won't embed falls to cultural backfill, never the
  // audio rerank. So the embedded count, NOT `resolved_found`, is how many were truly CLAP-scored;
  // surface the gap honestly when found > embedded (e.g. Take Five: 64 of 68 embedded). (Cultural-only
  // degraded runs carry null embedding counts and no audio rerank — that copy is the deferred F2 work.)
  const embedded =
    (coverage.embeddings_cache_hits ?? 0) + (coverage.embeddings_computed ?? 0);
  const audioNote =
    embedded < coverage.resolved_found
      ? `CLAP-scored ${embedded} of ${coverage.resolved_found} found · top 10 kept`
      : `CLAP-scored all ${coverage.resolved_found} found · top 10 kept`;

  const stages: Stage[] = [
    {
      value: coverage.candidate_count,
      label: "cultural candidates",
      note: "Last.fm + ListenBrainz, deduped + RRF-fused (k=60)",
      leg: "cultural",
    },
    {
      value: coverage.resolve_attempted,
      label: "resolve attempts",
      note: `top ${meta.resolve_candidate_limit} by rank · MusicBrainz + Deezer verify`,
      leg: "cultural",
    },
    {
      value: coverage.resolved_found,
      label: "found",
      note: foundNote,
      leg: "cultural",
    },
    {
      value: coverage.audio_scored,
      label: "audio-reranked",
      note: audioNote,
      leg: "audio",
    },
  ];

  // The widest stage anchors every bar's proportion (candidate_count is always the funnel mouth).
  const widest = Math.max(...stages.map((s) => s.value), 1);
  const showControls = reduce === false && status !== "idle";

  return (
    <motion.div
      onViewportEnter={handleEnter}
      viewport={{ once: true, amount: 0.4 }}
      className="rounded-xl border p-5"
    >
      <div className="mb-4 flex items-center justify-between gap-3">
        {/* h2: a top-level section of the results view, peer of the "Recommendations" h2 (avoids an
            h1 -> h3 outline skip). The small-caps styling is purely visual; the level is semantic. */}
        <h2 className="text-muted-foreground text-xs font-semibold tracking-wide uppercase">
          Retrieve → rerank funnel
        </h2>
        {showControls && (
          <button
            type="button"
            onClick={status === "done" ? replay : skip}
            aria-controls={stagesId}
            aria-label={
              status === "done"
                ? "Replay the funnel animation"
                : "Skip the funnel animation"
            }
            className="text-muted-foreground hover:text-foreground focus-visible:ring-ring/50 -mr-1 inline-flex items-center gap-1.5 rounded-md px-2 py-1.5 text-xs font-medium outline-none transition-colors focus-visible:ring-[3px]"
          >
            {status === "done" ? (
              <>
                <RotateCcw className="size-3.5" aria-hidden />
                Replay
              </>
            ) : (
              <>
                <SkipForward className="size-3.5" aria-hidden />
                Skip
              </>
            )}
          </button>
        )}
      </div>

      <div id={stagesId} className="flex flex-col gap-3.5">
        {stages.map((stage, i) => {
          const pct = Math.max((stage.value / widest) * 100, 2);
          const delay = i * STAGGER;
          return (
            <div
              key={stage.label}
              className="flex flex-col gap-1.5 sm:grid sm:grid-cols-[8.5rem_1fr] sm:items-center sm:gap-x-5"
            >
              <div className="flex items-baseline gap-2 sm:flex-col sm:items-start sm:gap-0">
                <span
                  className={cn(
                    "font-mono text-2xl font-semibold tabular-nums leading-none",
                    stage.leg === "audio" ? "text-audio" : "text-cultural",
                  )}
                >
                  <StageCount
                    value={stage.value}
                    status={status}
                    runId={runId}
                    delay={delay}
                  />
                </span>
                <span className="text-sm font-medium sm:mt-1">{stage.label}</span>
              </div>
              <div>
                <StageBar
                  pct={pct}
                  leg={stage.leg}
                  status={status}
                  runId={runId}
                  delay={delay}
                />
                <div className="text-muted-foreground mt-1.5 text-xs leading-snug">
                  {stage.note}
                </div>
              </div>
            </div>
          );
        })}
      </div>

      <div className="text-muted-foreground mt-4 border-t pt-3 font-mono text-[11px] tabular-nums">
        {coverage.embeddings_cache_hits ?? 0} embeddings from cache ·{" "}
        {coverage.embeddings_computed ?? 0} computed · {coverage.latency_ms} ms
        total
        <span className="text-muted-foreground">
          {" "}
          (cache-first: warm runs skip re-embedding)
        </span>
      </div>
    </motion.div>
  );
}
