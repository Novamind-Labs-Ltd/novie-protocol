"""Session 与 SessionEvent 契约 —— 跨 chat / workflow / gate / callback 的统一时间线。

设计动机（对应 docs/HIGH_PRIORITY_MANAGED_RUNTIME_GAPS.md §2.1）：

- ``Session`` 升级为一等运行时实体。它不再只是一次请求里的 `ctx.session_id`
  字段，而是平台账本上的**长期对象**：UI / 审计 / 回放 / HITL / 恢复都围绕它建模。
- ``SessionEvent`` 是统一时间线条目。chat 流、workflow dispatch 流、HITL gate
  状态翻牌、callback 关键动作都最终 append 进同一条 timeline，而不是各自走
  独立通道。
- ``seq`` 是 per-session 单调递增整数，专门用于 SSE catch-up（``Last-Event-ID`` /
  ``?since=`` 都用它）。``event_id`` 则是全局唯一字符串，用于审计 / 去重。

字段层级原则：

1. **必填**：``seq / event_id / occurred_at / session_id / source / kind``。
   即使来源系统的 envelope 字段不全，envelope 这一层也必须能回答
   "这是谁、什么时候、什么类型的事件"。
2. **检索字段**：``thread_id / tenant_id / workspace_id`` —— 拉时间线、按租户
   隔离、关联 LangGraph thread。
3. **展示字段**：``summary`` —— UI 一行；不存原文，前端不必拉详情就能渲染列表。
4. **结构化负载**：``payload`` 给来源系统自行约定 schema，不收敛 kind 词表，
   保留扩展能力（新增来源不需要改协议层）。
5. **诊断字段**：``metadata`` —— 来源 envelope 原样附带，调试用，UI 可不显示。

故意没把 ``kind`` 限制成 ``Literal[...]``：
- chat 来源会有 ``content / trace / end``
- dispatch 来源会有 ``plan_start / step_status / gate_pending / ...``
- callback 来源会有任意 ``events/publish`` topic
强行收敛会迫使每个来源把语义压扁，反而让 UI 更难做精细展示。``source`` +
``kind`` 二元组才是 UI 路由的稳定 key。
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

from .context import ExecutionContext

SessionEventSource = Literal[
    "chat", "planning", "dispatch", "gate", "callback", "system",
]
"""``SessionEvent.source`` 的稳定枚举。

- ``chat``     ：``ChatAppService`` 的对话流（reception 链路）。
- ``planning`` ：``PlanningAppService`` 的三段式规划（brief 建好 / 策略选中 /
  草案产出 / gate 仲裁 / 最终承诺或拒绝）—— UI 把 planning 作为
  Reception → Dispatch 之间的独立阶段渲染。
- ``dispatch`` ：``DispatchService`` 的 plan / step 流。
- ``gate``     ：HITL gate 状态翻牌（往往作为 dispatch 的子集，但单列出来便于
  UI 在不依赖 dispatch 全量事件的情况下追 gate 状态）。
- ``callback`` ：agent 通过 callback server 反向调用平台时产生的关键事件。
- ``system``   ：由 ``SessionTimelineService`` 自身写入的 envelope 元事件
  （session 创建 / 关闭等）。
"""


SessionStatus = Literal["active", "waiting", "completed", "failed", "cancelled"]
"""Session 生命周期状态。

设计上故意只保留五档：
- ``active``    ：至少一次 in-flight turn。
- ``waiting``   ：正在等待外部输入（HITL gate / external task pending）。
- ``completed`` ：任务正常结束。
- ``failed``    ：因 plan_error / dispatch error 等异常终止。
- ``cancelled`` ：被外部主动取消。

进一步细分（如 ``draft / planning``）应通过 ``payload`` / ``metadata`` 表达，
而不是膨胀此处的状态机。
"""


@dataclass(frozen=True, slots=True)
class Session:
    """一等 Session 资源。

    与 ``ExecutionContext.session_id`` 的关系：``ctx.session_id`` 是请求级
    correlation id，``Session.session_id`` 与之同字符串。``Session`` 携带
    ExecutionContext 之外的运行时账本字段（``status``、起止时间、最后一条事件
    位点等），由 ``SessionTimelineService`` 维护。
    """

    session_id: str
    tenant_id: str
    workspace_id: str
    created_at: datetime
    updated_at: datetime
    project_id: str = ""
    status: SessionStatus = "active"
    thread_id: str | None = None
    title: str | None = None
    last_event_seq: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SessionEvent:
    """单条 session timeline 事件。

    `seq` 是 per-session 的单调递增 id；新事件的 `seq` 严格大于历史最大值。
    SSE catch-up 通过 `?since=<seq>` 拉取，`subscribe` 同样以 `seq` 表达
    断点续传位置。
    """

    seq: int
    event_id: str
    occurred_at: datetime
    session_id: str
    source: SessionEventSource
    kind: str
    summary: str = ""
    tenant_id: str = ""
    workspace_id: str = ""
    project_id: str = ""
    thread_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


def new_session_event(
    *,
    ctx: ExecutionContext,
    source: SessionEventSource,
    kind: str,
    summary: str = "",
    payload: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> SessionEvent:
    """工厂：填好 ``event_id / occurred_at / session_id / 租户字段``。

    `seq` 此处填 0；实际 seq 在 ``SessionTimelineService.record`` 里由实现方
    分配，避免调用方需要先去查 last_seq。这与 ``AuditEvent.new`` 的写法对齐。
    """
    return SessionEvent(
        seq=0,
        event_id=f"sev-{uuid.uuid4().hex[:16]}",
        occurred_at=datetime.now(timezone.utc),
        session_id=ctx.session_id,
        source=source,
        kind=kind,
        summary=summary,
        tenant_id=ctx.tenant.tenant_id,
        workspace_id=ctx.tenant.workspace_id,
        project_id=ctx.tenant.project_id or ctx.tenant.workspace_id,
        thread_id=ctx.thread_id,
        payload=dict(payload or {}),
        metadata=dict(metadata or {}),
    )


@dataclass(frozen=True, slots=True)
class ProjectSessionSummary:
    """Project-scoped session history row for workspace session switching."""

    project_id: str
    session_id: str
    status: SessionStatus
    updated_at: datetime
    last_event_seq: int
    title: str | None = None


@dataclass(frozen=True, slots=True)
class SessionEventsPage:
    """``GET /sessions/{id}/events`` 的分页响应。

    ``events`` 按 ``seq`` 升序，``next_since`` 是下一页应使用的 ``?since=`` 值
    （即本页最后一个 event 的 ``seq``）。``has_more`` 表示服务端确认还有更多
    事件未返回。
    """

    session_id: str
    events: tuple[SessionEvent, ...] = ()
    next_since: int = 0
    has_more: bool = False
