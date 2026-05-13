"""ValidatedPlan —— PlanValidator 输出的中间契约。

对应 `docs/ORCHESTRATION_DAG_HITL_DESIGN.md` §5.2。

流程：
  LLM → PlanDraft → PlanValidator → ValidatedPlan → (PlanReviewGate?)
    → PolicyValidator → ExecutionPlan

和 ``ExecutionPlan`` 的分工：
- ``ValidatedPlan``  : v0.2 DAG-HITL 路径的**中间对象**。已经经过：
  1. DAG 无环 / 节点可达性校验
  2. agent 存在性 / capability 校验
  3. pattern 推导（supervisor / map_reduce 等 hint 在 Phase 1 被拒掉）
  4. 风险打分 + ``requires_plan_review`` 判定
- ``ExecutionPlan``  : 最终执行契约，由 ``PolicyValidator.validate`` 基于
  ``ValidatedPlan.plan_draft`` + ``resolved_pattern`` 生成。

v0.2 起 PlanDraft 是统一的中间态；旧的 DraftPlan 退役，``ValidatedPlan``
不再携带 ``resolved_draft_plan`` 退化字段。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from .plan_draft import PlanDraft

ValidatedPattern = Literal["single", "sequential", "parallel_flat", "dag"]
"""Phase 1 + Phase 2 支持的最终执行 pattern 子集。

- ``single`` / ``sequential`` / ``parallel_flat`` —— Phase 1 既有的三档退化形状
- ``dag``                                         —— Phase 2 新增的一般 DAG

``supervisor`` / ``map_reduce`` / ``hierarchical`` 是 Phase 3/4 的动态拓扑，
没法用静态 DAG 表达；``PlanValidator`` 碰到这些 ``pattern_hint`` 且拓扑
超出当前支持范围时，应显式拒绝并让上层走 fallback，而不是静默降级。
"""


PlanRiskSeverity = Literal["low", "medium", "high"]


@dataclass(frozen=True, slots=True)
class PlanRiskFlag:
    """``PlanValidator`` 对一条风险的结构化记录。

    触发方式（Phase 1）：

    - ``external_agent``      : 计划里出现了外部复杂 agent（如 ``novie-cortex``）
    - ``llm_self_reported``   : PlanDraft.risk_flags 中的 LLM 自报项
    - ``parallel_pattern``    : 推导出的 pattern == ``parallel_flat``
    - ``sensitivity_tags``    : brief 中的 ``sensitivity_tags`` 命中敏感清单
    - ``large_graph``         : 节点数量超阈值
    """

    code: str
    severity: PlanRiskSeverity
    message: str
    targets: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ValidatedPlan:
    """``PlanValidator.validate`` 的产物。

    - ``plan_draft``              : 已解析过 agent 与 capability 的 PlanDraft
                                    （供 audit / replan / Stage ③ 直接消费）
    - ``resolved_pattern``        : 按 nodes/edges 拓扑重新推导出的 pattern
    - ``risk_flags``              : 结构化风险条目
    - ``requires_plan_review``    : ``True`` 表示需要插入 Plan HITL，触发条件
                                    见 §6.3（pattern / 外部 agent / 风险 /
                                    用户显式要求…）
    - ``plan_review_reasons``     : 为什么要求 plan review 的简短 reason codes
    - ``estimated_node_count``    : 节点数（冗余字段，便于 UI 不拆 nodes 就能渲染）
    - ``metadata``                : 诊断字段，例如 validator 版本 / replan 轮次
    """

    plan_draft: PlanDraft
    resolved_pattern: ValidatedPattern
    risk_flags: tuple[PlanRiskFlag, ...] = ()
    requires_plan_review: bool = False
    plan_review_reasons: tuple[str, ...] = ()
    estimated_node_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # 与其他契约一致：sequence 字段 round-trip msgpack 会退化成 list。
        if not isinstance(self.risk_flags, tuple):
            object.__setattr__(self, "risk_flags", tuple(self.risk_flags))
        if not isinstance(self.plan_review_reasons, tuple):
            object.__setattr__(
                self,
                "plan_review_reasons",
                tuple(self.plan_review_reasons),
            )
