from __future__ import annotations

import inspect
import json
from dataclasses import replace
from pathlib import Path

import pytest

from dynamislm import (
    SERIALIZATION_VERSION,
    InstanceIdentifier,
    MetadataEntry,
    ScalarValue,
    ScientificRole,
    SerializationError,
    ValueOrigin,
    canonical_hash,
    canonical_json,
    from_canonical_json,
)
from dynamislm.comparability import ComparabilityReasonCode, ComparabilityState
from dynamislm.measurement.cmj import (
    CMJ_BALLISTIC_VERTICAL_MOTION_ASSUMPTION,
    CMJ_FLIGHT_TIME_JUMP_HEIGHT_METHOD,
    CMJ_FLIGHT_TIME_JUMP_HEIGHT_METHOD_V1,
    CMJ_FLIGHT_TIME_JUMP_HEIGHT_METHOD_V2,
    CMJ_JUMP_HEIGHT_MEASURAND,
    CMJ_JUMP_HEIGHT_METRIC,
    CMJ_LOCAL_GRAVITY_APPLICABLE_ASSUMPTION,
    CMJ_NEGLIGIBLE_AIR_RESISTANCE_ASSUMPTION,
    CMJ_REGISTERED_FLIGHT_LOADING_APPLICABILITY_ASSUMPTION,
    CMJ_REGISTERED_MECHANICAL_SYSTEM_CONTRACT_ASSUMPTION,
    CMJ_SUPPORTED_SYSTEM_STABLE_ASSUMPTION,
    CMJ_TAKEOFF_LANDING_HEIGHT_EQUIVALENCE_ASSUMPTION,
    CMJ_TAKEOFF_VELOCITY_EVENT_SAMPLE_CONVENTION,
    CMJ_TAKEOFF_VELOCITY_JUMP_HEIGHT_METHOD,
    RES47_DECISION_FLIGHT_TIME_BALLISTIC_APPLICABILITY,
    RES48_DECISION_FLIGHT_TIME_V2_LOADING_AUTHORITY,
    STANDARD_GRAVITY,
    CMJEventOccurrence,
    CMJForceInput,
    CMJIntegrationInterval,
    CMJJumpHeightResult,
    CMJMeasurementIdentity,
    CMJMechanicalSystemContract,
    CMJThresholdDirection,
    FlightBallisticApplicability,
    FlightLoadingState,
    FlightTimeV2EstimatorParameters,
    InitialVelocityCondition,
    JumpHeightEstimatorParameters,
    QualifiedZeroVelocityReference,
    SupportedSystemComVelocityResult,
    assess_cmj_jump_height_comparability,
    compare_cmj_jump_height_estimates,
    defer_com_displacement_jump_height,
    derive_net_vertical_force,
    derive_physical_system_mass,
    derive_supported_system_com_acceleration,
    derive_supported_system_com_velocity,
    detect_landing,
    detect_movement_onset,
    detect_takeoff,
    estimate_flight_time_jump_height,
    estimate_takeoff_velocity_jump_height,
    refusal_for_cmj_jump_height_comparability,
    refuse_unregistered_cmj_jump_height_estimator,
)
from dynamislm.provenance import LineageRelation
from dynamislm.refusal import RefusalReasonCode, RefusalResult
from test_cmj import (
    _absolute_parameters,
    _event_baseline,
    _event_input,
    _event_trace,
    _local_gravity,
    _mechanics_contract,
    _mechanics_fixture,
    _onset_parameters,
)


def _flight_fixture(
    suffix: str,
    *,
    gravity_suffix: str | None = None,
    external_loading: str = "none",
    loading_state: FlightLoadingState = FlightLoadingState.UNLOADED,
) -> tuple[CMJJumpHeightResult, CMJEventOccurrence, CMJEventOccurrence, CMJForceInput]:
    takeoff, landing, force = _flight_events(
        suffix,
        external_loading=external_loading,
    )
    gravity = _local_gravity(gravity_suffix or suffix)
    includes_supported_external_load = (
        loading_state is FlightLoadingState.STABLE_ATTACHED_SUPPORTED_LOAD
    )
    contract = _mechanics_contract(
        includes_supported_external_load=includes_supported_external_load
    )
    applicability = FlightBallisticApplicability.from_takeoff_event(
        force.observation,
        takeoff,
        loading_state,
        contract,
    )
    result = estimate_flight_time_jump_height(
        takeoff,
        landing,
        gravity,
        source_observation=force.observation,
        ballistic_applicability=applicability,
    )
    assert isinstance(result, CMJJumpHeightResult)
    return result, takeoff, landing, force


def _flight_events(
    suffix: str,
    *,
    external_loading: str = "none",
) -> tuple[CMJEventOccurrence, CMJEventOccurrence, CMJForceInput]:
    force = _event_input(
        suffix,
        _event_trace(),
        external_loading=external_loading,
    )
    baseline = _event_baseline(force)
    onset = detect_movement_onset(force, baseline, _onset_parameters(baseline))
    assert isinstance(onset, CMJEventOccurrence)
    takeoff = detect_takeoff(
        force,
        _absolute_parameters(
            20.0,
            CMJThresholdDirection.BELOW_THRESHOLD,
            search_start_index=9,
        ),
    )
    assert isinstance(takeoff, CMJEventOccurrence)
    landing = detect_landing(
        force,
        takeoff,
        _absolute_parameters(
            20.0,
            CMJThresholdDirection.ABOVE_THRESHOLD,
            search_start_index=None,
        ),
    )
    assert isinstance(landing, CMJEventOccurrence)
    return takeoff, landing, force


def _velocity_fixture(
    suffix: str,
    *,
    samples: tuple[float, ...] = (100.0, 100.0, 100.0, 200.0, 300.0, 0.0, 0.0, 100.0),
    gravity_suffix: str | None = None,
    external_loading: str = "none",
) -> tuple[
    CMJJumpHeightResult,
    SupportedSystemComVelocityResult,
    CMJEventOccurrence,
    CMJMechanicalSystemContract,
]:
    gravity = _local_gravity(gravity_suffix or suffix)
    _, total, weight, contract = _mechanics_fixture(
        suffix,
        samples,
        external_loading=external_loading,
        weighing_end_index=3,
    )
    net = derive_net_vertical_force(total, weight, contract)
    assert not isinstance(net, RefusalResult)
    mass = derive_physical_system_mass(weight, gravity)
    assert not isinstance(mass, RefusalResult)
    acceleration = derive_supported_system_com_acceleration(net, mass, contract)
    assert not isinstance(acceleration, RefusalResult)
    interval = CMJIntegrationInterval.explicit_sample(
        acceleration.series.series_id,
        2,
        len(samples) - 1,
    )
    reference = QualifiedZeroVelocityReference.from_system_weight(weight, 2)
    velocity = derive_supported_system_com_velocity(acceleration, interval, reference)
    assert isinstance(velocity, SupportedSystemComVelocityResult)
    takeoff = detect_takeoff(
        total,
        _absolute_parameters(
            20.0,
            CMJThresholdDirection.BELOW_THRESHOLD,
            search_start_index=0,
        ),
    )
    assert isinstance(takeoff, CMJEventOccurrence)
    result = estimate_takeoff_velocity_jump_height(velocity, takeoff, gravity)
    assert isinstance(result, CMJJumpHeightResult)
    return result, velocity, takeoff, contract


def _historical_v1_result(result: CMJJumpHeightResult) -> CMJJumpHeightResult:
    """Build the exact pre-RES-47 V1 shape from an equivalent V2 fixture."""

    import dynamislm.measurement.cmj.jump_height as jump_height

    assert isinstance(result.parameters, FlightTimeV2EstimatorParameters)
    assert isinstance(result.observation.identity, CMJMeasurementIdentity)
    historical_parameters = JumpHeightEstimatorParameters(
        gravity=result.parameters.gravity,
        source_observation_id=result.parameters.source_observation_id,
        source_signal_id=result.parameters.source_signal_id,
        source_artifact_id=result.parameters.source_artifact_id,
        source_acquisition_id=result.parameters.source_acquisition_id,
        source_measurement_identity_id=result.parameters.source_measurement_identity_id,
        source_timebase=result.parameters.source_timebase,
        takeoff_event_id=result.parameters.takeoff_event_id,
        takeoff_sample_index=result.parameters.takeoff_sample_index,
        takeoff_event_time_s=result.parameters.takeoff_event_time_s,
        landing_event_id=result.parameters.landing_event_id,
        landing_sample_index=result.parameters.landing_sample_index,
        landing_event_time_s=result.parameters.landing_event_time_s,
        flight_time_s=result.parameters.flight_time_s,
        assumptions=CMJ_FLIGHT_TIME_JUMP_HEIGHT_METHOD_V1.assumptions,
    )
    metadata = jump_height._processing_parameters(
        CMJ_FLIGHT_TIME_JUMP_HEIGHT_METHOD_V1,
        historical_parameters,
        result.takeoff_event,
        result.landing_event,
        None,
        result.observation.identity,
    )
    identity = result.observation.identity
    historical_processing = replace(
        identity.processing,
        estimator=CMJ_FLIGHT_TIME_JUMP_HEIGHT_METHOD_V1.reference,
        registered_operation=CMJ_FLIGHT_TIME_JUMP_HEIGHT_METHOD_V1.operation,
        method_parameters=metadata,
    )
    historical_version = replace(
        identity.version,
        processing_method=CMJ_FLIGHT_TIME_JUMP_HEIGHT_METHOD_V1.operation,
        software_version=jump_height.RES38_SOFTWARE_VERSION,
    )
    historical_identity = replace(
        identity,
        processing=historical_processing,
        version=historical_version,
    )
    historical_run = replace(
        result.observation.provenance.processing_runs[-1],
        method=CMJ_FLIGHT_TIME_JUMP_HEIGHT_METHOD_V1.operation,
        parameters=metadata,
        software_version=jump_height.RES38_SOFTWARE_VERSION,
    )
    authority_ids = {
        RES47_DECISION_FLIGHT_TIME_BALLISTIC_APPLICABILITY.stable_id,
        RES48_DECISION_FLIGHT_TIME_V2_LOADING_AUTHORITY.stable_id,
    }
    historical_provenance = replace(
        result.observation.provenance,
        processing_runs=tuple(
            historical_run if run.output_entity_id == result.observation.observation_id else run
            for run in result.observation.provenance.processing_runs
        ),
        evidence_references=tuple(
            evidence
            for evidence in result.observation.provenance.evidence_references
            if evidence.reference.stable_id not in authority_ids
        ),
        lineage_edges=tuple(
            edge
            for edge in result.observation.provenance.lineage_edges
            if edge.from_id not in authority_ids
        ),
    )
    historical_observation = replace(
        result.observation,
        identity=historical_identity,
        provenance=historical_provenance,
    )
    return CMJJumpHeightResult(
        observation=historical_observation,
        method=CMJ_FLIGHT_TIME_JUMP_HEIGHT_METHOD_V1,
        parameters=historical_parameters,
        takeoff_event=result.takeoff_event,
        landing_event=result.landing_event,
    )


def test_registry_has_one_shared_estimand_and_distinct_methods() -> None:
    assert CMJ_FLIGHT_TIME_JUMP_HEIGHT_METHOD.estimand.reference == CMJ_JUMP_HEIGHT_MEASURAND
    assert CMJ_TAKEOFF_VELOCITY_JUMP_HEIGHT_METHOD.estimand.reference == CMJ_JUMP_HEIGHT_MEASURAND
    assert CMJ_FLIGHT_TIME_JUMP_HEIGHT_METHOD.reference != (
        CMJ_TAKEOFF_VELOCITY_JUMP_HEIGHT_METHOD.reference
    )
    assert CMJ_FLIGHT_TIME_JUMP_HEIGHT_METHOD.operation != (
        CMJ_TAKEOFF_VELOCITY_JUMP_HEIGHT_METHOD.operation
    )
    assert CMJ_JUMP_HEIGHT_METRIC.stable_id.endswith("@1.0.0")


def test_flight_time_v1_is_historical_and_v2_has_distinct_scientific_identity() -> None:
    assert CMJ_FLIGHT_TIME_JUMP_HEIGHT_METHOD_V1.reference != (
        CMJ_FLIGHT_TIME_JUMP_HEIGHT_METHOD_V2.reference
    )
    assert CMJ_FLIGHT_TIME_JUMP_HEIGHT_METHOD_V1.operation != (
        CMJ_FLIGHT_TIME_JUMP_HEIGHT_METHOD_V2.operation
    )
    assert CMJ_FLIGHT_TIME_JUMP_HEIGHT_METHOD_V1.reference.identifier.version != (
        CMJ_FLIGHT_TIME_JUMP_HEIGHT_METHOD_V2.reference.identifier.version
    )
    assert CMJ_FLIGHT_TIME_JUMP_HEIGHT_METHOD_V1.operation.identifier.version != (
        CMJ_FLIGHT_TIME_JUMP_HEIGHT_METHOD_V2.operation.identifier.version
    )
    assert CMJ_FLIGHT_TIME_JUMP_HEIGHT_METHOD_V1.assumptions == (
        CMJ_BALLISTIC_VERTICAL_MOTION_ASSUMPTION,
        CMJ_TAKEOFF_LANDING_HEIGHT_EQUIVALENCE_ASSUMPTION,
        CMJ_NEGLIGIBLE_AIR_RESISTANCE_ASSUMPTION,
        CMJ_LOCAL_GRAVITY_APPLICABLE_ASSUMPTION,
    )
    assert (
        CMJ_SUPPORTED_SYSTEM_STABLE_ASSUMPTION in CMJ_FLIGHT_TIME_JUMP_HEIGHT_METHOD_V2.assumptions
    )
    assert (
        CMJ_REGISTERED_MECHANICAL_SYSTEM_CONTRACT_ASSUMPTION
        in CMJ_FLIGHT_TIME_JUMP_HEIGHT_METHOD_V2.assumptions
    )
    assert (
        CMJ_REGISTERED_FLIGHT_LOADING_APPLICABILITY_ASSUMPTION
        in CMJ_FLIGHT_TIME_JUMP_HEIGHT_METHOD_V2.assumptions
    )
    assert CMJ_FLIGHT_TIME_JUMP_HEIGHT_METHOD is CMJ_FLIGHT_TIME_JUMP_HEIGHT_METHOD_V2


def test_no_unqualified_public_jump_height_operation_exists() -> None:
    import dynamislm.measurement.cmj as cmj

    assert not hasattr(cmj, "estimate_jump_height")
    assert hasattr(cmj, "estimate_flight_time_jump_height")
    assert hasattr(cmj, "estimate_takeoff_velocity_jump_height")


def test_generic_unregistered_jump_height_claim_is_refused() -> None:
    refusal = refuse_unregistered_cmj_jump_height_estimator()

    assert isinstance(refusal, RefusalResult)
    assert RefusalReasonCode.JUMP_HEIGHT_ESTIMATOR_NOT_REGISTERED in refusal.reason_codes


def test_flight_time_uses_exact_recorded_event_times_and_model_classification() -> None:
    result, takeoff, landing, _ = _flight_fixture("flight-exact", gravity_suffix="flight-g")

    assert takeoff.sample_index == 10
    assert landing.sample_index == 15
    assert result.parameters.flight_time_s == landing.event_time_s - takeoff.event_time_s
    assert result.method.equation == "h = g_local * flight_time_s^2 / 8"
    assert result.value_m == pytest.approx((0.005**2) / 8.0)
    assert result.observation.result.classification.value_origin is ValueOrigin.MODEL_ESTIMATE
    assert result.observation.result.classification.scientific_roles == (
        ScientificRole.PERFORMANCE_OUTCOME,
    )
    assert result.method is CMJ_FLIGHT_TIME_JUMP_HEIGHT_METHOD
    assert result.parameters.landing_event_id == landing.occurrence_id
    assert (
        CMJ_TAKEOFF_LANDING_HEIGHT_EQUIVALENCE_ASSUMPTION
        in CMJ_FLIGHT_TIME_JUMP_HEIGHT_METHOD.assumptions
    )
    assert CMJ_SUPPORTED_SYSTEM_STABLE_ASSUMPTION in CMJ_FLIGHT_TIME_JUMP_HEIGHT_METHOD.assumptions
    assert CMJ_SUPPORTED_SYSTEM_STABLE_ASSUMPTION in result.parameters.assumptions


def test_flight_time_boundary_has_no_hidden_sample_correction_or_interpolation() -> None:
    result, takeoff, landing, _ = _flight_fixture("flight-boundary", gravity_suffix="boundary-g")
    metadata = {
        entry.key: entry.value for entry in result.observation.identity.processing.method_parameters
    }

    assert metadata["event_time_semantics"] == "recorded event_time_s difference; no interpolation"
    assert metadata["takeoff_sample_index"] == takeoff.sample_index
    assert metadata["landing_sample_index"] == landing.sample_index
    assert result.parameters.flight_time_s == pytest.approx(0.005)
    assert result.value_m != pytest.approx((0.006**2) / 8.0)
    assert metadata["filtering"] == "none"
    assert metadata["resampling"] == "none"


def test_flight_time_preserves_event_and_source_provenance() -> None:
    result, takeoff, landing, force = _flight_fixture("flight-provenance", gravity_suffix="prov-g")
    run = result.observation.provenance.processing_runs[-1]
    edges = result.observation.provenance.lineage_edges

    assert any(
        edge.from_id == takeoff.occurrence_id.qualified
        and edge.to_id == run.processing_run_id.qualified
        and edge.relation is LineageRelation.DERIVED_FROM
        for edge in edges
    )
    assert any(
        edge.from_id == landing.occurrence_id.qualified
        and edge.to_id == run.processing_run_id.qualified
        and edge.relation is LineageRelation.DERIVED_FROM
        for edge in edges
    )
    assert any(
        edge.from_id == run.processing_run_id.qualified
        and edge.to_id == result.observation.observation_id.qualified
        and edge.relation is LineageRelation.PRODUCED
        for edge in edges
    )
    assert force.observation.observation_id == result.parameters.source_observation_id
    assert result.method == CMJ_FLIGHT_TIME_JUMP_HEIGHT_METHOD_V2
    assert isinstance(result.parameters, FlightTimeV2EstimatorParameters)
    applicability = result.parameters.ballistic_applicability
    assert applicability is not None
    assert applicability.source_observation_id == force.observation.observation_id
    assert applicability.source_signal_id == takeoff.source_signal_id
    assert applicability.source_measurement_identity_id == force.identity.identity_id
    assert applicability.source_protocol_identity == force.identity.semantic.protocol_identity
    assert applicability.system_contract == result.parameters.system_contract
    assert applicability.is_authorized
    assert any(
        evidence.reference == result.method.evidence_decision
        for evidence in result.observation.provenance.evidence_references
    )
    assert any(
        evidence.reference == RES47_DECISION_FLIGHT_TIME_BALLISTIC_APPLICABILITY
        for evidence in result.observation.provenance.evidence_references
    )
    assert any(
        evidence.reference == RES48_DECISION_FLIGHT_TIME_V2_LOADING_AUTHORITY
        for evidence in result.observation.provenance.evidence_references
    )
    metadata = {
        entry.key: entry.value for entry in result.observation.identity.processing.method_parameters
    }
    assert metadata["system_contract"] == canonical_json(result.parameters.system_contract)
    assert metadata["ballistic_applicability"] == canonical_json(applicability)
    assert metadata["ballistic_loading_state"] == FlightLoadingState.UNLOADED.value
    assert metadata["protocol_external_loading"] == "none"


def test_flight_time_refuses_missing_or_mismatched_sources_and_gravity() -> None:
    result_a, takeoff_a, landing_a, force_a = _flight_fixture(
        "flight-source-a", gravity_suffix="source-g"
    )
    _, takeoff_b, landing_b, force_b = _flight_fixture("flight-source-b", gravity_suffix="source-g")
    assert isinstance(result_a, CMJJumpHeightResult)

    missing_takeoff = estimate_flight_time_jump_height(
        None,
        landing_a,
        _local_gravity("source-g"),
        source_observation=force_a.observation,
    )
    missing_landing = estimate_flight_time_jump_height(
        takeoff_a,
        None,
        _local_gravity("source-g"),
        source_observation=force_a.observation,
    )
    mismatched = estimate_flight_time_jump_height(
        takeoff_a,
        landing_b,
        _local_gravity("source-g"),
        source_observation=force_a.observation,
    )
    wrong_gravity = estimate_flight_time_jump_height(
        takeoff_a,
        landing_a,
        STANDARD_GRAVITY,
        source_observation=force_a.observation,
    )

    assert isinstance(missing_takeoff, RefusalResult)
    assert RefusalReasonCode.TAKEOFF_REQUIRED in missing_takeoff.reason_codes
    assert isinstance(missing_landing, RefusalResult)
    assert RefusalReasonCode.LANDING_REQUIRED in missing_landing.reason_codes
    assert isinstance(mismatched, RefusalResult)
    assert RefusalReasonCode.EVENT_SOURCE_MISMATCH in mismatched.reason_codes
    assert isinstance(wrong_gravity, RefusalResult)
    assert RefusalReasonCode.GRAVITY_REFERENCE_MISMATCH in wrong_gravity.reason_codes
    assert force_b.observation.observation_id != force_a.observation.observation_id


def test_flight_time_requires_explicit_source_observation_and_rejects_invalid_interval() -> None:
    _, takeoff, landing, force = _flight_fixture("flight-context", gravity_suffix="context-g")
    missing_source = estimate_flight_time_jump_height(
        takeoff,
        landing,
        _local_gravity("context-g"),
    )
    reversed_result = estimate_flight_time_jump_height(
        replace(takeoff, event_time_s=landing.event_time_s + 1.0),
        landing,
        _local_gravity("context-g"),
        source_observation=force.observation,
    )

    assert isinstance(missing_source, RefusalResult)
    assert RefusalReasonCode.MISSING_METADATA in missing_source.reason_codes
    assert isinstance(reversed_result, RefusalResult)
    assert RefusalReasonCode.FLIGHT_INTERVAL_INVALID in reversed_result.reason_codes


def test_flight_time_has_no_hidden_gravity_constants() -> None:
    import dynamislm.measurement.cmj.jump_height as jump_height

    source = inspect.getsource(jump_height)
    assert "9.81" not in source
    assert "9.80665" not in source
    result, _, _, _ = _flight_fixture("flight-local-g", gravity_suffix="explicit-one")
    assert result.value_m == pytest.approx((0.005**2) / 8.0)


def test_flight_time_requires_an_explicit_ballistic_system_contract() -> None:
    takeoff, landing, force = _flight_events("flight-contract-required")

    refusal = estimate_flight_time_jump_height(
        takeoff,
        landing,
        _local_gravity("flight-contract-required"),
        source_observation=force.observation,
    )

    assert isinstance(refusal, RefusalResult)
    assert RefusalReasonCode.MECHANICAL_SYSTEM_UNRESOLVED in refusal.reason_codes
    assert refusal.observation_ids == (force.observation.observation_id,)


def test_flight_time_accepts_a_stable_free_flying_supported_load() -> None:
    result, _, _, _ = _flight_fixture(
        "flight-loaded-supported",
        external_loading="supported-barbell",
        loading_state=FlightLoadingState.STABLE_ATTACHED_SUPPORTED_LOAD,
    )
    contract = result.parameters.system_contract
    metadata = {
        entry.key: entry.value for entry in result.observation.identity.processing.method_parameters
    }

    assert contract is not None
    assert contract.is_authorized
    assert contract.includes_supported_external_load
    assert result.observation.identity.semantic.construct.stable_id.endswith(
        "cmj-supported-system@1.0.0"
    )
    assert "not automatically anatomical athlete COM jump height" in result.method.claim_ceiling
    assert metadata["system_contract"] == canonical_json(contract)


@pytest.mark.parametrize(
    "external_loading",
    (
        "supported-barbell-overhead-harness",
        "supported-barbell-banded",
        "supported-barbell-experimental-device",
        "free-flying-whatever",
        "definitely-safe-trust-me",
        "completely-new-unseen-description",
    ),
)
def test_raw_external_loading_text_has_zero_authority(
    external_loading: str,
) -> None:
    takeoff, landing, force = _flight_events(
        f"flight-refusal-{external_loading}",
        external_loading=external_loading,
    )

    refusal = estimate_flight_time_jump_height(
        takeoff,
        landing,
        _local_gravity(f"flight-refusal-{external_loading}"),
        source_observation=force.observation,
        system_contract=_mechanics_contract(includes_supported_external_load=True),
    )

    assert isinstance(refusal, RefusalResult)
    assert RefusalReasonCode.MECHANICAL_SYSTEM_UNRESOLVED in refusal.reason_codes
    assert RefusalReasonCode.EXTERNAL_FORCE_MODEL_UNRESOLVED in refusal.reason_codes
    assert refusal.observation_ids == (force.observation.observation_id,)
    assert force.identity.semantic.protocol_identity is not None
    assert force.identity.semantic.protocol_identity.external_loading is not None
    assert force.identity.semantic.protocol_identity.external_loading.value == external_loading


@pytest.mark.parametrize(
    ("loading_state", "includes_supported_external_load", "expected_reason"),
    (
        (
            FlightLoadingState.NON_BALLISTIC_EXTERNAL_FORCE,
            False,
            RefusalReasonCode.BALLISTIC_ASSUMPTION_UNSUPPORTED,
        ),
        (
            FlightLoadingState.UNRESOLVED,
            False,
            RefusalReasonCode.EXTERNAL_FORCE_MODEL_UNRESOLVED,
        ),
        (
            FlightLoadingState.UNLOADED,
            True,
            RefusalReasonCode.SUPPORTED_SYSTEM_INTERPRETATION_REQUIRED,
        ),
        (
            FlightLoadingState.STABLE_ATTACHED_SUPPORTED_LOAD,
            False,
            RefusalReasonCode.SUPPORTED_SYSTEM_INTERPRETATION_REQUIRED,
        ),
    ),
)
def test_registered_loading_state_and_contract_control_v2_authority(
    loading_state: FlightLoadingState,
    includes_supported_external_load: bool,
    expected_reason: RefusalReasonCode,
) -> None:
    takeoff, landing, force = _flight_events(
        f"flight-typed-refusal-{loading_state.value}",
        external_loading="definitely-safe-trust-me",
    )
    contract = _mechanics_contract(
        includes_supported_external_load=includes_supported_external_load
    )
    applicability = FlightBallisticApplicability.from_takeoff_event(
        force.observation,
        takeoff,
        loading_state,
        contract,
    )

    refusal = estimate_flight_time_jump_height(
        takeoff,
        landing,
        _local_gravity(f"flight-typed-refusal-{loading_state.value}"),
        source_observation=force.observation,
        ballistic_applicability=applicability,
    )

    assert isinstance(refusal, RefusalResult)
    assert expected_reason in refusal.reason_codes


def test_registered_typed_state_authorizes_even_when_raw_text_is_only_audit_metadata() -> None:
    result, _, _, force = _flight_fixture(
        "flight-typed-authority-with-raw-text",
        external_loading="completely-new-unseen-description",
        loading_state=FlightLoadingState.UNLOADED,
    )
    assert result.method == CMJ_FLIGHT_TIME_JUMP_HEIGHT_METHOD_V2
    assert isinstance(result.parameters, FlightTimeV2EstimatorParameters)
    assert result.parameters.ballistic_applicability is not None
    metadata = {
        entry.key: entry.value for entry in result.observation.identity.processing.method_parameters
    }
    assert metadata["protocol_external_loading"] == "completely-new-unseen-description"
    assert metadata["ballistic_loading_state"] == FlightLoadingState.UNLOADED.value
    assert force.identity.semantic.protocol_identity is not None


def test_flight_applicability_requires_exact_trial_measurement_protocol_and_contract() -> None:
    takeoff_a, landing_a, force_a = _flight_events("applicability-source-a")
    takeoff_b, _, force_b = _flight_events(
        "applicability-source-b",
        external_loading="supported-barbell",
    )
    contract_a = _mechanics_contract(includes_supported_external_load=False)
    app_a = FlightBallisticApplicability.from_takeoff_event(
        force_a.observation,
        takeoff_a,
        FlightLoadingState.UNLOADED,
        contract_a,
    )
    app_b = FlightBallisticApplicability.from_takeoff_event(
        force_b.observation,
        takeoff_b,
        FlightLoadingState.UNLOADED,
        contract_a,
    )

    wrong_trial = estimate_flight_time_jump_height(
        takeoff_a,
        landing_a,
        _local_gravity("applicability-source-a"),
        source_observation=force_a.observation,
        ballistic_applicability=app_b,
    )
    wrong_measurement = replace(
        app_a,
        source_measurement_identity_id=force_b.identity.identity_id,
        source_binding_digest=None,
    )
    wrong_measurement_result = estimate_flight_time_jump_height(
        takeoff_a,
        landing_a,
        _local_gravity("applicability-source-a"),
        source_observation=force_a.observation,
        ballistic_applicability=wrong_measurement,
    )
    assert force_b.identity.semantic.protocol_identity is not None
    wrong_protocol = replace(
        app_a,
        source_protocol_identity=force_b.identity.semantic.protocol_identity,
        source_binding_digest=None,
    )
    wrong_protocol_result = estimate_flight_time_jump_height(
        takeoff_a,
        landing_a,
        _local_gravity("applicability-source-a"),
        source_observation=force_a.observation,
        ballistic_applicability=wrong_protocol,
    )
    wrong_contract = replace(
        app_a,
        system_contract=_mechanics_contract(includes_supported_external_load=True),
        source_binding_digest=None,
    )
    wrong_contract_result = estimate_flight_time_jump_height(
        takeoff_a,
        landing_a,
        _local_gravity("applicability-source-a"),
        source_observation=force_a.observation,
        ballistic_applicability=wrong_contract,
    )

    for refusal in (
        wrong_trial,
        wrong_measurement_result,
        wrong_protocol_result,
        wrong_contract_result,
    ):
        assert isinstance(refusal, RefusalResult)
    assert isinstance(wrong_trial, RefusalResult)
    assert isinstance(wrong_measurement_result, RefusalResult)
    assert isinstance(wrong_protocol_result, RefusalResult)
    assert isinstance(wrong_contract_result, RefusalResult)
    assert RefusalReasonCode.EVENT_SOURCE_MISMATCH in wrong_trial.reason_codes
    assert RefusalReasonCode.EVENT_SOURCE_MISMATCH in wrong_measurement_result.reason_codes
    assert RefusalReasonCode.PROTOCOL_IDENTITY_MISMATCH in wrong_protocol_result.reason_codes
    assert (
        RefusalReasonCode.SUPPORTED_SYSTEM_INTERPRETATION_REQUIRED
        in wrong_contract_result.reason_codes
    )


def test_flight_time_refuses_missing_protocol_applicability_without_erasing_events() -> None:
    takeoff, landing, force = _flight_events("flight-protocol-missing")
    missing_identity = replace(
        force.identity,
        semantic=replace(
            force.identity.semantic,
            protocol=None,
            protocol_identity=None,
        ),
    )
    missing_observation = replace(force.observation, identity=missing_identity)
    takeoff = replace(takeoff, source_measurement_identity=missing_identity)
    landing = replace(landing, source_measurement_identity=missing_identity)
    takeoff_id = takeoff.occurrence_id
    landing_id = landing.occurrence_id

    refusal = estimate_flight_time_jump_height(
        takeoff,
        landing,
        _local_gravity("flight-protocol-missing"),
        source_observation=missing_observation,
        system_contract=_mechanics_contract(),
    )

    assert isinstance(refusal, RefusalResult)
    assert RefusalReasonCode.PROTOCOL_IDENTITY_MISSING in refusal.reason_codes
    assert refusal.status.value == "PARTIALLY_REFUSED"
    assert any(
        "recorded event-time differences" in description
        for description in refusal.what_can_still_be_safely_described
    )
    assert takeoff.status.value == "DETECTED"
    assert landing.status.value == "DETECTED"
    assert takeoff.occurrence_id == takeoff_id
    assert landing.occurrence_id == landing_id


def test_flight_time_loaded_and_unloaded_contracts_are_not_automatically_interchangeable() -> None:
    unloaded, _, _, _ = _flight_fixture("flight-comparable-unloaded")
    loaded, _, _, _ = _flight_fixture(
        "flight-comparable-loaded",
        external_loading="supported-barbell",
        loading_state=FlightLoadingState.STABLE_ATTACHED_SUPPORTED_LOAD,
    )

    comparison = compare_cmj_jump_height_estimates(
        unloaded,
        loaded,
        claim="compare unloaded and supported-load flight-time heights",
        request_id=InstanceIdentifier("comparability-request", "flight-loaded-unloaded"),
    )

    assert comparison.state is ComparabilityState.BRIDGE_VALIDATION_REQUIRED
    assert ComparabilityReasonCode.PROTOCOL_MISMATCH in comparison.reason_codes
    assert ComparabilityReasonCode.SYSTEM_DEFINITION_MISMATCH in comparison.reason_codes
    refusal = refusal_for_cmj_jump_height_comparability(
        comparison,
        blocked_claim="compare unloaded and supported-load flight-time heights",
        observation_ids=(
            unloaded.observation.observation_id,
            loaded.observation.observation_id,
        ),
    )
    assert isinstance(refusal, RefusalResult)
    assert RefusalReasonCode.PROTOCOL_IDENTITY_MISMATCH in refusal.reason_codes
    assert RefusalReasonCode.SYSTEM_DEFINITION_UNRESOLVED in refusal.reason_codes


def test_takeoff_velocity_uses_event_sample_not_preceding_sample() -> None:
    result, velocity, takeoff, _ = _velocity_fixture("velocity-sample", gravity_suffix="velocity-g")
    local_index = takeoff.sample_index - velocity.series.sample_start_index
    assert velocity.samples[local_index] != velocity.samples[local_index - 1]
    assert result.parameters.takeoff_velocity_sample_index == takeoff.sample_index
    assert (
        result.parameters.takeoff_velocity_sample_convention
        == CMJ_TAKEOFF_VELOCITY_EVENT_SAMPLE_CONVENTION
    )
    assert result.parameters.takeoff_velocity_m_per_s == velocity.samples[local_index]
    assert result.value_m == pytest.approx(velocity.samples[local_index] ** 2 / 2.0)
    assert result.value_m != pytest.approx(velocity.samples[local_index - 1] ** 2 / 2.0)


def test_takeoff_velocity_requires_qualified_res46_velocity() -> None:
    result, velocity, takeoff, _ = _velocity_fixture(
        "velocity-qualified", gravity_suffix="qualified-g"
    )
    assert isinstance(result, CMJJumpHeightResult)
    assert isinstance(velocity.initial_velocity_condition, QualifiedZeroVelocityReference)
    assert velocity.initial_velocity_condition.is_authorized
    legacy: object = InitialVelocityCondition.zero_at_sample(
        velocity.series.series_id,
        velocity.series.sample_start_index,
    )
    refusal = estimate_takeoff_velocity_jump_height(
        legacy,  # type: ignore[arg-type]
        takeoff,
        _local_gravity("qualified-g"),
    )
    assert isinstance(refusal, RefusalResult)
    assert RefusalReasonCode.TAKEOFF_VELOCITY_REQUIRED in refusal.reason_codes


def test_takeoff_velocity_refuses_wrong_source_sample_and_gravity() -> None:
    result, velocity, takeoff, _ = _velocity_fixture(
        "velocity-source-a", gravity_suffix="source-a-g"
    )
    _, _, other_takeoff, _ = _velocity_fixture("velocity-source-b", gravity_suffix="source-a-g")
    assert isinstance(result, CMJJumpHeightResult)
    wrong_event = estimate_takeoff_velocity_jump_height(
        velocity,
        other_takeoff,
        _local_gravity("source-a-g"),
    )
    wrong_gravity = estimate_takeoff_velocity_jump_height(
        velocity,
        takeoff,
        _local_gravity("source-b-g"),
    )
    standard_gravity = estimate_takeoff_velocity_jump_height(
        velocity,
        takeoff,
        STANDARD_GRAVITY,
    )

    assert isinstance(wrong_event, RefusalResult)
    assert RefusalReasonCode.EVENT_SOURCE_MISMATCH in wrong_event.reason_codes
    assert isinstance(wrong_gravity, RefusalResult)
    assert RefusalReasonCode.GRAVITY_REFERENCE_MISMATCH in wrong_gravity.reason_codes
    assert isinstance(standard_gravity, RefusalResult)
    assert RefusalReasonCode.GRAVITY_REFERENCE_MISMATCH in standard_gravity.reason_codes


def test_takeoff_velocity_preserves_upstream_mechanics_and_loaded_system_semantics() -> None:
    result, velocity, _, contract = _velocity_fixture(
        "velocity-loaded",
        gravity_suffix="loaded-g",
        external_loading="supported-barbell",
    )
    parameters = {
        entry.key: entry.value for entry in result.observation.identity.processing.method_parameters
    }

    assert result.parameters.system_contract == contract
    assert contract.includes_supported_external_load
    assert result.observation.identity.semantic.construct.stable_id.endswith(
        "cmj-supported-system@1.0.0"
    )
    assert result.source_velocity is velocity
    assert (
        result.parameters.source_velocity_initial_condition == velocity.initial_velocity_condition
    )
    assert any(
        run.method.stable_id.endswith("cmj-physical-system-mass-from-weight-v1@1.0.0")
        for run in result.observation.provenance.processing_runs
    )
    assert parameters["source_velocity_initial_condition"] == canonical_json(
        velocity.initial_velocity_condition
    )
    assert "athlete-only" in result.method.claim_ceiling


def test_takeoff_velocity_result_roundtrips_deterministically_under_v3() -> None:
    result, _, _, _ = _velocity_fixture("velocity-roundtrip", gravity_suffix="roundtrip-g")
    encoded = canonical_json(result)
    restored = from_canonical_json(encoded, CMJJumpHeightResult)

    assert restored == result
    assert canonical_json(restored) == encoded
    assert canonical_hash(restored) == canonical_hash(result)
    assert SERIALIZATION_VERSION == 3


def test_flight_time_result_roundtrips_deterministically_under_v3() -> None:
    result, _, _, _ = _flight_fixture("flight-roundtrip", gravity_suffix="roundtrip-flight-g")
    encoded = canonical_json(result)
    restored = from_canonical_json(encoded, CMJJumpHeightResult)

    assert restored == result
    assert canonical_json(restored) == encoded
    assert canonical_hash(restored) == canonical_hash(result)


def test_historical_pre_res47_v1_fixture_roundtrips_as_v1() -> None:
    result, _, _, _ = _flight_fixture("historical-v1", gravity_suffix="historical-v1-g")
    historical = _historical_v1_result(result)

    assert historical.method == CMJ_FLIGHT_TIME_JUMP_HEIGHT_METHOD_V1
    assert type(historical.parameters) is JumpHeightEstimatorParameters
    assert historical.parameters.system_contract is None
    assert historical.parameters.assumptions == CMJ_FLIGHT_TIME_JUMP_HEIGHT_METHOD_V1.assumptions
    encoded = canonical_json(historical)
    restored = from_canonical_json(encoded, CMJJumpHeightResult)

    assert restored == historical
    assert restored.method.reference == CMJ_FLIGHT_TIME_JUMP_HEIGHT_METHOD_V1.reference
    assert restored.method.operation == CMJ_FLIGHT_TIME_JUMP_HEIGHT_METHOD_V1.operation
    assert restored.method.reference.identifier.version == "1.0.0"
    assert "ballistic_applicability" not in encoded
    assert canonical_json(restored) == encoded


def test_transitional_res47_v1_identity_with_v2_semantics_is_rejected() -> None:
    result, _, _, _ = _flight_fixture("transitional-res47", gravity_suffix="transitional-g")
    historical = _historical_v1_result(result)
    assert isinstance(result.parameters, FlightTimeV2EstimatorParameters)
    payload = json.loads(canonical_json(historical))
    payload["payload"]["parameters"]["system_contract"] = json.loads(
        canonical_json(result.parameters.system_contract)
    )["payload"]
    payload["payload"]["parameters"]["assumptions"] = json.loads(
        canonical_json(CMJ_FLIGHT_TIME_JUMP_HEIGHT_METHOD_V2.assumptions)
    )["payload"]
    transitional = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)

    with pytest.raises(SerializationError, match="invalid|historical|transitional"):
        from_canonical_json(transitional, CMJJumpHeightResult)


def test_v1_and_v2_comparability_requires_a_registered_bridge() -> None:
    v2, _, _, _ = _flight_fixture("v2-bridge-right", gravity_suffix="bridge-g")
    v1_source, _, _, _ = _flight_fixture("v1-bridge-left", gravity_suffix="bridge-g")
    v1 = _historical_v1_result(v1_source)

    comparison = compare_cmj_jump_height_estimates(
        v1,
        v2,
        claim="compare historical V1 and qualified V2 flight-time heights",
        request_id=InstanceIdentifier("comparability-request", "v1-v2-bridge"),
    )

    assert comparison.state is ComparabilityState.BRIDGE_VALIDATION_REQUIRED
    assert ComparabilityReasonCode.ESTIMATOR_MISMATCH in comparison.reason_codes
    assert ComparabilityReasonCode.BRIDGE_NOT_REGISTERED in comparison.reason_codes


def test_unknown_loading_state_is_not_decodable_or_defaulted() -> None:
    result, _, _, _ = _flight_fixture("unknown-loading-state")
    assert isinstance(result.parameters, FlightTimeV2EstimatorParameters)
    applicability = result.parameters.ballistic_applicability
    assert applicability is not None
    with pytest.raises(ValueError, match="closed registered vocabulary"):
        replace(applicability, loading_state="NEW_STATE", source_binding_digest=None)  # type: ignore[arg-type]

    payload = json.loads(canonical_json(result))
    nested = payload["payload"]["parameters"]["ballistic_applicability"]
    nested["loading_state"] = "NEW_STATE"
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    with pytest.raises(SerializationError, match="invalid|loading state"):
        from_canonical_json(encoded, CMJJumpHeightResult)


def test_xu_2023_reference_uses_the_exact_pmc10115716_title() -> None:
    decision = Path(__file__).parents[1] / (
        "docs/decisions/RES47-DR-001-flight-time-ballistic-system-applicability.md"
    )
    text = " ".join(decision.read_text(encoding="utf-8").split())
    assert (
        "A Systematic Review of the Different Calculation Methods for Measuring Jump Height "
        "During the Countermovement and Drop Jump Tests"
    ) in text
    assert (
        "A Systematic Review of the Methodology and Validation of Countermovement Jump Tests"
        not in text
    )
    assert "PMC10115716" in text


def test_result_rejects_a_scalar_that_does_not_match_the_registered_equation() -> None:
    result, _, _, _ = _flight_fixture("flight-equation-integrity", gravity_suffix="integrity-g")
    bad_measurement = replace(
        result.observation.result,
        value=ScalarValue(result.value_m + 0.001),
    )
    bad_observation = replace(result.observation, result=bad_measurement)

    with pytest.raises(ValueError, match="registered equation"):
        replace(result, observation=bad_observation)


def test_result_rejects_a_takeoff_velocity_parameter_not_at_the_event_sample() -> None:
    result, _, _, _ = _velocity_fixture("velocity-equation-integrity", gravity_suffix="integrity-g")
    assert result.parameters.takeoff_velocity_m_per_s is not None
    bad_parameters = replace(
        result.parameters,
        takeoff_velocity_m_per_s=result.parameters.takeoff_velocity_m_per_s + 0.001,
    )
    bad_metadata = tuple(
        MetadataEntry(
            entry.key,
            canonical_json(bad_parameters) if entry.key == "estimator_parameters" else entry.value,
        )
        for entry in result.observation.identity.processing.method_parameters
    )
    bad_processing = replace(
        result.observation.identity.processing,
        method_parameters=bad_metadata,
    )
    bad_identity = replace(result.observation.identity, processing=bad_processing)
    bad_observation = replace(result.observation, identity=bad_identity)

    with pytest.raises(ValueError, match="linkage"):
        replace(result, observation=bad_observation, parameters=bad_parameters)


def test_same_method_comparability_ignores_trial_instance_ids() -> None:
    left, _, _, _ = _flight_fixture("comparable-left", gravity_suffix="comparable-g")
    right, _, _, _ = _flight_fixture("comparable-right", gravity_suffix="comparable-g")

    comparison = compare_cmj_jump_height_estimates(
        left,
        right,
        claim="compare estimator-qualified flight-time heights",
        request_id=InstanceIdentifier("comparability-request", "jump-same-method"),
    )

    assert comparison.state is ComparabilityState.COMPARABLE
    assert comparison.reason_codes == ()
    assert (
        refusal_for_cmj_jump_height_comparability(
            comparison,
            blocked_claim="compare estimator-qualified flight-time heights",
        )
        is None
    )


def test_cross_estimator_same_numeric_value_requires_bridge_validation() -> None:
    flight, _, _, _ = _flight_fixture("cross-family-flight", gravity_suffix="cross-family-g")
    velocity, _, _, _ = _velocity_fixture("cross-family-velocity", gravity_suffix="cross-family-g")

    assert velocity.value_m == pytest.approx(flight.value_m)
    comparison = compare_cmj_jump_height_estimates(
        flight,
        velocity,
        claim="these estimators are interchangeable",
        request_id=InstanceIdentifier("comparability-request", "jump-cross-family"),
    )

    assert comparison.state is ComparabilityState.BRIDGE_VALIDATION_REQUIRED
    assert ComparabilityReasonCode.ESTIMATOR_MISMATCH in comparison.reason_codes
    refusal = refusal_for_cmj_jump_height_comparability(
        comparison,
        blocked_claim="these estimators are interchangeable",
        observation_ids=(flight.observation.observation_id, velocity.observation.observation_id),
    )
    assert isinstance(refusal, RefusalResult)
    assert refusal.status.value == "PARTIALLY_REFUSED"
    assert RefusalReasonCode.ESTIMATOR_MISMATCH in refusal.reason_codes


def test_estimator_disagreement_remains_method_distinct() -> None:
    flight, _, _, _ = _flight_fixture("disagreement-flight", gravity_suffix="disagreement-g")
    velocity, _, _, _ = _velocity_fixture(
        "disagreement-velocity",
        gravity_suffix="disagreement-g",
        samples=(100.0, 100.0, 100.0, 200.0, 200.0, 0.0, 0.0, 100.0),
    )
    assert velocity.value_m != pytest.approx(flight.value_m)
    comparison = assess_cmj_jump_height_comparability(
        __import__(
            "dynamislm.measurement.cmj",
            fromlist=["CMJJumpHeightComparabilityRequest"],
        ).CMJJumpHeightComparabilityRequest(
            request_id=InstanceIdentifier("comparability-request", "jump-disagreement"),
            left=flight,
            right=velocity,
            claim="compare two jump-height estimator outputs",
        )
    )
    assert comparison.state is ComparabilityState.BRIDGE_VALIDATION_REQUIRED
    assert ComparabilityReasonCode.ESTIMATOR_MISMATCH in comparison.reason_codes


def test_gravity_is_a_material_comparability_dimension() -> None:
    left, takeoff, landing, force = _flight_fixture("gravity-left", gravity_suffix="gravity-left-g")
    assert isinstance(left.parameters, FlightTimeV2EstimatorParameters)
    right = estimate_flight_time_jump_height(
        takeoff,
        landing,
        _local_gravity("gravity-right-g"),
        source_observation=force.observation,
        ballistic_applicability=left.parameters.ballistic_applicability,
    )
    assert isinstance(right, CMJJumpHeightResult)
    comparison = compare_cmj_jump_height_estimates(
        left,
        right,
        claim="compare heights across gravity references",
        request_id=InstanceIdentifier("comparability-request", "jump-gravity"),
    )
    assert comparison.state is ComparabilityState.BRIDGE_VALIDATION_REQUIRED
    assert ComparabilityReasonCode.GRAVITY_REFERENCE_MISMATCH in comparison.reason_codes


def test_com_displacement_is_explicitly_deferred() -> None:
    refusal = defer_com_displacement_jump_height(
        observation_ids=(InstanceIdentifier("observation", "relative-displacement"),)
    )

    assert isinstance(refusal, RefusalResult)
    assert RefusalReasonCode.COM_DISPLACEMENT_ESTIMATOR_DEFERRED in refusal.reason_codes
    assert refusal.status.value == "PARTIALLY_REFUSED"
    assert "absolute or anatomical COM origin" not in refusal.missing_information
    assert "registered apex/phase authority" in refusal.missing_information
    assert "registered drift/error policy" in refusal.missing_information
