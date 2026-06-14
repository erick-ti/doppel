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

## v1.1 — Showcase Frontend (COMPLETE — frontend 2026-05-31; the deferred screencast superseded by v1.2's replay console, 2026-06-12)

A public-safe showcase frontend that demonstrates Doppel to any visitor — instant first-glance value + a
verifiable technical-depth layer — **WITHOUT** exposing the live backend, persisting audio, or doing
request-time inference. Deliberately crosses the v1 "Frontend/UI" Non-Goal as a conscious post-v1
scope decision. Full plan + design rationale in `V1.1_SHOWCASE_PLAN.md`; the wrap/scope decision is in
DECISIONS.md (2026-05-28).

**Architecture — Option A (static-precompute).** A Next.js app (in `web/`) on Vercel serves frozen
`RecommendationResponse` JSON, regenerated once per curated seed by running the REAL pipeline on the
VPS (`scripts/export_showcase.py`). A recorded deep-dive over the existing SSH tunnel was planned to
carry the "it actually runs" proof — superseded by the v1.2 replay console (2026-06-12), which takes
that role over. This sidesteps, by design (not by patching): the 701 s
cold-latency cliff, the "validate-before-public" live-embedding legal question, and the
no-auth/DoS/cost liability. The deferred poll-handle/auth/rate-limit/asyncpg hardening (the v1 list
above) is **narrated as scoped judgment, not built**.

Phases (each independently shippable; ~6.5–9.5 build-days total):
- ✓ **Phase 0 — Data export** (shipped — PR #16): `scripts/export_showcase.py` + the shared
  `doppel/api/responses.py` wire-builder (export is byte-identical to the live API) + a source-failure
  secret-redaction fix; 10 curated seed JSONs exported (from the warm local corpus) to `web/public/seeds/`.
- ✓ **Phase 1 — "Minimum impressive"** (shipped — PR #17; **live on Vercel** at
  https://doppel.erickti.com): Next.js 16 static-export app (App Router + TS + Tailwind v4 +
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
- ✓ **Phase 4 — Recorded deep-dive — PAGE shipped; video superseded by v1.2 (recording optional)** (PR #23): `/deep-dive` route + a
  written act-by-act walkthrough + a placeholder video slot. The **screencast itself is recorded LAST**
  (operator-only, against the final system) and swapped in via a one-line `DEEP_DIVE_VIDEO` change —
  DECISIONS.md 2026-05-31. **Superseded 2026-06-12**: the v1.2 replay console takes over the
  "it actually runs" proof (DECISIONS.md 2026-06-12 v1.2); the written walkthrough stays, a recording
  is optional, and v1.1 closes.

Curated roster: 8 genre heroes + 2 vibe-steer variants (HUMBLE.-acoustic the hero) — plan §3.

Done = curated showcase live on Vercel; `/how-it-works` + `/deep-dive` shipped; the VPS remains
SSH-only and internet-private.

## v2 — Deepen the Engine (COMPLETE — 2026-05-31 → 2026-06-12)

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

**Provenance gate + enable (landed)**: full source-aware provenance shipped first — a frontend "hnsw"
source chip, explainer-prompt awareness, eval-ablation labels (DECISIONS.md 2026-05-31) — then a 2×2
eval A/B (lane × β over the vibe seeds, 2026-06-12) measured the flip. At the production β=0.3 the lane
cleanly improves descriptive vibes (new on-vibe #1 for the M83 seed) with zero hub-track leakage, so
`HNSW_LANE_ENABLED` now **defaults ON**. β=0.5 steering (which also unlocks moderate-steer seeds like
Take Five) is a follow-on, gated on hub-track mitigation — the A/B reproduced the known corpus hub
surfacing at β=0.5. Remaining tuning: `HNSW_LANE_K`, pgvector `ef_search`. **Production rollout complete
(2026-06-12)**: the VPS redeployed to the enabled build, its corpus warmed 147→934 embeddings via an
API-driven pass over the 16 benchmark seeds, and the lane verified live (an `hnsw`-tagged result on a
real vibe request).

Deferred past v2: **LLM-reranking A/B → v3** (bets against the validated "CLAP owns ranking" rule; needs a
blind human-preference gate). **Corpus densification** (better-motivated now — the lane leans on corpus
diversity — though the accidental-accretion corpus already demonstrates the mechanism).

## v1.2 — Engine Replay Console (build phases COMPLETE — 2026-06-12 → 2026-06-13; operator-wiring + optional Phase 4 remain)

The showcase's landing page becomes an idle "engine console": a visitor picks a curated seed and watches
a **stage-by-stage animated replay of a real recorded pipeline run** — aggregate → gate 1 → resolve →
gate 2 → embed → hnsw lane → score → backfill → explain → results — driven by per-stage telemetry captured from
the real pipeline, stamped (`git_sha`, capture date) and explicitly labeled a **recorded replay** (time
compression shown, e.g. "cold run 11m41s, replayed at 40×"; the page never implies a live run was
triggered). Alongside it, a visually distinct **live ops panel** shows genuinely real-time production
signals via outbound push only — healthchecks.io public status badges (backup + heartbeat checks) and a
VPS cron pushing a sanitized `stats.json` (corpus size, queries served, last backup) to a public-read
Cloudflare R2 bucket — no new inbound surface, no client-side tokens; the VPS stays loopback + SSH-only.
Still Option A (static-precompute): replay data ships as **sidecar trace files** per seed
(`web/public/seeds/<slug>.trace.json`) captured by an export-only `trace_recorder` seam; the 10 frozen
seed docs are not regenerated (one new cold-run capture *adds* a seed). Supersedes the v1.1 deep-dive
screencast (decision + full rationale: DECISIONS.md 2026-06-12 v1.2).

Phases (each independently shippable):
- ✓ **Phase 1 — Trace capture + sidecars** (shipped — PR #28): `trace_recorder` on `PipelineDeps` (default
  `None`; production paths untouched), exporter integration + `--trace-only`, reconciliation gate +
  `paired_export`, 11 sidecars incl. one real Jolene cold-run capture, the `RunTrace` TS type.
- ✓ **Phase 2 — Replay console** (shipped — PR #29): idle-console landing + curated seed picker (the
  disabled seed-box inverted), `/run/[slug]` RAF replay-player (play/pause/scrub/speed, dual-stamp banner,
  hydration/idle=final + reduced-motion path), results cascade reusing the existing card components.
- ✓ **Phase 3 — Live ops panel** (shipped — PR #30): `scripts/push_stats.sh` (VPS cron → sanitized
  stats.json → public R2) + `web/lib/ops.ts` + `ops-panel`, fail-soft with honest degradation; hardened
  across 10 Codex rounds. **Operator-wiring remains** (DEPLOY.md §9.3): public R2 bucket + cron + Vercel
  `NEXT_PUBLIC_*` — until then the panel renders "feed not configured."
- **Phase 4 — Optional polish** (not started): host vitals, a `/status` route, the custom-domain question.

Done (build) = console-first landing on Vercel with a stage-by-stage replay for every curated seed + the
LIVE ops panel rendering honestly; the VPS remains SSH-only and internet-private. Live ops data is gated on
the §9.3 operator steps.

## Upcoming Milestones

**v2 — Deepen the Engine is COMPLETE (2026-05-31 → 2026-06-12)**: the HNSW vibe-retrieval lane shipped
end-to-end — built flag-off, provenance-gated, 2×2 A/B-measured, enabled by default (β=0.3), and live in
production. Its gated leftovers are **post-v2 follow-ons**, not open milestone work: hub-track mitigation
→ β=0.5 steering (DECISIONS.md 2026-06-12), and `HNSW_LANE_K` / `ef_search` tuning.

**v1.2 — Engine Replay Console: build phases COMPLETE (2026-06-13)** — Phases 1–3 shipped + merged to
`main` (PRs #28/#29/#30), which also closed v1.1 by superseding its deferred screencast. Remaining v1.2
items are **not open milestone work**: operator-only live-panel wiring (DEPLOY.md §9.3) and optional
Phase 4 polish. **The next milestone is not yet chosen** — candidates: Phase 4, hub-track mitigation →
β=0.5 (gated v2 follow-on), or corpus densification. Past v2: **LLM-reranking A/B** is **v3** and
**corpus densification** stays deferred — see DECISIONS.md 2026-05-31 / 2026-06-12 and BRAINDUMP.md
"Future Improvements (Deferred)".

## Non-Goals

- Frontend or UI (API-first, validate with curl)
- SSE/WebSocket streaming
- User accounts, auth, multi-tenancy
- Spotify/Apple Music integration or in-app audio playback
- Fine-tuned audio models
- LLM reranking (explanation only in v1)
- Background corpus densification
- Vibe-first scoring for extreme cross-genre steering (β≥0.5 / a vibe-dominant mode) — the HNSW lane ships at β=0.3 where it is cleanly positive; stronger steering is gated on hub-track mitigation (DECISIONS.md 2026-06-12)
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
- **Deep-dive screencast** — **RESOLVED (2026-06-12, superseded)**: the v1.2 replay console takes over the "it actually runs" proof (interactive, honestly time-compressed, not operator-gated — DECISIONS.md 2026-06-12 v1.2). The written walkthrough stays on `/deep-dive`; a recording is optional and the `DEEP_DIVE_VIDEO` one-line swap remains available if one is ever made.
- **Custom domain** — **RESOLVED (2026-06-14)**: live at the custom domain `doppel.erickti.com` (subdomain of `erickti.com`), replacing the free `doppel-music.vercel.app`.
