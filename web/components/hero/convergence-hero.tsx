"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { motion, useReducedMotion } from "motion/react";
import { RotateCcw } from "lucide-react";

import { Button } from "@/components/ui/button";
import { EngineConsole, type ConsoleSeed } from "@/components/engine-console";
import { Seam } from "@/components/hero/seam";
import { FoldedStages } from "@/components/hero/folded-stages";
import { formatClock, pairProvenance, shaStamp } from "@/lib/replay";
import { cn } from "@/lib/utils";
import type { SeedDocument } from "@/types/recommendation";
import type { RunTrace } from "@/types/trace";

/**
 * The console-first landing hero. The signature SEAM instrument is the dominant object above the
 * fold: a featured RECORDED run wakes on arrival — two retrieval streams braid into the fused rail,
 * the folded mini-replay fills, and the shortlist is strung on the rail as the rail's output.
 *
 * One RAF clock owns p (0..1); the seam, the folded stages, and the shortlist reveal all read it, so
 * nothing on screen can disagree (the repo's single-owner rule). idle = final: SSR / no-JS /
 * reduced-motion render the fully welded instrument with the complete shortlist and every real number
 * shown; motion only ever rewinds post-mount from a real viewport event. It is a RECORDED replay,
 * never implied-live (the v1.2 cardinal rule) — picking any seed routes to its full /run replay.
 */
export function ConvergenceHero({
  seeds,
  featuredDoc,
  featuredTrace,
  latestCapture,
}: {
  seeds: ConsoleSeed[];
  featuredDoc: SeedDocument;
  featuredTrace: RunTrace;
  latestCapture: string | null;
}) {
  const reduce = useReducedMotion();

  // The teaser plays the retrieve -> rerank -> fuse span; the long LLM `explain` step is a noted fact
  // on the fuse row, not animated (it never ranks, and would otherwise dominate the teaser's pacing).
  const teaserTotal = useMemo(() => {
    const ends = featuredTrace.stages.filter((s) => s.stage !== "explain").map((s) => s.t1_ms);
    return ends.length ? Math.max(...ends) : featuredTrace.total_ms;
  }, [featuredTrace]);

  // Honest playback: a short (warm) span plays at REAL TIME — no time-scaling to disclose; only a
  // long (cold) span is compressed, and then the speed is labeled. clockMs always sweeps REAL
  // telemetry, and the `explain` step is noted-not-animated — so any time-scaling stays explicit
  // (v1.2 cardinal rule: recorded time compression must be visible, never implied real/live).
  const playbackMs = teaserTotal > 3600 ? 3600 : teaserTotal;
  const speed = teaserTotal / playbackMs;
  const teaserSpeedLabel = speed <= 1.05 ? "real time" : `compressed ${Math.round(speed)}×`;

  const [clockMs, setClockMs] = useState(teaserTotal); // idle = final (welded)
  const [playing, setPlaying] = useState(false);
  const [started, setStarted] = useState(false);
  const clockRef = useRef(teaserTotal);

  const p = Math.min(1, clockMs / teaserTotal);
  const degraded = !featuredDoc.degradation.seed_audio_scored;

  const startedOnce = useRef(false);
  const wake = useCallback(() => {
    if (startedOnce.current || reduce !== false) return;
    startedOnce.current = true;
    setStarted(true);
    clockRef.current = 0;
    setClockMs(0);
    setPlaying(true);
  }, [reduce]);

  const replay = useCallback(() => {
    setStarted(true);
    clockRef.current = 0;
    setClockMs(0);
    setPlaying(true);
  }, []);

  useEffect(() => {
    if (!playing) return;
    let raf = 0;
    let last = performance.now();
    const tick = (now: number) => {
      const dt = (now - last) * speed;
      last = now;
      const next = Math.min(clockRef.current + dt, teaserTotal);
      clockRef.current = next;
      setClockMs(next);
      if (next >= teaserTotal) {
        setPlaying(false);
        return;
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [playing, speed, teaserTotal]);

  const top = featuredDoc.results.slice(0, 5);
  // The shortlist is the OUTPUT of the `results` (fuse + rank) stage — reveal it only once the
  // recorded clock reaches that stage's completion, NEVER before fusion happened (recorded-replay
  // honesty + the single-clock rule). The per-row stagger below is a pure CSS reveal flourish, not a
  // fabricated earlier timestamp.
  const resultsEnd = useMemo(
    () => featuredTrace.stages.find((s) => s.stage === "results")?.t1_ms ?? teaserTotal,
    [featuredTrace, teaserTotal],
  );
  // The fused OUTPUT — the rail and the shortlist — only exists once the recorded `results` (fuse)
  // stage completes; the streams/node converging beforehand are a non-output "convergence effect".
  const fusionReached = reduce !== false || !started || clockMs >= resultsEnd;

  // The featured doc (frozen results) and its trace (timing) can come from different export batches —
  // disclose that the same way /run does (the dual-stamp rule), never as one frame-accurate claim.
  const provenance = pairProvenance(featuredDoc.meta, featuredTrace);

  return (
    <section className="border-b">
      <div className="mx-auto w-full max-w-6xl px-5 py-10 sm:py-14">
        {/* honesty stamp — the recorded-run posture, stated up front */}
        <div className="text-muted-foreground flex flex-wrap items-center gap-x-2 gap-y-1 font-mono text-[11px]">
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

        {/* masthead — the one serif gesture: "feeling", the warm human note against the telemetry */}
        <h1 className="font-display mt-6 max-w-3xl text-4xl font-semibold tracking-tight sm:text-6xl sm:leading-[1.04]">
          Find the <span className="font-serif text-cultural text-[1.05em] italic">feeling</span> in the
          track.
          <span className="text-muted-foreground block">Not the crowd around it.</span>
        </h1>
        <p className="text-muted-foreground mt-5 max-w-2xl text-base sm:text-lg">
          A hybrid retrieve-then-rerank engine: cultural recall surfaces candidates, CLAP audio
          embeddings rerank them by how they actually sound, and the two legs fuse into one shortlist.
        </p>

        {/* the ignition control — load a recorded run (the console input) */}
        <EngineConsole seeds={seeds} />

        {/* THE INSTRUMENT — the dominant seam, a featured recorded run wired through it */}
        <div className="bg-card/30 mt-9 overflow-hidden rounded-2xl border">
          <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 border-b px-4 py-2.5 font-mono text-[11px]">
            <span className="text-cultural">cultural recall</span>
            <span className="text-muted-foreground tabular-nums">
              featured run ·{" "}
              <span className="text-foreground">
                {featuredDoc.seed.title} — {featuredDoc.seed.artist}
              </span>{" "}
              · {featuredTrace.mode} · recorded {formatClock(featuredTrace.total_ms)}
            </span>
            <span className="text-audio">audio rerank</span>
          </div>

          {/* folded pipeline strip — the mini-replay, driven by the same clock. The teaser animates
              only the retrieve→rerank span at a labeled speed; the long LLM `explain` step is a noted
              fact, not animated — so the time-scaling is always explicit (v1.2 cardinal rule). */}
          <div className="border-b px-4 py-3">
            <div className="text-muted-foreground mb-2 flex flex-wrap items-center justify-between gap-x-3 gap-y-1 font-mono text-[10px] tracking-[0.16em] uppercase">
              <span>pipeline · folded</span>
              <span>teaser · {teaserSpeedLabel} · explain not animated</span>
            </div>
            <FoldedStages stages={featuredTrace.stages} clockMs={clockMs} />
          </div>

          <motion.div onViewportEnter={wake} viewport={{ once: true, amount: 0.25 }}>
            {/* convergence stage — a tall vertical convergence on mobile, wide on desktop, so the
                signature never letterboxes on a phone */}
            <div className="relative">
              <div className="mx-auto block aspect-[4/5] max-h-[440px] max-w-[352px] sm:hidden">
                <Seam p={p} degraded={degraded} orientation="tall" railFormed={fusionReached} />
              </div>
              <div className="hidden sm:block sm:h-[280px]">
                <Seam p={p} degraded={degraded} orientation="wide" railFormed={fusionReached} />
              </div>
              {reduce === false && started && (
                <Button
                  variant="seam"
                  size="sm"
                  onClick={replay}
                  aria-label="Replay the convergence"
                  className="bg-background/70 absolute top-3 right-3 font-mono text-[11px] backdrop-blur"
                >
                  <RotateCcw className="size-3" aria-hidden />
                  replay
                </Button>
              )}
            </div>

            {/* the fused shortlist — strung on the rail that descends from the convergence node */}
            <div className="relative border-t px-4 pt-5 pb-5">
              {/* the rail continues down the center, threading the shortlist (the output is ON the rail) */}
              <div
                aria-hidden
                className={cn(
                  "bg-seam/45 absolute top-0 bottom-5 left-1/2 w-[2px] -translate-x-1/2 rounded-full transition-opacity duration-500",
                  fusionReached ? "opacity-100" : "opacity-0",
                )}
                style={{ boxShadow: "0 0 10px var(--seam)" }}
              />
              <p
                aria-hidden={!fusionReached}
                className={cn(
                  "text-seam relative mb-3 text-center font-mono text-[10px] tracking-[0.18em] uppercase transition-opacity duration-500",
                  fusionReached ? "opacity-100" : "opacity-0",
                )}
              >
                fused shortlist · top {top.length}
              </p>
              {/* Gated from the a11y tree too (not just visually) until the recorded results stage
                  completes — AT must not encounter the fused output before fusion. idle=final keeps it
                  exposed for SSR / no-JS / reduced-motion (fusionReached is true there). */}
              <ol aria-hidden={!fusionReached} className="relative mx-auto flex max-w-2xl flex-col gap-2">
                {top.map((r, i) => {
                  const revealed = fusionReached;
                  const isHnsw = r.sources.includes("hnsw");
                  return (
                    <li
                      key={r.position}
                      className={cn(
                        "bg-card/70 relative flex items-center gap-3 rounded-lg border px-3 py-2 backdrop-blur-sm transition-all duration-500",
                        revealed ? "translate-y-0 opacity-100" : "translate-y-1.5 opacity-0",
                      )}
                      style={{ transitionDelay: revealed && started ? `${i * 70}ms` : "0ms" }}
                    >
                      {/* the bead on the rail */}
                      <span
                        className="bg-seam ring-background absolute -top-[5px] left-1/2 size-2 -translate-x-1/2 rounded-full ring-2"
                        aria-hidden
                      />
                      <span
                        className={cn(
                          "inline-flex size-5 shrink-0 items-center justify-center rounded font-mono text-[11px] tabular-nums",
                          i === 0 ? "bg-seam/20 text-seam" : "bg-muted text-muted-foreground",
                        )}
                      >
                        {r.position}
                      </span>
                      <span className="min-w-0 flex-1 truncate text-sm">
                        {r.title} <span className="text-muted-foreground">— {r.artist}</span>
                      </span>
                      {r.audio_score != null && (
                        <span
                          className={cn(
                            "shrink-0 font-mono text-[11px] tabular-nums",
                            isHnsw ? "text-audio-deep" : "text-audio",
                          )}
                          title={isHnsw ? "global vibe match (HNSW lane)" : "CLAP audio cosine"}
                        >
                          {r.audio_score.toFixed(3)}
                        </span>
                      )}
                    </li>
                  );
                })}
              </ol>
              <div className="mt-4 text-center">
                <p className="text-muted-foreground/70 mb-1.5 font-mono text-[10px]">
                  {provenance.sameCapture
                    ? `captured ${provenance.traceDate} · ${shaStamp(provenance.traceSha, provenance.traceDirty)}`
                    : `results frozen ${provenance.docDate} (${shaStamp(provenance.docSha, provenance.docDirty)}) · telemetry captured ${provenance.traceDate} (${shaStamp(provenance.traceSha, provenance.traceDirty)})`}
                </p>
                <Link
                  href={`/run/${featuredDoc.meta.slug}`}
                  className="text-foreground/80 hover:text-foreground inline-flex items-center gap-1 text-xs underline decoration-dotted underline-offset-2"
                >
                  replay this full run, stage by stage →
                </Link>
              </div>
            </div>
          </motion.div>
        </div>
      </div>
    </section>
  );
}
