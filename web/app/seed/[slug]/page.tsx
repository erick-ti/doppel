import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { CoverageStrip } from "@/components/coverage-strip";
import { ResultList } from "@/components/result-list";
import { SeedHeader } from "@/components/seed-header";
import { TransparencyPanel } from "@/components/transparency-panel";
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

  // Cross-link the plain <-> vibe-steered pairing, whichever direction exists.
  const [base, variant] = await Promise.all([
    getBaseSeedFor(doc),
    getVibeVariantFor(doc),
  ]);
  const pair = base
    ? { slug: base.meta.slug, label: "Compare with the plain run" }
    : variant
      ? { slug: variant.meta.slug, label: "See the vibe-steered run" }
      : null;

  return (
    <div className="mx-auto flex w-full max-w-4xl flex-col gap-8 px-5 py-10">
      <SeedHeader doc={doc} pair={pair} />
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
    </div>
  );
}
