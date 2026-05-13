"""W1 of SKILL_TIERED_MANAGEMENT — Skill data-model contract tests."""
# ruff: noqa: I001
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from novie_protocol.contracts import (
    EFFECTIVE_SKILL_COUNT_CAP,
    EFFECTIVE_SKILL_TOTAL_BODY_KIB,
    EffectiveSkillSet,
    SKILL_BODY_HARD_KIB,
    SKILL_BODY_MAX_KIB,
    Skill,
    SkillValidationError,
)


def _skill(**overrides) -> Skill:
    base = {
        "skill_id": "org:tenant-a:report-tone",
        "scope": "organization",
        "scope_ref": "tenant-a",
        "name": "report-tone",
        "description": "House style for reports",
        "body_markdown": "Use plain English. No emoji.",
    }
    base.update(overrides)
    return Skill(**base)


# ── Three scope variants ────────────────────────────────────────────


def test_organization_scope_round_trips() -> None:
    skill = _skill()
    out = Skill.from_dict(skill.to_dict())
    assert out == skill


def test_project_scope_round_trips() -> None:
    skill = _skill(
        skill_id="project:proj-1:linting",
        scope="project",
        scope_ref="proj-1",
        name="linting",
    )
    out = Skill.from_dict(skill.to_dict())
    assert out.scope == "project"
    assert out.scope_ref == "proj-1"


def test_personal_scope_round_trips() -> None:
    skill = _skill(
        skill_id="user:u-7:short-replies",
        scope="personal",
        scope_ref="u-7",
        name="short-replies",
    )
    out = Skill.from_dict(skill.to_dict())
    assert out.scope == "personal"


# ── Validation ───────────────────────────────────────────────────────


def test_invalid_scope_rejected() -> None:
    with pytest.raises(SkillValidationError, match="invalid scope"):
        _skill(scope="planet")  # type: ignore[arg-type]


def test_empty_scope_ref_rejected() -> None:
    with pytest.raises(SkillValidationError, match="scope_ref is required"):
        _skill(scope_ref="")


def test_empty_skill_id_rejected() -> None:
    with pytest.raises(SkillValidationError, match="skill_id is required"):
        _skill(skill_id="")


def test_body_over_hard_cap_rejected() -> None:
    huge = "x" * (SKILL_BODY_HARD_KIB * 1024 + 1)
    with pytest.raises(SkillValidationError, match="hard cap is 64 KiB"):
        _skill(body_markdown=huge)


def test_body_over_soft_cap_warns_but_accepts() -> None:
    body = "y" * (SKILL_BODY_MAX_KIB * 1024 + 1)
    skill = _skill(body_markdown=body)
    warning = skill.body_oversized_warning()
    assert warning is not None
    assert "16 KiB" in warning


def test_body_under_soft_cap_no_warning() -> None:
    skill = _skill(body_markdown="Short body")
    assert skill.body_oversized_warning() is None


def test_empty_allowed_consumers_rejected() -> None:
    with pytest.raises(SkillValidationError, match="allowed_consumers cannot be empty"):
        Skill(
            skill_id="org:tenant-a:x",
            scope="organization",
            scope_ref="tenant-a",
            name="x",
            description="",
            body_markdown="",
            allowed_consumers=frozenset(),
        )


# ── allowed_consumers filter shape ───────────────────────────────────


def test_default_allowed_consumers_is_all_three() -> None:
    skill = _skill()
    assert skill.allowed_consumers == frozenset(
        {"reception", "planner", "agents"},
    )


def test_reception_only_skill_round_trips_with_subset() -> None:
    skill = _skill(allowed_consumers=frozenset({"reception"}))
    out = Skill.from_dict(skill.to_dict())
    assert out.allowed_consumers == frozenset({"reception"})


# ── EffectiveSkillSet ────────────────────────────────────────────────


def test_effective_skill_set_round_trips() -> None:
    skill = _skill()
    eff = EffectiveSkillSet(
        consumer="reception", skills=(skill,), snapshot_ref="sha:abc",
    )
    payload = eff.to_dict()
    assert payload["consumer"] == "reception"
    assert payload["skills"][0]["skill_id"] == skill.skill_id
    assert payload["snapshot_ref"] == "sha:abc"


def test_caps_constants_match_documented_defaults() -> None:
    """Lock the cap constants so a future refactor that changes them
    forces an explicit discussion (these flow into prompt-budget
    accounting everywhere)."""
    assert EFFECTIVE_SKILL_COUNT_CAP == 8
    assert EFFECTIVE_SKILL_TOTAL_BODY_KIB == 32


# ── Timestamps round-trip via ISO format ────────────────────────────


def test_timestamps_round_trip() -> None:
    now = datetime(2026, 5, 11, 12, 0, 0, tzinfo=UTC)
    skill = _skill(created_at=now, updated_at=now)
    out = Skill.from_dict(skill.to_dict())
    assert out.created_at == now
    assert out.updated_at == now
