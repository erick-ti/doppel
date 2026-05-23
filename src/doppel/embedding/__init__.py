"""Audio embedding + similarity rerank.

:mod:`~doppel.embedding.embedder` loads CLAP and turns previews / text into 512-dim
vectors (heavy ``clap``-group deps, imported lazily); :mod:`~doppel.embedding.scoring`
reranks candidates by audio cosine (+ optional vibe-text), batch-normalized and fused
(pure NumPy, runs on the API-only path).
"""
from __future__ import annotations

from doppel.embedding.scoring import (
    ScoredCandidate,
    cosine_similarity,
    min_max_normalize,
    score_candidates,
)

# Note: embedder symbols (ClapEmbedder, decode_preview, EmbeddingError) are intentionally
# NOT re-exported here — importing them pulls the lazy torch/transformers/av path into
# scope only when you import the embedder module directly, keeping `import doppel.embedding`
# (and thus the scoring path) free of the heavy `clap` group.

__all__ = [
    "ScoredCandidate",
    "cosine_similarity",
    "min_max_normalize",
    "score_candidates",
]
