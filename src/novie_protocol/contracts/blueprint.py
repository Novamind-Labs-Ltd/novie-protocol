"""Project blueprint contract — W1 of PROJECT_BLUEPRINT_BACKLOG.

A blueprint is a **declarative, build-time-only** scaffolder:
- Applied at project create via ``POST /projects?from_blueprint=...``.
- Stamps a ``created_from_blueprint`` marker on the project.
- Plays NO runtime role — Reception / Planner never consult
  blueprints during a chat turn.

The schema is split into independently optional top-level sections
so a "blank" blueprint can be empty everywhere except ``id`` /
``name`` / ``version``. Each section maps to one downstream
subsystem (skill repo, agent catalog binding, tracker, etc.) the
applier (W3) knows how to invoke.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


class BlueprintValidationError(ValueError):
    """Raised when a blueprint payload violates the schema."""


# ── Sub-shapes ───────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class BlueprintDefaults:
    """Project-level defaults the applier writes into the project's
    metadata. ``effective_template_id`` / ``effective_view_hint`` /
    ``governance_policy_ref`` are the canonical knobs the existing
    ``_derive_effective_context`` consumes."""

    effective_template_id: str = ""
    effective_view_hint: str = ""
    governance_policy_ref: str = ""
    capability_policy_ref: str = ""
    tracker_binding: str = ""


@dataclass(frozen=True, slots=True)
class BlueprintKnowledgeSeed:
    """One knowledge entry the applier ingests at project create."""

    source: str
    """Free-form source identifier (URL, file path, etc.)."""

    namespace_alias: str = ""
    """Optional alias used by the project's effective_context."""


@dataclass(frozen=True, slots=True)
class BlueprintTracker:
    """Tracker initial state — lanes + default issue template."""

    lanes: tuple[str, ...] = ()
    default_issue_template: str = "user_story"


@dataclass(frozen=True, slots=True)
class BlueprintIssue:
    """One starter issue the applier creates after project setup.

    Fields are deliberately a shallow subset of the PMS issue create
    payload — real PMS field coverage lands when the PMS integration
    is unmocked. ``extra`` lets callers smuggle PMS-specific fields
    without forcing a contract bump.
    """

    title: str
    description: str = ""
    lane: str = ""
    template: str = ""
    labels: tuple[str, ...] = ()
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class BlueprintCapabilityBindings:
    """Capability ids the applier enables / disables on the new
    project. The applier rejects ids that overlap (an id can't be in
    both ``enabled`` and ``disabled`` at the same time)."""

    enabled: tuple[str, ...] = ()
    disabled: tuple[str, ...] = ()


BlueprintMode = Literal["frozen", "evolving"]
"""``frozen`` (default v1) — applied once at create, never re-applied.
``evolving`` is reserved for a future revision; v1 applier rejects
non-frozen modes for safety."""


# ── Top-level dataclass ──────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ProjectBlueprint:
    """The declarative blueprint shape consumed by the applier.

    Validation rules (enforced in ``__post_init__``):
    - ``id`` and ``name`` non-empty.
    - ``version`` semver-shaped (``X.Y.Z`` with non-negative ints).
    - No capability id in both ``capability_bindings.enabled`` and
      ``capability_bindings.disabled``.
    - ``starter_issues`` cannot reference a lane not declared in
      ``tracker.lanes`` (when the lanes section is non-empty).
    """

    id: str
    name: str
    version: str = "1.0.0"
    description: str = ""
    mode: BlueprintMode = "frozen"

    defaults: BlueprintDefaults = field(default_factory=BlueprintDefaults)
    agents_enabled: tuple[str, ...] = ()
    skills_enabled: tuple[str, ...] = ()
    knowledge_seeds: tuple[BlueprintKnowledgeSeed, ...] = ()
    tracker: BlueprintTracker = field(default_factory=BlueprintTracker)
    starter_issues: tuple[BlueprintIssue, ...] = ()
    capability_bindings: BlueprintCapabilityBindings = field(
        default_factory=BlueprintCapabilityBindings,
    )

    def __post_init__(self) -> None:
        if not self.id:
            raise BlueprintValidationError("id is required")
        if not self.name:
            raise BlueprintValidationError(f"name is required for blueprint {self.id!r}")
        _validate_semver(self.version, blueprint_id=self.id)
        if self.mode not in ("frozen", "evolving"):
            raise BlueprintValidationError(
                f"invalid mode {self.mode!r} for blueprint {self.id!r}; "
                f"must be 'frozen' or 'evolving'",
            )
        overlap = (
            set(self.capability_bindings.enabled)
            & set(self.capability_bindings.disabled)
        )
        if overlap:
            raise BlueprintValidationError(
                f"capability_bindings.enabled and .disabled overlap on "
                f"{sorted(overlap)} in blueprint {self.id!r}",
            )
        if self.tracker.lanes:
            allowed_lanes = set(self.tracker.lanes)
            for issue in self.starter_issues:
                if issue.lane and issue.lane not in allowed_lanes:
                    raise BlueprintValidationError(
                        f"starter_issue {issue.title!r} references lane "
                        f"{issue.lane!r} not declared in tracker.lanes "
                        f"{sorted(allowed_lanes)} (blueprint {self.id!r})",
                    )

    @property
    def summary(self) -> "BlueprintSummary":
        return BlueprintSummary(
            id=self.id,
            name=self.name,
            version=self.version,
            description=self.description,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProjectBlueprint":
        if not isinstance(data, dict):
            raise BlueprintValidationError("blueprint payload must be a mapping")
        defaults_raw = data.get("defaults") or {}
        if not isinstance(defaults_raw, dict):
            raise BlueprintValidationError("defaults must be a mapping")
        tracker_raw = data.get("tracker") or {}
        if not isinstance(tracker_raw, dict):
            raise BlueprintValidationError("tracker must be a mapping")
        bindings_raw = data.get("capability_bindings") or {}
        if not isinstance(bindings_raw, dict):
            raise BlueprintValidationError("capability_bindings must be a mapping")
        return cls(
            id=str(data["id"]),
            name=str(data["name"]),
            version=str(data.get("version") or "1.0.0"),
            description=str(data.get("description") or ""),
            mode=str(data.get("mode") or "frozen"),  # type: ignore[arg-type]
            defaults=BlueprintDefaults(
                effective_template_id=str(defaults_raw.get("effective_template_id") or ""),
                effective_view_hint=str(defaults_raw.get("effective_view_hint") or ""),
                governance_policy_ref=str(defaults_raw.get("governance_policy_ref") or ""),
                capability_policy_ref=str(defaults_raw.get("capability_policy_ref") or ""),
                tracker_binding=str(defaults_raw.get("tracker_binding") or ""),
            ),
            agents_enabled=tuple(str(c) for c in (data.get("agents_enabled") or ())),
            skills_enabled=tuple(str(s) for s in (data.get("skills_enabled") or ())),
            knowledge_seeds=tuple(
                BlueprintKnowledgeSeed(
                    source=str(k.get("source") or ""),
                    namespace_alias=str(k.get("namespace_alias") or ""),
                )
                for k in (data.get("knowledge_seeds") or ())
                if isinstance(k, dict) and k.get("source")
            ),
            tracker=BlueprintTracker(
                lanes=tuple(str(l) for l in (tracker_raw.get("lanes") or ())),
                default_issue_template=str(
                    tracker_raw.get("default_issue_template") or "user_story",
                ),
            ),
            starter_issues=tuple(
                BlueprintIssue(
                    title=str(i.get("title") or ""),
                    description=str(i.get("description") or ""),
                    lane=str(i.get("lane") or ""),
                    template=str(i.get("template") or ""),
                    labels=tuple(str(l) for l in (i.get("labels") or ())),
                    extra={
                        k: v for k, v in i.items()
                        if k not in {"title", "description", "lane", "template", "labels"}
                    },
                )
                for i in (data.get("starter_issues") or ())
                if isinstance(i, dict)
            ),
            capability_bindings=BlueprintCapabilityBindings(
                enabled=tuple(str(c) for c in (bindings_raw.get("enabled") or ())),
                disabled=tuple(str(c) for c in (bindings_raw.get("disabled") or ())),
            ),
        )


@dataclass(frozen=True, slots=True)
class BlueprintSummary:
    """Compact record returned by ``BlueprintRegistry.list()``."""

    id: str
    name: str
    version: str
    description: str = ""


def _validate_semver(version: str, *, blueprint_id: str) -> None:
    parts = version.split(".")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        raise BlueprintValidationError(
            f"version {version!r} is not semver (X.Y.Z) for blueprint "
            f"{blueprint_id!r}",
        )


__all__ = [
    "BlueprintCapabilityBindings",
    "BlueprintDefaults",
    "BlueprintIssue",
    "BlueprintKnowledgeSeed",
    "BlueprintMode",
    "BlueprintSummary",
    "BlueprintTracker",
    "BlueprintValidationError",
    "ProjectBlueprint",
]
