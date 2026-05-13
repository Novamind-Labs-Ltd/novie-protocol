# ruff: noqa: RUF001, RUF002, RUF003
"""Unified Stage ① DAG draft for the planner pipeline.

See ``docs/ORCHESTRATION_DAG_HITL_DESIGN.md`` §5.1.

From v0.2, ``PlanDraft`` is the only Stage ① output shape:
- Produced by ``LLMPlanDraftStrategy`` in production, or any other
  ``PlanDraftStrategy`` implementation (including test fixtures) that matches
  the same contract.
- Validated by ``PlanValidator`` into ``ValidatedPlan``.
- After optional plan-level review, ``ValidatedPlan`` enters Stage ②
  ``GateArbitrator`` and Stage ③ ``PolicyValidator``, yielding ``ExecutionPlan``.

Hard floor:
- LLM paths emit ``PlanDraft`` only; the platform never executes side effects
  directly from a draft.
- ``pattern_hint`` is a producer hint, not the execution contract; the
  resolved pattern is derived from nodes/edges topology in ``PlanValidator``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from .gates import GateSpec

PlanPatternHint = Literal[
    "single",
    "sequential",
    "parallel",
    "supervisor",
    "map_reduce",
    "hierarchical",
    "dag",
]
"""LLM 对 “这像什么图” 的建议标签。

和 ``OrchestrationPattern`` 的区别：
- ``OrchestrationPattern`` 是 ExecutionPlan 的**执行契约**（GraphTemplate 选哪个模板）；
- ``PlanPatternHint`` 只是 Planner 对 DAG 形状的提示，``PlanValidator`` 会按
  nodes/edges 的真实拓扑决定是否接受，不允许仅凭 hint 越级执行。
"""


@dataclass(frozen=True, slots=True)
class PlanNodeDraft:
    """PlanDraft 中的一个节点。

    `required_capabilities` 是节点主键语义：Planner 只声明此节点需要哪些
    capability；具体 agent / runtime binding 由 ``PlanValidator`` 和
    PlanReview approval 阶段解析并冻结。

    `capability_args` / `rationale` / `metadata` 允许 LLM 给出辅助信息，但
    **不构成** Policy / Gate 决策的输入 —— 这些仍由 Stage ③ 决定。

    `execution_mode` / `routing_target` 是 W1 引入的 first-class 路由字段；
    Planner 必须在 PlanReview approve 之前为每个节点 set 这两个字段
    （由 ``PlanValidator.derive_step_routing`` 兜底推断）。下游消费者
    （ingestion service / direct lane / execution re-planner）只读 typed
    字段，不再 fallback 到 metadata blob。
    """

    node_id: str
    required_capabilities: tuple[str, ...]
    capability_args: dict[str, dict[str, Any]] = field(default_factory=dict)
    implicit_runtime_context_refs: tuple[str, ...] = ()
    fitness_score_breakdown: dict[str, dict[str, float]] = field(default_factory=dict)
    rationale: str | None = None
    risk_flags: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    # 取值见 plan.py 的 StepExecutionMode / StepRoutingTarget。LLM 输出时
    # 允许 None（草案阶段），validator 会在转 ExecutionStep 时强制 set。
    execution_mode: str | None = None
    routing_target: str | None = None

    def __post_init__(self) -> None:
        for name in (
            "required_capabilities",
            "implicit_runtime_context_refs",
            "risk_flags",
        ):
            value = getattr(self, name)
            if not isinstance(value, tuple):
                object.__setattr__(self, name, tuple(value))
        if isinstance(self.execution_mode, str) and not self.execution_mode:
            object.__setattr__(self, "execution_mode", None)
        if isinstance(self.routing_target, str) and not self.routing_target:
            object.__setattr__(self, "routing_target", None)


@dataclass(frozen=True, slots=True)
class PlanEdgeDraft:
    """PlanDraft 中的一条有向依赖边。

    `condition` 是可选的文本条件提示（例如 "if analyst.needs_clarification"），
    Phase 1 的 ``PlanValidator`` 直接忽略并强制当作无条件依赖处理；条件路由在
    后续 supervisor / map_reduce 阶段实装。
    """

    from_node: str
    to_node: str
    condition: str | None = None


@dataclass(frozen=True, slots=True)
class PlanDraft:
    """LLM 输出的 DAG 草案。

    字段语义见 `docs/ORCHESTRATION_DAG_HITL_DESIGN.md` §5.1。

    - ``draft_id``          唯一 id，用于 audit / replan 关联
    - ``pattern_hint``      LLM 建议的图形（非执行契约）
    - ``nodes`` / ``edges`` 核心 DAG 结构
    - ``reducer_hint``      map_reduce 合并策略提示（Phase 1 不生效）
    - ``planner_rationale`` LLM 的自述；进 audit / PlanReview 展示
    - ``risk_flags``        LLM 自报风险（触发 Plan HITL 的一条输入）
    - ``planner_suggested_gates`` Stage ① 推荐的门禁（被 GateArbitrator 与
                                  其他源融合）
    - ``pattern_config``    图形运行参数（max_revisions_per_step 等），最终
                            透传给 ExecutionPlan.pattern_config
    - ``metadata``          诊断附加字段，例如 ``llm_strategy_status`` /
                            ``replan_round`` / ``template_id`` / ``strategy_name`` 等
    """

    draft_id: str
    pattern_hint: PlanPatternHint
    nodes: tuple[PlanNodeDraft, ...]
    edges: tuple[PlanEdgeDraft, ...] = ()
    reducer_hint: dict[str, Any] | None = None
    planner_rationale: str = ""
    risk_flags: tuple[str, ...] = ()
    planner_suggested_gates: tuple[GateSpec, ...] = ()
    pattern_config: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # 反序列化兜底：checkpoint / HTTP body 过 msgpack/JSON 后 tuple 会退化
        # 成 list；这里强制归一，保持 ``__annotations__`` 宣告的不变量。
        if not isinstance(self.nodes, tuple):
            object.__setattr__(self, "nodes", tuple(self.nodes))
        if not isinstance(self.edges, tuple):
            object.__setattr__(self, "edges", tuple(self.edges))
        if not isinstance(self.risk_flags, tuple):
            object.__setattr__(self, "risk_flags", tuple(self.risk_flags))
        if not isinstance(self.planner_suggested_gates, tuple):
            object.__setattr__(
                self,
                "planner_suggested_gates",
                tuple(self.planner_suggested_gates),
            )
