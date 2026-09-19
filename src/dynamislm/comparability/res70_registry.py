"""Canonical RES-70 comparability and bridge registries."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from dynamislm.comparability.res70_models import BridgeRegistration
from dynamislm.measurement.identity import (
    MetadataEntry,
    RegistryReference,
    ScientificIdentifier,
    _require_instance,
    _require_text,
    _require_tuple_items,
    require_tuple,
)
from dynamislm.serialization import canonical_hash, register_serializable_type

RES70_REGISTRY_VERSION = "1.0.0"
RES70_SOFTWARE_VERSION = "dynamislm-res70-1.0.0"


def _reference(object_type: str, key: str, label: str) -> RegistryReference:
    return RegistryReference(
        ScientificIdentifier("dynamislm", object_type, key, RES70_REGISTRY_VERSION),
        label,
    )


RES70_CROSS_SOURCE_COMPARABILITY_RULE = _reference(
    "comparability-rule",
    "cross-source-pairwise-v1",
    "RES-70 pairwise cross-source comparability",
)
RES70_AFFINE_BRIDGE_OPERATION = _reference(
    "registered-operation",
    "res70-registered-affine-transformation-v1",
    "RES-70 registered affine transformation",
)
RES70_BRIDGE_PROVENANCE_RULE = _reference(
    "provenance-rule",
    "res70-bridge-execution-v1",
    "RES-70 bridge execution provenance",
)


BridgeTransform = Callable[[float, tuple[MetadataEntry, ...]], float]


@dataclass(frozen=True, slots=True)
class RegisteredBridgeOperation:
    """Deterministic operation implementation owned by the canonical registry."""

    reference: RegistryReference
    execute: BridgeTransform
    note: str

    def __post_init__(self) -> None:
        _require_instance(self.reference, RegistryReference, "reference")
        if self.reference.identifier.object_type != "registered-operation":
            raise ValueError("bridge operation reference must identify a registered operation")
        _require_text(self.note, "note")


@dataclass(frozen=True, slots=True)
class BridgeOperationRegistry:
    """Non-callable wire-free dispatch table for canonical operations."""

    entries: tuple[RegisteredBridgeOperation, ...]

    def __post_init__(self) -> None:
        require_tuple(self.entries, "entries")
        if any(not isinstance(item, RegisteredBridgeOperation) for item in self.entries):
            raise ValueError("bridge operation registry entries must be typed")
        refs = tuple(item.reference.stable_id for item in self.entries)
        if len(set(refs)) != len(refs):
            raise ValueError("bridge operation registry cannot contain duplicate references")

    def resolve(self, reference: RegistryReference) -> RegisteredBridgeOperation | None:
        _require_instance(reference, RegistryReference, "reference")
        matches = tuple(
            item for item in self.entries if item.reference.stable_id == reference.stable_id
        )
        if len(matches) > 1:
            raise ValueError("RES70_REGISTRY_INTEGRITY_FAILURE: duplicate bridge operation")
        return matches[0] if matches else None


@register_serializable_type
@dataclass(frozen=True, slots=True)
class BridgeRegistry:
    """Immutable bridge declarations with a canonical content hash."""

    entries: tuple[BridgeRegistration, ...] = ()
    registry_version: str = RES70_REGISTRY_VERSION
    authority_origin: str = "PRODUCTION"
    registry_hash: str | None = None

    def __post_init__(self) -> None:
        _require_tuple_items(self.entries, BridgeRegistration, "entries")
        _require_text(self.registry_version, "registry_version")
        _require_text(self.authority_origin, "authority_origin")
        refs = tuple(item.bridge_reference.stable_id for item in self.entries)
        if len(set(refs)) != len(refs):
            raise ValueError("RES70_REGISTRY_INTEGRITY_FAILURE: duplicate bridge reference")
        if self.authority_origin == "PRODUCTION" and any(
            item.authority_origin.value != "PRODUCTION" for item in self.entries
        ):
            raise ValueError("production bridge registry cannot contain synthetic bridges")
        if any(item.registry_version != self.registry_version for item in self.entries):
            raise ValueError("bridge and bridge-registry versions must match")
        expected = canonical_hash(
            {
                "entries": self.entries,
                "registry_version": self.registry_version,
                "authority_origin": self.authority_origin,
            }
        )
        if self.registry_hash is None:
            object.__setattr__(self, "registry_hash", expected)
        elif self.registry_hash != expected:
            raise ValueError("registry_hash does not match immutable bridge registry")

    def resolve(self, reference: RegistryReference) -> BridgeRegistration | None:
        _require_instance(reference, RegistryReference, "reference")
        matches = tuple(
            item for item in self.entries if item.bridge_reference.stable_id == reference.stable_id
        )
        if len(matches) > 1:
            raise ValueError("RES70_REGISTRY_INTEGRITY_FAILURE: duplicate bridge authority")
        return matches[0] if matches else None

    def with_synthetic_entry(self, entry: BridgeRegistration) -> BridgeRegistry:
        if entry.authority_origin.value != "SYNTHETIC_TEST":
            raise ValueError("with_synthetic_entry accepts only synthetic bridge declarations")
        return BridgeRegistry(
            entries=(*self.entries, entry),
            registry_version=self.registry_version,
            authority_origin="SYNTHETIC_TEST",
        )

    @property
    def canonical_hash(self) -> str:
        assert self.registry_hash is not None
        return self.registry_hash


@register_serializable_type
@dataclass(frozen=True, slots=True)
class ComparabilityRuleRegistry:
    """Immutable semantic rule references used by the RES-70 wrapper."""

    entries: tuple[RegistryReference, ...]
    registry_version: str = RES70_REGISTRY_VERSION
    registry_hash: str | None = None

    def __post_init__(self) -> None:
        _require_tuple_items(self.entries, RegistryReference, "entries")
        _require_text(self.registry_version, "registry_version")
        refs = tuple(item.stable_id for item in self.entries)
        if len(set(refs)) != len(refs):
            raise ValueError("comparability rule registry cannot contain duplicate references")
        expected = canonical_hash(
            {"entries": self.entries, "registry_version": self.registry_version}
        )
        if self.registry_hash is None:
            object.__setattr__(self, "registry_hash", expected)
        elif self.registry_hash != expected:
            raise ValueError("registry_hash does not match immutable rule registry")

    def contains(self, reference: RegistryReference) -> bool:
        return any(item.stable_id == reference.stable_id for item in self.entries)

    @property
    def canonical_hash(self) -> str:
        assert self.registry_hash is not None
        return self.registry_hash


def _affine_transform(value: float, parameters: tuple[MetadataEntry, ...]) -> float:
    values = {item.key: item.value for item in parameters}
    scale = values.get("scale")
    offset = values.get("offset", 0.0)
    if isinstance(scale, bool) or not isinstance(scale, int | float):
        raise ValueError("registered affine bridge requires a numeric fixed scale")
    if isinstance(offset, bool) or not isinstance(offset, int | float):
        raise ValueError("registered affine bridge requires a numeric fixed offset")
    result = float(value) * float(scale) + float(offset)
    if result != result or result in (float("inf"), float("-inf")):
        raise ValueError("registered bridge produced a non-finite result")
    return result


CANONICAL_BRIDGE_OPERATION_REGISTRY = BridgeOperationRegistry(
    entries=(
        RegisteredBridgeOperation(
            reference=RES70_AFFINE_BRIDGE_OPERATION,
            execute=_affine_transform,
            note="fixed affine operation; scale and offset come only from a registered bridge",
        ),
    )
)

CANONICAL_BRIDGE_REGISTRY = BridgeRegistry()
RES70_BRIDGE_REGISTRY = CANONICAL_BRIDGE_REGISTRY
RES70_COMPARABILITY_RULE_REGISTRY = ComparabilityRuleRegistry(
    entries=(RES70_CROSS_SOURCE_COMPARABILITY_RULE,)
)


def canonical_registry_hash(
    *,
    bridge_registry: BridgeRegistry = CANONICAL_BRIDGE_REGISTRY,
    rule_registry: ComparabilityRuleRegistry = RES70_COMPARABILITY_RULE_REGISTRY,
) -> str:
    return canonical_hash(
        {
            "bridge_registry": bridge_registry,
            "rule_registry": rule_registry,
        }
    )


def is_canonical_bridge_registry(registry: BridgeRegistry) -> bool:
    return registry is CANONICAL_BRIDGE_REGISTRY


def is_canonical_operation_registry(registry: BridgeOperationRegistry) -> bool:
    return registry is CANONICAL_BRIDGE_OPERATION_REGISTRY


__all__ = [
    "CANONICAL_BRIDGE_OPERATION_REGISTRY",
    "CANONICAL_BRIDGE_REGISTRY",
    "RES70_AFFINE_BRIDGE_OPERATION",
    "RES70_BRIDGE_PROVENANCE_RULE",
    "RES70_BRIDGE_REGISTRY",
    "RES70_COMPARABILITY_RULE_REGISTRY",
    "RES70_CROSS_SOURCE_COMPARABILITY_RULE",
    "RES70_REGISTRY_VERSION",
    "RES70_SOFTWARE_VERSION",
    "BridgeOperationRegistry",
    "BridgeRegistry",
    "ComparabilityRuleRegistry",
    "RegisteredBridgeOperation",
    "canonical_registry_hash",
    "is_canonical_bridge_registry",
    "is_canonical_operation_registry",
]
