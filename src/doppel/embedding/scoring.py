"""Audio (+ optional vibe-text) similarity scoring for the rerank step.

The matcher resolves cultural candidates to verified previews; the embedder turns
those previews into 512-dim CLAP vectors. This module is the rerank: it scores each
candidate against the *seed* by audio cosine similarity and, when the user supplies a
natural-language vibe description, against that description too (CLAP puts audio and
text in one space, so a text vector is directly comparable to an audio vector).

The two similarity families live on different scales — audio-to-audio cosine and
text-to-audio cosine do not occupy the same range — so they are **min-max normalized
within the candidate batch** before fusion:

    combined = α · norm(audio_cos) + β · norm(vibe_text_cos)

with α = :data:`~doppel.config.AUDIO_SIM_WEIGHT`, β = :data:`~doppel.config.VIBE_TEXT_WEIGHT`.
With no vibe description the text leg drops out and the ranking is the (normalized)
audio cosine alone. The raw cosines are always preserved on the result so downstream
consumers (LLM rationale, logging, the re-embedding policy) see real similarities, not
just the within-batch rescaling.

This is purely the *audio-scored* path: the seed must have an embedding, and only
candidates that were successfully embedded belong in ``candidate_audios``. Candidates
without a usable preview are scored culturally (RRF, :mod:`doppel.aggregation.ranking`)
and backfilled by the orchestration, not here.

Pure NumPy, no torch/transformers — so it runs (and is tested) on the API-only path
without the heavy ``clap`` group. Vectors need not be pre-normalized: cosine is
computed defensively (a zero vector scores 0.0, never a divide-by-zero).
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from numpy.typing import ArrayLike, NDArray

from doppel.config import AUDIO_SIM_WEIGHT, VIBE_TEXT_WEIGHT


@dataclass(frozen=True)
class ScoredCandidate:
    """One candidate's rerank result, keyed back to its position in the input batch.

    ``index`` is the candidate's position in the ``candidate_audios`` passed to
    :func:`score_candidates`, so the caller can map the result back to its
    ``RankedCandidate`` / ``ResolvedMatch``. ``audio_similarity`` / ``text_similarity``
    are the *raw* cosines in [-1, 1] (``text_similarity`` is ``None`` when no vibe
    description was given); ``combined_score`` is the fused, batch-normalized ranking
    score in [0, 1] (when α + β ≤ 1).
    """

    index: int
    audio_similarity: float
    text_similarity: float | None
    combined_score: float


def cosine_similarity(a: ArrayLike, b: ArrayLike) -> float:
    """Cosine similarity of two vectors in [-1, 1]; 0.0 if either has zero norm."""
    av = np.asarray(a, dtype=np.float64)
    bv = np.asarray(b, dtype=np.float64)
    na = float(np.linalg.norm(av))
    nb = float(np.linalg.norm(bv))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return float(np.dot(av, bv) / (na * nb))


def min_max_normalize(values: ArrayLike) -> NDArray[np.float64]:
    """Min-max scale a 1-D array to [0, 1].

    A zero-range batch (a single candidate, or all values equal) carries no ordering
    information, so every entry maps to 1.0 — min-max sends the batch maximum to 1.0,
    and when everything ties everything *is* the maximum. As a constant this leaves any
    fused ranking to the other score (or, with none, to the caller's input order via
    :func:`score_candidates`'s stable index tie-break). An empty array passes through.
    """
    v = np.asarray(values, dtype=np.float64)
    if v.size == 0:
        return v
    lo = float(v.min())
    hi = float(v.max())
    rng = hi - lo
    if rng <= 0.0:
        return np.ones_like(v)
    return (v - lo) / rng


def _cosine_to_batch(query: NDArray[np.float64], matrix: NDArray[np.float64]) -> NDArray[np.float64]:
    """Cosine of ``query`` (D,) against every row of ``matrix`` (N, D) → (N,).

    Zero-norm rows (or a zero-norm query) score 0.0 rather than NaN.
    """
    q_norm = float(np.linalg.norm(query))
    row_norms = np.linalg.norm(matrix, axis=1)
    denom = row_norms * q_norm
    dots = matrix @ query
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(denom > 0.0, dots / denom, 0.0)


def score_candidates(
    seed_audio: ArrayLike,
    candidate_audios: Sequence[ArrayLike],
    *,
    vibe_text: ArrayLike | None = None,
    alpha: float = AUDIO_SIM_WEIGHT,
    beta: float = VIBE_TEXT_WEIGHT,
) -> list[ScoredCandidate]:
    """Rerank ``candidate_audios`` against ``seed_audio`` (+ optional ``vibe_text``).

    Returns the candidates ordered by descending ``combined_score``. Ties break by
    ascending ``index``, so when audio provides no discrimination (e.g. a degenerate
    batch) the caller's incoming order — the cultural RRF order — is preserved.

    ``seed_audio`` and each entry of ``candidate_audios`` are 512-dim CLAP audio
    vectors; ``vibe_text`` is a CLAP *text* vector for the user's vibe description, or
    ``None`` for pure audio scoring. An empty candidate batch yields an empty list.
    """
    candidates = list(candidate_audios)
    if not candidates:
        return []

    matrix = np.asarray(candidates, dtype=np.float64)
    seed = np.asarray(seed_audio, dtype=np.float64)

    audio_cos = _cosine_to_batch(seed, matrix)
    norm_audio = min_max_normalize(audio_cos)

    if vibe_text is not None:
        text_cos = _cosine_to_batch(np.asarray(vibe_text, dtype=np.float64), matrix)
        norm_text = min_max_normalize(text_cos)
        combined = alpha * norm_audio + beta * norm_text
    else:
        text_cos = None
        combined = norm_audio

    scored = [
        ScoredCandidate(
            index=i,
            audio_similarity=float(audio_cos[i]),
            text_similarity=(float(text_cos[i]) if text_cos is not None else None),
            combined_score=float(combined[i]),
        )
        for i in range(len(candidates))
    ]
    scored.sort(key=lambda s: (-s.combined_score, s.index))
    return scored
