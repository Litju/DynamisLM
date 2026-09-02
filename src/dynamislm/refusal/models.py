"""Structured claim-specific refusal results."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from dynamislm.measurement.identity import InstanceIdentifier, RegistryReference, require_tuple
from dynamislm.serialization import register_serializable_type


def _require_text(value: str, field_name: str) -> None:
    if not value or not value.strip():
        raise ValueError(f"{field_name} must not be empty")


class RefusalClass(StrEnum):
    IDENTITY_UNRESOLVED = "IDENTITY_UNRESOLVED"
    COMPARABILITY_UNESTABLISHED = "COMPARABILITY_UNESTABLISHED"
    EVIDENCE_SCOPE_UNSUPPORTED = "EVIDENCE_SCOPE_UNSUPPORTED"
    DATA_ADEQUACY_INSUFFICIENT = "DATA_ADEQUACY_INSUFFICIENT"
    ANALYSIS_DESIGN_MISMATCH = "ANALYSIS_DESIGN_MISMATCH"
    UNCERTAINTY_LIMITS_CLAIM = "UNCERTAINTY_LIMITS_CLAIM"
    CAUSAL_IDENTIFICATION_UNSUPPORTED = "CAUSAL_IDENTIFICATION_UNSUPPORTED"
    COMPUTATION_NOT_REGISTERED = "COMPUTATION_NOT_REGISTERED"


class RefusalReasonCode(StrEnum):
    COMPARABILITY_NOT_REGISTERED = "COMPARABILITY_NOT_REGISTERED"
    MISSING_METADATA = "MISSING_METADATA"
    METRIC_DEFINITION_MISMATCH = "METRIC_DEFINITION_MISMATCH"
    MEASURAND_MISMATCH = "MEASURAND_MISMATCH"
    DEVICE_COMPARABILITY_NOT_ESTABLISHED = "DEVICE_COMPARABILITY_NOT_ESTABLISHED"
    SOFTWARE_PIPELINE_NOT_ESTABLISHED = "SOFTWARE_PIPELINE_NOT_ESTABLISHED"
    LONGITUDINAL_DATA_INSUFFICIENT = "LONGITUDINAL_DATA_INSUFFICIENT"
    BETWEEN_WITHIN_MISMATCH = "BETWEEN_WITHIN_MISMATCH"
    UNCERTAINTY_INADEQUATE = "UNCERTAINTY_INADEQUATE"
    CAUSAL_DESIGN_UNSUPPORTED = "CAUSAL_DESIGN_UNSUPPORTED"
    NO_REGISTERED_OPERATION = "NO_REGISTERED_OPERATION"
    PROTOCOL_IDENTITY_MISSING = "PROTOCOL_IDENTITY_MISSING"
    DEVICE_IDENTITY_MISSING = "DEVICE_IDENTITY_MISSING"
    MEASURING_SYSTEM_MISSING = "MEASURING_SYSTEM_MISSING"
    CHANNEL_IDENTITY_MISSING = "CHANNEL_IDENTITY_MISSING"
    AXIS_OR_FRAME_MISSING = "AXIS_OR_FRAME_MISSING"
    SIGN_CONVENTION_MISSING = "SIGN_CONVENTION_MISSING"
    SAMPLING_METADATA_MISSING = "SAMPLING_METADATA_MISSING"
    PROCESSING_STATE_UNKNOWN = "PROCESSING_STATE_UNKNOWN"
    SOURCE_ARTIFACT_UNVERIFIED = "SOURCE_ARTIFACT_UNVERIFIED"
    ACQUISITION_ARRANGEMENT_MISMATCH = "ACQUISITION_ARRANGEMENT_MISMATCH"
    AXIS_OR_FRAME_MISMATCH = "AXIS_OR_FRAME_MISMATCH"
    SIGN_CONVENTION_MISMATCH = "SIGN_CONVENTION_MISMATCH"
    DEVICE_BRIDGE_NOT_REGISTERED = "DEVICE_BRIDGE_NOT_REGISTERED"
    INVALID_TIMEBASE = "INVALID_TIMEBASE"
    NONFINITE_SIGNAL = "NONFINITE_SIGNAL"
    TRANSFORMATION_REQUIRED = "TRANSFORMATION_REQUIRED"
    PROTOCOL_IDENTITY_MISMATCH = "PROTOCOL_IDENTITY_MISMATCH"
    UNIT_OR_NORMALIZATION_MISMATCH = "UNIT_OR_NORMALIZATION_MISMATCH"
    SAMPLE_OR_TIMEBASE_MISMATCH = "SAMPLE_OR_TIMEBASE_MISMATCH"
    WEIGHING_SEGMENT_MISSING = "WEIGHING_SEGMENT_MISSING"
    WEIGHING_SEGMENT_INVALID = "WEIGHING_SEGMENT_INVALID"
    INSUFFICIENT_WEIGHING_SAMPLES = "INSUFFICIENT_WEIGHING_SAMPLES"
    BILATERAL_INPUTS_REQUIRED = "BILATERAL_INPUTS_REQUIRED"
    BILATERAL_INPUTS_INCOMPATIBLE = "BILATERAL_INPUTS_INCOMPATIBLE"
    TIMEBASE_NOT_SYNCHRONIZED = "TIMEBASE_NOT_SYNCHRONIZED"
    SAMPLE_SUPPORT_MISMATCH = "SAMPLE_SUPPORT_MISMATCH"
    FORCE_UNIT_TRANSFORMATION_REQUIRED = "FORCE_UNIT_TRANSFORMATION_REQUIRED"
    SIGN_OR_FRAME_UNRESOLVED = "SIGN_OR_FRAME_UNRESOLVED"
    PROCESSING_LINEAGE_UNRESOLVED = "PROCESSING_LINEAGE_UNRESOLVED"
    GRAVITY_REFERENCE_MISSING = "GRAVITY_REFERENCE_MISSING"
    GRAVITY_REFERENCE_INVALID = "GRAVITY_REFERENCE_INVALID"
    SYSTEM_DEFINITION_UNRESOLVED = "SYSTEM_DEFINITION_UNRESOLVED"
    BODY_MASS_CLAIM_UNSUPPORTED = "BODY_MASS_CLAIM_UNSUPPORTED"


class RefusalStatus(StrEnum):
    REFUSED = "REFUSED"
    PARTIALLY_REFUSED = "PARTIALLY_REFUSED"


@register_serializable_type
@dataclass(frozen=True, slots=True)
class RefusalResult:
    """Blocks one claim while retaining safe independent descriptions."""

    refusal_id: InstanceIdentifier
    status: RefusalStatus
    refusal_class: RefusalClass
    blocked_claim: str
    reason_codes: tuple[str, ...]
    missing_information: tuple[str, ...]
    what_can_still_be_safely_described: tuple[str, ...]
    evidence_references: tuple[RegistryReference, ...] = ()
    observation_ids: tuple[InstanceIdentifier, ...] = ()

    def __post_init__(self) -> None:
        for field_name, value in (
            ("reason_codes", self.reason_codes),
            ("missing_information", self.missing_information),
            ("what_can_still_be_safely_described", self.what_can_still_be_safely_described),
            ("evidence_references", self.evidence_references),
            ("observation_ids", self.observation_ids),
        ):
            require_tuple(value, field_name)
        _require_text(self.blocked_claim, "blocked_claim")
        for field_name, values in (
            ("reason_codes", self.reason_codes),
            ("missing_information", self.missing_information),
            ("what_can_still_be_safely_described", self.what_can_still_be_safely_described),
        ):
            if any(not value.strip() for value in values):
                raise ValueError(f"{field_name} must not contain empty strings")

    @property
    def blocks_claim(self) -> bool:
        return True
