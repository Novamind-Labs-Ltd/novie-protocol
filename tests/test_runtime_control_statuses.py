from __future__ import annotations

from typing import get_args

from novie_protocol.contracts.runtime_control import (
    RunStatus,
    RuntimeRun,
    RuntimeStep,
    StepStatus,
)


def test_run_status_accepts_adr054_lifecycle_values() -> None:
    values = set(get_args(RunStatus))

    assert {
        "pending",
        "planning",
        "compiled",
        "gate_pending",
        "finalizing",
        "timed_out",
    }.issubset(values)
    assert "waiting_human" in values

    run = RuntimeRun(
        run_id="run-1",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        run_kind="execution",
        status="gate_pending",
    )

    assert run.status == "gate_pending"


def test_step_status_accepts_adr054_lifecycle_values() -> None:
    values = set(get_args(StepStatus))

    assert {
        "ready",
        "gate_pending",
        "output_available",
        "finalizing",
        "timed_out",
    }.issubset(values)
    assert "waiting_human" in values

    step = RuntimeStep(
        step_id="s1",
        run_id="run-1",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        status="gate_pending",
    )

    assert step.status == "gate_pending"


def test_waiting_human_remains_a_compatibility_alias_for_one_release() -> None:
    run = RuntimeRun(
        run_id="run-1",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        run_kind="execution",
        status="waiting_human",
    )
    step = RuntimeStep(
        step_id="s1",
        run_id="run-1",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        status="waiting_human",
    )

    assert run.status == "waiting_human"
    assert step.status == "waiting_human"
