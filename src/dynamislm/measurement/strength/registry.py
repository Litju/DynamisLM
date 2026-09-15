"""Explicit registry surface for the RES-66 strength scientific engine."""

from __future__ import annotations

from dynamislm.measurement.identity import RegistryReference, ScientificIdentifier, UnitReference

STRENGTH_REGISTRY_VERSION = "1.0.0"


def _reference(object_type: str, key: str, label: str) -> RegistryReference:
    return RegistryReference(
        identifier=ScientificIdentifier("dynamislm", object_type, key, STRENGTH_REGISTRY_VERSION),
        display_label=label,
    )


def _unit(key: str, label: str) -> UnitReference:
    return UnitReference(
        identifier=ScientificIdentifier("dynamislm", "unit", key, STRENGTH_REGISTRY_VERSION),
        display_label=label,
    )


RES66_DECISION_STRENGTH_IMTP_VBT = RegistryReference(
    identifier=ScientificIdentifier(
        "dynamislm", "decision-record", "res66-strength-imtp-vbt", STRENGTH_REGISTRY_VERSION
    ),
    display_label="RES-66 strength, IMTP and VBT scientific-engine decision",
    reference_ids=("docs/decisions/RES66-DR-001-strength-imtp-vbt-scientific-engine.md",),
)

STRENGTH_TEST_FAMILY = _reference("test-family", "strength", "Strength testing")
IMTP_TEST_FAMILY = _reference("test-family", "imtp", "Isometric mid-thigh pull")
SQUAT_VBT_TEST_FAMILY = _reference("test-family", "squat-vbt", "Squat velocity-based testing")
BENCH_PRESS_VBT_TEST_FAMILY = _reference(
    "test-family", "bench-press-vbt", "Bench-press velocity-based testing"
)

IMTP_CONSTRUCT = _reference("construct", "imtp-force-time", "IMTP force-time construct")
VBT_BAR_VELOCITY_CONSTRUCT = _reference(
    "construct", "barbell-velocity", "Barbell velocity construct"
)
STRENGTH_MAXIMUM_STRENGTH_CONSTRUCT = _reference(
    "construct", "maximum-strength", "Maximum-strength outcome"
)

IMTP_PROTOCOL_V1 = _reference("protocol", "imtp-v1", "IMTP explicit protocol identity V1")
SQUAT_VBT_PROTOCOL_V1 = _reference(
    "protocol", "squat-vbt-v1", "Squat VBT explicit protocol identity V1"
)
BENCH_PRESS_VBT_PROTOCOL_V1 = _reference(
    "protocol", "bench-press-vbt-v1", "Bench-press VBT explicit protocol identity V1"
)

IMTP_FORCE_TIME_SERIES_SCHEMA = _reference(
    "schema", "imtp-force-time-series-v1", "IMTP force-time series V1"
)
VBT_VELOCITY_SERIES_SCHEMA = _reference(
    "schema", "vbt-velocity-series-v1", "VBT delivered velocity series V1"
)
VBT_CONCENTRIC_PHASE_SCHEMA = _reference(
    "schema", "vbt-concentric-phase-v1", "VBT qualified concentric phase V1"
)

IMTP_INPUT_OPERATION = _reference(
    "processing-method", "imtp-force-input-v1", "IMTP force-time source observation"
)
VBT_INPUT_OPERATION = _reference(
    "processing-method", "vbt-velocity-input-v1", "VBT velocity source observation"
)

IMTP_BASELINE_SEGMENT_METHOD = _reference(
    "selection-method", "imtp-explicit-baseline-segment-v1", "IMTP explicit baseline segment"
)
IMTP_BASELINE_OPERATION = _reference(
    "registered-operation", "imtp-baseline-force-statistics-v1", "IMTP baseline force statistics"
)
IMTP_TRIAL_SUPPORT_METHOD = _reference(
    "selection-method", "imtp-explicit-trial-support-v1", "IMTP explicit trial support"
)
IMTP_ONSET_EVENT_DEFINITION = _reference(
    "event-definition", "imtp-force-onset-v1", "IMTP force onset"
)
IMTP_ONSET_BASELINE_FIVE_SD_METHOD = _reference(
    "event-method", "imtp-baseline-plus-five-sd-v1", "IMTP baseline mean plus five SD onset"
)
IMTP_ONSET_BASELINE_SD_METHOD = IMTP_ONSET_BASELINE_FIVE_SD_METHOD
IMTP_ONSET_SAMPLE_CONVENTION = _reference(
    "sample-convention", "imtp-first-qualifying-sample-v1", "IMTP first qualifying onset sample"
)
IMTP_SAMPLE_MAXIMUM_METHOD = _reference(
    "estimator", "imtp-sampled-maximum-v1", "IMTP sampled maximum"
)
IMTP_SAMPLE_PEAK_FORCE_OPERATION = _reference(
    "registered-operation", "imtp-sampled-peak-force-v1", "IMTP sampled peak-force operation"
)
IMTP_EXACT_SAMPLE_AT_TIME_METHOD = _reference(
    "estimator", "imtp-exact-registered-time-sample-v1", "IMTP exact registered-time sample"
)
IMTP_FORCE_AT_TIME_OPERATION = _reference(
    "registered-operation",
    "imtp-force-at-registered-time-v1",
    "IMTP force-at-registered-time operation",
)
IMTP_TRAPEZOIDAL_INTEGRATION_METHOD = _reference(
    "integration-method",
    "imtp-sample-attached-trapezoidal-v1",
    "IMTP sample-attached trapezoidal integration",
)
IMTP_IMPULSE_OPERATION = _reference(
    "registered-operation", "imtp-force-impulse-v1", "IMTP force impulse operation"
)
IMTP_ENDPOINT_RFD_METHOD = _reference(
    "estimator", "imtp-endpoint-average-rfd-v1", "IMTP endpoint average RFD"
)
IMTP_RFD_OPERATION = _reference(
    "registered-operation", "imtp-endpoint-average-rfd-v1", "IMTP endpoint average RFD operation"
)
IMTP_NO_INTERPOLATION_METHOD = _reference(
    "interpolation-method", "imtp-no-interpolation-v1", "IMTP no interpolation"
)
IMTP_BODY_MASS_NORMALIZATION_METHOD = _reference(
    "registered-operation", "imtp-force-body-mass-normalization-v1", "IMTP force per body mass"
)

IMTP_VERTICAL_FORCE_MEASURAND = _reference(
    "measurand", "imtp-vertical-force", "IMTP vertical force"
)
IMTP_NET_FORCE_ABOVE_BASELINE_MEASURAND = _reference(
    "measurand", "imtp-net-force-above-baseline", "IMTP net force above registered baseline"
)
IMTP_FORCE_TIME_SERIES_METRIC = _reference(
    "metric", "imtp-force-time-series", "IMTP force-time series"
)
IMTP_GROSS_PEAK_FORCE_METRIC = _reference(
    "metric", "imtp-gross-sampled-peak-force", "IMTP gross sampled peak force"
)
IMTP_NET_PEAK_FORCE_METRIC = _reference(
    "metric",
    "imtp-net-sampled-peak-force-above-baseline",
    "IMTP net sampled peak force above baseline",
)
IMTP_GROSS_FORCE_AT_TIME_METRIC = _reference(
    "metric", "imtp-gross-force-at-registered-time", "IMTP gross force at registered time"
)
IMTP_NET_FORCE_AT_TIME_METRIC = _reference(
    "metric", "imtp-net-force-at-registered-time", "IMTP net force at registered time"
)
IMTP_GROSS_IMPULSE_METRIC = _reference(
    "metric", "imtp-gross-force-impulse", "IMTP gross force impulse"
)
IMTP_NET_IMPULSE_METRIC = _reference(
    "metric", "imtp-net-force-impulse-above-baseline", "IMTP net force impulse above baseline"
)
IMTP_GROSS_RFD_METRIC = _reference(
    "metric", "imtp-gross-endpoint-average-rfd", "IMTP gross endpoint average RFD"
)
IMTP_NET_RFD_METRIC = _reference(
    "metric",
    "imtp-net-endpoint-average-rfd-above-baseline",
    "IMTP net endpoint average RFD above baseline",
)
IMTP_NORMALIZED_FORCE_METRIC = _reference(
    "metric", "imtp-force-per-body-mass", "IMTP force per body mass"
)
IMTP_NORMALIZED_FORCE_MEASURAND = _reference(
    "measurand", "imtp-force-per-body-mass", "IMTP force per body mass"
)
IMTP_BASELINE_MEAN_METRIC = _reference(
    "metric", "imtp-baseline-force-mean", "IMTP baseline force mean"
)

IMTP_FORCE_AT_50_MS_METRIC = _reference("metric", "imtp-force-at-50-ms", "IMTP force at 50 ms")
IMTP_FORCE_AT_100_MS_METRIC = _reference("metric", "imtp-force-at-100-ms", "IMTP force at 100 ms")
IMTP_FORCE_AT_150_MS_METRIC = _reference("metric", "imtp-force-at-150-ms", "IMTP force at 150 ms")
IMTP_FORCE_AT_200_MS_METRIC = _reference("metric", "imtp-force-at-200-ms", "IMTP force at 200 ms")
IMTP_RFD_0_50_MS_METRIC = _reference(
    "metric", "imtp-rfd-0-50-ms", "IMTP endpoint average RFD 0-50 ms"
)
IMTP_RFD_0_100_MS_METRIC = _reference(
    "metric", "imtp-rfd-0-100-ms", "IMTP endpoint average RFD 0-100 ms"
)
IMTP_RFD_0_150_MS_METRIC = _reference(
    "metric", "imtp-rfd-0-150-ms", "IMTP endpoint average RFD 0-150 ms"
)
IMTP_RFD_0_200_MS_METRIC = _reference(
    "metric", "imtp-rfd-0-200-ms", "IMTP endpoint average RFD 0-200 ms"
)
IMTP_IMPULSE_0_50_MS_METRIC = _reference(
    "metric", "imtp-impulse-0-50-ms", "IMTP force impulse 0-50 ms"
)
IMTP_IMPULSE_0_100_MS_METRIC = _reference(
    "metric", "imtp-impulse-0-100-ms", "IMTP force impulse 0-100 ms"
)
IMTP_IMPULSE_0_150_MS_METRIC = _reference(
    "metric", "imtp-impulse-0-150-ms", "IMTP force impulse 0-150 ms"
)
IMTP_IMPULSE_0_200_MS_METRIC = _reference(
    "metric", "imtp-impulse-0-200-ms", "IMTP force impulse 0-200 ms"
)

BODY_MASS_MEASURAND = _reference("measurand", "body-mass", "Body mass")
BODY_MASS_METRIC = _reference("metric", "body-mass", "Body mass")

IMTP_BEST_PEAK_FORCE_SELECTION = _reference(
    "aggregation-rule", "imtp-best-peak-force-v1", "IMTP best peak-force trial"
)
IMTP_MEAN_ALL_ELIGIBLE_SELECTION = _reference(
    "aggregation-rule", "imtp-mean-all-eligible-v1", "IMTP mean of all eligible trials"
)
IMTP_MEAN_BEST_N_SELECTION = _reference(
    "aggregation-rule", "imtp-mean-best-n-v1", "IMTP mean of best N trials"
)
IMTP_TRIAL_AGGREGATION_OPERATION = _reference(
    "registered-operation",
    "imtp-trial-selection-aggregation-v1",
    "IMTP explicit trial selection and aggregation",
)

VBT_CONCENTRIC_PHASE_DEFINITION = _reference(
    "phase-definition", "vbt-concentric-phase-v1", "VBT exact concentric phase"
)
VBT_EXPLICIT_CONCENTRIC_PHASE_METHOD = _reference(
    "phase-method",
    "vbt-qualified-explicit-concentric-phase-v1",
    "VBT qualified upstream explicit concentric phase",
)
VBT_PHASE_BOUNDARY_CONVENTION = _reference(
    "phase-boundary-convention",
    "vbt-inclusive-sample-boundaries-v1",
    "VBT inclusive sample phase boundaries",
)

VBT_VELOCITY_MEASURAND = _reference("measurand", "barbell-velocity", "Barbell velocity")
VBT_VELOCITY_SERIES_METRIC = _reference(
    "metric", "delivered-velocity-series", "Delivered barbell velocity series"
)
VBT_MEAN_CONCENTRIC_VELOCITY_METRIC = _reference(
    "metric", "mean-concentric-velocity", "Mean concentric velocity"
)
VBT_MEAN_PROPULSIVE_VELOCITY_METRIC = _reference(
    "metric", "mean-propulsive-velocity", "Mean propulsive velocity"
)
VBT_PEAK_VELOCITY_METRIC = _reference("metric", "peak-velocity", "Peak velocity")
VBT_MEAN_CONCENTRIC_VELOCITY_OPERATION = _reference(
    "registered-operation", "mean-concentric-velocity-v1", "VBT time-mean concentric velocity"
)
VBT_PEAK_VELOCITY_OPERATION = _reference(
    "registered-operation",
    "sampled-peak-concentric-velocity-v1",
    "VBT sampled peak concentric velocity",
)
VBT_MEAN_PROPULSIVE_VELOCITY_OPERATION = _reference(
    "registered-operation",
    "mean-propulsive-velocity-v1",
    "VBT mean propulsive velocity (unimplemented)",
)
VBT_MEAN_CONCENTRIC_VELOCITY = VBT_MEAN_CONCENTRIC_VELOCITY_OPERATION
VBT_MEAN_PROPULSIVE_VELOCITY = VBT_MEAN_PROPULSIVE_VELOCITY_OPERATION
VBT_PEAK_VELOCITY = VBT_PEAK_VELOCITY_OPERATION

VBT_FIXED_LOAD_COMPARABILITY_RULE = _reference(
    "comparability-rule",
    "vbt-fixed-load-longitudinal-v1",
    "VBT fixed-load longitudinal comparability",
)
VBT_DEVICE_BRIDGE_RULE = _reference(
    "bridge-rule", "vbt-device-agreement-bridge-v1", "VBT registered device agreement bridge"
)

VBT_MEASURED_1RM_MEASURAND = _reference(
    "measurand", "measured-one-repetition-maximum", "Measured one-repetition maximum"
)
VBT_MEASURED_1RM_METRIC = _reference("metric", "measured-one-repetition-maximum", "Measured 1RM")
VBT_MEASURED_1RM_OPERATION = _reference(
    "registered-operation",
    "measured-one-repetition-maximum-v1",
    "VBT measured successful-repetition 1RM",
)
VBT_SUCCESSFUL_REPETITION_CRITERION = _reference(
    "rep-criterion",
    "successful-repetition-explicit-v1",
    "VBT explicit successful-repetition criterion",
)
VBT_MEASURED_1RM_SELECTION_RULE = _reference(
    "selection-rule",
    "measured-1rm-explicit-successful-repetition-v1",
    "Measured 1RM explicit successful-repetition selection",
)

VBT_LOAD_VELOCITY_MODEL = _reference(
    "model", "individual-linear-load-velocity-v1", "Individual linear load-velocity model"
)
VBT_LINEAR_REGRESSION_METHOD = _reference(
    "regression-method",
    "ordinary-least-squares-linear-v1",
    "Ordinary least-squares linear regression",
)
VBT_LOAD_VELOCITY_MEASURAND = _reference(
    "measurand", "load-velocity-relationship", "Load-velocity relationship"
)
VBT_LOAD_VELOCITY_METRIC = _reference(
    "metric", "individual-linear-load-velocity", "Individual linear load-velocity relationship"
)
VBT_ESTIMATED_1RM_METRIC = _reference("metric", "estimated-one-repetition-maximum", "Estimated 1RM")
VBT_ESTIMATED_1RM_MEASURAND = _reference(
    "measurand", "estimated-one-repetition-maximum", "Estimated one-repetition maximum"
)
VBT_ESTIMATED_1RM_OPERATION = _reference(
    "registered-operation",
    "estimated-one-repetition-maximum-from-linear-load-velocity-v1",
    "Estimated 1RM from registered load-velocity model",
)
VBT_SMITH_BENCH_GENERAL_TERMINAL_VELOCITY = _reference(
    "terminal-velocity-assumption",
    "smith-bench-general-terminal-velocity-0-17-mps-v1",
    "Smith-machine bench press general 1RM velocity 0.17 m/s",
)

VBT_VELOCITY_LOSS_MEASURAND = _reference(
    "measurand", "within-set-velocity-loss", "Within-set velocity loss"
)
VBT_VELOCITY_LOSS_METRIC = _reference(
    "metric", "within-set-velocity-loss", "Within-set velocity loss"
)
VBT_VELOCITY_LOSS_OPERATION = _reference(
    "registered-operation", "within-set-velocity-loss-v1", "VBT within-set velocity loss"
)
VBT_FIRST_REPETITION_REFERENCE = _reference(
    "reference-rule",
    "velocity-loss-first-repetition-v1",
    "Velocity-loss first-repetition reference",
)
VBT_FASTEST_REPETITION_REFERENCE = _reference(
    "reference-rule",
    "velocity-loss-fastest-repetition-v1",
    "Velocity-loss fastest-repetition reference",
)
VBT_BEST_PREVIOUS_REPETITION_REFERENCE = _reference(
    "reference-rule",
    "velocity-loss-best-previous-repetition-v1",
    "Velocity-loss best-previous-repetition reference",
)

NEWTON = _unit("newton", "N")
NEWTON_SECOND = _unit("newton-second", "N·s")
NEWTON_PER_SECOND = _unit("newton-per-second", "N/s")
KILOGRAM = _unit("kilogram", "kg")
NEWTON_PER_KILOGRAM = _unit("newton-per-kilogram", "N/kg")
METER_PER_SECOND = _unit("meter-per-second", "m/s")
SECOND = _unit("second", "s")
PERCENT = _unit("percent", "%")

# Readable aliases do not create additional identities.
METERS_PER_SECOND = METER_PER_SECOND


__all__ = [name for name, value in globals().items() if name.isupper() and not name.startswith("_")]
