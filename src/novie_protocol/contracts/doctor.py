"""Doctor contract — W1 of SYSTEM_DOCTOR_AND_REPAIR_BACKLOG.

Frozen shape for health checks, findings, and (future) repair
proposals. The platform DoctorService (W2) composes existing
runtime signals into these primitives; the read-only capabilities
(W3) project them onto the universal capability layer.

Field discipline:
- ``classification`` is a closed enum so dashboards / repair
  catalogs can pattern-match.
- ``severity`` is also closed — operator UI colour-codes from
  these.
- ``evidence`` carries free-form key/value pairs that point AT
  data; the actual payloads live in audit / observability stores.
- ``recommended_action`` is mandatory on every finding so the
  operator always has a next step.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal


DoctorClassification = Literal[
    "dependency_unavailable",
    "degraded_readiness",
    "agent_unhealthy",
    "capability_hidden",
    "binding_missing",
    "credential_unavailable",
    "resource_graph_unavailable",
    "temporal_disconnected",
    "redis_live_tail_degraded",
    "postgres_unreachable",
    "knowledge_boundary_unavailable",
    "mock_dependency_unhealthy",
    "provider_conformance_failed",
    "stalled_stream",
    "catalog_stale",
    "configuration_drift",
]

DoctorSeverity = Literal["info", "warning", "error", "critical"]
"""Operator-facing severity. ``info`` is "FYI"; ``warning`` is
"something is suboptimal but service runs"; ``error`` is "feature
unavailable"; ``critical`` is "platform fundamentally broken"."""

DoctorCheckStatus = Literal["ok", "skipped", "failed"]
RepairRiskTier = Literal["safe_read", "low", "medium", "high", "dangerous"]


class DoctorValidationError(ValueError):
    """Raised when a Doctor payload violates the contract."""


@dataclass(frozen=True, slots=True)
class DoctorCheck:
    """Declarative check the DoctorService runs. Identifies the
    check + bounds runtime."""

    check_id: str
    """Stable id used for dedupe and per-check timeout config."""

    description: str
    timeout_seconds: float = 5.0


@dataclass(frozen=True, slots=True)
class DoctorCheckResult:
    """Outcome of one check execution.

    ``ok`` checks may still produce ``findings`` (e.g. a degraded
    sub-signal that doesn't take the whole check down). ``failed``
    checks MUST produce at least one finding so the operator has
    something to act on; ``skipped`` checks carry zero findings.
    """

    check_id: str
    status: DoctorCheckStatus
    findings: tuple["DoctorFinding", ...] = ()
    duration_ms: int = 0
    error: str = ""
    """When ``status == "failed"`` and the failure was a Python
    exception (vs. a found condition), the message goes here so
    audit replay can reconstruct."""

    def __post_init__(self) -> None:
        if self.status == "failed" and not self.findings and not self.error:
            raise DoctorValidationError(
                f"failed check {self.check_id!r} must carry a finding or error",
            )
        if self.status == "skipped" and self.findings:
            raise DoctorValidationError(
                f"skipped check {self.check_id!r} cannot carry findings",
            )


@dataclass(frozen=True, slots=True)
class DoctorFinding:
    """One concrete diagnostic emitted by a check.

    ``recommended_action`` is REQUIRED — Doctor's contract is "never
    leave an operator without a next step". Repair proposals
    (W5/W6) are the structured form of the action; this field is
    the human prose."""

    finding_id: str
    classification: DoctorClassification
    severity: DoctorSeverity
    title: str
    detail: str
    recommended_action: str
    evidence: dict[str, Any] = field(default_factory=dict)
    detected_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.finding_id:
            raise DoctorValidationError("finding_id is required")
        if not self.title:
            raise DoctorValidationError(
                f"finding {self.finding_id!r} requires a title",
            )
        if not self.recommended_action:
            raise DoctorValidationError(
                f"finding {self.finding_id!r} requires a recommended_action — "
                "Doctor never leaves an operator without a next step",
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "finding_id": self.finding_id,
            "classification": self.classification,
            "severity": self.severity,
            "title": self.title,
            "detail": self.detail,
            "recommended_action": self.recommended_action,
            "evidence": dict(self.evidence),
            "detected_at": self.detected_at.isoformat() if self.detected_at else None,
        }


@dataclass(frozen=True, slots=True)
class RepairProposal:
    """Structured form of a Doctor recommendation. ``W5+ wires the
    execute path; v1 only emits proposals through the read path.

    ``required_capability_id`` is the platform capability that, when
    invoked, performs the repair. ``requires_confirmation`` is the
    operator-facing gate flag; ``risk_tier`` informs the policy
    layer whether auto-execution is allowed."""

    proposal_id: str
    title: str
    description: str
    required_capability_id: str
    risk_tier: RepairRiskTier
    requires_confirmation: bool = True
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RepairOutcome:
    """Result of a (future) repair execution. v1 doesn't run
    repairs; this contract is provided so the protocol layer is
    complete and W5 can land without bumping it."""

    proposal_id: str
    status: Literal["executed", "previewed", "denied", "failed"]
    summary: str
    audit_id: str = ""
    trace_id: str = ""


@dataclass(frozen=True, slots=True)
class DoctorReport:
    """Top-level envelope returned by ``DoctorAppService.run``."""

    report_id: str
    scope: str
    """``platform`` | ``tenant`` | ``project`` | ``agent`` — narrows
    what the report covers."""

    results: tuple[DoctorCheckResult, ...] = ()
    generated_at: datetime | None = None

    @property
    def findings(self) -> tuple[DoctorFinding, ...]:
        """Flattened view across all check results."""
        out: list[DoctorFinding] = []
        for r in self.results:
            out.extend(r.findings)
        return tuple(out)

    @property
    def severity_summary(self) -> dict[str, int]:
        """Per-severity count for at-a-glance dashboards."""
        counts: dict[str, int] = {"info": 0, "warning": 0, "error": 0, "critical": 0}
        for f in self.findings:
            counts[f.severity] = counts.get(f.severity, 0) + 1
        return counts

    @property
    def status(self) -> str:
        """Aggregated status: ``critical`` > ``error`` > ``warning`` > ``ok``."""
        counts = self.severity_summary
        if counts.get("critical"):
            return "critical"
        if counts.get("error"):
            return "error"
        if counts.get("warning"):
            return "warning"
        return "ok"


__all__ = [
    "DoctorCheck",
    "DoctorCheckResult",
    "DoctorCheckStatus",
    "DoctorClassification",
    "DoctorFinding",
    "DoctorReport",
    "DoctorSeverity",
    "DoctorValidationError",
    "RepairOutcome",
    "RepairProposal",
    "RepairRiskTier",
]
