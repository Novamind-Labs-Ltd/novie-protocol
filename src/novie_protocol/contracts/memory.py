# ruff: noqa: RUF002
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal


@dataclass(frozen=True, slots=True)
class CheckpointSnapshot:
    """LangGraph CompiledStateGraph persisted checkpoint snapshot."""

    checkpoint_id: str
    thread_id: str
    thread_kind: Literal["dispatch", "agent"]
    parent_checkpoint_id: str | None
    created_at: datetime
    state: dict[str, Any]
    pending_writes: tuple[dict[str, Any], ...] = ()
    memory_scope: Literal["platform", "agent"] = "platform"
    owner_agent_id: str | None = None


@dataclass(frozen=True, slots=True)
class ExternalAgentCheckpointRecord:
    """Opaque external-agent checkpoint stored by the platform.

    Platform indexes, isolates, and returns this payload but does not interpret
    the agent's internal checkpoint schema.
    """

    checkpoint_id: str
    tenant_id: str
    workspace_id: str
    owner_agent_id: str
    thread_id: str
    session_id: str | None
    workflow_id: str | None
    step_id: str | None
    checkpoint_format: str
    checkpoint_version: str
    payload: dict[str, Any]
    summary: str | None
    parent_checkpoint_id: str | None
    created_at: datetime
    metadata: dict[str, Any]
