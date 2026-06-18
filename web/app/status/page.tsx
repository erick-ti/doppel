import type { Metadata } from "next";

import { BackLink } from "@/components/back-link";
import { OpsPanel } from "@/components/ops/ops-panel";

export const metadata: Metadata = {
  title: "System status",
  description:
    "Live status for the Doppel engine: whether it's up, how many songs it knows, searches run, and basic server health.",
};

// Build-time provenance: Vercel exposes VERCEL_GIT_COMMIT_SHA in the build env (System Environment
// Variables enabled), and a statically-rendered server component bakes it into the prerendered HTML.
// Absent locally (dev) ⇒ omitted. This is the DEPLOYED commit — distinct from the live feed's
// "updated Nm ago" freshness inside the panel, which is fetched client-side at runtime.
const deployedSha = process.env.VERCEL_GIT_COMMIT_SHA?.slice(0, 7) ?? null;

export default function StatusPage() {
  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-8 px-5 py-12 sm:py-16">
      <header className="flex flex-col gap-4">
        <BackLink label="Home" />
        <h1 className="font-display text-3xl font-semibold tracking-tight sm:text-4xl">System status</h1>
        <p className="text-muted-foreground max-w-2xl text-lg leading-relaxed">
          The real engine, live. These numbers come straight from the server every 15 minutes. Just counts
          and basic health, nothing private. If the server goes quiet, the numbers show as overdue instead
          of pretending everything&rsquo;s fine.
        </p>
      </header>

      <OpsPanel />

      <p className="text-muted-foreground font-mono text-[11px] leading-relaxed">
        This site is just static files. The server has no public way in.
        {deployedSha ? (
          <>
            {" "}
            Deployed build <span className="text-muted-foreground">{deployedSha}</span>.
          </>
        ) : null}
      </p>
    </div>
  );
}
