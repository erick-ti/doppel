import type { Metadata } from "next";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";

import { ArchitectureDag } from "@/components/how-it-works/architecture-dag";
import { EvalEvidence } from "@/components/how-it-works/eval-evidence";
import { Narrative } from "@/components/how-it-works/narrative";

export const metadata: Metadata = {
  title: "How it works",
  description:
    "How Doppel works: two killed designs, the hybrid retrieve-then-rerank wedge, the pipeline end to end, and diagnostic eval evidence that the CLAP audio leg earns its keep.",
};

export default function HowItWorks() {
  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-16 px-5 py-12 sm:py-16">
      <header className="flex flex-col gap-4">
        <Link
          href="/"
          className="text-muted-foreground hover:text-foreground inline-flex w-fit items-center gap-1.5 text-sm transition-colors"
        >
          <ArrowLeft className="size-4" aria-hidden />
          All seeds
        </Link>
        <h1 className="text-3xl font-bold tracking-tight sm:text-4xl">How it works</h1>
        <p className="text-muted-foreground max-w-2xl text-lg leading-relaxed">
          Doppel matches the <span className="text-audio">vibe</span> of a seed track by combining cultural
          retrieval with audio-embedding rerank. Here&rsquo;s the reasoning behind that design, the pipeline
          itself, and the diagnostic evidence that the audio leg earns its place.
        </p>
      </header>

      <Narrative />
      <ArchitectureDag />
      <EvalEvidence />
    </div>
  );
}
