from __future__ import annotations

from dynamislm import (
    AnalysisCapability,
    AnalysisCapabilityDisposition,
    AnalysisClass,
    AnalysisEstimandLevel,
    AnalysisLevelIdentity,
    AnalysisUnitOfAnalysis,
    ApplicabilityAssessment,
    ApplicabilityAxis,
    ApplicabilityDecision,
    BridgeAuthorityOrigin,
    BridgeInvertibility,
    BridgeMode,
    BridgeRegistration,
    ClaimIntent,
    ClaimTarget,
    ComparabilityDimension,
    CrossSourceComparabilityRequest,
    InstanceIdentifier,
    MeasurementClaimLevel,
    MetadataEntry,
    ObservationAuthorityReference,
    RegistryReference,
    ScientificIdentifier,
    SemanticIdentityKey,
    canonical_hash,
    canonical_json,
    from_canonical_json,
)
from test_kernel import _derived_observation


def _reference(object_type: str, key: str, label: str) -> RegistryReference:
    return RegistryReference(ScientificIdentifier("dynamislm", object_type, key, "1.0.0"), label)


def test_observation_authority_reference_binds_all_component_hashes() -> None:
    observation = _derived_observation("res70-reference")
    reference = ObservationAuthorityReference.from_observation(observation)

    assert reference.observation_hash == canonical_hash(observation)
    assert reference.identity_hash == canonical_hash(observation.identity)
    reference.validate_observation(observation)

    restored = from_canonical_json(canonical_json(reference), ObservationAuthorityReference)
    assert restored == reference


def test_cross_source_request_is_pairwise_and_label_agnostic() -> None:
    left = _derived_observation("res70-left")
    right = _derived_observation("res70-right")
    request = CrossSourceComparabilityRequest(
        request_id=InstanceIdentifier("cross-source-comparability-request", "request-1"),
        left_observation=ObservationAuthorityReference.from_observation(left),
        right_observation=ObservationAuthorityReference.from_observation(right),
        claim_intent=_reference("claim-intent", "longitudinal-change", "longitudinal change"),
        requested_dimensions=(ComparabilityDimension.MEASURAND, ComparabilityDimension.UNIT),
    )

    assert request.left_observation.observation_id != request.right_observation.observation_id
    assert request.request_hash == canonical_hash(request)
    assert from_canonical_json(canonical_json(request), CrossSourceComparabilityRequest) == request


def test_semantic_bridge_keys_exclude_observation_instances() -> None:
    observation = _derived_observation("res70-key")
    key = SemanticIdentityKey.from_identity(observation.identity)

    assert all(
        not any(
            isinstance(item.value, str) and item.value.startswith(prefix)
            for prefix in ("observation:", "artifact:", "acquisition:", "session:")
        )
        for item in key.components
    )
    assert key == SemanticIdentityKey.from_identity(observation.identity)


def test_production_bridge_contract_is_versioned_and_hashable() -> None:
    observation = _derived_observation("res70-bridge")
    source_key = SemanticIdentityKey.from_identity(observation.identity)
    target_key = SemanticIdentityKey(
        tuple(MetadataEntry(item.key, f"target:{item.value}") for item in source_key.components)
    )
    bridge = BridgeRegistration(
        bridge_reference=_reference("comparability-bridge", "example-v1", "Example bridge"),
        source_semantic_key=source_key,
        target_semantic_key=target_key,
        claim_scope=(_reference("claim-intent", "longitudinal-change", "longitudinal change"),),
        bridge_mode=BridgeMode.DECLARATIVE_EQUIVALENCE,
        transformation_operation=None,
        source_units=(),
        target_units=(),
        fixed_parameters=(),
        domain_constraints=(MetadataEntry("domain", "synthetic-test"),),
        applicability_conditions=(MetadataEntry("condition", "validated domain"),),
        method_version=_reference("bridge-method", "example-v1", "Example bridge method"),
        evidence_references=(_reference("evidence", "example", "Example evidence"),),
        evidence_applicability=(),
        uncertainty_model=None,
        invertibility=BridgeInvertibility.EXACT,
        lossiness_description=None,
        provenance_rule=_reference("provenance-rule", "bridge-v1", "Bridge provenance"),
        registry_version="res70-1.0.0",
        authority_origin=BridgeAuthorityOrigin.SYNTHETIC_TEST,
    )

    assert bridge.canonical_bridge_hash == canonical_hash(
        {
            "bridge_reference": bridge.bridge_reference,
            "source_semantic_key": bridge.source_semantic_key,
            "target_semantic_key": bridge.target_semantic_key,
            "claim_scope": bridge.claim_scope,
            "bridge_mode": bridge.bridge_mode,
            "transformation_operation": bridge.transformation_operation,
            "source_units": bridge.source_units,
            "target_units": bridge.target_units,
            "fixed_parameters": bridge.fixed_parameters,
            "domain_constraints": bridge.domain_constraints,
            "applicability_conditions": bridge.applicability_conditions,
            "method_version": bridge.method_version,
            "evidence_references": bridge.evidence_references,
            "evidence_applicability": bridge.evidence_applicability,
            "uncertainty_model": bridge.uncertainty_model,
            "invertibility": bridge.invertibility,
            "lossiness_description": bridge.lossiness_description,
            "provenance_rule": bridge.provenance_rule,
            "registry_version": bridge.registry_version,
            "authority_origin": bridge.authority_origin,
        }
    )
    assert from_canonical_json(canonical_json(bridge), BridgeRegistration) == bridge


def test_analysis_level_and_capability_preserve_estimand_identity() -> None:
    level = AnalysisLevelIdentity(
        unit_of_analysis=AnalysisUnitOfAnalysis.ATHLETE,
        estimand_level=AnalysisEstimandLevel.WITHIN_ATHLETE,
        subject_key="athlete_id",
        clustering_keys=("athlete_id", "session_id"),
        grouping_keys=(),
    )
    capability = AnalysisCapability(
        capability_reference=_reference("analysis-capability", "scalar-change", "Scalar change"),
        analysis_class=AnalysisClass.SCALAR_ABSOLUTE_CHANGE,
        registered_operation_reference=_reference(
            "registered-operation", "absolute-change", "Absolute change"
        ),
        estimator_reference=_reference("estimator", "absolute-change", "Absolute change"),
        disposition=AnalysisCapabilityDisposition.IMPLEMENTED,
        required_support_shape=("exactly-two-scalar-entries",),
        required_identity_dimensions=("MEASURAND", "UNIT"),
        required_comparability_states=(),
        required_bridge_execution=False,
        required_level_of_analysis=(AnalysisEstimandLevel.WITHIN_ATHLETE,),
        required_statistical_authority=(),
        required_evidence_axes=(),
        required_context=(),
        output_claim_floor="NUMERICAL_CHANGE",
        registry_version="res70-1.0.0",
    )

    assert level.level_key == "ATHLETE:WITHIN_ATHLETE"
    assert capability.canonical_capability_hash.startswith("sha256:")
    assert from_canonical_json(canonical_json(level), AnalysisLevelIdentity) == level


def test_evidence_applicability_is_a_vector_without_confidence_collapse() -> None:
    claim = _reference("claim-intent", "observed", "Observed value")
    applicability = tuple(
        ApplicabilityAssessment(
            axis=axis,
            decision=ApplicabilityDecision.SUPPORTED,
            required_for_claim=True,
            evidence_references=(_reference("evidence", axis.value.lower(), axis.value),),
            authority_references=(),
            conditions=(),
            rationale=f"synthetic {axis.value}",
        )
        for axis in ApplicabilityAxis
    )
    intent = ClaimIntent(
        claim_reference=claim,
        measurement_level=MeasurementClaimLevel.OBSERVED_VALUE,
        relationship_level=None,
        predictive_intent=None,
        target=ClaimTarget.INDIVIDUAL,
        analysis_reference=None,
        evidence_applicability_reference=None,
        decision_criterion_reference=None,
    )

    assert len(applicability) == 5
    assert not hasattr(intent, "confidence_score")
    assert all(item.required_for_claim for item in applicability)
