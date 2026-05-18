# ruff: noqa: RUF002, RUF003
"""Canonical staged work-item graph contract.

The task-splitter agent emits this platform-owned shape. PMS-specific fields
belong in tracker adapters, not in the agent contract.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

WorkItemRelation = Literal["blocks"]


@dataclass(frozen=True, slots=True)
class ContextArtifactRef:
    """Typed reference to an upstream direct-lane artifact."""

    source_step_id: str
    artifact_type: str
    payload_ref: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class WorkItemDraft:
    """Tracker-agnostic work item draft."""

    draft_key: str
    title: str
    description: str = ""
    acceptance_criteria: tuple[str, ...] = ()
    priority: int = 3
    labels: tuple[str, ...] = ()
    target_repo: str = ""
    target_branch: str = "main"
    estimate: int | None = None
    parent_draft_key: str | None = None
    source_chunks: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("acceptance_criteria", "labels", "source_chunks"):
            value = getattr(self, name)
            if not isinstance(value, tuple):
                object.__setattr__(self, name, tuple(value))


@dataclass(frozen=True, slots=True)
class WorkItemEdge:
    """Dependency edge between work item drafts.

    ``from_key`` blocks ``to_key``.
    """

    from_key: str
    to_key: str
    relation: WorkItemRelation = "blocks"
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.relation != "blocks":
            raise ValueError(f"unsupported WorkItemEdge relation {self.relation!r}")


@dataclass(frozen=True, slots=True)
class WorkItemDraftGraph:
    """Complete staged Backlog graph produced by authoring."""

    draft_set_id: str
    summary: str = ""
    items: tuple[WorkItemDraft, ...] = ()
    edges: tuple[WorkItemEdge, ...] = ()
    context_artifacts: tuple[ContextArtifactRef, ...] = ()
    source_brief_id: str = ""
    source_plan_id: str = ""
    authoring_workflow_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("items", "edges", "context_artifacts"):
            value = getattr(self, name)
            if not isinstance(value, tuple):
                object.__setattr__(self, name, tuple(value))

    def get(self, draft_key: str) -> WorkItemDraft | None:
        for item in self.items:
            if item.draft_key == draft_key:
                return item
        return None
