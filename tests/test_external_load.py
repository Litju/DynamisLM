from __future__ import annotations

import datetime as datetime_module
import json
from dataclasses import replace
from pathlib import Path

import pytest

from dynamislm import (
    EXTERNAL_LOAD_COMPARABILITY_RULE,
    EXTERNAL_LOAD_CONSTRUCT,
    EXTERNAL_LOAD_COUNT,
    EXTERNAL_LOAD_DISTANCE_MEASURAND,
    EXTERNAL_LOAD_INPUT_PROCESSING_METHOD,
    EXTERNAL_LOAD_KILOMETER,
    EXTERNAL_LOAD_KILOMETERS_PER_HOUR,
    EXTERNAL_LOAD_LINEAR_INTERPOLATION,
    EXTERNAL_LOAD_METER,
    EXTERNAL_LOAD_METERS_PER_MINUTE,
    EXTERNAL_LOAD_METERS_PER_SECOND,
    EXTERNAL_LOAD_MINUTE,
    EXTERNAL_LOAD_NO_FILTERING,
    EXTERNAL_LOAD_NO_RESAMPLING,
    EXTERNAL_LOAD_NO_SMOOTHING,
    EXTERNAL_LOAD_RELATIVE_DISTANCE_METRIC,
    EXTERNAL_LOAD_RELATIVE_DISTANCE_OPERATION,
    EXTERNAL_LOAD_SECOND,
    EXTERNAL_LOAD_SOURCE_A_PLAYER_MATCH_AGGREGATION,
    EXTERNAL_LOAD_SPEED_MEASURAND,
    EXTERNAL_LOAD_TEST_FAMILY,
    EXTERNAL_LOAD_THRESHOLD_EVENT_COUNT_METRIC,
    EXTERNAL_LOAD_THRESHOLD_EVENT_DEFINITION,
    EXTERNAL_LOAD_THRESHOLD_EVENT_END_RULE,
    EXTERNAL_LOAD_THRESHOLD_EVENT_START_RULE,
    EXTERNAL_LOAD_THRESHOLD_TIME_METRIC,
    EXTERNAL_LOAD_TOTAL_DISTANCE_METRIC,
    AcquisitionIdentity,
    AcquisitionRecord,
    AggregationContext,
    AggregationScope,
    ComparabilityResult,
    EventHysteresisStatus,
    ExternalLoadAggregationIdentity,
    ExternalLoadComputationError,
    ExternalLoadDefinitionStatus,
    ExternalLoadEventDefinition,
    ExternalLoadMeasurementIdentity,
    ExternalLoadMetricFamily,
    ExternalLoadMetricResult,
    ExternalLoadModality,
    ExternalLoadNormalizationIdentity,
    ExternalLoadProcessingIdentity,
    ExternalLoadSourceMapping,
    ExternalLoadSystemIdentity,
    ExternalLoadThresholdIdentity,
    ExternalLoadThresholdSummary,
    InstanceIdentifier,
    LineageEdge,
    LineageRelation,
    MeasurementResult,
    MetadataEntry,
    NormalizationKind,
    ObservationContext,
    ProcessingComponentStatus,
    ProcessingRun,
    ProcessingStepIdentity,
    Provenance,
    RefusalReasonCode,
    RefusalResult,
    RegistryReference,
    ResultStatus,
    SamplingCharacteristics,
    ScalarValue,
    ScientificClassification,
    ScientificIdentifier,
    ScientificMeasurementObservation,
    SemanticIdentity,
    SourceArtifact,
    ThresholdBasis,
    ThresholdBoundary,
    UnitReference,
    ValueOrigin,
    VelocitySample,
    VelocitySeries,
    VersionIdentity,
    canonical_hash,
    canonical_json,
    compare_external_load_measurement_identities,
    convert_external_load_value,
    derive_duration_normalized_distance,
    duration_normalized_distance,
    from_canonical_json,
    map_source_a_variable,
    refuse_unregistered_external_load_computation,
    source_a_external_column_names,
    summarize_velocity_threshold,
)
from dynamislm.external_load.registry import (
    EXTERNAL_LOAD_ACCELERATION_EVENT_COUNT_METRIC,
    EXTERNAL_LOAD_ACCELERATION_MEASURAND,
    EXTERNAL_LOAD_PROVIDER_LOAD_MEASURAND,
    EXTERNAL_LOAD_PROVIDER_LOAD_METRIC,
    EXTERNAL_LOAD_SOURCE_A_GNSS_ALGORITHM,
    EXTERNAL_LOAD_SOURCE_A_PLAYERLOAD_ALGORITHM,
)
from dynamislm.ingestion.adapters.unifesp_serie_a import source_a_variable_identities

UTC = datetime_module.UTC


def _reference(object_type: str, key: str, label: str) -> RegistryReference:
    return RegistryReference(
        ScientificIdentifier("synthetic-res64", object_type, key, "1.0.0"),
        label,
    )


def _threshold(
    value: float = 20.0,
    unit: UnitReference = EXTERNAL_LOAD_KILOMETERS_PER_HOUR,
) -> ExternalLoadThresholdIdentity:
    return ExternalLoadThresholdIdentity(
        basis=ThresholdBasis.ABSOLUTE,
        threshold_quantity=EXTERNAL_LOAD_SPEED_MEASURAND,
        threshold_value=value,
        threshold_unit=unit,
        boundary=ThresholdBoundary.GREATER_THAN,
    )


def _event(minimum_duration_s: float | None = 0.5) -> ExternalLoadEventDefinition:
    return ExternalLoadEventDefinition(
        definition=EXTERNAL_LOAD_THRESHOLD_EVENT_DEFINITION,
        minimum_duration_s=minimum_duration_s,
        hysteresis_status=EventHysteresisStatus.NONE,
        gap_allowance_s=0.0,
        start_rule=EXTERNAL_LOAD_THRESHOLD_EVENT_START_RULE,
        end_rule=EXTERNAL_LOAD_THRESHOLD_EVENT_END_RULE,
    )


def _identity(
    suffix: str,
    *,
    metric_family: ExternalLoadMetricFamily = ExternalLoadMetricFamily.THRESHOLD_TIME,
    modality: ExternalLoadModality = ExternalLoadModality.GNSS,
    value_origin: ValueOrigin = ValueOrigin.DIRECT_MEASUREMENT,
    threshold: ExternalLoadThresholdIdentity | None = None,
    event_definition: ExternalLoadEventDefinition | None = None,
    normalization: ExternalLoadNormalizationIdentity | None = None,
    filtering_status: ProcessingComponentStatus = ProcessingComponentStatus.REGISTERED,
    provider: str = "synthetic-provider",
    provider_algorithm: RegistryReference | None = EXTERNAL_LOAD_SOURCE_A_GNSS_ALGORITHM,
    context: AggregationContext = AggregationContext.MATCH,
    output_unit: UnitReference | None = EXTERNAL_LOAD_METERS_PER_SECOND,
    definition_status: ExternalLoadDefinitionStatus = ExternalLoadDefinitionStatus.RESOLVED,
) -> ExternalLoadMeasurementIdentity:
    metric_reference = {
        ExternalLoadMetricFamily.THRESHOLD_TIME: EXTERNAL_LOAD_THRESHOLD_TIME_METRIC,
        ExternalLoadMetricFamily.THRESHOLD_EVENT_COUNT: EXTERNAL_LOAD_THRESHOLD_EVENT_COUNT_METRIC,
        ExternalLoadMetricFamily.TOTAL_DISTANCE: EXTERNAL_LOAD_TOTAL_DISTANCE_METRIC,
        ExternalLoadMetricFamily.RELATIVE_DISTANCE: EXTERNAL_LOAD_RELATIVE_DISTANCE_METRIC,
        ExternalLoadMetricFamily.ACCELERATION_EVENT_COUNT: (
            EXTERNAL_LOAD_ACCELERATION_EVENT_COUNT_METRIC
        ),
        ExternalLoadMetricFamily.PROVIDER_LOAD: EXTERNAL_LOAD_PROVIDER_LOAD_METRIC,
    }.get(metric_family, EXTERNAL_LOAD_THRESHOLD_TIME_METRIC)
    measurand = {
        ExternalLoadMetricFamily.TOTAL_DISTANCE: EXTERNAL_LOAD_DISTANCE_MEASURAND,
        ExternalLoadMetricFamily.RELATIVE_DISTANCE: EXTERNAL_LOAD_DISTANCE_MEASURAND,
        ExternalLoadMetricFamily.PROVIDER_LOAD: EXTERNAL_LOAD_PROVIDER_LOAD_MEASURAND,
        ExternalLoadMetricFamily.ACCELERATION_EVENT_COUNT: EXTERNAL_LOAD_ACCELERATION_MEASURAND,
    }.get(metric_family, EXTERNAL_LOAD_SPEED_MEASURAND)
    if threshold is None:
        threshold = (
            _threshold()
            if metric_family
            in {
                ExternalLoadMetricFamily.THRESHOLD_TIME,
                ExternalLoadMetricFamily.THRESHOLD_EVENT_COUNT,
                ExternalLoadMetricFamily.ACCELERATION_EVENT_COUNT,
            }
            else ExternalLoadThresholdIdentity.none()
        )
    if normalization is None:
        normalization = ExternalLoadNormalizationIdentity.none()
    if output_unit is None and metric_family is ExternalLoadMetricFamily.THRESHOLD_EVENT_COUNT:
        output_unit = EXTERNAL_LOAD_COUNT
    device = _reference("device", f"device-{suffix}", "synthetic device")
    sampling = None
    if modality is not ExternalLoadModality.SOURCE_REPORTED:
        sampling = SamplingCharacteristics(10.0, ("velocity",), "float64")
    system = ExternalLoadSystemIdentity(
        provider=provider,
        device_or_system=device,
        sampling=sampling,
        provider_algorithm=(
            provider_algorithm if value_origin is ValueOrigin.PROVIDER_DERIVED else None
        ),
        provider_algorithm_status=(
            ProcessingComponentStatus.REGISTERED
            if value_origin is ValueOrigin.PROVIDER_DERIVED
            else ProcessingComponentStatus.NOT_APPLICABLE
        ),
    )
    acquisition = AcquisitionIdentity(device=device, raw_artifact=None, sampling=sampling)
    unit = output_unit
    signal_processing = modality is not ExternalLoadModality.SOURCE_REPORTED
    processing = ExternalLoadProcessingIdentity(
        unit=unit,
        filtering=(EXTERNAL_LOAD_NO_FILTERING,) if signal_processing else (),
        filtering_status=(
            filtering_status if signal_processing else ProcessingComponentStatus.NOT_APPLICABLE
        ),
        smoothing=(
            ProcessingStepIdentity(
                ProcessingComponentStatus.REGISTERED,
                EXTERNAL_LOAD_NO_SMOOTHING,
            )
            if signal_processing
            else ProcessingStepIdentity.not_applicable()
        ),
        resampling=(
            ProcessingStepIdentity(
                ProcessingComponentStatus.REGISTERED,
                EXTERNAL_LOAD_NO_RESAMPLING,
            )
            if signal_processing
            else ProcessingStepIdentity.not_applicable()
        ),
        differentiation_status=(
            ProcessingComponentStatus.REGISTERED
            if metric_family is ExternalLoadMetricFamily.ACCELERATION_EVENT_COUNT
            else ProcessingComponentStatus.NOT_APPLICABLE
        ),
        differentiation_method=(
            _reference("differentiation-method", "finite-difference", "finite difference")
            if metric_family is ExternalLoadMetricFamily.ACCELERATION_EVENT_COUNT
            else None
        ),
        method_parameters=(MetadataEntry("fixture", "SYNTHETIC RES-64"),),
        interpolation_method=EXTERNAL_LOAD_LINEAR_INTERPOLATION if signal_processing else None,
    )
    if metric_family is ExternalLoadMetricFamily.ACCELERATION_EVENT_COUNT:
        processing = replace(processing, unit=EXTERNAL_LOAD_COUNT)
    semantic = SemanticIdentity(
        construct=EXTERNAL_LOAD_CONSTRUCT,
        test_family=EXTERNAL_LOAD_TEST_FAMILY,
        protocol=None,
        measurand=measurand,
        metric_definition=metric_reference,
    )
    return ExternalLoadMeasurementIdentity(
        identity_id=ScientificIdentifier(
            "synthetic-res64", "measurement-identity", f"external-{suffix}", "1.0.0"
        ),
        semantic=semantic,
        acquisition=acquisition,
        processing=processing,
        version=VersionIdentity(
            EXTERNAL_LOAD_INPUT_PROCESSING_METHOD,
            "1.0.0",
            "synthetic-res64-software-1.0.0",
        ),
        modality=modality,
        value_origin=value_origin,
        system=system,
        threshold=threshold,
        aggregation=ExternalLoadAggregationIdentity(
            session_definition=EXTERNAL_LOAD_SOURCE_A_PLAYER_MATCH_AGGREGATION,
            context=context,
            scope=AggregationScope.WHOLE_SESSION,
        ),
        normalization=normalization,
        event_definition=event_definition,
        metric_family=metric_family,
        definition_status=definition_status,
        dynamislm_recomputable=value_origin is ValueOrigin.DYNAMISLM_DERIVED,
    )


def _provenance(
    identity: ExternalLoadMeasurementIdentity,
    observation_id: InstanceIdentifier,
) -> Provenance:
    artifact = SourceArtifact(
        artifact_id=InstanceIdentifier("artifact", f"artifact-{observation_id.value}"),
        content_digest="sha256:" + "a" * 64,
        media_type="application/vnd.synthetic-res64.velocity",
    )
    device = identity.acquisition.device or _reference("device", "source", "source device")
    acquisition = AcquisitionRecord(
        acquisition_id=InstanceIdentifier("acquisition", f"acquisition-{observation_id.value}"),
        device=device,
        source_artifact_id=artifact.artifact_id,
        sampling=identity.acquisition.sampling,
    )
    run = ProcessingRun(
        processing_run_id=InstanceIdentifier("processing-run", f"run-{observation_id.value}"),
        source_artifact_ids=(artifact.artifact_id,),
        method=identity.version.processing_method,
        parameters=(),
        software_version=identity.version.software_version,
        output_entity_id=observation_id,
    )
    return Provenance(
        provenance_id=InstanceIdentifier("provenance", f"provenance-{observation_id.value}"),
        source_artifacts=(artifact,),
        acquisitions=(acquisition,),
        processing_runs=(run,),
        lineage_edges=(
            LineageEdge(
                artifact.artifact_id.qualified,
                acquisition.acquisition_id.qualified,
                LineageRelation.ACQUIRED_AS,
            ),
            LineageEdge(
                acquisition.acquisition_id.qualified,
                run.processing_run_id.qualified,
                LineageRelation.PROCESSED_AS,
            ),
            LineageEdge(
                run.processing_run_id.qualified,
                observation_id.qualified,
                LineageRelation.PRODUCED,
            ),
        ),
    )


def _observation(
    identity: ExternalLoadMeasurementIdentity,
    suffix: str,
) -> ScientificMeasurementObservation:
    observation_id = InstanceIdentifier("observation", suffix)
    context = ObservationContext(
        context_id=InstanceIdentifier("context", suffix),
        athlete_id=InstanceIdentifier("athlete", "athlete-1"),
        session_id=InstanceIdentifier("session", "session-1"),
        test_instance_id=InstanceIdentifier("test-instance", suffix),
        trial_id=None,
        observed_at=datetime_module.datetime(2026, 1, 1, tzinfo=UTC),
        population_context="SYNTHETIC RES-64 descriptive context",
    )
    unit = identity.processing.unit
    return ScientificMeasurementObservation(
        observation_id=observation_id,
        context=context,
        identity=identity,
        result=MeasurementResult(
            result_id=InstanceIdentifier("result", suffix),
            value=ScalarValue(1.0),
            unit=unit,
            classification=ScientificClassification(identity.value_origin, ()),
            status=ResultStatus.VALID,
        ),
        provenance=_provenance(identity, observation_id),
    )


def _compare(
    left: ExternalLoadMeasurementIdentity,
    right: ExternalLoadMeasurementIdentity,
) -> ComparabilityResult:
    return compare_external_load_measurement_identities(
        left,
        right,
        claim="compare two external-load observations",
        request_id=InstanceIdentifier("comparability-request", "synthetic-res64"),
        left_observation_id=InstanceIdentifier("observation", "left"),
        right_observation_id=InstanceIdentifier("observation", "right"),
    )


def test_external_load_identity_roundtrips_through_v3_without_value_coupling() -> None:
    identity = _identity("roundtrip")
    serialized = canonical_json(identity)
    restored = from_canonical_json(serialized, ExternalLoadMeasurementIdentity)

    assert restored == identity
    assert canonical_hash(restored) == canonical_hash(identity)
    assert '"value":1.0' not in serialized
    assert '"serialization_version":3' in canonical_json(
        _observation(identity, "roundtrip-observation")
    )


def test_external_load_observation_reuses_generic_result_and_provenance_contracts() -> None:
    identity = _identity("observation", value_origin=ValueOrigin.PROVIDER_DERIVED)
    observation = _observation(identity, "provider-observation")

    assert isinstance(observation, ScientificMeasurementObservation)
    assert isinstance(observation.result, MeasurementResult)
    assert isinstance(observation.provenance, Provenance)
    assert isinstance(observation.identity, ExternalLoadMeasurementIdentity)
    assert observation.identity.value_origin is ValueOrigin.PROVIDER_DERIVED
    assert observation.result.classification.value_origin is ValueOrigin.PROVIDER_DERIVED
    assert observation.provenance.processing_runs[0].output_entity_id == observation.observation_id

    forged_result = replace(
        observation.result,
        classification=ScientificClassification(ValueOrigin.DIRECT_MEASUREMENT, ()),
    )
    with pytest.raises(ValueError, match="origins must agree"):
        ScientificMeasurementObservation(
            observation_id=observation.observation_id,
            context=observation.context,
            identity=observation.identity,
            result=forged_result,
            provenance=observation.provenance,
        )


def test_unit_normalization_is_registered_and_dimension_safe() -> None:
    assert convert_external_load_value(
        20.0, EXTERNAL_LOAD_KILOMETERS_PER_HOUR, EXTERNAL_LOAD_METERS_PER_SECOND
    ) == pytest.approx(5.555555555555555)
    assert convert_external_load_value(
        1.0, EXTERNAL_LOAD_KILOMETER, EXTERNAL_LOAD_METER
    ) == pytest.approx(1000.0)
    assert convert_external_load_value(
        2.0, EXTERNAL_LOAD_MINUTE, EXTERNAL_LOAD_SECOND
    ) == pytest.approx(120.0)
    with pytest.raises(ExternalLoadComputationError) as error:
        convert_external_load_value(1.0, EXTERNAL_LOAD_METER, EXTERNAL_LOAD_MINUTE)
    assert error.value.reason_code is RefusalReasonCode.INCOMPATIBLE_UNITS


def test_relative_distance_requires_explicit_positive_duration() -> None:
    assert duration_normalized_distance(
        1_200.0,
        120.0,
        distance_unit=EXTERNAL_LOAD_METER,
        duration_unit=EXTERNAL_LOAD_SECOND,
    ) == pytest.approx(600.0)
    with pytest.raises(ExternalLoadComputationError) as missing:
        duration_normalized_distance(
            1_200.0,
            None,
            distance_unit=EXTERNAL_LOAD_METER,
            duration_unit=EXTERNAL_LOAD_SECOND,
        )
    assert missing.value.reason_code is RefusalReasonCode.MISSING_DURATION
    with pytest.raises(ExternalLoadComputationError) as zero:
        duration_normalized_distance(
            1_200.0,
            0.0,
            distance_unit=EXTERNAL_LOAD_METER,
            duration_unit=EXTERNAL_LOAD_SECOND,
        )
    assert zero.value.reason_code is RefusalReasonCode.ZERO_DURATION


def test_relative_distance_result_is_a_new_dynamislm_derived_identity() -> None:
    source = _identity(
        "derived-source",
        metric_family=ExternalLoadMetricFamily.TOTAL_DISTANCE,
        output_unit=EXTERNAL_LOAD_METER,
    )
    duration = _identity(
        "derived-duration",
        metric_family=ExternalLoadMetricFamily.MINUTES_EXPOSURE,
        output_unit=EXTERNAL_LOAD_MINUTE,
    )
    result = derive_duration_normalized_distance(
        1_200.0,
        120.0,
        distance_unit=EXTERNAL_LOAD_METER,
        duration_unit=EXTERNAL_LOAD_SECOND,
        source_identity=source,
        duration_identity=duration,
    )

    assert isinstance(result, ExternalLoadMetricResult)
    assert result.value == pytest.approx(600.0)
    assert result.metric_identity.value_origin is ValueOrigin.DYNAMISLM_DERIVED
    assert result.measurement_result.classification.value_origin is ValueOrigin.DYNAMISLM_DERIVED
    assert result.metric_identity.dynamislm_recomputable is True
    assert from_canonical_json(canonical_json(result), ExternalLoadMetricResult) == result


def test_velocity_threshold_summary_uses_actual_samples_and_explicit_boundaries() -> None:
    identity = _identity(
        "threshold-summary",
        threshold=ExternalLoadThresholdIdentity(
            basis=ThresholdBasis.ABSOLUTE,
            threshold_quantity=EXTERNAL_LOAD_SPEED_MEASURAND,
            threshold_value=5.0,
            threshold_unit=EXTERNAL_LOAD_METERS_PER_SECOND,
            boundary=ThresholdBoundary.GREATER_THAN,
        ),
    )
    series = VelocitySeries(
        InstanceIdentifier("series", "threshold-summary"),
        (
            VelocitySample(0.0, 0.0, EXTERNAL_LOAD_METERS_PER_SECOND),
            VelocitySample(1.0, 10.0, EXTERNAL_LOAD_METERS_PER_SECOND),
            VelocitySample(2.0, 10.0, EXTERNAL_LOAD_METERS_PER_SECOND),
            VelocitySample(3.0, 0.0, EXTERNAL_LOAD_METERS_PER_SECOND),
        ),
        maximum_gap_s=1.0,
    )
    summary = summarize_velocity_threshold(series, identity)

    assert isinstance(summary, ExternalLoadThresholdSummary)
    assert summary.time_above_threshold_s == pytest.approx(2.0)
    assert summary.distance_above_threshold_m == pytest.approx(17.5)
    assert summary.event_count is None


def test_threshold_event_count_requires_and_uses_dwell_definition() -> None:
    identity = _identity(
        "event-summary",
        metric_family=ExternalLoadMetricFamily.THRESHOLD_EVENT_COUNT,
        event_definition=_event(0.5),
        output_unit=EXTERNAL_LOAD_COUNT,
    )
    series = VelocitySeries(
        InstanceIdentifier("series", "event-summary"),
        (
            VelocitySample(0.0, 0.0, EXTERNAL_LOAD_METERS_PER_SECOND),
            VelocitySample(1.0, 10.0, EXTERNAL_LOAD_METERS_PER_SECOND),
            VelocitySample(2.0, 10.0, EXTERNAL_LOAD_METERS_PER_SECOND),
            VelocitySample(3.0, 0.0, EXTERNAL_LOAD_METERS_PER_SECOND),
        ),
        maximum_gap_s=1.0,
    )
    summary = summarize_velocity_threshold(series, identity)
    assert isinstance(summary, ExternalLoadThresholdSummary)
    assert summary.event_count == 1

    unresolved = _identity(
        "event-summary-unresolved",
        metric_family=ExternalLoadMetricFamily.THRESHOLD_EVENT_COUNT,
        event_definition=_event(None),
        output_unit=EXTERNAL_LOAD_COUNT,
    )
    refused = summarize_velocity_threshold(series, unresolved)
    assert isinstance(refused, RefusalResult)
    assert RefusalReasonCode.UNKNOWN_DWELL_RULE.value in refused.reason_codes


def test_unknown_filtering_and_undeclared_gap_refuse_threshold_summary() -> None:
    identity = _identity(
        "unknown-filter",
        filtering_status=ProcessingComponentStatus.UNKNOWN,
    )
    series = VelocitySeries(
        InstanceIdentifier("series", "unknown-filter"),
        (
            VelocitySample(0.0, 0.0, EXTERNAL_LOAD_METERS_PER_SECOND),
            VelocitySample(1.0, 10.0, EXTERNAL_LOAD_METERS_PER_SECOND),
        ),
        maximum_gap_s=None,
    )
    refused = summarize_velocity_threshold(series, identity)
    assert isinstance(refused, RefusalResult)
    assert RefusalReasonCode.UNKNOWN_FILTERING.value in refused.reason_codes
    assert RefusalReasonCode.UNDECLARED_TIME_GAP.value in refused.reason_codes


def test_acceleration_event_family_has_no_hidden_velocity_threshold_authority() -> None:
    identity = _identity(
        "acceleration-no-authority",
        metric_family=ExternalLoadMetricFamily.ACCELERATION_EVENT_COUNT,
        output_unit=EXTERNAL_LOAD_COUNT,
    )
    series = VelocitySeries(
        InstanceIdentifier("series", "acceleration-no-authority"),
        (
            VelocitySample(0.0, 0.0, EXTERNAL_LOAD_METERS_PER_SECOND),
            VelocitySample(1.0, 10.0, EXTERNAL_LOAD_METERS_PER_SECOND),
        ),
        maximum_gap_s=1.0,
    )

    refused = summarize_velocity_threshold(series, identity)
    assert isinstance(refused, RefusalResult)
    assert RefusalReasonCode.EXTERNAL_LOAD_METRIC_NOT_REGISTERED.value in refused.reason_codes


def test_same_label_different_threshold_is_not_directly_comparable() -> None:
    left = _identity("threshold-20")
    right = replace(
        left,
        threshold=replace(left.threshold, threshold_value=25.0),
    )

    result = _compare(left, right)
    assert result.state is not result.state.COMPARABLE
    assert "THRESHOLD_VALUE_MISMATCH" in result.reason_codes
    assert result.rule_reference == EXTERNAL_LOAD_COMPARABILITY_RULE


def test_same_numeric_threshold_different_units_normalizes_for_comparison() -> None:
    left = _identity("threshold-kmh")
    right = replace(
        left,
        threshold=replace(
            left.threshold,
            threshold_value=20.0 / 3.6,
            threshold_unit=EXTERNAL_LOAD_METERS_PER_SECOND,
        ),
    )

    assert _compare(left, right).state.value == "COMPARABLE"


def test_absolute_and_individualized_thresholds_remain_distinct() -> None:
    left = _identity("absolute-threshold")
    right = replace(
        left,
        threshold=replace(
            left.threshold,
            basis=ThresholdBasis.INDIVIDUALIZED,
            individualized_reference=_reference("reference", "max-speed", "individual max speed"),
        ),
    )

    result = _compare(left, right)
    assert "THRESHOLD_BASIS_MISMATCH" in result.reason_codes
    assert result.state.value != "COMPARABLE"


def test_gnss_and_optical_modalities_require_a_bridge() -> None:
    left = _identity("gnss")
    optical_device = _reference("device", "optical", "optical system")
    right = replace(
        left,
        modality=ExternalLoadModality.OPTICAL_TRACKING,
        system=replace(
            left.system,
            provider="synthetic-optical-provider",
            device_or_system=optical_device,
            provider_algorithm=None,
            provider_algorithm_status=ProcessingComponentStatus.NOT_APPLICABLE,
        ),
        acquisition=replace(left.acquisition, device=optical_device),
    )

    result = _compare(left, right)
    assert "MODALITY_MISMATCH" in result.reason_codes
    assert result.state.value == "BRIDGE_VALIDATION_REQUIRED"


def test_provider_algorithms_and_origins_do_not_collapse() -> None:
    left = _identity(
        "provider-a",
        metric_family=ExternalLoadMetricFamily.PROVIDER_LOAD,
        value_origin=ValueOrigin.PROVIDER_DERIVED,
        output_unit=EXTERNAL_LOAD_COUNT,
        provider="provider-a",
        provider_algorithm=EXTERNAL_LOAD_SOURCE_A_PLAYERLOAD_ALGORITHM,
    )
    right = _identity(
        "provider-b",
        metric_family=ExternalLoadMetricFamily.PROVIDER_LOAD,
        value_origin=ValueOrigin.PROVIDER_DERIVED,
        output_unit=EXTERNAL_LOAD_COUNT,
        provider="provider-b",
        provider_algorithm=EXTERNAL_LOAD_SOURCE_A_GNSS_ALGORITHM,
    )

    result = _compare(left, right)
    assert "PROVIDER_MISMATCH" in result.reason_codes
    assert "PROVIDER_ALGORITHM_MISMATCH" in result.reason_codes
    assert result.state.value != "COMPARABLE"

    refused = refuse_unregistered_external_load_computation(left)
    assert RefusalReasonCode.PROVIDER_DERIVATION_NOT_RECOMPUTABLE.value in refused.reason_codes
    assert RefusalReasonCode.EXTERNAL_LOAD_METRIC_NOT_REGISTERED.value in refused.reason_codes


def test_total_distance_and_relative_distance_are_different_metric_identities() -> None:
    total = _identity(
        "total-distance",
        metric_family=ExternalLoadMetricFamily.TOTAL_DISTANCE,
        output_unit=EXTERNAL_LOAD_METER,
    )
    relative = _identity(
        "relative-distance",
        metric_family=ExternalLoadMetricFamily.RELATIVE_DISTANCE,
        normalization=ExternalLoadNormalizationIdentity(
            kind=NormalizationKind.DURATION_NORMALIZED,
            method=EXTERNAL_LOAD_RELATIVE_DISTANCE_OPERATION,
        ),
        output_unit=EXTERNAL_LOAD_METERS_PER_MINUTE,
    )

    result = _compare(total, relative)
    assert "METRIC_FAMILY_MISMATCH" in result.reason_codes
    assert result.state.value == "NOT_COMPARABLE"


def test_unknown_threshold_and_event_metadata_fail_closed() -> None:
    unknown = _identity(
        "unknown-threshold",
        threshold=ExternalLoadThresholdIdentity.unknown(),
    )
    result = _compare(unknown, unknown)
    # The request still uses two distinct observation IDs even if the identity
    # objects happen to be equal; missing threshold semantics remain unresolved.
    assert result.state.value == "INSUFFICIENT_INFORMATION"
    assert "UNKNOWN_THRESHOLD_BASIS" in result.reason_codes

    event_left = _identity(
        "dwell-left",
        metric_family=ExternalLoadMetricFamily.THRESHOLD_EVENT_COUNT,
        event_definition=_event(0.5),
        output_unit=EXTERNAL_LOAD_COUNT,
    )
    event_right = replace(event_left, event_definition=_event(1.0))
    event_result = _compare(event_left, event_right)
    assert "DWELL_RULE_MISMATCH" in event_result.reason_codes
    assert event_result.state.value != "COMPARABLE"


def test_session_aggregation_mismatch_is_not_comparable() -> None:
    left = _identity("match-aggregation", context=AggregationContext.MATCH)
    right = _identity("training-aggregation", context=AggregationContext.TRAINING)

    result = _compare(left, right)
    assert "EXPOSURE_CONTEXT_MISMATCH" in result.reason_codes
    assert result.state.value != "COMPARABLE"


def test_source_a_mapping_preserves_exact_threshold_and_provider_origin() -> None:
    variables = source_a_variable_identities(
        ("Distance>20,0km/h(m)", "Distance>25,0km/h(m)", "Playerload")
    )
    mapped = tuple(map_source_a_variable(variable) for variable in variables)
    mapping_20, mapping_25, playerload = mapped
    assert mapping_20 is not None and mapping_25 is not None and playerload is not None
    assert mapping_20.source_variable_id != mapping_25.source_variable_id
    assert mapping_20.external_identity.threshold.threshold_value == 20.0
    assert mapping_25.external_identity.threshold.threshold_value == 25.0
    assert mapping_20.external_identity.display_label == mapping_25.external_identity.display_label
    assert mapping_20.method_label == "Distance>20,0km/h(m)"
    assert mapping_20.provider == "UNIFESP Domus Dados / Dataverse"
    assert mapping_20.definition_status is ExternalLoadDefinitionStatus.PARTIAL
    assert from_canonical_json(canonical_json(mapping_20), ExternalLoadSourceMapping) == mapping_20
    assert playerload.external_identity.value_origin is ValueOrigin.PROVIDER_DERIVED
    assert playerload.external_identity.dynamislm_recomputable is False
    assert playerload.external_identity.definition_status.value == "PARTIAL"
    assert playerload.external_identity.modality is ExternalLoadModality.INERTIAL


def test_source_a_variable_identity_cannot_be_substituted() -> None:
    variable = source_a_variable_identities(("Distance>20,0km/h(m)",))[0]
    forged = replace(variable, source_threshold_or_band=">25.0 km/h")
    with pytest.raises(ValueError, match="cannot be substituted"):
        map_source_a_variable(forged)


def test_source_a_external_column_scope_and_qualified_invariants_remain_unchanged() -> None:
    assert source_a_external_column_names()[:5] == (
        "Matchduration(min)",
        "TotalDistance(m)",
        "Relativedistance(m/min)",
        "Distance>20,0km/h(m)",
        "Distance>25,0km/h(m)",
    )
    report_dir = Path(__file__).resolve().parents[1] / "reports" / "res63"
    schema = json.loads((report_dir / "source-a-schema.json").read_text())
    receipt = json.loads((report_dir / "source-a-artifact-receipt.json").read_text())
    assert schema["raw_artifact_sha256"] == (
        "sha256:f00cf3f32caa76c392e608630d3f2f30a2789c25446702678f7a268a622bf8e5"
    )
    assert receipt["canonical_artifact_sha256"] == (
        "sha256:7ef19b2b93ebd139d41cb63ecf1b5c57146f37af6d9652c943b886da7f92b98f"
    )
    assert receipt["canonical_record_count"] == 140454
    assert receipt["mapping_version"] == "unifesp-serie-a-mapping@1.1.0"
    assert receipt["variable_registry_sha256"] == (
        "sha256:02e2019a112edf70bba425bf1f8ef719e4d03e8fb72d039c351f4f1e7754fcf0"
    )
