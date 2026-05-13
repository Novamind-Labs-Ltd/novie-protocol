"""Stable Knowledge ingestion raw surface on Platform Postgres.

The Knowledge service connects read-only using the ``knowledge_reader`` role.

``v_memory_entries`` and the ``memory_entries`` table were retired (migration 017).
Curated long-form knowledge belongs in the independent Knowledge service.

Remaining Platform SQL views (see ``010_knowledge_raw_surface.sql`` and related DDL):

- ``v_gate_decisions`` — HITL outcomes for curator attribution
- ``v_artifact_refs`` — artifact index metadata for ingestion pipelines
- ``v_checkpoint_signals`` — checkpoint-derived signals for ingestion pipelines
  (see ``009_checkpoint_signals.sql``)
- ``v_audit_events`` — audit stream filtered by Knowledge consumers when needed
- ``v_session_final_summaries`` — per-session terminal summaries for retrieval
  injection and KB ingestion pipelines
"""
from __future__ import annotations

KNOWLEDGE_READER_ROLE = "knowledge_reader"
"""Read-only role granted to Knowledge DB users (SELECT on stable views only)."""

PLATFORM_RAW_SURFACE_VIEWS: dict[str, str] = {
    "v_gate_decisions": "HITL gate resolutions for curator attribution.",
    "v_artifact_refs": "Artifact index metadata references.",
    "v_checkpoint_signals": "Checkpoint-derived signals for incremental ingestion.",
    "v_audit_events": "Audit events Knowledge may filter by kind.",
    "v_session_final_summaries": "Session terminal summaries for retrieval and ingestion.",
}
