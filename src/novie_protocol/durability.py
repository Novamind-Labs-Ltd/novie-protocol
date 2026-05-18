"""DurableUsageLedger — three-tier durability wrapper for ``UsageLedgerService``.

Background: ``UsageCaptureCallback`` previously swallowed ``UsageLedgerService.record``
exceptions silently (``except Exception: pass``), causing usage records to be lost
on transient ledger failures. ADR-025 mandates a three-tier strategy:

  1. **In-process retry** — bounded exponential backoff for transient inner failures.
  2. **SQLite spill** — when retries exhaust, append the serialised record to a local
     SQLite database on disk. The original call returns without raising.
  3. **Async drain task** — a background coroutine periodically attempts to push
     spilled records back into the inner ledger; succeeded rows are marked drained.

``DurableUsageLedger`` implements the ``UsageLedgerService`` Protocol (structural)
so callers can compose it transparently at SDK / platform-composition-root setup
time. All other ``UsageLedgerService`` methods (``get_summary``, ``list_records``)
delegate straight to the inner ledger — durability only applies to writes.

This module lives in ``novie_protocol`` (per §13.5 boundary) so agent bundles can
import it without depending on ``novie_platform``. It uses only the Python
standard library (``sqlite3``, ``asyncio``, ``json``, ``logging``).
"""
# ruff: noqa: RUF002, RUF003
from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .contracts import (
    ExecutionContext,
    UsageCtxSummary,
    UsageDimension,
    UsageRecord,
    UsageSummary,
)
from .services import UsageLedgerService

_LOG = logging.getLogger(__name__)

_SPILL_SCHEMA_VERSION = 1

# DDL — append-only spill table. ``record_id`` is uuid-shaped and stable; we use
# it as the primary key so a re-spilled record (which should never happen) is
# de-duplicated rather than producing two ledger inserts on drain.
_SCHEMA_DDL = """
CREATE TABLE IF NOT EXISTS usage_spill (
    record_id TEXT PRIMARY KEY,
    schema_version INTEGER NOT NULL DEFAULT 1,
    serialized_record TEXT NOT NULL,
    created_at TEXT NOT NULL,
    drain_attempts INTEGER NOT NULL DEFAULT 0,
    last_attempt_at TEXT,
    last_error TEXT,
    drained_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_usage_spill_pending
    ON usage_spill (drained_at, created_at)
    WHERE drained_at IS NULL;
"""


# ── Serialization ──────────────────────────────────────────────────


def _serialize_record(record: UsageRecord) -> str:
    """Serialise a ``UsageRecord`` to a JSON string suitable for spill storage."""
    data = dataclasses.asdict(record)
    data["recorded_at"] = record.recorded_at.isoformat()
    return json.dumps(data, ensure_ascii=False, sort_keys=True)


def _deserialize_record(payload: str) -> UsageRecord:
    """Reconstruct a ``UsageRecord`` from spill JSON.

    Tolerant of unknown fields (drops them) so a future schema bump that adds
    fields to ``UsageRecord`` does not strand pre-bump spill rows. Tolerant of
    missing optional fields (defaults applied).
    """
    raw = json.loads(payload)
    # Reconstruct nested UsageCtxSummary, dropping any unexpected keys.
    ctx_raw = raw.pop("ctx")
    ctx_fields = {f.name for f in dataclasses.fields(UsageCtxSummary)}
    ctx = UsageCtxSummary(
        **{k: v for k, v in ctx_raw.items() if k in ctx_fields},
    )
    # Parse datetime back. Pre-bump spill rows always have ISO-8601.
    recorded_at = datetime.fromisoformat(raw.pop("recorded_at"))
    # Drop any extra keys from the top level too, defensively.
    record_fields = {f.name for f in dataclasses.fields(UsageRecord)} - {
        "ctx", "recorded_at",
    }
    kwargs = {k: v for k, v in raw.items() if k in record_fields}
    return UsageRecord(ctx=ctx, recorded_at=recorded_at, **kwargs)


# ── SpillStore ─────────────────────────────────────────────────────


class _SpillStore:
    """Thin SQLite wrapper. All public methods are coroutines that run blocking
    SQLite calls on a thread, serialised by an asyncio.Lock.

    A single connection is held with ``check_same_thread=False``. The lock
    enforces single-flight access so the lifetime sharing is safe.
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(
            db_path,
            check_same_thread=False,
            isolation_level=None,  # autocommit; we wrap explicit transactions where needed
        )
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.executescript(_SCHEMA_DDL)
        self._lock = asyncio.Lock()

    async def append(self, record: UsageRecord) -> None:
        payload = _serialize_record(record)
        now = datetime.now(timezone.utc).isoformat()
        async with self._lock:
            await asyncio.to_thread(
                self._conn.execute,
                "INSERT OR IGNORE INTO usage_spill "
                "(record_id, schema_version, serialized_record, created_at) "
                "VALUES (?, ?, ?, ?)",
                (record.record_id, _SPILL_SCHEMA_VERSION, payload, now),
            )

    async def pending_batch(self, limit: int = 100) -> list[tuple[str, UsageRecord]]:
        """Return up to ``limit`` non-drained records, oldest first."""
        def _fetch() -> list[tuple[str, str]]:
            cursor = self._conn.execute(
                "SELECT record_id, serialized_record "
                "FROM usage_spill "
                "WHERE drained_at IS NULL "
                "ORDER BY created_at ASC "
                "LIMIT ?",
                (limit,),
            )
            return cursor.fetchall()

        async with self._lock:
            rows = await asyncio.to_thread(_fetch)
        results: list[tuple[str, UsageRecord]] = []
        for record_id, payload in rows:
            try:
                results.append((record_id, _deserialize_record(payload)))
            except Exception:
                # Corrupt row — log and skip. It will be cleaned up later by
                # max-attempts policy or manual ops. We don't delete here so
                # that operators can inspect.
                _LOG.exception(
                    "usage_durability.spill.deserialize_failed",
                    extra={"record_id": record_id},
                )
                continue
        return results

    async def mark_drained(self, record_id: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        async with self._lock:
            await asyncio.to_thread(
                self._conn.execute,
                "UPDATE usage_spill SET drained_at = ? WHERE record_id = ?",
                (now, record_id),
            )

    async def record_drain_failure(self, record_id: str, error: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        async with self._lock:
            await asyncio.to_thread(
                self._conn.execute,
                "UPDATE usage_spill "
                "SET drain_attempts = drain_attempts + 1, "
                "    last_attempt_at = ?, "
                "    last_error = ? "
                "WHERE record_id = ?",
                (now, error, record_id),
            )

    async def cleanup_drained(self, max_age_days: int = 7) -> int:
        """Delete drained rows older than ``max_age_days``. Returns count deleted."""
        async with self._lock:
            cur = await asyncio.to_thread(
                self._conn.execute,
                "DELETE FROM usage_spill "
                "WHERE drained_at IS NOT NULL "
                "AND drained_at < datetime('now', ?)",
                (f"-{max_age_days} days",),
            )
            return cur.rowcount

    async def pending_count(self) -> int:
        def _fetch() -> int:
            cursor = self._conn.execute(
                "SELECT COUNT(*) FROM usage_spill WHERE drained_at IS NULL",
            )
            row = cursor.fetchone()
            return int(row[0])

        async with self._lock:
            return await asyncio.to_thread(_fetch)

    def close(self) -> None:
        self._conn.close()


# ── DurableUsageLedger ─────────────────────────────────────────────


class DurableUsageLedger:
    """Wraps a ``UsageLedgerService`` with three-tier durability on writes.

    Reads (``get_summary``, ``list_records``) delegate straight to the inner
    ledger — there is no read-side caching or shadowing.

    ``record()`` never raises. Caller code (LLM callbacks, agent SDK helpers)
    can therefore drop the ``except Exception: pass`` defensive guard that
    historically swallowed write failures silently.

    The drain loop is **not** started automatically — call ``start_drain()``
    once at SDK / platform-composition-root setup, and ``stop_drain()`` at
    shutdown. This lets test code construct an instance without an event-loop
    task hanging around.
    """

    def __init__(
        self,
        inner: UsageLedgerService,
        spill_db_path: Path,
        *,
        max_retries: int = 3,
        backoff_base_seconds: float = 0.5,
        drain_interval_seconds: float = 60.0,
        drain_batch_size: int = 100,
        max_drain_attempts: int = 50,
        cleanup_max_age_days: int = 7,
    ) -> None:
        if max_retries < 1:
            raise ValueError("max_retries must be >= 1")
        if backoff_base_seconds < 0:
            raise ValueError("backoff_base_seconds must be >= 0")
        if drain_interval_seconds <= 0:
            raise ValueError("drain_interval_seconds must be > 0")
        self._inner = inner
        self._store = _SpillStore(spill_db_path)
        self._max_retries = max_retries
        self._backoff_base_seconds = backoff_base_seconds
        self._drain_interval_seconds = drain_interval_seconds
        self._drain_batch_size = drain_batch_size
        self._max_drain_attempts = max_drain_attempts
        self._cleanup_max_age_days = cleanup_max_age_days
        self._drain_task: asyncio.Task[None] | None = None
        self._stopped = asyncio.Event()

    # ── UsageLedgerService Protocol (record) ──────────────────────

    async def record(self, record: UsageRecord) -> None:
        """Tier 1 retry → Tier 2 spill. Never raises."""
        last_error: BaseException | None = None
        for attempt in range(1, self._max_retries + 1):
            try:
                await self._inner.record(record)
                return
            except BaseException as err:  # noqa: BLE001 — we re-classify below
                # Don't swallow asyncio.CancelledError — propagate cancellation.
                if isinstance(err, asyncio.CancelledError):
                    raise
                last_error = err
                _LOG.warning(
                    "usage_durability.record.retry",
                    extra={
                        "record_id": record.record_id,
                        "attempt": attempt,
                        "max_retries": self._max_retries,
                        "error": repr(err),
                    },
                )
                if attempt < self._max_retries:
                    delay = self._backoff_base_seconds * (2 ** (attempt - 1))
                    await asyncio.sleep(delay)
        # All retries exhausted — spill.
        try:
            await self._store.append(record)
            _LOG.warning(
                "usage_durability.record.spilled",
                extra={
                    "record_id": record.record_id,
                    "last_error": repr(last_error),
                },
            )
        except BaseException as spill_err:  # noqa: BLE001
            # Tier 3 (drain) cannot help if spill itself is broken.
            # Log loud, do not crash the LLM call. This is the very last
            # fallback; operators must wire a metric / alert on this event.
            _LOG.error(
                "usage_durability.record.spill_failed",
                extra={
                    "record_id": record.record_id,
                    "ledger_error": repr(last_error),
                    "spill_error": repr(spill_err),
                },
                exc_info=spill_err,
            )

    # ── UsageLedgerService Protocol (read passthrough) ─────────────

    async def get_summary(
        self,
        ctx: ExecutionContext,
        *,
        scope: UsageDimension = "session",
        scope_value: str | None = None,
        breakdown_by: UsageDimension | None = None,
    ) -> UsageSummary:
        return await self._inner.get_summary(
            ctx,
            scope=scope,
            scope_value=scope_value,
            breakdown_by=breakdown_by,
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
        return await self._inner.list_records(
            ctx,
            session_id=session_id,
            thread_id=thread_id,
            agent_id=agent_id,
            workflow_id=workflow_id,
            limit=limit,
        )

    # ── Drain lifecycle ────────────────────────────────────────────

    async def start_drain(self) -> None:
        """Start the background drain task. Idempotent (does nothing if running)."""
        if self._drain_task is not None and not self._drain_task.done():
            return
        self._stopped.clear()
        self._drain_task = asyncio.create_task(
            self._drain_loop(), name="usage-durability-drain",
        )

    async def stop_drain(self) -> None:
        """Stop the background drain task and wait for it to finish."""
        self._stopped.set()
        task = self._drain_task
        self._drain_task = None
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass

    async def drain_once(self) -> int:
        """Public single-shot drain; returns count of newly drained records.

        Useful for tests and for triggering an immediate drain after an inner
        ledger known to have just recovered.
        """
        return await self._drain_once()

    async def pending_count(self) -> int:
        return await self._store.pending_count()

    def close(self) -> None:
        """Synchronous close of the underlying SQLite connection. Call after
        ``stop_drain`` has completed."""
        self._store.close()

    # ── Internal ───────────────────────────────────────────────────

    async def _drain_loop(self) -> None:
        # Run periodic drain + cleanup until stopped.
        try:
            while not self._stopped.is_set():
                try:
                    await asyncio.wait_for(
                        self._stopped.wait(),
                        timeout=self._drain_interval_seconds,
                    )
                except asyncio.TimeoutError:
                    pass  # normal tick
                if self._stopped.is_set():
                    break
                try:
                    drained = await self._drain_once()
                    if drained:
                        _LOG.info(
                            "usage_durability.drain.batch",
                            extra={"drained_count": drained},
                        )
                except asyncio.CancelledError:
                    raise
                except Exception:  # noqa: BLE001
                    _LOG.exception("usage_durability.drain.loop_error")
                # Best-effort cleanup of old drained rows; never blocks the next tick.
                try:
                    await self._store.cleanup_drained(self._cleanup_max_age_days)
                except asyncio.CancelledError:
                    raise
                except Exception:  # noqa: BLE001
                    _LOG.exception("usage_durability.drain.cleanup_error")
        except asyncio.CancelledError:
            pass

    async def _drain_once(self) -> int:
        batch = await self._store.pending_batch(limit=self._drain_batch_size)
        drained = 0
        for record_id, record in batch:
            try:
                await self._inner.record(record)
            except asyncio.CancelledError:
                raise
            except Exception as err:  # noqa: BLE001
                await self._store.record_drain_failure(record_id, repr(err))
                continue
            await self._store.mark_drained(record_id)
            drained += 1
        return drained


__all__ = ["DurableUsageLedger"]
