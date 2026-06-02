"""Typed inter-step handoff contracts.

The platform may store full step outputs as artifacts, but downstream agents
must receive a bounded, prompt-safe handoff envelope by default.  These models
define that wire shape without requiring agent runtimes to import platform
internals.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list | tuple) else []


@dataclass(frozen=True, slots=True)
class HandoffEnvelope:
    """Bounded context passed from one DAG step to another."""

    source_step_id: str
    status: str = ""
    artifact_type: str = ""
    handoff_summary: dict[str, Any] = field(default_factory=dict)
    artifact_refs: tuple[dict[str, Any], ...] = ()
    provides_artifacts: dict[str, Any] = field(default_factory=dict)
    provided_artifacts: dict[str, Any] = field(default_factory=dict)
    output_keys: tuple[str, ...] = ()
    omitted_fields: tuple[str, ...] = ()
    truncated: bool = True
    handoff_envelope: dict[str, Any] = field(default_factory=dict)
    artifact_ref: Any | None = None
    payload_ref: Any | None = None
    fact_ref: Any | None = None
    storage_uri: str = ""

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> "HandoffEnvelope":
        artifact_refs = tuple(
            dict(item) for item in _list(value.get("artifact_refs")) if isinstance(item, dict)
        )
        output_keys = tuple(str(item) for item in _list(value.get("output_keys")))
        omitted_fields = tuple(str(item) for item in _list(value.get("omitted_fields")))
        return cls(
            source_step_id=str(value.get("source_step_id") or ""),
            status=str(value.get("status") or ""),
            artifact_type=str(value.get("artifact_type") or ""),
            handoff_summary=_dict(value.get("handoff_summary")),
            artifact_refs=artifact_refs,
            provides_artifacts=_dict(value.get("provides_artifacts")),
            provided_artifacts=_dict(value.get("provided_artifacts")),
            output_keys=output_keys,
            omitted_fields=omitted_fields,
            truncated=bool(value.get("truncated", True)),
            handoff_envelope=_dict(value.get("handoff_envelope")),
            artifact_ref=value.get("artifact_ref"),
            payload_ref=value.get("payload_ref"),
            fact_ref=value.get("fact_ref"),
            storage_uri=str(value.get("storage_uri") or ""),
        )

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "source_step_id": self.source_step_id,
            "status": self.status,
            "artifact_type": self.artifact_type,
            "handoff_summary": dict(self.handoff_summary),
            "artifact_refs": [dict(item) for item in self.artifact_refs],
            "output_keys": list(self.output_keys),
            "omitted_fields": list(self.omitted_fields),
            "truncated": self.truncated,
        }
        if self.handoff_envelope:
            out["handoff_envelope"] = dict(self.handoff_envelope)
        if self.provides_artifacts:
            out["provides_artifacts"] = dict(self.provides_artifacts)
        if self.provided_artifacts:
            out["provided_artifacts"] = dict(self.provided_artifacts)
        if self.artifact_ref:
            out["artifact_ref"] = self.artifact_ref
        if self.payload_ref:
            out["payload_ref"] = self.payload_ref
        if self.fact_ref:
            out["fact_ref"] = self.fact_ref
        if self.storage_uri:
            out["storage_uri"] = self.storage_uri
        return out


__all__ = ["HandoffEnvelope"]
