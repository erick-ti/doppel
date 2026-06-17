import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { Play } from "lucide-react";

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
import { getTraceBySlug } from "@/lib/traces";

type Params = { params: Promise<{ slug: string }> };

export async function generateStaticParams() {
  const slugs = await getAllSlugs();
  return slugs.map((slug) => ({ slug }));
}

export async function generateMetadata({ params }: Params): Promise<Metadata> {
  const { slug } = await params;
  const doc = await getSeedBySlug(slug);
  if (!doc) return { title: "Seed not found" };
  const vibePart = doc.vibe ? ` · mood: "${doc.vibe}"` : "";
  return {
    title: `${doc.seed.title} by ${doc.seed.artist}`,
    description: `The top ${doc.results.length} songs that sound like ${doc.seed.title} by ${doc.seed.artist}${vibePart}.`,
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

  // Replay links are trace-gated AND run-specific (v1.2). On a paired page the link lives inside
  // VibeSteer so it tracks the active run with the toggle — rendered here it could point at a
  // different recorded run than the visible results (Codex review 2026-06-12). A lone seed keeps
  // the static link below the header.
  const replayHref = async (slugFor: string) =>
    (await getTraceBySlug(slugFor)) !== null ? `/run/${slugFor}` : null;
  const [docReplay, plainReplay, vibeReplay] = await Promise.all([
    steer ? Promise.resolve(null) : replayHref(doc.meta.slug),
    steer ? replayHref(steer.plain.meta.slug) : Promise.resolve(null),
    steer ? replayHref(steer.vibe.meta.slug) : Promise.resolve(null),
  ]);

  return (
    <div className="mx-auto flex w-full max-w-4xl flex-col gap-8 px-5 py-10">
      <SeedHeader doc={headerDoc} />
      {docReplay && (
        <Link
          href={docReplay}
          className="text-muted-foreground hover:text-foreground -mt-4 inline-flex w-fit items-center gap-1.5 font-mono text-xs transition-colors"
        >
          <Play className="size-3" aria-hidden />
          watch this run play back, step by step
        </Link>
      )}
      {steer ? (
        // The toggle owns every run-specific surface (funnel + list + transparency) so they all
        // track the active run together — latency and the raw response body differ between the two
        // runs, so pinning them outside the toggle would desync them from the visible list.
        <VibeSteer
          plain={steer.plain}
          vibe={steer.vibe}
          initialMode={steer.initialMode}
          replayHrefs={{ plain: plainReplay, vibe: vibeReplay }}
        />
      ) : (
        <>
          <CoverageStrip coverage={doc.coverage} meta={doc.meta} />
          <section>
            <h2 className="font-display mb-4 flex items-baseline gap-2 text-xl font-semibold tracking-tight">
              The picks
              <span className="text-muted-foreground text-sm font-normal">
                top {doc.results.length}, best sound matches first
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
