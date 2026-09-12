"""Registered deterministic external-load metric operations."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from enum import StrEnum
from itertools import pairwise

from dynamislm.external_load.identity import (
    AggregationScope,
    EventHysteresisStatus,
    ExternalLoadDefinitionStatus,
    ExternalLoadEventDefinition,
    ExternalLoadMeasurementIdentity,
    ExternalLoadMetricFamily,
    ExternalLoadNormalizationIdentity,
    ExternalLoadThresholdIdentity,
    NormalizationKind,
    ProcessingComponentStatus,
    ThresholdBasis,
    ThresholdBoundary,
)
from dynamislm.external_load.registry import (
    EXTERNAL_LOAD_COUNT,
    EXTERNAL_LOAD_DISTANCE_MEASURAND,
    EXTERNAL_LOAD_KILOMETER,
    EXTERNAL_LOAD_KILOMETERS_PER_HOUR,
    EXTERNAL_LOAD_LINEAR_INTERPOLATION,
    EXTERNAL_LOAD_METER,
    EXTERNAL_LOAD_METERS_PER_MINUTE,
    EXTERNAL_LOAD_METERS_PER_SECOND,
    EXTERNAL_LOAD_MINUTE,
    EXTERNAL_LOAD_RELATIVE_DISTANCE_METRIC,
    EXTERNAL_LOAD_RELATIVE_DISTANCE_OPERATION,
    EXTERNAL_LOAD_SECOND,
    EXTERNAL_LOAD_THRESHOLD_SUMMARY_OPERATION,
)
from dynamislm.measurement.identity import (
    InstanceIdentifier,
    MetadataEntry,
    RegistryReference,
    ScientificIdentifier,
    UnitReference,
    _require_instance,
    _require_number,
    _require_optional_instance,
    require_tuple,
)
from dynamislm.measurement.result import (
    MeasurementQuality,
    MeasurementResult,
    ResultStatus,
    ScalarValue,
    UncertaintyMetadata,
)
from dynamislm.measurement.taxonomy import ScientificClassification, ScientificRole, ValueOrigin
from dynamislm.provenance.models import Provenance
from dynamislm.refusal.models import RefusalClass, RefusalReasonCode, RefusalResult, RefusalStatus
from dynamislm.serialization import canonical_hash, register_serializable_type


class ExternalLoadComputationStatus(StrEnum):
    COMPUTED = "COMPUTED"
    REFUSED = "REFUSED"


class ExternalLoadComputationError(ValueError):
    """Raised by scalar convenience functions when prerequisites are absent."""

    def __init__(self, reason_code: RefusalReasonCode, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


def _finite_number(value: object, field_name: str) -> float:
    _require_number(value, field_name)
    assert isinstance(value, int | float)
    numeric = float(value)
    if not math.isfinite(numeric):
        raise ExternalLoadComputationError(
            RefusalReasonCode.NONFINITE_INPUT,
            f"{field_name} must be finite",
        )
    return numeric


def _unit_key(unit: UnitReference) -> str:
    _require_instance(unit, UnitReference, "unit")
    if unit.identifier.stable_id not in _REGISTERED_UNIT_IDS:
        raise ExternalLoadComputationError(
            RefusalReasonCode.INCOMPATIBLE_UNITS,
            "unit is not registered by RES-64",
        )
    return unit.identifier.key


# Factor to the SI base unit for each supported dimensional family.  The
# operation never uses a display label as a unit identity.
_UNIT_FACTORS: dict[str, tuple[str, float]] = {
    EXTERNAL_LOAD_COUNT.identifier.key: ("count", 1.0),
    EXTERNAL_LOAD_METER.identifier.key: ("length", 1.0),
    EXTERNAL_LOAD_KILOMETER.identifier.key: ("length", 1000.0),
    EXTERNAL_LOAD_SECOND.identifier.key: ("time", 1.0),
    EXTERNAL_LOAD_MINUTE.identifier.key: ("time", 60.0),
    EXTERNAL_LOAD_METERS_PER_SECOND.identifier.key: ("speed", 1.0),
    EXTERNAL_LOAD_KILOMETERS_PER_HOUR.identifier.key: ("speed", 1000.0 / 3600.0),
    EXTERNAL_LOAD_METERS_PER_MINUTE.identifier.key: ("speed", 1.0 / 60.0),
}
_REGISTERED_UNIT_IDS = frozenset(
    unit.identifier.stable_id
    for unit in (
        EXTERNAL_LOAD_COUNT,
        EXTERNAL_LOAD_METER,
        EXTERNAL_LOAD_KILOMETER,
        EXTERNAL_LOAD_SECOND,
        EXTERNAL_LOAD_MINUTE,
        EXTERNAL_LOAD_METERS_PER_SECOND,
        EXTERNAL_LOAD_KILOMETERS_PER_HOUR,
        EXTERNAL_LOAD_METERS_PER_MINUTE,
    )
)


def convert_external_load_value(
    value: int | float,
    from_unit: UnitReference,
    to_unit: UnitReference,
) -> float:
    """Convert a finite value between registered compatible external units."""

    numeric = _finite_number(value, "value")
    source_key = _unit_key(from_unit)
    target_key = _unit_key(to_unit)
    try:
        source_dimension, source_factor = _UNIT_FACTORS[source_key]
        target_dimension, target_factor = _UNIT_FACTORS[target_key]
    except KeyError as exc:
        raise ExternalLoadComputationError(
            RefusalReasonCode.INCOMPATIBLE_UNITS,
            "both units must be registered external-load units",
        ) from exc
    if source_dimension != target_dimension:
        raise ExternalLoadComputationError(
            RefusalReasonCode.INCOMPATIBLE_UNITS,
            f"cannot convert {source_dimension} to {target_dimension}",
        )
    return numeric * source_factor / target_factor


def normalize_external_load_unit(
    value: int | float,
    from_unit: UnitReference,
    to_unit: UnitReference,
) -> float:
    """Readable alias for the registered unit-normalization operation."""

    return convert_external_load_value(value, from_unit, to_unit)


def duration_normalized_distance(
    total_distance: int | float | None,
    valid_duration: int | float | None,
    *,
    distance_unit: UnitReference,
    duration_unit: UnitReference,
    output_unit: UnitReference = EXTERNAL_LOAD_METERS_PER_MINUTE,
) -> float:
    """Return distance divided by explicit positive valid duration.

    ``None`` is missing data, not zero.  The output defaults to the registered
    ``m/min`` rate because that is the external-load relative-distance unit;
    callers may request another registered distance-per-time unit.
    """

    if total_distance is None:
        raise ExternalLoadComputationError(
            RefusalReasonCode.MISSING_DISTANCE,
            "total distance is required",
        )
    if valid_duration is None:
        raise ExternalLoadComputationError(
            RefusalReasonCode.MISSING_DURATION,
            "valid duration is required and is not defaulted to zero",
        )
    distance_m = convert_external_load_value(total_distance, distance_unit, EXTERNAL_LOAD_METER)
    duration_s = convert_external_load_value(valid_duration, duration_unit, EXTERNAL_LOAD_SECOND)
    if duration_s <= 0:
        raise ExternalLoadComputationError(
            RefusalReasonCode.ZERO_DURATION,
            "valid duration must be positive",
        )
    # Convert the SI distance-rate value to the requested registered rate.
    return convert_external_load_value(
        distance_m / duration_s,
        EXTERNAL_LOAD_METERS_PER_SECOND,
        output_unit,
    )


# Common names used by callers; all invoke the same registered semantics.
relative_distance = duration_normalized_distance
calculate_relative_distance = duration_normalized_distance


@register_serializable_type
@dataclass(frozen=True, slots=True)
class VelocitySample:
    """One timestamp-attached velocity sample; no implicit sampling rate."""

    time_s: float
    velocity: float
    unit: UnitReference

    def __post_init__(self) -> None:
        object.__setattr__(self, "time_s", _finite_number(self.time_s, "time_s"))
        object.__setattr__(self, "velocity", _finite_number(self.velocity, "velocity"))
        _require_instance(self.unit, UnitReference, "unit")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class VelocitySeries:
    """Immutable velocity samples with an explicit maximum accepted gap."""

    series_id: InstanceIdentifier
    samples: tuple[VelocitySample, ...]
    maximum_gap_s: float | None

    def __post_init__(self) -> None:
        _require_instance(self.series_id, InstanceIdentifier, "series_id")
        if self.series_id.instance_type != "series":
            raise ValueError("series_id must identify a series")
        require_tuple(self.samples, "samples")
        if not self.samples:
            raise ValueError("velocity series must contain at least one sample")
        previous_time: float | None = None
        for sample in self.samples:
            _require_instance(sample, VelocitySample, "samples")
            if previous_time is not None and sample.time_s <= previous_time:
                raise ValueError("velocity sample timestamps must be strictly increasing")
            previous_time = sample.time_s
        if self.maximum_gap_s is not None:
            gap = _finite_number(self.maximum_gap_s, "maximum_gap_s")
            if gap < 0:
                raise ValueError("maximum_gap_s must be non-negative")
            object.__setattr__(self, "maximum_gap_s", gap)

    @property
    def has_intervals(self) -> bool:
        return len(self.samples) >= 2


@register_serializable_type
@dataclass(frozen=True, slots=True)
class ExternalLoadMetricResult:
    """One computed scalar in the existing MeasurementResult vocabulary."""

    operation: RegistryReference
    metric_identity: ExternalLoadMeasurementIdentity
    measurement_result: MeasurementResult
    input_identity_ids: tuple[ScientificIdentifier, ...] = ()
    source_observation_ids: tuple[InstanceIdentifier, ...] = ()
    source_series_id: InstanceIdentifier | None = None
    source_provenance: tuple[Provenance, ...] = ()

    def __post_init__(self) -> None:
        _require_instance(self.operation, RegistryReference, "operation")
        if self.operation not in {
            EXTERNAL_LOAD_RELATIVE_DISTANCE_OPERATION,
            EXTERNAL_LOAD_THRESHOLD_SUMMARY_OPERATION,
        }:
            raise ValueError("external-load metric result operation is not registered")
        _require_instance(self.metric_identity, ExternalLoadMeasurementIdentity, "metric_identity")
        _require_instance(self.measurement_result, MeasurementResult, "measurement_result")
        require_tuple(self.input_identity_ids, "input_identity_ids")
        if any(not isinstance(item, ScientificIdentifier) for item in self.input_identity_ids):
            raise ValueError("input_identity_ids must contain ScientificIdentifier values")
        require_tuple(self.source_observation_ids, "source_observation_ids")
        if any(
            not isinstance(item, InstanceIdentifier) or item.instance_type != "observation"
            for item in self.source_observation_ids
        ):
            raise ValueError("source_observation_ids must identify observations")
        _require_optional_instance(self.source_series_id, InstanceIdentifier, "source_series_id")
        if self.source_series_id is not None and self.source_series_id.instance_type != "series":
            raise ValueError("source_series_id must identify a series")
        require_tuple(self.source_provenance, "source_provenance")
        if any(not isinstance(item, Provenance) for item in self.source_provenance):
            raise ValueError("source_provenance must contain Provenance values")
        if self.metric_identity.value_origin is not ValueOrigin.DYNAMISLM_DERIVED:
            raise ValueError("computed external-load results must be DYNAMISLM_DERIVED")
        if self.metric_identity.processing.registered_operation != self.operation:
            raise ValueError("metric identity must retain its registered operation")
        if self.measurement_result.classification.value_origin is not ValueOrigin.DYNAMISLM_DERIVED:
            raise ValueError("computed result classification must be DYNAMISLM_DERIVED")
        if self.measurement_result.unit != self.metric_identity.processing.unit:
            raise ValueError("computed result unit must match its metric identity")

    @property
    def value(self) -> float:
        scalar = self.measurement_result.value
        if not isinstance(scalar, ScalarValue) or isinstance(scalar.value, bool):
            raise ValueError("external-load metric result is not a numeric scalar")
        return float(scalar.value)

    @property
    def unit(self) -> UnitReference | None:
        return self.measurement_result.unit


@register_serializable_type
@dataclass(frozen=True, slots=True)
class ExternalLoadThresholdSummary:
    """Threshold time, distance, and optional event-count outputs."""

    operation: RegistryReference
    source_series_id: InstanceIdentifier
    source_identity_id: ScientificIdentifier
    threshold: ExternalLoadThresholdIdentity
    time_above_threshold_s: float
    distance_above_threshold_m: float
    event_count: int | None
    event_definition: ExternalLoadEventDefinition | None
    interpolation_method: RegistryReference = EXTERNAL_LOAD_LINEAR_INTERPOLATION

    def __post_init__(self) -> None:
        _require_instance(self.operation, RegistryReference, "operation")
        if self.operation != EXTERNAL_LOAD_THRESHOLD_SUMMARY_OPERATION:
            raise ValueError("threshold summary must use the registered threshold operation")
        if self.interpolation_method != EXTERNAL_LOAD_LINEAR_INTERPOLATION:
            raise ValueError("threshold summary must use registered linear interpolation")
        _require_instance(self.source_series_id, InstanceIdentifier, "source_series_id")
        if self.source_series_id.instance_type != "series":
            raise ValueError("source_series_id must identify a series")
        _require_instance(self.source_identity_id, ScientificIdentifier, "source_identity_id")
        _require_instance(self.threshold, ExternalLoadThresholdIdentity, "threshold")
        if not math.isfinite(self.time_above_threshold_s) or self.time_above_threshold_s < 0:
            raise ValueError("time_above_threshold_s must be finite and non-negative")
        if (
            not math.isfinite(self.distance_above_threshold_m)
            or self.distance_above_threshold_m < 0
        ):
            raise ValueError("distance_above_threshold_m must be finite and non-negative")
        if self.event_count is not None and (
            isinstance(self.event_count, bool)
            or not isinstance(self.event_count, int)
            or self.event_count < 0
        ):
            raise ValueError("event_count must be a non-negative integer when present")
        _require_optional_instance(
            self.event_definition,
            ExternalLoadEventDefinition,
            "event_definition",
        )


def _refusal(
    *,
    blocked_claim: str,
    reason_codes: tuple[RefusalReasonCode, ...],
    missing_information: tuple[str, ...] = (),
    observation_ids: tuple[InstanceIdentifier, ...] = (),
) -> RefusalResult:
    normalized_reasons = tuple(dict.fromkeys(reason.value for reason in reason_codes))
    normalized_missing = tuple(dict.fromkeys(missing_information))
    refusal_id = InstanceIdentifier(
        "refusal",
        f"external-load:{
            canonical_hash(
                {
                    'claim': blocked_claim,
                    'reasons': normalized_reasons,
                    'missing': normalized_missing,
                    'observations': observation_ids,
                }
            ).removeprefix('sha256:')[:24]
        }",
    )
    return RefusalResult(
        refusal_id=refusal_id,
        status=RefusalStatus.PARTIALLY_REFUSED if observation_ids else RefusalStatus.REFUSED,
        refusal_class=RefusalClass.COMPUTATION_NOT_REGISTERED,
        blocked_claim=blocked_claim,
        reason_codes=normalized_reasons,
        missing_information=normalized_missing,
        what_can_still_be_safely_described=(
            "the external-load observation remains independently describable under its exact "
            "modality, provider, and source identity",
            "no unsupported external-load derivation or decision claim is authorized",
        ),
        observation_ids=observation_ids,
    )


def refuse_unregistered_external_load_computation(
    identity: ExternalLoadMeasurementIdentity,
    *,
    observation_ids: tuple[InstanceIdentifier, ...] = (),
) -> RefusalResult:
    """Refuse a provider output computation that RES-64 does not own."""

    if not isinstance(identity, ExternalLoadMeasurementIdentity):
        raise ValueError("identity must be an ExternalLoadMeasurementIdentity")
    reasons = [RefusalReasonCode.EXTERNAL_LOAD_METRIC_NOT_REGISTERED]
    missing = ["registered deterministic operation for this external-load metric"]
    if identity.value_origin is ValueOrigin.PROVIDER_DERIVED:
        reasons.insert(0, RefusalReasonCode.PROVIDER_DERIVATION_NOT_RECOMPUTABLE)
        missing.insert(0, "provider algorithm inputs and exact reproducible definition")
    return _refusal(
        blocked_claim=f"derive {identity.display_label} with DynamisLM",
        reason_codes=tuple(reasons),
        missing_information=tuple(missing),
        observation_ids=observation_ids,
    )


def _derived_identity(
    source_identity: ExternalLoadMeasurementIdentity,
    *,
    metric_family: ExternalLoadMetricFamily,
    metric_reference: RegistryReference,
    unit: UnitReference,
    normalization: ExternalLoadNormalizationIdentity,
    operation: RegistryReference,
) -> ExternalLoadMeasurementIdentity:
    digest = canonical_hash(
        {
            "source_identity": source_identity,
            "metric_family": metric_family,
            "metric_reference": metric_reference,
            "unit": unit,
            "normalization": normalization,
            "operation": operation,
        }
    ).removeprefix("sha256:")[:24]
    identity_id = ScientificIdentifier(
        "dynamislm",
        "measurement-identity",
        f"external-load-{metric_family.value.lower()}-{digest}",
        operation.identifier.version,
    )
    processing = replace(
        source_identity.processing,
        registered_operation=operation,
        method_parameters=(
            *source_identity.processing.method_parameters,
            MetadataEntry("input_identity_id", source_identity.identity_id.stable_id),
            MetadataEntry("operation_id", operation.stable_id),
        ),
        unit=unit,
    )
    version = replace(
        source_identity.version,
        processing_method=operation,
        method_registry_version=operation.identifier.version,
        software_version=f"dynamislm-res64-{operation.identifier.key}-1.0.0",
    )
    semantic = replace(
        source_identity.semantic,
        measurand=EXTERNAL_LOAD_DISTANCE_MEASURAND,
        metric_definition=metric_reference,
    )
    return replace(
        source_identity,
        identity_id=identity_id,
        semantic=semantic,
        processing=processing,
        version=version,
        value_origin=ValueOrigin.DYNAMISLM_DERIVED,
        threshold=ExternalLoadThresholdIdentity.none(),
        normalization=normalization,
        event_definition=None,
        metric_family=metric_family,
        definition_status=ExternalLoadDefinitionStatus.RESOLVED,
        dynamislm_recomputable=True,
    )


def _metric_result(
    *,
    operation: RegistryReference,
    identity: ExternalLoadMeasurementIdentity,
    value: float,
    unit: UnitReference,
    input_identity_ids: tuple[ScientificIdentifier, ...],
    source_observation_ids: tuple[InstanceIdentifier, ...] = (),
    source_series_id: InstanceIdentifier | None = None,
    source_provenance: tuple[Provenance, ...] = (),
) -> ExternalLoadMetricResult:
    result_digest = canonical_hash(
        {
            "operation": operation,
            "identity": identity,
            "value": value,
            "unit": unit,
            "inputs": input_identity_ids,
            "source_observations": source_observation_ids,
            "source_series": source_series_id,
            "source_provenance": source_provenance,
        }
    ).removeprefix("sha256:")[:24]
    return ExternalLoadMetricResult(
        operation=operation,
        metric_identity=identity,
        measurement_result=MeasurementResult(
            result_id=InstanceIdentifier("result", f"external-load:{result_digest}"),
            value=ScalarValue(value),
            unit=unit,
            classification=ScientificClassification(
                value_origin=ValueOrigin.DYNAMISLM_DERIVED,
                scientific_roles=(ScientificRole.PERFORMANCE_OUTCOME,),
            ),
            quality=MeasurementQuality(),
            uncertainty=UncertaintyMetadata(),
            status=ResultStatus.VALID,
        ),
        input_identity_ids=input_identity_ids,
        source_observation_ids=source_observation_ids,
        source_series_id=source_series_id,
        source_provenance=source_provenance,
    )


def derive_duration_normalized_distance(
    total_distance: int | float | None,
    valid_duration: int | float | None,
    *,
    distance_unit: UnitReference,
    duration_unit: UnitReference,
    source_identity: ExternalLoadMeasurementIdentity,
    duration_identity: ExternalLoadMeasurementIdentity,
    source_observation_ids: tuple[InstanceIdentifier, ...] = (),
    source_provenance: tuple[Provenance, ...] = (),
) -> ExternalLoadMetricResult | RefusalResult:
    """Derive relative distance while preserving both input identities."""

    if not isinstance(source_identity, ExternalLoadMeasurementIdentity):
        raise ValueError("source_identity must be an ExternalLoadMeasurementIdentity")
    if not isinstance(duration_identity, ExternalLoadMeasurementIdentity):
        raise ValueError("duration_identity must be an ExternalLoadMeasurementIdentity")
    if source_identity.metric_family is not ExternalLoadMetricFamily.TOTAL_DISTANCE:
        return _refusal(
            blocked_claim="derive duration-normalized relative distance",
            reason_codes=(RefusalReasonCode.METRIC_DEFINITION_MISMATCH,),
            missing_information=("a total-distance source metric identity",),
            observation_ids=source_observation_ids,
        )
    if duration_identity.metric_family not in {
        ExternalLoadMetricFamily.SESSION_DURATION,
        ExternalLoadMetricFamily.MINUTES_EXPOSURE,
    }:
        return _refusal(
            blocked_claim="derive duration-normalized relative distance",
            reason_codes=(RefusalReasonCode.METRIC_DEFINITION_MISMATCH,),
            missing_information=("a session-duration or minutes-exposure identity",),
            observation_ids=source_observation_ids,
        )
    if source_identity.aggregation != duration_identity.aggregation:
        return _refusal(
            blocked_claim="derive duration-normalized relative distance",
            reason_codes=(RefusalReasonCode.SOURCE_PROCESSING_MISMATCH,),
            missing_information=("matching source distance and duration aggregation identity",),
            observation_ids=source_observation_ids,
        )
    try:
        value = duration_normalized_distance(
            total_distance,
            valid_duration,
            distance_unit=distance_unit,
            duration_unit=duration_unit,
        )
    except ExternalLoadComputationError as exc:
        return _refusal(
            blocked_claim="derive duration-normalized relative distance",
            reason_codes=(exc.reason_code,),
            missing_information=(str(exc),),
            observation_ids=source_observation_ids,
        )
    identity = _derived_identity(
        source_identity,
        metric_family=ExternalLoadMetricFamily.RELATIVE_DISTANCE,
        metric_reference=EXTERNAL_LOAD_RELATIVE_DISTANCE_METRIC,
        unit=EXTERNAL_LOAD_METERS_PER_MINUTE,
        normalization=ExternalLoadNormalizationIdentity(
            kind=NormalizationKind.DURATION_NORMALIZED,
            method=EXTERNAL_LOAD_RELATIVE_DISTANCE_OPERATION,
            parameters=(MetadataEntry("duration_semantics", "explicit valid exposure duration"),),
        ),
        operation=EXTERNAL_LOAD_RELATIVE_DISTANCE_OPERATION,
    )
    return _metric_result(
        operation=EXTERNAL_LOAD_RELATIVE_DISTANCE_OPERATION,
        identity=identity,
        value=value,
        unit=EXTERNAL_LOAD_METERS_PER_MINUTE,
        input_identity_ids=(source_identity.identity_id, duration_identity.identity_id),
        source_observation_ids=source_observation_ids,
        source_provenance=source_provenance,
    )


def _predicate(value: float, threshold: float, boundary: ThresholdBoundary) -> bool:
    if boundary is ThresholdBoundary.GREATER_THAN:
        return value > threshold
    if boundary is ThresholdBoundary.GREATER_THAN_OR_EQUAL:
        return value >= threshold
    if boundary is ThresholdBoundary.LESS_THAN:
        return value < threshold
    if boundary is ThresholdBoundary.LESS_THAN_OR_EQUAL:
        return value <= threshold
    raise ValueError("threshold boundary is unresolved")


def _qualified_intervals(
    series: VelocitySeries,
    threshold_m_per_s: float,
    boundary: ThresholdBoundary,
) -> tuple[tuple[float, float], ...]:
    intervals: list[tuple[float, float]] = []
    for left, right in pairwise(series.samples):
        t0, t1 = left.time_s, right.time_s
        v0_mps = convert_external_load_value(
            left.velocity,
            left.unit,
            EXTERNAL_LOAD_METERS_PER_SECOND,
        )
        v1_mps = convert_external_load_value(
            right.velocity,
            right.unit,
            EXTERNAL_LOAD_METERS_PER_SECOND,
        )
        cuts = [0.0, 1.0]
        delta = v1_mps - v0_mps
        if delta != 0:
            fraction = (threshold_m_per_s - v0_mps) / delta
            if 0.0 < fraction < 1.0:
                cuts.append(fraction)
        cuts.sort()
        for start_fraction, end_fraction in pairwise(cuts):
            start_t = t0 + (t1 - t0) * start_fraction
            end_t = t0 + (t1 - t0) * end_fraction
            midpoint_fraction = (start_fraction + end_fraction) / 2.0
            midpoint_velocity = v0_mps + delta * midpoint_fraction
            if _predicate(midpoint_velocity, threshold_m_per_s, boundary):
                intervals.append((start_t, end_t))
    return tuple(intervals)


def _merge_intervals(
    intervals: tuple[tuple[float, float], ...], gap_allowance_s: float
) -> tuple[tuple[float, float], ...]:
    if not intervals:
        return ()
    merged: list[list[float]] = [[intervals[0][0], intervals[0][1]]]
    for start, end in intervals[1:]:
        previous = merged[-1]
        if start - previous[1] <= gap_allowance_s:
            previous[1] = max(previous[1], end)
        else:
            merged.append([start, end])
    return tuple((start, end) for start, end in merged)


def _integrate_qualified_distance(
    series: VelocitySeries,
    threshold_m_per_s: float,
    boundary: ThresholdBoundary,
) -> tuple[float, float]:
    time_s = 0.0
    distance_m = 0.0
    for left, right in pairwise(series.samples):
        t0, t1 = left.time_s, right.time_s
        dt = t1 - t0
        v0 = convert_external_load_value(left.velocity, left.unit, EXTERNAL_LOAD_METERS_PER_SECOND)
        v1 = convert_external_load_value(
            right.velocity,
            right.unit,
            EXTERNAL_LOAD_METERS_PER_SECOND,
        )
        delta = v1 - v0
        cuts = [0.0, 1.0]
        if delta != 0:
            crossing = (threshold_m_per_s - v0) / delta
            if 0.0 < crossing < 1.0:
                cuts.append(crossing)
        cuts.sort()
        for start_fraction, end_fraction in pairwise(cuts):
            span_fraction = end_fraction - start_fraction
            midpoint = (start_fraction + end_fraction) / 2.0
            if not _predicate(v0 + delta * midpoint, threshold_m_per_s, boundary):
                continue
            time_s += dt * span_fraction
            average_velocity = v0 + delta * (start_fraction + end_fraction) / 2.0
            distance_m += dt * span_fraction * average_velocity
    return time_s, distance_m


def summarize_velocity_threshold(
    series: VelocitySeries,
    identity: ExternalLoadMeasurementIdentity,
) -> ExternalLoadThresholdSummary | RefusalResult:
    """Summarize a resolved velocity threshold from actual timestamped samples.

    The operation uses piecewise-linear interpolation only between supplied
    samples.  It never extrapolates before the first sample or after the last,
    and it never infers missing samples or a sampling rate.
    """

    if not isinstance(series, VelocitySeries):
        raise ValueError("series must be a VelocitySeries")
    if not isinstance(identity, ExternalLoadMeasurementIdentity):
        raise ValueError("identity must be an ExternalLoadMeasurementIdentity")
    supported_metric_families = {
        ExternalLoadMetricFamily.THRESHOLD_DISTANCE,
        ExternalLoadMetricFamily.THRESHOLD_TIME,
        ExternalLoadMetricFamily.THRESHOLD_EVENT_COUNT,
        ExternalLoadMetricFamily.SPRINT_DISTANCE,
        ExternalLoadMetricFamily.SPRINT_TIME,
        ExternalLoadMetricFamily.SPRINT_EVENT_COUNT,
    }
    if identity.metric_family not in supported_metric_families:
        return _refusal(
            blocked_claim="compute external-load velocity threshold summary",
            reason_codes=(RefusalReasonCode.EXTERNAL_LOAD_METRIC_NOT_REGISTERED,),
            missing_information=(
                "a registered velocity threshold operation for this metric family",
            ),
        )
    if identity.definition_status is not ExternalLoadDefinitionStatus.RESOLVED:
        return _refusal(
            blocked_claim="compute external-load velocity threshold summary",
            reason_codes=(RefusalReasonCode.UNKNOWN_METRIC_DEFINITION,),
            missing_information=("complete registered external-load metric definition",),
        )
    reasons: list[RefusalReasonCode] = []
    missing: list[str] = []
    threshold = identity.threshold
    if not threshold.is_resolved:
        reasons.append(RefusalReasonCode.UNKNOWN_THRESHOLD)
        if threshold.basis is ThresholdBasis.UNKNOWN:
            reasons.append(RefusalReasonCode.UNKNOWN_THRESHOLD_BASIS)
        missing.append("resolved threshold quantity, value, unit, basis, and boundary")
    if threshold.boundary in (ThresholdBoundary.UNKNOWN, ThresholdBoundary.NONE):
        reasons.append(RefusalReasonCode.BOUNDARY_SEMANTICS_MISSING)
        missing.append("threshold boundary semantics")
    if identity.processing.filtering_status is ProcessingComponentStatus.UNKNOWN:
        reasons.append(RefusalReasonCode.UNKNOWN_FILTERING)
        missing.append("filtering status")
    if identity.processing.interpolation_method is None:
        reasons.append(RefusalReasonCode.UNKNOWN_INTERPOLATION)
        missing.append("threshold interpolation method")
    elif identity.processing.interpolation_method != EXTERNAL_LOAD_LINEAR_INTERPOLATION:
        reasons.append(RefusalReasonCode.EXTERNAL_LOAD_METRIC_NOT_REGISTERED)
        missing.append("registered piecewise-linear threshold interpolation method")
    if identity.processing.smoothing.status is ProcessingComponentStatus.UNKNOWN:
        reasons.append(RefusalReasonCode.UNKNOWN_SMOOTHING)
        missing.append("smoothing status")
    if identity.processing.resampling.status is ProcessingComponentStatus.UNKNOWN:
        reasons.append(RefusalReasonCode.UNKNOWN_RESAMPLING)
        missing.append("resampling status")
    if identity.aggregation.scope is AggregationScope.UNKNOWN:
        reasons.append(RefusalReasonCode.UNKNOWN_SESSION_SEGMENTATION)
        missing.append("session aggregation scope")
    if identity.aggregation.session_definition is None:
        reasons.append(RefusalReasonCode.UNKNOWN_SESSION_SEGMENTATION)
        missing.append("session definition")
    if identity.aggregation.scope is AggregationScope.PERIOD_OR_SEGMENT:
        window = identity.aggregation.window
        if window.start_s is None or window.end_s is None:
            reasons.append(RefusalReasonCode.UNKNOWN_SESSION_SEGMENTATION)
            missing.append("numeric aggregation window bounds")
        elif series.samples[0].time_s < window.start_s or series.samples[-1].time_s > window.end_s:
            reasons.append(RefusalReasonCode.INVALID_TIME_SERIES)
            missing.append("velocity samples restricted to the declared aggregation window")
    if series.maximum_gap_s is None:
        reasons.append(RefusalReasonCode.UNDECLARED_TIME_GAP)
        missing.append("maximum accepted sample gap")
    else:
        for left, right in pairwise(series.samples):
            if right.time_s - left.time_s > series.maximum_gap_s:
                reasons.append(RefusalReasonCode.UNDECLARED_TIME_GAP)
                missing.append("sample gap exceeds declared maximum")
                break
    if identity.is_event_metric:
        event = identity.event_definition
        if event is None:
            reasons.append(RefusalReasonCode.UNKNOWN_EVENT_DEFINITION)
            missing.append("registered event definition")
        elif event.minimum_duration_s is None:
            reasons.append(RefusalReasonCode.UNKNOWN_DWELL_RULE)
            missing.append("minimum event duration/dwell")
        elif event.gap_allowance_s is None:
            reasons.append(RefusalReasonCode.UNKNOWN_DWELL_RULE)
            missing.append("event gap allowance")
        elif not event.is_resolved_for_event_count:
            reasons.append(RefusalReasonCode.UNKNOWN_EVENT_DEFINITION)
            missing.append("complete event start/end and hysteresis identity")
    if reasons:
        return _refusal(
            blocked_claim="compute external-load velocity threshold summary",
            reason_codes=tuple(dict.fromkeys(reasons)),
            missing_information=tuple(dict.fromkeys(missing)),
        )
    assert threshold.threshold_value is not None
    assert threshold.threshold_unit is not None
    try:
        threshold_mps = convert_external_load_value(
            threshold.threshold_value,
            threshold.threshold_unit,
            EXTERNAL_LOAD_METERS_PER_SECOND,
        )
        time_s, distance_m = _integrate_qualified_distance(
            series,
            threshold_mps,
            threshold.boundary,
        )
    except ExternalLoadComputationError as exc:
        return _refusal(
            blocked_claim="compute external-load velocity threshold summary",
            reason_codes=(exc.reason_code,),
            missing_information=(str(exc),),
        )
    event_count: int | None = None
    event_definition = identity.event_definition
    if identity.is_event_metric:
        assert event_definition is not None
        if event_definition.hysteresis_status is EventHysteresisStatus.DEFINED:
            return _refusal(
                blocked_claim="compute external-load velocity threshold event count",
                reason_codes=(RefusalReasonCode.EXTERNAL_LOAD_METRIC_NOT_REGISTERED,),
                missing_information=("registered hysteresis-aware threshold event operation",),
            )
        assert event_definition.minimum_duration_s is not None
        assert event_definition.gap_allowance_s is not None
        intervals = _qualified_intervals(series, threshold_mps, threshold.boundary)
        merged = _merge_intervals(intervals, event_definition.gap_allowance_s)
        event_count = sum(
            end - start >= event_definition.minimum_duration_s for start, end in merged
        )
        event_count = int(event_count)
    return ExternalLoadThresholdSummary(
        operation=EXTERNAL_LOAD_THRESHOLD_SUMMARY_OPERATION,
        source_series_id=series.series_id,
        source_identity_id=identity.identity_id,
        threshold=threshold,
        time_above_threshold_s=time_s,
        distance_above_threshold_m=distance_m,
        event_count=event_count,
        event_definition=event_definition,
    )


# Readable aliases for the registered threshold operation.
calculate_velocity_threshold_summary = summarize_velocity_threshold
threshold_summary_from_velocity_series = summarize_velocity_threshold


__all__ = [
    "ExternalLoadComputationError",
    "ExternalLoadComputationStatus",
    "ExternalLoadMetricResult",
    "ExternalLoadThresholdSummary",
    "VelocitySample",
    "VelocitySeries",
    "calculate_relative_distance",
    "calculate_velocity_threshold_summary",
    "convert_external_load_value",
    "derive_duration_normalized_distance",
    "duration_normalized_distance",
    "normalize_external_load_unit",
    "refuse_unregistered_external_load_computation",
    "relative_distance",
    "summarize_velocity_threshold",
    "threshold_summary_from_velocity_series",
]
