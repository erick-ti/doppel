/**
 * Cross-run rank movement, used by the vibe-steer toggle to label how each row moved when the
 * free-text vibe reweighted the rerank. Pure (no React) so the logic is trivial to reason about
 * and to test. The "baseline" is always the plain (un-steered) run, so every delta reads as
 * "where this track sat before steering".
 */
import type { ResultItem } from "@/types/recommendation";

export type RankDelta =
  | { kind: "new" } // not in the baseline top-N — entered the list under the vibe
  | { kind: "same" } // identical rank to the baseline
  | { kind: "up"; by: number } // a better (smaller) rank than baseline
  | { kind: "down"; by: number }; // a worse (larger) rank than baseline

/**
 * Stable cross-run identity for a result. Prefer the MBID; fall back to title+artist so rows
 * without a resolved MBID still pair up (the FLIP animation and the deltas both key on this).
 */
export function resultIdentity(r: ResultItem): string {
  return r.mbid ?? `${r.title}—${r.artist}`;
}

/** Map each result's identity to its 1-based rank within a list. */
export function rankMap(results: ResultItem[]): Map<string, number> {
  return new Map(results.map((r, i) => [resultIdentity(r), i + 1]));
}

/**
 * Movement of `item` (at `currentRank`, 1-based) relative to a `baseline` rank map.
 * `up` means it climbed to a smaller rank number; `new` means it isn't in the baseline at all.
 */
export function computeRankDelta(
  item: ResultItem,
  currentRank: number,
  baseline: Map<string, number>,
): RankDelta {
  const prev = baseline.get(resultIdentity(item));
  if (prev == null) return { kind: "new" };
  const diff = prev - currentRank; // positive => moved up (smaller rank number)
  if (diff === 0) return { kind: "same" };
  return diff > 0 ? { kind: "up", by: diff } : { kind: "down", by: -diff };
}
