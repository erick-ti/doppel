"""Offline tests for the config-tuning validation (``_validate_tuning``).

A Codex adversarial review flagged that the Day-7 resolve/timeout knobs accept any int from the
environment and are used directly as a slice bound, so a fat-fingered value silently defeats the cap
(``-1`` → ``pool[:-1]`` resolves nearly everything; ``0`` → no candidate audio scoring). These lock
the fail-fast guard, plus the ``GATE1 <= GATE2`` coupling that closes the inline-resolve-then-defer
dead band the review surfaced.
"""
from __future__ import annotations

import pytest

from doppel.config import _validate_tuning

# A coherent baseline (mirrors the shipped defaults); individual cases override one field.
_OK = dict(resolve_limit=75, job_timeout=900, gate1=5, gate2=10, resolve_cost=7, max_jobs=1)


def test_valid_defaults_pass():
    _validate_tuning(**_OK)  # does not raise


@pytest.mark.parametrize("resolve_limit", [0, -1, -75])
def test_nonpositive_resolve_limit_raises(resolve_limit):
    with pytest.raises(ValueError, match="RESOLVE_CANDIDATE_LIMIT"):
        _validate_tuning(**{**_OK, "resolve_limit": resolve_limit})


@pytest.mark.parametrize("job_timeout", [0, -1])
def test_nonpositive_job_timeout_raises(job_timeout):
    with pytest.raises(ValueError, match="JOB_TIMEOUT_S"):
        _validate_tuning(**{**_OK, "job_timeout": job_timeout})


def test_cap_exceeding_timeout_raises():
    # 200 × 7s = 1400s of worst-case cold resolve cannot finish inside a 900s job_timeout.
    with pytest.raises(ValueError, match="exceeds JOB_TIMEOUT_S"):
        _validate_tuning(**{**_OK, "resolve_limit": 200, "job_timeout": 900})


def test_gate1_above_gate2_raises():
    # The old 15 > 10 dead band: a request resolves inline then defers at Gate 2 anyway.
    with pytest.raises(ValueError, match="GATE1_ASYNC_THRESHOLD"):
        _validate_tuning(**{**_OK, "gate1": 15, "gate2": 10})


def test_gate1_equal_gate2_ok():
    _validate_tuning(**{**_OK, "gate1": 10, "gate2": 10})  # boundary: equal is allowed


def test_concurrency_exceeding_timeout_raises():
    # max_jobs=4 cold jobs share one ~1 req/s MB limiter: 4 × 75 × 7s = 2100s worst case > 900s, even
    # though a single job (525s) fits. The budget must be sized against concurrency (Codex 2nd round).
    with pytest.raises(ValueError, match="WORKER_MAX_JOBS"):
        _validate_tuning(**{**_OK, "max_jobs": 4})


@pytest.mark.parametrize("max_jobs", [0, -1])
def test_nonpositive_max_jobs_raises(max_jobs):
    with pytest.raises(ValueError, match="WORKER_MAX_JOBS must be"):
        _validate_tuning(**{**_OK, "max_jobs": max_jobs})
