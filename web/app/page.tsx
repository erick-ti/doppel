import { ConvergenceHero } from "@/components/hero/convergence-hero";
import { HeroArc } from "@/components/hero-arc";
import { OpsPanel } from "@/components/ops/ops-panel";
import { SeedCard } from "@/components/seed-card";
import { SeamRule } from "@/components/seam-rule";
import { fingerprintData } from "@/lib/fingerprint";
import { getGenreHeroes, getSeedBySlug, getVibeVariants } from "@/lib/seeds";
import { getAllTraceSlugs, getLatestCaptureDate, getTraceBySlug } from "@/lib/traces";

/** The featured run wired through the hero seam — a recognizable, clean, warm capture. */
const PREFERRED_FEATURED = "midnight-city";

export default async function Home() {
  const [heroes, variants, latestCapture, traceSlugs] = await Promise.all([
    getGenreHeroes(),
    getVibeVariants(),
    getLatestCaptureDate(),
    getAllTraceSlugs(),
  ]);

  // Compact, client-safe facts for the picker (lib/seeds is server-only). Intersected with the trace
  // sidecars BY CONSTRUCTION: the picker links /run/[slug], which only static-generates for doc∩trace.
  const withTrace = new Set(traceSlugs);
  const consoleSeeds = [...heroes, ...variants]
    .filter((doc) => withTrace.has(doc.meta.slug))
    .map((doc) => ({
      slug: doc.meta.slug,
      title: doc.seed.title,
      artist: doc.seed.artist,
      genre: doc.meta.genre,
      vibe: doc.vibe,
      fp: fingerprintData(doc),
    }));

  // Pick the featured run: the preferred seed if it has a trace, else the first hero that does.
  const featuredSlug = withTrace.has(PREFERRED_FEATURED)
    ? PREFERRED_FEATURED
    : (heroes.find((h) => withTrace.has(h.meta.slug))?.meta.slug ?? PREFERRED_FEATURED);
  const [featuredDoc, featuredTrace] = await Promise.all([
    getSeedBySlug(featuredSlug),
    getTraceBySlug(featuredSlug),
  ]);

  return (
    <>
      {featuredDoc && featuredTrace && (
        <ConvergenceHero
          seeds={consoleSeeds}
          featuredDoc={featuredDoc}
          featuredTrace={featuredTrace}
          latestCapture={latestCapture}
        />
      )}

      <div className="mx-auto w-full max-w-6xl px-5">
        {/* LIVE register — the real production system right now, deliberately distinct from the
            RECORDED replays the console links to (the juxtaposition is the point). */}
        <section className="py-8">
          <OpsPanel />
        </section>

        {/* The problem -> dead-ends -> wedge -> evidence narrative */}
        <HeroArc />

        {/* Gallery — genre heroes. pb matches the vibe-steered gallery below so the two galleries
            bracket the column with equal bottom space (consistent vertical rhythm). */}
        <section id="seed-gallery" className="scroll-mt-20 pb-12">
          <div className="mb-5 flex items-baseline justify-between">
            <h2 className="font-display text-xl font-semibold tracking-tight">Browse the songs</h2>
            <span className="text-muted-foreground text-sm">
              {heroes.length} genres · tap any one
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
          <>
            <SeamRule className="mb-10" />
            <section className="pb-12">
            <div className="mb-5">
              <h2 className="font-display text-xl font-semibold tracking-tight">
                Steer it with a mood
              </h2>
              <p className="text-muted-foreground mt-1 max-w-2xl text-sm">
                The same starting song, nudged by a few words about the feel you want. It leans the
                results that way. It won&rsquo;t force them.
              </p>
            </div>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
              {variants.map((doc) => (
                <SeedCard key={doc.meta.slug} doc={doc} />
              ))}
            </div>
            </section>
          </>
        )}
      </div>
    </>
  );
}
