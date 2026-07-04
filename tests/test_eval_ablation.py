"""Offline tests for the eval harness's HNSW-lane attribution (``eval.harness._hnsw_ablation``).

Pure-function tests (no DB) for the source-aware provenance gate: the eval
report must attribute produced results to the HNSW vibe lane vs the cultural pool, so an
``HNSW_LANE_ENABLED`` off-vs-on run pair is directly diff-able before the flag is ever flipped.
"""
from __future__ import annotations

from doppel.pipeline.recommend import RecommendationResult

from eval.harness import _hnsw_ablation


def _res(position: int, *, sources, combined: float | None = None) -> RecommendationResult:
    return RecommendationResult(
        position=position, title=f"T{position}", artist="A", cultural_score=0.0,
        was_audio_scored=True, sources=tuple(sources), combined_score=combined,
    )


def test_hnsw_ablation_attributes_lane_results_and_ranks():
    # Produced order == list order; lane hits (sources == ("hnsw",)) at final ranks 1, 6, 11 — two of
    # them inside the top-10 k. Cultural rows are correctly excluded from the count.
    results = []
    for i in range(12):
        combined = {0: 0.9, 5: 0.5, 10: 0.3}.get(i)
        if combined is not None:
            results.append(_res(i + 1, sources=("hnsw",), combined=combined))
        else:
            results.append(_res(i + 1, sources=("lastfm", "listenbrainz"), combined=0.6))

    out = _hnsw_ablation(results)
    assert out["n_hnsw"] == 3
    assert out["n_hnsw_top_k"] == 2          # ranks 1 and 6 are within k=10; rank 11 is not
    assert out["ranks"] == [1, 6, 11]        # 1-based final positions
    assert out["combined"] == {"min": 0.3, "median": 0.5, "max": 0.9, "n": 3}


def test_hnsw_ablation_is_empty_when_lane_off():
    # No "hnsw" source (flag off, or the lane surfaced nothing) ⇒ an all-zero/empty record, so an
    # on-run's numbers ARE the lane's measured contribution (nothing to subtract).
    results = [_res(i + 1, sources=("lastfm",), combined=0.5) for i in range(5)]
    out = _hnsw_ablation(results)
    assert out["n_hnsw"] == 0 and out["n_hnsw_top_k"] == 0
    assert out["ranks"] == [] and out["combined"] is None
