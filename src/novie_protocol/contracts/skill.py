"""Skill contract — W1 of SKILL_TIERED_MANAGEMENT_BACKLOG.

Skills are versioned, scoped, markdown-bodied procedural guidance the
platform injects into Reception / Planner / agent prompts so callers
don't have to manually re-state preferences each turn. They live at
three nested scopes (organization / project / personal) and merge with
**personal > project > organization** precedence when a name collision
occurs.

The model is **storage-shape agnostic**: this file freezes the wire /
prompt contract; the in-memory + PG repositories (W2) implement
persistence; the resolver (W4) composes the merged
``EffectiveSkillSet``.

Size policy: a single skill body is capped at 16 KiB markdown (soft
warn at 8 KiB). A request that asks for a body > 64 KiB is rejected at
contract validation — past that point the prompt budget impact is
catastrophic.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal


# ── Scope + consumer enums ──────────────────────────────────────────


SkillScope = Literal["organization", "project", "personal"]
"""Three nested scopes a skill can live at. The resolver order is
``organization`` (broadest) → ``project`` → ``personal`` (narrowest);
on name collision the narrower scope wins."""


SkillConsumer = Literal["reception", "planner", "agents"]
"""Which prompt boundary the skill may be rendered into. A
Reception-only skill is filtered out of Planner / agent prompts even
if it is otherwise in-scope."""


# ── Soft + hard caps ────────────────────────────────────────────────


SKILL_BODY_SOFT_KIB: int = 8
SKILL_BODY_MAX_KIB: int = 16
SKILL_BODY_HARD_KIB: int = 64
"""Hard reject at 64 KiB — past that the prompt blow-up is unacceptable
even at the org tier. The 16 KiB cap is the documented limit; the 64
KiB rejection is the defence-in-depth fail-fast.
"""

EFFECTIVE_SKILL_COUNT_CAP: int = 8
EFFECTIVE_SKILL_TOTAL_BODY_KIB: int = 32
"""Per-consumer caps applied by the resolver. ``count_cap`` bounds the
number of skills rendered; ``total_body_kib`` bounds the cumulative
body size so a tenant with many small skills can't blow the prompt
budget either.
"""


class SkillValidationError(ValueError):
    """Raised when a :class:`Skill` payload violates the contract.

    Distinct from generic ``ValueError`` so callers (storage layer,
    HTTP boundary) can match it without false-positive-prone string
    inspection.
    """


# ── Records ─────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Skill:
    """A single procedural-guidance entry.

    The ``skill_id`` is a stable composite key. Convention:
      - ``org:<tenant_id>:<name>``
      - ``project:<project_id>:<name>``
      - ``user:<user_id>:<name>``
    The resolver relies on this prefix to recover the scope without
    having to re-look-up the row.

    ``etag`` is a content hash used by the optimistic-concurrency
    update path (W7 management API). Empty string means "no current
    revision" (newly constructed in-memory).
    """

    skill_id: str
    scope: SkillScope
    scope_ref: str
    """Tenant id, project id, or user id depending on scope."""

    name: str
    description: str
    body_markdown: str

    version: str = "1.0.0"
    tags: tuple[str, ...] = ()
    applies_to_capabilities: tuple[str, ...] = ()
    """Optional capability-id allow-list. Empty tuple == applies to
    every capability. The resolver still applies the per-consumer
    filter on top."""

    allowed_consumers: frozenset[SkillConsumer] = field(
        default_factory=lambda: frozenset({"reception", "planner", "agents"}),
    )

    created_by: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None
    etag: str = ""

    def __post_init__(self) -> None:
        if not self.skill_id:
            raise SkillValidationError("skill_id is required")
        if self.scope not in ("organization", "project", "personal"):
            raise SkillValidationError(
                f"invalid scope {self.scope!r}; must be organization | project | personal",
            )
        if not self.scope_ref:
            raise SkillValidationError(
                f"scope_ref is required for skill {self.skill_id!r}",
            )
        if not self.name:
            raise SkillValidationError("name is required")
        body_bytes = len(self.body_markdown.encode("utf-8"))
        if body_bytes > SKILL_BODY_HARD_KIB * 1024:
            raise SkillValidationError(
                f"skill body for {self.skill_id!r} is {body_bytes} bytes; "
                f"hard cap is {SKILL_BODY_HARD_KIB} KiB. Split the skill "
                f"or move detail into linked docs.",
            )
        if not self.allowed_consumers:
            raise SkillValidationError(
                f"allowed_consumers cannot be empty for {self.skill_id!r}; "
                f"omit the field to default to all three consumers.",
            )

    def body_oversized_warning(self) -> str | None:
        """Return a human-readable warning when the body exceeds the
        soft cap, else ``None``. Operators surface this in the
        management UI and CI without rejecting the row."""
        body_bytes = len(self.body_markdown.encode("utf-8"))
        if body_bytes > SKILL_BODY_MAX_KIB * 1024:
            return (
                f"skill body is {body_bytes} bytes — exceeds documented "
                f"{SKILL_BODY_MAX_KIB} KiB cap; storage will accept but "
                f"prompt budgets may suffer."
            )
        if body_bytes > SKILL_BODY_SOFT_KIB * 1024:
            return (
                f"skill body is {body_bytes} bytes — exceeds soft warn "
                f"threshold of {SKILL_BODY_SOFT_KIB} KiB; consider splitting."
            )
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "scope": self.scope,
            "scope_ref": self.scope_ref,
            "name": self.name,
            "description": self.description,
            "body_markdown": self.body_markdown,
            "version": self.version,
            "tags": list(self.tags),
            "applies_to_capabilities": list(self.applies_to_capabilities),
            "allowed_consumers": sorted(self.allowed_consumers),
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "etag": self.etag,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Skill":
        from datetime import datetime as _dt
        created_at_raw = data.get("created_at")
        updated_at_raw = data.get("updated_at")
        return cls(
            skill_id=str(data["skill_id"]),
            scope=str(data["scope"]),  # type: ignore[arg-type]
            scope_ref=str(data["scope_ref"]),
            name=str(data.get("name") or ""),
            description=str(data.get("description") or ""),
            body_markdown=str(data.get("body_markdown") or ""),
            version=str(data.get("version") or "1.0.0"),
            tags=tuple(str(t) for t in (data.get("tags") or ())),
            applies_to_capabilities=tuple(
                str(c) for c in (data.get("applies_to_capabilities") or ())
            ),
            allowed_consumers=frozenset(
                str(c) for c in (data.get("allowed_consumers") or ())  # type: ignore[misc]
            ) or frozenset({"reception", "planner", "agents"}),
            created_by=str(data.get("created_by") or ""),
            created_at=(
                _dt.fromisoformat(created_at_raw)
                if isinstance(created_at_raw, str) and created_at_raw
                else None
            ),
            updated_at=(
                _dt.fromisoformat(updated_at_raw)
                if isinstance(updated_at_raw, str) and updated_at_raw
                else None
            ),
            etag=str(data.get("etag") or ""),
        )


@dataclass(frozen=True, slots=True)
class EffectiveSkillSet:
    """Per-request projection produced by ``EffectiveSkillResolver``.

    ``skills`` is the merged, deduplicated set after the org → project
    → personal precedence has been applied AND the per-consumer filter
    + caps have been enforced. ``snapshot_ref`` is the content-hash
    that snapshot storage uses (W4.5).
    """

    consumer: SkillConsumer
    skills: tuple[Skill, ...] = ()
    snapshot_ref: str = ""
    truncated: bool = False
    """True when count / size caps dropped at least one skill that
    would have otherwise qualified."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "consumer": self.consumer,
            "skills": [s.to_dict() for s in self.skills],
            "snapshot_ref": self.snapshot_ref,
            "truncated": self.truncated,
        }


__all__ = [
    "EFFECTIVE_SKILL_COUNT_CAP",
    "EFFECTIVE_SKILL_TOTAL_BODY_KIB",
    "EffectiveSkillSet",
    "SKILL_BODY_HARD_KIB",
    "SKILL_BODY_MAX_KIB",
    "SKILL_BODY_SOFT_KIB",
    "Skill",
    "SkillConsumer",
    "SkillScope",
    "SkillValidationError",
]
