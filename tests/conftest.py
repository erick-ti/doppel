"""Pytest configuration.

Two opt-in test classes keep the default suite offline, fast, and hermetic:
  * ``@pytest.mark.integration`` — hits live Deezer / MusicBrainz APIs; run with
    ``--run-integration`` (also gentle on MusicBrainz's rate limit).
  * ``@pytest.mark.db`` — needs a live Postgres + pgvector (``docker compose up`` /
    ``DATABASE_URL``); run with ``--run-db``.
"""
from __future__ import annotations

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-integration",
        action="store_true",
        default=False,
        help="run integration tests that hit live Deezer/MusicBrainz APIs",
    )
    parser.addoption(
        "--run-db",
        action="store_true",
        default=False,
        help="run db tests against a live Postgres + pgvector (DATABASE_URL / docker compose)",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    skip_integration = pytest.mark.skip(reason="live-API test; pass --run-integration to run")
    skip_db = pytest.mark.skip(reason="db test; pass --run-db with a running Postgres to run")
    run_integration = config.getoption("--run-integration")
    run_db = config.getoption("--run-db")
    for item in items:
        if "integration" in item.keywords and not run_integration:
            item.add_marker(skip_integration)
        if "db" in item.keywords and not run_db:
            item.add_marker(skip_db)
