"""Claim-relative BPT comparability; no provider/derived relabelling."""

from __future__ import annotations

from dataclasses import dataclass

from dynamislm.comparability.models import (
    ComparabilityDecisionSource,
    ComparabilityReasonCode,
    ComparabilityRequest,
    ComparabilityResult,
    ComparabilityState,
)
from dynamislm.measurement.bench_press_throw.identity import (
    BPTAcquisitionIdentity,
    BPTMeasurementIdentity,
    BPTProcessingIdentity,
    BPTProtocolIdentity,
)
from dynamislm.measurement.bench_press_throw.metrics import (
    BenchPressThrowMetricResult,
    BPTProviderMetricResult,
)
from dynamislm.measurement.bench_press_throw.registry import (
    BPT_COMPARABILITY_RULE,
    BPT_PROVIDER_MAXIMUM_VELOCITY_METRIC,
    BPT_PROVIDER_MEAN_POWER_METRIC,
    BPT_PROVIDER_MEAN_PROPULSIVE_VELOCITY_METRIC,
    BPT_PROVIDER_MEAN_VELOCITY_METRIC,
    BPT_PROVIDER_PEAK_POWER_METRIC,
    BPT_TEST_FAMILY,
    RES68_DECISION_EXPLOSIVE_TEST_FAMILY,
)
from dynamislm.measurement.identity import InstanceIdentifier
from dynamislm.measurement.observation import ScientificMeasurementObservation
from dynamislm.serialization import canonical_hash, register_serializable_type


@register_serializable_type
@dataclass(frozen=True, slots=True)
class BPTComparabilityRequest:
    request_id: InstanceIdentifier
    left_observation_id: InstanceIdentifier
    right_observation_id: InstanceIdentifier
    claim: str

    def __post_init__(self) -> None:
        if self.request_id.instance_type != "comparability-request":
            raise ValueError("BPT request ID must identify a comparability request")
        if self.left_observation_id == self.right_observation_id:
            raise ValueError("BPT comparison requires two observations")
        if not self.claim.strip():
            raise ValueError("BPT claim must not be empty")


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
        result_id=InstanceIdentifier("comparability-result", f"bpt:{digest}"),
        request_id=request.request_id,
        state=state,
        reason_codes=tuple(reason.value for reason in reasons),
        conditions=conditions,
        transformations_required=(),
        missing_information=missing,
        rule_reference=BPT_COMPARABILITY_RULE,
        evidence_references=(RES68_DECISION_EXPLOSIVE_TEST_FAMILY,),
        decided_by=ComparabilityDecisionSource.DETERMINISTIC_RULE,
    )


def _observation(
    item: BenchPressThrowMetricResult | BPTProviderMetricResult,
) -> ScientificMeasurementObservation:
    return item.observation


def _protocol_signature(protocol: BPTProtocolIdentity) -> tuple[object, ...]:
    """Compare method/mechanics, not source-instance or provider metadata."""

    return (
        protocol.reference,
        protocol.protocol_version,
        protocol.machine_type,
        protocol.counterbalance_status,
        protocol.counterbalance_identity,
        protocol.load_identity,
        protocol.concentric_pattern,
        protocol.pause_touch_bounce,
        protocol.grip,
        protocol.range_of_motion,
        protocol.feet_body_support,
        protocol.release_semantics,
        protocol.catch_semantics,
        protocol.trial_qualification,
        protocol.trial_selection,
        protocol.additional_attributes,
    )


def _acquisition_signature(acquisition: BPTAcquisitionIdentity) -> tuple[object, ...]:
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


def _processing_signature(processing: BPTProcessingIdentity) -> tuple[object, ...]:
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


def _support_signature(result: BenchPressThrowMetricResult) -> tuple[object, ...] | None:
    evidence = result.source_evidence
    if evidence is None:
        return None
    support = evidence.support
    return (
        support.metric,
        support.support_definition,
        support.includes_post_release_samples,
        evidence.series.timebase,
        evidence.series.velocity_frame,
        evidence.series.sign_convention,
    )


def compare_bpt_metric_results(
    left: BenchPressThrowMetricResult | BPTProviderMetricResult,
    right: BenchPressThrowMetricResult | BPTProviderMetricResult,
    claim: str = "compare BPT metric results",
) -> ComparabilityResult:
    """Adjudicate BPT comparisons using exact metric and mechanical identity."""

    left_observation = _observation(left)
    right_observation = _observation(right)
    left_id = left_observation.observation_id
    right_id = right_observation.observation_id
    request_id = InstanceIdentifier(
        "comparability-request",
        canonical_hash({"left": left_id, "right": right_id, "claim": claim}).removeprefix(
            "sha256:"
        )[:24],
    )
    try:
        if not isinstance(
            left, BenchPressThrowMetricResult | BPTProviderMetricResult
        ) or not isinstance(right, BenchPressThrowMetricResult | BPTProviderMetricResult):
            raise ValueError("typed BPT metric results are required")
        request = ComparabilityRequest(
            request_id=request_id,
            left_observation_id=left.observation.observation_id,
            right_observation_id=right.observation.observation_id,
            claim=claim,
            material_dimensions=(
                "metric",
                "protocol",
                "machine_type",
                "counterbalance",
                "moving_system_load",
                "device",
                "support",
                "value_origin",
            ),
        )
    except (AttributeError, TypeError, ValueError):
        fallback = ComparabilityRequest(
            request_id=request_id,
            left_observation_id=left_id,
            right_observation_id=right_id,
            claim=claim or "invalid BPT comparison",
        )
        if hasattr(left, "observation") and hasattr(right, "observation"):
            return _result(
                fallback,
                ComparabilityState.NOT_COMPARABLE,
                (ComparabilityReasonCode.METRIC_FAMILY_MISMATCH,),
            )
        return _result(
            fallback,
            ComparabilityState.INSUFFICIENT_INFORMATION,
            (ComparabilityReasonCode.MISSING_METADATA,),
            missing=("two typed BPT metric results",),
        )

    left_metric = left.metric
    right_metric = right.metric
    provider_metrics = {
        BPT_PROVIDER_MEAN_VELOCITY_METRIC,
        BPT_PROVIDER_MAXIMUM_VELOCITY_METRIC,
        BPT_PROVIDER_MEAN_PROPULSIVE_VELOCITY_METRIC,
        BPT_PROVIDER_MEAN_POWER_METRIC,
        BPT_PROVIDER_PEAK_POWER_METRIC,
    }
    if left_metric != right_metric:
        if (left_metric in provider_metrics) != (right_metric in provider_metrics):
            return _result(
                request,
                ComparabilityState.BRIDGE_VALIDATION_REQUIRED,
                (ComparabilityReasonCode.VALUE_ORIGIN_MISMATCH,),
                conditions=("provider-to-DynamisLM metric agreement bridge",),
            )
        if left_metric in {
            BPT_PROVIDER_MEAN_POWER_METRIC,
            BPT_PROVIDER_PEAK_POWER_METRIC,
        } or right_metric in {
            BPT_PROVIDER_MEAN_POWER_METRIC,
            BPT_PROVIDER_PEAK_POWER_METRIC,
        }:
            return _result(
                request,
                ComparabilityState.NOT_COMPARABLE,
                (ComparabilityReasonCode.MEASURAND_MISMATCH,),
            )
        return _result(
            request,
            ComparabilityState.NOT_COMPARABLE,
            (ComparabilityReasonCode.METRIC_DEFINITION_MISMATCH,),
        )
    left_identity = left.observation.identity
    right_identity = right.observation.identity
    if not isinstance(left_identity, BPTMeasurementIdentity) or not isinstance(
        right_identity, BPTMeasurementIdentity
    ):
        return _result(
            request,
            ComparabilityState.NOT_COMPARABLE,
            (ComparabilityReasonCode.METRIC_FAMILY_MISMATCH,),
        )
    if (
        left_identity.semantic.test_family != BPT_TEST_FAMILY
        or right_identity.semantic.test_family != BPT_TEST_FAMILY
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
            missing=("complete BPT protocol identity",),
        )
    if (
        left_protocol.machine_type.value == "UNKNOWN"
        or right_protocol.machine_type.value == "UNKNOWN"
    ):
        return _result(
            request,
            ComparabilityState.INSUFFICIENT_INFORMATION,
            (ComparabilityReasonCode.MISSING_METADATA,),
            missing=("BPT machine type",),
        )
    if (
        left_protocol.counterbalance_status.value == "UNKNOWN"
        or right_protocol.counterbalance_status.value == "UNKNOWN"
    ):
        return _result(
            request,
            ComparabilityState.INSUFFICIENT_INFORMATION,
            (ComparabilityReasonCode.MISSING_METADATA,),
            missing=("BPT counterbalance status",),
        )
    if left_protocol.load_identity is None or right_protocol.load_identity is None:
        return _result(
            request,
            ComparabilityState.INSUFFICIENT_INFORMATION,
            (ComparabilityReasonCode.MISSING_METADATA,),
            missing=("BPT moving-system load identity",),
        )
    if _protocol_signature(left_protocol) != _protocol_signature(right_protocol):
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
            missing=("BPT device identity",),
        )
    if _acquisition_signature(left_acquisition) != _acquisition_signature(right_acquisition):
        return _result(
            request,
            ComparabilityState.BRIDGE_VALIDATION_REQUIRED,
            (ComparabilityReasonCode.DEVICE_MISMATCH,),
        )
    if _processing_signature(left_identity.processing) != _processing_signature(
        right_identity.processing
    ):
        return _result(
            request,
            ComparabilityState.BRIDGE_VALIDATION_REQUIRED,
            (ComparabilityReasonCode.SOURCE_PROCESSING_MISMATCH,),
        )
    if isinstance(left, BPTProviderMetricResult) != isinstance(right, BPTProviderMetricResult):
        return _result(
            request,
            ComparabilityState.BRIDGE_VALIDATION_REQUIRED,
            (ComparabilityReasonCode.VALUE_ORIGIN_MISMATCH,),
        )
    if isinstance(left, BenchPressThrowMetricResult) and isinstance(
        right, BenchPressThrowMetricResult
    ):
        if _support_signature(left) != _support_signature(right):
            return _result(
                request,
                ComparabilityState.BRIDGE_VALIDATION_REQUIRED,
                (ComparabilityReasonCode.SAMPLE_OR_TIMEBASE_MISMATCH,),
            )
    return _result(request, ComparabilityState.COMPARABLE, ())


def assess_bpt_comparability(
    left: BenchPressThrowMetricResult | BPTProviderMetricResult,
    right: BenchPressThrowMetricResult | BPTProviderMetricResult,
    claim: str = "compare BPT metric results",
) -> ComparabilityResult:
    return compare_bpt_metric_results(left, right, claim)


compare_bench_press_throw_results = compare_bpt_metric_results


__all__ = [
    "BPTComparabilityRequest",
    "assess_bpt_comparability",
    "compare_bench_press_throw_results",
    "compare_bpt_metric_results",
]
