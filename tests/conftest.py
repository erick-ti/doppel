"""Pytest configuration.

Integration tests (marked ``@pytest.mark.integration``) hit live Deezer /
MusicBrainz APIs and are skipped unless ``--run-integration`` is passed, so the
default suite stays offline, fast, and gentle on MusicBrainz's rate limit.
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


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if config.getoption("--run-integration"):
        return
    skip = pytest.mark.skip(reason="live-API test; pass --run-integration to run")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip)
