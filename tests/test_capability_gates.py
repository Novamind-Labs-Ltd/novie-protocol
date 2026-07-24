from __future__ import annotations

import pytest

from novie_protocol.contracts import (
    AgentCapabilityManifestEntry,
    CapabilityGateDeclaration,
    GateContentDeclaration,
    GateSpec,
)


def test_capability_gates_round_trip() -> None:
    entry = AgentCapabilityManifestEntry(
        capability_id="agent.architect.create_implementation_plan",
        version="1.0.0",
        display_name="Create implementation plan",
        description="Create an implementation plan before ticket authoring.",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        risk="read",
        side_effect="none",
        exec_kind="async",
        runtime_ref="agent:novie-architect:create_implementation_plan",
        gates=(
            CapabilityGateDeclaration(
                gate_key="output_review",
                timing="post_step",
                title="Review implementation plan",
                description="Approve the plan before ticket splitting.",
                allowed_actions=("allow", "request_changes", "reject"),
                required_approver_roles=("project_owner",),
                content=(
                    GateContentDeclaration(
                        kind="artifact_preview",
                        binding="output.implementation_plan_document",
                        block_id="implementation_plan",
                    ),
                ),
            ),
        ),
    )

    parsed = AgentCapabilityManifestEntry.from_dict(entry.to_dict())

    assert parsed.gates == entry.gates
    assert parsed.to_dict()["gates"] == [
        {
            "gate_key": "output_review",
            "timing": "post_step",
            "title": "Review implementation plan",
            "description": "Approve the plan before ticket splitting.",
            "required": True,
            "allowed_actions": ["allow", "request_changes", "reject"],
            "required_approver_roles": ["project_owner"],
            "content": [
                {
                    "kind": "artifact_preview",
                    "binding": "output.implementation_plan_document",
                    "block_id": "implementation_plan",
                }
            ],
            "payload_schema": {},
        }
    ]


def test_capability_manifest_without_gates_defaults_to_empty() -> None:
    entry = AgentCapabilityManifestEntry(
        capability_id="agent.architect.analyze",
        version="1.0.0",
        display_name="Analyze",
        description="Analyze a project.",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        risk="read",
        side_effect="none",
        exec_kind="async",
        runtime_ref="agent:novie-architect:analyze",
    )

    data = entry.to_dict()
    data.pop("gates")

    assert AgentCapabilityManifestEntry.from_dict(data).gates == ()


def test_pre_side_effect_gate_requires_declared_boundary() -> None:
    kwargs = {
        "capability_id": "agent.cortex.execute",
        "version": "1.0.0",
        "display_name": "Execute",
        "description": "Mutate a repository.",
        "input_schema": {"type": "object"},
        "output_schema": {"type": "object"},
        "risk": "write",
        "side_effect": "external",
        "exec_kind": "async",
        "runtime_ref": "agent:cortex:execute",
        "gates": (
            CapabilityGateDeclaration(
                gate_key="repository_mutation",
                timing="pre_side_effect",
                boundary_id="agent_invocation",
                title="Approve mutation",
                description="",
            ),
        ),
    }

    with pytest.raises(ValueError, match="side_effect boundary"):
        AgentCapabilityManifestEntry(**kwargs)

    entry = AgentCapabilityManifestEntry(
        **kwargs,
        side_effect_boundaries=("agent_invocation",),
    )
    assert entry.to_dict()["gates"][0]["boundary_id"] == "agent_invocation"


def test_gate_spec_preserves_capability_identity_round_trip() -> None:
    gate = GateSpec(
        gate_id="g-cap-s0-output-review-architect",
        gate_key="output_review",
        gate_lineage_id="g-cap-s0-output-review-architect",
        review_revision=2,
        anchor_step_id="s0",
        sources=("agent_declared",),
        source_refs=("agent.architect.create_implementation_plan",),
        timing="post_step",
        required=True,
        title="Review implementation plan",
        description="Approve before splitting tickets.",
        allowed_actions=("allow", "request_changes", "reject"),
        content=(
            GateContentDeclaration(
                kind="artifact_preview",
                binding="output.implementation_plan_document",
            ),
        ),
    )

    parsed = GateSpec.from_dict(gate.to_dict())

    assert parsed == gate
    assert parsed.after_step_id == "s0"
    assert parsed.to_dict()["anchor_step_id"] == "s0"


def test_gate_spec_loads_legacy_after_step_id_as_anchor() -> None:
    gate = GateSpec.from_dict(
        {
            "gate_id": "legacy-gate",
            "after_step_id": "s0",
            "sources": ["planner_suggested"],
            "title": "Confirm",
            "description": "",
        }
    )

    assert gate.anchor_step_id == "s0"
    assert gate.after_step_id == "s0"
    assert gate.timing == "pre_step"
    assert gate.gate_key == "legacy-gate"
