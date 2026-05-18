from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

PlanGraphMode = Literal["direct_only", "staged_only", "mixed"]


@dataclass(frozen=True, slots=True)
class TaskBrief:
    """Reception Agent 输出 → Planner 输入。

    经过 Reception 的意图澄清 / chitchat 过滤后产生的"业务任务摘要"。
    """

    brief_id: str
    title: str
    summary: str
    user_goal: str
    routing_hint: PlanGraphMode | None = None
    constraints: tuple[str, ...] = ()
    attachments: tuple[str, ...] = ()
    raw_metadata: dict[str, Any] = field(default_factory=dict)
