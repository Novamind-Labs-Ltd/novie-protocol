"""Signed A2A envelope (ADR-133 §8)."""

from __future__ import annotations

from novie_protocol.contracts.a2a_envelope import sign_headers, verify_envelope


def _roundtrip(**overrides):
    base = dict(
        secret="tok", method="POST", path="/tasks",
        tenant_id="tenant-a", task_id="t1", now=1_000_000.0,
    )
    headers = sign_headers(**{k: v for k, v in base.items() if k != "task_id"} | {"task_id": base["task_id"]})
    check = dict(
        secret=base["secret"], method=base["method"], path=base["path"],
        tenant_id=base["tenant_id"], task_id=base["task_id"],
        timestamp=headers["x-novie-timestamp"],
        signature=headers["x-novie-a2a-sig"], now=1_000_000.0,
    )
    check.update(overrides)
    return verify_envelope(**check)


def test_a_valid_envelope_verifies() -> None:
    assert _roundtrip() is True


def test_a_different_tenant_fails() -> None:
    """The whole point: you cannot claim to act for another tenant."""
    assert _roundtrip(tenant_id="tenant-b") is False


def test_a_different_task_fails() -> None:
    assert _roundtrip(task_id="someone-elses-task") is False


def test_a_stale_timestamp_fails() -> None:
    assert _roundtrip(now=1_000_000.0 + 301) is False


def test_a_wrong_secret_fails() -> None:
    assert _roundtrip(secret="other") is False


def test_missing_signature_fails() -> None:
    assert _roundtrip(signature="") is False


def test_empty_secret_means_standalone_and_allows() -> None:
    assert verify_envelope(
        secret="", method="POST", path="/tasks", tenant_id="t",
        task_id="", timestamp="", signature="",
    ) is True
