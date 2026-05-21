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

**Day 1-2**: Matcher and resolver module — recording-level MusicBrainz canonicalization, ISRC-first Deezer preview fetch, and match verification (ISRC / duration / RapidFuzz), with a 30-50 case test suite.

_Day 0 (external dependency validation) — **complete, verdict GO** (2026-05-21). All 6 checks passed; see SESSION_NOTES.md / DECISIONS.md._

## Upcoming Milestones

- **Day 3**: Candidate aggregator with conservative dedupe, Gate 1 async check, cultural ranking (RRF)
- **Day 4**: CLAP embedder + similarity scoring with batch normalization
- **Day 5**: Full database schema (tracks, audio_assets, canonical_lookups, embeddings, query_logs)
- **Day 6**: LLM explainer + FastAPI `/recommend` endpoint with both async gates and degraded modes
- **Day 7**: Deploy to VPS, first evaluation round against benchmark seeds

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
- **Candidate pool yield**: Target 200-300 after dedupe. Actual yield depends on Last.fm/ListenBrainz coverage per genre. Validated Day 3.
- **CLAP dual-load memory** — **RESOLVED (Day 0)**: ~659 MB process RSS per load (~1.3 GB dual-load across FastAPI + ARQ worker), 76 ms/clip warm on CPU, 512-dim. Fits a modest VPS.
- **Coverage matrix representativeness**: Day 0 measured 100% Deezer coverage on 5 tracks (one per genre). Re-measure across R&B, pre-2000 classics, and non-English before treating coverage as a corpus-wide claim — the small sample likely overstates it.
