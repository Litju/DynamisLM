from __future__ import annotations

import datetime as datetime_module
from dataclasses import FrozenInstanceError, replace

import pytest

from dynamislm import (
    AcquisitionRecord,
    InstanceIdentifier,
    MeasurementIdentity,
    ObservationContext,
    ProcessingIdentity,
    RegistryReference,
    SamplingCharacteristics,
    ScientificIdentifier,
    ScientificMeasurementObservation,
    SignConvention,
    SourceArtifact,
    StructuredOutputReference,
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
    CMJ_TEST_FAMILY,
    KILONEWTON,
    NEWTON,
    AcquisitionArrangement,
    ArtifactStatus,
    ChannelRole,
    CMJAcquisitionIdentity,
    CMJChannelIdentity,
    CMJComparabilityRequest,
    CMJComputation,
    CMJMeasurementIdentity,
    CMJProtocolAttribute,
    CMJProtocolIdentity,
    CMJSemanticIdentity,
    CMJSourceArtifact,
    CMJValidationCode,
    CMJValidationResult,
    CombinationLineage,
    CombinationLineageKind,
    ExplicitTimebase,
    RawVerticalForceSignal,
    ReferenceMetadata,
    ReferenceState,
    RegularTimebase,
    SignalProcessingState,
    SignalTimebase,
    TimebaseIdentity,
    TimebaseKind,
    assess_cmj_acquisition_comparability,
    create_cmj_raw_observation,
    refusal_for_cmj_comparability,
    refusal_for_cmj_validation,
    refuse_unregistered_computation,
    source_artifact_for_signal,
    validate_cmj_acquisition,
    validate_raw_vertical_force_signal,
)
from dynamislm.provenance import LineageRelation, Provenance
from dynamislm.refusal import RefusalClass, RefusalReasonCode, RefusalStatus

UTC = datetime_module.UTC


def _reference(object_type: str, key: str, label: str | None = None) -> RegistryReference:
    return RegistryReference(
        identifier=ScientificIdentifier("synthetic", object_type, key, "1.0.0"),
        display_label=label or key,
    )


def _protocol() -> CMJProtocolIdentity:
    return CMJProtocolIdentity(
        reference=_reference("protocol", "cmj-standard", "Synthetic CMJ protocol"),
        arm_use_constraint=CMJProtocolAttribute("arm_use", "restricted"),
        external_loading=CMJProtocolAttribute("external_load", "none"),
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
    protocol = _protocol() if protocol_present else None
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


def test_p1b_public_surface_has_no_downstream_cmj_modules_or_operations() -> None:
    import dynamislm.measurement.cmj as cmj

    assert not hasattr(cmj, "calculate_body_mass")
    assert not hasattr(cmj, "calculate_impulse")
    assert not hasattr(cmj, "detect_movement_onset")
    assert not hasattr(cmj, "estimate_jump_height")
