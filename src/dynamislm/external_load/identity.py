"""Typed external-load measurement identity extensions.

The generic measurement kernel deliberately does not assume that a metric
label has one meaning.  This module adds the external-load dimensions that
are material for GNSS, optical, inertial, and provider-reported observations
while keeping ``ScientificMeasurementObservation`` and ``Provenance`` as the
composite/source contracts.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import StrEnum

from dynamislm.measurement.identity import (
    MeasurementIdentity,
    MetadataEntry,
    ProcessingIdentity,
    RegistryReference,
    SamplingCharacteristics,
    UnitReference,
    _require_enum,
    _require_instance,
    _require_number,
    _require_optional_instance,
    _require_text,
    _require_tuple_items,
)
from dynamislm.measurement.taxonomy import ValueOrigin
from dynamislm.serialization import register_serializable_type


class ExternalLoadModality(StrEnum):
    """The measuring modality or source form of an external-load value."""

    GNSS = "GNSS"
    OPTICAL_TRACKING = "OPTICAL_TRACKING"
    INERTIAL = "INERTIAL"
    SOURCE_REPORTED = "SOURCE_REPORTED"
    OTHER_REGISTERED = "OTHER_REGISTERED"


# The generic taxonomy is the serialization/observation authority.  This
# alias gives external-load callers a discoverable domain name without
# creating a second value-origin enum that MeasurementResult could not carry.
ExternalLoadValueOrigin = ValueOrigin


class ExternalLoadMetricFamily(StrEnum):
    """Identity-bearing metric families; none supplies a universal definition."""

    SESSION_DURATION = "SESSION_DURATION"
    MINUTES_EXPOSURE = "MINUTES_EXPOSURE"
    TOTAL_DISTANCE = "TOTAL_DISTANCE"
    RELATIVE_DISTANCE = "RELATIVE_DISTANCE"
    MAXIMUM_SPEED = "MAXIMUM_SPEED"
    THRESHOLD_DISTANCE = "THRESHOLD_DISTANCE"
    THRESHOLD_TIME = "THRESHOLD_TIME"
    THRESHOLD_EVENT_COUNT = "THRESHOLD_EVENT_COUNT"
    SPRINT_DISTANCE = "SPRINT_DISTANCE"
    SPRINT_TIME = "SPRINT_TIME"
    SPRINT_EVENT_COUNT = "SPRINT_EVENT_COUNT"
    EXPLOSIVE_EFFORT_EVENT_COUNT = "EXPLOSIVE_EFFORT_EVENT_COUNT"
    CHANGE_OF_DIRECTION_EVENT_COUNT = "CHANGE_OF_DIRECTION_EVENT_COUNT"
    JUMP_EVENT_COUNT = "JUMP_EVENT_COUNT"
    ACCELERATION_EVENT_COUNT = "ACCELERATION_EVENT_COUNT"
    DECELERATION_EVENT_COUNT = "DECELERATION_EVENT_COUNT"
    REPEATED_HIGH_INTENSITY_EFFORT = "REPEATED_HIGH_INTENSITY_EFFORT"
    PROVIDER_LOAD = "PROVIDER_LOAD"
    OTHER_REGISTERED = "OTHER_REGISTERED"


# Readable compatibility alias for callers that call the family a metric kind.
ExternalLoadMetricKind = ExternalLoadMetricFamily


class ExternalLoadDefinitionStatus(StrEnum):
    """Resolution state for a source/provider definition."""

    RESOLVED = "RESOLVED"
    PARTIAL = "PARTIAL"
    UNRESOLVED = "UNRESOLVED"


class ThresholdBasis(StrEnum):
    """Whether a threshold is absolute, individualized, absent, or unknown."""

    NONE = "NONE"
    ABSOLUTE = "ABSOLUTE"
    INDIVIDUALIZED = "INDIVIDUALIZED"
    UNKNOWN = "UNKNOWN"


class ThresholdBoundary(StrEnum):
    """Boundary semantics for a threshold predicate."""

    GREATER_THAN = "GREATER_THAN"
    GREATER_THAN_OR_EQUAL = "GREATER_THAN_OR_EQUAL"
    LESS_THAN = "LESS_THAN"
    LESS_THAN_OR_EQUAL = "LESS_THAN_OR_EQUAL"
    NONE = "NONE"
    UNKNOWN = "UNKNOWN"


class EventHysteresisStatus(StrEnum):
    """Explicit hysteresis state; absence is not interpreted as no hysteresis."""

    NONE = "NONE"
    DEFINED = "DEFINED"
    UNKNOWN = "UNKNOWN"


class ProcessingComponentStatus(StrEnum):
    """Resolution state for a processing component."""

    NOT_APPLICABLE = "NOT_APPLICABLE"
    REGISTERED = "REGISTERED"
    UNKNOWN = "UNKNOWN"


class AggregationContext(StrEnum):
    """Football exposure context for an aggregate."""

    MATCH = "MATCH"
    TRAINING = "TRAINING"
    OTHER = "OTHER"
    UNKNOWN = "UNKNOWN"


class AggregationScope(StrEnum):
    """Session/period scope of an aggregate."""

    WHOLE_SESSION = "WHOLE_SESSION"
    PERIOD_OR_SEGMENT = "PERIOD_OR_SEGMENT"
    UNKNOWN = "UNKNOWN"


class NormalizationKind(StrEnum):
    """Normalization identity, independent of whether an operation is run."""

    NONE = "NONE"
    DURATION_NORMALIZED = "DURATION_NORMALIZED"
    BODY_MASS_NORMALIZED = "BODY_MASS_NORMALIZED"
    OTHER_REGISTERED = "OTHER_REGISTERED"
    UNKNOWN = "UNKNOWN"


def _finite_optional(value: float | None, field_name: str) -> None:
    if value is not None:
        _require_number(value, field_name)
        if not math.isfinite(float(value)):
            raise ValueError(f"{field_name} must be finite")


def _nonnegative_optional(value: float | None, field_name: str) -> None:
    _finite_optional(value, field_name)
    if value is not None and float(value) < 0:
        raise ValueError(f"{field_name} must be non-negative")


def _require_metadata_tuple(value: object, field_name: str) -> None:
    _require_tuple_items(value, MetadataEntry, field_name)


@register_serializable_type
@dataclass(frozen=True, slots=True)
class ExternalLoadSystemIdentity:
    """Provider/device/acquisition identity for an external-load observation."""

    provider: str
    device_or_system: RegistryReference | None = None
    model: RegistryReference | None = None
    sampling: SamplingCharacteristics | None = None
    acquisition_characteristics: tuple[MetadataEntry, ...] = ()
    firmware_version: str | None = None
    software_version: str | None = None
    processing_version: str | None = None
    provider_algorithm: RegistryReference | None = None
    provider_algorithm_status: ProcessingComponentStatus = ProcessingComponentStatus.UNKNOWN

    def __post_init__(self) -> None:
        _require_text(self.provider, "provider")
        _require_optional_instance(self.device_or_system, RegistryReference, "device_or_system")
        _require_optional_instance(self.model, RegistryReference, "model")
        _require_optional_instance(self.sampling, SamplingCharacteristics, "sampling")
        _require_metadata_tuple(self.acquisition_characteristics, "acquisition_characteristics")
        for field_name, value in (
            ("firmware_version", self.firmware_version),
            ("software_version", self.software_version),
            ("processing_version", self.processing_version),
        ):
            if value is not None:
                _require_text(value, field_name)
        _require_optional_instance(
            self.provider_algorithm,
            RegistryReference,
            "provider_algorithm",
        )
        _require_enum(
            self.provider_algorithm_status,
            ProcessingComponentStatus,
            "provider_algorithm_status",
        )
        if (
            self.provider_algorithm_status is ProcessingComponentStatus.NOT_APPLICABLE
            and self.provider_algorithm is not None
        ):
            raise ValueError("a not-applicable provider algorithm cannot have a method")
        if (
            self.provider_algorithm_status is ProcessingComponentStatus.REGISTERED
            and self.provider_algorithm is None
        ):
            raise ValueError("a registered provider algorithm must identify its method")

    @property
    def device(self) -> RegistryReference | None:
        """Readable alias for the provider's device/measuring-system identity."""

        return self.device_or_system

    @property
    def sampling_rate_hz(self) -> float | None:
        """Return the declared rate, or ``None`` when the rate is unknown."""

        return None if self.sampling is None else self.sampling.frequency_hz


@register_serializable_type
@dataclass(frozen=True, slots=True)
class ExternalLoadThresholdIdentity:
    """Threshold quantity, value, basis, unit, reference, and boundary."""

    basis: ThresholdBasis = ThresholdBasis.UNKNOWN
    threshold_quantity: RegistryReference | None = None
    threshold_value: float | None = None
    threshold_unit: UnitReference | None = None
    individualized_reference: RegistryReference | None = None
    boundary: ThresholdBoundary = ThresholdBoundary.UNKNOWN

    def __post_init__(self) -> None:
        _require_enum(self.basis, ThresholdBasis, "basis")
        _require_optional_instance(
            self.threshold_quantity,
            RegistryReference,
            "threshold_quantity",
        )
        _finite_optional(self.threshold_value, "threshold_value")
        if self.threshold_value is not None:
            object.__setattr__(self, "threshold_value", float(self.threshold_value))
        _require_optional_instance(self.threshold_unit, UnitReference, "threshold_unit")
        _require_optional_instance(
            self.individualized_reference,
            RegistryReference,
            "individualized_reference",
        )
        _require_enum(self.boundary, ThresholdBoundary, "boundary")
        if self.basis is ThresholdBasis.NONE:
            if any(
                value is not None
                for value in (
                    self.threshold_quantity,
                    self.threshold_value,
                    self.threshold_unit,
                    self.individualized_reference,
                )
            ):
                raise ValueError("a NONE threshold cannot carry threshold parameters")
            if self.boundary is not ThresholdBoundary.NONE:
                raise ValueError("a NONE threshold must use NONE boundary semantics")
        elif self.basis in (ThresholdBasis.ABSOLUTE, ThresholdBasis.INDIVIDUALIZED):
            if self.threshold_quantity is None:
                raise ValueError("a resolved threshold requires threshold_quantity")
            if self.threshold_value is None:
                raise ValueError("a resolved threshold requires threshold_value")
            if self.threshold_unit is None:
                raise ValueError("a resolved threshold requires threshold_unit")
            if self.boundary in (ThresholdBoundary.NONE, ThresholdBoundary.UNKNOWN):
                raise ValueError("a resolved threshold requires boundary semantics")
            if self.basis is ThresholdBasis.ABSOLUTE and self.individualized_reference is not None:
                raise ValueError("an absolute threshold cannot carry an individualized reference")
            if (
                self.basis is ThresholdBasis.INDIVIDUALIZED
                and self.individualized_reference is None
            ):
                raise ValueError("an individualized threshold requires its reference")
        elif self.boundary is ThresholdBoundary.NONE:
            raise ValueError("an unknown threshold cannot use NONE boundary semantics")

    @property
    def is_resolved(self) -> bool:
        return self.basis in (ThresholdBasis.ABSOLUTE, ThresholdBasis.INDIVIDUALIZED)

    @classmethod
    def none(cls) -> ExternalLoadThresholdIdentity:
        """Return an explicit identity for a metric that is not thresholded."""

        return cls(basis=ThresholdBasis.NONE, boundary=ThresholdBoundary.NONE)

    @classmethod
    def unknown(cls) -> ExternalLoadThresholdIdentity:
        """Return an explicit unresolved threshold identity."""

        return cls()


@register_serializable_type
@dataclass(frozen=True, slots=True)
class EventHysteresisIdentity:
    """Entry/exit thresholds used by a registered event definition."""

    quantity: RegistryReference
    entry_value: float
    exit_value: float
    unit: UnitReference
    entry_boundary: ThresholdBoundary
    exit_boundary: ThresholdBoundary

    def __post_init__(self) -> None:
        _require_instance(self.quantity, RegistryReference, "quantity")
        _finite_optional(self.entry_value, "entry_value")
        _finite_optional(self.exit_value, "exit_value")
        object.__setattr__(self, "entry_value", float(self.entry_value))
        object.__setattr__(self, "exit_value", float(self.exit_value))
        _require_instance(self.unit, UnitReference, "unit")
        for field_name, value in (
            ("entry_boundary", self.entry_boundary),
            ("exit_boundary", self.exit_boundary),
        ):
            _require_enum(value, ThresholdBoundary, field_name)
            if value in (ThresholdBoundary.NONE, ThresholdBoundary.UNKNOWN):
                raise ValueError(f"{field_name} must be explicit for defined hysteresis")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class ExternalLoadEventDefinition:
    """Identity of a threshold/acceleration/deceleration event detector."""

    definition: RegistryReference | None = None
    minimum_duration_s: float | None = None
    hysteresis_status: EventHysteresisStatus = EventHysteresisStatus.UNKNOWN
    hysteresis: EventHysteresisIdentity | None = None
    gap_allowance_s: float | None = None
    start_rule: RegistryReference | None = None
    end_rule: RegistryReference | None = None
    acceleration_threshold: ExternalLoadThresholdIdentity | None = None
    deceleration_threshold: ExternalLoadThresholdIdentity | None = None

    def __post_init__(self) -> None:
        _require_optional_instance(self.definition, RegistryReference, "definition")
        _nonnegative_optional(self.minimum_duration_s, "minimum_duration_s")
        if self.minimum_duration_s is not None:
            object.__setattr__(self, "minimum_duration_s", float(self.minimum_duration_s))
        _require_enum(self.hysteresis_status, EventHysteresisStatus, "hysteresis_status")
        _require_optional_instance(self.hysteresis, EventHysteresisIdentity, "hysteresis")
        _nonnegative_optional(self.gap_allowance_s, "gap_allowance_s")
        if self.gap_allowance_s is not None:
            object.__setattr__(self, "gap_allowance_s", float(self.gap_allowance_s))
        _require_optional_instance(self.start_rule, RegistryReference, "start_rule")
        _require_optional_instance(self.end_rule, RegistryReference, "end_rule")
        _require_optional_instance(
            self.acceleration_threshold,
            ExternalLoadThresholdIdentity,
            "acceleration_threshold",
        )
        _require_optional_instance(
            self.deceleration_threshold,
            ExternalLoadThresholdIdentity,
            "deceleration_threshold",
        )
        if self.hysteresis_status is EventHysteresisStatus.NONE and self.hysteresis is not None:
            raise ValueError("NONE hysteresis cannot carry hysteresis parameters")
        if self.hysteresis_status is EventHysteresisStatus.DEFINED and self.hysteresis is None:
            raise ValueError("DEFINED hysteresis requires hysteresis parameters")

    @property
    def is_resolved_for_event_count(self) -> bool:
        return bool(
            self.definition is not None
            and self.minimum_duration_s is not None
            and self.hysteresis_status is not EventHysteresisStatus.UNKNOWN
            and self.gap_allowance_s is not None
            and self.start_rule is not None
            and self.end_rule is not None
        )


@register_serializable_type
@dataclass(frozen=True, slots=True)
class ExternalLoadAggregationWindow:
    """Optional explicit period/segment window inside a session."""

    reference: RegistryReference | None = None
    start_s: float | None = None
    end_s: float | None = None

    def __post_init__(self) -> None:
        _require_optional_instance(self.reference, RegistryReference, "reference")
        _finite_optional(self.start_s, "start_s")
        _finite_optional(self.end_s, "end_s")
        if self.start_s is not None:
            object.__setattr__(self, "start_s", float(self.start_s))
        if self.end_s is not None:
            object.__setattr__(self, "end_s", float(self.end_s))
        if self.start_s is not None and self.start_s < 0:
            raise ValueError("start_s must be non-negative")
        if self.end_s is not None and self.end_s < 0:
            raise ValueError("end_s must be non-negative")
        if self.start_s is not None and self.end_s is not None and self.end_s <= self.start_s:
            raise ValueError("end_s must be greater than start_s")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class ExternalLoadAggregationIdentity:
    """Session, context, and temporal aggregation identity."""

    session_definition: RegistryReference | None = None
    window: ExternalLoadAggregationWindow = field(default_factory=ExternalLoadAggregationWindow)
    context: AggregationContext = AggregationContext.UNKNOWN
    scope: AggregationScope = AggregationScope.UNKNOWN

    def __post_init__(self) -> None:
        _require_optional_instance(self.session_definition, RegistryReference, "session_definition")
        _require_instance(self.window, ExternalLoadAggregationWindow, "window")
        _require_enum(self.context, AggregationContext, "context")
        _require_enum(self.scope, AggregationScope, "scope")
        if self.scope is AggregationScope.PERIOD_OR_SEGMENT:
            if self.window.reference is None and (
                self.window.start_s is None or self.window.end_s is None
            ):
                raise ValueError("a period/segment aggregation requires an explicit window")

    @property
    def is_resolved(self) -> bool:
        return (
            self.session_definition is not None
            and self.context is not AggregationContext.UNKNOWN
            and self.scope is not AggregationScope.UNKNOWN
            and (
                self.scope is AggregationScope.WHOLE_SESSION
                or self.window.reference is not None
                or (self.window.start_s is not None and self.window.end_s is not None)
            )
        )


@register_serializable_type
@dataclass(frozen=True, slots=True)
class ProcessingStepIdentity:
    """Registered/unknown/not-applicable processing component."""

    status: ProcessingComponentStatus = ProcessingComponentStatus.UNKNOWN
    method: RegistryReference | None = None
    parameters: tuple[MetadataEntry, ...] = ()

    def __post_init__(self) -> None:
        _require_enum(self.status, ProcessingComponentStatus, "status")
        _require_optional_instance(self.method, RegistryReference, "method")
        _require_metadata_tuple(self.parameters, "parameters")
        if self.status is ProcessingComponentStatus.NOT_APPLICABLE and (
            self.method is not None or self.parameters
        ):
            raise ValueError("a not-applicable processing step cannot carry method parameters")
        if self.status is ProcessingComponentStatus.REGISTERED and self.method is None:
            raise ValueError("a registered processing step must identify its method")

    @classmethod
    def unknown(cls) -> ProcessingStepIdentity:
        return cls()

    @classmethod
    def not_applicable(cls) -> ProcessingStepIdentity:
        return cls(status=ProcessingComponentStatus.NOT_APPLICABLE)


@register_serializable_type
@dataclass(frozen=True, slots=True, kw_only=True)
class ExternalLoadProcessingIdentity(ProcessingIdentity):
    """Processing extension for filtering, smoothing, resampling, and derivatives."""

    filtering_status: ProcessingComponentStatus = ProcessingComponentStatus.UNKNOWN
    smoothing: ProcessingStepIdentity = field(default_factory=ProcessingStepIdentity.unknown)
    resampling: ProcessingStepIdentity = field(default_factory=ProcessingStepIdentity.unknown)
    differentiation_status: ProcessingComponentStatus = ProcessingComponentStatus.UNKNOWN
    interpolation_method: RegistryReference | None = None

    def __post_init__(self) -> None:
        ProcessingIdentity.__post_init__(self)
        _require_enum(self.filtering_status, ProcessingComponentStatus, "filtering_status")
        _require_instance(self.smoothing, ProcessingStepIdentity, "smoothing")
        _require_instance(self.resampling, ProcessingStepIdentity, "resampling")
        _require_enum(
            self.differentiation_status,
            ProcessingComponentStatus,
            "differentiation_status",
        )
        _require_optional_instance(
            self.interpolation_method,
            RegistryReference,
            "interpolation_method",
        )
        if self.filtering_status is ProcessingComponentStatus.NOT_APPLICABLE and self.filtering:
            raise ValueError("not-applicable filtering cannot carry methods")
        if self.filtering_status is ProcessingComponentStatus.REGISTERED and not self.filtering:
            raise ValueError("registered filtering must identify at least one method")
        if self.differentiation_status is ProcessingComponentStatus.NOT_APPLICABLE and (
            self.differentiation_method is not None
        ):
            raise ValueError("not-applicable differentiation cannot carry a method")
        if self.differentiation_status is ProcessingComponentStatus.REGISTERED and (
            self.differentiation_method is None
        ):
            raise ValueError("registered differentiation must identify a method")

    @property
    def filtering_is_known(self) -> bool:
        return self.filtering_status is not ProcessingComponentStatus.UNKNOWN


@register_serializable_type
@dataclass(frozen=True, slots=True)
class ExternalLoadNormalizationIdentity:
    """Normalization identity; no normalization is applied by construction."""

    kind: NormalizationKind = NormalizationKind.UNKNOWN
    method: RegistryReference | None = None
    parameters: tuple[MetadataEntry, ...] = ()

    def __post_init__(self) -> None:
        _require_enum(self.kind, NormalizationKind, "kind")
        _require_optional_instance(self.method, RegistryReference, "method")
        _require_metadata_tuple(self.parameters, "parameters")
        if self.kind is NormalizationKind.NONE and (self.method is not None or self.parameters):
            raise ValueError("NONE normalization cannot carry a method or parameters")
        if (
            self.kind
            in (
                NormalizationKind.DURATION_NORMALIZED,
                NormalizationKind.BODY_MASS_NORMALIZED,
                NormalizationKind.OTHER_REGISTERED,
            )
            and self.method is None
        ):
            raise ValueError("a registered normalization kind requires its method")

    @classmethod
    def none(cls) -> ExternalLoadNormalizationIdentity:
        return cls(kind=NormalizationKind.NONE)

    @classmethod
    def unknown(cls) -> ExternalLoadNormalizationIdentity:
        return cls()


_EXTERNAL_VALUE_ORIGINS = frozenset(
    {
        ValueOrigin.DIRECT_MEASUREMENT,
        ValueOrigin.SOURCE_REPORTED,
        ValueOrigin.PROVIDER_DERIVED,
        ValueOrigin.DYNAMISLM_DERIVED,
    }
)


@register_serializable_type
@dataclass(frozen=True, slots=True, kw_only=True)
class ExternalLoadMeasurementIdentity(MeasurementIdentity):
    """External-load identity extension accepted by the generic observation contract."""

    processing: ExternalLoadProcessingIdentity
    modality: ExternalLoadModality
    value_origin: ValueOrigin
    system: ExternalLoadSystemIdentity
    threshold: ExternalLoadThresholdIdentity
    aggregation: ExternalLoadAggregationIdentity
    normalization: ExternalLoadNormalizationIdentity
    event_definition: ExternalLoadEventDefinition | None = None
    metric_family: ExternalLoadMetricFamily = ExternalLoadMetricFamily.OTHER_REGISTERED
    definition_status: ExternalLoadDefinitionStatus = ExternalLoadDefinitionStatus.UNRESOLVED
    dynamislm_recomputable: bool = False

    def __post_init__(self) -> None:
        MeasurementIdentity.__post_init__(self)
        _require_instance(self.processing, ExternalLoadProcessingIdentity, "processing")
        _require_enum(self.modality, ExternalLoadModality, "modality")
        _require_enum(self.value_origin, ValueOrigin, "value_origin")
        if self.value_origin not in _EXTERNAL_VALUE_ORIGINS:
            raise ValueError("external-load identity uses an unsupported value origin")
        _require_instance(self.system, ExternalLoadSystemIdentity, "system")
        _require_instance(self.threshold, ExternalLoadThresholdIdentity, "threshold")
        _require_instance(self.aggregation, ExternalLoadAggregationIdentity, "aggregation")
        _require_instance(self.normalization, ExternalLoadNormalizationIdentity, "normalization")
        _require_optional_instance(
            self.event_definition,
            ExternalLoadEventDefinition,
            "event_definition",
        )
        _require_enum(self.metric_family, ExternalLoadMetricFamily, "metric_family")
        _require_enum(self.definition_status, ExternalLoadDefinitionStatus, "definition_status")
        if not isinstance(self.dynamislm_recomputable, bool):
            raise ValueError("dynamislm_recomputable must be a boolean")
        if (
            self.system.device_or_system is not None
            and self.acquisition.device is not None
            and self.system.device_or_system != self.acquisition.device
        ):
            raise ValueError("external system and generic acquisition device identities differ")
        if self.system.sampling != self.acquisition.sampling:
            raise ValueError("external system and generic acquisition sampling identities differ")
        if self.value_origin is ValueOrigin.DYNAMISLM_DERIVED and not self.dynamislm_recomputable:
            raise ValueError("DYNAMISLM_DERIVED identity must be marked recomputable")
        if self.value_origin is ValueOrigin.PROVIDER_DERIVED and self.dynamislm_recomputable:
            raise ValueError("PROVIDER_DERIVED identity cannot claim DynamisLM recomputability")

    @property
    def display_label(self) -> str:
        return self.semantic.metric_definition.display_label

    @property
    def provider(self) -> str:
        return self.system.provider

    @property
    def method_label(self) -> str | None:
        """Return a preserved source/provider method label when one is recorded."""

        for entry in self.processing.method_parameters:
            if entry.key in {"method_label", "source_label"} and isinstance(entry.value, str):
                return entry.value
        return None

    @property
    def is_event_metric(self) -> bool:
        return self.metric_family in {
            ExternalLoadMetricFamily.THRESHOLD_EVENT_COUNT,
            ExternalLoadMetricFamily.SPRINT_EVENT_COUNT,
            ExternalLoadMetricFamily.EXPLOSIVE_EFFORT_EVENT_COUNT,
            ExternalLoadMetricFamily.CHANGE_OF_DIRECTION_EVENT_COUNT,
            ExternalLoadMetricFamily.JUMP_EVENT_COUNT,
            ExternalLoadMetricFamily.ACCELERATION_EVENT_COUNT,
            ExternalLoadMetricFamily.DECELERATION_EVENT_COUNT,
            ExternalLoadMetricFamily.REPEATED_HIGH_INTENSITY_EFFORT,
        }

    @property
    def is_threshold_metric(self) -> bool:
        return self.metric_family in {
            ExternalLoadMetricFamily.THRESHOLD_DISTANCE,
            ExternalLoadMetricFamily.THRESHOLD_TIME,
            ExternalLoadMetricFamily.THRESHOLD_EVENT_COUNT,
            ExternalLoadMetricFamily.SPRINT_DISTANCE,
            ExternalLoadMetricFamily.SPRINT_TIME,
            ExternalLoadMetricFamily.SPRINT_EVENT_COUNT,
        }


# Short aliases make the vertical identity vocabulary easy to discover while
# retaining the explicit class names in serialized type identifiers.
ExternalLoadIdentity = ExternalLoadMeasurementIdentity
ThresholdIdentity = ExternalLoadThresholdIdentity
EventDefinition = ExternalLoadEventDefinition
AggregationIdentity = ExternalLoadAggregationIdentity
NormalizationIdentity = ExternalLoadNormalizationIdentity


__all__ = [
    "AggregationContext",
    "AggregationIdentity",
    "AggregationScope",
    "EventDefinition",
    "EventHysteresisIdentity",
    "EventHysteresisStatus",
    "ExternalLoadAggregationIdentity",
    "ExternalLoadAggregationWindow",
    "ExternalLoadDefinitionStatus",
    "ExternalLoadEventDefinition",
    "ExternalLoadIdentity",
    "ExternalLoadMeasurementIdentity",
    "ExternalLoadMetricFamily",
    "ExternalLoadMetricKind",
    "ExternalLoadModality",
    "ExternalLoadNormalizationIdentity",
    "ExternalLoadProcessingIdentity",
    "ExternalLoadSystemIdentity",
    "ExternalLoadThresholdIdentity",
    "ExternalLoadValueOrigin",
    "NormalizationIdentity",
    "NormalizationKind",
    "ProcessingComponentStatus",
    "ProcessingStepIdentity",
    "ThresholdBasis",
    "ThresholdBoundary",
    "ThresholdIdentity",
]
