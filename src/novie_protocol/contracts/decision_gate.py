"""DecisionGateEnvelope — W5 reusable expert-raised decision-gate contract.

Background
----------

Pre-W5 the platform had two gate-like contracts in this package:

- ``GateSpec`` (``gates.py``)         — step-level HITL declared at plan
  compile time; lifecycle approve / reject / request_changes against
  someone else's output.
- ``PlanReviewRequest`` / ``Decision`` (``plan_review.py``) — plan-level
  HITL before execution starts; same approve / reject / request_changes
  shape.

Both are **review-style**: a producer ships an artefact, a reviewer
decides whether to let it proceed. Neither matches the
``ANALYST_REFACTOR_AND_DECISION_GATE_BACKLOG`` W4-W5 use case where an
expert agent (analyst now; pm / architect / scrum later) raises a
decision question mid-run because *it* is uncertain — "I'm 40%
confident the brief means X vs. Y, can you steer me?". The shape is
multiple-choice (or freeform), often auto-resolvable by policy if
confidence is high or risk is low.

W5 adds this third contract alongside (not instead of) the existing
two. Platform code that already understands GateSpec keeps working;
new platform-side persistence + UI for decision gates lands in W7
without disturbing review-style gates.

Design intent
-------------

- Cross-agent: every expert agent uses the *same* envelope. ``gate_type``
  is an open string with analyst-canonical values from the W4 taxonomy;
  pm / architect / scrum can use any string here without modifying the
  contract.
- LLM-driven, not rule-driven (per the ``feedback_prefer_llm_over_rules``
  guidance): ``confidence`` and ``risk_level`` are values the LLM sets
  directly. The envelope's job is to validate shape, not to score on
  the LLM's behalf.
- Auto-resolution friendly: ``auto_resolvable`` + ``recommended_option``
  let W6 policy resolve low-risk / high-confidence gates without
  blocking the run.
- Resume-friendly: ``resume_hint`` carries what the runtime should do
  after resolution lands so the agent doesn't need to re-derive its
  state from scratch on resume.

Lifecycle (covered in W7 — platform persistence)
------------------------------------------------

1. ``raised``       — agent yields the envelope as part of its event stream
2. ``pending``      — platform persists the envelope, surfaces it on Run Detail
3. ``resolved``     — user picks an option / writes freeform / policy
                      auto-resolves it; ``DecisionGateResolution`` is recorded
4. ``ack``          — runtime resumes from ``resume_hint`` with the resolution

W5 only locks the wire shape. The lifecycle bookkeeping lands in W7.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

# ── Risk + canonical analyst gate types ────────────────────────────────────

DecisionGateRiskLevel = Literal["low", "medium", "high"]
"""How impactful is choosing wrong on this gate?

The LLM sets this value. Platform / W6 policy reads it to decide
whether the gate is auto-resolvable (e.g. "low risk + confidence > 0.8
+ ``auto_resolvable=True`` ⇒ pick ``recommended_option`` without
blocking").
"""

DecisionGateResolutionType = Literal[
    "selected_option",
    "freeform",
    "auto_policy",
    "skipped",
]
"""How a decision gate was resolved.

- ``selected_option``: user picked one of ``options`` by ``id``
- ``freeform``: user wrote a free-form answer (only valid when the
  envelope had ``allow_freeform=True``)
- ``auto_policy``: W6 policy auto-resolved without surfacing to the
  user (only valid when the envelope had ``auto_resolvable=True``)
- ``skipped``: gate timed out or was abandoned; runtime falls through
  with the envelope's ``recommended_option`` if present, else with
  agent-internal default behaviour
"""


# ── ADR-017 Block 4a/4b: mid-run ask timeout + per-step cap ────────────────

MidRunAskTimeoutAction = Literal[
    "skip",
    "auto_recommended",
    "fail_implementation",
]
"""What the platform should do when a mid-run decision gate times out.

- ``skip``                  Treat the gate as ``skipped`` (existing behaviour).
                            Runtime falls through with ``recommended_option``
                            if present, else with agent-internal default.
- ``auto_recommended``      Synthesise an ``auto_policy`` resolution using
                            ``recommended_option``. Requires the envelope to
                            carry a ``recommended_option``.
- ``fail_implementation``   Fail the step with ``failure_type=implementation_failed``.
                            High-risk gates that cannot proceed without a
                            human answer use this so the dispatch
                            classifier escalates rather than silently
                            falling through.
"""

DEFAULT_MAX_MID_RUN_ASKS_PER_STEP = 3
"""ADR-017 default cap on the number of mid-run decision gates a single
step can raise. Exceeding the cap escalates the step to ``re-plan`` or
``implementation_failed`` per platform policy; the cap can be tightened
per capability via ``capability_metadata.max_mid_run_asks`` or per tenant
via tenant-policy ``max_mid_run_asks``.

Both 4a (envelope-declared ``timeout_seconds`` / ``default_action_on_timeout``)
and 4b (per-step cap) are the protocol-side primitives. Platform
middleware reads the envelope + counter and enforces; the wiring
itself is a follow-up slice once the consumer-side semantics
stabilise."""


def check_mid_run_ask_budget(
    current_count: int,
    *,
    cap: int = DEFAULT_MAX_MID_RUN_ASKS_PER_STEP,
) -> bool:
    """ADR-017 Block 4b — return ``True`` iff another mid-run ask is
    allowed for this step.

    Mirrors :func:`has_snapshot_patch_budget` (ADR-018) shape: callers
    pass the current count of asks already raised on this step; the
    function reports whether the *next* one would exceed the cap.

    ``current_count`` is what the platform has already counted, *not*
    what the next ask would bring the total to. The caller increments
    AFTER the check (and only if the check passed).
    """
    return max(0, current_count) < max(0, cap)


# Canonical gate_type values for the analyst W4 taxonomy. ``gate_type`` on
# the envelope is an open string so non-analyst experts can introduce
# their own values without modifying this contract; this tuple is exposed
# only for analyst code that wants compile-time consistency.
ANALYST_DECISION_GATE_TYPES: tuple[str, ...] = (
    "brief_alignment",   # "Did I read the brief the way you meant?"
    "missing_inputs",    # "I need X to proceed; can you provide / confirm?"
    "research_depth",    # "Should I dig deeper here or move on?"
    "report_focus",      # "Lead with angle A or angle B?"
    "artifact_commit",   # "Commit this artefact as canonical or keep iterating?"
)


# ── Option + envelope ──────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class DecisionGateOption:
    """One option the user can pick on a decision gate.

    The expert agent supplies the option set. ``confidence_hint`` is the
    LLM's brief rationale for why this option might be the right one —
    surfaces in the UI so users can compare without reading the full
    ``description``.
    """

    id: str
    """Stable id for this option within the gate. The user / policy
    references this when selecting; the runtime reads it back from
    ``DecisionGateResolution.selected_option_id``."""

    title: str
    """One-line label for UI. Keep short."""

    description: str = ""
    """Multi-line explanation of what this option means and what would
    follow if selected. Markdown-safe."""

    confidence_hint: str = ""
    """LLM's brief rationale for this option. One sentence. Empty when
    the agent chose not to express a per-option preference."""


@dataclass(frozen=True, slots=True)
class DecisionGateEnvelope:
    """The W5 wire-format contract for an expert-raised decision gate.

    Shape is intentionally cross-agent: analyst raises it now (W4); pm /
    architect / scrum can raise it later by reusing the same envelope
    with their own ``gate_type`` / ``raised_by_agent_id`` values, with
    no contract change required.

    Field semantics
    ---------------

    - ``gate_id``                  Globally unique id (UUID hex).
    - ``gate_type``                Free-form string. Analyst canonical values
                                   in ``ANALYST_DECISION_GATE_TYPES``; other
                                   experts use their own strings.
    - ``title`` / ``question``     UI text. ``title`` is one line for list
                                   rendering; ``question`` is the full
                                   question the user is being asked.
    - ``why_now``                  One-line explanation of why the agent
                                   raised this gate at this point in the
                                   run (e.g. "the brief mentions both
                                   product and market analysis; I need to
                                   know which is primary").
    - ``options``                  Tuple of 2-5 ``DecisionGateOption`` items.
                                   Empty allowed only when
                                   ``allow_freeform=True``.
    - ``recommended_option``       ``option.id`` the agent leans toward;
                                   ``None`` when the agent has no
                                   preference. Required when
                                   ``auto_resolvable=True`` so policy has
                                   a default to apply.
    - ``allow_freeform``           When True, the user may write a
                                   free-form answer instead of picking an
                                   option.
    - ``auto_resolvable``          When True, W6 policy may resolve this
                                   gate without surfacing to the user
                                   (low-risk + high-confidence path).
    - ``confidence``               LLM's confidence in its current path
                                   (0.0-1.0). Producers must clamp.
    - ``risk_level``               Impact of choosing wrong. LLM-set.
    - ``estimated_cost_impact``    Optional. USD or token-equivalent
                                   estimate of the cost delta between
                                   picking the wrong option vs. the
                                   right one. None when the agent has no
                                   estimate.
    - ``resume_hint``              Free-form. Tells the runtime what to
                                   do after the gate resolves (e.g.
                                   "rerun ``research_synthesize`` with
                                   the chosen scope"). Agent-internal
                                   semantics — platform passes through.
    - ``agent_metadata``           Free-form dict. Carries raising-agent
                                   context (e.g. ``{"runtime_phase":
                                   "collect_evidence", "narrative_chars":
                                   5400}``) so resume can re-derive
                                   state. Platform persists opaquely;
                                   does not interpret.
    - ``raised_by_agent_id``       The agent that raised the gate
                                   ("analyst" / "pm" / "architect" / …).
    - ``raised_at_phase``          Runtime phase id (analyst-internal)
                                   when the gate was raised. Diagnostic
                                   only.
    - ``raised_at_ms``             Optional millisecond timestamp.
    """

    gate_id: str
    gate_type: str
    title: str
    question: str
    why_now: str = ""
    options: tuple[DecisionGateOption, ...] = ()
    recommended_option: str | None = None
    allow_freeform: bool = False
    auto_resolvable: bool = False
    confidence: float = 0.0
    risk_level: DecisionGateRiskLevel = "medium"
    estimated_cost_impact: float | None = None
    resume_hint: str = ""
    agent_metadata: dict[str, Any] = field(default_factory=dict)
    raised_by_agent_id: str = ""
    raised_at_phase: str = ""
    raised_at_ms: int | None = None
    # ADR-017 Block 4a — agent-declared timeout + default action.
    # ``timeout_seconds=None`` means "use platform default" (tenant
    # policy can fill this in). ``default_action_on_timeout="skip"``
    # preserves the pre-ADR-017 behaviour, so existing producers stay
    # unchanged by default.
    timeout_seconds: float | None = None
    default_action_on_timeout: MidRunAskTimeoutAction = "skip"

    def __post_init__(self) -> None:
        # Reserialisation safety: tuples may arrive as lists from JSON.
        if not isinstance(self.options, tuple):
            object.__setattr__(self, "options", tuple(self.options))
        # Validate confidence clamp at construction so producers can't
        # silently pass through nonsense like 1.7 / -0.3.
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(
                f"DecisionGateEnvelope.confidence must be 0.0-1.0; "
                f"got {self.confidence!r}"
            )
        # auto_resolvable requires a recommended option (so policy has
        # something to pick) OR allow_freeform (so policy can synthesise
        # a freeform default). Otherwise auto-resolution would be
        # ill-defined.
        if self.auto_resolvable and self.recommended_option is None and not self.allow_freeform:
            raise ValueError(
                "DecisionGateEnvelope.auto_resolvable=True requires either "
                "recommended_option or allow_freeform=True so policy has a "
                "default resolution"
            )
        # If options is empty, allow_freeform must be True — otherwise
        # there's literally no way to resolve the gate.
        if not self.options and not self.allow_freeform:
            raise ValueError(
                "DecisionGateEnvelope must supply options or set "
                "allow_freeform=True; otherwise the gate is unresolvable"
            )
        # If recommended_option is set, it must reference an existing
        # option id (cross-check). Producers that build the envelope by
        # hand are guarded by this; LLM-built envelopes routed through
        # the analyst factory are pre-validated by W4 helpers.
        if self.recommended_option is not None:
            option_ids = {opt.id for opt in self.options}
            if self.recommended_option not in option_ids:
                raise ValueError(
                    f"recommended_option={self.recommended_option!r} does "
                    f"not match any option.id in {sorted(option_ids)!r}"
                )
        # ADR-017 Block 4a — validate timeout + default_action consistency.
        if self.timeout_seconds is not None and self.timeout_seconds <= 0:
            raise ValueError(
                f"DecisionGateEnvelope.timeout_seconds must be positive when "
                f"set; got {self.timeout_seconds!r}"
            )
        if (
            self.default_action_on_timeout == "auto_recommended"
            and self.recommended_option is None
        ):
            raise ValueError(
                "DecisionGateEnvelope.default_action_on_timeout='auto_recommended' "
                "requires recommended_option so the platform has a default to "
                "synthesise on timeout"
            )


@dataclass(frozen=True, slots=True)
class DecisionGateResolution:
    """How a decision gate was resolved.

    Recorded by platform when the user (or W6 policy) responds to a
    raised envelope. Surfaces back to the runtime so the resume path
    can act on it.
    """

    gate_id: str
    resolution_type: DecisionGateResolutionType
    selected_option_id: str | None = None
    freeform_answer: str = ""
    resolved_by: str = ""
    """User principal id, or ``"policy:<rule>"`` for auto-resolutions.
    Empty for ``skipped``."""
    resolved_at_ms: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Cross-field consistency: the resolution_type dictates which
        # detail field is meaningful.
        if self.resolution_type == "selected_option" and not self.selected_option_id:
            raise ValueError(
                "DecisionGateResolution(selected_option) requires "
                "selected_option_id"
            )
        if self.resolution_type == "freeform" and not self.freeform_answer.strip():
            raise ValueError(
                "DecisionGateResolution(freeform) requires non-empty "
                "freeform_answer"
            )


# ── W7 — runtime state + lifecycle ────────────────────────────────────────


DecisionGateRuntimeStatus = Literal[
    "raised",
    "pending",
    "resolved",
    "skipped",
]
"""Lifecycle states for a persisted decision gate.

- ``raised``: agent emitted the envelope but platform hasn't yet
  decided whether policy auto-resolves it.
- ``pending``: policy declined to auto-resolve; the gate is awaiting
  user input.
- ``resolved``: a ``DecisionGateResolution`` has been recorded
  (``selected_option`` / ``freeform`` / ``auto_policy``). Terminal.
- ``skipped``: the gate was abandoned (timeout, run cancelled, agent
  retracted). Terminal.

Terminal states must not transition further. ``raised → pending`` is
the manual-policy / hybrid-declined branch; ``raised → resolved`` is
the auto-policy branch; either ``pending`` or ``raised`` may transit
to ``skipped`` on timeout / cancel.
"""


@dataclass(frozen=True, slots=True)
class DecisionGateRuntimeState:
    """One persisted decision gate's current lifecycle state.

    Distinct from ``GateRuntimeState`` (which models review-style HITL
    gates declared on the ExecutionPlan): ``DecisionGateRuntimeState``
    persists an *expert-raised* decision envelope and its resolution.
    Both can coexist on a plan; ``PlanRuntimeState.active_gates``
    handles review gates, ``PlanRuntimeState.active_decision_gates``
    handles decision gates. The split lets reviewers / compliance
    code keep its existing surface unchanged.

    Field semantics
    ---------------

    - ``gate_id``: matches ``envelope.gate_id``. Acts as the row key.
    - ``plan_id``: the plan the gate belongs to. Indexed for
      ``list_active_decision_gates(plan_id)``.
    - ``envelope``: the original ``DecisionGateEnvelope``. Stored as a
      dict (already JSON-serialisable via dataclass conversion) so
      DB layers can persist verbatim.
    - ``status``: ``DecisionGateRuntimeStatus``. Read by run-detail UI
      and by the runtime resume path.
    - ``raised_at`` / ``resolved_at``: lifecycle timestamps.
    - ``resolution``: the recorded ``DecisionGateResolution``, or
      ``None`` while ``raised`` / ``pending`` / ``skipped``.
    - ``resolution_source``: audit string. ``"user:<principal_id>"``
      for human-resolved; ``"policy:<preset_label>"`` for policy
      auto-resolved; ``"timeout"`` / ``"cancel"`` for skipped paths;
      empty while raised / pending.
    """

    gate_id: str
    plan_id: str
    envelope: dict[str, Any]
    status: DecisionGateRuntimeStatus = "raised"
    raised_at: datetime | None = None
    resolved_at: datetime | None = None
    resolution: dict[str, Any] | None = None
    resolution_source: str = ""


__all__ = [
    "ANALYST_DECISION_GATE_TYPES",
    "DEFAULT_MAX_MID_RUN_ASKS_PER_STEP",
    "DecisionGateEnvelope",
    "DecisionGateOption",
    "DecisionGateResolution",
    "DecisionGateResolutionType",
    "DecisionGateRiskLevel",
    "DecisionGateRuntimeState",
    "DecisionGateRuntimeStatus",
    "MidRunAskTimeoutAction",
    "check_mid_run_ask_budget",
]
