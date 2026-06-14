import type { Metadata } from "next";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";

import { OpsPanel } from "@/components/ops/ops-panel";

export const metadata: Metadata = {
  title: "System status",
  description:
    "Live production status for the Doppel engine — API liveness, corpus size, queries served, last backup, and host vitals, pushed from the VPS to Cloudflare R2 every 15 minutes.",
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
        <Link
          href="/"
          className="text-muted-foreground hover:text-foreground inline-flex w-fit items-center gap-1.5 text-sm transition-colors"
        >
          <ArrowLeft className="size-4" aria-hidden />
          All seeds
        </Link>
        <h1 className="text-3xl font-bold tracking-tight sm:text-4xl">System status</h1>
        <p className="text-muted-foreground max-w-2xl text-lg leading-relaxed">
          The real production engine, live. These figures are pushed from the Hetzner VPS to a public
          Cloudflare R2 bucket every 15 minutes and fetched here client-side — sanitized counts and host
          vitals only, never request-time inference. Staleness is the down signal: an overdue snapshot
          reads as overdue, never as fresh.
        </p>
      </header>

      <OpsPanel />

      <p className="text-muted-foreground/70 font-mono text-[11px] leading-relaxed">
        Static export on Vercel · the VPS stays loopback + SSH-only (no inbound surface).
        {deployedSha ? (
          <>
            {" "}
            Deployed commit <span className="text-muted-foreground">{deployedSha}</span>.
          </>
        ) : null}
      </p>
    </div>
  );
}
