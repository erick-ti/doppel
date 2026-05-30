import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { CoverageStrip } from "@/components/coverage-strip";
import { ResultList } from "@/components/result-list";
import { SeedHeader } from "@/components/seed-header";
import { TransparencyPanel } from "@/components/transparency-panel";
import { VibeSteer } from "@/components/vibe-steer";
import {
  getAllSlugs,
  getBaseSeedFor,
  getSeedBySlug,
  getVibeVariantFor,
} from "@/lib/seeds";

type Params = { params: Promise<{ slug: string }> };

export async function generateStaticParams() {
  const slugs = await getAllSlugs();
  return slugs.map((slug) => ({ slug }));
}

export async function generateMetadata({ params }: Params): Promise<Metadata> {
  const { slug } = await params;
  const doc = await getSeedBySlug(slug);
  if (!doc) return { title: "Seed not found" };
  const vibePart = doc.vibe ? ` · vibe: "${doc.vibe}"` : "";
  return {
    title: `${doc.seed.title} — ${doc.seed.artist}`,
    description: `Top ${doc.results.length} vibe-matched recommendations for ${doc.seed.title} by ${doc.seed.artist}${vibePart}, scored by CLAP audio embeddings.`,
  };
}

export default async function SeedPage({ params }: Params) {
  const { slug } = await params;
  const doc = await getSeedBySlug(slug);
  if (!doc) notFound();

  // Resolve the plain <-> vibe-steered pairing into a single {plain, vibe} when both sides exist.
  // A doc is either plain or vibe, so at most one of these is non-null.
  const [base, variant] = await Promise.all([
    getBaseSeedFor(doc),
    getVibeVariantFor(doc),
  ]);
  const steer = base
    ? { plain: base, vibe: doc, initialMode: "vibe" as const } // navigated to the vibe slug
    : variant
      ? { plain: doc, vibe: variant, initialMode: "plain" as const } // navigated to the plain slug
      : null;

  // When a pair exists the toggle owns all vibe display, so the header is seed-identity only
  // (the plain doc carries no vibe block) with no cross-link. A lone seed keeps its own header.
  const headerDoc = steer ? steer.plain : doc;

  return (
    <div className="mx-auto flex w-full max-w-4xl flex-col gap-8 px-5 py-10">
      <SeedHeader doc={headerDoc} />
      {steer ? (
        // The toggle owns every run-specific surface (funnel + list + transparency) so they all
        // track the active run together — latency and the raw response body differ between the two
        // runs, so pinning them outside the toggle would desync them from the visible list.
        <VibeSteer
          plain={steer.plain}
          vibe={steer.vibe}
          initialMode={steer.initialMode}
        />
      ) : (
        <>
          <CoverageStrip coverage={doc.coverage} meta={doc.meta} />
          <section>
            <h2 className="mb-4 flex items-baseline gap-2 text-xl font-semibold tracking-tight">
              Recommendations
              <span className="text-muted-foreground text-sm font-normal">
                top {doc.results.length}, audio-scored first
              </span>
            </h2>
            <ResultList results={doc.results} />
          </section>
          <TransparencyPanel doc={doc} />
        </>
      )}
    </div>
  );
}
