"""Registered identities and deterministic operations for RES-67 field testing."""

from __future__ import annotations

from dynamislm.measurement.identity import RegistryReference, ScientificIdentifier, UnitReference

FIELD_TESTING_REGISTRY_VERSION = "1.0.0"
FIELD_TESTING_SOFTWARE_VERSION = "dynamislm-res67-1.0.0"


def _reference(object_type: str, key: str, label: str) -> RegistryReference:
    return RegistryReference(
        identifier=ScientificIdentifier(
            "dynamislm", object_type, key, FIELD_TESTING_REGISTRY_VERSION
        ),
        display_label=label,
    )


def _unit(key: str, label: str) -> UnitReference:
    return UnitReference(
        identifier=ScientificIdentifier("dynamislm", "unit", key, FIELD_TESTING_REGISTRY_VERSION),
        display_label=label,
    )


RES67_DECISION_FIELD_TESTING = RegistryReference(
    identifier=ScientificIdentifier(
        "dynamislm",
        "decision-record",
        "res67-field-testing-scientific-engine",
        FIELD_TESTING_REGISTRY_VERSION,
    ),
    display_label="RES-67 field-testing scientific-engine decision",
    reference_ids=("docs/decisions/RES67-DR-001-field-testing-scientific-engine.md",),
)

FIELD_TESTING_TEST_FAMILY = _reference("test-family", "field-testing", "Football field testing")
SHORT_LINEAR_SPRINT_TEST_FAMILY = _reference(
    "test-family", "short-linear-sprint", "Short linear sprint testing"
)
MAXIMUM_SPRINT_VELOCITY_TEST_FAMILY = _reference(
    "test-family", "maximum-sprint-velocity", "Maximum sprint velocity testing"
)
STANDARD_505_TEST_FAMILY = _reference(
    "test-family", "standard-505", "Standard 505 change-of-direction testing"
)
RSA_TEST_FAMILY = _reference("test-family", "repeated-sprint-ability", "Repeated-sprint ability")
IFT30_15_TEST_FAMILY = _reference("test-family", "30-15-ift", "30-15 intermittent fitness testing")

SHORT_LINEAR_SPRINT_CONSTRUCT = _reference(
    "construct", "short-linear-sprint-time", "Short linear sprint-time construct"
)
SPRINT_VELOCITY_CONSTRUCT = _reference("construct", "sprint-velocity", "Sprint velocity construct")
MAXIMUM_SPRINT_VELOCITY_CONSTRUCT = _reference(
    "construct", "maximum-sprint-velocity", "Maximum sprint velocity construct"
)
STANDARD_505_CONSTRUCT = _reference(
    "construct", "505-change-of-direction", "505 change-of-direction construct"
)
RSA_CONSTRUCT = _reference(
    "construct", "repeated-sprint-ability", "Repeated-sprint ability construct"
)
IFT30_15_CONSTRUCT = _reference(
    "construct", "30-15-intermittent-fitness", "30-15 intermittent fitness construct"
)

SHORT_LINEAR_SPRINT_PROTOCOL_V1 = _reference(
    "protocol", "short-linear-sprint-v1", "Short linear sprint protocol V1"
)
LINEAR_SPRINT_30M_PROTOCOL_V1 = _reference(
    "protocol", "linear-sprint-30m-v1", "30 m linear sprint with 0-10 m split V1"
)
STANDARD_505_PROTOCOL_V1 = _reference(
    "protocol", "standard-505-v1", "Standard 505 15 m approach / 5 m + 5 m timed V1"
)
RSA_6X40_SHUTTLE_PROTOCOL_V1 = _reference(
    "protocol", "rsa-6x40m-shuttle-20s-v1", "RSA 6 x 40 m shuttle with 20 s recovery V1"
)
IFT30_15_PROTOCOL_V1 = _reference(
    "protocol", "30-15-ift-40m-v1", "Canonical 40 m 30-15 IFT protocol V1"
)
IFT30_15_AUDIO_PACE = _reference(
    "pace-source", "30-15-ift-prerecorded-audio-v1", "Registered prerecorded 30-15 IFT audio pace"
)
IFT30_15_TERMINATION_RULE = _reference(
    "termination-rule",
    "30-15-ift-voluntary-or-three-control-zone-failures-v1",
    "Voluntary exhaustion or three consecutive control-zone failures",
)

# Readable aliases preserve one registry identity.
RSA_PROTOCOL_V1 = RSA_6X40_SHUTTLE_PROTOCOL_V1
IFT_30_15_PROTOCOL_V1 = IFT30_15_PROTOCOL_V1

SECOND = _unit("second", "s")
METER = _unit("meter", "m")
METER_PER_SECOND = _unit("meter-per-second", "m/s")
KILOMETER_PER_HOUR = _unit("kilometer-per-hour", "km/h")
PERCENT = _unit("percent", "%")

FIELD_TEST_VELOCITY_SERIES_SCHEMA = _reference(
    "schema", "field-test-velocity-series-v1", "Field-test velocity series V1"
)
FIELD_TEST_QUALIFICATION_SCHEMA = _reference(
    "schema", "field-test-source-qualification-v1", "Field-test source qualification V1"
)

FIELD_TEST_SOURCE_OBSERVATION_OPERATION = _reference(
    "processing-method", "field-test-source-observation-v1", "Field-test source observation V1"
)
PHOTOCELL_GATE_START_TRIGGER = _reference(
    "trigger", "photocell-gate-crossing-start-v1", "Photocell gate crossing start trigger"
)
PHOTOCELL_GATE_FINISH_TRIGGER = _reference(
    "trigger", "photocell-gate-crossing-finish-v1", "Photocell gate crossing finish trigger"
)
IFT_AUDIO_SIGNAL_TRIGGER = _reference(
    "trigger", "30-15-ift-audio-signal-v1", "Registered 30-15 IFT audio signal trigger"
)
SPRINT_TIMING_SOURCE_OPERATION = _reference(
    "processing-method", "sprint-timing-source-v1", "Short sprint timing source observation V1"
)
SPRINT_INTERVAL_SPLIT_OPERATION = _reference(
    "registered-operation",
    "sprint-interval-split-v1",
    "Interval split from compatible cumulative times",
)
LINEAR_SPRINT_MEAN_OPERATION = _reference(
    "registered-operation",
    "linear-sprint-mean-0-10m-reference-v1",
    "Mean qualified linear 0-10 m reference",
)
SPRINT_SEGMENT_AVERAGE_VELOCITY_OPERATION = _reference(
    "registered-operation",
    "sprint-segment-average-velocity-v1",
    "Segment-average velocity from distance and interval time",
)
SPRINT_VELOCITY_CONSTRUCT = _reference(
    "construct", "segment-sprint-velocity", "Segment sprint velocity construct"
)
SPRINT_CUMULATIVE_SPLIT_ESTIMATOR = _reference(
    "estimator", "cumulative-split-time", "Cumulative split time from timing origin"
)
SPRINT_INTERVAL_SPLIT_ESTIMATOR = _reference(
    "estimator", "interval-split-difference", "Interval split by cumulative-time difference"
)
SEGMENT_AVERAGE_VELOCITY_ESTIMATOR = _reference(
    "estimator", "segment-distance-over-interval-time", "Segment distance divided by interval time"
)
SPRINT_ACCELERATION_METHOD = _reference(
    "estimator", "sprint-acceleration-v1", "Sprint acceleration (represented, not computed)"
)

MAXIMUM_SPRINT_VELOCITY_SOURCE_OPERATION = _reference(
    "processing-method",
    "maximum-sprint-velocity-source-v1",
    "Maximum sprint velocity source series V1",
)
SAMPLED_MAXIMUM_VELOCITY_OPERATION = _reference(
    "registered-operation", "sampled-maximum-sprint-velocity-v1", "Sampled maximum sprint velocity"
)
SUSTAINED_MAXIMUM_VELOCITY_OPERATION = _reference(
    "registered-operation",
    "sustained-maximum-sprint-velocity-v1",
    "Sustained maximum sprint velocity (not computed in V1)",
)
SAMPLED_MAXIMUM_ESTIMATOR = _reference(
    "estimator", "sampled-maximum", "Maximum sampled velocity over exact support"
)
SUSTAINED_MAXIMUM_ESTIMATOR = _reference(
    "estimator", "sustained-maximum", "Velocity sustained for a registered duration"
)

STANDARD_505_SOURCE_OPERATION = _reference(
    "processing-method", "standard-505-source-v1", "Standard 505 source observation V1"
)
STANDARD_505_MEAN_OPERATION = _reference(
    "registered-operation", "standard-505-mean-of-three-v1", "Mean of three qualified 505 trials"
)
COD_DEFICIT_OPERATION = _reference(
    "registered-operation", "505-cod-deficit-mean-505-minus-mean-10m-v1", "505 COD deficit"
)
COD_DEFICIT_ESTIMATOR = _reference(
    "estimator", "mean-505-minus-mean-10m", "Mean 505 time minus mean 0-10 m time"
)
COD_ASYMMETRY_OPERATION = _reference(
    "registered-operation", "505-asymmetry-v1", "505 asymmetry (represented, not computed)"
)

RSA_SPRINT_SOURCE_OPERATION = _reference(
    "processing-method", "rsa-sprint-source-v1", "RSA repetition source observation V1"
)
RSA_AGGREGATION_OPERATION = _reference(
    "registered-operation", "rsa-complete-series-aggregation-v1", "RSA complete-series aggregation"
)
RSA_BEST_TIME_OPERATION = _reference(
    "registered-operation", "rsa-best-time-v1", "RSA best sprint time"
)
RSA_MEAN_TIME_OPERATION = _reference(
    "registered-operation", "rsa-mean-time-v1", "RSA mean sprint time"
)
RSA_TOTAL_TIME_OPERATION = _reference(
    "registered-operation", "rsa-total-time-v1", "RSA total sprint time"
)
RSA_PERCENT_DECREMENT_OPERATION = _reference(
    "registered-operation", "rsa-percent-decrement-s-dec-v1", "RSA mechanical percent decrement"
)
RSA_PERCENT_DECREMENT_ESTIMATOR = _reference(
    "estimator",
    "rsa-s-dec-total-over-best-times-n-minus-one-v1",
    "RSA S_dec = 100 x (total / (best x n) - 1)",
)
RSA_S_DEC_OPERATION = RSA_PERCENT_DECREMENT_OPERATION

IFT_STAGE_SOURCE_OPERATION = _reference(
    "processing-method", "30-15-ift-stage-source-v1", "30-15 IFT stage source observation V1"
)
IFT_TEST_SOURCE_OPERATION = _reference(
    "processing-method", "30-15-ift-test-source-v1", "30-15 IFT test source observation V1"
)
VIFT_OPERATION = _reference(
    "registered-operation", "30-15-ift-last-completed-stage-v1", "VIFT from last completed stage"
)
VIFT = VIFT_OPERATION
VIFT_ESTIMATOR = _reference(
    "estimator",
    "last-successfully-completed-stage",
    "Velocity of last successfully completed stage",
)

FIELD_TEST_SOURCE_QUALIFICATION_OPERATION = _reference(
    "source-adjudication-rule",
    "field-test-source-qualification-v1",
    "Source-qualified field-test trial/stage adjudication",
)
FIELD_TEST_QUALIFICATION_MEASURAND = _reference(
    "measurand", "field-test-source-qualification", "Field-test source qualification status"
)
FIELD_TEST_QUALIFICATION_METRIC = _reference(
    "metric", "field-test-source-qualification", "Field-test source qualification status"
)

SPLIT_TIME_MEASURAND = _reference("measurand", "sprint-time", "Sprint split time")
SPRINT_TIME_METRIC = _reference("metric", "sprint-time", "Sprint timing result")
SPRINT_CUMULATIVE_SPLIT_METRIC = _reference(
    "metric", "cumulative-split-time", "Cumulative sprint split time"
)
SPRINT_INTERVAL_SPLIT_METRIC = _reference(
    "metric", "interval-split-time", "Interval sprint split time"
)
SEGMENT_AVERAGE_VELOCITY_MEASURAND = _reference(
    "measurand", "segment-average-velocity", "Segment-average velocity"
)
SEGMENT_AVERAGE_VELOCITY_METRIC = _reference(
    "metric", "segment-average-velocity", "Segment-average velocity"
)
MAXIMUM_SPRINT_VELOCITY_MEASURAND = _reference(
    "measurand", "maximum-sprint-velocity", "Maximum sprint velocity"
)
VELOCITY_SERIES_METRIC = _reference(
    "metric", "sprint-velocity-series", "Delivered sprint velocity series"
)
MAXIMUM_SPRINT_VELOCITY_METRIC = _reference(
    "metric", "maximum-sprint-velocity", "Maximum sampled sprint velocity"
)

STANDARD_505_TIME_MEASURAND = _reference("measurand", "505-time", "Standard 505 timed result")
STANDARD_505_TIME_METRIC = _reference(
    "metric", "standard-505-time", "Standard 505 total timed result"
)
COD_DEFICIT_MEASURAND = _reference("measurand", "cod-deficit", "505 change-of-direction deficit")
COD_DEFICIT_METRIC = _reference("metric", "505-cod-deficit", "505 COD deficit")
COD_ASYMMETRY_METRIC = _reference(
    "metric", "505-asymmetry", "505 asymmetry (represented, not computed)"
)

RSA_SPRINT_TIME_MEASURAND = _reference("measurand", "rsa-sprint-time", "RSA repetition sprint time")
RSA_SPRINT_TIME_METRIC = _reference("metric", "rsa-sprint-time", "RSA repetition sprint time")
RSA_BEST_TIME_METRIC = _reference("metric", "rsa-best-time", "RSA best sprint time")
RSA_MEAN_TIME_METRIC = _reference("metric", "rsa-mean-time", "RSA mean sprint time")
RSA_TOTAL_TIME_METRIC = _reference("metric", "rsa-total-time", "RSA total sprint time")
RSA_PERCENT_DECREMENT_METRIC = _reference(
    "metric", "rsa-percent-decrement", "RSA mechanical percent decrement"
)
RSA_S_DEC_METRIC = RSA_PERCENT_DECREMENT_METRIC

IFT_STAGE_VELOCITY_MEASURAND = _reference(
    "measurand", "30-15-ift-stage-velocity", "30-15 IFT target stage velocity"
)
IFT_STAGE_VELOCITY_METRIC = _reference(
    "metric", "30-15-ift-stage-velocity", "30-15 IFT stage velocity"
)
IFT_TERMINATION_MEASURAND = _reference(
    "measurand", "30-15-ift-termination", "30-15 IFT termination reason"
)
IFT_TERMINATION_METRIC = _reference(
    "metric", "30-15-ift-termination", "30-15 IFT termination reason"
)
VIFT_MEASURAND = _reference("measurand", "vift", "30-15 IFT final velocity")
VIFT_METRIC = _reference("metric", "vift", "30-15 IFT VIFT")

MEAN_OF_THREE_QUALIFIED_TRIALS = _reference(
    "aggregation-rule",
    "mean-of-three-source-qualified-trials",
    "Mean of three source-qualified trials",
)
MEAN_OF_THREE_QUALIFIED_10M_REFERENCE = _reference(
    "selection-rule",
    "mean-of-three-qualified-0-10m-reference",
    "Mean of three qualified 0-10 m references",
)
COMPLETE_REGISTERED_REPETITIONS = _reference(
    "aggregation-rule", "complete-registered-repetitions", "Complete registered RSA repetitions"
)
QUALIFIED_SOURCE_STAGE_COMPLETION = _reference(
    "selection-rule", "qualified-last-completed-stage", "Source-qualified last completed IFT stage"
)

FIELD_TEST_COMPARABILITY_RULE = _reference(
    "comparability-rule", "field-testing-identity-v1", "Field-testing claim-relative comparability"
)
SPRINT_TIME_COMPARABILITY_RULE = _reference(
    "comparability-rule", "sprint-time-identity-v1", "Sprint-time comparability"
)
MAXIMUM_SPRINT_VELOCITY_COMPARABILITY_RULE = _reference(
    "comparability-rule",
    "maximum-sprint-velocity-identity-v1",
    "Maximum sprint velocity comparability",
)
STANDARD_505_COMPARABILITY_RULE = _reference(
    "comparability-rule", "standard-505-identity-v1", "Standard 505 comparability"
)
RSA_COMPARABILITY_RULE = _reference("comparability-rule", "rsa-identity-v1", "RSA comparability")
IFT30_15_COMPARABILITY_RULE = _reference(
    "comparability-rule", "30-15-ift-identity-v1", "30-15 IFT exact protocol comparability"
)

__all__ = [name for name, value in globals().items() if name.isupper() and not name.startswith("_")]
