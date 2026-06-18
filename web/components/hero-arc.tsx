/**
 * The "short version" — a compact problem → dead-ends → wedge → evidence arc that frames why Doppel
 * is built as a hybrid retrieve-then-rerank engine. Pure content (server component); the leg accents
 * (amber = cultural recall, blue = audio rerank) match the two-leg duality carried across the app.
 *
 * Copy stays product/engineering-framed and neutral. The numbers it cites are the same real eval
 * figures the proof ribbon and the per-seed funnel show — no claim here that isn't backed elsewhere.
 */

import { SeamRule } from "@/components/seam-rule";
import { Term } from "@/components/term";
import { cn } from "@/lib/utils";

type Accent = "neutral" | "cultural" | "audio" | "both";

/** Leg-colored left rail per beat — the "wedge" beat (both legs) resolves to the --seam rail. */
const ACCENT_LEFT: Record<Accent, string> = {
  neutral: "border-l-border",
  cultural: "border-l-cultural",
  audio: "border-l-audio",
  both: "border-l-seam",
};

/** A miniature convergence — two legs meeting at a seam node — marking the wedge beat. */
function ConvergenceGlyph() {
  return (
    <svg viewBox="0 0 28 12" className="h-3 w-7 shrink-0" aria-hidden fill="none">
      <path d="M1 3 C7 3, 9 6, 14 6" className="stroke-cultural" strokeWidth="1.5" strokeLinecap="round" />
      <path d="M27 9 C21 9, 19 6, 14 6" className="stroke-audio" strokeWidth="1.5" strokeLinecap="round" />
      <circle cx="14" cy="6" r="2" className="fill-seam" />
    </svg>
  );
}

interface Beat {
  step: string;
  label: string;
  accent: Accent;
  body: React.ReactNode;
}

const BEATS: Beat[] = [
  {
    step: "01",
    label: "The problem",
    accent: "neutral",
    body: (
      <>
        “Play me something like this” usually just means “play me something
        popular.” Most apps go by what other people clicked, not by what the
        song actually sounds like.
      </>
    ),
  },
  {
    step: "02",
    label: "Why the easy fixes fall short",
    accent: "cultural",
    body: (
      <>
        You can’t just ask a chatbot what a song sounds like, because it has
        never heard it. And a fixed library of free-to-use tracks answers a hit
        song with thirty tunes nobody knows.
      </>
    ),
  },
  {
    step: "03",
    label: "What Doppel does",
    accent: "both",
    body: (
      <>
        It uses both sides. The crowd is good at knowing which songs get played
        together. <Term name="clap">A model that actually listens</Term> is good at
        knowing which ones sound alike. Lean on each for what it does well, and the
        picks get a lot better.
      </>
    ),
  },
  {
    step: "04",
    label: "Why you can trust it",
    accent: "audio",
    body: (
      <>
        None of this is hand-waving. Every result page lets you watch the list
        narrow down with the real numbers behind it, and see how much the
        listening step reshuffles the crowd’s picks.
      </>
    ),
  },
];

export function HeroArc() {
  return (
    <section className="py-12 sm:py-16">
      <SeamRule className="mb-10" />
      <div className="mb-8 max-w-2xl">
        <h2 className="font-display text-2xl font-semibold tracking-tight">
          The short version
        </h2>
        <p className="text-muted-foreground mt-2 text-sm">
          Finding songs that genuinely sound alike is harder than it looks. Here&rsquo;s the idea.
        </p>
      </div>

      <ol className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        {BEATS.map((beat) => (
          <li
            key={beat.step}
            className={cn("bg-card/20 rounded-xl border border-l-[3px] p-5", ACCENT_LEFT[beat.accent])}
          >
            <div className="flex items-center gap-2.5">
              <span className="text-seam font-mono text-xs font-semibold tabular-nums">{beat.step}</span>
              <h3 className="font-display text-base font-semibold tracking-tight">{beat.label}</h3>
              {beat.accent === "both" && <ConvergenceGlyph />}
            </div>
            <p className="text-muted-foreground mt-2.5 leading-relaxed">{beat.body}</p>
          </li>
        ))}
      </ol>
    </section>
  );
}
