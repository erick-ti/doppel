"""LLM explanation layer — Claude generates per-result rationales (explanation, never ranking).

:class:`~doppel.explanation.explainer.ClaudeExplainer` satisfies the pipeline's ``Explainer``
protocol and is fully degradable (no key / error / timeout → no rationales). Import-cheap: the
``anthropic`` client is imported lazily on first use.
"""
from __future__ import annotations

from doppel.explanation.explainer import ClaudeExplainer

__all__ = ["ClaudeExplainer"]
