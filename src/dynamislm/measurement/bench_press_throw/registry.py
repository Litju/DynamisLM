"""Explicit, family-scoped registry identities for RES-68 bench press throws."""

from __future__ import annotations

from dynamislm.measurement.identity import RegistryReference, ScientificIdentifier, UnitReference

BPT_REGISTRY_VERSION = "1.0.0"
BPT_SOFTWARE_VERSION = "dynamislm-res68-bench-press-throw-1.0.0"


def _reference(object_type: str, key: str, label: str) -> RegistryReference:
    return RegistryReference(
        identifier=ScientificIdentifier("dynamislm", object_type, key, BPT_REGISTRY_VERSION),
        display_label=label,
    )


def _unit(key: str, label: str) -> UnitReference:
    return UnitReference(
        identifier=ScientificIdentifier("dynamislm", "unit", key, BPT_REGISTRY_VERSION),
        display_label=label,
    )


RES68_DECISION_EXPLOSIVE_TEST_FAMILY = RegistryReference(
    identifier=ScientificIdentifier(
        "dynamislm", "decision-record", "res68-explosive-test-family-closure", BPT_REGISTRY_VERSION
    ),
    display_label="RES-68 explosive-test family closure decision",
    reference_ids=("docs/decisions/RES68-DR-001-explosive-test-family-closure.md",),
)

BPT_TEST_FAMILY = _reference("test-family", "bench-press-throw", "Bench press throw testing")
BPT_CONSTRUCT = _reference(
    "construct", "upper-body-ballistic-bar-velocity", "Upper-body ballistic bar velocity"
)
BPT_PROTOCOL_V1 = _reference(
    "protocol",
    "bench-press-throw-explicit-identity-v1",
    "Bench press throw explicit protocol identity V1",
)
BPT_SOURCE_VELOCITY_SERIES_OPERATION = _reference(
    "processing-method",
    "bench-press-throw-source-velocity-series-v1",
    "BPT source velocity series V1",
)
BPT_PROVIDER_METRIC_SOURCE_OPERATION = _reference(
    "processing-method",
    "bench-press-throw-provider-metric-source-v1",
    "BPT provider metric source V1",
)
BPT_SOURCE_QUALIFICATION_OPERATION = _reference(
    "source-adjudication-rule",
    "bench-press-throw-source-qualification-v1",
    "BPT source qualification V1",
)
BPT_VELOCITY_SERIES_SCHEMA = _reference(
    "schema", "bench-press-throw-velocity-series-v1", "BPT velocity series V1"
)
BPT_SUPPORT_SCHEMA = _reference(
    "schema", "bench-press-throw-metric-support-v1", "BPT metric support V1"
)
BPT_METRIC_SCHEMA = _reference(
    "schema", "bench-press-throw-scalar-metric-v1", "BPT scalar metric V1"
)

BPT_BAR_VELOCITY_MEASURAND = _reference(
    "measurand", "bench-press-throw-bar-velocity", "Bench press throw bar velocity"
)
BPT_VELOCITY_SERIES_METRIC = _reference(
    "metric", "bench-press-throw-velocity-series", "BPT delivered bar-velocity series"
)
BPT_QUALIFICATION_MEASURAND = _reference(
    "measurand", "bench-press-throw-source-qualification", "BPT source qualification status"
)
BPT_QUALIFICATION_METRIC = _reference(
    "metric", "bench-press-throw-source-qualification", "BPT source qualification status"
)
BPT_SAMPLED_MAXIMUM_BAR_VELOCITY_MEASURAND = _reference(
    "measurand",
    "bench-press-throw-sampled-maximum-bar-velocity",
    "BPT sampled maximum bar velocity",
)
BPT_DYNAMISLM_TIME_WEIGHTED_MEAN_BAR_VELOCITY_MEASURAND = _reference(
    "measurand",
    "bench-press-throw-dynamislm-time-weighted-mean-bar-velocity",
    "BPT DynamisLM time-weighted mean bar velocity",
)
BPT_MEAN_PROPULSIVE_VELOCITY_MEASURAND = _reference(
    "measurand", "bench-press-throw-mean-propulsive-velocity", "BPT mean propulsive velocity"
)
BPT_MEAN_POWER_MEASURAND = _reference("measurand", "bench-press-throw-mean-power", "BPT mean power")
BPT_PEAK_POWER_MEASURAND = _reference("measurand", "bench-press-throw-peak-power", "BPT peak power")

BPT_SAMPLED_MAXIMUM_BAR_VELOCITY_METRIC = _reference(
    "metric", "bench-press-throw-sampled-maximum-bar-velocity", "BPT sampled maximum bar velocity"
)
BPT_DYNAMISLM_TIME_WEIGHTED_MEAN_BAR_VELOCITY_METRIC = _reference(
    "metric",
    "bench-press-throw-dynamislm-time-weighted-mean-bar-velocity",
    "BPT DynamisLM time-weighted mean bar velocity",
)
BPT_PROVIDER_MEAN_VELOCITY_METRIC = _reference(
    "metric", "bench-press-throw-provider-mean-velocity", "BPT provider-reported mean velocity"
)
BPT_PROVIDER_MAXIMUM_VELOCITY_METRIC = _reference(
    "metric",
    "bench-press-throw-provider-maximum-velocity",
    "BPT provider-reported maximum velocity",
)
BPT_PROVIDER_MEAN_PROPULSIVE_VELOCITY_METRIC = _reference(
    "metric",
    "bench-press-throw-provider-mean-propulsive-velocity",
    "BPT provider-reported mean propulsive velocity",
)
BPT_PROVIDER_MEAN_POWER_METRIC = _reference(
    "metric", "bench-press-throw-provider-mean-power", "BPT provider-reported mean power"
)
BPT_PROVIDER_PEAK_POWER_METRIC = _reference(
    "metric", "bench-press-throw-provider-peak-power", "BPT provider-reported peak power"
)

BPT_SAMPLED_MAXIMUM_BAR_VELOCITY_OPERATION = _reference(
    "registered-operation",
    "bench-press-throw-sampled-maximum-bar-velocity-v1",
    "BPT sampled maximum bar velocity",
)
BPT_DYNAMISLM_TIME_WEIGHTED_MEAN_BAR_VELOCITY_OPERATION = _reference(
    "registered-operation",
    "bench-press-throw-dynamislm-time-weighted-mean-bar-velocity-v1",
    "BPT DynamisLM time-weighted mean bar velocity",
)
BPT_MEAN_PROPULSIVE_VELOCITY_OPERATION = _reference(
    "registered-operation",
    "bench-press-throw-mean-propulsive-velocity-v1",
    "BPT mean propulsive velocity (representation only in V1)",
)

BPT_METRIC_SUPPORT_METHOD = _reference(
    "support-method", "bench-press-throw-metric-specific-support-v1", "BPT metric-specific support"
)
BPT_TIME_WEIGHTED_TRAPEZOIDAL_METHOD = _reference(
    "integration-method",
    "bench-press-throw-sample-attached-trapezoidal-v1",
    "BPT sample-attached trapezoidal time integration",
)
BPT_SAMPLED_MAXIMUM_ESTIMATOR = _reference(
    "estimator", "bench-press-throw-sampled-maximum-v1", "BPT sampled maximum over exact support"
)
BPT_TIME_WEIGHTED_MEAN_ESTIMATOR = _reference(
    "estimator",
    "bench-press-throw-time-weighted-mean-v1",
    "BPT time-weighted mean over exact support",
)
BPT_COUNTERWEIGHTED_SMITH_POWER_FUTURE_CANDIDATE = _reference(
    "future-method",
    "counterweighted-smith-bench-throw-force-power-v1",
    "Counterweighted Smith-machine bench-throw force/power future candidate",
)
BPT_COMPARABILITY_RULE = _reference(
    "comparability-rule", "bench-press-throw-identity-v1", "BPT claim-relative comparability"
)
BPT_DEVICE_BRIDGE_RULE = _reference(
    "bridge-rule", "bench-press-throw-device-agreement-v1", "BPT device agreement bridge"
)

METER_PER_SECOND = _unit("meter-per-second", "m/s")
SECOND = _unit("second", "s")
KILOGRAM = _unit("kilogram", "kg")
WATT = _unit("watt", "W")
PERCENT = _unit("percent", "%")

# Readable aliases used by clients; aliases do not add identities.
BPT_VMAX_OPERATION = BPT_SAMPLED_MAXIMUM_BAR_VELOCITY_OPERATION
BPT_DYNAMISLM_MEAN_VELOCITY_OPERATION = BPT_DYNAMISLM_TIME_WEIGHTED_MEAN_BAR_VELOCITY_OPERATION
BPT_MPV_OPERATION = BPT_MEAN_PROPULSIVE_VELOCITY_OPERATION
BPT_VMAX_METRIC = BPT_SAMPLED_MAXIMUM_BAR_VELOCITY_METRIC
BPT_DYNAMISLM_MEAN_VELOCITY_METRIC = BPT_DYNAMISLM_TIME_WEIGHTED_MEAN_BAR_VELOCITY_METRIC
BPT_MPV_METRIC = BPT_PROVIDER_MEAN_PROPULSIVE_VELOCITY_METRIC
BPT_SAMPLED_MAXIMUM_BAR_VELOCITY = BPT_SAMPLED_MAXIMUM_BAR_VELOCITY_OPERATION
BPT_DYNAMISLM_TIME_WEIGHTED_MEAN_BAR_VELOCITY = (
    BPT_DYNAMISLM_TIME_WEIGHTED_MEAN_BAR_VELOCITY_OPERATION
)
BPT_MEAN_PROPULSIVE_VELOCITY = BPT_MEAN_PROPULSIVE_VELOCITY_OPERATION


__all__ = [name for name, value in globals().items() if name.isupper() and not name.startswith("_")]
