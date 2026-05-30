/**
 * The four-axis score breakdown — the single highest-credibility surface of the showcase.
 *
 * Each axis has DISTINCT, correct semantics. A uniform 0-100% bar would be wrong on every
 * one of them, and a sharp reviewer would catch it. So the bar fill for each axis is computed
 * differently and every axis ships an explicit caption stating what its number actually means:
 *
 *   audio     -> raw CLAP cosine in [-1, 1]; music clusters ~0.5-0.96. Fixed perceptual band.
 *   vibe      -> raw text->audio cosine in [-1, 1]; deliberately weak leg (~0.15-0.37). Fixed band.
 *               (null on audio-scored rows with no vibe)
 *   combined  -> within-batch fused rerank score in [0, 1]; top row nears 1.0 (it sits lower when
 *               vibe-steering splits the legs, or a near-duplicate of the seed was suppressed).
 *   cultural  -> unbounded RRF (k=60) consensus score, NOT a percentage. Batch-relative bar.
 *
 * The displayed number is always the real value; the bar is only a visual aid, captioned so it
 * can never be mistaken for a probability or a cross-seed-comparable percentage.
 */
import type { ResultItem } from "@/types/recommendation";

export type AxisKey = "audio" | "vibe" | "combined" | "cultural";

/** Which retrieval leg an axis belongs to — drives the two-accent color coding. */
export type Leg = "audio" | "cultural" | "fused";

export interface AxisSpec {
  key: AxisKey;
  label: string;
  /** Short tag rendered next to the number, e.g. "cosine", "fused", "RRF k=60". */
  unit: string;
  leg: Leg;
  /** One-line, honest description of what this number is (and is not). */
  caption: string;
}

export const AXES: readonly AxisSpec[] = [
  {
    key: "audio",
    label: "Audio similarity",
    unit: "cosine",
    leg: "audio",
    caption:
      "Raw CLAP audio cosine in [-1, 1] — how alike the two tracks actually sound. Music clusters around 0.5-0.96, so a plain 0-100% bar would mislead; the bar maps a 0.30-1.0 band.",
  },
  {
    key: "vibe",
    label: "Vibe-text match",
    unit: "cosine",
    leg: "audio",
    caption:
      "Raw text->audio cosine — how well the track matches your free-text vibe. The text leg is a deliberately weak signal (~0.15-0.37); the bar maps a 0-0.5 band. Null when no vibe was given.",
  },
  {
    key: "combined",
    label: "Fused rerank",
    unit: "fused",
    leg: "fused",
    caption:
      "Within-batch fused rerank score in [0, 1] — each leg is min-max-normalized within this query's batch, then alpha/beta weighted. Relative to THIS query's batch, not comparable across seeds; the top row nears 1.0, but sits lower when vibe-steering splits the legs or a near-duplicate of the seed was suppressed.",
  },
  {
    key: "cultural",
    label: "Cultural consensus",
    unit: "RRF k=60",
    leg: "cultural",
    caption:
      "Reciprocal-Rank-Fusion consensus score (k=60) — unbounded, NOT a percentage. Higher means stronger cross-source listener agreement; the bar is relative to the top consensus in this set.",
  },
] as const;

/** The raw value for an axis on a given result (null where the schema allows null). */
export function axisValue(item: ResultItem, key: AxisKey): number | null {
  switch (key) {
    case "audio":
      return item.audio_score;
    case "vibe":
      return item.vibe_text_score;
    case "combined":
      return item.combined_score;
    case "cultural":
      return item.cultural_score;
  }
}

const clamp01 = (x: number) => Math.min(1, Math.max(0, x));

/** Fixed perceptual bands for the cosine axes (see AXES captions). */
const AUDIO_BAND = { min: 0.3, max: 1.0 } as const;
const VIBE_BAND = { min: 0.0, max: 0.5 } as const;

export interface BatchStats {
  /** Max cultural_score across this seed's results — the cultural bar is relative to it. */
  maxCultural: number;
}

export function batchStats(results: ResultItem[]): BatchStats {
  const maxCultural = results.reduce((m, r) => Math.max(m, r.cultural_score), 0);
  return { maxCultural };
}

/**
 * Bar fill fraction in [0, 1] for an axis, or null if the value is null (render "n/a").
 * Each axis uses its own honest mapping — never a uniform percentage.
 */
export function axisFill(
  key: AxisKey,
  value: number | null,
  batch: BatchStats,
): number | null {
  if (value == null) return null;
  switch (key) {
    case "audio":
      return clamp01((value - AUDIO_BAND.min) / (AUDIO_BAND.max - AUDIO_BAND.min));
    case "vibe":
      return clamp01((value - VIBE_BAND.min) / (VIBE_BAND.max - VIBE_BAND.min));
    case "combined":
      return clamp01(value);
    case "cultural":
      return batch.maxCultural > 0 ? clamp01(value / batch.maxCultural) : 0;
  }
}

/** Format the displayed number with precision suited to the axis's natural scale. */
export function formatScore(key: AxisKey, value: number | null): string {
  if (value == null) return "n/a";
  // Cultural (RRF) lives near ~0.01-0.02; show more decimals so it isn't all zeros.
  return key === "cultural" ? value.toFixed(4) : value.toFixed(3);
}
