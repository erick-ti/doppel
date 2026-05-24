"""Pipeline orchestration — the resolve → embed → score → backfill → explain flow behind /recommend.

:func:`run_pipeline` is the one coroutine that runs both inline (WARM) and inside the ARQ worker
(COLD); see :mod:`doppel.pipeline.recommend`. Import-cheap (no torch at import time — the embedder
loads CLAP lazily), so the API-only path and the offline tests can import it freely.
"""
from __future__ import annotations

from doppel.pipeline.recommend import (
    Deferred,
    Degradation,
    Explainer,
    Gate1Meta,
    PipelineDeps,
    Recommendation,
    RecommendationResult,
    enqueue_recommendation,
    parse_handle,
    pool_from_payload,
    request_key_for,
    run_pipeline,
)

__all__ = [
    "Deferred",
    "Degradation",
    "Explainer",
    "Gate1Meta",
    "PipelineDeps",
    "Recommendation",
    "RecommendationResult",
    "enqueue_recommendation",
    "parse_handle",
    "pool_from_payload",
    "request_key_for",
    "run_pipeline",
]
