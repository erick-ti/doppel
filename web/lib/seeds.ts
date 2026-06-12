/**
 * Server-only typed loader for the frozen showcase seeds.
 *
 * Reads every `public/seeds/*.json` at build time (static generation) and returns it typed as
 * `SeedDocument`. Adding a new exported seed needs no code change — it appears in the gallery
 * automatically, ordered by the curated genre sequence below.
 *
 * The seeds split into two groups by the presence of a `vibe`:
 *   - genre heroes  (vibe === null) -> the main gallery
 *   - vibe variants (vibe !== null) -> flagged as vibe-steered, paired back to their base seed
 */
import "server-only";

import { promises as fs } from "fs";
import path from "path";

import type { SeedDocument } from "@/types/recommendation";

const SEEDS_DIR = path.join(process.cwd(), "public", "seeds");

/** Curated display order for the genre heroes (most recognizable first -> long-tail coverage proof). */
const GENRE_ORDER: readonly string[] = [
  "pop",
  "r&b",
  "hip-hop",
  "indie",
  "electronic",
  "jazz",
  "pre-2000",
  "non-english",
];

function genreRank(genre: string): number {
  const i = GENRE_ORDER.indexOf(genre);
  return i === -1 ? GENRE_ORDER.length : i;
}

export function isVibeSteered(doc: SeedDocument): boolean {
  return doc.vibe != null && doc.vibe.trim().length > 0;
}

let cache: SeedDocument[] | null = null;

async function readAll(): Promise<SeedDocument[]> {
  if (cache) return cache;
  // `.trace.json` files are v1.2 replay sidecars (types/trace.ts), not SeedDocuments — never load
  // them here or the gallery would try to render a trace (no `meta`/`results` shape).
  const files = (await fs.readdir(SEEDS_DIR)).filter(
    (f) => f.endsWith(".json") && !f.endsWith(".trace.json"),
  );
  const docs = await Promise.all(
    files.map(async (f) => {
      const raw = await fs.readFile(path.join(SEEDS_DIR, f), "utf-8");
      return JSON.parse(raw) as SeedDocument;
    }),
  );
  cache = docs;
  return docs;
}

/** All seeds, deterministically ordered: by genre sequence, base seed before its vibe variant. */
export async function getAllSeeds(): Promise<SeedDocument[]> {
  const docs = await readAll();
  return [...docs].sort((a, b) => {
    const g = genreRank(a.meta.genre) - genreRank(b.meta.genre);
    if (g !== 0) return g;
    // Within a genre: base (no vibe) first, then vibe variants; finally by slug for stability.
    const av = isVibeSteered(a) ? 1 : 0;
    const bv = isVibeSteered(b) ? 1 : 0;
    if (av !== bv) return av - bv;
    return a.meta.slug.localeCompare(b.meta.slug);
  });
}

export async function getGenreHeroes(): Promise<SeedDocument[]> {
  return (await getAllSeeds()).filter((d) => !isVibeSteered(d));
}

export async function getVibeVariants(): Promise<SeedDocument[]> {
  return (await getAllSeeds()).filter(isVibeSteered);
}

export async function getSeedBySlug(slug: string): Promise<SeedDocument | null> {
  const docs = await readAll();
  return docs.find((d) => d.meta.slug === slug) ?? null;
}

export async function getAllSlugs(): Promise<string[]> {
  return (await readAll()).map((d) => d.meta.slug);
}

/**
 * For a vibe-steered seed, the matching base seed (same title+artist, no vibe), if exported.
 * Lets the results page cross-link plain <-> vibe runs (the Phase-2 toggle lives on this pairing).
 */
export async function getBaseSeedFor(doc: SeedDocument): Promise<SeedDocument | null> {
  if (!isVibeSteered(doc)) return null;
  const docs = await readAll();
  return (
    docs.find(
      (d) =>
        !isVibeSteered(d) &&
        d.seed.title === doc.seed.title &&
        d.seed.artist === doc.seed.artist,
    ) ?? null
  );
}

/** The vibe-steered variant of a base seed, if one was exported. */
export async function getVibeVariantFor(doc: SeedDocument): Promise<SeedDocument | null> {
  if (isVibeSteered(doc)) return null;
  const docs = await readAll();
  return (
    docs.find(
      (d) =>
        isVibeSteered(d) &&
        d.seed.title === doc.seed.title &&
        d.seed.artist === doc.seed.artist,
    ) ?? null
  );
}
