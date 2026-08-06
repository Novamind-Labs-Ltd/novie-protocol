"""One feature vocabulary, two carriers (ADR-133 §4)."""

from __future__ import annotations

from novie_protocol.contracts.executor_features import (
    ExecutorFeatureSet,
    features_from_mapping,
)


def test_manifest_spelling_maps_to_the_vocabulary() -> None:
    features = features_from_mapping(
        {"steerable": True, "sandbox": "harness_provided"}
    )
    assert features.steerable is True
    assert features.sandbox_mode == "harness_provided"


def test_harness_profile_legacy_spelling_maps_too() -> None:
    features = features_from_mapping(
        {"supports_steer": True, "supports_cancel": True}
    )
    assert features.steerable is True
    assert features.cancellable is True


def test_requirements_accept_both_spellings() -> None:
    features = ExecutorFeatureSet(steerable=True, sandbox_mode="harness_provided")
    assert features.satisfies({"steerable": True}) is True
    assert features.satisfies({"supports_steer": True}) is True
    assert features.satisfies({"sandbox": "harness_provided"}) is True
    assert features.satisfies({"sandbox_mode": "harness_provided"}) is True


def test_unknown_requirements_fail_closed() -> None:
    assert ExecutorFeatureSet().satisfies({"telepathy": True}) is False


def test_undeclared_means_unoffered() -> None:
    features = features_from_mapping({})
    assert features.steerable is False
    assert features.sandbox_mode == "none"
    assert features.satisfies({"steerable": True}) is False


def test_invalid_sandbox_mode_degrades_to_none() -> None:
    assert features_from_mapping({"sandbox": "yolo"}).sandbox_mode == "none"
