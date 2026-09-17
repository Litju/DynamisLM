"""Typed drop-jump protocol, acquisition, processing and source identities."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from itertools import pairwise

from dynamislm.measurement.drop_jump.registry import (
    DJ_FLIGHT_TIME_JUMP_HEIGHT_MEASURAND,
    DJ_GROUND_CONTACT_TIME_MEASURAND,
    DJ_REBOUND_FLIGHT_TIME_MEASURAND,
    DJ_RSI_JH_CT_MEASURAND,
    DJ_RSR_FT_CT_MEASURAND,
    DROP_JUMP_PROTOCOL_V1,
    DROP_JUMP_TEST_FAMILY,
    RES68_DECISION_EXPLOSIVE_TEST_FAMILY,
)
from dynamislm.measurement.identity import (
    AcquisitionIdentity,
    InstanceIdentifier,
    MeasurementIdentity,
    MetadataEntry,
    ProcessingIdentity,
    RegistryReference,
    SemanticIdentity,
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


class DropJumpInitiationMode(StrEnum):
    STEP_OFF = "STEP_OFF"
    JUMP_FROM_BOX = "JUMP_FROM_BOX"
    OTHER_REGISTERED = "OTHER_REGISTERED"
    UNKNOWN = "UNKNOWN"


class DropJumpArmCondition(StrEnum):
    ALLOWED = "ALLOWED"
    PROHIBITED = "PROHIBITED"
    UNKNOWN = "UNKNOWN"


class DropJumpReboundStrategy(StrEnum):
    MINIMIZE_CONTACT_TIME = "MINIMIZE_CONTACT_TIME"
    MAXIMIZE_JUMP_HEIGHT = "MAXIMIZE_JUMP_HEIGHT"
    COMBINED = "COMBINED"
    OTHER_REGISTERED = "OTHER_REGISTERED"
    UNKNOWN = "UNKNOWN"


class DropJumpTimebaseKind(StrEnum):
    REGULAR = "REGULAR"
    EXPLICIT = "EXPLICIT"


class DropJumpSensorModality(StrEnum):
    FORCE_PLATFORM = "FORCE_PLATFORM"
    CONTACT_MAT = "CONTACT_MAT"
    IMU = "IMU"
    OPTICAL = "OPTICAL"
    VIDEO = "VIDEO"
    OTHER_REGISTERED = "OTHER_REGISTERED"
    UNKNOWN = "UNKNOWN"


class DropJumpProcessingState(StrEnum):
    RAW_ACQUIRED = "RAW_ACQUIRED"
    DEVICE_PROCESSED = "DEVICE_PROCESSED"
    PROVIDER_PROCESSED = "PROVIDER_PROCESSED"
    DYNAMISLM_PROCESSED = "DYNAMISLM_PROCESSED"
    UNKNOWN = "UNKNOWN"


class DropJumpHashAlgorithm(StrEnum):
    SHA256 = "sha256"


class DropJumpArtifactHashScope(StrEnum):
    CONTENT_BYTES = "CONTENT_BYTES"
    CANONICAL_SERIES_REPRESENTATION = "CANONICAL_SERIES_REPRESENTATION"


class DropJumpArtifactStatus(StrEnum):
    VERIFIED = "VERIFIED"
    UNVERIFIED = "UNVERIFIED"


class DropJumpQualificationStatus(StrEnum):
    QUALIFIED = "QUALIFIED"
    REJECTED = "REJECTED"
    UNKNOWN = "UNKNOWN"


@register_serializable_type
@dataclass(frozen=True, slots=True)
class DropJumpFlightTimeApplicability:
    """Explicit ballistic/posture assumptions for one exact DJ trial."""

    source_observation_id: InstanceIdentifier
    rebound_takeoff_event_id: InstanceIdentifier
    subsequent_landing_event_id: InstanceIdentifier
    ballistic_vertical_motion: bool
    takeoff_landing_height_equivalence: bool
    negligible_air_resistance: bool
    decision_reference: RegistryReference = RES68_DECISION_EXPLOSIVE_TEST_FAMILY
    source_binding_digest: str | None = None

    def __post_init__(self) -> None:
        for name, value, expected in (
            ("source_observation_id", self.source_observation_id, "observation"),
            ("rebound_takeoff_event_id", self.rebound_takeoff_event_id, "event-occurrence"),
            (
                "subsequent_landing_event_id",
                self.subsequent_landing_event_id,
                "event-occurrence",
            ),
        ):
            _require_instance(value, InstanceIdentifier, name)
            if value.instance_type != expected:
                raise ValueError(f"{name} must identify a {expected}")
        if not isinstance(self.ballistic_vertical_motion, bool):
            raise ValueError("ballistic_vertical_motion must be a boolean")
        if not isinstance(self.takeoff_landing_height_equivalence, bool):
            raise ValueError("takeoff_landing_height_equivalence must be a boolean")
        if not isinstance(self.negligible_air_resistance, bool):
            raise ValueError("negligible_air_resistance must be a boolean")
        _require_instance(self.decision_reference, RegistryReference, "decision_reference")
        if self.decision_reference != RES68_DECISION_EXPLOSIVE_TEST_FAMILY:
            raise ValueError("DJ applicability must use the RES-68 decision reference")
        expected_digest = canonical_hash(self._binding_payload())
        if self.source_binding_digest is None:
            object.__setattr__(self, "source_binding_digest", expected_digest)
        elif self.source_binding_digest != expected_digest:
            raise ValueError("DJ applicability source binding digest is invalid")

    @property
    def is_authorized(self) -> bool:
        return (
            self.ballistic_vertical_motion
            and self.takeoff_landing_height_equivalence
            and self.negligible_air_resistance
        )

    def matches(
        self,
        source_observation_id: InstanceIdentifier,
        rebound_takeoff_event_id: InstanceIdentifier,
        subsequent_landing_event_id: InstanceIdentifier,
    ) -> bool:
        return (
            self.source_observation_id == source_observation_id
            and self.rebound_takeoff_event_id == rebound_takeoff_event_id
            and self.subsequent_landing_event_id == subsequent_landing_event_id
        )

    def _binding_payload(self) -> dict[str, object]:
        return {
            "source_observation_id": self.source_observation_id,
            "rebound_takeoff_event_id": self.rebound_takeoff_event_id,
            "subsequent_landing_event_id": self.subsequent_landing_event_id,
            "ballistic_vertical_motion": self.ballistic_vertical_motion,
            "takeoff_landing_height_equivalence": self.takeoff_landing_height_equivalence,
            "negligible_air_resistance": self.negligible_air_resistance,
            "decision_reference": self.decision_reference,
        }


@register_serializable_type
@dataclass(frozen=True, slots=True)
class DropJumpTimebase:
    """Regular or explicit timestamps for one drop-jump source series."""

    kind: DropJumpTimebaseKind
    sample_rate_hz: float | None = None
    start_time_s: float = 0.0
    times_s: tuple[float, ...] = ()

    def __post_init__(self) -> None:
        _require_enum(self.kind, DropJumpTimebaseKind, "kind")
        rate = _finite_optional(self.sample_rate_hz, "sample_rate_hz")
        if rate is not None and rate <= 0:
            raise ValueError("sample_rate_hz must be positive")
        object.__setattr__(self, "sample_rate_hz", rate)
        object.__setattr__(self, "start_time_s", _finite(self.start_time_s, "start_time_s"))
        require_tuple(self.times_s, "times_s")
        if self.kind is DropJumpTimebaseKind.REGULAR:
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
        if self.kind is DropJumpTimebaseKind.REGULAR:
            assert self.sample_rate_hz is not None
            return self.start_time_s + index / self.sample_rate_hz
        if index >= len(self.times_s):
            raise IndexError("sample index is outside explicit timebase")
        return self.times_s[index]


@register_serializable_type
@dataclass(frozen=True, slots=True)
class DropJumpProtocolIdentity:
    """Explicit DJ protocol; omitted material fields remain unresolved."""

    reference: RegistryReference = DROP_JUMP_PROTOCOL_V1
    protocol_version: str = "1.0.0"
    nominal_box_height_m: float | None = None
    actual_drop_height_m: float | None = None
    actual_drop_height_method: RegistryReference | None = None
    actual_drop_height_source: RegistryReference | None = None
    initiation_mode: DropJumpInitiationMode = DropJumpInitiationMode.UNKNOWN
    pre_drop_posture: str | None = None
    pre_drop_stillness: bool | None = None
    step_off_leg: str | None = None
    arms_condition: DropJumpArmCondition = DropJumpArmCondition.UNKNOWN
    rebound_strategy: DropJumpReboundStrategy = DropJumpReboundStrategy.UNKNOWN
    explicit_cue: str | None = None
    support_platform_configuration: str | None = None
    landing_rebound_technique: str | None = None
    pause_continuity_semantics: str | None = None
    additional_attributes: tuple[MetadataEntry, ...] = ()

    def __post_init__(self) -> None:
        _require_instance(self.reference, RegistryReference, "reference")
        if self.reference.identifier.object_type != "protocol":
            raise ValueError("drop-jump protocol reference must identify a protocol")
        _require_text(self.protocol_version, "protocol_version")
        nominal = _finite_optional(self.nominal_box_height_m, "nominal_box_height_m")
        actual = _finite_optional(self.actual_drop_height_m, "actual_drop_height_m")
        if nominal is not None and nominal <= 0:
            raise ValueError("nominal_box_height_m must be positive")
        if actual is not None and actual <= 0:
            raise ValueError("actual_drop_height_m must be positive")
        object.__setattr__(self, "nominal_box_height_m", nominal)
        object.__setattr__(self, "actual_drop_height_m", actual)
        for name, value in (
            ("actual_drop_height_method", self.actual_drop_height_method),
            ("actual_drop_height_source", self.actual_drop_height_source),
        ):
            _require_optional_instance(value, RegistryReference, name)
        if actual is not None and (
            self.actual_drop_height_method is None and self.actual_drop_height_source is None
        ):
            raise ValueError("actual drop height requires an independent method or source")
        if actual is None and (
            self.actual_drop_height_method is not None or self.actual_drop_height_source is not None
        ):
            raise ValueError("actual drop-height method/source requires an actual value")
        _require_enum(self.initiation_mode, DropJumpInitiationMode, "initiation_mode")
        _require_enum(self.arms_condition, DropJumpArmCondition, "arms_condition")
        _require_enum(self.rebound_strategy, DropJumpReboundStrategy, "rebound_strategy")
        if self.pre_drop_stillness is not None and not isinstance(self.pre_drop_stillness, bool):
            raise ValueError("pre_drop_stillness must be a boolean when present")
        for name in (
            "pre_drop_posture",
            "step_off_leg",
            "explicit_cue",
            "support_platform_configuration",
            "landing_rebound_technique",
            "pause_continuity_semantics",
        ):
            value = getattr(self, name)
            if value is not None:
                _require_text(value, name)
        _require_tuple_items(self.additional_attributes, MetadataEntry, "additional_attributes")

    @property
    def test_family(self) -> RegistryReference:
        return DROP_JUMP_TEST_FAMILY


@register_serializable_type
@dataclass(frozen=True, slots=True, kw_only=True)
class DropJumpAcquisitionIdentity(AcquisitionIdentity):
    """Acquisition identity for force, contact, inertial or optical DJ sources."""

    acquisition_instance_id: InstanceIdentifier | None = None
    provider: str | None = None
    sensor_modality: DropJumpSensorModality = DropJumpSensorModality.UNKNOWN
    timebase: DropJumpTimebase | None = None
    axis_or_frame: RegistryReference | None = None
    source_series_digest: str | None = None

    def __post_init__(self) -> None:
        AcquisitionIdentity.__post_init__(self)
        _require_optional_instance(
            self.acquisition_instance_id, InstanceIdentifier, "acquisition_instance_id"
        )
        if self.acquisition_instance_id is not None and (
            self.acquisition_instance_id.instance_type != "acquisition"
        ):
            raise ValueError("acquisition_instance_id must identify an acquisition")
        if self.provider is not None:
            _require_text(self.provider, "provider")
        _require_enum(self.sensor_modality, DropJumpSensorModality, "sensor_modality")
        _require_optional_instance(self.timebase, DropJumpTimebase, "timebase")
        _require_optional_instance(self.axis_or_frame, RegistryReference, "axis_or_frame")
        if self.source_series_digest is not None:
            _require_text(self.source_series_digest, "source_series_digest")


@register_serializable_type
@dataclass(frozen=True, slots=True, kw_only=True)
class DropJumpProcessingIdentity(ProcessingIdentity):
    """Processing identity including DJ timebase and source-processing state."""

    timebase: DropJumpTimebase | None = None
    processing_state: DropJumpProcessingState = DropJumpProcessingState.UNKNOWN
    provider_algorithm: RegistryReference | None = None

    def __post_init__(self) -> None:
        ProcessingIdentity.__post_init__(self)
        _require_optional_instance(self.timebase, DropJumpTimebase, "timebase")
        _require_enum(self.processing_state, DropJumpProcessingState, "processing_state")
        _require_optional_instance(self.provider_algorithm, RegistryReference, "provider_algorithm")


@register_serializable_type
@dataclass(frozen=True, slots=True, kw_only=True)
class DropJumpSemanticIdentity(SemanticIdentity):
    """Semantic identity carrying the complete DJ protocol object."""

    protocol_identity: DropJumpProtocolIdentity | None = None

    def __post_init__(self) -> None:
        SemanticIdentity.__post_init__(self)
        _require_instance(self.protocol_identity, DropJumpProtocolIdentity, "protocol_identity")
        assert self.protocol_identity is not None
        if self.test_family != DROP_JUMP_TEST_FAMILY:
            raise ValueError("drop-jump semantic identity has the wrong test family")
        if self.protocol != self.protocol_identity.reference:
            raise ValueError("protocol and protocol_identity references must agree")


@register_serializable_type
@dataclass(frozen=True, slots=True, kw_only=True)
class DropJumpMeasurementIdentity(MeasurementIdentity):
    """Measurement identity for a DJ source or one of its derived metrics."""

    semantic: DropJumpSemanticIdentity
    acquisition: DropJumpAcquisitionIdentity
    processing: DropJumpProcessingIdentity

    def __post_init__(self) -> None:
        MeasurementIdentity.__post_init__(self)
        _require_instance(self.semantic, DropJumpSemanticIdentity, "semantic")
        _require_instance(self.acquisition, DropJumpAcquisitionIdentity, "acquisition")
        _require_instance(self.processing, DropJumpProcessingIdentity, "processing")
        if self.semantic.test_family != DROP_JUMP_TEST_FAMILY:
            raise ValueError("drop-jump measurement identity has the wrong family")


@register_serializable_type
@dataclass(frozen=True, slots=True, kw_only=True)
class DropJumpSourceArtifact(SourceArtifact):
    """Content-addressed DJ source artifact with explicit verification state."""

    hash_algorithm: DropJumpHashAlgorithm = DropJumpHashAlgorithm.SHA256
    hash_scope: DropJumpArtifactHashScope = DropJumpArtifactHashScope.CONTENT_BYTES
    status: DropJumpArtifactStatus = DropJumpArtifactStatus.UNVERIFIED

    def __post_init__(self) -> None:
        SourceArtifact.__post_init__(self)
        _require_enum(self.hash_algorithm, DropJumpHashAlgorithm, "hash_algorithm")
        _require_enum(self.hash_scope, DropJumpArtifactHashScope, "hash_scope")
        _require_enum(self.status, DropJumpArtifactStatus, "status")


@register_serializable_type
@dataclass(frozen=True, slots=True, kw_only=True)
class DropJumpAcquisitionRecord(AcquisitionRecord):
    """Acquisition record preserving DJ provider/modality/timebase metadata."""

    provider: str | None = None
    sensor_modality: DropJumpSensorModality = DropJumpSensorModality.UNKNOWN
    timebase: DropJumpTimebase | None = None
    axis_or_frame: RegistryReference | None = None

    def __post_init__(self) -> None:
        AcquisitionRecord.__post_init__(self)
        if self.provider is not None:
            _require_text(self.provider, "provider")
        _require_enum(self.sensor_modality, DropJumpSensorModality, "sensor_modality")
        _require_optional_instance(self.timebase, DropJumpTimebase, "timebase")
        _require_optional_instance(self.axis_or_frame, RegistryReference, "axis_or_frame")


def canonical_drop_jump_series_digest(
    samples: tuple[float, ...],
    timebase: DropJumpTimebase,
    *,
    channel: str | None = None,
) -> str:
    """Digest exact DJ samples and timebase for event/source binding."""

    require_tuple(samples, "samples")
    normalized = tuple(_finite(value, "sample") for value in samples)
    if channel is not None:
        _require_text(channel, "channel")
    return canonical_hash({"samples": normalized, "timebase": timebase, "channel": channel})


# These aliases make the five registered output semantics easy to discover
# without introducing a generic explosive-test identity.
DJ_CONTACT_TIME_MEASURAND = DJ_GROUND_CONTACT_TIME_MEASURAND
DJ_FLIGHT_TIME_MEASURAND = DJ_REBOUND_FLIGHT_TIME_MEASURAND
DJ_JUMP_HEIGHT_MEASURAND = DJ_FLIGHT_TIME_JUMP_HEIGHT_MEASURAND
DJ_RSI_MEASURAND = DJ_RSI_JH_CT_MEASURAND
DJ_RSR_MEASURAND = DJ_RSR_FT_CT_MEASURAND


__all__ = [
    "DJ_CONTACT_TIME_MEASURAND",
    "DJ_FLIGHT_TIME_MEASURAND",
    "DJ_JUMP_HEIGHT_MEASURAND",
    "DJ_RSI_MEASURAND",
    "DJ_RSR_MEASURAND",
    "DropJumpAcquisitionIdentity",
    "DropJumpAcquisitionRecord",
    "DropJumpArmCondition",
    "DropJumpArtifactHashScope",
    "DropJumpArtifactStatus",
    "DropJumpFlightTimeApplicability",
    "DropJumpHashAlgorithm",
    "DropJumpInitiationMode",
    "DropJumpMeasurementIdentity",
    "DropJumpProcessingIdentity",
    "DropJumpProcessingState",
    "DropJumpProtocolIdentity",
    "DropJumpQualificationStatus",
    "DropJumpReboundStrategy",
    "DropJumpSemanticIdentity",
    "DropJumpSensorModality",
    "DropJumpSourceArtifact",
    "DropJumpTimebase",
    "DropJumpTimebaseKind",
    "canonical_drop_jump_series_digest",
]
