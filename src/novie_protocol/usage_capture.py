"""UsageCaptureCallback — importable from any agent bundle.

This module lives in novie_protocol so that ExpertAgent bundles (analyst,
pm, …) can import it without depending on novie_platform (§13.5 boundary).

Cost resolution is attempted via an optional ``cost_resolver`` callable.
novie_platform injects a real pricing resolver; bundles that don't have
access to it simply get cost_usd=None.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any
from uuid import UUID

from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.outputs import LLMResult

from .contracts import ExecutionContext, UsageRecord, UsageSourceKind
from .services import UsageLedgerService

CostResolver = Callable[[str, str, int | None, int | None], float | None]


def _infer_provider_model(model_name: str | None) -> tuple[str, str]:
    if not model_name:
        return "unknown", "unknown"
    if "/" in model_name:
        provider, _, model = model_name.partition("/")
        return provider.lower(), model.lower()
    return "unknown", model_name.lower()


class UsageCaptureCallback(AsyncCallbackHandler):
    """Async LangChain callback: write one UsageRecord after every LLM call."""

    def __init__(
        self,
        ctx: ExecutionContext,
        ledger: UsageLedgerService,
        *,
        source_kind: UsageSourceKind,
        provider: str | None = None,
        model: str | None = None,
        agent_id: str | None = None,
        step_id: str | None = None,
        tags: dict[str, str] | None = None,
        cost_resolver: CostResolver | None = None,
    ) -> None:
        super().__init__()
        self._ctx = ctx
        self._ledger = ledger
        self._source_kind = source_kind
        self._provider = provider
        self._model = model
        self._agent_id = agent_id
        self._step_id = step_id
        self._tags = dict(tags or {})
        self._tool_call_count = 0
        self._start_times: dict[str, float] = {}
        self._cost_resolver = cost_resolver

    async def on_llm_start(
        self, serialized: dict[str, Any], prompts: list[str],
        *, run_id: UUID, **kwargs: Any,
    ) -> None:
        self._start_times[str(run_id)] = time.perf_counter()

    async def on_chat_model_start(
        self, serialized: dict[str, Any], messages: list[list[Any]],
        *, run_id: UUID, **kwargs: Any,
    ) -> None:
        self._start_times[str(run_id)] = time.perf_counter()

    async def on_tool_start(
        self, serialized: dict[str, Any], input_str: str,
        *, run_id: UUID, **kwargs: Any,
    ) -> None:
        self._tool_call_count += 1

    async def on_llm_end(
        self, response: LLMResult, *, run_id: UUID, **kwargs: Any,
    ) -> None:
        start = self._start_times.pop(str(run_id), None)
        latency_ms = (time.perf_counter() - start) * 1000 if start is not None else None

        input_tokens: int | None = None
        output_tokens: int | None = None
        total_tokens: int | None = None

        llm_output = response.llm_output or {}

        # OpenAI / Anthropic style
        usage = llm_output.get("token_usage") or llm_output.get("usage") or {}
        if usage:
            input_tokens = usage.get("prompt_tokens") or usage.get("input_tokens")
            output_tokens = usage.get("completion_tokens") or usage.get("output_tokens")
            total_tokens = usage.get("total_tokens")

        # Per-generation usage_metadata
        if input_tokens is None and response.generations:
            gen = response.generations[0]
            if gen and hasattr(gen[0], "generation_info"):
                ginfo = gen[0].generation_info or {}
                um = ginfo.get("usage_metadata") or ginfo.get("usage") or {}
                if um:
                    input_tokens = um.get("input_tokens") or um.get("prompt_tokens")
                    output_tokens = um.get("output_tokens") or um.get("completion_tokens")
                    total_tokens = um.get("total_tokens")

        # Streaming ChatModel path: usage hangs off the merged AIMessage
        # (``gen[0].message.usage_metadata``), not on ``llm_output`` /
        # ``generation_info``. ChatOpenAI populates it when ``stream_usage=True``.
        model_name_from_msg: str | None = None
        if input_tokens is None and response.generations:
            gen = response.generations[0]
            if gen:
                message = getattr(gen[0], "message", None)
                if message is not None:
                    um = getattr(message, "usage_metadata", None) or {}
                    if um:
                        input_tokens = um.get("input_tokens") or um.get("prompt_tokens")
                        output_tokens = um.get("output_tokens") or um.get("completion_tokens")
                        total_tokens = um.get("total_tokens")
                    response_metadata = getattr(message, "response_metadata", None) or {}
                    model_name_from_msg = (
                        response_metadata.get("model_name")
                        or response_metadata.get("model")
                    )

        provider = self._provider
        model = self._model
        if provider is None or model is None:
            model_name = (
                llm_output.get("model_name")
                or llm_output.get("model")
                or model_name_from_msg
            )
            ip, im = _infer_provider_model(model_name)
            provider = provider or ip
            model = model or im

        cost_usd: float | None = None
        if self._cost_resolver is not None:
            cost_usd = self._cost_resolver(provider, model, input_tokens, output_tokens)

        record = UsageRecord.new(
            self._ctx,
            source_kind=self._source_kind,
            provider=provider,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            cost_usd=cost_usd,
            latency_ms=latency_ms,
            tool_call_count=self._tool_call_count,
            agent_id=self._agent_id,
            step_id=self._step_id,
            raw_usage_metadata=dict(usage),
            tags=self._tags,
        )
        self._tool_call_count = 0

        try:
            await self._ledger.record(record)
        except Exception:
            pass
