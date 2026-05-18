from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from .gates import GateSpec

OrchestrationPattern = Literal[
    "single",        # 单 Agent
    "sequential",    # 链式
    "parallel",      # 同层并行
    "dag",           # 一般 DAG（Phase 2；single/sequential/parallel 的超集）
    "supervisor",    # LLM Supervisor 路由 (Phase 3)
    "map_reduce",    # 拆分→并行→合并 (Phase 4)
    "hierarchical",  # supervisor of supervisors (Phase 4)
]

# ---------------------------------------------------------------------------
# Unified orchestration: PlanGraph mode + step routing (W1).
# These are first-class fields, not informal metadata blobs.
# Contract spec: docs/UNIFIED_ORCHESTRATION_PLAN_GRAPH_CONTRACT.md
# ---------------------------------------------------------------------------

PlanGraphMode = Literal[
    "direct_only",   # every step executes directly after governance
    "staged_only",   # every step is materialized into PMS before execution
    "mixed",         # some steps execute directly, others are staged into PMS
]

StepExecutionMode = Literal[
    "direct",        # execute immediately after governance approval
    "staged_pms",    # project step into a PMS work item; execution re-planned later
]

ExecutionModeProvenance = Literal[
    "planner_draft",
    "policy_rewrite",
    "hint_applied",
]

# ADR-016: deprecated since 2026-05-16. ``StepRoutingTarget`` was the
# pre-capability-registry routing hint — it baked specific agent ids
# (``cortex``, ``analyst``, ``reviewer``) into the plan contract. The
# canonical routing is now ``required_capabilities`` + capability
# governance tags resolved through ``CapabilityResolutionSnapshot``;
# the runtime no longer branches on this enum. The alias is kept for
# one cycle for external import compatibility; new contract fields use
# plain ``str`` so business code cannot depend on the enum.
#
# Do not add new values. Do not add new branches that read this enum
# in dispatch / routing logic — the ``ADR-016`` CI grep invariant
# guards against regression.
StepRoutingTarget = Literal[
    "planner",
    "cortex",
    "analyst",
    "reviewer",
    "pms",
    "custom",
]

# Plan-time step status vocabulary. Distinct from runtime ``StepStatus``
# (runtime_state.StepStatus) — that one tracks live execution; this one tracks
# the plan/governance/staging lifecycle of a step before/around execution.
PlanStepStatus = Literal[
    "draft",          # planner emitted; not yet approved
    "approved",       # governance accepted the step
    "staged",         # step has been written into PMS as a work item
    "ready",          # dependencies satisfied; execution may begin
    "running",        # execution started
    "waiting_human",  # blocked on explicit human action (HITL)
    "done",           # execution completed
    "failed",         # execution failed terminally
    "cancelled",      # cancelled before/during execution
]


@dataclass(frozen=True, slots=True)
class ExecutionStep:
    """ExecutionPlan 中的 capability-first 执行节点。

    执行计划不再以 ``agent_id`` 作为主键。Planner 只声明节点需要的
    capability；具体 runtime / agent / binding 必须来自 approve 时冻结的
    ``CapabilityResolutionSnapshot``。
    """

    step_id: str
    required_capabilities: tuple[str, ...]
    capability_args: dict[str, dict[str, Any]] = field(default_factory=dict)
    depends_on: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    # W1-1: first-class step routing.
    # ``execution_mode`` decides whether the step runs directly or is projected
    # into PMS for later execution re-planning. Both are optional during the
    # migration window; downstream consumers must treat ``None`` as
    # "legacy / unspecified" and fall back to current behaviour.
    execution_mode: StepExecutionMode | None = None
    # ADR-010: provenance of how ``execution_mode`` was determined.
    # - planner_draft: accepted directly from planner node
    # - hint_applied: inferred from capability hints/heuristics
    # - policy_rewrite: policy layer rewrote planner intent
    execution_mode_provenance: ExecutionModeProvenance | None = None
    # ADR-016 deprecated since 2026-05-16 — the canonical routing input is
    # ``required_capabilities`` resolved through
    # ``CapabilityResolutionSnapshot``. Kept for one cycle for downstream
    # UI / audit consumers and removed after they migrate. Don't read it
    # in dispatch / routing logic; the ``ADR-016`` CI invariant
    # (``test_adr_016_no_new_agent_id_hardcodings.py``) guards regressions.
    routing_target: str | None = None
    # ``governance_policy`` carries plan-time policy hints for this step
    # (e.g. required reviewer roles, sensitivity tags). ``execution_context_seed``
    # is the structured payload an execution re-planner will consume to build
    # an execution graph (artifact ids, knowledge refs, scheduling hints, ...).
    governance_policy: dict[str, Any] = field(default_factory=dict)
    execution_context_seed: dict[str, Any] = field(default_factory=dict)
    # P9: plan-time lifecycle status. Validator emits ``draft``; PlanReview
    # approve flips it to ``approved``; ingestion service flips to ``staged``
    # when the step is materialised into PMS. Distinct from runtime
    # ``StepStatus`` (which tracks live execution).
    status: PlanStepStatus | None = None

    def __post_init__(self) -> None:
        # 反序列化兜底：LangGraph checkpoint 走 ormsgpack，tuple 在 wire 上
        # 与 list 不可区分，解出来变 list。这里强制回成 tuple，保持
        # ``__annotations__`` 宣告的不变量（字段声明是真相）。``frozen=True``
        # 所以走 ``object.__setattr__`` 绕过冻结保护，__post_init__ 的标准用法。
        if not isinstance(self.required_capabilities, tuple):
            object.__setattr__(
                self,
                "required_capabilities",
                tuple(self.required_capabilities),
            )
        if not isinstance(self.depends_on, tuple):
            object.__setattr__(self, "depends_on", tuple(self.depends_on))
        # Empty strings collapse to ``None`` so wire round-trips don't accidentally
        # produce a literal "" that fails the Literal[...] type contract downstream.
        if isinstance(self.execution_mode, str) and not self.execution_mode:
            object.__setattr__(self, "execution_mode", None)
        if isinstance(self.execution_mode_provenance, str) and not self.execution_mode_provenance:
            object.__setattr__(self, "execution_mode_provenance", None)
        if isinstance(self.routing_target, str) and not self.routing_target:
            object.__setattr__(self, "routing_target", None)
        if isinstance(self.status, str) and not self.status:
            object.__setattr__(self, "status", None)

    def merged_capability_args(self) -> dict[str, Any]:
        merged: dict[str, Any] = {}
        for capability_id in self.required_capabilities:
            merged.update(dict(self.capability_args.get(capability_id) or {}))
        return merged


@dataclass(frozen=True, slots=True)
class ExecutionPlan:
    """Planner 三段式（TeamAssembler → GateArbitrator → PolicyValidator）的最终产出。

    DispatchService.GraphCompiler 拿到此对象，根据 `pattern` 选 GraphTemplate
    并注入 cross-cutting concerns（Policy / HITL / Audit）。

    `plan_provenance` 留给审计 / re-plan / 调试用，记录"这张图是怎么被画出来的"：
    strategy_name / template_id / rationale / policy_decision_refs 等。
    详见 ARCHITECTURE.md §18 附录 A（line 1385）。
    """

    plan_id: str
    pattern: OrchestrationPattern
    steps: tuple[ExecutionStep, ...]
    gates: tuple[GateSpec, ...] = ()
    pattern_config: dict[str, Any] = field(default_factory=dict)
    plan_provenance: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    # W1-1: request-level lane mode for unified orchestration. ``None`` means
    # "legacy/unspecified" — current callers preserve their behaviour. Once W2/W4
    # land, planners are expected to set this explicitly so the platform can
    # derive direct vs staged routing from the contract instead of guessing.
    mode: PlanGraphMode | None = None
    # ADR-027: who originally authored this plan. ``creator_principal_id`` is
    # checked by ``assert_plan_mutation_principal`` on cancel / re-plan paths
    # so a foreign principal cannot cancel another user's plan even within
    # the same tenant. ``creator_session_id`` records the session the plan
    # was born in; it is immutable (re-plans reuse the same value) and is
    # what audit / billing keys on. Empty defaults preserve backwards
    # compatibility — legacy plans without attribution are treated as
    # fail-open (see ``assert_plan_mutation_principal``).
    creator_principal_id: str = ""
    creator_session_id: str = ""

    def __post_init__(self) -> None:
        # 见 ExecutionStep.__post_init__：msgpack 回写的 tuple 会退化成 list，
        # 这里 round-trip 后强制归一。只兜底 sequence 字段；dict 字段直接就是 dict。
        if not isinstance(self.steps, tuple):
            object.__setattr__(self, "steps", tuple(self.steps))
        if not isinstance(self.gates, tuple):
            object.__setattr__(self, "gates", tuple(self.gates))
        if isinstance(self.mode, str) and not self.mode:
            object.__setattr__(self, "mode", None)


# ── ADR-016 deprecation registry ──────────────────────────────────────


DEPRECATED_EXECUTION_STEP_FIELDS: frozenset[str] = frozenset({
    # routing_target was the pre-capability-registry routing hint.
    # See the field declaration in ``ExecutionStep`` and the matching
    # entry on ``novie_platform.domain.plan.PlanStep``. Removal target:
    # one release cycle after 2026-05-16 once downstream consumers
    # (PMS UI categorisation, audit) migrate to capability-based
    # introspection.
    "routing_target",
})
"""Plan-contract fields that are kept only for backwards compatibility.

The CI invariant test asserts the set matches expectations so a
deprecation cannot silently disappear (which would mean the field was
removed without going through the documented cycle) and a new field
can't quietly be marked deprecated without an ADR update."""


# ── ADR-027 plan mutation auth ────────────────────────────────────────


def assert_plan_mutation_principal(
    creator_principal_id: str,
    caller_principal_id: str,
    *,
    op: str,
) -> None:
    """Enforce ADR-027 ``plan_mutation_requires_principal_match`` invariant.

    Cancel / re-plan / patch paths must verify the caller is the plan's
    original creator (``ExecutionPlan.creator_principal_id``) or a
    platform-owned ``system:`` principal (background TTL sweeps, auto
    re-plan from patch exhaustion, doctor / self-heal). Foreign principals
    inside the same tenant are rejected with ``PermissionError``.

    ``creator_principal_id == ""`` is treated as fail-open during the
    migration window: plans authored before ADR-027 wiring landed have
    no attribution. Once every plan creation site populates the field,
    callers should tighten this to a hard rejection.

    ``op`` is a short verb (``cancel_plan`` / ``replan`` / ``patch``)
    surfaced in the error and in audit logs so the rejection point is
    debuggable.
    """
    if not creator_principal_id:
        # Legacy plan — no attribution recorded. Fail open until the
        # full migration completes; see ADR-027 §enforcement.
        return
    if caller_principal_id == creator_principal_id:
        return
    # Platform-owned system principals are trusted for background mutation
    # (auto re-plan, TTL cleanup, doctor). See ``mint_system_principal_id``.
    if caller_principal_id.startswith("system:"):
        return
    raise PermissionError(
        f"plan mutation denied (op={op}): caller principal "
        f"{caller_principal_id!r} does not match plan creator "
        f"{creator_principal_id!r}",
    )


def assert_plan_session_immutable(
    prior_session_id: str,
    new_session_id: str,
    *,
    op: str,
) -> None:
    """Enforce ADR-027 ``plan_creator_session_id_immutable`` invariant.

    Patch / re-plan paths re-construct an :class:`ExecutionPlan` value
    (the contract is frozen but the patch applicator creates a new
    instance). The new instance MUST carry the same
    ``creator_session_id`` as the prior one — re-plans stay in the
    session the plan was born in. Cross-session re-plan would defeat
    the audit / billing keying story and let one session smuggle work
    onto another session's plan id.

    ``prior_session_id == ""`` fails open during the migration window
    (legacy plans without attribution). Once every plan creation site
    populates the field, callers may tighten this to a hard rejection.

    ``op`` is a short verb (``replan`` / ``patch`` / ``ingest``)
    surfaced in the error and audit so the rejection point is
    debuggable.
    """
    if not prior_session_id:
        # Legacy plan with no recorded session; allow rebinding.
        return
    if prior_session_id == new_session_id:
        return
    raise PermissionError(
        f"plan session immutability denied (op={op}): new session "
        f"{new_session_id!r} differs from creator session "
        f"{prior_session_id!r}"
    )
