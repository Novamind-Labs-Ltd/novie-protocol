from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from .context import ExecutionContext

PolicyScenario = Literal[
    "delegation_context",     # Agent 间委派时附加约束
    "sensitive_action",       # 敏感动作准入（如发邮件、改库）
    "tool_invocation",        # 工具调用准入
    "data_access",            # 数据访问准入
    "agent_initiated_gate",   # Agent 发起的 HITL 翻译
    "hitl_arbitration",       # 多源 HITL 仲裁（Planner.GateArbitrator 唯一调用）
    "orchestration_change",   # Change-Aware Orchestrator 变更提案风险评估
    "pms_ticket_execution",   # PMS-First v2: Todo issue → Temporal execution workflow 准入
]


@dataclass(frozen=True, slots=True)
class PolicyRequest:
    scenario: PolicyScenario
    context: ExecutionContext
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    allow: bool
    reason: str
    obligations: tuple[str, ...] = ()  # 例如 "must_audit", "must_redact_pii"
    extras: dict[str, Any] = field(default_factory=dict)
