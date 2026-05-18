"""Tests for ``DurableUsageLedger`` three-tier durability wrapper.

Covers the behaviour locked in ADR-025:

- Tier 1 retry succeeds without spilling.
- Tier 2 spill triggers when retries exhaust.
- Tier 3 drain succeeds after the inner ledger recovers.
- Drain failure increments attempts; record stays pending.
- Serialised records round-trip without losing fields (including the
  2026-05-16 anchor/leaf additions).
- Spill is idempotent on duplicate ``record_id``.
- Read methods passthrough to inner.
- ``asyncio.CancelledError`` propagates through the retry layer.
- Forward-compat: unknown fields in spill JSON are dropped on read.
"""
# ruff: noqa: RUF002, RUF003
from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from novie_protocol.contracts import (
    ExecutionContext,
    IdentityContext,
    TenantScope,
    UsageCtxSummary,
    UsageRecord,
    UsageSummary,
)
from novie_protocol.durability import DurableUsageLedger


# ── Test helpers ───────────────────────────────────────────────────


def _ctx() -> ExecutionContext:
    return ExecutionContext(
        request_id="req-1",
        session_id="sess-1",
        thread_id="th-1",
        tenant=TenantScope(tenant_id="t", workspace_id="w", project_id="p"),
        identity=IdentityContext(principal_id="u1", principal_type="user"),
    )


def _make_record(record_id: str = "usg-test-1", **overrides: Any) -> UsageRecord:
    """Build a minimal UsageRecord with all fields populated."""
    base: dict[str, Any] = dict(
        record_id=record_id,
        recorded_at=datetime.now(timezone.utc),
        ctx=UsageCtxSummary(
            tenant_id="t1",
            workspace_id="w1",
            principal_id="p1",
            session_id="s1",
            thread_id="th1",
            request_id="r1",
        ),
        source_kind="agent",
        agent_id="analyst",
        step_id="step-1",
        workflow_id="wf-1",
        provider="anthropic",
        model="claude-sonnet-4.5",
        input_tokens=100,
        output_tokens=50,
        total_tokens=150,
        cost_usd=0.012,
    )
    base.update(overrides)
    return UsageRecord(**base)


class _MockLedger:
    """In-memory UsageLedgerService stub with configurable failure modes."""

    def __init__(
        self,
        *,
        fail_n_times: int = 0,
        always_fail: bool = False,
        raise_cancel: bool = False,
    ) -> None:
        self.recorded: list[UsageRecord] = []
        self._fail_n_times = fail_n_times
        self._always_fail = always_fail
        self._raise_cancel = raise_cancel
        self._fail_count = 0
        self.summary_calls: list[tuple[Any, ...]] = []
        self.list_calls: list[tuple[Any, ...]] = []

    async def record(self, record: UsageRecord) -> None:
        if self._raise_cancel:
            raise asyncio.CancelledError()
        if self._always_fail or self._fail_count < self._fail_n_times:
            self._fail_count += 1
            raise RuntimeError(f"mock failure {self._fail_count}")
        self.recorded.append(record)

    def recover(self) -> None:
        self._always_fail = False
        self._fail_n_times = 0

    async def get_summary(
        self,
        ctx: ExecutionContext,
        *,
        scope: Any = "session",
        scope_value: str | None = None,
        breakdown_by: Any = None,
    ) -> UsageSummary:
        self.summary_calls.append((scope, scope_value, breakdown_by))
        return UsageSummary(
            scope=scope,
            scope_value=scope_value or "",
            input_tokens=0,
            output_tokens=0,
            total_tokens=0,
            cost_usd=0.0,
            request_count=0,
            tool_call_count=0,
            record_count=0,
        )

    async def list_records(
        self,
        ctx: ExecutionContext,
        *,
        session_id: str | None = None,
        thread_id: str | None = None,
        agent_id: str | None = None,
        workflow_id: str | None = None,
        limit: int = 200,
    ) -> list[UsageRecord]:
        self.list_calls.append(
            (session_id, thread_id, agent_id, workflow_id, limit),
        )
        return []


def _build_durable(
    inner: _MockLedger,
    spill_path: Path,
    *,
    max_retries: int = 3,
    drain_interval: float = 60.0,
) -> DurableUsageLedger:
    return DurableUsageLedger(
        inner=inner,
        spill_db_path=spill_path,
        max_retries=max_retries,
        backoff_base_seconds=0.001,
        drain_interval_seconds=drain_interval,
    )


# ── Tier 1: in-process retry ───────────────────────────────────────


@pytest.mark.asyncio
async def test_record_succeeds_first_try_no_spill(tmp_path: Path) -> None:
    inner = _MockLedger()
    durable = _build_durable(inner, tmp_path / "spill.db")
    try:
        await durable.record(_make_record())
        assert len(inner.recorded) == 1
        assert await durable.pending_count() == 0
    finally:
        durable.close()


@pytest.mark.asyncio
async def test_record_retries_then_succeeds(tmp_path: Path) -> None:
    inner = _MockLedger(fail_n_times=2)
    durable = _build_durable(inner, tmp_path / "spill.db", max_retries=3)
    try:
        await durable.record(_make_record())
        assert len(inner.recorded) == 1
        assert await durable.pending_count() == 0
    finally:
        durable.close()


# ── Tier 2: spill on retry exhaustion ──────────────────────────────


@pytest.mark.asyncio
async def test_record_retry_exhausted_spills_does_not_raise(tmp_path: Path) -> None:
    inner = _MockLedger(always_fail=True)
    durable = _build_durable(inner, tmp_path / "spill.db", max_retries=2)
    try:
        # Must NOT raise even though inner always fails.
        await durable.record(_make_record())
        assert len(inner.recorded) == 0
        assert await durable.pending_count() == 1
    finally:
        durable.close()


@pytest.mark.asyncio
async def test_record_idempotent_on_duplicate_record_id(tmp_path: Path) -> None:
    inner = _MockLedger(always_fail=True)
    durable = _build_durable(inner, tmp_path / "spill.db", max_retries=1)
    try:
        rec = _make_record("usg-dup")
        await durable.record(rec)
        await durable.record(rec)
        # Both writes targeted the same record_id; spill stores it once.
        assert await durable.pending_count() == 1
    finally:
        durable.close()


# ── Tier 3: drain on recovery ──────────────────────────────────────


@pytest.mark.asyncio
async def test_drain_pushes_spilled_records_after_recovery(tmp_path: Path) -> None:
    inner = _MockLedger(always_fail=True)
    durable = _build_durable(inner, tmp_path / "spill.db", max_retries=1)
    try:
        await durable.record(_make_record("usg-1"))
        await durable.record(_make_record("usg-2"))
        assert await durable.pending_count() == 2

        inner.recover()
        drained = await durable.drain_once()
        assert drained == 2
        assert {r.record_id for r in inner.recorded} == {"usg-1", "usg-2"}
        assert await durable.pending_count() == 0
    finally:
        durable.close()


@pytest.mark.asyncio
async def test_drain_failure_increments_attempts_and_records_error(
    tmp_path: Path,
) -> None:
    inner = _MockLedger(always_fail=True)
    spill_path = tmp_path / "spill.db"
    durable = _build_durable(inner, spill_path, max_retries=1)
    try:
        await durable.record(_make_record("usg-x"))
        await durable.drain_once()  # inner still failing
        # Verify failure metadata via direct sqlite read.
        conn = sqlite3.connect(spill_path)
        row = conn.execute(
            "SELECT drain_attempts, last_error, drained_at "
            "FROM usage_spill WHERE record_id = ?",
            ("usg-x",),
        ).fetchone()
        conn.close()
        assert row[0] == 1
        assert "mock failure" in row[1]
        assert row[2] is None  # not drained
        # Subsequent drain attempt accumulates.
        await durable.drain_once()
        conn = sqlite3.connect(spill_path)
        row = conn.execute(
            "SELECT drain_attempts FROM usage_spill WHERE record_id = ?",
            ("usg-x",),
        ).fetchone()
        conn.close()
        assert row[0] == 2
    finally:
        durable.close()


# ── Drain loop lifecycle ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_drain_loop_runs_until_stopped(tmp_path: Path) -> None:
    inner = _MockLedger(always_fail=True)
    durable = _build_durable(
        inner,
        tmp_path / "spill.db",
        max_retries=1,
        drain_interval=0.05,
    )
    try:
        await durable.record(_make_record("usg-loop"))
        assert await durable.pending_count() == 1

        await durable.start_drain()
        # Let the loop tick a few times while inner is still failing.
        await asyncio.sleep(0.2)
        assert await durable.pending_count() == 1

        inner.recover()
        # Next tick should drain.
        await asyncio.sleep(0.2)
        assert await durable.pending_count() == 0

        await durable.stop_drain()
    finally:
        durable.close()


@pytest.mark.asyncio
async def test_start_drain_is_idempotent(tmp_path: Path) -> None:
    inner = _MockLedger()
    durable = _build_durable(
        inner, tmp_path / "spill.db", drain_interval=0.05,
    )
    try:
        await durable.start_drain()
        first_task = durable._drain_task  # noqa: SLF001 — test-only introspection
        await durable.start_drain()  # second call is a no-op
        assert durable._drain_task is first_task  # noqa: SLF001
        await durable.stop_drain()
    finally:
        durable.close()


# ── Read passthrough ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_summary_delegates_to_inner(tmp_path: Path) -> None:
    inner = _MockLedger()
    durable = _build_durable(inner, tmp_path / "spill.db")
    try:
        await durable.get_summary(_ctx(), scope="session", scope_value="sess-1")
        assert inner.summary_calls == [("session", "sess-1", None)]
    finally:
        durable.close()


@pytest.mark.asyncio
async def test_list_records_delegates_to_inner(tmp_path: Path) -> None:
    inner = _MockLedger()
    durable = _build_durable(inner, tmp_path / "spill.db")
    try:
        await durable.list_records(
            _ctx(), session_id="sess-1", limit=10,
        )
        assert inner.list_calls == [("sess-1", None, None, None, 10)]
    finally:
        durable.close()


# ── Serialization round-trip ───────────────────────────────────────


@pytest.mark.asyncio
async def test_serialization_round_trip_preserves_all_fields(
    tmp_path: Path,
) -> None:
    inner = _MockLedger(always_fail=True)
    durable = _build_durable(inner, tmp_path / "spill.db", max_retries=1)
    try:
        original = _make_record(
            record_id="usg-roundtrip",
            anchor_kind="plan_step",
            anchor_id="step-99",
            leaf_kind="llm",
            quantity=150.0,
            quantity_unit="tokens",
            tags={"phase": "design"},
            raw_usage_metadata={"raw": {"nested": "data"}},
            request_count=2,
            tool_call_count=3,
            latency_ms=480.5,
        )
        await durable.record(original)
        inner.recover()
        await durable.drain_once()

        assert len(inner.recorded) == 1
        recovered = inner.recorded[0]
        assert recovered.record_id == "usg-roundtrip"
        assert recovered.anchor_kind == "plan_step"
        assert recovered.anchor_id == "step-99"
        assert recovered.leaf_kind == "llm"
        assert recovered.quantity == 150.0
        assert recovered.quantity_unit == "tokens"
        assert recovered.tags == {"phase": "design"}
        assert recovered.raw_usage_metadata == {"raw": {"nested": "data"}}
        assert recovered.request_count == 2
        assert recovered.tool_call_count == 3
        assert recovered.latency_ms == 480.5
        assert recovered.ctx.tenant_id == "t1"
        assert recovered.ctx.principal_id == "p1"
    finally:
        durable.close()


@pytest.mark.asyncio
async def test_deserialize_tolerates_unknown_fields() -> None:
    """Forward-compat: if a future ``UsageRecord`` adds fields and the spill
    file pre-dates the upgrade, deserialisation must drop unknown keys instead
    of raising. Otherwise a code rollback could strand old spill rows."""
    from novie_protocol.durability import _deserialize_record  # noqa: PLC0415 — internal helper

    payload = json.dumps(
        {
            "record_id": "usg-future",
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "ctx": {
                "tenant_id": "t",
                "workspace_id": "w",
                "principal_id": "p",
                "session_id": "s",
                "thread_id": "th",
                "request_id": "r",
                "future_ctx_field": "ignored",
            },
            "source_kind": "agent",
            "agent_id": None,
            "step_id": None,
            "workflow_id": None,
            "provider": "x",
            "model": "y",
            "input_tokens": None,
            "output_tokens": None,
            "total_tokens": None,
            "cost_usd": None,
            "future_field": "from-version-N+1",
        },
    )
    rec = _deserialize_record(payload)
    assert rec.record_id == "usg-future"
    assert rec.ctx.tenant_id == "t"


# ── Cancellation propagation ───────────────────────────────────────


@pytest.mark.asyncio
async def test_cancelled_error_propagates_through_retry(tmp_path: Path) -> None:
    """``asyncio.CancelledError`` must NOT be caught by the retry layer."""
    inner = _MockLedger(raise_cancel=True)
    durable = _build_durable(inner, tmp_path / "spill.db", max_retries=3)
    try:
        with pytest.raises(asyncio.CancelledError):
            await durable.record(_make_record())
        # Cancelled record was NOT spilled (caller is in the middle of cancel).
        assert await durable.pending_count() == 0
    finally:
        durable.close()


# ── Construction validation ────────────────────────────────────────


def test_invalid_max_retries_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="max_retries"):
        DurableUsageLedger(
            inner=_MockLedger(),
            spill_db_path=tmp_path / "spill.db",
            max_retries=0,
        )


def test_invalid_drain_interval_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="drain_interval_seconds"):
        DurableUsageLedger(
            inner=_MockLedger(),
            spill_db_path=tmp_path / "spill.db",
            drain_interval_seconds=0,
        )


def test_invalid_backoff_base_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="backoff_base_seconds"):
        DurableUsageLedger(
            inner=_MockLedger(),
            spill_db_path=tmp_path / "spill.db",
            backoff_base_seconds=-1,
        )
