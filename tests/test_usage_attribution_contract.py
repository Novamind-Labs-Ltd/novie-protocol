from __future__ import annotations

import pytest

from novie_protocol.contracts import (
    ExecutionContext,
    IdentityContext,
    TenantScope,
    UsageRecord,
)


def _ctx(
    *,
    tenant_id: str = "tenant-1",
    workspace_id: str = "workspace-1",
    principal_id: str = "user-1",
    session_id: str = "session-1",
) -> ExecutionContext:
    return ExecutionContext(
        request_id="request-1",
        session_id=session_id,
        thread_id="thread-1",
        tenant=TenantScope(tenant_id=tenant_id, workspace_id=workspace_id),
        identity=IdentityContext(
            principal_id=principal_id,
            principal_type="user",
        ),
    )


def _record(ctx: ExecutionContext) -> UsageRecord:
    return UsageRecord.new(
        ctx,
        source_kind="reception",
        provider="openai",
        model="gpt-test",
        input_tokens=10,
        output_tokens=5,
    )


def test_usage_record_new_keeps_adr_025_anchor_defaults_non_empty() -> None:
    rec = _record(_ctx())

    assert rec.ctx.tenant_id == "tenant-1"
    assert rec.ctx.workspace_id == "workspace-1"
    assert rec.ctx.principal_id == "user-1"
    assert rec.ctx.session_id == "session-1"
    assert rec.anchor_kind == "reception_turn"
    assert rec.anchor_id == "request-1"
    assert rec.leaf_kind == "llm"
    assert rec.quantity == 15.0
    assert rec.quantity_unit == "tokens"


@pytest.mark.parametrize(
    ("field", "kwargs"),
    (
        ("tenant_id", {"tenant_id": ""}),
        ("workspace_id", {"workspace_id": ""}),
        ("principal_id", {"principal_id": ""}),
        ("session_id", {"session_id": ""}),
    ),
)
def test_usage_record_new_rejects_empty_required_attribution_fields(
    field: str,
    kwargs: dict[str, str],
) -> None:
    with pytest.raises(ValueError, match=field):
        _record(_ctx(**kwargs))
