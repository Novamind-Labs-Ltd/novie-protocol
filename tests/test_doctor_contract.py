"""W1 of SYSTEM_DOCTOR — contract tests."""
# ruff: noqa: I001
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from novie_protocol.contracts import (
    DoctorCheckResult,
    DoctorFinding,
    DoctorReport,
    DoctorValidationError,
)


def _finding(
    finding_id: str = "f-1",
    severity: str = "warning",
    classification: str = "degraded_readiness",
) -> DoctorFinding:
    return DoctorFinding(
        finding_id=finding_id,
        classification=classification,  # type: ignore[arg-type]
        severity=severity,  # type: ignore[arg-type]
        title="Title",
        detail="Detail.",
        recommended_action="Do X.",
        detected_at=datetime(2026, 5, 11, tzinfo=UTC),
    )


# ── DoctorFinding contract ───────────────────────────────────────────


def test_finding_round_trips_to_dict() -> None:
    f = _finding()
    payload = f.to_dict()
    assert payload["finding_id"] == "f-1"
    assert payload["severity"] == "warning"
    assert payload["recommended_action"] == "Do X."


def test_finding_requires_finding_id() -> None:
    with pytest.raises(DoctorValidationError, match="finding_id is required"):
        DoctorFinding(
            finding_id="",
            classification="degraded_readiness",
            severity="warning",
            title="T",
            detail="D",
            recommended_action="X",
        )


def test_finding_requires_title() -> None:
    with pytest.raises(DoctorValidationError, match="title"):
        DoctorFinding(
            finding_id="f-1",
            classification="degraded_readiness",
            severity="warning",
            title="",
            detail="D",
            recommended_action="X",
        )


def test_finding_requires_recommended_action() -> None:
    """The 'never leave an operator without a next step' invariant."""
    with pytest.raises(DoctorValidationError, match="recommended_action"):
        DoctorFinding(
            finding_id="f-1",
            classification="degraded_readiness",
            severity="warning",
            title="T",
            detail="D",
            recommended_action="",
        )


# ── DoctorCheckResult contract ──────────────────────────────────────


def test_failed_check_requires_finding_or_error() -> None:
    with pytest.raises(DoctorValidationError, match="must carry a finding or error"):
        DoctorCheckResult(check_id="c-1", status="failed")


def test_skipped_check_rejects_findings() -> None:
    with pytest.raises(DoctorValidationError, match="cannot carry findings"):
        DoctorCheckResult(
            check_id="c-1", status="skipped",
            findings=(_finding(),),
        )


def test_ok_check_can_carry_findings() -> None:
    """A check can be ``ok`` overall while still emitting a
    ``warning`` finding — the per-check status is the operator's
    'did this probe succeed?' answer, not the severity rollup."""
    result = DoctorCheckResult(
        check_id="c-1", status="ok",
        findings=(_finding(severity="warning"),),
    )
    assert result.status == "ok"
    assert len(result.findings) == 1


# ── DoctorReport rollups ────────────────────────────────────────────


def test_report_aggregates_findings_across_checks() -> None:
    r = DoctorReport(
        report_id="r-1",
        scope="platform",
        results=(
            DoctorCheckResult(
                check_id="a", status="ok",
                findings=(_finding(finding_id="f-a", severity="warning"),),
            ),
            DoctorCheckResult(
                check_id="b", status="failed",
                findings=(_finding(finding_id="f-b", severity="error"),),
            ),
        ),
    )
    flat = r.findings
    assert {f.finding_id for f in flat} == {"f-a", "f-b"}


def test_report_severity_summary_counts() -> None:
    r = DoctorReport(
        report_id="r-1",
        scope="platform",
        results=(
            DoctorCheckResult(
                check_id="a", status="failed",
                findings=(_finding(severity="critical"),),
            ),
            DoctorCheckResult(
                check_id="b", status="ok",
                findings=(_finding(severity="warning"),),
            ),
        ),
    )
    counts = r.severity_summary
    assert counts["critical"] == 1
    assert counts["warning"] == 1
    assert counts["error"] == 0
    assert counts["info"] == 0


def test_report_status_picks_highest_severity() -> None:
    """status priority: critical > error > warning > ok."""
    r = DoctorReport(
        report_id="r-1",
        scope="platform",
        results=(
            DoctorCheckResult(
                check_id="a", status="failed",
                findings=(_finding(severity="warning"),),
            ),
            DoctorCheckResult(
                check_id="b", status="failed",
                findings=(_finding(severity="critical"),),
            ),
        ),
    )
    assert r.status == "critical"


def test_report_status_ok_when_no_findings() -> None:
    r = DoctorReport(
        report_id="r-1",
        scope="platform",
        results=(DoctorCheckResult(check_id="a", status="ok"),),
    )
    assert r.status == "ok"
