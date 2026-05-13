"""DecisionGate policy + evaluator (W6).

Background
----------

W4 + W5 landed the wire format (``DecisionGateEnvelope``) and the
analyst-side raise rules. W6 layers a *resolution policy* on top:
given a raised envelope and a policy preset, can the platform resolve
the gate without surfacing it to a human, or must it block on user
input?

Per the W6 spec the same envelope must be either user-interactive or
auto-resolvable — without forking analyst code. The evaluator below is
**pure** (no IO, no platform state) so analyst, runtime, gateway, or a
test harness can all drive it identically. Per the
``feedback_prefer_llm_over_rules`` guidance, ``confidence`` and
``risk_level`` on the envelope are LLM-set values; the policy here
codifies operator-tunable thresholds *over* those values, not in place
of them.

Three canonical presets ship with the contract:

- ``interactive`` — block on every gate. Production default for
  enterprise / compliance-sensitive contexts.
- ``balanced``    — auto-resolve only low-risk + high-confidence +
  ``auto_resolvable=True`` gates. Sensible default for
  individual-contributor flows.
- ``yolo``        — auto-resolve any ``auto_resolvable`` gate that has
  a ``recommended_option``. Aimed at "let the agent run; bother me
  only if it's truly stuck".

Each preset is a fully-formed ``DecisionGatePolicy`` dataclass; callers
that want a custom policy can construct one directly with their own
thresholds.

Lifecycle
---------

1. Envelope raised by an expert agent.
2. Caller invokes ``evaluate_decision_gate(envelope, policy)``:
   - returns ``DecisionGateResolution`` ⇒ caller writes the resolution
     to the platform store and resumes; the gate never surfaces to the
     user. ``resolution.resolved_by`` is ``"policy:<preset_label>"``
     so audit can reconstruct who chose.
   - returns ``None`` ⇒ caller persists the gate as ``pending`` and
     surfaces it to the user.

The evaluator never returns a partial / synthetic resolution that
violates the envelope's own validation; that means the underlying
``DecisionGateResolution`` constructor (with its
``__post_init__`` cross-field checks) is the single point of truth for
"is this resolution well-formed?".
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .decision_gate import (
    DecisionGateEnvelope,
    DecisionGateResolution,
    DecisionGateRiskLevel,
)

# ── Mode + preset enums ────────────────────────────────────────────────────

ResolutionMode = Literal["manual", "auto", "hybrid"]
"""How a policy resolves gates.

- ``manual``: never auto-resolve; every gate blocks for user input.
- ``auto``:   auto-resolve every ``auto_resolvable`` gate with a
              recommended_option. Used by the ``yolo`` preset.
- ``hybrid``: auto-resolve only when the gate's confidence + risk +
              irreversibility all clear the policy thresholds.
"""

PolicyPreset = Literal["interactive", "balanced", "yolo"]
"""Operator-facing preset labels surfaced on resolution audit so
``resolution.resolved_by = "policy:<preset>"`` reads cleanly."""


# ── Policy dataclass ──────────────────────────────────────────────────────


_RISK_ORDER: dict[DecisionGateRiskLevel, int] = {
    "low": 0,
    "medium": 1,
    "high": 2,
}


def _risk_at_or_below(actual: DecisionGateRiskLevel, ceiling: DecisionGateRiskLevel) -> bool:
    """``actual <= ceiling`` along the low < medium < high ordering."""
    return _RISK_ORDER[actual] <= _RISK_ORDER[ceiling]


@dataclass(frozen=True, slots=True)
class DecisionGatePolicy:
    """A resolution policy applied to raised decision gates.

    ``mode`` is the high-level branch; the threshold fields are only
    consulted when ``mode == "hybrid"``. ``preset_label`` is the audit
    string surfaced on every auto-resolution this policy emits.

    Field semantics
    ---------------

    - ``mode``: see ``ResolutionMode``.
    - ``min_confidence_for_auto``: gate must satisfy
      ``envelope.confidence >= min_confidence_for_auto`` to auto-resolve
      under ``hybrid`` mode. Ignored under ``manual`` / ``auto``.
    - ``max_risk_for_auto``: gate must satisfy
      ``envelope.risk_level <= max_risk_for_auto`` (along low < medium <
      high) to auto-resolve under ``hybrid`` mode. Ignored under
      ``manual`` / ``auto``.
    - ``block_on_irreversible``: when True, an envelope whose
      ``agent_metadata`` carries ``"irreversible": True`` ALWAYS blocks
      regardless of mode. Lets ops carve out specific gate categories
      ("artefact_commit" tends to be irreversible) without overriding
      the mode globally.
    - ``preset_label``: audit string. ``"interactive"`` / ``"balanced"``
      / ``"yolo"`` for the canonical presets; custom-built policies can
      pick any short label.
    """

    mode: ResolutionMode
    min_confidence_for_auto: float = 0.8
    max_risk_for_auto: DecisionGateRiskLevel = "low"
    block_on_irreversible: bool = True
    preset_label: str = ""

    def __post_init__(self) -> None:
        if not (0.0 <= self.min_confidence_for_auto <= 1.0):
            raise ValueError(
                "min_confidence_for_auto must be 0.0-1.0; got "
                f"{self.min_confidence_for_auto!r}"
            )


# ── Canonical presets ──────────────────────────────────────────────────────


INTERACTIVE_POLICY = DecisionGatePolicy(
    mode="manual",
    min_confidence_for_auto=1.0,  # unreachable; mode=manual short-circuits
    max_risk_for_auto="low",
    block_on_irreversible=True,
    preset_label="interactive",
)
"""Block on every gate. Production-safe default for enterprise /
compliance contexts."""


BALANCED_POLICY = DecisionGatePolicy(
    mode="hybrid",
    min_confidence_for_auto=0.8,
    max_risk_for_auto="low",
    block_on_irreversible=True,
    preset_label="balanced",
)
"""Auto-resolve only low-risk + high-confidence + ``auto_resolvable=True``
gates. Sensible default for individual-contributor flows."""


YOLO_POLICY = DecisionGatePolicy(
    mode="auto",
    min_confidence_for_auto=0.0,  # unreachable; mode=auto short-circuits
    max_risk_for_auto="high",
    block_on_irreversible=True,   # even yolo refuses to auto-pick irreversible
    preset_label="yolo",
)
"""Auto-resolve any ``auto_resolvable=True`` gate that has a
``recommended_option``. Aimed at "let the agent run; bother me only if
it's truly stuck"."""


CANONICAL_PRESETS: dict[PolicyPreset, DecisionGatePolicy] = {
    "interactive": INTERACTIVE_POLICY,
    "balanced": BALANCED_POLICY,
    "yolo": YOLO_POLICY,
}


def resolve_preset(preset: PolicyPreset) -> DecisionGatePolicy:
    """Look up a canonical preset by label.

    Raises ``KeyError`` for unknown labels rather than silently
    falling back; callers that want a default behaviour should pick
    ``CANONICAL_PRESETS["interactive"]`` explicitly.
    """
    return CANONICAL_PRESETS[preset]


# ── Evaluator ─────────────────────────────────────────────────────────────


def evaluate_decision_gate(
    envelope: DecisionGateEnvelope,
    policy: DecisionGatePolicy,
) -> DecisionGateResolution | None:
    """Apply ``policy`` to a raised ``envelope``.

    Returns:

    - ``DecisionGateResolution`` ⇒ the policy auto-resolves the gate;
      caller writes the resolution to the platform store and resumes
      without surfacing the gate.
    - ``None`` ⇒ the policy declines to auto-resolve; caller persists
      the gate as ``pending`` and surfaces it to the user.

    The function is pure: same inputs always produce the same output,
    no IO. This makes it identically callable from analyst code,
    runtime hooks, or a gateway pre-flight check.
    """
    # Universal block: irreversible envelopes never auto-resolve when
    # the policy says so, regardless of mode. Producers signal
    # irreversibility on ``agent_metadata["irreversible"]`` because
    # that's the cleanest surface that doesn't bump the W5 envelope.
    if policy.block_on_irreversible and bool(
        envelope.agent_metadata.get("irreversible")
    ):
        return None

    # ``manual`` always blocks.
    if policy.mode == "manual":
        return None

    # No way to auto-pick on a gate that didn't opt in.
    if not envelope.auto_resolvable:
        return None

    # ``auto`` short-circuits the hybrid thresholds: any
    # ``auto_resolvable`` gate with a default may auto-resolve.
    if policy.mode == "auto":
        return _build_auto_resolution(envelope, policy)

    # ``hybrid``: confidence + risk thresholds gate auto-resolution.
    if policy.mode == "hybrid":
        if envelope.confidence < policy.min_confidence_for_auto:
            return None
        if not _risk_at_or_below(envelope.risk_level, policy.max_risk_for_auto):
            return None
        return _build_auto_resolution(envelope, policy)

    return None


def _build_auto_resolution(
    envelope: DecisionGateEnvelope,
    policy: DecisionGatePolicy,
) -> DecisionGateResolution | None:
    """Construct a ``DecisionGateResolution`` for an auto-resolution path.

    Picks the recommended option when present; falls back to a
    freeform synthesised default when the envelope is freeform-only +
    ``auto_resolvable``. Returns ``None`` if neither path is available
    (defensive — the envelope's own ``__post_init__`` should already
    have rejected this combination, so this branch is a belt-and-
    braces guard for hand-built test envelopes).
    """
    resolved_by = (
        f"policy:{policy.preset_label}" if policy.preset_label else "policy:custom"
    )
    if envelope.recommended_option is not None:
        return DecisionGateResolution(
            gate_id=envelope.gate_id,
            resolution_type="auto_policy",
            selected_option_id=envelope.recommended_option,
            resolved_by=resolved_by,
        )
    if envelope.allow_freeform:
        return DecisionGateResolution(
            gate_id=envelope.gate_id,
            resolution_type="auto_policy",
            freeform_answer="(auto-policy: no recommended option)",
            resolved_by=resolved_by,
        )
    return None


__all__ = [
    "BALANCED_POLICY",
    "CANONICAL_PRESETS",
    "INTERACTIVE_POLICY",
    "YOLO_POLICY",
    "DecisionGatePolicy",
    "PolicyPreset",
    "ResolutionMode",
    "evaluate_decision_gate",
    "resolve_preset",
]
