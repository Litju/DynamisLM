"""Small, explicit CMJ registry surface for the P1B acquisition contract."""

from __future__ import annotations

from dynamislm.measurement.cmj.identity import CMJ_REGISTRY_VERSION
from dynamislm.measurement.identity import RegistryReference, ScientificIdentifier, UnitReference


def _reference(object_type: str, key: str, label: str) -> RegistryReference:
    return RegistryReference(
        identifier=ScientificIdentifier("dynamislm", object_type, key, CMJ_REGISTRY_VERSION),
        display_label=label,
    )


CMJ_RAW_VERTICAL_FORCE_SIGNAL_SCHEMA = _reference(
    "schema", "cmj-raw-vertical-force-signal", "CMJ raw vertical-force signal"
)
CMJ_ACQUISITION_COMPARABILITY_RULE = _reference(
    "comparability-rule", "cmj-acquisition-identity-v1", "CMJ acquisition identity comparability"
)

NEWTON = UnitReference(
    ScientificIdentifier("dynamislm", "unit", "newton", CMJ_REGISTRY_VERSION), "N"
)
KILONEWTON = UnitReference(
    ScientificIdentifier("dynamislm", "unit", "kilonewton", CMJ_REGISTRY_VERSION), "kN"
)
POUND_FORCE = UnitReference(
    ScientificIdentifier("dynamislm", "unit", "pound-force", CMJ_REGISTRY_VERSION), "lbf"
)
KILOGRAM_FORCE = UnitReference(
    ScientificIdentifier("dynamislm", "unit", "kilogram-force", CMJ_REGISTRY_VERSION), "kgf"
)
REGISTERED_FORCE_UNITS = (NEWTON, KILONEWTON, POUND_FORCE, KILOGRAM_FORCE)


def is_registered_force_unit(unit: UnitReference) -> bool:
    """Return whether the unit is explicitly registered for CMJ force signals."""

    return any(
        candidate.identifier.stable_id == unit.identifier.stable_id
        for candidate in REGISTERED_FORCE_UNITS
    )


def is_registered_axis(reference: RegistryReference) -> bool:
    return reference.identifier.object_type == "axis"


def is_registered_reference_frame(reference: RegistryReference) -> bool:
    return reference.identifier.object_type == "reference-frame"


def is_registered_arrangement(reference: RegistryReference) -> bool:
    return reference.identifier.object_type == "acquisition-arrangement"
