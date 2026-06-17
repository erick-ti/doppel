import type { Metadata } from "next";

import { ArchitectureDag } from "@/components/how-it-works/architecture-dag";
import { EvalEvidence } from "@/components/how-it-works/eval-evidence";
import { Narrative } from "@/components/how-it-works/narrative";
import { BackLink } from "@/components/back-link";
import { SeamRule } from "@/components/seam-rule";

export const metadata: Metadata = {
  title: "How it works",
  description:
    "How Doppel works: the two ideas that failed first, the approach that stuck, and the evidence the listening step earns its keep.",
};

export default function HowItWorks() {
  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-16 px-5 py-12 sm:py-16">
      <header className="flex flex-col gap-4">
        <BackLink label="Home" />
        <h1 className="font-display text-3xl font-semibold tracking-tight sm:text-4xl">How it works</h1>
        <p className="text-muted-foreground max-w-2xl text-lg leading-relaxed">
          Doppel finds songs that match the <span className="text-audio">feel</span>{" "}of one you love,
          by mixing what the crowd plays together with a model that actually listens. Here&rsquo;s the
          thinking behind it, how it runs, and the proof the listening step earns its keep.
        </p>
      </header>

      <Narrative />
      <SeamRule />
      <ArchitectureDag />
      <SeamRule />
      <EvalEvidence />
    </div>
  );
}
