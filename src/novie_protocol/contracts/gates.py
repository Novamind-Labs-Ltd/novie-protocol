from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

GateSource = Literal[
    "agent_declared",     # Agent 在自己 graph 里 interrupt
    "planner_suggested",  # Planner.TeamAssembler 推荐
    "user_config",        # 用户在 session/workspace level 配置
    "compliance",         # Policy 强制
]

GateAction = Literal[
    "approve",
    "allow",
    "allow_local",
    "request_changes",
    "reject",
]

REVIEW_GATE_ACTIONS: tuple[GateAction, ...] = (
    "approve",
    "request_changes",
    "reject",
)

EXECUTION_GATE_ACTIONS: tuple[GateAction, ...] = (
    "allow",
    "allow_local",
    "reject",
)


@dataclass(frozen=True, slots=True)
class GateSpec:
    """ExecutionPlan 上的一个 HITL 暂停点。

    经 Planner.GateArbitrator 仲裁后产生（输入可能来自 4 类源）。
    详见 ARCHITECTURE.md §8.2 / §9.3 hitl_arbitration。
    """

    gate_id: str
    after_step_id: str
    sources: tuple[GateSource, ...]
    title: str
    description: str
    allowed_actions: tuple[GateAction, ...] = REVIEW_GATE_ACTIONS
    required_approver_roles: tuple[str, ...] = ()
    timeout_seconds: int | None = None
    payload_schema: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # 反序列化兜底：详见 ExecutionStep.__post_init__。
        for attr in ("sources", "allowed_actions", "required_approver_roles"):
            val = getattr(self, attr)
            if not isinstance(val, tuple):
                object.__setattr__(self, attr, tuple(val))
