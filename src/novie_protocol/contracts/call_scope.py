"""AgentCallScope —— 平台 → agent 的"单次调用作用域"契约。

**为什么存在**：cortex / tasks-capable agent 这类 agent 自带沙箱能力（自己管 git
workspace / 文件 / token 使用），平台**不**重建 Environment 一等对象
（见 ADR-008 + ARCHITECTURE §1.1.1）。但平台仍然必须告诉 agent：

1. **这次调用属于哪个作用域** —— agent 自己决定是否为此开新 workspace；
2. **凭证的 scope 和 TTL** —— 给 agent 的 `GITHUB_TOKEN` 不应长期全局，
   应是本次任务临时 mint 的；
3. **清理时机约定** —— task 终态后 agent 应在何时回收 workspace / 凭证。

AgentCallScope 作为 ``inputs["__call_scope__"]`` 随 invoke payload 下发。
Agent 侧实现（novie_agent_sdk）提供 helper 拆包。

**平台不执行这些约束**——它是**信任声明 + 协议提示**。真正做隔离的是 agent
自己。AgentCard.sandbox_isolation 告诉平台 agent 的承诺，本对象告诉 agent
每次调用的具体 scope。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

WorkspaceScope = Literal["per_task", "per_session", "shared", "none"]
"""本次调用工作空间的语义范围 —— 给 agent 判断是否新开 workspace。

与 ``AgentCard.sandbox_isolation`` 的差异：
- sandbox_isolation 是 agent 的**能力**（"我能做到 per_task 隔离"）
- WorkspaceScope 是本次调用**平台希望的**范围（"这次请按 per_task 来"）
两者要求一致时 agent 按此开工作空间；冲突时 agent 应走保守策略（更严）。
"""


TokenScopeKind = Literal[
    "per_task",       # 本次 task 专用短 TTL token；task 完成即废
    "per_session",    # session 级共享 token
    "none",           # 本次调用不需要凭证
]
"""平台发给 agent 的凭证的作用域。

给 agent 提示"这个 token 的生命周期"，agent 据此决定是否缓存 / 何时刷新。
实际的发 token 逻辑在平台侧（GitHub App mint / cloud IAM / 等），本字段
只是**声明**。
"""


CleanupWhen = Literal[
    "on_step_complete",  # step 一完成（含 error）平台会发 cleanup
    "on_plan_complete",  # 整个 plan 完成才 cleanup（跨 step 的共用 workspace）
    "agent_managed",     # agent 自己决定，平台不管
    "no_cleanup",        # 本次调用无需 cleanup（对应 none / shared 场景）
]


@dataclass(frozen=True, slots=True)
class CredentialHint:
    """凭证提示 —— 告诉 agent "这把 token 能用多久 / 谁授权的"。

    本对象**不**携带 token 本身（token 在 ``__platform_callback__`` 里或
    专门的凭证交付通道）；只携带元数据，让 agent 能做缓存 / 失效判断。
    """

    kind: TokenScopeKind = "none"
    ttl_seconds: int | None = None
    authorized_by: str | None = None
    # 可选：声明 token 能访问哪些资源（如 ["github:org/repo1", "s3:bucket"]）
    # agent 可据此做权限自检，避免越权
    allowed_resources: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AgentCallScope:
    """随 invoke payload 下发，承载本次调用的作用域约定。

    ``inputs["__call_scope__"]``（**双下划线**，和 ``__platform_callback__`` /
    ``__project_brief__`` 同规则，保留给平台元数据）。
    """

    workspace_scope: WorkspaceScope = "shared"
    cleanup_when: CleanupWhen = "no_cleanup"

    # Tenant / workspace 维度标识，让 agent 据此 namespacing 内部文件系统。
    # 即便 workspace_scope=shared，agent 也应按 tenant 隔离。
    tenant_id: str = ""
    workspace_id: str = ""
    project_id: str | None = None

    # 本次调用的稳定 key，适合当作 workspace 目录名 / cache key 前缀
    # （per_task 模式下 agent 用它开 workspace）。
    scope_key: str = ""

    credentials: CredentialHint = field(default_factory=CredentialHint)

    # 可选：agent 用完可通过 HTTP POST 这个 URL 通知平台"我清理了"
    # （和 long_task_webhook 同签名机制）。不填表示平台不要求 agent 主动上报。
    cleanup_callback_url: str | None = None

    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "workspace_scope": self.workspace_scope,
            "cleanup_when": self.cleanup_when,
            "tenant_id": self.tenant_id,
            "workspace_id": self.workspace_id,
            "project_id": self.project_id,
            "scope_key": self.scope_key,
            "credentials": {
                "kind": self.credentials.kind,
                "ttl_seconds": self.credentials.ttl_seconds,
                "authorized_by": self.credentials.authorized_by,
                "allowed_resources": list(self.credentials.allowed_resources),
            },
            "cleanup_callback_url": self.cleanup_callback_url,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AgentCallScope":
        creds_raw = data.get("credentials") or {}
        credentials = CredentialHint(
            kind=creds_raw.get("kind", "none"),
            ttl_seconds=creds_raw.get("ttl_seconds"),
            authorized_by=creds_raw.get("authorized_by"),
            allowed_resources=tuple(creds_raw.get("allowed_resources") or ()),
        )
        return cls(
            workspace_scope=data.get("workspace_scope", "shared"),
            cleanup_when=data.get("cleanup_when", "no_cleanup"),
            tenant_id=str(data.get("tenant_id") or ""),
            workspace_id=str(data.get("workspace_id") or ""),
            project_id=data.get("project_id"),
            scope_key=str(data.get("scope_key") or ""),
            credentials=credentials,
            cleanup_callback_url=data.get("cleanup_callback_url"),
            metadata=dict(data.get("metadata") or {}),
        )
