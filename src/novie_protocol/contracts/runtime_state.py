"""运行时世界状态快照模型。

``PlanRuntimeState`` 是 OrchestrationStateProjector 投影的输出，
表达"当前这张 plan 的运行时全貌"，是 Orchestrator 做决策的观察面。

关键约束：
- 这些模型只描述运行时状态，不包含业务逻辑。
- ``StepRuntimeState.stale`` 由 Projector 根据上游 artifact 变化自动标记。
- 所有时间戳使用 UTC datetime；``last_event_seq`` 用于 EventStore catch-up。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

# ---------------------------------------------------------------------------
# Step runtime
# ---------------------------------------------------------------------------

StepStatus = Literal[
    "pending",           # 尚未开始
    "running",           # 已派发、正在执行
    "waiting_for_human", # 等待 HITL 或外部输入
    "completed",         # 正常完成
    "failed",            # 执行失败
    "cancelled",         # 被取消
    "skipped",           # 被跳过
    "stale",             # 上游 artifact 变化，输入已过时，需要重跑
]


@dataclass(frozen=True, slots=True)
class StepRuntimeState:
    """单个 step 的运行时状态。"""

    step_id: str
    agent_id: str
    status: StepStatus = "pending"
    started_at: datetime | None = None
    completed_at: datetime | None = None
    retry_count: int = 0
    last_error: str | None = None
    output_artifact_ids: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    stale: bool = False                     # 上游 artifact 变化导致输入过时
    stale_reason: str | None = None         # 哪个 artifact 变化触发了 stale


# ---------------------------------------------------------------------------
# Artifact ref
# ---------------------------------------------------------------------------

ArtifactValidity = Literal["valid", "stale", "invalid"]


@dataclass(frozen=True, slots=True)
class ArtifactRef:
    """plan 上下文中对一个产物的引用（轻量视图）。完整血缘信息在 ArtifactLineage。"""

    artifact_id: str
    artifact_type: str            # requirements_analysis / task_bundle / code_diff / report ...
    version: int = 1
    content_hash: str = ""
    produced_by_step_id: str = ""
    produced_by_agent_id: str = ""
    validity: ArtifactValidity = "valid"
    created_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Gate runtime
# ---------------------------------------------------------------------------

GateRuntimeStatus = Literal[
    "pending",          # 尚未触发
    "open",             # 已打开，等待人工裁决
    "approved",
    "rejected",
    "changes_requested",
    "timed_out",
]


@dataclass(frozen=True, slots=True)
class GateRuntimeState:
    """单个 gate 的当前运行时状态。"""

    gate_id: str
    gate_spec_id: str             # 对应 GateSpec.gate_id（规则定义 id）
    after_step_id: str
    gate_type: str                # 如 scope_confirmation / plan_change_approval / evidence_review
    status: GateRuntimeStatus = "pending"
    opened_at: datetime | None = None
    resolved_at: datetime | None = None
    resolution: dict[str, Any] = field(default_factory=dict)
    payload: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Agent runtime status
# ---------------------------------------------------------------------------

AgentHealthStatus = Literal["healthy", "degraded", "unhealthy", "unknown"]


@dataclass(frozen=True, slots=True)
class AgentRuntimeStatus:
    """单个注册 agent 的运行时健康与负载状态。"""

    agent_id: str
    health: AgentHealthStatus = "unknown"
    active_task_count: int = 0
    last_heartbeat_at: datetime | None = None
    last_error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Policy & Quota runtime state
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class PolicyRuntimeState:
    """plan 当前的 policy / quota 态势。"""

    blocked: bool = False
    block_reason: str | None = None
    active_obligations: tuple[str, ...] = ()
    quota_warning: bool = False
    quota_warning_detail: str | None = None
    last_evaluated_at: datetime | None = None


# ---------------------------------------------------------------------------
# World State
# ---------------------------------------------------------------------------

PlanRuntimeStatus = Literal[
    "pending",
    "running",
    "paused",
    "waiting_change_approval",   # 等待 plan_change_approval gate 通过
    "completed",
    "failed",
    "cancelled",
]


AgentRuntimeReadiness = Literal["ready", "not_ready", "unknown"]
AgentRuntimeProbeResult = Literal["ok", "degraded", "error", "unknown"]
AgentRuntimeFailureSeverity = Literal["info", "warning", "error", "critical"]
RunLivenessCase = Literal[
    "ok",
    "no_first_chunk",
    "mid_stream_silence",
    "timeout_after_accept_unknown",
    "human_wait",
    "not_running",
    "unknown",
]
AgentRuntimeFailureCode = Literal[
    "none",
    "agent_heartbeat_stale",
    "agent_health_probe_failed",
    "agent_endpoint_unreachable",
    "agent_readiness_failed",
    "agent_stream_no_first_chunk",
    "agent_stream_no_progress",
    "agent_invoke_timeout_after_accept",
    "agent_task_failed",
    "agent_registry_missing",
    "agent_capability_unavailable",
]


@dataclass(frozen=True, slots=True)
class AgentRuntimeProbeStatus:
    """Latest health probe result for one agent endpoint."""

    target: str = "healthz"
    status: AgentRuntimeProbeResult = "unknown"
    checked_at: datetime | None = None
    http_status: int | None = None
    latency_ms: int | None = None
    error: str | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AgentRuntimeFailure:
    """Normalized runtime failure envelope for operators and planners."""

    code: AgentRuntimeFailureCode = "none"
    severity: AgentRuntimeFailureSeverity = "info"
    retryable: bool = False
    replan_eligible: bool = False
    message: str = ""
    observed_at: datetime | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AgentCapabilityAvailability:
    """Capability-level availability derived from runtime health state."""

    capability_id: str
    agent_id: str
    project_id: str = ""
    health: AgentHealthStatus = "unknown"
    available: bool = False
    failure_code: AgentRuntimeFailureCode = "none"
    reason: str = ""
    retryable: bool = False
    replan_eligible: bool = False
    observed_at: datetime | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RunLivenessSnapshot:
    """Run-level liveness classification used by workflow status surfaces."""

    plan_id: str
    session_id: str = ""
    health: AgentHealthStatus = "unknown"
    is_stalled: bool = False
    liveness_case: RunLivenessCase = "unknown"
    reason: str = ""
    recommended_actions: tuple[str, ...] = ()
    last_timeline_event_at: datetime | None = None
    observed_at: datetime | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AgentRuntimeHealthSnapshot:
    """Unified runtime health snapshot for one registered expert agent."""

    agent_id: str
    capability_ids: tuple[str, ...] = ()
    project_id: str = ""
    endpoint: str = ""
    protocol_mode: str = ""
    health: AgentHealthStatus = "unknown"
    readiness: AgentRuntimeReadiness = "unknown"
    liveness_case: RunLivenessCase = "unknown"
    failure_code: AgentRuntimeFailureCode = "none"
    severity: AgentRuntimeFailureSeverity = "info"
    retryable: bool = False
    replan_eligible: bool = False
    last_heartbeat_at: datetime | None = None
    last_probe_at: datetime | None = None
    last_timeline_event_at: datetime | None = None
    observed_at: datetime | None = None
    expires_at: datetime | None = None
    recommended_actions: tuple[str, ...] = ()
    diagnostics: dict[str, Any] = field(default_factory=dict)
    probe: AgentRuntimeProbeStatus = field(default_factory=AgentRuntimeProbeStatus)
    failure: AgentRuntimeFailure = field(default_factory=AgentRuntimeFailure)


@dataclass(frozen=True, slots=True)
class PlanRuntimeState:
    """一张 ExecutionPlan 的完整运行时世界状态。

    ``last_event_seq`` 对应 OrchestrationEventStore 中该 plan 的最新 seq，
    用于 Orchestrator 的增量 catch-up：
    ``list_recent_change_events(plan_id, since_seq=last_event_seq)``。
    """

    plan_id: str
    status: PlanRuntimeStatus = "pending"
    current_step_id: str | None = None

    step_states: dict[str, StepRuntimeState] = field(default_factory=dict)
    active_gates: list[GateRuntimeState] = field(default_factory=list)
    artifacts: list[ArtifactRef] = field(default_factory=list)
    agent_statuses: dict[str, AgentRuntimeStatus] = field(default_factory=dict)
    policy_state: PolicyRuntimeState = field(default_factory=PolicyRuntimeState)

    last_event_seq: int = 0
    started_at: datetime | None = None
    updated_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def stale_step_ids(self) -> list[str]:
        """返回所有 stale 状态的 step id。"""
        return [sid for sid, s in self.step_states.items() if s.stale]

    def open_gate_ids(self) -> list[str]:
        """返回所有 open 状态的 gate id。"""
        return [g.gate_id for g in self.active_gates if g.status == "open"]
