import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { ReplayPlayer } from "@/components/replay/replay-player";
import { SeedHeader } from "@/components/seed-header";
import { getSeedBySlug } from "@/lib/seeds";
import { getAllTraceSlugs, getTraceBySlug } from "@/lib/traces";

type Params = { params: Promise<{ slug: string }> };

/** A replay route exists only where BOTH the frozen seed doc and its trace sidecar shipped. */
export async function generateStaticParams() {
  const slugs = await getAllTraceSlugs();
  const withDocs = await Promise.all(
    slugs.map(async (slug) => ((await getSeedBySlug(slug)) ? slug : null)),
  );
  return withDocs.filter((s): s is string => s !== null).map((slug) => ({ slug }));
}

export async function generateMetadata({ params }: Params): Promise<Metadata> {
  const { slug } = await params;
  const doc = await getSeedBySlug(slug);
  if (!doc) return { title: "Replay not found" };
  return {
    title: `Replay: ${doc.seed.title} — ${doc.seed.artist}`,
    description: `Stage-by-stage replay of the recorded pipeline run for ${doc.seed.title} — real persisted telemetry, not a live request.`,
  };
}

export default async function RunPage({ params }: Params) {
  const { slug } = await params;
  const [doc, trace] = await Promise.all([getSeedBySlug(slug), getTraceBySlug(slug)]);
  if (!doc || !trace) notFound();

  return (
    <div className="mx-auto flex w-full max-w-4xl flex-col gap-8 px-5 py-10">
      <SeedHeader doc={doc} />
      <ReplayPlayer doc={doc} trace={trace} />
      <p className="text-muted-foreground text-sm">
        Prefer it static?{" "}
        <Link
          href={`/seed/${doc.meta.slug}`}
          className="text-foreground underline decoration-dotted underline-offset-2"
        >
          The result sheet for this seed
        </Link>{" "}
        has the full score breakdown, funnel, and raw JSON.
      </p>
    </div>
  );
}
