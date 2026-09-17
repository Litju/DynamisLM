"""Explicit, family-scoped registry identities for RES-68 medicine-ball throws."""

from __future__ import annotations

from dynamislm.measurement.identity import RegistryReference, ScientificIdentifier, UnitReference

MBT_REGISTRY_VERSION = "1.0.0"
MBT_SOFTWARE_VERSION = "dynamislm-res68-medicine-ball-throw-1.0.0"


def _reference(object_type: str, key: str, label: str) -> RegistryReference:
    return RegistryReference(
        identifier=ScientificIdentifier("dynamislm", object_type, key, MBT_REGISTRY_VERSION),
        display_label=label,
    )


def _unit(key: str, label: str) -> UnitReference:
    return UnitReference(
        identifier=ScientificIdentifier("dynamislm", "unit", key, MBT_REGISTRY_VERSION),
        display_label=label,
    )


RES68_DECISION_EXPLOSIVE_TEST_FAMILY = RegistryReference(
    identifier=ScientificIdentifier(
        "dynamislm", "decision-record", "res68-explosive-test-family-closure", MBT_REGISTRY_VERSION
    ),
    display_label="RES-68 explosive-test family closure decision",
    reference_ids=("docs/decisions/RES68-DR-001-explosive-test-family-closure.md",),
)

MEDICINE_BALL_THROW_TEST_FAMILY = _reference(
    "test-family", "medicine-ball-throw", "Medicine-ball throw testing"
)
MEDICINE_BALL_THROW_CONSTRUCT = _reference(
    "construct", "medicine-ball-throw-performance", "Medicine-ball throw performance construct"
)
MEDICINE_BALL_THROW_PROTOCOL_V1 = _reference(
    "protocol",
    "medicine-ball-throw-explicit-identity-v1",
    "Medicine-ball throw explicit protocol identity V1",
)
MBT_SEATED_CHEST_PROTOCOL = _reference(
    "protocol-variant", "medicine-ball-seated-chest-v1", "Seated chest medicine-ball throw"
)
MBT_STANDING_CHEST_PROTOCOL = _reference(
    "protocol-variant", "medicine-ball-standing-chest-v1", "Standing chest medicine-ball throw"
)
MBT_BACKWARD_OVERHEAD_PROTOCOL = _reference(
    "protocol-variant",
    "medicine-ball-backward-overhead-v1",
    "Backward overhead medicine-ball throw",
)
MBT_ROTATIONAL_PROTOCOL = _reference(
    "protocol-variant", "medicine-ball-rotational-v1", "Rotational medicine-ball throw"
)
MBT_SUPINE_PROTOCOL = _reference(
    "protocol-variant", "medicine-ball-supine-v1", "Supine medicine-ball throw"
)
MBT_PUSH_PRESS_PROTOCOL = _reference(
    "protocol-variant", "medicine-ball-push-press-v1", "Medicine-ball push press"
)

MBT_SOURCE_DISTANCE_OPERATION = _reference(
    "processing-method", "medicine-ball-throw-source-distance-v1", "MBT source distance V1"
)
MBT_COORDINATE_SOURCE_OPERATION = _reference(
    "processing-method",
    "medicine-ball-throw-coordinate-source-v1",
    "MBT coordinate source V1",
)
MBT_COORDINATE_QUALIFICATION_RULE = _reference(
    "source-adjudication-rule",
    "medicine-ball-throw-coordinate-qualification-v1",
    "MBT coordinate qualification V1",
)
MBT_DISTANCE_FROM_REGISTERED_COORDINATES_OPERATION = _reference(
    "registered-operation",
    "medicine-ball-throw-distance-from-registered-coordinates-v1",
    "MBT distance from registered coordinates",
)
MBT_RELEASE_VELOCITY_SOURCE_OPERATION = _reference(
    "processing-method",
    "medicine-ball-throw-release-velocity-source-v1",
    "MBT release-velocity source V1",
)
MBT_RELEASE_EVENT_SOURCE_OPERATION = _reference(
    "processing-method",
    "medicine-ball-throw-release-event-source-v1",
    "MBT release-event source V1",
)
MBT_RELEASE_EVENT_QUALIFICATION_RULE = _reference(
    "source-adjudication-rule",
    "medicine-ball-throw-release-event-qualification-v1",
    "MBT release-event qualification V1",
)
MBT_INSTRUMENTED_RELEASE_VELOCITY_OPERATION = _reference(
    "registered-operation",
    "medicine-ball-throw-instrumented-release-velocity-v1",
    "MBT instrumented release velocity",
)
MBT_SOURCE_QUALIFICATION_OPERATION = _reference(
    "source-adjudication-rule",
    "medicine-ball-throw-source-qualification-v1",
    "MBT source qualification V1",
)
MBT_QUALIFICATION_MEASURAND = _reference(
    "measurand", "medicine-ball-throw-source-qualification", "MBT source qualification status"
)
MBT_QUALIFICATION_METRIC = _reference(
    "metric", "medicine-ball-throw-source-qualification", "MBT source qualification status"
)
MBT_DISTANCE_SCHEMA = _reference("schema", "medicine-ball-throw-distance-v1", "MBT distance V1")
MBT_RELEASE_VELOCITY_SCHEMA = _reference(
    "schema", "medicine-ball-throw-release-velocity-v1", "MBT release velocity V1"
)

MBT_THROW_DISTANCE_MEASURAND = _reference(
    "measurand", "medicine-ball-throw-distance", "Medicine-ball throw distance"
)
MBT_INSTRUMENTED_RELEASE_VELOCITY_MEASURAND = _reference(
    "measurand",
    "medicine-ball-instrumented-release-velocity",
    "Instrumented medicine-ball release velocity",
)
MBT_THROW_DISTANCE_METRIC = _reference(
    "metric", "medicine-ball-throw-distance", "Medicine-ball throw distance"
)
MBT_INSTRUMENTED_RELEASE_VELOCITY_METRIC = _reference(
    "metric",
    "medicine-ball-instrumented-release-velocity",
    "Instrumented medicine-ball release velocity",
)

MBT_DISTANCE_COMPARABILITY_RULE = _reference(
    "comparability-rule",
    "medicine-ball-throw-distance-identity-v1",
    "MBT distance claim-relative comparability",
)
MBT_RELEASE_VELOCITY_COMPARABILITY_RULE = _reference(
    "comparability-rule",
    "medicine-ball-release-velocity-identity-v1",
    "MBT release-velocity comparability",
)
MBT_DEVICE_BRIDGE_RULE = _reference(
    "bridge-rule", "medicine-ball-throw-device-agreement-v1", "MBT device agreement bridge"
)

METER = _unit("meter", "m")
METERS_PER_SECOND = _unit("meter-per-second", "m/s")
KILOGRAM = _unit("kilogram", "kg")
SECOND = _unit("second", "s")

MBT_THROW_DISTANCE = MBT_DISTANCE_FROM_REGISTERED_COORDINATES_OPERATION
MBT_INSTRUMENTED_RELEASE_VELOCITY = MBT_INSTRUMENTED_RELEASE_VELOCITY_OPERATION


__all__ = [name for name, value in globals().items() if name.isupper() and not name.startswith("_")]
