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
SEARCH_RELEVANCE_MIN = 80
