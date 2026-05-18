"""ADR-012 ``CapabilitySelectionRationale`` contract tests.

Cover the additive selection-rationale fields on ``CapabilityResolution``:
construction, round-trip via ``to_dict`` / ``from_dict``, and back-compat
with pre-ADR-012 serialised snapshots that omit the field.
"""
from __future__ import annotations

from novie_protocol.contracts import (
    CapabilityCandidateScore,
    CapabilityResolution,
    CapabilityResolutionSnapshot,
    CapabilitySelectionRationale,
)


def _rationale() -> CapabilitySelectionRationale:
    return CapabilitySelectionRationale(
        source="llm_rank",
        rationale_text="Picker chose writer over editor because the task is authoring.",
        candidate_scores=(
            CapabilityCandidateScore(
                capability_id="agent.writer",
                agent_id="writer-agent",
                score=0.91,
                risk_class="write",
                side_effect="external",
                notes="winner",
            ),
            CapabilityCandidateScore(
                capability_id="agent.editor",
                agent_id="editor-agent",
                score=0.42,
                risk_class="read_only",
                side_effect="none",
                notes="too narrow scope",
            ),
        ),
    )


def test_rationale_round_trip_preserves_structure() -> None:
    rationale = _rationale()
    restored = CapabilitySelectionRationale.from_dict(rationale.to_dict())

    assert restored.source == "llm_rank"
    assert restored.rationale_text.startswith("Picker chose")
    assert len(restored.candidate_scores) == 2
    assert restored.candidate_scores[0].capability_id == "agent.writer"
    assert restored.candidate_scores[0].score == 0.91
    assert restored.candidate_scores[1].notes == "too narrow scope"


def test_unknown_source_defaults_to_unspecified() -> None:
    """Future protocol additions must not crash older readers — the
    ``source`` field deserialises to ``"unspecified"`` if an unknown
    value appears (closed-set safety)."""
    rationale = CapabilitySelectionRationale.from_dict(
        {
            "source": "future_strategy_x",
            "rationale_text": "n/a",
            "candidate_scores": [],
        }
    )
    assert rationale.source == "unspecified"


def test_candidate_score_handles_missing_optional_fields() -> None:
    """``score`` is optional and ``agent_id`` may be empty for
    catalog-only candidates (e.g. picker hadn't bound to an agent yet)."""
    score = CapabilityCandidateScore.from_dict(
        {"capability_id": "cap.x"}
    )
    assert score.capability_id == "cap.x"
    assert score.agent_id == ""
    assert score.score is None


def test_candidate_score_coerces_string_numbers() -> None:
    score = CapabilityCandidateScore.from_dict(
        {"capability_id": "cap.x", "score": "0.5"}
    )
    assert score.score == 0.5


def test_candidate_score_drops_uncoercible_score() -> None:
    score = CapabilityCandidateScore.from_dict(
        {"capability_id": "cap.x", "score": "not-a-number"}
    )
    assert score.score is None


def test_capability_resolution_round_trip_with_rationale() -> None:
    resolution = CapabilityResolution(
        node_id="step-1",
        required_capability="agent.writer",
        resolved_runtime_ref="agent-runtime-1",
        resolved_capability_version="1.2.3",
        selection_rationale=_rationale(),
    )

    restored = CapabilityResolution.from_dict(resolution.to_dict())

    assert restored.selection_rationale is not None
    assert restored.selection_rationale.source == "llm_rank"
    assert len(restored.selection_rationale.candidate_scores) == 2


def test_capability_resolution_round_trip_without_rationale() -> None:
    """Pre-ADR-012 snapshots / resolutions had no rationale. The field
    must remain ``None`` after round-trip and the serialised payload
    must NOT include the key (so legacy stores see the same shape they
    wrote)."""
    resolution = CapabilityResolution(
        node_id="step-1",
        required_capability="agent.writer",
        resolved_runtime_ref="agent-runtime-1",
        resolved_capability_version="1.2.3",
    )

    payload = resolution.to_dict()
    assert "selection_rationale" not in payload

    restored = CapabilityResolution.from_dict(payload)
    assert restored.selection_rationale is None


def test_legacy_snapshot_dict_deserialises_cleanly() -> None:
    """A snapshot dict produced by a pre-ADR-012 writer (no rationale
    key) must round-trip into a ``CapabilityResolutionSnapshot`` with
    resolutions whose ``selection_rationale`` is ``None``."""
    legacy = {
        "plan_id": "plan-legacy",
        "frozen_at": "2026-04-01T00:00:00Z",
        "resolutions": [
            {
                "node_id": "step-1",
                "required_capability": "agent.writer",
                "resolved_runtime_ref": "agent-runtime-1",
                "resolved_capability_version": "1.0.0",
                "resolved_binding_id": None,
                "resolved_credential_ref": None,
                "metadata": {},
            }
        ],
        "snapshot_version": "v1",
        "predecessor_snapshot_version": None,
        "patch_attempt": 0,
    }
    snapshot = CapabilityResolutionSnapshot.from_dict(legacy)
    assert snapshot.resolutions[0].selection_rationale is None


def test_rationale_text_only_with_empty_scores_is_valid() -> None:
    """Short-circuit paths (``single_candidate_short_circuit``) have a
    rationale text but no score table — that combination must serialise
    + round-trip without inventing empty rows."""
    rationale = CapabilitySelectionRationale(
        source="single_candidate_short_circuit",
        rationale_text="only one hard-filtered capability available",
    )
    assert rationale.candidate_scores == ()

    restored = CapabilitySelectionRationale.from_dict(rationale.to_dict())
    assert restored.source == "single_candidate_short_circuit"
    assert restored.candidate_scores == ()
