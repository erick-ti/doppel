/**
 * Frozen eval evidence for the /how-it-works depth layer.
 *
 * Every figure here is transcribed from ONE real diagnostic run — the warm full benchmark
 * `eval/reports/eval-full-20260527-083852.json` (gitignored; produced by `python -m eval.harness
 * --seeds full`). The provenance stamp below pins the exact run so the page is honestly dated, the
 * same way the per-seed exports carry their own `meta`.
 *
 * HONESTY INVARIANTS (these numbers are public claims):
 *  - This is a DIAGNOSTIC coverage/behavior run, NOT precision/recall. There is no ground-truth
 *    "good vibe match" label, so none of this measures or claims to beat any competitor. The page
 *    must label it diagnostic wherever it renders.
 *  - The audio/vibe-text figures are raw CLAP cosines (the same scale the per-row score breakdown
 *    shows), never rescaled to look like percentages.
 *  - The ablation is N=75 only (the resolve cap of this run). The plan once floated an "N=20 vs N=75"
 *    comparison, but no committed run backs an N=20 number, so it is deliberately NOT rendered — the
 *    ablation is framed as "CLAP reshuffles the cultural shortlist," which the overlap/displacement
 *    here genuinely show, not as a tuned-vs-untuned A/B.
 */

export interface EvalProvenance {
  run: string;
  ranAt: string;
  seedSet: string;
  resolveLimit: number;
  /** The diagnostic run had the explainer OFF — these are scoring metrics, not rationale quality. */
  explain: boolean;
}

export interface GenreBand {
  genre: string;
  label: string;
  /** Lowest audio cosine seen across this genre's seeds' top-10. */
  min: number;
  /** Highest audio cosine seen across this genre's seeds' top-10. */
  max: number;
  seeds: string[];
}

export interface ScoreBand {
  min: number;
  max: number;
}

export interface AblationStats {
  k: number;
  overlapMedian: number;
  overlapMin: number;
  overlapMax: number;
  displacementMedian: number;
  displacementMin: number;
  displacementMax: number;
}

export interface AblationExample {
  seed: string;
  genre: string;
  /** Top-k overlap between the pure-RRF order and the CLAP-reranked order (0 = fully reshuffled). */
  overlap: number;
  /** Mean rank displacement of the shared tracks between the two orders. */
  displacement: number;
  /** The CLAP-reranked top 3 (note: the seed's own master is suppressed — see PR #12). */
  clapTop3: string[];
}

export const EVAL_PROVENANCE: EvalProvenance = {
  run: "eval-full-20260527-083852",
  ranAt: "2026-05-27T08:38:52+00:00",
  seedSet: "full",
  resolveLimit: 75,
  explain: false,
};

export const EVAL_HEADLINE = {
  seedsAudioScored: 19,
  seedsTotal: 19,
  genres: 8,
  foundRatioMedian: 0.987,
} as const;

/** Per-genre audio-cosine ranges — the "works across the whole map" evidence. Curated genre order. */
export const GENRE_BANDS: readonly GenreBand[] = [
  { genre: "pop", label: "Pop", min: 0.835, max: 0.919, seeds: ["Blinding Lights", "good 4 u"] },
  { genre: "r&b", label: "R&B", min: 0.756, max: 0.87, seeds: ["Pink + White", "Cranes in the Sky"] },
  { genre: "hip-hop", label: "Hip-hop", min: 0.685, max: 0.93, seeds: ["HUMBLE.", "Passionfruit"] },
  { genre: "indie", label: "Indie", min: 0.759, max: 0.946, seeds: ["The Less I Know the Better", "Two Weeks"] },
  { genre: "electronic", label: "Electronic", min: 0.49, max: 0.883, seeds: ["Midnight City", "Strobe"] },
  { genre: "jazz", label: "Jazz", min: 0.904, max: 0.956, seeds: ["Take Five", "So What"] },
  { genre: "pre-2000", label: "Pre-2000", min: 0.677, max: 0.851, seeds: ["Bohemian Rhapsody", "Dreams"] },
  { genre: "non-english", label: "Non-English", min: 0.786, max: 0.906, seeds: ["Despacito", "La Vie en rose"] },
] as const;

/**
 * The two legs live in different ranges — audio cosine clusters high, the deliberately-weak text
 * encoder clusters low — which is exactly why fusion min-max-normalizes each leg WITHIN a batch
 * before weighting (you can't fuse raw values on different scales). These bands are the empirical
 * justification, drawn from the audio top-10s and the three vibe-seed text cosines respectively.
 */
export const AUDIO_BAND: ScoreBand = { min: 0.49, max: 0.956 };
export const VIBE_BAND: ScoreBand = { min: 0.15, max: 0.372 };

export const ABLATION: AblationStats = {
  k: 10,
  overlapMedian: 0.2,
  overlapMin: 0.0,
  overlapMax: 0.5,
  displacementMedian: 3.4,
  displacementMin: 2.4,
  displacementMax: 4.4,
};

/** A few real seeds showing how far CLAP moves the order, with the reranked top 3. */
export const ABLATION_EXAMPLES: readonly AblationExample[] = [
  {
    seed: "Take Five — The Dave Brubeck Quartet",
    genre: "jazz",
    overlap: 0.4,
    displacement: 4,
    clapTop3: ["Alphanumeric — Lee Konitz", "Red Pepper Blues — Art Pepper", "Three to Get Ready — Dave Brubeck"],
  },
  {
    seed: "HUMBLE. — Kendrick Lamar",
    genre: "hip-hop",
    overlap: 0.3,
    displacement: 2.6,
    clapTop3: ["DNA. — Kendrick Lamar", "Magnolia — Playboi Carti", "Stir Fry — Migos"],
  },
  {
    seed: "Strobe — deadmau5",
    genre: "electronic",
    overlap: 0.3,
    displacement: 3.6,
    clapTop3: ["Opus — Eric Prydz", "Create — OVERWERK", "Virus (How About Now) — Martin Garrix"],
  },
] as const;
