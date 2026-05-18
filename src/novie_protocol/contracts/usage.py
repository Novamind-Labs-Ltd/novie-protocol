"""Usage ledger contracts.

Each LLM call, tool invocation, or agent step writes one immutable
UsageRecord. Aggregation always recomputes from the raw ledger so that
future cost corrections and new dimensions can be back-filled.

Attribution keys are lifted directly from ExecutionContext, matching the
same indexed fields used by AuditCtxSummary.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

from .context import ExecutionContext

UsageSourceKind = Literal[
    "reception",   # Reception agent LLM call
    "planner",     # Planner strategy LLM call
    "agent",       # Expert agent LLM call (analyst, pm, …)
    "tool",        # Tool invocation inside an agent
]

UsageAnchorKind = Literal[
    "plan_step",
    "planner_phase",
    "authoring",
    "reception_turn",
    "capability_query",
    "system",
]

UsageLeafKind = Literal[
    "llm",
    "tool",
    "a2a",
    "storage",
    "compute",
    "network",
]

UsageDimension = Literal[
    "org",
    "project",
    "user",
    "session",
    "thread",
    "agent",
    "step",
    "model",
]


@dataclass(frozen=True, slots=True)
class UsageCtxSummary:
    """Thin attribution snapshot extracted from ExecutionContext."""

    tenant_id: str       # maps to org
    workspace_id: str    # maps to project
    principal_id: str    # maps to user
    session_id: str
    thread_id: str
    request_id: str

    @classmethod
    def from_ctx(cls, ctx: ExecutionContext) -> "UsageCtxSummary":
        _require_non_empty_usage_context(ctx)
        return cls(
            tenant_id=ctx.tenant.tenant_id,
            workspace_id=ctx.tenant.workspace_id,
            principal_id=ctx.identity.principal_id,
            session_id=ctx.session_id,
            thread_id=ctx.thread_id,
            request_id=ctx.request_id,
        )


@dataclass(frozen=True, slots=True)
class UsageRecord:
    """Single immutable usage record written after each LLM/tool call."""

    record_id: str
    recorded_at: datetime

    # Attribution
    ctx: UsageCtxSummary

    # Execution identity
    source_kind: UsageSourceKind
    agent_id: str | None              # populated for agent/tool calls
    step_id: str | None               # populated for dispatch steps
    workflow_id: str | None

    # Model identity
    provider: str                     # e.g. "anthropic", "openai"
    model: str                        # e.g. "claude-sonnet-4.5"

    # Token metrics (None = provider did not report)
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None

    # Cost (computed by PricingResolver, may be None if no price table entry)
    cost_usd: float | None

    # ADR-025 attribution anchor. ``source_kind`` remains as the legacy alias
    # while callers migrate to anchor/leaf terminology.
    anchor_kind: UsageAnchorKind = "system"
    anchor_id: str = ""
    leaf_kind: UsageLeafKind = "llm"
    quantity: float = 1.0
    quantity_unit: str = "request"

    # Other metrics
    request_count: int = 1
    tool_call_count: int = 0
    latency_ms: float | None = None

    # Raw provider usage payload for forward-compatibility
    raw_usage_metadata: dict[str, Any] = field(default_factory=dict)

    # Optional free-form tags (e.g. analysis_phase, template_id)
    tags: dict[str, str] = field(default_factory=dict)

    @classmethod
    def new(
        cls,
        ctx: ExecutionContext,
        *,
        source_kind: UsageSourceKind,
        provider: str,
        model: str,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        total_tokens: int | None = None,
        cost_usd: float | None = None,
        request_count: int = 1,
        tool_call_count: int = 0,
        latency_ms: float | None = None,
        agent_id: str | None = None,
        step_id: str | None = None,
        workflow_id: str | None = None,
        anchor_kind: UsageAnchorKind | None = None,
        anchor_id: str | None = None,
        leaf_kind: UsageLeafKind = "llm",
        quantity: float | None = None,
        quantity_unit: str | None = None,
        raw_usage_metadata: dict[str, Any] | None = None,
        tags: dict[str, str] | None = None,
    ) -> "UsageRecord":
        resolved_workflow_id = workflow_id or ctx.workflow_id
        resolved_anchor_kind, resolved_anchor_id = _default_anchor(
            source_kind=source_kind,
            step_id=step_id,
            agent_id=agent_id,
            workflow_id=resolved_workflow_id,
            request_id=ctx.request_id,
        )
        resolved_quantity, resolved_quantity_unit = _default_quantity(
            total_tokens=total_tokens,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            request_count=request_count,
            quantity=quantity,
            quantity_unit=quantity_unit,
        )
        return cls(
            record_id=f"usg-{uuid.uuid4().hex[:16]}",
            recorded_at=datetime.now(timezone.utc),
            ctx=UsageCtxSummary.from_ctx(ctx),
            source_kind=source_kind,
            agent_id=agent_id,
            step_id=step_id,
            workflow_id=resolved_workflow_id,
            anchor_kind=anchor_kind or resolved_anchor_kind,
            anchor_id=anchor_id or resolved_anchor_id,
            leaf_kind=leaf_kind,
            quantity=resolved_quantity,
            quantity_unit=resolved_quantity_unit,
            provider=provider,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            cost_usd=cost_usd,
            request_count=request_count,
            tool_call_count=tool_call_count,
            latency_ms=latency_ms,
            raw_usage_metadata=dict(raw_usage_metadata or {}),
            tags=dict(tags or {}),
        )


def _default_anchor(
    *,
    source_kind: UsageSourceKind,
    step_id: str | None,
    agent_id: str | None,
    workflow_id: str | None,
    request_id: str,
) -> tuple[UsageAnchorKind, str]:
    if step_id:
        return "plan_step", step_id
    if source_kind == "planner":
        return "planner_phase", workflow_id or request_id
    if source_kind == "reception":
        return "reception_turn", request_id
    if source_kind == "tool":
        return "capability_query", agent_id or workflow_id or request_id
    if workflow_id:
        return "authoring", workflow_id
    return "system", request_id


def _require_non_empty_usage_context(ctx: ExecutionContext) -> None:
    missing: list[str] = []
    if not ctx.tenant.tenant_id.strip():
        missing.append("tenant_id")
    if not ctx.tenant.workspace_id.strip():
        missing.append("workspace_id")
    if not ctx.identity.principal_id.strip():
        missing.append("principal_id")
    if not ctx.session_id.strip():
        missing.append("session_id")
    if missing:
        raise ValueError(
            "usage records require non-empty context fields: "
            + ", ".join(missing)
        )


def _default_quantity(
    *,
    total_tokens: int | None,
    input_tokens: int | None,
    output_tokens: int | None,
    request_count: int,
    quantity: float | None,
    quantity_unit: str | None,
) -> tuple[float, str]:
    if quantity is not None:
        return float(quantity), quantity_unit or "unit"
    token_total = total_tokens
    if token_total is None and (input_tokens is not None or output_tokens is not None):
        token_total = (input_tokens or 0) + (output_tokens or 0)
    if token_total is not None:
        return float(token_total), quantity_unit or "tokens"
    return float(request_count), quantity_unit or "request"


@dataclass(frozen=True, slots=True)
class UsageSummary:
    """Aggregated usage metrics across a given scope."""

    # What this summary covers
    scope: UsageDimension
    scope_value: str           # e.g. tenant_id, session_id, model name

    # Token totals (None = no records with token data in this scope)
    input_tokens: int
    output_tokens: int
    total_tokens: int

    # Cost total (None = no pricing data available)
    cost_usd: float

    # Count metrics
    request_count: int
    tool_call_count: int
    record_count: int

    # Breakdown by a secondary dimension (optional, populated on demand)
    breakdown: dict[str, "UsageSummary"] = field(default_factory=dict)


QuotaMetric = Literal["tokens", "cost_usd", "request_count", "tool_call_count"]
QuotaWindow = Literal["session", "daily", "monthly", "rolling_30d"]
QuotaAction = Literal["observe", "warn", "block"]


@dataclass(frozen=True, slots=True)
class QuotaPolicy:
    """Quota definition for a given scope.

    Phase-1 (P0-4 第 1 刀): only ``scope='session'`` + ``metric='tokens'`` +
    ``window='session'`` is enforced; other dimensions are accepted by the
    contract but not yet evaluated. ``action='observe'`` is the safe default
    so legacy deployments without an explicit policy keep running.
    """

    scope: UsageDimension
    scope_value: str
    metric: QuotaMetric
    window: QuotaWindow

    limit: float                              # hard cap value
    warn_at: float | None = None             # warn threshold (< limit)
    action: QuotaAction = "observe"


@dataclass(frozen=True, slots=True)
class QuotaDecision:
    """Result of a single quota preflight check.

    Returned by ``QuotaService.check_*`` methods; mirrors ``PolicyDecision``
    in shape so dispatch / agent code can treat them with the same flow
    (record audit, optionally block, optionally warn the caller).

    ``policy`` is ``None`` only when no policy is configured for the scope
    being checked — in that case ``allow=True`` and the call is a noop.
    """

    allow: bool
    policy: QuotaPolicy | None
    current_value: float                      # observed usage at check time
    limit: float | None                       # mirrors policy.limit when policy is set
    warn: bool = False                        # current_value >= warn_at < limit
    reason: str | None = None                 # set when allow=False or warn=True
