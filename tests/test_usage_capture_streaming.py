"""Streaming-path coverage for UsageCaptureCallback.

LangChain's ChatOpenAI in streaming mode does not populate
``LLMResult.llm_output`` with ``token_usage`` / ``model_name``. Instead the
merged ``AIMessage`` carries token counts on ``usage_metadata`` and the
upstream model id on ``response_metadata["model_name"]``. These tests lock
that fallback in so reception/supervisor turns no longer record
``unknown/unknown`` rows with NULL tokens.
"""
from __future__ import annotations

from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult
from novie_protocol.contracts import (
    ExecutionContext,
    IdentityContext,
    TenantScope,
    UsageRecord,
)
from novie_protocol.usage_capture import UsageCaptureCallback


class _RecordingLedger:
    def __init__(self) -> None:
        self.records: list[UsageRecord] = []

    async def record(self, record: UsageRecord) -> None:
        self.records.append(record)


def _ctx() -> ExecutionContext:
    return ExecutionContext(
        request_id="req-1",
        session_id="sess-1",
        thread_id="th-1",
        tenant=TenantScope(tenant_id="t", workspace_id="w", project_id="p"),
        identity=IdentityContext(principal_id="u1", principal_type="user"),
    )


@pytest.mark.asyncio
async def test_streaming_message_usage_metadata_is_captured() -> None:
    ledger = _RecordingLedger()
    cb = UsageCaptureCallback(_ctx(), ledger, source_kind="reception")

    msg = AIMessage(
        content="hi",
        usage_metadata={"input_tokens": 12, "output_tokens": 7, "total_tokens": 19},
        response_metadata={"model_name": "anthropic/claude-opus-4.6"},
    )
    result = LLMResult(generations=[[ChatGeneration(message=msg)]], llm_output={})
    await cb.on_llm_end(result, run_id=uuid4())

    assert len(ledger.records) == 1
    rec = ledger.records[0]
    assert rec.input_tokens == 12
    assert rec.output_tokens == 7
    assert rec.total_tokens == 19
    assert rec.provider == "anthropic"
    assert rec.model == "claude-opus-4.6"


@pytest.mark.asyncio
async def test_explicit_provider_model_overrides_inference() -> None:
    ledger = _RecordingLedger()
    cb = UsageCaptureCallback(
        _ctx(),
        ledger,
        source_kind="reception",
        provider="openrouter",
        model="anthropic/claude-opus-4.6",
    )

    # Empty llm_output and no message metadata: would otherwise infer
    # ``unknown/unknown``; explicit override must win.
    msg = AIMessage(content="hi")
    result = LLMResult(generations=[[ChatGeneration(message=msg)]], llm_output={})
    await cb.on_llm_end(result, run_id=uuid4())

    assert ledger.records[0].provider == "openrouter"
    assert ledger.records[0].model == "anthropic/claude-opus-4.6"
