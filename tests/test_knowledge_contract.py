"""W1 of KNOWLEDGE_LIFECYCLE_SEDIMENTATION — KnowledgeRecord contract tests."""
# ruff: noqa: I001
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from novie_protocol.contracts import (
    EFFECTIVE_KNOWLEDGE_COUNT_CAP,
    EFFECTIVE_KNOWLEDGE_TOTAL_BODY_KIB,
    EffectiveKnowledgeSet,
    KnowledgeProvenance,
    KnowledgeRecord,
    KnowledgeValidationError,
)
from novie_protocol.contracts.knowledge import kind_body_cap_kib


def _provenance() -> KnowledgeProvenance:
    return KnowledgeProvenance(
        originating_run_id="run-1",
        originating_turn_id="turn-1",
        originating_capability_id="platform.planner.compile",
        originating_agent_id="planner",
        created_at=datetime(2026, 5, 11, 12, 0, 0, tzinfo=UTC),
        created_by="system:plan_decision_outcome",
    )


def _record(**overrides) -> KnowledgeRecord:
    base = {
        "record_id": "kn-1",
        "kind": "plan_decision",
        "scope": "project",
        "scope_ref": "proj-1",
        "summary": "Approved repo mutation against repo-X.",
        "body": "Approved by user-7 after preview.",
        "provenance": _provenance(),
    }
    base.update(overrides)
    return KnowledgeRecord(**base)


# ── Five-family round trip ──────────────────────────────────────────


@pytest.mark.parametrize(
    "kind",
    [
        "plan_decision",
        "artifact_summary",
        "intermediate_conclusion",
        "preference",
        "correction",
    ],
)
def test_each_kind_round_trips(kind: str) -> None:
    record = _record(kind=kind, body="brief body")
    out = KnowledgeRecord.from_dict(record.to_dict())
    assert out.kind == kind
    assert out == record


# ── Required-field validation ────────────────────────────────────────


def test_record_id_required() -> None:
    with pytest.raises(KnowledgeValidationError, match="record_id"):
        _record(record_id="")


def test_summary_required() -> None:
    with pytest.raises(KnowledgeValidationError, match="summary is required"):
        _record(summary="")


def test_summary_over_max_chars_rejected() -> None:
    with pytest.raises(KnowledgeValidationError, match="summary for"):
        _record(summary="x" * 281)


def test_invalid_kind_rejected() -> None:
    with pytest.raises(KnowledgeValidationError, match="invalid kind"):
        _record(kind="not-a-real-kind")  # type: ignore[arg-type]


def test_invalid_scope_rejected() -> None:
    with pytest.raises(KnowledgeValidationError, match="invalid scope"):
        _record(scope="personal")  # type: ignore[arg-type]


def test_empty_scope_ref_rejected() -> None:
    with pytest.raises(KnowledgeValidationError, match="scope_ref is required"):
        _record(scope_ref="")


# ── Per-family body caps ─────────────────────────────────────────────


@pytest.mark.parametrize(
    "kind,cap_kib",
    [
        ("plan_decision", 8),
        ("artifact_summary", 4),
        ("intermediate_conclusion", 4),
        ("preference", 1),
        ("correction", 2),
    ],
)
def test_per_kind_body_cap(kind: str, cap_kib: int) -> None:
    """Each family has a documented body cap; exceeding it fails
    contract validation with a clear error pointing at the cap."""
    huge = "x" * (cap_kib * 1024 + 1)
    with pytest.raises(KnowledgeValidationError, match=f"per-family cap is {cap_kib} KiB"):
        _record(kind=kind, body=huge)
    assert kind_body_cap_kib(kind) == cap_kib


# ── Provenance required ──────────────────────────────────────────────


def test_provenance_created_at_required() -> None:
    """Audits replay the provenance envelope; ``created_at`` is the
    one field they cannot infer from anywhere else."""
    bad = KnowledgeProvenance(created_by="system")
    with pytest.raises(KnowledgeValidationError, match="provenance.created_at"):
        _record(provenance=bad)


def test_provenance_created_by_required() -> None:
    bad = KnowledgeProvenance(
        created_at=datetime(2026, 5, 11, tzinfo=UTC),
        created_by="",
    )
    with pytest.raises(KnowledgeValidationError, match="provenance.created_by"):
        _record(provenance=bad)


# ── EffectiveKnowledgeSet ────────────────────────────────────────────


def test_effective_knowledge_set_round_trip() -> None:
    record = _record()
    eff = EffectiveKnowledgeSet(
        records=(record,), snapshot_ref="sha:abc",
    )
    payload = eff.to_dict()
    assert payload["records"][0]["record_id"] == record.record_id
    assert payload["snapshot_ref"] == "sha:abc"


def test_caps_constants_match_documented_defaults() -> None:
    assert EFFECTIVE_KNOWLEDGE_COUNT_CAP == 12
    assert EFFECTIVE_KNOWLEDGE_TOTAL_BODY_KIB == 24
