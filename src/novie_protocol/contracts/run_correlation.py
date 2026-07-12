"""Root-run correlation contract shared by platform, SDK, and agents."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RunCorrelation:
    """Immutable lineage for one user-triggered business chain."""

    tenant_id: str
    workspace_id: str
    project_id: str
    principal_id: str
    session_id: str
    turn_id: str
    root_run_id: str
    thread_id: str
    request_id: str
    workflow_id: str = ""
    workflow_run_id: str = ""
    attempt_id: str = ""
    entity_type: str = ""
    entity_id: str = ""
    causation_event_id: str = ""

    def __post_init__(self) -> None:
        required = {
            "tenant_id": self.tenant_id,
            "workspace_id": self.workspace_id,
            "principal_id": self.principal_id,
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "root_run_id": self.root_run_id,
            "thread_id": self.thread_id,
            "request_id": self.request_id,
        }
        missing = [name for name, value in required.items() if not str(value).strip()]
        if missing:
            raise ValueError(f"RunCorrelation missing required fields: {', '.join(missing)}")

    def with_workflow(
        self,
        workflow_id: str,
        *,
        workflow_run_id: str = "",
    ) -> RunCorrelation:
        return RunCorrelation(
            **{
                **self.to_dict(),
                "workflow_id": workflow_id,
                "workflow_run_id": workflow_run_id,
            }
        )

    def with_attempt(self, attempt_id: str) -> RunCorrelation:
        return RunCorrelation(**{**self.to_dict(), "attempt_id": attempt_id})

    def with_entity(
        self,
        *,
        entity_type: str,
        entity_id: str,
        causation_event_id: str = "",
    ) -> RunCorrelation:
        return RunCorrelation(
            **{
                **self.to_dict(),
                "entity_type": entity_type,
                "entity_id": entity_id,
                "causation_event_id": causation_event_id,
            }
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "tenant_id": self.tenant_id,
            "workspace_id": self.workspace_id,
            "project_id": self.project_id,
            "principal_id": self.principal_id,
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "root_run_id": self.root_run_id,
            "thread_id": self.thread_id,
            "request_id": self.request_id,
            "workflow_id": self.workflow_id,
            "workflow_run_id": self.workflow_run_id,
            "attempt_id": self.attempt_id,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "causation_event_id": self.causation_event_id,
        }


__all__ = ["RunCorrelation"]
