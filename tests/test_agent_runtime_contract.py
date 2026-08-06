"""The unified Agent Runtime Contract (ADR-133).

These tests defend the property the contract exists for: a payload that is
wrong is wrong *at parse time*, in the process that built it — not four hops
later disguised as an unrelated timeout.
"""

from __future__ import annotations

import pytest

from novie_protocol.contracts.agent_runtime import (
    AgentRunContractError,
    AgentRunInput,
    AgentRunResult,
    ExecutionMandate,
    SkillRef,
    WorkspaceDescriptor,
    parse_run_input,
)


def _mandate() -> ExecutionMandate:
    return ExecutionMandate(
        repository_ref="octocat/Hello-World",
        repository_revision="master",
        side_effects=("workspace.read", "workspace.write"),
        max_cost_usd=5.0,
        max_steps=50,
    )


def test_work_order_survives_a_round_trip() -> None:
    run = AgentRunInput(
        objective="add a draft-autosave button",
        instructions=("only touch the chat input component",),
        skills=(SkillRef(skill_id="frontend.react", version="2"),),
        capabilities=("platform.sandbox.execute_work_unit",),
        workspace=WorkspaceDescriptor(
            repository_ref="octocat/Hello-World",
            commit_sha="cafe",
            files=({"path": "README.md", "content": "hi\n"},),
        ),
        mandate=_mandate(),
        inputs={"acceptance": "tests pass"},
    )

    parsed = parse_run_input(run.to_wire())

    assert parsed.objective == run.objective
    assert parsed.instructions == run.instructions
    assert parsed.skills[0].skill_id == "frontend.react"
    assert parsed.capabilities == ("platform.sandbox.execute_work_unit",)
    assert parsed.workspace is not None
    assert parsed.workspace.files[0]["path"] == "README.md"
    assert parsed.mandate == run.mandate
    # Free-form task payload rides along without colliding with contract fields.
    assert parsed.inputs["acceptance"] == "tests pass"


@pytest.mark.parametrize(
    "stray",
    ["repository_ref", "workspace_files", "objective", "commit_sha", "capabilities"],
)
def test_a_contract_field_at_the_envelope_top_level_is_rejected(stray: str) -> None:
    """The exact defect this contract was extracted to kill.

    The platform put the repository at the envelope's top level while the wire
    contract read it from ``brief``. The field vanished, the agent ran with no
    repository, and the only symptom was a ten-minute timeout.
    """
    envelope = {"brief": {"objective": "do the thing"}, stray: "value"}

    with pytest.raises(AgentRunContractError) as caught:
        parse_run_input(envelope)

    assert stray in str(caught.value)
    assert "brief" in str(caught.value)


def test_a_missing_body_is_rejected_rather_than_defaulted() -> None:
    with pytest.raises(AgentRunContractError, match="no 'brief' body"):
        parse_run_input({"constraints": {}})


def test_an_empty_objective_is_rejected() -> None:
    with pytest.raises(AgentRunContractError, match="objective"):
        parse_run_input({"brief": {"objective": "   "}})


def test_an_incompatible_major_schema_version_is_refused() -> None:
    with pytest.raises(AgentRunContractError, match="schema_version"):
        parse_run_input({"brief": {"objective": "x", "schema_version": "2.0"}})


def test_a_compatible_minor_version_is_accepted() -> None:
    parsed = parse_run_input({"brief": {"objective": "x", "schema_version": "1.7"}})
    assert parsed.schema_version == "1.7"


def test_mandate_denies_everything_it_does_not_name() -> None:
    mandate = _mandate()
    assert mandate.allows("workspace.write") is True
    assert mandate.allows("repo.pull_request") is False
    assert mandate.allows("deploy.preview") is False


def test_an_invented_side_effect_class_is_rejected() -> None:
    """A mandate cannot grant a permission the platform does not model."""
    with pytest.raises(AgentRunContractError, match="unknown side-effect"):
        ExecutionMandate.from_mapping({"side_effects": ["repo.force_push"]})


def test_mandate_round_trips_through_the_constraints_slot() -> None:
    wire = AgentRunInput(objective="x", mandate=_mandate()).to_wire()
    assert wire["constraints"]["max_cost_usd"] == 5.0
    assert ExecutionMandate.from_mapping(wire["constraints"]) == _mandate()


def test_completion_report_round_trips() -> None:
    result = AgentRunResult(
        status="completed",
        artifacts=({"kind": "diff", "ref": "art-1"},),
        evidence=({"kind": "test_report", "passed": 34},),
        capability_calls=({"capability_id": "platform.sandbox.execute_work_unit"},),
        usage={"cost_usd": 1.2},
    )

    assert AgentRunResult.from_mapping(result.to_dict()) == result


def test_an_unknown_status_is_rejected_rather_than_read_as_success() -> None:
    with pytest.raises(AgentRunContractError, match="completed"):
        AgentRunResult.from_mapping({"status": "done"})


def test_a_blocked_run_is_a_first_class_outcome() -> None:
    """Blocked is neither success nor failure: the loop needs to tell them apart."""
    blocked = AgentRunResult.from_mapping(
        {"status": "blocked", "suggested_next_action": "connect the GitHub App"}
    )
    assert blocked.status == "blocked"
    assert blocked.suggested_next_action == "connect the GitHub App"


def test_the_workspace_carries_content_and_never_a_credential() -> None:
    """ADR-070: the executor receives files, not a token or a clone URL."""
    workspace = WorkspaceDescriptor(
        repository_ref="octocat/Hello-World",
        commit_sha="cafe",
        files=({"path": "a.py", "content": "x = 1\n"},),
    )
    flat = repr(
        AgentRunInput(objective="x", workspace=workspace, mandate=_mandate()).to_wire()
    )
    for forbidden in ("token", "x-access-token", "password", "credential"):
        assert forbidden not in flat


@pytest.mark.parametrize(
    ("stray", "canonical"),
    [
        ("workspace_files", "brief.workspace.files"),
        ("commit_sha", "brief.workspace.commit_sha"),
        ("repository_ref", "constraints.repository_ref"),
    ],
)
def test_a_pre_contract_field_inside_the_body_is_rejected(
    stray: str, canonical: str
) -> None:
    """Two homes for one fact is the problem; accepting the old one keeps it."""
    with pytest.raises(AgentRunContractError) as caught:
        parse_run_input(
            {"brief": {"schema_version": "1.0", "objective": "x", stray: "v"}}
        )

    assert stray in str(caught.value)
    assert canonical in str(caught.value)
