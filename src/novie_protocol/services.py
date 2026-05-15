# ruff: noqa: E501, RUF002, RUF003
"""平台向 Agent 暴露的 Service Protocol。

对应 ARCHITECTURE.md 附录 A。Agent 通过 `PlatformServices` 收口注入；
不允许 Agent 直接 import `novie_platform.*`。
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Protocol

from .contracts import (
    AuditEvent,
    AuditEventKind,
    ChangeEvent,
    CheckpointSnapshot,
    EntitlementDecision,
    ExecutionContext,
    ExternalAgentCheckpointRecord,
    LlmKeyPolicy,
    OrgTokenPool,
    PolicyDecision,
    PolicyRequest,
    ProjectSessionSummary,
    QuotaDecision,
    QuotaPolicy,
    Session,
    SessionEvent,
    SessionEventsPage,
    UsageDimension,
    UsageRecord,
    UsageSummary,
)


class KnowledgeService(Protocol):
    """Query boundary for the independent Knowledge service.

    Platform agents consume curated project knowledge through this protocol.
    Ingestion interfaces are platform-internal and intentionally not exposed via
    ``PlatformServices`` yet; the current runtime only requires retrieval.
    """

    async def search(
        self,
        ctx: ExecutionContext,
        query: str,
        top_k: int = 5,
        *,
        project_id: str | None = None,
    ) -> list[dict[str, Any]]: ...


class KnowledgeIngestionService(Protocol):
    """Platform-internal write boundary for the independent Knowledge service.

    Reception / planner runtime only needs retrieval through ``KnowledgeService``.
    Ingestion remains optional and is intentionally not exposed to agents via
    ``PlatformServices`` yet. Platform producers call one of these typed entry
    points when they want Knowledge to ingest curated inputs.
    """

    async def ingest_artifact_ref(
        self,
        ctx: ExecutionContext,
        *,
        artifact_id: str,
        project_id: str | None = None,
        workspace_id: str | None = None,
        tenant_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None: ...

    async def ingest_hitl_decision(
        self,
        ctx: ExecutionContext,
        *,
        decision_id: str,
        session_id: str | None = None,
        project_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None: ...

    async def ingest_session_summary(
        self,
        ctx: ExecutionContext,
        *,
        session_id: str,
        summary_id: str | None = None,
        project_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None: ...

    async def ingest_uploaded_document(
        self,
        ctx: ExecutionContext,
        *,
        document_id: str,
        filename: str | None = None,
        project_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None: ...


# Compatibility alias while older call sites still refer to ``WikiService``.
# Transition-only: keep for old imports, but do not use this name in new code,
# docs, or capability descriptions.
WikiService = KnowledgeService


class ArtifactIndexReader(Protocol):
    """Artifact index backed by durable storage metadata (blob at ``storage_uri``).

    Production implementations (for example PG-backed registries) expose both
    lookup and registration; agents consume reads via capabilities while the
    orchestration worker writes index rows when steps complete.
    """

    async def get(
        self,
        tenant_id: str,
        workspace_id: str,
        artifact_id: str,
    ) -> Any | None: ...

    async def register(self, ref: Any) -> str:
        """Upsert artifact metadata; ``ref`` matches the platform registry shape."""
        ...

    async def search(
        self,
        tenant_id: str,
        workspace_id: str,
        *,
        thread_id: str | None = None,
        workflow_id: str | None = None,
        artifact_type_prefix: str | None = None,
        summary_contains: str | None = None,
        limit: int = 50,
    ) -> list[Any]:
        """Filtered artifact index scan within tenant/workspace (bounded ``limit``)."""
        ...


class PolicyService(Protocol):
    async def evaluate(self, request: PolicyRequest) -> PolicyDecision: ...


class ReviewService(Protocol):
    """HumanGate 的创建与 resume。"""

    async def open_gate(self, ctx: ExecutionContext, gate_payload: dict[str, Any]) -> str: ...
    async def wait_for_resolution(self, gate_id: str) -> dict[str, Any]: ...


class CheckpointService(Protocol):
    """执行图的状态快照存取。

    所有方法强制携带 `ctx`（含 tenant 信息），禁止裸 thread_id 查库。
    底层实现须以 `ctx.tenant.tenant_id + ctx.tenant.workspace_id + thread_id`
    作为复合分区键，防止跨租户碰撞。
    """

    async def get(
        self,
        ctx: ExecutionContext,
        thread_id: str,
        checkpoint_id: str | None = None,
        *,
        memory_scope: str | None = None,
        owner_agent_id: str | None = None,
    ) -> CheckpointSnapshot | None: ...

    async def list_history(
        self,
        ctx: ExecutionContext,
        thread_id: str,
        limit: int = 20,
        *,
        memory_scope: str | None = None,
        owner_agent_id: str | None = None,
    ) -> list[CheckpointSnapshot]: ...

    async def record_summary(
        self,
        ctx: ExecutionContext,
        *,
        thread_id: str,
        summary: str,
        checkpoint_id: str | None = None,
        payload: dict[str, Any] | None = None,
        workflow_id: str | None = None,
        agent_id: str | None = None,
        step_id: str | None = None,
        memory_scope: str | None = None,
        owner_agent_id: str | None = None,
    ) -> str: ...


class TimeTravelService(Protocol):
    """白名单 + 受控的时间旅行。仅 fork，不允许覆盖历史。见 §10.6。

    所有方法强制携带 `ctx`，fork 时由工厂生成新 thread_id 并写入 checkpoint metadata。
    """

    async def list_history(
        self,
        ctx: ExecutionContext,
        thread_id: str,
        limit: int = 20,
    ) -> list[CheckpointSnapshot]: ...

    async def fork_from(
        self,
        ctx: ExecutionContext,
        thread_id: str,
        checkpoint_id: str,
        reason: str,
    ) -> str: ...


class ExternalAgentCheckpointService(Protocol):
    """Opaque checkpoint persistence for external expert agents."""

    async def put(
        self,
        ctx: ExecutionContext,
        *,
        owner_agent_id: str,
        thread_id: str,
        payload: dict[str, Any],
        checkpoint_id: str | None = None,
        session_id: str | None = None,
        workflow_id: str | None = None,
        step_id: str | None = None,
        checkpoint_format: str = "langgraph",
        checkpoint_version: str = "1",
        summary: str | None = None,
        parent_checkpoint_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ExternalAgentCheckpointRecord: ...

    async def get(
        self,
        ctx: ExecutionContext,
        *,
        owner_agent_id: str,
        thread_id: str,
        checkpoint_id: str | None = None,
    ) -> ExternalAgentCheckpointRecord | None: ...

    async def list_history(
        self,
        ctx: ExecutionContext,
        *,
        owner_agent_id: str,
        thread_id: str,
        limit: int = 20,
    ) -> list[ExternalAgentCheckpointRecord]: ...


class EventBus(Protocol):
    async def publish(self, topic: str, payload: dict[str, Any]) -> None: ...
    def subscribe(self, topic: str) -> AsyncIterator[dict[str, Any]]: ...


class AuditService(Protocol):
    """统一审计落库入口。

    与 EventBus 的差异：审计要 fail-fast / 强一致 / 可查询；EventBus 是
    best-effort pub/sub。两套语义不同，不复用同一通道。
    """

    async def record(self, event: AuditEvent) -> None: ...

    async def query(
        self,
        ctx: ExecutionContext,
        *,
        kinds: tuple[AuditEventKind, ...] = (),
        thread_id: str | None = None,
        limit: int = 100,
    ) -> list[AuditEvent]: ...


class UsageLedgerService(Protocol):
    """Append-only usage ledger.

    Each LLM / tool call writes one immutable UsageRecord.  Aggregation is
    always computed from raw records so corrections and new dimensions can
    be back-filled.

    Phase-1: record + query only.  Quota enforcement (preflight/commit) will
    be added in Phase-2 once the QuotaPolicy model is wired.
    """

    async def record(self, record: UsageRecord) -> None: ...

    async def get_summary(
        self,
        ctx: ExecutionContext,
        *,
        scope: UsageDimension = "session",
        scope_value: str | None = None,
        breakdown_by: UsageDimension | None = None,
    ) -> UsageSummary: ...

    async def list_records(
        self,
        ctx: ExecutionContext,
        *,
        session_id: str | None = None,
        thread_id: str | None = None,
        agent_id: str | None = None,
        workflow_id: str | None = None,
        limit: int = 200,
    ) -> list[UsageRecord]: ...


class EntitlementService(Protocol):
    """Org-level LLM token pool and key-policy check (MVP).

    ``novie_owned_key`` calls go through ``reserve → commit/refund``.
    ``tenant_managed_key`` calls only write usage; ``reserve`` always
    returns ``allow=True`` with ``reservation_id=None``.

    The mock implementation lives in
    ``novie_platform.infra.entitlement.mock``; a real billing/entitlement
    service replaces it without changing this protocol.
    """

    async def get_llm_policy(self, org_id: str) -> LlmKeyPolicy:
        """Return the active LLM key policy for an organisation."""
        ...

    async def get_pool(self, org_id: str) -> OrgTokenPool:
        """Return the current token pool state for display / diagnostics."""
        ...

    async def reserve_tokens(
        self,
        org_id: str,
        estimated_tokens: int,
        request_id: str,
    ) -> EntitlementDecision:
        """Place a hold on the pool for the duration of one LLM call.

        Returns ``allow=False`` when the pool is exhausted (only for
        ``novie_owned_key`` orgs).  Always returns ``allow=True`` for
        ``tenant_managed_key`` (no reservation placed).
        """
        ...

    async def commit_tokens(
        self,
        reservation_id: str,
        actual_tokens: int,
    ) -> None:
        """Finalise the reservation with real token count from LLM response.

        Releases any difference between ``estimated_tokens`` and
        ``actual_tokens`` back to the pool (if actual < estimated).
        No-op when ``reservation_id`` is unknown / already committed.
        """
        ...

    async def refund_tokens(self, reservation_id: str) -> None:
        """Cancel a reservation and release all held tokens.

        Called when an LLM call fails before completing.
        No-op when ``reservation_id`` is unknown.
        """
        ...


class QuotaService(Protocol):
    """Session-level runtime policy 的入口（P0-4 第 1 刀，phase-1: token quota）。

    与 ``PolicyService`` 的差异：
    - ``PolicyService`` 决策 6 类业务场景（hitl_arbitration / sensitive_action /
      ...），输入是结构化 ``PolicyRequest``，规则是静态白名单。
    - ``QuotaService`` 决策的是"已经用掉多少 vs 配额上限"，输入是
      ``ExecutionContext`` + 当前累计的 ``UsageSummary``，规则是 ``QuotaPolicy``
      表，可在运行期 ``configure``。

    Phase-1 只实现 ``check_session_token_quota`` —— 所有 LLM/tool 都已经写
    ``UsageRecord``，session 维度直接 ``usage.get_summary(scope='session')``
    即可拿到累计 token，无需新增数据通路。

    后续会扩展到 cost / request_count、project / org 维度，以及 tool_policy /
    delegation_depth 等其它 session-level runtime policy。Protocol 暂只暴露
    一个方法，便于实现方以最小面积保持向后兼容。
    """

    async def check_session_token_quota(
        self,
        ctx: ExecutionContext,
    ) -> QuotaDecision:
        """根据 ``ctx.session_id`` 累计 token 与已配置的 session-token policy
        决策；无 policy → ``allow=True`` 的 noop decision。"""
        ...

    def configure(self, policy: QuotaPolicy) -> None:
        """运行期注册/替换一条策略；按 ``(scope, scope_value, metric, window)``
        覆盖。``scope_value='*'`` 视为该 scope 的默认策略，命中具体值时被覆盖。
        """
        ...


class SessionTimelineService(Protocol):
    """Session 一等时间线的写入与订阅入口（对应 P0-1 §2.1）。

    与 ``AuditService`` 的差异：
    - ``AuditService`` 是 plan/gate/policy 层的强一致决策账本，kind 词表收敛、
      不暴露 SSE catch-up 语义。
    - ``SessionTimelineService`` 是 UI / 回放 / HITL 视角的时间线，``kind``
      词表故意不收敛，``seq`` 单调用于 ``?since=<seq>`` 续传。

    与 ``EventBus`` 的差异：
    - ``EventBus`` 是 best-effort pub/sub，没有持久化与 catch-up。
    - ``SessionTimelineService`` 的 ``record`` 必须 append-and-broadcast，
      ``subscribe`` 必须先回放 `since` 之后的历史，再切换到 live tail，
      保证客户端断线重连看到完整序列。
    """

    async def record(self, event: SessionEvent) -> SessionEvent:
        """追加一条事件，分配 ``seq`` 后返回写入态对象。"""
        ...

    async def get_session(
        self, ctx: ExecutionContext, session_id: str
    ) -> Session | None: ...

    async def list_sessions(
        self,
        ctx: ExecutionContext,
        *,
        limit: int = 50,
    ) -> list[Session]: ...

    async def list_project_sessions(
        self,
        ctx: ExecutionContext,
        project_id: str,
        *,
        limit: int = 50,
    ) -> list[ProjectSessionSummary]: ...

    async def set_session_title(
        self,
        ctx: ExecutionContext,
        session_id: str,
        title: str,
    ) -> None: ...

    async def list_events(
        self,
        ctx: ExecutionContext,
        session_id: str,
        *,
        since: int = 0,
        limit: int = 200,
    ) -> SessionEventsPage: ...

    def subscribe(
        self,
        ctx: ExecutionContext,
        session_id: str,
        *,
        since: int = 0,
    ) -> AsyncIterator[SessionEvent]:
        """先回放 ``since`` 之后的历史事件，然后无限 yield 后续 live 事件。

        消费方负责自行 ``break`` / 断开 SSE 连接。实现方应在调用方取消
        async iterator 时释放订阅资源（避免 in-memory 实现长跑后泄漏 Queue）。
        """
        ...


class OrchestrationEventStoreService(Protocol):
    """OrchestrationEventStore 的 Protocol 视图，供 PlatformServices 收口。

    与 SessionTimelineService 的区别：
    - SessionTimelineService 服务 UI / SSE 时间线（展示语义）。
    - OrchestrationEventStoreService 服务 Change-Aware Orchestrator（控制面语义）；
      索引维度不同（plan_id 而非 session_id），并支持按主体查询。
    """

    async def append(self, ctx: ExecutionContext, event: ChangeEvent) -> ChangeEvent: ...

    async def list_by_plan(
        self,
        ctx: ExecutionContext,
        plan_id: str,
        since_seq: int = 0,
    ) -> list[ChangeEvent]: ...

    async def get_latest_seq(self, ctx: ExecutionContext, plan_id: str) -> int: ...


@dataclass(frozen=True, slots=True)
class PlatformServices:
    """Injected platform service bundle for agents (protocols only).

    ``wiki`` is retained only as a historical field name for compatibility.
    New code should use ``services.knowledge`` and think in terms of the
    independent Knowledge service boundary.
    """

    # Historical field name retained for compatibility with older integrations.
    wiki: KnowledgeService
    policy: PolicyService
    review: ReviewService
    checkpoint: CheckpointService
    time_travel: TimeTravelService
    events: EventBus
    audit: AuditService
    usage: UsageLedgerService
    quota: QuotaService
    sessions: SessionTimelineService | None = None
    # Change-Aware Orchestrator 的事件存储。可选 —— 注入即生效，缺失时静默跳过。
    orchestration_events: OrchestrationEventStoreService | None = None
    # Artifact index (PG-backed in production). Optional until wired by composition root.
    artifacts: ArtifactIndexReader | None = None
    external_agent_checkpoints: ExternalAgentCheckpointService | None = None

    # Org-level LLM token pool & key-policy gate. Optional so existing
    # deployments keep working; when None, platform.llm.* calls are allowed
    # but not token-pool-gated (behaves like tenant_managed_key).
    entitlement: EntitlementService | None = None

    @property
    def knowledge(self) -> KnowledgeService:
        """Preferred semantic name for the independent Knowledge service boundary."""
        return self.wiki
