"""Change-Aware Orchestrator 的统一变化事件模型。

所有平台层面的运行时变化 —— plan/step 状态、artifact 产出、agent 心跳、
gate 打开/关闭、policy 决策、外部系统（GitHub / CI / Linear）状态变更 ——
都归一为 ``ChangeEvent`` 进入统一事件流。

设计原则：
- ``correlation_id`` 串联一次任务链路（同一 brief 从 Reception 到 Dispatch 到 Cortex）。
- ``causation_id`` 表明"这个事件由哪个事件直接触发"，形成因果图。
- ``severity`` 让 Orchestrator 快速过滤：info 可忽略；blocking/critical 必须响应。
- ``source`` + ``kind`` 联合唯一标识事件语义，UI 和 Orchestrator 只信这两个字段。
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

from .context import ExecutionContext

# ---------------------------------------------------------------------------
# Source & Severity
# ---------------------------------------------------------------------------

ChangeEventSource = Literal[
    "user",        # 用户发送新消息 / 修改意图
    "planner",     # Planner 生成或修改计划
    "dispatch",    # DispatchService plan/step 流
    "gate",        # HITL gate 状态变化
    "agent",       # 专家 agent（analyst / task_splitter / novie-cortex 等）
    "policy",      # Policy 决策（deny / allow / quota）
    "review",      # 人工 review 结果
    "github",      # GitHub PR / CI 状态变化
    "ci",          # CI pipeline 状态变化
    "linear",      # Linear issue / cycle 状态变化
    "mcp",         # MCP 外部工具调用结果
    "system",      # 平台内部系统事件
]

ChangeEventSeverity = Literal[
    "info",       # 可记录可忽略：正常进度
    "warning",    # 潜在问题，需关注但不阻断
    "blocking",   # 需要人工或系统干预才能继续
    "critical",   # 需立即响应（policy deny / quota exceeded / agent crash 等）
]

# ---------------------------------------------------------------------------
# Kind 枚举 —— 按 subject_type 分组
# ---------------------------------------------------------------------------

# plan.*
CHANGE_KIND_PLAN_CREATED = "plan.created"
CHANGE_KIND_PLAN_STARTED = "plan.started"
CHANGE_KIND_PLAN_PAUSED = "plan.paused"
CHANGE_KIND_PLAN_RESUMED = "plan.resumed"
CHANGE_KIND_PLAN_COMPLETED = "plan.completed"
CHANGE_KIND_PLAN_FAILED = "plan.failed"
CHANGE_KIND_PLAN_CANCELLED = "plan.cancelled"
CHANGE_KIND_PLAN_PATCH_PROPOSED = "plan.patch_proposed"
CHANGE_KIND_PLAN_PATCH_APPROVED = "plan.patch_approved"
CHANGE_KIND_PLAN_PATCH_REJECTED = "plan.patch_rejected"
CHANGE_KIND_PLAN_PATCH_APPLIED = "plan.patch_applied"

# step.*
CHANGE_KIND_STEP_STARTED = "step.started"
CHANGE_KIND_STEP_COMPLETED = "step.completed"
CHANGE_KIND_STEP_FAILED = "step.failed"
CHANGE_KIND_STEP_RETRY_SCHEDULED = "step.retry_scheduled"
CHANGE_KIND_STEP_WAITING_FOR_HUMAN = "step.waiting_for_human"
CHANGE_KIND_STEP_SKIPPED = "step.skipped"
CHANGE_KIND_STEP_STALE = "step.stale"   # 上游 artifact 变化导致 step 输入过时

# artifact.*
CHANGE_KIND_ARTIFACT_CREATED = "artifact.created"
CHANGE_KIND_ARTIFACT_UPDATED = "artifact.updated"
CHANGE_KIND_ARTIFACT_INVALIDATED = "artifact.invalidated"
CHANGE_KIND_ARTIFACT_SCHEMA_INVALID = "artifact.schema_invalid"

# agent.*
CHANGE_KIND_AGENT_STATUS_CHANGED = "agent.status_changed"
CHANGE_KIND_AGENT_TOOL_CALL = "agent.tool_call"
CHANGE_KIND_AGENT_TOOL_RESULT = "agent.tool_result"
CHANGE_KIND_AGENT_HEALTH_CHANGED = "agent.health_changed"

# gate.*
CHANGE_KIND_GATE_REQUESTED = "gate.requested"
CHANGE_KIND_GATE_APPROVED = "gate.approved"
CHANGE_KIND_GATE_REJECTED = "gate.rejected"
CHANGE_KIND_GATE_CHANGES_REQUESTED = "gate.changes_requested"
CHANGE_KIND_GATE_TIMED_OUT = "gate.timed_out"

# policy.*
CHANGE_KIND_POLICY_DENIED = "policy.denied"
CHANGE_KIND_POLICY_REQUIRES_APPROVAL = "policy.requires_approval"
CHANGE_KIND_QUOTA_WARNING = "quota.warning"
CHANGE_KIND_QUOTA_EXCEEDED = "quota.exceeded"

# external.*
CHANGE_KIND_PR_STATUS_CHANGED = "pr.status_changed"
CHANGE_KIND_PR_REVIEW_COMMENT_ADDED = "pr.review_comment_added"
CHANGE_KIND_CI_STATUS_CHANGED = "ci.status_changed"
CHANGE_KIND_LINEAR_ISSUE_STATUS_CHANGED = "linear.issue_status_changed"

# user.*
CHANGE_KIND_USER_INTENT_UPDATED = "user.intent_updated"
CHANGE_KIND_USER_FEEDBACK_SUBMITTED = "user.feedback_submitted"


# ---------------------------------------------------------------------------
# ChangeEvent
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class ChangeEvent:
    """统一变化事件。所有 Orchestrator 关心的运行时变化都归一为此结构。

    ``seq`` 由 ``OrchestrationEventStore`` 分配（写入时），调用方填 0；
    实现方保证 per-plan 单调递增。

    ``subject_type`` / ``subject_id`` 表示"变化的主体"，不一定和
    ``plan_id`` / ``step_id`` 重复（例如 PR 是外部主体）。
    """

    event_id: str
    occurred_at: datetime
    source: ChangeEventSource
    kind: str                        # 建议用上方 CHANGE_KIND_* 常量
    subject_type: str                # plan / step / artifact / agent / gate / pr / ci ...
    subject_id: str                  # 对应主体的 id

    # 可选检索字段 —— 并非每条事件都有 plan/step 上下文
    tenant_id: str = ""
    workspace_id: str = ""
    session_id: str | None = None
    plan_id: str | None = None
    step_id: str | None = None

    severity: ChangeEventSeverity = "info"
    summary: str = ""

    payload: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    # 因果关联
    correlation_id: str | None = None   # 链路级 id（同一 brief → dispatch 链路）
    causation_id: str | None = None     # 直接原因事件 id

    seq: int = 0                        # 由 EventStore 写入时分配


def new_change_event(
    *,
    source: ChangeEventSource,
    kind: str,
    subject_type: str,
    subject_id: str,
    ctx: ExecutionContext | None = None,
    plan_id: str | None = None,
    step_id: str | None = None,
    severity: ChangeEventSeverity = "info",
    summary: str = "",
    payload: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    correlation_id: str | None = None,
    causation_id: str | None = None,
) -> ChangeEvent:
    """工厂：生成一条 ChangeEvent；seq=0，写入 store 时由实现方分配。"""
    return ChangeEvent(
        event_id=f"ce-{uuid.uuid4().hex[:16]}",
        occurred_at=datetime.now(timezone.utc),
        source=source,
        kind=kind,
        subject_type=subject_type,
        subject_id=subject_id,
        tenant_id=ctx.tenant.tenant_id if ctx else "",
        workspace_id=ctx.tenant.workspace_id if ctx else "",
        session_id=ctx.session_id if ctx else None,
        plan_id=plan_id,
        step_id=step_id,
        severity=severity,
        summary=summary,
        payload=dict(payload or {}),
        metadata=dict(metadata or {}),
        correlation_id=correlation_id,
        causation_id=causation_id,
        seq=0,
    )
