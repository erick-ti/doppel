"""ARQ worker package — the COLD recommendation path.

Run with ``arq doppel.worker.worker.WorkerSettings``. See :mod:`doppel.worker.worker`.
"""
from __future__ import annotations

from doppel.worker.worker import WorkerSettings, recommend_job

__all__ = ["WorkerSettings", "recommend_job"]
