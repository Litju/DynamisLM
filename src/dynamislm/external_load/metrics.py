"""Registered deterministic external-load metric operations."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from enum import StrEnum
from itertools import pairwise
from typing import Any

from dynamislm.external_load.identity import (
    AggregationScope,
    EventHysteresisStatus,
    ExternalLoadDefinitionStatus,
    ExternalLoadEventDefinition,
    ExternalLoadMeasurementIdentity,
    ExternalLoadMetricFamily,
    ExternalLoadNormalizationIdentity,
    ExternalLoadProcessingIdentity,
    ExternalLoadSystemIdentity,
    ExternalLoadThresholdIdentity,
    NormalizationKind,
    ProcessingComponentStatus,
    ThresholdBasis,
    ThresholdBoundary,
)
from dynamislm.external_load.registry import (
    EXTERNAL_LOAD_COUNT,
    EXTERNAL_LOAD_DISTANCE_MEASURAND,
    EXTERNAL_LOAD_DURATION_MEASURAND,
    EXTERNAL_LOAD_EVENT_COUNT_MEASURAND,
    EXTERNAL_LOAD_KILOMETER,
    EXTERNAL_LOAD_KILOMETERS_PER_HOUR,
    EXTERNAL_LOAD_LINEAR_INTERPOLATION,
    EXTERNAL_LOAD_METER,
    EXTERNAL_LOAD_METERS_PER_MINUTE,
    EXTERNAL_LOAD_METERS_PER_SECOND,
    EXTERNAL_LOAD_MINUTE,
    EXTERNAL_LOAD_RAW_VELOCITY_SERIES_SCHEMA,
    EXTERNAL_LOAD_RELATIVE_DISTANCE_METRIC,
    EXTERNAL_LOAD_RELATIVE_DISTANCE_OPERATION,
    EXTERNAL_LOAD_SECOND,
    EXTERNAL_LOAD_SPEED_MEASURAND,
    EXTERNAL_LOAD_SPRINT_DISTANCE_METRIC,
    EXTERNAL_LOAD_SPRINT_EVENT_COUNT_METRIC,
    EXTERNAL_LOAD_SPRINT_TIME_METRIC,
    EXTERNAL_LOAD_THRESHOLD_DISTANCE_METRIC,
    EXTERNAL_LOAD_THRESHOLD_EVENT_COUNT_METRIC,
    EXTERNAL_LOAD_THRESHOLD_EVENT_DEFINITION,
    EXTERNAL_LOAD_THRESHOLD_EVENT_END_RULE,
    EXTERNAL_LOAD_THRESHOLD_EVENT_START_RULE,
    EXTERNAL_LOAD_THRESHOLD_SUMMARY_OPERATION,
    EXTERNAL_LOAD_THRESHOLD_TIME_METRIC,
)
from dynamislm.measurement.identity import (
    InstanceIdentifier,
    MetadataEntry,
    RegistryReference,
    SamplingCharacteristics,
    ScientificIdentifier,
    UnitReference,
    _require_instance,
    _require_number,
    _require_optional_instance,
    require_tuple,
)
from dynamislm.measurement.observation import ObservationContext, ScientificMeasurementObservation
from dynamislm.measurement.result import (
    MeasurementQuality,
    MeasurementResult,
    ResultStatus,
    ScalarValue,
    StructuredOutputReference,
    UncertaintyMetadata,
)
from dynamislm.measurement.taxonomy import ScientificClassification, ScientificRole, ValueOrigin
from dynamislm.provenance.models import (
    AcquisitionRecord,
    LineageEdge,
    LineageRelation,
    ProcessingRun,
    Provenance,
    SourceArtifact,
)
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
class ExternalLoadVelocitySeriesEvidence:
    """Immutable evidence binding a velocity series to its scientific identity."""

    series: VelocitySeries
    identity: ExternalLoadMeasurementIdentity
    context: ObservationContext
    provenance: Provenance
    observation_id: InstanceIdentifier | None = None

    def __post_init__(self) -> None:
        _require_instance(self.series, VelocitySeries, "series")
        _require_instance(self.identity, ExternalLoadMeasurementIdentity, "identity")
        _require_instance(self.context, ObservationContext, "context")
        _require_instance(self.provenance, Provenance, "provenance")
        if self.observation_id is None:
            object.__setattr__(
                self,
                "observation_id",
                InstanceIdentifier("observation", f"velocity-series:{self.series.series_id.value}"),
            )
        else:
            _require_instance(self.observation_id, InstanceIdentifier, "observation_id")
            if self.observation_id.instance_type != "observation":
                raise ValueError("observation_id must identify an observation")

    @property
    def measurement_identity(self) -> ExternalLoadMeasurementIdentity:
        """Readable name for the identity bound to the series evidence."""

        return self.identity

    @property
    def series_identity(self) -> ExternalLoadMeasurementIdentity:
        return self.identity

    @property
    def system_identity(self) -> ExternalLoadSystemIdentity:
        return self.identity.system

    @property
    def processing_identity(self) -> ExternalLoadProcessingIdentity:
        return self.identity.processing

    @property
    def sampling(self) -> SamplingCharacteristics | None:
        return self.identity.system.sampling

    @property
    def series_id(self) -> InstanceIdentifier:
        return self.series.series_id

    @property
    def bound_observation_id(self) -> InstanceIdentifier:
        assert self.observation_id is not None
        return self.observation_id

    @property
    def maximum_gap_s(self) -> float | None:
        return self.series.maximum_gap_s

    @property
    def source_artifacts(self) -> tuple[SourceArtifact, ...]:
        return self.provenance.source_artifacts

    @property
    def source_artifact(self) -> SourceArtifact | None:
        return (
            self.provenance.source_artifacts[0]
            if len(self.provenance.source_artifacts) == 1
            else None
        )

    @property
    def acquisitions(self) -> tuple[AcquisitionRecord, ...]:
        return self.provenance.acquisitions

    @property
    def acquisition(self) -> AcquisitionRecord | None:
        return self.provenance.acquisitions[0] if len(self.provenance.acquisitions) == 1 else None

    @property
    def processing_runs(self) -> tuple[ProcessingRun, ...]:
        return self.provenance.processing_runs


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
    input_observations: tuple[ScientificMeasurementObservation, ...] = ()
    source_series_evidence: ExternalLoadVelocitySeriesEvidence | None = None
    derived_observation: ScientificMeasurementObservation | None = None

    @classmethod
    def __decode_legacy_wire__(
        cls,
        value: object,
        kwargs: dict[str, Any],
    ) -> dict[str, Any]:
        """Fill additive evidence fields for historical V3 metric results."""

        del value
        kwargs.setdefault("input_observations", ())
        kwargs.setdefault("source_series_evidence", None)
        kwargs.setdefault("derived_observation", None)
        return kwargs

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
        require_tuple(self.input_observations, "input_observations")
        if any(
            not isinstance(item, ScientificMeasurementObservation)
            for item in self.input_observations
        ):
            raise ValueError(
                "input_observations must contain ScientificMeasurementObservation values"
            )
        _require_optional_instance(
            self.source_series_evidence,
            ExternalLoadVelocitySeriesEvidence,
            "source_series_evidence",
        )
        _require_optional_instance(
            self.derived_observation,
            ScientificMeasurementObservation,
            "derived_observation",
        )
        if self.metric_identity.value_origin is not ValueOrigin.DYNAMISLM_DERIVED:
            raise ValueError("computed external-load results must be DYNAMISLM_DERIVED")
        if self.metric_identity.processing.registered_operation != self.operation:
            raise ValueError("metric identity must retain its registered operation")
        if self.measurement_result.classification.value_origin is not ValueOrigin.DYNAMISLM_DERIVED:
            raise ValueError("computed result classification must be DYNAMISLM_DERIVED")
        if self.measurement_result.unit != self.metric_identity.processing.unit:
            raise ValueError("computed result unit must match its metric identity")
        if self.input_observations:
            expected_observation_ids = tuple(
                observation.observation_id for observation in self.input_observations
            )
            expected_identity_ids = tuple(
                observation.identity.identity_id for observation in self.input_observations
            )
            expected_provenance = tuple(
                observation.provenance for observation in self.input_observations
            )
            if self.source_observation_ids != expected_observation_ids:
                raise ValueError("source observation IDs must be extracted from input observations")
            if self.input_identity_ids != expected_identity_ids:
                raise ValueError("input identity IDs must be extracted from input observations")
            if self.source_provenance != expected_provenance:
                raise ValueError("source provenance must be extracted from input observations")
        if self.source_series_evidence is not None:
            evidence = self.source_series_evidence
            if self.source_series_id != evidence.series_id:
                raise ValueError("source series ID must be extracted from series evidence")
            if self.source_observation_ids != (evidence.bound_observation_id,):
                raise ValueError("source observation ID must identify the series evidence")
            if self.input_identity_ids != (evidence.identity.identity_id,):
                raise ValueError("input identity ID must identify the series evidence")
            if self.source_provenance != (evidence.provenance,):
                raise ValueError("source provenance must be extracted from series evidence")
        if self.derived_observation is not None:
            if self.derived_observation.identity != self.metric_identity:
                raise ValueError("derived observation identity must match metric identity")
            if self.derived_observation.result != self.measurement_result:
                raise ValueError("derived observation result must match measurement result")
            if not any(
                run.output_entity_id == self.derived_observation.observation_id
                for run in self.derived_observation.provenance.processing_runs
            ):
                raise ValueError("derived observation provenance must bind its output ID")
        if (
            self.operation == EXTERNAL_LOAD_RELATIVE_DISTANCE_OPERATION
            and not self.input_observations
        ):
            raise ValueError("relative-distance results require bound input observations")
        if (
            self.operation == EXTERNAL_LOAD_THRESHOLD_SUMMARY_OPERATION
            and self.source_series_evidence is None
        ):
            raise ValueError("threshold results require bound velocity-series evidence")
        expected_value = _authoritative_metric_value(self)
        if not math.isclose(self.value, expected_value, rel_tol=0.0, abs_tol=1e-12):
            raise ValueError("computed metric result value does not match registered execution")

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
    time_result: ExternalLoadMetricResult | None = None
    distance_result: ExternalLoadMetricResult | None = None
    event_count_result: ExternalLoadMetricResult | None = None
    evidence: ExternalLoadVelocitySeriesEvidence | None = None

    @classmethod
    def __decode_legacy_wire__(
        cls,
        value: object,
        kwargs: dict[str, Any],
    ) -> dict[str, Any]:
        """Fill additive typed-output fields for historical V3 receipts."""

        del value
        kwargs.setdefault("time_result", None)
        kwargs.setdefault("distance_result", None)
        kwargs.setdefault("event_count_result", None)
        kwargs.setdefault("evidence", None)
        return kwargs

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
        _require_optional_instance(self.time_result, ExternalLoadMetricResult, "time_result")
        _require_optional_instance(
            self.distance_result,
            ExternalLoadMetricResult,
            "distance_result",
        )
        _require_optional_instance(
            self.event_count_result,
            ExternalLoadMetricResult,
            "event_count_result",
        )
        _require_optional_instance(self.evidence, ExternalLoadVelocitySeriesEvidence, "evidence")
        if self.evidence is not None:
            if self.source_series_id != self.evidence.series_id:
                raise ValueError("threshold summary series ID must come from its evidence")
            if self.source_identity_id != self.evidence.identity.identity_id:
                raise ValueError("threshold summary identity ID must come from its evidence")
            if self.threshold != self.evidence.identity.threshold:
                raise ValueError("threshold summary threshold must come from its evidence")
            if self.event_definition != self.evidence.identity.event_definition:
                raise ValueError("threshold summary event definition must come from its evidence")
            if self.interpolation_method != self.evidence.identity.processing.interpolation_method:
                raise ValueError("threshold summary interpolation must come from its evidence")
        sprint_output = self.evidence is not None and self.evidence.identity.metric_family in {
            ExternalLoadMetricFamily.SPRINT_DISTANCE,
            ExternalLoadMetricFamily.SPRINT_TIME,
            ExternalLoadMetricFamily.SPRINT_EVENT_COUNT,
        }
        expected_time_family = (
            ExternalLoadMetricFamily.SPRINT_TIME
            if sprint_output
            else ExternalLoadMetricFamily.THRESHOLD_TIME
        )
        expected_distance_family = (
            ExternalLoadMetricFamily.SPRINT_DISTANCE
            if sprint_output
            else ExternalLoadMetricFamily.THRESHOLD_DISTANCE
        )
        expected_event_family = (
            ExternalLoadMetricFamily.SPRINT_EVENT_COUNT
            if sprint_output
            else ExternalLoadMetricFamily.THRESHOLD_EVENT_COUNT
        )
        if self.time_result is not None:
            self._validate_typed_output(
                self.time_result,
                expected_time_family,
                EXTERNAL_LOAD_SECOND,
                self.time_above_threshold_s,
            )
        if self.distance_result is not None:
            self._validate_typed_output(
                self.distance_result,
                expected_distance_family,
                EXTERNAL_LOAD_METER,
                self.distance_above_threshold_m,
            )
        if self.event_count_result is not None:
            if self.event_count is None:
                raise ValueError("an event-count result requires an event-count value")
            self._validate_typed_output(
                self.event_count_result,
                expected_event_family,
                EXTERNAL_LOAD_COUNT,
                float(self.event_count),
            )
        if self.evidence is not None and (self.time_result is None or self.distance_result is None):
            raise ValueError("authoritative threshold summaries require typed time and distance")
        if self.evidence is not None and self.event_count is not None:
            if self.event_count_result is None:
                raise ValueError("authoritative event counts require a typed event result")
        if (
            self.evidence is not None
            and self.event_count is None
            and self.event_count_result is not None
        ):
            raise ValueError("an event result cannot be present without an event-count value")

    def _validate_typed_output(
        self,
        result: ExternalLoadMetricResult,
        expected_family: ExternalLoadMetricFamily,
        expected_unit: UnitReference,
        expected_value: float,
    ) -> None:
        if result.operation != EXTERNAL_LOAD_THRESHOLD_SUMMARY_OPERATION:
            raise ValueError("threshold summary outputs must use the registered operation")
        if result.metric_identity.metric_family is not expected_family:
            raise ValueError("threshold summary output metric family is incorrect")
        if result.unit != expected_unit:
            raise ValueError("threshold summary output unit is incorrect")
        if result.metric_identity.threshold != self.threshold:
            raise ValueError("threshold summary output threshold identity is incomplete")
        if self.evidence is not None and result.source_series_evidence != self.evidence:
            raise ValueError("threshold summary output must retain its source evidence binding")
        if not math.isclose(result.value, expected_value, rel_tol=0.0, abs_tol=1e-12):
            raise ValueError("threshold summary typed output disagrees with its receipt value")


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


def _unique_tuple[T](values: tuple[T, ...]) -> tuple[T, ...]:
    unique: list[T] = []
    for value in values:
        if value not in unique:
            unique.append(value)
    return tuple(unique)


def _observation_context_matches(
    left: ObservationContext,
    right: ObservationContext,
) -> bool:
    """Match the context dimensions required for a cross-metric derivation."""

    return (
        left.context_id == right.context_id
        and left.athlete_id == right.athlete_id
        and left.session_id == right.session_id
        and left.test_instance_id == right.test_instance_id
        and left.trial_id == right.trial_id
        and left.population_context == right.population_context
        and left.environment == right.environment
        and left.context_metadata == right.context_metadata
    )


def _observation_provenance_failures(
    observation: ScientificMeasurementObservation,
) -> tuple[RefusalReasonCode, ...] | None:
    """Validate source-to-observation lineage and identity/run consistency."""

    provenance = observation.provenance
    matching_runs = tuple(
        run
        for run in provenance.processing_runs
        if run.output_entity_id == observation.observation_id
    )
    if len(matching_runs) != 1:
        return (RefusalReasonCode.PROCESSING_LINEAGE_UNRESOLVED,)
    run = matching_runs[0]
    artifact_ids = {artifact.artifact_id for artifact in provenance.source_artifacts}
    if not set(run.source_artifact_ids).issubset(artifact_ids):
        return (RefusalReasonCode.SOURCE_ARTIFACT_UNVERIFIED,)
    if not provenance.acquisitions:
        return (RefusalReasonCode.ACQUISITION_ARRANGEMENT_MISMATCH,)
    identity = observation.identity
    if not isinstance(identity, ExternalLoadMeasurementIdentity):
        return (RefusalReasonCode.METRIC_DEFINITION_MISMATCH,)
    if run.method != identity.version.processing_method:
        return (RefusalReasonCode.PROCESSING_LINEAGE_UNRESOLVED,)
    if run.software_version != identity.version.software_version:
        return (RefusalReasonCode.SOFTWARE_PIPELINE_NOT_ESTABLISHED,)
    if run.parameters != identity.processing.method_parameters:
        return (RefusalReasonCode.PROCESSING_LINEAGE_UNRESOLVED,)
    if identity.acquisition.raw_artifact is not None and all(
        identity.acquisition.raw_artifact != artifact.artifact_id
        for artifact in provenance.source_artifacts
    ):
        return (RefusalReasonCode.SOURCE_ARTIFACT_UNVERIFIED,)
    if identity.acquisition.device is not None and all(
        acquisition.device != identity.acquisition.device for acquisition in provenance.acquisitions
    ):
        return (RefusalReasonCode.ACQUISITION_ARRANGEMENT_MISMATCH,)
    if any(
        acquisition.source_artifact_id not in run.source_artifact_ids
        for acquisition in provenance.acquisitions
    ):
        return (RefusalReasonCode.SOURCE_ARTIFACT_UNVERIFIED,)
    if identity.acquisition.sampling is not None and all(
        acquisition.sampling != identity.acquisition.sampling
        for acquisition in provenance.acquisitions
    ):
        return (RefusalReasonCode.SAMPLE_OR_TIMEBASE_MISMATCH,)
    return None


def _numeric_observation_value(
    observation: object,
    *,
    expected_families: frozenset[ExternalLoadMetricFamily],
    expected_measurand: RegistryReference,
    label: str,
) -> tuple[float, ExternalLoadMeasurementIdentity] | tuple[None, RefusalReasonCode]:
    if not isinstance(observation, ScientificMeasurementObservation):
        return None, RefusalReasonCode.MISSING_METADATA
    identity = observation.identity
    if not isinstance(identity, ExternalLoadMeasurementIdentity):
        return None, RefusalReasonCode.METRIC_DEFINITION_MISMATCH
    if identity.metric_family not in expected_families:
        return None, RefusalReasonCode.METRIC_DEFINITION_MISMATCH
    if identity.semantic.measurand != expected_measurand:
        return None, RefusalReasonCode.MEASURAND_MISMATCH
    if observation.result.result_id.instance_type != "result":
        return None, RefusalReasonCode.MISSING_METADATA
    if observation.result.unit != identity.processing.unit:
        return None, RefusalReasonCode.UNIT_OR_NORMALIZATION_MISMATCH
    if observation.result.classification.value_origin is not identity.value_origin:
        return None, RefusalReasonCode.MISSING_METADATA
    if observation.result.status is not ResultStatus.VALID:
        return None, RefusalReasonCode.MISSING_METADATA
    scalar = observation.result.value
    if not isinstance(scalar, ScalarValue) or isinstance(scalar.value, bool):
        return None, RefusalReasonCode.MISSING_METADATA
    try:
        value = _finite_number(scalar.value, label)
    except ExternalLoadComputationError as exc:
        return None, exc.reason_code
    provenance_failure = _observation_provenance_failures(observation)
    if provenance_failure is not None:
        return None, provenance_failure[0]
    return value, identity


def _derived_provenance(
    *,
    output_observation_id: InstanceIdentifier,
    input_observations: tuple[ScientificMeasurementObservation, ...],
    operation: RegistryReference,
    parameters: tuple[MetadataEntry, ...],
    software_version: str,
) -> Provenance:
    source_artifacts = _unique_tuple(
        tuple(
            artifact
            for observation in input_observations
            for artifact in observation.provenance.source_artifacts
        )
    )
    acquisitions = _unique_tuple(
        tuple(
            acquisition
            for observation in input_observations
            for acquisition in observation.provenance.acquisitions
        )
    )
    source_runs = _unique_tuple(
        tuple(
            run
            for observation in input_observations
            for run in observation.provenance.processing_runs
        )
    )
    source_edges = _unique_tuple(
        tuple(
            edge
            for observation in input_observations
            for edge in observation.provenance.lineage_edges
        )
    )
    source_artifact_ids = tuple(artifact.artifact_id for artifact in source_artifacts)
    derived_run = ProcessingRun(
        processing_run_id=InstanceIdentifier(
            "processing-run", f"{operation.identifier.key}:{output_observation_id.value}"
        ),
        source_artifact_ids=source_artifact_ids,
        method=operation,
        parameters=parameters,
        software_version=software_version,
        output_entity_id=output_observation_id,
    )
    derived_edges = (
        *tuple(
            LineageEdge(
                observation.observation_id.qualified,
                derived_run.processing_run_id.qualified,
                LineageRelation.DERIVED_FROM,
            )
            for observation in input_observations
        ),
        LineageEdge(
            derived_run.processing_run_id.qualified,
            output_observation_id.qualified,
            LineageRelation.PRODUCED,
        ),
    )
    evidence_references = _unique_tuple(
        tuple(
            evidence
            for observation in input_observations
            for evidence in observation.provenance.evidence_references
        )
    )
    metrological_traceability = _unique_tuple(
        tuple(
            reference
            for observation in input_observations
            for reference in observation.provenance.metrological_traceability
        )
    )
    return Provenance(
        provenance_id=InstanceIdentifier("provenance", output_observation_id.value),
        source_artifacts=source_artifacts,
        acquisitions=acquisitions,
        processing_runs=(*source_runs, derived_run),
        lineage_edges=_unique_tuple(source_edges + derived_edges),
        evidence_references=evidence_references,
        metrological_traceability=metrological_traceability,
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
    input_identity_ids: tuple[ScientificIdentifier, ...] = (),
) -> ExternalLoadMeasurementIdentity:
    digest = canonical_hash(
        {
            "source_identity": source_identity,
            "metric_family": metric_family,
            "metric_reference": metric_reference,
            "unit": unit,
            "normalization": normalization,
            "operation": operation,
            "input_identity_ids": input_identity_ids,
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
            *tuple(
                MetadataEntry("input_identity_id", identity_id.stable_id)
                for identity_id in input_identity_ids
                if identity_id != source_identity.identity_id
            ),
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
    input_observations: tuple[ScientificMeasurementObservation, ...] = (),
    source_series_evidence: ExternalLoadVelocitySeriesEvidence | None = None,
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
            "input_observations": input_observations,
            "source_series_evidence": source_series_evidence,
        }
    ).removeprefix("sha256:")[:24]
    measurement_result = MeasurementResult(
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
    )
    derived_observation: ScientificMeasurementObservation | None = None
    if input_observations:
        output_observation_id = InstanceIdentifier("observation", f"derived:{result_digest}")
        output_provenance = _derived_provenance(
            output_observation_id=output_observation_id,
            input_observations=input_observations,
            operation=operation,
            parameters=(
                MetadataEntry(
                    "input_observation_ids",
                    ",".join(
                        observation.observation_id.qualified for observation in input_observations
                    ),
                ),
                MetadataEntry(
                    "input_identity_ids",
                    ",".join(
                        observation.identity.identity_id.stable_id
                        for observation in input_observations
                    ),
                ),
            ),
            software_version=f"dynamislm-res64-{operation.identifier.key}-1.0.0",
        )
        derived_observation = ScientificMeasurementObservation(
            observation_id=output_observation_id,
            context=input_observations[0].context,
            identity=identity,
            result=measurement_result,
            provenance=output_provenance,
        )
    return ExternalLoadMetricResult(
        operation=operation,
        metric_identity=identity,
        measurement_result=measurement_result,
        input_identity_ids=input_identity_ids,
        source_observation_ids=source_observation_ids,
        source_series_id=source_series_id,
        source_provenance=source_provenance,
        input_observations=input_observations,
        source_series_evidence=source_series_evidence,
        derived_observation=derived_observation,
    )


_UNSET = object()


def derive_duration_normalized_distance(
    source_observation: ScientificMeasurementObservation | object | None = None,
    duration_observation: ScientificMeasurementObservation | object | None = None,
    *,
    # These legacy names remain accepted only to return a structured refusal;
    # no scalar, unit, identity, ID, or provenance override is ever consumed.
    total_distance: object = _UNSET,
    valid_duration: object = _UNSET,
    distance_unit: UnitReference | None = None,
    duration_unit: UnitReference | None = None,
    source_identity: ExternalLoadMeasurementIdentity | None = None,
    duration_identity: ExternalLoadMeasurementIdentity | None = None,
    source_observation_ids: tuple[InstanceIdentifier, ...] = (),
    source_provenance: tuple[Provenance, ...] = (),
) -> ExternalLoadMetricResult | RefusalResult:
    """Derive relative distance from two evidence-bound observations.

    ``duration_normalized_distance`` remains the pure numerical helper.  This
    authority entry point never consumes its historical scalar-style arguments.
    """

    if not isinstance(source_observation, ScientificMeasurementObservation) or not isinstance(
        duration_observation,
        ScientificMeasurementObservation,
    ):
        return _refusal(
            blocked_claim="derive duration-normalized relative distance",
            reason_codes=(RefusalReasonCode.MISSING_METADATA,),
            missing_information=(
                "a total-distance ScientificMeasurementObservation",
                "a duration ScientificMeasurementObservation",
                "raw scalar/unit/identity/provenance arguments cannot authorize derivation",
            ),
        )
    if any(value is not _UNSET for value in (total_distance, valid_duration)) or any(
        value is not None
        for value in (distance_unit, duration_unit, source_identity, duration_identity)
    ):
        return _refusal(
            blocked_claim="derive duration-normalized relative distance",
            reason_codes=(RefusalReasonCode.MISSING_METADATA,),
            missing_information=(
                "the operation accepts values and units only from the supplied observations",
                "caller scalar/identity/unit overrides are not authoritative",
            ),
            observation_ids=(
                source_observation.observation_id,
                duration_observation.observation_id,
            ),
        )

    source_value, source_identity_value = _numeric_observation_value(
        source_observation,
        expected_families=frozenset({ExternalLoadMetricFamily.TOTAL_DISTANCE}),
        expected_measurand=EXTERNAL_LOAD_DISTANCE_MEASURAND,
        label="total distance observation value",
    )
    duration_value, duration_identity_value = _numeric_observation_value(
        duration_observation,
        expected_families=frozenset(
            {
                ExternalLoadMetricFamily.SESSION_DURATION,
                ExternalLoadMetricFamily.MINUTES_EXPOSURE,
            }
        ),
        expected_measurand=EXTERNAL_LOAD_DURATION_MEASURAND,
        label="duration observation value",
    )
    failures: list[RefusalReasonCode] = []
    if source_value is None:
        assert isinstance(source_identity_value, RefusalReasonCode)
        failures.append(source_identity_value)
    if duration_value is None:
        assert isinstance(duration_identity_value, RefusalReasonCode)
        failures.append(duration_identity_value)
    if failures:
        return _refusal(
            blocked_claim="derive duration-normalized relative distance",
            reason_codes=tuple(failures),
            missing_information=(
                "validated source observation identity/result/unit/provenance binding",
            ),
            observation_ids=(
                source_observation.observation_id,
                duration_observation.observation_id,
            ),
        )
    assert isinstance(source_value, float)
    assert isinstance(duration_value, float)
    assert isinstance(source_identity_value, ExternalLoadMeasurementIdentity)
    assert isinstance(duration_identity_value, ExternalLoadMeasurementIdentity)
    if not _observation_context_matches(source_observation.context, duration_observation.context):
        return _refusal(
            blocked_claim="derive duration-normalized relative distance",
            reason_codes=(RefusalReasonCode.ACQUISITION_ARRANGEMENT_MISMATCH,),
            missing_information=("matching athlete/session/test/context identity",),
            observation_ids=(
                source_observation.observation_id,
                duration_observation.observation_id,
            ),
        )
    if source_identity_value.aggregation != duration_identity_value.aggregation:
        return _refusal(
            blocked_claim="derive duration-normalized relative distance",
            reason_codes=(RefusalReasonCode.SOURCE_PROCESSING_MISMATCH,),
            missing_information=("matching source distance and duration aggregation identity",),
            observation_ids=(
                source_observation.observation_id,
                duration_observation.observation_id,
            ),
        )
    if source_observation_ids and source_observation_ids != (
        source_observation.observation_id,
        duration_observation.observation_id,
    ):
        return _refusal(
            blocked_claim="derive duration-normalized relative distance",
            reason_codes=(RefusalReasonCode.MISSING_METADATA,),
            missing_information=("source observation IDs extracted from observations",),
            observation_ids=(
                source_observation.observation_id,
                duration_observation.observation_id,
            ),
        )
    if source_provenance and source_provenance != (
        source_observation.provenance,
        duration_observation.provenance,
    ):
        return _refusal(
            blocked_claim="derive duration-normalized relative distance",
            reason_codes=(RefusalReasonCode.PROCESSING_LINEAGE_UNRESOLVED,),
            missing_information=("source provenance extracted from observations",),
            observation_ids=(
                source_observation.observation_id,
                duration_observation.observation_id,
            ),
        )
    source_unit = source_observation.result.unit
    duration_unit_from_observation = duration_observation.result.unit
    if source_unit is None or duration_unit_from_observation is None:
        return _refusal(
            blocked_claim="derive duration-normalized relative distance",
            reason_codes=(RefusalReasonCode.MISSING_METADATA,),
            missing_information=("source observation result units",),
            observation_ids=(
                source_observation.observation_id,
                duration_observation.observation_id,
            ),
        )
    try:
        value = duration_normalized_distance(
            source_value,
            duration_value,
            distance_unit=source_unit,
            duration_unit=duration_unit_from_observation,
        )
    except ExternalLoadComputationError as exc:
        return _refusal(
            blocked_claim="derive duration-normalized relative distance",
            reason_codes=(exc.reason_code,),
            missing_information=(str(exc),),
            observation_ids=(
                source_observation.observation_id,
                duration_observation.observation_id,
            ),
        )
    input_identity_ids = (
        source_identity_value.identity_id,
        duration_identity_value.identity_id,
    )
    identity = _derived_identity(
        source_identity_value,
        metric_family=ExternalLoadMetricFamily.RELATIVE_DISTANCE,
        metric_reference=EXTERNAL_LOAD_RELATIVE_DISTANCE_METRIC,
        unit=EXTERNAL_LOAD_METERS_PER_MINUTE,
        normalization=ExternalLoadNormalizationIdentity(
            kind=NormalizationKind.DURATION_NORMALIZED,
            method=EXTERNAL_LOAD_RELATIVE_DISTANCE_OPERATION,
            parameters=(
                MetadataEntry(
                    "denominator_identity_id",
                    duration_identity_value.identity_id.stable_id,
                ),
                MetadataEntry(
                    "denominator_metric_family",
                    duration_identity_value.metric_family.value,
                ),
            ),
        ),
        operation=EXTERNAL_LOAD_RELATIVE_DISTANCE_OPERATION,
        input_identity_ids=input_identity_ids,
    )
    return _metric_result(
        operation=EXTERNAL_LOAD_RELATIVE_DISTANCE_OPERATION,
        identity=identity,
        value=value,
        unit=EXTERNAL_LOAD_METERS_PER_MINUTE,
        input_identity_ids=input_identity_ids,
        source_observation_ids=(
            source_observation.observation_id,
            duration_observation.observation_id,
        ),
        source_provenance=(source_observation.provenance, duration_observation.provenance),
        input_observations=(source_observation, duration_observation),
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


def _velocity_evidence_refusal(
    evidence: ExternalLoadVelocitySeriesEvidence,
    *,
    reasons: tuple[RefusalReasonCode, ...],
    missing: tuple[str, ...],
) -> RefusalResult:
    return _refusal(
        blocked_claim="compute external-load velocity threshold summary",
        reason_codes=reasons,
        missing_information=missing,
        observation_ids=(evidence.bound_observation_id,),
    )


def _metadata_value(
    entries: tuple[MetadataEntry, ...],
    key: str,
) -> object | None:
    values = tuple(entry.value for entry in entries if entry.key == key)
    return values[0] if len(values) == 1 else None


def _validate_velocity_evidence(
    evidence: ExternalLoadVelocitySeriesEvidence,
    identity: ExternalLoadMeasurementIdentity,
) -> RefusalResult | None:
    """Require every series/evidence/identity/provenance binding before execution."""

    if evidence.identity != identity:
        reasons: list[RefusalReasonCode] = [RefusalReasonCode.SOURCE_PROCESSING_MISMATCH]
        missing = ["the measurement identity mechanically bound to the velocity evidence"]
        if evidence.identity.system.provider != identity.system.provider:
            reasons.append(RefusalReasonCode.SOURCE_IDENTITY_INADEQUATE)
        if evidence.identity.system.device_or_system != identity.system.device_or_system:
            reasons.append(RefusalReasonCode.ACQUISITION_ARRANGEMENT_MISMATCH)
        if evidence.identity.system.sampling != identity.system.sampling:
            reasons.append(RefusalReasonCode.SAMPLE_OR_TIMEBASE_MISMATCH)
        if evidence.identity.aggregation != identity.aggregation:
            reasons.append(RefusalReasonCode.SESSION_SOURCE_MISMATCH)
        if evidence.identity.processing != identity.processing:
            reasons.append(RefusalReasonCode.SOURCE_PROCESSING_MISMATCH)
        return _velocity_evidence_refusal(
            evidence,
            reasons=tuple(dict.fromkeys(reasons)),
            missing=tuple(missing),
        )

    supported_metric_families = {
        ExternalLoadMetricFamily.THRESHOLD_DISTANCE,
        ExternalLoadMetricFamily.THRESHOLD_TIME,
        ExternalLoadMetricFamily.THRESHOLD_EVENT_COUNT,
        ExternalLoadMetricFamily.SPRINT_DISTANCE,
        ExternalLoadMetricFamily.SPRINT_TIME,
        ExternalLoadMetricFamily.SPRINT_EVENT_COUNT,
    }
    if identity.metric_family not in supported_metric_families:
        return _velocity_evidence_refusal(
            evidence,
            reasons=(RefusalReasonCode.EXTERNAL_LOAD_METRIC_NOT_REGISTERED,),
            missing=("a registered velocity threshold operation for this metric family",),
        )
    if identity.definition_status is not ExternalLoadDefinitionStatus.RESOLVED:
        return _velocity_evidence_refusal(
            evidence,
            reasons=(RefusalReasonCode.UNKNOWN_METRIC_DEFINITION,),
            missing=("complete registered external-load metric definition",),
        )
    expected_output = {
        ExternalLoadMetricFamily.THRESHOLD_DISTANCE: (
            EXTERNAL_LOAD_THRESHOLD_DISTANCE_METRIC,
            EXTERNAL_LOAD_METER,
        ),
        ExternalLoadMetricFamily.THRESHOLD_TIME: (
            EXTERNAL_LOAD_THRESHOLD_TIME_METRIC,
            EXTERNAL_LOAD_SECOND,
        ),
        ExternalLoadMetricFamily.THRESHOLD_EVENT_COUNT: (
            EXTERNAL_LOAD_THRESHOLD_EVENT_COUNT_METRIC,
            EXTERNAL_LOAD_COUNT,
        ),
        ExternalLoadMetricFamily.SPRINT_DISTANCE: (
            EXTERNAL_LOAD_SPRINT_DISTANCE_METRIC,
            EXTERNAL_LOAD_METER,
        ),
        ExternalLoadMetricFamily.SPRINT_TIME: (
            EXTERNAL_LOAD_SPRINT_TIME_METRIC,
            EXTERNAL_LOAD_SECOND,
        ),
        ExternalLoadMetricFamily.SPRINT_EVENT_COUNT: (
            EXTERNAL_LOAD_SPRINT_EVENT_COUNT_METRIC,
            EXTERNAL_LOAD_COUNT,
        ),
    }
    expected_metric, expected_unit = expected_output[identity.metric_family]
    if identity.semantic.metric_definition != expected_metric:
        return _velocity_evidence_refusal(
            evidence,
            reasons=(RefusalReasonCode.METRIC_DEFINITION_MISMATCH,),
            missing=("the registered metric definition executed by the threshold operation",),
        )
    if identity.processing.unit != expected_unit:
        return _velocity_evidence_refusal(
            evidence,
            reasons=(RefusalReasonCode.UNIT_OR_NORMALIZATION_MISMATCH,),
            missing=("the metric-family output unit",),
        )
    if identity.processing.registered_operation is not None:
        return _velocity_evidence_refusal(
            evidence,
            reasons=(RefusalReasonCode.EVENT_METHOD_MISMATCH,),
            missing=("an input identity without a pre-existing derived operation",),
        )
    if identity.system.device_or_system is None or identity.acquisition.device is None:
        return _velocity_evidence_refusal(
            evidence,
            reasons=(RefusalReasonCode.DEVICE_IDENTITY_MISSING,),
            missing=("evidence-bound device/measuring-system identity",),
        )
    if identity.system.device_or_system != identity.acquisition.device:
        return _velocity_evidence_refusal(
            evidence,
            reasons=(RefusalReasonCode.ACQUISITION_ARRANGEMENT_MISMATCH,),
            missing=("matching generic and external device identities",),
        )
    if identity.system.sampling is None or identity.acquisition.sampling is None:
        return _velocity_evidence_refusal(
            evidence,
            reasons=(RefusalReasonCode.SAMPLING_METADATA_MISSING,),
            missing=("evidence-bound sampling characteristics",),
        )
    if identity.system.sampling != identity.acquisition.sampling:
        return _velocity_evidence_refusal(
            evidence,
            reasons=(RefusalReasonCode.SAMPLE_OR_TIMEBASE_MISMATCH,),
            missing=("matching generic and external sampling identities",),
        )
    if not evidence.provenance.source_artifacts:
        return _velocity_evidence_refusal(
            evidence,
            reasons=(RefusalReasonCode.SOURCE_ARTIFACT_UNVERIFIED,),
            missing=("source artifact bound to the velocity evidence",),
        )
    if identity.acquisition.raw_artifact is None:
        return _velocity_evidence_refusal(
            evidence,
            reasons=(RefusalReasonCode.SOURCE_ARTIFACT_UNVERIFIED,),
            missing=("the exact raw/series source artifact identity",),
        )
    if identity.acquisition.raw_artifact not in {
        artifact.artifact_id for artifact in evidence.provenance.source_artifacts
    }:
        return _velocity_evidence_refusal(
            evidence,
            reasons=(RefusalReasonCode.SOURCE_ARTIFACT_UNVERIFIED,),
            missing=("identity raw artifact bound to provenance source artifacts",),
        )
    if any(not artifact.immutable for artifact in evidence.provenance.source_artifacts):
        return _velocity_evidence_refusal(
            evidence,
            reasons=(RefusalReasonCode.SOURCE_ARTIFACT_UNVERIFIED,),
            missing=("immutable source artifact evidence",),
        )

    provenance_failure = _observation_provenance_failures(
        ScientificMeasurementObservation(
            observation_id=evidence.bound_observation_id,
            context=evidence.context,
            identity=identity,
            result=MeasurementResult(
                result_id=InstanceIdentifier("result", evidence.series_id.value),
                value=StructuredOutputReference(
                    artifact_id=evidence.provenance.source_artifacts[0].artifact_id,
                    schema=EXTERNAL_LOAD_RAW_VELOCITY_SERIES_SCHEMA,
                ),
                unit=None,
                classification=ScientificClassification(
                    identity.value_origin,
                    (ScientificRole.PERFORMANCE_OUTCOME,),
                ),
                status=ResultStatus.VALID,
            ),
            provenance=evidence.provenance,
        )
    )
    if provenance_failure is not None:
        return _velocity_evidence_refusal(
            evidence,
            reasons=provenance_failure,
            missing=("provenance bound to the evidence observation and identity",),
        )
    matching_runs = tuple(
        run
        for run in evidence.provenance.processing_runs
        if run.output_entity_id == evidence.bound_observation_id
    )
    if len(matching_runs) != 1:
        return _velocity_evidence_refusal(
            evidence,
            reasons=(RefusalReasonCode.PROCESSING_LINEAGE_UNRESOLVED,),
            missing=("exactly one processing run producing the evidence observation",),
        )
    if any(
        acquisition.device != identity.system.device_or_system
        or acquisition.sampling != identity.system.sampling
        or acquisition.source_artifact_id != identity.acquisition.raw_artifact
        or acquisition.sensor_channel != identity.acquisition.sensor_channel
        or acquisition.calibration_reference != identity.acquisition.calibration_reference
        or acquisition.hardware_firmware != identity.acquisition.hardware_firmware
        for acquisition in evidence.provenance.acquisitions
    ):
        return _velocity_evidence_refusal(
            evidence,
            reasons=(RefusalReasonCode.ACQUISITION_ARRANGEMENT_MISMATCH,),
            missing=("provenance acquisition device and sampling bound to identity",),
        )
    run = matching_runs[0]
    binding_values = {
        "series_id": evidence.series_id.qualified,
        "series_digest": canonical_hash(evidence.series),
        "observation_id": evidence.bound_observation_id.qualified,
        "context_id": evidence.context.context_id.qualified,
        "athlete_id": evidence.context.athlete_id.qualified,
        "session_id": evidence.context.session_id.qualified,
        "test_instance_id": evidence.context.test_instance_id.qualified,
        "source_artifact_id": identity.acquisition.raw_artifact.qualified,
        "device_identity": identity.system.device_or_system.stable_id,
        "system_provider": identity.system.provider,
        "sampling_frequency_hz": identity.system.sampling.frequency_hz,
        "sampling_channels": ",".join(identity.system.sampling.channels),
    }
    for key, expected in binding_values.items():
        if _metadata_value(run.parameters, key) != expected:
            return _velocity_evidence_refusal(
                evidence,
                reasons=(RefusalReasonCode.PROCESSING_LINEAGE_UNRESOLVED,),
                missing=(f"processing provenance binding for {key}",),
            )
    for sample in evidence.series.samples:
        try:
            convert_external_load_value(
                sample.velocity,
                sample.unit,
                EXTERNAL_LOAD_METERS_PER_SECOND,
            )
        except ExternalLoadComputationError as exc:
            return _velocity_evidence_refusal(
                evidence,
                reasons=(exc.reason_code,),
                missing=("registered velocity sample units",),
            )
    return None


def _validate_threshold_event_v1(
    identity: ExternalLoadMeasurementIdentity,
    evidence: ExternalLoadVelocitySeriesEvidence,
) -> RefusalResult | None:
    event = identity.event_definition
    if not identity.is_event_metric:
        if event is not None:
            return _velocity_evidence_refusal(
                evidence,
                reasons=(RefusalReasonCode.EVENT_DEFINITION_MISMATCH,),
                missing=("no event definition for a non-event threshold output",),
            )
        return None
    if event is None:
        return _velocity_evidence_refusal(
            evidence,
            reasons=(RefusalReasonCode.UNKNOWN_EVENT_DEFINITION,),
            missing=("registered event definition",),
        )
    if event.definition != EXTERNAL_LOAD_THRESHOLD_EVENT_DEFINITION:
        return _velocity_evidence_refusal(
            evidence,
            reasons=(RefusalReasonCode.EVENT_DEFINITION_MISMATCH,),
            missing=("the registered V1 threshold event definition",),
        )
    if event.start_rule != EXTERNAL_LOAD_THRESHOLD_EVENT_START_RULE:
        return _velocity_evidence_refusal(
            evidence,
            reasons=(RefusalReasonCode.EVENT_METHOD_MISMATCH,),
            missing=("the registered V1 threshold-entry rule",),
        )
    if event.end_rule != EXTERNAL_LOAD_THRESHOLD_EVENT_END_RULE:
        return _velocity_evidence_refusal(
            evidence,
            reasons=(RefusalReasonCode.EVENT_METHOD_MISMATCH,),
            missing=("the registered V1 threshold-exit rule",),
        )
    if event.hysteresis_status is EventHysteresisStatus.DEFINED:
        return _velocity_evidence_refusal(
            evidence,
            reasons=(RefusalReasonCode.EXTERNAL_LOAD_METRIC_NOT_REGISTERED,),
            missing=("registered hysteresis-aware threshold event operation",),
        )
    if event.hysteresis_status is not EventHysteresisStatus.NONE or event.hysteresis is not None:
        return _velocity_evidence_refusal(
            evidence,
            reasons=(RefusalReasonCode.UNKNOWN_EVENT_DEFINITION,),
            missing=("explicit no-hysteresis V1 event semantics",),
        )
    if event.minimum_duration_s is None:
        return _velocity_evidence_refusal(
            evidence,
            reasons=(RefusalReasonCode.UNKNOWN_DWELL_RULE,),
            missing=("minimum event duration/dwell",),
        )
    if event.gap_allowance_s is None:
        return _velocity_evidence_refusal(
            evidence,
            reasons=(RefusalReasonCode.UNKNOWN_DWELL_RULE,),
            missing=("event gap allowance",),
        )
    if event.acceleration_threshold is not None or event.deceleration_threshold is not None:
        return _velocity_evidence_refusal(
            evidence,
            reasons=(RefusalReasonCode.EVENT_DEFINITION_MISMATCH,),
            missing=("V1 threshold event without acceleration/deceleration sub-definitions",),
        )
    return None


def _threshold_output_identity(
    source_identity: ExternalLoadMeasurementIdentity,
    *,
    metric_family: ExternalLoadMetricFamily,
    metric_reference: RegistryReference,
    measurand: RegistryReference,
    unit: UnitReference,
) -> ExternalLoadMeasurementIdentity:
    digest = canonical_hash(
        {
            "source_identity": source_identity,
            "output_metric_family": metric_family,
            "output_metric_reference": metric_reference,
            "output_measurand": measurand,
            "output_unit": unit,
            "operation": EXTERNAL_LOAD_THRESHOLD_SUMMARY_OPERATION,
        }
    ).removeprefix("sha256:")[:24]
    processing = replace(
        source_identity.processing,
        registered_operation=EXTERNAL_LOAD_THRESHOLD_SUMMARY_OPERATION,
        method_parameters=(
            *source_identity.processing.method_parameters,
            MetadataEntry("output_metric_family", metric_family.value),
            MetadataEntry("operation_id", EXTERNAL_LOAD_THRESHOLD_SUMMARY_OPERATION.stable_id),
        ),
        unit=unit,
    )
    return replace(
        source_identity,
        identity_id=ScientificIdentifier(
            "dynamislm",
            "measurement-identity",
            f"external-load-{metric_family.value.lower()}-{digest}",
            EXTERNAL_LOAD_THRESHOLD_SUMMARY_OPERATION.identifier.version,
        ),
        semantic=replace(
            source_identity.semantic,
            measurand=measurand,
            metric_definition=metric_reference,
        ),
        processing=processing,
        version=replace(
            source_identity.version,
            processing_method=EXTERNAL_LOAD_THRESHOLD_SUMMARY_OPERATION,
            method_registry_version=EXTERNAL_LOAD_THRESHOLD_SUMMARY_OPERATION.identifier.version,
            software_version="dynamislm-res64-velocity-threshold-summary-1.0.0",
        ),
        value_origin=ValueOrigin.DYNAMISLM_DERIVED,
        event_definition=(
            source_identity.event_definition
            if metric_family
            in {
                ExternalLoadMetricFamily.THRESHOLD_EVENT_COUNT,
                ExternalLoadMetricFamily.SPRINT_EVENT_COUNT,
            }
            else None
        ),
        metric_family=metric_family,
        definition_status=ExternalLoadDefinitionStatus.RESOLVED,
        dynamislm_recomputable=True,
    )


def _threshold_output_spec(
    metric_family: ExternalLoadMetricFamily,
) -> tuple[RegistryReference, RegistryReference, UnitReference]:
    if metric_family in {
        ExternalLoadMetricFamily.THRESHOLD_TIME,
        ExternalLoadMetricFamily.SPRINT_TIME,
    }:
        return (
            EXTERNAL_LOAD_SPRINT_TIME_METRIC
            if metric_family is ExternalLoadMetricFamily.SPRINT_TIME
            else EXTERNAL_LOAD_THRESHOLD_TIME_METRIC,
            EXTERNAL_LOAD_DURATION_MEASURAND,
            EXTERNAL_LOAD_SECOND,
        )
    if metric_family in {
        ExternalLoadMetricFamily.THRESHOLD_DISTANCE,
        ExternalLoadMetricFamily.SPRINT_DISTANCE,
    }:
        return (
            EXTERNAL_LOAD_SPRINT_DISTANCE_METRIC
            if metric_family is ExternalLoadMetricFamily.SPRINT_DISTANCE
            else EXTERNAL_LOAD_THRESHOLD_DISTANCE_METRIC,
            EXTERNAL_LOAD_DISTANCE_MEASURAND,
            EXTERNAL_LOAD_METER,
        )
    if metric_family in {
        ExternalLoadMetricFamily.THRESHOLD_EVENT_COUNT,
        ExternalLoadMetricFamily.SPRINT_EVENT_COUNT,
    }:
        return (
            EXTERNAL_LOAD_SPRINT_EVENT_COUNT_METRIC
            if metric_family is ExternalLoadMetricFamily.SPRINT_EVENT_COUNT
            else EXTERNAL_LOAD_THRESHOLD_EVENT_COUNT_METRIC,
            EXTERNAL_LOAD_EVENT_COUNT_MEASURAND,
            EXTERNAL_LOAD_COUNT,
        )
    raise ValueError("metric family is not a registered threshold output")


def _authoritative_metric_value(result: ExternalLoadMetricResult) -> float:
    if result.operation == EXTERNAL_LOAD_RELATIVE_DISTANCE_OPERATION:
        if len(result.input_observations) != 2:
            raise ValueError("relative-distance results require two input observations")
        source_observation, duration_observation = result.input_observations
        source_value, source_identity = _numeric_observation_value(
            source_observation,
            expected_families=frozenset({ExternalLoadMetricFamily.TOTAL_DISTANCE}),
            expected_measurand=EXTERNAL_LOAD_DISTANCE_MEASURAND,
            label="total distance observation value",
        )
        duration_value, duration_identity = _numeric_observation_value(
            duration_observation,
            expected_families=frozenset(
                {
                    ExternalLoadMetricFamily.SESSION_DURATION,
                    ExternalLoadMetricFamily.MINUTES_EXPOSURE,
                }
            ),
            expected_measurand=EXTERNAL_LOAD_DURATION_MEASURAND,
            label="duration observation value",
        )
        if source_value is None or duration_value is None:
            raise ValueError("relative-distance input observations are not authoritative")
        if not isinstance(source_identity, ExternalLoadMeasurementIdentity) or not isinstance(
            duration_identity,
            ExternalLoadMeasurementIdentity,
        ):
            raise ValueError("relative-distance input identities are not authoritative")
        if not _observation_context_matches(
            source_observation.context,
            duration_observation.context,
        ):
            raise ValueError("relative-distance input contexts do not match")
        if source_identity.aggregation != duration_identity.aggregation:
            raise ValueError("relative-distance input aggregations do not match")
        source_unit = source_observation.result.unit
        duration_unit = duration_observation.result.unit
        if source_unit is None or duration_unit is None:
            raise ValueError("relative-distance input units are missing")
        expected_identity = _derived_identity(
            source_identity,
            metric_family=ExternalLoadMetricFamily.RELATIVE_DISTANCE,
            metric_reference=EXTERNAL_LOAD_RELATIVE_DISTANCE_METRIC,
            unit=EXTERNAL_LOAD_METERS_PER_MINUTE,
            normalization=ExternalLoadNormalizationIdentity(
                kind=NormalizationKind.DURATION_NORMALIZED,
                method=EXTERNAL_LOAD_RELATIVE_DISTANCE_OPERATION,
                parameters=(
                    MetadataEntry(
                        "denominator_identity_id",
                        duration_identity.identity_id.stable_id,
                    ),
                    MetadataEntry(
                        "denominator_metric_family",
                        duration_identity.metric_family.value,
                    ),
                ),
            ),
            operation=EXTERNAL_LOAD_RELATIVE_DISTANCE_OPERATION,
            input_identity_ids=(
                source_identity.identity_id,
                duration_identity.identity_id,
            ),
        )
        if result.metric_identity != expected_identity:
            raise ValueError("relative-distance result identity is not execution-bound")
        return duration_normalized_distance(
            source_value,
            duration_value,
            distance_unit=source_unit,
            duration_unit=duration_unit,
        )

    if result.operation != EXTERNAL_LOAD_THRESHOLD_SUMMARY_OPERATION:
        raise ValueError("unsupported external-load result operation")
    evidence = result.source_series_evidence
    if evidence is None:
        raise ValueError("threshold result evidence is missing")
    evidence_refusal = _validate_velocity_evidence(evidence, evidence.identity)
    if evidence_refusal is not None:
        raise ValueError(
            "threshold result evidence is not authoritative: "
            + ",".join(evidence_refusal.reason_codes)
        )
    event_refusal = _validate_threshold_event_v1(evidence.identity, evidence)
    if event_refusal is not None:
        raise ValueError(
            "threshold result event semantics are not authoritative: "
            + ",".join(event_refusal.reason_codes)
        )
    target_identity = evidence.identity
    threshold = target_identity.threshold
    if not threshold.is_resolved:
        raise ValueError("threshold result threshold is unresolved")
    if threshold.threshold_quantity != EXTERNAL_LOAD_SPEED_MEASURAND:
        raise ValueError("threshold result quantity is not the registered speed measurand")
    if threshold.threshold_value is None or threshold.threshold_unit is None:
        raise ValueError("threshold result threshold parameters are incomplete")
    if target_identity.processing.filtering_status is ProcessingComponentStatus.UNKNOWN:
        raise ValueError("threshold result filtering status is unknown")
    if target_identity.processing.interpolation_method != EXTERNAL_LOAD_LINEAR_INTERPOLATION:
        raise ValueError("threshold result interpolation is not registered")
    if target_identity.processing.smoothing.status is ProcessingComponentStatus.UNKNOWN:
        raise ValueError("threshold result smoothing status is unknown")
    if target_identity.processing.resampling.status is ProcessingComponentStatus.UNKNOWN:
        raise ValueError("threshold result resampling status is unknown")
    if not target_identity.aggregation.is_resolved:
        raise ValueError("threshold result aggregation is unresolved")
    if target_identity.aggregation.scope is AggregationScope.PERIOD_OR_SEGMENT:
        window = target_identity.aggregation.window
        if window.start_s is None or window.end_s is None:
            raise ValueError("threshold result aggregation window is incomplete")
        if (
            evidence.series.samples[0].time_s < window.start_s
            or evidence.series.samples[-1].time_s > window.end_s
        ):
            raise ValueError("threshold result samples exceed the aggregation window")
    if evidence.series.maximum_gap_s is None:
        raise ValueError("threshold result maximum gap is missing")
    for left, right in pairwise(evidence.series.samples):
        if right.time_s - left.time_s > evidence.series.maximum_gap_s:
            raise ValueError("threshold result contains an unaccepted sample gap")
    threshold_mps = convert_external_load_value(
        threshold.threshold_value,
        threshold.threshold_unit,
        EXTERNAL_LOAD_METERS_PER_SECOND,
    )
    time_s, distance_m = _integrate_qualified_distance(
        evidence.series,
        threshold_mps,
        threshold.boundary,
    )
    event_count: int | None = None
    if target_identity.is_event_metric:
        event = target_identity.event_definition
        if event is None or event.minimum_duration_s is None or event.gap_allowance_s is None:
            raise ValueError("threshold event result parameters are incomplete")
        merged = _merge_intervals(
            _qualified_intervals(evidence.series, threshold_mps, threshold.boundary),
            event.gap_allowance_s,
        )
        event_count = int(sum(end - start >= event.minimum_duration_s for start, end in merged))
    output_family = result.metric_identity.metric_family
    if (
        output_family
        in {
            ExternalLoadMetricFamily.THRESHOLD_EVENT_COUNT,
            ExternalLoadMetricFamily.SPRINT_EVENT_COUNT,
        }
        and event_count is None
    ):
        raise ValueError("event output is not applicable to a non-event threshold input")
    metric_reference, measurand, unit = _threshold_output_spec(output_family)
    expected_identity = _threshold_output_identity(
        target_identity,
        metric_family=output_family,
        metric_reference=metric_reference,
        measurand=measurand,
        unit=unit,
    )
    if result.metric_identity != expected_identity:
        raise ValueError("threshold result identity is not execution-bound")
    if output_family in {
        ExternalLoadMetricFamily.THRESHOLD_TIME,
        ExternalLoadMetricFamily.SPRINT_TIME,
    }:
        return time_s
    if output_family in {
        ExternalLoadMetricFamily.THRESHOLD_DISTANCE,
        ExternalLoadMetricFamily.SPRINT_DISTANCE,
    }:
        return distance_m
    assert event_count is not None
    return float(event_count)


def summarize_velocity_threshold(
    evidence: ExternalLoadVelocitySeriesEvidence | VelocitySeries,
    identity: ExternalLoadMeasurementIdentity | None = None,
) -> ExternalLoadThresholdSummary | RefusalResult:
    """Summarize a resolved velocity threshold from actual timestamped samples.

    The operation uses piecewise-linear interpolation only between supplied
    samples.  It never extrapolates before the first sample or after the last,
    and it never infers missing samples or a sampling rate.
    """

    if isinstance(evidence, VelocitySeries):
        return _refusal(
            blocked_claim="compute external-load velocity threshold summary",
            reason_codes=(RefusalReasonCode.THRESHOLD_SUMMARY_REQUIRES_RAW_SERIES,),
            missing_information=(
                "ExternalLoadVelocitySeriesEvidence binding samples to identity, context, "
                "acquisition, processing, and provenance",
            ),
        )
    if not isinstance(evidence, ExternalLoadVelocitySeriesEvidence):
        return _refusal(
            blocked_claim="compute external-load velocity threshold summary",
            reason_codes=(RefusalReasonCode.MISSING_METADATA,),
            missing_information=("ExternalLoadVelocitySeriesEvidence",),
        )
    if identity is None:
        identity = evidence.identity
    elif not isinstance(identity, ExternalLoadMeasurementIdentity):
        return _velocity_evidence_refusal(
            evidence,
            reasons=(RefusalReasonCode.MISSING_METADATA,),
            missing=("an ExternalLoadMeasurementIdentity bound to the evidence",),
        )
    evidence_refusal = _validate_velocity_evidence(evidence, identity)
    if evidence_refusal is not None:
        return evidence_refusal
    event_refusal = _validate_threshold_event_v1(identity, evidence)
    if event_refusal is not None:
        return event_refusal
    series = evidence.series
    reasons: list[RefusalReasonCode] = []
    missing: list[str] = []
    threshold = identity.threshold
    if series.maximum_gap_s is None:
        reasons.append(RefusalReasonCode.UNDECLARED_TIME_GAP)
        missing.append("maximum accepted sample gap")
    else:
        for left, right in pairwise(series.samples):
            if right.time_s - left.time_s > series.maximum_gap_s:
                reasons.append(RefusalReasonCode.UNDECLARED_TIME_GAP)
                missing.append("sample gap exceeds declared maximum")
                break
    if not threshold.is_resolved:
        reasons.append(RefusalReasonCode.UNKNOWN_THRESHOLD)
        if threshold.basis is ThresholdBasis.UNKNOWN:
            reasons.append(RefusalReasonCode.UNKNOWN_THRESHOLD_BASIS)
        missing.append("resolved threshold quantity, value, unit, basis, and boundary")
    elif threshold.threshold_quantity != EXTERNAL_LOAD_SPEED_MEASURAND:
        reasons.append(RefusalReasonCode.MEASURAND_MISMATCH)
        missing.append("the registered external-load speed measurand as threshold quantity")
    if threshold.boundary in (ThresholdBoundary.UNKNOWN, ThresholdBoundary.NONE):
        reasons.append(RefusalReasonCode.BOUNDARY_SEMANTICS_MISSING)
        missing.append("threshold boundary semantics")
    if identity.processing.filtering_status is ProcessingComponentStatus.UNKNOWN:
        reasons.append(RefusalReasonCode.UNKNOWN_FILTERING)
        missing.append("filtering status")
    if identity.processing.interpolation_method != EXTERNAL_LOAD_LINEAR_INTERPOLATION:
        reasons.append(RefusalReasonCode.UNKNOWN_INTERPOLATION)
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
    if reasons:
        return _refusal(
            blocked_claim="compute external-load velocity threshold summary",
            reason_codes=tuple(dict.fromkeys(reasons)),
            missing_information=tuple(dict.fromkeys(missing)),
            observation_ids=(evidence.bound_observation_id,),
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
            observation_ids=(evidence.bound_observation_id,),
        )
    event_count: int | None = None
    event_definition = identity.event_definition
    if identity.is_event_metric:
        assert event_definition is not None
        assert event_definition.minimum_duration_s is not None
        assert event_definition.gap_allowance_s is not None
        intervals = _qualified_intervals(series, threshold_mps, threshold.boundary)
        merged = _merge_intervals(intervals, event_definition.gap_allowance_s)
        event_count = sum(
            end - start >= event_definition.minimum_duration_s for start, end in merged
        )
        event_count = int(event_count)
    sprint_output = identity.metric_family in {
        ExternalLoadMetricFamily.SPRINT_DISTANCE,
        ExternalLoadMetricFamily.SPRINT_TIME,
        ExternalLoadMetricFamily.SPRINT_EVENT_COUNT,
    }
    time_family = (
        ExternalLoadMetricFamily.SPRINT_TIME
        if sprint_output
        else ExternalLoadMetricFamily.THRESHOLD_TIME
    )
    distance_family = (
        ExternalLoadMetricFamily.SPRINT_DISTANCE
        if sprint_output
        else ExternalLoadMetricFamily.THRESHOLD_DISTANCE
    )
    event_family = (
        ExternalLoadMetricFamily.SPRINT_EVENT_COUNT
        if sprint_output
        else ExternalLoadMetricFamily.THRESHOLD_EVENT_COUNT
    )
    time_metric = (
        EXTERNAL_LOAD_SPRINT_TIME_METRIC if sprint_output else EXTERNAL_LOAD_THRESHOLD_TIME_METRIC
    )
    distance_metric = (
        EXTERNAL_LOAD_SPRINT_DISTANCE_METRIC
        if sprint_output
        else EXTERNAL_LOAD_THRESHOLD_DISTANCE_METRIC
    )
    event_metric = (
        EXTERNAL_LOAD_SPRINT_EVENT_COUNT_METRIC
        if sprint_output
        else EXTERNAL_LOAD_THRESHOLD_EVENT_COUNT_METRIC
    )
    time_identity = _threshold_output_identity(
        identity,
        metric_family=time_family,
        metric_reference=time_metric,
        measurand=EXTERNAL_LOAD_DURATION_MEASURAND,
        unit=EXTERNAL_LOAD_SECOND,
    )
    distance_identity = _threshold_output_identity(
        identity,
        metric_family=distance_family,
        metric_reference=distance_metric,
        measurand=EXTERNAL_LOAD_DISTANCE_MEASURAND,
        unit=EXTERNAL_LOAD_METER,
    )
    time_result = _metric_result(
        operation=EXTERNAL_LOAD_THRESHOLD_SUMMARY_OPERATION,
        identity=time_identity,
        value=time_s,
        unit=EXTERNAL_LOAD_SECOND,
        input_identity_ids=(identity.identity_id,),
        source_observation_ids=(evidence.bound_observation_id,),
        source_series_id=evidence.series_id,
        source_provenance=(evidence.provenance,),
        source_series_evidence=evidence,
    )
    distance_result = _metric_result(
        operation=EXTERNAL_LOAD_THRESHOLD_SUMMARY_OPERATION,
        identity=distance_identity,
        value=distance_m,
        unit=EXTERNAL_LOAD_METER,
        input_identity_ids=(identity.identity_id,),
        source_observation_ids=(evidence.bound_observation_id,),
        source_series_id=evidence.series_id,
        source_provenance=(evidence.provenance,),
        source_series_evidence=evidence,
    )
    event_result: ExternalLoadMetricResult | None = None
    if event_count is not None:
        event_identity = _threshold_output_identity(
            identity,
            metric_family=event_family,
            metric_reference=event_metric,
            measurand=EXTERNAL_LOAD_EVENT_COUNT_MEASURAND,
            unit=EXTERNAL_LOAD_COUNT,
        )
        event_result = _metric_result(
            operation=EXTERNAL_LOAD_THRESHOLD_SUMMARY_OPERATION,
            identity=event_identity,
            value=event_count,
            unit=EXTERNAL_LOAD_COUNT,
            input_identity_ids=(identity.identity_id,),
            source_observation_ids=(evidence.bound_observation_id,),
            source_series_id=evidence.series_id,
            source_provenance=(evidence.provenance,),
            source_series_evidence=evidence,
        )
    return ExternalLoadThresholdSummary(
        operation=EXTERNAL_LOAD_THRESHOLD_SUMMARY_OPERATION,
        source_series_id=series.series_id,
        source_identity_id=identity.identity_id,
        threshold=threshold,
        time_above_threshold_s=time_s,
        distance_above_threshold_m=distance_m,
        event_count=event_count,
        event_definition=event_definition,
        time_result=time_result,
        distance_result=distance_result,
        event_count_result=event_result,
        evidence=evidence,
    )


# Readable aliases for the registered threshold operation.
calculate_velocity_threshold_summary = summarize_velocity_threshold
threshold_summary_from_velocity_series = summarize_velocity_threshold


__all__ = [
    "ExternalLoadComputationError",
    "ExternalLoadComputationStatus",
    "ExternalLoadMetricResult",
    "ExternalLoadThresholdSummary",
    "ExternalLoadVelocitySeriesEvidence",
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
