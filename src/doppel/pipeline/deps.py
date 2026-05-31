"""Dependency-injection factory for the pipeline — builds :class:`PipelineDeps` for the API + worker.

One shared ``httpx.AsyncClient`` (HTTP/2, MusicBrainz's mandatory User-Agent) backs the Deezer
finder, the MusicBrainz canonicalizer, and the ephemeral preview fetches. The asyncpg pool is the
process-wide singleton; CLAP and the Anthropic client load lazily on first use. The API passes an
``enqueue_job`` closure (to defer COLD work to the worker); the worker passes ``None`` — its gates
never enqueue (``execution_mode="job"``).

Import-cheap (no torch at import — the embedder loads it lazily), so importing this on the API-only
path is free. The same shared ``http`` client is reused by the API to build the cultural-aggregation
sources (ListenBrainz / Last.fm), which live outside :class:`PipelineDeps`.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable

import httpx

from doppel.config import HTTP_TIMEOUT_S, USER_AGENT, VIBE_TRANSLATION_ENABLED
from doppel.db.pool import close_pool, get_pool
from doppel.embedding.embedder import ClapEmbedder
from doppel.explanation import ClaudeExplainer
from doppel.pipeline.recommend import PipelineDeps
from doppel.sources.deezer import DeezerClient
from doppel.sources.musicbrainz import MusicBrainzClient
from doppel.translation import ClaudeVibeTranslator


def build_http_client() -> httpx.AsyncClient:
    """The shared async HTTP client — HTTP/2, sane timeout, and the MusicBrainz-required User-Agent."""
    return httpx.AsyncClient(http2=True, timeout=HTTP_TIMEOUT_S, headers={"User-Agent": USER_AGENT})


async def build_deps(
    *, enqueue_job: Callable[..., Awaitable[object]] | None = None
) -> PipelineDeps:
    """Assemble :class:`PipelineDeps` for one process (the API request path or the ARQ worker).

    Opens the process-wide asyncpg pool and a shared HTTP client; constructs the Deezer finder, the
    MusicBrainz canonicalizer (which makes its own ~1 req/s limiter), a lazy CLAP embedder, and the
    degradable Claude explainer. Pass ``enqueue_job`` on the API path so a Gate-2-COLD decision can
    hand off to the worker; leave it ``None`` in the worker.
    """
    http = build_http_client()
    return PipelineDeps(
        pool=await get_pool(),
        finder=DeezerClient(http),
        canonicalizer=MusicBrainzClient(http),
        embedder=ClapEmbedder(),
        http=http,
        explainer=ClaudeExplainer(),
        # v2 flagship, default OFF (VIBE_TRANSLATION_ENABLED): when off, no translator is wired and the
        # raw vibe goes straight to embed — pipeline behaviour is byte-identical to pre-v2.
        translator=ClaudeVibeTranslator() if VIBE_TRANSLATION_ENABLED else None,
        enqueue_job=enqueue_job,
    )


async def close_deps(deps: PipelineDeps) -> None:
    """Tear down what :func:`build_deps` opened — the HTTP client, the explainer, the translator, the pool."""
    await deps.http.aclose()
    if isinstance(deps.explainer, ClaudeExplainer):
        await deps.explainer.aclose()
    if isinstance(deps.translator, ClaudeVibeTranslator):
        await deps.translator.aclose()
    await close_pool()
