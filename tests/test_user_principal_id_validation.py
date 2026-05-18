"""ADR-027 ``assert_user_principal_id`` validation tests.

Cover the protocol-level helper that rejects ``system:``-prefixed
principal ids on user-facing write paths. Empty strings remain
tolerated as the documented "legacy plan" sentinel; everything else
is normalised (stripped).
"""
from __future__ import annotations

import pytest

from novie_protocol.contracts import (
    ReservedPrincipalNamespaceRejected,
    SYSTEM_PRINCIPAL_PREFIX,
    assert_user_principal_id,
    mint_system_principal_id,
)


def test_user_principal_id_passes_through_normalised() -> None:
    assert assert_user_principal_id("user-42") == "user-42"
    assert assert_user_principal_id("  user-42  ") == "user-42"


def test_empty_or_whitespace_returns_empty_string() -> None:
    """Empty principal_id is the documented legacy sentinel — must
    NOT raise (otherwise re-publishing pre-ADR-027 plans would 422)."""
    assert assert_user_principal_id("") == ""
    assert assert_user_principal_id("   ") == ""


def test_system_prefix_is_rejected() -> None:
    with pytest.raises(ReservedPrincipalNamespaceRejected) as exc_info:
        assert_user_principal_id("system:doctor")
    err = exc_info.value
    assert err.principal_id == "system:doctor"
    assert err.field == "principal_id"


def test_minted_system_principal_id_is_rejected() -> None:
    """End-to-end: anything ``mint_system_principal_id`` produces must
    be refused by the user-facing validator. Defends against a tenant
    re-using a system component name."""
    sys_id = mint_system_principal_id("doctor")
    assert sys_id.startswith(SYSTEM_PRINCIPAL_PREFIX)
    with pytest.raises(ReservedPrincipalNamespaceRejected):
        assert_user_principal_id(sys_id)


def test_field_arg_is_surfaced_in_error() -> None:
    """API validators pass field path so the 422 detail points at the
    JSON body location that violated the rule."""
    with pytest.raises(ReservedPrincipalNamespaceRejected) as exc_info:
        assert_user_principal_id(
            "system:doctor",
            field="body.plan.creator_principal_id",
        )
    err = exc_info.value
    assert err.field == "body.plan.creator_principal_id"
    assert "body.plan.creator_principal_id" in str(err)


def test_system_prefix_only_value_is_rejected() -> None:
    """``"system:"`` alone (no component) is malformed but still falls
    inside the reserved namespace; must reject."""
    with pytest.raises(ReservedPrincipalNamespaceRejected):
        assert_user_principal_id(SYSTEM_PRINCIPAL_PREFIX)


def test_whitespace_around_system_prefix_does_not_bypass_check() -> None:
    """Strip-then-check ordering: whitespace padding around a system
    id must NOT slip through. ``"  system:doctor  "`` strips to
    ``"system:doctor"``."""
    with pytest.raises(ReservedPrincipalNamespaceRejected):
        assert_user_principal_id("  system:doctor  ")


def test_substring_system_does_not_trigger() -> None:
    """Only the prefix is reserved. ``"user:system:42"`` and
    ``"my-system-account"`` must pass."""
    assert assert_user_principal_id("user:system:42") == "user:system:42"
    assert assert_user_principal_id("my-system-account") == "my-system-account"


def test_default_field_label_is_principal_id() -> None:
    with pytest.raises(ReservedPrincipalNamespaceRejected) as exc_info:
        assert_user_principal_id("system:cron")
    assert exc_info.value.field == "principal_id"
