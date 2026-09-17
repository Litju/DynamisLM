"""Registered RES-69 operation and scale-semantic identities.

This module stays family-neutral.  Family-specific scale decisions remain in
the scientific registries that own those identities; V1 accepts only exact
semantic keys supplied by this registry or explicitly marked synthetic test
registrations.
"""

from __future__ import annotations

from dataclasses import dataclass

from dynamislm.longitudinal.statistics.models import (
    MeasurementScaleSemanticKeyV1,
    MeasurementScaleSemantics,
    ScaleAuthorityOrigin,
    StatisticalOperationDisposition,
)
from dynamislm.measurement.identity import RegistryReference, ScientificIdentifier, UnitReference
from dynamislm.serialization import register_serializable_type

RES69_REGISTRY_VERSION = "1.0.0"
RES69_SOFTWARE_VERSION = "dynamislm-res69-1.0.0"


def _reference(object_type: str, key: str, label: str) -> RegistryReference:
    return RegistryReference(
        ScientificIdentifier("dynamislm", object_type, key, RES69_REGISTRY_VERSION),
        label,
    )


def _unit(key: str, label: str) -> UnitReference:
    return UnitReference(
        ScientificIdentifier("dynamislm", "unit", key, RES69_REGISTRY_VERSION),
        label,
    )


RES69_DIMENSIONLESS_UNIT = _unit("dimensionless", "1")
RES69_PERCENT_UNIT = _unit("percent", "%")
RES69_LOG_RATIO_UNIT = _unit("natural-log-ratio", "ln ratio")
RES69_SECOND_UNIT = _unit("second", "s")
RES69_UNIT_DERIVATION_OPERATION = _reference(
    "unit-derivation",
    "numerator-per-second-v1",
    "RES-69 numerator unit per elapsed second",
)

RES69_EXACT_SEMANTIC_COMPARABILITY_RULE = _reference(
    "comparability-rule",
    "exact-registered-semantic-support-v1",
    "RES-69 exact registered semantic comparability support",
)
RES69_SCALE_SEMANTICS_AUTHORITY = _reference(
    "scale-semantics",
    "measurement-scale-semantic-key-v1",
    "RES-69 measurement-scale semantic authority V1",
)

RES69_ABSOLUTE_CHANGE_OPERATION = _reference(
    "registered-operation", "longitudinal-absolute-change-v1", "RES-69 absolute change"
)
RES69_RELATIVE_CHANGE_OPERATION = _reference(
    "registered-operation", "longitudinal-relative-change-v1", "RES-69 arithmetic relative change"
)
RES69_LOG_RATIO_OPERATION = _reference(
    "registered-operation", "longitudinal-log-ratio-v1", "RES-69 logarithmic ratio change"
)
RES69_WINDOW_DESCRIPTIVES_OPERATION = _reference(
    "registered-operation", "longitudinal-window-descriptives-v1", "RES-69 window descriptives"
)
RES69_REFERENCE_WINDOW_DEVIATION_OPERATION = _reference(
    "registered-operation",
    "longitudinal-reference-window-deviation-v1",
    "RES-69 reference-window standardized deviation",
)
RES69_OLS_SLOPE_OPERATION = _reference(
    "registered-operation", "longitudinal-descriptive-ols-v1", "RES-69 descriptive timestamp OLS"
)
RES69_WITHIN_ATHLETE_SD_OPERATION = _reference(
    "registered-operation",
    "longitudinal-within-athlete-sample-sd-v1",
    "RES-69 descriptive within-athlete sample SD",
)
RES69_TWO_REPLICATE_RANDOM_ERROR_OPERATION = _reference(
    "registered-operation",
    "two-replicate-within-subject-random-error-v1",
    "RES-69 two-replicate random error",
)
RES69_RELIABILITY_DESIGN_OPERATION = _reference(
    "registered-operation", "reliability-design-authority-v1", "RES-69 reliability design authority"
)
RES69_RAW_RELATIVE_ERROR_OPERATION = _reference(
    "registered-operation",
    "two-replicate-pooled-raw-relative-error-v1",
    "RES-69 two-replicate pooled raw relative error",
)
RES69_LOG_SCALE_ERROR_OPERATION = _reference(
    "registered-operation",
    "two-replicate-log-multiplicative-error-v1",
    "RES-69 two-replicate log-multiplicative error",
)
RES69_METHOD_COMPARISON_OPERATION = _reference(
    "registered-operation", "method-comparison-ba-summary-v1", "RES-69 method-comparison summary"
)
RES69_METHOD_COMPARISON_DESIGN_OPERATION = _reference(
    "registered-operation",
    "method-comparison-design-authority-v1",
    "RES-69 method-comparison design authority",
)
RES69_CLASSICAL_BA_LIMITS_OPERATION = _reference(
    "registered-operation",
    "classical-bland-altman-limits-v1",
    "RES-69 classical Bland-Altman limits (represented only)",
)
CLASSICAL_BA_LIMITS = RES69_CLASSICAL_BA_LIMITS_OPERATION

RES69_CHANGE_ESTIMAND = _reference("estimand", "change", "absolute change")
RES69_RELATIVE_CHANGE_ESTIMAND = _reference(
    "estimand", "relative-change", "arithmetic relative change"
)
RES69_PERCENT_CHANGE_ESTIMAND = _reference("estimand", "percent-change", "percent change")
RES69_LOG_RATIO_ESTIMAND = _reference("estimand", "log-ratio", "natural log ratio")
RES69_MEAN_ESTIMAND = _reference("estimand", "mean", "arithmetic mean")
RES69_MEDIAN_ESTIMAND = _reference("estimand", "median", "median")
RES69_SAMPLE_SD_ESTIMAND = _reference("estimand", "sample-sd", "sample standard deviation")
RES69_MINIMUM_ESTIMAND = _reference("estimand", "minimum", "minimum")
RES69_MAXIMUM_ESTIMAND = _reference("estimand", "maximum", "maximum")
RES69_RANGE_ESTIMAND = _reference("estimand", "range", "range")
RES69_REFERENCE_Z_ESTIMAND = _reference(
    "estimand", "reference-window-z", "reference-window standardized deviation"
)
RES69_INTERCEPT_ESTIMAND = _reference("estimand", "ols-intercept", "descriptive OLS intercept")
RES69_SLOPE_ESTIMAND = _reference("estimand", "ols-slope", "descriptive OLS slope")
RES69_MEAN_TRIAL_SHIFT_ESTIMAND = _reference(
    "estimand", "mean-trial-shift", "mean replicate trial shift"
)
RES69_SD_DIFFERENCE_ESTIMAND = _reference(
    "estimand", "sd-difference", "sample SD of replicate differences"
)
RES69_RANDOM_ERROR_SD_ESTIMAND = _reference(
    "estimand", "random-error-sd", "two-replicate within-subject random error SD"
)
RES69_RAW_REFERENCE_MEAN_ESTIMAND = _reference(
    "estimand", "raw-pooled-grand-mean", "pooled raw two-replicate grand mean"
)
RES69_RAW_RELATIVE_ERROR_PERCENT_ESTIMAND = _reference(
    "estimand", "raw-relative-error-percent", "raw relative error percent"
)
RES69_MEAN_LOG_SHIFT_ESTIMAND = _reference("estimand", "mean-log-shift", "mean log replicate shift")
RES69_SD_LOG_DIFFERENCE_ESTIMAND = _reference(
    "estimand", "sd-log-difference", "sample SD of log replicate differences"
)
RES69_LOG_TYPICAL_ERROR_ESTIMAND = _reference(
    "estimand", "log-typical-error", "log-scale typical error"
)
RES69_MULTIPLICATIVE_FACTOR_ESTIMAND = _reference(
    "estimand", "multiplicative-factor", "multiplicative typical-error factor"
)
RES69_LOWER_FACTOR_ESTIMAND = _reference("estimand", "lower-factor", "lower multiplicative factor")
RES69_UPPER_FACTOR_ESTIMAND = _reference("estimand", "upper-factor", "upper multiplicative factor")
RES69_LOWER_PERCENT_ESTIMAND = _reference(
    "estimand", "lower-percent", "lower multiplicative percent"
)
RES69_UPPER_PERCENT_ESTIMAND = _reference(
    "estimand", "upper-percent", "upper multiplicative percent"
)
RES69_BA_BIAS_ESTIMAND = _reference("estimand", "ba-bias", "B minus A Bland-Altman bias")
RES69_BA_SD_DIFFERENCE_ESTIMAND = _reference(
    "estimand", "ba-sd-difference", "B minus A Bland-Altman SD difference"
)

RES69_ABSOLUTE_CHANGE_ESTIMATOR = _reference(
    "estimator", "absolute-change-v1", "follow-up minus baseline"
)
RES69_RELATIVE_CHANGE_ESTIMATOR = _reference(
    "estimator", "arithmetic-relative-change-v1", "arithmetic relative change"
)
RES69_LOG_RATIO_ESTIMATOR = _reference("estimator", "log-ratio-v1", "natural log ratio")
RES69_WINDOW_DESCRIPTIVE_ESTIMATOR = _reference(
    "estimator", "window-descriptives-v1", "window descriptive estimators"
)
RES69_REFERENCE_Z_ESTIMATOR = _reference(
    "estimator", "reference-window-z-v1", "current minus reference mean over reference sample SD"
)
RES69_OLS_ESTIMATOR = _reference("estimator", "descriptive-ols-v1", "centered timestamp OLS")
RES69_WITHIN_ATHLETE_SD_ESTIMATOR = _reference(
    "estimator", "within-athlete-sample-sd-v1", "descriptive within-athlete sample SD"
)
TWO_REPLICATE_WITHIN_SUBJECT_RANDOM_ERROR_SD_V1 = _reference(
    "estimator",
    "two-replicate-within-subject-random-error-sd-v1",
    "two-replicate within-subject random error SD V1",
)
TWO_REPLICATE_POOLED_RAW_GRAND_MEAN_V1 = _reference(
    "estimator",
    "two-replicate-pooled-raw-grand-mean-v1",
    "two-replicate pooled raw grand mean V1",
)
RES69_LOG_MULTIPLICATIVE_ERROR_ESTIMATOR = _reference(
    "estimator",
    "two-replicate-log-multiplicative-error-v1",
    "two-replicate log multiplicative error V1",
)
RES69_BA_ESTIMATOR = _reference(
    "estimator", "simple-bland-altman-summary-v1", "B minus A mean and sample SD"
)

SEM_FROM_REGISTERED_ICC = _reference(
    "registered-operation", "sem-from-registered-icc", "SEM from registered ICC (represented only)"
)
SEM_FROM_ICC = SEM_FROM_REGISTERED_ICC
GENERIC_SEM = _reference("registered-operation", "generic-sem", "generic SEM (rejected)")
MDC_SDC = _reference("registered-operation", "mdc-sdc", "MDC/SDC (represented only)")
ICC_VARIANTS = _reference("registered-operation", "icc-variants", "ICC variants (represented only)")
LOG_BA = _reference("registered-operation", "log-ba", "log-scale Bland-Altman (deferred)")
REPEATED_MEASURES_BA = _reference(
    "registered-operation", "repeated-measures-ba", "repeated-measures Bland-Altman (deferred)"
)
CONFIDENCE_INTERVALS = _reference(
    "registered-operation", "confidence-intervals", "confidence intervals (deferred)"
)
COVARIANCE_PROPAGATION = _reference(
    "registered-operation", "covariance-propagation", "covariance propagation (deferred)"
)
REPEATED_MEASURES_CORRELATION = _reference(
    "registered-operation",
    "repeated-measures-correlation",
    "repeated-measures correlation (deferred)",
)
MIXED_EFFECTS = _reference(
    "registered-operation", "mixed-effects", "mixed-effects models (deferred)"
)
GENERIC_MEANINGFUL_CHANGE = _reference(
    "registered-operation", "generic-meaningful-change", "generic meaningful change (rejected)"
)
READINESS_FATIGUE_INJURY_INTERPRETATION = _reference(
    "registered-operation",
    "readiness-fatigue-injury-interpretation",
    "readiness/fatigue/injury interpretation (rejected)",
)

RES69_B_MINUS_A_SIGN_CONVENTION = _reference(
    "sign-convention", "b-minus-a", "method comparison difference B minus A"
)
RES69_METHOD_COMPARISON_OCCASION_POLICY = _reference(
    "protocol-constraint",
    "same-occasion-independent-subject-pairs",
    "same occasion independent pairs",
)
RES69_METHOD_COMPARISON_PAIRING_POLICY = _reference(
    "pairing-policy", "one-pair-per-independent-subject", "one exact pair per independent subject"
)
RES69_REPLICATE_ORDERING = _reference(
    "replicate-ordering", "trial-one-then-trial-two", "registered replicate one then replicate two"
)


@register_serializable_type
@dataclass(frozen=True, slots=True)
class RegisteredStatisticalOperation:
    reference: RegistryReference
    disposition: StatisticalOperationDisposition
    estimator: RegistryReference | None
    note: str


@register_serializable_type
@dataclass(frozen=True, slots=True)
class ScaleRegistryAuditEntry:
    key: MeasurementScaleSemanticKeyV1 | None
    metric_stable_id: str
    status: str
    rationale: str


@register_serializable_type
@dataclass(frozen=True, slots=True)
class MeasurementScaleRegistry:
    entries: tuple[MeasurementScaleSemantics, ...] = ()
    registry_version: str = RES69_REGISTRY_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.entries, tuple):
            raise ValueError("scale registry entries must be an immutable tuple")
        if any(not isinstance(item, MeasurementScaleSemantics) for item in self.entries):
            raise ValueError("scale registry entries must contain MeasurementScaleSemantics values")
        keys = [item.semantic_key for item in self.entries]
        if len(set(keys)) != len(keys):
            raise ValueError(
                "RES69_REGISTRY_INTEGRITY_FAILURE: scale registry cannot contain "
                "duplicate semantic keys"
            )
        if not isinstance(self.registry_version, str) or not self.registry_version.strip():
            raise ValueError("registry_version must not be empty")

    def resolve(self, key: MeasurementScaleSemanticKeyV1) -> MeasurementScaleSemantics | None:
        if not isinstance(key, MeasurementScaleSemanticKeyV1):
            raise ValueError("scale lookup requires a MeasurementScaleSemanticKeyV1")
        matches = tuple(item for item in self.entries if item.semantic_key == key)
        if len(matches) > 1:
            raise ValueError("RES69_REGISTRY_INTEGRITY_FAILURE: conflicting scale authority")
        return matches[0] if matches else None

    def with_synthetic_entry(self, entry: MeasurementScaleSemantics) -> MeasurementScaleRegistry:
        if not isinstance(entry, MeasurementScaleSemantics):
            raise ValueError("entry must be MeasurementScaleSemantics")
        if entry.authority_origin is not ScaleAuthorityOrigin.SYNTHETIC_TEST:
            raise ValueError("only explicitly synthetic test scale authority may be added locally")
        return MeasurementScaleRegistry((*self.entries, entry), self.registry_version)


# No family-specific scale authority is imported into the generic package.
# RES-69 accepts exact production entries only after the owning scientific
# registry supplies them; synthetic test entries are explicit and local.
RES69_SCALE_REGISTRY = MeasurementScaleRegistry()
REGISTERED_SCALE_KEYS: tuple[MeasurementScaleSemanticKeyV1, ...] = ()
UNREGISTERED_SCALE_KEYS = (
    "RES34-RES68_PUBLIC_SCALAR_METRIC_IDENTITIES",
    "RES34-RES68_PROVIDER_REPORTED_SCALAR_METRICS",
    "RES34-RES68_DERIVED_SCALAR_METRIC_VARIANTS",
    "RES34-RES68_NORMALIZED_SCALAR_METRIC_VARIANTS",
)
WHY_EACH_REGISTERED_KEY_IS_AUTHORIZED: tuple[str, ...] = ()
SCALE_REGISTRY_AUDIT = tuple(
    ScaleRegistryAuditEntry(None, item, "UNREGISTERED", "No frozen RES-69 scale authority entry.")
    for item in UNREGISTERED_SCALE_KEYS
)


@register_serializable_type
@dataclass(frozen=True, slots=True)
class StatisticalOperationRegistry:
    entries: tuple[RegisteredStatisticalOperation, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.entries, tuple):
            raise ValueError("operation registry entries must be an immutable tuple")
        if any(not isinstance(item, RegisteredStatisticalOperation) for item in self.entries):
            raise ValueError("operation registry entries must be typed")
        refs = [item.reference.stable_id for item in self.entries]
        if len(set(refs)) != len(refs):
            raise ValueError("operation registry cannot contain duplicate references")

    def get(self, reference: RegistryReference) -> RegisteredStatisticalOperation | None:
        return next(
            (item for item in self.entries if item.reference.stable_id == reference.stable_id),
            None,
        )


RES69_OPERATION_REGISTRY = StatisticalOperationRegistry(
    entries=(
        RegisteredStatisticalOperation(
            RES69_ABSOLUTE_CHANGE_OPERATION,
            StatisticalOperationDisposition.IMPLEMENTED,
            RES69_ABSOLUTE_CHANGE_ESTIMATOR,
            "two-observation follow-up minus baseline",
        ),
        RegisteredStatisticalOperation(
            RES69_RELATIVE_CHANGE_OPERATION,
            StatisticalOperationDisposition.IMPLEMENTED,
            RES69_RELATIVE_CHANGE_ESTIMATOR,
            "ratio and percent share one arithmetic ratio-change estimand",
        ),
        RegisteredStatisticalOperation(
            RES69_LOG_RATIO_OPERATION,
            StatisticalOperationDisposition.IMPLEMENTED,
            RES69_LOG_RATIO_ESTIMATOR,
            "natural log ratio for registered positive ratio-scale support",
        ),
        RegisteredStatisticalOperation(
            RES69_WINDOW_DESCRIPTIVES_OPERATION,
            StatisticalOperationDisposition.IMPLEMENTED,
            RES69_WINDOW_DESCRIPTIVE_ESTIMATOR,
            "mean, median, sample SD, min, max, and range",
        ),
        RegisteredStatisticalOperation(
            RES69_REFERENCE_WINDOW_DEVIATION_OPERATION,
            StatisticalOperationDisposition.IMPLEMENTED,
            RES69_REFERENCE_Z_ESTIMATOR,
            "current value standardized against an explicitly prior reference window",
        ),
        RegisteredStatisticalOperation(
            RES69_OLS_SLOPE_OPERATION,
            StatisticalOperationDisposition.IMPLEMENTED,
            RES69_OLS_ESTIMATOR,
            "descriptive timestamp OLS slope and intercept",
        ),
        RegisteredStatisticalOperation(
            RES69_WITHIN_ATHLETE_SD_OPERATION,
            StatisticalOperationDisposition.IMPLEMENTED,
            RES69_WITHIN_ATHLETE_SD_ESTIMATOR,
            "descriptive within-athlete sample SD",
        ),
        RegisteredStatisticalOperation(
            RES69_TWO_REPLICATE_RANDOM_ERROR_OPERATION,
            StatisticalOperationDisposition.IMPLEMENTED,
            TWO_REPLICATE_WITHIN_SUBJECT_RANDOM_ERROR_SD_V1,
            "mean shift, SD difference, and SD difference divided by sqrt(2)",
        ),
        RegisteredStatisticalOperation(
            RES69_RELIABILITY_DESIGN_OPERATION,
            StatisticalOperationDisposition.IMPLEMENTED,
            None,
            "source/protocol-bound reliability design normalization",
        ),
        RegisteredStatisticalOperation(
            RES69_RAW_RELATIVE_ERROR_OPERATION,
            StatisticalOperationDisposition.IMPLEMENTED,
            TWO_REPLICATE_POOLED_RAW_GRAND_MEAN_V1,
            "raw relative error with derived pooled 2N grand mean",
        ),
        RegisteredStatisticalOperation(
            RES69_LOG_SCALE_ERROR_OPERATION,
            StatisticalOperationDisposition.IMPLEMENTED,
            RES69_LOG_MULTIPLICATIVE_ERROR_ESTIMATOR,
            "log-scale typical error with multiplicative factor interval",
        ),
        RegisteredStatisticalOperation(
            RES69_METHOD_COMPARISON_OPERATION,
            StatisticalOperationDisposition.IMPLEMENTED,
            RES69_BA_ESTIMATOR,
            "narrow B minus A Bland-Altman summary",
        ),
        RegisteredStatisticalOperation(
            RES69_METHOD_COMPARISON_DESIGN_OPERATION,
            StatisticalOperationDisposition.IMPLEMENTED,
            None,
            "source/protocol-bound method-comparison design normalization",
        ),
        RegisteredStatisticalOperation(
            RES69_CLASSICAL_BA_LIMITS_OPERATION,
            StatisticalOperationDisposition.REPRESENT_BUT_DO_NOT_COMPUTE,
            None,
            "classical limits of agreement are represented but not computed in V1",
        ),
        RegisteredStatisticalOperation(
            SEM_FROM_REGISTERED_ICC,
            StatisticalOperationDisposition.REPRESENT_BUT_DO_NOT_COMPUTE,
            None,
            "registered ICC input is not a V1 numeric authority",
        ),
        RegisteredStatisticalOperation(
            GENERIC_SEM,
            StatisticalOperationDisposition.REJECT,
            None,
            "generic SEM has no registered estimand or design",
        ),
        RegisteredStatisticalOperation(
            MDC_SDC,
            StatisticalOperationDisposition.REPRESENT_BUT_DO_NOT_COMPUTE,
            None,
            "MDC/SDC remains deferred",
        ),
        RegisteredStatisticalOperation(
            ICC_VARIANTS,
            StatisticalOperationDisposition.REPRESENT_BUT_DO_NOT_COMPUTE,
            None,
            "ICC variants remain deferred",
        ),
        RegisteredStatisticalOperation(
            LOG_BA,
            StatisticalOperationDisposition.DEFER,
            None,
            "log Bland-Altman is deferred",
        ),
        RegisteredStatisticalOperation(
            REPEATED_MEASURES_BA,
            StatisticalOperationDisposition.DEFER,
            None,
            "repeated-measures Bland-Altman is deferred",
        ),
        RegisteredStatisticalOperation(
            CONFIDENCE_INTERVALS,
            StatisticalOperationDisposition.DEFER,
            None,
            "confidence intervals are deferred",
        ),
        RegisteredStatisticalOperation(
            COVARIANCE_PROPAGATION,
            StatisticalOperationDisposition.DEFER,
            None,
            "covariance propagation is deferred",
        ),
        RegisteredStatisticalOperation(
            REPEATED_MEASURES_CORRELATION,
            StatisticalOperationDisposition.DEFER,
            None,
            "repeated-measures correlation is deferred",
        ),
        RegisteredStatisticalOperation(
            MIXED_EFFECTS,
            StatisticalOperationDisposition.DEFER,
            None,
            "mixed-effects models are deferred",
        ),
        RegisteredStatisticalOperation(
            GENERIC_MEANINGFUL_CHANGE,
            StatisticalOperationDisposition.REJECT,
            None,
            "generic meaningful change is not an authority",
        ),
        RegisteredStatisticalOperation(
            READINESS_FATIGUE_INJURY_INTERPRETATION,
            StatisticalOperationDisposition.REJECT,
            None,
            "readiness/fatigue/injury interpretation is outside RES-69",
        ),
    )
)

STATISTICAL_OPERATION_REGISTRY = RES69_OPERATION_REGISTRY
REPRESENT_BUT_DO_NOT_COMPUTE = StatisticalOperationDisposition.REPRESENT_BUT_DO_NOT_COMPUTE


def scale_semantics_for_identity(
    identity: object,
    unit: UnitReference,
    *,
    registry: MeasurementScaleRegistry = RES69_SCALE_REGISTRY,
) -> MeasurementScaleSemantics | None:
    """Resolve exact semantic scale authority; caller flags are not accepted."""

    from dynamislm.measurement.identity import MeasurementIdentity

    if not isinstance(identity, MeasurementIdentity):
        raise ValueError("identity must be a MeasurementIdentity")
    key = MeasurementScaleSemanticKeyV1.from_measurement_identity(identity, unit)
    return registry.resolve(key)


def audit_scale_registry() -> tuple[ScaleRegistryAuditEntry, ...]:
    """Return the deterministic production metric scale-registration audit."""

    return SCALE_REGISTRY_AUDIT


__all__ = [
    "CLASSICAL_BA_LIMITS",
    "CONFIDENCE_INTERVALS",
    "COVARIANCE_PROPAGATION",
    "GENERIC_MEANINGFUL_CHANGE",
    "GENERIC_SEM",
    "ICC_VARIANTS",
    "LOG_BA",
    "MDC_SDC",
    "MIXED_EFFECTS",
    "READINESS_FATIGUE_INJURY_INTERPRETATION",
    "REGISTERED_SCALE_KEYS",
    "REPEATED_MEASURES_BA",
    "REPEATED_MEASURES_CORRELATION",
    "REPRESENT_BUT_DO_NOT_COMPUTE",
    "RES69_ABSOLUTE_CHANGE_ESTIMATOR",
    "RES69_ABSOLUTE_CHANGE_OPERATION",
    "RES69_BA_BIAS_ESTIMAND",
    "RES69_BA_ESTIMATOR",
    "RES69_BA_SD_DIFFERENCE_ESTIMAND",
    "RES69_B_MINUS_A_SIGN_CONVENTION",
    "RES69_CHANGE_ESTIMAND",
    "RES69_CLASSICAL_BA_LIMITS_OPERATION",
    "RES69_DIMENSIONLESS_UNIT",
    "RES69_EXACT_SEMANTIC_COMPARABILITY_RULE",
    "RES69_INTERCEPT_ESTIMAND",
    "RES69_LOG_MULTIPLICATIVE_ERROR_ESTIMATOR",
    "RES69_LOG_RATIO_ESTIMAND",
    "RES69_LOG_RATIO_ESTIMATOR",
    "RES69_LOG_RATIO_OPERATION",
    "RES69_LOG_RATIO_UNIT",
    "RES69_LOG_SCALE_ERROR_OPERATION",
    "RES69_LOG_TYPICAL_ERROR_ESTIMAND",
    "RES69_LOWER_FACTOR_ESTIMAND",
    "RES69_LOWER_PERCENT_ESTIMAND",
    "RES69_MAXIMUM_ESTIMAND",
    "RES69_MEAN_ESTIMAND",
    "RES69_MEAN_LOG_SHIFT_ESTIMAND",
    "RES69_MEAN_TRIAL_SHIFT_ESTIMAND",
    "RES69_MEDIAN_ESTIMAND",
    "RES69_METHOD_COMPARISON_DESIGN_OPERATION",
    "RES69_METHOD_COMPARISON_OCCASION_POLICY",
    "RES69_METHOD_COMPARISON_OPERATION",
    "RES69_METHOD_COMPARISON_PAIRING_POLICY",
    "RES69_MINIMUM_ESTIMAND",
    "RES69_MULTIPLICATIVE_FACTOR_ESTIMAND",
    "RES69_OLS_ESTIMATOR",
    "RES69_OLS_SLOPE_OPERATION",
    "RES69_OPERATION_REGISTRY",
    "RES69_PERCENT_CHANGE_ESTIMAND",
    "RES69_PERCENT_UNIT",
    "RES69_RANDOM_ERROR_SD_ESTIMAND",
    "RES69_RAW_REFERENCE_MEAN_ESTIMAND",
    "RES69_RAW_RELATIVE_ERROR_OPERATION",
    "RES69_RAW_RELATIVE_ERROR_PERCENT_ESTIMAND",
    "RES69_REFERENCE_WINDOW_DEVIATION_OPERATION",
    "RES69_REFERENCE_Z_ESTIMAND",
    "RES69_REFERENCE_Z_ESTIMATOR",
    "RES69_REGISTRY_VERSION",
    "RES69_RELATIVE_CHANGE_ESTIMAND",
    "RES69_RELATIVE_CHANGE_ESTIMATOR",
    "RES69_RELATIVE_CHANGE_OPERATION",
    "RES69_RELIABILITY_DESIGN_OPERATION",
    "RES69_REPLICATE_ORDERING",
    "RES69_SAMPLE_SD_ESTIMAND",
    "RES69_SCALE_REGISTRY",
    "RES69_SCALE_SEMANTICS_AUTHORITY",
    "RES69_SD_DIFFERENCE_ESTIMAND",
    "RES69_SD_LOG_DIFFERENCE_ESTIMAND",
    "RES69_SECOND_UNIT",
    "RES69_SLOPE_ESTIMAND",
    "RES69_SOFTWARE_VERSION",
    "RES69_TWO_REPLICATE_RANDOM_ERROR_OPERATION",
    "RES69_UNIT_DERIVATION_OPERATION",
    "RES69_UPPER_FACTOR_ESTIMAND",
    "RES69_UPPER_PERCENT_ESTIMAND",
    "RES69_WINDOW_DESCRIPTIVES_OPERATION",
    "RES69_WINDOW_DESCRIPTIVE_ESTIMATOR",
    "RES69_WITHIN_ATHLETE_SD_ESTIMATOR",
    "RES69_WITHIN_ATHLETE_SD_OPERATION",
    "SCALE_REGISTRY_AUDIT",
    "SEM_FROM_ICC",
    "SEM_FROM_REGISTERED_ICC",
    "STATISTICAL_OPERATION_REGISTRY",
    "TWO_REPLICATE_POOLED_RAW_GRAND_MEAN_V1",
    "TWO_REPLICATE_WITHIN_SUBJECT_RANDOM_ERROR_SD_V1",
    "UNREGISTERED_SCALE_KEYS",
    "WHY_EACH_REGISTERED_KEY_IS_AUTHORIZED",
    "MeasurementScaleRegistry",
    "RegisteredStatisticalOperation",
    "ScaleRegistryAuditEntry",
    "StatisticalOperationRegistry",
    "audit_scale_registry",
    "scale_semantics_for_identity",
]
