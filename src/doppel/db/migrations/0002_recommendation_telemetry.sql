-- 0002_recommendation_telemetry — Day 6 /recommend orchestration telemetry + durable results.
--
-- Extends query_logs (Day 5 shipped only the request-level columns whose meaning/source existed
-- then) with the Day-6 gate decisions + the measured counts behind them, the COLD-path job
-- lifecycle, and the degraded-path flags; and adds query_log_results — one row per returned track —
-- as the durable, queryable record of what each request actually recommended. That child table (not
-- a JSONB blob) is the single write/read shape for the WARM return, the COLD poll, AND the Day-7
-- evaluation read model: per-result analytics ("avg position of cultural backfill", "how often does
-- a track recur across seeds") are trivial SQL here and painful over JSONB. See DECISIONS.md (Day 6).
--
-- INVARIANT: never edit this file once it has been applied/committed — add a new, higher-numbered
-- migration (the runner stores a checksum and refuses to run on drift). See 0001 / Invariant #3.

-- --- query_logs: COLD-path job lifecycle. The /recommend poll reads status from HERE, not Redis —
--     ARQ is the execution queue only, so a result survives a Redis eviction/restart. The poll
--     handle is the PER-REQUEST query_logs.id (the ARQ job runs under _job_id = 'rec-<id>'). ---- --
ALTER TABLE query_logs
    ADD COLUMN status       TEXT NOT NULL DEFAULT 'succeeded'
                   CHECK (status IN ('queued', 'running', 'succeeded', 'failed')),
    ADD COLUMN error        TEXT,         -- sanitized failure summary when status = 'failed'
    ADD COLUMN completed_at TIMESTAMPTZ,  -- when the run reached a terminal status
    ADD COLUMN updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    ADD COLUMN request_key  TEXT;         -- deterministic seed+vibe key, for IN-FLIGHT dedup ONLY

-- In-flight dedup, decoupled from row identity: at most ONE active (queued/running) row per
-- request_key. Terminal rows (succeeded/failed) are deliberately NOT covered — so a later identical
-- request creates a NEW row and a fresh run, preserving per-request telemetry and never permanently
-- reusing a completed result. (A unique index over *all* statuses, keyed on a deterministic id,
-- would force every repeat of a seed onto one stale row — the bug this design avoids.) request_key
-- is the dedup key, not the handle: the poll keys on query_logs.id.
CREATE UNIQUE INDEX query_logs_active_request_key
    ON query_logs (request_key) WHERE status IN ('queued', 'running');

-- --- query_logs: Gate decisions + the counts they were compared against (Day-7 calibration needs
--     BOTH the threshold in effect AND the measured count), plus per-stage counters. All nullable:
--     a request can terminate early (no preview ⇒ cultural-only ⇒ no embedding stage). --------- --
ALTER TABLE query_logs
    ADD COLUMN gate1                    TEXT CHECK (gate1 IN ('warm', 'cold')),
    ADD COLUMN gate2                    TEXT CHECK (gate2 IN ('warm', 'cold')),
    ADD COLUMN gate1_threshold          INTEGER,
    ADD COLUMN gate2_threshold          INTEGER,
    ADD COLUMN uncached_count           INTEGER,  -- Gate-1 measured: candidates NOT in canonical_lookups
    ADD COLUMN missing_embeddings_count INTEGER,  -- Gate-2 measured: FOUND tracks lacking a servable vector
    ADD COLUMN resolved_found           INTEGER,
    ADD COLUMN resolved_rejected        INTEGER,
    ADD COLUMN resolved_not_found       INTEGER,
    ADD COLUMN embeddings_computed      INTEGER,  -- previews embedded this request (corpus growth)
    ADD COLUMN embeddings_cache_hits    INTEGER,
    ADD COLUMN audio_scored_count       INTEGER,
    ADD COLUMN backfill_count           INTEGER,  -- cultural rows added to reach RECOMMENDATION_LIMIT
    ADD COLUMN seed_audio_scored        BOOLEAN,  -- FALSE ⇒ seed had no usable preview (cultural-only)
    ADD COLUMN rationales_available     BOOLEAN;  -- FALSE ⇒ the LLM explainer was absent or failed

-- query_logs was deliberately off the Day-5 updated_at trigger (it was insert-only then); the COLD
-- lifecycle now mutates the row (queued → running → succeeded/failed), so maintain updated_at too.
CREATE TRIGGER query_logs_set_updated_at
    BEFORE UPDATE ON query_logs FOR EACH ROW EXECUTE FUNCTION set_updated_at();


-- --- query_log_results: the durable per-track recommendation record. One write/read shape for the
--     WARM return, the COLD poll, and Day-7 eval. Denormalized on purpose — it is an immutable
--     snapshot of what was served, so it must render without joining tracks/audio_assets (which can
--     change or cascade-delete underneath it). ---------------------------------------------------- --
CREATE TABLE query_log_results (
    query_log_id      BIGINT NOT NULL REFERENCES query_logs(id) ON DELETE CASCADE,
    position          INTEGER NOT NULL,            -- 1-based final rank in the response
    mbid              UUID,                         -- NULL for an unresolved cultural-backfill track
    title             TEXT NOT NULL,                -- denormalized snapshot (renders w/o a join, faithful)
    artist            TEXT NOT NULL,
    provider_track_id TEXT,                         -- builds the Deezer track-PAGE link (invariant #2: a
                                                    -- link, NEVER the ephemeral preview-audio URL)
    audio_score       REAL,                         -- raw seed-vs-candidate cosine [-1,1]; NULL if not audio-scored
    vibe_text_score   REAL,                         -- raw vibe-text cosine; NULL if no vibe / not audio-scored
    combined_score    REAL,                         -- batch-normalized fused score [0,1]; NULL for a backfill row
    cultural_score    REAL NOT NULL,                -- RRF score; every result came from the cultural pool
    was_audio_scored  BOOLEAN NOT NULL,             -- FALSE = cultural-only backfill (distinct scale from above)
    sources           TEXT[] NOT NULL DEFAULT '{}', -- cultural sources that surfaced it (provenance)
    rationale         TEXT,                         -- LLM rationale; NULL when the explainer degraded
    PRIMARY KEY (query_log_id, position)
);
-- Cross-result analytics (Day 7: "how often does track X appear", "avg position of backfill"): index mbid.
CREATE INDEX query_log_results_mbid_idx ON query_log_results (mbid);
