# ruff: noqa: RUF002, RUF003
"""PMS issue lifecycle / execution link 契约（v2 PMS-First）。

PMS issue 状态机（产品层）：

- ``Backlog``       ：authoring 写入的初始状态，未获人工批准
- ``Todo``          ：人工批准；platform 可发起 execution policy 评估
- ``In Progress``   ：execution workflow 已启动
- ``Human Review``  ：execution 终态失败 / 需人工介入
- ``Done``          ：execution 成功
- ``Cancelled``     ：被显式终止

允许的转换（platform 主动触发或人工触发）：

- Backlog -> Todo
- Todo -> In Progress
- Todo -> Human Review
- In Progress -> Done
- In Progress -> Human Review
- In Progress -> Cancelled
- Human Review -> Todo

`PmsExecutionLink` 是 platform-side 的"哪条 PMS issue 当前由哪条 Temporal
execution workflow 跑"对照表，作为 lease 防止同一 issue 同时被多个 workflow
启动。``(pms_issue_id, status='active')`` 必须 DB unique。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

PmsIssueState = Literal[
    "Backlog",
    "Todo",
    "In Progress",
    "Human Review",
    "Done",
    "Cancelled",
]

PmsExecutionLinkStatus = Literal[
    "active",       # workflow 当前在跑或刚启动
    "completed",    # workflow 成功结束（PMS Done）
    "failed",       # workflow 终态失败（PMS Human Review）
    "cancelled",    # workflow 被取消
    "released",     # lease 主动释放（用于异常恢复）
]


@dataclass(frozen=True, slots=True)
class PmsIssueSnapshot:
    """Execution workflow 的输入快照；对齐既有 ``PmsIssue`` shape（即 Linear-兼容）。

    cortex 在 ticket-execution 路径下消费此 snapshot——它在 v0.x 已经能消费
    Linear issue payload，无需新增解析路径。``PmsTicketExecutionService`` 在
    启动 workflow 前从 PMS load 一次完整 issue，序列化进 workflow input；
    后续 workflow 内部不再回查 PMS（确定性）。
    """

    issue_id: str
    identifier: str
    project_id: str
    workspace_id: str
    tenant_id: str
    title: str
    description: str = ""
    acceptance_criteria: tuple[str, ...] = ()
    priority: int = 3
    state: PmsIssueState = "Todo"
    labels: tuple[str, ...] = ()
    blocked_by: tuple[dict[str, Any], ...] = ()
    assignee_id: str | None = None
    assignee_name: str | None = None
    estimate: int | None = None
    parent_id: str | None = None
    parent_identifier: str | None = None
    cycle_id: str | None = None
    branch_name: str | None = None
    linked_pr_urls: tuple[str, ...] = ()
    target_repo: str = ""
    target_branch: str = "main"
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self) -> None:
        for name in (
            "acceptance_criteria",
            "labels",
            "blocked_by",
            "linked_pr_urls",
        ):
            value = getattr(self, name)
            if not isinstance(value, tuple):
                object.__setattr__(self, name, tuple(value))


@dataclass(frozen=True, slots=True)
class PmsExecutionLink:
    """``pms_issue_id <-> Temporal workflow_id`` 的活跃绑定。

    DB schema 上 ``(pms_issue_id, status='active')`` 必须 unique，保证同一
    PMS issue 同时只有一条活跃 workflow——避免 poller 在 webhook 抖动 /
    重启过程中重复触发。
    """

    link_id: str
    pms_issue_id: str
    tenant_id: str
    workspace_id: str
    project_id: str
    workflow_id: str = ""                     # filled by ``attach_workflow`` after Temporal start
    workflow_run_id: str = ""
    status: PmsExecutionLinkStatus = "active"
    trigger_source: str = "pms_todo_poller"  # poller / webhook / manual
    lease_holder: str = ""                    # worker_id / poller_id
    lease_acquired_at: str = ""               # iso8601 utc
    lease_expires_at: str = ""                # iso8601 utc
    last_heartbeat_at: str = ""
    started_at: str = ""
    finished_at: str = ""
    failure_type: str = ""                    # see ExecutionFailureType
    failure_reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
