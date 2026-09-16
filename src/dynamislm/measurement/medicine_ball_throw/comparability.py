"""Claim-relative medicine-ball throw comparability."""

from __future__ import annotations

from dataclasses import dataclass

from dynamislm.comparability.models import (
    ComparabilityDecisionSource,
    ComparabilityReasonCode,
    ComparabilityRequest,
    ComparabilityResult,
    ComparabilityState,
)
from dynamislm.measurement.identity import InstanceIdentifier, RegistryReference, _require_instance
from dynamislm.measurement.medicine_ball_throw.identity import (
    MedicineBallThrowAcquisitionIdentity,
    MedicineBallThrowMeasurementIdentity,
    MedicineBallThrowProcessingIdentity,
    MedicineBallThrowProtocolIdentity,
)
from dynamislm.measurement.medicine_ball_throw.metrics import MedicineBallThrowMetricResult
from dynamislm.measurement.medicine_ball_throw.registry import (
    MBT_DISTANCE_COMPARABILITY_RULE,
    MBT_INSTRUMENTED_RELEASE_VELOCITY_METRIC,
    MBT_RELEASE_VELOCITY_COMPARABILITY_RULE,
    MBT_THROW_DISTANCE_METRIC,
    MEDICINE_BALL_THROW_TEST_FAMILY,
    RES68_DECISION_EXPLOSIVE_TEST_FAMILY,
)
from dynamislm.measurement.observation import ScientificMeasurementObservation
from dynamislm.serialization import canonical_hash, register_serializable_type


@register_serializable_type
@dataclass(frozen=True, slots=True)
class MBTComparabilityRequest:
    request_id: InstanceIdentifier
    left_observation_id: InstanceIdentifier
    right_observation_id: InstanceIdentifier
    claim: str

    def __post_init__(self) -> None:
        if self.request_id.instance_type != "comparability-request":
            raise ValueError("MBT request ID must identify a comparability request")
        if self.left_observation_id == self.right_observation_id:
            raise ValueError("MBT comparison requires two observations")
        if not self.claim.strip():
            raise ValueError("MBT claim must not be empty")


def _result(
    request: ComparabilityRequest,
    state: ComparabilityState,
    reasons: tuple[ComparabilityReasonCode, ...],
    *,
    missing: tuple[str, ...] = (),
    conditions: tuple[str, ...] = (),
    rule: RegistryReference | None = None,
) -> ComparabilityResult:
    if rule is None:
        rule = MBT_DISTANCE_COMPARABILITY_RULE
    _require_instance(rule, RegistryReference, "rule")
    digest = canonical_hash(
        {"request": request, "state": state, "reasons": reasons, "missing": missing}
    ).removeprefix("sha256:")[:24]
    return ComparabilityResult(
        result_id=InstanceIdentifier("comparability-result", f"mbt:{digest}"),
        request_id=request.request_id,
        state=state,
        reason_codes=tuple(reason.value for reason in reasons),
        conditions=conditions,
        transformations_required=(),
        missing_information=missing,
        rule_reference=rule,
        evidence_references=(RES68_DECISION_EXPLOSIVE_TEST_FAMILY,),
        decided_by=ComparabilityDecisionSource.DETERMINISTIC_RULE,
    )


def _protocol_signature(protocol: MedicineBallThrowProtocolIdentity) -> tuple[object, ...]:
    return (
        protocol.reference,
        protocol.protocol_version,
        protocol.throw_type,
        protocol.body_posture,
        protocol.support_restraint_condition,
        protocol.ball_mass_kg,
        protocol.countermovement,
        protocol.lower_body_contribution,
        protocol.throw_arm_technique,
        protocol.starting_position,
        protocol.release_semantics,
        protocol.measurement_method,
        protocol.distance_origin_convention,
        protocol.distance_endpoint_convention,
        protocol.first_contact_no_roll_convention,
        protocol.trial_qualification,
        protocol.trial_selection,
        protocol.additional_attributes,
    )


def _acquisition_signature(
    acquisition: MedicineBallThrowAcquisitionIdentity,
) -> tuple[object, ...]:
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


def _processing_signature(
    processing: MedicineBallThrowProcessingIdentity,
) -> tuple[object, ...]:
    return (
        processing.event_definitions,
        processing.phase_definitions,
        processing.estimator,
        processing.registered_operation,
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
        processing.provider_algorithm,
        processing.resampling,
    )


def compare_mbt_metric_results(
    left: MedicineBallThrowMetricResult,
    right: MedicineBallThrowMetricResult,
    claim: str = "compare MBT metric results",
) -> ComparabilityResult:
    left_id = getattr(left, "observation", None)
    right_id = getattr(right, "observation", None)
    request_id = InstanceIdentifier(
        "comparability-request",
        canonical_hash(
            {
                "left": getattr(left_id, "observation_id", "invalid-left"),
                "right": getattr(right_id, "observation_id", "invalid-right"),
                "claim": claim,
            }
        ).removeprefix("sha256:")[:24],
    )
    try:
        _require_instance(left, MedicineBallThrowMetricResult, "left")
        _require_instance(right, MedicineBallThrowMetricResult, "right")
        request = ComparabilityRequest(
            request_id=request_id,
            left_observation_id=left.observation.observation_id,
            right_observation_id=right.observation.observation_id,
            claim=claim,
            material_dimensions=(
                "metric",
                "throw_type",
                "posture",
                "support",
                "ball_mass",
                "distance_conventions",
                "device",
                "release_event",
            ),
        )
    except (AttributeError, TypeError, ValueError):
        fallback = ComparabilityRequest(
            request_id=request_id,
            left_observation_id=InstanceIdentifier("observation", "invalid-left"),
            right_observation_id=InstanceIdentifier("observation", "invalid-right"),
            claim=claim or "invalid MBT comparison",
        )
        if hasattr(left, "observation") and hasattr(right, "observation"):
            left_observation = left.observation
            right_observation = right.observation
            if isinstance(left_observation, ScientificMeasurementObservation) and isinstance(
                right_observation, ScientificMeasurementObservation
            ):
                fallback = ComparabilityRequest(
                    request_id=request_id,
                    left_observation_id=left_observation.observation_id,
                    right_observation_id=right_observation.observation_id,
                    claim=claim or "invalid MBT comparison",
                )
                return _result(
                    fallback,
                    ComparabilityState.NOT_COMPARABLE,
                    (ComparabilityReasonCode.METRIC_FAMILY_MISMATCH,),
                )
        return _result(
            fallback,
            ComparabilityState.INSUFFICIENT_INFORMATION,
            (ComparabilityReasonCode.MISSING_METADATA,),
            missing=("two typed MBT metric results",),
        )
    if left.metric != right.metric:
        return _result(
            request,
            ComparabilityState.NOT_COMPARABLE,
            (ComparabilityReasonCode.MEASURAND_MISMATCH,),
        )
    left_identity = left.observation.identity
    right_identity = right.observation.identity
    if not isinstance(left_identity, MedicineBallThrowMeasurementIdentity) or not isinstance(
        right_identity, MedicineBallThrowMeasurementIdentity
    ):
        return _result(
            request,
            ComparabilityState.NOT_COMPARABLE,
            (ComparabilityReasonCode.METRIC_FAMILY_MISMATCH,),
        )
    if (
        left_identity.semantic.test_family != MEDICINE_BALL_THROW_TEST_FAMILY
        or right_identity.semantic.test_family != MEDICINE_BALL_THROW_TEST_FAMILY
    ):
        return _result(
            request,
            ComparabilityState.NOT_COMPARABLE,
            (ComparabilityReasonCode.METRIC_FAMILY_MISMATCH,),
        )
    left_protocol = left_identity.semantic.protocol_identity
    right_protocol = right_identity.semantic.protocol_identity
    if left_protocol is None or right_protocol is None:
        return _result(
            request,
            ComparabilityState.INSUFFICIENT_INFORMATION,
            (ComparabilityReasonCode.MISSING_METADATA,),
            missing=("complete MBT protocol identity",),
        )
    required = (
        (left_protocol.throw_type.value, right_protocol.throw_type.value, "throw type"),
        (left_protocol.body_posture.value, right_protocol.body_posture.value, "body posture"),
        (
            left_protocol.support_restraint_condition.value,
            right_protocol.support_restraint_condition.value,
            "support/restraint",
        ),
        (left_protocol.ball_mass_kg, right_protocol.ball_mass_kg, "ball mass"),
    )
    for left_value, right_value, label in required:
        if left_value in {None, "UNKNOWN"} or right_value in {None, "UNKNOWN"}:
            return _result(
                request,
                ComparabilityState.INSUFFICIENT_INFORMATION,
                (ComparabilityReasonCode.MISSING_METADATA,),
                missing=(label,),
            )
        if left_value != right_value:
            return _result(
                request,
                ComparabilityState.NOT_COMPARABLE,
                (ComparabilityReasonCode.PROTOCOL_MISMATCH,),
            )
    if left.metric == MBT_THROW_DISTANCE_METRIC:
        conventions = (
            left_protocol.distance_origin_convention,
            right_protocol.distance_origin_convention,
            left_protocol.distance_endpoint_convention,
            right_protocol.distance_endpoint_convention,
            left_protocol.first_contact_no_roll_convention,
            right_protocol.first_contact_no_roll_convention,
        )
        if any(item is None for item in conventions):
            return _result(
                request,
                ComparabilityState.INSUFFICIENT_INFORMATION,
                (ComparabilityReasonCode.MISSING_METADATA,),
                missing=("origin, endpoint and first-contact/no-roll conventions",),
            )
        if (
            conventions[0] != conventions[1]
            or conventions[2] != conventions[3]
            or conventions[4] != conventions[5]
        ):
            return _result(
                request,
                ComparabilityState.NOT_COMPARABLE,
                (ComparabilityReasonCode.PROTOCOL_MISMATCH,),
            )
        rule = MBT_DISTANCE_COMPARABILITY_RULE
    elif left.metric == MBT_INSTRUMENTED_RELEASE_VELOCITY_METRIC:
        if (
            left_protocol.release_semantics.value == "UNKNOWN"
            or right_protocol.release_semantics.value == "UNKNOWN"
        ):
            return _result(
                request,
                ComparabilityState.INSUFFICIENT_INFORMATION,
                (ComparabilityReasonCode.MISSING_METADATA,),
                missing=("explicit release semantics",),
                rule=MBT_RELEASE_VELOCITY_COMPARABILITY_RULE,
            )
        if left_protocol.release_semantics != right_protocol.release_semantics:
            return _result(
                request,
                ComparabilityState.NOT_COMPARABLE,
                (ComparabilityReasonCode.PROTOCOL_MISMATCH,),
                rule=MBT_RELEASE_VELOCITY_COMPARABILITY_RULE,
            )
        rule = MBT_RELEASE_VELOCITY_COMPARABILITY_RULE
    else:
        return _result(
            request,
            ComparabilityState.NOT_COMPARABLE,
            (ComparabilityReasonCode.METRIC_DEFINITION_MISMATCH,),
        )
    if _protocol_signature(left_protocol) != _protocol_signature(right_protocol):
        return _result(
            request,
            ComparabilityState.NOT_COMPARABLE,
            (ComparabilityReasonCode.PROTOCOL_MISMATCH,),
            rule=rule,
        )
    if _acquisition_signature(left_identity.acquisition) != _acquisition_signature(
        right_identity.acquisition
    ):
        if left_identity.acquisition.device is None or right_identity.acquisition.device is None:
            return _result(
                request,
                ComparabilityState.INSUFFICIENT_INFORMATION,
                (ComparabilityReasonCode.MISSING_METADATA,),
                missing=("MBT device identity",),
                rule=rule,
            )
        return _result(
            request,
            ComparabilityState.BRIDGE_VALIDATION_REQUIRED,
            (ComparabilityReasonCode.DEVICE_MISMATCH,),
            rule=rule,
        )
    if _processing_signature(left_identity.processing) != _processing_signature(
        right_identity.processing
    ):
        return _result(
            request,
            ComparabilityState.BRIDGE_VALIDATION_REQUIRED,
            (ComparabilityReasonCode.SOURCE_PROCESSING_MISMATCH,),
            rule=rule,
        )
    return _result(request, ComparabilityState.COMPARABLE, (), rule=rule)


def assess_mbt_comparability(
    left: MedicineBallThrowMetricResult,
    right: MedicineBallThrowMetricResult,
    claim: str = "compare MBT metric results",
) -> ComparabilityResult:
    return compare_mbt_metric_results(left, right, claim)


compare_medicine_ball_throw_results = compare_mbt_metric_results


__all__ = [
    "MBTComparabilityRequest",
    "assess_mbt_comparability",
    "compare_mbt_metric_results",
    "compare_medicine_ball_throw_results",
]
