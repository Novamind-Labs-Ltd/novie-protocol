"""Platform capability layer contracts.

These dataclasses are the Phase 0 wire contract for the future thick capability
gateway.  They intentionally live in ``novie_protocol`` before any runtime
implementation so every caller shares the same schema, error codes, and response
shape from the start.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from .gates import CapabilityGateDeclaration

CapabilityStatus = Literal["alpha", "beta", "stable", "deprecated", "removed"]
CapabilityKind = Literal[
    "tool",
    "agent_action",
    "workflow",
    "llm",
    "memory",
    "artifact",
    "integration",
    "project",
    "platform_native",
]
CapabilityProvider = Literal["internal", "mcp", "openapi", "agent", "temporal", "llm_provider"]
CapabilityRisk = Literal["read", "write", "dangerous"]
CapabilitySideEffect = Literal["none", "session", "tenant", "external", "irreversible"]
CapabilityExecKind = Literal["sync", "async", "stream", "workflow_handle"]
CapabilityDurationClass = Literal["<1s", "<1min", "<1h", ">1h"]
CapabilityCostTier = Literal["free", "cheap", "standard", "expensive", "critical"]
CapabilityQualityTier = Literal["low", "standard", "high"]
CapabilityCallerType = Literal[
    "reception",
    "planner",
    "mcp",
    "external_agent",
    "executor",
    "agent",
    # External sync workers (Member/PMS fact projection). HTTP invoke uses caller_type.
    "facts_projection",
]
CapabilityCallerMode = Literal["interactive", "preview", "execute", "delegated"]
CapabilityInvokeMode = Literal["execute", "dry_run", "plan_eval"]
CapabilityInvokeStatus = Literal["ok", "needs_confirmation", "denied", "error"]
CapabilitySchemaCompat = Literal["compatible", "breaking", "unknown"]
SnapshotPatchTriggerSource = Literal[
    "provider_version_bump",
    "quota_refill",
    "manifest_patch_update",
    "equivalent_provider_swap",
    "delivery_blocked",
    "manual",
    "registry_drift",
]
SnapshotPatchDecision = Literal["auto_patch", "human_review", "replan"]
CapabilityMiddlewareStep = Literal[
    "auth",
    "policy",
    "binding",
    "quota",
    "context_inject",
    "invoke",
    "usage_record",
    "audit",
    "response",
]
CapabilityMiddlewareStatus = Literal["pending", "ok", "skipped", "denied", "error"]
CapabilityManifestKind = Literal["capability", "provider"]
CapabilityInputSource = Literal[
    "user_input",
    "upstream_capability",
    "runtime_context",
    "platform_projection",
]

DEFAULT_AUTO_SNAPSHOT_PATCH_CAP = 2


def has_snapshot_patch_budget(
    previous_attempts: int,
    *,
    cap: int = DEFAULT_AUTO_SNAPSHOT_PATCH_CAP,
) -> bool:
    """Whether another automatic snapshot patch may be attempted."""
    return max(0, previous_attempts) < max(0, cap)

# ── Capability governance schema (W1 of capability-contract orchestration) ──
#
# These vocabularies extend the agent-authored manifest entry with stable
# metadata the platform compiler can read instead of stage-specific
# planner if/else logic. The values intentionally describe *constraints
# the capability declares about itself* rather than how a particular
# stage should consume it.

CapabilityExecutionLane = Literal["direct", "board_controlled"]
"""How the capability is allowed to enter execution.

- ``direct``: the platform may compile this capability into an executable
  plan directly off LLM intent. Most read-only / analytical capabilities
  use this lane.
- ``board_controlled``: execution is gated on tracker / board state. The
  capability cannot run from a planner draft alone — a tracker issue must
  exist and a human must transition it to a runnable state. Used today by
  ``cortex.execute_task_bundle``; replaces the bespoke "if cortex then
  force task_splitter -> PMS" planner rule.
"""

CapabilityRiskClass = Literal["read_only", "repo_mutation", "external_write"]
"""Coarse semantic risk taxonomy used by the dependency compiler.

Distinct from the existing ``CapabilityRisk`` (``read``/``write``/
``dangerous``) which describes the *invocation* surface. ``risk_class``
describes the *kind* of side effect the capability ultimately causes,
which is what governance and auditing care about.

- ``read_only``: produces artifacts only; no external mutation.
- ``repo_mutation``: edits a project repository (commits, PRs, etc.).
- ``external_write``: mutates a non-repo external system (tracker write,
  email, deployment, etc.).
"""

CapabilityGovernanceRiskTier = Literal["low", "medium", "high", "dangerous"]


@dataclass(frozen=True, slots=True)
class CapabilityGovernance:
    """Governance flags declared on a capability manifest entry.

    Each flag captures a constraint the platform compiler / runtime must
    enforce before the capability may execute. Flags compose: a
    capability with multiple governance requirements must satisfy all of
    them.

    Today's hardcoded planner rules ("repo_mutation must route through
    sprint_planning", "cortex must be board-controlled") are special
    cases of these declarations. The compiler that lands in W2 reads
    these flags instead of agent-id checks.
    """

    requires_plan_review: bool = False
    """The compiled plan must enter ``plan_review`` before any step
    executes. Used for high-impact authoring flows."""

    requires_tracker_issue: bool = False
    """Execution may only begin from a runnable tracker issue (a
    materialised PMS ticket transitioned to Todo). The compiler inserts
    the ``work_item_draft_graph -> tracker_ingestion -> tracker_issue`` chain
    upstream when needed; runtime denies execution if no issue is bound."""

    requires_human_gate: bool = False
    """A human gate must be raised + decided before execution proceeds.
    Distinct from ``requires_plan_review``: this gates *runtime* not
    plan approval."""

    risk_tier: CapabilityGovernanceRiskTier = "low"
    mutates_external_state: bool = False
    produces_artifact: bool = False
    long_running: bool = False
    requires_workspace_mount: bool = False
    requires_durable_checkpoint: bool = False
    streams_intermediate_artifacts: bool = False
    self_managed_checkpoint: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "requires_plan_review": self.requires_plan_review,
            "requires_tracker_issue": self.requires_tracker_issue,
            "requires_human_gate": self.requires_human_gate,
            "risk_tier": self.risk_tier,
            "mutates_external_state": self.mutates_external_state,
            "produces_artifact": self.produces_artifact,
            "long_running": self.long_running,
            "requires_workspace_mount": self.requires_workspace_mount,
            "requires_durable_checkpoint": self.requires_durable_checkpoint,
            "streams_intermediate_artifacts": self.streams_intermediate_artifacts,
            "self_managed_checkpoint": self.self_managed_checkpoint,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> CapabilityGovernance:
        if not data:
            return cls()
        return cls(
            requires_plan_review=bool(data.get("requires_plan_review", False)),
            requires_tracker_issue=bool(data.get("requires_tracker_issue", False)),
            requires_human_gate=bool(data.get("requires_human_gate", False)),
            risk_tier=data.get("risk_tier", "low"),
            mutates_external_state=bool(data.get("mutates_external_state", False)),
            produces_artifact=bool(data.get("produces_artifact", False)),
            long_running=bool(data.get("long_running", False)),
            requires_workspace_mount=bool(data.get("requires_workspace_mount", False)),
            requires_durable_checkpoint=bool(data.get("requires_durable_checkpoint", False)),
            streams_intermediate_artifacts=bool(
                data.get("streams_intermediate_artifacts", False)
            ),
            self_managed_checkpoint=bool(data.get("self_managed_checkpoint", False)),
        )


CAPABILITY_MIDDLEWARE_CHAIN: tuple[CapabilityMiddlewareStep, ...] = (
    "auth",
    "policy",
    "binding",
    "quota",
    "context_inject",
    "invoke",
    "usage_record",
    "audit",
    "response",
)

CapabilityErrorCode = Literal[
    "denied_by_policy",
    "denied_by_binding",
    "quota_exceeded",
    "unavailable_transient",
    "unavailable_permanent",
    "invalid_args",
    "schema_violation",
    "upstream_timeout",
    "needs_confirmation",
    "needs_capability_dependency",
    "needs_runtime_context",
    "capability_not_found",
    "governance_boundary_unavailable",
    "internal_error",
]
CAPABILITY_ERROR_CODES: tuple[str, ...] = (
    "denied_by_policy",
    "denied_by_binding",
    "quota_exceeded",
    "unavailable_transient",
    "unavailable_permanent",
    "invalid_args",
    "schema_violation",
    "upstream_timeout",
    "needs_confirmation",
    "needs_capability_dependency",
    "needs_runtime_context",
    "capability_not_found",
    "governance_boundary_unavailable",
    "internal_error",
)


@dataclass(frozen=True, slots=True)
class ServedAction:
    resource_type: str
    verb: str
    aliases: tuple[str, ...] = ()
    description: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.aliases, tuple):
            object.__setattr__(self, "aliases", tuple(self.aliases))

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "resource_type": self.resource_type,
            "verb": self.verb,
            "aliases": list(self.aliases),
        }
        if self.description:
            out["description"] = self.description
        return out

    @classmethod
    def from_dict(cls, data: dict[str, Any] | str) -> ServedAction:
        if isinstance(data, str):
            resource_type, _, verb = data.partition(".")
            if not verb:
                verb = resource_type
                resource_type = ""
            return cls(resource_type=resource_type, verb=verb)
        aliases = data.get("aliases") or ()
        if isinstance(aliases, str):
            aliases = (aliases,)
        return cls(
            resource_type=str(data.get("resource_type") or ""),
            verb=str(data.get("verb") or ""),
            aliases=tuple(str(item) for item in aliases),
            description=str(data.get("description") or ""),
        )


@dataclass(frozen=True, slots=True)
class CapabilityInputContract:
    """Typed source declaration for one consumed artifact.

    ``consumes`` names the artifact dependency. ``input_contracts`` explains
    who is allowed to satisfy it, so the platform can validate routability
    without guessing from artifact names.
    """

    artifact: str
    source: CapabilityInputSource = "upstream_capability"
    provider: str = ""
    required: bool = True

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "artifact": self.artifact,
            "source": self.source,
            "required": self.required,
        }
        if self.provider:
            out["provider"] = self.provider
        return out

    @classmethod
    def from_dict(cls, data: dict[str, Any] | str) -> CapabilityInputContract:
        if isinstance(data, str):
            return cls(artifact=data)
        return cls(
            artifact=str(data.get("artifact") or ""),
            source=data.get("source", "upstream_capability"),
            provider=str(data.get("provider") or ""),
            required=bool(data.get("required", True)),
        )


@dataclass(frozen=True, slots=True)
class AgentCapabilityManifestEntry:
    """Structured capability declaration published by an agent manifest.

    This is the agent-authored boundary contract.  The platform may project it
    into a ``PlatformCapability`` catalog record after applying bindings,
    policy, observed reliability, and runtime metadata.
    """

    capability_id: str
    version: str
    display_name: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    risk: CapabilityRisk
    side_effect: CapabilitySideEffect
    exec_kind: CapabilityExecKind
    runtime_ref: str
    manifest_kind: CapabilityManifestKind = "capability"
    tags: tuple[str, ...] = ()
    natural_language_aliases: tuple[str, ...] = ()
    examples: tuple[dict[str, Any], ...] = ()
    idempotent: bool = False
    expected_duration_class: CapabilityDurationClass = "<1min"
    streamable: bool = False
    cancellation_supported: bool = False
    progress_events: bool = False
    dry_run_supported: bool = False
    requires_confirmation: bool = False
    requires: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()
    provides: tuple[str, ...] = ()
    consumes: tuple[str, ...] = ()
    input_contracts: tuple[CapabilityInputContract, ...] = ()
    caller_types: tuple[CapabilityCallerType, ...] = ()
    serves_actions: tuple[ServedAction, ...] = ()
    execution_lane: CapabilityExecutionLane = "direct"
    risk_class: CapabilityRiskClass = "read_only"
    governance: CapabilityGovernance = field(default_factory=CapabilityGovernance)
    side_effect_boundaries: tuple[str, ...] = ()
    gates: tuple[CapabilityGateDeclaration, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    canonical_id: str | None = None
    legacy_id: str | None = None

    def __post_init__(self) -> None:
        for name in (
            "tags",
            "natural_language_aliases",
            "examples",
            "requires",
            "conflicts",
            "provides",
            "consumes",
            "input_contracts",
            "caller_types",
            "serves_actions",
            "side_effect_boundaries",
            "gates",
        ):
            value = getattr(self, name)
            if not isinstance(value, tuple):
                object.__setattr__(self, name, tuple(value))
        object.__setattr__(
            self,
            "input_contracts",
            tuple(
                item
                if isinstance(item, CapabilityInputContract)
                else CapabilityInputContract.from_dict(item)
                for item in self.input_contracts
            ),
        )
        object.__setattr__(
            self,
            "serves_actions",
            tuple(
                item if isinstance(item, ServedAction) else ServedAction.from_dict(item)
                for item in self.serves_actions
            ),
        )
        object.__setattr__(
            self,
            "gates",
            tuple(
                item
                if isinstance(item, CapabilityGateDeclaration)
                else CapabilityGateDeclaration.from_dict(item)
                for item in self.gates
            ),
        )
        for gate in self.gates:
            if gate.timing == "pre_side_effect" and (
                not gate.boundary_id
                or gate.boundary_id not in self.side_effect_boundaries
            ):
                raise ValueError(
                    f"pre_side_effect gate {gate.gate_key!r} requires a "
                    "declared side_effect boundary"
                )
        if isinstance(self.canonical_id, str) and not self.canonical_id.strip():
            object.__setattr__(self, "canonical_id", None)
        if isinstance(self.legacy_id, str) and not self.legacy_id.strip():
            object.__setattr__(self, "legacy_id", None)

    def to_dict(self) -> dict[str, Any]:
        data = {
            "capability_id": self.capability_id,
            "version": self.version,
            "display_name": self.display_name,
            "description": self.description,
            "input_schema": dict(self.input_schema),
            "output_schema": dict(self.output_schema),
            "risk": self.risk,
            "side_effect": self.side_effect,
            "exec_kind": self.exec_kind,
            "runtime_ref": self.runtime_ref,
            "manifest_kind": self.manifest_kind,
            "tags": list(self.tags),
            "natural_language_aliases": list(self.natural_language_aliases),
            "examples": [dict(item) for item in self.examples],
            "idempotent": self.idempotent,
            "expected_duration_class": self.expected_duration_class,
            "streamable": self.streamable,
            "cancellation_supported": self.cancellation_supported,
            "progress_events": self.progress_events,
            "dry_run_supported": self.dry_run_supported,
            "requires_confirmation": self.requires_confirmation,
            "requires": list(self.requires),
            "conflicts": list(self.conflicts),
            "provides": list(self.provides),
            "consumes": list(self.consumes),
            "input_contracts": [item.to_dict() for item in self.input_contracts],
            "caller_types": list(self.caller_types),
            "serves_actions": [item.to_dict() for item in self.serves_actions],
            "execution_lane": self.execution_lane,
            "risk_class": self.risk_class,
            "governance": self.governance.to_dict(),
            "side_effect_boundaries": list(self.side_effect_boundaries),
            "gates": [item.to_dict() for item in self.gates],
            "metadata": dict(self.metadata),
        }
        if self.canonical_id:
            data["canonical_id"] = self.canonical_id
        if self.legacy_id:
            data["legacy_id"] = self.legacy_id
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentCapabilityManifestEntry:
        metadata = dict(data.get("metadata") or {})
        serves_actions_raw = data.get("serves_actions")
        if serves_actions_raw is None:
            serves_actions_raw = metadata.get("serves_actions") or ()
        return cls(
            capability_id=str(data["capability_id"]),
            version=str(data["version"]),
            display_name=str(data["display_name"]),
            description=str(data.get("description") or ""),
            input_schema=dict(data.get("input_schema") or {}),
            output_schema=dict(data.get("output_schema") or {}),
            risk=data["risk"],
            side_effect=data["side_effect"],
            exec_kind=data["exec_kind"],
            runtime_ref=str(data.get("runtime_ref") or ""),
            manifest_kind=_manifest_kind_from_dict(data),
            tags=tuple(data.get("tags") or ()),
            natural_language_aliases=tuple(data.get("natural_language_aliases") or ()),
            examples=tuple(dict(item) for item in data.get("examples") or ()),
            idempotent=bool(data.get("idempotent", False)),
            expected_duration_class=data.get("expected_duration_class", "<1min"),
            streamable=bool(data.get("streamable", False)),
            cancellation_supported=bool(data.get("cancellation_supported", False)),
            progress_events=bool(data.get("progress_events", False)),
            dry_run_supported=bool(data.get("dry_run_supported", False)),
            requires_confirmation=bool(data.get("requires_confirmation", False)),
            requires=tuple(data.get("requires") or ()),
            conflicts=tuple(data.get("conflicts") or ()),
            provides=tuple(data.get("provides") or ()),
            consumes=tuple(data.get("consumes") or ()),
            input_contracts=tuple(
                CapabilityInputContract.from_dict(item)
                for item in (data.get("input_contracts") or ())
            ),
            caller_types=tuple(data.get("caller_types") or ()),
            serves_actions=tuple(
                ServedAction.from_dict(item)
                for item in (serves_actions_raw or ())
            ),
            execution_lane=data.get("execution_lane", "direct"),
            risk_class=data.get("risk_class", "read_only"),
            governance=CapabilityGovernance.from_dict(data.get("governance")),
            side_effect_boundaries=tuple(
                str(item) for item in (data.get("side_effect_boundaries") or ())
            ),
            gates=tuple(
                CapabilityGateDeclaration.from_dict(item)
                for item in (data.get("gates") or ())
            ),
            metadata=metadata,
            canonical_id=(
                str(data.get("canonical_id"))
                if data.get("canonical_id") not in (None, "")
                else None
            ),
            legacy_id=(
                str(data.get("legacy_id"))
                if data.get("legacy_id") not in (None, "")
                else None
            ),
        )


def _manifest_kind_from_dict(data: dict[str, Any]) -> CapabilityManifestKind:
    value = data.get("manifest_kind")
    if value is None and data.get("kind") in ("capability", "provider"):
        value = data.get("kind")
    return value or "capability"


@dataclass(frozen=True, slots=True)
class CapabilityMiddlewareRecord:
    """One immutable record emitted by a thick gateway middleware step."""

    step: CapabilityMiddlewareStep
    status: CapabilityMiddlewareStatus
    error_code: CapabilityErrorCode | None = None
    explanation: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    latency_ms: int | None = None
    side_effect_refs: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.side_effect_refs, tuple):
            object.__setattr__(self, "side_effect_refs", tuple(self.side_effect_refs))

    def to_dict(self) -> dict[str, Any]:
        return {
            "step": self.step,
            "status": self.status,
            "error_code": self.error_code,
            "explanation": self.explanation,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "latency_ms": self.latency_ms,
            "side_effect_refs": list(self.side_effect_refs),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CapabilityMiddlewareRecord:
        return cls(
            step=data["step"],
            status=data["status"],
            error_code=data.get("error_code"),
            explanation=data.get("explanation"),
            started_at=data.get("started_at"),
            finished_at=data.get("finished_at"),
            latency_ms=data.get("latency_ms"),
            side_effect_refs=tuple(data.get("side_effect_refs") or ()),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True, slots=True)
class CapabilityCatalogFilter:
    """Structured filters for catalog list and search APIs."""

    enabled_for: tuple[CapabilityCallerType, ...] = ()
    kinds: tuple[CapabilityKind, ...] = ()
    providers: tuple[CapabilityProvider, ...] = ()
    risk: tuple[CapabilityRisk, ...] = ()
    tags: tuple[str, ...] = ()
    requires_binding: bool | None = None
    supports_dry_run: bool | None = None
    streamable: bool | None = None
    project_id: str | None = None
    workspace_id: str | None = None

    def __post_init__(self) -> None:
        for name in ("enabled_for", "kinds", "providers", "risk", "tags"):
            value = getattr(self, name)
            if not isinstance(value, tuple):
                object.__setattr__(self, name, tuple(value))

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled_for": list(self.enabled_for),
            "kinds": list(self.kinds),
            "providers": list(self.providers),
            "risk": list(self.risk),
            "tags": list(self.tags),
            "requires_binding": self.requires_binding,
            "supports_dry_run": self.supports_dry_run,
            "streamable": self.streamable,
            "project_id": self.project_id,
            "workspace_id": self.workspace_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> CapabilityCatalogFilter:
        if not data:
            return cls()
        return cls(
            enabled_for=tuple(data.get("enabled_for") or ()),
            kinds=tuple(data.get("kinds") or ()),
            providers=tuple(data.get("providers") or ()),
            risk=tuple(data.get("risk") or ()),
            tags=tuple(data.get("tags") or ()),
            requires_binding=data.get("requires_binding"),
            supports_dry_run=data.get("supports_dry_run"),
            streamable=data.get("streamable"),
            project_id=data.get("project_id"),
            workspace_id=data.get("workspace_id"),
        )


@dataclass(frozen=True, slots=True)
class CapabilitySearchRequest:
    """Request body for ``POST /capabilities/search``."""

    query: str
    caller: CallerFrame
    filters: CapabilityCatalogFilter = field(default_factory=CapabilityCatalogFilter)
    limit: int = 20
    include_examples: bool = False
    include_deprecated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "caller": self.caller.to_dict(),
            "filters": self.filters.to_dict(),
            "limit": self.limit,
            "include_examples": self.include_examples,
            "include_deprecated": self.include_deprecated,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CapabilitySearchRequest:
        return cls(
            query=str(data.get("query") or ""),
            caller=CallerFrame.from_dict(dict(data["caller"])),
            filters=CapabilityCatalogFilter.from_dict(data.get("filters")),
            limit=int(data.get("limit", 20)),
            include_examples=bool(data.get("include_examples", False)),
            include_deprecated=bool(data.get("include_deprecated", False)),
        )


@dataclass(frozen=True, slots=True)
class CapabilitySearchMatch:
    """One scored catalog match for LLM or lexical capability search."""

    capability: PlatformCapability
    score: float
    matched_aliases: tuple[str, ...] = ()
    rationale: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.matched_aliases, tuple):
            object.__setattr__(self, "matched_aliases", tuple(self.matched_aliases))

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability": self.capability.to_dict(),
            "score": self.score,
            "matched_aliases": list(self.matched_aliases),
            "rationale": self.rationale,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CapabilitySearchMatch:
        return cls(
            capability=PlatformCapability.from_dict(dict(data["capability"])),
            score=float(data.get("score", 0.0)),
            matched_aliases=tuple(data.get("matched_aliases") or ()),
            rationale=data.get("rationale"),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True, slots=True)
class CapabilitySearchResponse:
    """Response body for capability search."""

    query: str
    matches: tuple[CapabilitySearchMatch, ...]
    ambiguous: bool = False
    classifier_metrics: dict[str, float] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.matches, tuple):
            object.__setattr__(self, "matches", tuple(self.matches))

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "matches": [match.to_dict() for match in self.matches],
            "ambiguous": self.ambiguous,
            "classifier_metrics": dict(self.classifier_metrics),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CapabilitySearchResponse:
        return cls(
            query=str(data.get("query") or ""),
            matches=tuple(
                CapabilitySearchMatch.from_dict(dict(item))
                for item in data.get("matches", ())
            ),
            ambiguous=bool(data.get("ambiguous", False)),
            classifier_metrics={
                str(key): float(value)
                for key, value in dict(data.get("classifier_metrics") or {}).items()
            },
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True, slots=True)
class CapabilityCatalogSnapshot:
    """A tenant/workspace-scoped catalog snapshot returned by ``GET /capabilities``."""

    catalog_version: str
    generated_at: str
    capabilities: tuple[PlatformCapability, ...]
    filters: CapabilityCatalogFilter = field(default_factory=CapabilityCatalogFilter)
    total: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.capabilities, tuple):
            object.__setattr__(self, "capabilities", tuple(self.capabilities))
        if self.total is None:
            object.__setattr__(self, "total", len(self.capabilities))

    def to_dict(self) -> dict[str, Any]:
        return {
            "catalog_version": self.catalog_version,
            "generated_at": self.generated_at,
            "capabilities": [capability.to_dict() for capability in self.capabilities],
            "filters": self.filters.to_dict(),
            "total": self.total,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CapabilityCatalogSnapshot:
        return cls(
            catalog_version=str(data["catalog_version"]),
            generated_at=str(data["generated_at"]),
            capabilities=tuple(
                PlatformCapability.from_dict(dict(item))
                for item in data.get("capabilities", ())
            ),
            filters=CapabilityCatalogFilter.from_dict(data.get("filters")),
            total=data.get("total"),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True, slots=True)
class CapabilityInvocationTrace:
    """Gateway trace for one capability invocation.

    Runtime implementations must keep ``middleware_chain`` equal to
    ``CAPABILITY_MIDDLEWARE_CHAIN`` unless the protocol version is changed.
    """

    trace_id: str
    capability_id: str
    middleware_chain: tuple[CapabilityMiddlewareStep, ...] = CAPABILITY_MIDDLEWARE_CHAIN
    records: tuple[CapabilityMiddlewareRecord, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.middleware_chain, tuple):
            object.__setattr__(self, "middleware_chain", tuple(self.middleware_chain))
        if not isinstance(self.records, tuple):
            object.__setattr__(self, "records", tuple(self.records))

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "capability_id": self.capability_id,
            "middleware_chain": list(self.middleware_chain),
            "records": [record.to_dict() for record in self.records],
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CapabilityInvocationTrace:
        return cls(
            trace_id=str(data["trace_id"]),
            capability_id=str(data["capability_id"]),
            middleware_chain=tuple(data.get("middleware_chain") or CAPABILITY_MIDDLEWARE_CHAIN),
            records=tuple(
                CapabilityMiddlewareRecord.from_dict(dict(item))
                for item in data.get("records", ())
            ),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True, slots=True)
class SuggestedNextCapability:
    """A provider-authored next action hint for Reception or operators."""

    capability_id: str
    rationale: str
    confidence: float
    args_hint: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "rationale": self.rationale,
            "confidence": self.confidence,
            "args_hint": dict(self.args_hint),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SuggestedNextCapability:
        return cls(
            capability_id=str(data["capability_id"]),
            rationale=str(data.get("rationale") or ""),
            confidence=float(data.get("confidence", 0.0)),
            args_hint=dict(data.get("args_hint") or {}),
        )


@dataclass(frozen=True, slots=True)
class CapabilityExecutionHandle:
    """Subscription handle returned by async, stream, or workflow capabilities."""

    run_id: str
    session_event_filter: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "session_event_filter": dict(self.session_event_filter),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CapabilityExecutionHandle:
        return cls(
            run_id=str(data["run_id"]),
            session_event_filter=dict(data.get("session_event_filter") or {}),
        )


@dataclass(frozen=True, slots=True)
class CapabilityEscalation:
    """How a denied caller can request access or human approval."""

    approver_role: str
    request_capability: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "approver_role": self.approver_role,
            "request_capability": self.request_capability,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CapabilityEscalation:
        return cls(
            approver_role=str(data["approver_role"]),
            request_capability=data.get("request_capability"),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True, slots=True)
class CallerFrame:
    """Identity of the capability caller and its side-effect mode."""

    type: CapabilityCallerType
    id: str
    mode: CapabilityCallerMode

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type, "id": self.id, "mode": self.mode}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CallerFrame:
        return cls(
            type=data["type"],
            id=str(data["id"]),
            mode=data["mode"],
        )


@dataclass(frozen=True, slots=True)
class CapabilityInvokeContext:
    """Scoped tenant/session/runtime context passed into a capability invoke."""

    tenant_id: str
    workspace_id: str
    project_id: str | None = None
    session_id: str | None = None
    run_id: str | None = None
    request_id: str | None = None
    trace_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "workspace_id": self.workspace_id,
            "project_id": self.project_id,
            "session_id": self.session_id,
            "run_id": self.run_id,
            "request_id": self.request_id,
            "trace_id": self.trace_id,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CapabilityInvokeContext:
        return cls(
            tenant_id=str(data["tenant_id"]),
            workspace_id=str(data["workspace_id"]),
            project_id=data.get("project_id"),
            session_id=data.get("session_id"),
            run_id=data.get("run_id"),
            request_id=data.get("request_id"),
            trace_id=data.get("trace_id"),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True, slots=True)
class CapabilityConfirmation:
    """Confirmation state supplied by the caller."""

    confirmed: bool = False
    decision_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"confirmed": self.confirmed, "decision_id": self.decision_id}

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> CapabilityConfirmation:
        if not data:
            return cls()
        return cls(
            confirmed=bool(data.get("confirmed", False)),
            decision_id=data.get("decision_id"),
        )


@dataclass(frozen=True, slots=True)
class CapabilityInvokeRequest:
    """Canonical request for ``POST /capabilities/{capability_id}/invoke``."""

    caller: CallerFrame
    context: CapabilityInvokeContext
    arguments: dict[str, Any] = field(default_factory=dict)
    implicit_args_resolution: Literal["auto", "disabled", "strict"] = "auto"
    confirmation: CapabilityConfirmation = field(default_factory=CapabilityConfirmation)
    mode: CapabilityInvokeMode = "execute"

    def to_dict(self) -> dict[str, Any]:
        return {
            "caller": self.caller.to_dict(),
            "context": self.context.to_dict(),
            "implicit_args_resolution": self.implicit_args_resolution,
            "arguments": dict(self.arguments),
            "confirmation": self.confirmation.to_dict(),
            "mode": self.mode,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CapabilityInvokeRequest:
        return cls(
            caller=CallerFrame.from_dict(dict(data["caller"])),
            context=CapabilityInvokeContext.from_dict(dict(data["context"])),
            implicit_args_resolution=data.get("implicit_args_resolution", "auto"),
            arguments=dict(data.get("arguments") or {}),
            confirmation=CapabilityConfirmation.from_dict(data.get("confirmation")),
            mode=data.get("mode", "execute"),
        )


@dataclass(frozen=True, slots=True)
class CapabilityInvokeResponse:
    """Canonical response for all capability invocations."""

    status: CapabilityInvokeStatus
    result: dict[str, Any] | None = None
    error_code: CapabilityErrorCode | None = None
    explanation: str | None = None
    retry_after_ms: int | None = None
    decision_id: str | None = None
    risk: CapabilityRisk | None = None
    preview: dict[str, Any] | None = None
    missing_binding: dict[str, Any] | None = None
    escalation: CapabilityEscalation | None = None
    execution_handle: CapabilityExecutionHandle | None = None
    suggested_next_capabilities: tuple[SuggestedNextCapability, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.suggested_next_capabilities, tuple):
            object.__setattr__(
                self,
                "suggested_next_capabilities",
                tuple(self.suggested_next_capabilities),
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "result": self.result,
            "error_code": self.error_code,
            "explanation": self.explanation,
            "retry_after_ms": self.retry_after_ms,
            "decision_id": self.decision_id,
            "risk": self.risk,
            "preview": self.preview,
            "missing_binding": self.missing_binding,
            "escalation": self.escalation.to_dict() if self.escalation else None,
            "execution_handle": (
                self.execution_handle.to_dict() if self.execution_handle else None
            ),
            "suggested_next_capabilities": [
                item.to_dict() for item in self.suggested_next_capabilities
            ],
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CapabilityInvokeResponse:
        return cls(
            status=data["status"],
            result=data.get("result"),
            error_code=data.get("error_code"),
            explanation=data.get("explanation"),
            retry_after_ms=data.get("retry_after_ms"),
            decision_id=data.get("decision_id"),
            risk=data.get("risk"),
            preview=data.get("preview"),
            missing_binding=data.get("missing_binding"),
            escalation=(
                CapabilityEscalation.from_dict(dict(data["escalation"]))
                if data.get("escalation")
                else None
            ),
            execution_handle=(
                CapabilityExecutionHandle.from_dict(dict(data["execution_handle"]))
                if data.get("execution_handle")
                else None
            ),
            suggested_next_capabilities=tuple(
                SuggestedNextCapability.from_dict(dict(item))
                for item in data.get("suggested_next_capabilities", ())
            ),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True, slots=True)
class PlatformCapability:
    """Stable catalog record for a platform, agent, or integration capability."""

    capability_id: str
    version: str
    status: CapabilityStatus
    display_name: str
    description: str
    kind: CapabilityKind
    provider: CapabilityProvider
    runtime_ref: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    risk: CapabilityRisk
    side_effect: CapabilitySideEffect
    exec_kind: CapabilityExecKind
    tags: tuple[str, ...] = ()
    compat_range: tuple[str, ...] = ()
    replaced_by: str | None = None
    migration_hint: str | None = None
    input_schema_version: int = 1
    introduced_at: str = ""
    natural_language_aliases: tuple[str, ...] = ()
    examples: tuple[dict[str, Any], ...] = ()
    idempotent: bool = False
    expected_duration_class: CapabilityDurationClass = "<1min"
    streamable: bool = False
    cancellation_supported: bool = False
    progress_events: bool = False
    dry_run_supported: bool = False
    requires_confirmation: bool = False
    cost_tier: CapabilityCostTier = "standard"
    p50_latency_ms: int | None = None
    p99_latency_ms: int | None = None
    reliability_score: float | None = None
    recent_error_rate: float | None = None
    quality_tier: CapabilityQualityTier = "standard"
    enabled_for: tuple[CapabilityCallerType, ...] = ()
    scopes_required: tuple[str, ...] = ()
    binding_required: bool = False
    accepts_implicit_args: tuple[str, ...] = ()
    usage_metering: dict[str, Any] = field(default_factory=dict)
    requires: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()
    dependencies: tuple[str, ...] = ()
    provides: tuple[str, ...] = ()
    consumes: tuple[str, ...] = ()
    execution_lane: CapabilityExecutionLane = "direct"
    risk_class: CapabilityRiskClass = "read_only"
    governance: CapabilityGovernance = field(default_factory=CapabilityGovernance)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in (
            "tags",
            "compat_range",
            "natural_language_aliases",
            "examples",
            "enabled_for",
            "scopes_required",
            "accepts_implicit_args",
            "requires",
            "conflicts",
            "dependencies",
            "provides",
            "consumes",
        ):
            value = getattr(self, name)
            if not isinstance(value, tuple):
                object.__setattr__(self, name, tuple(value))

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "version": self.version,
            "status": self.status,
            "compat_range": list(self.compat_range),
            "replaced_by": self.replaced_by,
            "migration_hint": self.migration_hint,
            "input_schema_version": self.input_schema_version,
            "introduced_at": self.introduced_at,
            "display_name": self.display_name,
            "description": self.description,
            "kind": self.kind,
            "provider": self.provider,
            "runtime_ref": self.runtime_ref,
            "tags": list(self.tags),
            "natural_language_aliases": list(self.natural_language_aliases),
            "examples": [dict(item) for item in self.examples],
            "input_schema": dict(self.input_schema),
            "output_schema": dict(self.output_schema),
            "risk": self.risk,
            "side_effect": self.side_effect,
            "idempotent": self.idempotent,
            "exec_kind": self.exec_kind,
            "expected_duration_class": self.expected_duration_class,
            "streamable": self.streamable,
            "cancellation_supported": self.cancellation_supported,
            "progress_events": self.progress_events,
            "dry_run_supported": self.dry_run_supported,
            "requires_confirmation": self.requires_confirmation,
            "cost_tier": self.cost_tier,
            "p50_latency_ms": self.p50_latency_ms,
            "p99_latency_ms": self.p99_latency_ms,
            "reliability_score": self.reliability_score,
            "recent_error_rate": self.recent_error_rate,
            "quality_tier": self.quality_tier,
            "enabled_for": list(self.enabled_for),
            "scopes_required": list(self.scopes_required),
            "binding_required": self.binding_required,
            "accepts_implicit_args": list(self.accepts_implicit_args),
            "usage_metering": dict(self.usage_metering),
            "requires": list(self.requires),
            "conflicts": list(self.conflicts),
            "dependencies": list(self.dependencies),
            "provides": list(self.provides),
            "consumes": list(self.consumes),
            "execution_lane": self.execution_lane,
            "risk_class": self.risk_class,
            "governance": self.governance.to_dict(),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PlatformCapability:
        return cls(
            capability_id=str(data["capability_id"]),
            version=str(data["version"]),
            status=data["status"],
            compat_range=tuple(data.get("compat_range") or ()),
            replaced_by=data.get("replaced_by"),
            migration_hint=data.get("migration_hint"),
            input_schema_version=int(data.get("input_schema_version", 1)),
            introduced_at=str(data.get("introduced_at") or ""),
            display_name=str(data["display_name"]),
            description=str(data.get("description") or ""),
            kind=data["kind"],
            provider=data["provider"],
            runtime_ref=str(data.get("runtime_ref") or ""),
            tags=tuple(data.get("tags") or ()),
            natural_language_aliases=tuple(data.get("natural_language_aliases") or ()),
            examples=tuple(dict(item) for item in data.get("examples") or ()),
            input_schema=dict(data.get("input_schema") or {}),
            output_schema=dict(data.get("output_schema") or {}),
            risk=data["risk"],
            side_effect=data["side_effect"],
            idempotent=bool(data.get("idempotent", False)),
            exec_kind=data["exec_kind"],
            expected_duration_class=data.get("expected_duration_class", "<1min"),
            streamable=bool(data.get("streamable", False)),
            cancellation_supported=bool(data.get("cancellation_supported", False)),
            progress_events=bool(data.get("progress_events", False)),
            dry_run_supported=bool(data.get("dry_run_supported", False)),
            requires_confirmation=bool(data.get("requires_confirmation", False)),
            cost_tier=data.get("cost_tier", "standard"),
            p50_latency_ms=data.get("p50_latency_ms"),
            p99_latency_ms=data.get("p99_latency_ms"),
            reliability_score=data.get("reliability_score"),
            recent_error_rate=data.get("recent_error_rate"),
            quality_tier=data.get("quality_tier", "standard"),
            enabled_for=tuple(data.get("enabled_for") or ()),
            scopes_required=tuple(data.get("scopes_required") or ()),
            binding_required=bool(data.get("binding_required", False)),
            accepts_implicit_args=tuple(data.get("accepts_implicit_args") or ()),
            usage_metering=dict(data.get("usage_metering") or {}),
            requires=tuple(data.get("requires") or ()),
            conflicts=tuple(data.get("conflicts") or ()),
            dependencies=tuple(data.get("dependencies") or ()),
            provides=tuple(data.get("provides") or ()),
            consumes=tuple(data.get("consumes") or ()),
            execution_lane=data.get("execution_lane", "direct"),
            risk_class=data.get("risk_class", "read_only"),
            governance=CapabilityGovernance.from_dict(data.get("governance")),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True, slots=True)
class CapabilityPlanNodeDraft:
    """Capability-first plan node target shape.

    This is the protocol shape Planner should eventually emit.  Legacy
    ``agent_id`` based nodes remain in older runtime contracts until the Phase 4
    hard cut, but no new field is added here for that fallback.
    """

    node_id: str
    required_capabilities: tuple[str, ...]
    capability_args: dict[str, dict[str, Any]] = field(default_factory=dict)
    implicit_runtime_context_refs: tuple[str, ...] = ()
    fitness_score_breakdown: dict[str, dict[str, float]] = field(default_factory=dict)
    risk_flags: tuple[str, ...] = ()
    resolved_at_approval: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in (
            "required_capabilities",
            "implicit_runtime_context_refs",
            "risk_flags",
        ):
            value = getattr(self, name)
            if not isinstance(value, tuple):
                object.__setattr__(self, name, tuple(value))

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "required_capabilities": list(self.required_capabilities),
            "capability_args": {
                capability_id: dict(args)
                for capability_id, args in self.capability_args.items()
            },
            "implicit_runtime_context_refs": list(self.implicit_runtime_context_refs),
            "fitness_score_breakdown": {
                capability_id: dict(scores)
                for capability_id, scores in self.fitness_score_breakdown.items()
            },
            "risk_flags": list(self.risk_flags),
            "resolved_at_approval": self.resolved_at_approval,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CapabilityPlanNodeDraft:
        return cls(
            node_id=str(data["node_id"]),
            required_capabilities=tuple(data.get("required_capabilities") or ()),
            capability_args={
                str(capability_id): dict(args)
                for capability_id, args in dict(data.get("capability_args") or {}).items()
            },
            implicit_runtime_context_refs=tuple(
                data.get("implicit_runtime_context_refs") or ()
            ),
            fitness_score_breakdown={
                str(capability_id): {
                    str(score_name): float(score)
                    for score_name, score in dict(scores).items()
                }
                for capability_id, scores in dict(
                    data.get("fitness_score_breakdown") or {}
                ).items()
            },
            risk_flags=tuple(data.get("risk_flags") or ()),
            resolved_at_approval=data.get("resolved_at_approval"),
            metadata=dict(data.get("metadata") or {}),
        )


CapabilitySelectionSource = Literal[
    "llm_rank",
    "single_candidate_short_circuit",
    "manual",
    "policy_rewrite",
    "patch_replay",
    "unspecified",
]
"""Closed set of provenance markers for ``CapabilitySelectionRationale.source``.

ADR-012 audit needs to distinguish how a capability was picked so the
replay path can decide whether to re-run the LLM (``llm_rank`` /
``single_candidate_short_circuit``) or trust a deterministic upstream
decision (``manual`` / ``policy_rewrite`` / ``patch_replay``)."""


@dataclass(frozen=True, slots=True)
class CapabilityCandidateScore:
    """One candidate the picker considered for a single step.

    ADR-012 audit replays "why this capability won" by storing every
    alternative the LLM saw alongside the chosen winner. Score is
    optional because the picker is LLM-driven — when ranks are
    qualitative (no numeric score), the ``notes`` field carries the
    LLM's reasoning instead.
    """

    capability_id: str
    agent_id: str = ""
    score: float | None = None
    risk_class: str = ""
    side_effect: str = ""
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "agent_id": self.agent_id,
            "score": self.score,
            "risk_class": self.risk_class,
            "side_effect": self.side_effect,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CapabilityCandidateScore:
        score_raw = data.get("score")
        score: float | None
        if score_raw is None:
            score = None
        else:
            try:
                score = float(score_raw)
            except (TypeError, ValueError):
                score = None
        return cls(
            capability_id=str(data.get("capability_id") or ""),
            agent_id=str(data.get("agent_id") or ""),
            score=score,
            risk_class=str(data.get("risk_class") or ""),
            side_effect=str(data.get("side_effect") or ""),
            notes=str(data.get("notes") or ""),
        )


@dataclass(frozen=True, slots=True)
class CapabilitySelectionRationale:
    """ADR-012 LLM-rank rationale pinned per ``CapabilityResolution``.

    Captures the picker's per-step explanation + the candidate score
    table at plan-approve time so audit can replay the routing decision
    without re-running the LLM. Empty default values keep legacy
    snapshots deserialisable.
    """

    source: CapabilitySelectionSource = "unspecified"
    rationale_text: str = ""
    candidate_scores: tuple[CapabilityCandidateScore, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.candidate_scores, tuple):
            object.__setattr__(
                self, "candidate_scores", tuple(self.candidate_scores)
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "rationale_text": self.rationale_text,
            "candidate_scores": [c.to_dict() for c in self.candidate_scores],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CapabilitySelectionRationale:
        raw_source = str(data.get("source") or "unspecified")
        source: CapabilitySelectionSource = (
            raw_source  # type: ignore[assignment]
            if raw_source
            in (
                "llm_rank",
                "single_candidate_short_circuit",
                "manual",
                "policy_rewrite",
                "patch_replay",
                "unspecified",
            )
            else "unspecified"
        )
        return cls(
            source=source,
            rationale_text=str(data.get("rationale_text") or ""),
            candidate_scores=tuple(
                CapabilityCandidateScore.from_dict(dict(item))
                for item in data.get("candidate_scores", ())
            ),
        )


@dataclass(frozen=True, slots=True)
class CapabilityResolution:
    """A frozen capability binding chosen for one approved plan node."""

    node_id: str
    required_capability: str
    resolved_runtime_ref: str
    resolved_capability_version: str
    resolved_binding_id: str | None = None
    resolved_credential_ref: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    # ADR-012 — picker rationale captured at plan-approve time. ``None``
    # for legacy resolutions or resolutions where rationale was not
    # surfaced; serialisation drops the field when ``None`` to keep
    # round-trip shape backwards compatible with pre-ADR-012 snapshots.
    selection_rationale: CapabilitySelectionRationale | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "node_id": self.node_id,
            "required_capability": self.required_capability,
            "resolved_runtime_ref": self.resolved_runtime_ref,
            "resolved_capability_version": self.resolved_capability_version,
            "resolved_binding_id": self.resolved_binding_id,
            "resolved_credential_ref": self.resolved_credential_ref,
            "metadata": dict(self.metadata),
        }
        if self.selection_rationale is not None:
            payload["selection_rationale"] = self.selection_rationale.to_dict()
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CapabilityResolution:
        rationale_raw = data.get("selection_rationale")
        rationale: CapabilitySelectionRationale | None = None
        if isinstance(rationale_raw, dict):
            rationale = CapabilitySelectionRationale.from_dict(rationale_raw)
        return cls(
            node_id=str(data["node_id"]),
            required_capability=str(data["required_capability"]),
            resolved_runtime_ref=str(data["resolved_runtime_ref"]),
            resolved_capability_version=str(data["resolved_capability_version"]),
            resolved_binding_id=data.get("resolved_binding_id"),
            resolved_credential_ref=data.get("resolved_credential_ref"),
            metadata=dict(data.get("metadata") or {}),
            selection_rationale=rationale,
        )


@dataclass(frozen=True, slots=True)
class CapabilityDriftReportItem:
    """Difference between a prior frozen resolution and current catalog state."""

    previous_capability_id: str
    previous_version: str
    current_status: CapabilityStatus
    current_version: str
    schema_compat: CapabilitySchemaCompat
    binding_status: str
    replaced_by: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "previous_capability_id": self.previous_capability_id,
            "previous_version": self.previous_version,
            "current_status": self.current_status,
            "replaced_by": self.replaced_by,
            "current_version": self.current_version,
            "schema_compat": self.schema_compat,
            "binding_status": self.binding_status,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CapabilityDriftReportItem:
        return cls(
            previous_capability_id=str(data["previous_capability_id"]),
            previous_version=str(data["previous_version"]),
            current_status=data["current_status"],
            replaced_by=data.get("replaced_by"),
            current_version=str(data["current_version"]),
            schema_compat=data["schema_compat"],
            binding_status=str(data["binding_status"]),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True, slots=True)
class CapabilityResolutionSnapshotPatch:
    """Append-only record describing why a resolution snapshot version changed."""

    patch_id: str
    plan_id: str
    from_snapshot_version: str
    to_snapshot_version: str
    trigger_source: SnapshotPatchTriggerSource
    decision: SnapshotPatchDecision
    reason: str
    patch_attempt: int = 1
    affected_step_ids: tuple[str, ...] = ()
    drift_items: tuple[CapabilityDriftReportItem, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.affected_step_ids, tuple):
            object.__setattr__(
                self,
                "affected_step_ids",
                tuple(self.affected_step_ids),
            )
        if not isinstance(self.drift_items, tuple):
            object.__setattr__(self, "drift_items", tuple(self.drift_items))
        object.__setattr__(self, "patch_attempt", max(1, int(self.patch_attempt)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "patch_id": self.patch_id,
            "plan_id": self.plan_id,
            "from_snapshot_version": self.from_snapshot_version,
            "to_snapshot_version": self.to_snapshot_version,
            "trigger_source": self.trigger_source,
            "decision": self.decision,
            "reason": self.reason,
            "patch_attempt": self.patch_attempt,
            "affected_step_ids": list(self.affected_step_ids),
            "drift_items": [item.to_dict() for item in self.drift_items],
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CapabilityResolutionSnapshotPatch:
        return cls(
            patch_id=str(data["patch_id"]),
            plan_id=str(data["plan_id"]),
            from_snapshot_version=str(data["from_snapshot_version"]),
            to_snapshot_version=str(data["to_snapshot_version"]),
            trigger_source=data["trigger_source"],
            decision=data["decision"],
            reason=str(data.get("reason") or ""),
            patch_attempt=int(data.get("patch_attempt") or 1),
            affected_step_ids=tuple(data.get("affected_step_ids") or ()),
            drift_items=tuple(
                CapabilityDriftReportItem.from_dict(dict(item))
                for item in data.get("drift_items", ())
            ),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True, slots=True)
class CapabilityResolutionSnapshot:
    """Capability resolutions frozen when a plan is approved."""

    plan_id: str
    frozen_at: str
    resolutions: tuple[CapabilityResolution, ...]
    runtime_context_snapshot_ref: str | None = None
    snapshot_version: str = "v1"
    predecessor_snapshot_version: str | None = None
    patch_attempt: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.resolutions, tuple):
            object.__setattr__(self, "resolutions", tuple(self.resolutions))
        object.__setattr__(self, "patch_attempt", max(0, int(self.patch_attempt)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "frozen_at": self.frozen_at,
            "resolutions": [item.to_dict() for item in self.resolutions],
            "runtime_context_snapshot_ref": self.runtime_context_snapshot_ref,
            "snapshot_version": self.snapshot_version,
            "predecessor_snapshot_version": self.predecessor_snapshot_version,
            "patch_attempt": self.patch_attempt,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CapabilityResolutionSnapshot:
        return cls(
            plan_id=str(data["plan_id"]),
            frozen_at=str(data["frozen_at"]),
            resolutions=tuple(
                CapabilityResolution.from_dict(dict(item))
                for item in data.get("resolutions", ())
            ),
            runtime_context_snapshot_ref=data.get("runtime_context_snapshot_ref"),
            snapshot_version=str(data.get("snapshot_version") or "v1"),
            predecessor_snapshot_version=data.get("predecessor_snapshot_version"),
            patch_attempt=int(data.get("patch_attempt") or 0),
            metadata=dict(data.get("metadata") or {}),
        )


# ── Capability description quality rules ─────────────────────────────────────
#
# The CapabilityPicker (LLM-driven RoutingReplanner) selects agents using
# the ``description`` field of each capability. A vague description
# directly degrades routing accuracy and gets the platform parked in
# Human Review. Enforce minimum quality at registration time so a thin
# manifest can never land in the registry in the first place.
#
# Two rules, both deterministic:
#
# - Length floor (``_DESCRIPTION_MIN_LENGTH``). 30 chars is enough for a
#   short but real "<verb> <subject> <constraint>" sentence in either
#   Chinese or English, and rejects every canonical placeholder we've
#   seen in stub manifests ("todo", "no description", "stub", "TBD",
#   "-", empty string). Production manifests are expected to do
#   considerably better — the picker's routing accuracy correlates
#   directly with description richness — but 30 is the floor below
#   which the manifest is clearly unfit for routing.
# - No duplication of ``display_name``. The laziest "fill the required
#   field" workaround is to copy the display name into the description;
#   detecting it is cheap and high-signal.
#
# A "placeholder phrase" blacklist was considered and rejected: every
# canonical placeholder we'd want to block is already shorter than the
# length floor, so the blacklist would never actually fire. If we ever
# need to catch verbose-but-vacuous descriptions ("This capability is a
# placeholder capability that placeholders things ..."), that's a
# semantic check best done via conformance testing, not a hard-coded
# substring list.

_DESCRIPTION_MIN_LENGTH = 30


def validate_capability_description(
    entry: "AgentCapabilityManifestEntry",
) -> list[str]:
    """Return human-readable errors for a thin ``description``.

    Returns ``[]`` when the description meets minimum quality rules:

    1. Length >= ``_DESCRIPTION_MIN_LENGTH`` characters after strip.
    2. Not equal to ``display_name`` (case-insensitive, both stripped).

    The caller (``AgentManifestV2.validate``) flattens the errors into
    its overall error list, which the ``/agents/register`` route then
    surfaces as a 422 response — so an agent with a thin description
    cannot register at all.
    """
    errors: list[str] = []
    description = (entry.description or "").strip()
    display_name = (entry.display_name or "").strip()
    capability_id = entry.capability_id or "<unknown>"

    if len(description) < _DESCRIPTION_MIN_LENGTH:
        errors.append(
            f"capability {capability_id!r}: description too short "
            f"({len(description)} chars; minimum {_DESCRIPTION_MIN_LENGTH}). "
            "Describe what the capability does, its inputs, and its side effects."
        )
        return errors

    if description.lower() == display_name.lower():
        errors.append(
            f"capability {capability_id!r}: description duplicates display_name; "
            "write a real explanation of what the capability does."
        )
    return errors
