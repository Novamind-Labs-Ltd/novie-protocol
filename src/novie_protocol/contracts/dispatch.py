"""Dispatch 层契约。

DispatchService 把 ExecutionPlan 编译并执行后，对外吐两类东西：
- `DispatchEvent` ：流式渲染（CLI / SSE 用），表达"现在跑到哪一步"。
- `DispatchResult`：终态聚合（一次性等结果用），含每个 step 的输出。

事件 schema 刻意与 reception 的 trace 事件同形（`event` / `source` / 自带 metadata），
让 CLI 能用同一套 `_render_trace_event` 渲染两条链路，避免双套渲染分叉。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from .failure_taxonomy import EXECUTION_FAILURE_TYPES

DispatchEventKind = Literal[
    "plan_start",      # dispatch 开始；payload: plan_id, pattern, step_count
    "step_start",      # 单 step 进入；payload: step_id, agent_id, revision_count
    "step_content",    # 单 step 流式内容；payload: step_id, agent_id, content
    "step_status",     # 单 step 的结构化进度状态；payload: step_id, agent_id,
                       #   status_kind, message, task_status, task_id
    "step_waiting",    # 单 step 进入等待态（例如外部 task 请求人工输入）；payload:
                       #   step_id, agent_id, message, task_status, task_id, resume_ref
    "step_retry",      # transient failure 触发单 step 重试；payload: step_id,
                       #   agent_id, attempt, max_retries, failure_type, error,
                       #   backoff_seconds
    "step_tool_call",  # step 内 agent 正在调用工具；payload: step_id, agent_id,
                       #   tool_name, tool_args, tool_call_id
    "step_tool_result",# 对应工具返回；payload: step_id, agent_id, tool_name,
                       #   tool_call_id, tool_result（caller 已截断）
    "step_complete",   # 单 step 完成；payload: step_id, agent_id, output_summary
    "step_error",      # 单 step 出错；payload: step_id, agent_id, error
    "gate_pending",    # 进入 HITL gate，等待人工裁决；payload: gate_id,
                       #   gate_spec_id, after_step_id, title, description,
                       #   allowed_actions, step_output
    "gate_resolved",   # gate 已被外部 resolve；payload: gate_id, decision
    "gate_revision_cap_hit",  # request_changes 达到 pattern_config.max_revisions_per_step
                              #   上限，自动降级为 approve 之前发；payload:
                              #   gate_id, after_step_id, max_revisions,
                              #   attempted_revision
    "plan_complete",   # 整 plan 完成；payload: plan_id
    "plan_replanned",  # plan 版本被 re-plan 替换；payload: plan_id,
                       #   old_plan_version, new_plan_version, trigger_source, reason
    "plan_paused",     # graph interrupt 挂起（durable 长任务 / HITL 等外部 resume）；
                       #   payload: plan_id, reason, tracker_id?, agent_task_id?, step_id?,
                       #   step_outputs（挂起前已完成的 step）
    "plan_error",      # 整 plan 终止；payload: plan_id, error
    "quota_blocked",   # P0-4：dispatch preflight quota 拒绝启动；payload:
                       #   plan_id, scope, scope_value, metric, window, limit,
                       #   current_value, action, reason
    "quota_warning",   # P0-4：preflight 通过但已经 warn（warn_at 命中或 action=warn
                       #   时越限）；payload 同 quota_blocked，allow=true
]


@dataclass(frozen=True, slots=True)
class DispatchEvent:
    """单条 dispatch 进度事件。

    `metadata` 是结构化 payload，CLI / SSE 自行决定展示哪些字段。
    `source` 固定为 ``"dispatch"``，便于与 reception trace 事件区分。
    """

    kind: DispatchEventKind
    metadata: dict[str, Any] = field(default_factory=dict)
    source: str = "dispatch"

    def __post_init__(self) -> None:
        if self.kind not in ("step_error", "plan_error"):
            return
        failure_type = str(self.metadata.get("failure_type") or "")
        if failure_type not in EXECUTION_FAILURE_TYPES:
            raise ValueError(
                f"DispatchEvent {self.kind!r} requires metadata.failure_type"
            )


@dataclass(frozen=True, slots=True)
class DispatchResult:
    """DispatchService.run 的终态聚合。

    `step_outputs` 的 key 是 ``ExecutionStep.step_id``，value 是对应 agent
    `ainvoke` 的返回 dict，原样透传，不做二次封装。
    """

    plan_id: str
    pattern: str
    step_outputs: dict[str, dict[str, Any]] = field(default_factory=dict)
