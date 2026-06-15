/**
 * The retrieve → rerank → explain pipeline as a single linear DAG, with the honest caps on each stage.
 * Built from flex/grid (no SVG) so it reflows to a vertical stack on mobile and stays legible — the
 * stages are colour-keyed to the leg they belong to (cultural amber → audio blue → neutral explain).
 */
import { ArrowRight } from "lucide-react";

type Leg = "cultural" | "audio" | "fused" | "neutral";

const LEG_RING: Record<Leg, string> = {
  cultural: "border-cultural/40 bg-cultural/5",
  audio: "border-audio/40 bg-audio/5",
  fused: "border-seam/40 bg-seam/5",
  neutral: "border-border bg-card/40",
};

interface Stage {
  title: string;
  detail: string;
  leg: Leg;
}

const STAGES: Stage[] = [
  { title: "Cultural recall", detail: "Last.fm + ListenBrainz · ~200–300 raw candidates", leg: "cultural" },
  { title: "Dedupe + RRF fuse", detail: "dual-key dedupe · reciprocal-rank fusion (k=60)", leg: "cultural" },
  { title: "Resolve top 75", detail: "MusicBrainz canonicalize + Deezer verify · sequential, ~1 req/s", leg: "cultural" },
  { title: "Embed cache-misses", detail: "CLAP · in-memory decode · bounded concurrency (sem=4)", leg: "audio" },
  { title: "Score + fuse", detail: "min-max-then-fuse · pure-numpy · α=0.7 / β=0.3", leg: "fused" },
  { title: "Top 10", detail: "audio-scored first · cultural backfill tail if short", leg: "fused" },
  { title: "LLM explains", detail: "one batched call · explains, never ranks", leg: "neutral" },
];

export function ArchitectureDag() {
  return (
    <section className="flex flex-col gap-5">
      <div className="max-w-2xl">
        <h2 className="font-display text-2xl font-semibold tracking-tight">The pipeline, end to end</h2>
        <p className="text-muted-foreground mt-2 text-sm leading-relaxed">
          One <span className="font-mono text-xs">run_pipeline</span> coroutine, cache-first. The same code
          path serves a warm ~12s request and a cold ~12min one — the only difference is how many candidates
          miss the pgvector cache and need embedding.
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
          <line x1={360} y1={78} x2={360} y2={142} className="stroke-seam" strokeWidth="3" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
          <circle cx={360} cy={78} r={26} className="fill-seam" filter="url(#dag-glow)" style={{ opacity: 0.3 }} />
          <circle cx={360} cy={78} r={9} className="fill-seam" />
          <circle cx={360} cy={78} r={3.5} className="fill-background" />
          <circle cx={360} cy={142} r={3.5} className="fill-seam" />
        </svg>
        <span className="text-cultural absolute top-3 left-3 font-mono text-[10px] tracking-[0.16em] uppercase">cultural recall</span>
        <span className="text-audio absolute top-3 right-3 font-mono text-[10px] tracking-[0.16em] uppercase">audio rerank</span>
        <span className="text-seam absolute bottom-2 left-1/2 -translate-x-1/2 font-mono text-[10px] tracking-[0.16em] uppercase">fused shortlist</span>
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
          <span className="bg-cultural size-2 rounded-full" aria-hidden /> cultural recall
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="bg-audio size-2 rounded-full" aria-hidden /> audio rerank
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="bg-seam size-2 rounded-full" aria-hidden /> fused shortlist
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="bg-muted-foreground size-2 rounded-full" aria-hidden /> explanation only
        </span>
      </div>
    </section>
  );
}
