"""CMJ force-platform acquisition identity and artifact contracts."""

from __future__ import annotations

import datetime as datetime_module
import math
from dataclasses import dataclass, field
from enum import StrEnum

from dynamislm.measurement.identity import (
    AcquisitionIdentity,
    InstanceIdentifier,
    MetadataEntry,
    RegistryReference,
    SignConvention,
    UnitReference,
    require_tuple,
)
from dynamislm.provenance.models import SourceArtifact
from dynamislm.serialization import register_serializable_type


def _require_text(value: str, field_name: str) -> None:
    if not value or not value.strip():
        raise ValueError(f"{field_name} must not be empty")


class AcquisitionArrangement(StrEnum):
    LEFT_FORCE_PLATFORM = "LEFT_FORCE_PLATFORM"
    RIGHT_FORCE_PLATFORM = "RIGHT_FORCE_PLATFORM"
    BILATERAL_SEPARATE = "BILATERAL_SEPARATE"
    BILATERAL_PRECOMBINED = "BILATERAL_PRECOMBINED"
    SINGLE_PLATFORM = "SINGLE_PLATFORM"
    OTHER_REGISTERED_ARRANGEMENT = "OTHER_REGISTERED_ARRANGEMENT"


class ChannelRole(StrEnum):
    LEFT_FORCE_PLATFORM = "LEFT_FORCE_PLATFORM"
    RIGHT_FORCE_PLATFORM = "RIGHT_FORCE_PLATFORM"
    PRECOMBINED_VERTICAL_FORCE = "PRECOMBINED_VERTICAL_FORCE"
    SINGLE_FORCE_PLATFORM = "SINGLE_FORCE_PLATFORM"
    OTHER = "OTHER"


class SignalProcessingState(StrEnum):
    RAW_ACQUIRED = "RAW_ACQUIRED"
    DEVICE_PROCESSED = "DEVICE_PROCESSED"
    SYSTEM_PROCESSED = "SYSTEM_PROCESSED"
    UNKNOWN = "UNKNOWN"


class TimebaseKind(StrEnum):
    REGULAR = "REGULAR"
    EXPLICIT = "EXPLICIT"


class ReferenceState(StrEnum):
    DOCUMENTED = "DOCUMENTED"
    NOT_PROVIDED = "NOT_PROVIDED"
    UNKNOWN = "UNKNOWN"


class CombinationLineageKind(StrEnum):
    DIRECT_COMBINED_OUTPUT = "DIRECT_COMBINED_OUTPUT"
    VENDOR_COMBINED_OUTPUT = "VENDOR_COMBINED_OUTPUT"
    DYNAMISLM_COMBINED_OUTPUT = "DYNAMISLM_COMBINED_OUTPUT"


class HashAlgorithm(StrEnum):
    SHA256 = "sha256"


class ArtifactHashScope(StrEnum):
    CONTENT_BYTES = "CONTENT_BYTES"
    CANONICAL_SIGNAL_REPRESENTATION = "CANONICAL_SIGNAL_REPRESENTATION"


class ArtifactStatus(StrEnum):
    VERIFIED = "VERIFIED"
    UNVERIFIED = "UNVERIFIED"


@register_serializable_type
@dataclass(frozen=True, slots=True)
class CMJChannelIdentity:
    """Stable identity and role for one force-platform channel."""

    channel_id: str
    role: ChannelRole

    def __post_init__(self) -> None:
        _require_text(self.channel_id, "channel_id")
        if not isinstance(self.role, ChannelRole):
            raise ValueError("channel role must be a registered ChannelRole")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class TimebaseIdentity:
    """Declared acquisition timebase semantics without resampling or inference."""

    kind: TimebaseKind
    sample_rate_hz: float | None
    clock_reference: RegistryReference | None = None
    description: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, TimebaseKind):
            raise ValueError("timebase kind must be a registered TimebaseKind")
        if self.sample_rate_hz is not None:
            if isinstance(self.sample_rate_hz, bool) or not isinstance(
                self.sample_rate_hz, int | float
            ):
                raise ValueError("sample_rate_hz must be numeric when present")
            if not math.isfinite(self.sample_rate_hz) or self.sample_rate_hz <= 0:
                raise ValueError("sample_rate_hz must be finite and positive when present")
            object.__setattr__(self, "sample_rate_hz", float(self.sample_rate_hz))
        if self.kind is TimebaseKind.REGULAR and self.sample_rate_hz is None:
            raise ValueError("regular timebase requires sample_rate_hz")
        if self.description is not None:
            _require_text(self.description, "description")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class ReferenceMetadata:
    """Calibration or zeroing state retained without applying a correction."""

    status: ReferenceState
    reference: RegistryReference | None = None
    details: tuple[MetadataEntry, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.status, ReferenceState):
            raise ValueError("reference state must be a registered ReferenceState")
        require_tuple(self.details, "details")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class CombinationLineage:
    """Provenance of a pre-combined bilateral output."""

    kind: CombinationLineageKind
    source_channels: tuple[str, ...] = ()
    method: RegistryReference | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, CombinationLineageKind):
            raise ValueError("combination lineage kind must be registered")
        require_tuple(self.source_channels, "source_channels")
        if any(not channel.strip() for channel in self.source_channels):
            raise ValueError("source_channels must not contain empty strings")
        if self.kind is not CombinationLineageKind.DIRECT_COMBINED_OUTPUT and not (
            len(self.source_channels) >= 2
        ):
            raise ValueError("pre-combined software output must name its source channels")
        if self.kind is CombinationLineageKind.DYNAMISLM_COMBINED_OUTPUT and self.method is None:
            raise ValueError("DynamisLM combination must identify its registered method")


@register_serializable_type
@dataclass(frozen=True, slots=True, kw_only=True)
class CMJSourceArtifact(SourceArtifact):
    """Content-addressed raw artifact metadata for a CMJ acquisition."""

    hash_algorithm: HashAlgorithm
    hash_scope: ArtifactHashScope
    status: ArtifactStatus
    storage_reference: str | None = None
    acquisition_id: InstanceIdentifier | None = None

    def __post_init__(self) -> None:
        SourceArtifact.__post_init__(self)
        if not isinstance(self.hash_algorithm, HashAlgorithm):
            raise ValueError("artifact hash algorithm must be a registered HashAlgorithm")
        if not isinstance(self.hash_scope, ArtifactHashScope):
            raise ValueError("artifact hash scope must be a registered ArtifactHashScope")
        if not isinstance(self.status, ArtifactStatus):
            raise ValueError("artifact status must be a registered ArtifactStatus")
        _require_text(self.hash_algorithm.value, "hash_algorithm")
        if self.storage_reference is not None:
            _require_text(self.storage_reference, "storage_reference")


@register_serializable_type
@dataclass(frozen=True, slots=True, kw_only=True)
class CMJAcquisitionIdentity(AcquisitionIdentity):
    """Explicit force-platform acquisition identity, including unresolved states."""

    measuring_system: RegistryReference | None = None
    arrangement: AcquisitionArrangement | None = None
    acquisition_instance_id: InstanceIdentifier | None = None
    channel: CMJChannelIdentity | None = None
    available_channels: tuple[CMJChannelIdentity, ...] = ()
    physical_axis: RegistryReference | None = None
    reference_frame: RegistryReference | None = None
    unit: UnitReference | None = None
    sign_convention: SignConvention | None = None
    timebase: TimebaseIdentity | None = None
    acquisition_software_version: str | None = None
    acquisition_timestamp: datetime_module.datetime | None = None
    calibration: ReferenceMetadata = field(
        default_factory=lambda: ReferenceMetadata(ReferenceState.UNKNOWN)
    )
    zeroing: ReferenceMetadata = field(
        default_factory=lambda: ReferenceMetadata(ReferenceState.UNKNOWN)
    )
    processing_state: SignalProcessingState = SignalProcessingState.UNKNOWN
    combination_lineage: CombinationLineage | None = None
    arrangement_reference: RegistryReference | None = None

    def __post_init__(self) -> None:
        AcquisitionIdentity.__post_init__(self)
        require_tuple(self.available_channels, "available_channels")
        if any(not isinstance(channel, CMJChannelIdentity) for channel in self.available_channels):
            raise ValueError("available_channels must contain CMJChannelIdentity values")
        if self.arrangement is not None and not isinstance(
            self.arrangement, AcquisitionArrangement
        ):
            raise ValueError("arrangement must be a registered AcquisitionArrangement")
        if not isinstance(self.processing_state, SignalProcessingState):
            raise ValueError("processing state must be a registered SignalProcessingState")
        if self.acquisition_software_version is not None:
            _require_text(self.acquisition_software_version, "acquisition_software_version")
        if self.acquisition_timestamp is not None and (
            self.acquisition_timestamp.tzinfo is None
            or self.acquisition_timestamp.utcoffset() is None
        ):
            raise ValueError("acquisition_timestamp must include an explicit timezone")
