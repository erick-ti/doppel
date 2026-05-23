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
# /track/isrc: endpoint — see DECISIONS.md.)
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
# return [] — see DECISIONS.md). This session-based algorithm favors broad recall.
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

# Gate 1: at or above this many deduped candidates, push MusicBrainz canonicalization
# to the async path instead of resolving inline (MB is ~1 req/sec, so a large pool
# would stall a warm request). See ROADMAP "two-gate async model".
GATE1_ASYNC_THRESHOLD = 15

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
# deployment-hardening pass (see DECISIONS.md) — low marginal value once these + no-redirects
# are in, and correct only with connection pinning to avoid DNS-rebinding.
ALLOWED_PREVIEW_HOST_SUFFIXES = ("dzcdn.net", "deezer.com")

# Audio/text fusion weights (BRAINDUMP "Scoring calibration"):
#   combined = α·norm(audio_cos) + β·norm(vibe_text_cos)
# with each similarity min-max normalized *within the candidate batch* first. Audio
# is the precision leg; CLAP's text encoder is the weaker one on cultural/emotional
# descriptors (BRAINDUMP risk), so the default leans audio-dominant. Provisional —
# to be calibrated against real score distributions in Day 7 eval. With no vibe
# description, scoring falls back to audio alone (β drops out) regardless of these.
AUDIO_SIM_WEIGHT = 0.7  # α
VIBE_TEXT_WEIGHT = 0.3  # β

# The vibe description is user-supplied (the /recommend text leg). CLAP's RoBERTa text
# encoder hard-caps at this many tokens and *raises* (position-embedding overflow) on longer
# input — the tokenizer does not truncate by default — so embed_text token-truncates to it
# and a verbose description degrades instead of crashing the request.
CLAP_TEXT_MAX_TOKENS = 512
# Cheap pre-tokenization char cap, applied before the model loads, so a pathologically large
# vibe string can't burn CPU/memory tokenizing before the token cap applies. Generous (~40× a
# real description); the token cap above does the semantic limiting.
MAX_VIBE_TEXT_CHARS = 8192
