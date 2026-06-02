from __future__ import annotations

from novie_protocol.contracts import (
    AgentCapabilityManifestEntry,
    CapabilityInputContract,
)


def test_capability_input_contracts_round_trip() -> None:
    entry = AgentCapabilityManifestEntry(
        capability_id="agent.novie-cortex.execute_task_bundle",
        version="1.0.0",
        display_name="Execute Task Bundle",
        description="Execute an approved PMS ticket against a project repository.",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        risk="write",
        side_effect="external",
        exec_kind="async",
        runtime_ref="agent:novie-cortex:execute_task_bundle",
        consumes=("task_bundle", "project.repo.default"),
        provides=("implementation_result", "code_changes"),
        input_contracts=(
            CapabilityInputContract(
                artifact="task_bundle",
                source="runtime_context",
                provider="platform.pms.ticket_execution",
            ),
            CapabilityInputContract(
                artifact="project.repo.default",
                source="runtime_context",
                provider="platform.project_context.repo_default",
            ),
        ),
    )

    parsed = AgentCapabilityManifestEntry.from_dict(entry.to_dict())

    assert parsed.input_contracts == entry.input_contracts
    assert parsed.to_dict()["input_contracts"] == [
        {
            "artifact": "task_bundle",
            "source": "runtime_context",
            "required": True,
            "provider": "platform.pms.ticket_execution",
        },
        {
            "artifact": "project.repo.default",
            "source": "runtime_context",
            "required": True,
            "provider": "platform.project_context.repo_default",
        },
    ]
