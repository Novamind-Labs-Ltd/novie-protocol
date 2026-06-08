from __future__ import annotations

from novie_protocol.tool_stream import ToolStreamAccumulator


class _ToolChunk:
    type = "tool"
    tool_call_id = "call-1"
    name = "fetch_artifact"
    content = "large artifact body"


def test_tool_result_events_are_internal_by_default() -> None:
    acc = ToolStreamAccumulator(default_metadata={"capability_id": "agent.test"})

    events = list(acc.feed(_ToolChunk()))

    assert len(events) == 1
    event = events[0]
    assert event.kind == "tool_result"
    assert event.tool_name == "fetch_artifact"
    assert event.tool_result == "large artifact body"
    assert event.metadata["capability_id"] == "agent.test"
    assert event.metadata["visibility"] == "internal"
    assert event.metadata["tool_result_visibility"] == "internal"
    assert event.metadata["tool_result_chars"] == len("large artifact body")

