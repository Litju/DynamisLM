"""Stable identity and immutable method metadata."""

from __future__ import annotations

import math
from dataclasses import dataclass

from dynamislm.serialization import register_serializable_type

type MetadataValue = str | int | float | bool | None


def _require_text(value: str, field_name: str) -> None:
    if not value or not value.strip():
        raise ValueError(f"{field_name} must not be empty")


def _validate_metadata_value(value: MetadataValue) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("metadata values cannot be NaN or Infinity")


def require_tuple(value: object, field_name: str) -> None:
    if not isinstance(value, tuple):
        raise ValueError(f"{field_name} must be an immutable tuple")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class ScientificIdentifier:
    """Stable namespace/type/key/version identity for registry definitions."""

    namespace: str
    object_type: str
    key: str
    version: str

    def __post_init__(self) -> None:
        for field_name, value in (
            ("namespace", self.namespace),
            ("object_type", self.object_type),
            ("key", self.key),
            ("version", self.version),
        ):
            _require_text(value, field_name)
            if any(character.isspace() for character in value):
                raise ValueError(f"{field_name} must not contain whitespace")

    @property
    def stable_id(self) -> str:
        return f"{self.namespace}:{self.object_type}:{self.key}@{self.version}"


@register_serializable_type
@dataclass(frozen=True, slots=True)
class InstanceIdentifier:
    """Unique identifier for an observation, artifact, acquisition, or run instance."""

    instance_type: str
    value: str

    def __post_init__(self) -> None:
        _require_text(self.instance_type, "instance_type")
        _require_text(self.value, "value")

    @property
    def qualified(self) -> str:
        return f"{self.instance_type}:{self.value}"


@register_serializable_type
@dataclass(frozen=True, slots=True)
class RegistryReference:
    """A stable registry identity with a separate human-facing label."""

    identifier: ScientificIdentifier
    display_label: str
    aliases: tuple[str, ...] = ()
    reference_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_text(self.display_label, "display_label")
        require_tuple(self.aliases, "aliases")
        require_tuple(self.reference_ids, "reference_ids")
        if any(not alias.strip() for alias in self.aliases):
            raise ValueError("aliases must not contain empty strings")
        if any(not reference_id.strip() for reference_id in self.reference_ids):
            raise ValueError("reference_ids must not contain empty strings")

    @property
    def stable_id(self) -> str:
        return self.identifier.stable_id


@register_serializable_type
@dataclass(frozen=True, slots=True)
class MetadataEntry:
    """Small immutable key/value metadata item for method parameters and context."""

    key: str
    value: MetadataValue

    def __post_init__(self) -> None:
        _require_text(self.key, "key")
        _validate_metadata_value(self.value)


@register_serializable_type
@dataclass(frozen=True, slots=True)
class SamplingCharacteristics:
    """Acquisition sampling metadata without a signal-processing implementation."""

    frequency_hz: float | None = None
    channels: tuple[str, ...] = ()
    sample_format: str | None = None

    def __post_init__(self) -> None:
        if self.frequency_hz is not None and (
            not math.isfinite(self.frequency_hz) or self.frequency_hz <= 0
        ):
            raise ValueError("frequency_hz must be finite and positive when present")
        require_tuple(self.channels, "channels")
        if any(not channel.strip() for channel in self.channels):
            raise ValueError("sampling channels must not contain empty strings")
        if self.sample_format is not None:
            _require_text(self.sample_format, "sample_format")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class UnitReference:
    """Stable unit identity; this class does not perform conversions."""

    identifier: ScientificIdentifier
    display_label: str

    def __post_init__(self) -> None:
        _require_text(self.display_label, "display_label")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class SignConvention:
    """Explicit sign-direction metadata, not an arithmetic operation."""

    reference: RegistryReference | None = None
    positive_direction: str | None = None

    def __post_init__(self) -> None:
        if self.positive_direction is not None:
            _require_text(self.positive_direction, "positive_direction")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class NormalizationSpec:
    """Normalization identity and parameters without applying normalization."""

    method: RegistryReference | None = None
    parameters: tuple[MetadataEntry, ...] = ()
    description: str | None = None

    def __post_init__(self) -> None:
        if self.description is not None:
            _require_text(self.description, "description")
        require_tuple(self.parameters, "parameters")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class SemanticIdentity:
    """Construct, protocol, measurand, and metric identity references."""

    construct: RegistryReference
    test_family: RegistryReference
    protocol: RegistryReference
    measurand: RegistryReference
    metric_definition: RegistryReference


@register_serializable_type
@dataclass(frozen=True, slots=True)
class AcquisitionIdentity:
    """Device/raw-artifact/channel identity and material acquisition metadata."""

    device: RegistryReference
    raw_artifact: InstanceIdentifier
    sensor_channel: str | None = None
    sampling: SamplingCharacteristics | None = None
    calibration_reference: RegistryReference | None = None
    hardware_firmware: RegistryReference | None = None

    def __post_init__(self) -> None:
        if self.sensor_channel is not None:
            _require_text(self.sensor_channel, "sensor_channel")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class ProcessingIdentity:
    """Registered processing identity; no method is executed by this object."""

    event_definitions: tuple[RegistryReference, ...] = ()
    phase_definitions: tuple[RegistryReference, ...] = ()
    estimator: RegistryReference | None = None
    registered_operation: RegistryReference | None = None
    method_parameters: tuple[MetadataEntry, ...] = ()
    filtering: tuple[RegistryReference, ...] = ()
    differentiation_method: RegistryReference | None = None
    integration_method: RegistryReference | None = None
    unit: UnitReference | None = None
    sign_convention: SignConvention | None = None
    normalization: NormalizationSpec | None = None
    trial_selection: RegistryReference | None = None
    aggregation: RegistryReference | None = None

    def __post_init__(self) -> None:
        for field_name, value in (
            ("event_definitions", self.event_definitions),
            ("phase_definitions", self.phase_definitions),
            ("method_parameters", self.method_parameters),
            ("filtering", self.filtering),
        ):
            require_tuple(value, field_name)


@register_serializable_type
@dataclass(frozen=True, slots=True)
class VersionIdentity:
    """Explicit processing, software, registry, and material hardware versions."""

    processing_method: RegistryReference
    method_registry_version: str
    software_version: str
    hardware_firmware: RegistryReference | None = None

    def __post_init__(self) -> None:
        _require_text(self.method_registry_version, "method_registry_version")
        _require_text(self.software_version, "software_version")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class MeasurementIdentity:
    """What was measured and how it was defined; never the observed result value."""

    identity_id: ScientificIdentifier
    semantic: SemanticIdentity
    acquisition: AcquisitionIdentity
    processing: ProcessingIdentity
    version: VersionIdentity

    @property
    def display_label(self) -> str:
        return self.semantic.metric_definition.display_label
