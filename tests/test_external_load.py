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
    EXTERNAL_LOAD_DURATION_MEASURAND,
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
    EXTERNAL_LOAD_THRESHOLD_SUMMARY_OPERATION,
    EXTERNAL_LOAD_THRESHOLD_TIME_METRIC,
    EXTERNAL_LOAD_TOTAL_DISTANCE_METRIC,
    AcquisitionIdentity,
    AcquisitionRecord,
    AggregationContext,
    AggregationScope,
    ComparabilityResult,
    EventHysteresisIdentity,
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
    ExternalLoadVelocitySeriesEvidence,
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
    EXTERNAL_LOAD_CHANGE_OF_DIRECTION_LEFT_EVENT_COUNT_METRIC,
    EXTERNAL_LOAD_CHANGE_OF_DIRECTION_RIGHT_EVENT_COUNT_METRIC,
    EXTERNAL_LOAD_EXPLOSIVE_EFFORT_EVENT_COUNT_METRIC,
    EXTERNAL_LOAD_JUMP_EVENT_COUNT_METRIC,
    EXTERNAL_LOAD_MINUTES_EXPOSURE_METRIC,
    EXTERNAL_LOAD_PROVIDER_LOAD_MEASURAND,
    EXTERNAL_LOAD_PROVIDER_LOAD_METRIC,
    EXTERNAL_LOAD_RHIE_BOUT_COUNT_METRIC,
    EXTERNAL_LOAD_RHIE_EFFORTS_PER_BOUT_METRIC,
    EXTERNAL_LOAD_RHIE_RECOVERY_TIME_METRIC,
    EXTERNAL_LOAD_SESSION_DURATION_METRIC,
    EXTERNAL_LOAD_SOURCE_A_CHANGE_OF_DIRECTION_EVENT_DEFINITION,
    EXTERNAL_LOAD_SOURCE_A_EXPLOSIVE_EFFORT_EVENT_DEFINITION,
    EXTERNAL_LOAD_SOURCE_A_GNSS_ALGORITHM,
    EXTERNAL_LOAD_SOURCE_A_JUMP_EVENT_DEFINITION,
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
    output_unit: UnitReference | None = None,
    definition_status: ExternalLoadDefinitionStatus = ExternalLoadDefinitionStatus.RESOLVED,
) -> ExternalLoadMeasurementIdentity:
    metric_reference = {
        ExternalLoadMetricFamily.SESSION_DURATION: EXTERNAL_LOAD_SESSION_DURATION_METRIC,
        ExternalLoadMetricFamily.MINUTES_EXPOSURE: EXTERNAL_LOAD_MINUTES_EXPOSURE_METRIC,
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
        ExternalLoadMetricFamily.SESSION_DURATION: EXTERNAL_LOAD_DURATION_MEASURAND,
        ExternalLoadMetricFamily.MINUTES_EXPOSURE: EXTERNAL_LOAD_DURATION_MEASURAND,
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
    if output_unit is None:
        output_unit = {
            ExternalLoadMetricFamily.SESSION_DURATION: EXTERNAL_LOAD_MINUTE,
            ExternalLoadMetricFamily.MINUTES_EXPOSURE: EXTERNAL_LOAD_MINUTE,
            ExternalLoadMetricFamily.TOTAL_DISTANCE: EXTERNAL_LOAD_METER,
            ExternalLoadMetricFamily.RELATIVE_DISTANCE: EXTERNAL_LOAD_METERS_PER_MINUTE,
            ExternalLoadMetricFamily.THRESHOLD_TIME: EXTERNAL_LOAD_SECOND,
            ExternalLoadMetricFamily.THRESHOLD_EVENT_COUNT: EXTERNAL_LOAD_COUNT,
            ExternalLoadMetricFamily.ACCELERATION_EVENT_COUNT: EXTERNAL_LOAD_COUNT,
        }.get(metric_family, EXTERNAL_LOAD_METERS_PER_SECOND)
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
        parameters=identity.processing.method_parameters,
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
    *,
    context: ObservationContext | None = None,
    value: float = 1.0,
) -> ScientificMeasurementObservation:
    observation_id = InstanceIdentifier("observation", suffix)
    observation_context = context or ObservationContext(
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
        context=observation_context,
        identity=identity,
        result=MeasurementResult(
            result_id=InstanceIdentifier("result", suffix),
            value=ScalarValue(value),
            unit=unit,
            classification=ScientificClassification(identity.value_origin, ()),
            status=ResultStatus.VALID,
        ),
        provenance=_provenance(identity, observation_id),
    )


def _velocity_evidence(
    identity: ExternalLoadMeasurementIdentity,
    suffix: str,
    *,
    context: ObservationContext | None = None,
    maximum_gap_s: float | None = 1.0,
) -> ExternalLoadVelocitySeriesEvidence:
    observation_id = InstanceIdentifier("observation", f"velocity-{suffix}")
    observation_context = context or ObservationContext(
        context_id=InstanceIdentifier("context", f"velocity-{suffix}"),
        athlete_id=InstanceIdentifier("athlete", "athlete-1"),
        session_id=InstanceIdentifier("session", "session-1"),
        test_instance_id=InstanceIdentifier("test-instance", f"velocity-{suffix}"),
        trial_id=None,
        observed_at=datetime_module.datetime(2026, 1, 1, tzinfo=UTC),
        population_context="SYNTHETIC RES-64 velocity evidence",
    )
    artifact_id = InstanceIdentifier("artifact", f"artifact-velocity-{suffix}")
    assert identity.system.device_or_system is not None
    assert identity.system.sampling is not None
    series = VelocitySeries(
        InstanceIdentifier("series", f"velocity-{suffix}"),
        (
            VelocitySample(0.0, 0.0, EXTERNAL_LOAD_METERS_PER_SECOND),
            VelocitySample(1.0, 10.0, EXTERNAL_LOAD_METERS_PER_SECOND),
            VelocitySample(2.0, 10.0, EXTERNAL_LOAD_METERS_PER_SECOND),
            VelocitySample(3.0, 0.0, EXTERNAL_LOAD_METERS_PER_SECOND),
        ),
        maximum_gap_s=maximum_gap_s,
    )
    bound_identity = replace(
        identity,
        acquisition=replace(identity.acquisition, raw_artifact=artifact_id),
        processing=replace(
            identity.processing,
            method_parameters=(
                *identity.processing.method_parameters,
                MetadataEntry("series_id", f"series:velocity-{suffix}"),
                MetadataEntry("series_digest", canonical_hash(series)),
                MetadataEntry("observation_id", observation_id.qualified),
                MetadataEntry("context_id", observation_context.context_id.qualified),
                MetadataEntry("athlete_id", observation_context.athlete_id.qualified),
                MetadataEntry("session_id", observation_context.session_id.qualified),
                MetadataEntry("test_instance_id", observation_context.test_instance_id.qualified),
                MetadataEntry("source_artifact_id", artifact_id.qualified),
                MetadataEntry("device_identity", identity.system.device_or_system.stable_id),
                MetadataEntry("system_provider", identity.system.provider),
                MetadataEntry(
                    "sampling_frequency_hz",
                    identity.system.sampling.frequency_hz,
                ),
                MetadataEntry(
                    "sampling_channels",
                    ",".join(identity.system.sampling.channels),
                ),
            ),
        ),
    )
    provenance = _provenance(bound_identity, observation_id)
    return ExternalLoadVelocitySeriesEvidence(
        series=series,
        identity=bound_identity,
        context=observation_context,
        provenance=provenance,
        observation_id=observation_id,
    )


def _relative_observations(
    suffix: str,
) -> tuple[ScientificMeasurementObservation, ScientificMeasurementObservation]:
    context = ObservationContext(
        context_id=InstanceIdentifier("context", f"relative-{suffix}"),
        athlete_id=InstanceIdentifier("athlete", "athlete-1"),
        session_id=InstanceIdentifier("session", "session-1"),
        test_instance_id=InstanceIdentifier("test-instance", f"relative-{suffix}"),
        trial_id=None,
        observed_at=datetime_module.datetime(2026, 1, 1, tzinfo=UTC),
        population_context="SYNTHETIC RES-64 relative-distance evidence",
    )
    source = _identity(
        f"relative-source-{suffix}",
        metric_family=ExternalLoadMetricFamily.TOTAL_DISTANCE,
    )
    duration = _identity(
        f"relative-duration-{suffix}",
        metric_family=ExternalLoadMetricFamily.MINUTES_EXPOSURE,
    )
    return (
        _observation(source, f"relative-source-{suffix}", context=context, value=1_200.0),
        _observation(duration, f"relative-duration-{suffix}", context=context, value=120.0),
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
    shared_context = ObservationContext(
        context_id=InstanceIdentifier("context", "derived-shared"),
        athlete_id=InstanceIdentifier("athlete", "athlete-1"),
        session_id=InstanceIdentifier("session", "session-1"),
        test_instance_id=InstanceIdentifier("test-instance", "derived-shared"),
        trial_id=None,
        observed_at=datetime_module.datetime(2026, 1, 1, tzinfo=UTC),
        population_context="SYNTHETIC RES-64 descriptive context",
    )
    source_observation = _observation(
        source, "derived-source", context=shared_context, value=1_200.0
    )
    duration_observation = _observation(
        duration,
        "derived-duration",
        context=shared_context,
        value=120.0,
    )
    result = derive_duration_normalized_distance(
        source_observation,
        duration_observation,
    )

    assert isinstance(result, ExternalLoadMetricResult)
    assert result.value == pytest.approx(10.0)
    assert result.metric_identity.value_origin is ValueOrigin.DYNAMISLM_DERIVED
    assert result.measurement_result.classification.value_origin is ValueOrigin.DYNAMISLM_DERIVED
    assert result.metric_identity.dynamislm_recomputable is True
    assert result.input_observations == (source_observation, duration_observation)
    assert result.derived_observation is not None
    assert from_canonical_json(canonical_json(result), ExternalLoadMetricResult) == result


def test_relative_distance_rejects_scalar_cross_binding_even_with_legacy_metadata() -> None:
    source_observation, duration_observation = _relative_observations("scalar-attack")
    assert isinstance(source_observation.identity, ExternalLoadMeasurementIdentity)
    assert isinstance(duration_observation.identity, ExternalLoadMeasurementIdentity)

    refused = derive_duration_normalized_distance(
        source_observation,
        duration_observation,
        total_distance=999_999.0,
        valid_duration=1.0,
        distance_unit=EXTERNAL_LOAD_METER,
        duration_unit=EXTERNAL_LOAD_SECOND,
        source_identity=source_observation.identity,
        duration_identity=duration_observation.identity,
    )

    assert isinstance(refused, RefusalResult)
    assert RefusalReasonCode.MISSING_METADATA.value in refused.reason_codes


def test_relative_distance_rejects_observation_value_unit_and_provenance_mismatch() -> None:
    source_observation, duration_observation = _relative_observations("binding-attack")
    wrong_unit = replace(
        source_observation,
        result=replace(source_observation.result, unit=EXTERNAL_LOAD_SECOND),
    )
    refused_unit = derive_duration_normalized_distance(wrong_unit, duration_observation)
    assert isinstance(refused_unit, RefusalResult)
    assert RefusalReasonCode.UNIT_OR_NORMALIZATION_MISMATCH.value in refused_unit.reason_codes

    unrelated_identity = _identity(
        "unrelated-provenance",
        metric_family=ExternalLoadMetricFamily.TOTAL_DISTANCE,
    )
    unrelated_provenance = _provenance(unrelated_identity, source_observation.observation_id)
    wrong_provenance = replace(source_observation, provenance=unrelated_provenance)
    refused_provenance = derive_duration_normalized_distance(
        wrong_provenance,
        duration_observation,
    )
    assert isinstance(refused_provenance, RefusalResult)
    assert (
        RefusalReasonCode.ACQUISITION_ARRANGEMENT_MISMATCH.value in refused_provenance.reason_codes
    )


@pytest.mark.parametrize("context_field", ["athlete_id", "session_id"])
def test_relative_distance_rejects_mismatched_athlete_or_session(context_field: str) -> None:
    source_observation, duration_observation = _relative_observations(f"context-{context_field}")
    if context_field == "athlete_id":
        changed_context = replace(
            duration_observation.context,
            athlete_id=InstanceIdentifier("athlete", "different"),
        )
    else:
        changed_context = replace(
            duration_observation.context,
            session_id=InstanceIdentifier("session", "different"),
        )
    wrong_duration = replace(duration_observation, context=changed_context)

    refused = derive_duration_normalized_distance(source_observation, wrong_duration)

    assert isinstance(refused, RefusalResult)
    assert RefusalReasonCode.ACQUISITION_ARRANGEMENT_MISMATCH.value in refused.reason_codes


def test_distinct_duration_denominators_produce_distinct_derived_measurement_identities() -> None:
    source_observation, minutes_observation = _relative_observations("denominator")
    session_duration_identity = _identity(
        "session-denominator",
        metric_family=ExternalLoadMetricFamily.SESSION_DURATION,
    )
    session_duration_observation = _observation(
        session_duration_identity,
        "session-denominator",
        context=minutes_observation.context,
        value=120.0,
    )

    minutes_result = derive_duration_normalized_distance(
        source_observation,
        minutes_observation,
    )
    session_result = derive_duration_normalized_distance(
        source_observation,
        session_duration_observation,
    )

    assert isinstance(minutes_result, ExternalLoadMetricResult)
    assert isinstance(session_result, ExternalLoadMetricResult)
    assert minutes_result.metric_identity.identity_id != session_result.metric_identity.identity_id
    assert (
        minutes_result.metric_identity.normalization.parameters
        != session_result.metric_identity.normalization.parameters
    )


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
    evidence = _velocity_evidence(identity, "threshold-summary")
    summary = summarize_velocity_threshold(evidence)

    assert isinstance(summary, ExternalLoadThresholdSummary)
    assert summary.time_above_threshold_s == pytest.approx(2.0)
    assert summary.distance_above_threshold_m == pytest.approx(17.5)
    assert summary.event_count is None
    assert summary.time_result is not None
    assert summary.distance_result is not None
    assert summary.time_result.value == pytest.approx(2.0)
    assert summary.distance_result.value == pytest.approx(17.5)
    assert (
        summary.time_result.measurement_result.classification.value_origin
        is ValueOrigin.DYNAMISLM_DERIVED
    )
    assert summary.time_result.source_series_evidence == evidence
    assert summary.time_result.metric_identity.threshold == evidence.identity.threshold
    assert summary.time_result.metric_identity.aggregation == evidence.identity.aggregation
    assert (
        summary.time_result.metric_identity.processing.filtering_status
        == evidence.identity.processing.filtering_status
    )
    assert (
        summary.time_result.metric_identity.processing.smoothing
        == evidence.identity.processing.smoothing
    )
    assert (
        summary.time_result.metric_identity.processing.resampling
        == evidence.identity.processing.resampling
    )
    assert summary.time_result.metric_identity.system == evidence.identity.system
    assert summary.time_result.metric_identity.processing.registered_operation == (
        EXTERNAL_LOAD_THRESHOLD_SUMMARY_OPERATION
    )


def test_threshold_event_count_requires_and_uses_dwell_definition() -> None:
    identity = _identity(
        "event-summary",
        metric_family=ExternalLoadMetricFamily.THRESHOLD_EVENT_COUNT,
        event_definition=_event(0.5),
        output_unit=EXTERNAL_LOAD_COUNT,
    )
    evidence = _velocity_evidence(identity, "event-summary")
    summary = summarize_velocity_threshold(evidence)
    assert isinstance(summary, ExternalLoadThresholdSummary)
    assert summary.event_count == 1
    assert summary.event_count_result is not None
    assert summary.event_count_result.value == pytest.approx(1.0)
    assert summary.event_count_result.metric_identity.value_origin is ValueOrigin.DYNAMISLM_DERIVED
    assert summary.event_count_result.unit == EXTERNAL_LOAD_COUNT
    restored = from_canonical_json(canonical_json(summary), ExternalLoadThresholdSummary)
    assert restored == summary

    unresolved = _identity(
        "event-summary-unresolved",
        metric_family=ExternalLoadMetricFamily.THRESHOLD_EVENT_COUNT,
        event_definition=_event(None),
        output_unit=EXTERNAL_LOAD_COUNT,
    )
    unresolved_evidence = _velocity_evidence(unresolved, "event-summary-unresolved")
    refused = summarize_velocity_threshold(unresolved_evidence)
    assert isinstance(refused, RefusalResult)
    assert RefusalReasonCode.UNKNOWN_DWELL_RULE.value in refused.reason_codes


def test_velocity_series_requires_evidence_binding_and_roundtrips() -> None:
    identity = _identity("evidence-binding")
    evidence = _velocity_evidence(identity, "evidence-binding")

    refused = summarize_velocity_threshold(evidence.series, evidence.identity)
    assert isinstance(refused, RefusalResult)
    assert RefusalReasonCode.THRESHOLD_SUMMARY_REQUIRES_RAW_SERIES.value in refused.reason_codes

    restored = from_canonical_json(
        canonical_json(evidence),
        ExternalLoadVelocitySeriesEvidence,
    )
    assert restored == evidence


def test_velocity_series_cross_binding_attacks_are_blocked() -> None:
    identity = _identity("series-cross-binding")
    evidence = _velocity_evidence(identity, "series-cross-binding")

    wrong_device = _reference("device", "wrong-device", "wrong device")
    wrong_device_identity = replace(
        evidence.identity,
        system=replace(evidence.identity.system, device_or_system=wrong_device),
        acquisition=replace(evidence.identity.acquisition, device=wrong_device),
    )
    wrong_device_refused = summarize_velocity_threshold(evidence, wrong_device_identity)
    assert isinstance(wrong_device_refused, RefusalResult)
    assert RefusalReasonCode.ACQUISITION_ARRANGEMENT_MISMATCH.value in (
        wrong_device_refused.reason_codes
    )

    wrong_session_identity = replace(
        evidence.identity,
        aggregation=replace(
            evidence.identity.aggregation,
            session_definition=_reference("session-definition", "other", "other session"),
        ),
    )
    wrong_session_refused = summarize_velocity_threshold(evidence, wrong_session_identity)
    assert isinstance(wrong_session_refused, RefusalResult)
    assert RefusalReasonCode.SOURCE_PROCESSING_MISMATCH.value in (
        wrong_session_refused.reason_codes
    )

    wrong_sampling = SamplingCharacteristics(20.0, ("velocity",), "float64")
    wrong_sampling_identity = replace(
        evidence.identity,
        system=replace(evidence.identity.system, sampling=wrong_sampling),
        acquisition=replace(evidence.identity.acquisition, sampling=wrong_sampling),
    )
    wrong_sampling_refused = summarize_velocity_threshold(evidence, wrong_sampling_identity)
    assert isinstance(wrong_sampling_refused, RefusalResult)
    assert RefusalReasonCode.SAMPLE_OR_TIMEBASE_MISMATCH.value in (
        wrong_sampling_refused.reason_codes
    )

    other_evidence = _velocity_evidence(_identity("other-series"), "other-series")
    wrong_provenance = replace(evidence, provenance=other_evidence.provenance)
    wrong_provenance_refused = summarize_velocity_threshold(wrong_provenance)
    assert isinstance(wrong_provenance_refused, RefusalResult)
    assert RefusalReasonCode.SOURCE_ARTIFACT_UNVERIFIED.value in (
        wrong_provenance_refused.reason_codes
    )

    tampered_series = replace(
        evidence.series,
        samples=(
            evidence.series.samples[0],
            replace(evidence.series.samples[1], velocity=999.0),
            *evidence.series.samples[2:],
        ),
    )
    tampered_refused = summarize_velocity_threshold(replace(evidence, series=tampered_series))
    assert isinstance(tampered_refused, RefusalResult)
    assert RefusalReasonCode.PROCESSING_LINEAGE_UNRESOLVED.value in (tampered_refused.reason_codes)


def test_threshold_quantity_substitution_is_blocked() -> None:
    identity = _identity("threshold-quantity")
    wrong_quantity = _reference("measurand", "heart-rate", "Heart rate")
    forged_identity = replace(
        identity,
        threshold=replace(identity.threshold, threshold_quantity=wrong_quantity),
    )
    evidence = _velocity_evidence(forged_identity, "threshold-quantity")

    refused = summarize_velocity_threshold(evidence)

    assert isinstance(refused, RefusalResult)
    assert RefusalReasonCode.MEASURAND_MISMATCH.value in refused.reason_codes


@pytest.mark.parametrize("field_name", ["definition", "start_rule", "end_rule"])
def test_threshold_event_reference_substitution_is_blocked(field_name: str) -> None:
    identity = _identity(
        "event-reference-substitution",
        metric_family=ExternalLoadMetricFamily.THRESHOLD_EVENT_COUNT,
        event_definition=_event(),
    )
    assert identity.event_definition is not None
    forged_reference = _reference("event-rule", f"forged-{field_name}", "forged")
    if field_name == "definition":
        forged_event = replace(identity.event_definition, definition=forged_reference)
    elif field_name == "start_rule":
        forged_event = replace(identity.event_definition, start_rule=forged_reference)
    else:
        forged_event = replace(identity.event_definition, end_rule=forged_reference)
    forged_identity = replace(identity, event_definition=forged_event)
    evidence = _velocity_evidence(forged_identity, f"event-reference-{field_name}")

    refused = summarize_velocity_threshold(evidence)

    assert isinstance(refused, RefusalResult)
    assert any(
        reason in refused.reason_codes
        for reason in (
            RefusalReasonCode.EVENT_DEFINITION_MISMATCH.value,
            RefusalReasonCode.EVENT_METHOD_MISMATCH.value,
        )
    )


def test_defined_hysteresis_without_registered_implementation_is_blocked() -> None:
    identity = _identity(
        "hysteresis-unregistered",
        metric_family=ExternalLoadMetricFamily.THRESHOLD_EVENT_COUNT,
        event_definition=_event(),
    )
    assert identity.event_definition is not None
    hysteresis = EventHysteresisIdentity(
        quantity=EXTERNAL_LOAD_SPEED_MEASURAND,
        entry_value=5.0,
        exit_value=4.5,
        unit=EXTERNAL_LOAD_METERS_PER_SECOND,
        entry_boundary=ThresholdBoundary.GREATER_THAN,
        exit_boundary=ThresholdBoundary.LESS_THAN_OR_EQUAL,
    )
    forged_identity = replace(
        identity,
        event_definition=replace(
            identity.event_definition,
            hysteresis_status=EventHysteresisStatus.DEFINED,
            hysteresis=hysteresis,
        ),
    )
    evidence = _velocity_evidence(forged_identity, "hysteresis-unregistered")

    refused = summarize_velocity_threshold(evidence)

    assert isinstance(refused, RefusalResult)
    assert RefusalReasonCode.EXTERNAL_LOAD_METRIC_NOT_REGISTERED.value in refused.reason_codes


def test_raw_threshold_result_without_bound_evidence_is_not_authoritative() -> None:
    identity = _identity("raw-result-authority")
    summary = summarize_velocity_threshold(_velocity_evidence(identity, "raw-result-authority"))
    assert isinstance(summary, ExternalLoadThresholdSummary)
    assert summary.time_result is not None
    with pytest.raises(ValueError, match="disagrees"):
        replace(summary, time_above_threshold_s=999_999.0)

    forged_measurement_result = replace(
        summary.time_result.measurement_result,
        value=ScalarValue(999_999.0),
    )
    with pytest.raises(ValueError, match="registered execution"):
        ExternalLoadMetricResult(
            operation=summary.time_result.operation,
            metric_identity=summary.time_result.metric_identity,
            measurement_result=forged_measurement_result,
            input_identity_ids=summary.time_result.input_identity_ids,
            source_observation_ids=summary.time_result.source_observation_ids,
            source_series_id=summary.time_result.source_series_id,
            source_provenance=summary.time_result.source_provenance,
            source_series_evidence=summary.time_result.source_series_evidence,
        )


def test_unknown_filtering_and_undeclared_gap_refuse_threshold_summary() -> None:
    identity = _identity(
        "unknown-filter",
        filtering_status=ProcessingComponentStatus.UNKNOWN,
    )
    evidence = _velocity_evidence(identity, "unknown-filter")
    refused = summarize_velocity_threshold(evidence)
    assert isinstance(refused, RefusalResult)
    assert RefusalReasonCode.UNKNOWN_FILTERING.value in refused.reason_codes

    gap_identity = _identity("undeclared-gap")
    gap_evidence = _velocity_evidence(gap_identity, "undeclared-gap", maximum_gap_s=None)
    gap_refused = summarize_velocity_threshold(gap_evidence)
    assert isinstance(gap_refused, RefusalResult)
    assert RefusalReasonCode.UNDECLARED_TIME_GAP.value in gap_refused.reason_codes


def test_acceleration_event_family_has_no_hidden_velocity_threshold_authority() -> None:
    identity = _identity(
        "acceleration-no-authority",
        metric_family=ExternalLoadMetricFamily.ACCELERATION_EVENT_COUNT,
        output_unit=EXTERNAL_LOAD_COUNT,
    )
    evidence = _velocity_evidence(identity, "acceleration-no-authority")
    refused = summarize_velocity_threshold(evidence)
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


def test_provider_output_cannot_gain_dynamislm_authority_or_direct_comparability() -> None:
    provider = _identity(
        "provider-authority",
        metric_family=ExternalLoadMetricFamily.PROVIDER_LOAD,
        value_origin=ValueOrigin.PROVIDER_DERIVED,
        output_unit=EXTERNAL_LOAD_COUNT,
        provider_algorithm=EXTERNAL_LOAD_SOURCE_A_PLAYERLOAD_ALGORITHM,
    )
    with pytest.raises(ValueError, match="cannot claim DynamisLM recomputability"):
        replace(
            provider,
            value_origin=ValueOrigin.PROVIDER_DERIVED,
            dynamislm_recomputable=True,
        )

    derived = replace(
        provider,
        identity_id=ScientificIdentifier(
            "synthetic-res64",
            "measurement-identity",
            "derived-provider-authority",
            "1.0.0",
        ),
        value_origin=ValueOrigin.DYNAMISLM_DERIVED,
        dynamislm_recomputable=True,
        processing=replace(
            provider.processing,
            registered_operation=EXTERNAL_LOAD_RELATIVE_DISTANCE_OPERATION,
            unit=EXTERNAL_LOAD_METERS_PER_MINUTE,
        ),
        version=replace(
            provider.version,
            processing_method=EXTERNAL_LOAD_RELATIVE_DISTANCE_OPERATION,
        ),
        semantic=replace(
            provider.semantic, metric_definition=EXTERNAL_LOAD_RELATIVE_DISTANCE_METRIC
        ),
        metric_family=ExternalLoadMetricFamily.RELATIVE_DISTANCE,
        normalization=ExternalLoadNormalizationIdentity(
            kind=NormalizationKind.DURATION_NORMALIZED,
            method=EXTERNAL_LOAD_RELATIVE_DISTANCE_OPERATION,
        ),
    )
    result = _compare(provider, derived)
    assert "VALUE_ORIGIN_MISMATCH" in result.reason_codes
    assert result.state.value != "COMPARABLE"


def test_unknown_provider_algorithm_and_event_rule_differences_fail_closed() -> None:
    known_provider = _identity(
        "known-provider-algorithm",
        metric_family=ExternalLoadMetricFamily.PROVIDER_LOAD,
        value_origin=ValueOrigin.PROVIDER_DERIVED,
        output_unit=EXTERNAL_LOAD_COUNT,
        provider_algorithm=EXTERNAL_LOAD_SOURCE_A_PLAYERLOAD_ALGORITHM,
    )
    unknown_system = replace(
        known_provider.system,
        provider_algorithm=None,
        provider_algorithm_status=ProcessingComponentStatus.UNKNOWN,
    )
    unknown_provider = replace(known_provider, system=unknown_system)
    provider_comparison = _compare(unknown_provider, known_provider)
    assert "UNKNOWN_PROVIDER_ALGORITHM" in provider_comparison.reason_codes
    assert provider_comparison.state.value == "INSUFFICIENT_INFORMATION"

    event_left = _identity(
        "event-rule-left",
        metric_family=ExternalLoadMetricFamily.THRESHOLD_EVENT_COUNT,
        event_definition=_event(),
    )
    assert event_left.event_definition is not None
    event_right = replace(
        event_left,
        event_definition=replace(
            event_left.event_definition,
            start_rule=_reference("event-rule", "different-start", "different start"),
        ),
    )
    event_comparison = _compare(event_left, event_right)
    assert "EVENT_START_RULE_MISMATCH" in event_comparison.reason_codes
    assert event_comparison.state.value != "COMPARABLE"


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
    assert mapping_20.provider == "Catapult"
    assert mapping_20.dataset_provider == "UNIFESP Domus Dados / Dataverse"
    assert mapping_20.external_identity.system.device_or_system is not None
    assert mapping_20.external_identity.system.device_or_system.stable_id.endswith(
        "device:catapult-vector7@1.0.0"
    )
    assert mapping_20.external_identity.system.sampling is not None
    assert mapping_20.external_identity.system.sampling.frequency_hz == 18.0
    acquisition_metadata = {
        entry.key: entry.value
        for entry in mapping_20.external_identity.system.acquisition_characteristics
    }
    assert acquisition_metadata == {
        "gnss_acquisition_frequency_hz": 18.0,
        "lps_acquisition_frequency_hz": 10.0,
        "accelerometer_sensor_sampling_frequency_hz": 1000.0,
        "accelerometer_provider_output_frequency_hz": 100.0,
        "gyroscope_sampling_frequency_hz": 100.0,
        "magnetometer_sampling_frequency_hz": 100.0,
    }
    assert mapping_20.definition_status is ExternalLoadDefinitionStatus.PARTIAL
    assert from_canonical_json(canonical_json(mapping_20), ExternalLoadSourceMapping) == mapping_20
    assert playerload.external_identity.value_origin is ValueOrigin.PROVIDER_DERIVED
    assert playerload.external_identity.dynamislm_recomputable is False
    assert playerload.external_identity.definition_status.value == "PARTIAL"
    assert playerload.external_identity.modality is ExternalLoadModality.INERTIAL


def test_source_a_supported_provider_event_mappings_keep_specific_count_identities() -> None:
    columns = (
        "Sprints",
        "Explosiveefforts(N)",
        "Acceleration(N)",
        "Deceleration(N)",
        "Changeofdirectiontoleft(N)",
        "Changeofdirectiontoright(N)",
        "Jumps>40cm(IMA)",
        "RHIEBoutRecoveryMean(s)",
        "RHIETotalBouts(N)",
        "RHIEEffortsPerBout-Mean",
    )
    mapped = tuple(
        map_source_a_variable(variable) for variable in source_a_variable_identities(columns)
    )
    assert all(mapping is not None for mapping in mapped)
    by_column = {mapping.method_label: mapping for mapping in mapped if mapping is not None}

    assert by_column["Sprints"].external_identity.processing.unit == EXTERNAL_LOAD_COUNT
    assert (
        by_column["Explosiveefforts(N)"].external_identity.semantic.metric_definition
        == EXTERNAL_LOAD_EXPLOSIVE_EFFORT_EVENT_COUNT_METRIC
    )
    explosive_event = by_column["Explosiveefforts(N)"].external_identity.event_definition
    assert explosive_event is not None
    assert explosive_event.definition == EXTERNAL_LOAD_SOURCE_A_EXPLOSIVE_EFFORT_EVENT_DEFINITION
    assert by_column["Explosiveefforts(N)"].external_identity.processing.unit == EXTERNAL_LOAD_COUNT
    assert by_column["Acceleration(N)"].external_identity.processing.unit == EXTERNAL_LOAD_COUNT
    assert by_column["Deceleration(N)"].external_identity.processing.unit == EXTERNAL_LOAD_COUNT
    assert (
        by_column["Changeofdirectiontoleft(N)"].external_identity.semantic.metric_definition
        == EXTERNAL_LOAD_CHANGE_OF_DIRECTION_LEFT_EVENT_COUNT_METRIC
    )
    assert (
        by_column["Changeofdirectiontoright(N)"].external_identity.semantic.metric_definition
        == EXTERNAL_LOAD_CHANGE_OF_DIRECTION_RIGHT_EVENT_COUNT_METRIC
    )
    assert by_column["Changeofdirectiontoleft(N)"].external_identity.event_definition is not None
    assert (
        by_column["Changeofdirectiontoleft(N)"].external_identity.event_definition.definition
        == EXTERNAL_LOAD_SOURCE_A_CHANGE_OF_DIRECTION_EVENT_DEFINITION
    )
    assert (
        by_column["Jumps>40cm(IMA)"].external_identity.semantic.metric_definition
        == EXTERNAL_LOAD_JUMP_EVENT_COUNT_METRIC
    )
    assert by_column["Jumps>40cm(IMA)"].external_identity.event_definition is not None
    assert (
        by_column["Jumps>40cm(IMA)"].external_identity.event_definition.definition
        == EXTERNAL_LOAD_SOURCE_A_JUMP_EVENT_DEFINITION
    )
    assert (
        by_column["RHIEBoutRecoveryMean(s)"].external_identity.semantic.metric_definition
        == EXTERNAL_LOAD_RHIE_RECOVERY_TIME_METRIC
    )
    assert (
        by_column["RHIETotalBouts(N)"].external_identity.semantic.metric_definition
        == EXTERNAL_LOAD_RHIE_BOUT_COUNT_METRIC
    )
    assert (
        by_column["RHIEEffortsPerBout-Mean"].external_identity.semantic.metric_definition
        == EXTERNAL_LOAD_RHIE_EFFORTS_PER_BOUT_METRIC
    )
    assert by_column["RHIETotalBouts(N)"].external_identity.processing.unit == EXTERNAL_LOAD_COUNT
    assert (
        by_column["RHIEEffortsPerBout-Mean"].external_identity.processing.unit
        == EXTERNAL_LOAD_COUNT
    )
    assert by_column["Jumps>40cm(IMA)"].external_identity.system.sampling is not None
    assert by_column["Jumps>40cm(IMA)"].external_identity.system.sampling.frequency_hz == 100.0
    for mapping in by_column.values():
        assert mapping.external_identity.value_origin is ValueOrigin.PROVIDER_DERIVED
        assert mapping.external_identity.dynamislm_recomputable is False
        assert mapping.external_identity.system.provider == "Catapult"
        assert mapping.dataset_provider == "UNIFESP Domus Dados / Dataverse"
        assert mapping.external_identity.system.provider != mapping.dataset_provider
        assert (
            mapping.external_identity.system.provider_algorithm_status
            is ProcessingComponentStatus.UNKNOWN
        )
        assert (
            mapping.external_identity.processing.filtering_status
            is ProcessingComponentStatus.UNKNOWN
        )
        assert (
            mapping.external_identity.processing.smoothing.status
            is ProcessingComponentStatus.UNKNOWN
        )
        assert (
            mapping.external_identity.processing.resampling.status
            is ProcessingComponentStatus.UNKNOWN
        )
        assert mapping.external_identity.system.firmware_version is None
        assert mapping.external_identity.system.software_version is None
        assert mapping.external_identity.system.processing_version is None


def test_source_a_mapping_constructor_blocks_exact_variable_cross_binding() -> None:
    variable_20 = source_a_variable_identities(("Distance>20,0km/h(m)",))[0]
    variable_25 = source_a_variable_identities(("Distance>25,0km/h(m)",))[0]
    mapping_20 = map_source_a_variable(variable_20)
    mapping_25 = map_source_a_variable(variable_25)
    assert mapping_20 is not None and mapping_25 is not None

    with pytest.raises(ValueError, match="exact Source A variable interpretation"):
        ExternalLoadSourceMapping(
            source_variable_id=mapping_20.source_variable_id,
            source_variable_identity=variable_20,
            external_identity=mapping_25.external_identity,
        )


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
