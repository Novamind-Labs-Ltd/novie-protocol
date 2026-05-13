"""ExpertAgent Protocol & AgentCard."""
# ruff: noqa: RUF001, RUF002
from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from .contracts import AgentCapabilityManifestEntry, ExecutionContext
from .services import PlatformServices

AgentKind = Literal["platform", "expert_basic", "expert_complex"]
RuntimeShape = Literal["langgraph", "deepagents", "react", "external_a2a"]

SandboxIsolation = Literal["per_task", "per_session", "shared", "none"]
"""Agent 对"单次调用的隔离粒度"的自声明。

- ``per_task``    : agent 会为每次 invoke 开独立工作空间（cortex 这类跑代码
                    的复杂 agent 的合理值）
- ``per_session`` : 同一 session 内复用，不同 session 隔离
- ``shared``      : 所有调用共享同一个工作空间（无状态 LLM agent 的常态）
- ``none``        : agent 明确声明"没有工作空间概念"（如纯问答 / 纯总结）

平台不验证 agent 实际行为 —— 这是**信任声明**，用于：
1. Dispatch 决定是否为该 agent 类型发放 per_task 临时 token
2. UI 决定是否对用户展示 workspace 生命周期信息
3. 管理端审计是否存在可疑的跨租户状态共享
"""


@dataclass(frozen=True, slots=True)
class AgentCard:
    """A2A 风格的 Agent 描述符。物理形态：`<agent>/.well-known/agent.json`。"""

    agent_id: str
    name: str
    version: str
    kind: AgentKind
    runtime: RuntimeShape
    capabilities: tuple[str, ...]
    skills: tuple[str, ...] = ()
    declared_gates: tuple[str, ...] = ()
    capability_manifest: tuple[AgentCapabilityManifestEntry, ...] = ()
    sandbox_isolation: SandboxIsolation = "shared"
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("capabilities", "skills", "declared_gates", "capability_manifest"):
            value = getattr(self, name)
            if not isinstance(value, tuple):
                object.__setattr__(self, name, tuple(value))


@dataclass(frozen=True, slots=True)
class AgentStreamEvent:
    """Canonical agent-side streaming event.

    Four kinds — the first three stream **during** agent execution, ``final``
    marks completion with the structured output.

    - ``content``      : incremental user-visible text (LLM token delta).
    - ``tool_call``    : agent is about to invoke a tool; ``tool_name`` +
                         ``tool_args`` (parsed) + ``tool_call_id`` populated.
    - ``tool_result``  : tool returned; ``tool_name`` + ``tool_result`` (str,
                         truncated by caller if needed) + ``tool_call_id`` populated.
    - ``final``        : single terminal event; ``output`` is the full step
                         output dict that DispatchService forwards downstream.

    ``tool_call_id`` ties a ``tool_call`` to its matching ``tool_result`` so
    UIs can collapse the pair into one line. Missing/unknown ids are allowed;
    renderers should tolerate unpaired events.
    """

    kind: Literal["content", "tool_call", "tool_result", "final"]
    content: str = ""
    output: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    tool_name: str | None = None
    tool_args: dict[str, Any] | None = None
    tool_result: str | None = None
    tool_call_id: str | None = None


class ExpertAgent(Protocol):
    """All expert agents must implement this minimal contract.

    The platform only talks to agents through this protocol. Agents can be
    implemented with LangGraph, DeepAgents, ReAct, or anything else internally.
    """

    card: AgentCard

    async def astream(
        self,
        ctx: ExecutionContext,
        inputs: dict[str, Any],
        services: PlatformServices,
    ) -> AsyncIterator[AgentStreamEvent]: ...

    async def ainvoke(
        self,
        ctx: ExecutionContext,
        inputs: dict[str, Any],
        services: PlatformServices,
    ) -> dict[str, Any]: ...
