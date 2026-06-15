/**
 * Earned, deterministic "signal fingerprints" — the data-derived replacement for the old
 * letter-on-a-gradient cover (seed-card.tsx) and the generic picker rows.
 *
 * NOTHING here is decorative or random: every shape is computed from a seed's REAL frozen telemetry,
 * so each seed renders a visibly distinct mark and the imagery is earned by the engine, not faked.
 * Pure + client-safe (no server-only import): it runs in the server seed-card AND the client picker.
 *
 * The dual spectrum maps the two retrieval legs:
 *   - cool AUDIO bars    -> the audio_score cosines, band-normalized via scores.ts AUDIO_BAND
 *   - warm CULTURAL bars -> the RRF cultural_score, batch-relative
 *   - the rank-1 column carries a SEAM node; combined_score drives per-bar emphasis.
 */
import { axisFill, batchStats } from "@/lib/scores";
import type { SeedDocument } from "@/types/recommendation";

export interface FingerprintRow {
  /** Sources that surfaced the row — "hnsw" gets the deep-cool accent. */
  sources: string[];
}

export interface FingerprintData {
  slug: string;
  /** AUDIO leg: band-normalized cosines in [0,1], rank order. null = a row with no audio score. */
  audio: (number | null)[];
  /** CULTURAL leg: batch-relative RRF heights in [0,1], rank order. */
  cultural: number[];
  /** FUSED emphasis: combined_score in [0,1], rank order. null on cultural-backfill rows. */
  fused: (number | null)[];
  rows: FingerprintRow[];
  /** True for a cultural-only / degraded run (no audio rerank) -> hatched audio band. */
  degraded: boolean;
}

/** Derive the deterministic fingerprint payload for a seed. */
export function fingerprintData(doc: SeedDocument): FingerprintData {
  const batch = batchStats(doc.results);
  return {
    slug: doc.meta.slug,
    audio: doc.results.map((r) => axisFill("audio", r.audio_score, batch)),
    cultural: doc.results.map((r) => axisFill("cultural", r.cultural_score, batch) ?? 0),
    fused: doc.results.map((r) => r.combined_score),
    rows: doc.results.map((r) => ({ sources: r.sources })),
    degraded:
      !doc.degradation.seed_audio_scored ||
      doc.coverage.audio_scored === 0 ||
      doc.degradation.cultural_backfill_count >= doc.results.length,
  };
}
