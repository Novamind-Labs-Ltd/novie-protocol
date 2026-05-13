from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class TenantScope:
    """多租户隔离边界。所有 Service 入参必带。

    - `tenant_id`    : 顶级隔离键，对应外部系统的 org_id。
    - `workspace_id` : 项目级子键，对应外部系统的 project_id。
    """

    tenant_id: str
    workspace_id: str
    project_id: str | None = None


@dataclass(frozen=True, slots=True)
class IdentityContext:
    """调用方身份。区分人 / Agent / 系统。"""

    principal_id: str
    principal_type: str  # "user" | "agent" | "service"
    roles: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        # 反序列化兜底：见 ExecutionStep.__post_init__。IdentityContext
        # 随 ExecutionContext 一起落 checkpoint，必须过这一步。
        if not isinstance(self.roles, tuple):
            object.__setattr__(self, "roles", tuple(self.roles))


@dataclass(frozen=True, slots=True)
class TrustedHeaders:
    """上游系统传递的已认证请求头契约。

    Novie Gateway 信任上游（API 网关 / BFF / 内部服务）完成 token 验证，
    仅接受以下字段作为身份与租户信息的来源。

    HTTP 头名称约定（全小写）：
        x-novie-org-id        -> org_id
        x-novie-project-id    -> project_id
        x-novie-workspace-id  -> workspace_id (optional; falls back to project_id for legacy callers)
        x-novie-user-id       -> user_id
        x-novie-service-principal -> service_principal (optional alternative to user_id)
        x-novie-session-id    -> session_id       (可选，调用方预先分配)
        x-novie-request-id    -> request_id       (可选，链路追踪 ID)
        x-novie-auth-source   -> auth_source      (可选，标识认证来源)
        x-novie-user-roles    -> deprecated；roles 由 Member Service 返回

    CLI / 本地开发时从环境变量读取（见 .env.example）：
        NOVIE_ORG_ID / NOVIE_PROJECT_ID / NOVIE_USER_ID
    """

    org_id: str
    project_id: str
    user_id: str
    service_principal: str = ""
    workspace_id: str | None = None
    session_id: str | None = None
    request_id: str | None = None
    auth_source: str = "trusted_upstream"
    user_roles: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ExecutionContext:
    """贯穿一次请求 → 工作流 → Agent 执行的不可变上下文。

    ID 分层模型：
        request_id  : 单次 HTTP / CLI 请求粒度，用于 trace / audit。
        session_id  : 用户视角的对话会话 ID，贯穿多轮。
        thread_id   : LangGraph 执行线程 ID（含租户命名空间前缀）。
                      一个 session 内可存在多个 thread（fork / time-travel）。
        workflow_id : 本次编排工作流 ID（非 Reception 阶段时填入）。

    时间旅行与 fork 时：
        - session_id 不变
        - 生成新的 thread_id
        - 在 metadata 中记录 parent_thread_id / forked_from_checkpoint_id
    """

    request_id: str
    session_id: str
    thread_id: str
    tenant: TenantScope
    identity: IdentityContext
    workflow_id: str | None = None
    parent_step_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def fork(self, new_thread_id: str, forked_from_checkpoint_id: str) -> ExecutionContext:
        """派生一个 time-travel fork 用的新上下文。

        保持 session_id / tenant / identity 不变，仅替换 thread_id 并记录 fork 来源。
        """
        return ExecutionContext(
            request_id=self.request_id,
            session_id=self.session_id,
            thread_id=new_thread_id,
            tenant=self.tenant,
            identity=self.identity,
            workflow_id=self.workflow_id,
            parent_step_id=self.parent_step_id,
            metadata={
                **self.metadata,
                "parent_thread_id": self.thread_id,
                "forked_from_checkpoint_id": forked_from_checkpoint_id,
            },
        )
