"""Unified Agent Runtime Contract (ADR-133).

One work order in, one completion report out — identical for every executor,
whether it runs in-process (DeepAgents) or across A2A (OpenCode, Codex).

The contract lives here rather than in the A2A SDK on purpose: an in-process
executor must not be forced through HTTP to receive a typed work order, and two
definitions would reintroduce exactly the drift this contract exists to kill.
The SDK adds the *network* binding on top of these types.

The failure this prevents is concrete. The platform used to hand-assemble the
A2A payload with the repository at the envelope's top level while the wire
contract read it from ``brief``; the field vanished silently, the agent ran with
no repository, wandered into its own home directory and hung until the platform
timed it out ten minutes later. Nothing along that path could report the error,
because nothing held a type. :func:`parse_run_input` is where that now dies.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

SCHEMA_VERSION = "1.0"

RunStatus = Literal["completed", "blocked", "failed"]

#: Side-effect classes a mandate may grant. Anything absent is denied.
SIDE_EFFECT_CLASSES: tuple[str, ...] = (
    "workspace.read",
    "workspace.write",
    "repo.pull_request",
    "deploy.preview",
    "tracker.write",
)

#: Contract-owned names. Seeing one at the envelope's top level means a caller
#: hand-assembled the payload instead of serialising the contract.
_CONTRACT_OWNED = frozenset(
    {
        "objective",
        "instructions",
        "skills",
        "memory_refs",
        "capabilities",
        "workspace",
        "workspace_files",
        "output_schema",
        "repository_ref",
        "repository_revision",
        "commit_sha",
    }
)

#: Names with a canonical home elsewhere in the contract. Inside the body they
#: are the pre-contract shape, and accepting them would quietly resurrect the
#: two-places-for-one-fact problem the contract removes.
_RELOCATED = {
    "workspace_files": "brief.workspace.files",
    "commit_sha": "brief.workspace.commit_sha",
    "repository_ref": "constraints.repository_ref",
    "repository_revision": "constraints.repository_revision",
}


class AgentRunContractError(ValueError):
    """Raised when a payload does not satisfy the runtime contract."""


@dataclass(frozen=True, slots=True)
class ExecutionMandate:
    """What this run is allowed to do (ADR-132).

    This is the object a human approves — deterministic data, not an LLM-drawn
    graph. It is also the contract's ``constraints``: the two were deliberately
    not modelled twice.
    """

    repository_ref: str = ""
    repository_revision: str = ""
    side_effects: tuple[str, ...] = ()
    allowed_paths: tuple[str, ...] = ()
    network_access: bool = False
    max_cost_usd: float = 0.0
    max_steps: int = 0

    def allows(self, side_effect: str) -> bool:
        return side_effect in self.side_effects

    def to_dict(self) -> dict[str, Any]:
        return {
            "repository_ref": self.repository_ref,
            "repository_revision": self.repository_revision,
            "side_effects": list(self.side_effects),
            "allowed_paths": list(self.allowed_paths),
            "network_access": self.network_access,
            "max_cost_usd": self.max_cost_usd,
            "max_steps": self.max_steps,
        }

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any] | None) -> ExecutionMandate:
        data = dict(raw or {})
        unknown = [
            item
            for item in _strings(data.get("side_effects"))
            if item not in SIDE_EFFECT_CLASSES
        ]
        if unknown:
            raise AgentRunContractError(
                f"unknown side-effect class(es) {unknown}; "
                f"allowed: {list(SIDE_EFFECT_CLASSES)}"
            )
        return cls(
            repository_ref=str(data.get("repository_ref") or ""),
            repository_revision=str(data.get("repository_revision") or ""),
            side_effects=_strings(data.get("side_effects")),
            allowed_paths=_strings(data.get("allowed_paths")),
            network_access=bool(data.get("network_access", False)),
            max_cost_usd=float(data.get("max_cost_usd") or 0.0),
            max_steps=int(data.get("max_steps") or 0),
        )


@dataclass(frozen=True, slots=True)
class WorkspaceDescriptor:
    """The repository content the harness supplies (ADR-070).

    Content, never a credential: the platform reads GitHub through GHIS and
    hands the files over, so no executor ever holds a token or a clone URL.
    """

    workspace_id: str = ""
    repository_ref: str = ""
    revision: str = ""
    commit_sha: str = ""
    files: tuple[Mapping[str, Any], ...] = ()
    truncated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "workspace_id": self.workspace_id,
            "repository_ref": self.repository_ref,
            "revision": self.revision,
            "commit_sha": self.commit_sha,
            "files": [dict(item) for item in self.files],
            "truncated": self.truncated,
        }

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any] | None) -> WorkspaceDescriptor | None:
        if not raw:
            return None
        data = dict(raw)
        files = tuple(
            dict(item) for item in (data.get("files") or ()) if isinstance(item, Mapping)
        )
        return cls(
            workspace_id=str(data.get("workspace_id") or ""),
            repository_ref=str(data.get("repository_ref") or ""),
            revision=str(data.get("revision") or ""),
            commit_sha=str(data.get("commit_sha") or ""),
            files=files,
            truncated=bool(data.get("truncated", False)),
        )


@dataclass(frozen=True, slots=True)
class SkillRef:
    """A reusable working method loaded for this task (ADR-133)."""

    skill_id: str
    version: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"skill_id": self.skill_id, "version": self.version}


@dataclass(frozen=True, slots=True)
class AgentRunInput:
    """The work order. Identical for every executor."""

    objective: str
    schema_version: str = SCHEMA_VERSION
    instructions: tuple[str, ...] = ()
    skills: tuple[SkillRef, ...] = ()
    memory_refs: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ()
    workspace: WorkspaceDescriptor | None = None
    output_schema: Mapping[str, Any] = field(default_factory=dict)
    mandate: ExecutionMandate = field(default_factory=ExecutionMandate)
    inputs: Mapping[str, Any] = field(default_factory=dict)

    def to_brief(self) -> dict[str, Any]:
        """The canonical payload body. One serialisation, no alternatives."""
        return {
            "schema_version": self.schema_version,
            "objective": self.objective,
            "instructions": list(self.instructions),
            "skills": [item.to_dict() for item in self.skills],
            "memory_refs": list(self.memory_refs),
            "capabilities": list(self.capabilities),
            "workspace": self.workspace.to_dict() if self.workspace else None,
            "output_schema": dict(self.output_schema),
            **dict(self.inputs),
        }

    def to_wire(self) -> dict[str, Any]:
        """A2A envelope fragment: body under ``brief``, mandate under ``constraints``."""
        return {"brief": self.to_brief(), "constraints": self.mandate.to_dict()}


@dataclass(frozen=True, slots=True)
class AgentRunResult:
    """The completion report. Identical for every executor."""

    status: RunStatus
    artifacts: tuple[Mapping[str, Any], ...] = ()
    evidence: tuple[Mapping[str, Any], ...] = ()
    capability_calls: tuple[Mapping[str, Any], ...] = ()
    usage: Mapping[str, Any] = field(default_factory=dict)
    error_code: str = ""
    message: str = ""
    suggested_next_action: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "artifacts": [dict(item) for item in self.artifacts],
            "evidence": [dict(item) for item in self.evidence],
            "capability_calls": [dict(item) for item in self.capability_calls],
            "usage": dict(self.usage),
            "error_code": self.error_code,
            "message": self.message,
            "suggested_next_action": self.suggested_next_action,
        }

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any] | None) -> AgentRunResult:
        data = dict(raw or {})
        status = str(data.get("status") or "failed")
        if status not in ("completed", "blocked", "failed"):
            raise AgentRunContractError(
                f"status {status!r} is not one of completed|blocked|failed"
            )
        return cls(
            status=status,  # type: ignore[arg-type]
            artifacts=_mappings(data.get("artifacts")),
            evidence=_mappings(data.get("evidence")),
            capability_calls=_mappings(data.get("capability_calls")),
            usage=dict(data.get("usage") or {}),
            error_code=str(data.get("error_code") or ""),
            message=str(data.get("message") or ""),
            suggested_next_action=str(data.get("suggested_next_action") or ""),
        )


def parse_run_input(envelope: Mapping[str, Any] | None) -> AgentRunInput:
    """Read a work order from an A2A envelope, failing loudly on misplacement.

    A contract-owned field sitting at the envelope's top level is not tolerated
    and silently ignored — that tolerance is what let a repository reference
    disappear between two services that each believed they were correct.
    """
    data = dict(envelope or {})
    misplaced = sorted(_CONTRACT_OWNED.intersection(data))
    if misplaced:
        raise AgentRunContractError(
            f"contract fields {misplaced} were placed at the envelope top level; "
            "they belong inside 'brief' (or 'constraints' for mandate fields). "
            "Serialise AgentRunInput.to_wire() instead of hand-assembling."
        )
    brief = data.get("brief")
    if not isinstance(brief, Mapping):
        raise AgentRunContractError("envelope has no 'brief' body")
    body = dict(brief)
    objective = str(body.get("objective") or "").strip()
    if not objective:
        raise AgentRunContractError("brief.objective is required and was empty")
    version = str(body.get("schema_version") or SCHEMA_VERSION)
    if version.split(".")[0] != SCHEMA_VERSION.split(".")[0]:
        raise AgentRunContractError(
            f"incompatible schema_version {version!r}; this runtime speaks "
            f"{SCHEMA_VERSION}"
        )
    relocated = sorted(set(_RELOCATED).intersection(body))
    if relocated:
        raise AgentRunContractError(
            "brief carries pre-contract fields "
            + ", ".join(f"{key!r} (now {_RELOCATED[key]})" for key in relocated)
        )
    reserved = {
        "schema_version",
        "objective",
        "instructions",
        "skills",
        "memory_refs",
        "capabilities",
        "workspace",
        "output_schema",
    }
    return AgentRunInput(
        objective=objective,
        schema_version=version,
        instructions=_strings(body.get("instructions")),
        skills=tuple(
            SkillRef(
                skill_id=str(item.get("skill_id") or ""),
                version=str(item.get("version") or ""),
            )
            for item in (body.get("skills") or ())
            if isinstance(item, Mapping) and item.get("skill_id")
        ),
        memory_refs=_strings(body.get("memory_refs")),
        capabilities=_strings(body.get("capabilities")),
        workspace=WorkspaceDescriptor.from_mapping(body.get("workspace")),
        output_schema=dict(body.get("output_schema") or {}),
        mandate=ExecutionMandate.from_mapping(data.get("constraints")),
        inputs={key: value for key, value in body.items() if key not in reserved},
    )


def _strings(value: Any) -> tuple[str, ...]:
    if isinstance(value, str) or not isinstance(value, Sequence):
        return ()
    return tuple(str(item) for item in value if str(item).strip())


def _mappings(value: Any) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, Sequence) or isinstance(value, str):
        return ()
    return tuple(dict(item) for item in value if isinstance(item, Mapping))


__all__ = [
    "SCHEMA_VERSION",
    "SIDE_EFFECT_CLASSES",
    "AgentRunContractError",
    "AgentRunInput",
    "AgentRunResult",
    "ExecutionMandate",
    "SkillRef",
    "WorkspaceDescriptor",
    "parse_run_input",
]
