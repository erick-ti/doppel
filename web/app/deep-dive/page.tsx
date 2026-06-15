import type { Metadata } from "next";
import Link from "next/link";
import { ArrowLeft, ArrowRight, Snowflake, Zap } from "lucide-react";

import { SeamRule } from "@/components/seam-rule";
import { ACTS } from "@/lib/deep-dive";
import { cn } from "@/lib/utils";

export const metadata: Metadata = {
  title: "Deep dive",
  description:
    "A walkthrough of Doppel running for real: the warm ~12s path, the cold 202→poll→200 cliff and why it's bounded by design, the lazy-corpus payoff, and the telemetry behind it — driven against the live backend over an SSH tunnel.",
};

/** One half of the same-code-path latency readout — warm (cache hit) vs cold (cache miss). */
function LatencyReadout({
  tone,
  icon,
  value,
  label,
  note,
}: {
  tone: "warm" | "cold";
  icon: React.ReactNode;
  value: string;
  label: string;
  note: string;
}) {
  // Latency, not liveness — stays in the retrieval/seam family so --ok/--warning never leak off the
  // ops register (warm cache-hit = the fused/fast ideal; cold = the deep, raw cache-miss path).
  const accent = tone === "warm" ? "text-seam" : "text-audio-deep";
  return (
    <div className="bg-card/20 p-5">
      <div className={cn("flex items-center gap-1.5 font-mono text-[11px] tracking-[0.16em] uppercase", accent)}>
        {icon}
        {label}
      </div>
      <div className={cn("font-display mt-2 text-4xl font-semibold tabular-nums", accent)}>{value}</div>
      <p className="text-muted-foreground mt-2 text-xs leading-relaxed">{note}</p>
    </div>
  );
}

export default function DeepDive() {
  return (
    <div className="mx-auto flex w-full max-w-4xl flex-col gap-12 px-5 py-12 sm:py-16">
      <header className="flex flex-col gap-4">
        <Link
          href="/"
          className="text-muted-foreground hover:text-foreground inline-flex w-fit items-center gap-1.5 text-sm transition-colors"
        >
          <ArrowLeft className="size-4" aria-hidden />
          All seeds
        </Link>
        <h1 className="font-display text-3xl font-semibold tracking-tight sm:text-4xl">Watch it run cold</h1>
        <p className="text-muted-foreground max-w-2xl text-lg leading-relaxed">
          The rest of this site serves <em>frozen</em> pipeline output for speed and safety. This page
          is the other half of the proof: the engine driven live — a warm ~12&nbsp;second answer, the
          ~12&nbsp;minute cold path and why it&rsquo;s bounded by design, and the cache payoff that makes
          both coexist. It&rsquo;s run against the real backend over an SSH tunnel — never linked from this
          site or exposed to the internet — and walked through act by act below.
        </p>
      </header>

      {/* The drama of the page: one code path, two latencies — a telemetry readout, not a video. */}
      <section className="bg-card/30 overflow-hidden rounded-2xl border">
        <div className="text-muted-foreground flex items-center gap-2 border-b px-4 py-2.5 font-mono text-[11px] tracking-[0.16em] uppercase">
          <span className="bg-seam size-1.5 rounded-full" aria-hidden />
          same code path · two latencies
        </div>
        <div className="grid gap-px sm:grid-cols-2">
          <LatencyReadout
            tone="warm"
            icon={<Zap className="size-3.5" aria-hidden />}
            value="~12 s"
            label="warm · cache hit"
            note="The median latency across the frozen exports — every candidate already embedded in the pgvector corpus, so the run skips embedding entirely."
          />
          <LatencyReadout
            tone="cold"
            icon={<Snowflake className="size-3.5" aria-hidden />}
            value="~12 min"
            label="cold · cache miss"
            note="701 s end-to-end in prod — the ARQ worker grinding MusicBrainz at ~1 req/s, bounded at ~75×7s by the resolve cap (WORKER_MAX_JOBS=1; the work is I/O-bound, so concurrency would only multiply latency)."
          />
        </div>
        <div className="text-muted-foreground border-t px-4 py-3 text-sm leading-relaxed">
          One <span className="font-mono text-xs">run_pipeline</span> coroutine serves both — the only
          difference is how many candidates miss the cache. The ~12&nbsp;min above is the full
          75-candidate production run; the recorded cold replay below is a shorter capture of the same
          shape (~3&nbsp;min, 60 uncached candidates).{" "}
          <Link
            href="/run/jolene"
            className="text-seam hover:text-seam/80 inline-flex items-center gap-1 font-medium transition-colors"
          >
            Replay the Gate-1-cold Jolene capture
            <ArrowRight className="size-3.5" aria-hidden />
          </Link>
        </div>
      </section>

      <SeamRule />

      {/* The act-by-act walkthrough, strung on the fused rail. */}
      <section className="flex flex-col gap-6">
        <div className="max-w-2xl">
          <h2 className="font-display text-2xl font-semibold tracking-tight">What the run shows</h2>
          <p className="text-muted-foreground mt-2 text-sm leading-relaxed">
            The live run, act by act, driven against the real backend over an SSH tunnel — the same
            sequence the recorded replays animate from persisted telemetry.
          </p>
        </div>

        <ol className="border-seam/25 ml-1.5 flex flex-col gap-5 border-l pl-7">
          {ACTS.map((act) => (
            <li key={act.n} className="relative">
              <span
                className="bg-seam ring-background absolute top-1.5 -left-[34px] size-2.5 rounded-full ring-4"
                aria-hidden
              />
              <div className="bg-card/30 rounded-xl border p-5">
                <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                  <span className="text-seam font-mono text-xs font-semibold tracking-[0.16em] uppercase tabular-nums">
                    Act {act.n}
                  </span>
                  <h3 className="font-display text-lg font-semibold tracking-tight">{act.title}</h3>
                  <span className="text-muted-foreground font-mono text-xs">{act.duration}</span>
                </div>
                <ul className="mt-3 flex flex-col gap-2.5">
                  {act.beats.map((beat, i) => (
                    <li key={i} className="flex gap-3">
                      <span className="bg-seam/50 mt-2 size-1.5 shrink-0 rounded-full" aria-hidden />
                      <span className="text-muted-foreground text-sm leading-relaxed">{beat}</span>
                    </li>
                  ))}
                </ul>
              </div>
            </li>
          ))}
        </ol>
      </section>

      <p className="text-muted-foreground border-t pt-6 text-sm leading-relaxed">
        Want the reasoning rather than the runtime?{" "}
        <Link
          href="/how-it-works"
          className="text-foreground underline decoration-dotted underline-offset-2"
        >
          How it works
        </Link>{" "}
        covers the design, the pipeline, and the eval evidence.
      </p>
    </div>
  );
}
