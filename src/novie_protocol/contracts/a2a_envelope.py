"""Signed A2A request envelope (ADR-133 §8 附带项).

The platform and every A2A provider sit on one Docker network / service mesh.
Before this envelope, a provider trusted the plaintext ``x-novie-tenant-id``
header — anything that could reach the provider's port could impersonate any
tenant and read that tenant's tasks, diffs, and repository content.

Both sides import this module, so there is exactly one definition of what is
signed — the same single-definition discipline as ``agent_runtime``.

The signature covers ``(method, path, tenant_id, task_id, timestamp)`` with the
registration token both parties already hold. It authenticates *who the caller
is acting for*; transport integrity beyond that is the mesh's job (TLS/mTLS in
production).
"""

from __future__ import annotations

import hashlib
import hmac
import time

TENANT_HEADER = "x-novie-tenant-id"
TIMESTAMP_HEADER = "x-novie-timestamp"
SIGNATURE_HEADER = "x-novie-a2a-sig"

#: Reject envelopes older/newer than this many seconds. Wide enough for clock
#: drift between local containers, narrow enough to blunt replay.
MAX_SKEW_SECONDS = 300


def _canonical(
    method: str, path: str, tenant_id: str, task_id: str, timestamp: str
) -> bytes:
    return "\n".join(
        [method.upper(), path, tenant_id, task_id, timestamp]
    ).encode("utf-8")


def sign_headers(
    *,
    secret: str,
    method: str,
    path: str,
    tenant_id: str,
    task_id: str = "",
    now: float | None = None,
) -> dict[str, str]:
    """Headers the platform attaches to an outbound A2A request."""
    timestamp = str(int(now if now is not None else time.time()))
    digest = hmac.new(
        secret.encode("utf-8"),
        _canonical(method, path, tenant_id, task_id, timestamp),
        hashlib.sha256,
    ).hexdigest()
    return {
        TENANT_HEADER: tenant_id,
        TIMESTAMP_HEADER: timestamp,
        SIGNATURE_HEADER: f"sha256={digest}",
    }


def verify_envelope(
    *,
    secret: str,
    method: str,
    path: str,
    tenant_id: str,
    task_id: str,
    timestamp: str,
    signature: str,
    now: float | None = None,
) -> bool:
    """Provider-side check. False means reject the request.

    An empty ``secret`` returns True — standalone development outside the
    platform runs unsigned. Inside the platform the token is always set, so
    this never silently downgrades a deployed provider.
    """
    if not secret:
        return True
    if not timestamp or not signature:
        return False
    try:
        skew = abs((now if now is not None else time.time()) - int(timestamp))
    except ValueError:
        return False
    if skew > MAX_SKEW_SECONDS:
        return False
    expected = hmac.new(
        secret.encode("utf-8"),
        _canonical(method, path, tenant_id, task_id, timestamp),
        hashlib.sha256,
    ).hexdigest()
    provided = signature.removeprefix("sha256=")
    return hmac.compare_digest(expected, provided)


__all__ = [
    "MAX_SKEW_SECONDS",
    "SIGNATURE_HEADER",
    "TENANT_HEADER",
    "TIMESTAMP_HEADER",
    "sign_headers",
    "verify_envelope",
]
