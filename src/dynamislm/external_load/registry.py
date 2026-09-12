"""Registered external-load identities and deterministic operation references."""

from __future__ import annotations

from dynamislm.measurement.identity import RegistryReference, ScientificIdentifier, UnitReference

EXTERNAL_LOAD_REGISTRY_VERSION = "1.0.0"
SOURCE_A_MAPPING_VERSION = "unifesp-serie-a-mapping@1.1.0"
SOURCE_A_VARIABLE_REGISTRY_SHA256 = (
    "sha256:02e2019a112edf70bba425bf1f8ef719e4d03e8fb72d039c351f4f1e7754fcf0"
)


def _reference(object_type: str, key: str, label: str) -> RegistryReference:
    return RegistryReference(
        identifier=ScientificIdentifier(
            "dynamislm",
            object_type,
            key,
            EXTERNAL_LOAD_REGISTRY_VERSION,
        ),
        display_label=label,
    )


def _unit(key: str, label: str) -> UnitReference:
    return UnitReference(
        identifier=ScientificIdentifier(
            "dynamislm",
            "unit",
            key,
            EXTERNAL_LOAD_REGISTRY_VERSION,
        ),
        display_label=label,
    )


EXTERNAL_LOAD_TEST_FAMILY = _reference(
    "exposure-family", "external-load-exposure", "External load and exposure"
)
EXTERNAL_LOAD_CONSTRUCT = _reference(
    "construct", "external-load", "External load / exposure construct"
)
EXTERNAL_LOAD_SPEED_MEASURAND = _reference("measurand", "locomotor-speed", "Locomotor speed")
EXTERNAL_LOAD_DISTANCE_MEASURAND = _reference(
    "measurand", "locomotor-distance", "Locomotor distance"
)
EXTERNAL_LOAD_DURATION_MEASURAND = _reference("measurand", "exposure-duration", "Exposure duration")
EXTERNAL_LOAD_ACCELERATION_MEASURAND = _reference(
    "measurand", "locomotor-acceleration", "Locomotor acceleration"
)
EXTERNAL_LOAD_DECELERATION_MEASURAND = _reference(
    "measurand", "locomotor-deceleration", "Locomotor deceleration"
)
EXTERNAL_LOAD_PROVIDER_LOAD_MEASURAND = _reference(
    "measurand", "provider-load-output", "Provider load output"
)
EXTERNAL_LOAD_METABOLIC_POWER_MEASURAND = _reference(
    "measurand", "metabolic-power", "Metabolic power"
)

EXTERNAL_LOAD_SESSION_DURATION_METRIC = _reference(
    "metric", "session-duration", "Session/match duration"
)
EXTERNAL_LOAD_MINUTES_EXPOSURE_METRIC = _reference("metric", "minutes-exposure", "Minutes exposure")
EXTERNAL_LOAD_TOTAL_DISTANCE_METRIC = _reference("metric", "total-distance", "Total distance")
EXTERNAL_LOAD_RELATIVE_DISTANCE_METRIC = _reference(
    "metric", "relative-distance", "Duration-normalized relative distance"
)
EXTERNAL_LOAD_MAXIMUM_SPEED_METRIC = _reference("metric", "maximum-speed", "Maximum/peak speed")
EXTERNAL_LOAD_THRESHOLD_DISTANCE_METRIC = _reference(
    "metric", "threshold-distance", "Threshold-defined distance"
)
EXTERNAL_LOAD_THRESHOLD_TIME_METRIC = _reference(
    "metric", "threshold-time", "Threshold-defined time"
)
EXTERNAL_LOAD_THRESHOLD_EVENT_COUNT_METRIC = _reference(
    "metric", "threshold-event-count", "Threshold-defined event count"
)
EXTERNAL_LOAD_SPRINT_DISTANCE_METRIC = _reference("metric", "sprint-distance", "Sprint distance")
EXTERNAL_LOAD_SPRINT_TIME_METRIC = _reference("metric", "sprint-time", "Sprint time")
EXTERNAL_LOAD_SPRINT_EVENT_COUNT_METRIC = _reference(
    "metric", "sprint-event-count", "Sprint event count"
)
EXTERNAL_LOAD_ACCELERATION_EVENT_COUNT_METRIC = _reference(
    "metric", "acceleration-event-count", "Acceleration event count"
)
EXTERNAL_LOAD_DECELERATION_EVENT_COUNT_METRIC = _reference(
    "metric", "deceleration-event-count", "Deceleration event count"
)
EXTERNAL_LOAD_REPEATED_HIGH_INTENSITY_EFFORT_METRIC = _reference(
    "metric", "repeated-high-intensity-effort", "Repeated high-intensity effort"
)
EXTERNAL_LOAD_PROVIDER_LOAD_METRIC = _reference("metric", "provider-load", "Provider load output")
EXTERNAL_LOAD_SOURCE_A_PROVIDER_NORMALIZATION = _reference(
    "normalization",
    "source-a-provider-normalization",
    "Source A provider normalization",
)
EXTERNAL_LOAD_SOURCE_A_PLAYER_MATCH_AGGREGATION = _reference(
    "aggregation-rule",
    "source-a-player-match-row-v1",
    "Source A one-athlete player-match row aggregation",
)

EXTERNAL_LOAD_RAW_VELOCITY_SERIES_SCHEMA = _reference(
    "schema", "raw-velocity-series", "External-load timestamped velocity series"
)

EXTERNAL_LOAD_UNIT_NORMALIZATION_OPERATION = _reference(
    "registered-operation", "unit-normalization", "External-load unit normalization"
)
EXTERNAL_LOAD_RELATIVE_DISTANCE_OPERATION = _reference(
    "registered-operation",
    "duration-normalized-distance",
    "External-load duration-normalized distance",
)
EXTERNAL_LOAD_THRESHOLD_SUMMARY_OPERATION = _reference(
    "registered-operation",
    "velocity-threshold-summary",
    "External-load velocity threshold summary",
)
EXTERNAL_LOAD_COMPARABILITY_RULE = _reference(
    "comparability-rule",
    "external-load-measurement-identity-v1",
    "External-load measurement identity comparability V1",
)

EXTERNAL_LOAD_INPUT_PROCESSING_METHOD = _reference(
    "processing-method", "external-load-input-observation-v1", "External-load input observation"
)
EXTERNAL_LOAD_NO_FILTERING = _reference(
    "filtering-method", "no-filtering-declared-v1", "No filtering declared"
)
EXTERNAL_LOAD_NO_SMOOTHING = _reference(
    "smoothing-method", "no-smoothing-declared-v1", "No smoothing declared"
)
EXTERNAL_LOAD_NO_RESAMPLING = _reference(
    "resampling-method", "no-resampling-declared-v1", "No resampling declared"
)
EXTERNAL_LOAD_LINEAR_INTERPOLATION = _reference(
    "interpolation-method",
    "piecewise-linear-between-samples-v1",
    "Piecewise-linear interpolation between velocity samples",
)
EXTERNAL_LOAD_THRESHOLD_EVENT_DEFINITION = _reference(
    "event-definition",
    "velocity-above-threshold-v1",
    "Velocity-above-threshold event V1",
)
EXTERNAL_LOAD_THRESHOLD_EVENT_START_RULE = _reference(
    "event-rule", "threshold-entry-v1", "Threshold event entry rule V1"
)
EXTERNAL_LOAD_THRESHOLD_EVENT_END_RULE = _reference(
    "event-rule", "threshold-exit-v1", "Threshold event exit rule V1"
)
EXTERNAL_LOAD_SOURCE_A_SPRINT_EVENT_DEFINITION = _reference(
    "event-definition", "source-a-sprint-provider-v1", "Source A provider sprint event"
)
EXTERNAL_LOAD_SOURCE_A_ACCELERATION_EVENT_DEFINITION = _reference(
    "event-definition",
    "source-a-acceleration-provider-v1",
    "Source A provider acceleration event",
)
EXTERNAL_LOAD_SOURCE_A_DECELERATION_EVENT_DEFINITION = _reference(
    "event-definition",
    "source-a-deceleration-provider-v1",
    "Source A provider deceleration event",
)
EXTERNAL_LOAD_SOURCE_A_RHIE_EVENT_DEFINITION = _reference(
    "event-definition", "source-a-rhie-provider-v1", "Source A provider RHIE event"
)

EXTERNAL_LOAD_SOURCE_A_VECTOR7 = _reference(
    "device", "catapult-vector7", "Catapult VECTOR7 (Source A provider)"
)
EXTERNAL_LOAD_SOURCE_A_GNSS_ALGORITHM = _reference(
    "provider-algorithm", "catapult-gnss-source-a", "Catapult GNSS provider processing"
)
EXTERNAL_LOAD_SOURCE_A_IMA_ALGORITHM = _reference(
    "provider-algorithm", "catapult-ima-source-a", "Catapult IMA provider processing"
)
EXTERNAL_LOAD_SOURCE_A_PLAYERLOAD_ALGORITHM = _reference(
    "provider-algorithm", "catapult-playerload-source-a", "Catapult PlayerLoad provider processing"
)
EXTERNAL_LOAD_SOURCE_A_RHIE_ALGORITHM = _reference(
    "provider-algorithm", "catapult-rhie-source-a", "Catapult RHIE provider processing"
)
EXTERNAL_LOAD_SOURCE_A_MAPPING_DECISION = RegistryReference(
    identifier=ScientificIdentifier(
        "dynamislm", "decision-record", "res64-source-a-mapping", EXTERNAL_LOAD_REGISTRY_VERSION
    ),
    display_label="RES-64 Source A external-load interpretation mapping",
    reference_ids=("docs/decisions/RES64-DR-001-external-load-scientific-identity.md",),
)

# Registered unit vocabulary used by the deterministic conversion operation.
EXTERNAL_LOAD_METER = _unit("meter", "m")
EXTERNAL_LOAD_KILOMETER = _unit("kilometer", "km")
EXTERNAL_LOAD_SECOND = _unit("second", "s")
EXTERNAL_LOAD_MINUTE = _unit("minute", "min")
EXTERNAL_LOAD_METERS_PER_SECOND = _unit("meter-per-second", "m/s")
EXTERNAL_LOAD_KILOMETERS_PER_HOUR = _unit("kilometer-per-hour", "km/h")
EXTERNAL_LOAD_METERS_PER_MINUTE = _unit("meter-per-minute", "m/min")
EXTERNAL_LOAD_WATTS_PER_KILOGRAM = _unit("watt-per-kilogram", "W/kg")
EXTERNAL_LOAD_COUNT = _unit("count", "count")

# Short unit names are intentionally aliases to the registered references, not
# separate unit identities.
METER = EXTERNAL_LOAD_METER
KILOMETER = EXTERNAL_LOAD_KILOMETER
SECOND = EXTERNAL_LOAD_SECOND
MINUTE = EXTERNAL_LOAD_MINUTE
METERS_PER_SECOND = EXTERNAL_LOAD_METERS_PER_SECOND
KILOMETERS_PER_HOUR = EXTERNAL_LOAD_KILOMETERS_PER_HOUR
METERS_PER_MINUTE = EXTERNAL_LOAD_METERS_PER_MINUTE
WATTS_PER_KILOGRAM = EXTERNAL_LOAD_WATTS_PER_KILOGRAM
COUNT = EXTERNAL_LOAD_COUNT

__all__ = [
    "COUNT",
    "EXTERNAL_LOAD_ACCELERATION_EVENT_COUNT_METRIC",
    "EXTERNAL_LOAD_ACCELERATION_MEASURAND",
    "EXTERNAL_LOAD_COMPARABILITY_RULE",
    "EXTERNAL_LOAD_CONSTRUCT",
    "EXTERNAL_LOAD_COUNT",
    "EXTERNAL_LOAD_DECELERATION_EVENT_COUNT_METRIC",
    "EXTERNAL_LOAD_DECELERATION_MEASURAND",
    "EXTERNAL_LOAD_DISTANCE_MEASURAND",
    "EXTERNAL_LOAD_DURATION_MEASURAND",
    "EXTERNAL_LOAD_INPUT_PROCESSING_METHOD",
    "EXTERNAL_LOAD_KILOMETER",
    "EXTERNAL_LOAD_KILOMETERS_PER_HOUR",
    "EXTERNAL_LOAD_LINEAR_INTERPOLATION",
    "EXTERNAL_LOAD_MAXIMUM_SPEED_METRIC",
    "EXTERNAL_LOAD_METABOLIC_POWER_MEASURAND",
    "EXTERNAL_LOAD_METER",
    "EXTERNAL_LOAD_METERS_PER_MINUTE",
    "EXTERNAL_LOAD_METERS_PER_SECOND",
    "EXTERNAL_LOAD_MINUTE",
    "EXTERNAL_LOAD_MINUTES_EXPOSURE_METRIC",
    "EXTERNAL_LOAD_NO_FILTERING",
    "EXTERNAL_LOAD_NO_RESAMPLING",
    "EXTERNAL_LOAD_NO_SMOOTHING",
    "EXTERNAL_LOAD_PROVIDER_LOAD_MEASURAND",
    "EXTERNAL_LOAD_PROVIDER_LOAD_METRIC",
    "EXTERNAL_LOAD_RAW_VELOCITY_SERIES_SCHEMA",
    "EXTERNAL_LOAD_REGISTRY_VERSION",
    "EXTERNAL_LOAD_RELATIVE_DISTANCE_METRIC",
    "EXTERNAL_LOAD_RELATIVE_DISTANCE_OPERATION",
    "EXTERNAL_LOAD_REPEATED_HIGH_INTENSITY_EFFORT_METRIC",
    "EXTERNAL_LOAD_SECOND",
    "EXTERNAL_LOAD_SESSION_DURATION_METRIC",
    "EXTERNAL_LOAD_SOURCE_A_ACCELERATION_EVENT_DEFINITION",
    "EXTERNAL_LOAD_SOURCE_A_DECELERATION_EVENT_DEFINITION",
    "EXTERNAL_LOAD_SOURCE_A_GNSS_ALGORITHM",
    "EXTERNAL_LOAD_SOURCE_A_IMA_ALGORITHM",
    "EXTERNAL_LOAD_SOURCE_A_MAPPING_DECISION",
    "EXTERNAL_LOAD_SOURCE_A_PLAYERLOAD_ALGORITHM",
    "EXTERNAL_LOAD_SOURCE_A_PLAYER_MATCH_AGGREGATION",
    "EXTERNAL_LOAD_SOURCE_A_PROVIDER_NORMALIZATION",
    "EXTERNAL_LOAD_SOURCE_A_RHIE_ALGORITHM",
    "EXTERNAL_LOAD_SOURCE_A_RHIE_EVENT_DEFINITION",
    "EXTERNAL_LOAD_SOURCE_A_SPRINT_EVENT_DEFINITION",
    "EXTERNAL_LOAD_SOURCE_A_VECTOR7",
    "EXTERNAL_LOAD_SPEED_MEASURAND",
    "EXTERNAL_LOAD_SPRINT_DISTANCE_METRIC",
    "EXTERNAL_LOAD_SPRINT_EVENT_COUNT_METRIC",
    "EXTERNAL_LOAD_SPRINT_TIME_METRIC",
    "EXTERNAL_LOAD_TEST_FAMILY",
    "EXTERNAL_LOAD_THRESHOLD_DISTANCE_METRIC",
    "EXTERNAL_LOAD_THRESHOLD_EVENT_COUNT_METRIC",
    "EXTERNAL_LOAD_THRESHOLD_EVENT_DEFINITION",
    "EXTERNAL_LOAD_THRESHOLD_EVENT_END_RULE",
    "EXTERNAL_LOAD_THRESHOLD_EVENT_START_RULE",
    "EXTERNAL_LOAD_THRESHOLD_SUMMARY_OPERATION",
    "EXTERNAL_LOAD_THRESHOLD_TIME_METRIC",
    "EXTERNAL_LOAD_TOTAL_DISTANCE_METRIC",
    "EXTERNAL_LOAD_UNIT_NORMALIZATION_OPERATION",
    "EXTERNAL_LOAD_WATTS_PER_KILOGRAM",
    "KILOMETER",
    "KILOMETERS_PER_HOUR",
    "METER",
    "METERS_PER_MINUTE",
    "METERS_PER_SECOND",
    "MINUTE",
    "SECOND",
    "SOURCE_A_MAPPING_VERSION",
    "SOURCE_A_VARIABLE_REGISTRY_SHA256",
    "WATTS_PER_KILOGRAM",
]
