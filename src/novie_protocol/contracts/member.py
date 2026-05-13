from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from .context import ExecutionContext


@dataclass(frozen=True, slots=True)
class MemberProfile:
    display_name: str
    email: str | None = None
    timezone: str | None = None
    locale: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "display_name": self.display_name,
            "email": self.email,
            "timezone": self.timezone,
            "locale": self.locale,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MemberProfile":
        return cls(
            display_name=str(data["display_name"]),
            email=data.get("email"),
            timezone=data.get("timezone"),
            locale=data.get("locale"),
        )


@dataclass(frozen=True, slots=True)
class MemberTeamBinding:
    team_id: str
    name: str
    role: str

    def to_dict(self) -> dict[str, Any]:
        return {"team_id": self.team_id, "name": self.name, "role": self.role}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MemberTeamBinding":
        return cls(
            team_id=str(data["team_id"]),
            name=str(data["name"]),
            role=str(data["role"]),
        )


@dataclass(frozen=True, slots=True)
class MemberApprovalContext:
    can_approve_risk: tuple[str, ...] = ()
    requires_escalation_for: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("can_approve_risk", "requires_escalation_for"):
            value = getattr(self, name)
            if not isinstance(value, tuple):
                object.__setattr__(self, name, tuple(value))

    def to_dict(self) -> dict[str, Any]:
        return {
            "can_approve_risk": list(self.can_approve_risk),
            "requires_escalation_for": list(self.requires_escalation_for),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "MemberApprovalContext":
        if not data:
            return cls()
        return cls(
            can_approve_risk=tuple(data.get("can_approve_risk") or ()),
            requires_escalation_for=tuple(data.get("requires_escalation_for") or ()),
        )


@dataclass(frozen=True, slots=True)
class MemberPreferences:
    default_language: str | None = None
    cli_verbosity: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "default_language": self.default_language,
            "cli_verbosity": self.cli_verbosity,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "MemberPreferences":
        if not data:
            return cls()
        return cls(
            default_language=data.get("default_language"),
            cli_verbosity=data.get("cli_verbosity"),
        )


@dataclass(frozen=True, slots=True)
class MemberRuntimeContext:
    member_id: str
    tenant_id: str
    workspace_ids: tuple[str, ...]
    default_project_id: str | None
    profile: MemberProfile
    roles: tuple[str, ...]
    teams: tuple[MemberTeamBinding, ...]
    permissions: tuple[str, ...]
    approval: MemberApprovalContext
    preferences: MemberPreferences
    metadata: dict[str, Any] = field(default_factory=dict)
    snapshot_id: str | None = None
    frozen_at: str | None = None

    def __post_init__(self) -> None:
        for name in ("workspace_ids", "roles", "teams", "permissions"):
            value = getattr(self, name)
            if not isinstance(value, tuple):
                object.__setattr__(self, name, tuple(value))

    def to_dict(self) -> dict[str, Any]:
        return {
            "member_id": self.member_id,
            "tenant_id": self.tenant_id,
            "workspace_ids": list(self.workspace_ids),
            "default_project_id": self.default_project_id,
            "profile": self.profile.to_dict(),
            "roles": list(self.roles),
            "teams": [team.to_dict() for team in self.teams],
            "permissions": list(self.permissions),
            "approval": self.approval.to_dict(),
            "preferences": self.preferences.to_dict(),
            "metadata": dict(self.metadata),
            "snapshot_id": self.snapshot_id,
            "frozen_at": self.frozen_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MemberRuntimeContext":
        return cls(
            member_id=str(data["member_id"]),
            tenant_id=str(data["tenant_id"]),
            workspace_ids=tuple(data.get("workspace_ids") or ()),
            default_project_id=data.get("default_project_id"),
            profile=MemberProfile.from_dict(dict(data["profile"])),
            roles=tuple(data.get("roles") or ()),
            teams=tuple(
                MemberTeamBinding.from_dict(dict(item))
                for item in data.get("teams", ())
            ),
            permissions=tuple(data.get("permissions") or ()),
            approval=MemberApprovalContext.from_dict(data.get("approval")),
            preferences=MemberPreferences.from_dict(data.get("preferences")),
            metadata=dict(data.get("metadata") or {}),
            snapshot_id=data.get("snapshot_id"),
            frozen_at=data.get("frozen_at"),
        )


class MemberContextClient(Protocol):
    async def get_runtime_context(
        self,
        ctx: ExecutionContext,
        member_id: str | None,
    ) -> MemberRuntimeContext: ...

    async def freeze_runtime_context_snapshot(
        self,
        ctx: ExecutionContext,
        member_id: str | None,
    ) -> MemberRuntimeContext: ...

    async def get_runtime_context_snapshot(
        self,
        snapshot_id: str,
    ) -> MemberRuntimeContext | None: ...
