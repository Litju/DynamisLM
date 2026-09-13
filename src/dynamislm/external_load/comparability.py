"""Claim-relative, fail-closed external-load identity comparability."""

from __future__ import annotations

from dataclasses import dataclass

from dynamislm.comparability.models import (
    ComparabilityDecisionSource,
    ComparabilityReasonCode,
    ComparabilityResult,
    ComparabilityState,
    TransformationRequest,
)
from dynamislm.external_load.identity import (
    AggregationContext,
    AggregationScope,
    EventHysteresisStatus,
    ExternalLoadDefinitionStatus,
    ExternalLoadEventDefinition,
    ExternalLoadMeasurementIdentity,
    ExternalLoadMetricFamily,
    ExternalLoadSystemIdentity,
    ExternalLoadThresholdIdentity,
    NormalizationKind,
    ProcessingComponentStatus,
    ProcessingStepIdentity,
    ThresholdBasis,
    ThresholdBoundary,
)
from dynamislm.external_load.metrics import (
    ExternalLoadComputationError,
    convert_external_load_value,
)
from dynamislm.external_load.registry import EXTERNAL_LOAD_COMPARABILITY_RULE
from dynamislm.measurement.identity import InstanceIdentifier, RegistryReference, UnitReference
from dynamislm.measurement.observation import ScientificMeasurementObservation
from dynamislm.measurement.taxonomy import ValueOrigin
from dynamislm.serialization import register_serializable_type


def _same_reference(left: RegistryReference | None, right: RegistryReference | None) -> bool:
    if left is None or right is None:
        return left is right
    return left.stable_id == right.stable_id


def _same_unit(left: UnitReference | None, right: UnitReference | None) -> bool:
    if left is None or right is None:
        return left is right
    return left.identifier.stable_id == right.identifier.stable_id


@register_serializable_type
@dataclass(frozen=True, slots=True)
class ExternalLoadComparabilityRequest:
    """Two external-load identities evaluated for one explicit claim."""

    request_id: InstanceIdentifier
    left_observation_id: InstanceIdentifier
    right_observation_id: InstanceIdentifier
    left_identity: ExternalLoadMeasurementIdentity
    right_identity: ExternalLoadMeasurementIdentity
    claim: str
    requested_transformations: tuple[TransformationRequest, ...] = ()

    def __post_init__(self) -> None:
        if self.request_id.instance_type != "comparability-request":
            raise ValueError("request_id must identify a comparability request")
        for field_name, value in (
            ("left_observation_id", self.left_observation_id),
            ("right_observation_id", self.right_observation_id),
        ):
            if value.instance_type != "observation":
                raise ValueError(f"{field_name} must identify an observation")
        if self.left_observation_id == self.right_observation_id:
            raise ValueError("external-load comparability requires distinct observations")
        if not isinstance(self.left_identity, ExternalLoadMeasurementIdentity):
            raise ValueError("left_identity must be an ExternalLoadMeasurementIdentity")
        if not isinstance(self.right_identity, ExternalLoadMeasurementIdentity):
            raise ValueError("right_identity must be an ExternalLoadMeasurementIdentity")
        if not self.claim.strip():
            raise ValueError("claim must not be empty")
        if not isinstance(self.requested_transformations, tuple):
            raise ValueError("requested_transformations must be an immutable tuple")


def _append(
    reasons: list[ComparabilityReasonCode],
    reason: ComparabilityReasonCode,
) -> None:
    if reason not in reasons:
        reasons.append(reason)


def _compare_thresholds(
    left: ExternalLoadThresholdIdentity,
    right: ExternalLoadThresholdIdentity,
    reasons: list[ComparabilityReasonCode],
    missing: list[str],
) -> None:
    if left.basis is ThresholdBasis.UNKNOWN or right.basis is ThresholdBasis.UNKNOWN:
        _append(reasons, ComparabilityReasonCode.UNKNOWN_THRESHOLD_BASIS)
        missing.append("threshold basis")
        return
    if left.basis is ThresholdBasis.NONE or right.basis is ThresholdBasis.NONE:
        if left.basis is not right.basis:
            _append(reasons, ComparabilityReasonCode.THRESHOLD_BASIS_MISMATCH)
        return
    if left.threshold_quantity is None or right.threshold_quantity is None:
        _append(reasons, ComparabilityReasonCode.UNKNOWN_THRESHOLD)
        missing.append("threshold quantity")
    elif not _same_reference(left.threshold_quantity, right.threshold_quantity):
        _append(reasons, ComparabilityReasonCode.MEASURAND_MISMATCH)
    if left.threshold_unit is None or right.threshold_unit is None:
        _append(reasons, ComparabilityReasonCode.UNKNOWN_THRESHOLD)
        missing.append("threshold unit")
    elif left.threshold_value is None or right.threshold_value is None:
        _append(reasons, ComparabilityReasonCode.UNKNOWN_THRESHOLD)
        missing.append("threshold value")
    else:
        try:
            right_value = (
                right.threshold_value
                if _same_unit(left.threshold_unit, right.threshold_unit)
                else convert_external_load_value(
                    right.threshold_value,
                    right.threshold_unit,
                    left.threshold_unit,
                )
            )
        except ExternalLoadComputationError:
            _append(reasons, ComparabilityReasonCode.THRESHOLD_UNIT_MISMATCH)
        else:
            if left.threshold_value != right_value:
                _append(reasons, ComparabilityReasonCode.THRESHOLD_VALUE_MISMATCH)
    if left.basis is not right.basis:
        _append(reasons, ComparabilityReasonCode.THRESHOLD_BASIS_MISMATCH)
    if not _same_reference(left.individualized_reference, right.individualized_reference):
        _append(reasons, ComparabilityReasonCode.INDIVIDUALIZED_REFERENCE_MISMATCH)
    if left.boundary is ThresholdBoundary.UNKNOWN or right.boundary is ThresholdBoundary.UNKNOWN:
        _append(reasons, ComparabilityReasonCode.UNKNOWN_THRESHOLD)
        missing.append("threshold boundary semantics")
    elif left.boundary is not right.boundary:
        _append(reasons, ComparabilityReasonCode.THRESHOLD_BOUNDARY_MISMATCH)


def _compare_event_definitions(
    left: ExternalLoadEventDefinition | None,
    right: ExternalLoadEventDefinition | None,
    reasons: list[ComparabilityReasonCode],
    missing: list[str],
) -> None:
    if left is None or right is None:
        if left is not right:
            _append(reasons, ComparabilityReasonCode.UNKNOWN_EVENT_DEFINITION)
            missing.append("registered event definition")
        return
    if left.definition is None or right.definition is None:
        _append(reasons, ComparabilityReasonCode.UNKNOWN_EVENT_DEFINITION)
        missing.append("event definition identity")
    elif not _same_reference(left.definition, right.definition):
        _append(reasons, ComparabilityReasonCode.EVENT_DEFINITION_MISMATCH)
    if left.minimum_duration_s is None or right.minimum_duration_s is None:
        _append(reasons, ComparabilityReasonCode.UNKNOWN_DWELL_RULE)
        missing.append("minimum event duration/dwell")
    elif left.minimum_duration_s != right.minimum_duration_s:
        _append(reasons, ComparabilityReasonCode.DWELL_RULE_MISMATCH)
    if (
        left.hysteresis_status is EventHysteresisStatus.UNKNOWN
        or right.hysteresis_status is EventHysteresisStatus.UNKNOWN
    ):
        _append(reasons, ComparabilityReasonCode.UNKNOWN_DWELL_RULE)
        missing.append("hysteresis semantics")
    elif left.hysteresis_status is not right.hysteresis_status:
        _append(reasons, ComparabilityReasonCode.HYSTERESIS_MISMATCH)
    elif left.hysteresis != right.hysteresis:
        _append(reasons, ComparabilityReasonCode.HYSTERESIS_MISMATCH)
    if left.gap_allowance_s is None or right.gap_allowance_s is None:
        _append(reasons, ComparabilityReasonCode.UNKNOWN_DWELL_RULE)
        missing.append("event gap allowance")
    elif left.gap_allowance_s != right.gap_allowance_s:
        _append(reasons, ComparabilityReasonCode.GAP_ALLOWANCE_MISMATCH)
    if left.start_rule is None or right.start_rule is None:
        _append(reasons, ComparabilityReasonCode.UNKNOWN_EVENT_DEFINITION)
        missing.append("event start rule")
    elif not _same_reference(left.start_rule, right.start_rule):
        _append(reasons, ComparabilityReasonCode.EVENT_START_RULE_MISMATCH)
    if left.end_rule is None or right.end_rule is None:
        _append(reasons, ComparabilityReasonCode.UNKNOWN_EVENT_DEFINITION)
        missing.append("event end rule")
    elif not _same_reference(left.end_rule, right.end_rule):
        _append(reasons, ComparabilityReasonCode.EVENT_END_RULE_MISMATCH)
    _compare_threshold_pair(
        left.acceleration_threshold,
        right.acceleration_threshold,
        reasons,
        missing,
        ComparabilityReasonCode.ACCELERATION_THRESHOLD_MISMATCH,
    )
    _compare_threshold_pair(
        left.deceleration_threshold,
        right.deceleration_threshold,
        reasons,
        missing,
        ComparabilityReasonCode.DECELERATION_THRESHOLD_MISMATCH,
    )


def _compare_threshold_pair(
    left: ExternalLoadThresholdIdentity | None,
    right: ExternalLoadThresholdIdentity | None,
    reasons: list[ComparabilityReasonCode],
    missing: list[str],
    mismatch_reason: ComparabilityReasonCode,
) -> None:
    if left is None or right is None:
        if left is not right:
            _append(reasons, mismatch_reason)
        return
    before = len(reasons)
    _compare_thresholds(left, right, reasons, missing)
    if len(reasons) > before:
        # Keep the generic threshold reasons as well; the specific event axis
        # makes the refusal useful to a caller asking about acceleration or
        # deceleration events.
        _append(reasons, mismatch_reason)


def _compare_step(
    left: ProcessingStepIdentity,
    right: ProcessingStepIdentity,
    reasons: list[ComparabilityReasonCode],
    missing: list[str],
    reason: ComparabilityReasonCode,
    unknown_reason: ComparabilityReasonCode,
    label: str,
) -> None:
    if (
        left.status is ProcessingComponentStatus.UNKNOWN
        or right.status is ProcessingComponentStatus.UNKNOWN
    ):
        _append(reasons, unknown_reason)
        missing.append(label)
    elif left.status is not right.status or left != right:
        _append(reasons, reason)


def _compare_systems(
    left: ExternalLoadSystemIdentity,
    right: ExternalLoadSystemIdentity,
    left_identity: ExternalLoadMeasurementIdentity,
    right_identity: ExternalLoadMeasurementIdentity,
    reasons: list[ComparabilityReasonCode],
    missing: list[str],
) -> None:
    if left.provider != right.provider:
        _append(reasons, ComparabilityReasonCode.PROVIDER_MISMATCH)
    if not _same_reference(left.device_or_system, right.device_or_system):
        if left.device_or_system is None or right.device_or_system is None:
            _append(reasons, ComparabilityReasonCode.SYSTEM_IDENTITY_MISMATCH)
            missing.append("device/measuring-system identity")
        else:
            _append(reasons, ComparabilityReasonCode.DEVICE_MISMATCH)
    if not _same_reference(left.model, right.model):
        if left.model is None or right.model is None:
            _append(reasons, ComparabilityReasonCode.MODEL_MISMATCH)
            missing.append("device model identity")
        else:
            _append(reasons, ComparabilityReasonCode.MODEL_MISMATCH)
    source_reported = (
        left_identity.value_origin is ValueOrigin.SOURCE_REPORTED
        and right_identity.value_origin is ValueOrigin.SOURCE_REPORTED
    )
    if not source_reported:
        if left.sampling is None or right.sampling is None:
            _append(reasons, ComparabilityReasonCode.UNKNOWN_SAMPLING_RATE)
            missing.append("sampling rate")
        elif left.sampling != right.sampling:
            _append(reasons, ComparabilityReasonCode.SAMPLE_OR_TIMEBASE_MISMATCH)
        if left.acquisition_characteristics != right.acquisition_characteristics:
            _append(reasons, ComparabilityReasonCode.SAMPLE_OR_TIMEBASE_MISMATCH)
    for field_name, reason in (
        ("firmware_version", ComparabilityReasonCode.SOURCE_PROCESSING_MISMATCH),
        ("software_version", ComparabilityReasonCode.ACQUISITION_SOFTWARE_MISMATCH),
        ("processing_version", ComparabilityReasonCode.SOURCE_PROCESSING_MISMATCH),
    ):
        left_value = getattr(left, field_name)
        right_value = getattr(right, field_name)
        if left_value is None or right_value is None:
            if left_value != right_value and not source_reported:
                _append(reasons, reason)
                missing.append(field_name)
        elif left_value != right_value:
            _append(reasons, reason)
    provider_output = (
        left_identity.value_origin is ValueOrigin.PROVIDER_DERIVED
        or right_identity.value_origin is ValueOrigin.PROVIDER_DERIVED
    )
    if provider_output:
        if (
            left.provider_algorithm_status is ProcessingComponentStatus.UNKNOWN
            or right.provider_algorithm_status is ProcessingComponentStatus.UNKNOWN
        ):
            _append(reasons, ComparabilityReasonCode.UNKNOWN_PROVIDER_ALGORITHM)
            missing.append("provider algorithm identity")
        elif not _same_reference(left.provider_algorithm, right.provider_algorithm):
            _append(reasons, ComparabilityReasonCode.PROVIDER_ALGORITHM_MISMATCH)
    if left_identity.acquisition.sensor_channel != right_identity.acquisition.sensor_channel:
        _append(reasons, ComparabilityReasonCode.CHANNEL_MISMATCH)
    if not _same_reference(
        left_identity.acquisition.hardware_firmware,
        right_identity.acquisition.hardware_firmware,
    ):
        _append(reasons, ComparabilityReasonCode.SOURCE_PROCESSING_MISMATCH)


def _compare_processing(
    left: ExternalLoadMeasurementIdentity,
    right: ExternalLoadMeasurementIdentity,
    reasons: list[ComparabilityReasonCode],
    missing: list[str],
) -> None:
    left_processing = left.processing
    right_processing = right.processing
    threshold_metric_families = {
        ExternalLoadMetricFamily.THRESHOLD_DISTANCE,
        ExternalLoadMetricFamily.THRESHOLD_TIME,
        ExternalLoadMetricFamily.THRESHOLD_EVENT_COUNT,
        ExternalLoadMetricFamily.SPRINT_DISTANCE,
        ExternalLoadMetricFamily.SPRINT_TIME,
        ExternalLoadMetricFamily.SPRINT_EVENT_COUNT,
    }
    if (
        left.metric_family in threshold_metric_families
        or right.metric_family in threshold_metric_families
    ):
        if (
            left_processing.interpolation_method is None
            or right_processing.interpolation_method is None
        ):
            _append(reasons, ComparabilityReasonCode.UNKNOWN_INTERPOLATION)
            missing.append("threshold interpolation method")
        elif not _same_reference(
            left_processing.interpolation_method,
            right_processing.interpolation_method,
        ):
            _append(reasons, ComparabilityReasonCode.INTERPOLATION_MISMATCH)
    if (
        left_processing.filtering_status is ProcessingComponentStatus.UNKNOWN
        or right_processing.filtering_status is ProcessingComponentStatus.UNKNOWN
    ):
        _append(reasons, ComparabilityReasonCode.UNKNOWN_FILTERING)
        missing.append("filtering status")
    elif left_processing.filtering_status is not right_processing.filtering_status or tuple(
        item.stable_id for item in left_processing.filtering
    ) != tuple(item.stable_id for item in right_processing.filtering):
        _append(reasons, ComparabilityReasonCode.FILTERING_MISMATCH)
    _compare_step(
        left_processing.smoothing,
        right_processing.smoothing,
        reasons,
        missing,
        ComparabilityReasonCode.SMOOTHING_MISMATCH,
        ComparabilityReasonCode.UNKNOWN_SMOOTHING,
        "smoothing status",
    )
    _compare_step(
        left_processing.resampling,
        right_processing.resampling,
        reasons,
        missing,
        ComparabilityReasonCode.RESAMPLING_MISMATCH,
        ComparabilityReasonCode.UNKNOWN_RESAMPLING,
        "resampling status",
    )
    if left.metric_family in {
        ExternalLoadMetricFamily.ACCELERATION_EVENT_COUNT,
        ExternalLoadMetricFamily.DECELERATION_EVENT_COUNT,
    } or right.metric_family in {
        ExternalLoadMetricFamily.ACCELERATION_EVENT_COUNT,
        ExternalLoadMetricFamily.DECELERATION_EVENT_COUNT,
    }:
        if (
            left_processing.differentiation_status is ProcessingComponentStatus.UNKNOWN
            or right_processing.differentiation_status is ProcessingComponentStatus.UNKNOWN
        ):
            _append(reasons, ComparabilityReasonCode.UNKNOWN_FILTERING)
            missing.append("differentiation method")
        elif (
            left_processing.differentiation_status is not right_processing.differentiation_status
            or not _same_reference(
                left_processing.differentiation_method,
                right_processing.differentiation_method,
            )
        ):
            _append(reasons, ComparabilityReasonCode.DIFFERENTIATION_MISMATCH)
    if not _same_reference(
        left_processing.registered_operation,
        right_processing.registered_operation,
    ):
        _append(reasons, ComparabilityReasonCode.METHOD_MISMATCH)
    if left_processing.method_parameters != right_processing.method_parameters:
        _append(reasons, ComparabilityReasonCode.METHOD_MISMATCH)
    if (
        left.version.method_registry_version != right.version.method_registry_version
        or left.version.software_version != right.version.software_version
        or not _same_reference(left.version.processing_method, right.version.processing_method)
    ):
        _append(reasons, ComparabilityReasonCode.SOURCE_PROCESSING_MISMATCH)


def _compare_aggregation(
    left: ExternalLoadMeasurementIdentity,
    right: ExternalLoadMeasurementIdentity,
    reasons: list[ComparabilityReasonCode],
    missing: list[str],
) -> None:
    left_aggregation = left.aggregation
    right_aggregation = right.aggregation
    if (
        left_aggregation.scope is AggregationScope.UNKNOWN
        or right_aggregation.scope is AggregationScope.UNKNOWN
    ):
        _append(reasons, ComparabilityReasonCode.UNKNOWN_SESSION_SEGMENTATION)
        missing.append("session aggregation scope")
    if left_aggregation.session_definition is None or right_aggregation.session_definition is None:
        _append(reasons, ComparabilityReasonCode.UNKNOWN_SESSION_SEGMENTATION)
        missing.append("session definition")
    elif not _same_reference(
        left_aggregation.session_definition,
        right_aggregation.session_definition,
    ):
        _append(reasons, ComparabilityReasonCode.SESSION_DEFINITION_MISMATCH)
    if (
        left_aggregation.context is AggregationContext.UNKNOWN
        or right_aggregation.context is AggregationContext.UNKNOWN
    ):
        _append(reasons, ComparabilityReasonCode.UNKNOWN_SESSION_SEGMENTATION)
        missing.append("match/training aggregation context")
    elif left_aggregation.context is not right_aggregation.context:
        _append(reasons, ComparabilityReasonCode.EXPOSURE_CONTEXT_MISMATCH)
    if left_aggregation.scope is not right_aggregation.scope:
        _append(reasons, ComparabilityReasonCode.AGGREGATION_SCOPE_MISMATCH)
    if left_aggregation.window != right_aggregation.window:
        _append(reasons, ComparabilityReasonCode.INTERVAL_WINDOW_MISMATCH)


def assess_external_load_comparability(
    request: ExternalLoadComparabilityRequest,
) -> ComparabilityResult:
    """Apply the registered RES-64 identity rule with no manual override."""

    left = request.left_identity
    right = request.right_identity
    reasons: list[ComparabilityReasonCode] = []
    missing: list[str] = []
    hard_not_comparable = False

    if left.modality is not right.modality:
        _append(reasons, ComparabilityReasonCode.MODALITY_MISMATCH)
    if left.value_origin is not right.value_origin:
        _append(reasons, ComparabilityReasonCode.VALUE_ORIGIN_MISMATCH)
    for identity in (left, right):
        if identity.definition_status is ExternalLoadDefinitionStatus.UNRESOLVED:
            _append(reasons, ComparabilityReasonCode.UNKNOWN_METRIC_DEFINITION)
            missing.append("external-load metric definition")
        elif identity.definition_status is ExternalLoadDefinitionStatus.PARTIAL:
            _append(reasons, ComparabilityReasonCode.UNKNOWN_METRIC_DEFINITION)
            missing.append("complete external-load metric definition")
    for left_ref, right_ref, reason, hard in (
        (
            left.semantic.construct,
            right.semantic.construct,
            ComparabilityReasonCode.IDENTITY_MISMATCH,
            False,
        ),
        (
            left.semantic.test_family,
            right.semantic.test_family,
            ComparabilityReasonCode.IDENTITY_MISMATCH,
            False,
        ),
        (
            left.semantic.protocol,
            right.semantic.protocol,
            ComparabilityReasonCode.PROTOCOL_MISMATCH,
            False,
        ),
        (
            left.semantic.measurand,
            right.semantic.measurand,
            ComparabilityReasonCode.MEASURAND_MISMATCH,
            True,
        ),
        (
            left.semantic.metric_definition,
            right.semantic.metric_definition,
            ComparabilityReasonCode.METRIC_DEFINITION_MISMATCH,
            False,
        ),
    ):
        if not _same_reference(left_ref, right_ref):
            _append(reasons, reason)
            hard_not_comparable = hard_not_comparable or hard
    if left.metric_family is not right.metric_family:
        _append(reasons, ComparabilityReasonCode.METRIC_FAMILY_MISMATCH)
        hard_not_comparable = True

    _compare_systems(left.system, right.system, left, right, reasons, missing)
    threshold_material = left.is_threshold_metric or right.is_threshold_metric
    if threshold_material:
        _compare_thresholds(left.threshold, right.threshold, reasons, missing)
    elif left.threshold.basis is not right.threshold.basis:
        _append(reasons, ComparabilityReasonCode.THRESHOLD_BASIS_MISMATCH)
    event_material = (
        left.is_event_metric
        or right.is_event_metric
        or (left.event_definition is not None or right.event_definition is not None)
    )
    if event_material:
        if (
            (left.is_event_metric or right.is_event_metric)
            and left.event_definition is None
            and right.event_definition is None
        ):
            _append(reasons, ComparabilityReasonCode.UNKNOWN_EVENT_DEFINITION)
            missing.append("registered event definition")
        else:
            _compare_event_definitions(
                left.event_definition, right.event_definition, reasons, missing
            )
        if (
            left.metric_family is ExternalLoadMetricFamily.ACCELERATION_EVENT_COUNT
            or right.metric_family is ExternalLoadMetricFamily.ACCELERATION_EVENT_COUNT
        ):
            if (
                left.event_definition is None
                or right.event_definition is None
                or left.event_definition.acceleration_threshold is None
                or right.event_definition.acceleration_threshold is None
            ):
                _append(reasons, ComparabilityReasonCode.UNKNOWN_THRESHOLD)
                missing.append("acceleration threshold identity")
        if (
            left.metric_family is ExternalLoadMetricFamily.DECELERATION_EVENT_COUNT
            or right.metric_family is ExternalLoadMetricFamily.DECELERATION_EVENT_COUNT
        ):
            if (
                left.event_definition is None
                or right.event_definition is None
                or left.event_definition.deceleration_threshold is None
                or right.event_definition.deceleration_threshold is None
            ):
                _append(reasons, ComparabilityReasonCode.UNKNOWN_THRESHOLD)
                missing.append("deceleration threshold identity")
    _compare_aggregation(left, right, reasons, missing)
    _compare_processing(left, right, reasons, missing)
    if (
        left.normalization.kind is NormalizationKind.UNKNOWN
        or right.normalization.kind is NormalizationKind.UNKNOWN
    ):
        _append(reasons, ComparabilityReasonCode.NORMALIZATION_MISMATCH)
        missing.append("normalization identity")
    elif left.normalization != right.normalization:
        _append(reasons, ComparabilityReasonCode.NORMALIZATION_MISMATCH)
    left_unit = left.processing.unit
    right_unit = right.processing.unit
    if left_unit is None or right_unit is None:
        _append(reasons, ComparabilityReasonCode.MISSING_METADATA)
        missing.append("output unit")
    elif not _same_unit(left_unit, right_unit):
        try:
            convert_external_load_value(1.0, left_unit, right_unit)
        except ExternalLoadComputationError:
            _append(reasons, ComparabilityReasonCode.UNIT_OR_NORMALIZATION_MISMATCH)

    if not reasons:
        if request.requested_transformations:
            return _result(
                request,
                state=ComparabilityState.REQUIRES_TRANSFORMATION,
                reasons=(ComparabilityReasonCode.TRANSFORMATION_REQUIRED,),
                conditions=("the requested registered transformation must be applied first",),
                transformations=request.requested_transformations,
            )
        return _result(request, state=ComparabilityState.COMPARABLE)

    unique_missing = tuple(dict.fromkeys(missing))
    unknown_reasons = {
        ComparabilityReasonCode.UNKNOWN_THRESHOLD,
        ComparabilityReasonCode.UNKNOWN_THRESHOLD_BASIS,
        ComparabilityReasonCode.UNKNOWN_DWELL_RULE,
        ComparabilityReasonCode.UNKNOWN_EVENT_DEFINITION,
        ComparabilityReasonCode.UNKNOWN_FILTERING,
        ComparabilityReasonCode.UNKNOWN_SAMPLING_RATE,
        ComparabilityReasonCode.UNKNOWN_PROVIDER_ALGORITHM,
        ComparabilityReasonCode.UNKNOWN_SESSION_SEGMENTATION,
        ComparabilityReasonCode.MISSING_METADATA,
        ComparabilityReasonCode.UNKNOWN_METRIC_DEFINITION,
        ComparabilityReasonCode.UNKNOWN_INTERPOLATION,
        ComparabilityReasonCode.UNKNOWN_SMOOTHING,
        ComparabilityReasonCode.UNKNOWN_RESAMPLING,
    }
    if any(reason in unknown_reasons for reason in reasons):
        state = ComparabilityState.INSUFFICIENT_INFORMATION
        conditions: tuple[str, ...] = (
            "resolve every material external-load identity field before comparison",
        )
    elif hard_not_comparable:
        state = ComparabilityState.NOT_COMPARABLE
        conditions = ()
    else:
        state = ComparabilityState.BRIDGE_VALIDATION_REQUIRED
        conditions = (
            "a registered deterministic or validated modality/provider bridge is required",
        )
    return _result(
        request,
        state=state,
        reasons=tuple(reasons),
        conditions=conditions,
        transformations=request.requested_transformations,
        missing_information=unique_missing,
    )


def _result(
    request: ExternalLoadComparabilityRequest,
    *,
    state: ComparabilityState,
    reasons: tuple[ComparabilityReasonCode, ...] = (),
    conditions: tuple[str, ...] = (),
    transformations: tuple[TransformationRequest, ...] = (),
    missing_information: tuple[str, ...] = (),
) -> ComparabilityResult:
    return ComparabilityResult(
        result_id=InstanceIdentifier(
            "comparability-result",
            f"external-load:{request.request_id.value}:{state.value.lower()}",
        ),
        request_id=request.request_id,
        state=state,
        reason_codes=tuple(reasons),
        conditions=conditions,
        transformations_required=transformations,
        missing_information=missing_information,
        rule_reference=EXTERNAL_LOAD_COMPARABILITY_RULE,
        evidence_references=(),
        decided_by=ComparabilityDecisionSource.DETERMINISTIC_RULE,
    )


def compare_external_load_measurement_identities(
    left_identity: ExternalLoadMeasurementIdentity,
    right_identity: ExternalLoadMeasurementIdentity,
    *,
    claim: str,
    request_id: InstanceIdentifier,
    left_observation_id: InstanceIdentifier,
    right_observation_id: InstanceIdentifier,
    requested_transformations: tuple[TransformationRequest, ...] = (),
) -> ComparabilityResult:
    """Convenience constructor for an external-load identity comparison."""

    return assess_external_load_comparability(
        ExternalLoadComparabilityRequest(
            request_id=request_id,
            left_observation_id=left_observation_id,
            right_observation_id=right_observation_id,
            left_identity=left_identity,
            right_identity=right_identity,
            claim=claim,
            requested_transformations=requested_transformations,
        )
    )


def compare_external_load_observations(
    left: ScientificMeasurementObservation,
    right: ScientificMeasurementObservation,
    *,
    claim: str,
    request_id: InstanceIdentifier,
    requested_transformations: tuple[TransformationRequest, ...] = (),
) -> ComparabilityResult:
    """Compare two existing generic observations without replacing their provenance."""

    if not isinstance(left, ScientificMeasurementObservation) or not isinstance(
        right,
        ScientificMeasurementObservation,
    ):
        raise ValueError("left and right must be ScientificMeasurementObservation values")
    if not isinstance(left.identity, ExternalLoadMeasurementIdentity) or not isinstance(
        right.identity,
        ExternalLoadMeasurementIdentity,
    ):
        raise ValueError("both observations must carry external-load identities")
    return compare_external_load_measurement_identities(
        left.identity,
        right.identity,
        claim=claim,
        request_id=request_id,
        left_observation_id=left.observation_id,
        right_observation_id=right.observation_id,
        requested_transformations=requested_transformations,
    )


# Concise aliases used in the vertical module documentation.
assess_external_load_measurement_comparability = assess_external_load_comparability
compare_external_load_identities = compare_external_load_measurement_identities


__all__ = [
    "ExternalLoadComparabilityRequest",
    "assess_external_load_comparability",
    "assess_external_load_measurement_comparability",
    "compare_external_load_identities",
    "compare_external_load_measurement_identities",
    "compare_external_load_observations",
]
