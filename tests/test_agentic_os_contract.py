"""W0 + W3 + W4 of AGENTIC_OS_RUNTIME_EVOLUTION — contract tests."""
# ruff: noqa: I001
from __future__ import annotations

import pytest

from novie_protocol.contracts import (
    EnvironmentProfile,
    EnvironmentSnapshot,
    RUNTIME_INVARIANTS,
    RuntimeHealthFinding,
    RuntimeQuotaDecision,
    RuntimeQuotaPolicy,
)


# ── W0: invariant lock ─────────────────────────────────────────────


def test_runtime_invariants_locked() -> None:
    """W0 acceptance — the invariant list is the canonical reference;
    locking the exact ids prevents drift between code and doc."""
    assert RUNTIME_INVARIANTS == (
        "product_execution_is_temporal_first",
        "every_workflow_run_has_session_id",
        "high_risk_actions_go_through_capability_registry",
        "high_risk_agents_bind_to_environment_profile",
        "repair_actions_are_capability_invocations",
        "self_check_automatic_but_self_repair_policy_gated",
    )


def test_runtime_invariants_count_is_stable() -> None:
    assert len(RUNTIME_INVARIANTS) == 6


# ── W3: Environment profile + snapshot ─────────────────────────────


def test_environment_profile_minimal_construction() -> None:
    profile = EnvironmentProfile(
        environment_id="code-exec-default",
        name="Default Code Execution",
        runtime_type="code_exec_sandbox",
        risk_tier="high",
    )
    assert profile.environment_id == "code-exec-default"
    assert profile.risk_tier == "high"


def test_environment_snapshot_carries_profile_ref() -> None:
    snap = EnvironmentSnapshot(
        snapshot_ref="sha256:abc",
        profile_ref="code-exec-default@1.0.0",
        environment_id="code-exec-default",
        runtime_type="code_exec_sandbox",
        risk_tier="high",
        quota_policy_ref="default-quota",
    )
    assert snap.snapshot_ref == "sha256:abc"
    assert snap.profile_ref == "code-exec-default@1.0.0"


# ── W4: Quota policy ───────────────────────────────────────────────


def test_quota_policy_minimal_construction() -> None:
    policy = RuntimeQuotaPolicy(
        policy_id="reception-tokens-daily",
        description="Daily LLM token cap for Reception.",
        unit="tokens",
        window="day",
        limit=1_000_000,
    )
    assert policy.limit == 1_000_000


def test_quota_policy_rejects_non_positive_limit() -> None:
    with pytest.raises(ValueError, match="limit > 0"):
        RuntimeQuotaPolicy(
            policy_id="x", description="",
            unit="tokens", window="day", limit=0,
        )


def test_quota_decision_shape() -> None:
    decision = RuntimeQuotaDecision(
        policy_id="reception-tokens-daily",
        decision="allow",
        used=50_000,
        limit=1_000_000,
        remaining=950_000,
        window="day",
    )
    assert decision.decision == "allow"
    assert decision.remaining == decision.limit - decision.used


# ── W6: RuntimeHealthFinding mirrors DoctorFinding invariant ───────


def test_runtime_health_finding_requires_recommended_action() -> None:
    """Same 'never leave operator without a next step' invariant as
    ``DoctorFinding``. Locked in both contracts so the future
    self-healing controller can't emit findings that lack an action."""
    with pytest.raises(ValueError, match="recommended_action"):
        RuntimeHealthFinding(
            finding_id="rh-1",
            category="dependency_unavailable",
            severity="error",
            title="X",
            detail="Y",
            recommended_action="",
        )


def test_runtime_health_finding_round_trips() -> None:
    f = RuntimeHealthFinding(
        finding_id="rh-1",
        category="dependency_unavailable",
        severity="error",
        title="Temporal disconnected",
        detail="The Temporal client lost its connection.",
        recommended_action="Run platform.doctor.run.",
    )
    assert f.category == "dependency_unavailable"
