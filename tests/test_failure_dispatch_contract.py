from __future__ import annotations

import pytest

from novie_protocol.contracts import DispatchEvent, ExecutionFailureRecord
from novie_protocol.contracts.workflow_stream import project_session_event_kind


def test_execution_failure_record_requires_closed_reason_code() -> None:
    record = ExecutionFailureRecord(
        record_id="fail-1",
        pms_issue_id="issue-1",
        execution_link_id="link-1",
        workflow_id="wf-1",
        workflow_run_id="run-1",
        failure_type="implementation_failed",
        reason_code="implementation_failed.agent_error",
    )

    assert record.reason_code == "implementation_failed.agent_error"


def test_execution_failure_record_rejects_empty_reason_code() -> None:
    with pytest.raises(ValueError, match="reason_code"):
        ExecutionFailureRecord(
            record_id="fail-1",
            pms_issue_id="issue-1",
            execution_link_id="link-1",
            workflow_id="wf-1",
            workflow_run_id="run-1",
            failure_type="implementation_failed",
            reason_code="",  # type: ignore[arg-type]
        )


def test_dispatch_error_events_require_failure_type() -> None:
    with pytest.raises(ValueError, match="failure_type"):
        DispatchEvent(kind="step_error", metadata={"step_id": "s1", "error": "boom"})

    event = DispatchEvent(
        kind="plan_error",
        metadata={"plan_id": "plan-1", "error": "boom", "failure_type": "delivery_blocked"},
    )
    assert event.metadata["failure_type"] == "delivery_blocked"


def test_dispatch_step_retry_event_is_constructible() -> None:
    event = DispatchEvent(
        kind="step_retry",
        metadata={
            "step_id": "s1",
            "agent_id": "agent-1",
            "attempt": 1,
            "max_retries": 3,
            "failure_type": "transient",
            "error": "temporary outage",
            "backoff_seconds": 1,
        },
    )

    assert event.kind == "step_retry"
    assert event.metadata["failure_type"] == "transient"


def test_step_retry_projects_as_step_status() -> None:
    assert project_session_event_kind("dispatch", "step_retry") == "step_status"


def test_dispatch_plan_replanned_event_is_constructible() -> None:
    event = DispatchEvent(
        kind="plan_replanned",
        metadata={
            "plan_id": "plan-1",
            "old_plan_version": "v1",
            "new_plan_version": "v2",
            "trigger_source": "auto_patch_exhausted",
            "reason": "delivery_blocked after snapshot patch cap",
        },
    )

    assert event.kind == "plan_replanned"
    assert event.metadata["new_plan_version"] == "v2"


def test_plan_replanned_projects_as_run_status() -> None:
    assert project_session_event_kind("dispatch", "plan_replanned") == "run_status"
