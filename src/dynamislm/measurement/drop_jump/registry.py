"""Explicit, family-scoped registry identities for RES-68 drop jumps."""

from __future__ import annotations

from dynamislm.measurement.identity import RegistryReference, ScientificIdentifier, UnitReference

DROP_JUMP_REGISTRY_VERSION = "1.0.0"
DROP_JUMP_SOFTWARE_VERSION = "dynamislm-res68-drop-jump-1.0.0"


def _reference(object_type: str, key: str, label: str) -> RegistryReference:
    return RegistryReference(
        identifier=ScientificIdentifier("dynamislm", object_type, key, DROP_JUMP_REGISTRY_VERSION),
        display_label=label,
    )


def _unit(key: str, label: str) -> UnitReference:
    return UnitReference(
        identifier=ScientificIdentifier("dynamislm", "unit", key, DROP_JUMP_REGISTRY_VERSION),
        display_label=label,
    )


RES68_DECISION_EXPLOSIVE_TEST_FAMILY = RegistryReference(
    identifier=ScientificIdentifier(
        "dynamislm",
        "decision-record",
        "res68-explosive-test-family-closure",
        DROP_JUMP_REGISTRY_VERSION,
    ),
    display_label="RES-68 explosive-test family closure decision",
    reference_ids=("docs/decisions/RES68-DR-001-explosive-test-family-closure.md",),
)

DROP_JUMP_TEST_FAMILY = _reference("test-family", "drop-jump", "Drop jump testing")
DROP_JUMP_CONSTRUCT = _reference(
    "construct", "drop-jump-reactive-performance", "Drop-jump reactive performance construct"
)
DROP_JUMP_PROTOCOL_V1 = _reference(
    "protocol", "drop-jump-explicit-identity-v1", "Drop-jump explicit protocol identity V1"
)

DROP_JUMP_SOURCE_OBSERVATION_OPERATION = _reference(
    "processing-method", "drop-jump-source-observation-v1", "Drop-jump source observation V1"
)
DROP_JUMP_SOURCE_QUALIFICATION_OPERATION = _reference(
    "source-adjudication-rule",
    "drop-jump-source-qualification-v1",
    "Drop-jump source qualification V1",
)
DROP_JUMP_EVENT_SCHEMA = _reference(
    "schema", "drop-jump-event-occurrence-v1", "Drop-jump event occurrence V1"
)
DROP_JUMP_METRIC_SCHEMA = _reference(
    "schema", "drop-jump-scalar-metric-v1", "Drop-jump scalar metric V1"
)
DROP_JUMP_QUALIFICATION_MEASURAND = _reference(
    "measurand", "drop-jump-source-qualification", "Drop-jump source qualification status"
)
DROP_JUMP_QUALIFICATION_METRIC = _reference(
    "metric", "drop-jump-source-qualification", "Drop-jump source qualification status"
)
DROP_JUMP_SOURCE_SERIES_MEASURAND = _reference(
    "measurand", "drop-jump-source-series", "Drop-jump source signal series"
)
DROP_JUMP_SOURCE_SERIES_METRIC = _reference(
    "metric", "drop-jump-source-series", "Drop-jump source signal series"
)

DROP_JUMP_TOUCHDOWN_EVENT_DEFINITION = _reference(
    "event-definition", "drop-jump-touchdown", "Drop-jump touchdown"
)
DROP_JUMP_REBOUND_TAKEOFF_EVENT_DEFINITION = _reference(
    "event-definition", "drop-jump-rebound-takeoff", "Drop-jump rebound takeoff"
)
DROP_JUMP_SUBSEQUENT_LANDING_EVENT_DEFINITION = _reference(
    "event-definition", "drop-jump-subsequent-landing", "Drop-jump subsequent landing"
)
DROP_JUMP_TOUCHDOWN_EVENT_METHOD = _reference(
    "event-method", "drop-jump-touchdown-registered-v1", "Drop-jump touchdown detector V1"
)
DROP_JUMP_REBOUND_TAKEOFF_EVENT_METHOD = _reference(
    "event-method",
    "drop-jump-rebound-takeoff-registered-v1",
    "Drop-jump rebound-takeoff detector V1",
)
DROP_JUMP_SUBSEQUENT_LANDING_EVENT_METHOD = _reference(
    "event-method",
    "drop-jump-subsequent-landing-registered-v1",
    "Drop-jump subsequent-landing detector V1",
)
DROP_JUMP_REGISTERED_EVENT_METHODS = (
    DROP_JUMP_TOUCHDOWN_EVENT_METHOD,
    DROP_JUMP_REBOUND_TAKEOFF_EVENT_METHOD,
    DROP_JUMP_SUBSEQUENT_LANDING_EVENT_METHOD,
)

DROP_JUMP_FLIGHT_TIME_ESTIMATOR = _reference(
    "estimator",
    "drop-jump-flight-time-ballistic-height-v1",
    "Drop-jump flight-time ballistic height",
)
DROP_JUMP_BALLISTIC_MOTION_ASSUMPTION = _reference(
    "assumption", "drop-jump-ballistic-vertical-motion-v1", "Drop-jump ballistic vertical motion"
)
DROP_JUMP_TAKEOFF_LANDING_HEIGHT_APPLICABILITY = _reference(
    "assumption",
    "drop-jump-takeoff-landing-height-applicability-v1",
    "Drop-jump takeoff/landing height applicability",
)
DROP_JUMP_NEGLIGIBLE_AIR_RESISTANCE = _reference(
    "assumption", "drop-jump-negligible-air-resistance-v1", "Drop-jump negligible air resistance"
)

DJ_GROUND_CONTACT_TIME_MEASURAND = _reference(
    "measurand", "drop-jump-ground-contact-time", "Drop-jump rebound ground-contact time"
)
DJ_REBOUND_FLIGHT_TIME_MEASURAND = _reference(
    "measurand", "drop-jump-rebound-flight-time", "Drop-jump rebound flight time"
)
DJ_FLIGHT_TIME_JUMP_HEIGHT_MEASURAND = _reference(
    "measurand",
    "drop-jump-flight-time-takeoff-to-apex-rise",
    "Drop-jump flight-time takeoff-to-apex ballistic rise",
)
DJ_RSI_JH_CT_MEASURAND = _reference(
    "measurand", "drop-jump-rsi-jh-over-ct", "Drop-jump jump-height/contact-time ratio"
)
DJ_RSR_FT_CT_MEASURAND = _reference(
    "measurand", "drop-jump-rsr-ft-over-ct", "Drop-jump flight-time/contact-time ratio"
)

DJ_GROUND_CONTACT_TIME_METRIC = _reference(
    "metric", "drop-jump-ground-contact-time", "Drop-jump ground-contact time"
)
DJ_REBOUND_FLIGHT_TIME_METRIC = _reference(
    "metric", "drop-jump-rebound-flight-time", "Drop-jump rebound flight time"
)
DJ_FLIGHT_TIME_JUMP_HEIGHT_METRIC = _reference(
    "metric", "drop-jump-flight-time-jump-height", "Drop-jump flight-time jump height"
)
DJ_RSI_JH_CT_METRIC = _reference("metric", "drop-jump-rsi-jh-ct", "Drop-jump RSI JH/CT")
DJ_RSR_FT_CT_METRIC = _reference("metric", "drop-jump-rsr-ft-ct", "Drop-jump RSR FT/CT")

DJ_GROUND_CONTACT_TIME_OPERATION = _reference(
    "registered-operation",
    "drop-jump-ground-contact-time-v1",
    "Drop-jump ground-contact time",
)
DJ_REBOUND_FLIGHT_TIME_OPERATION = _reference(
    "registered-operation",
    "drop-jump-rebound-flight-time-v1",
    "Drop-jump rebound flight time",
)
DJ_FLIGHT_TIME_JUMP_HEIGHT_OPERATION = _reference(
    "registered-operation",
    "drop-jump-flight-time-jump-height-v1",
    "Drop-jump flight-time jump-height estimate",
)
DJ_RSI_JH_CT_OPERATION = _reference(
    "registered-operation", "drop-jump-rsi-jh-ct-v1", "Drop-jump RSI JH/CT"
)
DJ_RSR_FT_CT_OPERATION = _reference(
    "registered-operation", "drop-jump-rsr-ft-ct-v1", "Drop-jump RSR FT/CT"
)

DROP_JUMP_COMPARABILITY_RULE = _reference(
    "comparability-rule", "drop-jump-identity-v1", "Drop-jump claim-relative comparability"
)
DROP_JUMP_DEVICE_BRIDGE_RULE = _reference(
    "bridge-rule", "drop-jump-device-agreement-v1", "Drop-jump device agreement bridge"
)

METER = _unit("meter", "m")
SECOND = _unit("second", "s")
METERS_PER_SECOND = _unit("meter-per-second", "m/s")
DIMENSIONLESS = _unit("dimensionless", "1")

# Readable aliases retain one identity and do not create a second wire object.
DJ_CONTACT_TIME_OPERATION = DJ_GROUND_CONTACT_TIME_OPERATION
DJ_FLIGHT_TIME_OPERATION = DJ_REBOUND_FLIGHT_TIME_OPERATION
DJ_JUMP_HEIGHT_OPERATION = DJ_FLIGHT_TIME_JUMP_HEIGHT_OPERATION
DJ_RSI_OPERATION = DJ_RSI_JH_CT_OPERATION
DJ_RSR_OPERATION = DJ_RSR_FT_CT_OPERATION
DJ_GROUND_CONTACT_TIME = DJ_GROUND_CONTACT_TIME_OPERATION
DJ_REBOUND_FLIGHT_TIME = DJ_REBOUND_FLIGHT_TIME_OPERATION
DJ_FLIGHT_TIME_JUMP_HEIGHT = DJ_FLIGHT_TIME_JUMP_HEIGHT_OPERATION
DJ_RSI_JH_CT = DJ_RSI_JH_CT_OPERATION
DJ_RSR_FT_CT = DJ_RSR_FT_CT_OPERATION


__all__ = [name for name, value in globals().items() if name.isupper() and not name.startswith("_")]
