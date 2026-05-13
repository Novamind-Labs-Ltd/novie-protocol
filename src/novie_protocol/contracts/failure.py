from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


def new_failure_id(plan_id: str, step_id: str, attempt: int) -> str:
    safe_step = (step_id or "workflow").strip() or "workflow"
    safe_attempt = max(1, int(attempt or 1))
    return f"failure:{plan_id}:{safe_step}:{safe_attempt}"


@dataclass(frozen=True, slots=True)
class FailureEnvelope:
    """Structured failure context used by recovery and observability flows."""

    failure_id: str
    parent_plan_id: str
    workflow_id: str
    run_id: str
    failed_step_id: str
    failed_agent_id: str
    capability_ids: tuple[str, ...] = ()
    protocol_mode: str = ""
    protocol_entity: str = ""
    error_code: str = ""
    error_class: str = ""
    message: str = ""
    retryable: bool = False
    repair_eligible: bool = False
    replan_eligible: bool = False
    attempt: int = 1
    input_digest: str = ""
    upstream_artifact_refs: tuple[str, ...] = ()
    runtime_context_snapshot_ref: str = ""
    timeline_event_seq: int = 0
    logs_ref: str = ""
    classification: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "failure_id": self.failure_id,
            "parent_plan_id": self.parent_plan_id,
            "workflow_id": self.workflow_id,
            "run_id": self.run_id,
            "failed_step_id": self.failed_step_id,
            "failed_agent_id": self.failed_agent_id,
            "capability_ids": list(self.capability_ids),
            "protocol_mode": self.protocol_mode,
            "protocol_entity": self.protocol_entity,
            "error_code": self.error_code,
            "error_class": self.error_class,
            "message": self.message,
            "retryable": self.retryable,
            "repair_eligible": self.repair_eligible,
            "replan_eligible": self.replan_eligible,
            "attempt": self.attempt,
            "input_digest": self.input_digest,
            "upstream_artifact_refs": list(self.upstream_artifact_refs),
            "runtime_context_snapshot_ref": self.runtime_context_snapshot_ref,
            "timeline_event_seq": self.timeline_event_seq,
            "logs_ref": self.logs_ref,
            "classification": dict(self.classification),
            "metadata": dict(self.metadata),
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "FailureEnvelope":
        return cls(
            failure_id=str(payload.get("failure_id") or ""),
            parent_plan_id=str(payload.get("parent_plan_id") or ""),
            workflow_id=str(payload.get("workflow_id") or ""),
            run_id=str(payload.get("run_id") or ""),
            failed_step_id=str(payload.get("failed_step_id") or ""),
            failed_agent_id=str(payload.get("failed_agent_id") or ""),
            capability_ids=tuple(str(i) for i in payload.get("capability_ids") or ()),
            protocol_mode=str(payload.get("protocol_mode") or ""),
            protocol_entity=str(payload.get("protocol_entity") or ""),
            error_code=str(payload.get("error_code") or ""),
            error_class=str(payload.get("error_class") or ""),
            message=str(payload.get("message") or ""),
            retryable=bool(payload.get("retryable", False)),
            repair_eligible=bool(payload.get("repair_eligible", False)),
            replan_eligible=bool(payload.get("replan_eligible", False)),
            attempt=int(payload.get("attempt") or 1),
            input_digest=str(payload.get("input_digest") or ""),
            upstream_artifact_refs=tuple(
                str(i) for i in payload.get("upstream_artifact_refs") or ()
            ),
            runtime_context_snapshot_ref=str(
                payload.get("runtime_context_snapshot_ref") or ""
            ),
            timeline_event_seq=int(payload.get("timeline_event_seq") or 0),
            logs_ref=str(payload.get("logs_ref") or ""),
            classification=dict(payload.get("classification") or {}),
            metadata=dict(payload.get("metadata") or {}),
            created_at=str(payload.get("created_at") or datetime.now(UTC).isoformat()),
        )

