"""Workflow live-stream envelope — the W2 contract for the platform-owned SSE
endpoint that powers Run Detail and CLI live-stream subscribers.

Design intent (per ``docs/issues/PLATFORM_OWNED_RUN_LIVE_SSE_BACKLOG.md``):

- The browser / CLI subscribes to **platform truth**, not raw expert-agent
  transport. ``WorkflowStreamEvent`` is the wire-format projection of
  platform-owned event sources (``SessionTimelineService``, workflow status,
  usage ledger) onto a workflow-scoped lens.
- ``kind`` is a *closed* enum — a UI subscriber can render every category
  without reading raw ``source``/``kind`` tuples from ``SessionEvent``.
- ``seq`` reuses the underlying ``SessionEvent.seq`` so SSE ``Last-Event-ID``
  / ``?since=`` resume semantics fall out for free.
- ``payload`` keeps a per-kind sub-schema; we deliberately do not over-spec
  it here so that adding a new sub-field (e.g. a new diagnostics counter)
  does not require a contract version bump.

Why a closed ``kind`` enum here vs. ``SessionEvent.kind`` being open:

``SessionEvent`` is an *internal* timeline that gathers chat / planning /
dispatch / gate / callback / agent traffic into one append-only ledger;
locking its kind would force every new subsystem to bump the protocol.
``WorkflowStreamEvent`` is the *external* contract a UI subscribes to;
keeping its categories closed is what lets clients render reliably without
spelunking arbitrary kinds.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from .session import SessionEvent

WorkflowStreamEventKind = Literal[
    "run_status",
    "step_status",
    "stream_delta",
    "usage_update",
    "review_state",
    "terminal_output_ready",
    "recoverability_update",
]
"""Closed enum of categories a UI subscriber must handle.

- ``run_status``               — overall workflow lifecycle (``plan_complete``,
  ``plan_error``, ``plan_cancelled``)
- ``step_status``              — per-step lifecycle (start / complete / failed /
  waiting)
- ``stream_delta``             — incremental ``text_delta`` from
  ``agent.stream_content`` or ``agent.stream_start``
- ``usage_update``             — token / cost progression from
  ``agent.event.token_usage``
- ``review_state``             — HITL gate state changes
- ``terminal_output_ready``    — terminal step output / final report ready for
  ``GET /workflows/{plan_id}/status`` or ``/ui/tasks/{plan_id}/output``
- ``recoverability_update``    — degraded / stalled / recovery-recommended
  signals (e.g. ``agent.stream_complete`` carrying diagnostics that imply
  silent agent or capability denial)
"""


@dataclass(frozen=True, slots=True)
class WorkflowStreamEvent:
    """One envelope on the platform-owned workflow live stream.

    The full SSE wire format is::

        id: <seq>\\n
        event: <kind>\\n
        data: <json-of-this-dataclass>\\n
        \\n

    so that a browser ``EventSource`` can dispatch on ``kind`` and resume
    via ``Last-Event-ID`` without any custom client logic.
    """

    seq: int
    """Monotonic per-(session, plan) sequence id reused from
    ``SessionEvent.seq``. Strictly increasing so SSE catch-up via
    ``?since=<seq>`` is well-defined."""

    event_id: str
    """Globally unique event id, mirrors ``SessionEvent.event_id``. Useful for
    audit / dedup; not used for ordering."""

    occurred_at: datetime
    """UTC datetime when the underlying source recorded the event."""

    plan_id: str
    """The workflow / plan id this stream is scoped to."""

    session_id: str
    """The session that owns the plan (for cross-stream correlation; the
    subscriber already knows it because they pass it as a query param)."""

    kind: WorkflowStreamEventKind

    summary: str = ""
    """One-line human-readable summary, copied from the source event when
    available. Safe to show in UI without escaping."""

    step_id: str | None = None
    """Step the event applies to. ``None`` for run-level events."""

    tenant_id: str = ""
    workspace_id: str = ""

    payload: dict[str, Any] = field(default_factory=dict)
    """Kind-specific structured data. Sub-schema by kind:

    - ``run_status``               — ``{"status": "completed"|"failed"|"cancelled"|...}``
    - ``step_status``              — ``{"status": "running"|"completed"|"failed"|"waiting", "agent_id": str}``
    - ``stream_delta``             — ``{"text_delta", "stream_seq", "offset_start",
      "offset_end", "preview", "chars_total", "chars_in_chunk", "final"}``
      (mirrors ``agent.stream_content`` payload)
    - ``usage_update``             — ``{"usage": {"input_tokens", "output_tokens",
      "total_tokens", ...}}`` (normalised by ``usage_capture``)
    - ``review_state``             — ``{"gate_id", "status", "decision"?, ...}``
    - ``terminal_output_ready``    — ``{"step_id", "output_field", "preview"}``
    - ``recoverability_update``    — ``{"diagnostics": {...}, "reason"?, ...}``
    """

    metadata: dict[str, Any] = field(default_factory=dict)
    """Diagnostic/correlation fields copied verbatim from the underlying
    ``SessionEvent.metadata``. Not part of the rendering contract."""


# ── Projection ──────────────────────────────────────────────────────────────


# (source_or_*, kind) → WorkflowStreamEventKind
# ``*`` means "any source" (some kinds like ``agent.stream_content`` come from
# different sources depending on the producer path).
_PLAN_LIFECYCLE_KINDS: frozenset[str] = frozenset({
    "plan_complete",
    "plan_error",
    "plan_cancelled",
    "workflow_complete",
    "workflow_failed",
    "workflow_cancelled",
})

_STEP_LIFECYCLE_KINDS: frozenset[str] = frozenset({
    "step_start",
    "step_started",
    "step_complete",
    "step_completed",
    "step_failed",
    "step_waiting",
    "step_skipped",
})

_REVIEW_KINDS: frozenset[str] = frozenset({
    "gate_pending",
    "gate_decided",
    "gate_resolved",
    "review_pending",
    "review_decided",
    # W7 — decision-gate lifecycle. Folded into ``review_state`` (the W2
    # closed enum kind for HITL) so platform UI can render decision
    # gates through the same SSE channel as review gates. Payload
    # carries ``gate_class="decision_gate"`` so the UI can branch
    # rendering without a new W2 enum entry.
    "decision_gate_raised",
    "decision_gate_resolved",
    "decision_gate_skipped",
})

_RECOVERABILITY_KINDS: frozenset[str] = frozenset({
    "recovery_recommended",
    "stalled",
    "agent_unavailable",
    "capability_denied",
})

# W8 — boundary-safety allowlist for the ``WorkflowStreamEvent.metadata``
# field. ``SessionEvent.metadata`` is documented as a *diagnostic* surface and
# producers are free to attach arbitrary debug context to it (raw envelope
# fields, capability binding hints, internal trace ids). The workflow stream
# is *public-facing*, so the projection must only forward metadata keys that
# are already considered public by other parts of the contract:
#
# - ``plan_id`` — public (``/workflows/{plan_id}/status`` accepts it as path)
# - ``step_id`` — public (returned in ``execution_facts.steps[]``)
# - ``agent_id`` — public (returned in ``execution_facts.steps[].agent_id``)
#
# Anything else (e.g. internal trace ids, agent endpoint URLs, capability
# binding tokens, credential lease handles) is stripped at the projection
# boundary so a future producer that adds debug context to ``metadata``
# cannot accidentally leak it onto the public live stream.
_PUBLIC_METADATA_KEYS: frozenset[str] = frozenset({
    "plan_id",
    "step_id",
    "agent_id",
})


def project_session_event_kind(
    source: str,
    kind: str,
) -> WorkflowStreamEventKind | None:
    """Map a ``SessionEvent`` ``(source, kind)`` tuple to the closed W2 enum.

    Returns ``None`` for events that should not surface on the workflow
    live stream (e.g. internal chat / reception traces with no plan
    context). Kept as a pure function so unit tests can lock the
    projection rules without reaching into routing code.
    """
    if kind in _PLAN_LIFECYCLE_KINDS:
        return "run_status"
    if kind in _STEP_LIFECYCLE_KINDS:
        return "step_status"
    if kind in _REVIEW_KINDS:
        return "review_state"
    if kind in _RECOVERABILITY_KINDS:
        return "recoverability_update"
    if kind == "agent.event.phase_changed" or kind == "agent.event.thinking":
        return "step_status"
    if kind == "agent.stream_content" or kind == "agent.stream_start":
        return "stream_delta"
    if kind == "agent.event.token_usage" or kind == "agent.event.status_changed":
        # ``status_changed`` only counts as usage when its payload normalised
        # form indicates ``agent_event_kind=token_usage``; the router checks
        # the payload, this mapping is the kind-only fast path.
        return "usage_update"
    if kind == "agent.stream_complete":
        # The terminating event is treated as a recoverability signal because
        # its diagnostics block (W8) is exactly what operators need to triage
        # silent / degraded agents. A pure "happy completion" is also covered
        # by the run_status / step_status events that fire alongside it.
        return "recoverability_update"
    if kind == "terminal_output_ready":
        return "terminal_output_ready"
    return None


def project_workflow_stream_event(
    event: SessionEvent,
    *,
    plan_id: str,
) -> WorkflowStreamEvent | None:
    """Project one ``SessionEvent`` into a workflow-scoped ``WorkflowStreamEvent``.

    Returns ``None`` when:

    - The event's ``(source, kind)`` tuple is not recognised as a workflow
      event (e.g. internal chat trace), so the W2 envelope's closed enum
      cannot describe it.
    - The event's payload carries an explicit ``plan_id`` that does not match
      the requested ``plan_id``. Events without a ``plan_id`` in their payload
      are kept on the assumption that session-level events (e.g. session
      lifecycle, gate state) belong to the only plan currently active in the
      session — a multi-plan session may need richer filtering later, but for
      W1+W2 single-plan-per-session is the dominant case.

    The output reuses ``SessionEvent.seq`` so SSE ``Last-Event-ID``-based
    catch-up still works without an additional cursor mapping.
    """
    payload = event.payload or {}
    event_plan_id = str(payload.get("plan_id") or "").strip()
    if event_plan_id and event_plan_id != plan_id:
        return None

    projected_kind = project_session_event_kind(str(event.source), event.kind)
    if projected_kind == "usage_update" and event.kind == "agent.event.status_changed":
        agent_event_kind = str(payload.get("agent_event_kind") or "").strip()
        usage_block = payload.get("usage")
        if agent_event_kind != "token_usage" and not isinstance(usage_block, dict):
            return None
    if projected_kind is None:
        return None

    step_id_raw = payload.get("step_id")
    step_id = str(step_id_raw).strip() if step_id_raw else None

    # W8 boundary: filter metadata through the public allowlist so debug-only
    # keys from ``SessionEvent.metadata`` cannot bleed onto the public stream.
    safe_metadata = {
        k: v
        for k, v in (event.metadata or {}).items()
        if k in _PUBLIC_METADATA_KEYS
    }

    return WorkflowStreamEvent(
        seq=event.seq,
        event_id=event.event_id,
        occurred_at=event.occurred_at,
        plan_id=plan_id,
        session_id=event.session_id,
        kind=projected_kind,
        summary=event.summary,
        step_id=step_id or None,
        tenant_id=event.tenant_id,
        workspace_id=event.workspace_id,
        payload=dict(payload),
        metadata=safe_metadata,
    )
