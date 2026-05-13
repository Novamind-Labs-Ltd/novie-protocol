"""Time Travel 域模型契约。

核心抽象：
  - RestorePoint：session/workflow 的某个可恢复快照（来自 checkpoint）
  - ForkResult：从 RestorePoint fork 出新 session 的结果（带 provenance）
  - ResumeRequest：从 checkpoint 恢复 workflow

设计约束（对应 SKILL_MANAGEMENT_DESIGN.md 邻近章节 / phase5 plan）：
  - Fork 后必须生成新 thread/session suffix，不覆盖原历史
  - 所有恢复/fork 写 AuditEvent (kind="session_forked" | "session_resumed" | "restore_point_created")
  - 不能跨 tenant/workspace fork
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal


@dataclass(frozen=True, slots=True)
class RestorePoint:
    """一个 checkpoint 快照，可用于 fork 或 resume。

    granularity 说明：
      - conversation_turn: 用户输入 → agent 回复 的完整轮次
      - workflow_step: ExecutionStep 完成时的状态
      - checkpoint: LangGraph 原生 checkpoint（任意粒度）
      - artifact_snapshot: 某个 artifact 生成后的状态
    """

    restore_point_id: str
    session_id: str
    thread_id: str
    tenant_id: str
    workspace_id: str
    checkpoint_id: str          # 对应底层 LangGraph checkpoint_id
    granularity: Literal["conversation_turn", "workflow_step", "checkpoint", "artifact_snapshot"]
    label: str                  # 人可读描述，如 "Step 2 complete: analyst agent"
    created_at: datetime
    state_summary: dict[str, Any]  # 状态摘要（不含全量 channel_values，避免泄露）
    provenance: dict[str, Any]   # 来源信息（parent_checkpoint_id / step_id / etc.）

    @classmethod
    def from_checkpoint(
        cls,
        *,
        session_id: str,
        thread_id: str,
        tenant_id: str,
        workspace_id: str,
        checkpoint_id: str,
        label: str = "",
        granularity: Literal[
            "conversation_turn", "workflow_step", "checkpoint", "artifact_snapshot"
        ] = "checkpoint",
        state_summary: dict[str, Any] | None = None,
        provenance: dict[str, Any] | None = None,
        created_at: datetime | None = None,
    ) -> "RestorePoint":
        return cls(
            restore_point_id=f"rp-{uuid.uuid4().hex[:16]}",
            session_id=session_id,
            thread_id=thread_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            checkpoint_id=checkpoint_id,
            granularity=granularity,
            label=label or f"checkpoint:{checkpoint_id[:12]}",
            created_at=created_at or datetime.now(timezone.utc),
            state_summary=state_summary or {},
            provenance=provenance or {},
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "restore_point_id": self.restore_point_id,
            "session_id": self.session_id,
            "thread_id": self.thread_id,
            "tenant_id": self.tenant_id,
            "workspace_id": self.workspace_id,
            "checkpoint_id": self.checkpoint_id,
            "granularity": self.granularity,
            "label": self.label,
            "created_at": self.created_at.isoformat(),
            "state_summary": self.state_summary,
            "provenance": self.provenance,
        }


@dataclass(frozen=True, slots=True)
class ForkResult:
    """RestorePoint 的 *provenance-only* fork 记录。

    §1.6 (2026-05-10) — *honesty pass*. This dataclass records that a
    user / operator clicked "fork from this restore point" so the
    timeline UI can render a what-if branch. It does **NOT** describe
    a running session.

    - ``forked_session_id`` / ``forked_thread_id`` are SYNTHETIC ids
      derived from the parent (``"{parent}:fork:{suffix}"``). No
      Temporal workflow is started under these ids; no LangGraph
      checkpoint is copied. They exist for timeline display and
      provenance lookup only.
    - ``provenance`` carries the parent session/thread/checkpoint
      links so the timeline can walk the fork tree.
    - When the platform later adds real runtime fork (Temporal
      ``start_workflow`` from a checkpoint snapshot), the audit
      event payload will switch from ``mode='metadata_only'`` to
      ``mode='runtime_fork'`` — consumers should branch on that
      field rather than assuming a ``ForkResult`` row implies live
      execution.
    """

    fork_id: str
    restore_point_id: str
    parent_session_id: str
    parent_thread_id: str
    forked_session_id: str
    forked_thread_id: str
    tenant_id: str
    workspace_id: str
    forked_at: datetime
    forked_by: str
    provenance: dict[str, Any]

    @classmethod
    def new(
        cls,
        *,
        restore_point: RestorePoint,
        forked_by: str,
        forked_session_suffix: str | None = None,
    ) -> "ForkResult":
        suffix = forked_session_suffix or uuid.uuid4().hex[:8]
        forked_session_id = f"{restore_point.session_id}:fork:{suffix}"
        forked_thread_id = f"{restore_point.thread_id}:fork:{suffix}"
        return cls(
            fork_id=f"fork-{uuid.uuid4().hex[:16]}",
            restore_point_id=restore_point.restore_point_id,
            parent_session_id=restore_point.session_id,
            parent_thread_id=restore_point.thread_id,
            forked_session_id=forked_session_id,
            forked_thread_id=forked_thread_id,
            tenant_id=restore_point.tenant_id,
            workspace_id=restore_point.workspace_id,
            forked_at=datetime.now(timezone.utc),
            forked_by=forked_by,
            provenance={
                "parent_session_id": restore_point.session_id,
                "parent_thread_id": restore_point.thread_id,
                "checkpoint_id": restore_point.checkpoint_id,
                "restore_point_id": restore_point.restore_point_id,
                "restore_point_label": restore_point.label,
            },
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "fork_id": self.fork_id,
            "restore_point_id": self.restore_point_id,
            "parent_session_id": self.parent_session_id,
            "parent_thread_id": self.parent_thread_id,
            "forked_session_id": self.forked_session_id,
            "forked_thread_id": self.forked_thread_id,
            "tenant_id": self.tenant_id,
            "workspace_id": self.workspace_id,
            "forked_at": self.forked_at.isoformat(),
            "forked_by": self.forked_by,
            "provenance": self.provenance,
        }
