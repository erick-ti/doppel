"""Offline tests for the v2 Phase-1 vibe-translation A/B instrument (eval.vibe_ab).

Only the pure metric core is exercised here — no DB, no CLAP, no network — so it runs on the offline
gate. The driver (run_vibe_ab_seed / main) is integration-only and validated by operator runs.

The load-bearing test is `test_inflation_without_agreement_fails_gate`: the whole point of the
label-free gate is that a translation which merely *inflates* text-cosine magnitude (the exact
"acoustic → non-acoustic" failure, now committed by the LLM) must NOT pass — it has to also rank
candidates more like the reliable audio order.
"""
from __future__ import annotations

import numpy as np
import pytest

from eval.vibe_ab import _ranks, beta_sensitivity, spearman, vibe_ab_metrics

# A 4-dim toy space. seed points along axis 0; candidates spread from near-parallel (high audio
# cosine) to orthogonal (zero), giving a clean audio ground-truth order c0 > c1 > c2 > c3.
SEED = [1.0, 0.0, 0.0, 0.0]
CANDS = [
    [0.9, 0.1, 0.0, 0.0],  # c0 — highest audio cosine (~0.994)
    [0.5, 0.5, 0.0, 0.0],  # c1 — mid (~0.707)
    [0.1, 0.9, 0.0, 0.0],  # c2 — low (~0.110)
    [0.0, 0.0, 1.0, 0.0],  # c3 — orthogonal (0.0)
]
ALIGNED = [1.0, 0.0, 0.0, 0.0]      # text vec parallel to seed → text order tracks audio order
ANTI = [0.1, 0.9, 0.0, 0.0]         # text vec ∝ the low-audio candidate → anti-correlated with audio
MOSTLY_ORTHOGONAL = [0.0, 0.0, 1.0, 0.1]  # aligns only with c3 → weak, anti-correlated text order


def _vecs(rows):
    return [np.asarray(r, dtype=np.float64) for r in rows]


# ── spearman / ranks ─────────────────────────────────────────────────────────────────────────────

def test_spearman_perfect_positive():
    assert spearman([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)


def test_spearman_perfect_negative():
    assert spearman([1, 2, 3, 4], [40, 30, 20, 10]) == pytest.approx(-1.0)


def test_spearman_constant_series_is_none():
    # zero variance ⇒ rank correlation undefined
    assert spearman([5, 5, 5], [1, 2, 3]) is None


def test_spearman_too_short_or_mismatched_is_none():
    assert spearman([1], [1]) is None
    assert spearman([1, 2], [1, 2, 3]) is None


def test_ranks_average_ties():
    # values [5, 5, 1]: the 1 ranks lowest (0), the two 5s share the mean of positions 1 and 2 → 1.5
    assert _ranks([5.0, 5.0, 1.0]) == [1.5, 1.5, 0.0]


# ── vibe_ab_metrics ──────────────────────────────────────────────────────────────────────────────

def test_empty_batch_is_none():
    assert vibe_ab_metrics(np.asarray(SEED), [], np.asarray(ALIGNED), np.asarray(ANTI)) is None


def test_good_translation_passes_gate():
    # raw vibe is mostly-orthogonal (anti-correlated with audio); translated vibe is seed-aligned, so
    # its text order tracks the reliable audio order → magnitude up, agreement up, spread preserved.
    m = vibe_ab_metrics(
        np.asarray(SEED, dtype=np.float64), _vecs(CANDS),
        np.asarray(MOSTLY_ORTHOGONAL, dtype=np.float64), np.asarray(ALIGNED, dtype=np.float64),
    )
    assert m is not None
    assert m["magnitude_lift"] > 0
    assert m["spearman_translated"] == pytest.approx(1.0)      # aligned text order == audio order
    assert m["spearman_raw"] < 0                               # raw vibe fought the audio order
    assert m["agreement_lift"] > 0
    assert m["spread_ok"] is True
    assert m["gate_pass"] is True


def test_inflation_without_agreement_fails_gate():
    # The honesty case: the translated arm RAISES median text-cosine (inflation) but ranks candidates
    # AGAINST the audio order (∝ the low-audio candidate). Magnitude lifts, agreement drops → REJECT.
    m = vibe_ab_metrics(
        np.asarray(SEED, dtype=np.float64), _vecs(CANDS),
        np.asarray(ALIGNED, dtype=np.float64), np.asarray(ANTI, dtype=np.float64),
    )
    assert m is not None
    assert m["magnitude_lift"] > 0          # cosines went UP …
    assert m["agreement_lift"] < 0          # … but agreement with audio went DOWN
    assert m["gate_pass"] is False          # so the gate must reject it


def test_beta_sensitivity_baseline_and_fidelity():
    # top_n=2 (< 4 candidates) so overlap is non-degenerate. β=0 is pure audio ⇒ identical to the
    # audio baseline; the ANTI vibe favours a low-audio candidate, so at β=1 the output diverges and
    # the chosen top-N's mean audio cosine (fidelity) drops.
    curve = beta_sensitivity(
        np.asarray(SEED, dtype=np.float64), _vecs(CANDS),
        np.asarray(ANTI, dtype=np.float64), betas=[0.0, 0.5, 1.0], top_n=2,
    )
    assert curve is not None and len(curve) == 3
    b0, _, b1 = curve
    assert b0["beta"] == 0.0 and b0["overlap_vs_audio"] == 1.0
    assert b1["overlap_vs_audio"] < 1.0
    assert b1["mean_audio_cos_topN"] <= b0["mean_audio_cos_topN"]


def test_beta_sensitivity_empty_is_none():
    assert beta_sensitivity(np.asarray(SEED), [], np.asarray(ANTI), betas=[0.0, 0.5]) is None


def test_noop_translation_fails_gate():
    # Identical arms ⇒ no magnitude lift, no agreement lift ⇒ gate must not pass.
    m = vibe_ab_metrics(
        np.asarray(SEED, dtype=np.float64), _vecs(CANDS),
        np.asarray(ALIGNED, dtype=np.float64), np.asarray(ALIGNED, dtype=np.float64),
    )
    assert m is not None
    assert m["magnitude_lift"] == pytest.approx(0.0)
    assert m["agreement_lift"] == pytest.approx(0.0)
    assert m["topn_overlap"] == pytest.approx(1.0)  # same order ⇒ full overlap
    assert m["gate_pass"] is False
