"""Agent authoring contracts shared by the platform and SDK."""

from .agent_yaml import (
    AgentType,
    AgentYamlAdvanced,
    AgentYamlConfig,
    AgentYamlGovernance,
    AgentYamlIdentity,
    AgentYamlInputs,
    AgentYamlOutputs,
    AgentYamlRouting,
    AgentYamlRuntime,
    GovernanceRisk,
    GovernanceSideEffect,
    RuntimeDuration,
)
from .manifest_generator import generate_agent_manifest
from .manifest_validator import (
    ManifestValidationIssue,
    ManifestValidationResult,
    Severity,
    validate_agent_yaml,
    validate_agent_yaml_and_manifest,
    validate_generated_manifest,
)

__all__ = [
    "AgentType",
    "AgentYamlAdvanced",
    "AgentYamlConfig",
    "AgentYamlGovernance",
    "AgentYamlIdentity",
    "AgentYamlInputs",
    "AgentYamlOutputs",
    "AgentYamlRouting",
    "AgentYamlRuntime",
    "GovernanceRisk",
    "GovernanceSideEffect",
    "RuntimeDuration",
    "ManifestValidationIssue",
    "ManifestValidationResult",
    "Severity",
    "generate_agent_manifest",
    "validate_agent_yaml",
    "validate_agent_yaml_and_manifest",
    "validate_generated_manifest",
]
