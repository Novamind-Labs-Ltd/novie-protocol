"""Helpers for translating LangGraph `stream_mode="messages"` chunks into
``AgentStreamEvent`` tool-call / tool-result pairs.

**为什么住在 protocol 包里**：
    这是实现逻辑，原则上该在 platform；但本模块**不 import 任何 LangChain
    类型**（全靠 ``getattr(chunk, "tool_call_chunks", ...)`` 鸭式读取），所以
    不会污染 protocol 的纯契约属性。放在这里的好处：expert-agent bundle
    （按 ARCH §19.4.20 只许依赖 protocol）能直接 ``from
    novie_protocol.tool_stream import ToolStreamAccumulator`` 复用，不必每个
    bundle 重写一份累加器 —— 也不用绕 "shared runtime" 那个缝。

契约：
    ``ToolStreamAccumulator.feed(chunk)`` 吃一个 LangChain message chunk，
    yield 0~N 个 ``AgentStreamEvent``。``tool_call`` 在参数 JSON 完整后发一次；
    ``tool_result`` 在看到 ``ToolMessage`` 时发一次。caller 决定是否 re-emit
    ``content`` 文本 delta —— 本 helper 不管 content，职责单一。
"""
from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from .agents import AgentStreamEvent


@dataclass
class _PendingCall:
    """单个 tool call 的累计状态 —— LangChain tool_call_chunks 是 delta 流，
    要等 name 填好 + args JSON 能 parse 才能 emit 一次完整的 tool_call。"""

    tool_call_id: str
    name: str = ""
    args_raw: str = ""
    emitted: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


def _args_is_complete(raw: str) -> bool:
    """返回 args JSON 是否已经是合法的闭合对象。

    LangChain 把 tool_call_chunks 一段段流出来（``{"``→``{"query"``→…），只有
    等 ``}`` 全部闭合后 ``json.loads`` 才能成功。用 loads 成功做 emit 触发器，
    比手写括号计数器稳；失败返回 False，等下一个 chunk。
    """
    if not raw:
        return False
    try:
        json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return False
    return True


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "…"


class ToolStreamAccumulator:
    """跨 chunk 累加 ReAct / tool-calling agent 的 tool 调用轨迹。

    Usage（见 ``analyst/runtime.py``）::

        acc = ToolStreamAccumulator()
        async for mode, payload in graph.astream(..., stream_mode=["messages", "values"]):
            if mode == "messages":
                chunk, _meta = payload
                for event in acc.feed(chunk):
                    yield event
                # caller 自己处理 content delta（本 helper 不发 content event）

    线程安全：**否**。单个 accumulator 实例只在一个协程里串行 feed。
    """

    def __init__(
        self,
        *,
        tool_result_max_chars: int = 400,
        default_metadata: dict[str, Any] | None = None,
    ) -> None:
        self._pending: dict[str, _PendingCall] = {}
        self._tool_result_max = tool_result_max_chars
        self._default_meta: dict[str, Any] = dict(default_metadata or {})

    def feed(self, chunk: Any) -> Iterable[AgentStreamEvent]:
        """喂一个 LangChain message chunk，yield 0~N 个 AgentStreamEvent。

        识别两类信号：
        - ``chunk.tool_call_chunks`` (``AIMessageChunk``) —— 追加到
          ``_pending[id]``；一旦 args JSON 完整就发 ``tool_call`` 事件
        - ``chunk.type == "tool"`` (``ToolMessage`` / ``ToolMessageChunk``)
          —— 发 ``tool_result`` 事件

        对所有不认识的 chunk 静默返回（normal content delta 由 caller 另行处理）。
        """
        # 1) tool_call_chunks（LLM 吐调用参数）
        tcc = getattr(chunk, "tool_call_chunks", None)
        if tcc:
            yield from self._consume_tool_call_chunks(tcc)
            return

        # LangChain 在非流式路径上有时只给 ``tool_calls``（已聚合）—— 直接 emit。
        tcs = getattr(chunk, "tool_calls", None)
        if tcs and not tcc:
            for tc in tcs:
                tcid = str(tc.get("id") or "")
                if tcid in self._pending and self._pending[tcid].emitted:
                    continue
                args = tc.get("args") or {}
                if not isinstance(args, dict):
                    # 历史 LangChain 版本用 str；尽力 parse
                    try:
                        args = json.loads(args) if isinstance(args, str) else {}
                    except (json.JSONDecodeError, ValueError):
                        args = {"_raw": str(args)}
                self._pending[tcid] = _PendingCall(
                    tool_call_id=tcid,
                    name=str(tc.get("name") or ""),
                    args_raw=json.dumps(args, ensure_ascii=False),
                    emitted=True,
                )
                yield AgentStreamEvent(
                    kind="tool_call",
                    tool_name=str(tc.get("name") or ""),
                    tool_args=args,
                    tool_call_id=tcid or None,
                    metadata=dict(self._default_meta),
                )
            return

        # 2) ToolMessage (chunk or full)
        chunk_type = getattr(chunk, "type", None)
        if chunk_type == "tool":
            tcid = str(getattr(chunk, "tool_call_id", "") or "")
            name = str(getattr(chunk, "name", "") or "")
            content = getattr(chunk, "content", "")
            if not isinstance(content, str):
                content = str(content)
            yield AgentStreamEvent(
                kind="tool_result",
                tool_name=name,
                tool_call_id=tcid or None,
                tool_result=_truncate(content, self._tool_result_max),
                metadata=dict(self._default_meta),
            )

    def _consume_tool_call_chunks(
        self, tcc: list[dict[str, Any]],
    ) -> Iterable[AgentStreamEvent]:
        for piece in tcc:
            tcid = str(piece.get("id") or "")
            if not tcid:
                # 没 id 的场景历史上有过（某些 model 不给 id）—— 用 index 兜
                idx = piece.get("index")
                tcid = f"__idx__{idx}" if idx is not None else "__unkeyed__"
            rec = self._pending.setdefault(tcid, _PendingCall(tool_call_id=tcid))
            if rec.emitted:
                continue
            if piece.get("name"):
                rec.name = str(piece["name"])
            if piece.get("args"):
                rec.args_raw += str(piece["args"])

            # emit 触发条件：name 已知 + args JSON 闭合。两者都满足才发。
            if rec.name and _args_is_complete(rec.args_raw):
                rec.emitted = True
                try:
                    parsed = json.loads(rec.args_raw) if rec.args_raw else {}
                except (json.JSONDecodeError, ValueError):  # pragma: no cover
                    parsed = {"_raw": rec.args_raw}
                yield AgentStreamEvent(
                    kind="tool_call",
                    tool_name=rec.name,
                    tool_args=parsed if isinstance(parsed, dict) else {"_raw": parsed},
                    tool_call_id=tcid if not tcid.startswith("__") else None,
                    metadata=dict(self._default_meta),
                )
