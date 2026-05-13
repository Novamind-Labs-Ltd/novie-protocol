# ruff: noqa: RUF002, RUF003
"""PMS Workbench canonical contracts (agent-facing, PMS-implementation agnostic).

Phase 0 / Wave 0 contract freeze for the agentic→platform migration.

This module owns the *canonical* shapes that platform capabilities expose to
agents. They are deliberately decoupled from:

- `pms_lifecycle.PmsIssueSnapshot` — a wider workflow input snapshot used by
  the ticket-execution path; it carries fields like ``acceptance_criteria``,
  ``target_repo``, ``blocked_by`` that are execution-only concerns.
- The mock PMS HTTP DTOs (``apps/agentic-beta/apps/mock_pms/...``) — those are
  storage-shaped and may add or rename fields without breaking agents.
- The real PMS internal REST DTOs exposed by
  ``apps/project-management-service/src/Api/...`` — those follow .NET / EF
  naming and may evolve independently.

Adapters (``MockPmsIssueAdapter``, ``RealPmsIssueAdapter``) are responsible
for mapping their respective transport DTOs into the types defined here.
Capability handlers should never touch transport-shaped types.

Decisions (2026-05-10):

- ``status.stage`` is the **primary** semantic match for routing decisions
  (execution-eligible / human-review / done / canceled). ``status.title`` is
  only used as a disambiguator when one stage maps to multiple titles or when
  a PMS deployment lacks standard stages.
- ``StatusMapping`` is configured at workspace scope with optional per-project
  overrides; project overrides *merge* with the workspace default rather than
  replacing it.
- ``trigger_coding`` is intentionally **not** a capability. Issue execution is
  driven asynchronously by the PMS Todo poller, never synchronously from a
  ``move`` capability.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

# ---------------------------------------------------------------------------
# Status primitives
# ---------------------------------------------------------------------------

PmsIssueStage = Literal[
    "unstarted",   # Backlog / Todo (not yet running)
    "started",     # In Progress / any active stage
    "completed",   # Done
    "canceled",    # Canceled
]
"""Stable semantic stage. Adapters MUST map every PMS title into one of these
four values. Routing decisions prefer this field.

If a PMS deployment exposes its own stage enum, adapters should map it
directly. If only titles are exposed, adapters should derive stage from the
title using the active ``StatusMapping``.
"""


@dataclass(frozen=True, slots=True)
class PmsIssueStatus:
    """Structured issue status: localized title + stable stage.

    ``title`` is what the user sees in the PMS UI (may be customized,
    localized, or differ between projects). ``stage`` is the platform's stable
    routing key. Capabilities should match on ``stage`` whenever possible.
    """

    title: str
    stage: PmsIssueStage


# ---------------------------------------------------------------------------
# Reference shapes (small structured pointers, not full entities)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PmsProjectRef:
    """Pointer to a PMS project. Title is denormalized for display."""

    id: str
    title: str = ""
    identifier: str = ""  # short slug, e.g. "NOV"


@dataclass(frozen=True, slots=True)
class PmsAssigneeRef:
    """Pointer to a member assigned to an issue."""

    id: str
    name: str = ""
    email: str = ""


@dataclass(frozen=True, slots=True)
class PmsCycleRef:
    """Pointer to a sprint / cycle. ``number`` is the cycle ordinal in the
    project; ``title`` is optional human label."""

    id: str
    number: int = 0
    title: str = ""


# ---------------------------------------------------------------------------
# Canonical issue read shape
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PmsIssue:
    """Canonical, agent-facing PMS issue.

    Adapters MUST populate this from their transport-specific shapes. Agents
    and capability handlers MUST NOT bypass this DTO to read transport fields
    directly — that would couple them to PMS deployment specifics.

    The shape matches the ``Minimum canonical issue shape`` declared in
    ``docs/plans/2026-05-08-pms-workbench-capability-todo.md``. New optional
    fields may be added; renames or removals require a versioned capability.
    """

    id: str
    identifier: str
    title: str
    description: str
    status: PmsIssueStatus
    project: PmsProjectRef
    tenant_id: str
    workspace_id: str
    priority: int = 3
    labels: tuple[str, ...] = ()
    assignee: PmsAssigneeRef | None = None
    cycle: PmsCycleRef | None = None
    branch_name: str | None = None
    linked_pull_request_urls: tuple[str, ...] = ()
    created_at: str = ""
    updated_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.labels, tuple):
            object.__setattr__(self, "labels", tuple(self.labels))
        if not isinstance(self.linked_pull_request_urls, tuple):
            object.__setattr__(
                self,
                "linked_pull_request_urls",
                tuple(self.linked_pull_request_urls),
            )


# ---------------------------------------------------------------------------
# Canonical issue write shapes
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PmsIssueDraft:
    """Input for ``platform.pms.issue.create``.

    Distinct from ``ticket_drafts.TicketDraft``:
    - ``TicketDraft`` is splitter-output, set-scoped, with cross-draft
      references (``blocked_by`` / ``depends_on`` by ``draft_key``).
    - ``PmsIssueDraft`` is a single-issue create payload, addressed by real
      PMS identifiers (``project_id``, ``parent_id``).

    ``TicketDraftIngestionService`` is responsible for converting a
    ``TicketDraftSet`` into a sequence of ``PmsIssueDraft`` writes.
    """

    project_id: str
    title: str
    description: str = ""
    initial_status_title: str | None = None  # default: PMS "Backlog"
    priority: int = 3
    labels: tuple[str, ...] = ()
    assignee_id: str | None = None
    cycle_id: str | None = None
    parent_id: str | None = None
    branch_name: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.labels, tuple):
            object.__setattr__(self, "labels", tuple(self.labels))


@dataclass(frozen=True, slots=True)
class PmsIssueUpdate:
    """Input for ``platform.pms.issue.update``.

    Partial-update semantics: only fields explicitly provided are applied.
    ``None`` means "do not change this field" — to clear a value, adapters
    should expose dedicated capabilities (e.g. ``unset_assignee``) rather than
    overload ``None``.

    Status changes go through ``platform.pms.issue.update_status`` and use
    ``PmsIssueStatusChange``, not this type.
    """

    issue_id: str
    title: str | None = None
    description: str | None = None
    priority: int | None = None
    labels: tuple[str, ...] | None = None
    assignee_id: str | None = None
    cycle_id: str | None = None
    metadata: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.labels is not None and not isinstance(self.labels, tuple):
            object.__setattr__(self, "labels", tuple(self.labels))


@dataclass(frozen=True, slots=True)
class PmsIssueStatusChange:
    """Input for ``platform.pms.issue.update_status``.

    ``target_status_title`` is the PMS-deployment-specific title (e.g. "Todo",
    "Ready to Code"). ``target_stage`` is the canonical stage; adapters MAY
    accept either form. When both are provided, ``target_status_title`` wins
    (operator intent is more specific than stage).

    ``suppress_notifications`` mirrors the ``/internal/issues/{id}/status``
    PMS knob and lets background jobs avoid spamming watchers.
    """

    issue_id: str
    target_status_title: str | None = None
    target_stage: PmsIssueStage | None = None
    suppress_notifications: bool = False
    reason: str = ""

    def __post_init__(self) -> None:
        if self.target_status_title is None and self.target_stage is None:
            raise ValueError(
                "PmsIssueStatusChange requires either target_status_title or "
                "target_stage"
            )


# ---------------------------------------------------------------------------
# Comments and links
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PmsIssueComment:
    """Body for ``platform.pms.issue.comment.add`` and the read shape returned
    by comment list capabilities.

    ``author_id`` is the upstream-authenticated principal id; agents MUST NOT
    self-report this — it is filled from authenticated context by the
    capability boundary. Free-form ``author_name`` is informational only.
    """

    body: str
    author_id: str = ""
    author_name: str = ""
    comment_id: str = ""           # filled on read; empty on write
    created_at: str = ""           # filled on read; empty on write
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PmsIssueLink:
    """A link attached to an issue (URL bookmark, related-doc, dashboard).

    NOT to be confused with ``pms_lifecycle.PmsExecutionLink`` (that one is
    the platform-side issue↔workflow lease). Use ``PmsIssueLink`` for
    user-visible attachments only.
    """

    title: str
    url: str
    link_id: str = ""              # filled on read; empty on write
    created_at: str = ""           # filled on read; empty on write
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Status mapping configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StatusMapping:
    """Resolves PMS titles ↔ canonical stages for a given scope.

    Scope precedence: workspace default → per-project overrides. Overrides
    *merge* (union of titles, last-writer-wins on stage assignment) rather
    than replace.

    The runtime wires this into the workbench adapter; capabilities query it
    only indirectly (through ``adapter.normalize_status(title)``).
    """

    # Stage-first matchers — the primary routing key.
    execution_eligible_stages: tuple[PmsIssueStage, ...] = ("started",)
    human_review_stages: tuple[PmsIssueStage, ...] = ()  # PMS rarely exposes
    done_stages: tuple[PmsIssueStage, ...] = ("completed",)
    canceled_stages: tuple[PmsIssueStage, ...] = ("canceled",)

    # Title-based disambiguators / fallbacks. Used when stages alone are
    # insufficient (e.g. PMS has no "started" subdivision but uses "Todo" vs
    # "In Progress" titles within the same stage).
    execution_eligible_titles: tuple[str, ...] = ("Todo",)
    human_review_titles: tuple[str, ...] = ("Human Review",)
    done_titles: tuple[str, ...] = ("Done",)
    canceled_titles: tuple[str, ...] = ("Canceled",)

    def __post_init__(self) -> None:
        for name in (
            "execution_eligible_stages",
            "human_review_stages",
            "done_stages",
            "canceled_stages",
            "execution_eligible_titles",
            "human_review_titles",
            "done_titles",
            "canceled_titles",
        ):
            value = getattr(self, name)
            if not isinstance(value, tuple):
                object.__setattr__(self, name, tuple(value))

    def merge_override(self, override: StatusMapping) -> StatusMapping:
        """Apply a per-project override on top of self (workspace default).

        Union semantics: titles and stages from the override are added to the
        defaults rather than replacing them. To narrow rather than widen, the
        runtime should construct a fresh ``StatusMapping`` instead.
        """
        return StatusMapping(
            execution_eligible_stages=_merge_unique(
                self.execution_eligible_stages,
                override.execution_eligible_stages,
            ),
            human_review_stages=_merge_unique(
                self.human_review_stages, override.human_review_stages
            ),
            done_stages=_merge_unique(self.done_stages, override.done_stages),
            canceled_stages=_merge_unique(
                self.canceled_stages, override.canceled_stages
            ),
            execution_eligible_titles=_merge_unique(
                self.execution_eligible_titles,
                override.execution_eligible_titles,
            ),
            human_review_titles=_merge_unique(
                self.human_review_titles, override.human_review_titles
            ),
            done_titles=_merge_unique(self.done_titles, override.done_titles),
            canceled_titles=_merge_unique(
                self.canceled_titles, override.canceled_titles
            ),
        )

    def is_execution_eligible(self, status: PmsIssueStatus) -> bool:
        return self._matches(
            status,
            self.execution_eligible_stages,
            self.execution_eligible_titles,
        )

    def is_human_review(self, status: PmsIssueStatus) -> bool:
        return self._matches(
            status, self.human_review_stages, self.human_review_titles
        )

    def is_done(self, status: PmsIssueStatus) -> bool:
        return self._matches(status, self.done_stages, self.done_titles)

    def is_canceled(self, status: PmsIssueStatus) -> bool:
        return self._matches(status, self.canceled_stages, self.canceled_titles)

    @staticmethod
    def _matches(
        status: PmsIssueStatus,
        stages: tuple[PmsIssueStage, ...],
        titles: tuple[str, ...],
    ) -> bool:
        # Stage-first: if the stage matches, accept regardless of title. This
        # is the cheap path for PMS deployments that expose stable stages.
        if status.stage in stages:
            return True
        # Title fallback: only consult when stage didn't match. Allows
        # disambiguating multi-title stages or PMS deployments without stages.
        return status.title in titles


def _merge_unique(left: tuple[Any, ...], right: tuple[Any, ...]) -> tuple[Any, ...]:
    """Union preserving order: items from ``left`` first, then new items from
    ``right`` not already present."""
    seen = set(left)
    extra = tuple(item for item in right if item not in seen)
    return left + extra


# ---------------------------------------------------------------------------
# Mapping helpers
# ---------------------------------------------------------------------------

# Default title→stage table for PMS deployments that ship the standard six
# states (``Backlog``, ``Todo``, ``In Progress``, ``Human Review``, ``Done``,
# ``Cancelled``). Adapters serving non-standard PMS deployments should
# construct their own table and pass it to ``stage_for_title``.
DEFAULT_TITLE_TO_STAGE: dict[str, PmsIssueStage] = {
    "Backlog": "unstarted",
    "Todo": "unstarted",
    "Ready to Code": "unstarted",
    "In Progress": "started",
    "Human Review": "started",  # still "running" from a workflow standpoint
    "Done": "completed",
    "Cancelled": "canceled",
    "Canceled": "canceled",  # American spelling tolerated
}


def stage_for_title(
    title: str,
    *,
    table: dict[str, PmsIssueStage] | None = None,
    default: PmsIssueStage = "unstarted",
) -> PmsIssueStage:
    """Best-effort title → stage resolver for adapters that only see titles.

    Real PMS deployments should expose ``stage`` directly on every issue
    response; this helper exists for the mock PMS and for legacy code paths
    that haven't been updated.
    """
    return (table or DEFAULT_TITLE_TO_STAGE).get(title, default)
