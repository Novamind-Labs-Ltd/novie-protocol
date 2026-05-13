# ruff: noqa: RUF001, RUF002
"""PlanReview —— 计划级 HITL 的请求 / 决定 / 反馈契约。

对应 `docs/ORCHESTRATION_DAG_HITL_DESIGN.md` §6 / §7。

定位：
- 与 ``GateSpec`` / ``REVIEW_GATE_ACTIONS`` 的关系：``GateSpec`` 是**执行中**
  节点级的 HITL（plan 已经在跑、暂停某个 step）。``PlanReviewRequest`` 是
  **执行前**的计划级 HITL —— 图还没编译，用户对 DAG 形状 / agent 选择 /
  并行关系 / 成本 做整体确认。
- Phase 1 还不把 plan_review 的 gate 事件塞进 LangGraph 内部 interrupt；
  它走 PlanningAppService 的主路径，用 ReviewService（或 PlanReviewService
  子类）收集决策后再进入 PolicyValidator。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from .capability import CapabilityDriftReportItem

PlanReviewAction = Literal["approve", "reject", "request_changes"]
"""计划级 HITL 的三档决定。与节点级 ``REVIEW_GATE_ACTIONS`` 有意对齐。"""


PlanReviewItemKind = Literal[
    "ordering",
    "parallelism",
    "agent_choice",
    "risk",
    "cost",
    "missing_step",
    "scope",
    "other",
]
"""结构化反馈条目的语义类别。

设计意图：用户的反馈至少骨架化，避免 LLM 读到一坨自由文本无从下手。Phase 1
支持 6 个核心 kind（§6.2），预留 ``scope`` / ``other`` 给 UI 扩展。
"""


@dataclass(frozen=True, slots=True)
class PlanReviewRequest:
    """发给人审的 plan review 摘要。

    - ``review_id``        这次 review 的唯一 id（用于 resume 异步决策）
    - ``plan_draft_id``    对应的 PlanDraft.draft_id（审计链关联）
    - ``title`` / ``summary`` UI 单行 / 段落展示
    - ``nodes`` / ``edges`` 给前端渲染图用的轻量结构（不传 LangGraph compiled graph）
    - ``risk_flags``       结构化风险
    - ``estimated_cost`` / ``estimated_tokens`` 预估成本（可能为 None）
    - ``rationale``        planner 自述（``PlanDraft.planner_rationale``）
    - ``metadata``         扩展槽位，例如 ``replan_round`` / ``fallback_used``
    """

    review_id: str
    plan_draft_id: str
    title: str
    summary: str
    nodes: tuple[dict[str, Any], ...] = ()
    edges: tuple[dict[str, Any], ...] = ()
    risk_flags: tuple[str, ...] = ()
    estimated_cost: float | None = None
    estimated_tokens: int | None = None
    rationale: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.nodes, tuple):
            object.__setattr__(self, "nodes", tuple(self.nodes))
        if not isinstance(self.edges, tuple):
            object.__setattr__(self, "edges", tuple(self.edges))
        if not isinstance(self.risk_flags, tuple):
            object.__setattr__(self, "risk_flags", tuple(self.risk_flags))


@dataclass(frozen=True, slots=True)
class PlanReviewItem:
    """一条结构化的反馈条目。

    ``target`` 可以指向：
    - 一个节点 node_id（如 ``"s0"``）
    - 一个 agent_id（如 ``"novie-cortex"``）
    - 一条边（惯例格式 ``"edge:<from>-><to>"``）
    - ``"plan"``（整体评述）

    LLM replan 时需要理解这组语义；Phase 1 里 ``kind`` 只作诊断与
    rationale 文案，实际 replan prompt 会把整个 list JSON 化进 context。
    """

    kind: PlanReviewItemKind
    target: str
    message: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PlanReviewDecision:
    """人审给出的最终决定。

    - ``action``            approve / reject / request_changes
    - ``global_note``       自由文本备注；approve 也可带 note（例如 "gg"）
    - ``items``             结构化反馈列表；``action == approve`` 时一般为空
    - ``reviewer``          审核人 id（给 audit / session timeline 用；可选）
    - ``decided_at_ms``     决策时刻（毫秒时间戳，可选，便于审计延迟）
    - ``metadata``          其它附加信息
    """

    action: PlanReviewAction
    global_note: str | None = None
    items: tuple[PlanReviewItem, ...] = ()
    reviewer: str | None = None
    decided_at_ms: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.items, tuple):
            object.__setattr__(self, "items", tuple(self.items))


@dataclass(frozen=True, slots=True)
class ReplanFeedback:
    """给 Planner 下一轮 replan 的结构化输入。

    由 ``PlanningAppService`` 根据上一轮的 ``PlanReviewDecision`` +
    ``ValidatedPlan`` 拼装；Planner strategy 读它来约束下一轮输出，而不是
    从头随机再来一次（§7.3）。

    - ``round``                  当前是第几轮 replan（从 1 起算）
    - ``previous_plan_draft_id`` 上一版 PlanDraft.draft_id
    - ``user_decision``          上一轮用户决定
    - ``validator_notes``        PlanValidator 给的结构化风险与拒绝原因
    - ``capability_drift_report`` 上一轮冻结 capability 与当前 catalog 的差异
    - ``max_rounds``             最多允许的 replan 轮次（达到则走 fallback）
    """

    round: int
    previous_plan_draft_id: str
    user_decision: PlanReviewDecision | None
    validator_notes: tuple[str, ...] = ()
    capability_drift_report: tuple[CapabilityDriftReportItem, ...] = ()
    max_rounds: int = 3
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.validator_notes, tuple):
            object.__setattr__(
                self, "validator_notes", tuple(self.validator_notes),
            )
        if not isinstance(self.capability_drift_report, tuple):
            object.__setattr__(
                self,
                "capability_drift_report",
                tuple(self.capability_drift_report),
            )
