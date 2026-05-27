# Doppel — Roadmap

## Vision

A song recommendation engine that matches the *vibe* of a seed track — mood, texture, production aesthetic, scene feel — by combining cultural retrieval with audio-embedding scoring and LLM-generated rationales.

## Stack

- **Backend**: Python 3.12+, FastAPI, Uvicorn (single worker)
- **Database**: PostgreSQL 16, pgvector extension
- **Audio embedding**: LAION-CLAP (`laion/larger_clap_music_and_speech`), 512-dim vectors
- **Background jobs**: ARQ + Redis
- **Candidate sources**: Last.fm API, ListenBrainz Labs similar-recordings endpoint, MusicBrainz API
- **Audio previews**: Deezer API (sole provider in v1)
- **String matching**: RapidFuzz
- **LLM explanation**: Claude Sonnet 4.6 via Anthropic API (configurable via `LLM_MODEL`)
- **HTTP client**: httpx (async, HTTP/2)
- **Rate limiting**: aiolimiter
- **Logging**: structlog
- **Dev environment**: Docker Compose (Postgres + Redis + FastAPI + ARQ worker)

## Architecture Direction

Hybrid retrieval-rerank with lazy embedding:

1. Cultural retrieval (Last.fm + ListenBrainz Labs) generates 200-300 candidates
2. Conservative dedupe → MusicBrainz recording-level canonicalization
3. Deezer preview fetch → match verification (ISRC / duration / string) → ephemeral CLAP embedding
4. CLAP cosine scoring (+ text-to-audio composite scoring if vibe description provided)
5. LLM generates rationales for top 10 (does not determine ranking)
6. Lazy corpus: embeddings cached in pgvector, grow with usage

Two-gate async model:
- Gate 1: if too many unresolved canonical lookups (≥15), async before MusicBrainz canonicalization
- Gate 2: if too many missing embeddings (≥10), async before embedding work

Graceful degradation:
- Seed without preview → cultural-only results
- Fewer than 10 audio-scored candidates → backfill with culturally ranked results via Reciprocal Rank Fusion

## Current Milestone

**Day 7**: Deploy to VPS, first evaluation round against benchmark seeds. Deploy-hardening items
carried from the Day-6 adversarial reviews (rationale in DECISIONS.md):
- ✓ Built + ran the app/worker Docker image end-to-end (PR #7): `/health` + a real cold `/recommend` confirmed in-container. (Image is 10.6 GB on the CUDA torch build — shrinking via a CPU-torch pin is the next step.)
- ✓ Cold-run resolve cap + tuning hardening (PR #7): top-N resolve cap (`RESOLVE_CANDIDATE_LIMIT`), `GATE1`=5 ≤ `GATE2`, `WORKER_MAX_JOBS`=1, `_validate_tuning`, verified-MBID result dedup — bounds cold latency against MusicBrainz's ~1 req/s (a 194-candidate seed had overrun the timeout at 85 resolved).
- Non-enumerable `/recommend` poll handles (random `public_id` token resolved to the row id) + API auth before any public/multi-user exposure.
- Stale-row reaper (running rows) — done in `day7-deploy-prep` (pending commit): a worker startup + 5-min-cron pass fails `running` rows stuck past `STALE_JOB_RECLAIM_S` (> `JOB_TIMEOUT_S`), freeing the in-flight dedup; Redis AOF (prod overlay) keeps `queued` jobs durable across restarts. **Deferred residual**: reconcile `queued` rows against ARQ job existence (covers a job lost *after* enqueue — the AOF-fsync window on a hard crash, or volume loss); a narrow single-user-v1 edge.
- Scope asyncpg connections to short reads/writes (release during the MB-paced resolve loop) once real concurrency warrants it.
- Calibrate the provisional knobs on real score distributions: `GATE1/GATE2_ASYNC_THRESHOLD`, `AUDIO_SIM_WEIGHT`/`VIBE_TEXT_WEIGHT`, `CLAP_EMBED_POOLING`.
- Dedup the final results on `provider_track_id`/`deezer_url` too, not just the verified MBID — the first prod run (2026-05-27, `Take Five`) surfaced one Deezer track twice under two MBIDs ("Three to Get Ready" ×2, both `/track/69122368`), which the MBID-only dedup can't catch.

_Day 0 (external dependency validation) — **complete, verdict GO** (2026-05-21). Day 1-2 (matcher/resolver) — **complete, merged 2026-05-21** (PR #2): match verification, provider-informed canonicalization, and cover/ISRC/artist-MBID hardening. Day 3 (candidate aggregator) — **complete, merged 2026-05-22** (PR #3): Last.fm + ListenBrainz sources, conservative dedupe, RRF (k=60), Gate-1, per-source isolation/observability. Day 4 (CLAP embedder + similarity scoring) — **complete, merged 2026-05-23** (PR #4): in-memory PyAV decode, deterministic duration-weighted window pooling, audio (+ optional vibe-text) cosine with within-batch min-max + α/β fusion, and hardened preview/text input guards. Day 5 (full database schema + asyncpg access layer) — **complete 2026-05-23** (PR #5): Postgres 16 + pgvector (`tracks`/`audio_assets`/`canonical_lookups`/`embeddings`/`query_logs`), a checksum-guarded raw-SQL migration runner, and the cache/corpus access layer. Day 6 (LLM explainer + FastAPI `/recommend`) — **complete, merged 2026-05-24** (PR #6 → `7ac120b`): the shared inline/worker `run_pipeline` (two async gates, cache-first resolve, ephemeral embed, scoring + cultural backfill), a degradable Claude explainer, the ARQ worker, FastAPI `/recommend` + poll, migration 0002 (telemetry + result snapshot), hardened across three adversarial-review rounds. See SESSION_NOTES.md / DECISIONS.md._

## Upcoming Milestones

Day 7 is the last planned v1 milestone. Post-v1 improvements (corpus densification, the HNSW retrieval
lane, LLM-reranking A/B, vibe-to-acoustic translation) are deferred — see BRAINDUMP.md "Future Improvements (Deferred)".

## Non-Goals

- Frontend or UI (API-first, validate with curl)
- SSE/WebSocket streaming
- User accounts, auth, multi-tenancy
- Spotify/Apple Music integration or in-app audio playback
- Fine-tuned audio models
- LLM reranking (explanation only in v1)
- Background corpus densification
- Global ANN retrieval via HNSW (index exists for future use)
- Additional preview providers beyond Deezer
- MusicBrainz local mirror
- `is_explicit` content filtering

## Open Questions

- **Deezer ISRC lookup** — **RESOLVED (Day 0)**: `/track/isrc:<ISRC>` works reliably (5/5); `DEEZER_ISRC_ENABLED` defaults true, with search+verify as the fallback. (An ISRC may map to a different release of the same recording.)
- **Deezer rate limits** — **PARTIAL (Day 0)**: no throttling observed at 60 concurrent (~100 req/s burst), so the true ceiling is above that and unmeasured. Keep the provisioned 45 req/5 sec as a conservative limit.
- **Deezer terms permissibility**: Ephemeral embedding computation from previews is consistent with storage restrictions but not explicitly addressed in developer terms. Validate before any public deployment.
- **ListenBrainz Labs stability** — **RESOLVED (Day 0)**: similar-recordings works (4/5 seeds, 100 results each; jazz/older = thin data). Requires resolving the seed to a canonical MBID via Labs `recording-search` first — MusicBrainz MBIDs return `[]`. Still experimental; keep behind the adapter.
- **CLAP text encoder quality**: May handle cultural/emotional descriptors ("sad late night driving vibes") less well than literal acoustic terms. If evaluation shows this, an LLM pre-processing translation step is the fix.
- **Candidate pool yield**: Target 200-300 after dedupe. Actual yield depends on Last.fm/ListenBrainz coverage per genre. Aggregator built (Day 3); full multi-genre yield run still pending.
- **CLAP dual-load memory** — **RESOLVED (Day 0)**: ~659 MB process RSS per load (~1.3 GB dual-load across FastAPI + ARQ worker), 76 ms/clip warm on CPU, 512-dim. Fits a modest VPS.
- **Coverage matrix representativeness**: Day 0 measured 100% Deezer coverage on 5 tracks (one per genre). Re-measure across R&B, pre-2000 classics, and non-English before treating coverage as a corpus-wide claim — the small sample likely overstates it.
