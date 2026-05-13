"""Reception resolution envelope (UNIVERSAL_CAPABILITY W5 step 3).

Structured Reception output. Reception emits a ``ReceptionResolution``
when it has classified the user message into actionable structured
data. Downstream consumers (Planner grounding envelope, HITL preview
UI, capability invocation pipeline) read from this envelope instead
of the unstructured raw user message.

The envelope is the W5 acceptance bullet's
"structured reception resolution":

- ``intent_type``
- ``resource_refs`` — canonical refs Reception resolved through W3
- ``action_candidates`` — verbs Reception inferred (move_to_lane /
  preview / invoke / search / ...)
- ``capability_candidates`` — capability ids returned by W2 discovery
- ``unresolved_hints`` — free-form hints Reception couldn't resolve
- ``diagnostics`` — operator-only explain text

The shape is intentionally thin. Reception's per-task LLM may
populate richer details on ``metadata``, but the named fields are
the stable contract Planner / preview UI / invocation layer all
consume.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from .resource import ResourceRef

ReceptionIntentType = Literal[
    "issue_action",
    "run_action",
    "capability_query",
    "free_form_task",
    "clarification_needed",
    "unknown",
]
"""High-level intent classification.

- ``issue_action`` — user wants to act on a PMS issue
  (move / comment / preview)
- ``run_action`` — user wants to act on a run / workflow
  (retry / repair / inspect)
- ``capability_query`` — user is searching the capability catalog
- ``free_form_task`` — user wants a TaskBrief / Planner workflow
  (multi-step / open-ended)
- ``clarification_needed`` — Reception couldn't pick one resource
  / capability and needs to ask the user
- ``unknown`` — Reception couldn't classify (treat as clarification
  candidate)
"""


@dataclass(frozen=True, slots=True)
class ReceptionResolution:
    """Structured Reception output.

    All fields except ``intent_type`` are optional so Reception can
    emit a partial resolution (e.g. ``intent_type="issue_action"``
    with only ``resource_refs`` filled when the user clearly named
    a single issue but didn't pick a verb).
    """

    intent_type: ReceptionIntentType
    resource_refs: tuple[ResourceRef, ...] = ()
    """Canonical refs Reception resolved through W3 ResourceGraph.
    Order matters when there's a primary + secondary resource
    (e.g. moving issue NOV-1 → lane Todo: ``resource_refs[0]`` is
    the issue, ``resource_refs[1]`` is implicit "the Todo lane")."""

    action_candidates: tuple[str, ...] = ()
    """Action verbs Reception inferred from the message
    (``move_to_lane`` / ``preview`` / ``invoke`` / ``search`` /
    ``cancel``). Free-form today; may become a Literal in a future
    slice once verbs stabilise."""

    capability_candidates: tuple[str, ...] = ()
    """Capability ids returned by W2 discovery search, ranked by
    relevance to the intent. Empty when ``intent_type`` is
    ``free_form_task`` (Planner does its own discovery) or
    ``clarification_needed``."""

    unresolved_hints: dict[str, str] = field(default_factory=dict)
    """Free-form hints Reception couldn't resolve to canonical refs.
    Keys are placeholder names Reception used internally
    (``primary_resource`` / ``target_resource`` / ...); values are
    the original strings the user wrote so the clarification turn
    can quote them back."""

    diagnostics: tuple[str, ...] = ()
    """Operator-only reasons explaining why a hint / capability
    didn't resolve. Audit / debug only — never shown to the user
    verbatim."""

    raw_query: str = ""
    """Original user message verbatim. Audit / debug only — never
    re-prompted into the LLM."""

    metadata: dict[str, Any] = field(default_factory=dict)
    """Free-form per-Reception extension. Reception subagents may
    drop additional structured signals here (selected lane name,
    target_repo, etc.) without growing the named field set."""

    def __post_init__(self) -> None:
        if not isinstance(self.resource_refs, tuple):
            object.__setattr__(self, "resource_refs", tuple(self.resource_refs))
        if not isinstance(self.action_candidates, tuple):
            object.__setattr__(
                self, "action_candidates", tuple(self.action_candidates),
            )
        if not isinstance(self.capability_candidates, tuple):
            object.__setattr__(
                self,
                "capability_candidates",
                tuple(self.capability_candidates),
            )
        if not isinstance(self.diagnostics, tuple):
            object.__setattr__(self, "diagnostics", tuple(self.diagnostics))

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent_type": self.intent_type,
            "resource_refs": [r.to_dict() for r in self.resource_refs],
            "action_candidates": list(self.action_candidates),
            "capability_candidates": list(self.capability_candidates),
            "unresolved_hints": dict(self.unresolved_hints),
            "diagnostics": list(self.diagnostics),
            "raw_query": self.raw_query,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ReceptionResolution:
        return cls(
            intent_type=data.get("intent_type", "unknown"),  # type: ignore[arg-type]
            resource_refs=tuple(
                ResourceRef.from_dict(r) for r in (data.get("resource_refs") or ())
            ),
            action_candidates=tuple(data.get("action_candidates") or ()),
            capability_candidates=tuple(
                data.get("capability_candidates") or ()
            ),
            unresolved_hints=dict(data.get("unresolved_hints") or {}),
            diagnostics=tuple(data.get("diagnostics") or ()),
            raw_query=str(data.get("raw_query") or ""),
            metadata=dict(data.get("metadata") or {}),
        )


__all__ = [
    "ReceptionIntentType",
    "ReceptionResolution",
]
