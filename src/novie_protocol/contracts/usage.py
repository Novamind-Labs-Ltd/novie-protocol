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
        raw_usage_metadata: dict[str, Any] | None = None,
        tags: dict[str, str] | None = None,
    ) -> "UsageRecord":
        return cls(
            record_id=f"usg-{uuid.uuid4().hex[:16]}",
            recorded_at=datetime.now(timezone.utc),
            ctx=UsageCtxSummary.from_ctx(ctx),
            source_kind=source_kind,
            agent_id=agent_id,
            step_id=step_id,
            workflow_id=workflow_id or ctx.workflow_id,
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
