from __future__ import annotations

from datetime import datetime, timezone

import pytest

from novie_protocol.contracts.capability_invocation import CapabilityInvocationRequest
from novie_protocol.contracts import (
    ExecutionContext,
    IdentityContext,
    RunCorrelation,
    TenantScope,
    WorkflowStreamEvent,
    new_session_event,
    project_workflow_stream_event,
)


def _correlation() -> RunCorrelation:
    return RunCorrelation(
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        project_id="project-1",
        principal_id="user-1",
        session_id="session-1",
        turn_id="turn-1",
        root_run_id="root-1",
        thread_id="thread-1",
        request_id="request-1",
    )


def test_run_correlation_requires_root_scope_and_turn() -> None:
    with pytest.raises(ValueError, match="root_run_id"):
        RunCorrelation(
            tenant_id="tenant-1",
            workspace_id="workspace-1",
            project_id="project-1",
            principal_id="user-1",
            session_id="session-1",
            turn_id="turn-1",
            root_run_id="",
            thread_id="thread-1",
            request_id="request-1",
        )


def test_run_correlation_derivations_preserve_root_and_scope() -> None:
    root = _correlation()

    derived = (
        root.with_workflow("workflow-1", workflow_run_id="run-1")
        .with_attempt("attempt-1")
        .with_entity(
            entity_type="artifact",
            entity_id="artifact-1",
            causation_event_id="event-1",
        )
    )

    assert derived.tenant_id == root.tenant_id
    assert derived.workspace_id == root.workspace_id
    assert derived.session_id == root.session_id
    assert derived.root_run_id == root.root_run_id
    assert derived.workflow_id == "workflow-1"
    assert derived.workflow_run_id == "run-1"
    assert derived.attempt_id == "attempt-1"
    assert derived.entity_type == "artifact"
    assert derived.entity_id == "artifact-1"


def test_execution_context_and_session_event_carry_optional_correlation() -> None:
    correlation = _correlation()
    ctx = ExecutionContext(
        request_id="request-1",
        session_id="session-1",
        thread_id="thread-1",
        tenant=TenantScope(tenant_id="tenant-1", workspace_id="workspace-1"),
        identity=IdentityContext(principal_id="user-1", principal_type="user"),
        correlation=correlation,
    )

    fork = ctx.fork("thread-2", "checkpoint-1")
    event = new_session_event(ctx=ctx, source="chat", kind="turn.accepted")

    assert fork.correlation is correlation
    assert event.correlation is correlation


def test_invocation_and_workflow_stream_envelopes_accept_correlation() -> None:
    correlation = _correlation().with_workflow("workflow-1")
    request = CapabilityInvocationRequest(
        capability_id="cap.test",
        provider_id="provider.test",
        mode="execute",
        run_correlation=correlation,
    )
    stream_event = WorkflowStreamEvent(
        seq=1,
        event_id="event-1",
        occurred_at=datetime.now(timezone.utc),
        plan_id="plan-1",
        session_id="session-1",
        kind="run_status",
        run_correlation=correlation,
    )

    assert request.run_correlation is correlation
    assert stream_event.run_correlation is correlation


def test_workflow_stream_projection_preserves_session_event_correlation() -> None:
    correlation = _correlation().with_workflow("workflow-1")
    ctx = ExecutionContext(
        request_id="request-1",
        session_id="session-1",
        thread_id="thread-1",
        tenant=TenantScope(tenant_id="tenant-1", workspace_id="workspace-1"),
        identity=IdentityContext(principal_id="user-1", principal_type="user"),
        correlation=correlation,
    )
    event = new_session_event(
        ctx=ctx,
        source="dispatch",
        kind="plan_complete",
        payload={"plan_id": "plan-1"},
    )

    projected = project_workflow_stream_event(event, plan_id="plan-1")

    assert projected is not None
    assert projected.run_correlation is correlation
