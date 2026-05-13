"""W2 of CHAT_CONTEXT_ATTACHMENTS — ChatContextSource contract tests."""
# ruff: noqa: I001
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from novie_protocol.contracts import (
    ArtifactRefContextSource,
    ChatContextSourceValidationError,
    EphemeralUploadContextSource,
    RunContextSource,
    SessionContextSource,
    UserPinnedContextSource,
    chat_context_source_from_dict,
)


# ── Validation per kind ─────────────────────────────────────────────


def test_ephemeral_upload_requires_attachment_id() -> None:
    with pytest.raises(ChatContextSourceValidationError, match="attachment_id"):
        EphemeralUploadContextSource()


def test_artifact_ref_requires_artifact_id() -> None:
    with pytest.raises(ChatContextSourceValidationError, match="artifact_id"):
        ArtifactRefContextSource()


def test_session_requires_session_id() -> None:
    with pytest.raises(ChatContextSourceValidationError, match="session_id"):
        SessionContextSource()


def test_run_requires_run_id() -> None:
    with pytest.raises(ChatContextSourceValidationError, match="run_id"):
        RunContextSource()


def test_user_pinned_requires_pin_id() -> None:
    with pytest.raises(ChatContextSourceValidationError, match="pin_id"):
        UserPinnedContextSource()


# ── Discriminator-driven factory ────────────────────────────────────


def test_from_dict_dispatches_to_correct_kind() -> None:
    src = chat_context_source_from_dict({
        "kind": "ephemeral_upload",
        "attachment_id": "att-1",
        "filename": "notes.md",
        "content_type": "text/markdown",
        "size_bytes": 1024,
    })
    assert isinstance(src, EphemeralUploadContextSource)
    assert src.filename == "notes.md"


def test_from_dict_round_trips_iso_timestamps() -> None:
    src = chat_context_source_from_dict({
        "kind": "ephemeral_upload",
        "attachment_id": "att-2",
        "filename": "x",
        "uploaded_at": "2026-05-11T12:00:00+00:00",
        "expires_at": "2026-05-11T13:00:00+00:00",
    })
    assert isinstance(src, EphemeralUploadContextSource)
    assert src.uploaded_at == datetime(2026, 5, 11, 12, tzinfo=UTC)
    assert src.expires_at == datetime(2026, 5, 11, 13, tzinfo=UTC)


def test_from_dict_unknown_kind_rejected() -> None:
    with pytest.raises(ChatContextSourceValidationError, match="unknown chat context"):
        chat_context_source_from_dict({
            "kind": "screenshot",  # not in the closed set
            "id": "x",
        })


def test_from_dict_ignores_unknown_fields() -> None:
    """Forward-compat: wire payloads carrying a future field should
    not break old code paths — drop the unknown key silently."""
    src = chat_context_source_from_dict({
        "kind": "session",
        "session_id": "s-1",
        "summary": "Recent session.",
        "future_field": "ignored",
    })
    assert isinstance(src, SessionContextSource)
    assert src.session_id == "s-1"


def test_kind_discriminator_locked() -> None:
    """The Literal discriminator on each class is the wire contract.
    Lock the values so a typo can't slip in unnoticed."""
    assert EphemeralUploadContextSource(attachment_id="x").kind == "ephemeral_upload"
    assert ArtifactRefContextSource(artifact_id="x").kind == "artifact_ref"
    assert SessionContextSource(session_id="x").kind == "session"
    assert RunContextSource(run_id="x").kind == "run"
    assert UserPinnedContextSource(pin_id="x").kind == "user_pinned"
