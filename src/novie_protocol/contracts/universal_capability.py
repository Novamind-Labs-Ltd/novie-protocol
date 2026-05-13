"""Universal Capability + Provider contracts (W1 — UNIVERSAL_CAPABILITY).

Frozen schema per ``docs/UNIVERSAL_CAPABILITY_CONTRACT.md``. Every
capability source — internal platform function, external A2A agent,
MCP tool, OpenAPI adapter, Temporal workflow, LLM proxy — projects
onto these two dataclasses before Reception or Planner can discover
or invoke it.

The literals reused from ``capability.py`` (CapabilityKind /
CapabilityRisk / CapabilitySideEffect / etc.) are kept verbatim so
the migration is additive: existing ``AgentCapabilityManifestEntry``
callers keep working, and the projection helper in
``novie_platform.runtime.agent_manifest.projection`` is the bridge.
"""
# ruff: noqa: RUF001, RUF002, RUF003
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from .capability import (
    CapabilityCallerMode,
    CapabilityCallerType,
    CapabilityCostTier,
    CapabilityDurationClass,
    CapabilityExecutionLane,
    CapabilityGovernance,
    CapabilityKind,
    CapabilityQualityTier,
    CapabilityRisk,
    CapabilityRiskClass,
    CapabilitySideEffect,
    CapabilityStatus,
)

# ── Provider transport ────────────────────────────────────────────────────────

ProviderType = Literal[
    "internal",
    "a2a_agent",
    "mcp",
    "openapi",
    "temporal_workflow",
    "llm_proxy",
]
"""Source category of a capability provider.

Renamed from the legacy ``CapabilityProvider`` literal in
``capability.py`` (``"agent"`` → ``"a2a_agent"`` for clarity); a
one-release alias is preserved at the bottom of this module so old
imports keep working.
"""

PROVIDER_TYPES: tuple[str, ...] = (
    "internal",
    "a2a_agent",
    "mcp",
    "openapi",
    "temporal_workflow",
    "llm_proxy",
)

HealthCheckKind = Literal["in_process", "http_get", "tcp_socket", "none"]
"""How the platform validates a provider is alive + ready."""


@dataclass(frozen=True, slots=True)
class HealthCheck:
    kind: HealthCheckKind = "none"
    path: str = ""
    url: str = ""
    port: int = 0

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"kind": self.kind}
        if self.path:
            out["path"] = self.path
        if self.url:
            out["url"] = self.url
        if self.port:
            out["port"] = self.port
        return out

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> HealthCheck:
        if not data:
            return cls()
        return cls(
            kind=data.get("kind", "none"),
            path=str(data.get("path", "")),
            url=str(data.get("url", "")),
            port=int(data.get("port", 0)),
        )


@dataclass(frozen=True, slots=True)
class TransportDescriptor:
    """Provider-specific invocation descriptor.

    The schema varies by ``kind``; the W4 invocation middleware
    selects an adapter based on ``kind``. Fields irrelevant to the
    selected kind are simply empty.
    """

    kind: ProviderType
    # internal
    entry_point: str = ""
    # a2a_agent
    endpoint: str = ""
    protocol_mode: str = ""
    manifest_url: str = ""
    # mcp
    server_url: str = ""
    tool_name: str = ""
    transport_protocol: str = ""  # stdio | sse | http
    # openapi
    spec_url: str = ""
    operation_id: str = ""
    base_url: str = ""
    security_scheme: str = ""
    # temporal_workflow
    task_queue: str = ""
    workflow_type: str = ""
    namespace: str = ""
    # llm_proxy
    model: str = ""
    api_key_ref: str = ""
    # extension
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"kind": self.kind}
        for f_name in (
            "entry_point",
            "endpoint",
            "protocol_mode",
            "manifest_url",
            "server_url",
            "tool_name",
            "transport_protocol",
            "spec_url",
            "operation_id",
            "base_url",
            "security_scheme",
            "task_queue",
            "workflow_type",
            "namespace",
            "model",
            "api_key_ref",
        ):
            value = getattr(self, f_name)
            if value:
                out[f_name] = value
        if self.extra:
            out["extra"] = dict(self.extra)
        return out

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TransportDescriptor:
        return cls(
            kind=data["kind"],
            entry_point=str(data.get("entry_point", "")),
            endpoint=str(data.get("endpoint", "")),
            protocol_mode=str(data.get("protocol_mode", "")),
            manifest_url=str(data.get("manifest_url", "")),
            server_url=str(data.get("server_url", "")),
            tool_name=str(data.get("tool_name", "")),
            transport_protocol=str(data.get("transport_protocol", "")),
            spec_url=str(data.get("spec_url", "")),
            operation_id=str(data.get("operation_id", "")),
            base_url=str(data.get("base_url", "")),
            security_scheme=str(data.get("security_scheme", "")),
            task_queue=str(data.get("task_queue", "")),
            workflow_type=str(data.get("workflow_type", "")),
            namespace=str(data.get("namespace", "")),
            model=str(data.get("model", "")),
            api_key_ref=str(data.get("api_key_ref", "")),
            extra=dict(data.get("extra") or {}),
        )


DryRunSupport = Literal[
    "none",
    "preview_only",
    "preview_with_diff",
    "preview_with_side_effect_simulation",
]
"""How thorough the capability's dry-run / preview path is.

Used by the W4 middleware to decide whether to short-circuit on
preview mode and what shape to return.
"""

ConfirmationDefault = Literal["auto", "required", "gated"]
"""Default UX shape for confirmation:

- ``auto`` — execute immediately (read-only by default)
- ``required`` — require an explicit user confirm step
- ``gated`` — require a HITL gate (governance-policy driven)
"""


@dataclass(frozen=True, slots=True)
class RoutingHints:
    when_to_use: str = ""
    when_not_to_use: str = ""
    natural_language_aliases: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.natural_language_aliases, tuple):
            object.__setattr__(
                self,
                "natural_language_aliases",
                tuple(self.natural_language_aliases),
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "when_to_use": self.when_to_use,
            "when_not_to_use": self.when_not_to_use,
            "natural_language_aliases": list(self.natural_language_aliases),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> RoutingHints:
        if not data:
            return cls()
        return cls(
            when_to_use=str(data.get("when_to_use", "")),
            when_not_to_use=str(data.get("when_not_to_use", "")),
            natural_language_aliases=tuple(
                data.get("natural_language_aliases") or ()
            ),
        )


# ── Capability + Provider ─────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class CapabilityContract:
    """Frozen capability shape per docs/UNIVERSAL_CAPABILITY_CONTRACT.md."""

    capability_id: str
    provider_id: str
    kind: CapabilityKind
    risk_level: CapabilityRisk
    side_effect: CapabilitySideEffect
    status: CapabilityStatus
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]

    duration_class: CapabilityDurationClass = "<1min"
    cost_tier: CapabilityCostTier = "standard"
    quality_tier: CapabilityQualityTier = "standard"
    execution_lane: CapabilityExecutionLane = "direct"
    risk_class: CapabilityRiskClass = "read_only"

    consumes_resources: tuple[str, ...] = ()
    produces_resources: tuple[str, ...] = ()

    dry_run_support: DryRunSupport = "none"
    confirmation_default: ConfirmationDefault = "auto"
    gate_policy: tuple[str, ...] = ()

    auth_scope: tuple[str, ...] = ()
    credential_refs: tuple[str, ...] = ()
    caller_types: tuple[CapabilityCallerType, ...] = ()
    caller_modes: tuple[CapabilityCallerMode, ...] = ()

    routing_hints: RoutingHints = field(default_factory=RoutingHints)
    examples: tuple[dict[str, Any], ...] = ()

    governance: CapabilityGovernance = field(default_factory=CapabilityGovernance)
    metadata: dict[str, Any] = field(default_factory=dict)

    transport: TransportDescriptor | None = None
    """Optional capability-level transport override.

    Most capabilities inherit their provider's transport; only set
    this when a single capability needs a different endpoint or tool
    name (e.g. one MCP server exposing two tools at different URLs).
    """

    def __post_init__(self) -> None:
        for name in (
            "consumes_resources",
            "produces_resources",
            "gate_policy",
            "auth_scope",
            "credential_refs",
            "caller_types",
            "caller_modes",
            "examples",
        ):
            value = getattr(self, name)
            if not isinstance(value, tuple):
                object.__setattr__(self, name, tuple(value))

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "capability_id": self.capability_id,
            "provider_id": self.provider_id,
            "kind": self.kind,
            "risk_level": self.risk_level,
            "side_effect": self.side_effect,
            "status": self.status,
            "duration_class": self.duration_class,
            "cost_tier": self.cost_tier,
            "quality_tier": self.quality_tier,
            "execution_lane": self.execution_lane,
            "risk_class": self.risk_class,
            "input_schema": dict(self.input_schema),
            "output_schema": dict(self.output_schema),
            "consumes_resources": list(self.consumes_resources),
            "produces_resources": list(self.produces_resources),
            "dry_run_support": self.dry_run_support,
            "confirmation_default": self.confirmation_default,
            "gate_policy": list(self.gate_policy),
            "auth_scope": list(self.auth_scope),
            "credential_refs": list(self.credential_refs),
            "caller_types": list(self.caller_types),
            "caller_modes": list(self.caller_modes),
            "routing_hints": self.routing_hints.to_dict(),
            "examples": [dict(item) for item in self.examples],
            "governance": self.governance.to_dict(),
            "metadata": dict(self.metadata),
        }
        if self.transport is not None:
            out["transport"] = self.transport.to_dict()
        return out

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CapabilityContract:
        transport_raw = data.get("transport")
        return cls(
            capability_id=str(data["capability_id"]),
            provider_id=str(data["provider_id"]),
            kind=data["kind"],
            risk_level=data["risk_level"],
            side_effect=data["side_effect"],
            status=data.get("status", "stable"),
            input_schema=dict(data.get("input_schema") or {}),
            output_schema=dict(data.get("output_schema") or {}),
            duration_class=data.get("duration_class", "<1min"),
            cost_tier=data.get("cost_tier", "standard"),
            quality_tier=data.get("quality_tier", "standard"),
            execution_lane=data.get("execution_lane", "direct"),
            risk_class=data.get("risk_class", "read_only"),
            consumes_resources=tuple(data.get("consumes_resources") or ()),
            produces_resources=tuple(data.get("produces_resources") or ()),
            dry_run_support=data.get("dry_run_support", "none"),
            confirmation_default=data.get("confirmation_default", "auto"),
            gate_policy=tuple(data.get("gate_policy") or ()),
            auth_scope=tuple(data.get("auth_scope") or ()),
            credential_refs=tuple(data.get("credential_refs") or ()),
            caller_types=tuple(data.get("caller_types") or ()),
            caller_modes=tuple(data.get("caller_modes") or ()),
            routing_hints=RoutingHints.from_dict(data.get("routing_hints")),
            examples=tuple(dict(item) for item in (data.get("examples") or ())),
            governance=CapabilityGovernance.from_dict(data.get("governance")),
            metadata=dict(data.get("metadata") or {}),
            transport=(
                TransportDescriptor.from_dict(transport_raw)
                if transport_raw
                else None
            ),
        )


@dataclass(frozen=True, slots=True)
class CapabilityProvider:
    """One provider that publishes a set of CapabilityContract entries."""

    provider_id: str
    provider_type: ProviderType
    display_name: str
    version: str
    conformance_version: str = "universal-capability-v1"
    health: HealthCheck = field(default_factory=HealthCheck)
    transport: TransportDescriptor | None = None
    resource_types: tuple[str, ...] = ()
    capabilities: tuple[CapabilityContract, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.resource_types, tuple):
            object.__setattr__(self, "resource_types", tuple(self.resource_types))
        if not isinstance(self.capabilities, tuple):
            object.__setattr__(self, "capabilities", tuple(self.capabilities))

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "provider_id": self.provider_id,
            "provider_type": self.provider_type,
            "display_name": self.display_name,
            "version": self.version,
            "conformance_version": self.conformance_version,
            "health": self.health.to_dict(),
            "resource_types": list(self.resource_types),
            "capabilities": [c.to_dict() for c in self.capabilities],
            "metadata": dict(self.metadata),
        }
        if self.transport is not None:
            out["transport"] = self.transport.to_dict()
        return out

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CapabilityProvider:
        transport_raw = data.get("transport")
        return cls(
            provider_id=str(data["provider_id"]),
            provider_type=data["provider_type"],
            display_name=str(data.get("display_name", "")),
            version=str(data.get("version", "")),
            conformance_version=str(
                data.get("conformance_version", "universal-capability-v1")
            ),
            health=HealthCheck.from_dict(data.get("health")),
            transport=(
                TransportDescriptor.from_dict(transport_raw)
                if transport_raw
                else None
            ),
            resource_types=tuple(data.get("resource_types") or ()),
            capabilities=tuple(
                CapabilityContract.from_dict(c)
                for c in (data.get("capabilities") or ())
            ),
            metadata=dict(data.get("metadata") or {}),
        )


# ── Validation ────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ValidationError:
    """JSON Pointer + message — author-facing diagnostic.

    Per the W1 contract: every validation failure carries a
    pointer so authors can find the offending field, plus a
    human-readable reason.
    """

    pointer: str
    message: str

    def __str__(self) -> str:
        return f"{self.pointer}: {self.message}"


_KNOWN_KINDS: frozenset[str] = frozenset(
    ("query", "command", "workflow", "stream", "task")
)
_KNOWN_RISK: frozenset[str] = frozenset(("read", "write", "dangerous"))
_KNOWN_DRY_RUN: frozenset[str] = frozenset(
    (
        "none",
        "preview_only",
        "preview_with_diff",
        "preview_with_side_effect_simulation",
    )
)
_KNOWN_CONFIRMATION: frozenset[str] = frozenset(("auto", "required", "gated"))


def validate_capability_contract(
    contract: CapabilityContract, pointer: str = ""
) -> list[ValidationError]:
    errors: list[ValidationError] = []
    if not contract.capability_id:
        errors.append(ValidationError(f"{pointer}/capability_id", "must be non-empty"))
    if not contract.provider_id:
        errors.append(ValidationError(f"{pointer}/provider_id", "must be non-empty"))
    if contract.kind not in _KNOWN_KINDS:
        errors.append(
            ValidationError(f"{pointer}/kind", f"unknown kind {contract.kind!r}")
        )
    if contract.risk_level not in _KNOWN_RISK:
        errors.append(
            ValidationError(
                f"{pointer}/risk_level",
                f"unknown risk_level {contract.risk_level!r}",
            )
        )
    if contract.dry_run_support not in _KNOWN_DRY_RUN:
        errors.append(
            ValidationError(
                f"{pointer}/dry_run_support",
                f"unknown dry_run_support {contract.dry_run_support!r}",
            )
        )
    if contract.confirmation_default not in _KNOWN_CONFIRMATION:
        errors.append(
            ValidationError(
                f"{pointer}/confirmation_default",
                f"unknown confirmation_default {contract.confirmation_default!r}",
            )
        )
    if not isinstance(contract.input_schema, dict):
        errors.append(
            ValidationError(
                f"{pointer}/input_schema", "must be a JSON Schema dict"
            )
        )
    if not isinstance(contract.output_schema, dict):
        errors.append(
            ValidationError(
                f"{pointer}/output_schema", "must be a JSON Schema dict"
            )
        )
    # Write capabilities cannot use ``auto`` confirmation if they have no
    # dry-run path — operators would have no way to preview before commit.
    if (
        contract.risk_level in ("write", "dangerous")
        and contract.dry_run_support == "none"
        and contract.confirmation_default == "auto"
    ):
        errors.append(
            ValidationError(
                f"{pointer}/confirmation_default",
                "write/dangerous capability with dry_run_support='none' "
                "cannot use confirmation_default='auto' — must require "
                "explicit confirm or gate",
            )
        )
    return errors


def validate_capability_provider(
    provider: CapabilityProvider,
) -> list[ValidationError]:
    errors: list[ValidationError] = []
    if not provider.provider_id:
        errors.append(ValidationError("/provider_id", "must be non-empty"))
    if provider.provider_type not in PROVIDER_TYPES:
        errors.append(
            ValidationError(
                "/provider_type",
                f"unknown provider_type {provider.provider_type!r}",
            )
        )
    if not provider.version:
        errors.append(ValidationError("/version", "must be non-empty"))
    if (
        provider.transport is not None
        and provider.transport.kind != provider.provider_type
    ):
        errors.append(
            ValidationError(
                "/transport/kind",
                f"transport.kind={provider.transport.kind!r} does not "
                f"match provider_type={provider.provider_type!r}",
            )
        )
    seen: set[str] = set()
    for index, capability in enumerate(provider.capabilities):
        cap_pointer = f"/capabilities/{index}"
        if (
            capability.provider_id
            and capability.provider_id != provider.provider_id
        ):
            errors.append(
                ValidationError(
                    f"{cap_pointer}/provider_id",
                    f"must match provider.provider_id={provider.provider_id!r}, "
                    f"got {capability.provider_id!r}",
                )
            )
        if capability.capability_id in seen:
            errors.append(
                ValidationError(
                    f"{cap_pointer}/capability_id",
                    f"duplicate capability_id within provider: "
                    f"{capability.capability_id!r}",
                )
            )
        seen.add(capability.capability_id)
        errors.extend(validate_capability_contract(capability, cap_pointer))
    return errors


# ── Compatibility alias ───────────────────────────────────────────────────────

# The legacy ``CapabilityProvider`` LITERAL in capability.py overlaps with
# our new dataclass NAME. Importers that wanted the legacy literal shape
# should use ``LegacyProviderTypeLiteral`` for one release cycle, then
# migrate to the new ``ProviderType`` literal. Keep the alias minimal —
# just point at the renamed literal so source compatibility holds.
LegacyProviderTypeLiteral = Literal[
    "internal",
    "mcp",
    "openapi",
    "agent",
    "temporal",
    "llm_provider",
]
"""Deprecated — see ``ProviderType`` for the new shape.

Maps:
- ``"agent"``         → ``"a2a_agent"``
- ``"temporal"``      → ``"temporal_workflow"``
- ``"llm_provider"``  → ``"llm_proxy"``
"""

LEGACY_PROVIDER_TYPE_REWRITE: dict[str, ProviderType] = {
    "internal": "internal",
    "mcp": "mcp",
    "openapi": "openapi",
    "agent": "a2a_agent",
    "temporal": "temporal_workflow",
    "llm_provider": "llm_proxy",
}
