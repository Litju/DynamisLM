"""Typed medicine-ball throw protocol, distance and release-event identities."""

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
    _require_enum,
    _require_instance,
    _require_optional_instance,
    _require_text,
    _require_tuple_items,
    require_tuple,
)
from dynamislm.measurement.medicine_ball_throw.registry import (
    MEDICINE_BALL_THROW_PROTOCOL_V1,
    MEDICINE_BALL_THROW_TEST_FAMILY,
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


class MBTThrowVariant(StrEnum):
    SEATED_CHEST = "SEATED_CHEST"
    STANDING_CHEST = "STANDING_CHEST"
    BACKWARD_OVERHEAD = "BACKWARD_OVERHEAD"
    ROTATIONAL = "ROTATIONAL"
    SUPINE = "SUPINE"
    MEDICINE_BALL_PUSH_PRESS = "MEDICINE_BALL_PUSH_PRESS"
    OTHER_REGISTERED = "OTHER_REGISTERED"
    UNKNOWN = "UNKNOWN"


class MBTBodyPosture(StrEnum):
    SEATED = "SEATED"
    STANDING = "STANDING"
    SUPINE = "SUPINE"
    KNEELING = "KNEELING"
    OTHER_REGISTERED = "OTHER_REGISTERED"
    UNKNOWN = "UNKNOWN"


class MBTSupportCondition(StrEnum):
    BACK_SUPPORTED = "BACK_SUPPORTED"
    FEET_RESTRAINED = "FEET_RESTRAINED"
    FREE_STANDING = "FREE_STANDING"
    OTHER_REGISTERED = "OTHER_REGISTERED"
    UNKNOWN = "UNKNOWN"


class MBTAllowedState(StrEnum):
    ALLOWED = "ALLOWED"
    PROHIBITED = "PROHIBITED"
    UNKNOWN = "UNKNOWN"


class MBTReleaseSemantics(StrEnum):
    EXPLICIT_RELEASE_EVENT = "EXPLICIT_RELEASE_EVENT"
    SOURCE_REPORTED_RELEASE = "SOURCE_REPORTED_RELEASE"
    UNKNOWN = "UNKNOWN"


class MBTSensorModality(StrEnum):
    MANUAL_DISTANCE = "MANUAL_DISTANCE"
    MEASURING_TAPE = "MEASURING_TAPE"
    OPTICAL = "OPTICAL"
    RADAR = "RADAR"
    LOCAL_POSITIONING = "LOCAL_POSITIONING"
    IMU = "IMU"
    OTHER_REGISTERED = "OTHER_REGISTERED"
    UNKNOWN = "UNKNOWN"


class MBTTimebaseKind(StrEnum):
    REGULAR = "REGULAR"
    EXPLICIT = "EXPLICIT"


class MBTProcessingState(StrEnum):
    RAW_ACQUIRED = "RAW_ACQUIRED"
    DEVICE_PROCESSED = "DEVICE_PROCESSED"
    PROVIDER_PROCESSED = "PROVIDER_PROCESSED"
    DYNAMISLM_PROCESSED = "DYNAMISLM_PROCESSED"
    UNKNOWN = "UNKNOWN"


class MBTArtifactStatus(StrEnum):
    VERIFIED = "VERIFIED"
    UNVERIFIED = "UNVERIFIED"


class MBTHashAlgorithm(StrEnum):
    SHA256 = "sha256"


class MBTArtifactHashScope(StrEnum):
    CONTENT_BYTES = "CONTENT_BYTES"
    CANONICAL_SERIES_REPRESENTATION = "CANONICAL_SERIES_REPRESENTATION"


class MBTQualificationStatus(StrEnum):
    QUALIFIED = "QUALIFIED"
    REJECTED = "REJECTED"
    UNKNOWN = "UNKNOWN"


@register_serializable_type
@dataclass(frozen=True, slots=True)
class MBTTimebase:
    kind: MBTTimebaseKind
    sample_rate_hz: float | None = None
    start_time_s: float = 0.0
    times_s: tuple[float, ...] = ()

    def __post_init__(self) -> None:
        _require_enum(self.kind, MBTTimebaseKind, "kind")
        rate = _finite_optional(self.sample_rate_hz, "sample_rate_hz")
        if rate is not None and rate <= 0:
            raise ValueError("sample_rate_hz must be positive")
        object.__setattr__(self, "sample_rate_hz", rate)
        object.__setattr__(self, "start_time_s", _finite(self.start_time_s, "start_time_s"))
        require_tuple(self.times_s, "times_s")
        if self.kind is MBTTimebaseKind.REGULAR:
            if rate is None:
                raise ValueError("regular timebase requires sample_rate_hz")
            if self.times_s:
                raise ValueError("regular timebase must not carry explicit timestamps")
        else:
            if not self.times_s:
                raise ValueError("explicit timebase requires timestamps")
            normalized = tuple(_finite(value, "times_s item") for value in self.times_s)
            if any(right <= left for left, right in pairwise(normalized)):
                raise ValueError("explicit timestamps must be strictly increasing")
            object.__setattr__(self, "times_s", normalized)

    def time_at(self, index: int) -> float:
        if type(index) is not int or index < 0:
            raise ValueError("MBT sample index must be a non-negative integer")
        if self.kind is MBTTimebaseKind.REGULAR:
            assert self.sample_rate_hz is not None
            return self.start_time_s + index / self.sample_rate_hz
        if index >= len(self.times_s):
            raise IndexError("MBT sample index is outside explicit timebase")
        return self.times_s[index]


@register_serializable_type
@dataclass(frozen=True, slots=True)
class MedicineBallThrowProtocolIdentity:
    """Exact MBT variant, posture, ball and distance convention identity."""

    reference: RegistryReference = MEDICINE_BALL_THROW_PROTOCOL_V1
    protocol_version: str = "1.0.0"
    throw_type: MBTThrowVariant = MBTThrowVariant.UNKNOWN
    body_posture: MBTBodyPosture = MBTBodyPosture.UNKNOWN
    support_restraint_condition: MBTSupportCondition = MBTSupportCondition.UNKNOWN
    ball_mass_kg: float | None = None
    countermovement: MBTAllowedState = MBTAllowedState.UNKNOWN
    lower_body_contribution: MBTAllowedState = MBTAllowedState.UNKNOWN
    throw_arm_technique: str | None = None
    starting_position: str | None = None
    release_semantics: MBTReleaseSemantics = MBTReleaseSemantics.UNKNOWN
    measurement_method: RegistryReference | None = None
    distance_origin_convention: RegistryReference | None = None
    distance_endpoint_convention: RegistryReference | None = None
    first_contact_no_roll_convention: RegistryReference | None = None
    provider: str | None = None
    device: RegistryReference | None = None
    sensor_modality: MBTSensorModality = MBTSensorModality.UNKNOWN
    sampling: SamplingCharacteristics | None = None
    timebase: MBTTimebase | None = None
    filtering: tuple[RegistryReference, ...] | None = None
    smoothing: RegistryReference | None = None
    resampling: RegistryReference | None = None
    software: str | None = None
    firmware: str | None = None
    trial_qualification: RegistryReference | None = None
    trial_selection: RegistryReference | None = None
    additional_attributes: tuple[MetadataEntry, ...] = ()

    def __post_init__(self) -> None:
        _require_instance(self.reference, RegistryReference, "reference")
        if self.reference.identifier.object_type != "protocol":
            raise ValueError("MBT protocol reference must identify a protocol")
        _require_text(self.protocol_version, "protocol_version")
        for name, value, expected in (
            ("throw_type", self.throw_type, MBTThrowVariant),
            ("body_posture", self.body_posture, MBTBodyPosture),
            ("support_restraint_condition", self.support_restraint_condition, MBTSupportCondition),
            ("countermovement", self.countermovement, MBTAllowedState),
            ("lower_body_contribution", self.lower_body_contribution, MBTAllowedState),
            ("release_semantics", self.release_semantics, MBTReleaseSemantics),
            ("sensor_modality", self.sensor_modality, MBTSensorModality),
        ):
            _require_enum(value, expected, name)
        mass = _finite_optional(self.ball_mass_kg, "ball_mass_kg")
        if mass is not None and mass <= 0:
            raise ValueError("ball_mass_kg must be positive")
        object.__setattr__(self, "ball_mass_kg", mass)
        for name in (
            "throw_arm_technique",
            "starting_position",
            "provider",
            "software",
            "firmware",
        ):
            text_value: object = getattr(self, name)
            if text_value is not None:
                assert isinstance(text_value, str)
                _require_text(text_value, name)
        for name in (
            "measurement_method",
            "distance_origin_convention",
            "distance_endpoint_convention",
            "first_contact_no_roll_convention",
            "device",
            "smoothing",
            "resampling",
            "trial_qualification",
            "trial_selection",
        ):
            _require_optional_instance(getattr(self, name), RegistryReference, name)
        _require_optional_instance(self.sampling, SamplingCharacteristics, "sampling")
        _require_optional_instance(self.timebase, MBTTimebase, "timebase")
        if self.filtering is not None:
            _require_tuple_items(self.filtering, RegistryReference, "filtering")
        _require_tuple_items(self.additional_attributes, MetadataEntry, "additional_attributes")

    @property
    def test_family(self) -> RegistryReference:
        return MEDICINE_BALL_THROW_TEST_FAMILY


@register_serializable_type
@dataclass(frozen=True, slots=True, kw_only=True)
class MedicineBallThrowAcquisitionIdentity(AcquisitionIdentity):
    provider: str | None = None
    sensor_modality: MBTSensorModality = MBTSensorModality.UNKNOWN
    timebase: MBTTimebase | None = None
    axis_or_frame: RegistryReference | None = None
    acquisition_instance_id: InstanceIdentifier | None = None
    source_series_digest: str | None = None

    def __post_init__(self) -> None:
        AcquisitionIdentity.__post_init__(self)
        if self.provider is not None:
            _require_text(self.provider, "provider")
        _require_enum(self.sensor_modality, MBTSensorModality, "sensor_modality")
        _require_optional_instance(self.timebase, MBTTimebase, "timebase")
        _require_optional_instance(self.axis_or_frame, RegistryReference, "axis_or_frame")
        _require_optional_instance(
            self.acquisition_instance_id, InstanceIdentifier, "acquisition_instance_id"
        )
        if (
            self.acquisition_instance_id is not None
            and self.acquisition_instance_id.instance_type != "acquisition"
        ):
            raise ValueError("acquisition_instance_id must identify an acquisition")
        if self.source_series_digest is not None:
            _require_text(self.source_series_digest, "source_series_digest")


@register_serializable_type
@dataclass(frozen=True, slots=True, kw_only=True)
class MedicineBallThrowProcessingIdentity(ProcessingIdentity):
    timebase: MBTTimebase | None = None
    processing_state: MBTProcessingState = MBTProcessingState.UNKNOWN
    provider_algorithm: RegistryReference | None = None
    resampling: RegistryReference | None = None

    def __post_init__(self) -> None:
        ProcessingIdentity.__post_init__(self)
        _require_optional_instance(self.timebase, MBTTimebase, "timebase")
        _require_enum(self.processing_state, MBTProcessingState, "processing_state")
        _require_optional_instance(self.provider_algorithm, RegistryReference, "provider_algorithm")
        _require_optional_instance(self.resampling, RegistryReference, "resampling")


@register_serializable_type
@dataclass(frozen=True, slots=True, kw_only=True)
class MedicineBallThrowSemanticIdentity(SemanticIdentity):
    protocol_identity: MedicineBallThrowProtocolIdentity | None = None

    def __post_init__(self) -> None:
        SemanticIdentity.__post_init__(self)
        _require_instance(
            self.protocol_identity, MedicineBallThrowProtocolIdentity, "protocol_identity"
        )
        assert self.protocol_identity is not None
        if self.test_family != MEDICINE_BALL_THROW_TEST_FAMILY:
            raise ValueError("MBT semantic identity has the wrong test family")
        if self.protocol != self.protocol_identity.reference:
            raise ValueError("MBT protocol and protocol_identity references must agree")


@register_serializable_type
@dataclass(frozen=True, slots=True, kw_only=True)
class MedicineBallThrowMeasurementIdentity(MeasurementIdentity):
    semantic: MedicineBallThrowSemanticIdentity
    acquisition: MedicineBallThrowAcquisitionIdentity
    processing: MedicineBallThrowProcessingIdentity

    def __post_init__(self) -> None:
        MeasurementIdentity.__post_init__(self)
        _require_instance(self.semantic, MedicineBallThrowSemanticIdentity, "semantic")
        _require_instance(self.acquisition, MedicineBallThrowAcquisitionIdentity, "acquisition")
        _require_instance(self.processing, MedicineBallThrowProcessingIdentity, "processing")
        if self.semantic.test_family != MEDICINE_BALL_THROW_TEST_FAMILY:
            raise ValueError("MBT measurement identity has the wrong family")


@register_serializable_type
@dataclass(frozen=True, slots=True, kw_only=True)
class MedicineBallThrowSourceArtifact(SourceArtifact):
    status: MBTArtifactStatus = MBTArtifactStatus.UNVERIFIED
    hash_algorithm: MBTHashAlgorithm = MBTHashAlgorithm.SHA256
    hash_scope: MBTArtifactHashScope = MBTArtifactHashScope.CONTENT_BYTES

    def __post_init__(self) -> None:
        SourceArtifact.__post_init__(self)
        _require_enum(self.status, MBTArtifactStatus, "status")
        _require_enum(self.hash_algorithm, MBTHashAlgorithm, "hash_algorithm")
        _require_enum(self.hash_scope, MBTArtifactHashScope, "hash_scope")


@register_serializable_type
@dataclass(frozen=True, slots=True, kw_only=True)
class MedicineBallThrowAcquisitionRecord(AcquisitionRecord):
    provider: str | None = None
    sensor_modality: MBTSensorModality = MBTSensorModality.UNKNOWN
    timebase: MBTTimebase | None = None
    axis_or_frame: RegistryReference | None = None

    def __post_init__(self) -> None:
        AcquisitionRecord.__post_init__(self)
        if self.provider is not None:
            _require_text(self.provider, "provider")
        _require_enum(self.sensor_modality, MBTSensorModality, "sensor_modality")
        _require_optional_instance(self.timebase, MBTTimebase, "timebase")
        _require_optional_instance(self.axis_or_frame, RegistryReference, "axis_or_frame")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class MBTCoordinateEvidence:
    """Exact coordinate endpoints for one protocol-defined throw distance."""

    source_observation_id: InstanceIdentifier
    origin_coordinate_m: float
    endpoint_coordinate_m: float
    coordinate_frame: RegistryReference
    origin_convention: RegistryReference
    endpoint_convention: RegistryReference
    first_contact_no_roll_convention: RegistryReference
    first_contact_observed: bool
    no_roll_observed: bool
    source_artifact_id: InstanceIdentifier
    acquisition_id: InstanceIdentifier

    def __post_init__(self) -> None:
        for name, value, expected in (
            ("source_observation_id", self.source_observation_id, "observation"),
            ("source_artifact_id", self.source_artifact_id, "artifact"),
            ("acquisition_id", self.acquisition_id, "acquisition"),
        ):
            _require_instance(value, InstanceIdentifier, name)
            if value.instance_type != expected:
                raise ValueError(f"{name} must identify a {expected}")
        for name in (
            "coordinate_frame",
            "origin_convention",
            "endpoint_convention",
            "first_contact_no_roll_convention",
        ):
            _require_instance(getattr(self, name), RegistryReference, name)
        origin = _finite(self.origin_coordinate_m, "origin_coordinate_m")
        endpoint = _finite(self.endpoint_coordinate_m, "endpoint_coordinate_m")
        if endpoint < origin:
            raise ValueError("MBT endpoint coordinate must not precede origin coordinate")
        object.__setattr__(self, "origin_coordinate_m", origin)
        object.__setattr__(self, "endpoint_coordinate_m", endpoint)
        if not isinstance(self.first_contact_observed, bool) or not isinstance(
            self.no_roll_observed, bool
        ):
            raise ValueError("MBT contact/no-roll observations must be booleans")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class MBTReleaseEvent:
    """Explicit release event bound to an instrumented source trajectory."""

    event_id: InstanceIdentifier
    source_observation_id: InstanceIdentifier
    source_series_id: InstanceIdentifier
    source_artifact_id: InstanceIdentifier
    acquisition_id: InstanceIdentifier
    sample_index: int
    event_time_s: float
    release_method: RegistryReference
    coordinate_frame: RegistryReference
    source_series_digest: str

    def __post_init__(self) -> None:
        for name, value, expected in (
            ("event_id", self.event_id, "event-occurrence"),
            ("source_observation_id", self.source_observation_id, "observation"),
            ("source_series_id", self.source_series_id, "signal"),
            ("source_artifact_id", self.source_artifact_id, "artifact"),
            ("acquisition_id", self.acquisition_id, "acquisition"),
        ):
            _require_instance(value, InstanceIdentifier, name)
            if value.instance_type != expected:
                raise ValueError(f"{name} must identify a {expected}")
        if type(self.sample_index) is not int or self.sample_index < 0:
            raise ValueError("MBT release sample index must be non-negative")
        _finite(self.event_time_s, "event_time_s")
        _require_instance(self.release_method, RegistryReference, "release_method")
        _require_instance(self.coordinate_frame, RegistryReference, "coordinate_frame")
        _require_text(self.source_series_digest, "source_series_digest")


def canonical_mbt_trajectory_digest(
    samples: tuple[tuple[float, float], ...],
    timebase: MBTTimebase,
    coordinate_frame: RegistryReference,
) -> str:
    require_tuple(samples, "samples")
    normalized = tuple(
        (_finite(item[0], "sample time"), _finite(item[1], "sample coordinate")) for item in samples
    )
    if any(right[0] <= left[0] for left, right in pairwise(normalized)):
        raise ValueError("MBT trajectory timestamps must increase")
    return canonical_hash(
        {"samples": normalized, "timebase": timebase, "coordinate_frame": coordinate_frame}
    )


# Short aliases preserve one serialization identity per class.
MBTProtocolIdentity = MedicineBallThrowProtocolIdentity
MBTAcquisitionIdentity = MedicineBallThrowAcquisitionIdentity
MBTProcessingIdentity = MedicineBallThrowProcessingIdentity
MBTSemanticIdentity = MedicineBallThrowSemanticIdentity
MBTMeasurementIdentity = MedicineBallThrowMeasurementIdentity
MBTSourceArtifact = MedicineBallThrowSourceArtifact
MBTAcquisitionRecord = MedicineBallThrowAcquisitionRecord


__all__ = [
    "MBTAcquisitionIdentity",
    "MBTAcquisitionRecord",
    "MBTAllowedState",
    "MBTArtifactHashScope",
    "MBTArtifactStatus",
    "MBTBodyPosture",
    "MBTCoordinateEvidence",
    "MBTHashAlgorithm",
    "MBTMeasurementIdentity",
    "MBTProcessingIdentity",
    "MBTProcessingState",
    "MBTProtocolIdentity",
    "MBTQualificationStatus",
    "MBTReleaseEvent",
    "MBTReleaseSemantics",
    "MBTSemanticIdentity",
    "MBTSensorModality",
    "MBTSourceArtifact",
    "MBTSupportCondition",
    "MBTThrowVariant",
    "MBTTimebase",
    "MBTTimebaseKind",
    "MedicineBallThrowAcquisitionIdentity",
    "MedicineBallThrowAcquisitionRecord",
    "MedicineBallThrowMeasurementIdentity",
    "MedicineBallThrowProcessingIdentity",
    "MedicineBallThrowProtocolIdentity",
    "MedicineBallThrowSemanticIdentity",
    "MedicineBallThrowSourceArtifact",
    "canonical_mbt_trajectory_digest",
]
