"""Adversarial deterministic fixtures for RES-66 strength authority."""

from __future__ import annotations

import datetime as datetime_module
from dataclasses import replace
from typing import Any

import pytest

from dynamislm.comparability import ComparabilityState
from dynamislm.measurement import (
    AcquisitionIdentity,
    InstanceIdentifier,
    MeasurementIdentity,
    MeasurementQuality,
    MeasurementResult,
    MetadataEntry,
    ObservationContext,
    ProcessingIdentity,
    RegistryReference,
    ResultStatus,
    ScalarValue,
    ScientificClassification,
    ScientificIdentifier,
    ScientificMeasurementObservation,
    SemanticIdentity,
    UncertaintyMetadata,
    VersionIdentity,
)
from dynamislm.measurement.identity import SamplingCharacteristics, SignConvention
from dynamislm.measurement.strength.identity import (
    IMTPMeasurementIdentity,
    StrengthAcquisitionIdentity,
    StrengthEquipmentMode,
    StrengthExternalLoadStatus,
    StrengthImplementType,
    StrengthLoadIdentity,
    StrengthLoadSemantics,
    StrengthProcessingComponentStatus,
    StrengthProcessingIdentity,
    StrengthProcessingState,
    StrengthProcessingStep,
    StrengthProtocolAttribute,
    StrengthProtocolIdentity,
    StrengthSemanticIdentity,
    StrengthSensorModality,
    StrengthTestFamily,
    StrengthTimebase,
    StrengthTimebaseKind,
    VBTMeasurementIdentity,
)
from dynamislm.measurement.strength.imtp import (
    IMTPBaseline,
    IMTPBaselineSegment,
    IMTPBodyMassObservation,
    IMTPForceInput,
    IMTPForceQuantity,
    IMTPForceTimeSeries,
    IMTPMetricResult,
    IMTPOnset,
    IMTPOnsetParameters,
    IMTPThresholdDirection,
    IMTPTrialMetricInput,
    IMTPTrialQualificationStatus,
    IMTPTrialSelectionRule,
    aggregate_imtp_metric_results,
    build_imtp_baseline,
    calculate_imtp_force_at_time,
    calculate_imtp_impulse,
    calculate_imtp_peak_force,
    calculate_imtp_rfd,
    create_imtp_force_input,
    detect_imtp_onset,
    normalize_imtp_force,
    qualify_imtp_trial,
    source_artifact_for_imtp_series,
)
from dynamislm.measurement.strength.registry import (
    BENCH_PRESS_VBT_PROTOCOL_V1,
    BENCH_PRESS_VBT_TEST_FAMILY,
    BODY_MASS_MEASURAND,
    BODY_MASS_METRIC,
    IMTP_CONSTRUCT,
    IMTP_ENDPOINT_RFD_METHOD,
    IMTP_FORCE_TIME_SERIES_METRIC,
    IMTP_INPUT_OPERATION,
    IMTP_ONSET_BASELINE_FIVE_SD_METHOD,
    IMTP_PROTOCOL_V1,
    IMTP_TEST_FAMILY,
    IMTP_VERTICAL_FORCE_MEASURAND,
    KILOGRAM,
    METER_PER_SECOND,
    NEWTON,
    NEWTON_PER_KILOGRAM,
    RES66_DECISION_STRENGTH_IMTP_VBT,
    STRENGTH_MAXIMUM_STRENGTH_CONSTRUCT,
    STRENGTH_REGISTRY_VERSION,
    VBT_BAR_VELOCITY_CONSTRUCT,
    VBT_BENCH_PRESS_EXERCISE,
    VBT_BENCH_PRESS_FULL_ROM,
    VBT_BENCH_PRESS_TOUCH_AND_GO_PAUSE,
    VBT_BENCH_PRESS_TOUCH_AND_GO_VARIANT,
    VBT_CONCENTRIC_PHASE_DEFINITION,
    VBT_DIRECT_1RM_ASSESSMENT_OPERATION,
    VBT_DIRECT_1RM_MAXIMALITY_DECLARATION,
    VBT_EXPLICIT_CONCENTRIC_PHASE_METHOD,
    VBT_INPUT_OPERATION,
    VBT_MEAN_PROPULSIVE_VELOCITY_METRIC,
    VBT_MEASURED_1RM_MEASURAND,
    VBT_MEASURED_1RM_METRIC,
    VBT_MEASURED_1RM_SELECTION_RULE,
    VBT_PEAK_VELOCITY_METRIC,
    VBT_PHASE_BOUNDARY_CONVENTION,
    VBT_PHASE_SOURCE_PROCESSING_METHOD,
    VBT_PHASE_SOURCE_QUALIFICATION_RULE,
    VBT_SMITH_MACHINE_EQUIPMENT,
    VBT_VELOCITY_MEASURAND,
    VBT_VELOCITY_SERIES_METRIC,
)
from dynamislm.measurement.strength.vbt import (
    VBT_SMITH_BENCH_GENERAL_TERMINAL_VELOCITY_017,
    EstimatedOneRepMax,
    MeasuredOneRepMax,
    MeasuredOneRepMaxAssessmentEvidence,
    TerminalVelocityAssumption,
    VBTConcentricPhase,
    VBTConcentricPhaseSourceEvidence,
    VBTMetric,
    VBTMetricResult,
    VBTPhaseSourceAuthority,
    VBTSuccessfulRepetition,
    VBTVelocityLossReference,
    VBTVelocitySeries,
    VBTVelocitySeriesEvidence,
    build_measured_1rm,
    calculate_mean_concentric_velocity,
    calculate_peak_velocity,
    calculate_velocity_loss,
    compare_vbt_fixed_load,
    create_vbt_velocity_evidence,
    estimate_1rm_from_load_velocity_model,
    fit_load_velocity_model,
    qualify_vbt_concentric_phase,
    refuse_estimated_1rm_as_measured,
    refuse_mean_propulsive_velocity,
    refuse_velocity_loss_as_fatigue,
    source_artifact_for_vbt_series,
)
from dynamislm.measurement.taxonomy import ValueOrigin
from dynamislm.provenance import (
    AcquisitionRecord,
    EvidenceReference,
    LineageEdge,
    LineageRelation,
    ProcessingRun,
    Provenance,
    SourceArtifact,
)
from dynamislm.refusal import RefusalResult
from dynamislm.serialization import canonical_hash, canonical_json, from_canonical_json


def _ref(object_type: str, key: str, label: str) -> RegistryReference:
    return RegistryReference(
        ScientificIdentifier("synthetic-res66", object_type, key, "1.0"), label
    )


def _context(*, trial: str = "trial") -> ObservationContext:
    return ObservationContext(
        context_id=InstanceIdentifier("context", f"ctx-{trial}"),
        athlete_id=InstanceIdentifier("athlete", "athlete-1"),
        session_id=InstanceIdentifier("session", "session-1"),
        test_instance_id=InstanceIdentifier("test-instance", "test-1"),
        trial_id=InstanceIdentifier("trial", trial),
        observed_at=datetime_module.datetime(2026, 1, 1, tzinfo=datetime_module.UTC),
        population_context="synthetic_deterministic_fixture",
    )


def _phase(
    evidence: VBTVelocitySeriesEvidence,
    *,
    boundary_parameters: tuple[MetadataEntry, ...] = (),
) -> VBTConcentricPhase:
    source_phase_id = InstanceIdentifier("phase-occurrence", f"upstream-phase-{evidence.rep_index}")
    start_index, end_index = 0, 3
    source_parameters = (
        MetadataEntry("phase_definition", VBT_CONCENTRIC_PHASE_DEFINITION.stable_id),
        MetadataEntry("boundary_method", VBT_EXPLICIT_CONCENTRIC_PHASE_METHOD.stable_id),
        MetadataEntry("boundary_convention", VBT_PHASE_BOUNDARY_CONVENTION.stable_id),
        MetadataEntry("source_phase_id", source_phase_id.qualified),
        MetadataEntry("source_observation_id", evidence.observation.observation_id.qualified),
        MetadataEntry("source_series_id", evidence.series.series_id.qualified),
        MetadataEntry("source_artifact_id", evidence.source_artifact.artifact_id.qualified),
        MetadataEntry("source_acquisition_id", evidence.acquisition.acquisition_id.qualified),
        MetadataEntry("source_measurement_identity_id", evidence.identity.identity_id.stable_id),
        MetadataEntry("source_series_digest", evidence.source_series_digest),
        MetadataEntry("source_timebase", canonical_json(evidence.series.timebase)),
        MetadataEntry("source_sample_count", len(evidence.series.samples)),
        MetadataEntry("set_id", evidence.set_id.qualified),
        MetadataEntry("rep_id", evidence.rep_id.qualified),
        MetadataEntry("rep_index", evidence.rep_index),
        MetadataEntry("external_load", canonical_json(evidence.external_load)),
        MetadataEntry("start_index", start_index),
        MetadataEntry("end_index", end_index),
        MetadataEntry("start_time_s", 0.0),
        MetadataEntry("end_time_s", 0.06),
        MetadataEntry("boundary_parameters", canonical_json(boundary_parameters)),
        MetadataEntry("authority", VBTPhaseSourceAuthority.REGISTERED_UPSTREAM_PROCESSING.value),
        MetadataEntry("upstream_processing_run_id", "processing-run:upstream-phase-run"),
    )
    source_run = ProcessingRun(
        processing_run_id=InstanceIdentifier("processing-run", "upstream-phase-run"),
        source_artifact_ids=(evidence.source_artifact.artifact_id,),
        method=VBT_PHASE_SOURCE_PROCESSING_METHOD,
        parameters=source_parameters,
        software_version="synthetic-upstream-phase-1",
        output_entity_id=source_phase_id,
    )
    source_edges = list(evidence.observation.provenance.lineage_edges)
    for entity_id in (
        evidence.observation.observation_id,
        evidence.series.series_id,
        evidence.set_id,
        evidence.rep_id,
    ):
        source_edges.append(
            LineageEdge(
                entity_id.qualified,
                source_run.processing_run_id.qualified,
                LineageRelation.DERIVED_FROM,
            )
        )
    source_edges.append(
        LineageEdge(
            VBT_PHASE_SOURCE_QUALIFICATION_RULE.stable_id,
            source_run.processing_run_id.qualified,
            LineageRelation.SUPPORTED_BY,
        )
    )
    source_edges.append(
        LineageEdge(
            source_run.processing_run_id.qualified,
            source_phase_id.qualified,
            LineageRelation.PRODUCED,
        )
    )
    source_provenance = replace(
        evidence.observation.provenance,
        processing_runs=(*evidence.observation.provenance.processing_runs, source_run),
        lineage_edges=tuple(source_edges),
    )
    source = VBTConcentricPhaseSourceEvidence(
        source_phase_id=source_phase_id,
        source_context=evidence.observation.context,
        source_observation_id=evidence.observation.observation_id,
        source_series_id=evidence.series.series_id,
        source_artifact_id=evidence.source_artifact.artifact_id,
        source_acquisition_id=evidence.acquisition.acquisition_id,
        source_measurement_identity_id=evidence.identity.identity_id,
        source_series_digest=evidence.source_series_digest,
        source_timebase=evidence.series.timebase,
        source_sample_count=len(evidence.series.samples),
        set_id=evidence.set_id,
        rep_id=evidence.rep_id,
        rep_index=evidence.rep_index,
        external_load=evidence.external_load,
        start_index=start_index,
        end_index=end_index,
        start_time_s=0.0,
        end_time_s=0.06,
        boundary_parameters=boundary_parameters,
        authority=VBTPhaseSourceAuthority.REGISTERED_UPSTREAM_PROCESSING,
        upstream_processing_run_id=source_run.processing_run_id,
        provenance=source_provenance,
    )
    phase = qualify_vbt_concentric_phase(evidence, source)
    if not isinstance(phase, VBTConcentricPhase):
        raise AssertionError("synthetic phase fixture failed")
    return phase


def _imtp_fixture(
    suffix: str = "",
) -> tuple[IMTPForceInput, IMTPBaseline, IMTPOnset, IMTPMeasurementIdentity]:
    device = _ref("device", "force-platform", "Synthetic force platform")
    axis = _ref("axis", "vertical", "Vertical")
    frame = _ref("reference-frame", "platform", "Platform frame")
    timebase = StrengthTimebase(StrengthTimebaseKind.REGULAR, sample_rate_hz=1000.0)
    artifact_id = InstanceIdentifier("artifact", f"imtp-artifact{suffix}")
    acquisition_id = InstanceIdentifier("acquisition", f"imtp-acquisition{suffix}")
    signal_id = InstanceIdentifier("signal", f"imtp-signal{suffix}")
    identity_id = ScientificIdentifier(
        "dynamislm", "measurement-identity", f"imtp-source{suffix}", STRENGTH_REGISTRY_VERSION
    )
    sign = SignConvention(positive_direction="up")
    protocol = StrengthProtocolIdentity(
        reference=IMTP_PROTOCOL_V1,
        test_family=StrengthTestFamily.IMTP,
        exercise=_ref("exercise", "imtp", "Isometric mid-thigh pull"),
        equipment=_ref("equipment", "rig", "Synthetic fixed rig"),
        equipment_mode=StrengthEquipmentMode.FIXED_RIG,
        external_load_status=StrengthExternalLoadStatus.NONE,
        provider="synthetic fixture",
        sensor_modality=StrengthSensorModality.FORCE_PLATFORM,
        attachment_location="platform",
    )
    samples = (*((100.0, 100.0, 100.0, 100.0)), *(110.0 + 2.0 * index for index in range(201)))
    series = IMTPForceTimeSeries(
        signal_id=signal_id,
        source_artifact_id=artifact_id,
        acquisition_id=acquisition_id,
        source_measurement_identity_id=identity_id,
        samples=samples,
        timebase=timebase,
        unit=NEWTON,
        physical_axis=axis,
        reference_frame=frame,
        sign_convention=sign,
    )
    acquisition_identity = StrengthAcquisitionIdentity(
        device=device,
        raw_artifact=artifact_id,
        sensor_channel="force",
        sampling=SamplingCharacteristics(1000.0, ("force",)),
        provider="synthetic fixture",
        acquisition_instance_id=acquisition_id,
        sensor_modality=StrengthSensorModality.FORCE_PLATFORM,
        attachment_location="platform",
        timebase=timebase,
        unit=NEWTON,
        physical_axis=axis,
        reference_frame=frame,
        sign_convention=sign,
        processing_state=StrengthProcessingState.RAW_ACQUIRED,
    )
    identity = IMTPMeasurementIdentity(
        identity_id=identity_id,
        semantic=StrengthSemanticIdentity(
            construct=IMTP_CONSTRUCT,
            test_family=IMTP_TEST_FAMILY,
            protocol=IMTP_PROTOCOL_V1,
            measurand=IMTP_VERTICAL_FORCE_MEASURAND,
            metric_definition=IMTP_FORCE_TIME_SERIES_METRIC,
            protocol_identity=protocol,
        ),
        acquisition=acquisition_identity,
        processing=StrengthProcessingIdentity(
            registered_operation=IMTP_INPUT_OPERATION,
            filtering_status=StrengthProcessingComponentStatus.NONE_DECLARED,
            processing_state=StrengthProcessingState.RAW_ACQUIRED,
        ),
        version=VersionIdentity(
            processing_method=IMTP_INPUT_OPERATION,
            method_registry_version=STRENGTH_REGISTRY_VERSION,
            software_version="synthetic-imtp-source-1",
            hardware_firmware=device,
        ),
    )
    artifact = source_artifact_for_imtp_series(series)
    acquisition = AcquisitionRecord(
        acquisition_id=acquisition_id,
        device=device,
        source_artifact_id=artifact_id,
        sensor_channel="force",
        sampling=acquisition_identity.sampling,
    )
    force = create_imtp_force_input(
        observation_id=InstanceIdentifier("observation", f"imtp-source{suffix}"),
        result_id=InstanceIdentifier("result", f"imtp-source{suffix}"),
        context=_context(trial=f"imtp-trial{suffix}"),
        identity=identity,
        series=series,
        source_artifact=artifact,
        acquisition=acquisition,
        evidence_references=(
            EvidenceReference(RES66_DECISION_STRENGTH_IMTP_VBT, "synthetic fixture"),
        ),
    )
    baseline = build_imtp_baseline(
        force,
        IMTPBaselineSegment(signal_id, artifact_id, identity_id, 0, 4),
    )
    if not isinstance(baseline, IMTPBaseline):
        raise AssertionError("synthetic baseline fixture failed")
    onset = detect_imtp_onset(
        force,
        baseline,
        IMTPOnsetParameters(5.0, IMTPThresholdDirection.ABOVE_THRESHOLD, 1, 4),
    )
    if not isinstance(onset, IMTPOnset):
        raise AssertionError("synthetic onset fixture failed")
    return force, baseline, onset, identity


def _vbt_evidence(
    index: int,
    *,
    load_kg: float = 50.0,
    velocity: float = 0.5,
    device_key: str = "lpt",
    processing_state: StrengthProcessingState = StrengthProcessingState.PROVIDER_PROCESSED,
    phase_bounds: tuple[int, int] = (0, 3),
    set_key: str = "set-1",
) -> VBTVelocitySeriesEvidence:
    device = _ref("device", device_key, f"Synthetic {device_key}")
    axis = _ref("axis", "bar-vertical", "Bar vertical")
    frame = _ref("reference-frame", "bar", "Bar frame")
    sign = SignConvention(positive_direction="up")
    artifact_id = InstanceIdentifier("artifact", f"vbt-artifact-{index}")
    acquisition_id = InstanceIdentifier("acquisition", f"vbt-acquisition-{index}")
    signal_id = InstanceIdentifier("signal", f"vbt-signal-{index}")
    observation_id = InstanceIdentifier("observation", f"vbt-source-{index}")
    identity_id = ScientificIdentifier(
        "dynamislm", "measurement-identity", f"vbt-source-{index}", STRENGTH_REGISTRY_VERSION
    )
    load = StrengthLoadIdentity(
        value=load_kg,
        unit=KILOGRAM,
        implement_type=StrengthImplementType.SMITH_MACHINE_BAR,
        semantics=StrengthLoadSemantics.TOTAL_EXTERNAL_LOAD,
        bar_mass_kg=20.0,
        total_external_load_kg=load_kg,
    )
    protocol = StrengthProtocolIdentity(
        reference=BENCH_PRESS_VBT_PROTOCOL_V1,
        test_family=StrengthTestFamily.BENCH_PRESS_VBT,
        exercise=VBT_BENCH_PRESS_EXERCISE,
        exercise_variant=VBT_BENCH_PRESS_TOUCH_AND_GO_VARIANT,
        equipment=VBT_SMITH_MACHINE_EQUIPMENT,
        equipment_mode=StrengthEquipmentMode.SMITH_MACHINE,
        range_of_motion=StrengthProtocolAttribute(
            "range_of_motion", VBT_BENCH_PRESS_FULL_ROM.stable_id
        ),
        pause_semantics=StrengthProtocolAttribute(
            "pause_semantics", VBT_BENCH_PRESS_TOUCH_AND_GO_PAUSE.stable_id
        ),
        external_load_status=StrengthExternalLoadStatus.DEFINED,
        external_load=load,
        provider="synthetic fixture",
        sensor_modality=StrengthSensorModality.LINEAR_POSITION_TRANSDUCER,
        attachment_location="right distal bar",
        sampling=SamplingCharacteristics(1000.0, ("bar",)),
    )
    timebase = StrengthTimebase(
        StrengthTimebaseKind.EXPLICIT,
        times_s=(0.0, 0.01, 0.03, 0.06, 0.10),
    )
    series = VBTVelocitySeries(
        series_id=signal_id,
        source_artifact_id=artifact_id,
        acquisition_id=acquisition_id,
        source_measurement_identity_id=identity_id,
        samples=(velocity, velocity + 0.1, velocity + 0.2, velocity + 0.1, velocity),
        timebase=timebase,
        unit=METER_PER_SECOND,
        physical_axis=axis,
        reference_frame=frame,
        sign_convention=sign,
        processing_state=processing_state,
    )
    acquisition_identity = StrengthAcquisitionIdentity(
        device=device,
        raw_artifact=artifact_id,
        acquisition_instance_id=acquisition_id,
        sensor_channel="bar",
        sampling=SamplingCharacteristics(1000.0, ("bar",)),
        provider="synthetic fixture",
        sensor_modality=StrengthSensorModality.LINEAR_POSITION_TRANSDUCER,
        attachment_location="right distal bar",
        timebase=timebase,
        unit=METER_PER_SECOND,
        physical_axis=axis,
        reference_frame=frame,
        sign_convention=sign,
        processing_state=processing_state,
    )
    identity = VBTMeasurementIdentity(
        identity_id=identity_id,
        semantic=StrengthSemanticIdentity(
            construct=VBT_BAR_VELOCITY_CONSTRUCT,
            test_family=BENCH_PRESS_VBT_TEST_FAMILY,
            protocol=BENCH_PRESS_VBT_PROTOCOL_V1,
            measurand=VBT_VELOCITY_MEASURAND,
            metric_definition=VBT_VELOCITY_SERIES_METRIC,
            protocol_identity=protocol,
        ),
        acquisition=acquisition_identity,
        processing=StrengthProcessingIdentity(
            registered_operation=VBT_INPUT_OPERATION,
            filtering_status=StrengthProcessingComponentStatus.NONE_DECLARED,
            smoothing=StrengthProcessingStep(StrengthProcessingComponentStatus.NONE_DECLARED),
            resampling=StrengthProcessingStep(StrengthProcessingComponentStatus.NONE_DECLARED),
            processing_state=processing_state,
        ),
        version=VersionIdentity(
            processing_method=VBT_INPUT_OPERATION,
            method_registry_version=STRENGTH_REGISTRY_VERSION,
            software_version="synthetic-vbt-source-1",
            hardware_firmware=device,
        ),
    )
    artifact = source_artifact_for_vbt_series(series)
    acquisition = AcquisitionRecord(
        acquisition_id=acquisition_id,
        device=device,
        source_artifact_id=artifact_id,
        sensor_channel="bar",
        sampling=acquisition_identity.sampling,
    )
    return create_vbt_velocity_evidence(
        observation_id=observation_id,
        result_id=InstanceIdentifier("result", f"vbt-source-{index}"),
        context=_context(trial="vbt-trial"),
        identity=identity,
        series=series,
        source_artifact=artifact,
        acquisition=acquisition,
        set_id=InstanceIdentifier("set", set_key),
        rep_id=InstanceIdentifier("rep", f"rep-{index}"),
        rep_index=index,
        external_load=load,
    )


def _vbt_metric(index: int, *, load: float = 50.0, velocity: float = 0.5) -> VBTMetricResult:
    evidence = _vbt_evidence(index, load_kg=load, velocity=velocity)
    phase = _phase(evidence)
    evidence = evidence.with_phase(phase)
    result = calculate_mean_concentric_velocity(evidence)
    assert isinstance(result, VBTMetricResult)
    return result


def _measured_assessment(
    evidence: VBTVelocitySeriesEvidence,
) -> MeasuredOneRepMaxAssessmentEvidence:
    artifact_id = InstanceIdentifier("artifact", f"measured-1rm-artifact-{evidence.rep_index}")
    artifact = SourceArtifact(
        artifact_id=artifact_id,
        content_digest=f"sha256:measured-1rm-{evidence.rep_index}",
        media_type="application/vnd.synthetic.measured-1rm",
        immutable=True,
    )
    acquisition = replace(evidence.acquisition, source_artifact_id=artifact_id)
    identity = replace(
        evidence.identity,
        semantic=replace(
            evidence.identity.semantic,
            construct=STRENGTH_MAXIMUM_STRENGTH_CONSTRUCT,
            measurand=VBT_MEASURED_1RM_MEASURAND,
            metric_definition=VBT_MEASURED_1RM_METRIC,
        ),
        acquisition=replace(evidence.identity.acquisition, raw_artifact=artifact_id),
        processing=replace(
            evidence.identity.processing,
            registered_operation=VBT_DIRECT_1RM_ASSESSMENT_OPERATION,
            method_parameters=(),
        ),
        version=replace(
            evidence.identity.version,
            processing_method=VBT_DIRECT_1RM_ASSESSMENT_OPERATION,
        ),
    )
    observation = replace(
        evidence.observation,
        identity=identity,
        result=MeasurementResult(
            result_id=InstanceIdentifier("result", f"measured-1rm-{evidence.rep_index}"),
            value=ScalarValue(evidence.external_load.value),
            unit=KILOGRAM,
            classification=ScientificClassification(ValueOrigin.SOURCE_REPORTED, ()),
            quality=MeasurementQuality(),
            uncertainty=UncertaintyMetadata(),
            status=ResultStatus.VALID,
        ),
        provenance=replace(
            evidence.observation.provenance,
            source_artifacts=(artifact,),
            acquisitions=(acquisition,),
            processing_runs=(),
            lineage_edges=(
                LineageEdge(
                    artifact_id.qualified,
                    acquisition.acquisition_id.qualified,
                    LineageRelation.ACQUIRED_AS,
                ),
                LineageEdge(
                    acquisition.acquisition_id.qualified,
                    evidence.observation.observation_id.qualified,
                    LineageRelation.PRODUCED,
                ),
            ),
        ),
    )
    protocol_identity = evidence.identity.semantic.protocol_identity
    assert protocol_identity is not None
    return MeasuredOneRepMaxAssessmentEvidence(
        source_observation=observation,
        source_artifact=artifact,
        source_acquisition=acquisition,
        protocol_identity=protocol_identity,
        assessment_method=VBT_DIRECT_1RM_ASSESSMENT_OPERATION,
        maximality_declaration=VBT_DIRECT_1RM_MAXIMALITY_DECLARATION,
        selection_rule=VBT_MEASURED_1RM_SELECTION_RULE,
        attempt_id=InstanceIdentifier("attempt", f"direct-1rm-{evidence.rep_index}"),
        measured_load=evidence.external_load,
        source_value_origin=ValueOrigin.SOURCE_REPORTED,
    )


def test_imtp_analytic_metrics_and_roundtrip() -> None:
    force, baseline, onset, _ = _imtp_fixture()
    assert isinstance(baseline, IMTPBaseline)
    assert isinstance(onset, IMTPOnset)
    peak = calculate_imtp_peak_force(force, onset)
    force_100 = calculate_imtp_force_at_time(force, onset, 100)
    impulse = calculate_imtp_impulse(
        force, onset, 100, force_quantity=IMTPForceQuantity.NET_FORCE_ABOVE_BASELINE
    )
    rfd = calculate_imtp_rfd(force, onset, 100)
    assert isinstance(peak, IMTPMetricResult)
    assert isinstance(force_100, IMTPMetricResult)
    assert isinstance(impulse, IMTPMetricResult)
    assert isinstance(rfd, IMTPMetricResult)
    assert peak.value_n == 510.0
    assert force_100.value_n == 310.0
    assert impulse.value_n == pytest.approx(11.0)
    assert rfd.value_n == pytest.approx(2000.0)
    restored = from_canonical_json(canonical_json(rfd), IMTPMetricResult)
    assert restored == rfd
    assert canonical_hash(restored) == canonical_hash(rfd)


def test_imtp_onset_threshold_and_source_context_are_bound() -> None:
    force, baseline, onset, _ = _imtp_fixture()
    assert onset.parameters.sigma_multiplier == 5.0
    wrong_baseline = replace(
        baseline,
        source_context=replace(
            baseline.source_context, session_id=InstanceIdentifier("session", "other")
        ),
    )
    refused = detect_imtp_onset(force, wrong_baseline, onset.parameters)
    assert not isinstance(refused, IMTPOnset)
    assert "THRESHOLD_PARAMETER_MISSING" in refused.reason_codes


def test_imtp_exact_time_refuses_nearest_sample_and_method_substitution() -> None:
    force, _, onset, _ = _imtp_fixture()
    refused = calculate_imtp_force_at_time(force, onset, 75)
    assert not isinstance(refused, IMTPMetricResult)
    assert "UNKNOWN_INTERPOLATION" in refused.reason_codes
    assert IMTP_ONSET_BASELINE_FIVE_SD_METHOD.identifier.key == "imtp-baseline-plus-five-sd-v1"


def test_imtp_gross_and_net_force_are_distinct() -> None:
    force, _, onset, _ = _imtp_fixture()
    gross = calculate_imtp_peak_force(force, onset)
    net = calculate_imtp_peak_force(
        force, onset, force_quantity=IMTPForceQuantity.NET_FORCE_ABOVE_BASELINE
    )
    assert isinstance(gross, IMTPMetricResult)
    assert isinstance(net, IMTPMetricResult)
    assert gross.value_n != net.value_n
    assert (
        gross.observation.identity.semantic.measurand != net.observation.identity.semantic.measurand
    )


def test_imtp_normalization_requires_typed_body_mass() -> None:
    force, _, onset, identity = _imtp_fixture()
    peak = calculate_imtp_peak_force(force, onset)
    assert isinstance(peak, IMTPMetricResult)
    artifact_id = InstanceIdentifier("artifact", "body-mass")
    acquisition_id = InstanceIdentifier("acquisition", "body-mass")
    device = _ref("device", "scale", "Synthetic scale")
    body_identity = MeasurementIdentity(
        identity_id=ScientificIdentifier(
            "synthetic-res66", "measurement-identity", "body-mass", "1"
        ),
        semantic=SemanticIdentity(
            construct=IMTP_CONSTRUCT,
            test_family=IMTP_TEST_FAMILY,
            protocol=IMTP_PROTOCOL_V1,
            measurand=BODY_MASS_MEASURAND,
            metric_definition=BODY_MASS_METRIC,
        ),
        acquisition=AcquisitionIdentity(
            device=device,
            raw_artifact=artifact_id,
            sensor_channel="scale",
            sampling=SamplingCharacteristics(10.0, ("scale",)),
        ),
        processing=ProcessingIdentity(registered_operation=IMTP_INPUT_OPERATION),
        version=VersionIdentity(IMTP_INPUT_OPERATION, "1", "synthetic", device),
    )
    artifact = SourceArtifact(artifact_id, "sha256:body-mass", "application/octet-stream")
    acquisition = AcquisitionRecord(
        acquisition_id, device, artifact_id, "scale", SamplingCharacteristics(10.0, ("scale",))
    )
    provenance = Provenance(
        InstanceIdentifier("provenance", "body-mass"),
        (artifact,),
        (acquisition,),
        (),
        (
            LineageEdge(
                artifact_id.qualified, acquisition_id.qualified, LineageRelation.ACQUIRED_AS
            ),
            LineageEdge(
                acquisition_id.qualified, "observation:body-mass", LineageRelation.PRODUCED
            ),
        ),
    )
    body_observation = ScientificMeasurementObservation(
        InstanceIdentifier("observation", "body-mass"),
        force.observation.context,
        body_identity,
        MeasurementResult(
            InstanceIdentifier("result", "body-mass"),
            ScalarValue(80.0),
            KILOGRAM,
            ScientificClassification(ValueOrigin.DIRECT_MEASUREMENT, ()),
            MeasurementQuality(),
            UncertaintyMetadata(),
            ResultStatus.VALID,
        ),
        provenance,
    )
    normalized = normalize_imtp_force(peak, IMTPBodyMassObservation(body_observation))
    assert not isinstance(normalized, RefusalResult)
    assert normalized.observation.result.unit == NEWTON_PER_KILOGRAM
    assert isinstance(normalized.observation.result.value, ScalarValue)
    assert normalized.observation.result.value.value == pytest.approx(6.375)
    assert identity.acquisition != body_identity.acquisition


def test_imtp_trial_aggregation_requires_explicit_rule() -> None:
    force, _, onset, _ = _imtp_fixture()
    peak = calculate_imtp_peak_force(force, onset)
    assert isinstance(peak, IMTPMetricResult)
    qualification = qualify_imtp_trial(peak, status=IMTPTrialQualificationStatus.EXCLUDED)
    assert not isinstance(qualification, RefusalResult)
    ineligible = IMTPTrialMetricInput(peak, qualification)
    selected = aggregate_imtp_metric_results((ineligible,), IMTPTrialSelectionRule.BEST_PEAK_FORCE)
    assert isinstance(selected, RefusalResult)
    assert "TRIAL_NOT_ELIGIBLE" in selected.reason_codes


def test_imtp_trial_aggregation_replays_explicit_eligible_trials() -> None:
    force_a, _, onset_a, _ = _imtp_fixture("-a")
    force_b, _, onset_b, _ = _imtp_fixture("-b")
    peak_a = calculate_imtp_peak_force(force_a, onset_a)
    peak_b = calculate_imtp_peak_force(force_b, onset_b)
    assert isinstance(peak_a, IMTPMetricResult)
    assert isinstance(peak_b, IMTPMetricResult)
    qualification_a = qualify_imtp_trial(peak_a)
    qualification_b = qualify_imtp_trial(peak_b)
    assert not isinstance(qualification_a, RefusalResult)
    assert not isinstance(qualification_b, RefusalResult)
    aggregated = aggregate_imtp_metric_results(
        (
            IMTPTrialMetricInput(peak_a, qualification_a),
            IMTPTrialMetricInput(peak_b, qualification_b),
        ),
        IMTPTrialSelectionRule.MEAN_ALL_ELIGIBLE,
    )
    assert not isinstance(aggregated, RefusalResult)
    assert aggregated.value == pytest.approx(510.0)


def test_vbt_time_mean_peak_and_mpv_noncollapse() -> None:
    evidence = _vbt_evidence(1, velocity=0.2)
    bound = evidence.with_phase(_phase(evidence))
    mean = calculate_mean_concentric_velocity(bound)
    peak = calculate_peak_velocity(bound)
    mpv = refuse_mean_propulsive_velocity(bound)
    assert isinstance(mean, VBTMetricResult)
    assert isinstance(peak, VBTMetricResult)
    assert mean.value_m_per_s == pytest.approx(1 / 3)
    assert peak.value_m_per_s == pytest.approx(0.4)
    assert (
        mean.observation.identity.semantic.metric_definition
        != peak.observation.identity.semantic.metric_definition
    )
    assert VBT_MEAN_PROPULSIVE_VELOCITY_METRIC.identifier.key == "mean-propulsive-velocity"
    assert "NO_REGISTERED_OPERATION" in mpv.reason_codes


def test_vbt_scalar_without_phase_is_refused() -> None:
    refused = calculate_mean_concentric_velocity(_vbt_evidence(1))
    assert isinstance(refused, RefusalResult)
    assert "PHASE_SOURCE_MISMATCH" in refused.reason_codes


def test_vbt_source_digest_tampering_and_output_value_tampering_are_blocked() -> None:
    evidence = _vbt_evidence(1)
    with pytest.raises(ValueError, match="digest"):
        VBTVelocitySeriesEvidence(
            observation=evidence.observation,
            identity=evidence.identity,
            series=replace(evidence.series, samples=(9.0, 9.0, 9.0, 9.0, 9.0)),
            source_artifact=evidence.source_artifact,
            acquisition=evidence.acquisition,
            set_id=evidence.set_id,
            rep_id=evidence.rep_id,
            rep_index=evidence.rep_index,
            external_load=evidence.external_load,
            source_series_digest=evidence.source_series_digest,
        )
    result = calculate_mean_concentric_velocity(evidence.with_phase(_phase(evidence)))
    assert isinstance(result, VBTMetricResult)
    forged_observation = replace(
        result.observation,
        result=replace(result.observation.result, value=ScalarValue(99.0)),
    )
    with pytest.raises(ValueError, match="reproduce"):
        VBTMetricResult(forged_observation, result.metric, result.evidence, result.phase)


def test_vbt_phase_provenance_and_context_rebinding_are_blocked() -> None:
    evidence = _vbt_evidence(1)
    phase = _phase(evidence)
    with pytest.raises(ValueError, match="processing run"):
        evidence.with_phase(
            replace(
                phase,
                boundary_parameters=(MetadataEntry("changed", True),),
            )
        )
    result = calculate_mean_concentric_velocity(evidence.with_phase(phase))
    assert isinstance(result, VBTMetricResult)
    forged = replace(
        result.observation,
        context=replace(
            result.observation.context, session_id=InstanceIdentifier("session", "other")
        ),
    )
    with pytest.raises(ValueError, match="context"):
        VBTMetricResult(forged, result.metric, result.evidence, result.phase)


def test_vbt_measured_and_estimated_1rm_origins_are_invariant() -> None:
    evidence = _vbt_evidence(1, load_kg=50.0, velocity=1.2)
    evidence = evidence.with_phase(_phase(evidence))
    refused_success = build_measured_1rm(VBTSuccessfulRepetition(evidence, True))
    assert isinstance(refused_success, RefusalResult)
    measured = build_measured_1rm(_measured_assessment(evidence))
    assert isinstance(measured, MeasuredOneRepMax)
    assert measured.value_kg == 50.0
    assert measured.observation.identity.semantic.metric_definition == VBT_MEASURED_1RM_METRIC
    points = tuple(
        _vbt_metric(index, load=load, velocity=velocity)
        for index, (load, velocity) in enumerate(((50.0, 1.2), (100.0, 0.7), (150.0, 0.2)), 1)
    )
    model = fit_load_velocity_model(points)
    assert not isinstance(model, RefusalResult)
    estimate = estimate_1rm_from_load_velocity_model(
        model, VBT_SMITH_BENCH_GENERAL_TERMINAL_VELOCITY_017
    )
    assert isinstance(estimate, EstimatedOneRepMax)
    assert estimate.value_kg == pytest.approx(166.33333333333331)
    assert estimate.observation.result.classification.value_origin.value == "MODEL_ESTIMATE"
    refused = refuse_estimated_1rm_as_measured(
        observation_ids=(estimate.observation.observation_id,)
    )
    assert "MODEL_ESTIMATE" in refused.missing_information[0]


def test_vbt_model_missing_terminal_or_wrong_protocol_refuses_estimation() -> None:
    points = tuple(
        _vbt_metric(index, load=load, velocity=velocity)
        for index, (load, velocity) in enumerate(((50.0, 1.2), (100.0, 0.7)), 1)
    )
    model = fit_load_velocity_model(points)
    assert not isinstance(model, RefusalResult)
    refused = estimate_1rm_from_load_velocity_model(model)
    assert isinstance(refused, RefusalResult)
    assert "UNKNOWN_THRESHOLD" in refused.reason_codes


def test_vbt_velocity_loss_reference_rules_and_fatigue_refusal() -> None:
    results = tuple(
        _vbt_metric(index, velocity=velocity) for index, velocity in enumerate((1.0, 0.8, 0.6), 1)
    )
    first = calculate_velocity_loss(
        results, VBTVelocityLossReference.FIRST_REPETITION, current_rep_index=3
    )
    fastest = calculate_velocity_loss(
        results, VBTVelocityLossReference.FASTEST_REPETITION, current_rep_index=3
    )
    previous = calculate_velocity_loss(
        results, VBTVelocityLossReference.BEST_PREVIOUS_REPETITION, current_rep_index=3
    )
    assert not isinstance(first, RefusalResult)
    assert not isinstance(fastest, RefusalResult)
    assert not isinstance(previous, RefusalResult)
    assert first.value_percent == pytest.approx(
        100.0 * (1.1333333333333333 - 0.7333333333333334) / 1.1333333333333333
    )
    assert fastest.value_percent == first.value_percent
    assert previous.value_percent == first.value_percent
    assert "NO_REGISTERED_OPERATION" in refuse_velocity_loss_as_fatigue().reason_codes


def test_vbt_velocity_loss_cross_set_and_metric_mismatch_refuse() -> None:
    results = tuple(
        _vbt_metric(index, velocity=velocity) for index, velocity in enumerate((1.0, 0.8), 1)
    )
    other_evidence = _vbt_evidence(3, velocity=0.6, set_key="other")
    other = calculate_mean_concentric_velocity(other_evidence.with_phase(_phase(other_evidence)))
    assert isinstance(other, VBTMetricResult)
    refused = calculate_velocity_loss(
        (*results, other),
        VBTVelocityLossReference.FIRST_REPETITION,
        current_rep_index=3,
    )
    assert isinstance(refused, RefusalResult)
    assert "PROCESSING_LINEAGE_UNRESOLVED" in refused.reason_codes


def test_vbt_fixed_load_comparability_is_fail_closed() -> None:
    left = _vbt_metric(1, load=50.0, velocity=0.8)
    right = _vbt_metric(2, load=50.0, velocity=0.7)
    comparable = compare_vbt_fixed_load(left, right)
    assert comparable.state is ComparabilityState.COMPARABLE
    other_evidence = _vbt_evidence(3, load_kg=50.0, velocity=0.7, device_key="other-lpt")
    device_result = calculate_mean_concentric_velocity(
        other_evidence.with_phase(_phase(other_evidence))
    )
    assert isinstance(device_result, VBTMetricResult)
    bridged = compare_vbt_fixed_load(left, device_result)
    assert bridged.state is ComparabilityState.BRIDGE_VALIDATION_REQUIRED
    wrong_load = _vbt_metric(4, load=60.0, velocity=0.7)
    not_comparable = compare_vbt_fixed_load(left, wrong_load)
    assert not_comparable.state is ComparabilityState.NOT_COMPARABLE


def test_vbt_roundtrip_preserves_exact_result_identity() -> None:
    result = _vbt_metric(1)
    restored = from_canonical_json(canonical_json(result), VBTMetricResult)
    assert restored == result
    assert canonical_hash(restored) == canonical_hash(result)


def test_imtp_source_device_sampling_and_processing_tampering_refuse() -> None:
    force, _, onset, _ = _imtp_fixture()
    other_device = _ref("device", "other-platform", "Other platform")
    bad_device_force = replace(
        force,
        acquisition=replace(force.acquisition, device=other_device),
    )
    refused_device = calculate_imtp_peak_force(bad_device_force, onset)
    assert isinstance(refused_device, RefusalResult)
    bad_sampling_force = replace(
        force,
        acquisition=replace(
            force.acquisition,
            sampling=SamplingCharacteristics(500.0, ("force",)),
        ),
    )
    refused_sampling = calculate_imtp_peak_force(bad_sampling_force, onset)
    assert isinstance(refused_sampling, RefusalResult)
    filter_ref = _ref("filter", "low-pass", "Synthetic low-pass")
    bad_processing = replace(
        force.identity.processing,
        filtering=(filter_ref,),
        filtering_status=StrengthProcessingComponentStatus.REGISTERED,
    )
    refused_processing = calculate_imtp_peak_force(
        replace(force, identity=replace(force.identity, processing=bad_processing)), onset
    )
    assert isinstance(refused_processing, RefusalResult)


def test_imtp_onset_and_interval_identity_tampering_is_blocked() -> None:
    force, _, onset, _ = _imtp_fixture()
    forged_onset = replace(
        onset,
        baseline_mean_force_n=101.0,
        threshold_n=101.0,
    )
    refused_onset = calculate_imtp_peak_force(force, forged_onset)
    assert isinstance(refused_onset, RefusalResult)
    impulse = calculate_imtp_impulse(force, onset, 100)
    assert isinstance(impulse, IMTPMetricResult)
    forged_support = replace(
        impulse.support,
        end_index=impulse.support.end_index - 1,
        end_time_s=impulse.support.end_time_s - 0.001,
    )
    with pytest.raises(ValueError, match="registered window"):
        IMTPMetricResult(
            impulse.observation,
            impulse.metric,
            impulse.force_input,
            impulse.onset,
            forged_support,
            impulse.force_quantity,
            impulse.window_ms,
        )


def test_imtp_arbitrary_normalization_denominator_and_method_mutation_are_blocked() -> None:
    force, _, onset, _ = _imtp_fixture()
    peak = calculate_imtp_peak_force(force, onset)
    assert isinstance(peak, IMTPMetricResult)
    refused = normalize_imtp_force(peak, object())  # type: ignore[arg-type]
    assert isinstance(refused, RefusalResult)
    bad_processing = replace(
        peak.observation.identity.processing,
        registered_operation=IMTP_ENDPOINT_RFD_METHOD,
    )
    bad_identity = replace(peak.observation.identity, processing=bad_processing)
    with pytest.raises(ValueError, match="operation"):
        IMTPMetricResult(
            replace(peak.observation, identity=bad_identity),
            peak.metric,
            peak.force_input,
            peak.onset,
            peak.support,
            peak.force_quantity,
            peak.window_ms,
        )


def test_vbt_source_sampling_and_phase_support_tampering_are_blocked() -> None:
    evidence = _vbt_evidence(1)
    bad_acquisition = replace(
        evidence.acquisition,
        sampling=SamplingCharacteristics(200.0, ("bar",)),
    )
    with pytest.raises(ValueError, match="sampling"):
        VBTVelocitySeriesEvidence(
            evidence.observation,
            evidence.identity,
            evidence.series,
            evidence.source_artifact,
            bad_acquisition,
            evidence.set_id,
            evidence.rep_id,
            evidence.rep_index,
            evidence.external_load,
            evidence.source_series_digest,
        )
    phase = _phase(evidence)
    with pytest.raises(ValueError, match="processing run|upstream source evidence"):
        replace(
            phase,
            start_index=1,
            start_time_s=0.01,
        )


def test_vbt_metric_relabel_and_processing_provenance_mutation_are_blocked() -> None:
    evidence = _vbt_evidence(1)
    result = calculate_mean_concentric_velocity(evidence.with_phase(_phase(evidence)))
    assert isinstance(result, VBTMetricResult)
    relabelled_semantic = replace(
        result.observation.identity.semantic,
        metric_definition=VBT_PEAK_VELOCITY_METRIC,
    )
    with pytest.raises(ValueError, match="metric"):
        VBTMetricResult(
            replace(
                result.observation,
                identity=replace(result.observation.identity, semantic=relabelled_semantic),
            ),
            result.metric,
            result.evidence,
            result.phase,
        )
    changed_parameters = (
        *result.observation.identity.processing.method_parameters[:-1],
        MetadataEntry("changed", True),
    )
    changed_processing = replace(
        result.observation.identity.processing,
        method_parameters=changed_parameters,
    )
    with pytest.raises(ValueError, match="processing run|parameters"):
        VBTMetricResult(
            replace(
                result.observation,
                identity=replace(result.observation.identity, processing=changed_processing),
            ),
            result.metric,
            result.evidence,
            result.phase,
        )


def test_vbt_fixed_load_phase_support_and_cross_metric_mismatches_fail_closed() -> None:
    left = _vbt_metric(1, load=50.0)
    evidence = _vbt_evidence(2, load_kg=50.0)
    phase = _phase(evidence, boundary_parameters=(MetadataEntry("boundary_variant", "different"),))
    assert isinstance(phase, VBTConcentricPhase)
    right = calculate_mean_concentric_velocity(evidence.with_phase(phase))
    assert isinstance(right, VBTMetricResult)
    support_result = compare_vbt_fixed_load(left, right)
    assert support_result.state is ComparabilityState.NOT_COMPARABLE
    peak = calculate_peak_velocity(evidence.with_phase(_phase(evidence)))
    assert isinstance(peak, VBTMetricResult)
    loss = calculate_velocity_loss(
        (left, peak),
        VBTVelocityLossReference.FIRST_REPETITION,
        current=peak,
    )
    assert isinstance(loss, RefusalResult)


def test_load_velocity_model_coefficients_and_estimated_origin_cannot_be_forged() -> None:
    points = tuple(
        _vbt_metric(index, load=load, velocity=velocity)
        for index, (load, velocity) in enumerate(((50.0, 1.2), (100.0, 0.7)), 1)
    )
    model = fit_load_velocity_model(points)
    assert not isinstance(model, RefusalResult)
    with pytest.raises(ValueError, match="coefficients"):
        replace(model, slope_m_per_s_per_kg=-0.5)
    estimate = estimate_1rm_from_load_velocity_model(
        model, VBT_SMITH_BENCH_GENERAL_TERMINAL_VELOCITY_017
    )
    assert isinstance(estimate, EstimatedOneRepMax)
    forged_result = replace(
        estimate.observation.result,
        classification=ScientificClassification(ValueOrigin.DIRECT_MEASUREMENT, ()),
    )
    with pytest.raises(ValueError, match="model estimate|MODEL_ESTIMATE"):
        EstimatedOneRepMax(
            replace(estimate.observation, result=forged_result),
            model,
            estimate.terminal_velocity_assumption,
        )


def test_vbt_raw_indices_cannot_create_phase_authority() -> None:
    refused = qualify_vbt_concentric_phase(_vbt_evidence(1), start_index=0, end_index=3)
    assert isinstance(refused, RefusalResult)
    assert "PHASE_SOURCE_MISMATCH" in refused.reason_codes


def test_vbt_qualified_phase_has_source_digest_and_trial_free_metrics_are_not_used() -> None:
    evidence = _vbt_evidence(1)
    phase = _phase(evidence)
    assert phase.source_evidence is not None
    assert phase.source_series_digest == evidence.source_series_digest
    result = calculate_mean_concentric_velocity(evidence.with_phase(phase))
    assert isinstance(result, VBTMetricResult)


@pytest.mark.parametrize(
    "mutation",
    ("start_index", "end_index", "boundary_method", "set_id", "rep_id", "load", "digest"),
)
def test_vbt_phase_source_identity_mutations_are_blocked(mutation: str) -> None:
    evidence = _vbt_evidence(1)
    phase = _phase(evidence)
    if mutation == "start_index":
        with pytest.raises(ValueError, match="upstream source evidence"):
            replace(phase, start_index=1, start_time_s=0.01)
        return
    source = phase.source_evidence
    assert source is not None
    changes: dict[str, dict[str, Any]] = {
        "end_index": {"end_index": 2, "end_time_s": 0.03},
        "boundary_method": {"boundary_method": VBT_PHASE_SOURCE_PROCESSING_METHOD},
        "set_id": {"set_id": InstanceIdentifier("set", "other-set")},
        "rep_id": {"rep_id": InstanceIdentifier("rep", "other-rep")},
        "load": {"external_load": replace(evidence.external_load, value=60.0)},
        "digest": {"source_series_digest": "sha256:tampered"},
    }
    with pytest.raises(ValueError, match="parameters|source|provenance"):
        replace(source, **changes[mutation])


def test_measured_1rm_direct_assessment_binds_source_origin_and_maximality() -> None:
    evidence = _vbt_evidence(1, load_kg=50.0, velocity=1.2)
    assessment = _measured_assessment(evidence)
    measured = build_measured_1rm(assessment)
    assert isinstance(measured, MeasuredOneRepMax)
    assert measured.observation.result.classification.value_origin is ValueOrigin.SOURCE_REPORTED
    assert measured.assessment.attempt_id.instance_type == "attempt"


def test_measured_1rm_qualification_tampering_is_blocked() -> None:
    force, _, onset, _ = _imtp_fixture()
    peak = calculate_imtp_peak_force(force, onset)
    assert isinstance(peak, IMTPMetricResult)
    qualification = qualify_imtp_trial(peak)
    assert not isinstance(qualification, RefusalResult)
    with pytest.raises(ValueError, match="decision fields"):
        replace(qualification, reason_codes=("TAMPERED",))


def test_imtp_peak_support_is_source_end_and_free_end_index_is_blocked() -> None:
    force, _, onset, _ = _imtp_fixture()
    peak = calculate_imtp_peak_force(force, onset)
    assert isinstance(peak, IMTPMetricResult)
    assert peak.support.end_index == len(force.series.samples) - 1
    refused = calculate_imtp_peak_force(force, onset, trial_end_index=onset.sample_index)
    assert isinstance(refused, RefusalResult)


@pytest.mark.parametrize("dwell", (2, 5))
def test_imtp_v1_rejects_alternate_dwell_rules(dwell: int) -> None:
    with pytest.raises(ValueError, match="exactly one dwell"):
        IMTPOnsetParameters(5.0, IMTPThresholdDirection.ABOVE_THRESHOLD, dwell, 4)


def test_imtp_multisource_context_is_deterministic_and_trial_free() -> None:
    force_a, _, onset_a, _ = _imtp_fixture("-ctx-a")
    force_b, _, onset_b, _ = _imtp_fixture("-ctx-b")
    peak_a = calculate_imtp_peak_force(force_a, onset_a)
    peak_b = calculate_imtp_peak_force(force_b, onset_b)
    assert isinstance(peak_a, IMTPMetricResult)
    assert isinstance(peak_b, IMTPMetricResult)
    qualification_a = qualify_imtp_trial(peak_a)
    qualification_b = qualify_imtp_trial(peak_b)
    assert not isinstance(qualification_a, RefusalResult)
    assert not isinstance(qualification_b, RefusalResult)
    aggregated = aggregate_imtp_metric_results(
        (
            IMTPTrialMetricInput(peak_a, qualification_a),
            IMTPTrialMetricInput(peak_b, qualification_b),
        ),
        IMTPTrialSelectionRule.MEAN_ALL_ELIGIBLE,
    )
    assert not isinstance(aggregated, RefusalResult)
    assert aggregated.observation.context.trial_id is None
    assert aggregated.observation.context != peak_a.observation.context
    assert aggregated.observation.context.context_id.value.startswith("res66-multisource:")


def test_load_velocity_model_and_estimate_use_full_calibration_context() -> None:
    points = tuple(
        _vbt_metric(index, load=load, velocity=velocity)
        for index, (load, velocity) in enumerate(((50.0, 1.2), (100.0, 0.7)), 1)
    )
    model = fit_load_velocity_model(points)
    assert not isinstance(model, RefusalResult)
    assert model.analysis_context.trial_id is None
    assert model.analysis_context != points[0].observation.context
    estimate = estimate_1rm_from_load_velocity_model(
        model, VBT_SMITH_BENCH_GENERAL_TERMINAL_VELOCITY_017
    )
    assert isinstance(estimate, EstimatedOneRepMax)
    assert estimate.observation.context == model.analysis_context


@pytest.mark.parametrize(
    "field",
    ("filtering", "smoothing", "resampling", "software", "processing_state", "method_version"),
)
def test_load_velocity_processing_identity_mismatch_is_blocked(field: str) -> None:
    first = _vbt_metric(1, load=50.0, velocity=1.2)
    second_evidence = _vbt_evidence(
        2,
        load_kg=100.0,
        velocity=0.7,
        processing_state=(
            StrengthProcessingState.DEVICE_PROCESSED
            if field == "processing_state"
            else StrengthProcessingState.PROVIDER_PROCESSED
        ),
    )
    if field == "filtering":
        filter_ref = _ref("filter", "low-pass", "Synthetic low-pass")
        processing = replace(
            second_evidence.identity.processing,
            filtering=(filter_ref,),
            filtering_status=StrengthProcessingComponentStatus.REGISTERED,
        )
        second_evidence = replace(
            second_evidence,
            identity=replace(second_evidence.identity, processing=processing),
            observation=replace(
                second_evidence.observation,
                identity=replace(second_evidence.identity, processing=processing),
            ),
        )
    elif field == "smoothing":
        processing = replace(
            second_evidence.identity.processing,
            smoothing=StrengthProcessingStep(
                StrengthProcessingComponentStatus.REGISTERED,
                method=_ref("smoothing", "moving-average", "Synthetic smoothing"),
            ),
        )
        second_evidence = replace(
            second_evidence,
            identity=replace(second_evidence.identity, processing=processing),
            observation=replace(
                second_evidence.observation,
                identity=replace(second_evidence.identity, processing=processing),
            ),
        )
    elif field == "resampling":
        processing = replace(
            second_evidence.identity.processing,
            resampling=StrengthProcessingStep(
                StrengthProcessingComponentStatus.REGISTERED,
                method=_ref("resampling", "linear", "Synthetic resampling"),
            ),
        )
        second_evidence = replace(
            second_evidence,
            identity=replace(second_evidence.identity, processing=processing),
            observation=replace(
                second_evidence.observation,
                identity=replace(second_evidence.identity, processing=processing),
            ),
        )
    elif field == "software":
        version = replace(second_evidence.identity.version, software_version="other-software")
        second_evidence = replace(
            second_evidence,
            identity=replace(second_evidence.identity, version=version),
            observation=replace(
                second_evidence.observation,
                identity=replace(second_evidence.identity, version=version),
            ),
        )
    elif field == "method_version":
        version = replace(second_evidence.identity.version, method_registry_version="2.0.0")
        second_evidence = replace(
            second_evidence,
            identity=replace(second_evidence.identity, version=version),
            observation=replace(
                second_evidence.observation,
                identity=replace(second_evidence.identity, version=version),
            ),
        )
    second = calculate_mean_concentric_velocity(second_evidence.with_phase(_phase(second_evidence)))
    assert isinstance(second, VBTMetricResult)
    refused = fit_load_velocity_model((first, second))
    assert isinstance(refused, RefusalResult)


def test_load_velocity_phase_boundary_method_mismatch_is_blocked() -> None:
    evidence = _vbt_evidence(2, load_kg=100.0, velocity=0.7)
    source = _phase(evidence).source_evidence
    assert source is not None
    with pytest.raises(ValueError, match="parameters|source|provenance"):
        replace(source, boundary_method=VBT_PHASE_SOURCE_PROCESSING_METHOD)


def test_terminal_velocity_generic_assumption_is_not_constructible() -> None:
    with pytest.raises(ValueError, match="applicability"):
        TerminalVelocityAssumption(
            VBT_SMITH_BENCH_GENERAL_TERMINAL_VELOCITY_017.reference,
            0.17,
            "generic Smith-machine bench press",
        )


def test_terminal_velocity_wrong_metric_and_pause_contracts_are_blocked() -> None:
    with pytest.raises(ValueError, match="velocity metric"):
        replace(
            VBT_SMITH_BENCH_GENERAL_TERMINAL_VELOCITY_017,
            velocity_metric=VBTMetric.PEAK_VELOCITY,
        )
    with pytest.raises(ValueError, match="pause"):
        replace(
            VBT_SMITH_BENCH_GENERAL_TERMINAL_VELOCITY_017,
            pause_semantics=StrengthProtocolAttribute("pause_semantics", "unresolved"),
        )
