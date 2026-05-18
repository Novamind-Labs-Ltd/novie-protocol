# ruff: noqa: RUF002, RUF003
"""Execution failure taxonomy —— PMS-first execution workflow 终态分类。

Workflow 跑挂时由 ``ExecutionFailureClassifier`` 根据 exception / step 状态映射
出一个 ``ExecutionFailureType``，决定后续状态机：

| failure_type           | 处理 |
|------------------------|------|
| ``transient``          | workflow 内部 retry；PMS 维持 ``In Progress`` |
| ``delivery_blocked``   | workflow 终止；PMS → ``Human Review`` |
| ``implementation_failed`` | workflow 终止；PMS → ``Human Review`` |
| ``cancelled``          | workflow 终止；PMS → ``Cancelled`` 或 ``Human Review`` |

**Hard rule**：终态失败**不允许 resume 旧 workflow**。人工修完 → 把 PMS 拉回
``Todo`` → poller 启动**全新** ``ExecutionGraphWorkflow``。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

ExecutionFailureType = Literal[
    "transient",
    "delivery_blocked",
    "implementation_failed",
    "cancelled",
]

EXECUTION_FAILURE_TYPES: tuple[str, ...] = (
    "transient",
    "delivery_blocked",
    "implementation_failed",
    "cancelled",
)

ExecutionFailureReasonCode = Literal[
    "transient.llm_rate_limit",
    "transient.upstream_timeout",
    "delivery_blocked.quota_exhausted",
    "delivery_blocked.policy_gate_rejected",
    "delivery_blocked.dependency_deadlock",
    "implementation_failed.agent_error",
    "implementation_failed.schema_violation",
    "cancelled.user_cancelled",
]

EXECUTION_FAILURE_REASON_CODES: tuple[str, ...] = (
    "transient.llm_rate_limit",
    "transient.upstream_timeout",
    "delivery_blocked.quota_exhausted",
    "delivery_blocked.policy_gate_rejected",
    "delivery_blocked.dependency_deadlock",
    "implementation_failed.agent_error",
    "implementation_failed.schema_violation",
    "cancelled.user_cancelled",
)


@dataclass(frozen=True, slots=True)
class ExecutionFailureRecord:
    """终态失败的持久化记录；用于 PMS Human Review UI 展示和审计。

    每条记录绑定一次 workflow 运行；同一 PMS issue 重新跑会写一条新记录，
    旧记录保留作为历史轨迹。
    """

    record_id: str
    pms_issue_id: str
    execution_link_id: str
    workflow_id: str
    workflow_run_id: str
    failure_type: ExecutionFailureType
    reason_code: ExecutionFailureReasonCode
    failure_summary: str = ""
    last_agent_id: str = ""
    last_step_id: str = ""
    cortex_task_id: str = ""
    artifact_refs: tuple[str, ...] = ()
    log_refs: tuple[str, ...] = ()
    retryable: bool = False
    occurred_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not str(self.reason_code).strip():
            raise ValueError("ExecutionFailureRecord.reason_code must be non-empty")
        if self.reason_code not in EXECUTION_FAILURE_REASON_CODES:
            raise ValueError(f"unsupported ExecutionFailureRecord.reason_code {self.reason_code!r}")
        for name in ("artifact_refs", "log_refs"):
            value = getattr(self, name)
            if not isinstance(value, tuple):
                object.__setattr__(self, name, tuple(value))
