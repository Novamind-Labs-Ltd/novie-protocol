"""Narrow platform LLM credential (ADR-133 §9)."""

from __future__ import annotations

import pytest

from novie_protocol.contracts.llm_credential import (
    LlmCredentialError,
    mint_llm_credential,
    verify_llm_credential,
)


def test_roundtrip_carries_the_billing_scope() -> None:
    token = mint_llm_credential(
        secret="tok", tenant_id="t1", workspace_id="w1",
        project_id="p1", user_id="u1", now=1_000_000.0,
    )
    claims = verify_llm_credential(token, secret="tok", now=1_000_000.0)
    assert (claims.tenant_id, claims.workspace_id, claims.project_id,
            claims.user_id) == ("t1", "w1", "p1", "u1")


def test_a_tampered_payload_is_rejected() -> None:
    token = mint_llm_credential(secret="tok", tenant_id="t1", now=1_000_000.0)
    prefix, body, sig = token.split(".")
    forged = f"{prefix}.{body[:-2]}xy.{sig}"
    with pytest.raises(LlmCredentialError, match="signature"):
        verify_llm_credential(forged, secret="tok", now=1_000_000.0)


def test_an_expired_credential_is_rejected() -> None:
    token = mint_llm_credential(
        secret="tok", tenant_id="t1", ttl_seconds=60, now=1_000_000.0
    )
    with pytest.raises(LlmCredentialError, match="expired"):
        verify_llm_credential(token, secret="tok", now=1_000_000.0 + 61)


def test_a_wrong_secret_is_rejected() -> None:
    token = mint_llm_credential(secret="tok", tenant_id="t1", now=1_000_000.0)
    with pytest.raises(LlmCredentialError):
        verify_llm_credential(token, secret="other", now=1_000_000.0)


def test_random_bearer_strings_are_not_credentials() -> None:
    with pytest.raises(LlmCredentialError, match="not a platform"):
        verify_llm_credential("sk-abc123", secret="tok")


def test_minting_requires_a_tenant() -> None:
    """A credential that bills to nobody must not exist."""
    with pytest.raises(LlmCredentialError, match="tenant"):
        mint_llm_credential(secret="tok", tenant_id="")
