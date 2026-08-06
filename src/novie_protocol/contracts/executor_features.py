"""One feature vocabulary for every executor and harness (ADR-133 §4).

Two parallel declarations grew independently — ``HarnessProfile`` (in-process
conversation harnesses: ``supports_steer`` …) and manifest
``executor_features`` (A2A providers: ``steerable`` …). Same questions, two
spellings. This module is the single vocabulary both carriers map onto, so a
resolver can ask "can this executor be steered?" without knowing which kind
of executor it is asking about.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

FEATURE_KEYS: tuple[str, ...] = (
    "steerable",
    "cancellable",
    "resettable",
    "persistent_session",
    "native_skills",
    "structured_output",
    "subagents",
)

#: How an executor obtains its working tree. ``harness_provided`` is the only
#: ADR-070-compatible mode for repository work.
SANDBOX_MODES: tuple[str, ...] = ("harness_provided", "native", "none")

#: HarnessProfile's legacy spellings → the canonical key.
_LEGACY_ALIASES: Mapping[str, str] = {
    "supports_steer": "steerable",
    "supports_cancel": "cancellable",
    "supports_reset": "resettable",
}


@dataclass(frozen=True, slots=True)
class ExecutorFeatureSet:
    steerable: bool = False
    cancellable: bool = False
    resettable: bool = False
    persistent_session: bool = False
    native_skills: bool = False
    structured_output: bool = False
    subagents: bool = False
    sandbox_mode: str = "none"

    def satisfies(self, required: Mapping[str, Any]) -> bool:
        """True when every requested feature is actually offered.

        Unknown requirement keys fail closed — a requirement this vocabulary
        cannot express cannot be shown to be satisfied.
        """
        for raw_key, wanted in required.items():
            key = _LEGACY_ALIASES.get(raw_key, raw_key)
            if key in ("sandbox_mode", "sandbox"):
                if str(wanted) != self.sandbox_mode:
                    return False
                continue
            if key not in FEATURE_KEYS:
                return False
            if bool(wanted) and not getattr(self, key):
                return False
        return True


def features_from_mapping(raw: Mapping[str, Any] | None) -> ExecutorFeatureSet:
    """Read a feature set from either carrier's spelling.

    Accepts canonical keys, HarnessProfile legacy keys, and the manifest's
    ``sandbox`` shorthand. Undeclared means unoffered (conservative default —
    an executor that says nothing is assumed to do nothing special).
    """
    data = dict(raw or {})
    flags: dict[str, Any] = {}
    for key, value in data.items():
        canonical = _LEGACY_ALIASES.get(key, key)
        if canonical in FEATURE_KEYS:
            flags[canonical] = bool(value)
    sandbox = str(data.get("sandbox_mode") or data.get("sandbox") or "none")
    if sandbox not in SANDBOX_MODES:
        sandbox = "none"
    return ExecutorFeatureSet(**flags, sandbox_mode=sandbox)


__all__ = [
    "FEATURE_KEYS",
    "SANDBOX_MODES",
    "ExecutorFeatureSet",
    "features_from_mapping",
]
