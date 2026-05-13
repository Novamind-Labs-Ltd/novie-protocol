"""EXTERNAL_AGENT_HTTP W8 — shared agent diagnostic vocabulary.

Frozen literal types + dataclasses that the platform, the workspace
UI, and the operator runbooks all reference so failures get the same
name regardless of which surface the operator is looking at.

Acceptance bullets (W8) locked here:
- "Operators can tell whether a failure is network, auth, one-shot
  contract, worker runtime, platform workflow, or Knowledge ingestion."
  → ``DIAGNOSTIC_KIND`` enumerates the named failure modes the spec
  explicitly calls out.
- "Diagnostics use the same vocabulary as workspace status language."
  → this module is in ``novie_protocol`` so frontend code can import
  the same Literal type without a separate copy.

Existing W5 wire fields (already on stalled / cancellation / wait
diagnostics) keep their names — this module groups them so future
diagnostic surfaces stay aligned.
"""
from __future__ import annotations

from typing import Literal


# ── Per-agent diagnostic surface ────────────────────────────────────────────


AuthMode = Literal[
    "none",                 # dev — no auth required (NOVIE_RUNTIME_MODE != production)
    "signed_headers",       # production default — A2A shared-secret HMAC
    "registration_token",   # registration-only bearer token
    "external_bearer",      # bearer token issued by an external IdP
    "unknown",              # we can't tell from the manifest alone
]

ConformanceStatus = Literal[
    "passed",       # last conformance run was green
    "failed",       # last run had any fail probe
    "running",      # in flight
    "skipped",      # intentionally not run (dev / manual override)
    "unknown",      # never run for this agent_id+version
]

DurabilityClaim = Literal[
    "none",          # no durability — restart drops in-flight state
    "result_cache",  # one-shot replays after restart
    "task_store",    # full task lifecycle survives restart
]


# ── Run-detail failure modes ────────────────────────────────────────────────


DiagnosticKind = Literal[
    # Pre-flight + connection
    "agent_unreachable",            # transport error / DNS / connect refused
    "agent_health_degraded",        # /healthz returns non-200
    "manifest_unavailable",         # /.well-known/agent.json failed

    # One-shot contract failures
    "oneshot_contract_failure",     # /invoke or /stream returned a malformed envelope
    "oneshot_idempotency_violation",# duplicate Idempotency-Key returned different bodies
    "create_accepted_no_result",    # POST returned 202 but no result available

    # Worker / task runtime
    "worker_runtime_failure",       # task ended with status=failed + reason
    "duplicate_active_task",        # duplicate task accepted as new (idempotency missing)
    "task_event_stream_malformed",  # GET /tasks/{id}/events returned wrong shape
    "task_cancellation_unsupported",# cancel attempted on agent that doesn't support it

    # Platform workflow
    "platform_workflow_stalled",    # _detect_stalled fired (pre_stream_chunk / no_progress)
    "platform_workflow_failed",     # workflow itself raised before agent invocation

    # Liveness (already wired in W5 — duplicated here so the vocabulary is one place)
    "pre_stream_chunk",
    "no_progress",
    "human_wait_timeout",

    # Cancellation source (already wired in W5)
    "cancelled_by_user",
    "cancelled_by_worker",

    # Callback path
    "callback_denied",              # platform rejected agent callback (binding_denied)
    "callback_transport_error",     # agent couldn't reach platform for a callback

    # Side surfaces
    "knowledge_ingestion_degraded", # Knowledge write path returned non-OK
    "secret_unavailable",           # required secret missing in agent env
]


# ── Constants ───────────────────────────────────────────────────────────────


# Bumped together with the platform protocol version.
PLATFORM_PROTOCOL_VERSION: str = "v2"


__all__ = [
    "AuthMode",
    "ConformanceStatus",
    "DiagnosticKind",
    "DurabilityClaim",
    "PLATFORM_PROTOCOL_VERSION",
]
