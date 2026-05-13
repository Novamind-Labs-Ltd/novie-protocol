"""Project runtime context contracts.

Novie owns orchestration and capability invocation.  The external Project
Management System owns project configuration.  These dataclasses define the
Novie-facing adapter contract and the snapshot shape that dispatch can freeze
for long-running plans.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from .context import ExecutionContext

CapabilityBindingScope = Literal["workspace", "project"]
KnowledgeMode = Literal["summary_only", "retrieval_only", "summary_plus_retrieval", "disabled"]


@dataclass(frozen=True, slots=True)
class ProjectRepository:
    provider: str
    owner: str
    name: str
    default_branch: str
    protected_branches: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.protected_branches, tuple):
            object.__setattr__(self, "protected_branches", tuple(self.protected_branches))

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "owner": self.owner,
            "name": self.name,
            "default_branch": self.default_branch,
            "protected_branches": list(self.protected_branches),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProjectRepository:
        return cls(
            provider=str(data["provider"]),
            owner=str(data["owner"]),
            name=str(data["name"]),
            default_branch=str(data["default_branch"]),
            protected_branches=tuple(data.get("protected_branches") or ()),
        )


@dataclass(frozen=True, slots=True)
class IterationContext:
    current_sprint: str | None = None
    sprint_goal: str | None = None
    sprint_ends_at: str | None = None
    definition_of_done: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.definition_of_done, tuple):
            object.__setattr__(self, "definition_of_done", tuple(self.definition_of_done))

    def to_dict(self) -> dict[str, Any]:
        return {
            "current_sprint": self.current_sprint,
            "sprint_goal": self.sprint_goal,
            "sprint_ends_at": self.sprint_ends_at,
            "definition_of_done": list(self.definition_of_done),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> IterationContext:
        if not data:
            return cls()
        return cls(
            current_sprint=data.get("current_sprint"),
            sprint_goal=data.get("sprint_goal"),
            sprint_ends_at=data.get("sprint_ends_at"),
            definition_of_done=tuple(data.get("definition_of_done") or ()),
        )


@dataclass(frozen=True, slots=True)
class StakeholderMatrix:
    approvers_by_risk: dict[str, tuple[str, ...]] = field(default_factory=dict)
    default_reviewer: str | None = None
    escalation_chain: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "approvers_by_risk",
            {
                str(key): tuple(value)
                for key, value in dict(self.approvers_by_risk).items()
            },
        )
        if not isinstance(self.escalation_chain, tuple):
            object.__setattr__(self, "escalation_chain", tuple(self.escalation_chain))

    def to_dict(self) -> dict[str, Any]:
        return {
            "approvers_by_risk": {
                key: list(value) for key, value in self.approvers_by_risk.items()
            },
            "default_reviewer": self.default_reviewer,
            "escalation_chain": list(self.escalation_chain),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> StakeholderMatrix:
        if not data:
            return cls()
        return cls(
            approvers_by_risk={
                str(key): tuple(value)
                for key, value in dict(data.get("approvers_by_risk") or {}).items()
            },
            default_reviewer=data.get("default_reviewer"),
            escalation_chain=tuple(data.get("escalation_chain") or ()),
        )


@dataclass(frozen=True, slots=True)
class ProjectConventions:
    code_style_ref: str | None = None
    commit_convention: str | None = None
    pr_template_ref: str | None = None
    runbook_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.runbook_refs, tuple):
            object.__setattr__(self, "runbook_refs", tuple(self.runbook_refs))

    def to_dict(self) -> dict[str, Any]:
        return {
            "code_style_ref": self.code_style_ref,
            "commit_convention": self.commit_convention,
            "pr_template_ref": self.pr_template_ref,
            "runbook_refs": list(self.runbook_refs),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> ProjectConventions:
        if not data:
            return cls()
        return cls(
            code_style_ref=data.get("code_style_ref"),
            commit_convention=data.get("commit_convention"),
            pr_template_ref=data.get("pr_template_ref"),
            runbook_refs=tuple(data.get("runbook_refs") or ()),
        )


@dataclass(frozen=True, slots=True)
class TrackerBinding:
    vendor: str
    project_id: str
    issue_prefix: str | None = None
    default_assignee: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "vendor": self.vendor,
            "project_id": self.project_id,
            "issue_prefix": self.issue_prefix,
            "default_assignee": self.default_assignee,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TrackerBinding:
        return cls(
            vendor=str(data["vendor"]),
            project_id=str(data["project_id"]),
            issue_prefix=data.get("issue_prefix"),
            default_assignee=data.get("default_assignee"),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True, slots=True)
class ProjectCapabilityBinding:
    capability_id: str
    scope: CapabilityBindingScope
    enabled_for: tuple[str, ...]
    policy_profile: str
    credential_ref: str | None = None
    config: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.enabled_for, tuple):
            object.__setattr__(self, "enabled_for", tuple(self.enabled_for))

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "scope": self.scope,
            "enabled_for": list(self.enabled_for),
            "policy_profile": self.policy_profile,
            "credential_ref": self.credential_ref,
            "config": dict(self.config),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProjectCapabilityBinding:
        return cls(
            capability_id=str(data["capability_id"]),
            scope=data["scope"],
            enabled_for=tuple(data.get("enabled_for") or ()),
            policy_profile=str(data.get("policy_profile") or ""),
            credential_ref=data.get("credential_ref"),
            config=dict(data.get("config") or {}),
        )


@dataclass(frozen=True, slots=True)
class KnowledgeContext:
    namespace: str
    mode: KnowledgeMode
    shared_namespaces: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.shared_namespaces, tuple):
            object.__setattr__(self, "shared_namespaces", tuple(self.shared_namespaces))

    def to_dict(self) -> dict[str, Any]:
        return {
            "namespace": self.namespace,
            "mode": self.mode,
            "shared_namespaces": list(self.shared_namespaces),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> KnowledgeContext:
        return cls(
            namespace=str(data["namespace"]),
            mode=data["mode"],
            shared_namespaces=tuple(data.get("shared_namespaces") or ()),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True, slots=True)
class LLMProjectProfile:
    profile: str
    budget_ref: str | None = None
    fallback_profile: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile": self.profile,
            "budget_ref": self.budget_ref,
            "fallback_profile": self.fallback_profile,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LLMProjectProfile:
        return cls(
            profile=str(data["profile"]),
            budget_ref=data.get("budget_ref"),
            fallback_profile=data.get("fallback_profile"),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True, slots=True)
class CredentialLease:
    credential_ref: str
    token: str
    issued_at: str
    expires_at: str
    scope: tuple[str, ...]
    refreshable: bool = False
    refresh_capability: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.scope, tuple):
            object.__setattr__(self, "scope", tuple(self.scope))

    def to_dict(self, *, include_token: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "credential_ref": self.credential_ref,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "scope": list(self.scope),
            "refreshable": self.refreshable,
            "refresh_capability": self.refresh_capability,
        }
        if include_token:
            payload["token"] = self.token
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CredentialLease:
        return cls(
            credential_ref=str(data["credential_ref"]),
            token=str(data.get("token") or ""),
            issued_at=str(data["issued_at"]),
            expires_at=str(data["expires_at"]),
            scope=tuple(data.get("scope") or ()),
            refreshable=bool(data.get("refreshable", False)),
            refresh_capability=data.get("refresh_capability"),
        )


@dataclass(frozen=True, slots=True)
class ProjectRuntimeContext:
    """Complete project runtime context returned by the project adapter."""

    project_id: str
    tenant_id: str
    workspace_id: str
    repo: ProjectRepository
    iteration: IterationContext
    stakeholders: StakeholderMatrix
    conventions: ProjectConventions
    tracker_bindings: tuple[TrackerBinding, ...]
    capability_bindings: tuple[ProjectCapabilityBinding, ...]
    knowledge: KnowledgeContext
    llm: LLMProjectProfile
    snapshot_id: str | None = None
    frozen_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("tracker_bindings", "capability_bindings"):
            value = getattr(self, name)
            if not isinstance(value, tuple):
                object.__setattr__(self, name, tuple(value))

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "tenant_id": self.tenant_id,
            "workspace_id": self.workspace_id,
            "repo": self.repo.to_dict(),
            "iteration": self.iteration.to_dict(),
            "stakeholders": self.stakeholders.to_dict(),
            "conventions": self.conventions.to_dict(),
            "tracker_bindings": [item.to_dict() for item in self.tracker_bindings],
            "capability_bindings": [item.to_dict() for item in self.capability_bindings],
            "knowledge": self.knowledge.to_dict(),
            "llm": self.llm.to_dict(),
            "snapshot_id": self.snapshot_id,
            "frozen_at": self.frozen_at,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProjectRuntimeContext:
        return cls(
            project_id=str(data["project_id"]),
            tenant_id=str(data["tenant_id"]),
            workspace_id=str(data["workspace_id"]),
            repo=ProjectRepository.from_dict(dict(data["repo"])),
            iteration=IterationContext.from_dict(data.get("iteration")),
            stakeholders=StakeholderMatrix.from_dict(data.get("stakeholders")),
            conventions=ProjectConventions.from_dict(data.get("conventions")),
            tracker_bindings=tuple(
                TrackerBinding.from_dict(dict(item))
                for item in data.get("tracker_bindings", ())
            ),
            capability_bindings=tuple(
                ProjectCapabilityBinding.from_dict(dict(item))
                for item in data.get("capability_bindings", ())
            ),
            knowledge=KnowledgeContext.from_dict(dict(data["knowledge"])),
            llm=LLMProjectProfile.from_dict(dict(data["llm"])),
            snapshot_id=data.get("snapshot_id"),
            frozen_at=data.get("frozen_at"),
            metadata=dict(data.get("metadata") or {}),
        )


class ProjectContextClient(Protocol):
    """Novie-facing adapter interface for the external Project Management System."""

    async def get_runtime_context(
        self,
        ctx: ExecutionContext,
        project_id: str | None,
    ) -> ProjectRuntimeContext: ...

    async def freeze_runtime_context_snapshot(
        self,
        ctx: ExecutionContext,
        project_id: str | None,
    ) -> ProjectRuntimeContext: ...

    async def get_runtime_context_snapshot(
        self,
        snapshot_id: str,
    ) -> ProjectRuntimeContext | None: ...

    async def list_capability_bindings(
        self,
        ctx: ExecutionContext,
        project_id: str | None,
    ) -> list[ProjectCapabilityBinding]: ...

    async def get_knowledge_context(
        self,
        ctx: ExecutionContext,
        project_id: str | None,
    ) -> KnowledgeContext: ...

    async def get_iteration_context(
        self,
        ctx: ExecutionContext,
        project_id: str | None,
    ) -> IterationContext: ...

    async def get_stakeholder_matrix(
        self,
        ctx: ExecutionContext,
        project_id: str | None,
    ) -> StakeholderMatrix: ...

    async def get_conventions(
        self,
        ctx: ExecutionContext,
        project_id: str | None,
    ) -> ProjectConventions: ...

    async def get_tracker_bindings(
        self,
        ctx: ExecutionContext,
        project_id: str | None,
    ) -> list[TrackerBinding]: ...

    async def exchange_credential(
        self,
        ctx: ExecutionContext,
        credential_ref: str,
        purpose: str,
        ttl_s: int,
    ) -> CredentialLease: ...
