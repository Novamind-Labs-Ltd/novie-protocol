"""SessionEventChannel：CLI/Web → Backend 的事件流 schema。"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

EventKind = Literal[
    "user_message",
    "agent_message",
    "tool_call",
    "tool_result",
    "gate_opened",
    "gate_resolved",
    "step_started",
    "step_finished",
    "plan_created",
    "error",
]


@dataclass(frozen=True, slots=True)
class SessionEvent:
    event_id: str
    session_id: str
    workflow_id: str | None
    kind: EventKind
    occurred_at: datetime
    payload: dict[str, Any] = field(default_factory=dict)
