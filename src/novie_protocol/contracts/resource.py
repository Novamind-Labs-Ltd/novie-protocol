"""Universal Resource contracts (UNIVERSAL_CAPABILITY W3).

Reception resolves natural-language references — "this run", "README
ticket", "current project", "the PR from yesterday" — to canonical
``ResourceRef``s through ``ResourceGraph``. Every kind of platform
state that a capability can read or produce projects onto these
shapes:

- workbench / PMS issues
- runs / workflows
- sessions
- artifacts
- agents / capabilities
- third-party adapter resources (GitHub repos / PRs / issues, Notion
  pages, Jira tickets, Langfuse traces, ...)

The shapes are deliberately thin — providers carry richer
provider-specific state on ``Resource.metadata`` rather than growing
union types. Reception/Planner only consume what's on the
``Resource`` dataclass; safe projections.
"""
# ruff: noqa: RUF001, RUF002, RUF003
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


PermissionAction = Literal["read", "write", "delete", "execute"]
"""Coarse-grained action verbs. The W3 ``authorize_resource`` API
returns the allow/deny answer for a (resource, action) pair."""


@dataclass(frozen=True, slots=True)
class ResourceRef:
    """Canonical pointer to a resource.

    The triple ``(provider_id, resource_type, resource_id)`` uniquely
    identifies a resource within a tenant. ``external_id`` is what
    the upstream system (PMS / GitHub / Notion / …) calls the same
    object — kept on the ref for round-trip but never used for
    identity comparisons inside the platform.
    """

    provider_id: str
    resource_type: str
    resource_id: str
    external_id: str = ""

    def __str__(self) -> str:
        return f"{self.provider_id}/{self.resource_type}/{self.resource_id}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "external_id": self.external_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ResourceRef:
        missing = [
            key
            for key in ("provider_id", "resource_type", "resource_id")
            if not str(data.get(key) or "").strip()
        ]
        if missing:
            raise ValueError(
                f"ResourceRef is missing {missing}; required fields are "
                "['provider_id', 'resource_type', 'resource_id'] "
                "(optional: external_id)"
            )
        return cls(
            provider_id=str(data["provider_id"]),
            resource_type=str(data["resource_type"]),
            resource_id=str(data["resource_id"]),
            external_id=str(data.get("external_id", "")),
        )


@dataclass(frozen=True, slots=True)
class TenantBoundary:
    """Resource scope. Mirrors ``TenantScope`` but lives on the
    resource so provider records carry their own scope rather than
    relying on the calling ``ExecutionContext``.
    """

    tenant_id: str
    workspace_id: str = ""
    project_id: str = ""

    def matches(self, tenant_id: str, workspace_id: str = "") -> bool:
        if self.tenant_id and self.tenant_id != tenant_id:
            return False
        if self.workspace_id and workspace_id and self.workspace_id != workspace_id:
            return False
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "workspace_id": self.workspace_id,
            "project_id": self.project_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> TenantBoundary:
        if not data:
            return cls(tenant_id="")
        return cls(
            tenant_id=str(data.get("tenant_id", "")),
            workspace_id=str(data.get("workspace_id", "")),
            project_id=str(data.get("project_id", "")),
        )


@dataclass(frozen=True, slots=True)
class ResourceRelation:
    """A typed edge between two resources.

    The ``relation`` value is provider-defined (e.g. ``"parent"``,
    ``"linked_run"``, ``"created_from_session"``); ResourceGraph
    leaves it opaque and just exposes ``list_related`` as a
    relation-name lookup.
    """

    relation: str
    target: ResourceRef

    def to_dict(self) -> dict[str, Any]:
        return {
            "relation": self.relation,
            "target": self.target.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ResourceRelation:
        return cls(
            relation=str(data["relation"]),
            target=ResourceRef.from_dict(data["target"]),
        )


@dataclass(frozen=True, slots=True)
class Resource:
    """Normalised resource record.

    The data Reception/Planner are allowed to see in prompts. Anything
    sensitive (full document body, PII payloads, raw credentials)
    stays inside the provider; this shape is a *projection* surfaced
    on the prompt boundary.
    """

    ref: ResourceRef
    display_name: str
    boundary: TenantBoundary
    owner: str = ""
    """``identity.principal_id`` of the resource's owner if known."""
    assignee: str = ""
    """``identity.principal_id`` of the current assignee if known."""
    summary: str = ""
    """One-line human summary safe for prompt inclusion."""
    permission_hints: tuple[PermissionAction, ...] = ()
    """Best-effort list of actions the average reader can perform.
    Authorization is the **authoritative** source — these hints are
    only used by the discovery layer to skip clearly-impossible
    candidates."""
    relations: tuple[ResourceRelation, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    """Provider-specific extension. Keep secrets out — Reception
    prompts surface this dict via the safe-projection rules."""

    def __post_init__(self) -> None:
        if not isinstance(self.permission_hints, tuple):
            object.__setattr__(
                self, "permission_hints", tuple(self.permission_hints)
            )
        if not isinstance(self.relations, tuple):
            object.__setattr__(self, "relations", tuple(self.relations))

    @property
    def resource_id(self) -> str:
        return self.ref.resource_id

    @property
    def resource_type(self) -> str:
        return self.ref.resource_type

    @property
    def provider_id(self) -> str:
        return self.ref.provider_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "ref": self.ref.to_dict(),
            "display_name": self.display_name,
            "boundary": self.boundary.to_dict(),
            "owner": self.owner,
            "assignee": self.assignee,
            "summary": self.summary,
            "permission_hints": list(self.permission_hints),
            "relations": [r.to_dict() for r in self.relations],
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Resource:
        return cls(
            ref=ResourceRef.from_dict(data["ref"]),
            display_name=str(data.get("display_name", "")),
            boundary=TenantBoundary.from_dict(data.get("boundary")),
            owner=str(data.get("owner", "")),
            assignee=str(data.get("assignee", "")),
            summary=str(data.get("summary", "")),
            permission_hints=tuple(data.get("permission_hints") or ()),
            relations=tuple(
                ResourceRelation.from_dict(r) for r in (data.get("relations") or ())
            ),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True, slots=True)
class AuthorizationDecision:
    """Outcome of ``ResourceProvider.authorize_resource``."""

    allowed: bool
    needs_confirmation: bool = False
    """When True the caller may proceed only after explicit user
    confirmation (preview / gate). Distinct from ``allowed=False``,
    which is a hard deny."""
    reason: str = ""
    """Free-form copy a reception prompt can show: "you do not have
    write access to this PMS issue", "this is a cross-project resource
    and requires write authorization", etc."""

    def __bool__(self) -> bool:
        return self.allowed and not self.needs_confirmation
