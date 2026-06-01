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

## Final Milestone — v1 COMPLETE (wrapped 2026-05-28)

**v1 is formally complete and wrapped (2026-05-28).** Day 7 below was the last planned v1 milestone —
all ✓ items shipped; the unchecked items are deferred-beyond-v1 and condition-gated (none a blocker).
The active milestone is now **v1.1 — Showcase Frontend** (below).

**Day 7 — VPS deploy + first eval round shipped** (PR #8 → `4277951`, live on a Hetzner CX33 — cold
`/recommend` 701 s / warm 12 s validated in prod, 2026-05-27; the `eval/` harness drove a pilot + 19-seed
full benchmark and calibrated the knobs — calibration bullet below). The ✓ items below are those two
deliverables; the **unchecked items are deferred beyond v1, not blockers** — poll-handles/API auth gated
on public/multi-user exposure (a Non-Goal; v1 is single-user SSH-only), connection-scoping on real
concurrency, and the seed-equivalence self-rec an **accepted non-blocking v1 quality risk** (re-release-
heavy seeds only), its fix queued as a follow-up. Deploy-hardening items carried from the Day-6
adversarial reviews (rationale in DECISIONS.md):
- ✓ Built + ran the app/worker Docker image end-to-end (PR #7), then **shrunk 10.6 GB → ~2.2 GB via a CPU-torch wheel pin** (PR #8).
- ✓ Cold-run resolve cap + tuning hardening (PR #7): top-N resolve cap (`RESOLVE_CANDIDATE_LIMIT`), `GATE1`=5 ≤ `GATE2`, `WORKER_MAX_JOBS`=1, `_validate_tuning`, verified-MBID result dedup — bounds cold latency against MusicBrainz's ~1 req/s (a 194-candidate seed had overrun the timeout at 85 resolved).
- ✓ Production deploy (PR #8): prod compose overlay (loopback API, no public DB/Redis ports, Redis AOF, discrete DB password), base dev ports bound to `127.0.0.1`, a `pg_dump` backup script + daily cron, and the live Hetzner deploy (key-only SSH, Hetzner FW SSH-only, fail2ban, swap) — see `DEPLOY.md`.
- ✓ Off-box backup mirror via rclone — `scripts/backup_db.sh` now mirrors each successful local dump to an rclone remote when `BACKUP_REMOTE` is set (default-off, backwards-compatible; pre-flight validates retention + rclone-installed before dumping), and prunes off-box copies older than `OFFSITE_KEEP_DAYS` (default 30d, vs `KEEP`=7 local — off-box durability outlives local rotation). Client-side encryption via rclone `crypt` so the provider sees only ciphertext; failure semantics keep the local dump on copy failure. DEPLOY.md §9.1 walks through Cloudflare R2 (free egress, ~$0.015/GB/mo) as the worked example. Closes the Day-7 deferred deploy-hardening item.
- Non-enumerable `/recommend` poll handles (random `public_id` token resolved to the row id) + API auth before any public/multi-user exposure.
- ✓ Stale-row reaper (running rows) — done (PR #8): a worker startup + 5-min-cron pass fails `running` rows stuck past `STALE_JOB_RECLAIM_S` (> `JOB_TIMEOUT_S`), freeing the in-flight dedup; Redis AOF (prod overlay) keeps `queued` jobs durable across restarts. **Deferred residual**: reconcile `queued` rows against ARQ job existence (covers a job lost *after* enqueue — the AOF-fsync window on a hard crash, or volume loss); a narrow single-user-v1 edge.
- Scope asyncpg connections to short reads/writes (release during the MB-paced resolve loop) once real concurrency warrants it.
- ✓ Healthcheck-style notifier for `backup_db.sh` failures — `scripts/backup_db.sh` now pings a healthchecks.io-style URL on start (`<URL>/start`), success (bare URL after the off-box block), and explicit fail (`<URL>/fail` via an EXIT trap) when `BACKUP_HEALTHCHECK_URL` is set (default-off, backwards-compatible). Passive dead-man's switch model — the service alerts on both code-level failures (the script pinged `/fail`) and total no-shows (cron didn't fire / box is off / nothing pinged), via the configured grace timer. Notifier-outage curl failures are non-fatal (a notifier blip must never fail an otherwise-good backup) and the URL is the credential, so it never lands in logs. DEPLOY.md §9.2 walks through healthchecks.io setup.
- ✓ **Calibrated the provisional knobs** on real score distributions (Day-7 eval harness `eval/`; pilot + 19-seed full benchmark — rationale in DECISIONS.md): coverage holds across all genres (19/19 seed audio-scored, median found-ratio 0.987, incl. non-English/pre-2000/R&B/indie — the #1 risk doesn't bite); CLAP reranking earns its keep (top-10∩cultural 0.3 at N=75 vs 0.6 at N=20 — reranks harder with more reach); within-batch min-max fusion validated (audio-cosine scale is genre-dependent, ~0.5 deadmau5 vs ~0.99 jazz, and vibe-text cosines ~0.15–0.37 sit far below audio). **Keep `RESOLVE_CANDIDATE_LIMIT`=75 and α/β=0.7/0.3**; stronger vibe steering is the deferred LLM-vibe-translation, not a higher β (the CLAP text encoder is weak on cultural descriptors). `CLAP_EMBED_POOLING` mean-vs-center + an α/β grid were **not swept** and shouldn't be folded into the harness — pooling is in the embeddings cache key (a full re-embed under a new `model_version`, not a flag) and α/β is offline-analyzable from the persisted raw cosines; run either as a deliberate env re-run / offline query if ever needed.
- ✓ Dedup the final results on `provider_track_id` too, not just the verified MBID — the first prod run (2026-05-27, `Take Five`) surfaced one Deezer track twice under two MBIDs ("Three to Get Ready" ×2, both `/track/69122368`), which the MBID-only dedup can't catch. `_build_results` now tracks each placed provider-track-id across both the audio-scored and backfill phases, and seeds the set with the seed's own track so the seed can't return under a different MBID + the same track (a `None` ptid is never a collision; adversarial review caught the seed-equivalent case).
  - Known limitation (for the eval round): this seed-alias drop + the `seed_mbid` drop are effective on the **audio path only**. If the seed resolves but its preview fails to embed (cultural-only), `run_pipeline` skips candidate resolution, so backfill rows carry no ptid/mbid to match and a same-track seed alias can still surface — a pre-existing gap (shared with `seed_mbid`); closing it would mean resolving candidates on the deliberately-cheap degraded path.
- ✓ Seed-equivalence (title/audio) suppression — the Day-7 eval reproduced a seed recommending a *different master of itself* at #1 (Take Five → "Take Five — Dave Brubeck", audio cosine 0.988, but a distinct MBID + Deezer track, so the identity dedup above can't catch it). `_build_results` now drops an audio-scored result whose raw audio cosine ≥ `SEED_EQUIVALENCE_AUDIO_MIN` (0.98) **and** whose title token_set-matches the seed's (≥ `SEED_EQUIVALENCE_TITLE_MIN`, 0.90), recording its keys so backfill can't re-add it. A live/acoustic *version* scores lower audio and survives (the AND-gate is regression-tested). Audio-path only — the cultural-only case (no audio score to test against) stays the documented limitation above.

_Day 0 (external dependency validation) — **complete, verdict GO** (2026-05-21). Day 1-2 (matcher/resolver) — **complete, merged 2026-05-21** (PR #2): match verification, provider-informed canonicalization, and cover/ISRC/artist-MBID hardening. Day 3 (candidate aggregator) — **complete, merged 2026-05-22** (PR #3): Last.fm + ListenBrainz sources, conservative dedupe, RRF (k=60), Gate-1, per-source isolation/observability. Day 4 (CLAP embedder + similarity scoring) — **complete, merged 2026-05-23** (PR #4): in-memory PyAV decode, deterministic duration-weighted window pooling, audio (+ optional vibe-text) cosine with within-batch min-max + α/β fusion, and hardened preview/text input guards. Day 5 (full database schema + asyncpg access layer) — **complete 2026-05-23** (PR #5): Postgres 16 + pgvector (`tracks`/`audio_assets`/`canonical_lookups`/`embeddings`/`query_logs`), a checksum-guarded raw-SQL migration runner, and the cache/corpus access layer. Day 6 (LLM explainer + FastAPI `/recommend`) — **complete, merged 2026-05-24** (PR #6 → `7ac120b`): the shared inline/worker `run_pipeline` (two async gates, cache-first resolve, ephemeral embed, scoring + cultural backfill), a degradable Claude explainer, the ARQ worker, FastAPI `/recommend` + poll, migration 0002 (telemetry + result snapshot), hardened across three adversarial-review rounds. See SESSION_NOTES.md / DECISIONS.md._

## v1.1 — Showcase Frontend (frontend feature-complete 2026-05-31; only the deep-dive recording remains)

A public-safe showcase frontend that demonstrates Doppel to any visitor — instant first-glance value + a
verifiable technical-depth layer — **WITHOUT** exposing the live backend, persisting audio, or doing
request-time inference. Deliberately crosses the v1 "Frontend/UI" Non-Goal as a conscious post-v1
scope decision. Full plan + design rationale in `V1.1_SHOWCASE_PLAN.md`; the wrap/scope decision is in
DECISIONS.md (2026-05-28).

**Architecture — Option A (static-precompute).** A Next.js app (in `web/`) on Vercel serves frozen
`RecommendationResponse` JSON, regenerated once per curated seed by running the REAL pipeline on the
VPS (`scripts/export_showcase.py`). A recorded deep-dive drives the live engine over the existing SSH
tunnel for the "it actually runs" proof. This sidesteps, by design (not by patching): the 701 s
cold-latency cliff, the "validate-before-public" live-embedding legal question, and the
no-auth/DoS/cost liability. The deferred poll-handle/auth/rate-limit/asyncpg hardening (the v1 list
above) is **narrated as scoped judgment, not built**.

Phases (each independently shippable; ~6.5–9.5 build-days total):
- ✓ **Phase 0 — Data export** (shipped — PR #16): `scripts/export_showcase.py` + the shared
  `doppel/api/responses.py` wire-builder (export is byte-identical to the live API) + a source-failure
  secret-redaction fix; 10 curated seed JSONs exported (from the warm local corpus) to `web/public/seeds/`.
- ✓ **Phase 1 — "Minimum impressive"** (shipped — PR #17; **live on Vercel** at
  https://doppel-music.vercel.app): Next.js 16 static-export app (App Router + TS + Tailwind v4 +
  hand-authored shadcn-style ui), seed gallery + result cards with the correct four-axis score breakdown
  + transparency panel. Analytics + README showcase note in PR #18.
- ✓ **Phase 2 — "Wow" polish** (shipped — PRs #19/#20/#21): vibe-steer toggle (plain↔vibe FLIP) +
  real-telemetry funnel animation (count-up + proportional narrowing, `idle=final` SSR-safe) + expanded
  hero arc (problem→dead-ends→wedge→evidence) + disabled free-text seed box + System-Transparency panel +
  a full responsive/mobile pass.
- ✓ **Phase 3 — Technical-depth layer** (shipped — PR #22): `/how-it-works` (architecture-evolution
  narrative, competitive wedge + honest "where it doesn't win", eval-evidence panels + N=75 ablation, CSS
  pipeline DAG, all DIAGNOSTIC-labelled) + per-result raw-JSON disclosures. Eval figures frozen in
  `web/lib/eval-evidence.ts`. (Also folded in the Codex-caught funnel "CLAP-scored N of M found" honesty fix.)
- ✓ **Phase 4 — Recorded deep-dive — PAGE shipped, video pending** (PR #23): `/deep-dive` route + a
  written act-by-act walkthrough + a placeholder video slot. The **screencast itself is recorded LAST**
  (operator-only, against the final system) and swapped in via a one-line `DEEP_DIVE_VIDEO` change —
  DECISIONS.md 2026-05-31. This is the only remaining v1.1 work, and it's non-code.

Curated roster: 8 genre heroes + 2 vibe-steer variants (HUMBLE.-acoustic the hero) — plan §3.

Done = curated showcase live on Vercel; `/how-it-works` + `/deep-dive` shipped; the VPS remains
SSH-only and internet-private.

## v2 — Deepen the Engine (CURRENT — started 2026-05-31)

An algorithmic-quality milestone repairing the one pipeline link the Day-7 eval proved broken —
controllable vibe steering (CLAP's text encoder scores cultural descriptors at ~0.15–0.37, semantically
inconsistent). Measurement-first throughout: hypothesize → build flag-off → measure → decide. Full arc +
rationale: DECISIONS.md 2026-05-31.

**Hypothesis (DISCONFIRMED) — LLM vibe→acoustic-terms translation** (merged flag-off, PR #24). The bet was
that rewriting a vibe into literal CLAP-trained acoustic terms *before* text-encoding would clear the
weak-encoder wall. A label-free A/B + β-sensitivity harness (`eval/vibe_ab.py`) measured it live and
disconfirmed it: translation *lowers* the CLAP text cosine (0/3 vibe seeds pass the gate), and at β=0.3
the vibe leg barely moves output regardless — the bottleneck is the candidate *pool*, not the text vector.
The `ClaudeVibeTranslator` ships dormant (`VIBE_TRANSLATION_ENABLED=False`); the work also coupled the
fusion weights (β is the env knob, α=1−β ⇒ `combined_score ∈ [0,1]`).

**Flagship — HNSW vibe-retrieval lane** (built flag-off, `HNSW_LANE_ENABLED`). The disconfirmation pointed
at the pool: steer-away vibes fail because the seed's cultural neighbours can't contain the steer
direction. A bounded feasibility spike (`eval/hnsw_spike.py`) + a hybrid measurement
(`eval/hnsw_hybrid.py`) confirmed global `knn(vibe)` surfaces plausible on-vibe tracks the cultural pool
lacks, and that they survive the rerank at β≈0.5 (Blinding Lights → 8/10 acoustic ballads, end-to-end).
After three Codex rounds the lane was **redesigned** into a clean MBID-keyed scoring input inside
`run_pipeline` (`_hnsw_lane`): corpus tracks are MBID-native and now treated as such, never round-tripped
through the title-keyed pool. Validated; 293 offline + the db-gated suite in CI.

**Before enabling the lane** (the remaining v2 work): full source-aware provenance so HNSW results are
honest about themselves — a frontend "hnsw" source chip, explainer-prompt awareness, eval-ablation labels
(DECISIONS.md 2026-05-31). Optional tuning: `HNSW_LANE_K`, pgvector `ef_search`, the β interaction. The
lane is correct + complete as a flag-off experiment; turning it on is gated on the provenance work.

Deferred past v2: **LLM-reranking A/B → v3** (bets against the validated "CLAP owns ranking" rule; needs a
blind human-preference gate). **Corpus densification** (better-motivated now — the lane leans on corpus
diversity — though the accidental-accretion corpus already demonstrates the mechanism).

## Upcoming Milestones

**v2 — Deepen the Engine** (above) is the current milestone (started 2026-05-31); v1.1's frontend is
feature-complete, with only the operator-recorded deep-dive screencast deferred. Past v2: the **HNSW
retrieval lane** is a gated **v2.1**, **LLM-reranking A/B** is **v3**, and **corpus densification** stays
deferred — see DECISIONS.md 2026-05-31 and BRAINDUMP.md "Future Improvements (Deferred)".

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
- **CLAP text encoder quality** — **RESOLVED (Day-7 eval)**: confirmed weak on cultural/emotional descriptors — vibe-text cosines measured ~0.15–0.37 (vs audio ~0.8), low and semantically inconsistent ("contemplative"→a ballad, aptly; "acoustic"→non-acoustic). The LLM-vibe-to-acoustic-terms pre-processing step is the lever for stronger steering — deferred (BRAINDUMP "Future Improvements"), not a higher β.
- **Candidate pool yield** — **RESOLVED (Day-7 eval)**: the full 19-seed benchmark measured per-seed yields ~100–198 after dedupe (jazz standards / Piaf ~100; mainstream pop/electronic ~180–198); the min-max-fused rerank works across that range. Below the 200-300 target for thin-data seeds, but sufficient — the top-N resolve cap is 75 regardless.
- **CLAP dual-load memory** — **RESOLVED (Day 0)**: ~659 MB process RSS per load (~1.3 GB dual-load across FastAPI + ARQ worker), 76 ms/clip warm on CPU, 512-dim. Fits a modest VPS.
- **Coverage matrix representativeness** — **RESOLVED (Day-7 eval)**: re-measured across R&B (Pink + White, Cranes in the Sky), pre-2000 (Bohemian Rhapsody, Dreams), and non-English (Despacito, La Vie en rose) in the 19-seed benchmark — 19/19 seed audio-scored, median resolve found-ratio 0.987. The Day-0 small-sample 100% claim holds at scale; Deezer coverage is not the weak link.
- **Deep-dive screencast** — **OPEN (v1.1)**: record the 6–8 min SSH-tunnel cold→warm walkthrough (script in `web/lib/deep-dive.ts` `ACTS` / plan §6), or is the written walkthrough already on `/deep-dive` enough? Leaning: record last as the project's final step, then swap it in via the one-line `DEEP_DIVE_VIDEO` change (DECISIONS.md 2026-05-31). Operator-only work.
- **Custom domain** — **OPEN (v1.1)**: keep the free `doppel-music.vercel.app`, or register a custom domain? (`.music` explored, not bought.)
