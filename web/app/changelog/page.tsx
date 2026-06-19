import type { Metadata } from "next";

import { BackLink } from "@/components/back-link";
import { ConvergenceMasthead } from "@/components/changelog/convergence-masthead";
import { ReleaseTimeline } from "@/components/changelog/release-timeline";

export const metadata: Metadata = {
  title: "Changelog",
  description:
    "How Doppel came together, release by release. Every entry links to the real pull request behind it.",
};

export default function ChangelogPage() {
  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-8 px-5 py-12 sm:py-16">
      <header className="flex flex-col gap-4">
        <BackLink label="Home" />
        <h1 className="font-display text-3xl font-semibold tracking-tight sm:text-4xl">Changelog</h1>
        <p className="text-muted-foreground max-w-2xl text-lg leading-relaxed">
          How Doppel came together, newest first. The two halves of the engine, the crowd and the sound,
          braid into one result, and everything below built toward it. Every entry links to the real pull
          request behind it.
        </p>
      </header>

      <ConvergenceMasthead />

      {/* tuck the list up so the masthead's fused rail descends straight into the first (radiant) node,
          cancelling the parent flex gap so the convergence reads as one continuous through-line */}
      <ReleaseTimeline className="-mt-8" />
    </div>
  );
}
