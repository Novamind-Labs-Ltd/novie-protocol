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
from .run_correlation import RunCorrelation

SessionEventSource = Literal[
    "chat", "planning", "dispatch", "gate", "callback", "system", "work_agent",
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
- ``work_agent``：WorkAgent loop（ADR-132）自身投影的事件——能力审批门的
  ``gate_pending`` / ``gate_resolved`` 等。
"""


SessionStatus = Literal["active", "waiting", "completed", "failed", "cancelled"]
"""Session 任务运行状态（operational）。

设计上故意只保留五档：
- ``active``    ：至少一次 in-flight turn。
- ``waiting``   ：正在等待外部输入（HITL gate / external task pending）。
- ``completed`` ：任务正常结束。
- ``failed``    ：因 plan_error / dispatch error 等异常终止。
- ``cancelled`` ：被外部主动取消。

进一步细分（如 ``draft / planning``）应通过 ``payload`` / ``metadata`` 表达，
而不是膨胀此处的状态机。

跟 ``SessionLifecycleState`` 的区别：``SessionStatus`` 描述"这一轮 turn /
plan 在哪个 operational 阶段"；``SessionLifecycleState`` 描述"session 这个
长期对象本身是 alive / dormant / closed / archived"。两者正交，分开追踪。
"""


SessionLifecycleState = Literal["active", "idle", "closed", "archived"]
"""Session 长期对象生命周期（custody）。

ADR-027 锁的四档：

- ``active``    ：用户近期有交互；SSE channel 活；checkpoint 热。
- ``idle``      ：一段时间无交互但 user 未显式关闭；SSE 关闭、checkpoint 冷；
                 新消息进来可以 reactivate 回 ``active``。
- ``closed``    ：user 显式 end / 删除 chat thread；不可再 reactivate，
                 但 history 在 ``archive_ttl`` 内仍可查。
- ``archived``  ：TTL 已过；history 移到冷存储；UI 默认不显示。

合法转换：
  ``active   → idle``         （超过 ``active_idle_ttl_seconds`` 无新事件）
  ``idle     → active``       （新消息到达；reactivate）
  ``idle     → archived``     （超过 ``idle_archive_ttl_seconds``）
  ``active   → closed``       （user 显式关闭）
  ``closed   → archived``     （超过 ``closed_archive_ttl_seconds``）

`closed` 不可回 `active`：用户要继续就 clone history 到新 session。这条
invariant 跟 ``Plan.creator_session_id`` 的不可变性一起实现 ADR-027
"plan 跨 session 时 viewer/operator 而非 creator" 的语义。
"""


# Default lifecycle TTLs (seconds). Tenant policy may shorten these (e.g. for
# compliance retention windows) but never lengthen — short retention is the
# safer default per ADR-027. The cleanup job that enforces transitions reads
# both values; explicit per-tenant overrides win.
DEFAULT_ACTIVE_IDLE_TTL_SECONDS: int = 30 * 60        # 30 minutes
DEFAULT_IDLE_ARCHIVE_TTL_SECONDS: int = 7 * 24 * 3600   # 7 days
DEFAULT_CLOSED_ARCHIVE_TTL_SECONDS: int = 90 * 24 * 3600  # 90 days


# Allowed transitions between lifecycle states. Used by Phase 2's cleanup
# job and by the SessionTimelineService.transition_lifecycle entry point
# to reject illegal transitions at the API surface (closed → active is
# blocked — clone instead).
LIFECYCLE_TRANSITIONS: frozenset[tuple[SessionLifecycleState, SessionLifecycleState]] = frozenset(
    {
        ("active", "idle"),
        ("idle", "active"),
        ("idle", "archived"),
        ("active", "closed"),
        ("closed", "archived"),
    }
)


def is_legal_lifecycle_transition(
    src: SessionLifecycleState, dst: SessionLifecycleState,
) -> bool:
    """``True`` iff ``src → dst`` is in ``LIFECYCLE_TRANSITIONS``.

    No-op transitions (``src == dst``) return ``True`` — the cleanup job
    may write the same state again as a heartbeat without raising.
    """
    if src == dst:
        return True
    return (src, dst) in LIFECYCLE_TRANSITIONS


# ── System ephemeral session (ADR-027) ─────────────────────────────


# Reserved principal namespace prefix. Any principal id starting with
# ``SYSTEM_PRINCIPAL_PREFIX`` is platform-owned — tenants cannot register
# such principals. Enforcement lives in the member-service write path;
# this constant is the canonical reference value.
SYSTEM_PRINCIPAL_PREFIX: str = "system:"

# Session id prefix for platform-internal background tasks (doctor /
# self-heal / scheduled cron). The full shape is
# ``f"{SYSTEM_SESSION_PREFIX}{task_name}:{run_id}"`` so audit / billing
# can route every system invocation through a recognisable ephemeral
# session that does **not** look like a real user chat thread.
SYSTEM_SESSION_PREFIX: str = "system:"


def is_system_principal(principal_id: str) -> bool:
    """``True`` iff ``principal_id`` is reserved for platform use."""
    return principal_id.startswith(SYSTEM_PRINCIPAL_PREFIX)


def is_system_session(session_id: str) -> bool:
    """``True`` iff ``session_id`` is an ephemeral platform-task session."""
    return session_id.startswith(SYSTEM_SESSION_PREFIX)


def mint_system_session_id(task_name: str, run_id: str) -> str:
    """Build the canonical id for a system ephemeral session.

    Used by the doctor / self-heal / scheduled-task entry points to mint
    a session id that satisfies the ``every_workflow_run_has_session_id``
    invariant (W0) without polluting a real user chat thread.

    ``task_name`` and ``run_id`` must be non-empty; the result is
    URL-safe (no spaces / slashes) by construction since callers pass
    safe identifiers.
    """
    if not task_name:
        raise ValueError("system session task_name must be non-empty")
    if not run_id:
        raise ValueError("system session run_id must be non-empty")
    return f"{SYSTEM_SESSION_PREFIX}{task_name}:{run_id}"


def mint_system_principal_id(component: str) -> str:
    """Build a canonical principal id for a platform-owned actor.

    ``component`` is a short identifier for the platform sub-system
    (``doctor`` / ``self_heal`` / ``cron``). Returns a string in the
    ``system:`` namespace so tenant-side principal validation rejects it
    on the way in but the platform itself can audit it cleanly on the
    way out.
    """
    if not component:
        raise ValueError("system principal component must be non-empty")
    return f"{SYSTEM_PRINCIPAL_PREFIX}{component}"


class ReservedPrincipalNamespaceRejected(ValueError):
    """User-supplied principal_id collides with the ``system:`` namespace.

    ADR-027 reserves ``system:*`` for platform-owned background actors
    (doctor / TTL sweeper / auto re-plan). Any tenant-supplied principal
    id starting with that prefix must be rejected before it lands on a
    plan / session / audit row — otherwise a tenant could later cancel
    or mutate via ``assert_plan_mutation_principal``'s
    ``startswith("system:")`` fail-open path.
    """

    def __init__(self, *, principal_id: str, field: str) -> None:
        super().__init__(
            f"principal_id {principal_id!r} on field {field!r} starts with the "
            f"reserved {SYSTEM_PRINCIPAL_PREFIX!r} prefix; this namespace is "
            "platform-owned (ADR-027)."
        )
        self.principal_id = principal_id
        self.field = field


class SessionNotFoundError(LookupError):
    """Raised when a caller tries to write to a session that was not minted.

    Session ids are durable runtime identities. They must be created through
    the platform-owned session minting path before chat, workflow, or gate
    events can append to the timeline.
    """

    def __init__(self, *, session_id: str) -> None:
        super().__init__(f"session {session_id!r} was not explicitly created")
        self.session_id = session_id


def assert_user_principal_id(
    principal_id: str,
    *,
    field: str = "principal_id",
) -> str:
    """Validate a user-supplied principal id and return it normalised.

    Raises :class:`ReservedPrincipalNamespaceRejected` when the input
    falls inside the ``system:`` namespace. Empty strings pass through
    untouched — legacy plans without attribution are still tolerated
    by ``assert_plan_mutation_principal`` and ``Plan.creator_principal_id``
    defaulting to ``""`` is part of the migration contract.

    ``field`` is surfaced inside the exception message so API
    validators can render an actionable 422 (e.g.
    ``"body.plan.creator_principal_id"``).
    """
    normalised = (principal_id or "").strip()
    if not normalised:
        return ""
    if is_system_principal(normalised):
        raise ReservedPrincipalNamespaceRejected(
            principal_id=normalised, field=field,
        )
    return normalised


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
    # ADR-027 custody state — orthogonal to ``status`` (operational state).
    # New sessions begin ``active``; transitions are policed by
    # ``is_legal_lifecycle_transition`` and the cleanup job that owns TTL
    # enforcement. ``closed`` and ``archived`` are terminal (no return to
    # ``active`` — clone the history into a fresh session instead).
    lifecycle_state: SessionLifecycleState = "active"
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
    correlation: RunCorrelation | None = None
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
        correlation=ctx.correlation,
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
