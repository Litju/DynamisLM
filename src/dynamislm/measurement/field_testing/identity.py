"""Typed, unknown-preserving identities for RES-67 field testing."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from itertools import pairwise

from dynamislm.measurement.identity import (
    AcquisitionIdentity,
    InstanceIdentifier,
    MeasurementIdentity,
    MetadataEntry,
    ProcessingIdentity,
    RegistryReference,
    SamplingCharacteristics,
    SemanticIdentity,
    UnitReference,
    _require_enum,
    _require_instance,
    _require_optional_instance,
    _require_text,
    _require_tuple_items,
    require_tuple,
)
from dynamislm.provenance.models import AcquisitionRecord, SourceArtifact
from dynamislm.serialization import canonical_hash, register_serializable_type


def _finite(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{field_name} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{field_name} must be finite")
    return result


def _finite_optional(value: object | None, field_name: str) -> float | None:
    if value is None:
        return None
    return _finite(value, field_name)


class FieldTestFamily(StrEnum):
    SHORT_LINEAR_SPRINT = "SHORT_LINEAR_SPRINT"
    SPRINT = "SHORT_LINEAR_SPRINT"
    MAXIMUM_SPRINT_VELOCITY = "MAXIMUM_SPRINT_VELOCITY"
    STANDARD_505 = "STANDARD_505"
    STANDARD_505_COD = "STANDARD_505"
    REPEATED_SPRINT_ABILITY = "REPEATED_SPRINT_ABILITY"
    RSA = "REPEATED_SPRINT_ABILITY"
    INTERMITTENT_FITNESS_30_15 = "INTERMITTENT_FITNESS_30_15"
    IFT30_15 = "INTERMITTENT_FITNESS_30_15"


class FieldTestSide(StrEnum):
    LEFT = "LEFT"
    RIGHT = "RIGHT"


class FieldTestSensorModality(StrEnum):
    TIMING_GATE = "TIMING_GATE"
    RADAR = "RADAR"
    LASER = "LASER"
    GNSS_GPS = "GNSS_GPS"
    GNSS = "GNSS_GPS"
    GPS = "GNSS_GPS"
    LOCAL_POSITIONING = "LOCAL_POSITIONING"
    LPS = "LOCAL_POSITIONING"
    OPTICAL = "OPTICAL"
    OPTICAL_TRACKING = "OPTICAL"
    VIDEO = "VIDEO"
    MANUAL = "MANUAL"
    SOURCE_REPORTED = "SOURCE_REPORTED"
    OTHER_REGISTERED = "OTHER_REGISTERED"
    UNKNOWN = "UNKNOWN"


class TimingGateTopology(StrEnum):
    SINGLE_BEAM = "SINGLE_BEAM"
    SINGLE = "SINGLE_BEAM"
    DUAL_BEAM = "DUAL_BEAM"
    DUAL = "DUAL_BEAM"
    OTHER_REGISTERED = "OTHER_REGISTERED"
    UNKNOWN = "UNKNOWN"


class StartInitiationMode(StrEnum):
    SELF_INITIATED_PHOTOCELL_CROSSING = "SELF_INITIATED_PHOTOCELL_CROSSING"
    AUDIO_OR_GUN_TRIGGER = "AUDIO_OR_GUN_TRIGGER"
    PRESSURE_PAD_TRIGGER = "PRESSURE_PAD_TRIGGER"
    FIRST_MOVEMENT = "FIRST_MOVEMENT"
    FIRST_FORCE_CHANGE = "FIRST_FORCE_CHANGE"
    MANUAL_STOPWATCH = "MANUAL_STOPWATCH"
    BLOCKED_START = "BLOCKED_START"
    VOLUNTARY_START = "VOLUNTARY_START"
    UNKNOWN = "UNKNOWN"


class ReactionTimeSemantics(StrEnum):
    INCLUDED = "INCLUDED"
    EXCLUDED = "EXCLUDED"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    UNKNOWN = "UNKNOWN"


class FieldTestTimebaseKind(StrEnum):
    REGULAR = "REGULAR"
    EXPLICIT = "EXPLICIT"


class FieldTestProcessingState(StrEnum):
    RAW_ACQUIRED = "RAW_ACQUIRED"
    DEVICE_PROCESSED = "DEVICE_PROCESSED"
    PROVIDER_PROCESSED = "PROVIDER_PROCESSED"
    DYNAMISLM_PROCESSED = "DYNAMISLM_PROCESSED"
    UNKNOWN = "UNKNOWN"


class FieldTestProcessingComponentStatus(StrEnum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    REGISTERED = "REGISTERED"
    NONE_DECLARED = "NONE_DECLARED"
    UNKNOWN = "UNKNOWN"


class FieldTestHashAlgorithm(StrEnum):
    SHA256 = "sha256"


class FieldTestArtifactHashScope(StrEnum):
    CONTENT_BYTES = "CONTENT_BYTES"
    CANONICAL_SERIES_REPRESENTATION = "CANONICAL_SERIES_REPRESENTATION"


class FieldTestArtifactStatus(StrEnum):
    VERIFIED = "VERIFIED"
    UNVERIFIED = "UNVERIFIED"


class FieldTestQualificationStatus(StrEnum):
    QUALIFIED = "QUALIFIED"
    REJECTED = "REJECTED"
    UNKNOWN = "UNKNOWN"


@register_serializable_type
@dataclass(frozen=True, slots=True)
class FieldTestingTimebase:
    """Regular or explicit timestamps for a field-test velocity series."""

    kind: FieldTestTimebaseKind
    sample_rate_hz: float | None = None
    start_time_s: float = 0.0
    times_s: tuple[float, ...] = ()

    def __post_init__(self) -> None:
        _require_enum(self.kind, FieldTestTimebaseKind, "kind")
        rate = _finite_optional(self.sample_rate_hz, "sample_rate_hz")
        if rate is not None and rate <= 0:
            raise ValueError("sample_rate_hz must be positive")
        object.__setattr__(self, "sample_rate_hz", rate)
        object.__setattr__(self, "start_time_s", _finite(self.start_time_s, "start_time_s"))
        require_tuple(self.times_s, "times_s")
        if self.kind is FieldTestTimebaseKind.REGULAR:
            if rate is None:
                raise ValueError("regular timebase requires sample_rate_hz")
            if self.times_s:
                raise ValueError("regular timebase must not carry explicit times")
        else:
            if not self.times_s:
                raise ValueError("explicit timebase requires times_s")
            normalized = tuple(_finite(value, "times_s item") for value in self.times_s)
            if any(right <= left for left, right in pairwise(normalized)):
                raise ValueError("explicit times_s must be strictly increasing")
            object.__setattr__(self, "times_s", normalized)

    def time_at(self, index: int) -> float:
        if type(index) is not int or index < 0:
            raise ValueError("timebase sample index must be a non-negative integer")
        if self.kind is FieldTestTimebaseKind.REGULAR:
            assert self.sample_rate_hz is not None
            return self.start_time_s + index / self.sample_rate_hz
        if index >= len(self.times_s):
            raise IndexError("sample index is outside explicit timebase")
        return self.times_s[index]


@register_serializable_type
@dataclass(frozen=True, slots=True)
class FieldTestingProtocolAttribute:
    """One explicit protocol attribute; omitted fields remain unresolved."""

    name: str
    value: str | int | float | bool | None
    unit: UnitReference | None = None

    def __post_init__(self) -> None:
        _require_text(self.name, "name")
        if self.value is not None and not isinstance(self.value, str | int | float | bool):
            raise ValueError("protocol attribute value must be scalar")
        if isinstance(self.value, float) and not math.isfinite(self.value):
            raise ValueError("protocol attribute value must be finite")
        _require_optional_instance(self.unit, UnitReference, "unit")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class FieldTestingDistanceDefinition:
    """Named distance definition preserved independently of a metric result."""

    name: str
    distance_m: float
    description: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.name, "name")
        distance = _finite(self.distance_m, "distance_m")
        if distance <= 0:
            raise ValueError("distance_m must be positive")
        object.__setattr__(self, "distance_m", distance)
        if self.description is not None:
            _require_text(self.description, "description")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class FieldTestingSegmentDefinition:
    """Exact one-dimensional segment used by split and average-velocity metrics."""

    name: str
    start_m: float
    end_m: float
    description: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.name, "name")
        start = _finite(self.start_m, "start_m")
        end = _finite(self.end_m, "end_m")
        if start < 0 or end <= start:
            raise ValueError("segment must satisfy 0 <= start_m < end_m")
        object.__setattr__(self, "start_m", start)
        object.__setattr__(self, "end_m", end)
        if self.description is not None:
            _require_text(self.description, "description")

    @property
    def distance_m(self) -> float:
        return self.end_m - self.start_m


@register_serializable_type
@dataclass(frozen=True, slots=True)
class FieldTestingProtocolIdentity:
    """Shared field-test protocol identity with explicit unknown slots."""

    family: FieldTestFamily
    protocol_version: str
    reference: RegistryReference | None = None
    surface: str | None = None
    environment: tuple[MetadataEntry, ...] | None = None
    course_layout: tuple[FieldTestingProtocolAttribute, ...] | None = None
    start_position: str | None = None
    start_line_offset_m: float | None = None
    start_initiation_mode: StartInitiationMode = StartInitiationMode.UNKNOWN
    reaction_time_semantics: ReactionTimeSemantics = ReactionTimeSemantics.UNKNOWN
    start_trigger: RegistryReference | None = None
    finish_trigger: RegistryReference | None = None
    timing_device: RegistryReference | None = None
    provider: str | None = None
    sensor_modality: FieldTestSensorModality = FieldTestSensorModality.UNKNOWN
    gate_topology: TimingGateTopology = TimingGateTopology.UNKNOWN
    gate_height_m: float | None = None
    sampling: SamplingCharacteristics | None = None
    timebase: FieldTestingTimebase | None = None
    filtering: tuple[RegistryReference, ...] | None = None
    smoothing: RegistryReference | None = None
    interpolation: RegistryReference | None = None
    software: str | None = None
    firmware: str | None = None
    trial_selection: RegistryReference | None = None
    repetition_selection: RegistryReference | None = None
    side: FieldTestSide | None = None
    turn_leg_convention: str | None = None
    distance_definitions: tuple[FieldTestingDistanceDefinition, ...] | None = None
    segment_definitions: tuple[FieldTestingSegmentDefinition, ...] | None = None
    additional_attributes: tuple[FieldTestingProtocolAttribute, ...] = ()

    def __post_init__(self) -> None:
        _require_enum(self.family, FieldTestFamily, "family")
        _require_text(self.protocol_version, "protocol_version")
        _require_optional_instance(self.reference, RegistryReference, "reference")
        if self.reference is not None and self.reference.identifier.object_type != "protocol":
            raise ValueError("field-test protocol reference must have object_type 'protocol'")
        if self.surface is not None:
            _require_text(self.surface, "surface")
        if self.environment is not None:
            _require_tuple_items(self.environment, MetadataEntry, "environment")
        if self.course_layout is not None:
            _require_tuple_items(self.course_layout, FieldTestingProtocolAttribute, "course_layout")
        if self.start_position is not None:
            _require_text(self.start_position, "start_position")
        offset = _finite_optional(self.start_line_offset_m, "start_line_offset_m")
        if offset is not None and offset < 0:
            raise ValueError("start_line_offset_m must be non-negative")
        object.__setattr__(self, "start_line_offset_m", offset)
        _require_enum(self.start_initiation_mode, StartInitiationMode, "start_initiation_mode")
        _require_enum(
            self.reaction_time_semantics, ReactionTimeSemantics, "reaction_time_semantics"
        )
        for name, value in (
            ("start_trigger", self.start_trigger),
            ("finish_trigger", self.finish_trigger),
            ("timing_device", self.timing_device),
            ("smoothing", self.smoothing),
            ("interpolation", self.interpolation),
            ("trial_selection", self.trial_selection),
            ("repetition_selection", self.repetition_selection),
        ):
            _require_optional_instance(value, RegistryReference, name)
        if self.provider is not None:
            _require_text(self.provider, "provider")
        _require_enum(self.sensor_modality, FieldTestSensorModality, "sensor_modality")
        _require_enum(self.gate_topology, TimingGateTopology, "gate_topology")
        gate_height = _finite_optional(self.gate_height_m, "gate_height_m")
        if gate_height is not None and gate_height <= 0:
            raise ValueError("gate_height_m must be positive")
        object.__setattr__(self, "gate_height_m", gate_height)
        _require_optional_instance(self.sampling, SamplingCharacteristics, "sampling")
        _require_optional_instance(self.timebase, FieldTestingTimebase, "timebase")
        if self.filtering is not None:
            _require_tuple_items(self.filtering, RegistryReference, "filtering")
        for field_name, field_value in (("software", self.software), ("firmware", self.firmware)):
            if field_value is not None:
                _require_text(field_value, field_name)
        if self.distance_definitions is not None:
            _require_tuple_items(
                self.distance_definitions,
                FieldTestingDistanceDefinition,
                "distance_definitions",
            )
        if self.segment_definitions is not None:
            _require_tuple_items(
                self.segment_definitions,
                FieldTestingSegmentDefinition,
                "segment_definitions",
            )
        _require_tuple_items(
            self.additional_attributes,
            FieldTestingProtocolAttribute,
            "additional_attributes",
        )
        if self.side is not None:
            _require_enum(self.side, FieldTestSide, "side")
        if self.turn_leg_convention is not None:
            _require_text(self.turn_leg_convention, "turn_leg_convention")

    @property
    def test_family(self) -> FieldTestFamily:
        return self.family

    @property
    def start_offset_m(self) -> float | None:
        return self.start_line_offset_m

    @property
    def timing_gate_topology(self) -> TimingGateTopology:
        return self.gate_topology


@register_serializable_type
@dataclass(frozen=True, slots=True, kw_only=True)
class FieldTestingAcquisitionIdentity(AcquisitionIdentity):
    """Acquisition identity for timing and velocity-domain field-test sources."""

    acquisition_instance_id: InstanceIdentifier | None = None
    provider: str | None = None
    sensor_modality: FieldTestSensorModality = FieldTestSensorModality.UNKNOWN
    timebase: FieldTestingTimebase | None = None
    axis_or_frame: RegistryReference | None = None
    source_series_digest: str | None = None

    def __post_init__(self) -> None:
        AcquisitionIdentity.__post_init__(self)
        _require_optional_instance(
            self.acquisition_instance_id, InstanceIdentifier, "acquisition_instance_id"
        )
        if (
            self.acquisition_instance_id is not None
            and self.acquisition_instance_id.instance_type != "acquisition"
        ):
            raise ValueError("acquisition_instance_id must identify an acquisition")
        if self.provider is not None:
            _require_text(self.provider, "provider")
        _require_enum(self.sensor_modality, FieldTestSensorModality, "sensor_modality")
        _require_optional_instance(self.timebase, FieldTestingTimebase, "timebase")
        _require_optional_instance(self.axis_or_frame, RegistryReference, "axis_or_frame")
        if self.source_series_digest is not None:
            _require_text(self.source_series_digest, "source_series_digest")


@register_serializable_type
@dataclass(frozen=True, slots=True, kw_only=True)
class FieldTestingProcessingIdentity(ProcessingIdentity):
    """Processing identity including field-test timebase and provider state."""

    timebase: FieldTestingTimebase | None = None
    smoothing: RegistryReference | None = None
    interpolation: RegistryReference | None = None
    processing_state: FieldTestProcessingState = FieldTestProcessingState.UNKNOWN
    filtering_status: FieldTestProcessingComponentStatus = (
        FieldTestProcessingComponentStatus.UNKNOWN
    )
    provider_algorithm: RegistryReference | None = None

    def __post_init__(self) -> None:
        ProcessingIdentity.__post_init__(self)
        _require_optional_instance(self.timebase, FieldTestingTimebase, "timebase")
        _require_optional_instance(self.smoothing, RegistryReference, "smoothing")
        _require_optional_instance(self.interpolation, RegistryReference, "interpolation")
        _require_enum(self.processing_state, FieldTestProcessingState, "processing_state")
        _require_enum(
            self.filtering_status,
            FieldTestProcessingComponentStatus,
            "filtering_status",
        )
        _require_optional_instance(self.provider_algorithm, RegistryReference, "provider_algorithm")
        if (
            self.filtering_status is FieldTestProcessingComponentStatus.REGISTERED
            and not self.filtering
        ):
            raise ValueError("registered filtering requires at least one method")
        if (
            self.filtering_status
            in {
                FieldTestProcessingComponentStatus.NONE_DECLARED,
                FieldTestProcessingComponentStatus.NOT_APPLICABLE,
            }
            and self.filtering
        ):
            raise ValueError("none/not-applicable filtering cannot carry methods")


@register_serializable_type
@dataclass(frozen=True, slots=True, kw_only=True)
class FieldTestingSemanticIdentity(SemanticIdentity):
    """Generic semantic identity carrying the full field-test protocol object."""

    protocol_identity: FieldTestingProtocolIdentity | None = None

    def __post_init__(self) -> None:
        SemanticIdentity.__post_init__(self)
        _require_optional_instance(
            self.protocol_identity, FieldTestingProtocolIdentity, "protocol_identity"
        )
        if self.protocol_identity is not None:
            if (
                self.protocol_identity.reference is not None
                and self.protocol != self.protocol_identity.reference
            ):
                raise ValueError("protocol and protocol_identity references must agree")
            if self.protocol is None and self.protocol_identity.reference is not None:
                raise ValueError(
                    "protocol reference is required for a registered protocol identity"
                )


@register_serializable_type
@dataclass(frozen=True, slots=True, kw_only=True)
class FieldTestingMeasurementIdentity(MeasurementIdentity):
    """Measurement identity shared by all RES-67 source and derived metrics."""

    semantic: FieldTestingSemanticIdentity
    acquisition: FieldTestingAcquisitionIdentity
    processing: FieldTestingProcessingIdentity

    def __post_init__(self) -> None:
        MeasurementIdentity.__post_init__(self)
        _require_instance(self.semantic, FieldTestingSemanticIdentity, "semantic")
        _require_instance(self.acquisition, FieldTestingAcquisitionIdentity, "acquisition")
        _require_instance(self.processing, FieldTestingProcessingIdentity, "processing")
        protocol = self.semantic.protocol_identity
        if protocol is not None and self.semantic.protocol is not None:
            if self.semantic.protocol != protocol.reference:
                raise ValueError("field-test protocol references do not agree")


def _require_family(identity: FieldTestingMeasurementIdentity, family: FieldTestFamily) -> None:
    protocol = identity.semantic.protocol_identity
    if protocol is not None and protocol.family is not family:
        raise ValueError(f"field-test identity requires {family.value} protocol")


@register_serializable_type
@dataclass(frozen=True, slots=True, kw_only=True)
class SprintMeasurementIdentity(FieldTestingMeasurementIdentity):
    def __post_init__(self) -> None:
        FieldTestingMeasurementIdentity.__post_init__(self)
        _require_family(self, FieldTestFamily.SHORT_LINEAR_SPRINT)


@register_serializable_type
@dataclass(frozen=True, slots=True, kw_only=True)
class MaximumSprintVelocityMeasurementIdentity(FieldTestingMeasurementIdentity):
    def __post_init__(self) -> None:
        FieldTestingMeasurementIdentity.__post_init__(self)
        _require_family(self, FieldTestFamily.MAXIMUM_SPRINT_VELOCITY)


@register_serializable_type
@dataclass(frozen=True, slots=True, kw_only=True)
class Standard505MeasurementIdentity(FieldTestingMeasurementIdentity):
    def __post_init__(self) -> None:
        FieldTestingMeasurementIdentity.__post_init__(self)
        _require_family(self, FieldTestFamily.STANDARD_505)


@register_serializable_type
@dataclass(frozen=True, slots=True, kw_only=True)
class RSAMeasurementIdentity(FieldTestingMeasurementIdentity):
    def __post_init__(self) -> None:
        FieldTestingMeasurementIdentity.__post_init__(self)
        _require_family(self, FieldTestFamily.REPEATED_SPRINT_ABILITY)


@register_serializable_type
@dataclass(frozen=True, slots=True, kw_only=True)
class IFT30_15MeasurementIdentity(FieldTestingMeasurementIdentity):  # noqa: N801
    def __post_init__(self) -> None:
        FieldTestingMeasurementIdentity.__post_init__(self)
        _require_family(self, FieldTestFamily.INTERMITTENT_FITNESS_30_15)


@register_serializable_type
@dataclass(frozen=True, slots=True, kw_only=True)
class FieldTestingSourceArtifact(SourceArtifact):
    """Content-addressed field-test artifact with explicit verification state."""

    hash_algorithm: FieldTestHashAlgorithm
    hash_scope: FieldTestArtifactHashScope
    status: FieldTestArtifactStatus

    def __post_init__(self) -> None:
        SourceArtifact.__post_init__(self)
        _require_enum(self.hash_algorithm, FieldTestHashAlgorithm, "hash_algorithm")
        _require_enum(self.hash_scope, FieldTestArtifactHashScope, "hash_scope")
        _require_enum(self.status, FieldTestArtifactStatus, "status")


@register_serializable_type
@dataclass(frozen=True, slots=True, kw_only=True)
class FieldTestingAcquisitionRecord(AcquisitionRecord):
    """Acquisition record preserving provider and modality without redefining RES-64."""

    provider: str | None = None
    sensor_modality: FieldTestSensorModality = FieldTestSensorModality.UNKNOWN
    timebase: FieldTestingTimebase | None = None
    axis_or_frame: RegistryReference | None = None

    def __post_init__(self) -> None:
        AcquisitionRecord.__post_init__(self)
        if self.provider is not None:
            _require_text(self.provider, "provider")
        _require_enum(self.sensor_modality, FieldTestSensorModality, "sensor_modality")
        _require_optional_instance(self.timebase, FieldTestingTimebase, "timebase")
        _require_optional_instance(self.axis_or_frame, RegistryReference, "axis_or_frame")


@register_serializable_type
@dataclass(frozen=True, slots=True, kw_only=True)
class FieldTestingSupport:
    """Exact inclusive support for a delivered time-resolved velocity series."""

    support_id: InstanceIdentifier
    start_index: int
    end_index: int
    start_time_s: float
    end_time_s: float

    def __post_init__(self) -> None:
        _require_instance(self.support_id, InstanceIdentifier, "support_id")
        if self.support_id.instance_type != "support":
            raise ValueError("support_id must identify a support")
        if type(self.start_index) is not int or type(self.end_index) is not int:
            raise ValueError("support indices must be integers")
        if self.start_index < 0 or self.end_index < self.start_index:
            raise ValueError("support must satisfy 0 <= start_index <= end_index")
        start = _finite(self.start_time_s, "start_time_s")
        end = _finite(self.end_time_s, "end_time_s")
        if end < start:
            raise ValueError("support end time must not precede start time")
        object.__setattr__(self, "start_time_s", start)
        object.__setattr__(self, "end_time_s", end)


def canonical_velocity_series_digest(
    samples: tuple[tuple[float, float], ...],
    timebase: FieldTestingTimebase,
    support: FieldTestingSupport,
    unit: UnitReference,
    sampling: SamplingCharacteristics | None = None,
) -> str:
    """Digest exact samples, timestamps, support and unit for source binding."""

    return canonical_hash(
        {
            "samples": samples,
            "timebase": timebase,
            "support": support,
            "unit": unit,
            "sampling": sampling,
        }
    )


# Readable aliases used by callers that spell the vertical name first. They
# resolve to the same registered classes and do not add wire identities.
FieldTestingTestFamily = FieldTestFamily
FieldTestingSide = FieldTestSide
FieldTestingSensorModality = FieldTestSensorModality
FieldTestingProtocol = FieldTestingProtocolIdentity
FieldTestingTimebaseKind = FieldTestTimebaseKind
FieldTestingStartMode = StartInitiationMode
FieldTestingReactionTimeSemantics = ReactionTimeSemantics


__all__ = [
    "FieldTestArtifactHashScope",
    "FieldTestArtifactStatus",
    "FieldTestFamily",
    "FieldTestHashAlgorithm",
    "FieldTestProcessingComponentStatus",
    "FieldTestProcessingState",
    "FieldTestQualificationStatus",
    "FieldTestSensorModality",
    "FieldTestSide",
    "FieldTestTimebaseKind",
    "FieldTestingAcquisitionIdentity",
    "FieldTestingAcquisitionRecord",
    "FieldTestingDistanceDefinition",
    "FieldTestingMeasurementIdentity",
    "FieldTestingProcessingIdentity",
    "FieldTestingProtocol",
    "FieldTestingProtocolAttribute",
    "FieldTestingProtocolIdentity",
    "FieldTestingReactionTimeSemantics",
    "FieldTestingSegmentDefinition",
    "FieldTestingSemanticIdentity",
    "FieldTestingSensorModality",
    "FieldTestingSide",
    "FieldTestingSourceArtifact",
    "FieldTestingStartMode",
    "FieldTestingSupport",
    "FieldTestingTestFamily",
    "FieldTestingTimebase",
    "FieldTestingTimebaseKind",
    "IFT30_15MeasurementIdentity",
    "MaximumSprintVelocityMeasurementIdentity",
    "RSAMeasurementIdentity",
    "ReactionTimeSemantics",
    "SprintMeasurementIdentity",
    "Standard505MeasurementIdentity",
    "StartInitiationMode",
    "TimingGateTopology",
    "canonical_velocity_series_digest",
]
