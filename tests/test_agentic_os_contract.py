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
    locking the exact ids prevents drift between code and doc.

    The 2026-05-16 expansion (ADR-009 through ADR-032) added 23 new
    invariants on top of the original 7. See ADR-009 index for the
    list and rationale."""
    assert RUNTIME_INVARIANTS == (
        # W0 originals
        "product_execution_is_temporal_first",
        "every_workflow_run_has_session_id",
        "high_risk_actions_go_through_capability_registry",
        "high_risk_agents_bind_to_environment_profile",
        "repair_actions_are_capability_invocations",
        "self_check_automatic_but_self_repair_policy_gated",
        # 2026-05-16 first grilling (ADR-009..028)
        "all_platform_actions_go_through_capability_registry",
        "no_specific_agent_id_in_platform_code",
        "snapshot_is_append_only_chain",
        "cross_team_boundary_is_api_not_db_schema",
        "re_plan_and_patch_pass_full_three_stage_validation",
        "reception_to_planner_is_one_way",
        "platform_internal_changes_transparent_to_external_agents",
        "ingestion_writes_pms_atomically",
        "plan_dispatched_transfers_control_to_pms",
        "single_usage_record_belongs_to_one_tenant",
        "usage_record_persisted_at_least_once",
        "capability_id_namespace_fixed_at_registration",
        "manifest_version_diff_passes_platform_check",
        "agent_process_no_cross_tenant_state_pollution",
        "tenant_credentials_short_lived_lease",
        "plan_creator_session_id_immutable",
        "plan_mutation_requires_principal_match",
        "system_session_principal_id_platform_reserved",
        "resource_graph_index_is_hint_only",
        "authorization_decision_never_cached",
        # 2026-05-16 capability-layer deepenings (ADR-029..031)
        "reception_action_routing_strict_internal_namespace",
        "all_invocations_run_named_chain_canonical_v1",
        "discovery_view_single_read_truth_source",
        # 2026-05-16 reception-layer deepenings (ADR-032)
        "chat_subagent_holds_read_only_tools_via_cis",
        # 2026-05-17 ADR-027 reception session isolation
        "reception_loads_old_plan_via_capability_not_history",
        # 2026-05-17 incremental ADR-010/012 invariants
        "execution_mode_provenance_recorded_per_step",
        "task_brief_routing_hint_is_contract_field",
        "single_candidate_routing_skips_llm_rank",
        # 2026-05-17 A-lane follow-up collation
        "step_routing_target_is_compatibility_only",
        "execution_mode_policy_rewrite_is_upgrade_only",
        "capability_governance_is_upgrade_only",
        "capability_selection_rationale_recorded",
        "reception_rejects_unknown_capability_ids",
        "lifecycle_policy_enforced_in_invocation_chain",
    )


def test_runtime_invariants_count_is_stable() -> None:
    assert len(RUNTIME_INVARIANTS) == 40


def test_runtime_invariants_have_no_duplicates() -> None:
    """An ADR-009 expansion accidentally repeating an invariant id would
    otherwise pass the count check silently. Catch it explicitly."""
    assert len(set(RUNTIME_INVARIANTS)) == len(RUNTIME_INVARIANTS)


def test_runtime_invariants_lock_reception_router_requirements() -> None:
    assert "all_platform_actions_go_through_capability_registry" in RUNTIME_INVARIANTS
    assert "reception_action_routing_strict_internal_namespace" in RUNTIME_INVARIANTS


def test_runtime_invariants_lock_named_invocation_chain() -> None:
    assert "all_invocations_run_named_chain_canonical_v1" in RUNTIME_INVARIANTS


def test_runtime_invariants_lock_reception_session_isolation() -> None:
    """ADR-027 — Reception must not inject prior session conversation
    history into a new session prompt. Re-engaging with an old plan
    goes through ``platform.runs.*`` capabilities by plan_id."""
    assert "reception_loads_old_plan_via_capability_not_history" in RUNTIME_INVARIANTS


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
