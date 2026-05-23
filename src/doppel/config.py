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
