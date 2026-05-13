"""ArtifactLineage —— 产物血缘模型。

记录一个 artifact 的完整生产/消费链路：谁产生了它、它基于哪些输入、
哪些 step 将消费它。当 artifact 被更新或作废时，通过 ``consumer_step_ids``
立即知道哪些 step 需要被标记为 stale。

版本语义：
- ``version`` 单调递增，1 为初始版本。
- 同 artifact_id 的新版本产出时，旧版本自动作废（invalidated_by 指向新版本事件）。
- ``content_hash`` 用于内容幂等判断（hash 未变则 consumer 不需要 stale）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

ArtifactValidityStatus = Literal[
    "valid",       # 当前版本有效
    "stale",       # 有新版本，旧版本未被消费者使用的都应重跑
    "invalidated", # 被显式作废（上游 brief 变化 / 测试失败 / schema 不合法等）
    "superseded",  # 被同 artifact_id 的新版本替代
]


@dataclass(frozen=True, slots=True)
class ArtifactLineage:
    """单个 artifact 的完整血缘记录。

    Projector 在收到 ``artifact.created`` / ``artifact.updated`` 时创建；
    收到 ``artifact.invalidated`` 时标记 ``validity_status``。
    """

    artifact_id: str
    artifact_type: str               # requirements_analysis / task_bundle / report / code_diff ...
    version: int                     # 单调递增，1 起
    content_hash: str                # 内容 hash，用于幂等判断（SHA-256 hex 前 16 chars 即可）
    produced_by_step_id: str         # 产出 step
    produced_by_agent_id: str        # 产出 agent
    plan_id: str                     # 属于哪个 plan

    input_artifact_ids: tuple[str, ...] = ()    # 该 artifact 基于哪些上游 artifact 产出
    consumer_step_ids: tuple[str, ...] = ()     # 哪些 step 将以此 artifact 作为输入

    validity_status: ArtifactValidityStatus = "valid"
    invalidated_by_event_id: str | None = None  # 触发作废的 ChangeEvent.event_id

    created_at: datetime | None = None
    updated_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for attr in ("input_artifact_ids", "consumer_step_ids"):
            val = getattr(self, attr)
            if not isinstance(val, tuple):
                object.__setattr__(self, attr, tuple(val))

    def is_valid(self) -> bool:
        return self.validity_status == "valid"

    def downstream_steps(self) -> tuple[str, ...]:
        """返回需要感知此 artifact 变化的 step id 集合。"""
        return self.consumer_step_ids
