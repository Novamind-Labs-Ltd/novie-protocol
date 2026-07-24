# ruff: noqa: RUF002, RUF003
"""ExecutionBrief / ExecutionGraph contracts (W4).

Execution re-planning is a *separate* planning layer from authoring planning:

- authoring planning (``PlanningAppService`` + ``ExecutionPlan``) decides *what
  should be done* under the original user intent.
- execution re-planning (``ExecutionPlanningAppService`` + ``ExecutionGraph``)
  decides *how to execute now* — under current runtime conditions, against the
  staged work item, with execution-phase governance gates inserted as needed.

``ExecutionBrief`` is the canonical, deterministic input to execution
re-planning. It bundles every structured signal a re-planner is allowed to
read so that re-planning is reproducible and never depends on free-text ticket
bodies alone.

``ExecutionGraph`` is the canonical output. It is *not* an ``ExecutionPlan``:
it always traces back to one ``source_step_id`` (and one PMS work item, when
applicable), and its steps are runtime targets, not authoring intents.

This module intentionally keeps the wire shape minimal — the goal is to lock
the contract, not to spec every runtime nuance. Runtime targets reuse the
``StepRoutingTarget`` literal from ``plan.py``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .plan import StepRoutingTarget


@dataclass(frozen=True, slots=True)
class ExecutionBrief:
    """Deterministic input to execution re-planning.

    Built by ``ExecutionBriefBuilder`` from structured sources only:

    - ``pms_issue_id`` / ``pms_issue_snapshot`` — the staged work item
    - ``source_step_id`` / ``source_plan_id`` — provenance back to authoring
    - ``execution_context_seed`` — the seed copied from ``PlanStep`` at
      authoring time (artifact ids, knowledge refs, scheduling hints, ...)
    - ``staged_facts`` — runtime facts captured between authoring and now
      (project context, knowledge retrieval, etc.)
    - ``governance_hints`` — review-gate / sensitivity tags that authoring
      attached to the source step

    The brief is intentionally a value object: re-planners must not read
    anything else. That's what makes execution re-planning testable and
    auditable.
    """

    pms_issue_id: str
    source_step_id: str
    source_plan_id: str
    pms_issue_snapshot: dict[str, Any] = field(default_factory=dict)
    execution_context_seed: dict[str, Any] = field(default_factory=dict)
    staged_facts: dict[str, Any] = field(default_factory=dict)
    knowledge_refs: tuple[str, ...] = ()
    governance_hints: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.knowledge_refs, tuple):
            object.__setattr__(self, "knowledge_refs", tuple(self.knowledge_refs))


@dataclass(frozen=True, slots=True)
class ExecutionGraphStep:
    """One node in an ``ExecutionGraph``.

    ``runtime_target`` reuses the authoring-time ``StepRoutingTarget`` literal:
    cortex / analyst / reviewer / planner / pms / custom. ``capability_id`` is
    the resolved runtime capability (e.g. ``agent.novie-cortex.execute_task_bundle``).
    Args are runtime payload, not authoring metadata.
    """

    step_id: str
    runtime_target: StepRoutingTarget
    capability_id: str = ""
    args: dict[str, Any] = field(default_factory=dict)
    depends_on: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.depends_on, tuple):
            object.__setattr__(self, "depends_on", tuple(self.depends_on))


@dataclass(frozen=True, slots=True)
class ExecutionGraphEdge:
    """Optional explicit edge for graphs richer than DAG-via-depends_on."""

    from_step_id: str
    to_step_id: str
    kind: str = "control"


@dataclass(frozen=True, slots=True)
class ExecutionGovernanceGate:
    """Execution-phase review gate inserted by the re-planner.

    Distinct from authoring-phase ``GateSpec``: gates here exist because of
    *runtime* conditions (sensitive payload detected, policy escalation
    triggered, multi-step coordination required) — not because authoring
    decided so up front.
    """

    gate_id: str
    after_step_id: str
    reason: str
    required_action: str = "approve"
    timing: str = "post_step"
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ExecutionGraph:
    """Output of execution re-planning for one staged step.

    Invariants:

    - ``source_step_id`` is required — every execution graph traces back to
      exactly one authoring step (W2 guardrail).
    - ``source_pms_issue_id`` is required when the step was staged (i.e. the
      PMS lane originated the work).
    - ``steps`` must be non-empty.
    - ``governance_gates`` is optional; when present, execution must honour
      these gates before running the gated successor step.
    """

    execution_plan_id: str
    source_step_id: str
    source_pms_issue_id: str = ""
    steps: tuple[ExecutionGraphStep, ...] = ()
    edges: tuple[ExecutionGraphEdge, ...] = ()
    governance_gates: tuple[ExecutionGovernanceGate, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.steps, tuple):
            object.__setattr__(self, "steps", tuple(self.steps))
        if not isinstance(self.edges, tuple):
            object.__setattr__(self, "edges", tuple(self.edges))
        if not isinstance(self.governance_gates, tuple):
            object.__setattr__(
                self, "governance_gates", tuple(self.governance_gates),
            )
        if not (self.execution_plan_id or "").strip():
            raise ValueError("ExecutionGraph.execution_plan_id required")
        if not (self.source_step_id or "").strip():
            raise ValueError(
                "ExecutionGraph.source_step_id required (W2 traceability)",
            )
        if not self.steps:
            raise ValueError("ExecutionGraph.steps must be non-empty")
        step_ids = {s.step_id for s in self.steps}
        for edge in self.edges:
            if edge.from_step_id not in step_ids or edge.to_step_id not in step_ids:
                raise ValueError(
                    f"ExecutionGraph edge references unknown step "
                    f"({edge.from_step_id!r} → {edge.to_step_id!r})",
                )
        for gate in self.governance_gates:
            if gate.after_step_id not in step_ids:
                raise ValueError(
                    f"ExecutionGovernanceGate {gate.gate_id!r} references "
                    f"unknown step {gate.after_step_id!r}",
                )
