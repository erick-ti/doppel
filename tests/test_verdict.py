"""Regression tests for the Day-0 go/no-go verdict logic.

Guards a fix: ``Status.SKIP`` used to be ignored by the
verdict logic, so a skipped *critical* check (via ``--skip-clap`` or because the
CLAP deps weren't installed) printed "GO — all dependencies validated" and exited 0.
A critical SKIP must instead be INCOMPLETE (exit 2) and never read as a passing GO.
"""
from __future__ import annotations

from validate_dependencies import CheckResult, Status, compute_verdict


def _r(number: int, status: Status, *, critical: bool = False) -> CheckResult:
    return CheckResult(number, f"check{number}", status, "summary", critical=critical)


def test_all_pass_is_go() -> None:
    verdict, code = compute_verdict([_r(1, Status.PASS, critical=True), _r(6, Status.PASS, critical=True)])
    assert code == 0
    assert verdict == "GO — all dependencies validated"


def test_critical_fail_is_no_go() -> None:
    verdict, code = compute_verdict([_r(1, Status.PASS, critical=True), _r(6, Status.FAIL, critical=True)])
    assert code == 1
    assert verdict.startswith("NO-GO")


def test_critical_skip_missing_deps_is_incomplete_not_go() -> None:
    # CLAP deps missing => critical SKIP, not an explicit --skip-clap.
    verdict, code = compute_verdict(
        [_r(1, Status.PASS, critical=True), _r(6, Status.SKIP, critical=True)], api_only=False
    )
    assert code == 2
    assert verdict.startswith("INCOMPLETE")
    assert "all dependencies validated" not in verdict


def test_critical_skip_via_skip_clap_is_incomplete_api_only() -> None:
    verdict, code = compute_verdict(
        [_r(1, Status.PASS, critical=True), _r(6, Status.SKIP, critical=True)], api_only=True
    )
    assert code == 2
    assert "API-only" in verdict
    assert "all dependencies validated" not in verdict


def test_noncritical_fail_is_go_with_caveats() -> None:
    verdict, code = compute_verdict(
        [_r(1, Status.PASS, critical=True), _r(4, Status.FAIL, critical=False), _r(6, Status.PASS, critical=True)]
    )
    assert code == 0
    assert "CAVEATS" in verdict


def test_warning_is_go_but_not_fully_validated() -> None:
    verdict, code = compute_verdict(
        [_r(1, Status.PASS, critical=True), _r(4, Status.WARN), _r(6, Status.PASS, critical=True)]
    )
    assert code == 0
    assert verdict.startswith("GO")
    assert "all dependencies validated" not in verdict


def test_noncritical_skip_does_not_block_go() -> None:
    verdict, code = compute_verdict(
        [_r(1, Status.PASS, critical=True), _r(2, Status.SKIP, critical=False), _r(6, Status.PASS, critical=True)]
    )
    assert code == 0
    assert verdict.startswith("GO")
