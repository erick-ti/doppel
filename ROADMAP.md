# Doppel Roadmap

## Vision

A song recommendation engine that matches the *vibe* of a seed track (its mood,
texture, production aesthetic, and scene feel) by combining cultural retrieval
with audio-embedding scoring and LLM-generated rationales.

## Stack

- **Backend**: Python 3.12+, FastAPI, Uvicorn (single worker)
- **Database**: PostgreSQL 16, pgvector extension
- **Audio embedding**: LAION-CLAP (`laion/larger_clap_music_and_speech`), 512-dim vectors
- **Background jobs**: ARQ + Redis
- **Candidate sources**: Last.fm API, ListenBrainz Labs similar-recordings
- **Canonicalization + metadata**: MusicBrainz API
- **Audio previews**: Deezer API (sole provider in v1)
- **String matching**: RapidFuzz
- **LLM explanation**: Claude Sonnet 4.6 via Anthropic API (configurable via `LLM_MODEL`)
- **HTTP client**: httpx (async, HTTP/2)
- **Rate limiting**: aiolimiter (MusicBrainz's ~1 req/sec limit)
- **Observability**: telemetry in Postgres (`query_logs` + `query_log_results`), not a logging framework
- **Dev environment**: Docker Compose (Postgres + Redis + FastAPI + ARQ worker)
- **Showcase frontend**: Next.js (static export) on Vercel

## Architecture

A hybrid **retrieve-then-rerank** pipeline with lazy embedding. Cultural
retrieval knows what humans think is similar; audio embedding knows what
actually sounds similar; each covers the other's blind spot. The flow:

1. Cultural retrieval (Last.fm + ListenBrainz) generates a candidate pool (up to
   a couple hundred per seed).
2. Conservative dedupe, then MusicBrainz recording-level canonicalization.
3. Deezer preview fetch, match verification (ISRC / duration / string), then an
   ephemeral CLAP embedding computed in memory and discarded.
4. CLAP cosine scoring, plus optional mood-text scoring when a mood is given.
5. An LLM writes a rationale for the top results; it does not determine ranking.
6. Embeddings are cached in pgvector, so the corpus grows with real usage.

Two async gates absorb MusicBrainz's rate limit: Gate 1 defers a request with
too many uncached lookups, Gate 2 defers one with too many missing embeddings.
A deferred request returns a poll handle and finishes on a background worker.
When audio coverage is thin, results are backfilled from the cultural ranking
(Reciprocal Rank Fusion) so a partial signal still returns a full, labeled list.

Full detail, including the stage-by-stage map and the observability rationale,
is in [docs/architecture.md](docs/architecture.md).

## Milestones

### v1: the engine (complete)

Built over roughly a week and taken to production.

**Feasibility.** Before writing the engine, every outside piece it depends on
got a go/no-go check: the cultural sources (Last.fm, ListenBrainz, MusicBrainz),
Deezer previews, and the CLAP model. They held up (coverage held across pop,
R&B, hip-hop, indie, electronic, jazz, pre-2000, and non-English), so the build
got a green light. Deezer preview coverage was the single highest risk, and it
did not bite.

**Core engine.** The matcher and resolver (provider-informed canonicalization,
ISRC and duration and string verification, cover and remix rejection); the
candidate aggregator (concurrent sources, conservative dedupe that preserves
recording variants, RRF ranking, per-source isolation); the CLAP embedder and
scorer (in-memory PyAV decode, deterministic window pooling, within-batch
min-max fusion of audio and mood cosines); the Postgres + pgvector schema with a
checksum-guarded migration runner; and the orchestration layer, one
`run_pipeline` coroutine behind two async gates, a FastAPI `/recommend` with a
poll endpoint, an ARQ worker, and a degradable Claude explainer.

**Live and measured.** Deployed to a single Hetzner VPS: loopback-only API,
SSH-tunnel access, no public database or Redis ports, a daily `pg_dump` cron, an
encrypted off-site backup mirror, and failure alerts. A 19-seed benchmark then
put the engine to the test and calibrated its knobs:

- Coverage holds across every genre (19 of 19 seeds audio-scored, median resolve
  found-ratio 0.987), including non-English, pre-2000, R&B, and indie.
- CLAP reranking earns its keep: it reorders the cultural ranking more the more
  candidates it is given (top-10 overlap with pure cultural order 0.3 at 75
  candidates versus 0.6 at 20).
- Within-batch min-max fusion is validated: audio cosine scale is
  genre-dependent (about 0.5 for one electronic seed versus about 0.99 for jazz),
  so a fixed cross-genre threshold would be wrong.
- The CLAP text encoder is weak on cultural and emotional descriptors (mood-text
  cosines about 0.15 to 0.37, well below audio). Stronger mood steering is a
  retrieval problem, not a matter of raising the mood weight. Kept
  `RESOLVE_CANDIDATE_LIMIT` at 75 and the audio/mood weights at 0.7 / 0.3.

Two result-quality fixes followed the benchmark: deduping the final list on the
provider track id (not just the verified MBID), and suppressing a seed that
recommends a different master of itself (high audio cosine plus a title match).

Cold `/recommend` ran about 701 seconds and warm about 12 seconds in production,
which is why the two-gate async design exists.

### v1.1: the showcase site (complete)

A public-safe way to demonstrate the engine without exposing the live backend,
persisting audio, or doing request-time inference. A Next.js app on Vercel
serves frozen `RecommendationResponse` JSON, regenerated once per curated seed
by running the real pipeline. Static precompute designs the hard problems out of
existence rather than patching them: no cold-latency cliff, no request-time
preview embedding (and the legal question that comes with it), no auth, cost, or
denial-of-service surface. The site pairs an at-a-glance gallery and score
breakdown with a how-it-works depth layer, and every number is a serialization
of real persisted pipeline output.

### v2: deepen the engine (complete)

An algorithmic-quality milestone that repaired the one link the benchmark proved
weak: controllable mood steering. Measurement-first throughout.

First hypothesis: rewrite a natural-language mood into literal CLAP-trained
acoustic terms before encoding. An A/B harness measured it and disconfirmed it.
Translation lowered the mood-text cosine, and the real bottleneck turned out to
be the candidate pool, not the text vector. That path ships off by default.

The fix that worked is a second retrieval lane: when a mood is given, search the
whole embedding corpus by the mood vector (an HNSW nearest-neighbor query) to
surface on-mood tracks the seed's cultural pool cannot contain. It is enabled by
default at a mood weight of 0.3, where it cleanly improves descriptive moods with
no hub-track leakage. A stronger weight of 0.5 unlocks moderate cross-genre
steering but surfaces a corpus hub track, so it is gated on hub-track mitigation.

### v1.2: the engine replay console (complete)

The showcase landing page became an idle engine console. A visitor picks a
curated seed and watches a stage-by-stage animated replay of a real recorded
pipeline run, driven by per-stage telemetry captured from the real engine. The
replay is stamped and labeled as recorded (time compression is shown, for
example "cold run 11m41s, replayed at 40x"); it never implies the visitor
triggered a live run. Alongside it, a visually distinct live ops panel shows
genuinely real-time production signals through outbound push only: public
status badges for the backup and heartbeat checks, and a cron that pushes a
sanitized stats feed (corpus size, queries served, last backup, host vitals) to
a public-read bucket. No new inbound surface, no client-side tokens; the VPS
stays loopback and SSH-only. A standalone status page rounds it out.

### v1.3: signal-convergence redesign (complete)

A ground-up redesign of the showcase into an authored visual identity built on
one idea: the two retrieval legs (the crowd and the sound) braid into a single
fused result. New type, a warm-charcoal palette, and the seam motif where the
streams meet, recurring across every route. The seed gallery's tiles became
earned per-seed fingerprints derived from real scores. Honesty is load-bearing
site-wide: the pre-rendered and reduced-motion states show the complete truthful
final result, any time-scaling is labeled, and the fused output is revealed only
once the recorded results stage completes. Two follow-ons: a plain-language
rewrite of every user-facing string (with an accessibility, responsive, and
performance pass), and a changelog page telling the whole-project history along
the same convergence motif extended through time.

## Current state and what's next

The engine and the showcase are live at
[doppel.erickti.com](https://doppel.erickti.com). v1, v1.1, v1.2, v1.3, and v2
are complete. The next engine milestone is open. Candidates:

- **Hub-track mitigation**, which would unlock stronger mood steering (a mood
  weight of 0.5) by down-weighting the few corpus tracks that sit centrally near
  many mood vectors.
- **Corpus densification**: a background job that embeds tracks adjacent to
  existing corpus entries. The mood-retrieval lane leans on corpus diversity, so
  this is better motivated now than at v1.
- **LLM reranking as an A/B test (v3)**: a deliberate bet against the engine's
  "CLAP owns ranking" design rule, which would need a blind human-preference gate
  to justify.

## Non-Goals

- User accounts, auth, or multi-tenancy. The live backend is single-user and
  SSH-only. (The public showcase is a separate static site, not the backend.)
- SSE or WebSocket streaming.
- Spotify or Apple Music integration, or in-app audio playback.
- Fine-tuned audio models.
- LLM reranking in v1 (explanation only).
- Background corpus densification (deferred, a v2 follow-on candidate).
- Mood-dominant scoring for extreme cross-genre steering. The mood lane ships at
  the weight where it is cleanly positive; stronger steering is gated on
  hub-track mitigation.
- Additional preview providers beyond Deezer.
- A local MusicBrainz mirror.
- Explicit-content filtering.

## Resolved questions

- **Deezer resolution**: a track is found by search, then its ISRC is read from
  the documented `/track/{id}` endpoint to anchor the MusicBrainz match. The
  undocumented `/track/isrc:` lookup is deliberately not used. ISRC anchoring is
  on by default and can be turned off, falling back to duration and string
  matching.
- **Deezer terms permissibility**: ephemeral embedding from previews is
  consistent with Deezer's storage restrictions but is not explicitly addressed
  in the developer terms. It is validated as fine for a personal tool and would
  need review before any public live-embedding deployment (which is why the
  showcase serves frozen output instead).
- **ListenBrainz Labs stability**: the similar-recordings endpoint works but is
  experimental, so it stays behind a source adapter. It is keyed on
  ListenBrainz-canonical MBIDs, resolved via Labs recording-search first.
- **CLAP text encoder quality**: confirmed weak on cultural and emotional
  descriptors. The lever for stronger steering is better candidate retrieval (the
  mood lane), not a higher mood weight.
- **Candidate pool yield**: about 100 to 198 candidates per seed after dedupe.
  Below the 200-to-300 target for thin-data seeds (jazz standards, older
  non-English tracks) but sufficient, since the resolve cap is 75 regardless.
- **CLAP memory**: about 659 MB per process, roughly 1.3 GB when loaded in both
  the API and the worker, about 76 ms per clip warm on CPU. Fits a modest VPS.
- **Genre coverage**: re-measured at scale across R&B, pre-2000, and non-English
  seeds. Deezer coverage is not the weak link for known tracks.
