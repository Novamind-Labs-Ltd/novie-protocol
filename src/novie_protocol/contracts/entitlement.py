"""Entitlement contracts for org-level LLM token pool.

Separates two concerns:
- ``LlmKeyPolicy``: which party owns the upstream provider key (Novie vs tenant).
- ``OrgTokenPool``: org-level token budget, consumed only by ``novie_owned_key``
  calls; ``tenant_managed_key`` calls are counted but not capped.

These contracts are intentionally minimal (MVP).  A full billing/entitlement
service will replace the mock implementation, but the shapes here are
forward-compatible with that future boundary.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

LlmKeyPolicy = Literal[
    "novie_owned_key",    # Key owned by Novie team; pool is enforced.
    "tenant_managed_key", # Tenant's own key on Novie SaaS; pool not enforced.
    "standalone",         # Agent running outside platform; not managed.
]


@dataclass(frozen=True, slots=True)
class OrgTokenPool:
    """Current state of an organisation's LLM token pool.

    ``total_tokens`` is the purchased/provisioned cap.  ``used_tokens``
    is the cumulative consumption since the last reset.  When
    ``total_tokens <= 0`` the pool is considered unlimited (same as
    ``tenant_managed_key`` behaviour — used for dev/test orgs).
    """

    org_id: str
    key_policy: LlmKeyPolicy
    total_tokens: int               # 0 means unlimited
    used_tokens: int
    remaining_tokens: int           # max(0, total - used) for display
    warn_at_tokens: int | None = None
    exhausted: bool = False


@dataclass(frozen=True, slots=True)
class TokenReservation:
    """A hold placed on an org's token pool before the LLM call starts.

    ``estimated_tokens`` should be a conservative upper bound; the actual
    deduction on ``commit`` uses the real usage from the LLM response.
    Reservations that are never committed are released on ``refund``.
    """

    reservation_id: str
    org_id: str
    estimated_tokens: int
    request_id: str
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    @classmethod
    def new(
        cls,
        org_id: str,
        estimated_tokens: int,
        request_id: str,
    ) -> "TokenReservation":
        return cls(
            reservation_id=f"rsv-{uuid.uuid4().hex[:16]}",
            org_id=org_id,
            estimated_tokens=estimated_tokens,
            request_id=request_id,
        )


@dataclass(frozen=True, slots=True)
class EntitlementDecision:
    """Result returned by ``EntitlementService.reserve_tokens``.

    When ``allow=False`` the caller should return ``quota_exceeded`` to
    the agent without making the LLM call.  ``reservation_id`` is set
    only when ``allow=True``; callers must pass it to ``commit_tokens``
    or ``refund_tokens`` when the LLM call finishes.
    """

    allow: bool
    org_id: str
    key_policy: LlmKeyPolicy
    remaining_tokens: int           # after this reservation
    reservation_id: str | None = None
    reason: str | None = None
    warn: bool = False              # usage approaching pool limit
