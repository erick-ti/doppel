-- 0001_initial_schema — Doppel's caching corpus (Postgres 16 + pgvector).
--
-- Realizes BRAINDUMP "Schema separation": identity (tracks), provider evidence (audio_assets),
-- and CLAP vectors (embeddings) are kept distinct, plus a resolve cache (canonical_lookups) and
-- a request log (query_logs). See DECISIONS.md (Day 5) for the rationale behind each choice.
--
-- INVARIANT: never edit this file once it has been applied/committed (the migrate runner stores
-- a checksum and fails loudly on drift). Schema changes go in a new, higher-numbered migration.

CREATE EXTENSION IF NOT EXISTS vector;

-- Terminal resolve outcome, shared by canonical_lookups (all three values) and audio_assets
-- (found/rejected only — see its CHECK). Mirrors matching.resolver.ResolveStatus exactly.
CREATE TYPE resolve_status AS ENUM ('found', 'rejected', 'not_found');


-- tracks: pure MusicBrainz recording identity. Natural PK = the recording MBID, so different
-- recordings of the same work (live / remaster / remix) are distinct rows, each embeddable.
CREATE TABLE tracks (
    mbid        UUID PRIMARY KEY,
    title       TEXT NOT NULL,
    artist      TEXT NOT NULL,
    duration_ms INTEGER,                      -- recording length; NULL when MusicBrainz lacks it
    isrcs       TEXT[] NOT NULL DEFAULT '{}', -- MB ISRC list (the matcher keeps the matched one)
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
    -- genre_tags deferred until something populates it; ADD COLUMN is metadata-only in PG16.
);


-- audio_assets: provider-specific evidence for a recording. A track may accumulate several
-- assets (different providers / re-fetches). Only FOUND and REJECTED reach this table: the
-- resolver is Deezer-first, so "no preview" becomes NOT_FOUND *before* an MBID exists.
CREATE TABLE audio_assets (
    id                         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    mbid                       UUID NOT NULL REFERENCES tracks(mbid) ON DELETE CASCADE,
    provider                   TEXT NOT NULL DEFAULT 'deezer',
    provider_track_id          TEXT,            -- TEXT (not BIGINT) to stay provider-agnostic; nullable
    preview_url                TEXT NOT NULL,   -- find_track only returns preview-bearing hits
    provider_track_duration_ms INTEGER,         -- FULL track, not the 30 s preview; NULL tolerated
    isrc                       TEXT,
    asset_status               resolve_status NOT NULL CHECK (asset_status IN ('found', 'rejected')),
    match_confidence           REAL NOT NULL CHECK (match_confidence BETWEEN 0 AND 1),
    match_reason               TEXT NOT NULL,   -- matching.verify.MatchReason value
    isrc_match                 BOOLEAN NOT NULL DEFAULT FALSE,
    created_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- NULLS NOT DISTINCT (PG16): a no-id preview is still embeddable, so we keep it deduped (one
    -- per mbid/provider) and upsert-idempotent rather than letting NULL ids spawn duplicate rows.
    UNIQUE NULLS NOT DISTINCT (mbid, provider, provider_track_id),
    UNIQUE (id, mbid)                           -- referenced by embeddings' composite FK below
);
CREATE INDEX audio_assets_mbid_idx ON audio_assets (mbid);


-- canonical_lookups: caches (cultural candidate string) -> resolve outcome, so a repeat candidate
-- skips MusicBrainz (~1 req/sec) and Deezer. Keyed on the SAME normalization the aggregator
-- dedupes by (aggregation.candidates.normalize_text). Also the negative cache: NOT_FOUND lives
-- only here (it has no MBID to anchor in audio_assets). Gate-1's "uncached count" will read this.
CREATE TABLE canonical_lookups (
    id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    norm_title       TEXT NOT NULL,             -- normalize_text(title)
    norm_artist      TEXT NOT NULL,             -- normalize_text(artist)
    query_title      TEXT NOT NULL,             -- raw query strings, for debugging
    query_artist     TEXT NOT NULL,
    status           resolve_status NOT NULL,
    -- CASCADE (not SET NULL): a lookup pointing at a deleted track is stale, and SET NULL would
    -- null the mbid while leaving status found/rejected — violating the CHECK below and blocking
    -- the delete. Matches the CASCADE that tracks already has to audio_assets/embeddings.
    mbid             UUID REFERENCES tracks(mbid) ON DELETE CASCADE,
    match_confidence REAL CHECK (match_confidence BETWEEN 0 AND 1),
    resolver_version TEXT NOT NULL,             -- bump invalidates stale not_found/rejected entries
    last_resolved_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (norm_title, norm_artist),           -- one row per key; re-resolve overwrites (no version GC)
    -- matches resolver.py: FOUND and REJECTED both carry an MBID; only NOT_FOUND lacks one.
    CHECK ((mbid IS NULL) = (status = 'not_found'))
);


-- embeddings: CLAP vectors, one per (recording, embedding-contract version). source_confidence is
-- the match_confidence of the embedded asset, driving the re-embedding policy. The composite FK
-- makes it structurally impossible to store a vector under a different MBID than its source asset.
CREATE TABLE embeddings (
    mbid              UUID NOT NULL,
    model_version     TEXT NOT NULL,            -- config.CLAP_MODEL_VERSION (checkpoint + pooling)
    embedding         vector(512) NOT NULL,
    source_confidence REAL NOT NULL CHECK (source_confidence BETWEEN 0 AND 1),
    asset_id          BIGINT NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (mbid, model_version),
    FOREIGN KEY (mbid) REFERENCES tracks(mbid) ON DELETE CASCADE,
    FOREIGN KEY (asset_id, mbid) REFERENCES audio_assets(id, mbid)
);
-- Forward-looking ANN lane (ROADMAP: "index exists for future use"); v1 fetches by MBID. Vectors
-- are L2-normalized, so cosine distance ranks identically to inner product.
CREATE INDEX embeddings_hnsw_idx ON embeddings USING hnsw (embedding vector_cosine_ops);

-- The servable corpus: embeddings whose source asset is still a verified (found) match. EVERY read
-- path (get_embedding / fetch_embeddings / knn) queries this view, so the found-only invariant lives
-- in one place and no read path can forget it. A re-resolve that rejects an asset purges its
-- embeddings on the write side; this view is the read-side backstop for any row that slips through.
CREATE VIEW servable_embeddings AS
    SELECT e.mbid, e.model_version, e.embedding, e.source_confidence, e.asset_id,
           e.created_at, e.updated_at
    FROM embeddings e
    JOIN audio_assets a ON a.id = e.asset_id
    WHERE a.asset_status = 'found';


-- query_logs: one row per /recommend request (populated Day 6). Day 5 ships only columns whose
-- meaning + source exist today (yield, latency, degraded — the ROADMAP open questions). Day 6
-- adds gate/embed/backfill counters and the result representation; log tables extend cheaply.
CREATE TABLE query_logs (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    seed_title      TEXT NOT NULL,
    seed_artist     TEXT NOT NULL,
    vibe_text       TEXT,
    seed_mbid       UUID,                        -- soft ref (the seed may not resolve / persist)
    candidate_count INTEGER,                     -- deduped cultural pool size (AggregateResult.count)
    degraded        BOOLEAN NOT NULL DEFAULT FALSE,
    failed_sources  JSONB NOT NULL DEFAULT '{}',
    latency_ms      INTEGER,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);


-- Auto-maintain updated_at on the mutable tables (canonical_lookups uses last_resolved_at instead).
CREATE FUNCTION set_updated_at() RETURNS trigger AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER tracks_set_updated_at
    BEFORE UPDATE ON tracks FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER audio_assets_set_updated_at
    BEFORE UPDATE ON audio_assets FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER embeddings_set_updated_at
    BEFORE UPDATE ON embeddings FOR EACH ROW EXECUTE FUNCTION set_updated_at();
