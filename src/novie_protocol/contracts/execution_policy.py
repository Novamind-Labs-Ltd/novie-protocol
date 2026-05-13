# ruff: noqa: RUF002, RUF003
"""ExecutionPolicy —— PMS Todo issue 进入 execution workflow 前的策略决策契约。

``Todo`` 在 v2 语义下是"已批准进入 execution evaluation"，**不是"必须无条件
执行"**。Poller 观察到 Todo 后，``PmsTicketExecutionService`` 调用
``ExecutionPolicyService.evaluate(...)`` 决定：

- ``allow``           ：直接启动 ``ExecutionGraphWorkflow``，PMS → In Progress
- ``review_required`` ：PMS → Human Review；workflow **不启动**
- ``deny``            ：PMS → Human Review 或 Cancelled；workflow **不启动**

策略决策应基于：
- PMS issue snapshot（labels / priority / blockers / target_repo / target_branch）
- 所需 capabilities（platform 推断）
- 敏感标签（destructive / pii / external_network / production_write）
- tenant / workspace policy profile

**Hard floor**：``allow`` 之外的决策**不得**走 transition / fallback。
即——不存在"先 allow 跑跑看不行再 review"。

底层实现复用 ``PolicyDecisionPoint``（新增 scenario ``pms_ticket_execution``），
而不是新建独立 service；本文件只定契约 dataclass，不重新实现策略引擎。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

ExecutionPolicyDecisionKind = Literal["allow", "review_required", "deny"]


@dataclass(frozen=True, slots=True)
class ExecutionPolicyRequest:
    """``ExecutionPolicyService.evaluate`` 输入。"""

    pms_issue_id: str
    tenant_id: str
    workspace_id: str
    project_id: str
    issue_labels: tuple[str, ...] = ()
    issue_priority: int = 3
    target_repo: str = ""
    target_branch: str = "main"
    required_capabilities: tuple[str, ...] = ()
    sensitivity_tags: tuple[str, ...] = ()
    blocked_by: tuple[dict[str, Any], ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ExecutionPolicyDecision:
    """``ExecutionPolicyService.evaluate`` 输出。"""

    decision: ExecutionPolicyDecisionKind
    reason_codes: tuple[str, ...] = ()
    required_approver_roles: tuple[str, ...] = ()
    review_summary: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
