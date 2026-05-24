"""Offline tests for the FastAPI app — a no-op lifespan, so no DB / Redis / pipeline deps are needed.

Covers app construction, ``/health``, request validation, and the malformed-handle 404 — the routes
that don't reach the pipeline. The warm/cold/poll integration is exercised db-gated in
``test_api_db.py``.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from fastapi.testclient import TestClient

from doppel.api.app import create_app


@asynccontextmanager
async def _noop_lifespan(app) -> AsyncIterator[None]:
    yield


@pytest.fixture
def client():
    with TestClient(create_app(lifespan=_noop_lifespan)) as test_client:
        yield test_client


def test_health_ok(client):
    resp = client.get("/health")
    assert resp.status_code == 200 and resp.json() == {"status": "ok"}


def test_openapi_schema_builds(client):
    # Exercises every Pydantic response/request model — a bad schema would 500 here.
    assert client.get("/openapi.json").status_code == 200


def test_recommend_rejects_invalid_body(client):
    assert client.post("/recommend", json={"seed_title": "", "seed_artist": "x"}).status_code == 422  # empty title
    assert client.post("/recommend", json={"seed_artist": "x"}).status_code == 422  # missing title
    assert client.post("/recommend", json={}).status_code == 422


def test_poll_rejects_malformed_handle(client):
    # parse_handle on a non-"rec-<int>" handle raises → 404, before touching pipeline deps.
    assert client.get("/recommend/not-a-handle").status_code == 404
    assert client.get("/recommend/rec-xyz").status_code == 404
