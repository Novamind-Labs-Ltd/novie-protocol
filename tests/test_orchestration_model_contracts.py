from __future__ import annotations

from datetime import UTC, datetime

import pytest
from novie_protocol.contracts import (
    ExecutionPlan,
    ExecutionStep,
    Intent,
    PmsIssueSnapshot,
    assert_plan_mutation_principal,
    assert_plan_session_immutable,
    project_plan_graph,
    project_pms_work_item,
)


def test_project_plan_graph_exposes_step_routing_contract() -> None:
    plan = ExecutionPlan(
        plan_id="plan-1",
        pattern="dag",
        mode="mixed",
        metadata={
            "planner_notes": "route research direct, coding staged",
            "artifacts_out": ("report-1",),
        },
        steps=(
            ExecutionStep(
                step_id="research",
                required_capabilities=("cap.research",),
                execution_mode="direct",
                routing_target="analyst",
                metadata={"title": "Research", "kind": "analysis"},
            ),
            ExecutionStep(
                step_id="code",
                required_capabilities=("cap.code",),
                depends_on=("research",),
                execution_mode="staged_pms",
                routing_target="cortex",
                metadata={"title": "Implement", "kind": "coding"},
                execution_context_seed={"artifact_ids": ["report-1"]},
            ),
        ),
    )

    graph = project_plan_graph(
        plan=plan,
        intent_id="intent-1",
        goal_summary="Competitive report + implementation ticket",
    )

    assert graph["plan_id"] == "plan-1"
    assert graph["intent_id"] == "intent-1"
    assert graph["mode"] == "mixed"
    assert graph["artifacts_out"] == ("report-1",)
    assert graph["planner_notes"] == "route research direct, coding staged"
    assert len(graph["steps"]) == 2
    assert graph["steps"][0]["execution_mode"] == "direct"
    assert graph["steps"][1]["execution_mode"] == "staged_pms"
    assert graph["edges"] == (
        {"from_step_id": "research", "to_step_id": "code"},
    )


def test_project_pms_work_item_preserves_provenance_flags() -> None:
    snapshot = PmsIssueSnapshot(
        issue_id="iss-1",
        identifier="NOV-1",
        project_id="project-1",
        workspace_id="workspace-1",
        tenant_id="tenant-1",
        title="Manual backlog item",
        description="desc",
        acceptance_criteria=(),
        priority=3,
        state="Backlog",
        labels=(),
        blocked_by=(),
        assignee_id="",
        assignee_name="",
        estimate=None,
        parent_id="",
        parent_identifier="",
        cycle_id="",
        branch_name="",
        linked_pr_urls=(),
        target_repo="owner/repo",
        target_branch="main",
        metadata={
            "source_step_id": "",
            "source_plan_id": "",
            "human_created": True,
            "planner_generated": False,
            "execution_context_seed": {"notes": "manual"},
        },
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    item = project_pms_work_item(snapshot)

    assert item.pms_issue_id == "iss-1"
    assert item.project_id == "project-1"
    assert item.human_created is True
    assert item.planner_generated is False
    assert item.execution_context_seed == {"notes": "manual"}


def test_intent_artifacts_in_normalizes_to_tuple() -> None:
    intent = Intent(
        intent_id="intent-1",
        session_id="session-1",
        principal_id="user-1",
        project_id="project-1",
        artifacts_in=["a1", "a2"],
    )
    assert intent.artifacts_in == ("a1", "a2")


# ── ADR-027 plan mutation auth ────────────────────────────────────────


def test_execution_plan_creator_fields_default_empty() -> None:
    plan = ExecutionPlan(
        plan_id="plan-default",
        pattern="single",
        steps=(ExecutionStep(step_id="s1", required_capabilities=("cap.x",)),),
    )
    assert plan.creator_principal_id == ""
    assert plan.creator_session_id == ""


def test_execution_plan_creator_fields_round_trip() -> None:
    plan = ExecutionPlan(
        plan_id="plan-attributed",
        pattern="single",
        steps=(ExecutionStep(step_id="s1", required_capabilities=("cap.x",)),),
        creator_principal_id="user-42",
        creator_session_id="sess-7",
    )
    assert plan.creator_principal_id == "user-42"
    assert plan.creator_session_id == "sess-7"


def test_assert_plan_mutation_principal_accepts_match() -> None:
    assert_plan_mutation_principal(
        creator_principal_id="user-1",
        caller_principal_id="user-1",
        op="cancel_plan",
    )


def test_assert_plan_mutation_principal_accepts_system_caller() -> None:
    # Platform-internal background mutation (auto re-plan, TTL sweep,
    # doctor) is trusted regardless of the original creator.
    assert_plan_mutation_principal(
        creator_principal_id="user-1",
        caller_principal_id="system:auto-replan",
        op="replan",
    )


def test_assert_plan_mutation_principal_rejects_foreign_caller() -> None:
    with pytest.raises(PermissionError, match="plan mutation denied"):
        assert_plan_mutation_principal(
            creator_principal_id="user-owner",
            caller_principal_id="user-intruder",
            op="cancel_plan",
        )


def test_assert_plan_mutation_principal_fails_open_for_legacy_plan() -> None:
    # ``creator_principal_id == ""`` marks a legacy plan with no
    # attribution — fail-open during the migration window.
    assert_plan_mutation_principal(
        creator_principal_id="",
        caller_principal_id="user-anyone",
        op="cancel_plan",
    )


# ── ADR-027 plan_creator_session_id_immutable ────────────────────────


def test_assert_plan_session_immutable_accepts_match() -> None:
    assert_plan_session_immutable(
        prior_session_id="sess-7",
        new_session_id="sess-7",
        op="replan",
    )


def test_assert_plan_session_immutable_rejects_session_swap() -> None:
    with pytest.raises(PermissionError, match="plan session immutability denied"):
        assert_plan_session_immutable(
            prior_session_id="sess-original",
            new_session_id="sess-intruder",
            op="replan",
        )


def test_assert_plan_session_immutable_fails_open_for_legacy_plan() -> None:
    # ``prior_session_id == ""`` marks a legacy plan; allow rebinding
    # during the migration window per the docstring contract.
    assert_plan_session_immutable(
        prior_session_id="",
        new_session_id="sess-new",
        op="patch",
    )


def test_assert_plan_session_immutable_records_op_in_error() -> None:
    with pytest.raises(PermissionError) as exc:
        assert_plan_session_immutable(
            prior_session_id="sess-original",
            new_session_id="sess-other",
            op="patch",
        )
    msg = str(exc.value)
    assert "op=patch" in msg
    assert "sess-original" in msg
    assert "sess-other" in msg
