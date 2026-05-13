"""Chat context source contracts — W2 of
CHAT_CONTEXT_ATTACHMENTS_AND_SESSION_HISTORY_BACKLOG.

A ``ChatContextSource`` is a typed reference the chatbox attaches
to a user message. Sources are kept as **references** (id +
metadata) instead of inlining file content; the
``ChatContextAssembler`` (W4) resolves each ref to bounded text
later, before the prompt is rendered.

Five concrete source types ship in v1. Each carries the **minimum
information needed to resolve later** — Reception / Planner /
agent SDK never see the raw bytes via this contract, only the
typed ref.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal


ChatContextSourceKind = Literal[
    "ephemeral_upload",
    "artifact_ref",
    "session",
    "run",
    "user_pinned",
]


class ChatContextSourceValidationError(ValueError):
    """Raised when a chat context source payload violates the contract."""


@dataclass(frozen=True, slots=True)
class EphemeralUploadContextSource:
    """A short-lived file uploaded through the chatbox (W3 store).

    The actual bytes live in :class:`TemporaryAttachmentStore`;
    this record carries only the lookup id + the metadata the UI
    needs to render the attachment chip."""

    kind: Literal["ephemeral_upload"] = "ephemeral_upload"
    attachment_id: str = ""
    filename: str = ""
    content_type: str = ""
    size_bytes: int = 0
    uploaded_at: datetime | None = None
    expires_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.attachment_id:
            raise ChatContextSourceValidationError(
                "attachment_id is required for ephemeral_upload source",
            )


@dataclass(frozen=True, slots=True)
class ArtifactRefContextSource:
    """Reference to a durable artifact previously produced by a
    workflow / agent run. Used by ``@artifact`` mentions (W6) and
    by explicit promotion of an upload to a long-term artifact (W7).
    """

    kind: Literal["artifact_ref"] = "artifact_ref"
    artifact_id: str = ""
    summary: str = ""
    """Short prose describing the artifact (renders in the UI chip)."""

    artifact_type: str = ""

    def __post_init__(self) -> None:
        if not self.artifact_id:
            raise ChatContextSourceValidationError(
                "artifact_id is required for artifact_ref source",
            )


@dataclass(frozen=True, slots=True)
class SessionContextSource:
    """Reference to another session in the same tenant/workspace.
    The assembler renders the session's most-recent transcript /
    summary as bounded context."""

    kind: Literal["session"] = "session"
    session_id: str = ""
    summary: str = ""

    def __post_init__(self) -> None:
        if not self.session_id:
            raise ChatContextSourceValidationError(
                "session_id is required for session source",
            )


@dataclass(frozen=True, slots=True)
class RunContextSource:
    """Reference to a specific workflow run. The assembler can
    render the run's final output + key step summaries."""

    kind: Literal["run"] = "run"
    run_id: str = ""
    summary: str = ""

    def __post_init__(self) -> None:
        if not self.run_id:
            raise ChatContextSourceValidationError(
                "run_id is required for run source",
            )


@dataclass(frozen=True, slots=True)
class UserPinnedContextSource:
    """Free-form user-supplied note pinned to the chat. Reception
    keeps the note visible across turns without baking it into
    every user message."""

    kind: Literal["user_pinned"] = "user_pinned"
    pin_id: str = ""
    body: str = ""
    summary: str = ""

    def __post_init__(self) -> None:
        if not self.pin_id:
            raise ChatContextSourceValidationError(
                "pin_id is required for user_pinned source",
            )


# Discriminated union — call sites use this when accepting any
# context source kind. Validation lives on each concrete class.
ChatContextSource = (
    EphemeralUploadContextSource
    | ArtifactRefContextSource
    | SessionContextSource
    | RunContextSource
    | UserPinnedContextSource
)


_KIND_TO_CLASS: dict[str, type] = {
    "ephemeral_upload": EphemeralUploadContextSource,
    "artifact_ref": ArtifactRefContextSource,
    "session": SessionContextSource,
    "run": RunContextSource,
    "user_pinned": UserPinnedContextSource,
}


def chat_context_source_from_dict(data: dict[str, Any]) -> ChatContextSource:
    """Discriminator-driven factory. The ``kind`` field selects which
    concrete class to construct. Unknown kinds raise so a typo in
    the wire payload fails loud."""
    if not isinstance(data, dict):
        raise ChatContextSourceValidationError(
            "chat context source payload must be a mapping",
        )
    kind = str(data.get("kind") or "")
    cls = _KIND_TO_CLASS.get(kind)
    if cls is None:
        raise ChatContextSourceValidationError(
            f"unknown chat context source kind {kind!r}; "
            f"must be one of {sorted(_KIND_TO_CLASS)}",
        )
    # Drop the discriminator + any unknown keys before construction.
    cls_fields = {f for f in cls.__dataclass_fields__ if f != "kind"}
    cleaned: dict[str, Any] = {}
    for key, value in data.items():
        if key == "kind":
            continue
        if key not in cls_fields:
            continue
        if key in {"uploaded_at", "expires_at"} and isinstance(value, str) and value:
            cleaned[key] = datetime.fromisoformat(value)
        else:
            cleaned[key] = value
    return cls(**cleaned)


__all__ = [
    "ArtifactRefContextSource",
    "ChatContextSource",
    "ChatContextSourceKind",
    "ChatContextSourceValidationError",
    "EphemeralUploadContextSource",
    "RunContextSource",
    "SessionContextSource",
    "UserPinnedContextSource",
    "chat_context_source_from_dict",
]
