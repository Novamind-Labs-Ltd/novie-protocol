"""Agentic OS runtime contracts — W0 invariant lock + W3/W4 data
models for AGENTIC_OS_RUNTIME_EVOLUTION_BACKLOG.

This module hosts the **frozen** runtime invariant set + the
Environment / Quota / Health contracts. Even where the
implementation slices (self-healing controller, recovery state
machine, etc.) are still proposed, freezing the data shape lets the
rest of the platform code against a stable surface.

Invariants locked here (W0):
- Product execution is Temporal-first.
- Every product workflow run has a ``session_id``.
- High-risk actions enter through ``PlatformCapabilityRegistry``.
- High-risk agents bind to an Environment profile once W3 lands.
- Repair actions are capability invocations, not side-channel
  mutations.
- Self-check may be automatic; self-repair is policy-gated.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


# ── W0: invariant declarations (data-only, machine-readable) ────────


RUNTIME_INVARIANTS: tuple[str, ...] = (
    "product_execution_is_temporal_first",
    "every_workflow_run_has_session_id",
    "high_risk_actions_go_through_capability_registry",
    "high_risk_agents_bind_to_environment_profile",
    "repair_actions_are_capability_invocations",
    "self_check_automatic_but_self_repair_policy_gated",
)
"""Stable invariant ids; rollout tooling references these. A test
asserts the tuple matches the documented count so a future change
forces a deliberate update of the doc."""


# ── W3: Environment profile contracts ──────────────────────────────


EnvironmentRiskTier = Literal["low", "medium", "high", "dangerous"]
EnvironmentRuntimeType = Literal[
    "code_exec_sandbox",
    "shell_command",
    "container",
    "managed_runtime",
    "external_api",
]


@dataclass(frozen=True, slots=True)
class EnvironmentProfile:
    """A named runtime profile a high-risk agent binds to. The
    profile captures the policy knobs the platform enforces at
    execution time (quota, secret lease policy, approval policy)
    without leaking the underlying runtime details to callers."""

    environment_id: str
    name: str
    runtime_type: EnvironmentRuntimeType
    risk_tier: EnvironmentRiskTier
    quota_policy_ref: str = ""
    secret_lease_policy_ref: str = ""
    approval_policy_ref: str = ""
    description: str = ""
    tags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class EnvironmentSnapshot:
    """Immutable snapshot frozen into workflow / run metadata at
    execution start. ``profile_ref`` points at the
    :class:`EnvironmentProfile` row that produced this snapshot;
    bump the schema version when the snapshot shape changes."""

    snapshot_ref: str
    profile_ref: str
    environment_id: str
    runtime_type: EnvironmentRuntimeType
    risk_tier: EnvironmentRiskTier
    quota_policy_ref: str = ""
    secret_lease_policy_ref: str = ""
    approval_policy_ref: str = ""
    captured_metadata: dict[str, Any] = field(default_factory=dict)


# ── W4: Runtime policy / quota data shape ──────────────────────────


RuntimeQuotaWindow = Literal["minute", "hour", "day"]


@dataclass(frozen=True, slots=True)
class RuntimeQuotaPolicy:
    """Bounded-window quota applied at capability invocation /
    workflow start. ``limit`` is the maximum count of the
    ``unit`` per ``window``."""

    policy_id: str
    description: str
    unit: Literal[
        "invocations",
        "tokens",
        "cost_usd_cents",
        "workflow_starts",
    ]
    window: RuntimeQuotaWindow
    limit: int

    def __post_init__(self) -> None:
        if self.limit <= 0:
            raise ValueError(
                f"RuntimeQuotaPolicy {self.policy_id!r} requires limit > 0; got {self.limit}",
            )


@dataclass(frozen=True, slots=True)
class RuntimeQuotaDecision:
    """Outcome of an evaluation against a quota policy."""

    policy_id: str
    decision: Literal["allow", "warn", "deny"]
    used: int
    limit: int
    remaining: int
    window: RuntimeQuotaWindow
    detail: str = ""


# ── W6: Runtime health findings ────────────────────────────────────


RuntimeHealthSeverity = Literal["info", "warning", "error", "critical"]
RuntimeHealthCategory = Literal[
    "dependency_unavailable",
    "agent_unhealthy",
    "credential_unavailable",
    "quota_exceeded",
    "environment_misconfigured",
    "audit_gap",
    "session_event_dropped",
    "capability_drift",
    "recovery_loop",
]


@dataclass(frozen=True, slots=True)
class RuntimeHealthFinding:
    """W6 / Doctor cross-reference shape. Same enum-driven
    structure as ``DoctorFinding`` but scoped to **runtime** signals
    (active workflows, live capability traffic, agent heartbeats).

    The Doctor (W4 in SYSTEM_DOCTOR) and the future self-healing
    controller (W7 here) both consume this shape so the platform
    has one health vocabulary."""

    finding_id: str
    category: RuntimeHealthCategory
    severity: RuntimeHealthSeverity
    title: str
    detail: str
    recommended_action: str
    evidence: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.recommended_action:
            raise ValueError(
                f"RuntimeHealthFinding {self.finding_id!r} requires a "
                f"recommended_action — same invariant as DoctorFinding.",
            )


__all__ = [
    "EnvironmentProfile",
    "EnvironmentRiskTier",
    "EnvironmentRuntimeType",
    "EnvironmentSnapshot",
    "RuntimeQuotaDecision",
    "RuntimeQuotaPolicy",
    "RuntimeQuotaWindow",
    "RUNTIME_INVARIANTS",
    "RuntimeHealthCategory",
    "RuntimeHealthFinding",
    "RuntimeHealthSeverity",
]
