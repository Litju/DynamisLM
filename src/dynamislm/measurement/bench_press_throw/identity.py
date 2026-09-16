"""Typed BPT protocol, load-system, acquisition and support identities."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from itertools import pairwise

from dynamislm.measurement.bench_press_throw.registry import (
    BPT_DYNAMISLM_TIME_WEIGHTED_MEAN_BAR_VELOCITY_METRIC,
    BPT_PROTOCOL_V1,
    BPT_SAMPLED_MAXIMUM_BAR_VELOCITY_METRIC,
    BPT_TEST_FAMILY,
    KILOGRAM,
    METER_PER_SECOND,
    PERCENT,
)
from dynamislm.measurement.identity import (
    AcquisitionIdentity,
    InstanceIdentifier,
    MeasurementIdentity,
    MetadataEntry,
    ProcessingIdentity,
    RegistryReference,
    SamplingCharacteristics,
    ScientificIdentifier,
    SemanticIdentity,
    SignConvention,
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


class BPTMachineType(StrEnum):
    FIXED_VERTICAL_SMITH = "FIXED_VERTICAL_SMITH"
    OTHER_SMITH = "OTHER_SMITH"
    FREE_WEIGHT = "FREE_WEIGHT"
    OTHER_REGISTERED = "OTHER_REGISTERED"
    UNKNOWN = "UNKNOWN"


class BPTCounterbalanceStatus(StrEnum):
    PRESENT = "PRESENT"
    ABSENT = "ABSENT"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    UNKNOWN = "UNKNOWN"


class BPTLoadKind(StrEnum):
    PHYSICAL = "PHYSICAL"
    PERCENT_1RM = "PERCENT_1RM"
    UNKNOWN = "UNKNOWN"


class BPTMovementPattern(StrEnum):
    CONCENTRIC_ONLY = "CONCENTRIC_ONLY"
    ECCENTRIC_CONCENTRIC = "ECCENTRIC_CONCENTRIC"
    UNKNOWN = "UNKNOWN"


class BPTPauseTouchBounce(StrEnum):
    PAUSE = "PAUSE"
    TOUCH_AND_GO = "TOUCH_AND_GO"
    BOUNCE = "BOUNCE"
    UNKNOWN = "UNKNOWN"


class BPTReleaseSemantics(StrEnum):
    RELEASED = "RELEASED"
    NOT_RELEASED = "NOT_RELEASED"
    UNKNOWN = "UNKNOWN"


class BPTCatchSemantics(StrEnum):
    CAUGHT = "CAUGHT"
    NOT_CAUGHT = "NOT_CAUGHT"
    UNKNOWN = "UNKNOWN"


class BPTSensorModality(StrEnum):
    LINEAR_POSITION_TRANSDUCER = "LINEAR_POSITION_TRANSDUCER"
    LINEAR_ENCODER = "LINEAR_ENCODER"
    ACCELEROMETER = "ACCELEROMETER"
    OPTICAL = "OPTICAL"
    OTHER_REGISTERED = "OTHER_REGISTERED"
    UNKNOWN = "UNKNOWN"


class BPTTimebaseKind(StrEnum):
    REGULAR = "REGULAR"
    EXPLICIT = "EXPLICIT"


class BPTProcessingState(StrEnum):
    RAW_ACQUIRED = "RAW_ACQUIRED"
    DEVICE_PROCESSED = "DEVICE_PROCESSED"
    PROVIDER_PROCESSED = "PROVIDER_PROCESSED"
    DYNAMISLM_PROCESSED = "DYNAMISLM_PROCESSED"
    UNKNOWN = "UNKNOWN"


class BPTQualificationStatus(StrEnum):
    QUALIFIED = "QUALIFIED"
    REJECTED = "REJECTED"
    UNKNOWN = "UNKNOWN"


class BPTArtifactStatus(StrEnum):
    VERIFIED = "VERIFIED"
    UNVERIFIED = "UNVERIFIED"


class BPTHashAlgorithm(StrEnum):
    SHA256 = "sha256"


class BPTArtifactHashScope(StrEnum):
    CONTENT_BYTES = "CONTENT_BYTES"
    CANONICAL_SERIES_REPRESENTATION = "CANONICAL_SERIES_REPRESENTATION"


@register_serializable_type
@dataclass(frozen=True, slots=True)
class BPTLoadIdentity:
    """Physical or percent-1RM load plus the moving-system semantics."""

    kind: BPTLoadKind
    load_value: float | None
    load_unit: UnitReference | None
    bar_mass_kg: float | None
    added_load_kg: float | None
    counterweight_mass_kg: float | None
    moving_system_load_semantics: str | None
    effective_resistance_semantics: str | None

    def __post_init__(self) -> None:
        _require_enum(self.kind, BPTLoadKind, "kind")
        load_value = _finite_optional(self.load_value, "load_value")
        if load_value is not None and load_value <= 0:
            raise ValueError("load_value must be positive")
        object.__setattr__(self, "load_value", load_value)
        _require_optional_instance(self.load_unit, UnitReference, "load_unit")
        if self.kind is BPTLoadKind.PHYSICAL:
            if load_value is None or self.load_unit != KILOGRAM:
                raise ValueError("physical BPT load requires a positive kilogram value")
        elif self.kind is BPTLoadKind.PERCENT_1RM:
            if load_value is None or self.load_unit != PERCENT:
                raise ValueError("percent-1RM BPT load requires a positive percentage value")
        elif load_value is not None or self.load_unit is not None:
            raise ValueError("unknown BPT load kind cannot carry a load value")
        bar_mass = _finite_optional(self.bar_mass_kg, "bar_mass_kg")
        added_load = _finite_optional(self.added_load_kg, "added_load_kg")
        counterweight_mass = _finite_optional(self.counterweight_mass_kg, "counterweight_mass_kg")
        for name, value in (
            ("bar_mass_kg", bar_mass),
            ("added_load_kg", added_load),
            ("counterweight_mass_kg", counterweight_mass),
        ):
            if value is not None and value < 0:
                raise ValueError(f"{name} must not be negative")
        object.__setattr__(self, "bar_mass_kg", bar_mass)
        object.__setattr__(self, "added_load_kg", added_load)
        object.__setattr__(self, "counterweight_mass_kg", counterweight_mass)
        if self.moving_system_load_semantics is not None:
            _require_text(self.moving_system_load_semantics, "moving_system_load_semantics")
        if self.effective_resistance_semantics is not None:
            _require_text(self.effective_resistance_semantics, "effective_resistance_semantics")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class BPTTimebase:
    """Regular or explicit timestamps for one BPT velocity series."""

    kind: BPTTimebaseKind
    sample_rate_hz: float | None = None
    start_time_s: float = 0.0
    times_s: tuple[float, ...] = ()

    def __post_init__(self) -> None:
        _require_enum(self.kind, BPTTimebaseKind, "kind")
        rate = _finite_optional(self.sample_rate_hz, "sample_rate_hz")
        if rate is not None and rate <= 0:
            raise ValueError("sample_rate_hz must be positive")
        object.__setattr__(self, "sample_rate_hz", rate)
        object.__setattr__(self, "start_time_s", _finite(self.start_time_s, "start_time_s"))
        require_tuple(self.times_s, "times_s")
        if self.kind is BPTTimebaseKind.REGULAR:
            if rate is None:
                raise ValueError("regular timebase requires sample_rate_hz")
            if self.times_s:
                raise ValueError("regular timebase cannot carry explicit timestamps")
        else:
            if not self.times_s:
                raise ValueError("explicit timebase requires timestamps")
            normalized = tuple(_finite(item, "times_s item") for item in self.times_s)
            if any(right <= left for left, right in pairwise(normalized)):
                raise ValueError("explicit timestamps must be strictly increasing")
            object.__setattr__(self, "times_s", normalized)

    def time_at(self, index: int) -> float:
        if type(index) is not int or index < 0:
            raise ValueError("BPT sample index must be a non-negative integer")
        if self.kind is BPTTimebaseKind.REGULAR:
            assert self.sample_rate_hz is not None
            return self.start_time_s + index / self.sample_rate_hz
        if index >= len(self.times_s):
            raise IndexError("BPT sample index is outside explicit timebase")
        return self.times_s[index]


@register_serializable_type
@dataclass(frozen=True, slots=True)
class BenchPressThrowProtocolIdentity:
    """Material BPT protocol and mechanical-system identity."""

    reference: RegistryReference = BPT_PROTOCOL_V1
    protocol_version: str = "1.0.0"
    machine_type: BPTMachineType = BPTMachineType.UNKNOWN
    counterbalance_status: BPTCounterbalanceStatus = BPTCounterbalanceStatus.UNKNOWN
    counterbalance_identity: RegistryReference | None = None
    load_identity: BPTLoadIdentity | None = None
    concentric_pattern: BPTMovementPattern = BPTMovementPattern.UNKNOWN
    pause_touch_bounce: BPTPauseTouchBounce = BPTPauseTouchBounce.UNKNOWN
    grip: str | None = None
    range_of_motion: str | None = None
    feet_body_support: str | None = None
    release_semantics: BPTReleaseSemantics = BPTReleaseSemantics.UNKNOWN
    catch_semantics: BPTCatchSemantics = BPTCatchSemantics.UNKNOWN
    provider: str | None = None
    device: RegistryReference | None = None
    sensor_modality: BPTSensorModality = BPTSensorModality.UNKNOWN
    sampling: SamplingCharacteristics | None = None
    timebase: BPTTimebase | None = None
    filtering: tuple[RegistryReference, ...] | None = None
    smoothing: RegistryReference | None = None
    resampling: RegistryReference | None = None
    software: str | None = None
    firmware: str | None = None
    source_series_digest: str | None = None
    operation_support_definition: str | None = None
    trial_qualification: RegistryReference | None = None
    trial_selection: RegistryReference | None = None
    additional_attributes: tuple[MetadataEntry, ...] = ()

    def __post_init__(self) -> None:
        _require_instance(self.reference, RegistryReference, "reference")
        if self.reference.identifier.object_type != "protocol":
            raise ValueError("BPT protocol reference must identify a protocol")
        _require_text(self.protocol_version, "protocol_version")
        _require_enum(self.machine_type, BPTMachineType, "machine_type")
        _require_enum(self.counterbalance_status, BPTCounterbalanceStatus, "counterbalance_status")
        _require_optional_instance(
            self.counterbalance_identity, RegistryReference, "counterbalance_identity"
        )
        if (
            self.counterbalance_status is BPTCounterbalanceStatus.PRESENT
            and self.counterbalance_identity is None
        ):
            raise ValueError("present BPT counterbalance requires a counterbalance identity")
        if (
            self.counterbalance_status is not BPTCounterbalanceStatus.PRESENT
            and self.counterbalance_identity is not None
        ):
            raise ValueError("counterbalance identity requires PRESENT counterbalance status")
        _require_optional_instance(self.load_identity, BPTLoadIdentity, "load_identity")
        _require_enum(self.concentric_pattern, BPTMovementPattern, "concentric_pattern")
        _require_enum(self.pause_touch_bounce, BPTPauseTouchBounce, "pause_touch_bounce")
        _require_enum(self.release_semantics, BPTReleaseSemantics, "release_semantics")
        _require_enum(self.catch_semantics, BPTCatchSemantics, "catch_semantics")
        _require_enum(self.sensor_modality, BPTSensorModality, "sensor_modality")
        for name, value in (
            ("grip", self.grip),
            ("range_of_motion", self.range_of_motion),
            ("feet_body_support", self.feet_body_support),
            ("provider", self.provider),
            ("software", self.software),
            ("firmware", self.firmware),
            ("source_series_digest", self.source_series_digest),
            ("operation_support_definition", self.operation_support_definition),
        ):
            if value is not None:
                _require_text(value, name)
        _require_optional_instance(self.device, RegistryReference, "device")
        _require_optional_instance(self.sampling, SamplingCharacteristics, "sampling")
        _require_optional_instance(self.timebase, BPTTimebase, "timebase")
        if self.filtering is not None:
            _require_tuple_items(self.filtering, RegistryReference, "filtering")
        _require_optional_instance(self.smoothing, RegistryReference, "smoothing")
        _require_optional_instance(self.resampling, RegistryReference, "resampling")
        _require_optional_instance(
            self.trial_qualification, RegistryReference, "trial_qualification"
        )
        _require_optional_instance(self.trial_selection, RegistryReference, "trial_selection")
        _require_tuple_items(self.additional_attributes, MetadataEntry, "additional_attributes")

    @property
    def test_family(self) -> RegistryReference:
        return BPT_TEST_FAMILY


@register_serializable_type
@dataclass(frozen=True, slots=True, kw_only=True)
class BenchPressThrowAcquisitionIdentity(AcquisitionIdentity):
    """BPT device/provider/frame/timebase identity."""

    acquisition_instance_id: InstanceIdentifier | None = None
    provider: str | None = None
    sensor_modality: BPTSensorModality = BPTSensorModality.UNKNOWN
    timebase: BPTTimebase | None = None
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
        _require_enum(self.sensor_modality, BPTSensorModality, "sensor_modality")
        _require_optional_instance(self.timebase, BPTTimebase, "timebase")
        _require_optional_instance(self.axis_or_frame, RegistryReference, "axis_or_frame")
        if self.source_series_digest is not None:
            _require_text(self.source_series_digest, "source_series_digest")


@register_serializable_type
@dataclass(frozen=True, slots=True, kw_only=True)
class BenchPressThrowProcessingIdentity(ProcessingIdentity):
    """BPT support, filtering and provider-processing identity."""

    timebase: BPTTimebase | None = None
    processing_state: BPTProcessingState = BPTProcessingState.UNKNOWN
    provider_algorithm: RegistryReference | None = None
    resampling: RegistryReference | None = None

    def __post_init__(self) -> None:
        ProcessingIdentity.__post_init__(self)
        _require_optional_instance(self.timebase, BPTTimebase, "timebase")
        _require_enum(self.processing_state, BPTProcessingState, "processing_state")
        _require_optional_instance(self.provider_algorithm, RegistryReference, "provider_algorithm")
        _require_optional_instance(self.resampling, RegistryReference, "resampling")


@register_serializable_type
@dataclass(frozen=True, slots=True, kw_only=True)
class BenchPressThrowSemanticIdentity(SemanticIdentity):
    """Semantic identity carrying the complete BPT protocol object."""

    protocol_identity: BenchPressThrowProtocolIdentity | None = None

    def __post_init__(self) -> None:
        SemanticIdentity.__post_init__(self)
        _require_instance(
            self.protocol_identity, BenchPressThrowProtocolIdentity, "protocol_identity"
        )
        assert self.protocol_identity is not None
        if self.test_family != BPT_TEST_FAMILY:
            raise ValueError("BPT semantic identity has the wrong test family")
        if self.protocol != self.protocol_identity.reference:
            raise ValueError("BPT protocol and protocol_identity references must agree")


@register_serializable_type
@dataclass(frozen=True, slots=True, kw_only=True)
class BenchPressThrowMeasurementIdentity(MeasurementIdentity):
    """Distinct BPT identity; not the pre-existing barbell velocity-test family."""

    semantic: BenchPressThrowSemanticIdentity
    acquisition: BenchPressThrowAcquisitionIdentity
    processing: BenchPressThrowProcessingIdentity

    def __post_init__(self) -> None:
        MeasurementIdentity.__post_init__(self)
        _require_instance(self.semantic, BenchPressThrowSemanticIdentity, "semantic")
        _require_instance(self.acquisition, BenchPressThrowAcquisitionIdentity, "acquisition")
        _require_instance(self.processing, BenchPressThrowProcessingIdentity, "processing")
        if self.semantic.test_family != BPT_TEST_FAMILY:
            raise ValueError("BPT measurement identity has the wrong family")


@register_serializable_type
@dataclass(frozen=True, slots=True, kw_only=True)
class BenchPressThrowSourceArtifact(SourceArtifact):
    """Verified BPT source artifact."""

    status: BPTArtifactStatus = BPTArtifactStatus.UNVERIFIED
    hash_algorithm: BPTHashAlgorithm = BPTHashAlgorithm.SHA256
    hash_scope: BPTArtifactHashScope = BPTArtifactHashScope.CONTENT_BYTES

    def __post_init__(self) -> None:
        SourceArtifact.__post_init__(self)
        _require_enum(self.status, BPTArtifactStatus, "status")
        _require_enum(self.hash_algorithm, BPTHashAlgorithm, "hash_algorithm")
        _require_enum(self.hash_scope, BPTArtifactHashScope, "hash_scope")


@register_serializable_type
@dataclass(frozen=True, slots=True, kw_only=True)
class BenchPressThrowAcquisitionRecord(AcquisitionRecord):
    """BPT acquisition record with provider, modality, frame and timebase."""

    provider: str | None = None
    sensor_modality: BPTSensorModality = BPTSensorModality.UNKNOWN
    timebase: BPTTimebase | None = None
    axis_or_frame: RegistryReference | None = None

    def __post_init__(self) -> None:
        AcquisitionRecord.__post_init__(self)
        if self.provider is not None:
            _require_text(self.provider, "provider")
        _require_enum(self.sensor_modality, BPTSensorModality, "sensor_modality")
        _require_optional_instance(self.timebase, BPTTimebase, "timebase")
        _require_optional_instance(self.axis_or_frame, RegistryReference, "axis_or_frame")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class BenchPressThrowVelocitySeries:
    """Exact timestamp-attached BPT bar-velocity samples."""

    series_id: InstanceIdentifier
    source_artifact_id: InstanceIdentifier
    acquisition_id: InstanceIdentifier
    source_measurement_identity_id: ScientificIdentifier
    samples: tuple[tuple[float, float], ...]
    timebase: BPTTimebase
    unit: UnitReference
    velocity_frame: RegistryReference
    sign_convention: SignConvention
    processing_state: BPTProcessingState

    def __post_init__(self) -> None:
        for name, value, expected in (
            ("series_id", self.series_id, "signal"),
            ("source_artifact_id", self.source_artifact_id, "artifact"),
            ("acquisition_id", self.acquisition_id, "acquisition"),
        ):
            _require_instance(value, InstanceIdentifier, name)
            if value.instance_type != expected:
                raise ValueError(f"{name} must identify a {expected}")
        _require_instance(
            self.source_measurement_identity_id,
            ScientificIdentifier,
            "source_measurement_identity_id",
        )
        if self.source_measurement_identity_id.object_type != "measurement-identity":
            raise ValueError("source_measurement_identity_id must identify a measurement")
        _require_instance(self.timebase, BPTTimebase, "timebase")
        _require_instance(self.unit, UnitReference, "unit")
        if self.unit != METER_PER_SECOND:
            raise ValueError("BPT velocity series must use m/s")
        _require_instance(self.velocity_frame, RegistryReference, "velocity_frame")
        _require_instance(self.sign_convention, SignConvention, "sign_convention")
        if (
            self.sign_convention.reference is None
            and self.sign_convention.positive_direction is None
        ):
            raise ValueError("BPT velocity series requires an explicit sign convention")
        _require_enum(self.processing_state, BPTProcessingState, "processing_state")
        if self.processing_state in {
            BPTProcessingState.UNKNOWN,
            BPTProcessingState.DYNAMISLM_PROCESSED,
        }:
            raise ValueError("BPT source series must be raw or device/provider processed")
        require_tuple(self.samples, "samples")
        if not self.samples:
            raise ValueError("BPT velocity series must not be empty")
        normalized: list[tuple[float, float]] = []
        for sample in self.samples:
            if not isinstance(sample, tuple) or len(sample) != 2:
                raise ValueError("BPT samples must be (time_s, velocity_m_per_s) tuples")
            time_s = _finite(sample[0], "sample time")
            velocity = _finite(sample[1], "velocity sample")
            normalized.append((time_s, velocity))
        if any(right[0] <= left[0] for left, right in pairwise(normalized)):
            raise ValueError("BPT sample timestamps must be strictly increasing")
        if any(
            self.timebase.time_at(index) != sample[0] for index, sample in enumerate(normalized)
        ):
            raise ValueError("BPT sample timestamps must equal the declared timebase")
        object.__setattr__(self, "samples", tuple(normalized))
        if self.timebase.kind is BPTTimebaseKind.EXPLICIT and len(self.timebase.times_s) != len(
            normalized
        ):
            raise ValueError("explicit BPT timebase length must equal sample count")

    def canonical_content_digest(self) -> str:
        return canonical_hash(
            {
                "samples": self.samples,
                "timebase": self.timebase,
                "unit": self.unit,
                "velocity_frame": self.velocity_frame,
                "sign_convention": self.sign_convention,
                "processing_state": self.processing_state,
            }
        )


@register_serializable_type
@dataclass(frozen=True, slots=True)
class BenchPressThrowMetricSupport:
    """Exact inclusive support for one BPT metric method."""

    support_id: InstanceIdentifier
    metric: RegistryReference
    start_index: int
    end_index: int
    start_time_s: float
    end_time_s: float
    support_definition: str
    source_series_digest: str
    includes_post_release_samples: bool = False

    def __post_init__(self) -> None:
        if self.support_id.instance_type != "support":
            raise ValueError("support_id must identify a support")
        if self.metric not in {
            BPT_SAMPLED_MAXIMUM_BAR_VELOCITY_METRIC,
            BPT_DYNAMISLM_TIME_WEIGHTED_MEAN_BAR_VELOCITY_METRIC,
        }:
            raise ValueError("BPT support must identify an implemented BPT metric")
        if type(self.start_index) is not int or type(self.end_index) is not int:
            raise ValueError("BPT support indices must be integers")
        if self.start_index < 0 or self.end_index < self.start_index:
            raise ValueError("BPT support must satisfy 0 <= start <= end")
        start = _finite(self.start_time_s, "support start time")
        end = _finite(self.end_time_s, "support end time")
        if end < start:
            raise ValueError("BPT support end time must not precede start time")
        object.__setattr__(self, "start_time_s", start)
        object.__setattr__(self, "end_time_s", end)
        _require_text(self.support_definition, "support_definition")
        _require_text(self.source_series_digest, "source_series_digest")
        if not isinstance(self.includes_post_release_samples, bool):
            raise ValueError("includes_post_release_samples must be a boolean")


# Short names are aliases to the same registered classes, not new wire types.
BPTProtocolIdentity = BenchPressThrowProtocolIdentity
BPTAcquisitionIdentity = BenchPressThrowAcquisitionIdentity
BPTProcessingIdentity = BenchPressThrowProcessingIdentity
BPTSemanticIdentity = BenchPressThrowSemanticIdentity
BPTMeasurementIdentity = BenchPressThrowMeasurementIdentity
BPTSourceArtifact = BenchPressThrowSourceArtifact
BPTAcquisitionRecord = BenchPressThrowAcquisitionRecord
BPTVelocitySeries = BenchPressThrowVelocitySeries
BPTMetricSupport = BenchPressThrowMetricSupport


__all__ = [
    "BPTAcquisitionIdentity",
    "BPTAcquisitionRecord",
    "BPTArtifactHashScope",
    "BPTArtifactStatus",
    "BPTCatchSemantics",
    "BPTCounterbalanceStatus",
    "BPTHashAlgorithm",
    "BPTLoadIdentity",
    "BPTLoadKind",
    "BPTMachineType",
    "BPTMeasurementIdentity",
    "BPTMetricSupport",
    "BPTMovementPattern",
    "BPTPauseTouchBounce",
    "BPTProcessingIdentity",
    "BPTProcessingState",
    "BPTProtocolIdentity",
    "BPTQualificationStatus",
    "BPTReleaseSemantics",
    "BPTSemanticIdentity",
    "BPTSensorModality",
    "BPTSourceArtifact",
    "BPTTimebase",
    "BPTTimebaseKind",
    "BPTVelocitySeries",
    "BenchPressThrowAcquisitionIdentity",
    "BenchPressThrowAcquisitionRecord",
    "BenchPressThrowMeasurementIdentity",
    "BenchPressThrowMetricSupport",
    "BenchPressThrowProcessingIdentity",
    "BenchPressThrowProtocolIdentity",
    "BenchPressThrowSemanticIdentity",
    "BenchPressThrowSourceArtifact",
    "BenchPressThrowVelocitySeries",
]
