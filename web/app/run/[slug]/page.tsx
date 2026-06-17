import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { ReplayPlayer } from "@/components/replay/replay-player";
import { SeamRule } from "@/components/seam-rule";
import { SeedHeader } from "@/components/seed-header";
import { getSeedBySlug } from "@/lib/seeds";
import { getAllTraceSlugs, getTraceBySlug } from "@/lib/traces";
import { cn, linkFocus } from "@/lib/utils";

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
    title: `Replay: ${doc.seed.title} by ${doc.seed.artist}`,
    description: `Watch the saved run for ${doc.seed.title} play back, step by step.`,
  };
}

export default async function RunPage({ params }: Params) {
  const { slug } = await params;
  const [doc, trace] = await Promise.all([getSeedBySlug(slug), getTraceBySlug(slug)]);
  if (!doc || !trace) notFound();

  return (
    <div className="mx-auto flex w-full max-w-4xl flex-col gap-8 px-5 py-10">
      <SeedHeader doc={doc} />
      <SeamRule />
      <ReplayPlayer doc={doc} trace={trace} />
      <p className="text-muted-foreground text-sm">
        Want the quick version?{" "}
        <Link
          href={`/seed/${doc.meta.slug}`}
          className={cn("text-foreground underline decoration-dotted underline-offset-2", linkFocus)}
        >
          The result page
        </Link>{" "}
        has the same picks without the playback.
      </p>
    </div>
  );
}
