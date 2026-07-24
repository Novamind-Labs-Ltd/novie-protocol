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

GateTiming = Literal[
    "pre_step",
    "post_step",
    "pre_side_effect",
]

GateContentKind = Literal[
    "artifact_preview",
    "markdown",
    "facts",
    "table",
    "diff",
    "dependency_graph",
    "warning",
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
class GateContentDeclaration:
    """A safe, typed display block resolved from capability output at runtime."""

    kind: GateContentKind
    binding: str
    block_id: str = ""
    title: str = ""

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "kind": self.kind,
            "binding": self.binding,
        }
        if self.block_id:
            data["block_id"] = self.block_id
        if self.title:
            data["title"] = self.title
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GateContentDeclaration:
        return cls(
            kind=data["kind"],
            binding=str(data.get("binding") or ""),
            block_id=str(data.get("block_id") or ""),
            title=str(data.get("title") or ""),
        )


@dataclass(frozen=True, slots=True)
class CapabilityGateDeclaration:
    """Capability-authored gate copied onto matching execution-plan steps."""

    gate_key: str
    timing: GateTiming
    title: str
    description: str
    required: bool = True
    boundary_id: str = ""
    allowed_actions: tuple[GateAction, ...] = REVIEW_GATE_ACTIONS
    required_approver_roles: tuple[str, ...] = ()
    timeout_seconds: int | None = None
    content: tuple[GateContentDeclaration, ...] = ()
    payload_schema: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for attr in ("allowed_actions", "required_approver_roles", "content"):
            value = getattr(self, attr)
            if not isinstance(value, tuple):
                object.__setattr__(self, attr, tuple(value))
        object.__setattr__(
            self,
            "content",
            tuple(
                item
                if isinstance(item, GateContentDeclaration)
                else GateContentDeclaration.from_dict(item)
                for item in self.content
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "gate_key": self.gate_key,
            "timing": self.timing,
            "title": self.title,
            "description": self.description,
            "required": self.required,
            "allowed_actions": list(self.allowed_actions),
            "required_approver_roles": list(self.required_approver_roles),
            "content": [item.to_dict() for item in self.content],
            "payload_schema": dict(self.payload_schema),
        }
        if self.timeout_seconds is not None:
            data["timeout_seconds"] = self.timeout_seconds
        if self.boundary_id:
            data["boundary_id"] = self.boundary_id
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CapabilityGateDeclaration:
        return cls(
            gate_key=str(data.get("gate_key") or ""),
            timing=data.get("timing", "pre_step"),
            title=str(data.get("title") or ""),
            description=str(data.get("description") or ""),
            required=bool(data.get("required", True)),
            boundary_id=str(data.get("boundary_id") or ""),
            allowed_actions=tuple(data.get("allowed_actions") or REVIEW_GATE_ACTIONS),
            required_approver_roles=tuple(
                data.get("required_approver_roles") or ()
            ),
            timeout_seconds=data.get("timeout_seconds"),
            content=tuple(data.get("content") or ()),
            payload_schema=dict(data.get("payload_schema") or {}),
        )


@dataclass(frozen=True, slots=True)
class GateSpec:
    """ExecutionPlan 上的一个 HITL 暂停点。

    经 Planner.GateArbitrator 仲裁后产生（输入可能来自 4 类源）。
    详见 ARCHITECTURE.md §8.2 / §9.3 hitl_arbitration。
    """

    gate_id: str
    sources: tuple[GateSource, ...]
    title: str
    description: str
    allowed_actions: tuple[GateAction, ...] = REVIEW_GATE_ACTIONS
    required_approver_roles: tuple[str, ...] = ()
    timeout_seconds: int | None = None
    payload_schema: dict[str, Any] = field(default_factory=dict)
    gate_key: str = ""
    gate_lineage_id: str = ""
    review_revision: int = 1
    anchor_step_id: str = ""
    after_step_id: str = ""
    timing: GateTiming = "pre_step"
    required: bool = True
    source_refs: tuple[str, ...] = ()
    content: tuple[GateContentDeclaration, ...] = ()

    def __post_init__(self) -> None:
        # 反序列化兜底：详见 ExecutionStep.__post_init__。
        for attr in (
            "sources",
            "allowed_actions",
            "required_approver_roles",
            "source_refs",
            "content",
        ):
            val = getattr(self, attr)
            if not isinstance(val, tuple):
                object.__setattr__(self, attr, tuple(val))
        anchor = str(self.anchor_step_id or self.after_step_id or "").strip()
        if not anchor:
            raise ValueError("GateSpec requires anchor_step_id or after_step_id")
        object.__setattr__(self, "anchor_step_id", anchor)
        object.__setattr__(self, "after_step_id", anchor)
        object.__setattr__(
            self,
            "gate_key",
            str(self.gate_key or self.gate_id).strip(),
        )
        object.__setattr__(
            self,
            "gate_lineage_id",
            str(self.gate_lineage_id or self.gate_id).strip(),
        )
        object.__setattr__(self, "review_revision", max(1, int(self.review_revision or 1)))
        object.__setattr__(
            self,
            "content",
            tuple(
                item
                if isinstance(item, GateContentDeclaration)
                else GateContentDeclaration.from_dict(item)
                for item in self.content
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "gate_id": self.gate_id,
            "gate_key": self.gate_key,
            "gate_lineage_id": self.gate_lineage_id,
            "review_revision": self.review_revision,
            "anchor_step_id": self.anchor_step_id,
            "after_step_id": self.anchor_step_id,
            "timing": self.timing,
            "required": self.required,
            "sources": list(self.sources),
            "source_refs": list(self.source_refs),
            "title": self.title,
            "description": self.description,
            "allowed_actions": list(self.allowed_actions),
            "required_approver_roles": list(self.required_approver_roles),
            "payload_schema": dict(self.payload_schema),
            "content": [item.to_dict() for item in self.content],
        }
        if self.timeout_seconds is not None:
            data["timeout_seconds"] = self.timeout_seconds
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GateSpec:
        anchor = str(data.get("anchor_step_id") or data.get("after_step_id") or "")
        return cls(
            gate_id=str(data.get("gate_id") or ""),
            gate_key=str(data.get("gate_key") or ""),
            gate_lineage_id=str(data.get("gate_lineage_id") or ""),
            review_revision=int(data.get("review_revision") or 1),
            anchor_step_id=anchor,
            after_step_id=str(data.get("after_step_id") or anchor),
            timing=data.get("timing") or "pre_step",
            required=bool(data.get("required", True)),
            sources=tuple(data.get("sources") or ()),
            source_refs=tuple(data.get("source_refs") or ()),
            title=str(data.get("title") or ""),
            description=str(data.get("description") or ""),
            allowed_actions=tuple(data.get("allowed_actions") or REVIEW_GATE_ACTIONS),
            required_approver_roles=tuple(
                data.get("required_approver_roles") or ()
            ),
            timeout_seconds=data.get("timeout_seconds"),
            payload_schema=dict(data.get("payload_schema") or {}),
            content=tuple(data.get("content") or ()),
        )
