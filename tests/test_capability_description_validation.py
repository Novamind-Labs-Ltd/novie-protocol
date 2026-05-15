"""Unit tests for capability description quality gate.

The RoutingReplanner's accuracy depends on every capability having a
substantive description, so we reject thin descriptions at registration
time. These tests pin the rules and the per-case error messages.
"""
from __future__ import annotations

from novie_protocol.contracts.capability import (
    AgentCapabilityManifestEntry,
    CapabilityGovernance,
    validate_capability_description,
)


def _entry(
    *, description: str, display_name: str = "Cortex bundle",
) -> AgentCapabilityManifestEntry:
    return AgentCapabilityManifestEntry(
        capability_id="agent.cortex.execute_task_bundle",
        version="1.0.0",
        display_name=display_name,
        description=description,
        input_schema={},
        output_schema={},
        risk="medium",
        side_effect="repo_mutation",
        exec_kind="batch",
        runtime_ref="runtime://cortex",
        governance=CapabilityGovernance(),
    )


def test_rich_description_passes() -> None:
    entry = _entry(
        description=(
            "Implements code changes, runs the project's test suite, "
            "and opens a draft pull request against the target branch."
        ),
    )
    assert validate_capability_description(entry) == []


def test_too_short_description_rejected() -> None:
    entry = _entry(description="writes code")  # 11 chars
    errors = validate_capability_description(entry)
    assert len(errors) == 1
    assert "too short" in errors[0]
    assert "agent.cortex.execute_task_bundle" in errors[0]


def test_boundary_description_passes() -> None:
    # Exactly 30 chars — at the threshold.
    desc = "X" * 30
    entry = _entry(description=desc)
    assert validate_capability_description(entry) == []


def test_just_under_boundary_rejected() -> None:
    # 29 chars — just under threshold.
    desc = "X" * 29
    entry = _entry(description=desc)
    errors = validate_capability_description(entry)
    assert len(errors) == 1
    assert "too short" in errors[0]


def test_empty_description_rejected() -> None:
    entry = _entry(description="")
    errors = validate_capability_description(entry)
    assert len(errors) == 1
    assert "too short" in errors[0]


def test_whitespace_only_description_rejected() -> None:
    # Stripped length controls the gate — pure whitespace counts as 0 chars.
    entry = _entry(description="   \n\t   ")
    errors = validate_capability_description(entry)
    assert len(errors) == 1
    assert "too short" in errors[0]


def test_description_equal_to_display_name_rejected() -> None:
    long_name = "Implements code changes, runs tests, opens a draft pull request"
    entry = _entry(display_name=long_name, description=long_name)
    errors = validate_capability_description(entry)
    assert len(errors) == 1
    assert "duplicates display_name" in errors[0]


def test_description_equal_to_display_name_case_insensitive() -> None:
    name = "Implements code changes, runs tests, opens a draft pull request"
    entry = _entry(display_name=name.upper(), description=name.lower())
    errors = validate_capability_description(entry)
    assert len(errors) == 1
    assert "duplicates display_name" in errors[0]
