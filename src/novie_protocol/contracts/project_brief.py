"""ProjectBrief — project-level read-only brief injected into agent inputs.

Generated once per dispatch start and cached at project scope; each step's
``agent.astream/ainvoke`` reads the same snapshot from ``inputs["__project_brief__"]``.

Contract:
- Read-only for agents: agents must not write back through this object.
  Long-lived facts belong in curated Knowledge (RAG) or upstream Member/PMS
  staging synced by the platform.
- Snapshot semantics: fields reflect the aggregation at generation time and may
  lag live systems; agents needing fresher state must use explicit pull APIs.
- Optional degradation: when generation fails the platform injects ``minimal()``
  (project_id + tenant_id + reason); agents seeing ``minimal=True`` should rely
  on other injected context or approved pull capabilities.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass(frozen=True, slots=True)
class ProjectBrief:
    """LLM 生成的项目简报（结构化 + 自然语言混合）。

    - ``summary``            : 自然语言叙述（3-5 段），给 agent 当背景 prompt。
    - ``key_constraints``    : LLM 归纳的硬约束（合规 / 安全 / 交付门槛等）。
    - ``recent_focus``       : 最近团队在关注什么（从事件流归纳）。
    - ``open_questions``     : 悬而未决的问题（用于避免 agent 重复提问）。
    - ``source_hash``        : 生成输入的指纹；service 据此判断缓存是否失效。
    - ``minimal``            : 降级标记；LLM 失败时为 True，此时只有 id + reason。
    """

    project_id: str
    tenant_id: str
    generated_at: datetime
    source_hash: str

    summary: str = ""
    key_constraints: tuple[str, ...] = field(default_factory=tuple)
    recent_focus: tuple[str, ...] = field(default_factory=tuple)
    open_questions: tuple[str, ...] = field(default_factory=tuple)

    minimal: bool = False
    degraded_reason: str | None = None

    def __post_init__(self) -> None:
        # 反序列化兜底：checkpoint 回灌 / JSON round-trip 时 tuple 会变 list。
        if not isinstance(self.key_constraints, tuple):
            object.__setattr__(self, "key_constraints", tuple(self.key_constraints))
        if not isinstance(self.recent_focus, tuple):
            object.__setattr__(self, "recent_focus", tuple(self.recent_focus))
        if not isinstance(self.open_questions, tuple):
            object.__setattr__(self, "open_questions", tuple(self.open_questions))

    def to_dict(self) -> dict[str, object]:
        """随 dispatch 注入 inputs 前序列化为 plain dict（agent 反序列化友好）。"""
        return {
            "project_id": self.project_id,
            "tenant_id": self.tenant_id,
            "generated_at": self.generated_at.isoformat(),
            "source_hash": self.source_hash,
            "summary": self.summary,
            "key_constraints": list(self.key_constraints),
            "recent_focus": list(self.recent_focus),
            "open_questions": list(self.open_questions),
            "minimal": self.minimal,
            "degraded_reason": self.degraded_reason,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> ProjectBrief:
        generated_at = data.get("generated_at")
        if isinstance(generated_at, str):
            ts = datetime.fromisoformat(generated_at)
        elif isinstance(generated_at, datetime):
            ts = generated_at
        else:
            raise TypeError(
                f"ProjectBrief.from_dict: generated_at must be str|datetime, got {type(generated_at).__name__}"
            )
        return cls(
            project_id=str(data["project_id"]),
            tenant_id=str(data["tenant_id"]),
            generated_at=ts,
            source_hash=str(data["source_hash"]),
            summary=str(data.get("summary") or ""),
            key_constraints=tuple(data.get("key_constraints") or ()),
            recent_focus=tuple(data.get("recent_focus") or ()),
            open_questions=tuple(data.get("open_questions") or ()),
            minimal=bool(data.get("minimal") or False),
            degraded_reason=(
                str(data["degraded_reason"])
                if data.get("degraded_reason") is not None
                else None
            ),
        )

    @classmethod
    def degraded(
        cls,
        *,
        project_id: str,
        tenant_id: str,
        source_hash: str,
        reason: str,
        generated_at: datetime | None = None,
    ) -> ProjectBrief:
        """LLM 生成失败时的降级简报。Agent 可据此走 pull 路径。"""
        return cls(
            project_id=project_id,
            tenant_id=tenant_id,
            generated_at=generated_at or datetime.now(timezone.utc),
            source_hash=source_hash,
            summary="",
            minimal=True,
            degraded_reason=reason,
        )
