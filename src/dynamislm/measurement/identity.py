"""Stable identity and immutable method metadata."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Any

from dynamislm.serialization import register_serializable_type

type MetadataValue = str | int | float | bool | None


def _require_text(value: object, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must not be empty")


def _validate_metadata_value(value: object) -> None:
    if value is not None and not isinstance(value, str | int | float | bool):
        raise ValueError("metadata values must be scalar JSON-compatible values")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("metadata values cannot be NaN or Infinity")


def require_tuple(value: object, field_name: str) -> None:
    if not isinstance(value, tuple):
        raise ValueError(f"{field_name} must be an immutable tuple")


def _require_instance(value: object, expected_type: type[Any], field_name: str) -> None:
    if not isinstance(value, expected_type):
        raise ValueError(f"{field_name} must be a {expected_type.__name__}")


def _require_optional_instance(
    value: object,
    expected_type: type[Any],
    field_name: str,
) -> None:
    if value is not None:
        _require_instance(value, expected_type, field_name)


def _require_tuple_items(
    value: object,
    expected_type: type[Any],
    field_name: str,
) -> None:
    require_tuple(value, field_name)
    if not isinstance(value, tuple):
        raise ValueError(f"{field_name} must be an immutable tuple")
    if any(not isinstance(item, expected_type) for item in value):
        raise ValueError(f"{field_name} must contain {expected_type.__name__} values")


def _require_enum(value: object, expected_type: type[Enum], field_name: str) -> None:
    if not isinstance(value, expected_type):
        raise ValueError(f"{field_name} must be a {expected_type.__name__}")


def _require_number(value: object, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{field_name} must be numeric")


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
        _require_instance(self.identifier, ScientificIdentifier, "identifier")
        _require_text(self.display_label, "display_label")
        _require_tuple_items(self.aliases, str, "aliases")
        _require_tuple_items(self.reference_ids, str, "reference_ids")
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
        if self.frequency_hz is not None:
            _require_number(self.frequency_hz, "frequency_hz")
            if not math.isfinite(float(self.frequency_hz)) or self.frequency_hz <= 0:
                raise ValueError("frequency_hz must be finite and positive when present")
        _require_tuple_items(self.channels, str, "channels")
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
        _require_instance(self.identifier, ScientificIdentifier, "identifier")
        _require_text(self.display_label, "display_label")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class SignConvention:
    """Explicit sign-direction metadata, not an arithmetic operation."""

    reference: RegistryReference | None = None
    positive_direction: str | None = None

    def __post_init__(self) -> None:
        _require_optional_instance(self.reference, RegistryReference, "reference")
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
        _require_optional_instance(self.method, RegistryReference, "method")
        if self.description is not None:
            _require_text(self.description, "description")
        _require_tuple_items(self.parameters, MetadataEntry, "parameters")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class SemanticIdentity:
    """Construct, protocol, measurand, and metric identity references."""

    construct: RegistryReference
    test_family: RegistryReference
    protocol: RegistryReference | None
    measurand: RegistryReference
    metric_definition: RegistryReference

    def __post_init__(self) -> None:
        _require_instance(self.construct, RegistryReference, "construct")
        _require_instance(self.test_family, RegistryReference, "test_family")
        _require_optional_instance(self.protocol, RegistryReference, "protocol")
        _require_instance(self.measurand, RegistryReference, "measurand")
        _require_instance(self.metric_definition, RegistryReference, "metric_definition")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class AcquisitionIdentity:
    """Device/raw-artifact/channel identity and material acquisition metadata."""

    device: RegistryReference | None
    raw_artifact: InstanceIdentifier | None
    sensor_channel: str | None = None
    sampling: SamplingCharacteristics | None = None
    calibration_reference: RegistryReference | None = None
    hardware_firmware: RegistryReference | None = None

    def __post_init__(self) -> None:
        _require_optional_instance(self.device, RegistryReference, "device")
        _require_optional_instance(self.raw_artifact, InstanceIdentifier, "raw_artifact")
        _require_optional_instance(self.sampling, SamplingCharacteristics, "sampling")
        _require_optional_instance(
            self.calibration_reference,
            RegistryReference,
            "calibration_reference",
        )
        _require_optional_instance(
            self.hardware_firmware,
            RegistryReference,
            "hardware_firmware",
        )
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
        _require_tuple_items(self.event_definitions, RegistryReference, "event_definitions")
        _require_tuple_items(self.phase_definitions, RegistryReference, "phase_definitions")
        _require_optional_instance(self.estimator, RegistryReference, "estimator")
        _require_optional_instance(
            self.registered_operation,
            RegistryReference,
            "registered_operation",
        )
        _require_tuple_items(self.method_parameters, MetadataEntry, "method_parameters")
        _require_tuple_items(self.filtering, RegistryReference, "filtering")
        _require_optional_instance(
            self.differentiation_method,
            RegistryReference,
            "differentiation_method",
        )
        _require_optional_instance(self.integration_method, RegistryReference, "integration_method")
        _require_optional_instance(self.unit, UnitReference, "unit")
        _require_optional_instance(self.sign_convention, SignConvention, "sign_convention")
        _require_optional_instance(self.normalization, NormalizationSpec, "normalization")
        _require_optional_instance(self.trial_selection, RegistryReference, "trial_selection")
        _require_optional_instance(self.aggregation, RegistryReference, "aggregation")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class VersionIdentity:
    """Explicit processing, software, registry, and material hardware versions."""

    processing_method: RegistryReference
    method_registry_version: str
    software_version: str
    hardware_firmware: RegistryReference | None = None

    def __post_init__(self) -> None:
        _require_instance(self.processing_method, RegistryReference, "processing_method")
        _require_text(self.method_registry_version, "method_registry_version")
        _require_text(self.software_version, "software_version")
        _require_optional_instance(
            self.hardware_firmware,
            RegistryReference,
            "hardware_firmware",
        )


@register_serializable_type
@dataclass(frozen=True, slots=True)
class MeasurementIdentity:
    """What was measured and how it was defined; never the observed result value."""

    identity_id: ScientificIdentifier
    semantic: SemanticIdentity
    acquisition: AcquisitionIdentity
    processing: ProcessingIdentity
    version: VersionIdentity

    def __post_init__(self) -> None:
        _require_instance(self.identity_id, ScientificIdentifier, "identity_id")
        _require_instance(self.semantic, SemanticIdentity, "semantic")
        _require_instance(self.acquisition, AcquisitionIdentity, "acquisition")
        _require_instance(self.processing, ProcessingIdentity, "processing")
        _require_instance(self.version, VersionIdentity, "version")

    @property
    def display_label(self) -> str:
        return self.semantic.metric_definition.display_label
