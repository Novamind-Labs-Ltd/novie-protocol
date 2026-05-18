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
- All platform actions route through the capability registry.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


# ── W0: invariant declarations (data-only, machine-readable) ────────


RUNTIME_INVARIANTS: tuple[str, ...] = (
    # ── W0 originals (pre-2026-05-16, locked) ─────────────────────────
    "product_execution_is_temporal_first",
    "every_workflow_run_has_session_id",
    "high_risk_actions_go_through_capability_registry",
    "high_risk_agents_bind_to_environment_profile",
    "repair_actions_are_capability_invocations",
    "self_check_automatic_but_self_repair_policy_gated",
    # ── 2026-05-16 first grilling session (ADR-009 through ADR-028) ───
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
    # ── 2026-05-16 capability-layer deepenings (ADR-029, 030, 031) ────
    "reception_action_routing_strict_internal_namespace",
    "all_invocations_run_named_chain_canonical_v1",
    "discovery_view_single_read_truth_source",
    # ── 2026-05-16 reception-layer deepenings (ADR-032) ───────────────
    "chat_subagent_holds_read_only_tools_via_cis",
    # ── 2026-05-17 ADR-027 reception session isolation ────────────────
    # Reception never reads from prior sessions to build a new session's
    # prompt. The user can reference an old plan by id; Reception then
    # invokes a capability (``platform.runs.status`` /
    # ``platform.runs.final_output.get`` / future ``platform.plan.*``)
    # to fetch the minimal info, instead of pulling the old session's
    # full conversation timeline. Conversation history is per-session
    # custody; cross-session leakage would defeat the
    # ``plan_creator_session_id_immutable`` story.
    "reception_loads_old_plan_via_capability_not_history",
    # ── 2026-05-17 incremental ADR-010/012 invariants ─────────────────
    "execution_mode_provenance_recorded_per_step",
    "task_brief_routing_hint_is_contract_field",
    "single_candidate_routing_skips_llm_rank",
    # ── 2026-05-17 A-lane follow-up collation (ADR-010/011/012/016/019/020) ──
    "step_routing_target_is_compatibility_only",
    "execution_mode_policy_rewrite_is_upgrade_only",
    "capability_governance_is_upgrade_only",
    "capability_selection_rationale_recorded",
    "reception_rejects_unknown_capability_ids",
    "lifecycle_policy_enforced_in_invocation_chain",
)
"""Stable invariant ids; rollout tooling references these. A test
asserts the tuple matches the documented count so a future change
forces a deliberate update of the doc.

The list is **declaration**, not enforcement — each invariant is the
target shape the platform commits to; runtime / CI / review checks
are the enforcement mechanisms (and are tracked per-ADR in the
MIGRATION_GUIDE). Adding to this tuple is not a free action: each
entry must be backed by an ADR explaining context, decision,
consequences, and intended enforcement path. See
`apps/agentic-beta/docs/adr/ADR-009-*` for the canonical index of the
2026-05-16 expansions."""


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
