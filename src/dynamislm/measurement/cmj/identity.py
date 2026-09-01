"""CMJ test-family, protocol, and measurement identity contracts."""

from __future__ import annotations

import math
from dataclasses import dataclass

from dynamislm.measurement.cmj.acquisition import CMJAcquisitionIdentity
from dynamislm.measurement.identity import (
    MeasurementIdentity,
    RegistryReference,
    ScientificIdentifier,
    SemanticIdentity,
    UnitReference,
)
from dynamislm.serialization import register_serializable_type

CMJ_REGISTRY_VERSION = "1.0.0"
CMJ_TEST_FAMILY = RegistryReference(
    identifier=ScientificIdentifier(
        "dynamislm", "test-family", "countermovement-jump", CMJ_REGISTRY_VERSION
    ),
    display_label="Countermovement Jump",
    aliases=("CMJ",),
)


def _require_text(value: str, field_name: str) -> None:
    if not value or not value.strip():
        raise ValueError(f"{field_name} must not be empty")


type ProtocolAttributeValue = str | int | float | bool | None


@register_serializable_type
@dataclass(frozen=True, slots=True)
class CMJProtocolAttribute:
    """One explicitly named protocol attribute; absent means unresolved, not defaulted."""

    name: str
    value: ProtocolAttributeValue
    unit: UnitReference | None = None

    def __post_init__(self) -> None:
        _require_text(self.name, "name")
        if isinstance(self.value, float) and not math.isfinite(self.value):
            raise ValueError("protocol attribute values cannot be NaN or Infinity")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class CMJProtocolIdentity:
    """Optional registered protocol plus only the attributes actually supplied."""

    reference: RegistryReference | None
    arm_use_constraint: CMJProtocolAttribute | None = None
    external_loading: CMJProtocolAttribute | None = None
    movement_instruction: CMJProtocolAttribute | None = None
    start_posture: CMJProtocolAttribute | None = None
    additional_attributes: tuple[CMJProtocolAttribute, ...] = ()

    def __post_init__(self) -> None:
        if self.reference is not None and self.reference.identifier.object_type != "protocol":
            raise ValueError("CMJ protocol reference must have object_type 'protocol'")
        if not isinstance(self.additional_attributes, tuple):
            raise ValueError("additional_attributes must be an immutable tuple")

    @property
    def is_resolved(self) -> bool:
        return self.reference is not None


@register_serializable_type
@dataclass(frozen=True, slots=True, kw_only=True)
class CMJSemanticIdentity(SemanticIdentity):
    """Generic semantic identity with an explicit CMJ protocol contract."""

    protocol_identity: CMJProtocolIdentity | None = None

    def __post_init__(self) -> None:
        if self.test_family.identifier.stable_id != CMJ_TEST_FAMILY.identifier.stable_id:
            raise ValueError("CMJ semantic identity must use the registered CMJ test family")
        if self.protocol_identity is not None:
            reference = self.protocol_identity.reference
            if (
                self.protocol is None
                or reference is None
                or self.protocol.identifier.stable_id != reference.identifier.stable_id
            ):
                raise ValueError("protocol and protocol_identity references must agree")


@register_serializable_type
@dataclass(frozen=True, slots=True, kw_only=True)
class CMJMeasurementIdentity(MeasurementIdentity):
    """CMJ measurement identity specialized for force-platform acquisition."""

    semantic: CMJSemanticIdentity
    acquisition: CMJAcquisitionIdentity

    def __post_init__(self) -> None:
        if not isinstance(self.semantic, CMJSemanticIdentity):
            raise ValueError("CMJ measurement identity requires CMJSemanticIdentity")
        if not isinstance(self.acquisition, CMJAcquisitionIdentity):
            raise ValueError("CMJ measurement identity requires CMJAcquisitionIdentity")
