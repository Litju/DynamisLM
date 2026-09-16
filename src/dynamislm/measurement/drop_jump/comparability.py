"""Claim-relative comparability rules for drop-jump outputs."""

from __future__ import annotations

from dataclasses import dataclass

from dynamislm.comparability.models import (
    ComparabilityDecisionSource,
    ComparabilityReasonCode,
    ComparabilityRequest,
    ComparabilityResult,
    ComparabilityState,
)
from dynamislm.measurement.drop_jump.identity import (
    DropJumpAcquisitionIdentity,
    DropJumpMeasurementIdentity,
    DropJumpProtocolIdentity,
)
from dynamislm.measurement.drop_jump.metrics import DropJumpMetricResult
from dynamislm.measurement.drop_jump.registry import (
    DJ_RSI_JH_CT_METRIC,
    DJ_RSR_FT_CT_METRIC,
    DROP_JUMP_COMPARABILITY_RULE,
    DROP_JUMP_TEST_FAMILY,
    RES68_DECISION_EXPLOSIVE_TEST_FAMILY,
)
from dynamislm.measurement.identity import InstanceIdentifier, _require_instance
from dynamislm.serialization import canonical_hash, register_serializable_type


@register_serializable_type
@dataclass(frozen=True, slots=True)
class DropJumpComparabilityRequest:
    """Typed claim-relative DJ comparison request."""

    request_id: InstanceIdentifier
    left_observation_id: InstanceIdentifier
    right_observation_id: InstanceIdentifier
    claim: str
    material_dimensions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.request_id.instance_type != "comparability-request":
            raise ValueError("request_id must identify a comparability request")
        if self.left_observation_id == self.right_observation_id:
            raise ValueError("DJ comparison requires two observations")
        if not self.claim.strip():
            raise ValueError("DJ comparison claim must not be empty")
        if not isinstance(self.material_dimensions, tuple):
            raise ValueError("material_dimensions must be immutable")
        if any(not item.strip() for item in self.material_dimensions):
            raise ValueError("material dimensions must not be empty")

    def generic(self) -> ComparabilityRequest:
        return ComparabilityRequest(
            request_id=self.request_id,
            left_observation_id=self.left_observation_id,
            right_observation_id=self.right_observation_id,
            claim=self.claim,
            material_dimensions=self.material_dimensions,
        )


def _fallback_observation_id(item: object, side: str) -> InstanceIdentifier:
    if isinstance(item, DropJumpMetricResult):
        try:
            observation_id = item.observation.observation_id
            if isinstance(observation_id, InstanceIdentifier):
                return observation_id
        except (AttributeError, TypeError, ValueError):
            pass
    return InstanceIdentifier("observation", f"invalid-dj-{side}")


def _fallback_request(left: object, right: object, claim: object) -> ComparabilityRequest:
    safe_claim = claim if isinstance(claim, str) and claim.strip() else "invalid DJ comparison"
    left_id = _fallback_observation_id(left, "left")
    right_id = _fallback_observation_id(right, "right")
    if left_id == right_id:
        right_id = InstanceIdentifier("observation", f"{right_id.value}:right-envelope")
    request_id = InstanceIdentifier(
        "comparability-request",
        canonical_hash({"left": left_id, "right": right_id, "claim": safe_claim}).removeprefix(
            "sha256:"
        )[:24],
    )
    return ComparabilityRequest(
        request_id=request_id,
        left_observation_id=left_id,
        right_observation_id=right_id,
        claim=safe_claim,
    )


def _result(
    request: ComparabilityRequest,
    state: ComparabilityState,
    reasons: tuple[ComparabilityReasonCode, ...],
    *,
    missing: tuple[str, ...] = (),
    conditions: tuple[str, ...] = (),
) -> ComparabilityResult:
    digest = canonical_hash(
        {"request": request, "state": state, "reasons": reasons, "missing": missing}
    ).removeprefix("sha256:")[:24]
    return ComparabilityResult(
        result_id=InstanceIdentifier("comparability-result", f"drop-jump:{digest}"),
        request_id=request.request_id,
        state=state,
        reason_codes=tuple(item.value for item in reasons),
        conditions=conditions,
        transformations_required=(),
        missing_information=missing,
        rule_reference=DROP_JUMP_COMPARABILITY_RULE,
        evidence_references=(RES68_DECISION_EXPLOSIVE_TEST_FAMILY,),
        decided_by=ComparabilityDecisionSource.DETERMINISTIC_RULE,
    )


def _is_actual_claim(claim: str) -> bool:
    lowered = claim.lower()
    return any(
        phrase in lowered
        for phrase in (
            "actual drop",
            "drop exposure",
            "drop height normalization",
            "mechanical exposure",
            "realized com drop",
        )
    )


def _protocol_signature(
    protocol: DropJumpProtocolIdentity, *, include_actual: bool
) -> tuple[object, ...]:
    actual = (
        (
            protocol.actual_drop_height_m,
            protocol.actual_drop_height_method,
            protocol.actual_drop_height_source,
        )
        if include_actual
        else ()
    )
    return (
        protocol.reference,
        protocol.protocol_version,
        *actual,
        protocol.nominal_box_height_m,
        protocol.initiation_mode,
        protocol.pre_drop_posture,
        protocol.pre_drop_stillness,
        protocol.step_off_leg,
        protocol.arms_condition,
        protocol.rebound_strategy,
        protocol.explicit_cue,
        protocol.support_platform_configuration,
        protocol.landing_rebound_technique,
        protocol.pause_continuity_semantics,
        protocol.additional_attributes,
    )


def _acquisition_signature(acquisition: DropJumpAcquisitionIdentity) -> tuple[object, ...]:
    return (
        acquisition.device,
        acquisition.provider,
        acquisition.sensor_modality,
        acquisition.sampling,
        acquisition.timebase,
        acquisition.axis_or_frame,
        acquisition.calibration_reference,
        acquisition.hardware_firmware,
    )


def _processing_signature(identity: DropJumpMeasurementIdentity) -> tuple[object, ...]:
    processing = identity.processing
    material_parameters = tuple(
        (item.key, item.value)
        for item in processing.method_parameters
        if item.key
        in {
            "gravity_reference",
            "estimator_definition",
            "numerator_metric",
            "denominator_metric",
            "integration_method",
        }
    )
    return (
        processing.event_definitions,
        processing.phase_definitions,
        processing.estimator,
        processing.registered_operation,
        material_parameters,
        processing.filtering,
        processing.differentiation_method,
        processing.integration_method,
        processing.unit,
        processing.sign_convention,
        processing.normalization,
        processing.trial_selection,
        processing.aggregation,
        processing.timebase,
        processing.processing_state,
    )


def compare_drop_jump_metric_results(
    left: DropJumpMetricResult,
    right: DropJumpMetricResult,
    claim: str = "compare DJ metric results",
) -> ComparabilityResult:
    """Adjudicate two DJ outputs without accepting a manual override."""

    try:
        if not isinstance(claim, str) or not claim.strip():
            raise ValueError("DJ comparison claim must be non-empty text")
        _require_instance(left, DropJumpMetricResult, "left")
        _require_instance(right, DropJumpMetricResult, "right")
        left_token = left.observation.observation_id
        right_token = right.observation.observation_id
        request_id = InstanceIdentifier(
            "comparability-request",
            canonical_hash(
                {
                    "left": left_token,
                    "right": right_token,
                    "claim": claim,
                }
            ).removeprefix("sha256:")[:24],
        )
        request = ComparabilityRequest(
            request_id=request_id,
            left_observation_id=left.observation.observation_id,
            right_observation_id=right.observation.observation_id,
            claim=claim,
            material_dimensions=(
                "protocol",
                "metric",
                "event_method",
                "device",
                "timebase",
                "processing",
            ),
        )
    except (AttributeError, TypeError, ValueError):
        fallback = _fallback_request(left, right, claim)
        missing = (
            ("two distinct observations",)
            if fallback.right_observation_id.value.endswith(":right-envelope")
            else ("two typed DJ metric results",)
        )
        return ComparabilityResult.insufficient(fallback, missing_information=missing)

    left_identity = left.observation.identity
    right_identity = right.observation.identity
    if not isinstance(left_identity, DropJumpMeasurementIdentity) or not isinstance(
        right_identity, DropJumpMeasurementIdentity
    ):
        return _result(
            request,
            ComparabilityState.NOT_COMPARABLE,
            (ComparabilityReasonCode.METRIC_FAMILY_MISMATCH,),
        )
    if (
        left_identity.semantic.test_family != DROP_JUMP_TEST_FAMILY
        or right_identity.semantic.test_family != DROP_JUMP_TEST_FAMILY
    ):
        return _result(
            request,
            ComparabilityState.NOT_COMPARABLE,
            (ComparabilityReasonCode.METRIC_FAMILY_MISMATCH,),
        )
    if left.metric != right.metric:
        if {left.metric, right.metric} == {DJ_RSI_JH_CT_METRIC, DJ_RSR_FT_CT_METRIC}:
            return _result(
                request,
                ComparabilityState.NOT_COMPARABLE,
                (ComparabilityReasonCode.MEASURAND_MISMATCH,),
            )
        return _result(
            request,
            ComparabilityState.BRIDGE_VALIDATION_REQUIRED,
            (ComparabilityReasonCode.METRIC_DEFINITION_MISMATCH,),
        )
    if (
        left_identity.semantic.protocol_identity is None
        or right_identity.semantic.protocol_identity is None
    ):
        return _result(
            request,
            ComparabilityState.INSUFFICIENT_INFORMATION,
            (ComparabilityReasonCode.MISSING_METADATA,),
            missing=("complete DJ protocol identity",),
        )
    left_protocol = left_identity.semantic.protocol_identity
    right_protocol = right_identity.semantic.protocol_identity
    if _is_actual_claim(claim):
        if (
            left_protocol.actual_drop_height_m is None
            or right_protocol.actual_drop_height_m is None
        ):
            return _result(
                request,
                ComparabilityState.INSUFFICIENT_INFORMATION,
                (ComparabilityReasonCode.MISSING_METADATA,),
                missing=("actual drop height independently established for both trials",),
            )
        if left_protocol.actual_drop_height_m != right_protocol.actual_drop_height_m:
            return _result(
                request,
                ComparabilityState.BRIDGE_VALIDATION_REQUIRED,
                (ComparabilityReasonCode.PROTOCOL_MISMATCH,),
                conditions=("actual drop-height effect must be bridged before the claim",),
            )
    elif (
        left_protocol.actual_drop_height_m is not None
        and right_protocol.actual_drop_height_m is not None
        and left_protocol.actual_drop_height_m != right_protocol.actual_drop_height_m
    ):
        return _result(
            request,
            ComparabilityState.BRIDGE_VALIDATION_REQUIRED,
            (ComparabilityReasonCode.PROTOCOL_MISMATCH,),
            conditions=(
                "realized drop-height difference is material to the requested metric claim",
            ),
        )
    # Unknown actual height is deliberately ignored for claims whose equation
    # does not use it. Other protocol attributes remain material.
    if _protocol_signature(left_protocol, include_actual=False) != _protocol_signature(
        right_protocol, include_actual=False
    ):
        return _result(
            request,
            ComparabilityState.BRIDGE_VALIDATION_REQUIRED,
            (ComparabilityReasonCode.PROTOCOL_MISMATCH,),
        )
    left_acquisition = left_identity.acquisition
    right_acquisition = right_identity.acquisition
    if left_acquisition.device is None or right_acquisition.device is None:
        return _result(
            request,
            ComparabilityState.INSUFFICIENT_INFORMATION,
            (ComparabilityReasonCode.MISSING_METADATA,),
            missing=("DJ device/measuring-system identity",),
        )
    if _acquisition_signature(left_acquisition) != _acquisition_signature(right_acquisition):
        return _result(
            request,
            ComparabilityState.BRIDGE_VALIDATION_REQUIRED,
            (ComparabilityReasonCode.DEVICE_MISMATCH,),
        )
    if left.source_events and right.source_events:
        if len(left.source_events) != len(right.source_events):
            return _result(
                request,
                ComparabilityState.BRIDGE_VALIDATION_REQUIRED,
                (ComparabilityReasonCode.EVENT_METHOD_MISMATCH,),
            )
        for left_event, right_event in zip(left.source_events, right.source_events, strict=False):
            if (
                left_event.label != right_event.label
                or left_event.detector_method != right_event.detector_method
                or left_event.detector_parameters != right_event.detector_parameters
                or left_event.source_timebase != right_event.source_timebase
            ):
                return _result(
                    request,
                    ComparabilityState.BRIDGE_VALIDATION_REQUIRED,
                    (ComparabilityReasonCode.EVENT_METHOD_MISMATCH,),
                )
    if _processing_signature(left_identity) != _processing_signature(right_identity):
        return _result(
            request,
            ComparabilityState.BRIDGE_VALIDATION_REQUIRED,
            (ComparabilityReasonCode.SOURCE_PROCESSING_MISMATCH,),
        )
    return _result(request, ComparabilityState.COMPARABLE, ())


def assess_drop_jump_comparability(
    left: DropJumpMetricResult,
    right: DropJumpMetricResult,
    claim: str = "compare DJ metric results",
) -> ComparabilityResult:
    return compare_drop_jump_metric_results(left, right, claim)


compare_dj_metric_results = compare_drop_jump_metric_results


__all__ = [
    "DropJumpComparabilityRequest",
    "assess_drop_jump_comparability",
    "compare_dj_metric_results",
    "compare_drop_jump_metric_results",
]
