"""Agent SDK v2 contract —— manifest + task lifecycle + protocol_mode。
对应 TEMPORAL_A2A_AGENT_RUNTIME_MIGRATION.md §4.2、§4.3。

目标：定义 Python / Rust SDK 共用的行为 contract，为完整 SDK 实现提供基础。
  - manifest 字段 → AgentManifestV2 + ExecutionHints
  - task lifecycle 状态机 → TaskLifecycleSpec / TASK_TRANSITIONS
  - protocol_mode 三模式约束 → ProtocolMode / PROTOCOL_ENDPOINTS

开发者体验目标：
    from novie_agent_sdk import Agent, TaskContext
    async def handle_task(ctx: TaskContext, payload: dict) -> dict: ...
    agent = Agent.from_manifest(".well-known/agent.json")
    agent.task(handle_task)
    agent.serve()
"""
# ruff: noqa: RUF001, RUF002, RUF003
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from .capability import (
    AgentCapabilityManifestEntry,
    validate_capability_description,
)

# ── Protocol modes ──────────────────────────────────────────────────────────────

ProtocolMode = Literal["simple", "stream", "tasks"]
"""A2A Agent 支持的三种调用协议。

simple : POST /invoke
         同步 JSON 请求/响应，适合 ≤ 60s 的短任务。
         Temporal invoke_a2a_agent Activity 用 simple 协议时直接等 HTTP 200。

stream : POST /stream → SSE stream
         Agent 边处理边流式推送 content / done 事件。
         适合长文本生成类 agent；Activity 通过 heartbeat 保活。

tasks  : POST /tasks → { task_id }
         POST 创建任务后异步，Platform 通过 GET /tasks/{id} 轮询；
         GET /tasks/{id}/events  拉取中间事件；
         GET /tasks/{id}/result  拉取最终结果。
         适合长跑 / HITL / 文件生成类 agent。
"""

DurabilityLevel = Literal["none", "result_cache", "task_store"]
"""Agent-side accepted-work durability claim.

none         : stateless one-shot; no accepted work survives past the response.
result_cache : one-shot idempotency/result cache survives retries/restart.
task_store   : async task records/events/results survive restart.
"""

# 每种 protocol_mode 必须实现的 HTTP 端点
PROTOCOL_ENDPOINTS: dict[str, list[str]] = {
    "simple": [
        "GET /healthz",
        "GET /.well-known/agent.json",
        "POST /invoke",
    ],
    "stream": [
        "GET /healthz",
        "GET /.well-known/agent.json",
        "POST /stream",
    ],
    "tasks": [
        "GET /healthz",
        "GET /.well-known/agent.json",
        "POST /tasks",
        "GET /tasks/{task_id}",
        "GET /tasks/{task_id}/events",
        "GET /tasks/{task_id}/result",
        "POST /tasks/{task_id}/cancel",
    ],
}


# ── Execution hints ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ExecutionHints:
    """Agent 执行时的约束和提示，由 manifest 声明。

    Platform invoke_a2a_agent Activity 根据这些 hints 配置：
    - start_to_close_timeout（来自 max_duration_seconds）
    - retry_policy（来自 idempotent + manifest RetryPolicy）
    - cancel 调用（来自 supports_cancel）
    - event 拉取（来自 emits_events）
    """

    expected_duration_seconds: int = 60
    max_duration_seconds: int = 3600
    idempotent: bool = False
    supports_cancel: bool = False
    supports_resume: bool = False
    emits_events: bool = False
    durability: DurabilityLevel = "none"

    def to_dict(self) -> dict[str, Any]:
        return {
            "expected_duration_seconds": self.expected_duration_seconds,
            "max_duration_seconds": self.max_duration_seconds,
            "idempotent": self.idempotent,
            "supports_cancel": self.supports_cancel,
            "supports_resume": self.supports_resume,
            "emits_events": self.emits_events,
            "durability": self.durability,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ExecutionHints:
        return cls(
            expected_duration_seconds=int(d.get("expected_duration_seconds", 60)),
            max_duration_seconds=int(d.get("max_duration_seconds", 3600)),
            idempotent=bool(d.get("idempotent", False)),
            supports_cancel=bool(d.get("supports_cancel", False)),
            supports_resume=bool(d.get("supports_resume", False)),
            emits_events=bool(d.get("emits_events", False)),
            durability=d.get("durability", "none"),
        )


# ── Manifest v2 contract ──────────────────────────────────────────────────────

@dataclass(frozen=True)
class AgentManifestV2:
    """Agent manifest v2 完整 contract（.well-known/agent.json）。

    对应 TEMPORAL_A2A_AGENT_RUNTIME_MIGRATION.md §4.3。
    Platform 通过 GET /.well-known/agent.json 读取此结构（JSON 格式）。

    关键变化（相对于 v1）：
    - protocol_mode 上升为顶级字段，不再藏在 metadata 中。
    - endpoint 上升为顶级字段，由 manifest 声明。
    - execution hints 独立为 ExecutionHints sub-object。
    - required_secrets 声明 agent 所需的 secret key 名称。
    - supports_cancel / supports_resume 移到 execution 中。
    """

    agent_id: str                       # 全局唯一，不可变
    name: str                           # 展示名
    version: str                        # semver
    kind: str                           # "expert_basic" | "expert_complex"
    runtime: str                        # "external_a2a"（v2 全部是 external）
    capabilities: tuple[str, ...]       # IAM catalog 里的 capability 名
    declared_gates: tuple[str, ...]     # agent 声明的 HITL gate id 列表
    protocol_mode: ProtocolMode         # simple | stream | tasks
    endpoint: str = ""                  # agent 服务地址（注册到 Platform 时使用）
    capability_manifest: tuple[AgentCapabilityManifestEntry, ...] = field(default_factory=tuple)

    # 执行约束和提示
    execution: ExecutionHints = field(default_factory=ExecutionHints)

    # agent 运行所需 secret key 名称（Platform 通过 invocation boundary 注入）
    required_secrets: tuple[str, ...] = field(default_factory=tuple)

    # 其余保留字段
    supports_streaming: bool = False
    sandbox_isolation: str = "shared"
    task_bundles_path: str = ""
    metadata: dict = field(default_factory=dict)

    def required_endpoints(self) -> list[str]:
        """返回该 agent 必须实现的 HTTP 端点列表。"""
        return PROTOCOL_ENDPOINTS[self.protocol_mode]

    def validate(self) -> list[str]:
        """返回违规列表（空 = 合法）。"""
        errors: list[str] = []
        if not self.agent_id:
            errors.append("agent_id must be non-empty")
        if not self.version:
            errors.append("version must be non-empty")
        if self.protocol_mode not in ("simple", "stream", "tasks"):
            errors.append(f"unknown protocol_mode: {self.protocol_mode!r}")
        if self.execution.supports_cancel and self.protocol_mode != "tasks":
            errors.append("execution.supports_cancel=true requires protocol_mode='tasks'")
        if self.execution.supports_resume and self.protocol_mode != "tasks":
            errors.append("execution.supports_resume=true requires protocol_mode='tasks'")
        if self.execution.emits_events and self.protocol_mode not in ("tasks", "stream"):
            errors.append("execution.emits_events=true requires protocol_mode='tasks' or 'stream'")
        if self.execution.durability not in ("none", "result_cache", "task_store"):
            errors.append(
                "execution.durability must be one of 'none', 'result_cache', or 'task_store'"
            )
        for capability in self.capability_manifest:
            if not capability.capability_id:
                errors.append("capability_manifest entries must have non-empty capability_id")
                continue
            # Description-quality gate — see capability.py for rules.
            # The CapabilityPicker (RoutingReplanner) depends on rich
            # descriptions for correct routing; a thin description must
            # block registration outright.
            errors.extend(validate_capability_description(capability))
        return errors

    def to_dict(self) -> dict[str, Any]:
        """序列化为 JSON-compatible dict（用于 .well-known/agent.json）。"""
        return {
            "$schema": "https://novie.dev/schemas/agent-manifest-v2.json",
            "agent_id": self.agent_id,
            "name": self.name,
            "version": self.version,
            "kind": self.kind,
            "runtime": self.runtime,
            "capabilities": list(self.capabilities),
            "capability_manifest": [
                capability.to_dict() for capability in self.capability_manifest
            ],
            "declared_gates": list(self.declared_gates),
            "protocol_mode": self.protocol_mode,
            "endpoint": self.endpoint,
            "execution": self.execution.to_dict(),
            "required_secrets": list(self.required_secrets),
            "supports_streaming": self.supports_streaming,
            "sandbox_isolation": self.sandbox_isolation,
            "task_bundles_path": self.task_bundles_path,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> AgentManifestV2:
        """从 JSON dict 解析 manifest（.well-known/agent.json 内容）。"""
        # 兼容旧版：protocol_mode 可能在 metadata 里
        protocol_mode: ProtocolMode = (
            d.get("protocol_mode")
            or d.get("metadata", {}).get("protocol_mode", "simple")
        )

        # 兼容旧版：supports_cancel/resume 可能在顶级或 metadata 里
        meta = d.get("metadata", {})
        execution_raw = d.get("execution", {})
        if not execution_raw:
            execution_raw = {
                "supports_cancel": d.get("supports_cancel", meta.get("supports_cancel", False)),
                "supports_resume": d.get("supports_resume", meta.get("supports_resume", False)),
                "emits_events": meta.get("emits_events", protocol_mode in ("tasks", "stream")),
            }
        execution = ExecutionHints.from_dict(execution_raw)

        # 清理 metadata：去掉已提升到顶级的字段
        clean_meta = {
            k: v for k, v in meta.items()
            if k
            not in (
                "protocol_mode",
                "supports_cancel",
                "supports_resume",
                "supports_streaming",
                "emits_events",
            )
        }

        return cls(
            agent_id=d.get("agent_id", ""),
            name=d.get("name", ""),
            version=d.get("version", ""),
            kind=d.get("kind", "expert_basic"),
            runtime=d.get("runtime", "external_a2a"),
            capabilities=tuple(d.get("capabilities", [])),
            capability_manifest=tuple(
                AgentCapabilityManifestEntry.from_dict(dict(item))
                for item in d.get("capability_manifest", [])
            ),
            declared_gates=tuple(d.get("declared_gates", [])),
            protocol_mode=protocol_mode,
            endpoint=d.get("endpoint", ""),
            execution=execution,
            required_secrets=tuple(d.get("required_secrets", [])),
            supports_streaming=d.get("supports_streaming", meta.get("supports_streaming", False)),
            sandbox_isolation=d.get("sandbox_isolation", "shared"),
            task_bundles_path=d.get("task_bundles_path", ""),
            metadata=clean_meta,
        )

    @classmethod
    def from_file(cls, path: str | Path) -> AgentManifestV2:
        """从文件路径加载 manifest。"""
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls.from_dict(data)


# ── Task lifecycle state machine ──────────────────────────────────────────────

TaskLifecycleStatus = Literal[
    "pending",
    "queued",
    "running",
    "waiting_for_input",
    "waiting_for_human",
    "completed",
    "failed",
    "cancelled",
]

# 允许的状态跃迁（source → set of valid targets）
# Platform invoke_a2a_agent Activity 依赖这个状态机决定何时终止轮询。
TASK_TRANSITIONS: dict[str, frozenset[str]] = {
    "pending":              frozenset({"queued", "running", "completed", "failed", "cancelled"}),
    "queued":               frozenset({"running", "completed", "failed", "cancelled"}),
    "running":              frozenset({"waiting_for_input", "waiting_for_human",
                                        "completed", "failed", "cancelled"}),
    "waiting_for_input":    frozenset({"running", "failed", "cancelled"}),
    "waiting_for_human":    frozenset({"running", "failed", "cancelled"}),
    "completed":            frozenset(),   # terminal
    "failed":               frozenset(),   # terminal
    "cancelled":            frozenset(),   # terminal
}

TERMINAL_STATUSES: frozenset[str] = frozenset({"completed", "failed", "cancelled"})
WAIT_STATUSES: frozenset[str] = frozenset({"waiting_for_input", "waiting_for_human"})


def is_terminal(status: str) -> bool:
    return status in TERMINAL_STATUSES


def is_valid_transition(from_status: str, to_status: str) -> bool:
    """检查状态跃迁是否合法。"""
    return to_status in TASK_TRANSITIONS.get(from_status, frozenset())


# ── Task event kinds ──────────────────────────────────────────────────────────

TaskEventKind = Literal[
    "status_changed",
    "message",
    "artifact_created",
    "evidence_created",
    "human_input_requested",
    "task_completed",
    "task_failed",
]

TERMINAL_EVENT_KINDS: frozenset[str] = frozenset({"task_completed", "task_failed"})

# ── Conformance contract checks ───────────────────────────────────────────────

@dataclass
class ConformanceViolation:
    rule: str
    message: str
    severity: Literal["error", "warning"]


def check_task_event_sequence(events: list[dict]) -> list[ConformanceViolation]:
    """校验 task events 序列是否符合 SDK v2 contract。

    规则：
    R1. events 非空（running 任务至少要有一个 status_changed）
    R2. 最后一个 event 必须是 terminal kind（task_completed / task_failed）
    R3. terminal event 之后不得有其他事件
    R4. 每个 event 必须有 event_id、task_id、kind、timestamp
    """
    violations: list[ConformanceViolation] = []

    if not events:
        violations.append(ConformanceViolation(
            rule="R1", message="task events must be non-empty", severity="warning"
        ))
        return violations

    for i, ev in enumerate(events):
        for required_field in ("event_id", "task_id", "kind", "timestamp"):
            if required_field not in ev:
                violations.append(ConformanceViolation(
                    rule="R4",
                    message=f"event[{i}] missing required field '{required_field}'",
                    severity="error",
                ))

    last = events[-1]
    if last.get("kind") not in TERMINAL_EVENT_KINDS:
        violations.append(ConformanceViolation(
            rule="R2",
            message=(
                f"last event kind must be terminal "
                f"(task_completed/task_failed), got {last.get('kind')!r}"
            ),
            severity="warning",
        ))

    terminal_index = next(
        (i for i, ev in enumerate(events) if ev.get("kind") in TERMINAL_EVENT_KINDS),
        None,
    )
    if terminal_index is not None and terminal_index < len(events) - 1:
        violations.append(ConformanceViolation(
            rule="R3",
            message="events appear after terminal event kind",
            severity="error",
        ))

    return violations


def check_status_transitions(status_sequence: list[str]) -> list[ConformanceViolation]:
    """校验 task 状态跃迁序列是否合法。"""
    violations: list[ConformanceViolation] = []
    for i in range(len(status_sequence) - 1):
        src = status_sequence[i]
        dst = status_sequence[i + 1]
        if not is_valid_transition(src, dst):
            violations.append(ConformanceViolation(
                rule="T1",
                message=f"illegal status transition: {src!r} → {dst!r}",
                severity="error",
            ))
    return violations
