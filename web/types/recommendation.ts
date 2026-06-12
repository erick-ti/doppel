/**
 * TypeScript mirror of the Doppel `/recommend` wire contract.
 *
 * `SeedInfo` / `ResultItem` / `DegradationInfo` / `RecommendationResponse` mirror
 * `src/doppel/api/schemas.py` field-for-field. The committed seed JSON in
 * `public/seeds/*.json` is that response body PLUS two export-only top-level keys
 * (`coverage`, `meta`) written by `scripts/export_showcase.py` — they are not part
 * of the live API schema. `SeedDocument` is the on-disk shape the showcase reads.
 *
 * Nullability is faithful to the schema: `mbid`, `deezer_url`, `audio_score`,
 * `vibe_text_score`, `combined_score`, and `rationale` can all be null on a row;
 * `cultural_score` is always present. Render defensively (see `lib/scores.ts`).
 */

export interface SeedInfo {
  title: string;
  artist: string;
  mbid: string | null;
}

export interface ResultItem {
  position: number;
  title: string;
  artist: string;
  mbid: string | null;
  /** Deezer track-PAGE link — never preview audio (invariant #2). */
  deezer_url: string | null;
  was_audio_scored: boolean;
  /** Raw CLAP audio cosine in [-1, 1]. Null on a cultural-backfill row. */
  audio_score: number | null;
  /** Raw text->audio cosine in [-1, 1]. Null when no vibe was given (or backfill). */
  vibe_text_score: number | null;
  /** Within-batch fused rerank score in [0, 1]. Null on a cultural-backfill row. */
  combined_score: number | null;
  /** Unbounded RRF (k=60) cultural-consensus score. Always present. */
  cultural_score: number;
  /**
   * Sources that surfaced this candidate, e.g. ["lastfm", "listenbrainz"]. The v2 HNSW vibe lane
   * tags its results ["hnsw"] (global vibe/acoustic retrieval, not a cultural source).
   */
  sources: string[];
  rationale: string | null;
}

export interface DegradationInfo {
  seed_audio_scored: boolean;
  cultural_backfill_count: number;
  rationales_available: boolean;
  degraded_sources: Record<string, string>;
}

/** The completed-recommendation body the live API returns (WARM 200 / COLD poll). */
export interface RecommendationResponse {
  status: string;
  query_id: number;
  seed: SeedInfo;
  vibe: string | null;
  results: ResultItem[];
  degradation: DegradationInfo;
}

/** Export-only: the retrieve -> rerank funnel counts, from the persisted query_logs row. */
export interface Coverage {
  candidate_count: number;
  resolve_attempted: number;
  resolved_found: number;
  resolved_rejected: number;
  resolved_not_found: number;
  /** null when nothing was resolve-attempted (resolved == 0): the exporter writes null, not 0. */
  found_ratio: number | null;
  audio_scored: number;
  backfill: number;
  /** null on a cultural-only run with no audio path (no embeddings step ran). */
  embeddings_cache_hits: number | null;
  embeddings_computed: number | null;
  latency_ms: number;
}

/** Export-only: staleness/provenance stamp for the frozen snapshot. */
export interface ExportMeta {
  slug: string;
  genre: string;
  exported_at: string;
  git_sha: string;
  git_dirty: boolean;
  clap_model_version: string;
  alpha: number;
  beta: number;
  resolve_candidate_limit: number;
}

/** One `public/seeds/<slug>.json` document = response body + the two export-only keys. */
export interface SeedDocument extends RecommendationResponse {
  coverage: Coverage;
  meta: ExportMeta;
}
