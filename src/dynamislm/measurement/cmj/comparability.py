"""Claim-relative CMJ acquisition comparability without unregistered bridges."""

from __future__ import annotations

from dataclasses import dataclass

from dynamislm.comparability.models import (
    ComparabilityDecisionSource,
    ComparabilityReasonCode,
    ComparabilityResult,
    ComparabilityState,
    TransformationRequest,
)
from dynamislm.measurement.cmj.acquisition import (
    AcquisitionArrangement,
    CMJAcquisitionIdentity,
    ReferenceState,
    SignalProcessingState,
    TimebaseIdentity,
)
from dynamislm.measurement.cmj.identity import CMJMeasurementIdentity
from dynamislm.measurement.cmj.registry import CMJ_ACQUISITION_COMPARABILITY_RULE
from dynamislm.measurement.identity import InstanceIdentifier
from dynamislm.serialization import register_serializable_type


def _require_text(value: str, field_name: str) -> None:
    if not value or not value.strip():
        raise ValueError(f"{field_name} must not be empty")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class CMJComparabilityRequest:
    """Two CMJ identities evaluated for one explicitly stated claim."""

    request_id: InstanceIdentifier
    left_observation_id: InstanceIdentifier
    right_observation_id: InstanceIdentifier
    left_identity: CMJMeasurementIdentity
    right_identity: CMJMeasurementIdentity
    claim: str
    requested_transformations: tuple[TransformationRequest, ...] = ()

    def __post_init__(self) -> None:
        _require_text(self.claim, "claim")
        if self.left_observation_id == self.right_observation_id:
            raise ValueError("comparability requires two distinct observations")
        if not isinstance(self.requested_transformations, tuple):
            raise ValueError("requested_transformations must be an immutable tuple")


def assess_cmj_acquisition_comparability(
    request: CMJComparabilityRequest,
) -> ComparabilityResult:
    """Apply the registered P1B identity rule; never infer device equivalence."""

    missing = _missing_information(request.left_identity, "left") + _missing_information(
        request.right_identity, "right"
    )
    if missing:
        return _result(
            request,
            state=ComparabilityState.INSUFFICIENT_INFORMATION,
            reason_codes=(ComparabilityReasonCode.MISSING_METADATA,),
            missing_information=tuple(dict.fromkeys(missing)),
        )

    differences = _identity_differences(request.left_identity, request.right_identity)
    if request.requested_transformations and not differences:
        return _result(
            request,
            state=ComparabilityState.REQUIRES_TRANSFORMATION,
            reason_codes=(ComparabilityReasonCode.TRANSFORMATION_REQUIRED,),
            transformations_required=request.requested_transformations,
            conditions=("the requested registered transformation must be applied first",),
        )
    if differences:
        return _result(
            request,
            state=ComparabilityState.BRIDGE_VALIDATION_REQUIRED,
            reason_codes=(
                ComparabilityReasonCode.BRIDGE_NOT_REGISTERED,
                *(reason for reason, _ in differences),
            ),
            conditions=(
                "a registered deterministic device/method bridge is required before the claim",
            ),
            transformations_required=request.requested_transformations,
        )
    return _result(request, state=ComparabilityState.COMPARABLE)


def compare_cmj_measurement_identities(
    left_identity: CMJMeasurementIdentity,
    right_identity: CMJMeasurementIdentity,
    *,
    claim: str,
    request_id: InstanceIdentifier,
    left_observation_id: InstanceIdentifier,
    right_observation_id: InstanceIdentifier,
    requested_transformations: tuple[TransformationRequest, ...] = (),
) -> ComparabilityResult:
    """Convenience constructor for a claim-relative CMJ identity request."""

    return assess_cmj_acquisition_comparability(
        CMJComparabilityRequest(
            request_id=request_id,
            left_observation_id=left_observation_id,
            right_observation_id=right_observation_id,
            left_identity=left_identity,
            right_identity=right_identity,
            claim=claim,
            requested_transformations=requested_transformations,
        )
    )


def _result(
    request: CMJComparabilityRequest,
    *,
    state: ComparabilityState,
    reason_codes: tuple[str, ...] = (),
    conditions: tuple[str, ...] = (),
    transformations_required: tuple[TransformationRequest, ...] = (),
    missing_information: tuple[str, ...] = (),
) -> ComparabilityResult:
    return ComparabilityResult(
        result_id=InstanceIdentifier(
            "comparability-result", f"{request.request_id.value}:{state.value.lower()}"
        ),
        request_id=request.request_id,
        state=state,
        reason_codes=reason_codes,
        conditions=conditions,
        transformations_required=transformations_required,
        missing_information=missing_information,
        rule_reference=CMJ_ACQUISITION_COMPARABILITY_RULE,
        evidence_references=(),
        decided_by=ComparabilityDecisionSource.DETERMINISTIC_RULE,
    )


def _missing_information(identity: CMJMeasurementIdentity, side: str) -> tuple[str, ...]:
    acquisition = identity.acquisition
    missing: list[str] = []
    prefix = f"{side}.acquisition"
    if identity.semantic.protocol is None:
        missing.append(f"{side}.protocol identity")
    if acquisition.device is None:
        missing.append(f"{prefix}.device")
    if acquisition.measuring_system is None:
        missing.append(f"{prefix}.measuring_system")
    if acquisition.raw_artifact is None:
        missing.append(f"{prefix}.raw_artifact")
    if acquisition.arrangement is None:
        missing.append(f"{prefix}.arrangement")
    if acquisition.channel is None:
        missing.append(f"{prefix}.channel")
    if acquisition.acquisition_instance_id is None:
        missing.append(f"{prefix}.acquisition_instance_id")
    if acquisition.physical_axis is None:
        missing.append(f"{prefix}.physical_axis")
    if acquisition.reference_frame is None:
        missing.append(f"{prefix}.reference_frame")
    if acquisition.unit is None:
        missing.append(f"{prefix}.unit")
    if acquisition.sign_convention is None or (
        acquisition.sign_convention.reference is None
        and acquisition.sign_convention.positive_direction is None
    ):
        missing.append(f"{prefix}.sign_convention")
    if acquisition.timebase is None:
        missing.append(f"{prefix}.timebase")
    if acquisition.acquisition_software_version is None:
        missing.append(f"{prefix}.acquisition_software_version")
    if acquisition.acquisition_timestamp is None:
        missing.append(f"{prefix}.acquisition_timestamp")
    if acquisition.processing_state is SignalProcessingState.UNKNOWN:
        missing.append(f"{prefix}.processing_state")
    if acquisition.calibration.status is ReferenceState.UNKNOWN:
        missing.append(f"{prefix}.calibration state")
    if acquisition.zeroing.status is ReferenceState.UNKNOWN:
        missing.append(f"{prefix}.zeroing state")
    if acquisition.arrangement is AcquisitionArrangement.BILATERAL_SEPARATE and not {
        "LEFT_FORCE_PLATFORM",
        "RIGHT_FORCE_PLATFORM",
    } <= {channel.role.value for channel in acquisition.available_channels}:
        missing.append(f"{prefix}.left_and_right_channels")
    if acquisition.arrangement is AcquisitionArrangement.BILATERAL_PRECOMBINED and (
        acquisition.combination_lineage is None
    ):
        missing.append(f"{prefix}.combination_lineage")
    if acquisition.arrangement is AcquisitionArrangement.OTHER_REGISTERED_ARRANGEMENT and (
        acquisition.arrangement_reference is None
    ):
        missing.append(f"{prefix}.arrangement_reference")
    return tuple(missing)


def _identity_differences(
    left: CMJMeasurementIdentity,
    right: CMJMeasurementIdentity,
) -> tuple[tuple[str, str], ...]:
    left_acquisition = left.acquisition
    right_acquisition = right.acquisition
    differences: list[tuple[str, str]] = []
    if _protocol_key(left) != _protocol_key(right):
        differences.append((ComparabilityReasonCode.PROTOCOL_MISMATCH, "protocol"))
    if _device_key(left_acquisition) != _device_key(right_acquisition):
        differences.append((ComparabilityReasonCode.DEVICE_MISMATCH, "device"))
    if left_acquisition.arrangement != right_acquisition.arrangement:
        differences.append((ComparabilityReasonCode.ARRANGEMENT_MISMATCH, "arrangement"))
    if _channel_key(left_acquisition) != _channel_key(right_acquisition):
        differences.append((ComparabilityReasonCode.CHANNEL_MISMATCH, "channel"))
    if _reference_key(left_acquisition.physical_axis) != _reference_key(
        right_acquisition.physical_axis
    ):
        differences.append((ComparabilityReasonCode.AXIS_MISMATCH, "physical_axis"))
    if _reference_key(left_acquisition.reference_frame) != _reference_key(
        right_acquisition.reference_frame
    ):
        differences.append((ComparabilityReasonCode.REFERENCE_FRAME_MISMATCH, "reference_frame"))
    if _reference_key(left_acquisition.unit) != _reference_key(right_acquisition.unit):
        differences.append((ComparabilityReasonCode.UNIT_OR_NORMALIZATION_MISMATCH, "unit"))
    if _sign_key(left_acquisition) != _sign_key(right_acquisition):
        differences.append((ComparabilityReasonCode.SIGN_CONVENTION_MISMATCH, "sign_convention"))
    if _timebase_key(left_acquisition.timebase) != _timebase_key(right_acquisition.timebase):
        differences.append((ComparabilityReasonCode.SAMPLE_OR_TIMEBASE_MISMATCH, "timebase"))
    if left_acquisition.processing_state != right_acquisition.processing_state:
        differences.append((ComparabilityReasonCode.PROCESSING_STATE_MISMATCH, "processing_state"))
    if (
        left_acquisition.acquisition_software_version
        != right_acquisition.acquisition_software_version
    ):
        differences.append(
            (ComparabilityReasonCode.ACQUISITION_SOFTWARE_MISMATCH, "acquisition_software_version")
        )
    if (
        _reference_key(left_acquisition.calibration.reference)
        != _reference_key(right_acquisition.calibration.reference)
        or left_acquisition.calibration.status != right_acquisition.calibration.status
    ):
        differences.append((ComparabilityReasonCode.UNKNOWN_PROVENANCE, "calibration"))
    if (
        _reference_key(left_acquisition.zeroing.reference)
        != _reference_key(right_acquisition.zeroing.reference)
        or left_acquisition.zeroing.status != right_acquisition.zeroing.status
    ):
        differences.append((ComparabilityReasonCode.UNKNOWN_PROVENANCE, "zeroing"))
    if _lineage_key(left_acquisition.combination_lineage) != _lineage_key(
        right_acquisition.combination_lineage
    ):
        differences.append((ComparabilityReasonCode.ARRANGEMENT_MISMATCH, "combination_lineage"))
    return tuple(differences)


def _protocol_key(identity: CMJMeasurementIdentity) -> tuple[object, ...]:
    protocol = identity.semantic.protocol_identity
    if protocol is None:
        return (_reference_key(identity.semantic.protocol),)
    attributes = (
        protocol.arm_use_constraint,
        protocol.external_loading,
        protocol.movement_instruction,
        protocol.start_posture,
        *protocol.additional_attributes,
    )
    attribute_keys = tuple(
        (attribute.name, attribute.value, _reference_key(attribute.unit))
        for attribute in attributes
        if attribute is not None
    )
    return (_reference_key(protocol.reference), tuple(sorted(attribute_keys, key=repr)))


def _device_key(acquisition: CMJAcquisitionIdentity) -> tuple[object, ...]:
    return (
        _reference_key(acquisition.measuring_system),
        _reference_key(acquisition.device),
        _reference_key(acquisition.hardware_firmware),
    )


def _channel_key(acquisition: CMJAcquisitionIdentity) -> tuple[object, ...]:
    selected = acquisition.channel
    return (
        (selected.channel_id, selected.role.value) if selected is not None else None,
        tuple(
            sorted(
                (channel.channel_id, channel.role.value)
                for channel in acquisition.available_channels
            )
        ),
    )


def _sign_key(acquisition: CMJAcquisitionIdentity) -> tuple[object, ...] | None:
    sign = acquisition.sign_convention
    if sign is None:
        return None
    return (_reference_key(sign.reference), sign.positive_direction)


def _timebase_key(timebase: TimebaseIdentity | None) -> tuple[object, ...] | None:
    if timebase is None:
        return None
    return (
        timebase.kind.value,
        timebase.sample_rate_hz,
        _reference_key(timebase.clock_reference),
        timebase.description,
    )


def _lineage_key(lineage: object | None) -> tuple[object, ...] | None:
    if lineage is None:
        return None
    kind = getattr(getattr(lineage, "kind", None), "value", None)
    source_channels = getattr(lineage, "source_channels", ())
    method = _reference_key(getattr(lineage, "method", None))
    return (kind, tuple(source_channels), method)


def _reference_key(reference: object | None) -> str | None:
    if reference is None:
        return None
    identifier = getattr(reference, "identifier", None)
    stable_id = getattr(identifier, "stable_id", None)
    return stable_id if isinstance(stable_id, str) else None
