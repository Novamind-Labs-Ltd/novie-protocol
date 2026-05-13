"""W1 of PROJECT_BLUEPRINT — schema contract tests."""
# ruff: noqa: I001
from __future__ import annotations

import pytest

from novie_protocol.contracts import (
    BlueprintCapabilityBindings,
    BlueprintDefaults,
    BlueprintIssue,
    BlueprintKnowledgeSeed,
    BlueprintTracker,
    BlueprintValidationError,
    ProjectBlueprint,
)


def _blueprint(**overrides) -> ProjectBlueprint:
    base = dict(
        id="engineering_delivery",
        name="Engineering Delivery",
        version="1.0.0",
    )
    base.update(overrides)
    return ProjectBlueprint(**base)


# ── Required-field validation ───────────────────────────────────────


def test_id_required() -> None:
    with pytest.raises(BlueprintValidationError, match="id is required"):
        _blueprint(id="")


def test_name_required() -> None:
    with pytest.raises(BlueprintValidationError, match="name is required"):
        _blueprint(name="")


def test_invalid_semver_rejected() -> None:
    with pytest.raises(BlueprintValidationError, match="not semver"):
        _blueprint(version="1.0")


def test_invalid_mode_rejected() -> None:
    with pytest.raises(BlueprintValidationError, match="invalid mode"):
        _blueprint(mode="experimental")  # type: ignore[arg-type]


# ── Capability binding overlap ──────────────────────────────────────


def test_overlapping_enabled_disabled_rejected() -> None:
    with pytest.raises(BlueprintValidationError, match="overlap"):
        _blueprint(
            capability_bindings=BlueprintCapabilityBindings(
                enabled=("a", "b"), disabled=("b", "c"),
            ),
        )


def test_disjoint_enabled_disabled_ok() -> None:
    bp = _blueprint(
        capability_bindings=BlueprintCapabilityBindings(
            enabled=("a", "b"), disabled=("c", "d"),
        ),
    )
    assert bp.capability_bindings.enabled == ("a", "b")


# ── Starter issue / lane consistency ────────────────────────────────


def test_starter_issue_lane_must_exist_in_tracker_lanes() -> None:
    with pytest.raises(BlueprintValidationError, match="not declared in tracker.lanes"):
        _blueprint(
            tracker=BlueprintTracker(lanes=("Todo", "In Progress")),
            starter_issues=(
                BlueprintIssue(title="task", lane="Done"),
            ),
        )


def test_starter_issue_lane_in_tracker_ok() -> None:
    bp = _blueprint(
        tracker=BlueprintTracker(lanes=("Todo", "Done")),
        starter_issues=(BlueprintIssue(title="task", lane="Todo"),),
    )
    assert bp.starter_issues[0].lane == "Todo"


def test_starter_issue_without_lane_ok_even_when_tracker_lanes_set() -> None:
    bp = _blueprint(
        tracker=BlueprintTracker(lanes=("Todo",)),
        starter_issues=(BlueprintIssue(title="task"),),
    )
    assert bp.starter_issues[0].lane == ""


# ── from_dict round trip ────────────────────────────────────────────


def test_full_blueprint_from_dict() -> None:
    payload = {
        "id": "engineering_delivery",
        "name": "Engineering Delivery",
        "version": "1.2.3",
        "description": "Standard delivery project.",
        "defaults": {
            "effective_template_id": "engineering_delivery",
            "effective_view_hint": "board_first",
            "governance_policy_ref": "standard_repo_writes",
        },
        "agents_enabled": ["agent.cortex.execute"],
        "skills_enabled": ["org:t:tone"],
        "knowledge_seeds": [
            {"source": "https://docs.example.com", "namespace_alias": "docs"},
        ],
        "tracker": {
            "lanes": ["Todo", "In Progress", "Done"],
            "default_issue_template": "user_story",
        },
        "starter_issues": [
            {"title": "Set up CI", "lane": "Todo", "labels": ["infra"]},
        ],
        "capability_bindings": {
            "enabled": ["platform.pms.issue.move"],
        },
    }
    bp = ProjectBlueprint.from_dict(payload)
    assert bp.id == "engineering_delivery"
    assert bp.version == "1.2.3"
    assert bp.defaults.effective_template_id == "engineering_delivery"
    assert bp.agents_enabled == ("agent.cortex.execute",)
    assert bp.knowledge_seeds[0].source == "https://docs.example.com"
    assert bp.tracker.lanes == ("Todo", "In Progress", "Done")
    assert bp.starter_issues[0].labels == ("infra",)


def test_empty_blank_blueprint_ok() -> None:
    """A "blank" blueprint with only id/name/version is valid — used
    for the empty starter that a tenant can apply to skip every
    section."""
    bp = ProjectBlueprint.from_dict({
        "id": "blank", "name": "Blank", "version": "1.0.0",
    })
    assert bp.agents_enabled == ()
    assert bp.tracker.lanes == ()


def test_summary_projection() -> None:
    bp = _blueprint(description="A test blueprint.")
    s = bp.summary
    assert s.id == "engineering_delivery"
    assert s.description == "A test blueprint."
