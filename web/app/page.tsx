import { HeroArc } from "@/components/hero-arc";
import { SeedBox } from "@/components/seed-box";
import { SeedCard } from "@/components/seed-card";
import { getGenreHeroes, getVibeVariants } from "@/lib/seeds";

/** The four-way wedge — the combination no single competitor does. */
const WEDGE = [
  { label: "cultural recall", leg: "cultural" as const },
  { label: "perceptual audio rerank", leg: "audio" as const },
  { label: "text vibe-steering", leg: "audio" as const },
  { label: "grounded rationale", leg: "neutral" as const },
];

const DOT: Record<string, string> = {
  audio: "bg-audio",
  cultural: "bg-cultural",
  neutral: "bg-muted-foreground",
};

export default async function Home() {
  const [heroes, variants] = await Promise.all([
    getGenreHeroes(),
    getVibeVariants(),
  ]);

  return (
    <div className="mx-auto w-full max-w-6xl px-5">
      {/* Hero */}
      <section className="py-12 sm:py-24">
        <h1 className="max-w-3xl text-4xl leading-tight font-bold tracking-tight sm:text-5xl">
          Find songs that <span className="text-audio">sound</span> like the one
          you love — not just what other listeners clicked.
        </h1>
        <p className="text-muted-foreground mt-6 max-w-2xl text-lg">
          Doppel is a hybrid retrieve-then-rerank engine: cultural sources
          surface candidates, CLAP audio embeddings rerank them by how they
          actually sound, and an LLM explains the picks — but never ranks them.
        </p>

        <div className="bg-card/50 mt-8 inline-flex flex-wrap items-center gap-x-2 gap-y-1 rounded-lg border px-4 py-2 font-mono text-sm">
          <span className="font-semibold tabular-nums">19/19</span>
          <span className="text-muted-foreground">
            benchmark seeds audio-scored across 8 genres
          </span>
          <span className="text-muted-foreground/50">·</span>
          <span className="text-muted-foreground">median resolve found-ratio</span>
          <span className="font-semibold tabular-nums">0.987</span>
        </div>

        <div className="mt-6 flex flex-wrap gap-2">
          {WEDGE.map((w) => (
            <span
              key={w.label}
              className="border-border text-foreground/80 inline-flex items-center gap-2 rounded-full border px-3 py-1 text-sm"
            >
              <span
                className={`size-1.5 rounded-full ${DOT[w.leg]}`}
                aria-hidden
              />
              {w.label}
            </span>
          ))}
        </div>

        <SeedBox />
      </section>

      {/* The problem -> dead-ends -> wedge -> evidence narrative */}
      <HeroArc />

      {/* Gallery — genre heroes */}
      <section id="seed-gallery" className="scroll-mt-20 pb-8">
        <div className="mb-5 flex items-baseline justify-between">
          <h2 className="text-xl font-semibold tracking-tight">Seed gallery</h2>
          <span className="text-muted-foreground text-sm">
            {heroes.length} genres · click any seed
          </span>
        </div>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {heroes.map((doc) => (
            <SeedCard key={doc.meta.slug} doc={doc} />
          ))}
        </div>
      </section>

      {/* Gallery — vibe-steered variants */}
      {variants.length > 0 && (
        <section className="pb-12">
          <div className="mb-5">
            <h2 className="text-xl font-semibold tracking-tight">
              Vibe-steered runs
            </h2>
            <p className="text-muted-foreground mt-1 max-w-2xl text-sm">
              The same seed, reshaped by a free-text mood. Directional steering,
              not a hard filter — the text encoder is a deliberately weak leg.
            </p>
          </div>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {variants.map((doc) => (
              <SeedCard key={doc.meta.slug} doc={doc} />
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
