"""Phase 0 contract freeze tests for canonical PMS workbench DTOs.

Verifies the agent-facing canonical shape declared in
``docs/plans/2026-05-08-pms-workbench-capability-todo.md`` and the
status-mapping rules decided 2026-05-10 (workspace default + per-project
override; stage-first matching with title fallback).
"""
from __future__ import annotations

import pytest

from novie_protocol.contracts import (
    DEFAULT_TITLE_TO_STAGE,
    PmsAssigneeRef,
    PmsCycleRef,
    PmsIssue,
    PmsIssueComment,
    PmsIssueDraft,
    PmsIssueLink,
    PmsIssueStatus,
    PmsIssueStatusChange,
    PmsIssueUpdate,
    PmsProjectRef,
    StatusMapping,
    stage_for_title,
)


# ---------------------------------------------------------------------------
# Canonical issue read shape
# ---------------------------------------------------------------------------


def test_pms_issue_minimum_shape_matches_contract_doc() -> None:
    issue = PmsIssue(
        id="iss-1",
        identifier="NOV-42",
        title="Add capability adapter",
        description="...",
        status=PmsIssueStatus(title="Todo", stage="unstarted"),
        project=PmsProjectRef(id="proj-1", title="Novie", identifier="NOV"),
        tenant_id="tenant-1",
        workspace_id="ws-1",
    )

    # Canonical fields declared in the TODO file are all present and correctly
    # typed; defaults are stable so adapters can rely on them.
    assert issue.priority == 3
    assert issue.labels == ()
    assert issue.assignee is None
    assert issue.cycle is None
    assert issue.branch_name is None
    assert issue.linked_pull_request_urls == ()
    assert issue.metadata == {}


def test_pms_issue_normalizes_iterables_to_tuples() -> None:
    issue = PmsIssue(
        id="iss-1",
        identifier="NOV-42",
        title="t",
        description="",
        status=PmsIssueStatus(title="Todo", stage="unstarted"),
        project=PmsProjectRef(id="proj-1"),
        tenant_id="t",
        workspace_id="w",
        labels=["bug", "p0"],  # caller passed a list
        linked_pull_request_urls=["https://example/pr/1"],
    )

    assert isinstance(issue.labels, tuple)
    assert isinstance(issue.linked_pull_request_urls, tuple)


# ---------------------------------------------------------------------------
# Status change input
# ---------------------------------------------------------------------------


def test_status_change_requires_title_or_stage() -> None:
    with pytest.raises(ValueError, match="target_status_title or target_stage"):
        PmsIssueStatusChange(issue_id="iss-1")


def test_status_change_accepts_title_only() -> None:
    change = PmsIssueStatusChange(issue_id="iss-1", target_status_title="Todo")
    assert change.target_status_title == "Todo"
    assert change.target_stage is None


def test_status_change_accepts_stage_only() -> None:
    change = PmsIssueStatusChange(issue_id="iss-1", target_stage="started")
    assert change.target_stage == "started"
    assert change.target_status_title is None


# ---------------------------------------------------------------------------
# StatusMapping: stage-first matching, title fallback
# ---------------------------------------------------------------------------


def test_status_mapping_default_routes_started_to_execution_eligible() -> None:
    mapping = StatusMapping()
    todo = PmsIssueStatus(title="Todo", stage="started")

    assert mapping.is_execution_eligible(todo)
    assert not mapping.is_done(todo)


def test_status_mapping_falls_back_to_title_when_stage_misses() -> None:
    # Adapter exposes Todo as ``unstarted`` (not in default execution_eligible
    # stages), so matching must fall back to the title list.
    mapping = StatusMapping()
    todo = PmsIssueStatus(title="Todo", stage="unstarted")

    assert mapping.is_execution_eligible(todo)


def test_status_mapping_done_resolves_via_stage() -> None:
    mapping = StatusMapping()
    done = PmsIssueStatus(title="Shipped", stage="completed")

    # Custom title ("Shipped") is unknown but stage="completed" wins.
    assert mapping.is_done(done)
    assert not mapping.is_execution_eligible(done)


def test_status_mapping_canceled_resolves_via_stage() -> None:
    mapping = StatusMapping()
    canceled = PmsIssueStatus(title="Wontfix", stage="canceled")

    assert mapping.is_canceled(canceled)


# ---------------------------------------------------------------------------
# StatusMapping: per-project override merges (does not replace)
# ---------------------------------------------------------------------------


def test_per_project_override_unions_titles() -> None:
    workspace_default = StatusMapping()
    project_override = StatusMapping(
        execution_eligible_titles=("Ready to Code",),
    )

    merged = workspace_default.merge_override(project_override)

    # Workspace default ("Todo") preserved, project addition added.
    assert "Todo" in merged.execution_eligible_titles
    assert "Ready to Code" in merged.execution_eligible_titles


def test_per_project_override_does_not_duplicate() -> None:
    base = StatusMapping(execution_eligible_titles=("Todo",))
    override = StatusMapping(execution_eligible_titles=("Todo", "Ready"))

    merged = base.merge_override(override)

    # "Todo" appears exactly once.
    assert merged.execution_eligible_titles.count("Todo") == 1
    assert "Ready" in merged.execution_eligible_titles


def test_per_project_override_unions_stages() -> None:
    base = StatusMapping(human_review_stages=())
    override = StatusMapping(human_review_stages=("started",))

    merged = base.merge_override(override)

    assert "started" in merged.human_review_stages


# ---------------------------------------------------------------------------
# stage_for_title resolver
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Backlog", "unstarted"),
        ("Todo", "unstarted"),
        ("Ready to Code", "unstarted"),
        ("In Progress", "started"),
        ("Human Review", "started"),
        ("Done", "completed"),
        ("Cancelled", "canceled"),
        ("Canceled", "canceled"),  # American spelling tolerated
    ],
)
def test_default_title_to_stage_table(title: str, expected: str) -> None:
    assert DEFAULT_TITLE_TO_STAGE[title] == expected


def test_stage_for_title_falls_back_to_default_for_unknown() -> None:
    assert stage_for_title("Custom State") == "unstarted"
    assert stage_for_title("Custom State", default="started") == "started"


def test_stage_for_title_accepts_custom_table() -> None:
    custom = {"Shipped": "completed"}
    assert stage_for_title("Shipped", table=custom) == "completed"
    assert stage_for_title("Todo", table=custom) == "unstarted"  # default


# ---------------------------------------------------------------------------
# Write shapes
# ---------------------------------------------------------------------------


def test_pms_issue_draft_normalizes_labels() -> None:
    draft = PmsIssueDraft(
        project_id="proj-1",
        title="Implement adapter",
        labels=["arch", "p1"],
    )
    assert isinstance(draft.labels, tuple)


def test_pms_issue_update_partial_semantics() -> None:
    update = PmsIssueUpdate(issue_id="iss-1", title="New title")
    assert update.title == "New title"
    # Unspecified fields stay None — adapters interpret None as "do not change".
    assert update.description is None
    assert update.priority is None


def test_pms_issue_update_normalizes_labels_when_provided() -> None:
    update = PmsIssueUpdate(issue_id="iss-1", labels=["x", "y"])
    assert isinstance(update.labels, tuple)


# ---------------------------------------------------------------------------
# Comments / links
# ---------------------------------------------------------------------------


def test_pms_issue_comment_default_empty_metadata() -> None:
    comment = PmsIssueComment(body="LGTM")
    assert comment.metadata == {}
    # author_id is filled by the capability boundary, not the agent.
    assert comment.author_id == ""


def test_pms_issue_link_distinct_from_execution_link() -> None:
    # Workbench link (user-visible URL attachment) — must NOT be confused
    # with pms_lifecycle.PmsExecutionLink which is the workflow lease.
    link = PmsIssueLink(title="Design doc", url="https://example/design")
    assert link.url == "https://example/design"
    assert link.link_id == ""  # filled on read


# ---------------------------------------------------------------------------
# References
# ---------------------------------------------------------------------------


def test_assignee_ref_minimal() -> None:
    assignee = PmsAssigneeRef(id="user-1")
    assert assignee.name == ""
    assert assignee.email == ""


def test_cycle_ref_minimal() -> None:
    cycle = PmsCycleRef(id="cycle-1", number=3)
    assert cycle.title == ""
