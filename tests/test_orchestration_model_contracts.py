from __future__ import annotations

from datetime import UTC, datetime

from novie_protocol.contracts import (
    ExecutionPlan,
    ExecutionStep,
    Intent,
    PmsIssueSnapshot,
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
