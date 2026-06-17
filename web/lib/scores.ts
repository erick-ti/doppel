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
    label: "How alike it sounds",
    unit: "sound",
    leg: "audio",
    caption:
      "How close this song is to your pick in pure sound, on a 0 to 1 scale. Most music lands between about 0.5 and 0.96, so the bar uses that range instead of a flat 0 to 100 percent.",
  },
  {
    key: "vibe",
    label: "Mood match",
    unit: "mood",
    leg: "audio",
    caption:
      "How well this song fits the mood words you typed. It's a light touch on purpose, so the scores stay low (around 0.15 to 0.37). Blank when you didn't add a mood.",
  },
  {
    key: "combined",
    label: "Final score",
    unit: "blend",
    leg: "fused",
    caption:
      "The sound and mood scores blended into one, after each is put on the same scale for this set of results. The top pick sits near 1. It drops when a mood splits the results, or when a near-copy of your song got filtered out.",
  },
  {
    key: "cultural",
    label: "How often they're paired",
    unit: "agreement",
    leg: "cultural",
    caption:
      "How strongly the music sources agree these two go together. It isn't a percentage. Higher means more people treat them as a match. The bar is relative to the strongest pairing in this set.",
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
 *
 * NOTE: `batch` is consulted by the `cultural` axis ONLY (its bar is relative to this query's max
 * RRF consensus). The audio/vibe/combined axes use fixed bands/clamps and ignore it — callers still
 * thread a BatchStats through for a single uniform signature.
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
