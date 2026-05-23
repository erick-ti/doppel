"""Scoring tests — cosine, batch min-max normalization, and α/β fusion ranking.

Pure-NumPy rerank logic, so this runs on the offline merge gate (no ``clap`` group).
Pins the behaviors the rerank depends on: audio cosine orders candidates; the
within-batch min-max keeps audio and text comparable before fusion (and never divides
by zero on a degenerate batch); fusion is audio-dominant by default but the weights
steer it; and a batch with no audio discrimination falls back to the caller's incoming
(cultural RRF) order via a stable index tie-break.

Vector dimensionality is arbitrary here (the math is generic) — small vectors are used
for legibility; the real pipeline feeds 512-dim CLAP embeddings.
"""
from __future__ import annotations

import math

import numpy as np

from doppel.config import AUDIO_SIM_WEIGHT, VIBE_TEXT_WEIGHT
from doppel.embedding.scoring import (
    ScoredCandidate,
    cosine_similarity,
    min_max_normalize,
    score_candidates,
)


# --------------------------------------------------------------------------- #
# cosine_similarity
# --------------------------------------------------------------------------- #

def test_cosine_identical_orthogonal_opposite() -> None:
    assert cosine_similarity([1, 0, 0], [1, 0, 0]) == 1.0
    assert cosine_similarity([1, 0, 0], [0, 1, 0]) == 0.0
    assert cosine_similarity([1, 0, 0], [-1, 0, 0]) == -1.0


def test_cosine_is_scale_invariant() -> None:
    # Parallel vectors of different magnitudes are perfectly similar (within float eps).
    assert math.isclose(cosine_similarity([1, 1, 0], [5, 5, 0]), 1.0, abs_tol=1e-9)


def test_cosine_zero_vector_is_zero_not_nan() -> None:
    assert cosine_similarity([0, 0, 0], [1, 2, 3]) == 0.0
    assert cosine_similarity([1, 2, 3], [0, 0, 0]) == 0.0


# --------------------------------------------------------------------------- #
# min_max_normalize
# --------------------------------------------------------------------------- #

def test_min_max_scales_to_unit_range() -> None:
    out = min_max_normalize([1.0, 2.0, 3.0, 4.0])
    assert np.allclose(out, [0.0, 1 / 3, 2 / 3, 1.0])


def test_min_max_handles_negatives() -> None:
    assert np.allclose(min_max_normalize([-1.0, 0.0, 1.0]), [0.0, 0.5, 1.0])


def test_min_max_zero_range_maps_to_ones() -> None:
    # All-equal (incl. a single value) carries no ordering: every entry is the batch max.
    assert np.array_equal(min_max_normalize([5.0, 5.0, 5.0]), [1.0, 1.0, 1.0])
    assert np.array_equal(min_max_normalize([7.0]), [1.0])


def test_min_max_empty_passthrough() -> None:
    assert min_max_normalize([]).size == 0


# --------------------------------------------------------------------------- #
# score_candidates — pure audio
# --------------------------------------------------------------------------- #

def test_orders_by_audio_cosine_and_keeps_input_index() -> None:
    seed = [1.0, 0.0, 0.0]
    candidates = [
        [0.0, 1.0, 0.0],  # idx 0: orthogonal → cos 0.0
        [1.0, 0.0, 0.0],  # idx 1: identical  → cos 1.0
        [1.0, 1.0, 0.0],  # idx 2: 45°        → cos ~0.707
    ]
    scored = score_candidates(seed, candidates)

    assert [s.index for s in scored] == [1, 2, 0]  # best-similarity first
    assert [round(s.audio_similarity, 3) for s in scored] == [1.0, 0.707, 0.0]
    assert all(s.text_similarity is None for s in scored)
    # Min-max within the batch: best → 1.0, worst → 0.0.
    assert scored[0].combined_score == 1.0
    assert scored[-1].combined_score == 0.0
    assert all(0.0 <= s.combined_score <= 1.0 for s in scored)


def test_empty_batch_returns_empty() -> None:
    assert score_candidates([1.0, 0.0], []) == []


def test_single_candidate_scores_one() -> None:
    [only] = score_candidates([1.0, 0.0], [[0.0, 1.0]])
    assert only.index == 0
    assert only.combined_score == 1.0  # zero-range batch → top
    assert math.isclose(only.audio_similarity, 0.0, abs_tol=1e-9)


def test_no_audio_discrimination_preserves_input_order() -> None:
    # Two candidates with identical audio → equal cosine → stable index tie-break,
    # i.e. the caller's incoming (cultural RRF) order survives.
    seed = [1.0, 0.0, 0.0]
    scored = score_candidates(seed, [[0.0, 1.0, 0.0], [0.0, 1.0, 0.0]])
    assert [s.index for s in scored] == [0, 1]
    assert scored[0].combined_score == scored[1].combined_score == 1.0


def test_zero_candidate_vector_does_not_crash() -> None:
    scored = score_candidates([1.0, 0.0], [[0.0, 0.0], [1.0, 0.0]])
    by_index = {s.index: s for s in scored}
    assert by_index[0].audio_similarity == 0.0  # zero vector → cos 0, no NaN
    assert by_index[1].audio_similarity == 1.0


def test_default_weights_come_from_config() -> None:
    seed = [1.0, 0.0]
    cands = [[1.0, 0.0], [0.0, 1.0]]
    vibe = [0.0, 1.0]
    default = score_candidates(seed, cands, vibe_text=vibe)
    explicit = score_candidates(seed, cands, vibe_text=vibe,
                                alpha=AUDIO_SIM_WEIGHT, beta=VIBE_TEXT_WEIGHT)
    assert [s.combined_score for s in default] == [s.combined_score for s in explicit]


# --------------------------------------------------------------------------- #
# score_candidates — audio + vibe-text fusion
# --------------------------------------------------------------------------- #

def test_fusion_is_audio_dominant_by_default() -> None:
    # Audio favors c0, text favors c1. With the audio-dominant default, c0 still wins.
    seed_audio = [1.0, 0.0]
    vibe_text = [0.0, 1.0]
    candidates = [
        [1.0, 0.0],  # idx 0: audio cos 1, text cos 0
        [0.0, 1.0],  # idx 1: audio cos 0, text cos 1
    ]
    scored = score_candidates(seed_audio, candidates, vibe_text=vibe_text)
    assert [s.index for s in scored] == [0, 1]
    top = scored[0]
    assert top.text_similarity is not None  # raw text cosine is reported
    # norm_audio=[1,0], norm_text=[0,1] → combined = α·norm_audio + β·norm_text.
    assert math.isclose(top.combined_score, AUDIO_SIM_WEIGHT, abs_tol=1e-9)


def test_weights_can_flip_the_order() -> None:
    seed_audio = [1.0, 0.0]
    vibe_text = [0.0, 1.0]
    candidates = [[1.0, 0.0], [0.0, 1.0]]
    # Text-dominant weighting promotes the text-aligned candidate (idx 1).
    scored = score_candidates(seed_audio, candidates, vibe_text=vibe_text, alpha=0.3, beta=0.7)
    assert [s.index for s in scored] == [1, 0]


def test_text_breaks_ties_when_audio_is_flat() -> None:
    # A candidate is one audio vector, scored against both the seed audio and the vibe
    # text. These two are equidistant from the seed audio (equal audio cosine → flat),
    # so only the vibe-text alignment discriminates, and it decides the order.
    seed_audio = [1.0, 0.0, 0.0]
    vibe_text = [0.0, 1.0, 0.0]
    candidates = [
        [0.0, 1.0, 1.0],  # idx 0: audio cos 0, text cos ~0.707
        [0.0, 0.0, 1.0],  # idx 1: audio cos 0, text cos 0
    ]
    scored = score_candidates(seed_audio, candidates, vibe_text=vibe_text)
    assert [s.index for s in scored] == [0, 1]
    assert math.isclose(scored[0].audio_similarity, 0.0, abs_tol=1e-9)
    assert math.isclose(scored[1].audio_similarity, 0.0, abs_tol=1e-9)
    assert scored[0].text_similarity > scored[1].text_similarity  # type: ignore[operator]


def test_scored_candidate_is_frozen() -> None:
    s = ScoredCandidate(index=0, audio_similarity=1.0, text_similarity=None, combined_score=1.0)
    try:
        s.index = 5  # type: ignore[misc]
    except AttributeError:
        return
    raise AssertionError("ScoredCandidate should be immutable (frozen dataclass)")
