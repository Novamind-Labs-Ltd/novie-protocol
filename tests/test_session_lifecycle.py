"""ADR-027: SessionLifecycleState + system ephemeral session helpers.

Locks the Phase-1 schema additions:

- ``SessionLifecycleState`` is the closed enum ADR-027 specifies.
- ``Session.lifecycle_state`` defaults to ``active``; the field is
  orthogonal to the operational ``status``.
- Default TTL constants match the ADR-027 spec (30 min / 7 days / 90 days).
- Transition table allows the six documented edges and forbids the
  illegal ``closed → active`` resurrection (clone-instead invariant).
- ``mint_system_session_id`` / ``mint_system_principal_id`` produce
  ids in the reserved ``system:`` namespace; ``is_system_*`` helpers
  recognise them.
"""
# ruff: noqa: RUF002, RUF003
from __future__ import annotations

import dataclasses
from datetime import datetime, timezone

import pytest

from novie_protocol.contracts import (
    DEFAULT_ACTIVE_IDLE_TTL_SECONDS,
    DEFAULT_CLOSED_ARCHIVE_TTL_SECONDS,
    DEFAULT_IDLE_ARCHIVE_TTL_SECONDS,
    LIFECYCLE_TRANSITIONS,
    SYSTEM_PRINCIPAL_PREFIX,
    SYSTEM_SESSION_PREFIX,
    Session,
    SessionLifecycleState,
    is_legal_lifecycle_transition,
    is_system_principal,
    is_system_session,
    mint_system_principal_id,
    mint_system_session_id,
)


def _now() -> datetime:
    return datetime(2026, 5, 16, 12, 0, 0, tzinfo=timezone.utc)


# ── Session field shape ────────────────────────────────────────────


def test_session_lifecycle_state_defaults_to_active() -> None:
    s = Session(
        session_id="sess-1",
        tenant_id="t",
        workspace_id="w",
        created_at=_now(),
        updated_at=_now(),
    )
    assert s.lifecycle_state == "active"


def test_session_lifecycle_state_is_orthogonal_to_status() -> None:
    """``status`` (operational) and ``lifecycle_state`` (custody) move
    independently. A session can be ``waiting`` (HITL gate pending) yet
    still ``active`` in custody."""
    s = Session(
        session_id="sess-1",
        tenant_id="t",
        workspace_id="w",
        created_at=_now(),
        updated_at=_now(),
        status="waiting",
        lifecycle_state="active",
    )
    assert s.status == "waiting"
    assert s.lifecycle_state == "active"


def test_session_lifecycle_state_accepts_all_four_values() -> None:
    for state in ("active", "idle", "closed", "archived"):
        s = Session(
            session_id="x",
            tenant_id="t",
            workspace_id="w",
            created_at=_now(),
            updated_at=_now(),
            lifecycle_state=state,  # type: ignore[arg-type]
        )
        assert s.lifecycle_state == state


def test_session_is_still_frozen() -> None:
    s = Session(
        session_id="x",
        tenant_id="t",
        workspace_id="w",
        created_at=_now(),
        updated_at=_now(),
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        s.lifecycle_state = "idle"  # type: ignore[misc]


# ── TTL defaults ───────────────────────────────────────────────────


def test_default_ttls_match_adr_027_spec() -> None:
    """ADR-027 lists 30 min / 7 days / 90 days as the canonical defaults."""
    assert DEFAULT_ACTIVE_IDLE_TTL_SECONDS == 30 * 60
    assert DEFAULT_IDLE_ARCHIVE_TTL_SECONDS == 7 * 24 * 3600
    assert DEFAULT_CLOSED_ARCHIVE_TTL_SECONDS == 90 * 24 * 3600


# ── Lifecycle transitions ──────────────────────────────────────────


def test_legal_transitions_match_adr_027() -> None:
    """The transition table is the canonical reference. Adding or
    removing an edge requires an ADR amendment."""
    assert LIFECYCLE_TRANSITIONS == frozenset(
        {
            ("active", "idle"),
            ("idle", "active"),
            ("idle", "archived"),
            ("active", "closed"),
            ("closed", "archived"),
        }
    )


@pytest.mark.parametrize(
    "src,dst",
    [
        ("active", "idle"),
        ("idle", "active"),
        ("idle", "archived"),
        ("active", "closed"),
        ("closed", "archived"),
    ],
)
def test_legal_transitions_pass_helper_check(
    src: SessionLifecycleState, dst: SessionLifecycleState,
) -> None:
    assert is_legal_lifecycle_transition(src, dst)


@pytest.mark.parametrize(
    "src,dst",
    [
        ("closed", "active"),       # CRITICAL — no resurrection (clone instead)
        ("closed", "idle"),
        ("archived", "active"),
        ("archived", "idle"),
        ("archived", "closed"),
        ("active", "archived"),     # must go via idle or closed first
    ],
)
def test_illegal_transitions_rejected_by_helper(
    src: SessionLifecycleState, dst: SessionLifecycleState,
) -> None:
    assert not is_legal_lifecycle_transition(src, dst)


@pytest.mark.parametrize(
    "state",
    ["active", "idle", "closed", "archived"],
)
def test_self_transition_is_legal_no_op(
    state: SessionLifecycleState,
) -> None:
    """The cleanup job may re-write the same state as a heartbeat; this
    must not raise. Distinct from a true transition."""
    assert is_legal_lifecycle_transition(state, state)


def test_closed_to_active_is_explicitly_forbidden() -> None:
    """ADR-027 calls out ``closed → active`` resurrection as the canonical
    illegal transition: user must clone history into a new session, not
    revive the old one. Lock this with its own test name so a regression
    is impossible to overlook."""
    assert not is_legal_lifecycle_transition("closed", "active")


# ── System ephemeral session ───────────────────────────────────────


def test_mint_system_session_id_has_namespace_prefix() -> None:
    sid = mint_system_session_id("doctor", "run-001")
    assert sid.startswith(SYSTEM_SESSION_PREFIX)
    assert "doctor" in sid
    assert "run-001" in sid


def test_mint_system_session_id_rejects_empty_inputs() -> None:
    with pytest.raises(ValueError, match="task_name"):
        mint_system_session_id("", "run-1")
    with pytest.raises(ValueError, match="run_id"):
        mint_system_session_id("doctor", "")


def test_is_system_session_matches_mint() -> None:
    sid = mint_system_session_id("self_heal", "abc")
    assert is_system_session(sid)
    assert not is_system_session("sess-real-user-thread")


def test_mint_system_principal_id_has_namespace_prefix() -> None:
    pid = mint_system_principal_id("doctor")
    assert pid.startswith(SYSTEM_PRINCIPAL_PREFIX)
    assert pid == "system:doctor"


def test_mint_system_principal_id_rejects_empty() -> None:
    with pytest.raises(ValueError, match="component"):
        mint_system_principal_id("")


def test_is_system_principal_distinguishes_platform_from_tenant_users() -> None:
    """The platform must be able to refuse tenant-side registration of
    any principal id in the ``system:`` namespace. ``is_system_principal``
    is the canonical reference for that check."""
    assert is_system_principal(mint_system_principal_id("doctor"))
    assert is_system_principal("system:cron")
    assert not is_system_principal("user-12345")
    assert not is_system_principal("svc-account-xyz")
    assert not is_system_principal("")


def test_system_session_id_shape_is_two_segments_after_prefix() -> None:
    """Lock the shape ``system:<task>:<run>`` so audit / billing rollup
    can split deterministically. (Not a hard contract test against
    arbitrary callers — minted ids are predictable; user-provided ids
    are out of scope.)"""
    sid = mint_system_session_id("doctor", "run-42")
    rest = sid[len(SYSTEM_SESSION_PREFIX):]
    assert rest.count(":") == 1
    task, run = rest.split(":", 1)
    assert task == "doctor"
    assert run == "run-42"


# ── Cross-check ───────────────────────────────────────────────────


def test_system_session_and_principal_namespaces_are_distinct_concepts() -> None:
    """Both reserve the ``system:`` prefix but at different layers:
    session ids identify chat threads, principal ids identify actors.
    Asserting both prefixes are equal locks the convention without
    collapsing the concepts."""
    assert SYSTEM_SESSION_PREFIX == SYSTEM_PRINCIPAL_PREFIX
    # But the helpers operate on disjoint inputs (session id vs principal id);
    # callers should not pass one shape to the other helper.
