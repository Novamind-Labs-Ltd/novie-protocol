"""Universal capability invocation contracts (UNIVERSAL_CAPABILITY W4).

Every capability call — internal platform function, external A2A
agent, MCP tool, OpenAPI op, Temporal workflow — runs through
``CapabilityInvocationService``. This module defines the
**request/result envelope** and the **middleware step contract**;
the service implementation lives under
``novie_platform.runtime.capability_invocation``.

Design intent:
- One pipeline so the discovery/resource/audit/policy work in
  W1-W3 + W7 cannot be silently bypassed by a new capability source.
- Deterministic ordering: every call goes through the same 11
  middleware steps in the same order.
- Structured ``CapabilityInvocationResult`` so Reception / Planner /
  run-detail UI can read status, output, events, artifacts, usage,
  audit id, and trace id without reaching into provider internals.
- Dry-run / preview path explicit on the request so callers cannot
  accidentally execute a write while debugging.
"""
# ruff: noqa: RUF001, RUF002, RUF003
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from .capability import CapabilityErrorCode
from .resource import ResourceRef
from .run_correlation import RunCorrelation


InvocationMode = Literal["dry_run", "execute", "plan_eval"]
"""How the request should be processed.

- ``dry_run``  — middleware runs, the provider returns a preview
  envelope; no side effects.
- ``execute``  — full execution, side effects allowed if policy
  permits.
- ``plan_eval`` — Planner-only mode: the contract is checked
  against the input but the provider is not called. Used during
  plan compilation to validate ``consumes_resources`` /
  ``produces_resources`` slot wiring.
"""

InvocationStatus = Literal[
    "ok",
    "needs_confirmation",
    "denied",
    "error",
    "dry_run_only",
]
"""Terminal status the service returns to callers.

- ``ok`` — provider returned a successful execute or preview
  result.
- ``needs_confirmation`` — write capability ran in ``execute`` mode
  but policy demands a preview-and-confirm cycle. The result
  envelope carries the preview output.
- ``denied`` — middleware denied the call (auth / binding /
  credential / policy). ``error_code`` carries the specific
  ``CapabilityErrorCode``.
- ``error`` — provider failed. ``error_code`` carries the upstream
  classification.
- ``dry_run_only`` — caller asked for ``dry_run``; provider's
  preview envelope is in ``output`` and no side effects landed.
"""

MiddlewareStep = Literal[
    "auth",
    "tenant_boundary",
    "actor_resource_auth",
    "policy_gate",
    "binding",
    "credential_binding",
    "quota",
    "context_inject",
    "dry_run_preview",
    "execution",
    "usage_record",
    "audit",
    "trace",
]
"""Closed enum of the deterministic middleware steps. Order matches
the ``DEFAULT_MIDDLEWARE_CHAIN`` constant; deviations are the
service's prerogative but each named step can only appear once.

``context_inject`` (added §1.1 Slice 2, 2026-05-10) folds in the
implicit-arg injection step that previously lived only in
``PlatformCapabilityRegistry.ainvoke``. Position is post-quota /
pre-dry-run so policy decisions cannot depend on injected args (those
are derived from caller context, not policy input).

``binding`` (added §1.1 Slice 7-B, 2026-05-10) enforces tenant /
workspace capability bindings — the catalog-level "is this capability
enabled here?" check that previously lived only in the registry. Sits
between ``policy_gate`` (request-shape policy) and
``credential_binding`` (per-credential scope) because a missing
catalog binding should fail before the platform mints credentials it
won't use. Distinct from ``policy_gate`` because policy is
request-scoped while binding is config-scoped (tenant has/has-not
enabled this capability)."""

DEFAULT_MIDDLEWARE_CHAIN: tuple[MiddlewareStep, ...] = (
    "auth",
    "tenant_boundary",
    "actor_resource_auth",
    "policy_gate",
    "binding",
    "credential_binding",
    "quota",
    "context_inject",
    "dry_run_preview",
    "execution",
    "usage_record",
    "audit",
    "trace",
)


# ── Request envelope ──────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class CorrelationIds:
    """Correlation identifiers wired into every audit / trace /
    usage record so operators can pivot from any one of them.

    All fields are optional — fresh chat-turn invocations may have
    no plan/run/step yet, while planner-driven invocations always do.
    """

    plan_id: str = ""
    run_id: str = ""
    step_id: str = ""
    parent_invocation_id: str = ""
    """When one capability invocation triggers another (e.g.
    Planner's plan-eval invokes a query capability to validate a
    slot), the parent is recorded here."""


@dataclass(frozen=True, slots=True)
class CapabilityInvocationRequest:
    """The unit of work the invocation service processes.

    The service does not mutate this dataclass; middleware stages
    accumulate state on a separate context object. That keeps the
    request immutable across retries and makes audit trivial.
    """

    capability_id: str
    provider_id: str
    mode: InvocationMode
    """``dry_run`` / ``execute`` / ``plan_eval``. Callers must set
    this explicitly — the service never defaults to ``execute``."""
    inputs: dict[str, Any] = field(default_factory=dict)
    """Structured arguments matching the capability's ``input_schema``."""
    resource_refs: tuple[ResourceRef, ...] = ()
    """Resource references the capability consumes / produces. The
    invocation middleware re-authorises each ref via the W3 graph."""
    correlation: CorrelationIds = field(default_factory=CorrelationIds)
    run_correlation: RunCorrelation | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    """Free-form caller hints (UI selection state, planner
    re-planning context, etc.). Never carries secrets — credentials
    flow through the broker, not this dict."""

    def __post_init__(self) -> None:
        if not isinstance(self.resource_refs, tuple):
            object.__setattr__(self, "resource_refs", tuple(self.resource_refs))


# ── Result envelope ──────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class MiddlewareTrace:
    """One step's verdict on a single invocation.

    Always present (even for skipped steps) so audit + run-detail
    can render a complete pipeline view. ``"skipped"`` covers steps
    that were not applicable (e.g. ``credential_binding`` when the
    capability has no ``credential_refs``).
    """

    step: MiddlewareStep
    status: Literal["pending", "ok", "skipped", "denied", "error"]
    duration_ms: float = 0.0
    detail: str = ""
    """Free-form human-readable note. Populated for non-ok statuses
    so operators don't have to dig into structured payloads."""

    error_code: CapabilityErrorCode | None = None
    """Structured error classification when ``status`` is ``denied`` or
    ``error``. Propagated from :class:`MiddlewareDecision.error_code`
    so the service does not need to heuristically re-derive it from
    ``detail``. Added §1.1 Slice 2 (2026-05-10)."""

    metadata: dict[str, Any] = field(default_factory=dict)
    """Step-specific structured detail (e.g. ``ContextInjectMiddleware``
    records ``{"injected": [...], "accepted": [...], "missing": [...],
    "resolution": "auto"}``). Distinct from :attr:`detail` (free-form
    string for human display); ``metadata`` survives translation into
    registry-shaped :class:`CapabilityMiddlewareRecord` envelopes used
    by the run-detail UI. Added §1.1 Slice 7-fixup (2026-05-10)."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "step": self.step,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "detail": self.detail,
            "error_code": self.error_code,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class InvocationUsage:
    """Usage / cost record for one invocation.

    Mirrors the existing ``UsageLedger`` entry shape so the W4
    follow-up wiring can write directly into it without translation.
    """

    tokens_in: int = 0
    tokens_out: int = 0
    usd_cost: float = 0.0
    duration_ms: float = 0.0
    provider_units: dict[str, float] = field(default_factory=dict)
    """Provider-specific units (e.g. GitHub API calls, Temporal
    activity time, Redis ops)."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "usd_cost": self.usd_cost,
            "duration_ms": self.duration_ms,
            "provider_units": dict(self.provider_units),
        }


@dataclass(frozen=True, slots=True)
class InvocationEvent:
    """Single event emitted during the invocation (progress chunks,
    tool-call breadcrumbs, intermediate artifacts).

    These bubble up to the session timeline so run detail / chat UI
    can render them. Streaming providers fire one ``InvocationEvent``
    per chunk; sync providers may emit none.
    """

    kind: str
    """e.g. ``"progress"``, ``"tool_call"``, ``"artifact"``, ``"chunk"``."""
    occurred_at: str = ""
    """ISO timestamp; service fills if blank."""
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "occurred_at": self.occurred_at,
            "payload": dict(self.payload),
        }


@dataclass(frozen=True, slots=True)
class CapabilityInvocationResult:
    """The single envelope every caller (Reception / Planner /
    run-detail / HTTP API) reads from.

    Stable shape across all six provider types; provider-specific
    payload lives in ``output`` (and ``preview`` when ``mode=dry_run``).
    """

    invocation_id: str
    """Service-assigned UUID. Stable for retries (same id) and
    correlation (audit/trace records carry it)."""
    capability_id: str
    provider_id: str
    mode: InvocationMode
    status: InvocationStatus
    output: dict[str, Any] = field(default_factory=dict)
    """Provider's response payload when ``status=ok``. Schema must
    match the capability's ``output_schema``."""
    preview: dict[str, Any] = field(default_factory=dict)
    """Populated when ``status=dry_run_only`` or
    ``status=needs_confirmation``. Provider-rendered preview of the
    side effects the execute call would produce."""
    events: tuple[InvocationEvent, ...] = ()
    """Time-ordered events from the invocation."""
    artifacts: tuple[ResourceRef, ...] = ()
    """Resources the invocation produced. Reception / run detail
    surface these to the user."""
    usage: InvocationUsage = field(default_factory=InvocationUsage)
    audit_id: str = ""
    """Reference into the platform's audit store. Empty when audit
    middleware was skipped (e.g. ``plan_eval`` mode)."""
    trace_id: str = ""
    """Reference into the platform's trace store / Langfuse."""
    run_correlation: RunCorrelation | None = None
    error_code: CapabilityErrorCode | None = None
    error_message: str = ""
    middleware_trace: tuple[MiddlewareTrace, ...] = ()
    """Per-step pipeline view. Always populated with one record per
    step the service ran (including skipped) so audit can replay
    the chain."""

    def __post_init__(self) -> None:
        if not isinstance(self.events, tuple):
            object.__setattr__(self, "events", tuple(self.events))
        if not isinstance(self.artifacts, tuple):
            object.__setattr__(self, "artifacts", tuple(self.artifacts))
        if not isinstance(self.middleware_trace, tuple):
            object.__setattr__(
                self, "middleware_trace", tuple(self.middleware_trace),
            )

    @property
    def is_terminal(self) -> bool:
        """True for any status the caller cannot retry without
        a new request — i.e. denied / error / ok / dry_run_only.
        ``needs_confirmation`` is *not* terminal: the same request
        can re-execute after the user confirms."""
        return self.status in ("ok", "denied", "error", "dry_run_only")

    @property
    def is_success(self) -> bool:
        return self.status == "ok"

    def to_dict(self) -> dict[str, Any]:
        return {
            "invocation_id": self.invocation_id,
            "capability_id": self.capability_id,
            "provider_id": self.provider_id,
            "mode": self.mode,
            "status": self.status,
            "output": dict(self.output),
            "preview": dict(self.preview),
            "events": [e.to_dict() for e in self.events],
            "artifacts": [a.to_dict() for a in self.artifacts],
            "usage": self.usage.to_dict(),
            "audit_id": self.audit_id,
            "trace_id": self.trace_id,
            "run_correlation": (
                self.run_correlation.to_dict() if self.run_correlation else None
            ),
            "error_code": self.error_code,
            "error_message": self.error_message,
            "middleware_trace": [t.to_dict() for t in self.middleware_trace],
        }
