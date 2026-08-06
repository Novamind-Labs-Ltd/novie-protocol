"""Audit 契约 —— 给 step / gate / policy 决策落审计行用。

§9.7 约定：所有 Policy 决策、HITL gate 翻牌、敏感动作执行都必须留审计。

Schema 设计取舍：
- ``ctx_summary`` 是 ``ExecutionContext`` 的"瘦影本"：只留审计要的索引字段，
  避免把整个 ctx（含 metadata 等可变 dict）冻进每条审计行；查询走索引字段即可。
- ``payload`` 任意 JSON-able dict。schema 由 ``kind`` 决定，调用方约定。
- ``event_id`` / ``occurred_at`` 由 ``AuditService.record`` 实装方填，
  调用方传 ``AuditEvent.new(...)`` 工厂时不必关心。

故意没把 audit 做成"被动监听 EventBus"——审计要 fail-fast / 强一致，
和 best-effort 的 in-process pub/sub 是两类语义。
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

from .context import ExecutionContext

AuditEventKind = Literal[
    "plan_start",
    "plan_complete",
    "plan_paused",     # graph interrupt 挂起（durable 长任务 / HITL 等 resume）
    "plan_error",
    "plan_draft_created",      # v0.2 DAG-HITL：LLM 产出 PlanDraft
    "plan_draft_validated",    # v0.2：PlanValidator 产出 ValidatedPlan
    "plan_draft_rejected",     # v0.2：PlanValidator 判定 draft 非法（非 review 拒绝）
    "plan_review_pending",     # v0.2：等待用户计划级 HITL 决定
    "plan_review_resolved",    # v0.2：用户 approve / reject / request_changes
    "plan_replan_requested",   # v0.2：触发新一轮 LLM replan
    "step_start",
    "step_status",
    "step_waiting",
    "step_complete",
    "step_error",
    "gate_open",
    "gate_resolved",
    "gate_rejected",
    "policy_decision",
    # ── Time-travel / checkpoint ────────────────────────────────────────────
    "restore_point_created",      # checkpoint 生成 restore point
    "session_forked",             # 从 restore point fork 出新 session
    "session_resumed",            # 从 checkpoint resume
    # ── UNIVERSAL_CAPABILITY W4 invocation pipeline ──────────────────────────
    "capability_invoked",         # 单次 capability 调用通过 W4 chain (audit step)
    "artifact_accessed",          # capability 读取 artifact（ADR-130 读审计）
    # ── SYSTEM_DOCTOR ───────────────────────────────────────────────────────
    "doctor_check_run",
    "doctor_repair_previewed",
    "doctor_repair_confirmed",
    "doctor_repair_executed",
]


@dataclass(frozen=True, slots=True)
class AuditCtxSummary:
    """ExecutionContext 的不可变瘦影本，可直接索引。"""

    tenant_id: str
    workspace_id: str
    thread_id: str
    session_id: str
    request_id: str
    principal_id: str
    principal_type: str

    @classmethod
    def from_ctx(cls, ctx: ExecutionContext) -> "AuditCtxSummary":
        return cls(
            tenant_id=ctx.tenant.tenant_id,
            workspace_id=ctx.tenant.workspace_id,
            thread_id=ctx.thread_id,
            session_id=ctx.session_id,
            request_id=ctx.request_id,
            principal_id=ctx.identity.principal_id,
            principal_type=ctx.identity.principal_type,
        )


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """单条审计记录。"""

    event_id: str
    occurred_at: datetime
    kind: AuditEventKind
    ctx: AuditCtxSummary
    payload: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def new(
        cls,
        kind: AuditEventKind,
        ctx: ExecutionContext,
        payload: dict[str, Any] | None = None,
    ) -> "AuditEvent":
        """工厂：自动填 event_id / occurred_at / ctx_summary。"""
        return cls(
            event_id=f"audit-{uuid.uuid4().hex[:16]}",
            occurred_at=datetime.now(timezone.utc),
            kind=kind,
            ctx=AuditCtxSummary.from_ctx(ctx),
            payload=dict(payload or {}),
        )
