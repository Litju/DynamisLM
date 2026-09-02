"""CMJ acquisition and event refusals that preserve safe descriptions."""

from __future__ import annotations

from enum import StrEnum

from dynamislm.comparability.models import (
    ComparabilityReasonCode,
    ComparabilityResult,
    ComparabilityState,
)
from dynamislm.measurement.cmj.validation import (
    CMJValidationCode,
    CMJValidationResult,
    ValidationStatus,
)
from dynamislm.measurement.identity import InstanceIdentifier
from dynamislm.refusal.models import (
    RefusalClass,
    RefusalReasonCode,
    RefusalResult,
    RefusalStatus,
)
from dynamislm.serialization import canonical_hash


class CMJComputation(StrEnum):
    BODY_SYSTEM_MASS = "BODY_SYSTEM_MASS"
    IMPULSE = "IMPULSE"
    JUMP_HEIGHT = "JUMP_HEIGHT"


def refusal_for_cmj_validation(
    validation: CMJValidationResult,
    *,
    blocked_claim: str = "register this CMJ force-platform acquisition as valid",
    observation_ids: tuple[InstanceIdentifier, ...] = (),
) -> RefusalResult | None:
    """Map acquisition validation failures to the sealed refusal architecture."""

    if validation.status is ValidationStatus.VALID:
        return None
    identity_codes = {
        CMJValidationCode.MISSING_PROTOCOL_IDENTITY,
        CMJValidationCode.MISSING_DEVICE_IDENTITY,
        CMJValidationCode.MISSING_MEASURING_SYSTEM,
        CMJValidationCode.MISSING_ARRANGEMENT,
        CMJValidationCode.MISSING_CHANNEL,
        CMJValidationCode.MISSING_ACQUISITION_INSTANCE,
        CMJValidationCode.MISSING_AXIS,
        CMJValidationCode.MISSING_REFERENCE_FRAME,
        CMJValidationCode.MISSING_UNIT,
        CMJValidationCode.MISSING_SIGN_CONVENTION,
        CMJValidationCode.MISSING_TIMEBASE,
        CMJValidationCode.MISSING_ACQUISITION_SOFTWARE,
        CMJValidationCode.MISSING_ACQUISITION_TIMESTAMP,
        CMJValidationCode.PROCESSING_STATE_UNKNOWN,
        CMJValidationCode.CALIBRATION_STATE_UNKNOWN,
        CMJValidationCode.ZEROING_STATE_UNKNOWN,
        CMJValidationCode.ARTIFACT_METADATA_INSUFFICIENT,
        CMJValidationCode.ARTIFACT_ACQUISITION_LINK_MISSING,
        CMJValidationCode.ARTIFACT_NOT_IMMUTABLE,
        CMJValidationCode.ARTIFACT_HASH_INVALID,
        CMJValidationCode.ARTIFACT_HASH_MISMATCH,
        CMJValidationCode.ARTIFACT_HASH_UNVERIFIED,
        CMJValidationCode.COMBINATION_LINEAGE_MISSING,
        CMJValidationCode.MISSING_ARRANGEMENT_REFERENCE,
    }
    refusal_class = (
        RefusalClass.IDENTITY_UNRESOLVED
        if any(issue.code in identity_codes for issue in validation.issues)
        else RefusalClass.DATA_ADEQUACY_INSUFFICIENT
    )
    reason_codes = tuple(
        dict.fromkeys(_validation_reason(issue.code) for issue in validation.issues)
    )
    missing_information = tuple(dict.fromkeys(issue.field for issue in validation.issues))
    status = RefusalStatus.PARTIALLY_REFUSED if observation_ids else RefusalStatus.REFUSED
    refusal_id = InstanceIdentifier(
        "refusal",
        f"cmj-acquisition:{canonical_hash(validation).removeprefix('sha256:')[:24]}",
    )
    return RefusalResult(
        refusal_id=refusal_id,
        status=status,
        refusal_class=refusal_class,
        blocked_claim=blocked_claim,
        reason_codes=reason_codes,
        missing_information=missing_information,
        what_can_still_be_safely_described=(
            "the raw signal and declared acquisition identity may be described independently",
            "no CMJ mechanics or biological performance judgment is authorized by P1B",
        ),
        observation_ids=observation_ids,
    )


def refusal_for_cmj_comparability(
    result: ComparabilityResult,
    *,
    blocked_claim: str,
    observation_ids: tuple[InstanceIdentifier, ...] = (),
) -> RefusalResult | None:
    """Refuse only the blocked comparison while retaining both observations."""

    if result.state is ComparabilityState.COMPARABLE:
        return None
    reason_codes = tuple(
        dict.fromkeys(_comparability_reason(reason_code) for reason_code in result.reason_codes)
    )
    missing_information = result.missing_information
    if result.state is ComparabilityState.BRIDGE_VALIDATION_REQUIRED and not missing_information:
        missing_information = ("registered deterministic acquisition/device bridge",)
    return RefusalResult(
        refusal_id=InstanceIdentifier("refusal", f"cmj-comparability:{result.result_id.value}"),
        status=RefusalStatus.PARTIALLY_REFUSED if observation_ids else RefusalStatus.REFUSED,
        refusal_class=RefusalClass.COMPARABILITY_UNESTABLISHED,
        blocked_claim=blocked_claim,
        reason_codes=reason_codes,
        missing_information=missing_information,
        what_can_still_be_safely_described=(
            "each CMJ observation remains independently describable under its own identity",
            "the comparison is blocked until the stated bridge or metadata is resolved",
        ),
        observation_ids=observation_ids,
    )


def refuse_unregistered_computation(
    computation: CMJComputation | str,
    *,
    observation_ids: tuple[InstanceIdentifier, ...] = (),
) -> RefusalResult:
    """Return a refusal for downstream CMJ science not registered in P1B."""

    requested = CMJComputation(computation)
    labels = {
        CMJComputation.BODY_SYSTEM_MASS: "body/system mass",
        CMJComputation.IMPULSE: "impulse",
        CMJComputation.JUMP_HEIGHT: "jump height",
    }
    label = labels[requested]
    return RefusalResult(
        refusal_id=InstanceIdentifier("refusal", f"cmj-computation:{requested.value.lower()}"),
        status=RefusalStatus.PARTIALLY_REFUSED if observation_ids else RefusalStatus.REFUSED,
        refusal_class=RefusalClass.COMPUTATION_NOT_REGISTERED,
        blocked_claim=f"calculate {label}",
        reason_codes=(RefusalReasonCode.NO_REGISTERED_OPERATION,),
        missing_information=(f"registered deterministic operation for {label}",),
        what_can_still_be_safely_described=(
            "the CMJ acquisition may be described without the requested derived quantity",
        ),
        observation_ids=observation_ids,
    )


def _validation_reason(code: CMJValidationCode) -> str:
    mapping = {
        CMJValidationCode.MISSING_PROTOCOL_IDENTITY: RefusalReasonCode.PROTOCOL_IDENTITY_MISSING,
        CMJValidationCode.MISSING_DEVICE_IDENTITY: RefusalReasonCode.DEVICE_IDENTITY_MISSING,
        CMJValidationCode.MISSING_MEASURING_SYSTEM: RefusalReasonCode.MEASURING_SYSTEM_MISSING,
        CMJValidationCode.MISSING_CHANNEL: RefusalReasonCode.CHANNEL_IDENTITY_MISSING,
        CMJValidationCode.MISSING_AXIS: RefusalReasonCode.AXIS_OR_FRAME_MISSING,
        CMJValidationCode.MISSING_REFERENCE_FRAME: RefusalReasonCode.AXIS_OR_FRAME_MISSING,
        CMJValidationCode.MISSING_SIGN_CONVENTION: RefusalReasonCode.SIGN_CONVENTION_MISSING,
        CMJValidationCode.MISSING_TIMEBASE: RefusalReasonCode.SAMPLING_METADATA_MISSING,
        CMJValidationCode.PROCESSING_STATE_UNKNOWN: RefusalReasonCode.PROCESSING_STATE_UNKNOWN,
        CMJValidationCode.ARTIFACT_HASH_UNVERIFIED: RefusalReasonCode.SOURCE_ARTIFACT_UNVERIFIED,
        CMJValidationCode.ARRANGEMENT_CHANNEL_INCONSISTENT: (
            RefusalReasonCode.ACQUISITION_ARRANGEMENT_MISMATCH
        ),
        CMJValidationCode.COMBINATION_LINEAGE_MISSING: (
            RefusalReasonCode.ACQUISITION_ARRANGEMENT_MISMATCH
        ),
        CMJValidationCode.CHANNEL_MISMATCH: RefusalReasonCode.ACQUISITION_ARRANGEMENT_MISMATCH,
        CMJValidationCode.SIGNAL_SEMANTICS_MISMATCH: RefusalReasonCode.AXIS_OR_FRAME_MISMATCH,
        CMJValidationCode.PROCESSING_STATE_MISMATCH: (
            RefusalReasonCode.SOFTWARE_PIPELINE_NOT_ESTABLISHED
        ),
        CMJValidationCode.DECLARED_SAMPLE_RATE_MISMATCH: RefusalReasonCode.INVALID_TIMEBASE,
        CMJValidationCode.NONFINITE_SAMPLE: RefusalReasonCode.NONFINITE_SIGNAL,
        CMJValidationCode.EMPTY_SIGNAL: RefusalReasonCode.NONFINITE_SIGNAL,
        CMJValidationCode.ARTIFACT_HASH_INVALID: RefusalReasonCode.SOURCE_ARTIFACT_UNVERIFIED,
        CMJValidationCode.ARTIFACT_HASH_MISMATCH: RefusalReasonCode.SOURCE_ARTIFACT_UNVERIFIED,
    }
    return mapping.get(code, RefusalReasonCode.MISSING_METADATA)


def _comparability_reason(reason_code: str) -> str:
    mapping = {
        ComparabilityReasonCode.MISSING_METADATA: RefusalReasonCode.MISSING_METADATA,
        ComparabilityReasonCode.BRIDGE_NOT_REGISTERED: (
            RefusalReasonCode.DEVICE_BRIDGE_NOT_REGISTERED
        ),
        ComparabilityReasonCode.PROTOCOL_MISMATCH: RefusalReasonCode.PROTOCOL_IDENTITY_MISMATCH,
        ComparabilityReasonCode.DEVICE_MISMATCH: RefusalReasonCode.DEVICE_BRIDGE_NOT_REGISTERED,
        ComparabilityReasonCode.ARRANGEMENT_MISMATCH: (
            RefusalReasonCode.ACQUISITION_ARRANGEMENT_MISMATCH
        ),
        ComparabilityReasonCode.CHANNEL_MISMATCH: (
            RefusalReasonCode.ACQUISITION_ARRANGEMENT_MISMATCH
        ),
        ComparabilityReasonCode.AXIS_MISMATCH: RefusalReasonCode.AXIS_OR_FRAME_MISMATCH,
        ComparabilityReasonCode.REFERENCE_FRAME_MISMATCH: RefusalReasonCode.AXIS_OR_FRAME_MISMATCH,
        ComparabilityReasonCode.SIGN_CONVENTION_MISMATCH: (
            RefusalReasonCode.SIGN_CONVENTION_MISMATCH
        ),
        ComparabilityReasonCode.SAMPLE_OR_TIMEBASE_MISMATCH: (
            RefusalReasonCode.SAMPLE_OR_TIMEBASE_MISMATCH
        ),
        ComparabilityReasonCode.UNIT_OR_NORMALIZATION_MISMATCH: (
            RefusalReasonCode.UNIT_OR_NORMALIZATION_MISMATCH
        ),
        ComparabilityReasonCode.PROCESSING_STATE_MISMATCH: (
            RefusalReasonCode.SOFTWARE_PIPELINE_NOT_ESTABLISHED
        ),
        ComparabilityReasonCode.ACQUISITION_SOFTWARE_MISMATCH: (
            RefusalReasonCode.SOFTWARE_PIPELINE_NOT_ESTABLISHED
        ),
        ComparabilityReasonCode.UNKNOWN_PROVENANCE: RefusalReasonCode.SOURCE_ARTIFACT_UNVERIFIED,
        ComparabilityReasonCode.TRANSFORMATION_REQUIRED: RefusalReasonCode.TRANSFORMATION_REQUIRED,
        ComparabilityReasonCode.EVENT_DEFINITION_MISMATCH: (
            RefusalReasonCode.EVENT_DEFINITION_MISMATCH
        ),
        ComparabilityReasonCode.EVENT_METHOD_MISMATCH: RefusalReasonCode.EVENT_METHOD_MISMATCH,
        ComparabilityReasonCode.EVENT_PARAMETER_MISMATCH: (
            RefusalReasonCode.EVENT_PARAMETER_MISMATCH
        ),
        ComparabilityReasonCode.SOURCE_PROCESSING_MISMATCH: (
            RefusalReasonCode.SOURCE_PROCESSING_MISMATCH
        ),
    }
    try:
        normalized = ComparabilityReasonCode(reason_code)
    except ValueError:
        return RefusalReasonCode.COMPARABILITY_NOT_REGISTERED
    return mapping.get(normalized, RefusalReasonCode.COMPARABILITY_NOT_REGISTERED)


def refusal_for_cmj_event_comparability(
    result: ComparabilityResult,
    *,
    blocked_claim: str,
    observation_ids: tuple[InstanceIdentifier, ...] = (),
) -> RefusalResult | None:
    """Refuse an event comparison without flattening its event identities."""

    if result.state is ComparabilityState.COMPARABLE:
        return None
    reason_codes = tuple(
        dict.fromkeys(_comparability_reason(reason_code) for reason_code in result.reason_codes)
    )
    missing_information = result.missing_information or (
        "registered deterministic event comparability bridge or missing metadata",
    )
    return RefusalResult(
        refusal_id=InstanceIdentifier(
            "refusal", f"cmj-event-comparability:{result.result_id.value}"
        ),
        status=RefusalStatus.PARTIALLY_REFUSED if observation_ids else RefusalStatus.REFUSED,
        refusal_class=RefusalClass.COMPARABILITY_UNESTABLISHED,
        blocked_claim=blocked_claim,
        reason_codes=reason_codes,
        missing_information=missing_information,
        what_can_still_be_safely_described=(
            "each event occurrence remains independently describable under its own definition",
            "the event comparison is blocked until the stated method, parameter, or source "
            "identity issue is resolved",
        ),
        observation_ids=observation_ids,
    )
