/**
 * The retrieve → rerank → explain pipeline as a single linear DAG, with the honest caps on each stage.
 * Built from flex/grid (no SVG) so it reflows to a vertical stack on mobile and stays legible — the
 * stages are colour-keyed to the leg they belong to (cultural amber → audio blue → neutral explain).
 */
import { ArrowRight } from "lucide-react";

import { Term } from "@/components/term";

type Leg = "cultural" | "audio" | "fused" | "neutral";

const LEG_RING: Record<Leg, string> = {
  cultural: "border-cultural/40 bg-cultural/5",
  audio: "border-audio/40 bg-audio/5",
  fused: "border-seam/40 bg-seam/5",
  neutral: "border-border bg-card/40",
};

interface Stage {
  title: string;
  detail: React.ReactNode;
  leg: Leg;
}

const STAGES: Stage[] = [
  {
    title: "Ask the crowd",
    detail: <>pull each song&rsquo;s &ldquo;similar tracks&rdquo; from Last.fm and ListenBrainz (200 to 300)</>,
    leg: "cultural",
  },
  {
    title: "Merge the lists",
    detail: (
      <>
        dedupe, then blend them with <Term name="rrf">reciprocal-rank fusion</Term>
      </>
    ),
    leg: "cultural",
  },
  {
    title: "Look up the top 75",
    detail: <>resolve each against MusicBrainz, then verify a preview on Deezer (~1 a second)</>,
    leg: "cultural",
  },
  {
    title: "Listen to the new ones",
    detail: (
      <>
        the <Term name="clap">CLAP</Term> model turns each preview into an{" "}
        <Term name="embedding">embedding</Term>, saved so it never re-listens
      </>
    ),
    leg: "audio",
  },
  {
    title: "Score and blend",
    detail: (
      <>
        compare each embedding by <Term name="cosine">cosine similarity</Term>; fold in your mood at 30%
        if you added one
      </>
    ),
    leg: "fused",
  },
  {
    title: "Pick the top 10",
    detail: <>rank by the blended score; crowd picks fill any gap</>,
    leg: "fused",
  },
  {
    title: "Write the why",
    detail: (
      <>
        one batched <Term name="llm">LLM</Term> call writes a note per pick. It never ranks.
      </>
    ),
    leg: "neutral",
  },
];

export function ArchitectureDag() {
  return (
    <section className="flex flex-col gap-5">
      <div className="max-w-2xl">
        <h2 className="font-display text-2xl font-semibold tracking-tight">How it runs, start to finish</h2>
        <p className="text-muted-foreground mt-2 text-sm leading-relaxed">
          It all runs as one path. The same code answers a familiar song in about 12 seconds and a brand-new
          one in about 12 minutes. The only difference is how many songs it has to listen to fresh.
        </p>
      </div>

      {/* The section's seam emblem — the two legs converging into the fused rail, rendered (not just
          colored). The detailed, reflow-friendly stage list sits below it as the legend. */}
      <div className="bg-card/20 relative overflow-hidden rounded-xl border py-2">
        <svg viewBox="0 0 720 150" className="h-[130px] w-full sm:h-[150px]" preserveAspectRatio="xMidYMid meet" aria-hidden>
          <defs>
            <filter id="dag-glow" x="-80%" y="-80%" width="260%" height="260%">
              <feGaussianBlur stdDeviation="7" />
            </filter>
          </defs>
          {[28, 56, 84].map((y) => (
            <path
              key={`w${y}`}
              d={`M0 ${y} C 200 ${y}, 280 78, 360 78`}
              className="fill-none stroke-cultural"
              strokeWidth={y === 56 ? 2.2 : 1.5}
              strokeLinecap="round"
              vectorEffect="non-scaling-stroke"
              style={{ opacity: 0.6 }}
            />
          ))}
          {[28, 56, 84].map((y) => (
            <path
              key={`c${y}`}
              d={`M720 ${y} C 520 ${y}, 440 78, 360 78`}
              className="fill-none stroke-audio"
              strokeWidth={y === 56 ? 2.2 : 1.5}
              strokeLinecap="round"
              vectorEffect="non-scaling-stroke"
              style={{ opacity: 0.6 }}
            />
          ))}
          {/* Rail stops above the label so the descending line never crosses the text. */}
          <line x1={360} y1={78} x2={360} y2={120} className="stroke-seam" strokeWidth="3" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
          <circle cx={360} cy={78} r={26} className="fill-seam" filter="url(#dag-glow)" style={{ opacity: 0.3 }} />
          <circle cx={360} cy={78} r={9} className="fill-seam" />
          <circle cx={360} cy={78} r={3.5} className="fill-background" />
          <circle cx={360} cy={120} r={3.5} className="fill-seam" />
        </svg>
        <span className="text-cultural absolute top-3 left-3 font-mono text-[10px] tracking-[0.16em] uppercase">the crowd</span>
        <span className="text-audio absolute top-3 right-3 font-mono text-[10px] tracking-[0.16em] uppercase">the sound</span>
        {/* bg-background masks the rail behind the text as a belt; the shortened rail already clears it */}
        <span className="text-seam bg-background absolute bottom-2 left-1/2 -translate-x-1/2 rounded px-2 py-0.5 font-mono text-[10px] tracking-[0.16em] uppercase">the final list</span>
      </div>

      <ol className="flex flex-col gap-2 lg:flex-row lg:flex-wrap lg:items-stretch">
        {STAGES.map((s, i) => (
          <li key={s.title} className="flex items-stretch gap-2 lg:flex-1 lg:items-center">
            <div className={`flex-1 rounded-lg border p-3 ${LEG_RING[s.leg]}`}>
              <div className="text-sm font-semibold tracking-tight">{s.title}</div>
              <div className="text-muted-foreground mt-0.5 text-xs leading-snug">{s.detail}</div>
            </div>
            {i < STAGES.length - 1 && (
              <ArrowRight
                className="text-muted-foreground/60 size-4 shrink-0 self-center max-lg:rotate-90"
                aria-hidden
              />
            )}
          </li>
        ))}
      </ol>

      <div className="text-muted-foreground flex flex-wrap gap-x-5 gap-y-1 text-xs">
        <span className="inline-flex items-center gap-1.5">
          <span className="bg-cultural size-2 rounded-full" aria-hidden /> the crowd
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="bg-audio size-2 rounded-full" aria-hidden /> the sound
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="bg-seam size-2 rounded-full" aria-hidden /> the final list
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="bg-muted-foreground size-2 rounded-full" aria-hidden /> the write-up
        </span>
      </div>
    </section>
  );
}
