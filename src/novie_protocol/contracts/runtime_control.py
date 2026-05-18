# ruff: noqa: RUF002, RUF003
"""Runtime Control Plane v1 — product-visible running-truth models.

真值分工
--------
- Temporal           : execution truth — workflow history, signal, deterministic progression
- RuntimeStore (PG)  : product-visible operational truth — all models here
- SessionTimeline    : append-only event stream — SSE, history, animation only
- PMS               : human planning / prioritisation surface only

All models in this module are frozen dataclasses that map 1-to-1 to the
``runtime_*`` Postgres tables (``029_runtime_control_plane.sql``).  They are
the single shared vocabulary between gateway, workflow activities, gate service,
trigger inbox, and UI/API.

Authoring/Execution/Reception executors each emit RuntimeRun/Step/Gate records
via their lifecycle activities — they are NOT replaced, only required to project
into this shared surface.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

RunKind = Literal[
    "reception",           # LangGraph Reception chat-loop turn
    "authoring_planning",  # Planner Draft/Compile/Validate pipeline
    "authoring",           # TicketAuthoringWorkflow (Temporal DAG)
    "execution",           # ExecutionGraphWorkflow (Temporal DAG)
]

RunStatus = Literal[
    "created",
    "running",
    "waiting_human",
    "completed",
    "failed",
    "cancelled",
]


@dataclass(frozen=True, slots=True)
class RuntimeRun:
    """Product-visible record of one execution run.

    ``engine_ref`` is an opaque reference to the owning executor:
    - reception: LangGraph thread_id
    - authoring_planning: planner session_id
    - authoring: Temporal workflow_id
    - execution: Temporal workflow_id

    The ``run_id`` is platform-assigned and stable across retries.
    """

    run_id: str
    tenant_id: str
    workspace_id: str
    run_kind: RunKind
    status: RunStatus = "created"
    engine_ref: str = ""          # opaque owner reference
    session_id: str = ""
    project_id: str = ""
    plan_id: str = ""             # authoring/execution plan id if applicable
    pms_issue_id: str = ""        # set for execution runs
    trigger_id: str = ""          # runtime_triggers fk when PMS-triggered
    created_at: datetime | None = None
    updated_at: datetime | None = None
    completed_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Step
# ---------------------------------------------------------------------------

StepStatus = Literal[
    "pending",
    "running",
    "waiting_human",
    "completed",
    "failed",
    "skipped",
    "cancelled",
]


@dataclass(frozen=True, slots=True)
class RuntimeStep:
    """Product-visible record of one execution step inside a Run."""

    step_id: str
    run_id: str
    tenant_id: str
    workspace_id: str
    status: StepStatus = "pending"
    capability_id: str = ""
    agent_id: str = ""
    runtime_target: str = ""
    engine_step_ref: str = ""     # Temporal activity id or internal step ref
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error: str = ""
    output_summary: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Gate
# ---------------------------------------------------------------------------

GateStatus = Literal[
    "pending",         # gate opened, awaiting decision
    "deciding",        # decision received by platform, signal being sent
    "signaled",        # Temporal signal sent, workflow not yet applied
    "resolved",        # workflow applied decision successfully
    "rejected",        # workflow applied a rejection decision
    "signal_failed",   # signal to Temporal failed; needs retry
    "cancelled",       # gate cancelled (e.g. workflow terminated)
]

GateKind = Literal[
    "clarification",           # Reception LangGraph interrupt
    "plan_review",             # Planner plan review HITL
    "authoring_gate",          # TicketAuthoringWorkflow gate_decision signal
    "execution_governance",    # ExecutionGraphWorkflow governance_gate_decision
]


@dataclass(frozen=True, slots=True)
class RuntimeGate:
    """Product-visible record of one HITL gate.

    ``workflow_signal_ref`` is the Temporal signal name used to unblock the
    workflow.  ``current_decision_id`` and ``gate_version`` allow idempotent
    signal replay without stale-decision overwrites.
    """

    gate_id: str
    run_id: str
    tenant_id: str
    workspace_id: str
    gate_kind: GateKind
    status: GateStatus = "pending"
    step_id: str = ""
    workflow_id: str = ""
    workflow_signal_ref: str = ""   # signal name to send
    current_decision_id: str = ""
    gate_version: int = 0           # monotonically incremented on each decide
    gate_payload: dict[str, Any] = field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    resolved_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class RuntimeGateDecision:
    """One append-only decision attempt for a gate.

    Multiple rows may exist per gate (retries, reversals).  Only one may reach
    ``signal_status=applied``; that row's ``gate_id`` is promoted to ``resolved``
    or ``rejected`` in ``runtime_gates``.
    """

    decision_id: str
    gate_id: str
    tenant_id: str
    workspace_id: str
    gate_version: int
    decision: str                   # approve | reject | request_changes | allow | ...
    reviewer_id: str = ""
    comment: str = ""
    idempotency_key: str = ""
    signal_status: Literal["pending", "sent", "applied", "failed"] = "pending"
    created_at: datetime | None = None
    applied_at: datetime | None = None


# ---------------------------------------------------------------------------
# Trigger
# ---------------------------------------------------------------------------

TriggerKind = Literal[
    "pms_issue_moved_to_todo",
    "api_direct",
    "schedule",
    "manual",
]

TriggerStatus = Literal[
    "received",    # inbox received the trigger
    "claimed",     # dispatcher claimed for processing
    "dispatched",  # execution attempt created
    "ignored",     # duplicate / policy skip
    "failed",      # dispatch failed after retries
]


@dataclass(frozen=True, slots=True)
class RuntimeTrigger:
    """Platform-internal record of an execution trigger event.

    ``dedupe_key`` prevents duplicate execution from concurrent PMS webhook
    and poller observations of the same PMS state transition.

    Pattern: ``{source_type}:{source_id}:{source_state}:{source_version}``
    """

    trigger_id: str
    tenant_id: str
    workspace_id: str
    trigger_kind: TriggerKind
    source_type: str              # "pms" | "api" | "schedule" | "manual"
    source_id: str                # pms_issue_id etc.
    source_state: str = ""        # PMS lane state at transition time
    source_version: str = ""      # PMS updated_at or version token
    dedupe_key: str = ""
    status: TriggerStatus = "received"
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: datetime | None = None
    claimed_at: datetime | None = None
    dispatched_at: datetime | None = None
    delivered_at: datetime | None = None
    abandoned_at: datetime | None = None
    run_id: str = ""              # RuntimeRun created from this trigger


# ---------------------------------------------------------------------------
# Component
# ---------------------------------------------------------------------------

ComponentKind = Literal[
    "postgres",
    "temporal",
    "session_timeline",
    "runtime_store",
    "capability_invocation",
    "langfuse",
    "pms_trigger_inbox",
    "pms_poller",
    "knowledge",
    "redis",
    "external_facts",
    "runtime_monitor",
]

ComponentStatus = Literal[
    "ready",           # fully operational on canonical path
    "degraded",        # operational but on fallback / limited path
    "disabled",        # explicitly disabled via config
    "failed",          # tried to init, failed
    "not_configured",  # required env vars missing
]

ComponentRequirement = Literal[
    "production_required",   # missing → not-ready in production
    "optional",              # missing → degraded-ready
    "dev_only",              # must NOT run in production
]


@dataclass(frozen=True, slots=True)
class RuntimeComponentRecord:
    """Current status of one gateway runtime component.

    Populated by ``_lifespan`` for each component and exposed via ``/readyz``
    and the ``runtime_components`` PG table (for multi-replica visibility).
    """

    component_id: str               # e.g. "postgres", "temporal"
    kind: ComponentKind
    status: ComponentStatus
    requirement: ComponentRequirement
    effective_path: str = ""        # "canonical" | "legacy" | "disabled" | "in_memory"
    fallback_active: bool = False
    detail: str = ""                # human-readable status message
    contract_violations: tuple[str, ...] = field(default_factory=tuple)
    checked_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.contract_violations, tuple):
            object.__setattr__(
                self, "contract_violations", tuple(self.contract_violations),
            )

    @property
    def is_blocking(self) -> bool:
        """True when this component prevents production readiness."""
        return (
            self.requirement == "production_required"
            and self.status not in ("ready",)
        )

    @property
    def is_degraded(self) -> bool:
        return self.status == "degraded" or self.fallback_active


# ---------------------------------------------------------------------------
# ExecutionAttempt
# ---------------------------------------------------------------------------

AttemptStatus = Literal[
    "pending",   # attempt record created, dispatch in progress
    "started",   # workflow started successfully; workflow_id filled in
    "failed",    # dispatch failed; failure_reason filled in
    "ignored",   # trigger was a dup / policy denied (not_todo, lease_busy)
]


@dataclass(frozen=True, slots=True)
class ExecutionAttempt:
    """One dispatch attempt from RuntimeTriggerInbox → PmsTicketExecutionService.

    Maps 1-to-1 to ``execution_attempts`` (030_execution_attempts.sql).
    A single trigger can produce multiple attempts if earlier ones fail.
    """

    attempt_id: str
    trigger_id: str
    tenant_id: str
    workspace_id: str
    pms_issue_id: str
    status: AttemptStatus = "pending"
    workflow_id: str | None = None
    failure_reason: str | None = None
    trigger_source: str = "pms_trigger_inbox"
    created_at: datetime | None = None
    started_at: datetime | None = None


__all__ = [
    # Run
    "RunKind",
    "RunStatus",
    "RuntimeRun",
    # Step
    "StepStatus",
    "RuntimeStep",
    # Gate
    "GateKind",
    "GateStatus",
    "RuntimeGate",
    "RuntimeGateDecision",
    # Trigger
    "TriggerKind",
    "TriggerStatus",
    "RuntimeTrigger",
    # Execution attempt
    "AttemptStatus",
    "ExecutionAttempt",
    # Component
    "ComponentKind",
    "ComponentRequirement",
    "ComponentStatus",
    "RuntimeComponentRecord",
]
