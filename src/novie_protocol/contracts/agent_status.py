from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

AgentStatusKind = Literal[
    "turn_start",
    "turn_end",
    "tool_call",
    "tool_result",
    "progress_note",
    "status_update",
    "artifact_created",
]


@dataclass(frozen=True, slots=True)
class AgentStatusEvent:
    """Agent 主动上报的平台侧观测事件。"""

    event_id: str
    occurred_at: datetime
    kind: AgentStatusKind
    agent_id: str
    task_id: str
    session_id: str | None = None
    thread_id: str | None = None
    plan_id: str | None = None
    turn: int | None = None
    payload: dict[str, Any] = field(default_factory=dict)
