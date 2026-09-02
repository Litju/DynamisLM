from __future__ import annotations

import datetime as datetime_module
import json
from dataclasses import FrozenInstanceError, replace

import pytest

from dynamislm import (
    SERIALIZATION_VERSION,
    AcquisitionRecord,
    InstanceIdentifier,
    MeasurementIdentity,
    MetadataEntry,
    ObservationContext,
    ProcessingIdentity,
    RegistryReference,
    SamplingCharacteristics,
    ScalarValue,
    ScientificIdentifier,
    ScientificMeasurementObservation,
    SerializationError,
    SignConvention,
    SourceArtifact,
    StructuredOutputReference,
    UncertaintyMetadata,
    UncertaintyStatus,
    UnitReference,
    ValueOrigin,
    VersionIdentity,
    canonical_hash,
    canonical_json,
    from_canonical_json,
)
from dynamislm.comparability import (
    ComparabilityReasonCode,
    ComparabilityState,
)
from dynamislm.measurement.cmj import (
    CMJ_BILATERAL_TOTAL_VERTICAL_FORCE_SUM,
    CMJ_EVENT_COMPARABILITY_RULE,
    CMJ_FORCE_PLATFORM_PLUS_GRAVITY_EXTERNAL_FORCE_MODEL,
    CMJ_LANDING_ABSOLUTE_FORCE_METHOD,
    CMJ_LANDING_CONTACT_REGAIN_EVENT_DEFINITION,
    CMJ_MOVEMENT_ONSET_BASELINE_SD_METHOD,
    CMJ_MOVEMENT_ONSET_EVENT_DEFINITION,
    CMJ_SUPPORTED_SYSTEM_CONSTRUCT,
    CMJ_SYSTEM_WEIGHT_MEAN_FORCE,
    CMJ_SYSTEM_WEIGHT_OPERATION,
    CMJ_TAKEOFF_ABSOLUTE_FORCE_METHOD,
    CMJ_TAKEOFF_CONTACT_LOSS_EVENT_DEFINITION,
    CMJ_TEST_FAMILY,
    KILONEWTON,
    NEWTON,
    RES44_DECISION_MASS_METROLOGY,
    RES44_SOFTWARE_VERSION,
    STANDARD_GRAVITY,
    AcquisitionArrangement,
    ArtifactStatus,
    ChannelRole,
    CMJAcquisitionIdentity,
    CMJChannelIdentity,
    CMJComparabilityRequest,
    CMJComputation,
    CMJEventDetectorMethod,
    CMJEventDetectorParameters,
    CMJEventLabel,
    CMJEventOccurrence,
    CMJEventQCCode,
    CMJEventThresholdFamily,
    CMJForceInput,
    CMJIntegrationInterval,
    CMJIntegrationIntervalKind,
    CMJMeasurementIdentity,
    CMJMechanicalSystemContract,
    CMJMechanicsQuantity,
    CMJProtocolAttribute,
    CMJProtocolIdentity,
    CMJSemanticIdentity,
    CMJSourceArtifact,
    CMJThresholdDirection,
    CMJValidationCode,
    CMJValidationResult,
    CombinationLineage,
    CombinationLineageKind,
    DisplacementOrigin,
    ExplicitTimebase,
    GravityReference,
    GravityReferenceType,
    InitialVelocityCondition,
    NetVerticalForceResult,
    NetVerticalImpulseResult,
    PhysicalSystemMassResult,
    ProcessedVerticalForceSignal,
    QualifiedZeroVelocityReference,
    RawVerticalForceSignal,
    ReferenceMetadata,
    ReferenceState,
    RegularTimebase,
    SignalProcessingState,
    SignalTimebase,
    StandardGravityMassEquivalentResult,
    SupportedSystemComAccelerationResult,
    SupportedSystemComRelativeDisplacementResult,
    SupportedSystemComVelocityResult,
    SystemWeightResult,
    TimebaseIdentity,
    TimebaseKind,
    TotalSupportedForceResult,
    WeighingSegment,
    assess_cmj_acquisition_comparability,
    compare_cmj_derived_measurements,
    compare_cmj_events,
    compare_cmj_mechanics,
    construct_total_supported_vertical_force,
    create_cmj_raw_observation,
    derive_body_mass,
    derive_net_vertical_force,
    derive_physical_system_mass,
    derive_standard_gravity_mass_equivalent,
    derive_supported_system_com_acceleration,
    derive_supported_system_com_relative_vertical_displacement,
    derive_supported_system_com_velocity,
    detect_landing,
    detect_movement_onset,
    detect_takeoff,
    estimate_system_weight,
    integrate_net_vertical_impulse,
    refusal_for_cmj_comparability,
    refusal_for_cmj_derived_comparability,
    refusal_for_cmj_event_comparability,
    refusal_for_cmj_mechanics_comparability,
    refusal_for_cmj_validation,
    refuse_unregistered_computation,
    source_artifact_for_signal,
    validate_cmj_acquisition,
    validate_cmj_event_order,
    validate_raw_vertical_force_signal,
)
from dynamislm.provenance import LineageEdge, LineageRelation, Provenance
from dynamislm.refusal import RefusalClass, RefusalReasonCode, RefusalResult, RefusalStatus

UTC = datetime_module.UTC


def _reference(object_type: str, key: str, label: str | None = None) -> RegistryReference:
    return RegistryReference(
        identifier=ScientificIdentifier("synthetic", object_type, key, "1.0.0"),
        display_label=label or key,
    )


def _protocol(*, external_loading: str = "none") -> CMJProtocolIdentity:
    return CMJProtocolIdentity(
        reference=_reference("protocol", "cmj-standard", "Synthetic CMJ protocol"),
        arm_use_constraint=CMJProtocolAttribute("arm_use", "restricted"),
        external_loading=CMJProtocolAttribute("external_load", external_loading),
        movement_instruction=CMJProtocolAttribute("instruction", "synthetic fixture"),
        start_posture=CMJProtocolAttribute("start_posture", "upright"),
    )


def _fixture(
    suffix: str,
    *,
    device_key: str = "synthetic-platform",
    arrangement: AcquisitionArrangement = AcquisitionArrangement.BILATERAL_SEPARATE,
    processing_state: SignalProcessingState = SignalProcessingState.RAW_ACQUIRED,
    protocol_present: bool = True,
    external_loading: str = "none",
    axis_key: str = "vertical",
    frame_key: str = "platform",
    sign_key: str = "upward-positive",
    unit: UnitReference = NEWTON,
    timebase_kind: TimebaseKind = TimebaseKind.REGULAR,
    declared_sample_rate: float | None = 1000.0,
    software_version: str | None = "synthetic-acquisition-1.0",
    calibration_state: ReferenceState = ReferenceState.NOT_PROVIDED,
    zeroing_state: ReferenceState = ReferenceState.NOT_PROVIDED,
    combination_lineage: CombinationLineage | None = None,
) -> tuple[CMJMeasurementIdentity, RawVerticalForceSignal, CMJSourceArtifact]:
    protocol = _protocol(external_loading=external_loading) if protocol_present else None
    protocol_reference = protocol.reference if protocol is not None else None
    semantic = CMJSemanticIdentity(
        construct=_reference("construct", "force-platform-vertical-force"),
        test_family=CMJ_TEST_FAMILY,
        protocol=protocol_reference,
        measurand=_reference("measurand", "vertical-force", "Vertical force"),
        metric_definition=_reference("metric", "vertical-force", "vertical force"),
        protocol_identity=protocol,
    )
    channels: tuple[CMJChannelIdentity, ...]
    if arrangement is AcquisitionArrangement.BILATERAL_SEPARATE:
        channels = (
            CMJChannelIdentity("left", ChannelRole.LEFT_FORCE_PLATFORM),
            CMJChannelIdentity("right", ChannelRole.RIGHT_FORCE_PLATFORM),
        )
        selected_channel = channels[0]
    elif arrangement is AcquisitionArrangement.BILATERAL_PRECOMBINED:
        channels = (CMJChannelIdentity("combined", ChannelRole.PRECOMBINED_VERTICAL_FORCE),)
        selected_channel = channels[0]
        if combination_lineage is None:
            combination_lineage = CombinationLineage(CombinationLineageKind.DIRECT_COMBINED_OUTPUT)
    elif arrangement is AcquisitionArrangement.SINGLE_PLATFORM:
        channels = (CMJChannelIdentity("single", ChannelRole.SINGLE_FORCE_PLATFORM),)
        selected_channel = channels[0]
    else:
        channels = ()
        selected_channel = None
    sample_rate = declared_sample_rate if timebase_kind is TimebaseKind.REGULAR else None
    acquisition_id = InstanceIdentifier("acquisition", f"synthetic-{suffix}")
    artifact_id = InstanceIdentifier("artifact", f"synthetic-{suffix}")
    axis = _reference("axis", axis_key, "Vertical axis")
    frame = _reference("reference-frame", frame_key, "Platform frame")
    sign = SignConvention(_reference("sign-convention", sign_key), "upward")
    device = _reference("device", device_key, "Synthetic force platform")
    firmware = _reference("firmware", "synthetic-firmware", "Synthetic firmware")
    acquisition = CMJAcquisitionIdentity(
        device=device,
        raw_artifact=artifact_id,
        sensor_channel=selected_channel.channel_id if selected_channel is not None else None,
        sampling=SamplingCharacteristics(
            sample_rate, tuple(channel.channel_id for channel in channels)
        ),
        calibration_reference=None,
        hardware_firmware=firmware,
        measuring_system=_reference("measuring-system", "synthetic-system"),
        arrangement=arrangement,
        acquisition_instance_id=acquisition_id,
        channel=selected_channel,
        available_channels=channels,
        physical_axis=axis,
        reference_frame=frame,
        unit=unit,
        sign_convention=sign,
        timebase=TimebaseIdentity(timebase_kind, declared_sample_rate),
        acquisition_software_version=software_version,
        acquisition_timestamp=datetime_module.datetime(2026, 1, 1, tzinfo=UTC),
        calibration=ReferenceMetadata(calibration_state),
        zeroing=ReferenceMetadata(zeroing_state),
        processing_state=processing_state,
        combination_lineage=combination_lineage,
    )
    identity = CMJMeasurementIdentity(
        identity_id=ScientificIdentifier(
            "synthetic", "measurement-identity", f"cmj-{suffix}", "1.0.0"
        ),
        semantic=semantic,
        acquisition=acquisition,
        processing=ProcessingIdentity(),
        version=VersionIdentity(
            processing_method=_reference("processing-method", "raw-acquisition"),
            method_registry_version="1.0.0",
            software_version="synthetic-dynamislm-1.0",
            hardware_firmware=firmware,
        ),
    )
    if timebase_kind is TimebaseKind.REGULAR:
        signal_timebase: SignalTimebase = RegularTimebase(declared_sample_rate or 1000.0)
    else:
        signal_timebase = ExplicitTimebase((0.0, 0.001, 0.002))
    signal = RawVerticalForceSignal(
        signal_id=InstanceIdentifier("signal", f"synthetic-{suffix}"),
        source_artifact_id=artifact_id,
        acquisition_id=acquisition_id,
        acquisition_identity_id=identity.identity_id,
        samples=(100.0, 101.0, 102.0),
        timebase=signal_timebase,
        channel_id=selected_channel.channel_id if selected_channel is not None else None,
        unit=unit,
        physical_axis=axis,
        reference_frame=frame,
        sign_convention=sign,
        processing_state=processing_state,
    )
    return identity, signal, source_artifact_for_signal(signal)


def _acquisition_record(
    identity: CMJMeasurementIdentity,
    signal: RawVerticalForceSignal,
    artifact: CMJSourceArtifact,
) -> AcquisitionRecord:
    device = identity.acquisition.device
    assert device is not None
    return AcquisitionRecord(
        acquisition_id=signal.acquisition_id,
        device=device,
        source_artifact_id=artifact.artifact_id,
        sensor_channel=signal.channel_id,
        sampling=identity.acquisition.sampling,
        calibration_reference=identity.acquisition.calibration_reference,
        hardware_firmware=identity.acquisition.hardware_firmware,
    )


def _context(suffix: str, athlete: str = "athlete-1") -> ObservationContext:
    return ObservationContext(
        context_id=InstanceIdentifier("context", suffix),
        athlete_id=InstanceIdentifier("athlete", athlete),
        session_id=InstanceIdentifier("session", f"session-{suffix}"),
        test_instance_id=InstanceIdentifier("test-instance", f"test-{suffix}"),
        trial_id=InstanceIdentifier("trial", f"trial-{suffix}"),
        observed_at=datetime_module.datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
        population_context="synthetic fixture; not biological validation",
    )


def _observation(
    suffix: str = "one",
) -> ScientificMeasurementObservation:
    identity, signal, artifact = _fixture(suffix)
    return create_cmj_raw_observation(
        observation_id=InstanceIdentifier("observation", suffix),
        result_id=InstanceIdentifier("result", suffix),
        context=_context(suffix),
        identity=identity,
        signal=signal,
        source_artifact=artifact,
        acquisition=_acquisition_record(identity, signal, artifact),
        recorded_at=datetime_module.datetime(2026, 1, 1, 12, 1, tzinfo=UTC),
    )


def _codes(result: CMJValidationResult) -> set[CMJValidationCode]:
    return {issue.code for issue in result.issues}


def test_same_display_label_can_have_different_cmj_acquisition_identities() -> None:
    first, _, _ = _fixture("first", device_key="platform-a")
    second, _, _ = _fixture("second", device_key="platform-b")

    assert first.display_label == second.display_label == "vertical force"
    assert first.identity_id != second.identity_id
    assert first.acquisition.device != second.acquisition.device
    assert canonical_hash(first) != canonical_hash(second)


def test_context_changes_do_not_mutate_measurement_identity() -> None:
    observation = _observation("context-a")
    changed_context = replace(
        observation.context, athlete_id=InstanceIdentifier("athlete", "athlete-2")
    )
    changed = replace(observation, context=changed_context)

    assert changed.context != observation.context
    assert changed.identity == observation.identity
    assert canonical_hash(changed.identity) == canonical_hash(observation.identity)
    assert "athlete-2" not in canonical_json(observation.identity)


def test_bilateral_separate_and_precombined_are_distinct_acquisition_identities() -> None:
    separate, separate_signal, separate_artifact = _fixture("separate")
    combined, combined_signal, combined_artifact = _fixture(
        "combined", arrangement=AcquisitionArrangement.BILATERAL_PRECOMBINED
    )

    assert separate.acquisition.arrangement is AcquisitionArrangement.BILATERAL_SEPARATE
    assert combined.acquisition.arrangement is AcquisitionArrangement.BILATERAL_PRECOMBINED
    assert separate != combined
    assert validate_cmj_acquisition(separate, separate_signal, separate_artifact).is_valid
    assert validate_cmj_acquisition(combined, combined_signal, combined_artifact).is_valid


def test_identity_signal_and_artifact_roundtrip_preserve_scientific_semantics() -> None:
    identity, signal, artifact = _fixture("serialization")

    identity_json = canonical_json(identity)
    signal_json = canonical_json(signal)
    assert '"sample_rate_hz":1000.0' in identity_json
    assert '"reference_frame"' in identity_json
    assert '"sign_convention"' in identity_json
    assert '"key":"newton"' in identity_json
    assert '"timebase"' in signal_json
    assert '"processing_state":"RAW_ACQUIRED"' in signal_json
    assert from_canonical_json(identity_json, MeasurementIdentity) == identity
    assert from_canonical_json(signal_json, RawVerticalForceSignal) == signal
    assert from_canonical_json(canonical_json(artifact), SourceArtifact) == artifact


def test_raw_artifact_hash_is_stable_and_immutable() -> None:
    _, signal, artifact = _fixture("hash")
    repeated = source_artifact_for_signal(signal)
    changed_signal = replace(signal, samples=(100.0, 101.0, 103.0))

    assert artifact == repeated
    assert artifact.content_digest == signal.canonical_content_digest()
    assert artifact.acquisition_id == signal.acquisition_id
    assert artifact.content_digest != changed_signal.canonical_content_digest()
    with pytest.raises(FrozenInstanceError):
        artifact.content_digest = "sha256:changed"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        signal.samples = (1.0,)  # type: ignore[misc]


def test_raw_observation_keeps_signal_outside_result_and_preserves_provenance() -> None:
    observation = _observation("provenance")
    value = observation.result.value

    assert observation.provenance.processing_runs == ()
    assert isinstance(observation.provenance, Provenance)
    assert isinstance(observation.provenance.source_artifacts[0], CMJSourceArtifact)
    assert observation.provenance.lineage_edges[0].relation is LineageRelation.ACQUIRED_AS
    assert isinstance(value, StructuredOutputReference)
    assert value.artifact_id == observation.provenance.source_artifacts[0].artifact_id
    assert not hasattr(value, "samples")
    assert observation.result.classification.value_origin is ValueOrigin.DIRECT_MEASUREMENT
    assert observation.result.classification.scientific_roles == ()
    restored = from_canonical_json(canonical_json(observation), ScientificMeasurementObservation)
    assert restored == observation


def test_device_processed_signal_cannot_masquerade_as_raw_acquired() -> None:
    identity, signal, artifact = _fixture("processed")
    processed_signal = replace(signal, processing_state=SignalProcessingState.DEVICE_PROCESSED)
    processed_identity = replace(
        identity,
        acquisition=replace(
            identity.acquisition, processing_state=SignalProcessingState.DEVICE_PROCESSED
        ),
    )

    assert signal.is_raw_acquired
    assert not processed_signal.is_raw_acquired
    assert "DEVICE_PROCESSED" in canonical_json(processed_signal)
    assert validate_cmj_acquisition(processed_identity, processed_signal, artifact).is_valid
    with pytest.raises(ValueError, match="RAW_ACQUIRED"):
        create_cmj_raw_observation(
            observation_id=InstanceIdentifier("observation", "processed"),
            result_id=InstanceIdentifier("result", "processed"),
            context=_context("processed"),
            identity=processed_identity,
            signal=processed_signal,
            source_artifact=artifact,
            acquisition=_acquisition_record(processed_identity, processed_signal, artifact),
        )


def test_unknown_processing_state_survives_and_blocks_valid_registration() -> None:
    identity, signal, artifact = _fixture(
        "unknown-processing", processing_state=SignalProcessingState.UNKNOWN
    )
    result = validate_cmj_acquisition(identity, signal, artifact)

    assert result.status.value == "INSUFFICIENT_INFORMATION"
    assert CMJValidationCode.PROCESSING_STATE_UNKNOWN in _codes(result)
    refusal = refusal_for_cmj_validation(result)
    assert refusal is not None
    assert refusal.refusal_class is RefusalClass.IDENTITY_UNRESOLVED


def test_missing_protocol_identity_is_detected_without_a_default() -> None:
    identity, signal, artifact = _fixture("missing-protocol", protocol_present=False)
    result = validate_cmj_acquisition(identity, signal, artifact)

    assert identity.semantic.protocol is None
    assert identity.semantic.protocol_identity is None
    assert CMJValidationCode.MISSING_PROTOCOL_IDENTITY in _codes(result)
    refusal = refusal_for_cmj_validation(result)
    assert refusal is not None
    assert refusal.refusal_class is RefusalClass.IDENTITY_UNRESOLVED
    assert RefusalReasonCode.PROTOCOL_IDENTITY_MISSING in refusal.reason_codes


def test_missing_material_acquisition_metadata_is_explicitly_insufficient() -> None:
    identity, signal, artifact = _fixture("missing-metadata")
    missing_acquisition = replace(
        identity.acquisition,
        device=None,
        measuring_system=None,
        acquisition_instance_id=None,
        channel=None,
        physical_axis=None,
        reference_frame=None,
        unit=None,
        sign_convention=None,
        timebase=None,
        acquisition_software_version=None,
    )
    missing_identity = replace(identity, acquisition=missing_acquisition)
    missing_signal = replace(
        signal,
        channel_id=None,
        timebase=None,
        unit=None,
        physical_axis=None,
        reference_frame=None,
        sign_convention=None,
    )
    result = validate_cmj_acquisition(
        missing_identity, missing_signal, source_artifact_for_signal(missing_signal)
    )
    codes = _codes(result)

    assert result.status.value == "INSUFFICIENT_INFORMATION"
    assert {
        CMJValidationCode.MISSING_DEVICE_IDENTITY,
        CMJValidationCode.MISSING_MEASURING_SYSTEM,
        CMJValidationCode.MISSING_CHANNEL,
        CMJValidationCode.MISSING_AXIS,
        CMJValidationCode.MISSING_REFERENCE_FRAME,
        CMJValidationCode.MISSING_UNIT,
        CMJValidationCode.MISSING_SIGN_CONVENTION,
        CMJValidationCode.MISSING_TIMEBASE,
        CMJValidationCode.MISSING_ACQUISITION_INSTANCE,
        CMJValidationCode.MISSING_ACQUISITION_SOFTWARE,
    } <= codes


def test_axis_frame_sign_and_unit_mismatches_are_not_silently_harmonized() -> None:
    identity, signal, artifact = _fixture("semantic-mismatch")
    mismatched_signal = replace(
        signal,
        unit=KILONEWTON,
        physical_axis=_reference("axis", "horizontal"),
        reference_frame=_reference("reference-frame", "world"),
        sign_convention=SignConvention(
            _reference("sign-convention", "downward-positive"), "downward"
        ),
    )
    result = validate_cmj_acquisition(identity, mismatched_signal, artifact)

    assert result.status.value == "INVALID"
    assert CMJValidationCode.SIGNAL_SEMANTICS_MISMATCH in _codes(result)


def test_unregistered_cross_device_equivalence_requires_a_bridge() -> None:
    left_identity, _, _ = _fixture("bridge-left", device_key="platform-a")
    right_identity, _, _ = _fixture("bridge-right", device_key="platform-b")
    request = CMJComparabilityRequest(
        request_id=InstanceIdentifier("comparability-request", "bridge"),
        left_observation_id=InstanceIdentifier("observation", "left"),
        right_observation_id=InstanceIdentifier("observation", "right"),
        left_identity=left_identity,
        right_identity=right_identity,
        claim="compare force-platform observations",
    )
    result = assess_cmj_acquisition_comparability(request)

    assert result.state is ComparabilityState.BRIDGE_VALIDATION_REQUIRED
    assert ComparabilityReasonCode.BRIDGE_NOT_REGISTERED in result.reason_codes
    assert ComparabilityReasonCode.DEVICE_MISMATCH in result.reason_codes


def test_comparability_detects_protocol_arrangement_axis_frame_sign_and_timebase_changes() -> None:
    baseline, _, _ = _fixture("comparison-baseline")
    changed, _, _ = _fixture(
        "comparison-changed",
        arrangement=AcquisitionArrangement.BILATERAL_PRECOMBINED,
        axis_key="horizontal",
        frame_key="world",
        sign_key="downward-positive",
        timebase_kind=TimebaseKind.EXPLICIT,
        declared_sample_rate=None,
    )
    changed_semantic = replace(
        changed.semantic,
        protocol=_reference("protocol", "cmj-alternate", "Alternate CMJ protocol"),
        protocol_identity=CMJProtocolIdentity(
            _reference("protocol", "cmj-alternate", "Alternate CMJ protocol")
        ),
    )
    changed = replace(changed, semantic=changed_semantic)
    request = CMJComparabilityRequest(
        request_id=InstanceIdentifier("comparability-request", "dimensions"),
        left_observation_id=InstanceIdentifier("observation", "baseline"),
        right_observation_id=InstanceIdentifier("observation", "changed"),
        left_identity=baseline,
        right_identity=changed,
        claim="compare acquisition identities",
    )
    result = assess_cmj_acquisition_comparability(request)

    assert result.state is ComparabilityState.BRIDGE_VALIDATION_REQUIRED
    assert {
        ComparabilityReasonCode.PROTOCOL_MISMATCH,
        ComparabilityReasonCode.ARRANGEMENT_MISMATCH,
        ComparabilityReasonCode.AXIS_MISMATCH,
        ComparabilityReasonCode.REFERENCE_FRAME_MISMATCH,
        ComparabilityReasonCode.SIGN_CONVENTION_MISMATCH,
        ComparabilityReasonCode.SAMPLE_OR_TIMEBASE_MISMATCH,
    } <= set(result.reason_codes)


def test_missing_comparability_metadata_is_not_promoted_to_comparable() -> None:
    complete, _, _ = _fixture("complete")
    incomplete, _, _ = _fixture("incomplete")
    incomplete = replace(
        incomplete,
        acquisition=replace(
            incomplete.acquisition,
            device=None,
            timebase=None,
            processing_state=SignalProcessingState.UNKNOWN,
        ),
    )
    request = CMJComparabilityRequest(
        request_id=InstanceIdentifier("comparability-request", "insufficient"),
        left_observation_id=InstanceIdentifier("observation", "complete"),
        right_observation_id=InstanceIdentifier("observation", "incomplete"),
        left_identity=complete,
        right_identity=incomplete,
        claim="compare observations",
    )
    result = assess_cmj_acquisition_comparability(request)

    assert result.state is ComparabilityState.INSUFFICIENT_INFORMATION
    assert result.missing_information
    assert ComparabilityReasonCode.MISSING_METADATA in result.reason_codes


@pytest.mark.parametrize("computation", tuple(CMJComputation))
def test_unregistered_downstream_computations_are_refused(
    computation: CMJComputation,
) -> None:
    refusal = refuse_unregistered_computation(
        computation,
        observation_ids=(InstanceIdentifier("observation", "one"),),
    )

    assert refusal.status is RefusalStatus.PARTIALLY_REFUSED
    assert refusal.refusal_class is RefusalClass.COMPUTATION_NOT_REGISTERED
    assert refusal.reason_codes == (RefusalReasonCode.NO_REGISTERED_OPERATION,)
    assert len(refusal.observation_ids) == 1


def test_blocked_comparison_still_allows_safe_independent_descriptions() -> None:
    left_identity, _, _ = _fixture("safe-left", device_key="platform-a")
    right_identity, _, _ = _fixture("safe-right", device_key="platform-b")
    request = __import__(
        "dynamislm.measurement.cmj", fromlist=["CMJComparabilityRequest"]
    ).CMJComparabilityRequest(
        request_id=InstanceIdentifier("comparability-request", "safe"),
        left_observation_id=InstanceIdentifier("observation", "left"),
        right_observation_id=InstanceIdentifier("observation", "right"),
        left_identity=left_identity,
        right_identity=right_identity,
        claim="the athlete improved",
    )
    comparison = assess_cmj_acquisition_comparability(request)
    refusal = refusal_for_cmj_comparability(
        comparison,
        blocked_claim="the athlete improved",
        observation_ids=(request.left_observation_id, request.right_observation_id),
    )

    assert refusal is not None
    assert refusal.refusal_class is RefusalClass.COMPARABILITY_UNESTABLISHED
    assert refusal.status is RefusalStatus.PARTIALLY_REFUSED
    assert refusal.observation_ids == (
        request.left_observation_id,
        request.right_observation_id,
    )
    assert refusal.what_can_still_be_safely_described


def test_timebase_validation_rejects_duplicates_nonmonotonic_times_and_rate_mismatch() -> None:
    identity, signal, artifact = _fixture("timebase")
    duplicate = replace(signal, timebase=ExplicitTimebase((0.0, 0.001, 0.001)))
    nonmonotonic = replace(signal, timebase=ExplicitTimebase((0.0, 0.002, 0.001)))
    duplicate_result = validate_raw_vertical_force_signal(
        duplicate, source_artifact_for_signal(duplicate)
    )
    nonmonotonic_result = validate_raw_vertical_force_signal(
        nonmonotonic, source_artifact_for_signal(nonmonotonic)
    )
    rate_mismatch = replace(signal, timebase=RegularTimebase(500.0))
    rate_result = validate_cmj_acquisition(
        identity, rate_mismatch, source_artifact_for_signal(rate_mismatch)
    )

    assert CMJValidationCode.DUPLICATE_TIME in _codes(duplicate_result)
    assert CMJValidationCode.NON_MONOTONIC_TIME in _codes(nonmonotonic_result)
    assert CMJValidationCode.DECLARED_SAMPLE_RATE_MISMATCH in _codes(rate_result)
    assert artifact.content_digest == signal.canonical_content_digest()


def test_artifact_verification_and_integrity_failures_are_explicit() -> None:
    _, signal, artifact = _fixture("artifact-validation")
    unverified = replace(artifact, status=ArtifactStatus.UNVERIFIED)
    wrong_digest = replace(artifact, content_digest="sha256:" + "0" * 64)
    generic = SourceArtifact(
        artifact_id=artifact.artifact_id,
        content_digest=artifact.content_digest,
        media_type=artifact.media_type,
    )

    unverified_result = validate_raw_vertical_force_signal(signal, unverified)
    wrong_result = validate_raw_vertical_force_signal(signal, wrong_digest)
    generic_result = validate_raw_vertical_force_signal(signal, generic)

    assert CMJValidationCode.ARTIFACT_HASH_UNVERIFIED in _codes(unverified_result)
    assert CMJValidationCode.ARTIFACT_HASH_MISMATCH in _codes(wrong_result)
    assert CMJValidationCode.ARTIFACT_METADATA_INSUFFICIENT in _codes(generic_result)


def test_combination_lineage_distinguishes_direct_vendor_and_system_paths() -> None:
    direct, direct_signal, direct_artifact = _fixture(
        "direct-combined", arrangement=AcquisitionArrangement.BILATERAL_PRECOMBINED
    )
    vendor_lineage = CombinationLineage(
        CombinationLineageKind.VENDOR_COMBINED_OUTPUT,
        source_channels=("left", "right"),
    )
    vendor, vendor_signal, vendor_artifact = _fixture(
        "vendor-combined",
        arrangement=AcquisitionArrangement.BILATERAL_PRECOMBINED,
        processing_state=SignalProcessingState.DEVICE_PROCESSED,
        combination_lineage=vendor_lineage,
    )
    invalid_vendor = replace(
        vendor,
        acquisition=replace(
            vendor.acquisition, processing_state=SignalProcessingState.RAW_ACQUIRED
        ),
    )

    assert validate_cmj_acquisition(direct, direct_signal, direct_artifact).is_valid
    assert validate_cmj_acquisition(vendor, vendor_signal, vendor_artifact).is_valid
    invalid_result = validate_cmj_acquisition(invalid_vendor, vendor_signal, vendor_artifact)
    assert CMJValidationCode.COMBINATION_STATE_MISMATCH in _codes(invalid_result)
    assert direct.acquisition.combination_lineage != vendor.acquisition.combination_lineage


def test_deterministic_serialization_and_hash_are_stable_after_roundtrip() -> None:
    identity, signal, artifact = _fixture("determinism")

    assert canonical_json(identity) == canonical_json(identity)
    assert canonical_hash(identity) == canonical_hash(identity)
    restored = from_canonical_json(canonical_json(signal), RawVerticalForceSignal)
    restored_artifact = from_canonical_json(canonical_json(artifact), CMJSourceArtifact)
    assert canonical_json(restored) == canonical_json(signal)
    assert canonical_hash(restored_artifact) == canonical_hash(artifact)


def test_p1d_public_surface_stops_at_core_events() -> None:
    import dynamislm.measurement.cmj as cmj

    assert not hasattr(cmj, "calculate_body_mass")
    assert not hasattr(cmj, "calculate_impulse")
    assert not hasattr(cmj, "estimate_jump_height")
    assert hasattr(cmj, "detect_movement_onset")
    assert hasattr(cmj, "detect_takeoff")
    assert hasattr(cmj, "detect_landing")


def _cmj_input(
    suffix: str,
    *,
    arrangement: AcquisitionArrangement = AcquisitionArrangement.SINGLE_PLATFORM,
    context: ObservationContext | None = None,
    observation_suffix: str | None = None,
    external_loading: str = "none",
) -> CMJForceInput:
    identity, signal, artifact = _fixture(
        suffix,
        arrangement=arrangement,
        external_loading=external_loading,
    )
    observation_id = observation_suffix or suffix
    observation = create_cmj_raw_observation(
        observation_id=InstanceIdentifier("observation", observation_id),
        result_id=InstanceIdentifier("result", observation_id),
        context=context or _context(suffix),
        identity=identity,
        signal=signal,
        source_artifact=artifact,
        acquisition=_acquisition_record(identity, signal, artifact),
        recorded_at=datetime_module.datetime(2026, 1, 1, 12, 1, tzinfo=UTC),
    )
    return CMJForceInput(
        observation=observation,
        identity=identity,
        signal=signal,
        source_artifact=artifact,
        acquisition=_acquisition_record(identity, signal, artifact),
    )


def _event_input(
    suffix: str,
    samples: tuple[float, ...],
    *,
    timebase: SignalTimebase | None = None,
) -> CMJForceInput:
    timebase_kind = (
        TimebaseKind.EXPLICIT if isinstance(timebase, ExplicitTimebase) else TimebaseKind.REGULAR
    )
    identity, signal, artifact = _fixture(
        suffix,
        arrangement=AcquisitionArrangement.SINGLE_PLATFORM,
        timebase_kind=timebase_kind,
        declared_sample_rate=1000.0 if timebase_kind is TimebaseKind.REGULAR else None,
    )
    event_signal = replace(
        signal,
        samples=samples,
        timebase=timebase or RegularTimebase(1000.0),
    )
    event_artifact = source_artifact_for_signal(event_signal)
    event_observation = create_cmj_raw_observation(
        observation_id=InstanceIdentifier("observation", suffix),
        result_id=InstanceIdentifier("result", suffix),
        context=_context(suffix),
        identity=identity,
        signal=event_signal,
        source_artifact=event_artifact,
        acquisition=_acquisition_record(identity, event_signal, event_artifact),
        recorded_at=datetime_module.datetime(2026, 1, 1, 12, 1, tzinfo=UTC),
    )
    return CMJForceInput(
        observation=event_observation,
        identity=identity,
        signal=event_signal,
        source_artifact=event_artifact,
        acquisition=_acquisition_record(identity, event_signal, event_artifact),
    )


def _event_trace() -> tuple[float, ...]:
    return (
        100.0,
        101.0,
        99.0,
        100.0,
        100.0,
        95.0,
        95.0,
        100.0,
        100.0,
        100.0,
        5.0,
        5.0,
        0.0,
        0.0,
        0.0,
        100.0,
        101.0,
        102.0,
        102.0,
        100.0,
        100.0,
    )


def _event_baseline(
    force: CMJForceInput,
) -> SystemWeightResult:
    segment = WeighingSegment(
        source_signal_id=force.signal.signal_id,
        source_artifact_id=force.source_artifact.artifact_id,
        source_measurement_identity_id=force.identity.identity_id,
        start_index=0,
        end_index=5,
    )
    baseline = estimate_system_weight(force, segment)
    assert isinstance(baseline, SystemWeightResult)
    return baseline


def _onset_parameters(
    baseline: SystemWeightResult,
    *,
    search_start_index: int = 5,
    dwell_samples: int = 2,
) -> CMJEventDetectorParameters:
    return CMJEventDetectorParameters(
        baseline_observation_id=baseline.observation.observation_id,
        baseline_segment=baseline.segment,
        baseline_mean_force_n=baseline.qc.mean_force_n,
        baseline_standard_deviation_n=baseline.qc.standard_deviation_n,
        sigma_multiplier=1.0,
        direction=CMJThresholdDirection.BELOW_THRESHOLD,
        dwell_samples=dwell_samples,
        search_start_index=search_start_index,
    )


def _absolute_parameters(
    threshold_n: float,
    direction: CMJThresholdDirection,
    *,
    dwell_samples: int = 2,
    search_start_index: int | None = 9,
) -> CMJEventDetectorParameters:
    return CMJEventDetectorParameters(
        threshold_n=threshold_n,
        direction=direction,
        dwell_samples=dwell_samples,
        search_start_index=search_start_index,
    )


def _bilateral_inputs() -> tuple[CMJForceInput, CMJForceInput]:
    context = _context("bilateral")
    left = _cmj_input(
        "bilateral-left",
        arrangement=AcquisitionArrangement.BILATERAL_SEPARATE,
        context=context,
        observation_suffix="bilateral-left",
    )
    right_identity, right_raw_signal, right_artifact = _fixture(
        "bilateral-right",
        arrangement=AcquisitionArrangement.BILATERAL_SEPARATE,
    )
    right_identity = replace(
        right_identity,
        identity_id=ScientificIdentifier(
            "synthetic", "measurement-identity", "cmj-bilateral-right", "1.0.0"
        ),
        acquisition=replace(
            right_identity.acquisition,
            channel=CMJChannelIdentity("right", ChannelRole.RIGHT_FORCE_PLATFORM),
            sensor_channel="right",
        ),
    )
    right_signal = replace(
        right_raw_signal,
        acquisition_identity_id=right_identity.identity_id,
        channel_id="right",
        samples=(400.0, 401.0, 402.0),
    )
    right_artifact = source_artifact_for_signal(right_signal)
    right_observation = create_cmj_raw_observation(
        observation_id=InstanceIdentifier("observation", "bilateral-right"),
        result_id=InstanceIdentifier("result", "bilateral-right"),
        context=context,
        identity=right_identity,
        signal=right_signal,
        source_artifact=right_artifact,
        acquisition=_acquisition_record(right_identity, right_signal, right_artifact),
        recorded_at=datetime_module.datetime(2026, 1, 1, 12, 1, tzinfo=UTC),
    )
    assert isinstance(left.signal, RawVerticalForceSignal)
    left_signal = replace(left.signal, samples=(300.0, 301.0, 302.0))
    left_artifact = source_artifact_for_signal(left_signal)
    left_identity = replace(
        left.identity,
        acquisition=replace(left.identity.acquisition, raw_artifact=left_artifact.artifact_id),
    )
    left_signal = replace(
        left_signal,
        acquisition_identity_id=left_identity.identity_id,
        source_artifact_id=left_artifact.artifact_id,
    )
    left_observation = create_cmj_raw_observation(
        observation_id=InstanceIdentifier("observation", "bilateral-left"),
        result_id=InstanceIdentifier("result", "bilateral-left"),
        context=context,
        identity=left_identity,
        signal=left_signal,
        source_artifact=left_artifact,
        acquisition=_acquisition_record(left_identity, left_signal, left_artifact),
        recorded_at=datetime_module.datetime(2026, 1, 1, 12, 1, tzinfo=UTC),
    )
    return (
        CMJForceInput(
            observation=left_observation,
            identity=left_identity,
            signal=left_signal,
            source_artifact=left_artifact,
            acquisition=_acquisition_record(left_identity, left_signal, left_artifact),
        ),
        CMJForceInput(
            observation=right_observation,
            identity=right_identity,
            signal=right_signal,
            source_artifact=right_artifact,
            acquisition=_acquisition_record(right_identity, right_signal, right_artifact),
        ),
    )


def _rebind_raw_input(
    source: CMJForceInput,
    *,
    suffix: str,
    unit: UnitReference | None = None,
    axis: RegistryReference | None = None,
    frame: RegistryReference | None = None,
    sign: SignConvention | None = None,
    timebase: SignalTimebase | None = None,
    clock_reference: RegistryReference | None = None,
    samples: tuple[float, ...] | None = None,
) -> CMJForceInput:
    assert isinstance(source.signal, RawVerticalForceSignal)
    raw_signal = replace(
        source.signal,
        unit=unit if unit is not None else source.signal.unit,
        physical_axis=axis if axis is not None else source.signal.physical_axis,
        reference_frame=frame if frame is not None else source.signal.reference_frame,
        sign_convention=sign if sign is not None else source.signal.sign_convention,
        timebase=timebase if timebase is not None else source.signal.timebase,
        samples=samples if samples is not None else source.signal.samples,
    )
    artifact = source_artifact_for_signal(raw_signal)
    raw_identity = replace(
        source.identity,
        acquisition=replace(
            source.identity.acquisition,
            raw_artifact=artifact.artifact_id,
            sampling=SamplingCharacteristics(
                (
                    raw_signal.timebase.sample_rate_hz
                    if isinstance(raw_signal.timebase, RegularTimebase)
                    else None
                ),
                (
                    source.identity.acquisition.sampling.channels
                    if source.identity.acquisition.sampling is not None
                    else ((raw_signal.channel_id,) if raw_signal.channel_id is not None else ())
                ),
                (
                    source.identity.acquisition.sampling.sample_format
                    if source.identity.acquisition.sampling is not None
                    else None
                ),
            ),
            unit=raw_signal.unit,
            physical_axis=raw_signal.physical_axis,
            reference_frame=raw_signal.reference_frame,
            sign_convention=raw_signal.sign_convention,
            timebase=(
                TimebaseIdentity(
                    TimebaseKind.REGULAR,
                    raw_signal.timebase.sample_rate_hz,
                    clock_reference=clock_reference,
                )
                if isinstance(raw_signal.timebase, RegularTimebase)
                else TimebaseIdentity(
                    TimebaseKind.EXPLICIT,
                    None,
                    clock_reference=clock_reference,
                )
            ),
        ),
    )
    raw_signal = replace(
        raw_signal,
        acquisition_identity_id=raw_identity.identity_id,
        source_artifact_id=artifact.artifact_id,
    )
    acquisition = _acquisition_record(raw_identity, raw_signal, artifact)
    observation = create_cmj_raw_observation(
        observation_id=InstanceIdentifier("observation", suffix),
        result_id=InstanceIdentifier("result", suffix),
        context=source.observation.context,
        identity=raw_identity,
        signal=raw_signal,
        source_artifact=artifact,
        acquisition=acquisition,
    )
    return CMJForceInput(
        observation=observation,
        identity=raw_identity,
        signal=raw_signal,
        source_artifact=artifact,
        acquisition=acquisition,
    )


def test_res35_bilateral_sum_is_explicit_processed_and_two_source() -> None:
    left, right = _bilateral_inputs()
    original_left = left.signal.samples
    result = construct_total_supported_vertical_force(left, right)

    assert isinstance(result, TotalSupportedForceResult)
    assert isinstance(result.signal, ProcessedVerticalForceSignal)
    assert result.signal.samples == (700.0, 702.0, 704.0)
    assert result.signal.processing_state is SignalProcessingState.SYSTEM_PROCESSED
    assert result.signal.source_signal_ids == (left.signal.signal_id, right.signal.signal_id)
    assert result.signal.source_artifact_ids == (
        left.source_artifact.artifact_id,
        right.source_artifact.artifact_id,
    )
    assert left.signal.samples == original_left
    assert (
        result.observation.result.classification.value_origin
        is ValueOrigin.DERIVED_MECHANICAL_QUANTITY
    )
    assert result.observation.result.classification.scientific_roles == ()
    processing = result.observation.provenance.processing_runs[-1]
    assert processing.method == CMJ_BILATERAL_TOTAL_VERTICAL_FORCE_SUM
    assert processing.source_artifact_ids == (
        left.source_artifact.artifact_id,
        right.source_artifact.artifact_id,
    )
    assert (
        result.observation.provenance.lineage_edges.count(
            LineageEdge(
                left.observation.observation_id.qualified,
                processing.processing_run_id.qualified,
                LineageRelation.DERIVED_FROM,
            )
        )
        == 1
    )


def test_res35_processed_total_cannot_be_relabelled_as_bilateral_source() -> None:
    left, right = _bilateral_inputs()
    total = construct_total_supported_vertical_force(left, right)
    assert isinstance(total, TotalSupportedForceResult)
    assert isinstance(total.signal, ProcessedVerticalForceSignal)
    assert isinstance(total.observation.identity, CMJMeasurementIdentity)

    forged_acquisition = replace(
        total.observation.identity.acquisition,
        arrangement=AcquisitionArrangement.BILATERAL_SEPARATE,
        sensor_channel="left",
        channel=CMJChannelIdentity("left", ChannelRole.LEFT_FORCE_PLATFORM),
        available_channels=(
            CMJChannelIdentity("left", ChannelRole.LEFT_FORCE_PLATFORM),
            CMJChannelIdentity("right", ChannelRole.RIGHT_FORCE_PLATFORM),
        ),
        combination_lineage=None,
    )
    forged_identity = replace(total.observation.identity, acquisition=forged_acquisition)
    forged_signal = replace(total.signal, channel_id="left")
    forged_acquisition_record = replace(total.acquisition, sensor_channel="left")
    forged_observation = replace(total.observation, identity=forged_identity)
    forged = CMJForceInput(
        observation=forged_observation,
        identity=forged_identity,
        signal=forged_signal,
        source_artifact=total.source_artifact,
        acquisition=forged_acquisition_record,
    )

    refused = construct_total_supported_vertical_force(forged, right)
    assert isinstance(refused, RefusalResult)
    assert RefusalReasonCode.BILATERAL_INPUTS_INCOMPATIBLE in refused.reason_codes
    assert RefusalReasonCode.PROCESSING_LINEAGE_UNRESOLVED in refused.reason_codes


def test_res35_force_paths_and_bilateral_prerequisites_are_not_implicit() -> None:
    single = _cmj_input("single-path")
    single_result = construct_total_supported_vertical_force(single)
    assert isinstance(single_result, TotalSupportedForceResult)
    assert single_result.signal is single.signal

    precombined = _cmj_input(
        "precombined-path", arrangement=AcquisitionArrangement.BILATERAL_PRECOMBINED
    )
    precombined_result = construct_total_supported_vertical_force(precombined)
    assert isinstance(precombined_result, TotalSupportedForceResult)
    assert precombined_result.signal is precombined.signal

    separate = _cmj_input("separate-missing", arrangement=AcquisitionArrangement.BILATERAL_SEPARATE)
    refused = construct_total_supported_vertical_force(separate)
    assert isinstance(refused, RefusalResult)
    assert RefusalReasonCode.BILATERAL_INPUTS_REQUIRED in refused.reason_codes


def test_res35_bilateral_incompatible_timebase_and_sample_support_refuse() -> None:
    left, right = _bilateral_inputs()
    assert isinstance(right.signal, RawVerticalForceSignal)
    mismatched_timebase_signal = replace(
        right.signal,
        timebase=RegularTimebase(500.0),
    )
    mismatched_timebase_artifact = source_artifact_for_signal(mismatched_timebase_signal)
    mismatched_timebase_identity = replace(
        right.identity,
        acquisition=replace(
            right.identity.acquisition,
            raw_artifact=mismatched_timebase_artifact.artifact_id,
            timebase=TimebaseIdentity(TimebaseKind.REGULAR, 500.0),
        ),
    )
    mismatched_timebase_signal = replace(
        mismatched_timebase_signal,
        acquisition_identity_id=mismatched_timebase_identity.identity_id,
        source_artifact_id=mismatched_timebase_artifact.artifact_id,
    )
    mismatched_timebase_observation = create_cmj_raw_observation(
        observation_id=InstanceIdentifier("observation", "bilateral-timebase"),
        result_id=InstanceIdentifier("result", "bilateral-timebase"),
        context=left.observation.context,
        identity=mismatched_timebase_identity,
        signal=mismatched_timebase_signal,
        source_artifact=mismatched_timebase_artifact,
        acquisition=_acquisition_record(
            mismatched_timebase_identity,
            mismatched_timebase_signal,
            mismatched_timebase_artifact,
        ),
    )
    mismatched_timebase = CMJForceInput(
        observation=mismatched_timebase_observation,
        identity=mismatched_timebase_identity,
        signal=mismatched_timebase_signal,
        source_artifact=mismatched_timebase_artifact,
        acquisition=_acquisition_record(
            mismatched_timebase_identity,
            mismatched_timebase_signal,
            mismatched_timebase_artifact,
        ),
    )
    refused_timebase = construct_total_supported_vertical_force(left, mismatched_timebase)
    assert isinstance(refused_timebase, RefusalResult)
    assert RefusalReasonCode.TIMEBASE_NOT_SYNCHRONIZED in refused_timebase.reason_codes

    mismatched_clock = _rebind_raw_input(
        right,
        suffix="bilateral-clock",
        clock_reference=_reference("clock", "right-clock"),
    )
    refused_clock = construct_total_supported_vertical_force(left, mismatched_clock)
    assert isinstance(refused_clock, RefusalResult)
    assert RefusalReasonCode.TIMEBASE_NOT_SYNCHRONIZED in refused_clock.reason_codes

    shorter_signal = replace(right.signal, samples=(400.0, 401.0))
    shorter_artifact = source_artifact_for_signal(shorter_signal)
    shorter_identity = replace(
        right.identity,
        acquisition=replace(right.identity.acquisition, raw_artifact=shorter_artifact.artifact_id),
    )
    shorter_signal = replace(
        shorter_signal,
        acquisition_identity_id=shorter_identity.identity_id,
        source_artifact_id=shorter_artifact.artifact_id,
    )
    shorter_observation = create_cmj_raw_observation(
        observation_id=InstanceIdentifier("observation", "bilateral-shorter"),
        result_id=InstanceIdentifier("result", "bilateral-shorter"),
        context=left.observation.context,
        identity=shorter_identity,
        signal=shorter_signal,
        source_artifact=shorter_artifact,
        acquisition=_acquisition_record(shorter_identity, shorter_signal, shorter_artifact),
    )
    refused_support = construct_total_supported_vertical_force(
        left,
        CMJForceInput(
            observation=shorter_observation,
            identity=shorter_identity,
            signal=shorter_signal,
            source_artifact=shorter_artifact,
            acquisition=_acquisition_record(shorter_identity, shorter_signal, shorter_artifact),
        ),
    )
    assert isinstance(refused_support, RefusalResult)
    assert RefusalReasonCode.SAMPLE_SUPPORT_MISMATCH in refused_support.reason_codes


def test_res35_weighing_segment_is_separate_from_mean_estimator_and_qc_is_descriptive() -> None:
    source = _cmj_input("weighing")
    segment = WeighingSegment(
        source_signal_id=source.signal.signal_id,
        source_artifact_id=source.source_artifact.artifact_id,
        source_measurement_identity_id=source.identity.identity_id,
        start_index=1,
        end_index=3,
    )
    result = estimate_system_weight(source, segment)

    assert isinstance(result, SystemWeightResult)
    assert result.observation.result.value == ScalarValue(101.5)
    assert result.qc.sample_count == 2
    assert result.qc.elapsed_sample_span_s == pytest.approx(0.001)
    assert result.qc.standard_deviation_n == pytest.approx(0.7071067811865476)
    assert result.qc.range_n == 1.0
    assert result.qc.acceptability_adjudicated is False
    assert result.qc.quality_flags == ("QC_DESCRIBED", "QC_ACCEPTABILITY_NOT_ADJUDICATED")
    assert result.observation.identity.processing.estimator == CMJ_SYSTEM_WEIGHT_MEAN_FORCE
    assert (
        result.observation.identity.processing.registered_operation == CMJ_SYSTEM_WEIGHT_OPERATION
    )
    assert result.observation.result.classification.scientific_roles == ()
    assert (
        ValueOrigin.DERIVED_MECHANICAL_QUANTITY
        is result.observation.result.classification.value_origin
    )
    assert source.signal.samples == (100.0, 101.0, 102.0)

    missing = estimate_system_weight(source, None)
    assert isinstance(missing, RefusalResult)
    assert RefusalReasonCode.WEIGHING_SEGMENT_MISSING in missing.reason_codes
    too_few = estimate_system_weight(
        source,
        WeighingSegment(
            source.signal.signal_id,
            source.source_artifact.artifact_id,
            source.identity.identity_id,
            0,
            1,
        ),
    )
    assert isinstance(too_few, RefusalResult)
    assert RefusalReasonCode.INSUFFICIENT_WEIGHING_SAMPLES in too_few.reason_codes


def test_res45_weighing_uses_elapsed_sample_span_for_regular_and_explicit_support() -> None:
    regular_source = _rebind_raw_input(
        _cmj_input("elapsed-span-regular"),
        suffix="elapsed-span-regular-two",
        samples=(100.0, 101.0),
        timebase=RegularTimebase(1000.0, start_time_s=42.0),
    )
    explicit_source = _rebind_raw_input(
        _cmj_input("elapsed-span-explicit"),
        suffix="elapsed-span-explicit-two",
        samples=(100.0, 101.0),
        timebase=ExplicitTimebase((42.0, 42.001)),
    )
    regular_two = estimate_system_weight(
        regular_source,
        WeighingSegment(
            regular_source.signal.signal_id,
            regular_source.source_artifact.artifact_id,
            regular_source.identity.identity_id,
            0,
            2,
        ),
    )
    explicit_two = estimate_system_weight(
        explicit_source,
        WeighingSegment(
            explicit_source.signal.signal_id,
            explicit_source.source_artifact.artifact_id,
            explicit_source.identity.identity_id,
            0,
            2,
        ),
    )
    assert isinstance(regular_two, SystemWeightResult)
    assert isinstance(explicit_two, SystemWeightResult)
    assert regular_two.qc.elapsed_sample_span_s == pytest.approx(0.001)
    assert explicit_two.qc.elapsed_sample_span_s == pytest.approx(0.001)
    assert regular_two.value_n == explicit_two.value_n == pytest.approx(100.5)

    regular_three = _rebind_raw_input(
        _cmj_input("elapsed-span-regular-three"),
        suffix="elapsed-span-regular-three-rebound",
        samples=(100.0, 101.0, 102.0),
        timebase=RegularTimebase(1000.0, start_time_s=42.0),
    )
    explicit_three = _rebind_raw_input(
        _cmj_input("elapsed-span-explicit-three"),
        suffix="elapsed-span-explicit-three-rebound",
        samples=(100.0, 101.0, 102.0),
        timebase=ExplicitTimebase((42.0, 42.001, 42.002)),
    )
    irregular = _rebind_raw_input(
        _cmj_input("elapsed-span-irregular"),
        suffix="elapsed-span-irregular-rebound",
        samples=(100.0, 101.0, 102.0),
        timebase=ExplicitTimebase((42.0, 42.001, 42.004)),
    )

    def weighing(source: CMJForceInput) -> SystemWeightResult:
        result = estimate_system_weight(
            source,
            WeighingSegment(
                source.signal.signal_id,
                source.source_artifact.artifact_id,
                source.identity.identity_id,
                0,
                3,
            ),
        )
        assert isinstance(result, SystemWeightResult)
        return result

    regular_three_result = weighing(regular_three)
    explicit_three_result = weighing(explicit_three)
    irregular_result = weighing(irregular)
    assert regular_three_result.qc.elapsed_sample_span_s == pytest.approx(0.002)
    assert explicit_three_result.qc.elapsed_sample_span_s == pytest.approx(0.002)
    assert irregular_result.qc.elapsed_sample_span_s == pytest.approx(0.004)
    assert regular_three_result.value_n == explicit_three_result.value_n == pytest.approx(101.0)
    qc_json = canonical_json(regular_three_result.qc)
    assert '"elapsed_sample_span_s":0.002' in qc_json
    assert "duration_s" not in qc_json


def test_res35_system_mass_requires_explicit_gravity_and_preserves_weight() -> None:
    source = _cmj_input("mass")
    segment = WeighingSegment(
        source.signal.signal_id,
        source.source_artifact.artifact_id,
        source.identity.identity_id,
        0,
        3,
    )
    weight = estimate_system_weight(source, segment)
    assert isinstance(weight, SystemWeightResult)

    missing = derive_standard_gravity_mass_equivalent(weight)
    assert isinstance(missing, RefusalResult)
    assert RefusalReasonCode.GRAVITY_REFERENCE_MISSING in missing.reason_codes
    assert weight.value_n == 101.0

    mass = derive_standard_gravity_mass_equivalent(weight, STANDARD_GRAVITY)
    assert isinstance(mass, StandardGravityMassEquivalentResult)
    assert mass.value_kg == pytest.approx(101.0 / 9.80665)
    assert mass.observation.result.unit is not None
    assert mass.observation.result.unit.identifier.key == "kilogram"
    assert (
        mass.observation.result.classification.value_origin
        is ValueOrigin.DERIVED_MECHANICAL_QUANTITY
    )
    assert mass.observation.result.classification.scientific_roles == ()
    assert "9.81" not in canonical_json(mass)
    assert mass.observation.provenance.lineage_edges[
        -2
    ].relation is LineageRelation.SUPPORTED_BY or any(
        edge.relation is LineageRelation.SUPPORTED_BY
        for edge in mass.observation.provenance.lineage_edges
    )


def test_res35_system_mass_rejects_forged_weight_processing_lineage() -> None:
    source = _cmj_input("mass-lineage")
    segment = WeighingSegment(
        source.signal.signal_id,
        source.source_artifact.artifact_id,
        source.identity.identity_id,
        0,
        3,
    )
    weight = estimate_system_weight(source, segment)
    assert isinstance(weight, SystemWeightResult)
    assert len(weight.observation.provenance.processing_runs) == 1
    forged_run = replace(
        weight.observation.provenance.processing_runs[0],
        method=CMJ_BILATERAL_TOTAL_VERTICAL_FORCE_SUM,
    )
    forged_provenance = replace(
        weight.observation.provenance,
        processing_runs=(forged_run,),
    )
    forged_observation = replace(weight.observation, provenance=forged_provenance)

    refused = derive_standard_gravity_mass_equivalent(forged_observation, STANDARD_GRAVITY)
    assert isinstance(refused, RefusalResult)
    assert RefusalReasonCode.PROCESSING_LINEAGE_UNRESOLVED in refused.reason_codes


def test_res35_standard_and_local_gravity_are_distinct_and_body_mass_is_refused() -> None:
    source = _cmj_input("gravity-distinction")
    weight = estimate_system_weight(
        source,
        WeighingSegment(
            source.signal.signal_id,
            source.source_artifact.artifact_id,
            source.identity.identity_id,
            0,
            3,
        ),
    )
    assert isinstance(weight, SystemWeightResult)
    local = GravityReference(
        9.8,
        GravityReferenceType.LOCAL_GRAVITATIONAL_ACCELERATION,
        _reference("gravity-source", "synthetic-local-gravity"),
    )
    standard_mass = derive_standard_gravity_mass_equivalent(weight, STANDARD_GRAVITY)
    local_mass = derive_physical_system_mass(weight, local)
    assert isinstance(standard_mass, StandardGravityMassEquivalentResult)
    assert isinstance(local_mass, PhysicalSystemMassResult)
    assert standard_mass.gravity_reference.reference_type is GravityReferenceType.STANDARD_GRAVITY
    assert (
        local_mass.gravity_reference.reference_type
        is GravityReferenceType.LOCAL_GRAVITATIONAL_ACCELERATION
    )
    refusal = derive_body_mass(local_mass)
    assert isinstance(refusal, RefusalResult)
    assert refusal.refusal_class is RefusalClass.COMPUTATION_NOT_REGISTERED
    assert RefusalReasonCode.BODY_MASS_CLAIM_UNSUPPORTED in refusal.reason_codes
    assert refusal.observation_ids == (local_mass.observation.observation_id,)
    assert STANDARD_GRAVITY.value_m_per_s2 == 9.80665
    assert STANDARD_GRAVITY.uncertainty.status is UncertaintyStatus.NOT_APPLICABLE
    assert STANDARD_GRAVITY.uncertainty.description is not None
    assert "Conventional exact/reference" in STANDARD_GRAVITY.uncertainty.description
    assert "not a local measurement" in STANDARD_GRAVITY.uncertainty.description
    assert "not an unassessed empirical estimate" in STANDARD_GRAVITY.uncertainty.description
    assert local.uncertainty.status is UncertaintyStatus.NOT_ASSESSED
    with pytest.raises(ValueError, match="NOT_APPLICABLE"):
        GravityReference(
            9.80665,
            GravityReferenceType.STANDARD_GRAVITY,
            STANDARD_GRAVITY.source,
            uncertainty=UncertaintyMetadata(),
        )
    with pytest.raises(ValueError, match="standard-gravity source"):
        GravityReference(
            9.8,
            GravityReferenceType.LOCAL_GRAVITATIONAL_ACCELERATION,
            STANDARD_GRAVITY.source,
        )
    with pytest.raises(ValueError, match="exact-conventional metadata"):
        GravityReference(
            9.8,
            GravityReferenceType.LOCAL_GRAVITATIONAL_ACCELERATION,
            _reference("gravity-source", "local-with-standard-status"),
            uncertainty=STANDARD_GRAVITY.uncertainty,
        )
    with pytest.raises(ValueError, match="STANDARD_GRAVITY"):
        GravityReference(
            9.8,
            GravityReferenceType.STANDARD_GRAVITY,
            STANDARD_GRAVITY.source,
        )


def test_res44_mass_paths_require_their_adopted_gravity_semantics() -> None:
    source = _cmj_input("res44-gravity-semantics")
    weight = estimate_system_weight(
        source,
        WeighingSegment(
            source.signal.signal_id,
            source.source_artifact.artifact_id,
            source.identity.identity_id,
            0,
            3,
        ),
    )
    assert isinstance(weight, SystemWeightResult)

    missing_local = derive_physical_system_mass(weight)
    assert isinstance(missing_local, RefusalResult)
    assert RefusalReasonCode.GRAVITY_REFERENCE_MISSING in missing_local.reason_codes
    assert RefusalReasonCode.LOCAL_GRAVITY_REQUIRED in missing_local.reason_codes
    assert missing_local.observation_ids == (weight.observation.observation_id,)
    assert weight.value_n == 101.0

    standard_as_physical = derive_physical_system_mass(weight, STANDARD_GRAVITY)
    assert isinstance(standard_as_physical, RefusalResult)
    assert RefusalReasonCode.LOCAL_GRAVITY_REQUIRED in standard_as_physical.reason_codes
    assert RefusalReasonCode.GRAVITY_REFERENCE_MISMATCH in standard_as_physical.reason_codes

    local = GravityReference(
        9.8,
        GravityReferenceType.LOCAL_GRAVITATIONAL_ACCELERATION,
        _reference("gravity-source", "res44-local-gravity"),
    )
    standard = derive_standard_gravity_mass_equivalent(weight, STANDARD_GRAVITY)
    physical = derive_physical_system_mass(weight, local)
    assert isinstance(standard, StandardGravityMassEquivalentResult)
    assert isinstance(physical, PhysicalSystemMassResult)
    assert standard.value_kg == pytest.approx(101.0 / 9.80665)
    assert physical.value_kg == pytest.approx(101.0 / 9.8)
    assert standard.observation.result.unit is not None
    assert physical.observation.result.unit is not None
    assert standard.observation.result.unit.identifier.key == "kilogram"
    assert physical.observation.result.unit.identifier.key == "kilogram"
    assert (
        standard.observation.identity.semantic.measurand.stable_id
        != physical.observation.identity.semantic.measurand.stable_id
    )
    assert (
        standard.observation.identity.processing.registered_operation
        != physical.observation.identity.processing.registered_operation
    )
    assert standard.observation.result.classification.scientific_roles == ()
    assert physical.observation.result.classification.scientific_roles == ()
    assert "not physical" in (standard.observation.result.quality.note or "")
    assert "applicable local" in (physical.observation.result.quality.note or "")
    with pytest.raises(ValueError, match="LOCAL_GRAVITATIONAL_ACCELERATION"):
        PhysicalSystemMassResult(
            observation=standard.observation,
            gravity_reference=STANDARD_GRAVITY,
            source_system_weight_observation_id=weight.observation.observation_id,
        )
    with pytest.raises(ValueError, match="STANDARD_GRAVITY"):
        StandardGravityMassEquivalentResult(
            observation=physical.observation,
            gravity_reference=local,
            source_system_weight_observation_id=weight.observation.observation_id,
        )

    missing_standard = derive_standard_gravity_mass_equivalent(weight)
    assert isinstance(missing_standard, RefusalResult)
    assert RefusalReasonCode.GRAVITY_REFERENCE_MISSING in missing_standard.reason_codes

    local_as_standard = derive_standard_gravity_mass_equivalent(weight, local)
    assert isinstance(local_as_standard, RefusalResult)
    assert RefusalReasonCode.GRAVITY_REFERENCE_MISMATCH in local_as_standard.reason_codes


def test_res44_mass_serialization_and_provenance_keep_standard_and_local_distinct() -> None:
    source = _cmj_input("res44-provenance")
    weight = estimate_system_weight(
        source,
        WeighingSegment(
            source.signal.signal_id,
            source.source_artifact.artifact_id,
            source.identity.identity_id,
            0,
            3,
        ),
    )
    assert isinstance(weight, SystemWeightResult)
    local = GravityReference(
        9.8,
        GravityReferenceType.LOCAL_GRAVITATIONAL_ACCELERATION,
        _reference("gravity-source", "res44-provenance-local"),
    )
    standard = derive_standard_gravity_mass_equivalent(weight, STANDARD_GRAVITY)
    physical = derive_physical_system_mass(weight, local)
    assert isinstance(standard, StandardGravityMassEquivalentResult)
    assert isinstance(physical, PhysicalSystemMassResult)

    assert SERIALIZATION_VERSION == 3
    for value, result_type, gravity in (
        (standard, StandardGravityMassEquivalentResult, STANDARD_GRAVITY),
        (physical, PhysicalSystemMassResult, local),
    ):
        serialized = canonical_json(value)
        restored = from_canonical_json(serialized, result_type)
        assert canonical_json(restored) == serialized
        assert value.source_system_weight_observation_id == weight.observation.observation_id
        assert value.gravity_reference == gravity
        assert value.observation.result.classification.value_origin is (
            ValueOrigin.DERIVED_MECHANICAL_QUANTITY
        )
        assert f"{result_type.__name__}" in serialized
        run = next(
            run
            for run in value.observation.provenance.processing_runs
            if run.output_entity_id == value.observation.observation_id
        )
        parameters = {entry.key: entry.value for entry in run.parameters}
        assert (
            parameters["source_weight_observation_id"]
            == weight.observation.observation_id.qualified
        )
        assert parameters["gravity_value_m_per_s2"] == gravity.value_m_per_s2
        assert parameters["gravity_unit"] == gravity.unit.identifier.stable_id
        assert parameters["gravity_reference_type"] == gravity.reference_type.value
        assert parameters["gravity_source"] == gravity.source.stable_id
        assert run.software_version == RES44_SOFTWARE_VERSION
        assert gravity.source in value.observation.provenance.metrological_traceability
        assert any(
            reference.reference == RES44_DECISION_MASS_METROLOGY
            for reference in value.observation.provenance.evidence_references
        )
        assert any(
            edge.from_id == gravity.source.stable_id
            and edge.to_id == run.processing_run_id.qualified
            and edge.relation is LineageRelation.SUPPORTED_BY
            for edge in value.observation.provenance.lineage_edges
        )
        assert any(
            edge.from_id == RES44_DECISION_MASS_METROLOGY.stable_id
            and edge.to_id == run.processing_run_id.qualified
            and edge.relation is LineageRelation.SUPPORTED_BY
            for edge in value.observation.provenance.lineage_edges
        )

    standard_payload_with_old_type = canonical_json(standard).replace(
        "StandardGravityMassEquivalentResult", "SystemMassResult"
    )
    with pytest.raises(SerializationError, match="canonical type"):
        from_canonical_json(standard_payload_with_old_type, StandardGravityMassEquivalentResult)


def test_res35_loaded_protocol_preserves_supported_system_and_refuses_body_mass() -> None:
    loaded = _cmj_input("loaded", external_loading="20 kg supported external load")
    segment = WeighingSegment(
        loaded.signal.signal_id,
        loaded.source_artifact.artifact_id,
        loaded.identity.identity_id,
        0,
        3,
    )
    weight = estimate_system_weight(loaded, segment)
    assert isinstance(weight, SystemWeightResult)
    assert isinstance(weight.observation.identity, CMJMeasurementIdentity)
    protocol = weight.observation.identity.semantic.protocol_identity
    assert protocol is not None
    assert protocol.external_loading is not None
    assert protocol.external_loading.value == "20 kg supported external load"

    mass = derive_standard_gravity_mass_equivalent(weight, STANDARD_GRAVITY)
    assert isinstance(mass, StandardGravityMassEquivalentResult)
    assert mass.value_kg == pytest.approx(101.0 / 9.80665)
    refusal = derive_body_mass(mass)
    assert isinstance(refusal, RefusalResult)
    assert RefusalReasonCode.BODY_MASS_CLAIM_UNSUPPORTED in refusal.reason_codes


def test_res35_new_contracts_round_trip_under_serialization_v3() -> None:
    source = _cmj_input("serialization-res35")
    weight = estimate_system_weight(
        source,
        WeighingSegment(
            source.signal.signal_id,
            source.source_artifact.artifact_id,
            source.identity.identity_id,
            0,
            3,
        ),
    )
    assert isinstance(weight, SystemWeightResult)
    restored_weight = from_canonical_json(canonical_json(weight), SystemWeightResult)
    restored_gravity = from_canonical_json(canonical_json(STANDARD_GRAVITY), GravityReference)
    assert canonical_json(restored_weight) == canonical_json(weight)
    assert canonical_json(restored_gravity) == canonical_json(STANDARD_GRAVITY)


def test_res35_unit_axis_and_sign_contracts_refuse_without_hidden_harmonization() -> None:
    left, right = _bilateral_inputs()
    unit_mismatch = _rebind_raw_input(right, suffix="unit-mismatch", unit=KILONEWTON)
    unit_refusal = construct_total_supported_vertical_force(left, unit_mismatch)
    assert isinstance(unit_refusal, RefusalResult)
    assert RefusalReasonCode.FORCE_UNIT_TRANSFORMATION_REQUIRED in unit_refusal.reason_codes

    axis_mismatch = _rebind_raw_input(
        right,
        suffix="axis-mismatch",
        axis=_reference("axis", "horizontal", "Horizontal axis"),
    )
    axis_refusal = construct_total_supported_vertical_force(left, axis_mismatch)
    assert isinstance(axis_refusal, RefusalResult)
    assert RefusalReasonCode.SIGN_OR_FRAME_UNRESOLVED in axis_refusal.reason_codes

    sign_mismatch = _rebind_raw_input(
        right,
        suffix="sign-mismatch",
        sign=SignConvention(_reference("sign-convention", "alternate-upward"), "upward"),
    )
    sign_refusal = construct_total_supported_vertical_force(left, sign_mismatch)
    assert isinstance(sign_refusal, RefusalResult)
    assert RefusalReasonCode.BILATERAL_INPUTS_INCOMPATIBLE in sign_refusal.reason_codes
    assert RefusalReasonCode.SIGN_OR_FRAME_UNRESOLVED in sign_refusal.reason_codes


def test_res35_explicit_segment_uses_exact_half_open_sample_boundaries() -> None:
    source = _cmj_input("explicit-segment")
    explicit = _rebind_raw_input(
        source,
        suffix="explicit-segment-rebound",
        timebase=ExplicitTimebase((10.0, 10.1, 10.4)),
    )
    assert isinstance(explicit.signal, RawVerticalForceSignal)
    segment = WeighingSegment(
        explicit.signal.signal_id,
        explicit.source_artifact.artifact_id,
        explicit.identity.identity_id,
        1,
        3,
    )
    result = estimate_system_weight(explicit, segment)
    assert isinstance(result, SystemWeightResult)
    assert result.value_n == pytest.approx(101.5)
    assert result.qc.elapsed_sample_span_s == pytest.approx(0.3)
    assert result.qc.sample_count == 2


def test_res35_end_to_end_bilateral_weight_and_mass_preserves_processing_dag() -> None:
    left, right = _bilateral_inputs()
    total = construct_total_supported_vertical_force(left, right)
    assert isinstance(total, TotalSupportedForceResult)
    assert isinstance(total.signal, ProcessedVerticalForceSignal)
    reverse_total = construct_total_supported_vertical_force(right, left)
    assert isinstance(reverse_total, TotalSupportedForceResult)
    assert canonical_json(reverse_total) == canonical_json(total)
    segment = WeighingSegment(
        total.signal.signal_id,
        total.source_artifact.artifact_id,
        total.observation.identity.identity_id,
        0,
        3,
    )
    weight = estimate_system_weight(total, segment)
    assert isinstance(weight, SystemWeightResult)
    assert weight.value_n == pytest.approx(702.0)
    mass = derive_standard_gravity_mass_equivalent(weight, STANDARD_GRAVITY)
    assert isinstance(mass, StandardGravityMassEquivalentResult)
    assert mass.value_kg == pytest.approx(702.0 / 9.80665)
    restored_total = from_canonical_json(canonical_json(total), TotalSupportedForceResult)
    restored_mass = from_canonical_json(canonical_json(mass), StandardGravityMassEquivalentResult)
    assert canonical_json(restored_total) == canonical_json(total)
    assert canonical_json(restored_mass) == canonical_json(mass)
    assert len(mass.observation.provenance.processing_runs) == 3
    assert (
        sum(
            edge.relation is LineageRelation.PRODUCED
            and edge.to_id == mass.observation.observation_id.qualified
            for edge in mass.observation.provenance.lineage_edges
        )
        == 1
    )


def test_res35_incomplete_source_provenance_refuses_before_force_processing() -> None:
    source = _cmj_input("incomplete-provenance")
    incomplete_observation = replace(
        source.observation,
        provenance=replace(source.observation.provenance, lineage_edges=()),
    )
    incomplete = replace(source, observation=incomplete_observation)

    refused = construct_total_supported_vertical_force(incomplete)
    assert isinstance(refused, RefusalResult)
    assert RefusalReasonCode.PROCESSING_LINEAGE_UNRESOLVED in refused.reason_codes


def test_res35_derived_comparability_distinguishes_gravity_and_segment_identity() -> None:
    first_source = _cmj_input("comparability-one")
    second_source = _cmj_input("comparability-two")
    first_segment = WeighingSegment(
        first_source.signal.signal_id,
        first_source.source_artifact.artifact_id,
        first_source.identity.identity_id,
        0,
        3,
    )
    second_segment = WeighingSegment(
        second_source.signal.signal_id,
        second_source.source_artifact.artifact_id,
        second_source.identity.identity_id,
        0,
        3,
    )
    first_weight = estimate_system_weight(first_source, first_segment)
    second_weight = estimate_system_weight(second_source, second_segment)
    assert isinstance(first_weight, SystemWeightResult)
    assert isinstance(second_weight, SystemWeightResult)
    comparable = compare_cmj_derived_measurements(
        first_weight,
        second_weight,
        claim="compare system weight",
        request_id=InstanceIdentifier("comparability-request", "system-weight"),
    )
    assert comparable.state is ComparabilityState.COMPARABLE

    alternate_weight = estimate_system_weight(
        second_source,
        WeighingSegment(
            second_source.signal.signal_id,
            second_source.source_artifact.artifact_id,
            second_source.identity.identity_id,
            1,
            3,
        ),
    )
    assert isinstance(alternate_weight, SystemWeightResult)
    different_segment = compare_cmj_derived_measurements(
        first_weight,
        alternate_weight,
        claim="compare system weight with different weighing segment",
        request_id=InstanceIdentifier("comparability-request", "system-weight-segment"),
    )
    assert different_segment.state is ComparabilityState.BRIDGE_VALIDATION_REQUIRED
    assert ComparabilityReasonCode.WEIGHING_SEGMENT_MISMATCH in different_segment.reason_codes

    parameter_weight = estimate_system_weight(
        second_source,
        WeighingSegment(
            second_source.signal.signal_id,
            second_source.source_artifact.artifact_id,
            second_source.identity.identity_id,
            0,
            3,
            selection_parameters=(MetadataEntry("window_label", "operator-supplied"),),
        ),
    )
    assert isinstance(parameter_weight, SystemWeightResult)
    different_selection_parameters = compare_cmj_derived_measurements(
        first_weight,
        parameter_weight,
        claim="compare system weight with different selection parameters",
        request_id=InstanceIdentifier("comparability-request", "selection-parameters"),
    )
    assert different_selection_parameters.state is ComparabilityState.BRIDGE_VALIDATION_REQUIRED
    assert (
        ComparabilityReasonCode.WEIGHING_SEGMENT_MISMATCH
        in different_selection_parameters.reason_codes
    )

    first_mass = derive_standard_gravity_mass_equivalent(first_weight, STANDARD_GRAVITY)
    second_mass = derive_physical_system_mass(
        second_weight,
        GravityReference(
            9.8,
            GravityReferenceType.LOCAL_GRAVITATIONAL_ACCELERATION,
            _reference("gravity-source", "comparability-local"),
        ),
    )
    assert isinstance(first_mass, StandardGravityMassEquivalentResult)
    assert isinstance(second_mass, PhysicalSystemMassResult)
    different_gravity = compare_cmj_derived_measurements(
        first_mass,
        second_mass,
        claim="compare system mass",
        request_id=InstanceIdentifier("comparability-request", "system-mass"),
    )
    assert different_gravity.state is ComparabilityState.NOT_COMPARABLE
    assert ComparabilityReasonCode.MASS_MEASURAND_MISMATCH in different_gravity.reason_codes
    assert ComparabilityReasonCode.GRAVITY_REFERENCE_MISMATCH in different_gravity.reason_codes
    mass_refusal = refusal_for_cmj_derived_comparability(
        different_gravity,
        blocked_claim="compare physical system mass with standard-gravity mass equivalent",
        observation_ids=(
            first_mass.observation.observation_id,
            second_mass.observation.observation_id,
        ),
    )
    assert isinstance(mass_refusal, RefusalResult)
    assert RefusalReasonCode.MASS_MEASURAND_MISMATCH in mass_refusal.reason_codes
    assert RefusalReasonCode.GRAVITY_REFERENCE_MISMATCH in mass_refusal.reason_codes

    first_local = derive_physical_system_mass(
        first_weight,
        GravityReference(
            9.8,
            GravityReferenceType.LOCAL_GRAVITATIONAL_ACCELERATION,
            _reference("gravity-source", "comparability-local-one"),
        ),
    )
    second_local = derive_physical_system_mass(
        second_weight,
        GravityReference(
            9.81,
            GravityReferenceType.LOCAL_GRAVITATIONAL_ACCELERATION,
            _reference("gravity-source", "comparability-local-two"),
        ),
    )
    assert isinstance(first_local, PhysicalSystemMassResult)
    assert isinstance(second_local, PhysicalSystemMassResult)
    local_gravity_comparison = compare_cmj_derived_measurements(
        first_local,
        second_local,
        claim="compare physical system mass",
        request_id=InstanceIdentifier("comparability-request", "local-system-mass"),
    )
    assert local_gravity_comparison.state is ComparabilityState.BRIDGE_VALIDATION_REQUIRED
    assert ComparabilityReasonCode.GRAVITY_REFERENCE_MISMATCH in (
        local_gravity_comparison.reason_codes
    )
    local_gravity_refusal = refusal_for_cmj_derived_comparability(
        local_gravity_comparison,
        blocked_claim="compare physical system mass with different local gravity references",
        observation_ids=(
            first_local.observation.observation_id,
            second_local.observation.observation_id,
        ),
    )
    assert isinstance(local_gravity_refusal, RefusalResult)
    assert RefusalReasonCode.GRAVITY_REFERENCE_MISMATCH in local_gravity_refusal.reason_codes

    body_claim = compare_cmj_derived_measurements(
        first_weight,
        second_weight,
        claim="compare body mass",
        request_id=InstanceIdentifier("comparability-request", "body-mass"),
    )
    assert body_claim.state is ComparabilityState.NOT_COMPARABLE
    assert ComparabilityReasonCode.BODY_MASS_CLAIM_UNSUPPORTED in body_claim.reason_codes
    body_refusal = refusal_for_cmj_derived_comparability(
        body_claim,
        blocked_claim="compare body mass",
        observation_ids=(
            first_weight.observation.observation_id,
            second_weight.observation.observation_id,
        ),
    )
    assert isinstance(body_refusal, RefusalResult)
    assert body_refusal.refusal_class is RefusalClass.COMPUTATION_NOT_REGISTERED
    assert RefusalReasonCode.BODY_MASS_CLAIM_UNSUPPORTED in body_refusal.reason_codes


def test_res35_derived_comparability_detects_sampling_and_clock_differences() -> None:
    first_source = _cmj_input("comparability-sampling-one")
    second_source = _rebind_raw_input(
        _cmj_input("comparability-sampling-two"),
        suffix="comparability-sampling-two-rebound",
        timebase=RegularTimebase(500.0),
    )
    first_segment = WeighingSegment(
        first_source.signal.signal_id,
        first_source.source_artifact.artifact_id,
        first_source.identity.identity_id,
        0,
        3,
    )
    second_segment = WeighingSegment(
        second_source.signal.signal_id,
        second_source.source_artifact.artifact_id,
        second_source.identity.identity_id,
        0,
        3,
    )
    first_weight = estimate_system_weight(first_source, first_segment)
    second_weight = estimate_system_weight(second_source, second_segment)
    assert isinstance(first_weight, SystemWeightResult)
    assert isinstance(second_weight, SystemWeightResult)

    comparison = compare_cmj_derived_measurements(
        first_weight,
        second_weight,
        claim="compare system weight",
        request_id=InstanceIdentifier("comparability-request", "sampling"),
    )
    assert comparison.state is ComparabilityState.BRIDGE_VALIDATION_REQUIRED
    assert ComparabilityReasonCode.SAMPLE_OR_TIMEBASE_MISMATCH in comparison.reason_codes


def test_res36_event_definition_occurrence_and_method_parameter_identity_are_distinct() -> None:
    force = _event_input("event-identity", _event_trace())
    baseline = _event_baseline(force)
    parameters = _onset_parameters(baseline)
    onset = detect_movement_onset(force, baseline, parameters)

    assert isinstance(onset, CMJEventOccurrence)
    assert onset.definition is CMJ_MOVEMENT_ONSET_EVENT_DEFINITION
    assert onset.definition.reference.identifier.object_type == "event-definition"
    assert onset.occurrence_id.instance_type == "event-occurrence"
    assert onset.detector_method is CMJ_MOVEMENT_ONSET_BASELINE_SD_METHOD
    assert onset.detector_method.reference.identifier.object_type == "event-method"
    assert parameters.__class__.__name__ != onset.detector_method.__class__.__name__
    assert parameters != replace(parameters, sigma_multiplier=2.0)
    assert onset.detector_method.threshold_family is CMJEventThresholdFamily.BASELINE_SD_DEVIATION
    assert CMJEventDetectorParameters().threshold_n is None


def test_res36_clean_events_use_exact_index_time_and_ordering() -> None:
    force = _event_input(
        "event-clean",
        _event_trace(),
        timebase=RegularTimebase(sample_rate_hz=1000.0, start_time_s=10.0),
    )
    baseline = _event_baseline(force)
    onset = detect_movement_onset(force, baseline, _onset_parameters(baseline))
    assert isinstance(onset, CMJEventOccurrence)
    assert onset.definition.label is CMJEventLabel.MOVEMENT_ONSET
    takeoff = detect_takeoff(
        force,
        _absolute_parameters(20.0, CMJThresholdDirection.BELOW_THRESHOLD),
        onset=onset,
    )
    assert isinstance(takeoff, CMJEventOccurrence)
    assert takeoff.detector_method is CMJ_TAKEOFF_ABSOLUTE_FORCE_METHOD
    assert takeoff.definition is CMJ_TAKEOFF_CONTACT_LOSS_EVENT_DEFINITION
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
    assert landing.definition is CMJ_LANDING_CONTACT_REGAIN_EVENT_DEFINITION
    assert landing.detector_method is CMJ_LANDING_ABSOLUTE_FORCE_METHOD

    assert onset.sample_index == 5
    assert onset.event_time_s == pytest.approx(10.005)
    assert CMJEventQCCode.EVENT_NEAR_SIGNAL_BOUNDARY in onset.qc_codes
    assert takeoff.sample_index == 10
    assert takeoff.event_time_s == pytest.approx(10.01)
    assert landing.sample_index == 15
    assert landing.event_time_s == pytest.approx(10.015)
    assert takeoff.preceding_event_id == onset.occurrence_id
    assert landing.preceding_event_id == takeoff.occurrence_id
    assert validate_cmj_event_order((onset, takeoff, landing)) is None
    assert force.signal.samples == _event_trace()


def test_res36_explicit_irregular_timebase_is_indexed_without_interpolation() -> None:
    times = ExplicitTimebase(
        (
            100.0,
            100.001,
            100.003,
            100.006,
            100.010,
            100.015,
            100.021,
            100.028,
            100.036,
            100.045,
            100.055,
            100.066,
            100.078,
            100.091,
            100.105,
            100.120,
            100.136,
            100.153,
            100.171,
            100.190,
            100.210,
        )
    )
    force = _event_input("event-explicit-time", _event_trace(), timebase=times)
    baseline = _event_baseline(force)
    onset = detect_movement_onset(force, baseline, _onset_parameters(baseline))
    assert isinstance(onset, CMJEventOccurrence)
    takeoff = detect_takeoff(
        force,
        _absolute_parameters(20.0, CMJThresholdDirection.BELOW_THRESHOLD),
        onset=onset,
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

    assert onset.event_time_s == times.times_s[onset.sample_index]
    assert takeoff.event_time_s == times.times_s[takeoff.sample_index]
    assert landing.event_time_s == times.times_s[landing.sample_index]
    assert landing.event_time_s != pytest.approx(
        (times.times_s[landing.sample_index - 1] + times.times_s[landing.sample_index]) / 2
    )


def test_res36_baseline_sd_uses_exact_authorized_res35_inputs() -> None:
    force = _event_input("event-baseline-exact", _event_trace())
    baseline = _event_baseline(force)
    valid = detect_movement_onset(force, baseline, _onset_parameters(baseline))
    assert isinstance(valid, CMJEventOccurrence)

    altered_mean = replace(
        _onset_parameters(baseline),
        baseline_mean_force_n=baseline.qc.mean_force_n + 1.0,
    )
    refusal = detect_movement_onset(force, baseline, altered_mean)
    assert isinstance(refusal, RefusalResult)
    assert RefusalReasonCode.BASELINE_QC_REQUIRED in refusal.reason_codes

    missing_baseline = detect_movement_onset(
        force,
        None,
        CMJEventDetectorParameters(
            direction=CMJThresholdDirection.BELOW_THRESHOLD,
            dwell_samples=2,
            search_start_index=5,
        ),
    )
    assert isinstance(missing_baseline, RefusalResult)
    assert RefusalReasonCode.BASELINE_REQUIRED in missing_baseline.reason_codes


def test_res36_thresholds_and_dwell_are_explicit_and_transient_crossing_refuses() -> None:
    force = _event_input(
        "event-dwell",
        (100.0, 101.0, 99.0, 100.0, 100.0, 95.0, 100.0, 100.0, 100.0),
    )
    baseline = _event_baseline(force)
    transient = detect_movement_onset(force, baseline, _onset_parameters(baseline))
    assert isinstance(transient, RefusalResult)
    assert RefusalReasonCode.INSUFFICIENT_DWELL in transient.reason_codes

    no_crossing_force = _event_input(
        "event-no-crossing",
        (100.0, 101.0, 99.0, 100.0, 100.0, 100.0, 100.0, 100.0),
    )
    no_crossing_baseline = _event_baseline(no_crossing_force)
    no_crossing = detect_movement_onset(
        no_crossing_force,
        no_crossing_baseline,
        _onset_parameters(no_crossing_baseline),
    )
    assert isinstance(no_crossing, RefusalResult)
    assert RefusalReasonCode.THRESHOLD_NOT_CROSSED in no_crossing.reason_codes

    equality_force = _event_input(
        "event-threshold-equality",
        (100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0),
    )
    equality_baseline = _event_baseline(equality_force)
    equality = detect_movement_onset(
        equality_force,
        equality_baseline,
        _onset_parameters(equality_baseline, search_start_index=5),
    )
    assert isinstance(equality, RefusalResult)
    assert RefusalReasonCode.THRESHOLD_NOT_CROSSED in equality.reason_codes

    missing_takeoff_threshold = detect_takeoff(
        force,
        CMJEventDetectorParameters(
            direction=CMJThresholdDirection.BELOW_THRESHOLD,
            dwell_samples=2,
            search_start_index=5,
        ),
    )
    assert isinstance(missing_takeoff_threshold, RefusalResult)
    assert RefusalReasonCode.THRESHOLD_PARAMETER_MISSING in missing_takeoff_threshold.reason_codes


def test_res45_registered_event_parameter_domains_are_positive_and_parameterized() -> None:
    for threshold in (-500.0, 0.0):
        with pytest.raises(ValueError, match="threshold_n must be positive"):
            CMJEventDetectorParameters(threshold_n=threshold)
    valid_absolute = CMJEventDetectorParameters(threshold_n=12.5)
    assert valid_absolute.threshold_n == 12.5

    for sigma in (-1.0, 0.0):
        with pytest.raises(ValueError, match="sigma_multiplier must be positive"):
            CMJEventDetectorParameters(sigma_multiplier=sigma)
    valid_sigma = CMJEventDetectorParameters(sigma_multiplier=1.25)
    assert valid_sigma.sigma_multiplier == 1.25
    integer_parameters = CMJEventDetectorParameters(threshold_n=20, sigma_multiplier=2)
    float_parameters = CMJEventDetectorParameters(threshold_n=20.0, sigma_multiplier=2.0)
    assert integer_parameters == float_parameters
    assert canonical_json(integer_parameters) == canonical_json(float_parameters)

    with pytest.raises(ValueError, match="threshold_n must be finite"):
        CMJEventDetectorParameters(threshold_n=float("nan"))
    with pytest.raises(ValueError, match="threshold_n must be finite"):
        CMJEventDetectorParameters(threshold_n=float("inf"))
    with pytest.raises(ValueError, match="sigma_multiplier must be finite"):
        CMJEventDetectorParameters(sigma_multiplier=float("nan"))
    with pytest.raises(ValueError, match="sigma_multiplier must be finite"):
        CMJEventDetectorParameters(sigma_multiplier=float("inf"))

    assert CMJEventDetectorParameters().threshold_n is None
    assert CMJEventDetectorParameters().sigma_multiplier is None
    force = _event_input("event-positive-threshold", _event_trace())
    takeoff = detect_takeoff(
        force,
        _absolute_parameters(12.5, CMJThresholdDirection.BELOW_THRESHOLD),
    )
    assert isinstance(takeoff, CMJEventOccurrence)
    assert takeoff.detector_parameters.threshold_n == 12.5


def test_res36_multiple_crossings_use_registered_tie_break_and_qc() -> None:
    force = _event_input(
        "event-multiple",
        (100.0, 101.0, 99.0, 100.0, 100.0, 95.0, 95.0, 100.0, 95.0, 95.0, 100.0, 100.0),
    )
    baseline = _event_baseline(force)
    onset = detect_movement_onset(force, baseline, _onset_parameters(baseline))

    assert isinstance(onset, CMJEventOccurrence)
    assert onset.sample_index == 5
    assert CMJEventQCCode.MULTIPLE_CANDIDATE_CROSSINGS in onset.qc_codes


def test_res36_takeoff_and_landing_failures_do_not_repair_or_erase_prior_events() -> None:
    force = _event_input(
        "event-no-landing",
        (100.0, 101.0, 99.0, 100.0, 100.0, 100.0, 100.0, 100.0, 0.0, 0.0, 0.0, 0.0),
    )
    onset = detect_movement_onset(
        force,
        _event_baseline(force),
        _onset_parameters(_event_baseline(force), search_start_index=8),
    )
    assert isinstance(onset, CMJEventOccurrence)

    takeoff = detect_takeoff(
        force,
        _absolute_parameters(20.0, CMJThresholdDirection.BELOW_THRESHOLD, search_start_index=9),
        onset=onset,
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
    assert isinstance(landing, RefusalResult)
    assert RefusalReasonCode.LANDING_NOT_FOUND in landing.reason_codes
    assert takeoff.sample_index == 9


def test_res36_invalid_order_is_refused_without_shifting_events() -> None:
    force = _event_input("event-order", _event_trace())
    baseline = _event_baseline(force)
    onset = detect_movement_onset(force, baseline, _onset_parameters(baseline))
    assert isinstance(onset, CMJEventOccurrence)
    takeoff = detect_takeoff(
        force,
        _absolute_parameters(20.0, CMJThresholdDirection.BELOW_THRESHOLD),
        onset=onset,
    )
    assert isinstance(takeoff, CMJEventOccurrence)
    invalid_takeoff = replace(
        takeoff,
        sample_index=onset.sample_index,
        event_time_s=onset.event_time_s,
    )
    refusal = validate_cmj_event_order((onset, invalid_takeoff))
    assert isinstance(refusal, RefusalResult)
    assert RefusalReasonCode.EVENT_ORDER_INVALID in refusal.reason_codes
    assert invalid_takeoff.sample_index == onset.sample_index


def test_res36_total_supported_force_is_not_summed_twice() -> None:
    left, right = _bilateral_inputs()
    total = construct_total_supported_vertical_force(left, right)
    assert isinstance(total, TotalSupportedForceResult)
    assert total.signal.samples == (700.0, 702.0, 704.0)

    event = detect_takeoff(
        total,
        _absolute_parameters(
            750.0,
            CMJThresholdDirection.BELOW_THRESHOLD,
            dwell_samples=1,
            search_start_index=0,
        ),
    )
    assert isinstance(event, CMJEventOccurrence)
    assert event.sample_index == 0
    assert left.signal.samples == (300.0, 301.0, 302.0)
    assert right.signal.samples == (400.0, 401.0, 402.0)
    separate_refusal = detect_takeoff(
        left,
        _absolute_parameters(
            750.0,
            CMJThresholdDirection.BELOW_THRESHOLD,
            dwell_samples=1,
            search_start_index=0,
        ),
    )
    assert isinstance(separate_refusal, RefusalResult)
    assert RefusalReasonCode.BILATERAL_INPUTS_REQUIRED in separate_refusal.reason_codes


def test_res36_occurrence_provenance_and_canonical_serialization_are_complete() -> None:
    force = _event_input("event-serialization", _event_trace())
    baseline = _event_baseline(force)
    onset = detect_movement_onset(force, baseline, _onset_parameters(baseline))
    assert isinstance(onset, CMJEventOccurrence)
    event_json = canonical_json(onset)
    restored = from_canonical_json(event_json, CMJEventOccurrence)

    assert restored == onset
    assert canonical_json(restored) == event_json
    assert onset.provenance.processing_runs[-1].method == onset.detector_method.reference
    assert onset.detector_method.decision_reference in {
        evidence.reference for evidence in onset.provenance.evidence_references
    }
    assert onset.provenance.processing_runs[-1].output_entity_id == onset.occurrence_id
    assert onset.provenance.processing_runs[-1].output_entity_id.instance_type == "event-occurrence"
    assert any(
        edge.relation is LineageRelation.SUPPORTED_BY for edge in onset.provenance.lineage_edges
    )
    assert onset.provenance.processing_runs[-1].parameters


def test_res36_method_and_parameter_mismatches_remain_non_comparable() -> None:
    force = _event_input("event-comparison", _event_trace())
    baseline = _event_baseline(force)
    parameters = _onset_parameters(baseline)
    first = detect_movement_onset(force, baseline, parameters)
    second = detect_movement_onset(
        force,
        baseline,
        replace(parameters, sigma_multiplier=2.0),
    )
    assert isinstance(first, CMJEventOccurrence)
    assert isinstance(second, CMJEventOccurrence)

    parameter_comparison = compare_cmj_events(
        first,
        second,
        claim="compare movement-onset events",
        request_id=InstanceIdentifier("comparability-request", "event-parameters"),
    )
    assert parameter_comparison.state is ComparabilityState.BRIDGE_VALIDATION_REQUIRED
    assert parameter_comparison.rule_reference == CMJ_EVENT_COMPARABILITY_RULE
    assert ComparabilityReasonCode.EVENT_PARAMETER_MISMATCH in parameter_comparison.reason_codes
    parameter_refusal = refusal_for_cmj_event_comparability(
        parameter_comparison,
        blocked_claim="compare movement-onset events",
        observation_ids=(first.source_observation_id, second.source_observation_id),
    )
    assert isinstance(parameter_refusal, RefusalResult)
    assert RefusalReasonCode.EVENT_PARAMETER_MISMATCH in parameter_refusal.reason_codes

    alternate_method = CMJEventDetectorMethod(
        reference=_reference("event-method", "alternate-onset"),
        event_definition=CMJ_MOVEMENT_ONSET_EVENT_DEFINITION,
        threshold_family=CMJEventThresholdFamily.BASELINE_SD_DEVIATION,
        decision_reference=_reference("decision-record", "alternate-onset"),
    )
    alternate_id = InstanceIdentifier("event-occurrence", "alternate-onset")
    alternate_run = replace(
        first.provenance.processing_runs[-1],
        method=alternate_method.reference,
        output_entity_id=alternate_id,
    )
    alternate_edges = tuple(
        replace(
            edge,
            to_id=alternate_id.qualified,
        )
        if (
            edge.from_id == alternate_run.processing_run_id.qualified
            and edge.to_id == first.occurrence_id.qualified
            and edge.relation is LineageRelation.PRODUCED
        )
        else edge
        for edge in first.provenance.lineage_edges
    )
    alternate_provenance = replace(
        first.provenance,
        processing_runs=(*first.provenance.processing_runs[:-1], alternate_run),
        lineage_edges=alternate_edges,
    )
    alternate = replace(
        first,
        occurrence_id=alternate_id,
        detector_method=alternate_method,
        decision_reference=alternate_method.decision_reference,
        provenance=alternate_provenance,
    )
    method_comparison = compare_cmj_events(
        first,
        alternate,
        claim="compare movement-onset events",
        request_id=InstanceIdentifier("comparability-request", "event-method"),
    )
    assert method_comparison.state is ComparabilityState.BRIDGE_VALIDATION_REQUIRED
    assert ComparabilityReasonCode.EVENT_METHOD_MISMATCH in method_comparison.reason_codes


def test_res36_no_system_mass_or_downstream_phase_authority_is_added() -> None:
    import inspect

    import dynamislm.measurement.cmj.events as events

    source = inspect.getsource(events)
    assert "SystemMassResult" not in source
    assert "derive_system_mass" not in source
    assert "STANDARD_GRAVITY" not in source
    assert not hasattr(events, "calculate_net_force")
    assert not hasattr(events, "calculate_impulse")
    assert not hasattr(events, "calculate_jump_height")
    assert not hasattr(events, "detect_braking_phase")
    assert not hasattr(events, "detect_propulsive_phase")


def _mechanics_contract(
    *, includes_supported_external_load: bool = False
) -> CMJMechanicalSystemContract:
    return CMJMechanicalSystemContract(
        system_definition=CMJ_SUPPORTED_SYSTEM_CONSTRUCT,
        external_force_model=CMJ_FORCE_PLATFORM_PLUS_GRAVITY_EXTERNAL_FORCE_MODEL,
        system_description=(
            "athlete plus supported external load"
            if includes_supported_external_load
            else "supported athlete system"
        ),
        force_platform_represents_total_supported_force=True,
        gravity_is_only_other_material_vertical_external_force=True,
        composition_stable=True,
        includes_supported_external_load=includes_supported_external_load,
    )


def _mechanics_fixture(
    suffix: str,
    samples: tuple[float, ...],
    *,
    timebase: SignalTimebase | None = None,
    external_loading: str = "none",
    weighing_end_index: int = 2,
    weighing_selection_parameters: tuple[MetadataEntry, ...] = (),
) -> tuple[
    CMJForceInput, TotalSupportedForceResult, SystemWeightResult, CMJMechanicalSystemContract
]:
    source = _rebind_raw_input(
        _cmj_input(suffix, external_loading=external_loading),
        suffix=f"{suffix}-bound",
        samples=samples,
        timebase=timebase,
    )
    total = construct_total_supported_vertical_force(source)
    assert isinstance(total, TotalSupportedForceResult)
    segment = WeighingSegment(
        source_signal_id=total.signal.signal_id,
        source_artifact_id=total.source_artifact.artifact_id,
        source_measurement_identity_id=total.observation.identity.identity_id,
        start_index=0,
        end_index=weighing_end_index,
        selection_parameters=weighing_selection_parameters,
    )
    weight = estimate_system_weight(total, segment)
    assert isinstance(weight, SystemWeightResult)
    return (
        source,
        total,
        weight,
        _mechanics_contract(includes_supported_external_load=external_loading != "none"),
    )


def _local_gravity(suffix: str = "one") -> GravityReference:
    return GravityReference(
        value_m_per_s2=1.0,
        reference_type=GravityReferenceType.LOCAL_GRAVITATIONAL_ACCELERATION,
        source=_reference("gravity-source", f"local-{suffix}"),
    )


def test_res37_net_force_is_weight_subtraction_without_mass_and_preserves_lineage() -> None:
    source, total, weight, contract = _mechanics_fixture(
        "mechanics-net", (100.0, 100.0, 100.0, 0.0, 0.0)
    )
    original_samples = source.signal.samples

    result = derive_net_vertical_force(total, weight, contract)

    assert isinstance(result, NetVerticalForceResult)
    assert result.samples == (0.0, 0.0, 0.0, -100.0, -100.0)
    assert result.unit == NEWTON
    assert result.system_contract == contract
    assert (
        result.observation.result.classification.value_origin
        is ValueOrigin.DERIVED_MECHANICAL_QUANTITY
    )
    assert result.observation.result.classification.scientific_roles == ()
    assert source.signal.samples == original_samples
    processing_run = result.observation.provenance.processing_runs[-1]
    assert processing_run.output_entity_id == result.observation.observation_id
    assert any(
        edge.from_id == processing_run.processing_run_id.qualified
        and edge.to_id == result.observation.observation_id.qualified
        and edge.relation is LineageRelation.PRODUCED
        for edge in result.observation.provenance.lineage_edges
    )
    assert any(
        edge.from_id == processing_run.processing_run_id.qualified
        and edge.to_id == result.series.artifact_id.qualified
        and edge.relation is LineageRelation.PRODUCED
        for edge in result.observation.provenance.lineage_edges
    )
    parameters = {
        entry.key: entry.value for entry in result.observation.identity.processing.method_parameters
    }
    assert parameters["filtering"] == "none"
    assert parameters["interpolation"] == "none"
    assert parameters["drift_correction"] == "none"


def test_res37_force_weight_contracts_are_granular_and_upstream_survives() -> None:
    _, total, weight, contract = _mechanics_fixture("mechanics-required", (100.0, 100.0, 100.0))

    missing_weight = derive_net_vertical_force(total, None, contract)
    assert isinstance(missing_weight, RefusalResult)
    assert RefusalReasonCode.SYSTEM_WEIGHT_REQUIRED in missing_weight.reason_codes
    missing_contract = derive_net_vertical_force(total, weight, None)
    assert isinstance(missing_contract, RefusalResult)
    assert RefusalReasonCode.MECHANICAL_SYSTEM_UNRESOLVED in missing_contract.reason_codes

    other_source, other_total, other_weight, _ = _mechanics_fixture(
        "mechanics-wrong-weight", (100.0, 100.0, 100.0)
    )
    assert other_source.signal.samples == (100.0, 100.0, 100.0)
    wrong_weight = derive_net_vertical_force(other_total, weight, contract)
    assert isinstance(wrong_weight, RefusalResult)
    assert RefusalReasonCode.FORCE_WEIGHT_SYSTEM_MISMATCH in wrong_weight.reason_codes
    assert other_weight.value_n == weight.value_n


def test_res37_bilateral_total_force_is_not_summed_twice() -> None:
    left, right = _bilateral_inputs()
    total = construct_total_supported_vertical_force(left, right)
    assert isinstance(total, TotalSupportedForceResult)
    segment = WeighingSegment(
        total.signal.signal_id,
        total.source_artifact.artifact_id,
        total.observation.identity.identity_id,
        0,
        3,
    )
    weight = estimate_system_weight(total, segment)
    assert isinstance(weight, SystemWeightResult)
    result = derive_net_vertical_force(total, weight, _mechanics_contract())

    assert isinstance(result, NetVerticalForceResult)
    assert result.samples == (-2.0, 0.0, 2.0)
    assert total.signal.samples == (700.0, 702.0, 704.0)


def test_res37_flight_force_remains_negative_weight_under_registered_model() -> None:
    _, total, weight, contract = _mechanics_fixture("mechanics-flight", (100.0, 100.0, 0.0, 0.0))
    result = derive_net_vertical_force(total, weight, contract)

    assert isinstance(result, NetVerticalForceResult)
    assert result.samples[2:] == (-100.0, -100.0)


def test_res37_registered_interval_and_scalar_impulse_are_explicit_and_inclusive() -> None:
    _, total, weight, contract = _mechanics_fixture("mechanics-impulse", (1.0, 1.0, 3.0, 3.0, 3.0))
    net = derive_net_vertical_force(total, weight, contract)
    assert isinstance(net, NetVerticalForceResult)
    interval = CMJIntegrationInterval.explicit_sample(net.series.series_id, 2, 4)

    impulse = integrate_net_vertical_impulse(net, interval)

    assert isinstance(impulse, NetVerticalImpulseResult)
    assert impulse.value_ns == pytest.approx(0.004)
    assert impulse.interval.kind is CMJIntegrationIntervalKind.EXPLICIT_SAMPLE_INTERVAL
    assert impulse.interval.integration_method.stable_id.endswith(
        "sample-attached-trapezoidal-v1@1.0.0"
    )
    assert "inclusive" in impulse.interval.interval_semantics
    assert "no interpolation" in impulse.interval.interval_semantics
    assert impulse.observation.result.unit is not None
    assert impulse.observation.result.unit.identifier.stable_id.endswith("unit:newton-second@1.0.0")
    missing_interval = integrate_net_vertical_impulse(net)
    assert isinstance(missing_interval, RefusalResult)
    assert RefusalReasonCode.INTEGRATION_INTERVAL_INVALID in missing_interval.reason_codes


def test_res37_regular_start_time_does_not_change_integral() -> None:
    first = _mechanics_fixture(
        "mechanics-start-zero",
        (10.0, 10.0, 12.0, 12.0),
        timebase=RegularTimebase(1000.0, start_time_s=0.0),
    )
    second = _mechanics_fixture(
        "mechanics-start-shifted",
        (10.0, 10.0, 12.0, 12.0),
        timebase=RegularTimebase(1000.0, start_time_s=42.0),
    )
    first_net = derive_net_vertical_force(first[1], first[2], first[3])
    second_net = derive_net_vertical_force(second[1], second[2], second[3])
    assert isinstance(first_net, NetVerticalForceResult)
    assert isinstance(second_net, NetVerticalForceResult)
    first_impulse = integrate_net_vertical_impulse(
        first_net, CMJIntegrationInterval.explicit_sample(first_net.series.series_id, 0, 3)
    )
    second_impulse = integrate_net_vertical_impulse(
        second_net, CMJIntegrationInterval.explicit_sample(second_net.series.series_id, 0, 3)
    )
    assert isinstance(first_impulse, NetVerticalImpulseResult)
    assert isinstance(second_impulse, NetVerticalImpulseResult)
    assert first_impulse.timebase == first_net.series.timebase
    assert first_impulse.value_ns == pytest.approx(second_impulse.value_ns)
    assert first_impulse.value_ns == pytest.approx(0.003)


def test_res37_regular_integration_uses_exact_sample_delta_at_large_start_time() -> None:
    _, total, weight, contract = _mechanics_fixture(
        "mechanics-large-start",
        (100.0, 100.0, 100.0, 102.0),
        timebase=RegularTimebase(1000.0, start_time_s=1.0e15),
    )
    net = derive_net_vertical_force(total, weight, contract)
    assert isinstance(net, NetVerticalForceResult)
    impulse = integrate_net_vertical_impulse(
        net, CMJIntegrationInterval.explicit_sample(net.series.series_id, 2, 3)
    )

    assert isinstance(impulse, NetVerticalImpulseResult)
    assert impulse.value_ns == pytest.approx(0.001)


def test_res37_irregular_explicit_timebase_uses_actual_sample_deltas() -> None:
    _, total, weight, contract = _mechanics_fixture(
        "mechanics-irregular",
        (0.0, 2.0, 4.0, 6.0),
        timebase=ExplicitTimebase((10.0, 10.1, 10.3, 10.6)),
    )
    net = derive_net_vertical_force(total, weight, contract)
    assert isinstance(net, NetVerticalForceResult)
    impulse = integrate_net_vertical_impulse(
        net, CMJIntegrationInterval.explicit_sample(net.series.series_id, 0, 3)
    )

    assert isinstance(impulse, NetVerticalImpulseResult)
    assert impulse.value_ns == pytest.approx(1.6)


def test_res37_event_interval_uses_takeoff_event_sample_not_previous_sample() -> None:
    force = _event_input("mechanics-event-boundary", _event_trace())
    weight = _event_baseline(force)
    onset = detect_movement_onset(force, weight, _onset_parameters(weight))
    takeoff = detect_takeoff(
        force,
        _absolute_parameters(20.0, CMJThresholdDirection.BELOW_THRESHOLD),
        onset=onset if isinstance(onset, CMJEventOccurrence) else None,
    )
    assert isinstance(onset, CMJEventOccurrence)
    assert isinstance(takeoff, CMJEventOccurrence)
    total = construct_total_supported_vertical_force(force)
    assert isinstance(total, TotalSupportedForceResult)
    net = derive_net_vertical_force(total, weight, _mechanics_contract())
    assert isinstance(net, NetVerticalForceResult)
    interval = CMJIntegrationInterval.event_bounded(
        start_event=onset,
        end_event=takeoff,
    )
    impulse = integrate_net_vertical_impulse(net, interval)

    assert isinstance(impulse, NetVerticalImpulseResult)
    assert onset.sample_index == 5
    assert takeoff.sample_index == 10
    assert interval.end_index == 10
    assert impulse.value_ns == pytest.approx(-0.055)
    previous_sample_interval = CMJIntegrationInterval.explicit_sample(
        net.series.series_id, onset.sample_index, takeoff.sample_index - 1
    )
    previous = integrate_net_vertical_impulse(net, previous_sample_interval)
    assert isinstance(previous, NetVerticalImpulseResult)
    assert previous.value_ns == pytest.approx(-0.0075)
    assert impulse.value_ns != pytest.approx(previous.value_ns)


def test_res37_physical_acceleration_requires_mass_and_uses_exact_compatible_mass() -> None:
    _, total, weight, contract = _mechanics_fixture(
        "mechanics-acceleration", (1.0, 1.0, 3.0, 3.0, 3.0)
    )
    net = derive_net_vertical_force(total, weight, contract)
    assert isinstance(net, NetVerticalForceResult)
    missing = derive_supported_system_com_acceleration(net, None, contract)
    assert isinstance(missing, RefusalResult)
    assert RefusalReasonCode.PHYSICAL_SYSTEM_MASS_REQUIRED in missing.reason_codes
    mass = derive_physical_system_mass(weight, _local_gravity("acceleration"))
    assert isinstance(mass, PhysicalSystemMassResult)
    acceleration = derive_supported_system_com_acceleration(net, mass, contract)

    assert isinstance(acceleration, SupportedSystemComAccelerationResult)
    assert acceleration.samples == (0.0, 0.0, 2.0, 2.0, 2.0)
    assert acceleration.series.unit.identifier.stable_id.endswith(
        "unit:meter-per-second-squared@1.0.0"
    )
    assert acceleration.series.operation.stable_id.endswith(
        "supported-system-com-vertical-acceleration-v1@1.0.0"
    )


def test_res37_mass_provenance_and_standard_gravity_type_are_not_interchangeable() -> None:
    _, total_a, weight_a, contract = _mechanics_fixture("mechanics-mass-a", (1.0, 1.0, 3.0, 3.0))
    _, total_b, weight_b, _ = _mechanics_fixture("mechanics-mass-b", (1.0, 1.0, 3.0, 3.0))
    net_a = derive_net_vertical_force(total_a, weight_a, contract)
    assert isinstance(net_a, NetVerticalForceResult)
    mass_b = derive_physical_system_mass(weight_b, _local_gravity("mass-b"))
    assert isinstance(mass_b, PhysicalSystemMassResult)
    mismatched = derive_supported_system_com_acceleration(net_a, mass_b, contract)
    assert isinstance(mismatched, RefusalResult)
    assert RefusalReasonCode.MASS_SOURCE_MISMATCH in mismatched.reason_codes

    standard = derive_standard_gravity_mass_equivalent(weight_a, STANDARD_GRAVITY)
    assert isinstance(standard, StandardGravityMassEquivalentResult)
    rejected = derive_supported_system_com_acceleration(net_a, standard, contract)
    assert isinstance(rejected, RefusalResult)
    assert RefusalReasonCode.STANDARD_GRAVITY_EQUIVALENT_NOT_AUTHORIZED in rejected.reason_codes
    assert total_b.signal.samples == (1.0, 1.0, 3.0, 3.0)


def test_res46_velocity_requires_qualified_reference_and_preserves_pre_start_undefinedness() -> (
    None
):
    _, total, weight, contract = _mechanics_fixture(
        "mechanics-velocity",
        (1.0, 1.0, 1.0, 3.0, 3.0),
        weighing_end_index=3,
    )
    net = derive_net_vertical_force(total, weight, contract)
    assert isinstance(net, NetVerticalForceResult)
    mass = derive_physical_system_mass(weight, _local_gravity("velocity"))
    assert isinstance(mass, PhysicalSystemMassResult)
    acceleration = derive_supported_system_com_acceleration(net, mass, contract)
    assert isinstance(acceleration, SupportedSystemComAccelerationResult)
    interval = CMJIntegrationInterval.explicit_sample(acceleration.series.series_id, 2, 4)
    legacy_condition = InitialVelocityCondition.zero_at_sample(acceleration.series.series_id, 2)
    missing = derive_supported_system_com_velocity(acceleration, interval, None)
    assert isinstance(missing, RefusalResult)
    assert RefusalReasonCode.ZERO_VELOCITY_REFERENCE_REQUIRED in missing.reason_codes
    arbitrary = derive_supported_system_com_velocity(acceleration, interval, legacy_condition)
    assert isinstance(arbitrary, RefusalResult)
    assert RefusalReasonCode.ZERO_VELOCITY_REFERENCE_UNQUALIFIED in arbitrary.reason_codes
    condition = QualifiedZeroVelocityReference.from_system_weight(weight, 2)
    velocity = derive_supported_system_com_velocity(acceleration, interval, condition)

    assert isinstance(velocity, SupportedSystemComVelocityResult)
    assert velocity.samples == (0.0, 0.001, 0.003)
    assert velocity.series.sample_start_index == 2
    assert velocity.series.source_sample_indices == (2, 3, 4)
    assert velocity.initial_velocity_condition == condition
    assert acceleration.samples == (0.0, 0.0, 0.0, 2.0, 2.0)
    parameters = {
        entry.key: entry.value
        for entry in velocity.observation.identity.processing.method_parameters
    }
    assert parameters["zero_velocity_reference"] == canonical_json(condition)
    assert (
        velocity.observation.provenance.evidence_references[-1].reference
        == condition.evidence_decision
    )
    assert condition.source_system_weight_observation_id in velocity.series.source_observation_ids
    assert condition.source_artifact_id in velocity.series.source_artifact_ids
    assert (
        condition.source_measurement_identity_id in velocity.series.source_measurement_identity_ids
    )


def test_res46_arbitrary_post_movement_zero_cannot_be_physical_velocity_authority() -> None:
    _, total, weight, contract = _mechanics_fixture(
        "res46-post-movement",
        (1.0, 1.0, 3.0, 3.0, 3.0),
    )
    net = derive_net_vertical_force(total, weight, contract)
    assert isinstance(net, NetVerticalForceResult)
    mass = derive_physical_system_mass(weight, _local_gravity("post-movement"))
    assert isinstance(mass, PhysicalSystemMassResult)
    acceleration = derive_supported_system_com_acceleration(net, mass, contract)
    assert isinstance(acceleration, SupportedSystemComAccelerationResult)
    interval = CMJIntegrationInterval.explicit_sample(acceleration.series.series_id, 2, 4)
    arbitrary = InitialVelocityCondition.zero_at_sample(acceleration.series.series_id, 2)

    refused = derive_supported_system_com_velocity(acceleration, interval, arbitrary)

    assert isinstance(refused, RefusalResult)
    assert RefusalReasonCode.ZERO_VELOCITY_REFERENCE_UNQUALIFIED in refused.reason_codes


def test_res46_exact_movement_onset_event_does_not_authorize_zero_velocity() -> None:
    force = _event_input("res46-event-reference", _event_trace())
    weight = _event_baseline(force)
    onset = detect_movement_onset(force, weight, _onset_parameters(weight))
    assert isinstance(onset, CMJEventOccurrence)
    total = construct_total_supported_vertical_force(force)
    assert isinstance(total, TotalSupportedForceResult)
    contract = _mechanics_contract()
    net = derive_net_vertical_force(total, weight, contract)
    assert isinstance(net, NetVerticalForceResult)
    mass = derive_physical_system_mass(weight, _local_gravity("event-reference"))
    assert isinstance(mass, PhysicalSystemMassResult)
    acceleration = derive_supported_system_com_acceleration(net, mass, contract)
    assert isinstance(acceleration, SupportedSystemComAccelerationResult)
    interval = CMJIntegrationInterval.explicit_sample(
        acceleration.series.series_id, onset.sample_index, onset.sample_index
    )
    legacy_event_condition = InitialVelocityCondition.zero_at_sample(
        onset.source_signal_id,
        onset.sample_index,
        reference_event=onset,
    )

    refused = derive_supported_system_com_velocity(acceleration, interval, legacy_event_condition)

    assert isinstance(refused, RefusalResult)
    assert RefusalReasonCode.ZERO_VELOCITY_REFERENCE_UNQUALIFIED in refused.reason_codes


def test_res46_qualified_reference_requires_exact_source_trial_context_and_system() -> None:
    primary = _mechanics_fixture(
        "res46-primary",
        (1.0, 1.0, 1.0, 3.0, 3.0),
        weighing_end_index=3,
    )
    other = _mechanics_fixture(
        "res46-other",
        (1.0, 1.0, 1.0, 3.0, 3.0),
        weighing_end_index=3,
    )
    _, total, weight, contract = primary
    _, other_total, other_weight, _ = other
    net = derive_net_vertical_force(total, weight, contract)
    assert isinstance(net, NetVerticalForceResult)
    mass = derive_physical_system_mass(weight, _local_gravity("source-check"))
    assert isinstance(mass, PhysicalSystemMassResult)
    acceleration = derive_supported_system_com_acceleration(net, mass, contract)
    assert isinstance(acceleration, SupportedSystemComAccelerationResult)
    interval = CMJIntegrationInterval.explicit_sample(acceleration.series.series_id, 2, 4)
    other_reference = QualifiedZeroVelocityReference.from_system_weight(other_weight, 2)
    primary_reference = QualifiedZeroVelocityReference.from_system_weight(weight, 2)
    wrong_segment_reference = replace(
        primary_reference,
        weighing_segment=replace(primary_reference.weighing_segment, end_index=4),
    )

    wrong_trial = derive_supported_system_com_velocity(acceleration, interval, other_reference)
    wrong_weight_observation = derive_supported_system_com_velocity(
        acceleration,
        interval,
        replace(
            primary_reference,
            source_system_weight_observation_id=other_weight.observation.observation_id,
        ),
    )
    wrong_segment = derive_supported_system_com_velocity(
        acceleration, interval, wrong_segment_reference
    )
    loaded = _mechanics_fixture(
        "res46-loaded",
        (101.0, 101.0, 101.0, 103.0, 103.0),
        external_loading="supported-barbell",
        weighing_end_index=3,
    )
    loaded_reference = QualifiedZeroVelocityReference.from_system_weight(loaded[2], 2)
    wrong_system = derive_supported_system_com_velocity(acceleration, interval, loaded_reference)

    for refused in (wrong_trial, wrong_weight_observation, wrong_segment, wrong_system):
        assert isinstance(refused, RefusalResult)
        assert RefusalReasonCode.ZERO_VELOCITY_SOURCE_MISMATCH in refused.reason_codes
    assert other_total.signal.signal_id != total.signal.signal_id


def test_res46_reference_segment_is_half_open_and_interval_start_is_exact() -> None:
    _, total, weight, contract = _mechanics_fixture(
        "res46-boundary",
        (1.0, 1.0, 1.0, 3.0, 3.0),
        weighing_end_index=3,
    )
    with pytest.raises(ValueError, match="inside the weighing segment"):
        QualifiedZeroVelocityReference.from_system_weight(weight, weight.segment.end_index)

    net = derive_net_vertical_force(total, weight, contract)
    assert isinstance(net, NetVerticalForceResult)
    mass = derive_physical_system_mass(weight, _local_gravity("boundary"))
    assert isinstance(mass, PhysicalSystemMassResult)
    acceleration = derive_supported_system_com_acceleration(net, mass, contract)
    assert isinstance(acceleration, SupportedSystemComAccelerationResult)
    reference = QualifiedZeroVelocityReference.from_system_weight(weight, 1)
    interval = CMJIntegrationInterval.explicit_sample(acceleration.series.series_id, 2, 4)

    refused = derive_supported_system_com_velocity(acceleration, interval, reference)

    assert isinstance(refused, RefusalResult)
    assert RefusalReasonCode.ZERO_VELOCITY_REFERENCE_MISMATCH in refused.reason_codes


def test_res46_qualified_start_keeps_existing_trapezoidal_velocity_oracle() -> None:
    _, total, weight, contract = _mechanics_fixture(
        "res46-trapezoid-oracle",
        (1.0, 1.0, 3.0, 3.0, 3.0),
    )
    net = derive_net_vertical_force(total, weight, contract)
    assert isinstance(net, NetVerticalForceResult)
    mass = derive_physical_system_mass(weight, _local_gravity("trapezoid-oracle"))
    assert isinstance(mass, PhysicalSystemMassResult)
    acceleration = derive_supported_system_com_acceleration(net, mass, contract)
    assert isinstance(acceleration, SupportedSystemComAccelerationResult)
    interval = CMJIntegrationInterval.explicit_sample(acceleration.series.series_id, 1, 4)
    reference = QualifiedZeroVelocityReference.from_system_weight(weight, 1)

    velocity = derive_supported_system_com_velocity(acceleration, interval, reference)

    assert isinstance(velocity, SupportedSystemComVelocityResult)
    assert velocity.samples == pytest.approx((0.0, 0.001, 0.003, 0.005))
    assert velocity.series.samples == velocity.samples
    assert "backshift" not in canonical_json(reference)


def test_res37_relative_displacement_has_explicit_zero_origin_and_is_not_absolute_com_height() -> (
    None
):
    _, total, weight, contract = _mechanics_fixture(
        "mechanics-displacement",
        (1.0, 1.0, 1.0, 3.0, 3.0),
        weighing_end_index=3,
    )
    net = derive_net_vertical_force(total, weight, contract)
    assert isinstance(net, NetVerticalForceResult)
    mass = derive_physical_system_mass(weight, _local_gravity("displacement"))
    assert isinstance(mass, PhysicalSystemMassResult)
    acceleration = derive_supported_system_com_acceleration(net, mass, contract)
    assert isinstance(acceleration, SupportedSystemComAccelerationResult)
    interval = CMJIntegrationInterval.explicit_sample(acceleration.series.series_id, 2, 4)
    condition = QualifiedZeroVelocityReference.from_system_weight(weight, 2)
    velocity = derive_supported_system_com_velocity(acceleration, interval, condition)
    assert isinstance(velocity, SupportedSystemComVelocityResult)
    missing = derive_supported_system_com_relative_vertical_displacement(velocity, None)
    assert isinstance(missing, RefusalResult)
    assert RefusalReasonCode.DISPLACEMENT_REFERENCE_UNRESOLVED in missing.reason_codes
    origin = DisplacementOrigin.zero_at_velocity_start(
        velocity.series.series_id, velocity.series.sample_start_index
    )
    displacement = derive_supported_system_com_relative_vertical_displacement(velocity, origin)

    assert isinstance(displacement, SupportedSystemComRelativeDisplacementResult)
    assert displacement.samples == pytest.approx((0.0, 0.0000005, 0.0000025))
    assert displacement.series.unit.identifier.stable_id.endswith("unit:meter@1.0.0")
    assert "relative" in origin.coordinate_reference
    assert "anatomical" in origin.coordinate_reference
    assert "ABSOLUTE_COM_POSITION" not in canonical_json(displacement)


def test_res37_loaded_system_rejects_unresolved_force_model() -> None:
    _, total, weight, contract = _mechanics_fixture(
        "mechanics-loaded",
        (101.0, 101.0, 103.0, 103.0),
        external_loading="supported-barbell",
    )
    net = derive_net_vertical_force(total, weight, contract)
    assert isinstance(net, NetVerticalForceResult)
    assert net.system_contract.includes_supported_external_load
    assert "athlete plus supported external load" in net.system_contract.system_description
    assert "ATHLETE_COM" not in canonical_json(net)

    incomplete = replace(contract, gravity_is_only_other_material_vertical_external_force=False)
    refused = derive_net_vertical_force(total, weight, incomplete)
    assert isinstance(refused, RefusalResult)
    assert RefusalReasonCode.EXTERNAL_FORCE_MODEL_UNRESOLVED in refused.reason_codes


def test_res37_protocol_external_loading_must_be_supported_by_the_contract() -> None:
    _, total, weight, contract = _mechanics_fixture(
        "mechanics-anchored-elastic",
        (101.0, 101.0, 103.0, 103.0),
        external_loading="anchored-elastic",
    )
    refused = derive_net_vertical_force(total, weight, contract)

    assert isinstance(refused, RefusalResult)
    assert RefusalReasonCode.EXTERNAL_FORCE_MODEL_UNRESOLVED in refused.reason_codes


def test_res37_acceleration_contract_cannot_change_after_net_force_is_derived() -> None:
    _, total, weight, contract = _mechanics_fixture("mechanics-contract-link", (1.0, 1.0, 3.0, 3.0))
    net = derive_net_vertical_force(total, weight, contract)
    assert isinstance(net, NetVerticalForceResult)
    mass = derive_physical_system_mass(weight, _local_gravity("contract-link"))
    assert isinstance(mass, PhysicalSystemMassResult)
    changed_contract = replace(contract, system_description="a different declared boundary")

    refused = derive_supported_system_com_acceleration(net, mass, changed_contract)

    assert isinstance(refused, RefusalResult)
    assert RefusalReasonCode.MECHANICAL_SYSTEM_UNRESOLVED in refused.reason_codes


def test_res37_consistency_impulse_over_mass_equals_velocity_change() -> None:
    _, total, weight, contract = _mechanics_fixture(
        "mechanics-consistency",
        (1.0, 1.0, 1.0, 3.0, 3.0),
        weighing_end_index=3,
    )
    net = derive_net_vertical_force(total, weight, contract)
    assert isinstance(net, NetVerticalForceResult)
    interval = CMJIntegrationInterval.explicit_sample(net.series.series_id, 2, 4)
    impulse = integrate_net_vertical_impulse(net, interval)
    mass = derive_physical_system_mass(weight, _local_gravity("consistency"))
    assert isinstance(mass, PhysicalSystemMassResult)
    acceleration = derive_supported_system_com_acceleration(net, mass, contract)
    assert isinstance(acceleration, SupportedSystemComAccelerationResult)
    velocity_interval = CMJIntegrationInterval.explicit_sample(acceleration.series.series_id, 2, 4)
    reference = QualifiedZeroVelocityReference.from_system_weight(weight, 2)
    velocity = derive_supported_system_com_velocity(
        acceleration,
        velocity_interval,
        reference,
    )
    assert isinstance(impulse, NetVerticalImpulseResult)
    assert isinstance(velocity, SupportedSystemComVelocityResult)
    assert impulse.value_ns / mass.value_kg == pytest.approx(velocity.samples[-1])


def test_res37_mechanics_objects_roundtrip_under_serialization_v3() -> None:
    _, total, weight, contract = _mechanics_fixture(
        "mechanics-roundtrip",
        (1.0, 1.0, 1.0, 3.0, 3.0),
        weighing_end_index=3,
    )
    net = derive_net_vertical_force(total, weight, contract)
    assert isinstance(net, NetVerticalForceResult)
    impulse_interval = CMJIntegrationInterval.explicit_sample(net.series.series_id, 2, 4)
    impulse = integrate_net_vertical_impulse(net, impulse_interval)
    mass = derive_physical_system_mass(weight, _local_gravity("roundtrip"))
    assert isinstance(mass, PhysicalSystemMassResult)
    acceleration = derive_supported_system_com_acceleration(net, mass, contract)
    assert isinstance(acceleration, SupportedSystemComAccelerationResult)
    velocity_interval = CMJIntegrationInterval.explicit_sample(acceleration.series.series_id, 2, 4)
    reference = QualifiedZeroVelocityReference.from_system_weight(weight, 2)
    velocity = derive_supported_system_com_velocity(
        acceleration,
        velocity_interval,
        reference,
    )
    assert isinstance(velocity, SupportedSystemComVelocityResult)
    displacement = derive_supported_system_com_relative_vertical_displacement(
        velocity,
        DisplacementOrigin.zero_at_velocity_start(
            velocity.series.series_id, velocity.series.sample_start_index
        ),
    )
    assert isinstance(displacement, SupportedSystemComRelativeDisplacementResult)
    values = (
        contract,
        impulse_interval,
        reference,
        net,
        impulse,
        mass,
        acceleration,
        velocity,
        displacement,
    )

    for value in values:
        restored = from_canonical_json(canonical_json(value), value.__class__)
        assert restored == value
        assert canonical_json(restored) == canonical_json(value)
    assert SERIALIZATION_VERSION == 3


def test_res46_legacy_velocity_payload_is_not_reinterpreted_under_v3() -> None:
    _, total, weight, contract = _mechanics_fixture(
        "res46-legacy-wire",
        (1.0, 1.0, 1.0, 3.0, 3.0),
        weighing_end_index=3,
    )
    net = derive_net_vertical_force(total, weight, contract)
    assert isinstance(net, NetVerticalForceResult)
    mass = derive_physical_system_mass(weight, _local_gravity("legacy-wire"))
    assert isinstance(mass, PhysicalSystemMassResult)
    acceleration = derive_supported_system_com_acceleration(net, mass, contract)
    assert isinstance(acceleration, SupportedSystemComAccelerationResult)
    interval = CMJIntegrationInterval.explicit_sample(acceleration.series.series_id, 2, 4)
    reference = QualifiedZeroVelocityReference.from_system_weight(weight, 2)
    velocity = derive_supported_system_com_velocity(acceleration, interval, reference)
    assert isinstance(velocity, SupportedSystemComVelocityResult)
    legacy = InitialVelocityCondition.zero_at_sample(acceleration.series.series_id, 2)
    legacy_payload = json.loads(canonical_json(legacy))["payload"]
    envelope = json.loads(canonical_json(velocity))
    envelope["payload"]["series"]["initial_velocity_condition"] = legacy_payload
    envelope["payload"]["initial_velocity_condition"] = legacy_payload

    with pytest.raises(SerializationError):
        from_canonical_json(
            json.dumps(envelope, ensure_ascii=False, separators=(",", ":"), sort_keys=True),
            SupportedSystemComVelocityResult,
        )


def test_res37_mechanics_comparability_keeps_method_and_timebase_identity() -> None:
    first = _mechanics_fixture(
        "mechanics-comparable-a", (1.0, 1.0, 3.0, 3.0), timebase=RegularTimebase(1000.0)
    )
    second = _mechanics_fixture(
        "mechanics-comparable-b", (1.0, 1.0, 3.0, 3.0), timebase=RegularTimebase(1000.0)
    )
    first_net = derive_net_vertical_force(first[1], first[2], first[3])
    second_net = derive_net_vertical_force(second[1], second[2], second[3])
    assert isinstance(first_net, NetVerticalForceResult)
    assert isinstance(second_net, NetVerticalForceResult)
    comparable = compare_cmj_mechanics(
        first_net,
        second_net,
        claim="compare net vertical force",
        request_id=InstanceIdentifier("comparability-request", "mechanics-comparable"),
    )
    assert comparable.state is ComparabilityState.COMPARABLE
    shifted = _mechanics_fixture(
        "mechanics-comparable-shifted",
        (1.0, 1.0, 3.0, 3.0),
        timebase=RegularTimebase(500.0),
    )
    shifted_net = derive_net_vertical_force(shifted[1], shifted[2], shifted[3])
    assert isinstance(shifted_net, NetVerticalForceResult)
    not_comparable = compare_cmj_mechanics(
        first_net,
        shifted_net,
        claim="compare net vertical force",
        request_id=InstanceIdentifier("comparability-request", "mechanics-timebase"),
    )
    assert not_comparable.state is ComparabilityState.BRIDGE_VALIDATION_REQUIRED
    assert ComparabilityReasonCode.SAMPLE_OR_TIMEBASE_MISMATCH in not_comparable.reason_codes


def test_res37_downstream_comparability_keeps_upstream_weight_method_identity() -> None:
    first = _mechanics_fixture(
        "mechanics-upstream-method-a",
        (100.0, 100.0, 100.0, 102.0),
    )
    second_source = _rebind_raw_input(
        _cmj_input("mechanics-upstream-method-b"),
        suffix="mechanics-upstream-method-b-bound",
        samples=(100.0, 100.0, 100.0, 102.0),
    )
    second_total = construct_total_supported_vertical_force(second_source)
    assert isinstance(second_total, TotalSupportedForceResult)
    second_segment = WeighingSegment(
        second_total.signal.signal_id,
        second_total.source_artifact.artifact_id,
        second_total.observation.identity.identity_id,
        0,
        3,
    )
    second_weight = estimate_system_weight(second_total, second_segment)
    assert isinstance(second_weight, SystemWeightResult)

    first_net = derive_net_vertical_force(first[1], first[2], first[3])
    second_net = derive_net_vertical_force(second_total, second_weight, first[3])
    assert isinstance(first_net, NetVerticalForceResult)
    assert isinstance(second_net, NetVerticalForceResult)
    first_mass = derive_physical_system_mass(first[2], _local_gravity("upstream-method"))
    second_mass = derive_physical_system_mass(second_weight, _local_gravity("upstream-method"))
    assert isinstance(first_mass, PhysicalSystemMassResult)
    assert isinstance(second_mass, PhysicalSystemMassResult)
    first_acceleration = derive_supported_system_com_acceleration(first_net, first_mass, first[3])
    second_acceleration = derive_supported_system_com_acceleration(
        second_net, second_mass, first[3]
    )
    assert isinstance(first_acceleration, SupportedSystemComAccelerationResult)
    assert isinstance(second_acceleration, SupportedSystemComAccelerationResult)

    comparison = compare_cmj_mechanics(
        first_acceleration,
        second_acceleration,
        claim="compare supported-system COM acceleration",
        request_id=InstanceIdentifier("comparability-request", "mechanics-upstream-method"),
    )

    assert comparison.state is ComparabilityState.BRIDGE_VALIDATION_REQUIRED
    assert ComparabilityReasonCode.METHOD_MISMATCH in comparison.reason_codes


def test_res46_comparability_distinguishes_zero_reference_selection_at_same_start() -> None:
    def build_velocity(suffix: str, selection_label: str) -> SupportedSystemComVelocityResult:
        _, total, weight, contract = _mechanics_fixture(
            suffix,
            (1.0, 1.0, 1.0, 3.0, 3.0),
            weighing_end_index=3,
            weighing_selection_parameters=(MetadataEntry("selection_label", selection_label),),
        )
        net = derive_net_vertical_force(total, weight, contract)
        assert isinstance(net, NetVerticalForceResult)
        mass = derive_physical_system_mass(weight, _local_gravity("comparability"))
        assert isinstance(mass, PhysicalSystemMassResult)
        acceleration = derive_supported_system_com_acceleration(net, mass, contract)
        assert isinstance(acceleration, SupportedSystemComAccelerationResult)
        interval = CMJIntegrationInterval.explicit_sample(acceleration.series.series_id, 2, 4)
        reference = QualifiedZeroVelocityReference.from_system_weight(weight, 2)
        velocity = derive_supported_system_com_velocity(acceleration, interval, reference)
        assert isinstance(velocity, SupportedSystemComVelocityResult)
        return velocity

    first = build_velocity("res46-comparable-first", "first")
    second = build_velocity("res46-comparable-second", "second")
    comparison = compare_cmj_mechanics(
        first,
        second,
        claim="compare supported-system COM velocity",
        request_id=InstanceIdentifier("comparability-request", "res46-zero-reference"),
    )

    assert comparison.state is ComparabilityState.BRIDGE_VALIDATION_REQUIRED
    assert ComparabilityReasonCode.ZERO_VELOCITY_REFERENCE_MISMATCH in comparison.reason_codes
    refused = refusal_for_cmj_mechanics_comparability(
        comparison,
        blocked_claim="compare supported-system COM velocity",
        observation_ids=(first.observation.observation_id, second.observation.observation_id),
    )
    assert isinstance(refused, RefusalResult)
    assert RefusalReasonCode.ZERO_VELOCITY_REFERENCE_MISMATCH in refused.reason_codes


def test_res37_no_phase_or_jump_height_operation_is_exposed() -> None:
    import dynamislm.measurement.cmj as cmj

    assert set(CMJMechanicsQuantity) == {
        CMJMechanicsQuantity.NET_VERTICAL_FORCE,
        CMJMechanicsQuantity.SUPPORTED_SYSTEM_COM_VERTICAL_ACCELERATION,
        CMJMechanicsQuantity.SUPPORTED_SYSTEM_COM_VERTICAL_VELOCITY,
        CMJMechanicsQuantity.SUPPORTED_SYSTEM_COM_RELATIVE_VERTICAL_DISPLACEMENT,
    }
    assert not hasattr(cmj, "estimate_jump_height")
    assert not hasattr(cmj, "detect_braking_phase")
    assert not hasattr(cmj, "detect_propulsive_phase")
