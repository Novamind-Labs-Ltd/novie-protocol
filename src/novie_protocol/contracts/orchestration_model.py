"""Normalized orchestration model projections.

These objects formalize the conceptual nouns used by
``docs/UNIFIED_ORCHESTRATION_PLAN_GRAPH_CONTRACT.md`` without
replacing the existing runtime contracts. They serve two purposes:

1. provide stable typed names for higher-level orchestration semantics
2. keep backwards-compatible wire/runtime contracts (`ExecutionPlan`,
   `ExecutionGraph`, `PmsIssueSnapshot`, `PlanReviewDecision`, ...) intact

The platform runtime may continue to use legacy names internally. These
dataclasses are projection-friendly envelopes, not mandatory storage schemas.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from .plan import ExecutionPlan, ExecutionStep, PlanGraphMode, PlanStepStatus
from .pms_lifecycle import PmsIssueSnapshot, PmsIssueState

ExecutionLane = Literal["direct", "staged_pms"]
ExecutionRunStatus = Literal[
    "pending",
    "running",
    "completed",
    "failed",
    "cancelled",
]
GovernanceTargetType = Literal["plan", "step"]
GovernanceDecisionAction = Literal["approve", "reject", "request_changes"]


@dataclass(frozen=True, slots=True)
class Intent:
    intent_id: str
    session_id: str
    principal_id: str
    project_id: str
    raw_input: str = ""
    clarified_goal: str = ""
    constraints: dict[str, Any] = field(default_factory=dict)
    artifacts_in: tuple[str, ...] = ()
    created_at: datetime | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.artifacts_in, tuple):
            object.__setattr__(self, "artifacts_in", tuple(self.artifacts_in))


@dataclass(frozen=True, slots=True)
class GovernanceDecision:
    decision_id: str
    target_type: GovernanceTargetType
    target_id: str
    decision: GovernanceDecisionAction
    reason_codes: tuple[str, ...] = ()
    summary: str = ""
    reviewer_id: str | None = None
    created_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.reason_codes, tuple):
            object.__setattr__(self, "reason_codes", tuple(self.reason_codes))


@dataclass(frozen=True, slots=True)
class ExecutionHandoff:
    handoff_id: str
    step_id: str
    lane: ExecutionLane
    handoff_payload: dict[str, Any] = field(default_factory=dict)
    created_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class PmsWorkItem:
    pms_issue_id: str
    step_id: str
    plan_id: str
    intent_id: str = ""
    project_id: str = ""
    state: PmsIssueState = "Backlog"
    metadata: dict[str, Any] = field(default_factory=dict)
    execution_context_seed: dict[str, Any] = field(default_factory=dict)

    @property
    def planner_generated(self) -> bool:
        return bool(self.metadata.get("planner_generated"))

    @property
    def human_created(self) -> bool:
        return bool(self.metadata.get("human_created")) or not self.planner_generated


@dataclass(frozen=True, slots=True)
class ExecutionRun:
    run_id: str
    execution_plan_id: str
    status: ExecutionRunStatus = "pending"
    started_at: datetime | None = None
    finished_at: datetime | None = None
    result_summary: str = ""
    artifacts_out: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.artifacts_out, tuple):
            object.__setattr__(self, "artifacts_out", tuple(self.artifacts_out))


def project_plan_graph(
    *,
    plan: ExecutionPlan,
    intent_id: str = "",
    goal_summary: str = "",
    planner_notes: str = "",
) -> dict[str, Any]:
    """Return a normalized PlanGraph projection over ``ExecutionPlan``.

    The wire/runtime type remains ``ExecutionPlan`` for compatibility. This
    helper gives higher-level callers a stable PlanGraph-shaped dictionary
    without copying the whole model into a second live runtime object.
    """

    return {
        "plan_id": plan.plan_id,
        "intent_id": intent_id,
        "mode": plan.mode,
        "goal_summary": goal_summary,
        "steps": tuple(project_plan_step(step=step, plan_id=plan.plan_id) for step in plan.steps),
        "edges": tuple(
            {"from_step_id": dep, "to_step_id": step.step_id}
            for step in plan.steps
            for dep in step.depends_on
        ),
        "artifacts_out": tuple(plan.metadata.get("artifacts_out", ()) or ()),
        "planner_notes": planner_notes or str(plan.metadata.get("planner_notes") or ""),
        "metadata": dict(plan.metadata),
    }


def project_plan_step(*, step: ExecutionStep, plan_id: str) -> dict[str, Any]:
    return {
        "step_id": step.step_id,
        "plan_id": plan_id,
        "title": str(step.metadata.get("title") or step.step_id),
        "goal": str(step.metadata.get("goal") or ""),
        "kind": str(step.metadata.get("kind") or "other"),
        "execution_mode": step.execution_mode,
        "routing_target": step.routing_target,
        "depends_on": tuple(step.depends_on),
        "required_capabilities": tuple(step.required_capabilities),
        "governance_policy": dict(step.governance_policy),
        "sensitivity_tags": tuple(step.metadata.get("sensitivity_tags", ()) or ()),
        "artifacts_in": tuple(step.metadata.get("artifacts_in", ()) or ()),
        "artifacts_out": tuple(step.metadata.get("artifacts_out", ()) or ()),
        "status": _default_plan_step_status(step=step),
        "pms_issue_type": step.metadata.get("pms_issue_type"),
        "pms_project_id": step.metadata.get("pms_project_id"),
        "execution_context_seed": dict(step.execution_context_seed),
        "metadata": dict(step.metadata),
    }


def project_pms_work_item(snapshot: PmsIssueSnapshot) -> PmsWorkItem:
    metadata = dict(snapshot.metadata)
    return PmsWorkItem(
        pms_issue_id=snapshot.issue_id,
        step_id=str(metadata.get("source_step_id") or ""),
        plan_id=str(metadata.get("source_plan_id") or ""),
        intent_id=str(metadata.get("source_intent_id") or ""),
        project_id=snapshot.project_id,
        state=snapshot.state,
        metadata=metadata,
        execution_context_seed=dict(metadata.get("execution_context_seed") or {}),
    )


def _default_plan_step_status(*, step: ExecutionStep) -> PlanStepStatus:
    if step.execution_mode == "staged_pms":
        return "approved"
    return "ready"
