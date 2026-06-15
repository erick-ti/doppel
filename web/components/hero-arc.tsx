/**
 * The "short version" — a compact problem → dead-ends → wedge → evidence arc that frames why Doppel
 * is built as a hybrid retrieve-then-rerank engine. Pure content (server component); the leg accents
 * (amber = cultural recall, blue = audio rerank) match the two-leg duality carried across the app.
 *
 * Copy stays product/engineering-framed and neutral. The numbers it cites are the same real eval
 * figures the proof ribbon and the per-seed funnel show — no claim here that isn't backed elsewhere.
 */

import { SeamRule } from "@/components/seam-rule";
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
        “Play me something like this” usually resolves to collaborative
        filtering, which drifts toward whatever is already popular — or to taste
        graphs that never actually listen to the song.
      </>
    ),
  },
  {
    step: "02",
    label: "Two dead ends",
    accent: "cultural",
    body: (
      <>
        Asking an LLM to read a track’s BPM and key assumes it has{" "}
        <em>heard</em> the song (it hasn’t), and Spotify closed those audio
        endpoints to new apps in 2024. Pre-embedding a royalty-free corpus
        satisfies the math but answers a chart hit with thirty tracks nobody has
        heard of.
      </>
    ),
  },
  {
    step: "03",
    label: "The wedge",
    accent: "both",
    body: (
      <>
        The fix is to let each leg cover the other’s blind spot: cultural
        sources know what listeners <em>treat</em> as similar, the audio model
        knows what actually <em>sounds</em> similar. Neither is trustworthy
        alone; together they are.
      </>
    ),
  },
  {
    step: "04",
    label: "The evidence",
    accent: "audio",
    body: (
      <>
        19/19 benchmark seeds audio-scored across 8 genres, and the rerank
        visibly reshapes the cultural shortlist — the funnel on every result
        page shows that narrowing on real numbers.
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
          How a “find songs that sound alike” idea became a two-leg retrieve-then-rerank
          pipeline.
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
