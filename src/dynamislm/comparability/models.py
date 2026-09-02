"""Claim-relative comparability requests and outcomes."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from dynamislm.measurement.identity import (
    InstanceIdentifier,
    MetadataEntry,
    RegistryReference,
    require_tuple,
)
from dynamislm.serialization import register_serializable_type


def _require_text(value: str, field_name: str) -> None:
    if not value or not value.strip():
        raise ValueError(f"{field_name} must not be empty")


class ComparabilityState(StrEnum):
    COMPARABLE = "COMPARABLE"
    COMPARABLE_WITH_CONDITIONS = "COMPARABLE_WITH_CONDITIONS"
    REQUIRES_TRANSFORMATION = "REQUIRES_TRANSFORMATION"
    BRIDGE_VALIDATION_REQUIRED = "BRIDGE_VALIDATION_REQUIRED"
    NOT_COMPARABLE = "NOT_COMPARABLE"
    INSUFFICIENT_INFORMATION = "INSUFFICIENT_INFORMATION"


class ComparabilityDecisionSource(StrEnum):
    DETERMINISTIC_RULE = "DETERMINISTIC_RULE"
    UNRESOLVED = "UNRESOLVED"


class ComparabilityReasonCode(StrEnum):
    COMPARABILITY_NOT_REGISTERED = "COMPARABILITY_NOT_REGISTERED"
    MISSING_METADATA = "MISSING_METADATA"
    IDENTITY_MISMATCH = "IDENTITY_MISMATCH"
    MEASURAND_MISMATCH = "MEASURAND_MISMATCH"
    METHOD_MISMATCH = "METHOD_MISMATCH"
    UNIT_OR_NORMALIZATION_MISMATCH = "UNIT_OR_NORMALIZATION_MISMATCH"
    BRIDGE_NOT_REGISTERED = "BRIDGE_NOT_REGISTERED"
    TRANSFORMATION_REQUIRED = "TRANSFORMATION_REQUIRED"
    CONDITIONS_APPLY = "CONDITIONS_APPLY"
    PROTOCOL_MISMATCH = "PROTOCOL_MISMATCH"
    DEVICE_MISMATCH = "DEVICE_MISMATCH"
    ARRANGEMENT_MISMATCH = "ARRANGEMENT_MISMATCH"
    CHANNEL_MISMATCH = "CHANNEL_MISMATCH"
    AXIS_MISMATCH = "AXIS_MISMATCH"
    REFERENCE_FRAME_MISMATCH = "REFERENCE_FRAME_MISMATCH"
    SIGN_CONVENTION_MISMATCH = "SIGN_CONVENTION_MISMATCH"
    SAMPLE_OR_TIMEBASE_MISMATCH = "SAMPLE_OR_TIMEBASE_MISMATCH"
    PROCESSING_STATE_MISMATCH = "PROCESSING_STATE_MISMATCH"
    ACQUISITION_SOFTWARE_MISMATCH = "ACQUISITION_SOFTWARE_MISMATCH"
    UNKNOWN_PROVENANCE = "UNKNOWN_PROVENANCE"
    WEIGHING_SEGMENT_MISMATCH = "WEIGHING_SEGMENT_MISMATCH"
    ESTIMATOR_MISMATCH = "ESTIMATOR_MISMATCH"
    TOTAL_FORCE_CONSTRUCTION_MISMATCH = "TOTAL_FORCE_CONSTRUCTION_MISMATCH"
    MASS_MEASURAND_MISMATCH = "MASS_MEASURAND_MISMATCH"
    GRAVITY_REFERENCE_MISMATCH = "GRAVITY_REFERENCE_MISMATCH"
    SYSTEM_DEFINITION_MISMATCH = "SYSTEM_DEFINITION_MISMATCH"
    BODY_MASS_CLAIM_UNSUPPORTED = "BODY_MASS_CLAIM_UNSUPPORTED"
    EVENT_DEFINITION_MISMATCH = "EVENT_DEFINITION_MISMATCH"
    EVENT_METHOD_MISMATCH = "EVENT_METHOD_MISMATCH"
    EVENT_PARAMETER_MISMATCH = "EVENT_PARAMETER_MISMATCH"
    SOURCE_PROCESSING_MISMATCH = "SOURCE_PROCESSING_MISMATCH"


@register_serializable_type
@dataclass(frozen=True, slots=True)
class TransformationRequest:
    """Request for a registered deterministic transformation, not a verdict."""

    operation: RegistryReference
    parameters: tuple[MetadataEntry, ...] = ()

    def __post_init__(self) -> None:
        require_tuple(self.parameters, "parameters")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class ComparabilityRequest:
    """Claim-relative candidate pair and explicitly requested transformations."""

    request_id: InstanceIdentifier
    left_observation_id: InstanceIdentifier
    right_observation_id: InstanceIdentifier
    claim: str
    requested_transformations: tuple[TransformationRequest, ...] = ()
    material_dimensions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        require_tuple(self.requested_transformations, "requested_transformations")
        require_tuple(self.material_dimensions, "material_dimensions")
        _require_text(self.claim, "claim")
        if self.left_observation_id == self.right_observation_id:
            raise ValueError("comparability requires two distinct observations")
        if any(not dimension.strip() for dimension in self.material_dimensions):
            raise ValueError("material dimensions must not contain empty strings")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class ComparabilityResult:
    """Authoritative or explicitly unresolved result of a comparability check."""

    result_id: InstanceIdentifier
    request_id: InstanceIdentifier
    state: ComparabilityState
    reason_codes: tuple[str, ...]
    conditions: tuple[str, ...]
    transformations_required: tuple[TransformationRequest, ...]
    missing_information: tuple[str, ...]
    rule_reference: RegistryReference | None
    evidence_references: tuple[RegistryReference, ...]
    decided_by: ComparabilityDecisionSource

    def __post_init__(self) -> None:
        for field_name, value in (
            ("reason_codes", self.reason_codes),
            ("conditions", self.conditions),
            ("transformations_required", self.transformations_required),
            ("missing_information", self.missing_information),
            ("evidence_references", self.evidence_references),
        ):
            require_tuple(value, field_name)
        if any(not code.strip() for code in self.reason_codes):
            raise ValueError("comparability reason codes must not be empty")
        if any(not condition.strip() for condition in self.conditions):
            raise ValueError("comparability conditions must not be empty")
        if any(not item.strip() for item in self.missing_information):
            raise ValueError("missing information items must not be empty")
        if self.decided_by is ComparabilityDecisionSource.UNRESOLVED:
            if self.state is not ComparabilityState.INSUFFICIENT_INFORMATION:
                raise ValueError("unresolved comparability must be insufficient")
            if self.rule_reference is not None:
                raise ValueError("unresolved comparability cannot claim a rule reference")
            if ComparabilityReasonCode.COMPARABILITY_NOT_REGISTERED not in self.reason_codes:
                raise ValueError("unresolved comparability must state that no rule is registered")
        elif self.rule_reference is None:
            raise ValueError("deterministic comparability must identify its rule")
        if self.state is ComparabilityState.COMPARABLE_WITH_CONDITIONS and not self.conditions:
            raise ValueError("conditional comparability must state its conditions")
        if (
            self.state is ComparabilityState.REQUIRES_TRANSFORMATION
            and not self.transformations_required
        ):
            raise ValueError("transformation state must identify required transformations")

    @classmethod
    def insufficient(
        cls,
        request: ComparabilityRequest,
        *,
        missing_information: tuple[str, ...] = ("registered deterministic comparability rule",),
    ) -> ComparabilityResult:
        return cls(
            result_id=InstanceIdentifier(
                "comparability-result", f"{request.request_id.value}:unresolved"
            ),
            request_id=request.request_id,
            state=ComparabilityState.INSUFFICIENT_INFORMATION,
            reason_codes=(ComparabilityReasonCode.COMPARABILITY_NOT_REGISTERED,),
            conditions=(),
            transformations_required=request.requested_transformations,
            missing_information=missing_information,
            rule_reference=None,
            evidence_references=(),
            decided_by=ComparabilityDecisionSource.UNRESOLVED,
        )
