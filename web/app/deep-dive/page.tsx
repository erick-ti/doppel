import type { Metadata } from "next";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";

import { VideoSlot } from "@/components/deep-dive/video-slot";
import { ACTS } from "@/lib/deep-dive";

export const metadata: Metadata = {
  title: "Deep dive",
  description:
    "A walkthrough of Doppel running for real: the warm ~12s path, the cold 202→poll→200 cliff and why it's bounded by design, the lazy-corpus payoff, and the telemetry behind it — driven against the live backend over an SSH tunnel.",
};

export default function DeepDive() {
  return (
    <div className="mx-auto flex w-full max-w-4xl flex-col gap-10 px-5 py-12 sm:py-16">
      <header className="flex flex-col gap-4">
        <Link
          href="/"
          className="text-muted-foreground hover:text-foreground inline-flex w-fit items-center gap-1.5 text-sm transition-colors"
        >
          <ArrowLeft className="size-4" aria-hidden />
          All seeds
        </Link>
        <h1 className="text-3xl font-bold tracking-tight sm:text-4xl">Watch it run cold</h1>
        <p className="text-muted-foreground max-w-2xl text-lg leading-relaxed">
          The rest of this site serves <em>frozen</em> pipeline output for speed and safety. This page is
          the other half of the proof: the engine driven live — a warm ~12&nbsp;second answer, the
          ~12&nbsp;minute cold path and why it&rsquo;s bounded by design, and the cache payoff that makes
          both coexist. It&rsquo;s run against the real backend over an SSH tunnel — never linked from this
          site or exposed to the internet — and captured as the walkthrough below (a recorded screencast
          remains optional; the interactive replay now carries this proof).
        </p>
      </header>

      <div className="rounded-xl border p-5">
        <p className="text-sm leading-relaxed">
          <span className="font-semibold">This story is now interactive.</span>{" "}
          <span className="text-muted-foreground">
            The replay console animates recorded runs stage-by-stage from their persisted telemetry —
            including{" "}
            <Link
              href="/run/jolene"
              className="text-foreground underline decoration-dotted underline-offset-2"
            >
              a real Gate-1-cold capture
            </Link>{" "}
            of the same shape this page narrates: the MusicBrainz grind, honestly time-compressed
            (that capture resolved 60 uncached candidates in ~3 min; the production run narrated
            below hit the full ~12 min at the 75-candidate cap). The warm replays are the cache
            payoff on screen. Or{" "}
            <Link href="/" className="text-foreground underline decoration-dotted underline-offset-2">
              pick any seed from the console
            </Link>
            .
          </span>
        </p>
      </div>

      <VideoSlot />

      <section className="flex flex-col gap-6">
        <h2 className="text-2xl font-semibold tracking-tight">What the run shows</h2>
        <ol className="flex flex-col gap-5">
          {ACTS.map((act) => (
            <li key={act.n} className="rounded-xl border p-5">
              <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                <span className="text-audio font-mono text-sm font-semibold tabular-nums">
                  Act {act.n}
                </span>
                <h3 className="text-lg font-semibold tracking-tight">{act.title}</h3>
                <span className="text-muted-foreground font-mono text-xs">{act.duration}</span>
              </div>
              <ul className="mt-3 flex flex-col gap-2.5">
                {act.beats.map((beat, i) => (
                  <li key={i} className="flex gap-3">
                    <span
                      className="bg-audio/60 mt-2 size-1.5 shrink-0 rounded-full"
                      aria-hidden
                    />
                    <span className="text-muted-foreground text-sm leading-relaxed">{beat}</span>
                  </li>
                ))}
              </ul>
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
