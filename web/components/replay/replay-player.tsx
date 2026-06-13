"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Pause, Play, RotateCcw, SkipForward } from "lucide-react";
import { motion, useReducedMotion } from "motion/react";

import { ReplayBanner } from "@/components/replay/replay-banner";
import { ResultsCascade } from "@/components/replay/results-cascade";
import { StageFlow } from "@/components/replay/stage-flow";
import { defaultSpeed, formatClock, pairProvenance, speedLabel, speedOptions } from "@/lib/replay";
import { cn } from "@/lib/utils";
import type { SeedDocument } from "@/types/recommendation";
import type { RunTrace } from "@/types/trace";

/**
 * The replay orchestrator — owns EVERY surface that depends on playback state (the vibe-steer
 * ownership rule: one client component drives the banner, the stage flow, and the results reveal,
 * so nothing on screen can disagree with the clock).
 *
 * Honesty model: the clock plays the trace's REAL ms timeline scaled by a labeled speed factor.
 * SSR renders the finished state (the established idle=final pattern — no-JS readers and search
 * engines see the complete, truthful page); on mount the clock rewinds and plays, except under
 * prefers-reduced-motion, where the finished state simply stands (the app-wide invariant).
 */
export function ReplayPlayer({ doc, trace }: { doc: SeedDocument; trace: RunTrace }) {
  const reduce = useReducedMotion();
  const total = trace.total_ms;

  const [t, setT] = useState(total); // idle = final
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(() => defaultSpeed(trace.mode));
  const [runId, setRunId] = useState(0);
  // Client-only playback-existence flag — false on the server AND the first client render (it flips
  // only via post-hydration events), so every reduce/playback-dependent branch below hydrates clean
  // (the coverage-strip contract). It also keeps SSR/no-JS/reduced-motion on the plain final markup.
  const [started, setStarted] = useState(false);
  const tRef = useRef(total);

  const seek = useCallback((value: number) => {
    tRef.current = value;
    setT(value);
  }, []);

  // Autoplay on arrival (the console links straight here) — but never under reduced motion. The
  // event-driven onViewportEnter + once trigger is the coverage-strip idiom: SSR markup stays the
  // finished state, and the rewind happens only client-side from a real viewport event.
  const startedOnce = useRef(false);
  const autoplay = useCallback(() => {
    if (startedOnce.current || reduce !== false) return;
    startedOnce.current = true;
    setStarted(true);
    seek(0);
    setPlaying(true);
  }, [reduce, seek]);

  // Speed is a dependency on purpose: changing it restarts the loop, which re-anchors `last` — the
  // clock continues from the current t with the new factor, no jump. The clock value lives in tRef
  // (updaters stay pure: every state write happens from this callback, never inside an updater).
  useEffect(() => {
    if (!playing) return;
    let raf = 0;
    let last = performance.now();
    const tick = (now: number) => {
      const dt = (now - last) * speed;
      last = now;
      const next = Math.min(tRef.current + dt, total);
      tRef.current = next;
      setT(next);
      if (next >= total) {
        setPlaying(false);
        return;
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [playing, total, speed]);

  const restart = useCallback(() => {
    setRunId((id) => id + 1); // re-keys the cascade so the reveal staggers again
    setStarted(true);
    seek(0);
    setPlaying(true);
  }, [seek]);

  const done = t >= total;
  const provenance = pairProvenance(doc.meta, trace);

  const btn =
    "inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-xs font-medium transition-colors hover:bg-accent focus-visible:ring-ring/50 focus-visible:ring-[3px] focus-visible:outline-none disabled:opacity-40 disabled:pointer-events-none";

  return (
    <motion.div
      className="flex flex-col gap-6"
      onViewportEnter={autoplay}
      viewport={{ once: true, amount: 0.1 }}
    >
      <ReplayBanner
        provenance={provenance}
        mode={trace.mode}
        // A speed claim is only honest while playback exists; the static/no-JS/reduced-motion page
        // states the recorded span instead.
        speedLabel={started ? speedLabel(speed) : `recorded span ${formatClock(total)}`}
      />

      {/* Controls — gated on `started` so SSR and the first client render agree (hydration), and
          hidden entirely under reduced motion: the page is simply the finished record. The scrubber
          is deliberately not offered as a motion-free affordance — the reduced-motion page is the
          complete final state, matching the app-wide collapse-to-instant rule. */}
      {reduce === false && started && (
        <div className="bg-card/40 flex flex-col gap-3 rounded-xl border px-4 py-3">
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              className={btn}
              onClick={() => (done ? restart() : setPlaying((p) => !p))}
              aria-label={done ? "Replay" : playing ? "Pause" : "Play"}
            >
              {playing ? <Pause className="size-3.5" aria-hidden /> : <Play className="size-3.5" aria-hidden />}
              {done ? "Replay" : playing ? "Pause" : "Play"}
            </button>
            <button type="button" className={btn} onClick={restart} aria-label="Restart replay">
              <RotateCcw className="size-3.5" aria-hidden />
              Restart
            </button>
            <button
              type="button"
              className={btn}
              onClick={() => {
                setPlaying(false);
                seek(total);
              }}
              disabled={done}
              aria-label="Skip to results"
            >
              <SkipForward className="size-3.5" aria-hidden />
              Skip to results
            </button>
            <span className="text-muted-foreground ml-auto font-mono text-xs tabular-nums">
              {formatClock(t)} / {formatClock(total)}
            </span>
            <div className="flex items-center gap-1" role="group" aria-label="Playback speed">
              {speedOptions(trace.mode).map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => setSpeed(s)}
                  className={cn(
                    "focus-visible:ring-ring/50 rounded-md border px-2 py-1 font-mono text-[11px] tabular-nums transition-colors focus-visible:ring-[3px] focus-visible:outline-none",
                    s === speed ? "border-audio/40 bg-audio/15 text-audio" : "hover:bg-accent",
                  )}
                  aria-pressed={s === speed}
                >
                  {s}×
                </button>
              ))}
            </div>
          </div>

          {/* Scrubber over the trace's real timeline, with stage-boundary tick marks. */}
          <div className="relative">
            <input
              type="range"
              min={0}
              max={total}
              step={1}
              value={Math.round(t)}
              onChange={(e) => {
                setPlaying(false);
                seek(Number(e.target.value));
              }}
              className="accent-audio w-full"
              aria-label="Replay timeline"
              aria-valuetext={`${formatClock(t)} of ${formatClock(total)}`}
            />
            <div className="pointer-events-none absolute inset-x-0 top-full flex h-1.5" aria-hidden>
              {trace.stages.map((s) => (
                <span
                  key={s.stage}
                  className="bg-border absolute h-1.5 w-px"
                  style={{ left: `${(s.t0_ms / total) * 100}%` }}
                />
              ))}
            </div>
          </div>
        </div>
      )}

      <StageFlow stages={trace.stages} t={t} />

      {done && (
        <section aria-label="Recommendations">
          <h2 className="mb-4 flex items-baseline gap-2 text-xl font-semibold tracking-tight">
            Recommendations
            <span className="text-muted-foreground text-sm font-normal">top {doc.results.length}</span>
          </h2>
          <ResultsCascade results={doc.results} runId={runId} animateIn={started} />
        </section>
      )}
    </motion.div>
  );
}
