from __future__ import annotations

from dataclasses import replace

import pytest

import dynamislm.comparability.res70_registry as res70_registry
from dynamislm import (
    BridgeAuthorityOrigin,
    ComparabilityDimension,
    CrossSourceComparabilityRequest,
    InstanceIdentifier,
    ObservationAuthorityReference,
    RegistryReference,
    ScientificIdentifier,
    UnitReference,
    assess_cross_source_comparability,
    validate_cross_source_decision,
)
from dynamislm.comparability import (
    ComparabilityState,
    RES70ComparabilityAuthorityError,
    validate_pairwise_decisions,
)
from dynamislm.measurement.observation import ScientificMeasurementObservation
from test_kernel import _derived_observation


def _reference(object_type: str, key: str, label: str) -> RegistryReference:
    return RegistryReference(ScientificIdentifier("dynamislm", object_type, key, "1.0.0"), label)


def _claim() -> RegistryReference:
    return _reference("claim-intent", "longitudinal-change", "Longitudinal change")


def _unit() -> UnitReference:
    return UnitReference(ScientificIdentifier("dynamislm", "unit", "meter", "1.0.0"), "m")


def _observation_pair() -> tuple[
    ScientificMeasurementObservation, ScientificMeasurementObservation
]:
    unit = _unit()
    left = _derived_observation("res70-compare-left", value=1.0)
    identity = replace(left.identity, processing=replace(left.identity.processing, unit=unit))
    left = replace(left, identity=identity, result=replace(left.result, unit=unit))
    right = _derived_observation("res70-compare-right", value=2.0)
    right = replace(right, identity=identity, result=replace(right.result, unit=unit))
    return left, right


def _request(
    left: ScientificMeasurementObservation,
    right: ScientificMeasurementObservation,
) -> CrossSourceComparabilityRequest:
    return CrossSourceComparabilityRequest(
        request_id=InstanceIdentifier("cross-source-comparability-request", "res70-test"),
        left_observation=ObservationAuthorityReference.from_observation(left),
        right_observation=ObservationAuthorityReference.from_observation(right),
        claim_intent=_claim(),
    )


def test_identical_complete_measurements_are_directly_comparable() -> None:
    left, right = _observation_pair()
    request = _request(left, right)

    decision = assess_cross_source_comparability(request, (left, right))

    assert decision.state is ComparabilityState.COMPARABLE
    assert decision.bridge_application_reference is None
    assert all(
        item.status in (item.status.MATCH, item.status.NOT_APPLICABLE)
        for item in decision.dimension_findings
    )
    validate_cross_source_decision(
        decision,
        request,
        bridge_registry=res70_registry.CANONICAL_BRIDGE_REGISTRY,
        rule_registry=res70_registry.RES70_COMPARABILITY_RULE_REGISTRY,
    )


def test_same_label_different_measurand_is_not_comparable() -> None:
    left, right = _observation_pair()
    changed_semantic = replace(
        right.identity.semantic,
        measurand=_reference("measurand", "different", "Same display label"),
    )
    right = replace(right, identity=replace(right.identity, semantic=changed_semantic))
    request = _request(left, right)

    decision = assess_cross_source_comparability(request, (left, right))

    assert decision.state is ComparabilityState.NOT_COMPARABLE
    assert "MEASURAND_MISMATCH" in decision.reason_codes
    assert any(
        item.dimension is ComparabilityDimension.MEASURAND and item.status.value == "MISMATCH"
        for item in decision.dimension_findings
    )


def test_tampered_observation_hash_cannot_mint_comparability() -> None:
    left, right = _observation_pair()
    request = replace(
        _request(left, right),
        left_observation=replace(
            ObservationAuthorityReference.from_observation(left),
            result_hash="sha256:" + "0" * 64,
        ),
    )

    with pytest.raises(RES70ComparabilityAuthorityError, match="exact observation"):
        assess_cross_source_comparability(request, (left, right))


def test_pairwise_validation_rejects_duplicate_pairs_without_transitive_closure() -> None:
    left, right = _observation_pair()
    request = _request(left, right)
    decision = assess_cross_source_comparability(request, (left, right))

    validate_pairwise_decisions((decision,))
    with pytest.raises(ValueError, match="duplicate pairs"):
        validate_pairwise_decisions((decision, decision))


def test_caller_supplied_synthetic_registry_cannot_authorize_comparability() -> None:
    left, right = _observation_pair()
    bridge_key = _reference("comparability-bridge", "synthetic", "Synthetic bridge")
    synthetic_registry = res70_registry.BridgeRegistry(
        authority_origin=BridgeAuthorityOrigin.SYNTHETIC_TEST.value
    )
    request = _request(left, right)

    with pytest.raises(RES70ComparabilityAuthorityError, match="caller-supplied"):
        assess_cross_source_comparability(
            request,
            (left, right),
            bridge_registry=synthetic_registry,
        )

    assert bridge_key.stable_id not in {
        item.bridge_reference.stable_id for item in synthetic_registry.entries
    }
