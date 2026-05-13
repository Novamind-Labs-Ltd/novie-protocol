# ruff: noqa: RUF002, RUF003
"""TicketDraft / TicketDraftSet —— task_splitter 的统一输出契约（v2 PMS-First）。

旧路径：``task_splitter`` 产 ``task_bundle`` → 直接喂 cortex 执行。
v2 路径：``task_splitter`` 产 ``ticket_drafts`` → 写 PMS Backlog → Todo
触发独立的 execution workflow。

设计原则：
- 一次 splitter 运行 → 一份 ``TicketDraftSet``；set 内多条 ``TicketDraft``
  分别对应将要写入 PMS Backlog 的 issue。
- TicketDraft 字段对齐 ``PmsIssueDraft`` 的形状（title / description /
  acceptance_criteria / priority / labels / target_repo / target_branch ...），
  使 ``TicketDraftIngestionService`` 可以直接逐条转写到 PMS。
- ``draft_key`` 是 set 内唯一标识，``blocked_by`` / ``depends_on`` 用 draft_key
  引用同 set 内的其他 draft，让 ingestion service 在 PMS 写入后能正确建立
  issue 间依赖。
- ``metadata`` 必填 ``source_brief_id`` / ``source_plan_id``；ingestion service
  会在写 PMS issue 时合并 ``draft_set_id`` / ``draft_key`` /
  ``authoring_workflow_id`` / ``execution_mode='ticket'``。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class TicketDraft:
    """单条 ticket 草稿；ingestion service 会把它写成一条 PMS Backlog issue。

    ``draft_key`` 在 ``TicketDraftSet`` 内唯一，用于引用关系（``blocked_by`` /
    ``depends_on``）和 idempotency 追踪；写 PMS 后保留为 metadata.draft_key 以便
    回溯。
    """

    draft_key: str
    title: str
    description: str = ""
    acceptance_criteria: tuple[str, ...] = ()
    priority: int = 3
    labels: tuple[str, ...] = ()
    blocked_by: tuple[str, ...] = ()  # draft_keys
    depends_on: tuple[str, ...] = ()  # draft_keys
    target_repo: str = ""
    target_branch: str = "main"
    estimate: int | None = None
    parent_draft_key: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    # P2 hard-cut: per-draft step provenance + routing are MANDATORY. Splitters
    # MUST set both before emitting a draft. Ingestion service raises when
    # missing (no fallback / no default-to-"pms" coercion).
    source_step_id: str = ""
    routing_target: str = ""

    def __post_init__(self) -> None:
        for name in ("acceptance_criteria", "labels", "blocked_by", "depends_on"):
            value = getattr(self, name)
            if not isinstance(value, tuple):
                object.__setattr__(self, name, tuple(value))
        if not (self.source_step_id or "").strip():
            raise ValueError(
                f"TicketDraft {self.draft_key!r} requires source_step_id "
                "(W2 traceability invariant; splitters MUST set it)"
            )
        if not (self.routing_target or "").strip():
            raise ValueError(
                f"TicketDraft {self.draft_key!r} requires routing_target "
                "(W1 typed routing invariant; splitters MUST set it)"
            )


@dataclass(frozen=True, slots=True)
class TicketDraftSet:
    """一次 splitter 运行的完整产出，对应将要批量写入 PMS Backlog 的若干 issue。

    Ingestion service 应把整个 set 视作一个事务单元（要么全写入要么全失败），
    保证 ``draft_key`` 引用关系不会产生悬空 PMS issue。
    """

    draft_set_id: str
    summary: str = ""
    ticket_drafts: tuple[TicketDraft, ...] = ()
    source_brief_id: str = ""
    source_plan_id: str = ""
    authoring_workflow_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.ticket_drafts, tuple):
            object.__setattr__(self, "ticket_drafts", tuple(self.ticket_drafts))

    def get(self, draft_key: str) -> TicketDraft | None:
        for draft in self.ticket_drafts:
            if draft.draft_key == draft_key:
                return draft
        return None
