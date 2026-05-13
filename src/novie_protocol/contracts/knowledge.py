"""KnowledgeRecord contract — W1 of KNOWLEDGE_LIFECYCLE_SEDIMENTATION.

Generalizes the existing ``infra/plan_decision/`` sediment pattern
into a five-family taxonomy:

- ``plan_decision`` — a planner's verdict at a gate.
- ``artifact_summary`` — bounded summary of a deliverable.
- ``intermediate_conclusion`` — a worker's mid-run finding.
- ``preference`` — operator preference / habit (free-form).
- ``correction`` — explicit user correction over a prior output.

Each record carries a **provenance envelope** so audits can replay
the origin (run / turn / capability / agent / timestamp). Bodies are
size-capped per family to keep the prompt injection budget bounded.

Companion to ``contracts/skill.py``. The two contracts share the
``EffectiveXxxSet`` shape so the ``effective_context`` channel in
``application/planning.py`` can render both with one renderer.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal


KnowledgeKind = Literal[
    "plan_decision",
    "artifact_summary",
    "intermediate_conclusion",
    "preference",
    "correction",
]

KnowledgeScope = Literal["project", "org"]
"""Knowledge is org- or project-scoped only. There is no
``personal`` tier — operator preferences belong to a project at the
strongest narrowing; personal data has separate compliance
requirements that this backlog explicitly does not address.
"""


# ── Per-family caps ─────────────────────────────────────────────────


_PER_KIND_BODY_KIB: dict[KnowledgeKind, int] = {
    "plan_decision": 8,
    "artifact_summary": 4,
    "intermediate_conclusion": 4,
    "preference": 1,
    "correction": 2,
}

_SUMMARY_MAX_CHARS: int = 280  # ~1 sentence
_TOTAL_BODY_HARD_KIB: int = 16

EFFECTIVE_KNOWLEDGE_COUNT_CAP: int = 12
EFFECTIVE_KNOWLEDGE_TOTAL_BODY_KIB: int = 24


class KnowledgeValidationError(ValueError):
    """Raised when a KnowledgeRecord payload violates the contract."""


def kind_body_cap_kib(kind: KnowledgeKind) -> int:
    """Body size cap (in KiB) for a given record family. Useful for
    storage-side validation that has the kind in hand but not the
    full record."""
    return _PER_KIND_BODY_KIB.get(kind, 4)


# ── Records ─────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class KnowledgeProvenance:
    """Required envelope every KnowledgeRecord carries. Empty strings
    are allowed only when no equivalent identifier exists for the
    sedimentation hook — but ``created_at`` and ``created_by`` MUST
    always be populated."""

    originating_run_id: str = ""
    originating_turn_id: str = ""
    originating_capability_id: str = ""
    originating_agent_id: str = ""
    created_at: datetime | None = None
    created_by: str = "system"
    """Either a principal_id (user-driven sedimentation) or a system
    tag such as ``system:plan_decision_outcome`` (automated)."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "originating_run_id": self.originating_run_id,
            "originating_turn_id": self.originating_turn_id,
            "originating_capability_id": self.originating_capability_id,
            "originating_agent_id": self.originating_agent_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "created_by": self.created_by,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "KnowledgeProvenance":
        if not isinstance(data, dict):
            return cls()
        from datetime import datetime as _dt
        created_at_raw = data.get("created_at")
        return cls(
            originating_run_id=str(data.get("originating_run_id") or ""),
            originating_turn_id=str(data.get("originating_turn_id") or ""),
            originating_capability_id=str(data.get("originating_capability_id") or ""),
            originating_agent_id=str(data.get("originating_agent_id") or ""),
            created_at=(
                _dt.fromisoformat(created_at_raw)
                if isinstance(created_at_raw, str) and created_at_raw
                else None
            ),
            created_by=str(data.get("created_by") or "system"),
        )


@dataclass(frozen=True, slots=True)
class KnowledgeRecord:
    """A single sedimented knowledge entry.

    ``record_id`` is the deterministic, hash-derived id Temporal
    activities use for retry idempotency
    (``hash((run_id, turn_id, kind, summary))``). Storage layers may
    accept caller-supplied ids that match this shape.
    """

    record_id: str
    kind: KnowledgeKind
    scope: KnowledgeScope
    scope_ref: str
    """Project id or org / tenant id depending on scope."""

    summary: str
    body: str

    tags: tuple[str, ...] = ()
    applies_to: tuple[str, ...] = ()
    """Optional capability-id / stage allow-list — informs the
    retrieval ranker about where this record is most useful."""

    embeddings_ref: str = ""
    provenance: KnowledgeProvenance = field(default_factory=KnowledgeProvenance)

    def __post_init__(self) -> None:
        if not self.record_id:
            raise KnowledgeValidationError("record_id is required")
        if self.kind not in _PER_KIND_BODY_KIB:
            raise KnowledgeValidationError(
                f"invalid kind {self.kind!r}; must be one of "
                f"{sorted(_PER_KIND_BODY_KIB)}",
            )
        if self.scope not in ("project", "org"):
            raise KnowledgeValidationError(
                f"invalid scope {self.scope!r}; must be project | org",
            )
        if not self.scope_ref:
            raise KnowledgeValidationError(
                f"scope_ref is required for {self.record_id!r}",
            )
        summary = self.summary.strip()
        if not summary:
            raise KnowledgeValidationError(
                f"summary is required for {self.record_id!r} (audits cannot "
                f"render a record without a single-sentence summary).",
            )
        if len(summary) > _SUMMARY_MAX_CHARS:
            raise KnowledgeValidationError(
                f"summary for {self.record_id!r} is {len(summary)} chars; "
                f"cap is {_SUMMARY_MAX_CHARS}. Move detail into the body.",
            )
        body_bytes = len(self.body.encode("utf-8"))
        cap_kib = _PER_KIND_BODY_KIB[self.kind]
        if body_bytes > cap_kib * 1024:
            raise KnowledgeValidationError(
                f"body for {self.record_id!r} ({self.kind}) is {body_bytes} "
                f"bytes; per-family cap is {cap_kib} KiB. Use a shorter body "
                f"or pick a different record kind.",
            )
        # Hard cap on summary + body combined regardless of kind so
        # an outlier doesn't break the total-body resolver budget.
        total_bytes = body_bytes + len(summary.encode("utf-8"))
        if total_bytes > _TOTAL_BODY_HARD_KIB * 1024:
            raise KnowledgeValidationError(
                f"combined summary+body for {self.record_id!r} is "
                f"{total_bytes} bytes; hard cap is "
                f"{_TOTAL_BODY_HARD_KIB} KiB.",
            )
        # Provenance MUST be populated. Audits need at least
        # ``created_at`` and ``created_by``.
        if self.provenance.created_at is None:
            raise KnowledgeValidationError(
                f"provenance.created_at is required for {self.record_id!r}",
            )
        if not self.provenance.created_by:
            raise KnowledgeValidationError(
                f"provenance.created_by is required for {self.record_id!r}",
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "kind": self.kind,
            "scope": self.scope,
            "scope_ref": self.scope_ref,
            "summary": self.summary,
            "body": self.body,
            "tags": list(self.tags),
            "applies_to": list(self.applies_to),
            "embeddings_ref": self.embeddings_ref,
            "provenance": self.provenance.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "KnowledgeRecord":
        return cls(
            record_id=str(data["record_id"]),
            kind=str(data["kind"]),  # type: ignore[arg-type]
            scope=str(data["scope"]),  # type: ignore[arg-type]
            scope_ref=str(data["scope_ref"]),
            summary=str(data.get("summary") or ""),
            body=str(data.get("body") or ""),
            tags=tuple(str(t) for t in (data.get("tags") or ())),
            applies_to=tuple(str(c) for c in (data.get("applies_to") or ())),
            embeddings_ref=str(data.get("embeddings_ref") or ""),
            provenance=KnowledgeProvenance.from_dict(
                data.get("provenance") if isinstance(data.get("provenance"), dict) else None,
            ),
        )


@dataclass(frozen=True, slots=True)
class EffectiveKnowledgeSet:
    """Per-request projection produced by the knowledge resolver
    (W6). Mirrors :class:`EffectiveSkillSet` so prompts render both
    families through the same channel.
    """

    records: tuple[KnowledgeRecord, ...] = ()
    snapshot_ref: str = ""
    truncated: bool = False
    """True when count / size caps dropped at least one otherwise-
    qualifying record."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "records": [r.to_dict() for r in self.records],
            "snapshot_ref": self.snapshot_ref,
            "truncated": self.truncated,
        }


__all__ = [
    "EFFECTIVE_KNOWLEDGE_COUNT_CAP",
    "EFFECTIVE_KNOWLEDGE_TOTAL_BODY_KIB",
    "EffectiveKnowledgeSet",
    "KnowledgeKind",
    "KnowledgeProvenance",
    "KnowledgeRecord",
    "KnowledgeScope",
    "KnowledgeValidationError",
    "kind_body_cap_kib",
]
