"""Narrow platform LLM credential (ADR-133 §9).

Executors running inside the platform must not hold third-party LLM keys
(BYOK is the uncontrolled bypass); they call the platform's OpenAI-compatible
gateway instead. This credential is how such a call authenticates: a signed,
expiring token that encodes *which tenant scope the usage bills to* — and
nothing else. It is not a session, grants no capability, and cannot be
widened: the gateway derives the execution context solely from the payload
the signature covers.

Format: ``novie-llm-v1.<base64url(json)>.<hmac-sha256-hex>``

The signing secret is the registration token both parties already hold —
the same trust root as the A2A envelope, no new configuration surface.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass

PREFIX = "novie-llm-v1"

#: Default lifetime. Long enough for one executor instance's working session,
#: short enough that a leaked token goes stale the same day.
DEFAULT_TTL_SECONDS = 8 * 3600


class LlmCredentialError(ValueError):
    """The token is malformed, tampered with, or expired."""


@dataclass(frozen=True, slots=True)
class LlmCredentialClaims:
    tenant_id: str
    workspace_id: str = ""
    project_id: str = ""
    user_id: str = ""
    expires_at: int = 0


def mint_llm_credential(
    *,
    secret: str,
    tenant_id: str,
    workspace_id: str = "",
    project_id: str = "",
    user_id: str = "",
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    now: float | None = None,
) -> str:
    if not secret:
        raise LlmCredentialError("cannot mint a credential without a secret")
    if not tenant_id:
        raise LlmCredentialError("a credential must bill to a tenant")
    payload = {
        "tenant_id": tenant_id,
        "workspace_id": workspace_id,
        "project_id": project_id,
        "user_id": user_id,
        "exp": int((now if now is not None else time.time()) + ttl_seconds),
    }
    body = base64.urlsafe_b64encode(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).rstrip(b"=").decode()
    sig = hmac.new(
        secret.encode(), f"{PREFIX}.{body}".encode(), hashlib.sha256
    ).hexdigest()
    return f"{PREFIX}.{body}.{sig}"


def verify_llm_credential(
    token: str, *, secret: str, now: float | None = None
) -> LlmCredentialClaims:
    """Return the claims, or raise :class:`LlmCredentialError`."""
    if not secret:
        raise LlmCredentialError("no signing secret configured")
    parts = token.strip().split(".")
    if len(parts) != 3 or parts[0] != PREFIX:
        raise LlmCredentialError("not a platform LLM credential")
    _, body, provided = parts
    expected = hmac.new(
        secret.encode(), f"{PREFIX}.{body}".encode(), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, provided):
        raise LlmCredentialError("credential signature mismatch")
    try:
        padded = body + "=" * (-len(body) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))
    except (ValueError, TypeError) as exc:
        raise LlmCredentialError("credential payload unreadable") from exc
    expires_at = int(payload.get("exp") or 0)
    if (now if now is not None else time.time()) >= expires_at:
        raise LlmCredentialError("credential expired")
    tenant_id = str(payload.get("tenant_id") or "")
    if not tenant_id:
        raise LlmCredentialError("credential carries no tenant")
    return LlmCredentialClaims(
        tenant_id=tenant_id,
        workspace_id=str(payload.get("workspace_id") or ""),
        project_id=str(payload.get("project_id") or ""),
        user_id=str(payload.get("user_id") or ""),
        expires_at=expires_at,
    )


__all__ = [
    "DEFAULT_TTL_SECONDS",
    "PREFIX",
    "LlmCredentialClaims",
    "LlmCredentialError",
    "mint_llm_credential",
    "verify_llm_credential",
]
