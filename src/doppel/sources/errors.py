"""Shared exceptions for cultural source adapters.

A :class:`SourceError` marks a *degradable* source failure — one the aggregator should
record in ``failed_sources`` and carry on past (degrade to its other sources), not crash
on. It is deliberately distinct from a genuine empty result (a source that simply has no
candidates for the seed), which is not an error.
"""
from __future__ import annotations


class SourceError(RuntimeError):
    """A degradable failure from a cultural source (recorded by the aggregator, not fatal)."""


class SourceResponseError(SourceError):
    """The upstream returned a 200 with an unusable body — non-JSON, or the wrong shape.

    An outage / maintenance page or schema drift, *not* a legitimate empty result — so the
    aggregator flags the source as degraded rather than mistaking it for no-data.
    """
