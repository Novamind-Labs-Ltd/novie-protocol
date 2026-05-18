from __future__ import annotations

from novie_protocol.contracts import (
    CapabilityDriftReportItem,
    CapabilityResolution,
    CapabilityResolutionSnapshot,
    CapabilityResolutionSnapshotPatch,
    PlanReplannedEvent,
    has_auto_replan_budget,
    has_snapshot_patch_budget,
)


def _resolution() -> CapabilityResolution:
    return CapabilityResolution(
        node_id="step-1",
        required_capability="agent.writer",
        resolved_runtime_ref="agent-runtime-1",
        resolved_capability_version="1.2.3",
        resolved_binding_id="binding-1",
    )


def test_capability_resolution_snapshot_new_fields_round_trip() -> None:
    snapshot = CapabilityResolutionSnapshot(
        plan_id="plan-1",
        frozen_at="2026-05-16T00:00:00Z",
        resolutions=(_resolution(),),
        runtime_context_snapshot_ref="runtime-context-1",
        snapshot_version="v2",
        predecessor_snapshot_version="v1",
        patch_attempt=1,
    )

    restored = CapabilityResolutionSnapshot.from_dict(snapshot.to_dict())

    assert restored.snapshot_version == "v2"
    assert restored.predecessor_snapshot_version == "v1"
    assert restored.patch_attempt == 1
    assert restored.resolutions[0].required_capability == "agent.writer"


def test_capability_resolution_snapshot_accepts_legacy_payload_defaults() -> None:
    restored = CapabilityResolutionSnapshot.from_dict(
        {
            "plan_id": "plan-1",
            "frozen_at": "2026-05-16T00:00:00Z",
            "resolutions": [_resolution().to_dict()],
        }
    )

    assert restored.snapshot_version == "v1"
    assert restored.predecessor_snapshot_version is None
    assert restored.patch_attempt == 0


def test_capability_resolution_snapshot_patch_round_trip() -> None:
    drift_item = CapabilityDriftReportItem(
        previous_capability_id="agent.writer",
        previous_version="1.2.3",
        current_status="stable",
        current_version="1.2.4",
        schema_compat="compatible",
        binding_status="active",
    )
    patch = CapabilityResolutionSnapshotPatch(
        patch_id="patch-1",
        plan_id="plan-1",
        from_snapshot_version="v1",
        to_snapshot_version="v2",
        trigger_source="manifest_patch_update",
        decision="auto_patch",
        reason="patch-level manifest update",
        patch_attempt=1,
        affected_step_ids=("step-1",),
        drift_items=(drift_item,),
    )

    restored = CapabilityResolutionSnapshotPatch.from_dict(patch.to_dict())

    assert restored.patch_id == "patch-1"
    assert restored.trigger_source == "manifest_patch_update"
    assert restored.decision == "auto_patch"
    assert restored.affected_step_ids == ("step-1",)
    assert restored.drift_items[0].current_version == "1.2.4"


def test_snapshot_patch_budget_default_cap_is_two_attempts() -> None:
    assert has_snapshot_patch_budget(0) is True
    assert has_snapshot_patch_budget(1) is True
    assert has_snapshot_patch_budget(2) is False


def test_plan_replanned_event_round_trip_and_budget() -> None:
    event = PlanReplannedEvent(
        plan_id="plan-1",
        old_plan_version="v1",
        new_plan_version="v2",
        trigger_source="auto_patch_exhausted",
        reason="snapshot patch cap exceeded",
        preserved_step_ids=("done-1",),
        replaced_step_ids=("failed-1", "downstream-1"),
    )

    restored = PlanReplannedEvent.from_dict(event.to_dict())

    assert restored.trigger_source == "auto_patch_exhausted"
    assert restored.preserved_step_ids == ("done-1",)
    assert restored.replaced_step_ids == ("failed-1", "downstream-1")
    assert has_auto_replan_budget(0) is True
    assert has_auto_replan_budget(1) is True
    assert has_auto_replan_budget(2) is False
