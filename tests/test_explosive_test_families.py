"""Synthetic RES-68 contract tests; no empirical source bytes are committed."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import cast

import pytest

from dynamislm.comparability.models import ComparabilityResult, ComparabilityState
from dynamislm.measurement.bench_press_throw import (
    BenchPressThrowAcquisitionIdentity,
    BenchPressThrowAcquisitionRecord,
    BenchPressThrowMeasurementIdentity,
    BenchPressThrowMetricResult,
    BenchPressThrowMetricSupport,
    BenchPressThrowProcessingIdentity,
    BenchPressThrowProtocolIdentity,
    BenchPressThrowSemanticIdentity,
    BenchPressThrowSourceArtifact,
    BenchPressThrowVelocitySeries,
    BenchPressThrowVelocitySeriesEvidence,
    BPTArtifactHashScope,
    BPTArtifactStatus,
    BPTCatchSemantics,
    BPTCounterbalanceStatus,
    BPTLoadIdentity,
    BPTLoadKind,
    BPTMachineType,
    BPTMetricSupportSourceEvidence,
    BPTMovementPattern,
    BPTPauseTouchBounce,
    BPTProcessingState,
    BPTProviderMetricResult,
    BPTQualificationStatus,
    BPTReleaseSemantics,
    BPTSensorModality,
    BPTSourceQualificationEvidence,
    BPTTimebase,
    BPTTimebaseKind,
    build_bpt_provider_metric_observation,
    build_bpt_qualification_source_observation,
    calculate_bpt_dynamislm_time_weighted_mean_bar_velocity,
    calculate_bpt_load_times_velocity_power,
    calculate_bpt_mean_power,
    calculate_bpt_mean_propulsive_velocity,
    calculate_bpt_sampled_maximum_bar_velocity,
    compare_bpt_metric_results,
    create_bpt_velocity_series_evidence,
    normalize_bpt_metric_support,
    normalize_bpt_qualification,
    wrap_bpt_provider_metric,
)
from dynamislm.measurement.bench_press_throw.registry import (
    BPT_BAR_VELOCITY_MEASURAND,
    BPT_CONSTRUCT,
    BPT_DYNAMISLM_TIME_WEIGHTED_MEAN_BAR_VELOCITY_METRIC,
    BPT_MEAN_POWER_MEASURAND,
    BPT_MEAN_PROPULSIVE_VELOCITY_MEASURAND,
    BPT_METRIC_SUPPORT_BOUNDARY_CONVENTION,
    BPT_METRIC_SUPPORT_METHOD,
    BPT_METRIC_SUPPORT_QUALIFICATION_RULE,
    BPT_METRIC_SUPPORT_SOURCE_OPERATION,
    BPT_PEAK_POWER_MEASURAND,
    BPT_PROVIDER_MAXIMUM_VELOCITY_METRIC,
    BPT_PROVIDER_MEAN_POWER_METRIC,
    BPT_PROVIDER_MEAN_PROPULSIVE_VELOCITY_METRIC,
    BPT_PROVIDER_MEAN_VELOCITY_METRIC,
    BPT_PROVIDER_PEAK_POWER_METRIC,
    BPT_REGISTRY_VERSION,
    BPT_SAMPLED_MAXIMUM_BAR_VELOCITY_METRIC,
    BPT_SOURCE_VELOCITY_SERIES_OPERATION,
    BPT_TEST_FAMILY,
    BPT_VELOCITY_SERIES_METRIC,
    KILOGRAM,
    METER_PER_SECOND,
    WATT,
)
from dynamislm.measurement.cmj.weighing import STANDARD_GRAVITY
from dynamislm.measurement.drop_jump import (
    DROP_JUMP_REBOUND_TAKEOFF_DETECTOR,
    DROP_JUMP_SUBSEQUENT_LANDING_DETECTOR,
    DROP_JUMP_TOUCHDOWN_DETECTOR,
    DropJumpAcquisitionIdentity,
    DropJumpAcquisitionRecord,
    DropJumpArmCondition,
    DropJumpArtifactHashScope,
    DropJumpArtifactStatus,
    DropJumpEventDetectorParameters,
    DropJumpEventLabel,
    DropJumpEventOccurrence,
    DropJumpEventOccurrenceStatus,
    DropJumpEventSourceEvidence,
    DropJumpFlightTimeApplicability,
    DropJumpInitiationMode,
    DropJumpMeasurementIdentity,
    DropJumpMetricResult,
    DropJumpProcessingIdentity,
    DropJumpProcessingState,
    DropJumpProtocolIdentity,
    DropJumpQualificationStatus,
    DropJumpReboundStrategy,
    DropJumpSemanticIdentity,
    DropJumpSensorModality,
    DropJumpSourceArtifact,
    DropJumpSourceQualificationEvidence,
    DropJumpTimebase,
    DropJumpTimebaseKind,
    build_drop_jump_event_occurrence,
    build_drop_jump_qualification_source_observation,
    build_drop_jump_source_observation,
    calculate_drop_jump_contact_time,
    calculate_drop_jump_flight_time_jump_height,
    calculate_drop_jump_rebound_flight_time,
    calculate_drop_jump_rsi_jh_ct,
    calculate_drop_jump_rsr_ft_ct,
    compare_drop_jump_metric_results,
    normalize_drop_jump_qualification,
    validate_drop_jump_event_order,
)
from dynamislm.measurement.drop_jump.registry import (
    DROP_JUMP_CONSTRUCT,
    DROP_JUMP_EVENT_SCHEMA,
    DROP_JUMP_PROTOCOL_V1,
    DROP_JUMP_SOURCE_OBSERVATION_OPERATION,
    DROP_JUMP_SOURCE_SERIES_MEASURAND,
    DROP_JUMP_SOURCE_SERIES_METRIC,
    DROP_JUMP_TEST_FAMILY,
)
from dynamislm.measurement.identity import (
    InstanceIdentifier,
    MetadataEntry,
    RegistryReference,
    ScientificIdentifier,
    SignConvention,
    VersionIdentity,
)
from dynamislm.measurement.medicine_ball_throw import (
    MBTAllowedState,
    MBTArtifactHashScope,
    MBTArtifactStatus,
    MBTBodyPosture,
    MBTCoordinateEvidence,
    MBTCoordinateSourceEvidence,
    MBTQualificationStatus,
    MBTReleaseEvent,
    MBTReleaseEventSourceEvidence,
    MBTReleaseSemantics,
    MBTReleaseVelocityEvidence,
    MBTSensorModality,
    MBTSourceQualificationEvidence,
    MBTSupportCondition,
    MBTThrowVariant,
    MBTTimebase,
    MBTTimebaseKind,
    MedicineBallThrowAcquisitionRecord,
    MedicineBallThrowMetricResult,
    MedicineBallThrowProtocolIdentity,
    MedicineBallThrowSourceArtifact,
    build_mbt_qualification_source_observation,
    build_mbt_release_velocity_evidence,
    build_mbt_source_distance_observation,
    calculate_mbt_distance_as_power,
    calculate_mbt_instrumented_release_velocity,
    calculate_mbt_release_velocity_from_distance,
    calculate_mbt_throw_distance,
    compare_mbt_metric_results,
    normalize_mbt_coordinate_evidence,
    normalize_mbt_qualification,
)
from dynamislm.measurement.medicine_ball_throw.qualification import _release_event_source_parameters
from dynamislm.measurement.medicine_ball_throw.registry import (
    MBT_COORDINATE_QUALIFICATION_RULE,
    MBT_COORDINATE_SOURCE_OPERATION,
    MBT_RELEASE_EVENT_QUALIFICATION_RULE,
    MBT_RELEASE_EVENT_SOURCE_OPERATION,
)
from dynamislm.measurement.observation import ObservationContext, ScientificMeasurementObservation
from dynamislm.measurement.result import (
    MeasurementQuality,
    MeasurementResult,
    ScalarValue,
    StructuredOutputReference,
    UncertaintyMetadata,
)
from dynamislm.measurement.taxonomy import ScientificClassification, ValueOrigin
from dynamislm.provenance import LineageEdge, LineageRelation, ProcessingRun, Provenance
from dynamislm.refusal.models import RefusalResult
from dynamislm.serialization import (
    SERIALIZATION_VERSION,
    canonical_hash,
    canonical_json,
    from_canonical_json,
)
from test_cmj_jump_height import _flight_events


def _ref(object_type: str, key: str, label: str) -> RegistryReference:
    return RegistryReference(ScientificIdentifier("synthetic", object_type, key, "1.0.0"), label)


def _context(prefix: str) -> ObservationContext:
    return ObservationContext(
        context_id=InstanceIdentifier("context", prefix),
        athlete_id=InstanceIdentifier("athlete", "synthetic-athlete"),
        session_id=InstanceIdentifier("session", "synthetic-session"),
        test_instance_id=InstanceIdentifier("test-instance", prefix),
        trial_id=InstanceIdentifier("trial", prefix),
        observed_at=datetime(2026, 1, 1, tzinfo=UTC),
        population_context="synthetic-only trained adult team-sport athlete",
    )


def _dj_result(value: DropJumpMetricResult | RefusalResult) -> DropJumpMetricResult:
    assert isinstance(value, DropJumpMetricResult)
    return value


def _bpt_result(value: BenchPressThrowMetricResult | RefusalResult) -> BenchPressThrowMetricResult:
    assert isinstance(value, BenchPressThrowMetricResult)
    return value


def _bpt_provider_result(value: object) -> BPTProviderMetricResult:
    assert isinstance(value, BPTProviderMetricResult)
    return value


def _mbt_result(
    value: MedicineBallThrowMetricResult | RefusalResult,
) -> MedicineBallThrowMetricResult:
    assert isinstance(value, MedicineBallThrowMetricResult)
    return value


def _refused(value: object) -> RefusalResult:
    assert isinstance(value, RefusalResult)
    return value


def _dj_event_source(
    source: ScientificMeasurementObservation,
    *,
    label: DropJumpEventLabel,
    sample_index: int,
    source_sample_count: int,
    source_series_digest: str,
    detector_parameters: DropJumpEventDetectorParameters,
    prefix: str,
) -> DropJumpEventSourceEvidence:
    artifact = next(
        item
        for item in source.provenance.source_artifacts
        if isinstance(item, DropJumpSourceArtifact)
    )
    acquisition = next(
        item
        for item in source.provenance.acquisitions
        if isinstance(item, DropJumpAcquisitionRecord)
    )
    identity = source.identity
    if (
        not isinstance(identity, DropJumpMeasurementIdentity)
        or identity.acquisition.timebase is None
    ):
        raise AssertionError("DJ fixture requires a typed timebase")
    timebase = identity.acquisition.timebase
    detector = {
        DropJumpEventLabel.TOUCHDOWN: DROP_JUMP_TOUCHDOWN_DETECTOR,
        DropJumpEventLabel.REBOUND_TAKEOFF: DROP_JUMP_REBOUND_TAKEOFF_DETECTOR,
        DropJumpEventLabel.SUBSEQUENT_LANDING: DROP_JUMP_SUBSEQUENT_LANDING_DETECTOR,
    }[label]
    event_id = InstanceIdentifier("event-occurrence", f"{prefix}-{label.value.lower()}")
    signal_id = InstanceIdentifier(
        "signal", f"drop-jump:{source_series_digest.removeprefix('sha256:')[:24]}"
    )
    source_value_origin = ValueOrigin.SOURCE_REPORTED
    source_parameters = (
        MetadataEntry("source_event_id", event_id.qualified),
        MetadataEntry("source_observation_id", source.observation_id.qualified),
        MetadataEntry("source_signal_id", signal_id.qualified),
        MetadataEntry("source_artifact_id", artifact.artifact_id.qualified),
        MetadataEntry("source_acquisition_id", acquisition.acquisition_id.qualified),
        MetadataEntry("source_series_digest", source_series_digest),
        MetadataEntry("source_sample_count", source_sample_count),
        MetadataEntry("label", label.value),
        MetadataEntry("sample_index", sample_index),
        MetadataEntry("event_time_s", timebase.time_at(sample_index)),
        MetadataEntry("detector_parameters", canonical_hash(detector_parameters)),
        MetadataEntry("status", "VALID"),
        MetadataEntry("qc_codes", canonical_hash(())),
        MetadataEntry("source_value_origin", source_value_origin.value),
        MetadataEntry("preceding_event_id", None),
    )
    run_id = InstanceIdentifier("processing-run", f"{event_id.value}:source")
    run = ProcessingRun(
        processing_run_id=run_id,
        source_artifact_ids=(artifact.artifact_id,),
        method=detector.reference,
        parameters=source_parameters,
        software_version="synthetic-upstream-dj-event-v1",
        output_entity_id=event_id,
    )
    provenance = Provenance(
        provenance_id=InstanceIdentifier("provenance", event_id.value),
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
                source.observation_id.qualified,
                run_id.qualified,
                LineageRelation.DERIVED_FROM,
            ),
            LineageEdge(signal_id.qualified, run_id.qualified, LineageRelation.DERIVED_FROM),
            LineageEdge(
                artifact.artifact_id.qualified, run_id.qualified, LineageRelation.DERIVED_FROM
            ),
            LineageEdge(
                acquisition.acquisition_id.qualified,
                run_id.qualified,
                LineageRelation.DERIVED_FROM,
            ),
            LineageEdge(
                detector.decision_reference.stable_id,
                run_id.qualified,
                LineageRelation.SUPPORTED_BY,
            ),
            LineageEdge(run_id.qualified, event_id.qualified, LineageRelation.PRODUCED),
        ),
    )
    return DropJumpEventSourceEvidence(
        source_event_id=event_id,
        source_context=source.context,
        source_observation_id=source.observation_id,
        source_signal_id=signal_id,
        source_artifact_id=artifact.artifact_id,
        source_acquisition_id=acquisition.acquisition_id,
        source_measurement_identity=identity,
        source_timebase=timebase,
        source_series_digest=source_series_digest,
        source_sample_count=source_sample_count,
        label=label,
        sample_index=sample_index,
        event_time_s=timebase.time_at(sample_index),
        detector_method=detector,
        detector_parameters=detector_parameters,
        status=DropJumpEventOccurrenceStatus.VALID,
        qc_codes=(),
        source_value_origin=source_value_origin,
        upstream_processing_run_id=run_id,
        provenance=provenance,
    )


def _dj_fixture(
    *,
    actual_drop_height_m: float | None = None,
    actual_drop_height_method: RegistryReference | None = None,
    actual_drop_height_source: RegistryReference | None = None,
    arms: DropJumpArmCondition = DropJumpArmCondition.PROHIBITED,
    prefix: str = "synthetic-dj",
) -> tuple[
    ScientificMeasurementObservation,
    dict[DropJumpEventLabel, DropJumpEventOccurrence],
    DropJumpFlightTimeApplicability,
]:
    timebase = DropJumpTimebase(DropJumpTimebaseKind.REGULAR, sample_rate_hz=1000.0)
    samples = tuple(0.0 for _ in range(1000))
    series_digest = canonical_hash({"samples": samples, "timebase": timebase, "channel": "force"})
    artifact = DropJumpSourceArtifact(
        artifact_id=InstanceIdentifier("artifact", prefix),
        content_digest=series_digest,
        media_type="application/vnd.synthetic.drop-jump",
        hash_scope=DropJumpArtifactHashScope.CANONICAL_SERIES_REPRESENTATION,
        status=DropJumpArtifactStatus.VERIFIED,
    )
    acquisition_id = InstanceIdentifier("acquisition", prefix)
    device = _ref("device", "synthetic-force-platform", "Synthetic force platform")
    acquisition = DropJumpAcquisitionRecord(
        acquisition_id=acquisition_id,
        device=device,
        source_artifact_id=artifact.artifact_id,
        sensor_channel="vertical-force",
        provider="synthetic-provider",
        sensor_modality=DropJumpSensorModality.FORCE_PLATFORM,
        timebase=timebase,
    )
    protocol = DropJumpProtocolIdentity(
        reference=DROP_JUMP_PROTOCOL_V1,
        protocol_version="1.0.0",
        nominal_box_height_m=0.30,
        actual_drop_height_m=actual_drop_height_m,
        actual_drop_height_method=(
            actual_drop_height_method
            if actual_drop_height_method is not None
            else (
                _ref(
                    "measurement-method",
                    "synthetic-drop-height",
                    "Synthetic independent drop-height method",
                )
                if actual_drop_height_m is not None
                else None
            )
        ),
        actual_drop_height_source=actual_drop_height_source,
        initiation_mode=DropJumpInitiationMode.STEP_OFF,
        pre_drop_posture="quiet standing on box",
        pre_drop_stillness=True,
        step_off_leg="RIGHT",
        arms_condition=arms,
        rebound_strategy=DropJumpReboundStrategy.COMBINED,
        explicit_cue="step off, rebound immediately",
        support_platform_configuration="single synthetic force platform",
        landing_rebound_technique="continuous rebound; controlled subsequent landing",
        pause_continuity_semantics="no pause between touchdown and rebound takeoff",
    )
    identity = DropJumpMeasurementIdentity(
        identity_id=ScientificIdentifier("synthetic", "measurement-identity", "dj-source", "1.0.0"),
        semantic=DropJumpSemanticIdentity(
            construct=DROP_JUMP_CONSTRUCT,
            test_family=DROP_JUMP_TEST_FAMILY,
            protocol=protocol.reference,
            measurand=DROP_JUMP_SOURCE_SERIES_MEASURAND,
            metric_definition=DROP_JUMP_SOURCE_SERIES_METRIC,
            protocol_identity=protocol,
        ),
        acquisition=DropJumpAcquisitionIdentity(
            device=device,
            raw_artifact=artifact.artifact_id,
            acquisition_instance_id=acquisition_id,
            sensor_channel="vertical-force",
            provider=acquisition.provider,
            sensor_modality=acquisition.sensor_modality,
            timebase=timebase,
            source_series_digest=series_digest,
        ),
        processing=DropJumpProcessingIdentity(
            registered_operation=DROP_JUMP_SOURCE_OBSERVATION_OPERATION,
            timebase=timebase,
            processing_state=DropJumpProcessingState.RAW_ACQUIRED,
        ),
        version=VersionIdentity(
            processing_method=DROP_JUMP_SOURCE_OBSERVATION_OPERATION,
            method_registry_version="1.0.0",
            software_version="synthetic-source-v1",
        ),
    )
    context = _context(prefix)
    observation_id = InstanceIdentifier("observation", prefix)
    source = build_drop_jump_source_observation(
        observation_id=observation_id,
        context=context,
        identity=identity,
        result=MeasurementResult(
            result_id=InstanceIdentifier("result", prefix),
            value=StructuredOutputReference(artifact.artifact_id, DROP_JUMP_EVENT_SCHEMA),
            unit=None,
            classification=ScientificClassification(ValueOrigin.SOURCE_REPORTED, ()),
            quality=MeasurementQuality(),
            uncertainty=UncertaintyMetadata(),
        ),
        source_artifact=artifact,
        acquisition=acquisition,
    )
    parameters = DropJumpEventDetectorParameters(
        (MetadataEntry("threshold_semantics", "exact source detector output"),)
    )
    events = {
        label: build_drop_jump_event_occurrence(
            source_observation=source,
            label=label,
            sample_index=index,
            source_sample_count=len(samples),
            source_series_digest=series_digest,
            detector_parameters=parameters,
            source_evidence=_dj_event_source(
                source,
                label=label,
                sample_index=index,
                source_sample_count=len(samples),
                source_series_digest=series_digest,
                detector_parameters=parameters,
                prefix=prefix,
            ),
        )
        for label, index in (
            (DropJumpEventLabel.TOUCHDOWN, 100),
            (DropJumpEventLabel.REBOUND_TAKEOFF, 250),
            (DropJumpEventLabel.SUBSEQUENT_LANDING, 750),
        )
    }
    applicability = DropJumpFlightTimeApplicability(
        source_observation_id=source.observation_id,
        rebound_takeoff_event_id=events[DropJumpEventLabel.REBOUND_TAKEOFF].occurrence_id,
        subsequent_landing_event_id=events[DropJumpEventLabel.SUBSEQUENT_LANDING].occurrence_id,
        ballistic_vertical_motion=True,
        takeoff_landing_height_equivalence=True,
        negligible_air_resistance=True,
    )
    return source, events, applicability


def test_dj_gold_metrics_and_identity_separation() -> None:
    source, events, applicability = _dj_fixture()
    contact = _dj_result(
        calculate_drop_jump_contact_time(
            events[DropJumpEventLabel.TOUCHDOWN],
            events[DropJumpEventLabel.REBOUND_TAKEOFF],
            source,
        )
    )
    flight = _dj_result(
        calculate_drop_jump_rebound_flight_time(
            events[DropJumpEventLabel.REBOUND_TAKEOFF],
            events[DropJumpEventLabel.SUBSEQUENT_LANDING],
            source,
        )
    )
    height = _dj_result(
        calculate_drop_jump_flight_time_jump_height(
            events[DropJumpEventLabel.REBOUND_TAKEOFF],
            events[DropJumpEventLabel.SUBSEQUENT_LANDING],
            STANDARD_GRAVITY,
            source,
            applicability,
        )
    )
    assert contact.value_s == pytest.approx(0.15)
    assert flight.value_s == pytest.approx(0.5)
    assert height.value_m == pytest.approx(9.80665 * 0.5**2 / 8.0)
    rsi = _dj_result(calculate_drop_jump_rsi_jh_ct(height, contact))
    rsr = _dj_result(calculate_drop_jump_rsr_ft_ct(flight, contact))
    assert rsi.value_m_per_s == pytest.approx(height.value_m / 0.15)
    assert rsr.value_ratio == pytest.approx(0.5 / 0.15)
    assert rsi.metric != rsr.metric
    assert (
        rsi.observation.identity.semantic.measurand != rsr.observation.identity.semantic.measurand
    )


def test_dj_unknown_actual_height_does_not_poison_rebound_metrics() -> None:
    source, events, applicability = _dj_fixture()
    contact = _dj_result(
        calculate_drop_jump_contact_time(
            events[DropJumpEventLabel.TOUCHDOWN], events[DropJumpEventLabel.REBOUND_TAKEOFF], source
        )
    )
    height = _dj_result(
        calculate_drop_jump_flight_time_jump_height(
            events[DropJumpEventLabel.REBOUND_TAKEOFF],
            events[DropJumpEventLabel.SUBSEQUENT_LANDING],
            STANDARD_GRAVITY,
            source,
            applicability,
        )
    )
    assert contact.value_s == pytest.approx(0.15)
    assert height.value_m > 0
    assert isinstance(source.identity, DropJumpMeasurementIdentity)
    assert source.identity.semantic.protocol_identity is not None
    assert source.identity.semantic.protocol_identity.actual_drop_height_m is None


def test_dj_nominal_actual_height_and_claim_relative_comparability() -> None:
    source_a, events_a, applicability_a = _dj_fixture(
        actual_drop_height_m=0.27, prefix="synthetic-dj-a"
    )
    source_b, events_b, applicability_b = _dj_fixture(
        actual_drop_height_m=0.35, prefix="synthetic-dj-b"
    )
    height_a = _dj_result(
        calculate_drop_jump_flight_time_jump_height(
            events_a[DropJumpEventLabel.REBOUND_TAKEOFF],
            events_a[DropJumpEventLabel.SUBSEQUENT_LANDING],
            STANDARD_GRAVITY,
            source_a,
            applicability_a,
        )
    )
    height_b = _dj_result(
        calculate_drop_jump_flight_time_jump_height(
            events_b[DropJumpEventLabel.REBOUND_TAKEOFF],
            events_b[DropJumpEventLabel.SUBSEQUENT_LANDING],
            STANDARD_GRAVITY,
            source_b,
            applicability_b,
        )
    )
    assert isinstance(source_a.identity, DropJumpMeasurementIdentity)
    assert source_a.identity.semantic.protocol_identity is not None
    assert (
        source_a.identity.semantic.protocol_identity.nominal_box_height_m
        != source_a.identity.semantic.protocol_identity.actual_drop_height_m
    )
    assert (
        compare_drop_jump_metric_results(height_a, height_b).state
        is ComparabilityState.BRIDGE_VALIDATION_REQUIRED
    )
    source_unknown, events_unknown, _ = _dj_fixture(prefix="synthetic-dj-unknown")
    contact_unknown = _dj_result(
        calculate_drop_jump_contact_time(
            events_unknown[DropJumpEventLabel.TOUCHDOWN],
            events_unknown[DropJumpEventLabel.REBOUND_TAKEOFF],
            source_unknown,
        )
    )
    assert contact_unknown.value_s == pytest.approx(0.15)
    source_unknown_b, events_unknown_b, _ = _dj_fixture(prefix="synthetic-dj-unknown-b")
    contact_unknown_b = _dj_result(
        calculate_drop_jump_contact_time(
            events_unknown_b[DropJumpEventLabel.TOUCHDOWN],
            events_unknown_b[DropJumpEventLabel.REBOUND_TAKEOFF],
            source_unknown_b,
        )
    )
    assert (
        compare_drop_jump_metric_results(contact_unknown, contact_unknown_b).state
        is ComparabilityState.COMPARABLE
    )
    assert (
        compare_drop_jump_metric_results(
            contact_unknown,
            contact_unknown_b,
            "compare actual drop exposure",
        ).state
        is ComparabilityState.INSUFFICIENT_INFORMATION
    )


def test_dj_actual_height_identity_requires_complete_claim_relative_metadata() -> None:
    actual_method = _ref(
        "measurement-method",
        "synthetic-drop-height-complete",
        "Synthetic independent drop-height method",
    )
    actual_source = _ref(
        "measurement-source",
        "synthetic-drop-height-complete",
        "Synthetic independent drop-height source",
    )

    def contact_result(
        source: ScientificMeasurementObservation,
        events: dict[DropJumpEventLabel, DropJumpEventOccurrence],
    ) -> DropJumpMetricResult:
        return _dj_result(
            calculate_drop_jump_contact_time(
                events[DropJumpEventLabel.TOUCHDOWN],
                events[DropJumpEventLabel.REBOUND_TAKEOFF],
                source,
            )
        )

    same_a_source, same_a_events, _ = _dj_fixture(
        actual_drop_height_m=0.30,
        actual_drop_height_method=actual_method,
        actual_drop_height_source=actual_source,
        prefix="synthetic-dj-actual-same-a",
    )
    same_b_source, same_b_events, _ = _dj_fixture(
        actual_drop_height_m=0.30,
        actual_drop_height_method=actual_method,
        actual_drop_height_source=actual_source,
        prefix="synthetic-dj-actual-same-b",
    )
    same_a = contact_result(same_a_source, same_a_events)
    same_b = contact_result(same_b_source, same_b_events)
    assert (
        compare_drop_jump_metric_results(same_a, same_b, "compare actual drop exposure").state
        is ComparabilityState.COMPARABLE
    )

    different_method_source, different_method_events, _ = _dj_fixture(
        actual_drop_height_m=0.30,
        actual_drop_height_method=_ref(
            "measurement-method",
            "synthetic-drop-height-different-method",
            "Different synthetic independent drop-height method",
        ),
        actual_drop_height_source=actual_source,
        prefix="synthetic-dj-actual-different-method",
    )
    assert (
        compare_drop_jump_metric_results(
            same_a,
            contact_result(different_method_source, different_method_events),
            "compare actual drop exposure",
        ).state
        is ComparabilityState.BRIDGE_VALIDATION_REQUIRED
    )

    different_source_source, different_source_events, _ = _dj_fixture(
        actual_drop_height_m=0.30,
        actual_drop_height_method=actual_method,
        actual_drop_height_source=_ref(
            "measurement-source",
            "synthetic-drop-height-different-source",
            "Different synthetic independent drop-height source",
        ),
        prefix="synthetic-dj-actual-different-source",
    )
    assert (
        compare_drop_jump_metric_results(
            same_a,
            contact_result(different_source_source, different_source_events),
            "compare actual drop exposure",
        ).state
        is ComparabilityState.BRIDGE_VALIDATION_REQUIRED
    )

    different_height_source, different_height_events, _ = _dj_fixture(
        actual_drop_height_m=0.31,
        actual_drop_height_method=actual_method,
        actual_drop_height_source=actual_source,
        prefix="synthetic-dj-actual-different-height",
    )
    assert (
        compare_drop_jump_metric_results(
            same_a,
            contact_result(different_height_source, different_height_events),
            "compare actual drop exposure",
        ).state
        is ComparabilityState.BRIDGE_VALIDATION_REQUIRED
    )

    unknown_a_source, unknown_a_events, _ = _dj_fixture(prefix="synthetic-dj-actual-unknown-a")
    unknown_b_source, unknown_b_events, _ = _dj_fixture(prefix="synthetic-dj-actual-unknown-b")
    unknown_a = contact_result(unknown_a_source, unknown_a_events)
    unknown_b = contact_result(unknown_b_source, unknown_b_events)
    assert (
        compare_drop_jump_metric_results(unknown_a, unknown_b, "compare actual drop exposure").state
        is ComparabilityState.INSUFFICIENT_INFORMATION
    )
    assert (
        compare_drop_jump_metric_results(unknown_a, unknown_b).state
        is ComparabilityState.COMPARABLE
    )


def test_dj_event_order_source_and_missing_landing_fail_closed() -> None:
    source, events, _ = _dj_fixture()
    ordered = (
        events[DropJumpEventLabel.TOUCHDOWN],
        events[DropJumpEventLabel.REBOUND_TAKEOFF],
        events[DropJumpEventLabel.SUBSEQUENT_LANDING],
    )
    assert validate_drop_jump_event_order(ordered) is None
    assert validate_drop_jump_event_order(tuple(reversed(ordered))) is not None
    contact = _dj_result(calculate_drop_jump_contact_time(ordered[0], ordered[1], source))
    missing_landing = _refused(
        calculate_drop_jump_flight_time_jump_height(
            ordered[1],
            cast(DropJumpEventOccurrence, None),
            STANDARD_GRAVITY,
            source,
            None,
        )
    )
    assert contact.value_s == pytest.approx(0.15)
    assert missing_landing.blocks_claim
    assert "DJ flight-time ballistic jump height" in missing_landing.blocked_claim
    assert _refused(
        calculate_drop_jump_contact_time(
            ordered[0], ordered[1], cast(ScientificMeasurementObservation, object())
        )
    ).blocks_claim
    assert _refused(
        calculate_drop_jump_contact_time(
            cast(DropJumpEventOccurrence, "not-events"), ordered[1], source
        )
    ).blocks_claim


def test_dj_cmj_event_is_not_accepted_and_v3_roundtrip_is_stable() -> None:
    source, events, applicability = _dj_fixture()
    encoded = canonical_json(events[DropJumpEventLabel.TOUCHDOWN])
    decoded = from_canonical_json(encoded, type(events[DropJumpEventLabel.TOUCHDOWN]))
    assert decoded == events[DropJumpEventLabel.TOUCHDOWN]
    assert canonical_hash(decoded) == canonical_hash(events[DropJumpEventLabel.TOUCHDOWN])
    assert SERIALIZATION_VERSION == 3
    assert _refused(
        calculate_drop_jump_flight_time_jump_height(
            cast(DropJumpEventOccurrence, object()),
            events[DropJumpEventLabel.SUBSEQUENT_LANDING],
            STANDARD_GRAVITY,
            source,
            applicability,
        )
    ).blocks_claim

    cmj_takeoff, cmj_landing, _ = _flight_events("res68-real-cmj")
    real_cmj_refusal = calculate_drop_jump_flight_time_jump_height(
        cast(DropJumpEventOccurrence, cmj_takeoff),
        cast(DropJumpEventOccurrence, cmj_landing),
        STANDARD_GRAVITY,
        source,
        applicability,
    )
    assert isinstance(real_cmj_refusal, RefusalResult)
    assert "EVENT_SOURCE_MISMATCH" in real_cmj_refusal.reason_codes


def test_dj_adjudication_rule_is_validated_before_stable_id_access() -> None:
    source, _, _ = _dj_fixture(prefix="synthetic-dj-bad-adjudication")
    artifact = next(
        item
        for item in source.provenance.source_artifacts
        if isinstance(item, DropJumpSourceArtifact)
    )
    acquisition = next(
        item
        for item in source.provenance.acquisitions
        if isinstance(item, DropJumpAcquisitionRecord)
    )
    with pytest.raises(ValueError, match="adjudication_rule"):
        build_drop_jump_qualification_source_observation(
            target_observation=source,
            reported_status=DropJumpQualificationStatus.QUALIFIED,
            source_artifact=artifact,
            acquisition=acquisition,
            adjudication_rule=cast(RegistryReference, object()),
        )


def test_dj_event_authority_requires_upstream_event_evidence() -> None:
    source, events, _ = _dj_fixture(prefix="synthetic-dj-event-authority")
    valid_event = events[DropJumpEventLabel.TOUCHDOWN]
    assert valid_event.source_evidence is not None
    source_evidence = valid_event.source_evidence
    with pytest.raises(ValueError, match="source evidence"):
        build_drop_jump_event_occurrence(
            source_observation=source,
            label=DropJumpEventLabel.TOUCHDOWN,
            sample_index=100,
            source_sample_count=1000,
            source_series_digest=valid_event.source_series_digest,
            status=DropJumpEventOccurrenceStatus.VALID,
        )
    with pytest.raises(ValueError):
        replace(source_evidence, detector_method=DROP_JUMP_REBOUND_TAKEOFF_DETECTOR)
    with pytest.raises(ValueError):
        replace(
            source_evidence,
            provenance=replace(source_evidence.provenance, lineage_edges=()),
        )
    with pytest.raises(ValueError):
        replace(source_evidence, source_series_digest="sha256:forged")
    context_mismatch = replace(source_evidence, source_context=_context("other-dj-context"))
    with pytest.raises(ValueError, match="source"):
        build_drop_jump_event_occurrence(
            source_observation=source,
            source_evidence=context_mismatch,
        )
    with pytest.raises(ValueError):
        replace(source_evidence, source_artifact_id=InstanceIdentifier("artifact", "other"))
    with pytest.raises(ValueError):
        replace(source_evidence, source_acquisition_id=InstanceIdentifier("acquisition", "other"))
    other_source, _, _ = _dj_fixture(prefix="synthetic-dj-other-protocol", actual_drop_height_m=0.3)
    assert isinstance(other_source.identity, DropJumpMeasurementIdentity)
    protocol_mismatch = replace(
        source_evidence,
        source_measurement_identity=other_source.identity,
    )
    with pytest.raises(ValueError, match="source observation"):
        build_drop_jump_event_occurrence(
            source_observation=source,
            source_evidence=protocol_mismatch,
        )
    assert (
        valid_event.provenance.processing_runs[-1].method == valid_event.detector_method.reference
    )
    assert valid_event.provenance.processing_runs[-1].software_version.startswith(
        "synthetic-upstream"
    )
    encoded = canonical_json(source_evidence)
    restored = from_canonical_json(encoded, type(source_evidence))
    assert restored == source_evidence
    assert canonical_hash(restored) == canonical_hash(source_evidence)


def test_source_qualification_is_upstream_typed_and_cannot_be_minted() -> None:
    source, events, _ = _dj_fixture(prefix="synthetic-dj-qualified")
    dj_artifact = next(
        artifact
        for artifact in source.provenance.source_artifacts
        if isinstance(artifact, DropJumpSourceArtifact)
    )
    dj_acquisition = next(
        acquisition
        for acquisition in source.provenance.acquisitions
        if isinstance(acquisition, DropJumpAcquisitionRecord)
    )
    dj_qualification_source = build_drop_jump_qualification_source_observation(
        target_observation=source,
        reported_status=DropJumpQualificationStatus.QUALIFIED,
        source_artifact=dj_artifact,
        acquisition=dj_acquisition,
    )
    dj_qualification = normalize_drop_jump_qualification(dj_qualification_source, source)
    assert dj_qualification.status is DropJumpQualificationStatus.QUALIFIED
    contact = _dj_result(
        calculate_drop_jump_contact_time(
            events[DropJumpEventLabel.TOUCHDOWN],
            events[DropJumpEventLabel.REBOUND_TAKEOFF],
            source,
            dj_qualification,
        )
    )
    assert dj_qualification_source.observation_id in {
        item.observation_id for item in contact.source_observations
    }
    assert _refused(
        calculate_drop_jump_contact_time(
            events[DropJumpEventLabel.TOUCHDOWN],
            events[DropJumpEventLabel.REBOUND_TAKEOFF],
            source,
            cast(DropJumpSourceQualificationEvidence, True),
        )
    ).blocks_claim

    bpt_evidence, bpt_protocol, _, _, bpt_acquisition, bpt_artifact = _bpt_fixture()
    bpt_qualification_source = build_bpt_qualification_source_observation(
        target_observation=bpt_evidence.observation,
        reported_status=BPTQualificationStatus.QUALIFIED,
        source_artifact=bpt_artifact,
        acquisition=bpt_acquisition,
    )
    bpt_qualification = normalize_bpt_qualification(
        bpt_qualification_source, bpt_evidence.observation
    )
    assert bpt_qualification.status is BPTQualificationStatus.QUALIFIED
    assert _bpt_result(
        calculate_bpt_sampled_maximum_bar_velocity(bpt_evidence, bpt_qualification)
    ).value_m_per_s == pytest.approx(1.0)
    assert _refused(
        calculate_bpt_sampled_maximum_bar_velocity(
            bpt_evidence,
            cast(BPTSourceQualificationEvidence, True),
        )
    ).blocks_claim
    assert bpt_protocol.test_family == BPT_TEST_FAMILY

    mbt_source, mbt_coordinate, _, mbt_artifact, mbt_acquisition, _ = _mbt_distance_fixture(
        prefix="synthetic-mbt-qualified"
    )
    mbt_qualification_source = build_mbt_qualification_source_observation(
        target_observation=mbt_source,
        reported_status=MBTQualificationStatus.QUALIFIED,
        source_artifact=mbt_artifact,
        acquisition=mbt_acquisition,
    )
    mbt_qualification = normalize_mbt_qualification(mbt_qualification_source, mbt_source)
    assert mbt_qualification.status is MBTQualificationStatus.QUALIFIED
    assert _mbt_result(
        calculate_mbt_throw_distance(mbt_coordinate, mbt_source, mbt_qualification)
    ).value_m == pytest.approx(4.5)
    assert _refused(
        calculate_mbt_throw_distance(
            mbt_coordinate,
            mbt_source,
            cast(MBTSourceQualificationEvidence, True),
        )
    ).blocks_claim


def _bpt_support_source(
    *,
    context: ObservationContext,
    identity: BenchPressThrowMeasurementIdentity,
    series: BenchPressThrowVelocitySeries,
    artifact: BenchPressThrowSourceArtifact,
    acquisition: BenchPressThrowAcquisitionRecord,
    metric: RegistryReference,
    support_definition: str,
    includes_post_release_samples: bool,
    prefix: str,
) -> BPTMetricSupportSourceEvidence:
    support_id = InstanceIdentifier("support", f"{prefix}-{metric.identifier.key}")
    run_id = InstanceIdentifier("processing-run", f"{support_id.value}:source")
    source_origin = ValueOrigin.PROVIDER_DERIVED
    source = BPTMetricSupportSourceEvidence(
        support_id=support_id,
        source_context=context,
        source_observation_id=InstanceIdentifier("observation", f"{prefix}-series"),
        source_series_id=series.series_id,
        source_artifact_id=artifact.artifact_id,
        source_acquisition_id=acquisition.acquisition_id,
        source_measurement_identity_id=identity.identity_id,
        source_series_digest=series.canonical_content_digest(),
        source_timebase=series.timebase,
        source_sample_count=len(series.samples),
        metric=metric,
        start_index=0,
        end_index=len(series.samples) - 1,
        start_time_s=series.samples[0][0],
        end_time_s=series.samples[-1][0],
        support_definition=support_definition,
        boundary_method=BPT_METRIC_SUPPORT_METHOD,
        boundary_convention=BPT_METRIC_SUPPORT_BOUNDARY_CONVENTION,
        includes_post_release_samples=includes_post_release_samples,
        value_origin=source_origin,
        upstream_processing_run_id=run_id,
        provenance=Provenance(
            provenance_id=InstanceIdentifier("provenance", support_id.value),
            source_artifacts=(artifact,),
            acquisitions=(acquisition,),
            processing_runs=(),
            lineage_edges=(),
        ),
    )
    parameters = (
        MetadataEntry("support_id", source.support_id.qualified),
        MetadataEntry("source_context_id", source.source_context.context_id.qualified),
        MetadataEntry("source_observation_id", source.source_observation_id.qualified),
        MetadataEntry("source_series_id", source.source_series_id.qualified),
        MetadataEntry("source_artifact_id", source.source_artifact_id.qualified),
        MetadataEntry("source_acquisition_id", source.source_acquisition_id.qualified),
        MetadataEntry(
            "source_measurement_identity_id", source.source_measurement_identity_id.stable_id
        ),
        MetadataEntry("source_series_digest", source.source_series_digest),
        MetadataEntry("source_timebase", canonical_json(source.source_timebase)),
        MetadataEntry("source_sample_count", source.source_sample_count),
        MetadataEntry("metric", source.metric.stable_id),
        MetadataEntry("start_index", source.start_index),
        MetadataEntry("end_index", source.end_index),
        MetadataEntry("start_time_s", source.start_time_s),
        MetadataEntry("end_time_s", source.end_time_s),
        MetadataEntry("support_definition", source.support_definition),
        MetadataEntry("boundary_method", source.boundary_method.stable_id),
        MetadataEntry("boundary_convention", source.boundary_convention.stable_id),
        MetadataEntry("boundary_parameters", canonical_json(source.boundary_parameters)),
        MetadataEntry("includes_post_release_samples", source.includes_post_release_samples),
        MetadataEntry("value_origin", source.value_origin.value),
    )
    run = ProcessingRun(
        processing_run_id=run_id,
        source_artifact_ids=(artifact.artifact_id,),
        method=BPT_METRIC_SUPPORT_SOURCE_OPERATION,
        parameters=parameters,
        software_version="synthetic-upstream-bpt-support-v1",
        output_entity_id=support_id,
    )
    provenance = replace(
        source.provenance,
        processing_runs=(run,),
        lineage_edges=(
            LineageEdge(
                source.source_observation_id.qualified,
                run_id.qualified,
                LineageRelation.DERIVED_FROM,
            ),
            LineageEdge(series.series_id.qualified, run_id.qualified, LineageRelation.DERIVED_FROM),
            LineageEdge(
                artifact.artifact_id.qualified, run_id.qualified, LineageRelation.DERIVED_FROM
            ),
            LineageEdge(
                acquisition.acquisition_id.qualified,
                run_id.qualified,
                LineageRelation.DERIVED_FROM,
            ),
            LineageEdge(
                BPT_METRIC_SUPPORT_QUALIFICATION_RULE.stable_id,
                run_id.qualified,
                LineageRelation.SUPPORTED_BY,
            ),
            LineageEdge(run_id.qualified, support_id.qualified, LineageRelation.PRODUCED),
        ),
    )
    return replace(source, provenance=provenance)


def _bpt_fixture(
    *,
    movement: BPTMovementPattern = BPTMovementPattern.CONCENTRIC_ONLY,
    prefix: str = "synthetic-bpt",
    explicit_timebase: bool = False,
    counterbalance_status: BPTCounterbalanceStatus = BPTCounterbalanceStatus.ABSENT,
    support_metric: RegistryReference = BPT_SAMPLED_MAXIMUM_BAR_VELOCITY_METRIC,
    includes_post_release_samples: bool = True,
) -> tuple[
    BenchPressThrowVelocitySeriesEvidence,
    BenchPressThrowProtocolIdentity,
    BenchPressThrowMetricSupport,
    str,
    BenchPressThrowAcquisitionRecord,
    BenchPressThrowSourceArtifact,
]:
    timebase = (
        BPTTimebase(BPTTimebaseKind.EXPLICIT, times_s=(0.0, 0.1, 0.35, 0.5, 0.9))
        if explicit_timebase
        else BPTTimebase(BPTTimebaseKind.REGULAR, sample_rate_hz=10.0)
    )
    samples = (
        ((0.0, 0.1), (0.1, 0.2), (0.35, 1.0), (0.5, 0.5), (0.9, 0.0))
        if explicit_timebase
        else ((0.0, 0.1), (0.1, 0.2), (0.2, 1.0), (0.3, 0.5), (0.4, 0.0))
    )
    frame = _ref("frame", "bar-vertical-up", "Vertical bar-up frame")
    sign = SignConvention(reference=_ref("sign", "bar-up-positive", "Bar upward positive"))
    series_digest = canonical_hash(
        {
            "samples": samples,
            "timebase": timebase,
            "unit": METER_PER_SECOND,
            "velocity_frame": frame,
            "sign_convention": sign,
            "processing_state": BPTProcessingState.PROVIDER_PROCESSED,
        }
    )
    artifact = BenchPressThrowSourceArtifact(
        artifact_id=InstanceIdentifier("artifact", prefix),
        content_digest=series_digest,
        media_type="application/vnd.synthetic.bpt-series",
        status=BPTArtifactStatus.VERIFIED,
        hash_scope=BPTArtifactHashScope.CANONICAL_SERIES_REPRESENTATION,
    )
    device = _ref("device", "synthetic-t-force", "Synthetic velocity device")
    acquisition_id = InstanceIdentifier("acquisition", prefix)
    acquisition = BenchPressThrowAcquisitionRecord(
        acquisition_id=acquisition_id,
        device=device,
        source_artifact_id=artifact.artifact_id,
        sensor_channel="bar",
        provider="synthetic-provider",
        sensor_modality=BPTSensorModality.LINEAR_POSITION_TRANSDUCER,
        timebase=timebase,
        axis_or_frame=frame,
    )
    load = BPTLoadIdentity(
        kind=BPTLoadKind.PHYSICAL,
        load_value=20.0,
        load_unit=KILOGRAM,
        bar_mass_kg=10.0,
        added_load_kg=10.0,
        counterweight_mass_kg=0.0,
        moving_system_load_semantics="bar plus added load; counterweight status explicit",
        effective_resistance_semantics="physical moving-system load",
    )
    protocol = BenchPressThrowProtocolIdentity(
        machine_type=BPTMachineType.FIXED_VERTICAL_SMITH,
        counterbalance_status=counterbalance_status,
        load_identity=load,
        concentric_pattern=movement,
        pause_touch_bounce=BPTPauseTouchBounce.TOUCH_AND_GO,
        grip="medium pronated",
        range_of_motion="registered chest-to-throw ROM",
        feet_body_support="supine bench with feet supported",
        release_semantics=BPTReleaseSemantics.RELEASED,
        catch_semantics=BPTCatchSemantics.NOT_CAUGHT,
        provider="synthetic-provider",
        device=device,
        sensor_modality=BPTSensorModality.LINEAR_POSITION_TRANSDUCER,
        timebase=timebase,
        source_series_digest=series_digest,
        operation_support_definition="support supplied separately per metric",
    )
    identity = BenchPressThrowMeasurementIdentity(
        identity_id=ScientificIdentifier(
            "synthetic", "measurement-identity", "bpt-source", "1.0.0"
        ),
        semantic=BenchPressThrowSemanticIdentity(
            construct=BPT_CONSTRUCT,
            test_family=BPT_TEST_FAMILY,
            protocol=protocol.reference,
            measurand=BPT_BAR_VELOCITY_MEASURAND,
            metric_definition=BPT_VELOCITY_SERIES_METRIC,
            protocol_identity=protocol,
        ),
        acquisition=BenchPressThrowAcquisitionIdentity(
            device=device,
            raw_artifact=artifact.artifact_id,
            acquisition_instance_id=acquisition_id,
            sensor_channel="bar",
            provider=acquisition.provider,
            sensor_modality=acquisition.sensor_modality,
            timebase=timebase,
            axis_or_frame=frame,
            source_series_digest=series_digest,
        ),
        processing=BenchPressThrowProcessingIdentity(
            registered_operation=BPT_SOURCE_VELOCITY_SERIES_OPERATION,
            timebase=timebase,
            sign_convention=sign,
            processing_state=BPTProcessingState.PROVIDER_PROCESSED,
        ),
        version=VersionIdentity(
            processing_method=BPT_SOURCE_VELOCITY_SERIES_OPERATION,
            method_registry_version=BPT_REGISTRY_VERSION,
            software_version="synthetic-bpt-source-v1",
        ),
    )
    series = BenchPressThrowVelocitySeries(
        series_id=InstanceIdentifier("signal", f"{prefix}-series"),
        source_artifact_id=artifact.artifact_id,
        acquisition_id=acquisition_id,
        source_measurement_identity_id=identity.identity_id,
        samples=samples,
        timebase=timebase,
        unit=METER_PER_SECOND,
        velocity_frame=frame,
        sign_convention=sign,
        processing_state=BPTProcessingState.PROVIDER_PROCESSED,
    )
    context = _context(prefix)
    support_source = _bpt_support_source(
        context=context,
        identity=identity,
        series=series,
        artifact=artifact,
        acquisition=acquisition,
        metric=support_metric,
        support_definition=(
            "first positive bar velocity through explicit release/maximum-height support"
        ),
        includes_post_release_samples=includes_post_release_samples,
        prefix=prefix,
    )
    evidence = create_bpt_velocity_series_evidence(
        observation_id=InstanceIdentifier("observation", f"{prefix}-series"),
        result_id=InstanceIdentifier("result", f"{prefix}-series"),
        context=context,
        identity=identity,
        series=series,
        source_artifact=artifact,
        acquisition=acquisition,
        support=support_source,
    )
    return evidence, protocol, evidence.support, series_digest, acquisition, artifact


def test_bpt_vmax_time_weighted_mean_and_post_release_support() -> None:
    evidence, protocol, _, _, _, _ = _bpt_fixture()
    vmax = _bpt_result(calculate_bpt_sampled_maximum_bar_velocity(evidence))
    assert vmax.value_m_per_s == pytest.approx(1.0)
    assert evidence.support_source_evidence is not None
    assert evidence.support_source_evidence.includes_post_release_samples
    mean_evidence, _, _, _, _, _ = _bpt_fixture(
        prefix="synthetic-bpt-mean",
        support_metric=BPT_DYNAMISLM_TIME_WEIGHTED_MEAN_BAR_VELOCITY_METRIC,
    )
    mean = _bpt_result(calculate_bpt_dynamislm_time_weighted_mean_bar_velocity(mean_evidence))
    assert mean.value_m_per_s == pytest.approx(0.4375)
    assert (
        mean.observation.identity.semantic.metric_definition
        == BPT_DYNAMISLM_TIME_WEIGHTED_MEAN_BAR_VELOCITY_METRIC
    )
    assert protocol.release_semantics is BPTReleaseSemantics.RELEASED
    no_post_release, _, _, _, _, _ = _bpt_fixture(
        prefix="synthetic-bpt-no-post-release",
        includes_post_release_samples=False,
    )
    assert no_post_release.support_source_evidence is not None
    assert not no_post_release.support_source_evidence.includes_post_release_samples
    assert _bpt_result(
        calculate_bpt_sampled_maximum_bar_velocity(no_post_release)
    ).value_m_per_s == pytest.approx(1.0)


def test_bpt_metric_support_and_provider_origin_are_distinct() -> None:
    evidence, protocol, _, _, acquisition, artifact = _bpt_fixture()
    provider = build_bpt_provider_metric_observation(
        observation_id=InstanceIdentifier("observation", "synthetic-bpt-provider-mv"),
        result_id=InstanceIdentifier("result", "synthetic-bpt-provider-mv"),
        context=_context("synthetic-bpt-provider"),
        protocol_identity=protocol,
        metric=BPT_PROVIDER_MEAN_VELOCITY_METRIC,
        value=0.4375,
        unit=METER_PER_SECOND,
        source_artifact=artifact,
        acquisition=acquisition,
        value_origin=ValueOrigin.PROVIDER_DERIVED,
        provider_algorithm=_ref("provider-algorithm", "synthetic-mv", "Synthetic provider MV"),
    )
    derived = _bpt_result(calculate_bpt_sampled_maximum_bar_velocity(evidence))
    wrapped = _bpt_provider_result(
        wrap_bpt_provider_metric(provider, BPT_PROVIDER_MEAN_VELOCITY_METRIC)
    )
    assert provider.result.classification.value_origin is ValueOrigin.PROVIDER_DERIVED
    assert derived.metric != BPT_PROVIDER_MEAN_VELOCITY_METRIC
    assert (
        compare_bpt_metric_results(derived, wrapped).state
        is ComparabilityState.BRIDGE_VALIDATION_REQUIRED
    )


def test_bpt_provider_metrics_use_exact_measurands() -> None:
    _, protocol, _, _, acquisition, artifact = _bpt_fixture(prefix="synthetic-bpt-measurands")
    cases = (
        (
            BPT_PROVIDER_MEAN_VELOCITY_METRIC,
            METER_PER_SECOND,
            BPT_BAR_VELOCITY_MEASURAND,
        ),
        (
            BPT_PROVIDER_MAXIMUM_VELOCITY_METRIC,
            METER_PER_SECOND,
            BPT_BAR_VELOCITY_MEASURAND,
        ),
        (
            BPT_PROVIDER_MEAN_PROPULSIVE_VELOCITY_METRIC,
            METER_PER_SECOND,
            BPT_MEAN_PROPULSIVE_VELOCITY_MEASURAND,
        ),
        (BPT_PROVIDER_MEAN_POWER_METRIC, WATT, BPT_MEAN_POWER_MEASURAND),
        (BPT_PROVIDER_PEAK_POWER_METRIC, WATT, BPT_PEAK_POWER_MEASURAND),
    )
    for metric, unit, measurand in cases:
        observation = build_bpt_provider_metric_observation(
            observation_id=InstanceIdentifier(
                "observation", f"synthetic-bpt-provider-{metric.identifier.key}"
            ),
            result_id=InstanceIdentifier(
                "result", f"synthetic-bpt-provider-{metric.identifier.key}"
            ),
            context=_context(f"synthetic-bpt-provider-{metric.identifier.key}"),
            protocol_identity=protocol,
            metric=metric,
            value=1.0,
            unit=unit,
            source_artifact=artifact,
            acquisition=acquisition,
            value_origin=ValueOrigin.PROVIDER_DERIVED,
        )
        assert observation.identity.semantic.measurand == measurand


def test_bpt_metric_support_requires_upstream_source_authority() -> None:
    evidence, _, _, _, acquisition, artifact = _bpt_fixture(prefix="synthetic-bpt-authority")
    raw_support = BenchPressThrowMetricSupport(
        support_id=InstanceIdentifier("support", "raw-bpt-support"),
        metric=BPT_SAMPLED_MAXIMUM_BAR_VELOCITY_METRIC,
        start_index=0,
        end_index=4,
        start_time_s=0.0,
        end_time_s=0.4,
        support_definition="caller-selected support",
        source_series_digest=evidence.source_series_digest,
        includes_post_release_samples=True,
    )
    with pytest.raises(ValueError, match="upstream BPT metric support"):
        create_bpt_velocity_series_evidence(
            observation_id=evidence.observation.observation_id,
            result_id=evidence.observation.result.result_id,
            context=evidence.observation.context,
            identity=evidence.identity,
            series=evidence.series,
            source_artifact=artifact,
            acquisition=acquisition,
            support=raw_support,
        )
    source = evidence.support_source_evidence
    assert source is not None
    for mutated in (
        replace(source, source_series_digest="sha256:wrong"),
        replace(source, source_context=_context("synthetic-bpt-other-context")),
        replace(source, source_artifact_id=InstanceIdentifier("artifact", "other")),
        replace(source, source_acquisition_id=InstanceIdentifier("acquisition", "other")),
        replace(source, metric=BPT_DYNAMISLM_TIME_WEIGHTED_MEAN_BAR_VELOCITY_METRIC),
        replace(source, start_index=1),
        replace(source, end_time_s=99.0),
        replace(source, boundary_method=_ref("support-method", "other", "Other support")),
        replace(
            source,
            boundary_convention=_ref("boundary-convention", "other", "Other convention"),
        ),
        replace(
            source,
            provenance=replace(
                source.provenance,
                lineage_edges=(
                    LineageEdge(
                        source.upstream_processing_run_id.qualified,
                        source.support_id.qualified,
                        LineageRelation.PRODUCED,
                    ),
                ),
            ),
        ),
    ):
        with pytest.raises(ValueError):
            normalize_bpt_metric_support(
                mutated,
                evidence.observation,
                evidence.series,
                artifact,
                acquisition,
            )
    normalized = normalize_bpt_metric_support(
        source, evidence.observation, evidence.series, artifact, acquisition
    )
    assert normalized == evidence.support
    assert normalized.authority_source_id == source.support_id
    restored = from_canonical_json(canonical_json(source), type(source))
    assert restored == source
    assert canonical_hash(restored) == canonical_hash(source)


def test_bpt_metric_specific_refusals_and_serialization() -> None:
    evidence, _, _, _, _, _ = _bpt_fixture()
    assert calculate_bpt_mean_propulsive_velocity(evidence).blocks_claim
    assert calculate_bpt_mean_power(evidence).blocks_claim
    assert calculate_bpt_load_times_velocity_power(20.0, 1.0).blocks_claim
    assert _refused(
        calculate_bpt_sampled_maximum_bar_velocity(evidence, start_index=1)
    ).blocks_claim
    result = _bpt_result(calculate_bpt_sampled_maximum_bar_velocity(evidence))
    encoded = canonical_json(result)
    decoded = from_canonical_json(encoded, type(result))
    assert canonical_hash(decoded) == canonical_hash(result)
    assert result.observation.result.classification.value_origin is ValueOrigin.DYNAMISLM_DERIVED


def _assert_unresolved_comparison(value: object, missing: str) -> ComparabilityResult:
    assert isinstance(value, ComparabilityResult)
    assert value.state is ComparabilityState.INSUFFICIENT_INFORMATION
    assert value.decided_by.value == "UNRESOLVED"
    assert value.rule_reference is None
    assert missing in value.missing_information
    return value


def test_res68_comparators_fail_closed_for_refusals_malformed_inputs_and_duplicate_ids() -> None:
    bpt_evidence, _, _, _, _, _ = _bpt_fixture(prefix="synthetic-bpt-comparability")
    bpt_result = _bpt_result(calculate_bpt_sampled_maximum_bar_velocity(bpt_evidence))
    bpt_refusal = _refused(calculate_bpt_mean_power(bpt_evidence))
    _assert_unresolved_comparison(
        compare_bpt_metric_results(cast(BenchPressThrowMetricResult, bpt_refusal), bpt_result),
        "two typed BPT metric results",
    )
    _assert_unresolved_comparison(
        compare_bpt_metric_results(bpt_result, cast(BenchPressThrowMetricResult, bpt_refusal)),
        "two typed BPT metric results",
    )
    _assert_unresolved_comparison(
        compare_bpt_metric_results(cast(BenchPressThrowMetricResult, object()), bpt_result),
        "two typed BPT metric results",
    )
    duplicate_bpt = replace(bpt_result, metric=bpt_result.metric)
    _assert_unresolved_comparison(
        compare_bpt_metric_results(duplicate_bpt, bpt_result), "two distinct observations"
    )

    dj_source, dj_events, _ = _dj_fixture(prefix="synthetic-dj-comparability")
    dj_result = _dj_result(
        calculate_drop_jump_contact_time(
            dj_events[DropJumpEventLabel.TOUCHDOWN],
            dj_events[DropJumpEventLabel.REBOUND_TAKEOFF],
            dj_source,
        )
    )
    _assert_unresolved_comparison(
        compare_drop_jump_metric_results(cast(DropJumpMetricResult, object()), dj_result),
        "two typed DJ metric results",
    )
    _assert_unresolved_comparison(
        compare_drop_jump_metric_results(dj_result, dj_result), "two distinct observations"
    )
    duplicate_dj = replace(dj_result, metric=dj_result.metric)
    _assert_unresolved_comparison(
        compare_drop_jump_metric_results(duplicate_dj, dj_result), "two distinct observations"
    )

    mbt_source, mbt_coordinate, _, _, _, _ = _mbt_distance_fixture(
        prefix="synthetic-mbt-comparability"
    )
    mbt_result = _mbt_result(calculate_mbt_throw_distance(mbt_coordinate, mbt_source))
    _assert_unresolved_comparison(
        compare_mbt_metric_results(cast(MedicineBallThrowMetricResult, object()), mbt_result),
        "two typed MBT metric results",
    )
    _assert_unresolved_comparison(
        compare_mbt_metric_results(mbt_result, mbt_result), "two distinct observations"
    )
    duplicate_mbt = replace(mbt_result, metric=mbt_result.metric)
    _assert_unresolved_comparison(
        compare_mbt_metric_results(duplicate_mbt, mbt_result), "two distinct observations"
    )


def test_bpt_irregular_timebase_and_same_method_comparability() -> None:
    explicit, _, _, _, _, _ = _bpt_fixture(prefix="synthetic-bpt-explicit", explicit_timebase=True)
    mean_evidence, _, _, _, _, _ = _bpt_fixture(
        prefix="synthetic-bpt-explicit-mean",
        explicit_timebase=True,
        support_metric=BPT_DYNAMISLM_TIME_WEIGHTED_MEAN_BAR_VELOCITY_METRIC,
    )
    mean = _bpt_result(calculate_bpt_dynamislm_time_weighted_mean_bar_velocity(mean_evidence))
    assert mean.value_m_per_s == pytest.approx(0.3775 / 0.9)
    other, _, _, _, _, _ = _bpt_fixture(prefix="synthetic-bpt-other", explicit_timebase=True)
    other_vmax = _bpt_result(calculate_bpt_sampled_maximum_bar_velocity(other))
    assert (
        compare_bpt_metric_results(
            _bpt_result(calculate_bpt_sampled_maximum_bar_velocity(explicit)),
            other_vmax,
        ).state
        is ComparabilityState.COMPARABLE
    )


def test_bpt_unresolved_counterbalance_and_movement_mismatch_refuse_or_bridge() -> None:
    unresolved, _, _, _, _, _ = _bpt_fixture(
        prefix="synthetic-bpt-unresolved",
        counterbalance_status=BPTCounterbalanceStatus.UNKNOWN,
    )
    assert _refused(calculate_bpt_sampled_maximum_bar_velocity(unresolved)).blocks_claim
    concentric, _, _, _, _, _ = _bpt_fixture(prefix="synthetic-bpt-concentric")
    eccentric, _, _, _, _, _ = _bpt_fixture(
        prefix="synthetic-bpt-eccentric",
        movement=BPTMovementPattern.ECCENTRIC_CONCENTRIC,
    )
    assert (
        compare_bpt_metric_results(
            _bpt_result(calculate_bpt_sampled_maximum_bar_velocity(concentric)),
            _bpt_result(calculate_bpt_sampled_maximum_bar_velocity(eccentric)),
        ).state
        is ComparabilityState.BRIDGE_VALIDATION_REQUIRED
    )


def _mbt_coordinate_source(
    *,
    source_observation: ScientificMeasurementObservation,
    protocol: MedicineBallThrowProtocolIdentity,
    artifact: MedicineBallThrowSourceArtifact,
    acquisition: MedicineBallThrowAcquisitionRecord,
    origin_coordinate_m: float,
    endpoint_coordinate_m: float,
    coordinate_frame: RegistryReference,
    origin_convention: RegistryReference,
    endpoint_convention: RegistryReference,
    first_contact_no_roll_convention: RegistryReference,
    first_contact_observed: bool,
    no_roll_observed: bool,
    prefix: str,
) -> MBTCoordinateSourceEvidence:
    coordinate_id = InstanceIdentifier("coordinate-evidence", f"{prefix}-coordinate")
    run_id = InstanceIdentifier("processing-run", f"{coordinate_id.value}:source")
    source = MBTCoordinateSourceEvidence(
        source_coordinate_id=coordinate_id,
        source_context_id=source_observation.context.context_id,
        source_observation_id=source_observation.observation_id,
        source_artifact_id=artifact.artifact_id,
        source_acquisition_id=acquisition.acquisition_id,
        source_measurement_identity_id=source_observation.identity.identity_id,
        protocol_reference=protocol.reference,
        origin_coordinate_m=origin_coordinate_m,
        endpoint_coordinate_m=endpoint_coordinate_m,
        coordinate_frame=coordinate_frame,
        origin_convention=origin_convention,
        endpoint_convention=endpoint_convention,
        first_contact_no_roll_convention=first_contact_no_roll_convention,
        first_contact_observed=first_contact_observed,
        no_roll_observed=no_roll_observed,
        source_content_digest=artifact.content_digest,
        provider=acquisition.provider,
        source_value_origin=source_observation.result.classification.value_origin.value,
        upstream_processing_run_id=run_id,
        provenance=Provenance(
            provenance_id=InstanceIdentifier("provenance", coordinate_id.value),
            source_artifacts=(artifact,),
            acquisitions=(acquisition,),
            processing_runs=(),
            lineage_edges=(),
        ),
    )
    parameters = (
        MetadataEntry("source_coordinate_id", source.source_coordinate_id.qualified),
        MetadataEntry("source_context_id", source.source_context_id.qualified),
        MetadataEntry("source_observation_id", source.source_observation_id.qualified),
        MetadataEntry("source_artifact_id", source.source_artifact_id.qualified),
        MetadataEntry("source_acquisition_id", source.source_acquisition_id.qualified),
        MetadataEntry(
            "source_measurement_identity_id", source.source_measurement_identity_id.stable_id
        ),
        MetadataEntry("protocol_reference", source.protocol_reference.stable_id),
        MetadataEntry("origin_coordinate_m", source.origin_coordinate_m),
        MetadataEntry("endpoint_coordinate_m", source.endpoint_coordinate_m),
        MetadataEntry("coordinate_frame", source.coordinate_frame.stable_id),
        MetadataEntry("origin_convention", source.origin_convention.stable_id),
        MetadataEntry("endpoint_convention", source.endpoint_convention.stable_id),
        MetadataEntry(
            "first_contact_no_roll_convention",
            source.first_contact_no_roll_convention.stable_id,
        ),
        MetadataEntry("first_contact_observed", source.first_contact_observed),
        MetadataEntry("no_roll_observed", source.no_roll_observed),
        MetadataEntry("source_content_digest", source.source_content_digest),
        MetadataEntry("provider", source.provider),
        MetadataEntry("method_parameters", canonical_json(source.method_parameters)),
        MetadataEntry("source_value_origin", source.source_value_origin),
    )
    run = ProcessingRun(
        processing_run_id=run_id,
        source_artifact_ids=(artifact.artifact_id,),
        method=MBT_COORDINATE_SOURCE_OPERATION,
        parameters=parameters,
        software_version="synthetic-upstream-mbt-coordinate-v1",
        output_entity_id=coordinate_id,
    )
    provenance = replace(
        source.provenance,
        processing_runs=(run,),
        lineage_edges=(
            LineageEdge(
                artifact.artifact_id.qualified,
                acquisition.acquisition_id.qualified,
                LineageRelation.ACQUIRED_AS,
            ),
            LineageEdge(
                source_observation.observation_id.qualified,
                run_id.qualified,
                LineageRelation.DERIVED_FROM,
            ),
            LineageEdge(
                artifact.artifact_id.qualified, run_id.qualified, LineageRelation.DERIVED_FROM
            ),
            LineageEdge(
                acquisition.acquisition_id.qualified,
                run_id.qualified,
                LineageRelation.DERIVED_FROM,
            ),
            LineageEdge(
                MBT_COORDINATE_QUALIFICATION_RULE.stable_id,
                run_id.qualified,
                LineageRelation.SUPPORTED_BY,
            ),
            LineageEdge(run_id.qualified, coordinate_id.qualified, LineageRelation.PRODUCED),
        ),
    )
    return replace(source, provenance=provenance)


def _mbt_distance_fixture(
    *,
    throw_type: MBTThrowVariant = MBTThrowVariant.SEATED_CHEST,
    prefix: str = "synthetic-mbt-distance",
) -> tuple[
    ScientificMeasurementObservation,
    MBTCoordinateEvidence,
    MedicineBallThrowProtocolIdentity,
    MedicineBallThrowSourceArtifact,
    MedicineBallThrowAcquisitionRecord,
    RegistryReference,
]:
    origin = _ref("distance-origin", "pelvis-projection", "Projected starting origin")
    endpoint = _ref("distance-endpoint", "first-contact", "First ball-floor contact")
    no_roll = _ref("distance-endpoint-rule", "first-contact-no-roll", "First contact; no roll")
    frame = _ref("frame", "horizontal-forward", "Horizontal forward axis")
    device = _ref("device", "synthetic-measuring-tape", "Synthetic measuring tape")
    protocol = MedicineBallThrowProtocolIdentity(
        throw_type=throw_type,
        body_posture=MBTBodyPosture.SEATED,
        support_restraint_condition=MBTSupportCondition.BACK_SUPPORTED,
        ball_mass_kg=3.0,
        countermovement=MBTAllowedState.PROHIBITED,
        lower_body_contribution=MBTAllowedState.PROHIBITED,
        throw_arm_technique="two-hand chest pass",
        starting_position="ball at chest; back against support",
        release_semantics=MBTReleaseSemantics.SOURCE_REPORTED_RELEASE,
        measurement_method=_ref(
            "measurement-method", "synthetic-tape", "Synthetic tape measurement"
        ),
        distance_origin_convention=origin,
        distance_endpoint_convention=endpoint,
        first_contact_no_roll_convention=no_roll,
        provider="synthetic-provider",
        device=device,
        sensor_modality=MBTSensorModality.MEASURING_TAPE,
    )
    artifact = MedicineBallThrowSourceArtifact(
        artifact_id=InstanceIdentifier("artifact", prefix),
        content_digest=f"sha256:{prefix}",
        media_type="application/vnd.synthetic.mbt-distance",
        status=MBTArtifactStatus.VERIFIED,
        hash_scope=MBTArtifactHashScope.CONTENT_BYTES,
    )
    acquisition = MedicineBallThrowAcquisitionRecord(
        acquisition_id=InstanceIdentifier("acquisition", prefix),
        device=device,
        source_artifact_id=artifact.artifact_id,
        provider="synthetic-provider",
        sensor_modality=MBTSensorModality.MEASURING_TAPE,
        axis_or_frame=frame,
    )
    context = _context(prefix)
    source = build_mbt_source_distance_observation(
        observation_id=InstanceIdentifier("observation", prefix),
        result_id=InstanceIdentifier("result", prefix),
        context=context,
        protocol_identity=protocol,
        distance_m=4.5,
        source_artifact=artifact,
        acquisition=acquisition,
    )
    coordinate_source = _mbt_coordinate_source(
        source_observation=source,
        protocol=protocol,
        artifact=artifact,
        acquisition=acquisition,
        origin_coordinate_m=1.0,
        endpoint_coordinate_m=5.5,
        coordinate_frame=frame,
        origin_convention=origin,
        endpoint_convention=endpoint,
        first_contact_no_roll_convention=no_roll,
        first_contact_observed=True,
        no_roll_observed=True,
        prefix=prefix,
    )
    coordinate = MBTCoordinateEvidence(
        source_observation_id=source.observation_id,
        origin_coordinate_m=1.0,
        endpoint_coordinate_m=5.5,
        coordinate_frame=frame,
        origin_convention=origin,
        endpoint_convention=endpoint,
        first_contact_no_roll_convention=no_roll,
        first_contact_observed=True,
        no_roll_observed=True,
        source_artifact_id=artifact.artifact_id,
        acquisition_id=acquisition.acquisition_id,
        source_evidence=coordinate_source,
    )
    return source, coordinate, protocol, artifact, acquisition, frame


def test_mbt_exact_distance_and_power_refusals() -> None:
    source, coordinate, _, _, _, _ = _mbt_distance_fixture()
    distance = _mbt_result(calculate_mbt_throw_distance(coordinate, source))
    assert distance.value_m == pytest.approx(4.5)
    assert calculate_mbt_distance_as_power(distance).blocks_claim
    assert calculate_mbt_release_velocity_from_distance(distance).blocks_claim
    assert canonical_hash(
        from_canonical_json(canonical_json(distance), type(distance))
    ) == canonical_hash(distance)


def test_mbt_protocol_conventions_and_variant_comparability() -> None:
    source, coordinate, _, _, _, _ = _mbt_distance_fixture()
    distance = _mbt_result(calculate_mbt_throw_distance(coordinate, source))
    standing_source, standing_coordinate, _, _, _, _ = _mbt_distance_fixture(
        throw_type=MBTThrowVariant.STANDING_CHEST,
        prefix="synthetic-mbt-standing-distance",
    )
    standing_distance = _mbt_result(
        calculate_mbt_throw_distance(standing_coordinate, standing_source)
    )
    assert (
        compare_mbt_metric_results(distance, standing_distance).state
        is ComparabilityState.NOT_COMPARABLE
    )
    with pytest.raises(ValueError, match="upstream coordinate evidence"):
        replace(
            coordinate,
            endpoint_convention=_ref("distance-endpoint", "rolled", "Rolled endpoint"),
        )


def test_mbt_coordinate_authority_requires_upstream_adjudication() -> None:
    source, coordinate, protocol, artifact, acquisition, frame = _mbt_distance_fixture(
        prefix="synthetic-mbt-coordinate-authority"
    )
    assert protocol.distance_origin_convention is not None
    assert protocol.distance_endpoint_convention is not None
    assert protocol.first_contact_no_roll_convention is not None
    raw_coordinate = MBTCoordinateEvidence(
        source_observation_id=source.observation_id,
        origin_coordinate_m=1.0,
        endpoint_coordinate_m=5.5,
        coordinate_frame=frame,
        origin_convention=protocol.distance_origin_convention,
        endpoint_convention=protocol.distance_endpoint_convention,
        first_contact_no_roll_convention=protocol.first_contact_no_roll_convention,
        first_contact_observed=True,
        no_roll_observed=True,
        source_artifact_id=artifact.artifact_id,
        acquisition_id=acquisition.acquisition_id,
    )
    assert _refused(calculate_mbt_throw_distance(raw_coordinate, source)).blocks_claim
    source_evidence = coordinate.source_evidence
    assert source_evidence is not None
    with pytest.raises(ValueError):
        normalize_mbt_coordinate_evidence(
            replace(source_evidence, source_content_digest="sha256:wrong"), source
        )
    with pytest.raises(ValueError):
        normalize_mbt_coordinate_evidence(
            replace(source_evidence, source_context_id=InstanceIdentifier("context", "other")),
            source,
        )
    with pytest.raises(ValueError):
        normalize_mbt_coordinate_evidence(
            replace(source_evidence, protocol_reference=_ref("protocol", "other", "Other")),
            source,
        )
    with pytest.raises(ValueError):
        normalize_mbt_coordinate_evidence(
            replace(source_evidence, source_artifact_id=InstanceIdentifier("artifact", "other")),
            source,
        )
    with pytest.raises(ValueError):
        normalize_mbt_coordinate_evidence(
            replace(
                source_evidence,
                source_acquisition_id=InstanceIdentifier("acquisition", "other"),
            ),
            source,
        )
    with pytest.raises(ValueError):
        normalize_mbt_coordinate_evidence(
            replace(
                source_evidence,
                endpoint_convention=_ref("distance-endpoint", "other", "Other endpoint"),
            ),
            source,
        )
    with pytest.raises(ValueError):
        normalize_mbt_coordinate_evidence(
            replace(source_evidence, coordinate_frame=_ref("frame", "other", "Other frame")),
            source,
        )
    with pytest.raises(ValueError):
        normalize_mbt_coordinate_evidence(
            replace(
                source_evidence,
                provenance=replace(source_evidence.provenance, lineage_edges=()),
            ),
            source,
        )
    normalized = normalize_mbt_coordinate_evidence(source_evidence, source, coordinate)
    assert normalized == coordinate
    restored = from_canonical_json(canonical_json(source_evidence), type(source_evidence))
    assert restored == source_evidence
    assert canonical_hash(restored) == canonical_hash(source_evidence)
    distance = _mbt_result(calculate_mbt_throw_distance(normalized, source))
    assert distance.value_m == pytest.approx(4.5)
    assert source.result.classification.value_origin is ValueOrigin.SOURCE_REPORTED
    assert isinstance(source.result.value, ScalarValue)
    assert source.result.value.value == pytest.approx(4.5)
    assert acquisition.axis_or_frame == frame


def test_mbt_instrumented_release_velocity_requires_qualified_event_evidence() -> None:
    _, _, _, _, _, _ = _mbt_distance_fixture()
    frame = _ref("frame", "ball-forward", "Ball forward frame")
    device = _ref("device", "synthetic-radar", "Synthetic radar")
    protocol = MedicineBallThrowProtocolIdentity(
        throw_type=MBTThrowVariant.STANDING_CHEST,
        body_posture=MBTBodyPosture.STANDING,
        support_restraint_condition=MBTSupportCondition.FREE_STANDING,
        ball_mass_kg=2.0,
        countermovement=MBTAllowedState.ALLOWED,
        lower_body_contribution=MBTAllowedState.ALLOWED,
        throw_arm_technique="two-hand chest throw",
        starting_position="ball at chest",
        release_semantics=MBTReleaseSemantics.EXPLICIT_RELEASE_EVENT,
        measurement_method=_ref(
            "measurement-method", "synthetic-radar", "Synthetic trajectory/radar"
        ),
        provider="synthetic-provider",
        device=device,
        sensor_modality=MBTSensorModality.RADAR,
    )
    timebase = MBTTimebase(MBTTimebaseKind.EXPLICIT, times_s=(0.0, 0.1, 0.2))
    trajectory = ((0.0, 0.0), (0.1, 0.2), (0.2, 0.5))
    velocity = ((0.0, 0.0), (0.1, 2.0), (0.2, 3.5))
    velocity_definition = _ref(
        "velocity-definition", "release-sample", "Exact release sample velocity"
    )
    digest = canonical_hash(
        {
            "trajectory_samples": trajectory,
            "velocity_samples": velocity,
            "timebase": timebase,
            "coordinate_frame": frame,
        }
    )
    artifact = MedicineBallThrowSourceArtifact(
        artifact_id=InstanceIdentifier("artifact", "synthetic-mbt-release"),
        content_digest=digest,
        media_type="application/vnd.synthetic.mbt-trajectory",
        status=MBTArtifactStatus.VERIFIED,
        hash_scope=MBTArtifactHashScope.CANONICAL_SERIES_REPRESENTATION,
    )
    acquisition = MedicineBallThrowAcquisitionRecord(
        acquisition_id=InstanceIdentifier("acquisition", "synthetic-mbt-release"),
        device=device,
        source_artifact_id=artifact.artifact_id,
        provider="synthetic-provider",
        sensor_modality=MBTSensorModality.RADAR,
        timebase=timebase,
        axis_or_frame=frame,
    )
    context = _context("synthetic-mbt-release")
    event_id = InstanceIdentifier("event-occurrence", "synthetic-mbt-release")
    release_source = MBTReleaseEventSourceEvidence(
        source_event_id=event_id,
        source_context_id=context.context_id,
        source_observation_id=InstanceIdentifier("observation", "synthetic-mbt-release"),
        source_series_id=InstanceIdentifier("signal", "synthetic-mbt-release"),
        source_artifact_id=artifact.artifact_id,
        source_acquisition_id=acquisition.acquisition_id,
        source_measurement_identity_id=ScientificIdentifier(
            "dynamislm", "measurement-identity", "mbt-release:synthetic-mbt-release", "1.0.0"
        ),
        source_series_digest=digest,
        source_timebase=timebase,
        sample_index=2,
        event_time_s=0.2,
        release_method=velocity_definition,
        coordinate_frame=frame,
        protocol_reference=protocol.reference,
        provider=acquisition.provider,
        upstream_processing_run_id=InstanceIdentifier(
            "processing-run", "synthetic-mbt-release:event-source"
        ),
        provenance=Provenance(
            provenance_id=InstanceIdentifier("provenance", "synthetic-mbt-release:event-source"),
            source_artifacts=(artifact,),
            acquisitions=(acquisition,),
            processing_runs=(),
            lineage_edges=(),
        ),
    )
    release_source_parameters = (
        MetadataEntry("source_event_id", release_source.source_event_id.qualified),
        MetadataEntry("source_context_id", release_source.source_context_id.qualified),
        MetadataEntry("source_observation_id", release_source.source_observation_id.qualified),
        MetadataEntry("source_series_id", release_source.source_series_id.qualified),
        MetadataEntry("source_artifact_id", release_source.source_artifact_id.qualified),
        MetadataEntry("source_acquisition_id", release_source.source_acquisition_id.qualified),
        MetadataEntry(
            "source_measurement_identity_id",
            release_source.source_measurement_identity_id.stable_id,
        ),
        MetadataEntry("source_series_digest", release_source.source_series_digest),
        MetadataEntry("source_timebase", canonical_json(release_source.source_timebase)),
        MetadataEntry("sample_index", release_source.sample_index),
        MetadataEntry("event_time_s", release_source.event_time_s),
        MetadataEntry("release_method", release_source.release_method.stable_id),
        MetadataEntry("coordinate_frame", release_source.coordinate_frame.stable_id),
        MetadataEntry("protocol_reference", release_source.protocol_reference.stable_id),
        MetadataEntry("provider", release_source.provider),
        MetadataEntry("method_parameters", canonical_json(release_source.method_parameters)),
        MetadataEntry("source_value_origin", release_source.source_value_origin),
    )
    release_run = ProcessingRun(
        processing_run_id=release_source.upstream_processing_run_id,
        source_artifact_ids=(artifact.artifact_id,),
        method=MBT_RELEASE_EVENT_SOURCE_OPERATION,
        parameters=release_source_parameters,
        software_version="synthetic-upstream-mbt-release-event-v1",
        output_entity_id=event_id,
    )
    release_source = replace(
        release_source,
        provenance=replace(
            release_source.provenance,
            processing_runs=(release_run,),
            lineage_edges=(
                LineageEdge(
                    release_source.source_observation_id.qualified,
                    release_run.processing_run_id.qualified,
                    LineageRelation.DERIVED_FROM,
                ),
                LineageEdge(
                    release_source.source_series_id.qualified,
                    release_run.processing_run_id.qualified,
                    LineageRelation.DERIVED_FROM,
                ),
                LineageEdge(
                    artifact.artifact_id.qualified,
                    release_run.processing_run_id.qualified,
                    LineageRelation.DERIVED_FROM,
                ),
                LineageEdge(
                    acquisition.acquisition_id.qualified,
                    release_run.processing_run_id.qualified,
                    LineageRelation.DERIVED_FROM,
                ),
                LineageEdge(
                    MBT_RELEASE_EVENT_QUALIFICATION_RULE.stable_id,
                    release_run.processing_run_id.qualified,
                    LineageRelation.SUPPORTED_BY,
                ),
                LineageEdge(
                    release_run.processing_run_id.qualified,
                    event_id.qualified,
                    LineageRelation.PRODUCED,
                ),
            ),
        ),
    )
    event = MBTReleaseEvent(
        event_id=event_id,
        source_observation_id=InstanceIdentifier("observation", "synthetic-mbt-release"),
        source_series_id=InstanceIdentifier("signal", "synthetic-mbt-release"),
        source_artifact_id=artifact.artifact_id,
        acquisition_id=acquisition.acquisition_id,
        sample_index=2,
        event_time_s=0.2,
        release_method=velocity_definition,
        coordinate_frame=frame,
        source_series_digest=digest,
        source_evidence=release_source,
    )
    evidence = build_mbt_release_velocity_evidence(
        observation_id=event.source_observation_id,
        result_id=InstanceIdentifier("result", "synthetic-mbt-release"),
        context=context,
        protocol_identity=protocol,
        release_event=event,
        trajectory_samples=trajectory,
        velocity_samples=velocity,
        timebase=timebase,
        coordinate_frame=frame,
        velocity_definition=velocity_definition,
        source_artifact=artifact,
        acquisition=acquisition,
    )
    raw_event = replace(event, source_evidence=None)
    with pytest.raises(ValueError, match=r"source_evidence"):
        build_mbt_release_velocity_evidence(
            observation_id=event.source_observation_id,
            result_id=InstanceIdentifier("result", "synthetic-mbt-release-raw"),
            context=context,
            protocol_identity=protocol,
            release_event=raw_event,
            trajectory_samples=trajectory,
            velocity_samples=velocity,
            timebase=timebase,
            coordinate_frame=frame,
            velocity_definition=velocity_definition,
            source_artifact=artifact,
            acquisition=acquisition,
        )
    with pytest.raises(ValueError):
        replace(event, sample_index=1)
    with pytest.raises(ValueError):
        replace(event, event_time_s=0.1)
    with pytest.raises(ValueError):
        replace(event, release_method=_ref("velocity-definition", "other", "Other velocity"))
    with pytest.raises(ValueError):
        replace(event, source_artifact_id=InstanceIdentifier("artifact", "other-artifact"))
    with pytest.raises(ValueError):
        replace(event, acquisition_id=InstanceIdentifier("acquisition", "other-acquisition"))
    assert event.source_evidence is not None
    forged_protocol_event = replace(
        event,
        source_evidence=replace(
            event.source_evidence,
            protocol_reference=_ref("protocol", "other", "Other protocol"),
        ),
    )
    with pytest.raises(ValueError):
        build_mbt_release_velocity_evidence(
            observation_id=event.source_observation_id,
            result_id=InstanceIdentifier("result", "synthetic-mbt-release-forged-protocol"),
            context=context,
            protocol_identity=protocol,
            release_event=forged_protocol_event,
            trajectory_samples=trajectory,
            velocity_samples=velocity,
            timebase=timebase,
            coordinate_frame=frame,
            velocity_definition=velocity_definition,
            source_artifact=artifact,
            acquisition=acquisition,
        )
    forged_provenance_event = replace(
        event,
        source_evidence=replace(
            event.source_evidence,
            provenance=replace(
                event.source_evidence.provenance,
                lineage_edges=(
                    LineageEdge(
                        event.source_evidence.upstream_processing_run_id.qualified,
                        event.event_id.qualified,
                        LineageRelation.PRODUCED,
                    ),
                ),
            ),
        ),
    )
    with pytest.raises(ValueError):
        build_mbt_release_velocity_evidence(
            observation_id=event.source_observation_id,
            result_id=InstanceIdentifier("result", "synthetic-mbt-release-forged-provenance"),
            context=context,
            protocol_identity=protocol,
            release_event=forged_provenance_event,
            trajectory_samples=trajectory,
            velocity_samples=velocity,
            timebase=timebase,
            coordinate_frame=frame,
            velocity_definition=velocity_definition,
            source_artifact=artifact,
            acquisition=acquisition,
        )
    forged_origin_event = replace(
        event,
        source_evidence=replace(event.source_evidence, source_value_origin="SOURCE_REPORTED"),
    )
    with pytest.raises(ValueError):
        build_mbt_release_velocity_evidence(
            observation_id=event.source_observation_id,
            result_id=InstanceIdentifier("result", "synthetic-mbt-release-forged-origin"),
            context=context,
            protocol_identity=protocol,
            release_event=forged_origin_event,
            trajectory_samples=trajectory,
            velocity_samples=velocity,
            timebase=timebase,
            coordinate_frame=frame,
            velocity_definition=velocity_definition,
            source_artifact=artifact,
            acquisition=acquisition,
        )
    result = _mbt_result(calculate_mbt_instrumented_release_velocity(evidence))
    assert result.value_m_per_s == pytest.approx(3.5)
    assert evidence.release_event.source_evidence is not None
    encoded = canonical_json(evidence.release_event.source_evidence)
    restored = from_canonical_json(encoded, type(evidence.release_event.source_evidence))
    assert restored == evidence.release_event.source_evidence
    assert canonical_hash(restored) == canonical_hash(evidence.release_event.source_evidence)


def _mbt_release_fixture(
    trajectory_samples: tuple[tuple[int | float, int | float], ...],
    velocity_samples: tuple[tuple[int | float, int | float], ...],
    *,
    prefix: str,
) -> MBTReleaseVelocityEvidence:
    normalized_trajectory = tuple((float(time), float(value)) for time, value in trajectory_samples)
    normalized_velocity = tuple((float(time), float(value)) for time, value in velocity_samples)
    timebase = MBTTimebase(
        MBTTimebaseKind.EXPLICIT,
        times_s=tuple(time for time, _ in normalized_trajectory),
    )
    frame = _ref("frame", f"{prefix}-forward", "Ball forward frame")
    device = _ref("device", f"{prefix}-radar", "Synthetic radar")
    protocol = MedicineBallThrowProtocolIdentity(
        throw_type=MBTThrowVariant.STANDING_CHEST,
        body_posture=MBTBodyPosture.STANDING,
        support_restraint_condition=MBTSupportCondition.FREE_STANDING,
        ball_mass_kg=2.0,
        countermovement=MBTAllowedState.ALLOWED,
        lower_body_contribution=MBTAllowedState.ALLOWED,
        throw_arm_technique="two-hand chest throw",
        starting_position="ball at chest",
        release_semantics=MBTReleaseSemantics.EXPLICIT_RELEASE_EVENT,
        measurement_method=_ref("measurement-method", f"{prefix}-radar", "Synthetic radar"),
        provider="synthetic-provider",
        device=device,
        sensor_modality=MBTSensorModality.RADAR,
    )
    digest = canonical_hash(
        {
            "trajectory_samples": normalized_trajectory,
            "velocity_samples": normalized_velocity,
            "timebase": timebase,
            "coordinate_frame": frame,
        }
    )
    artifact = MedicineBallThrowSourceArtifact(
        artifact_id=InstanceIdentifier("artifact", prefix),
        content_digest=digest,
        media_type="application/vnd.synthetic.mbt-trajectory",
        status=MBTArtifactStatus.VERIFIED,
        hash_scope=MBTArtifactHashScope.CANONICAL_SERIES_REPRESENTATION,
    )
    acquisition = MedicineBallThrowAcquisitionRecord(
        acquisition_id=InstanceIdentifier("acquisition", prefix),
        device=device,
        source_artifact_id=artifact.artifact_id,
        provider="synthetic-provider",
        sensor_modality=MBTSensorModality.RADAR,
        timebase=timebase,
        axis_or_frame=frame,
    )
    context = _context(prefix)
    observation_id = InstanceIdentifier("observation", prefix)
    event_id = InstanceIdentifier("event-occurrence", prefix)
    source_event = MBTReleaseEventSourceEvidence(
        source_event_id=event_id,
        source_context_id=context.context_id,
        source_observation_id=observation_id,
        source_series_id=InstanceIdentifier("signal", prefix),
        source_artifact_id=artifact.artifact_id,
        source_acquisition_id=acquisition.acquisition_id,
        source_measurement_identity_id=ScientificIdentifier(
            "dynamislm", "measurement-identity", f"mbt-release:{prefix}", "1.0.0"
        ),
        source_series_digest=digest,
        source_timebase=timebase,
        sample_index=len(normalized_velocity) - 1,
        event_time_s=normalized_velocity[-1][0],
        release_method=_ref("velocity-definition", f"{prefix}-sample", "Exact release sample"),
        coordinate_frame=frame,
        protocol_reference=protocol.reference,
        provider=acquisition.provider,
        upstream_processing_run_id=InstanceIdentifier(
            "processing-run", f"{prefix}:release-event-source"
        ),
        provenance=Provenance(
            provenance_id=InstanceIdentifier("provenance", f"{prefix}:release-event-source"),
            source_artifacts=(artifact,),
            acquisitions=(acquisition,),
            processing_runs=(),
            lineage_edges=(),
        ),
    )
    source_event = replace(
        source_event,
        provenance=replace(
            source_event.provenance,
            processing_runs=(
                ProcessingRun(
                    processing_run_id=source_event.upstream_processing_run_id,
                    source_artifact_ids=(artifact.artifact_id,),
                    method=MBT_RELEASE_EVENT_SOURCE_OPERATION,
                    parameters=_release_event_source_parameters(source_event),
                    software_version="synthetic-upstream-mbt-release-event-v1",
                    output_entity_id=event_id,
                ),
            ),
            lineage_edges=(
                LineageEdge(
                    observation_id.qualified,
                    source_event.upstream_processing_run_id.qualified,
                    LineageRelation.DERIVED_FROM,
                ),
                LineageEdge(
                    source_event.source_series_id.qualified,
                    source_event.upstream_processing_run_id.qualified,
                    LineageRelation.DERIVED_FROM,
                ),
                LineageEdge(
                    artifact.artifact_id.qualified,
                    source_event.upstream_processing_run_id.qualified,
                    LineageRelation.DERIVED_FROM,
                ),
                LineageEdge(
                    acquisition.acquisition_id.qualified,
                    source_event.upstream_processing_run_id.qualified,
                    LineageRelation.DERIVED_FROM,
                ),
                LineageEdge(
                    MBT_RELEASE_EVENT_QUALIFICATION_RULE.stable_id,
                    source_event.upstream_processing_run_id.qualified,
                    LineageRelation.SUPPORTED_BY,
                ),
                LineageEdge(
                    source_event.upstream_processing_run_id.qualified,
                    event_id.qualified,
                    LineageRelation.PRODUCED,
                ),
            ),
        ),
    )
    event = MBTReleaseEvent(
        event_id=event_id,
        source_observation_id=observation_id,
        source_series_id=source_event.source_series_id,
        source_artifact_id=artifact.artifact_id,
        acquisition_id=acquisition.acquisition_id,
        sample_index=source_event.sample_index,
        event_time_s=source_event.event_time_s,
        release_method=source_event.release_method,
        coordinate_frame=frame,
        source_series_digest=digest,
        source_evidence=source_event,
    )
    return build_mbt_release_velocity_evidence(
        observation_id=observation_id,
        result_id=InstanceIdentifier("result", prefix),
        context=context,
        protocol_identity=protocol,
        release_event=event,
        trajectory_samples=trajectory_samples,
        velocity_samples=velocity_samples,
        timebase=timebase,
        coordinate_frame=frame,
        velocity_definition=source_event.release_method,
        source_artifact=artifact,
        acquisition=acquisition,
    )


def test_mbt_integer_and_float_samples_have_one_authoritative_digest() -> None:
    integer_evidence = _mbt_release_fixture(
        ((0, 0), (1, 2), (2, 3)),
        ((0, 0), (1, 2), (2, 3)),
        prefix="synthetic-mbt-numeric-equivalence",
    )
    float_evidence = _mbt_release_fixture(
        ((0.0, 0.0), (1.0, 2.0), (2.0, 3.0)),
        ((0.0, 0.0), (1.0, 2.0), (2.0, 3.0)),
        prefix="synthetic-mbt-numeric-equivalence",
    )
    assert integer_evidence == float_evidence
    assert canonical_hash(integer_evidence) == canonical_hash(float_evidence)
    assert integer_evidence.release_velocity_m_per_s == pytest.approx(3.0)
    assert _refused(
        calculate_mbt_instrumented_release_velocity(cast(MBTReleaseVelocityEvidence, object()))
    ).blocks_claim
