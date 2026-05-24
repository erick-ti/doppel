"""FastAPI application package — the ``/recommend`` API (+ poll) and ``/health``.

Run with ``uvicorn doppel.api.app:app``. See :mod:`doppel.api.app`.
"""
from __future__ import annotations

from doppel.api.app import app, create_app

__all__ = ["app", "create_app"]
