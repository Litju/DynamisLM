"""Shared, unknown-preserving identity contracts for the strength vertical.

The strength vertical has its own identities.  A force-platform IMTP series
and a barbell velocity series have different measurands, systems, phase
semantics, and scientific limits even when their human-facing labels appear
similar.
"""

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
    SignConvention,
    UnitReference,
    _require_enum,
    _require_instance,
    _require_optional_instance,
    _require_text,
    _require_tuple_items,
    require_tuple,
)
from dynamislm.provenance.models import SourceArtifact
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


class StrengthTestFamily(StrEnum):
    IMTP = "IMTP"
    SQUAT_VBT = "SQUAT_VBT"
    BENCH_PRESS_VBT = "BENCH_PRESS_VBT"


class StrengthEquipmentMode(StrEnum):
    FREE_WEIGHT = "FREE_WEIGHT"
    SMITH_MACHINE = "SMITH_MACHINE"
    FIXED_RIG = "FIXED_RIG"
    OTHER_REGISTERED = "OTHER_REGISTERED"
    UNKNOWN = "UNKNOWN"


class StrengthSensorModality(StrEnum):
    FORCE_PLATFORM = "FORCE_PLATFORM"
    LOAD_CELL = "LOAD_CELL"
    LINEAR_POSITION_TRANSDUCER = "LINEAR_POSITION_TRANSDUCER"
    MOTION_CAPTURE = "MOTION_CAPTURE"
    INERTIAL = "INERTIAL"
    SOURCE_REPORTED = "SOURCE_REPORTED"
    OTHER_REGISTERED = "OTHER_REGISTERED"
    UNKNOWN = "UNKNOWN"


class StrengthProcessingState(StrEnum):
    RAW_ACQUIRED = "RAW_ACQUIRED"
    DEVICE_PROCESSED = "DEVICE_PROCESSED"
    PROVIDER_PROCESSED = "PROVIDER_PROCESSED"
    DYNAMISLM_PROCESSED = "DYNAMISLM_PROCESSED"
    UNKNOWN = "UNKNOWN"


class StrengthProcessingComponentStatus(StrEnum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    REGISTERED = "REGISTERED"
    NONE_DECLARED = "NONE_DECLARED"
    UNKNOWN = "UNKNOWN"


class StrengthLoadSemantics(StrEnum):
    ADDED_EXTERNAL_LOAD = "ADDED_EXTERNAL_LOAD"
    TOTAL_EXTERNAL_LOAD = "TOTAL_EXTERNAL_LOAD"
    PERCENT_ONE_RM = "PERCENT_ONE_RM"
    UNKNOWN = "UNKNOWN"


class StrengthImplementType(StrEnum):
    BARBELL = "BARBELL"
    SMITH_MACHINE_BAR = "SMITH_MACHINE_BAR"
    FIXED_RIG = "FIXED_RIG"
    BODY_ONLY = "BODY_ONLY"
    OTHER_REGISTERED = "OTHER_REGISTERED"
    UNKNOWN = "UNKNOWN"


class StrengthExternalLoadStatus(StrEnum):
    NONE = "NONE"
    DEFINED = "DEFINED"
    UNKNOWN = "UNKNOWN"


class StrengthTimebaseKind(StrEnum):
    REGULAR = "REGULAR"
    EXPLICIT = "EXPLICIT"


def _family_key(family: StrengthTestFamily) -> str:
    return {
        StrengthTestFamily.IMTP: "imtp",
        StrengthTestFamily.SQUAT_VBT: "squat-vbt",
        StrengthTestFamily.BENCH_PRESS_VBT: "bench-press-vbt",
    }[family]


@register_serializable_type
@dataclass(frozen=True, slots=True)
class StrengthTimebase:
    """Regular or explicit timestamps for one strength source series."""

    kind: StrengthTimebaseKind
    sample_rate_hz: float | None = None
    start_time_s: float = 0.0
    times_s: tuple[float, ...] = ()

    def __post_init__(self) -> None:
        _require_enum(self.kind, StrengthTimebaseKind, "kind")
        if self.sample_rate_hz is not None:
            object.__setattr__(
                self, "sample_rate_hz", _finite(self.sample_rate_hz, "sample_rate_hz")
            )
            if self.sample_rate_hz <= 0:
                raise ValueError("sample_rate_hz must be positive")
        object.__setattr__(self, "start_time_s", _finite(self.start_time_s, "start_time_s"))
        require_tuple(self.times_s, "times_s")
        if self.kind is StrengthTimebaseKind.REGULAR:
            if self.sample_rate_hz is None:
                raise ValueError("regular timebase requires sample_rate_hz")
            if self.times_s:
                raise ValueError("regular timebase must not carry explicit times")
        else:
            if not self.times_s:
                raise ValueError("explicit timebase requires times_s")
            if any(not math.isfinite(float(value)) for value in self.times_s):
                raise ValueError("explicit times_s must be finite")
            normalized = tuple(float(value) for value in self.times_s)
            if any(right <= left for left, right in pairwise(normalized)):
                raise ValueError("explicit times_s must be strictly increasing")
            object.__setattr__(self, "times_s", normalized)

    def time_at(self, index: int) -> float:
        if isinstance(index, bool) or not isinstance(index, int) or index < 0:
            raise ValueError("timebase sample index must be a non-negative integer")
        if self.kind is StrengthTimebaseKind.REGULAR:
            if self.sample_rate_hz is None:
                raise ValueError("regular timebase has no sample rate")
            return self.start_time_s + index / self.sample_rate_hz
        if index >= len(self.times_s):
            raise IndexError("sample index is outside explicit timebase")
        return self.times_s[index]


@register_serializable_type
@dataclass(frozen=True, slots=True)
class StrengthProtocolAttribute:
    """One explicit protocol field; omitted fields stay unresolved."""

    name: str
    value: str | int | float | bool | None
    unit: UnitReference | None = None

    def __post_init__(self) -> None:
        _require_text(self.name, "name")
        if not isinstance(self.value, str | int | float | bool) and self.value is not None:
            raise ValueError("protocol attribute value must be scalar")
        if isinstance(self.value, float) and not math.isfinite(self.value):
            raise ValueError("protocol attribute value must be finite")
        _require_optional_instance(self.unit, UnitReference, "unit")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class StrengthLoadIdentity:
    """Physical or explicitly percentage-based external-load identity."""

    value: float
    unit: UnitReference
    implement_type: StrengthImplementType = StrengthImplementType.UNKNOWN
    semantics: StrengthLoadSemantics = StrengthLoadSemantics.UNKNOWN
    bar_mass_kg: float | None = None
    added_load_kg: float | None = None
    total_external_load_kg: float | None = None
    percentage_1rm: float | None = None
    source_reference: RegistryReference | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", _finite(self.value, "load value"))
        if self.value < 0:
            raise ValueError("load value must be non-negative")
        _require_instance(self.unit, UnitReference, "unit")
        _require_enum(self.implement_type, StrengthImplementType, "implement_type")
        _require_enum(self.semantics, StrengthLoadSemantics, "semantics")
        for name in ("bar_mass_kg", "added_load_kg", "total_external_load_kg", "percentage_1rm"):
            value = _finite_optional(getattr(self, name), name)
            if value is not None and value < 0:
                raise ValueError(f"{name} must be non-negative")
            object.__setattr__(self, name, value)
        _require_optional_instance(self.source_reference, RegistryReference, "source_reference")
        if self.semantics is StrengthLoadSemantics.PERCENT_ONE_RM and self.percentage_1rm is None:
            raise ValueError("percentage load semantics requires percentage_1rm")

    @property
    def is_physical_load(self) -> bool:
        return self.semantics in {
            StrengthLoadSemantics.ADDED_EXTERNAL_LOAD,
            StrengthLoadSemantics.TOTAL_EXTERNAL_LOAD,
        }


@register_serializable_type
@dataclass(frozen=True, slots=True)
class StrengthProcessingStep:
    """A filtering, smoothing, or resampling component with explicit status."""

    status: StrengthProcessingComponentStatus = StrengthProcessingComponentStatus.UNKNOWN
    method: RegistryReference | None = None
    parameters: tuple[MetadataEntry, ...] = ()

    def __post_init__(self) -> None:
        _require_enum(self.status, StrengthProcessingComponentStatus, "status")
        _require_optional_instance(self.method, RegistryReference, "method")
        _require_tuple_items(self.parameters, MetadataEntry, "parameters")
        if self.status in {
            StrengthProcessingComponentStatus.NOT_APPLICABLE,
            StrengthProcessingComponentStatus.NONE_DECLARED,
        } and (self.method is not None or self.parameters):
            raise ValueError("a non-applicable/none processing step cannot carry a method")
        if self.status is StrengthProcessingComponentStatus.REGISTERED and self.method is None:
            raise ValueError("a registered processing step must identify a method")


@register_serializable_type
@dataclass(frozen=True, slots=True, kw_only=True)
class StrengthProtocolIdentity:
    """Material protocol and acquisition-facing fields for IMTP/VBT."""

    reference: RegistryReference | None
    test_family: StrengthTestFamily
    exercise: RegistryReference
    exercise_variant: RegistryReference | None = None
    equipment: RegistryReference | None = None
    equipment_mode: StrengthEquipmentMode = StrengthEquipmentMode.UNKNOWN
    range_of_motion: StrengthProtocolAttribute | None = None
    joint_posture: StrengthProtocolAttribute | None = None
    bar_position: StrengthProtocolAttribute | None = None
    grip: StrengthProtocolAttribute | None = None
    stance: StrengthProtocolAttribute | None = None
    pause_semantics: StrengthProtocolAttribute | None = None
    external_load_status: StrengthExternalLoadStatus = StrengthExternalLoadStatus.UNKNOWN
    external_load: StrengthLoadIdentity | None = None
    supported_external_load_identity: RegistryReference | None = None
    device_or_system: RegistryReference | None = None
    provider: str | None = None
    sensor_modality: StrengthSensorModality = StrengthSensorModality.UNKNOWN
    attachment_location: str | None = None
    sampling: SamplingCharacteristics | None = None
    timebase: StrengthTimebase | None = None
    filtering: tuple[RegistryReference, ...] = ()
    filtering_status: StrengthProcessingComponentStatus = StrengthProcessingComponentStatus.UNKNOWN
    smoothing: StrengthProcessingStep = StrengthProcessingStep()
    resampling: StrengthProcessingStep = StrengthProcessingStep()
    software_version: str | None = None
    firmware_version: str | None = None
    rep_selection_rule: RegistryReference | None = None
    trial_selection_rule: RegistryReference | None = None
    additional_attributes: tuple[StrengthProtocolAttribute, ...] = ()

    def __post_init__(self) -> None:
        _require_optional_instance(self.reference, RegistryReference, "reference")
        if self.reference is not None and self.reference.identifier.object_type != "protocol":
            raise ValueError("strength protocol reference must have object_type 'protocol'")
        _require_enum(self.test_family, StrengthTestFamily, "test_family")
        _require_instance(self.exercise, RegistryReference, "exercise")
        for name, value in (
            ("exercise_variant", self.exercise_variant),
            ("equipment", self.equipment),
            ("device_or_system", self.device_or_system),
            ("supported_external_load_identity", self.supported_external_load_identity),
            ("rep_selection_rule", self.rep_selection_rule),
            ("trial_selection_rule", self.trial_selection_rule),
        ):
            _require_optional_instance(value, RegistryReference, name)
        _require_enum(self.equipment_mode, StrengthEquipmentMode, "equipment_mode")
        for name in (
            "range_of_motion",
            "joint_posture",
            "bar_position",
            "grip",
            "stance",
            "pause_semantics",
        ):
            _require_optional_instance(getattr(self, name), StrengthProtocolAttribute, name)
        _require_enum(self.external_load_status, StrengthExternalLoadStatus, "external_load_status")
        _require_optional_instance(self.external_load, StrengthLoadIdentity, "external_load")
        if (
            self.external_load_status is StrengthExternalLoadStatus.NONE
            and self.external_load is not None
        ):
            raise ValueError("NONE external-load status cannot carry a load")
        if (
            self.external_load_status is StrengthExternalLoadStatus.DEFINED
            and self.external_load is None
        ):
            raise ValueError("DEFINED external-load status requires a load")
        if self.provider is not None:
            _require_text(self.provider, "provider")
        _require_enum(self.sensor_modality, StrengthSensorModality, "sensor_modality")
        if self.attachment_location is not None:
            _require_text(self.attachment_location, "attachment_location")
        _require_optional_instance(self.sampling, SamplingCharacteristics, "sampling")
        _require_optional_instance(self.timebase, StrengthTimebase, "timebase")
        _require_tuple_items(self.filtering, RegistryReference, "filtering")
        _require_enum(self.filtering_status, StrengthProcessingComponentStatus, "filtering_status")
        if (
            self.filtering_status is StrengthProcessingComponentStatus.REGISTERED
            and not self.filtering
        ):
            raise ValueError("registered protocol filtering requires methods")
        if (
            self.filtering_status
            in {
                StrengthProcessingComponentStatus.NONE_DECLARED,
                StrengthProcessingComponentStatus.NOT_APPLICABLE,
            }
            and self.filtering
        ):
            raise ValueError("none/not-applicable protocol filtering cannot carry methods")
        _require_instance(self.smoothing, StrengthProcessingStep, "smoothing")
        _require_instance(self.resampling, StrengthProcessingStep, "resampling")
        for name, text_value in (
            ("software_version", self.software_version),
            ("firmware_version", self.firmware_version),
        ):
            if text_value is not None:
                _require_text(text_value, name)
        _require_tuple_items(
            self.additional_attributes, StrengthProtocolAttribute, "additional_attributes"
        )


@register_serializable_type
@dataclass(frozen=True, slots=True, kw_only=True)
class StrengthAcquisitionIdentity(AcquisitionIdentity):
    """Device, modality, attachment, timebase, and source processing state."""

    provider: str | None = None
    acquisition_instance_id: InstanceIdentifier | None = None
    sensor_modality: StrengthSensorModality = StrengthSensorModality.UNKNOWN
    attachment_location: str | None = None
    timebase: StrengthTimebase | None = None
    unit: UnitReference | None = None
    physical_axis: RegistryReference | None = None
    reference_frame: RegistryReference | None = None
    sign_convention: SignConvention | None = None
    processing_state: StrengthProcessingState = StrengthProcessingState.UNKNOWN

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
        _require_enum(self.sensor_modality, StrengthSensorModality, "sensor_modality")
        if self.attachment_location is not None:
            _require_text(self.attachment_location, "attachment_location")
        _require_optional_instance(self.timebase, StrengthTimebase, "timebase")
        _require_optional_instance(self.unit, UnitReference, "unit")
        _require_optional_instance(self.physical_axis, RegistryReference, "physical_axis")
        _require_optional_instance(self.reference_frame, RegistryReference, "reference_frame")
        _require_optional_instance(self.sign_convention, SignConvention, "sign_convention")
        _require_enum(self.processing_state, StrengthProcessingState, "processing_state")


@register_serializable_type
@dataclass(frozen=True, slots=True, kw_only=True)
class StrengthProcessingIdentity(ProcessingIdentity):
    """Processing identity with explicit unknown/registered component states."""

    filtering_status: StrengthProcessingComponentStatus = StrengthProcessingComponentStatus.UNKNOWN
    smoothing: StrengthProcessingStep = StrengthProcessingStep()
    resampling: StrengthProcessingStep = StrengthProcessingStep()
    processing_state: StrengthProcessingState = StrengthProcessingState.UNKNOWN

    def __post_init__(self) -> None:
        ProcessingIdentity.__post_init__(self)
        _require_enum(self.filtering_status, StrengthProcessingComponentStatus, "filtering_status")
        _require_instance(self.smoothing, StrengthProcessingStep, "smoothing")
        _require_instance(self.resampling, StrengthProcessingStep, "resampling")
        _require_enum(self.processing_state, StrengthProcessingState, "processing_state")
        if (
            self.filtering_status is StrengthProcessingComponentStatus.REGISTERED
            and not self.filtering
        ):
            raise ValueError("registered filtering requires at least one method")
        if (
            self.filtering_status
            in {
                StrengthProcessingComponentStatus.NONE_DECLARED,
                StrengthProcessingComponentStatus.NOT_APPLICABLE,
            }
            and self.filtering
        ):
            raise ValueError("none/not-applicable filtering cannot carry methods")


@register_serializable_type
@dataclass(frozen=True, slots=True, kw_only=True)
class StrengthSemanticIdentity(SemanticIdentity):
    """Generic semantic identity carrying the full strength protocol object."""

    protocol_identity: StrengthProtocolIdentity | None = None

    def __post_init__(self) -> None:
        SemanticIdentity.__post_init__(self)
        _require_optional_instance(
            self.protocol_identity, StrengthProtocolIdentity, "protocol_identity"
        )
        if self.protocol_identity is not None:
            if self.test_family.identifier.key != _family_key(self.protocol_identity.test_family):
                raise ValueError("strength protocol family does not match semantic test family")
            if self.protocol is not None and self.protocol != self.protocol_identity.reference:
                raise ValueError("protocol and protocol_identity references must agree")
            if self.protocol is None and self.protocol_identity.reference is not None:
                raise ValueError(
                    "protocol reference is required when protocol_identity is registered"
                )


@register_serializable_type
@dataclass(frozen=True, slots=True, kw_only=True)
class StrengthMeasurementIdentity(MeasurementIdentity):
    """Base identity for an IMTP or squat/bench VBT observation."""

    semantic: StrengthSemanticIdentity
    acquisition: StrengthAcquisitionIdentity
    processing: StrengthProcessingIdentity

    def __post_init__(self) -> None:
        MeasurementIdentity.__post_init__(self)
        _require_instance(self.semantic, StrengthSemanticIdentity, "semantic")
        _require_instance(self.acquisition, StrengthAcquisitionIdentity, "acquisition")
        _require_instance(self.processing, StrengthProcessingIdentity, "processing")
        protocol = self.semantic.protocol_identity
        if protocol is not None and self.semantic.test_family.identifier.key != _family_key(
            protocol.test_family
        ):
            raise ValueError("strength protocol family does not match semantic test family")


@register_serializable_type
@dataclass(frozen=True, slots=True, kw_only=True)
class IMTPMeasurementIdentity(StrengthMeasurementIdentity):
    """IMTP-specific strength identity."""

    def __post_init__(self) -> None:
        StrengthMeasurementIdentity.__post_init__(self)
        if (
            self.semantic.protocol_identity is not None
            and self.semantic.protocol_identity.test_family is not StrengthTestFamily.IMTP
        ):
            raise ValueError("IMTP identity requires an IMTP protocol")


@register_serializable_type
@dataclass(frozen=True, slots=True, kw_only=True)
class VBTMeasurementIdentity(StrengthMeasurementIdentity):
    """Squat or bench-press VBT identity."""

    def __post_init__(self) -> None:
        StrengthMeasurementIdentity.__post_init__(self)
        if (
            self.semantic.protocol_identity is not None
            and self.semantic.protocol_identity.test_family
            not in {
                StrengthTestFamily.SQUAT_VBT,
                StrengthTestFamily.BENCH_PRESS_VBT,
            }
        ):
            raise ValueError("VBT identity requires a squat or bench-press VBT protocol")


class StrengthHashAlgorithm(StrEnum):
    SHA256 = "sha256"


class StrengthArtifactHashScope(StrEnum):
    CANONICAL_SERIES_REPRESENTATION = "CANONICAL_SERIES_REPRESENTATION"
    CONTENT_BYTES = "CONTENT_BYTES"


class StrengthArtifactStatus(StrEnum):
    VERIFIED = "VERIFIED"
    UNVERIFIED = "UNVERIFIED"


@register_serializable_type
@dataclass(frozen=True, slots=True, kw_only=True)
class StrengthSourceArtifact(SourceArtifact):
    """Content-addressed source artifact for force or velocity series."""

    hash_algorithm: StrengthHashAlgorithm
    hash_scope: StrengthArtifactHashScope
    status: StrengthArtifactStatus

    def __post_init__(self) -> None:
        SourceArtifact.__post_init__(self)
        _require_enum(self.hash_algorithm, StrengthHashAlgorithm, "hash_algorithm")
        _require_enum(self.hash_scope, StrengthArtifactHashScope, "hash_scope")
        _require_enum(self.status, StrengthArtifactStatus, "status")


def time_at(timebase: StrengthTimebase, index: int) -> float:
    """Return the exact registered time for a sample index."""

    return timebase.time_at(index)


def validate_series_timebase(timebase: StrengthTimebase, sample_count: int) -> None:
    if isinstance(sample_count, bool) or not isinstance(sample_count, int) or sample_count < 1:
        raise ValueError("sample_count must be a positive integer")
    if timebase.kind is StrengthTimebaseKind.EXPLICIT and len(timebase.times_s) != sample_count:
        raise ValueError("explicit timebase length must equal sample count")
    if timebase.kind is StrengthTimebaseKind.REGULAR:
        timebase.time_at(sample_count - 1)


def canonical_series_digest(
    samples: tuple[float, ...],
    timebase: StrengthTimebase,
    *,
    unit: UnitReference | None = None,
) -> str:
    """Digest the exact delivered series, including its timebase and unit."""

    return canonical_hash({"samples": samples, "timebase": timebase, "unit": unit})


__all__ = [
    "IMTPMeasurementIdentity",
    "StrengthAcquisitionIdentity",
    "StrengthArtifactHashScope",
    "StrengthArtifactStatus",
    "StrengthEquipmentMode",
    "StrengthExternalLoadStatus",
    "StrengthHashAlgorithm",
    "StrengthImplementType",
    "StrengthLoadIdentity",
    "StrengthLoadSemantics",
    "StrengthMeasurementIdentity",
    "StrengthProcessingComponentStatus",
    "StrengthProcessingIdentity",
    "StrengthProcessingState",
    "StrengthProcessingStep",
    "StrengthProtocolAttribute",
    "StrengthProtocolIdentity",
    "StrengthSemanticIdentity",
    "StrengthSensorModality",
    "StrengthSourceArtifact",
    "StrengthTestFamily",
    "StrengthTimebase",
    "StrengthTimebaseKind",
    "VBTMeasurementIdentity",
    "canonical_series_digest",
    "time_at",
    "validate_series_timebase",
]
