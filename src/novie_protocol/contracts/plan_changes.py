"""Plan Change Control 数据模型。

当 Orchestrator 判断需要修改正在执行的 plan 时，不允许静默应用变更，
必须走 PlanChangeProposal → Policy 评估 → HITL gate（若需要）→ PlanPatch 应用 的全流程。

变更类型语义：
- ``retry_step``        : 幂等型，低风险，通常可自动执行。
- ``rerun_downstream``  : 会作废 downstream artifact，需要 HITL。
- ``pause`` / ``resume``: 不改 DAG，属于运行控制，中等风险。
- ``replace_agent``     : 改派 agent，中高风险，必须 HITL。
- ``insert_step``       : 改变 DAG 结构，必须 HITL。
- ``remove_step``       : 改变 DAG 结构，必须 HITL。
- ``modify_inputs``     : 修改 step inputs，低-中风险，由 policy 判断。
- ``cancel``            : 终止整个 plan，必须 HITL。
- ``replan``            : 完全重规划，必须 HITL。
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

# ---------------------------------------------------------------------------
# 变更类型
# ---------------------------------------------------------------------------

PlanChangeType = Literal[
    "retry_step",           # 重试单个失败/超时 step（幂等）
    "rerun_downstream",     # 从某个 artifact 开始重跑所有 downstream step
    "pause",                # 暂停 plan 执行（不改 DAG）
    "resume",               # 恢复被暂停的 plan
    "replace_agent",        # 将某 step 的执行 agent 替换为另一个
    "insert_step",          # 在 DAG 中插入新 step
    "remove_step",          # 从 DAG 中删除某 step
    "skip_step",            # 跳过某 step（不执行，但允许 DAG 继续）
    "modify_inputs",        # 修改某 step 的 inputs
    "cancel",               # 取消整个 plan
    "replan",               # 基于新 brief 或重大变化完全重规划
]

RiskLevel = Literal["low", "medium", "high", "critical"]
PlanReplanTriggerSource = Literal[
    "auto_patch_exhausted",
    "user_initiated",
    "reception_turn",
]
DEFAULT_AUTO_REPLAN_CAP = 2


def has_auto_replan_budget(
    previous_attempts: int,
    *,
    cap: int = DEFAULT_AUTO_REPLAN_CAP,
) -> bool:
    """Whether another automatic re-plan may be attempted for the plan."""
    return max(0, previous_attempts) < max(0, cap)


@dataclass(frozen=True, slots=True)
class PlanReplannedEvent:
    """Audit/dispatch payload emitted when a plan version is replaced."""

    plan_id: str
    old_plan_version: str
    new_plan_version: str
    trigger_source: PlanReplanTriggerSource
    reason: str
    preserved_step_ids: tuple[str, ...] = ()
    replaced_step_ids: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.preserved_step_ids, tuple):
            object.__setattr__(
                self,
                "preserved_step_ids",
                tuple(self.preserved_step_ids),
            )
        if not isinstance(self.replaced_step_ids, tuple):
            object.__setattr__(
                self,
                "replaced_step_ids",
                tuple(self.replaced_step_ids),
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "old_plan_version": self.old_plan_version,
            "new_plan_version": self.new_plan_version,
            "trigger_source": self.trigger_source,
            "reason": self.reason,
            "preserved_step_ids": list(self.preserved_step_ids),
            "replaced_step_ids": list(self.replaced_step_ids),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PlanReplannedEvent:
        return cls(
            plan_id=str(data["plan_id"]),
            old_plan_version=str(data["old_plan_version"]),
            new_plan_version=str(data["new_plan_version"]),
            trigger_source=data["trigger_source"],
            reason=str(data.get("reason") or ""),
            preserved_step_ids=tuple(data.get("preserved_step_ids") or ()),
            replaced_step_ids=tuple(data.get("replaced_step_ids") or ()),
            metadata=dict(data.get("metadata") or {}),
        )

# ---------------------------------------------------------------------------
# PlanPatchOperation —— 原子变更操作
# ---------------------------------------------------------------------------

PlanPatchOpKind = Literal[
    "add_step",
    "remove_step",
    "update_step_inputs",
    "update_step_agent",
    "add_gate",
    "remove_gate",
    "update_plan_metadata",
    "update_step_metadata",
]


# §1.3 (2026-05-10): structural ops change the plan's DAG topology
# (steps or gates added / removed). They MUST go through Temporal
# cancel + restart with a ``metadata.revised_plan`` payload — there's
# no in-place application path. Non-structural ops (update_*_inputs /
# update_*_agent / update_*_metadata) modify a single step's
# attributes in place and don't need a revised plan.
STRUCTURAL_PATCH_OP_KINDS: frozenset[str] = frozenset(
    {"add_step", "remove_step", "add_gate", "remove_gate"}
)


def is_structural_patch_op_kind(op_kind: str) -> bool:
    """Whether the given op kind is a structural DAG change."""
    return op_kind in STRUCTURAL_PATCH_OP_KINDS


def has_structural_patch_ops(ops: "Iterable[PlanPatchOp]") -> bool:
    """Whether ``ops`` contains at least one structural DAG change."""
    return any(is_structural_patch_op_kind(op.op) for op in ops)


def validate_structural_patch_metadata(
    ops: "Iterable[PlanPatchOp]", metadata: dict[str, Any] | None,
) -> None:
    """Raise ``ValueError`` if any structural op is present without a
    valid ``metadata['revised_plan']`` dict.

    Used by both :class:`PlanChangeService.create_proposal` (proposal
    boundary, fail-fast) and :class:`PlanPatchApplicator.apply` (apply
    boundary, defence in depth) so the contract is enforced at every
    seam — a structural change cannot enter the system without the
    revised plan that will replace the current Temporal workflow.

    No-op when ``ops`` contains only non-structural changes.
    """
    if not has_structural_patch_ops(ops):
        return
    if not isinstance((metadata or {}).get("revised_plan"), dict):
        raise ValueError(
            "Structural plan patches (add_step / remove_step / add_gate / "
            "remove_gate) require metadata['revised_plan'] (an "
            "ExecutionPlan dict) so the runtime can perform "
            "temporal_cancel_restart with the revised plan."
        )


@dataclass(frozen=True, slots=True)
class PlanPatchOp:
    """单个原子变更操作。

    ``op`` 决定 ``target_id`` 和 ``value`` 的语义：
    - add_step         : target_id = new step_id, value = step 定义 dict
    - remove_step      : target_id = step_id, value = {}
    - update_step_inputs : target_id = step_id, value = {"inputs": {...}}
    - update_step_capabilities : target_id = step_id,
      value = {"required_capabilities": ["..."]}
    - add_gate         : target_id = gate_id, value = gate spec dict
    - remove_gate      : target_id = gate_id, value = {}
    - update_plan_metadata : target_id = plan_id, value = metadata patch dict
    - update_step_metadata : target_id = step_id, value = metadata patch dict
    """

    op: PlanPatchOpKind
    target_id: str
    value: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# PlanChangeProposal
# ---------------------------------------------------------------------------

PlanChangeProposalStatus = Literal[
    "draft",             # Orchestrator 生成，尚未提交
    "pending_approval",  # 等待 HITL gate 裁决
    "approved",          # 已批准，待应用
    "rejected",          # 被拒绝，不应用
    "applied",           # 已成功应用
    "failed",            # 应用失败
    "withdrawn",         # Orchestrator 自行撤回（情况已改变）
]


@dataclass(frozen=True, slots=True)
class PlanChangeProposal:
    """Orchestrator 提出的 plan 变更提案。

    ``requires_hitl`` 由 Policy 在收到提案后评估并写入；
    ``required_gate_type`` 在 ``requires_hitl=True`` 时有效。
    """

    proposal_id: str
    plan_id: str
    trigger_event_ids: tuple[str, ...]    # 触发本次提案的 ChangeEvent id 集合
    change_type: PlanChangeType
    summary: str                          # 一句话描述变更目的
    rationale: str                        # 为什么做这个变更（详细说明）
    affected_step_ids: tuple[str, ...]
    affected_artifact_ids: tuple[str, ...]

    proposed_patch: tuple[PlanPatchOp, ...]  # 具体操作序列
    risk_level: RiskLevel = "medium"

    requires_hitl: bool = True           # 默认要求 HITL，Policy 可降级为 False
    required_gate_type: str = "plan_change_approval"  # gate spec 中的 gate_id

    status: PlanChangeProposalStatus = "draft"
    created_at: datetime | None = None
    updated_at: datetime | None = None
    gate_id: str | None = None           # 关联的 HITL gate id（打开后写入）
    applied_at: datetime | None = None
    apply_error: str | None = None

    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for attr in ("trigger_event_ids", "affected_step_ids",
                     "affected_artifact_ids", "proposed_patch"):
            val = getattr(self, attr)
            if not isinstance(val, tuple):
                object.__setattr__(self, attr, tuple(val))


# ---------------------------------------------------------------------------
# PlanPatch —— 最终验证后的可应用变更单元
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class PlanPatch:
    """经过 Policy 校验、HITL 批准后，可直接应用于 plan 运行时的变更单元。

    ``expected_preconditions`` 在应用前检查（防止竞争条件）：
    - {"plan_status": "paused"} → 要求 plan 当前处于 paused 状态
    - {"step_status.step_x": "failed"} → 要求 step_x 当前处于 failed 状态

    ``base_plan_version`` 是提案生成时的 plan 版本标识（plan_provenance hash），
    应用前做乐观并发校验。
    """

    patch_id: str
    plan_id: str
    proposal_id: str
    base_plan_version: str               # plan 版本标识，做乐观并发校验
    operations: tuple[PlanPatchOp, ...]
    expected_preconditions: dict[str, Any] = field(default_factory=dict)
    approved_by: str | None = None       # 批准人 principal_id
    approved_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.operations, tuple):
            object.__setattr__(self, "operations", tuple(self.operations))


# ---------------------------------------------------------------------------
# OrchestrationDecision —— Orchestrator Agent 的结构化输出
# ---------------------------------------------------------------------------

OrchestrationAction = Literal[
    "continue",             # 无需动作，继续等待
    "wait",                 # 等待外部状态变化
    "retry_step",           # 自动重试单个 step
    "pause_plan",           # 暂停 plan
    "resume_plan",          # 恢复 plan
    "create_change_proposal",  # 生成 PlanChangeProposal（走 HITL 流程）
    "request_human",        # 直接向用户发起确认请求
    "cancel_plan",          # 取消整个 plan（必须先经过 HITL）
]


@dataclass(frozen=True, slots=True)
class OrchestrationDecision:
    """Orchestrator Agent 在一个决策循环中的结构化输出。

    使用结构化输出而非自由文本，避免解析歧义。
    ``action`` 必须是 ``OrchestrationAction`` 中的合法值。

    ``proposed_patch`` 仅在 ``action == 'create_change_proposal'`` 时有意义。
    """

    decision_id: str
    plan_id: str
    trigger_event_ids: tuple[str, ...]
    action: OrchestrationAction
    rationale: str                          # LLM 的决策依据（记录用）
    risk_level: RiskLevel = "low"

    target_step_ids: tuple[str, ...] = ()   # 动作针对的 step
    target_artifact_ids: tuple[str, ...] = ()

    # 仅 action=create_change_proposal 时有效
    proposed_change_type: PlanChangeType | None = None
    proposed_change_summary: str = ""
    proposed_patch_ops: tuple[PlanPatchOp, ...] = ()

    # 仅 action=request_human 时有效
    human_question: str = ""
    human_options: tuple[str, ...] = ()

    created_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for attr in ("trigger_event_ids", "target_step_ids",
                     "target_artifact_ids", "proposed_patch_ops", "human_options"):
            val = getattr(self, attr)
            if not isinstance(val, tuple):
                object.__setattr__(self, attr, tuple(val))
