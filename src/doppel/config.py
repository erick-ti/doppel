"""Runtime configuration — module constants, env-overridable where it matters.

Deliberately framework-free (no pydantic): the matcher needs a handful of base
URLs, a mandatory MusicBrainz User-Agent, pacing, and a couple of toggles. Richer
settings can graduate to a typed Settings object when the API/worker need them.

Secrets (e.g. ``LASTFM_API_KEY``) come from the environment. For local dev a
gitignored ``.env`` at the repo root is loaded below (template: ``.env.example``);
real environment variables take precedence, so CI and production inject them
directly rather than shipping a ``.env``.
"""
from __future__ import annotations

import os

from dotenv import find_dotenv, load_dotenv

# Load a local .env (gitignored) before reading any config below. Search from the CWD
# upward so it's found regardless of where the installed package lives; values already
# in the real environment are NOT overridden (CI / prod / an explicit `export` win).
load_dotenv(find_dotenv(usecwd=True))


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


# --- HTTP -------------------------------------------------------------------- #

# MusicBrainz requires a descriptive User-Agent with contact info (a repo URL is
# fine); without it, or over the rate limit, the IP gets temporarily blocked.
USER_AGENT = "Doppel/0.1.0 ( https://github.com/erick-ti/doppel )"
HTTP_TIMEOUT_S = 30.0

# --- MusicBrainz ------------------------------------------------------------- #

MUSICBRAINZ_API = "https://musicbrainz.org/ws/2"
# Hard limit is ~1 req/sec; pace at one request per this interval (margin included).
MUSICBRAINZ_MIN_INTERVAL_S = 1.1
# How many recordings to pull for the title/artist cluster when picking the
# nearest-duration recording — must be wide enough to contain the right version
# (limit=3 routinely missed it; 25 covers the validated seeds comfortably).
MUSICBRAINZ_CLUSTER_LIMIT = 25

# --- Deezer ------------------------------------------------------------------ #

DEEZER_API = "https://api.deezer.com"
# When true, fetch each Deezer track's ISRC (via /track/{id}) and use it to
# ISRC-anchor MusicBrainz canonicalization + the verify_match short-circuit. When
# false, skip the ISRC entirely and rely on nearest-duration + weighted scoring.
# (We resolve the ISRC from the documented /track/{id}, not the undocumented
# /track/isrc: endpoint.)
DEEZER_ISRC_ENABLED = _env_bool("DEEZER_ISRC_ENABLED", True)

# --- Matching ---------------------------------------------------------------- #

# RapidFuzz token_set_ratio (0-100) a provider hit must clear against the *query*
# strings to be considered the right song before canonicalization/verification.
# Guards the ISRC short-circuit from anchoring onto a wrong-song Deezer result.
# Also gates ListenBrainz recording-search when resolving a seed's canonical MBID.
SEARCH_RELEVANCE_MIN = 80

# --- ListenBrainz (candidate source) ----------------------------------------- #

LISTENBRAINZ_LABS = "https://labs.api.listenbrainz.org"
# similar-recordings is keyed on ListenBrainz-canonical recording MBIDs; the seed is
# resolved to one via the Labs recording-search dataset first (MusicBrainz MBIDs
# return []). This session-based algorithm favors broad recall.
LISTENBRAINZ_ALGORITHM = (
    "session_based_days_9000_session_300_contribution_5_threshold_15_limit_50_skip_30"
)
# Polite spacing between the two Labs calls (recording-search → similar-recordings).
LISTENBRAINZ_POLITE_DELAY_S = 0.34
# Cap on similar recordings taken per seed (the endpoint returns ~100).
LISTENBRAINZ_SIMILAR_LIMIT = 100

# --- Last.fm (candidate source) ---------------------------------------------- #

LASTFM_API = "https://ws.audioscrobbler.com/2.0/"
# Read-only methods (track.getSimilar) need only an API key — no request signing.
# Absent → the Last.fm source yields nothing and the aggregator runs on its other
# sources (graceful degradation). Key: https://www.last.fm/api/account/create
LASTFM_API_KEY = os.getenv("LASTFM_API_KEY")
# Similar tracks requested per seed (plenty for cultural recall).
LASTFM_SIMILAR_LIMIT = 100

# --- Aggregation ------------------------------------------------------------- #

# Reciprocal Rank Fusion constant. k=60 is the standard value (Cormack et al.); it
# damps how much the very top ranks dominate, so cross-source agreement (a track
# ranked by *both* sources) outweighs a single source's #1.
RRF_K = 60

# Gate 1: at or above this many *uncached* candidate lookups (the ones that will actually hit
# MusicBrainz at ~1 req/s, ~7 s each — Day-7 measurement), resolve on the async/COLD path instead of
# inline in the request. Sized to a ~35 s inline budget (5 × ~7 s) and kept <= GATE2_ASYNC_THRESHOLD
# (enforced by _validate_tuning below) so a request that *would* defer at Gate 2 defers up front,
# instead of burning the resolve inline and then deferring anyway (the old 15 > 10 dead band). Provisional; calibrate in Day-7 eval. See ROADMAP "two-gate async model".
GATE1_ASYNC_THRESHOLD = int(os.getenv("GATE1_ASYNC_THRESHOLD", "5"))

# Per-source wall-clock budget for the aggregator's fan-out. Past this, a slow/hung
# source is recorded as degraded (failed_sources) so its latency can't hold the warm
# path hostage while other sources' candidates are already in. Generous vs. normal
# latency (~1-2s); well under the cumulative per-request HTTP timeout.
SOURCE_TIMEOUT_S = 15.0

# --- CLAP embedding + scoring ------------------------------------------------ #

# LAION-CLAP music+speech checkpoint: 512-dim embeddings at 48 kHz. Validated Day 0
# (~659 MB process RSS per load, 76 ms/clip warm on CPU). Audio and text share one
# embedding space, so a natural-language vibe description can be scored directly
# against candidate audio. The heavy deps (torch/transformers/av) live in the `clap`
# group and are imported lazily by the embedder — config stays import-cheap.
CLAP_MODEL_ID = "laion/larger_clap_music_and_speech"
CLAP_EMBED_DIM = 512
CLAP_SAMPLE_RATE = 48_000
# Torch device for inference. cpu is the VPS target (and Day 0's benchmark); override
# to "mps"/"cuda" for a local GPU. Read once here so the embedder needn't touch env.
CLAP_DEVICE = os.getenv("CLAP_DEVICE", "cpu")

# CLAP's audio encoder takes a fixed ~10s window (the checkpoint's max_length_s); beyond
# it the feature extractor *randomly crops* (truncation="rand_trunc"), which is fatal for
# a cached, reused corpus — the same track would embed differently every run, poisoning
# both the stored vector and the seed-vs-candidate cosine. So a clip longer than one
# window is reduced deterministically (see CLAP_EMBED_POOLING). 10 s @ 48 kHz = 480 000.
CLAP_WINDOW_SECONDS = 10
CLAP_WINDOW_SAMPLES = CLAP_SAMPLE_RATE * CLAP_WINDOW_SECONDS
# How to collapse a multi-window clip (a ~30s Deezer preview is ~3 windows) to one vector:
#   "mean"   — embed every non-overlapping window and average + renormalize (uses the
#              whole preview; best signal for *vibe*; the default). ~3× embed cost.
#   "center" — embed only the middle window (single pass, faster, lossy).
# Both are deterministic. Provisional default; revisit with Day 7 evaluation.
CLAP_EMBED_POOLING = os.getenv("CLAP_EMBED_POOLING", "mean")

# Per-asset ingestion caps so one oversized or pathological preview can't OOM the embedding
# worker (the Day-6 seam fetches hundreds per query). Deezer previews are ~0.5 MB / 30 s, so
# these are generous headroom, not tight limits; exceeding either raises EmbeddingError → the
# asset is skipped + backfilled (the project's "one bad external input never sinks the run").
# Provider-agnostic resource safety; cross-asset concurrency budgeting is Day-6 orchestration.
MAX_PREVIEW_BYTES = 10 * 1024 * 1024  # 10 MiB download cap (~20× a normal preview)
MAX_PREVIEW_DURATION_S = 60  # decode cap (~2× a 30 s preview); bounds a decompression bomb
MAX_PREVIEW_SAMPLES = CLAP_SAMPLE_RATE * MAX_PREVIEW_DURATION_S

# Host suffixes the embedder is allowed to fetch a preview from. The preview URL is
# Deezer-API-derived (not user input), but a provider response is still external data — and
# from Day 5 the URL is persisted and re-fetched — so the outbound fetch is restricted to
# https on one of these hosts, with redirects disabled, so the host contacted always equals
# the validated one. Deezer serves previews from cdnt-preview.dzcdn.net (confirmed live);
# deezer.com is kept for search-shaped hosts. Full DNS/private-IP pinning is deferred to the
# deployment-hardening pass, low marginal value once these + no-redirects
# are in, and correct only with connection pinning to avoid DNS-rebinding.
ALLOWED_PREVIEW_HOST_SUFFIXES = ("dzcdn.net", "deezer.com")

# Audio/text fusion weights:
#   combined = α·norm(audio_cos) + β·norm(vibe_text_cos)
# with each similarity min-max normalized *within the candidate batch* first. Audio
# is the precision leg; CLAP's text encoder is the weaker one on cultural/emotional
# descriptors (a known CLAP weakness), so the default leans audio-dominant. Provisional,
# to be calibrated against real score distributions in Day 7 eval. With no vibe
# description, scoring falls back to audio alone (β drops out) regardless of these.
# β (the vibe-text leg) is the single tunable knob; α (audio leg) is DERIVED as 1−β so the pair stays
# convex (α+β=1) and combined_score is provably in [0, 1]. scoring.py min-max-normalizes each leg to
# [0, 1], so the fused top reaches α+β — an independent α+β>1 would emit combined_score>1 and break the
# [0, 1] contract the API/showcase render (validate the sum α+β, not each weight in isolation). The
# live β-sweep showed β=0.3 leaves the vibe
# leg nearly inert and β≈0.5 makes steering visible, so β stays env-tunable; default 0.3 ⇒ α=0.7, the
# eval-validated pair, unchanged. (score_candidates still accepts explicit α/β for offline sweeps.)
VIBE_TEXT_WEIGHT = float(os.getenv("VIBE_TEXT_WEIGHT", "0.3"))  # β
if not 0.0 <= VIBE_TEXT_WEIGHT <= 1.0:
    raise ValueError(
        f"VIBE_TEXT_WEIGHT={VIBE_TEXT_WEIGHT} must be in [0, 1] — it is the vibe-leg fusion weight; "
        "α is derived as 1−β."
    )
AUDIO_SIM_WEIGHT = 1.0 - VIBE_TEXT_WEIGHT  # α, derived ⇒ α+β=1 (convex ⇒ combined_score ∈ [0, 1])

# Seed-equivalence suppression (Day-7 eval follow-up): drop a result that is the *seed itself* under a
# different master — a near-identical audio match (raw cosine ≥ SEED_EQUIVALENCE_AUDIO_MIN) whose title
# closely matches the seed's (token_set_ratio ≥ SEED_EQUIVALENCE_TITLE_MIN, both in [0,1]). Identity
# dedup (mbid/ptid) misses these: a re-release carries a distinct MBID + Deezer track (live Day-7: Take
# Five → "Take Five — Dave Brubeck" at 0.988). The audio floor sits above genuine matches (~0.95 in the
# eval), so a live/acoustic *version* — same title family but lower audio similarity — is preserved;
# only a near-identical master is dropped. Env-overridable for eval calibration.
SEED_EQUIVALENCE_AUDIO_MIN = float(os.getenv("SEED_EQUIVALENCE_AUDIO_MIN", "0.98"))
SEED_EQUIVALENCE_TITLE_MIN = float(os.getenv("SEED_EQUIVALENCE_TITLE_MIN", "0.90"))

# The vibe description is user-supplied (the /recommend text leg). CLAP's RoBERTa text
# encoder hard-caps at this many tokens and *raises* (position-embedding overflow) on longer
# input — the tokenizer does not truncate by default — so embed_text token-truncates to it
# and a verbose description degrades instead of crashing the request.
CLAP_TEXT_MAX_TOKENS = 512
# Cheap pre-tokenization char cap, applied before the model loads, so a pathologically large
# vibe string can't burn CPU/memory tokenizing before the token cap applies. Generous (~40× a
# real description); the token cap above does the semantic limiting.
MAX_VIBE_TEXT_CHARS = 8192

# --- Database (Postgres 16 + pgvector) --------------------------------------- #

# Connection DSN. The default matches docker-compose.yml's dev Postgres; production injects a
# real DATABASE_URL (env wins over .env). asyncpg parses this URL form directly.
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://doppel:doppel@localhost:5432/doppel")
# Optional discrete DB password. When set, it's passed to asyncpg as a connection *argument* that
# overrides any password in DATABASE_URL — never interpolated into the DSN — so an arbitrary secret
# (which may contain `/`, `@`, `?` etc. that would corrupt URL userinfo) connects safely. Prod sets
# this from POSTGRES_PASSWORD and keeps the password out of the DSN; dev/tests leave it unset and use
# the password embedded in the DSN (asyncpg falls back to the DSN password when this is None, so an
# unset value is a true no-op).
DB_PASSWORD = os.getenv("DB_PASSWORD") or None
# asyncpg pool bounds. One shared pool serves the app; min keeps a warm connection, max caps
# concurrency against a single-worker VPS Postgres. Both env-overridable for prod tuning.
DB_POOL_MIN_SIZE = int(os.getenv("DB_POOL_MIN_SIZE", "1"))
DB_POOL_MAX_SIZE = int(os.getenv("DB_POOL_MAX_SIZE", "10"))

# embeddings.model_version key. It must capture *everything* that changes the stored vector —
# the checkpoint AND the pooling strategy — so flipping CLAP_EMBED_POOLING during Day-7 eval
# stores under a distinct key instead of silently mixing incompatible vectors in one corpus.
# Derived (not a hand-minted alias) precisely so it can't be forgotten on a contract change.
CLAP_MODEL_VERSION = f"{CLAP_MODEL_ID}+{CLAP_EMBED_POOLING}"

# Re-embedding policy: an embedding is eligible for refresh when a newly matched
# asset's confidence exceeds the embedded asset's by at least this much — so the corpus upgrades
# off a "good enough" preview when a clearly better one appears, without churning on noise.
REEMBED_CONFIDENCE_DELTA = 0.15

# Stamp written onto every canonical_lookups row. Bump it whenever the matcher / canonicalization
# / normalization logic changes: get_canonical_lookup filters on it, so entries cached under the
# old logic read as a cache miss and get re-resolved, instead of staying sticky forever.
RESOLVER_VERSION = "1"

# --- API / worker / LLM (Day 6) ---------------------------------------------- #

# Redis DSN for the ARQ job queue (the COLD path) + ARQ's job-lifecycle state. docker-compose serves
# Redis under the `worker` profile; production injects a real value. ARQ is the *execution queue
# only* — durable recommendation results live in Postgres (query_logs / query_log_results), so the
# /recommend poll survives a Redis eviction/restart and Day-7 eval has one read interface.
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

# Anthropic (Claude) — the LLM explainer. It writes per-result rationales and NEVER ranks (ranking
# is CLAP's job; the LLM explains, it does not rank). Absent key / API error / timeout
# ⇒ results are returned without rationales (graceful degradation), so a recommendation never
# depends on the LLM. Sonnet 4.6 by default; override LLM_MODEL to swap checkpoints.
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
LLM_MODEL = os.getenv("LLM_MODEL", "claude-sonnet-4-6")
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "2048"))
LLM_TIMEOUT_S = float(os.getenv("LLM_TIMEOUT_S", "30"))

# Vibe→acoustic-terms translation (v2 flagship). Default OFF: when enabled,
# a small/fast LLM rewrites the listener's natural-language vibe into literal CLAP-trained acoustic
# terms before text-encoding, to clear the weak text encoder's ~0.15–0.37 cultural-descriptor wall.
# Degrades to the raw vibe on any failure (missing key / API error / timeout / empty output), so the
# eval-validated raw-vibe path is always the floor — the flagship can only help or no-op, never regress.
VIBE_TRANSLATION_ENABLED = _env_bool("VIBE_TRANSLATION_ENABLED", False)
VIBE_TRANSLATION_MODEL = os.getenv("VIBE_TRANSLATION_MODEL", "claude-haiku-4-5-20251001")
VIBE_TRANSLATION_MAX_TOKENS = int(os.getenv("VIBE_TRANSLATION_MAX_TOKENS", "256"))
VIBE_TRANSLATION_TIMEOUT_S = float(os.getenv("VIBE_TRANSLATION_TIMEOUT_S", "10"))

# HNSW vibe-retrieval lane (v2). Default ON since the source-aware provenance
# work landed and the off-vs-on eval A/B passed at β=0.3 (2026-06-12): when enabled AND a vibe is
# present, run_pipeline's scoring stage knn()s the corpus for the K vibe-nearest tracks and injects them
# as PRE-RESOLVED, MBID-keyed scoring inputs (`_hnsw_lane`) — already-embedded servable corpus rows,
# never the title-keyed pool/dedupe/resolve/gate path. It runs after both gates (a COLD request defers
# without it; the worker does the work), so it never delays a deferral. Off ⇒ behaviour byte-identical
# to pre-v2; no-vibe requests are untouched either way.
HNSW_LANE_ENABLED = _env_bool("HNSW_LANE_ENABLED", True)
HNSW_LANE_K = int(os.getenv("HNSW_LANE_K", "20"))

# Gate 2 (ROADMAP "two-gate async model"): at or above this many FOUND candidates that lack a
# servable embedding, defer the embedding work to the async path instead of embedding inline (CLAP
# is ~230 ms/clip, so a large miss set would stall a warm request). Provisional like Gate 1's
# threshold; calibrate against real pools in Day 7. Both thresholds AND the measured counts they're
# compared against are written to query_logs every request, so the calibration data exists.
GATE2_ASYNC_THRESHOLD = int(os.getenv("GATE2_ASYNC_THRESHOLD", "10"))

# How many results /recommend returns and the LLM explains — and the audio-scored floor that
# triggers cultural backfill: if fewer than this many candidates were audio-scored, top up from the
# cultural RRF order so a sparse-preview query still returns a full list (degraded, and flagged in
# the response's `degradation` block + query_logs).
RECOMMENDATION_LIMIT = int(os.getenv("RECOMMENDATION_LIMIT", "10"))

# How many preview cache-misses the pipeline embeds concurrently. Each in-flight embed buffers up to
# MAX_PREVIEW_BYTES and runs CLAP in a worker thread, so this bounds peak memory + thread pressure on
# the COLD path (which can face hundreds of misses). Small by default for a modest single-worker VPS;
# raise it if the box has headroom. Resolve (MusicBrainz ~1 req/s) stays sequential regardless.
EMBED_CONCURRENCY = int(os.getenv("EMBED_CONCURRENCY", "4"))

# Cap on how many cultural candidates a single run resolves + embeds, taken top-down by cultural RRF
# rank. MusicBrainz's ~1 req/s limit (×~3 paced calls/candidate ⇒ ~7 s each) makes resolving a full
# 100-200 pool infeasible in one run — a 194-candidate seed overran job_timeout at 85 resolved — so
# only the top-N most culturally-relevant candidates are audio-scored and the rest fall to cultural
# backfill. Bounds COLD latency to ~N×7 s; the lazy corpus still grows across queries. How far the
# audio reranker reaches into the pool (i.e. N) is a Day-7 eval calibration knob. Applied identically
# to run_pipeline's resolve loop and the API's Gate-1 uncached count.
RESOLVE_CANDIDATE_LIMIT = int(os.getenv("RESOLVE_CANDIDATE_LIMIT", "75"))

# ARQ job_timeout (seconds) for the COLD recommend_job. A COLD run's top-N resolve still waits on
# MusicBrainz (~1 req/s), so this is generous; RESOLVE_CANDIDATE_LIMIT bounds the work so ~N×7 s +
# seed/embed/explain finishes well inside it. A reaper for a hard kill (SIGKILL/OOM) that outruns
# even this is a separate Day-7 hardening item.
JOB_TIMEOUT_S = int(os.getenv("JOB_TIMEOUT_S", "900"))

# How many COLD jobs the ARQ worker runs concurrently. Default 1 because cold work is
# MusicBrainz-bound and all jobs in a worker share ONE ~1 req/s limiter — so >1 buys no MB throughput
# (the same budget split N ways), only multiplies each job's wall time (risking job_timeout) and
# embedding memory (up to WORKER_MAX_JOBS × EMBED_CONCURRENCY concurrent CLAP inferences). Per-job
# embed parallelism stays bounded by EMBED_CONCURRENCY regardless. Raise only alongside JOB_TIMEOUT_S
# (the validation below couples them).
WORKER_MAX_JOBS = int(os.getenv("WORKER_MAX_JOBS", "1"))

# Stale-running-row reaper threshold (seconds). A COLD recommend_job marks its query_logs row terminal
# only from its own in-process handler; a worker SIGKILL/OOM or VPS reboot *mid-job* leaves the row
# stuck 'running' — polling 202 forever and (via the active request_key index) dedup-wedging future
# identical requests. The worker reaps 'running' rows whose last transition is older than this, marking
# them 'failed' and freeing the dedup. Must exceed JOB_TIMEOUT_S (enforced below) so a job still inside
# its allowed runtime is never reclaimed — a 'running' row older than that outlived ARQ's job_timeout
# cancellation, i.e. a hard kill. ('queued' rows are deliberately NOT age-reaped: their wait scales
# with backlog depth and their ARQ job survives via Redis AOF — see reap_stale_active_query_logs.)
STALE_JOB_RECLAIM_S = int(os.getenv("STALE_JOB_RECLAIM_S", str(JOB_TIMEOUT_S * 2)))

# Measured cold-resolve cost (Day-7: ~85 candidates resolved in the 600 s before a timeout ≈ 7 s
# each, from ~3 paced MusicBrainz calls/candidate at ~1 req/s). Used only to sanity-check that the
# resolve cap fits the COLD job_timeout — not a runtime pacing knob.
COLD_RESOLVE_SECONDS_PER_CANDIDATE = 7


def _validate_tuning(*, resolve_limit: int, job_timeout: int, gate1: int, gate2: int,
                     resolve_cost: int, max_jobs: int, stale_reclaim: int) -> None:
    """Fail fast on incoherent tuning rather than silently defeating the cap or the gates.

    These are deploy/eval knobs (compose passes them through), so a fat-fingered value must be loud,
    not a silent production regression. A non-positive resolve cap makes
    ``pool[:N]`` resolve nearly everything (``N=-1`` → ``pool[:-1]``) or nothing (``N=0`` → no
    candidate audio scoring); a cap that can't finish inside ``job_timeout`` reintroduces the very
    timeout the cap removes; and ``GATE1 > GATE2`` recreates the "resolve inline, then defer at Gate 2
    anyway" dead band. The timeout budget is sized against *concurrent* cold jobs — all ``max_jobs``
    share one ~1 req/s MusicBrainz limiter, so the worst case is ``max_jobs × N × cost``; sizing for a
    single job (the original check) lets concurrent jobs time out despite passing.
    Finally ``STALE_JOB_RECLAIM_S`` must exceed ``job_timeout`` so the stale-row reaper can never
    reclaim a COLD job that is still inside its allowed runtime.
    """
    if resolve_limit < 1:
        raise ValueError(f"RESOLVE_CANDIDATE_LIMIT must be >= 1, got {resolve_limit}")
    if job_timeout < 1:
        raise ValueError(f"JOB_TIMEOUT_S must be >= 1, got {job_timeout}")
    if max_jobs < 1:
        raise ValueError(f"WORKER_MAX_JOBS must be >= 1, got {max_jobs}")
    worst_case = max_jobs * resolve_limit * resolve_cost
    if worst_case > job_timeout:
        raise ValueError(
            f"WORKER_MAX_JOBS={max_jobs} × RESOLVE_CANDIDATE_LIMIT={resolve_limit} × ~{resolve_cost}s "
            f"cold resolve (~{worst_case}s worst case, all jobs sharing one MB limiter) exceeds "
            f"JOB_TIMEOUT_S={job_timeout}; raise JOB_TIMEOUT_S, lower the cap, or lower WORKER_MAX_JOBS."
        )
    if gate1 > gate2:
        raise ValueError(
            f"GATE1_ASYNC_THRESHOLD={gate1} must be <= GATE2_ASYNC_THRESHOLD={gate2}, else a request "
            f"with gate1..gate2 uncached candidates resolves inline and then defers at Gate 2 anyway."
        )
    if stale_reclaim <= job_timeout:
        raise ValueError(
            f"STALE_JOB_RECLAIM_S={stale_reclaim} must be > JOB_TIMEOUT_S={job_timeout}, else the "
            f"reaper could reclaim a COLD job that is still legitimately running."
        )


_validate_tuning(
    resolve_limit=RESOLVE_CANDIDATE_LIMIT, job_timeout=JOB_TIMEOUT_S,
    gate1=GATE1_ASYNC_THRESHOLD, gate2=GATE2_ASYNC_THRESHOLD,
    resolve_cost=COLD_RESOLVE_SECONDS_PER_CANDIDATE, max_jobs=WORKER_MAX_JOBS,
    stale_reclaim=STALE_JOB_RECLAIM_S,
)
