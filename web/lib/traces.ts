/**
 * Server-only typed loader for the v1.2 replay-trace sidecars (`public/seeds/<slug>.trace.json`).
 *
 * Mirrors lib/seeds.ts: build-time reads, module-level cache, typed JSON.parse. A trace exists only
 * for seeds the exporter ran with the recorder attached — `/run/[slug]` static params come from the
 * intersection of "has a seed doc" and "has a trace", so a doc without a sidecar simply gets no
 * replay route (the static seed page still exists).
 */
import "server-only";

import { promises as fs } from "fs";
import path from "path";

import type { RunTrace } from "@/types/trace";

const SEEDS_DIR = path.join(process.cwd(), "public", "seeds");
const TRACE_SUFFIX = ".trace.json";

let cache: Map<string, RunTrace> | null = null;

async function readAll(): Promise<Map<string, RunTrace>> {
  if (cache) return cache;
  const files = (await fs.readdir(SEEDS_DIR)).filter((f) => f.endsWith(TRACE_SUFFIX));
  const entries = await Promise.all(
    files.map(async (f) => {
      const raw = await fs.readFile(path.join(SEEDS_DIR, f), "utf-8");
      const trace = JSON.parse(raw) as RunTrace;
      return [trace.slug, trace] as const;
    }),
  );
  cache = new Map(entries);
  return cache;
}

export async function getTraceBySlug(slug: string): Promise<RunTrace | null> {
  return (await readAll()).get(slug) ?? null;
}

export async function getAllTraceSlugs(): Promise<string[]> {
  return [...(await readAll()).keys()].sort();
}

/** The most recent `captured_at` across all sidecars — the console's honest "last recorded" stamp. */
export async function getLatestCaptureDate(): Promise<string | null> {
  const dates = [...(await readAll()).values()].map((t) => t.captured_at).sort();
  return dates.at(-1) ?? null;
}
