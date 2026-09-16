"""Claim-relative, fail-closed comparability rules for RES-67 outputs."""

from __future__ import annotations

from dataclasses import dataclass

from dynamislm.comparability.models import (
    ComparabilityDecisionSource,
    ComparabilityReasonCode,
    ComparabilityResult,
    ComparabilityState,
)
from dynamislm.measurement.field_testing.cod import Standard505Result
from dynamislm.measurement.field_testing.identity import FieldTestingMeasurementIdentity
from dynamislm.measurement.field_testing.ift import VIFTResult
from dynamislm.measurement.field_testing.registry import (
    FIELD_TEST_COMPARABILITY_RULE,
    FIELD_TESTING_REGISTRY_VERSION,
    IFT30_15_COMPARABILITY_RULE,
    MAXIMUM_SPRINT_VELOCITY_COMPARABILITY_RULE,
    MAXIMUM_SPRINT_VELOCITY_METRIC,
    RSA_COMPARABILITY_RULE,
    SPRINT_TIME_COMPARABILITY_RULE,
    STANDARD_505_COMPARABILITY_RULE,
)
from dynamislm.measurement.field_testing.rsa import RSAResult
from dynamislm.measurement.field_testing.sprint import (
    MaximumSprintVelocityResult,
    SprintTimeObservation,
)
from dynamislm.measurement.identity import InstanceIdentifier
from dynamislm.measurement.observation import ScientificMeasurementObservation
from dynamislm.serialization import canonical_hash, register_serializable_type


def _request_id(
    left: InstanceIdentifier, right: InstanceIdentifier, claim: str
) -> InstanceIdentifier:
    digest = canonical_hash({"left": left, "right": right, "claim": claim}).removeprefix("sha256:")[
        :24
    ]
    return InstanceIdentifier("comparability-request", f"field-test:{digest}")


def _result(
    *,
    left: InstanceIdentifier,
    right: InstanceIdentifier,
    claim: str,
    rule: object,
    state: ComparabilityState,
    reasons: tuple[ComparabilityReasonCode, ...] = (),
    conditions: tuple[str, ...] = (),
    missing: tuple[str, ...] = (),
) -> ComparabilityResult:
    request_id = _request_id(left, right, claim)
    from dynamislm.measurement.identity import RegistryReference

    if not isinstance(rule, RegistryReference):
        raise ValueError("comparability rule must be a RegistryReference")
    return ComparabilityResult(
        result_id=InstanceIdentifier(
            "comparability-result", f"{request_id.value}:{state.value.lower()}"
        ),
        request_id=request_id,
        state=state,
        reason_codes=tuple(reason.value for reason in reasons),
        conditions=conditions,
        transformations_required=(),
        missing_information=missing,
        rule_reference=rule,
        evidence_references=(),
        decided_by=ComparabilityDecisionSource.DETERMINISTIC_RULE,
    )


def _identifiers(left: object, right: object) -> tuple[InstanceIdentifier, InstanceIdentifier]:
    left_observation = getattr(left, "observation", None)
    right_observation = getattr(right, "observation", None)
    if not isinstance(left_observation, ScientificMeasurementObservation) or not isinstance(
        right_observation, ScientificMeasurementObservation
    ):
        raise ValueError("field-test comparability requires typed result observations")
    return left_observation.observation_id, right_observation.observation_id


def _device_method_key(observation: ScientificMeasurementObservation) -> object:
    identity = observation.identity
    if not isinstance(identity, FieldTestingMeasurementIdentity):
        raise ValueError("field-test observation requires FieldTestingMeasurementIdentity")
    acquisition = identity.acquisition
    processing = identity.processing
    return (
        acquisition.provider,
        acquisition.device,
        acquisition.sensor_modality,
        acquisition.sampling,
        acquisition.axis_or_frame,
        acquisition.sensor_channel,
        processing.event_definitions,
        processing.filtering,
        processing.filtering_status,
        processing.smoothing,
        processing.interpolation,
        processing.timebase,
        processing.processing_state,
        observation.result.classification.value_origin,
        identity.version.software_version,
        identity.version.hardware_firmware,
    )


def _device_difference_state(
    left: ScientificMeasurementObservation,
    right: ScientificMeasurementObservation,
) -> tuple[ComparabilityState, tuple[ComparabilityReasonCode, ...], tuple[str, ...]] | None:
    left_key = _device_method_key(left)
    right_key = _device_method_key(right)
    if left_key == right_key:
        return None
    left_identity = left.identity
    right_identity = right.identity
    if not isinstance(left_identity, FieldTestingMeasurementIdentity) or not isinstance(
        right_identity, FieldTestingMeasurementIdentity
    ):
        raise ValueError("field-test observation requires FieldTestingMeasurementIdentity")
    if left_identity.acquisition.device != right_identity.acquisition.device:
        return (
            ComparabilityState.BRIDGE_VALIDATION_REQUIRED,
            (
                ComparabilityReasonCode.DEVICE_MISMATCH,
                ComparabilityReasonCode.BRIDGE_NOT_REGISTERED,
            ),
            ("a registered cross-device agreement bridge",),
        )
    if left_identity.acquisition.sensor_modality != right_identity.acquisition.sensor_modality:
        return (
            ComparabilityState.BRIDGE_VALIDATION_REQUIRED,
            (
                ComparabilityReasonCode.MODALITY_MISMATCH,
                ComparabilityReasonCode.BRIDGE_NOT_REGISTERED,
            ),
            ("a registered cross-modality agreement bridge",),
        )
    return (
        ComparabilityState.NOT_COMPARABLE,
        (ComparabilityReasonCode.METHOD_MISMATCH,),
        (),
    )


def compare_sprint_time_observations(
    left: SprintTimeObservation,
    right: SprintTimeObservation,
    *,
    claim: str = "compare sprint timing observations",
) -> ComparabilityResult:
    """Compare typed sprint times under distance, split, trigger and device identity."""

    left_id, right_id = _identifiers(left, right)
    try:
        if not isinstance(left, SprintTimeObservation) or not isinstance(
            right, SprintTimeObservation
        ):
            raise ValueError("typed sprint times are required")
        if left.split != right.split:
            return _result(
                left=left_id,
                right=right_id,
                claim=claim,
                rule=SPRINT_TIME_COMPARABILITY_RULE,
                state=ComparabilityState.NOT_COMPARABLE,
                reasons=(ComparabilityReasonCode.METRIC_DEFINITION_MISMATCH,),
            )
        left_protocol = left.identity.semantic.protocol_identity
        right_protocol = right.identity.semantic.protocol_identity
        if left_protocol is None or right_protocol is None:
            return _result(
                left=left_id,
                right=right_id,
                claim=claim,
                rule=SPRINT_TIME_COMPARABILITY_RULE,
                state=ComparabilityState.INSUFFICIENT_INFORMATION,
                reasons=(ComparabilityReasonCode.MISSING_METADATA,),
                missing=("complete sprint protocol identity",),
            )
        if left_protocol != right_protocol:
            return _result(
                left=left_id,
                right=right_id,
                claim=claim,
                rule=SPRINT_TIME_COMPARABILITY_RULE,
                state=ComparabilityState.NOT_COMPARABLE,
                reasons=(ComparabilityReasonCode.PROTOCOL_MISMATCH,),
            )
        if left.context.athlete_id != right.context.athlete_id:
            return _result(
                left=left_id,
                right=right_id,
                claim=claim,
                rule=SPRINT_TIME_COMPARABILITY_RULE,
                state=ComparabilityState.NOT_COMPARABLE,
                reasons=(ComparabilityReasonCode.IDENTITY_MISMATCH,),
            )
        difference = _device_difference_state(left.observation, right.observation)
        if difference is not None:
            state, reasons, conditions = difference
            return _result(
                left=left_id,
                right=right_id,
                claim=claim,
                rule=SPRINT_TIME_COMPARABILITY_RULE,
                state=state,
                reasons=reasons,
                conditions=conditions,
            )
        return _result(
            left=left_id,
            right=right_id,
            claim=claim,
            rule=SPRINT_TIME_COMPARABILITY_RULE,
            state=ComparabilityState.COMPARABLE,
        )
    except (AttributeError, TypeError, ValueError) as exc:
        return _result(
            left=left_id,
            right=right_id,
            claim=claim,
            rule=SPRINT_TIME_COMPARABILITY_RULE,
            state=ComparabilityState.INSUFFICIENT_INFORMATION,
            reasons=(ComparabilityReasonCode.MISSING_METADATA,),
            missing=(str(exc),),
        )


def compare_maximum_sprint_velocity(
    left: MaximumSprintVelocityResult,
    right: MaximumSprintVelocityResult,
    *,
    claim: str = "compare maximum sprint velocity observations",
) -> ComparabilityResult:
    left_id, right_id = _identifiers(left, right)
    try:
        if not isinstance(left, MaximumSprintVelocityResult) or not isinstance(
            right, MaximumSprintVelocityResult
        ):
            raise ValueError("typed maximum-velocity results are required")
        if (
            left.metric != MAXIMUM_SPRINT_VELOCITY_METRIC
            or right.metric != MAXIMUM_SPRINT_VELOCITY_METRIC
        ):
            return _result(
                left=left_id,
                right=right_id,
                claim=claim,
                rule=MAXIMUM_SPRINT_VELOCITY_COMPARABILITY_RULE,
                state=ComparabilityState.NOT_COMPARABLE,
                reasons=(ComparabilityReasonCode.METRIC_DEFINITION_MISMATCH,),
            )
        left_identity = left.observation.identity
        right_identity = right.observation.identity
        if not isinstance(left_identity, FieldTestingMeasurementIdentity) or not isinstance(
            right_identity, FieldTestingMeasurementIdentity
        ):
            raise ValueError("maximum-velocity output requires FieldTestingMeasurementIdentity")
        if (
            left_identity.semantic.protocol_identity is None
            or right_identity.semantic.protocol_identity is None
        ):
            return _result(
                left=left_id,
                right=right_id,
                claim=claim,
                rule=MAXIMUM_SPRINT_VELOCITY_COMPARABILITY_RULE,
                state=ComparabilityState.INSUFFICIENT_INFORMATION,
                reasons=(ComparabilityReasonCode.MISSING_METADATA,),
                missing=("maximum-velocity protocol identity",),
            )
        if left_identity.semantic.protocol_identity != right_identity.semantic.protocol_identity:
            return _result(
                left=left_id,
                right=right_id,
                claim=claim,
                rule=MAXIMUM_SPRINT_VELOCITY_COMPARABILITY_RULE,
                state=ComparabilityState.NOT_COMPARABLE,
                reasons=(ComparabilityReasonCode.PROTOCOL_MISMATCH,),
            )
        if (
            left.evidence.observation.result.classification.value_origin
            != right.evidence.observation.result.classification.value_origin
        ):
            return _result(
                left=left_id,
                right=right_id,
                claim=claim,
                rule=MAXIMUM_SPRINT_VELOCITY_COMPARABILITY_RULE,
                state=ComparabilityState.NOT_COMPARABLE,
                reasons=(ComparabilityReasonCode.VALUE_ORIGIN_MISMATCH,),
            )
        left_params = {item.key: item.value for item in left_identity.processing.method_parameters}
        right_params = {
            item.key: item.value for item in right_identity.processing.method_parameters
        }
        if left_params.get("estimator") != right_params.get("estimator") and (
            left_identity.processing.estimator != right_identity.processing.estimator
        ):
            return _result(
                left=left_id,
                right=right_id,
                claim=claim,
                rule=MAXIMUM_SPRINT_VELOCITY_COMPARABILITY_RULE,
                state=ComparabilityState.NOT_COMPARABLE,
                reasons=(ComparabilityReasonCode.ESTIMATOR_MISMATCH,),
            )
        if left_params.get("support_start_index") != right_params.get(
            "support_start_index"
        ) or left_params.get("support_end_index") != right_params.get("support_end_index"):
            return _result(
                left=left_id,
                right=right_id,
                claim=claim,
                rule=MAXIMUM_SPRINT_VELOCITY_COMPARABILITY_RULE,
                state=ComparabilityState.NOT_COMPARABLE,
                reasons=(ComparabilityReasonCode.SAMPLE_OR_TIMEBASE_MISMATCH,),
            )
        difference = _device_difference_state(left.observation, right.observation)
        if difference is not None:
            state, reasons, conditions = difference
            return _result(
                left=left_id,
                right=right_id,
                claim=claim,
                rule=MAXIMUM_SPRINT_VELOCITY_COMPARABILITY_RULE,
                state=state,
                reasons=reasons,
                conditions=conditions,
            )
        return _result(
            left=left_id,
            right=right_id,
            claim=claim,
            rule=MAXIMUM_SPRINT_VELOCITY_COMPARABILITY_RULE,
            state=ComparabilityState.COMPARABLE,
        )
    except (AttributeError, TypeError, ValueError) as exc:
        return _result(
            left=left_id,
            right=right_id,
            claim=claim,
            rule=MAXIMUM_SPRINT_VELOCITY_COMPARABILITY_RULE,
            state=ComparabilityState.INSUFFICIENT_INFORMATION,
            reasons=(ComparabilityReasonCode.MISSING_METADATA,),
            missing=(str(exc),),
        )


def compare_standard_505_results(
    left: Standard505Result,
    right: Standard505Result,
    *,
    claim: str = "compare standard 505 results",
) -> ComparabilityResult:
    left_id, right_id = _identifiers(left, right)
    try:
        if not isinstance(left, Standard505Result) or not isinstance(right, Standard505Result):
            raise ValueError("typed standard 505 results are required")
        if left.side is not right.side:
            return _result(
                left=left_id,
                right=right_id,
                claim=claim,
                rule=STANDARD_505_COMPARABILITY_RULE,
                state=ComparabilityState.NOT_COMPARABLE,
                reasons=(ComparabilityReasonCode.IDENTITY_MISMATCH,),
            )
        if left.protocol != right.protocol:
            return _result(
                left=left_id,
                right=right_id,
                claim=claim,
                rule=STANDARD_505_COMPARABILITY_RULE,
                state=ComparabilityState.NOT_COMPARABLE,
                reasons=(ComparabilityReasonCode.PROTOCOL_MISMATCH,),
            )
        difference = _device_difference_state(left.observation, right.observation)
        if difference is not None:
            state, reasons, conditions = difference
            return _result(
                left=left_id,
                right=right_id,
                claim=claim,
                rule=STANDARD_505_COMPARABILITY_RULE,
                state=state,
                reasons=reasons,
                conditions=conditions,
            )
        return _result(
            left=left_id,
            right=right_id,
            claim=claim,
            rule=STANDARD_505_COMPARABILITY_RULE,
            state=ComparabilityState.COMPARABLE,
        )
    except (AttributeError, TypeError, ValueError) as exc:
        return _result(
            left=left_id,
            right=right_id,
            claim=claim,
            rule=STANDARD_505_COMPARABILITY_RULE,
            state=ComparabilityState.INSUFFICIENT_INFORMATION,
            reasons=(ComparabilityReasonCode.MISSING_METADATA,),
            missing=(str(exc),),
        )


def compare_rsa_results(
    left: RSAResult,
    right: RSAResult,
    *,
    claim: str = "compare RSA results",
) -> ComparabilityResult:
    left_id, right_id = _identifiers(left, right)
    try:
        if not isinstance(left, RSAResult) or not isinstance(right, RSAResult):
            raise ValueError("typed RSA results are required")
        if left.metric != right.metric:
            return _result(
                left=left_id,
                right=right_id,
                claim=claim,
                rule=RSA_COMPARABILITY_RULE,
                state=ComparabilityState.NOT_COMPARABLE,
                reasons=(ComparabilityReasonCode.METRIC_DEFINITION_MISMATCH,),
            )
        if left.protocol != right.protocol:
            return _result(
                left=left_id,
                right=right_id,
                claim=claim,
                rule=RSA_COMPARABILITY_RULE,
                state=ComparabilityState.NOT_COMPARABLE,
                reasons=(ComparabilityReasonCode.PROTOCOL_MISMATCH,),
            )
        difference = _device_difference_state(left.observation, right.observation)
        if difference is not None:
            state, reasons, conditions = difference
            return _result(
                left=left_id,
                right=right_id,
                claim=claim,
                rule=RSA_COMPARABILITY_RULE,
                state=state,
                reasons=reasons,
                conditions=conditions,
            )
        return _result(
            left=left_id,
            right=right_id,
            claim=claim,
            rule=RSA_COMPARABILITY_RULE,
            state=ComparabilityState.COMPARABLE,
        )
    except (AttributeError, TypeError, ValueError) as exc:
        return _result(
            left=left_id,
            right=right_id,
            claim=claim,
            rule=RSA_COMPARABILITY_RULE,
            state=ComparabilityState.INSUFFICIENT_INFORMATION,
            reasons=(ComparabilityReasonCode.MISSING_METADATA,),
            missing=(str(exc),),
        )


def compare_vift_results(
    left: VIFTResult,
    right: VIFTResult,
    *,
    claim: str = "compare 30-15 IFT VIFT results",
) -> ComparabilityResult:
    left_id, right_id = _identifiers(left, right)
    try:
        if not isinstance(left, VIFTResult) or not isinstance(right, VIFTResult):
            raise ValueError("typed VIFT results are required")
        if left.test.protocol != right.test.protocol:
            return _result(
                left=left_id,
                right=right_id,
                claim=claim,
                rule=IFT30_15_COMPARABILITY_RULE,
                state=ComparabilityState.NOT_COMPARABLE,
                reasons=(ComparabilityReasonCode.PROTOCOL_MISMATCH,),
            )
        difference = _device_difference_state(left.observation, right.observation)
        if difference is not None:
            state, reasons, conditions = difference
            return _result(
                left=left_id,
                right=right_id,
                claim=claim,
                rule=IFT30_15_COMPARABILITY_RULE,
                state=state,
                reasons=reasons,
                conditions=conditions,
            )
        return _result(
            left=left_id,
            right=right_id,
            claim=claim,
            rule=IFT30_15_COMPARABILITY_RULE,
            state=ComparabilityState.COMPARABLE,
        )
    except (AttributeError, TypeError, ValueError) as exc:
        return _result(
            left=left_id,
            right=right_id,
            claim=claim,
            rule=IFT30_15_COMPARABILITY_RULE,
            state=ComparabilityState.INSUFFICIENT_INFORMATION,
            reasons=(ComparabilityReasonCode.MISSING_METADATA,),
            missing=(str(exc),),
        )


def compare_field_testing_results(
    left: object, right: object, *, claim: str = "compare field-test results"
) -> ComparabilityResult:
    if isinstance(left, SprintTimeObservation) and isinstance(right, SprintTimeObservation):
        return compare_sprint_time_observations(left, right, claim=claim)
    if isinstance(left, MaximumSprintVelocityResult) and isinstance(
        right, MaximumSprintVelocityResult
    ):
        return compare_maximum_sprint_velocity(left, right, claim=claim)
    if isinstance(left, Standard505Result) and isinstance(right, Standard505Result):
        return compare_standard_505_results(left, right, claim=claim)
    if isinstance(left, RSAResult) and isinstance(right, RSAResult):
        return compare_rsa_results(left, right, claim=claim)
    if isinstance(left, VIFTResult) and isinstance(right, VIFTResult):
        return compare_vift_results(left, right, claim=claim)
    raise ValueError("field-test result types are incompatible or unregistered")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class FieldTestingComparabilityContract:
    """Readable registry version for the field-testing comparability surface."""

    registry_version: str = FIELD_TESTING_REGISTRY_VERSION
    rule: object = FIELD_TEST_COMPARABILITY_RULE

    def __post_init__(self) -> None:
        from dynamislm.measurement.identity import RegistryReference

        if not isinstance(self.registry_version, str) or not self.registry_version.strip():
            raise ValueError("registry_version must not be empty")
        if not isinstance(self.rule, RegistryReference):
            raise ValueError("rule must be a RegistryReference")


__all__ = [
    "FieldTestingComparabilityContract",
    "compare_field_testing_results",
    "compare_maximum_sprint_velocity",
    "compare_rsa_results",
    "compare_sprint_time_observations",
    "compare_standard_505_results",
    "compare_vift_results",
]
