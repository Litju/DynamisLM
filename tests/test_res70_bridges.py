from __future__ import annotations

from dataclasses import replace

import dynamislm.comparability.res70_registry as res70_registry
from dynamislm import (
    BridgeApplicationRequest,
    BridgeAuthorityOrigin,
    BridgeInvertibility,
    BridgeMode,
    BridgeRegistration,
    CrossSourceComparabilityRequest,
    InstanceIdentifier,
    MetadataEntry,
    ObservationAuthorityReference,
    RegistryReference,
    ScientificIdentifier,
    SemanticIdentityKey,
    UnitReference,
    assess_cross_source_comparability,
    execute_registered_bridge,
)
from dynamislm.comparability import (
    RES70_AFFINE_BRIDGE_OPERATION,
    RES70_BRIDGE_PROVENANCE_RULE,
    BridgeExecutionResult,
    BridgeExecutionStatus,
    BridgeRegistry,
)
from dynamislm.measurement.observation import ScientificMeasurementObservation
from dynamislm.measurement.taxonomy import ValueOrigin
from test_kernel import _derived_observation


def _reference(object_type: str, key: str, label: str) -> RegistryReference:
    return RegistryReference(ScientificIdentifier("dynamislm", object_type, key, "1.0.0"), label)


def _unit() -> UnitReference:
    return UnitReference(ScientificIdentifier("dynamislm", "unit", "meter", "1.0.0"), "m")


def _bridge_fixture() -> tuple[
    ScientificMeasurementObservation,
    ScientificMeasurementObservation,
    BridgeRegistration,
    BridgeRegistry,
    RegistryReference,
]:
    unit = _unit()
    source = _derived_observation("res70-bridge-source", value=1.0)
    source_identity = replace(
        source.identity,
        processing=replace(source.identity.processing, unit=unit),
    )
    source = replace(source, identity=source_identity, result=replace(source.result, unit=unit))
    target_identity = replace(
        source_identity,
        identity_id=ScientificIdentifier("dynamislm", "measurement", "target-identity", "1.0.0"),
        acquisition=replace(
            source_identity.acquisition,
            device=_reference("device", "target-device", "Target device"),
        ),
    )
    target = _derived_observation("res70-bridge-target", value=3.0)
    target = replace(target, identity=target_identity, result=replace(target.result, unit=unit))
    claim = _reference("claim-intent", "longitudinal-change", "Longitudinal change")
    bridge = BridgeRegistration(
        bridge_reference=_reference("comparability-bridge", "device-v1", "Device bridge"),
        source_semantic_key=SemanticIdentityKey.from_identity(source_identity),
        target_semantic_key=SemanticIdentityKey.from_identity(target_identity),
        claim_scope=(claim,),
        bridge_mode=BridgeMode.NUMERICAL_TRANSFORMATION,
        transformation_operation=RES70_AFFINE_BRIDGE_OPERATION,
        source_units=(unit,),
        target_units=(unit,),
        fixed_parameters=(MetadataEntry("scale", 2.0), MetadataEntry("offset", 1.0)),
        domain_constraints=(),
        applicability_conditions=(MetadataEntry("domain", "validated"),),
        method_version=_reference("bridge-method", "device-v1", "Device bridge method"),
        evidence_references=(_reference("evidence", "device-study", "Device study"),),
        evidence_applicability=(),
        uncertainty_model=None,
        invertibility=BridgeInvertibility.EXACT,
        lossiness_description=None,
        provenance_rule=RES70_BRIDGE_PROVENANCE_RULE,
        registry_version="1.0.0",
        authority_origin=BridgeAuthorityOrigin.PRODUCTION,
    )
    registry = BridgeRegistry(entries=(bridge,))
    return source, target, bridge, registry, claim


def test_registered_numeric_bridge_creates_new_value_and_provenance() -> None:
    source, target, bridge, registry, claim = _bridge_fixture()
    original_registry = res70_registry.CANONICAL_BRIDGE_REGISTRY
    res70_registry.CANONICAL_BRIDGE_REGISTRY = registry
    try:
        result = execute_registered_bridge(
            BridgeApplicationRequest(
                request_id=InstanceIdentifier("bridge-request", "res70-positive"),
                source_observation=ObservationAuthorityReference.from_observation(source),
                bridge_reference=bridge.bridge_reference,
                claim_intent=claim,
                target_identity=target.identity,
            ),
            source,
        )
    finally:
        res70_registry.CANONICAL_BRIDGE_REGISTRY = original_registry

    assert isinstance(result, BridgeExecutionResult)
    assert result.status is BridgeExecutionStatus.EXECUTED
    assert result.transformed_observation is not None
    assert result.transformed_observation.result.value.value == 3.0  # type: ignore[union-attr]
    assert (
        result.transformed_observation.result.classification.value_origin
        is ValueOrigin.DYNAMISLM_DERIVED
    )
    assert result.processing_run is not None
    assert result.provenance is not None
    assert result.output_observation_hash is not None
    assert result.transformed_observation.observation_id != source.observation_id


def test_executed_bridge_supports_conditional_pairwise_comparability() -> None:
    source, target, bridge, registry, claim = _bridge_fixture()
    original_registry = res70_registry.CANONICAL_BRIDGE_REGISTRY
    res70_registry.CANONICAL_BRIDGE_REGISTRY = registry
    try:
        execution = execute_registered_bridge(
            BridgeApplicationRequest(
                request_id=InstanceIdentifier("bridge-request", "res70-comparison"),
                source_observation=ObservationAuthorityReference.from_observation(source),
                bridge_reference=bridge.bridge_reference,
                claim_intent=claim,
                target_identity=target.identity,
            ),
            source,
        )
        request = CrossSourceComparabilityRequest(
            request_id=InstanceIdentifier(
                "cross-source-comparability-request", "res70-bridge-comparison"
            ),
            left_observation=ObservationAuthorityReference.from_observation(source),
            right_observation=ObservationAuthorityReference.from_observation(target),
            claim_intent=claim,
        )
        decision = assess_cross_source_comparability(
            request,
            (source, target),
            bridge_execution=execution,  # type: ignore[arg-type]
        )
    finally:
        res70_registry.CANONICAL_BRIDGE_REGISTRY = original_registry

    assert isinstance(execution, BridgeExecutionResult)
    assert decision.state.value == "COMPARABLE_WITH_CONDITIONS"
    assert decision.bridge_application_reference == bridge.bridge_reference


def test_declared_bridge_without_execution_never_supports_transformed_values() -> None:
    source, target, bridge, registry, claim = _bridge_fixture()
    original_registry = res70_registry.CANONICAL_BRIDGE_REGISTRY
    res70_registry.CANONICAL_BRIDGE_REGISTRY = registry
    try:
        request = CrossSourceComparabilityRequest(
            request_id=InstanceIdentifier("cross-source-comparability-request", "res70-unexecuted"),
            left_observation=ObservationAuthorityReference.from_observation(source),
            right_observation=ObservationAuthorityReference.from_observation(target),
            claim_intent=claim,
        )
        decision = assess_cross_source_comparability(request, (source, target))
    finally:
        res70_registry.CANONICAL_BRIDGE_REGISTRY = original_registry

    assert decision.state.value == "REQUIRES_TRANSFORMATION"
    assert "RES70_BRIDGE_NOT_EXECUTED" in decision.reason_codes
    assert decision.transformations_required
