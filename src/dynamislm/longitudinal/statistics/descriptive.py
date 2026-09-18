"""Deterministic descriptive longitudinal operations for RES-69."""

from __future__ import annotations

import datetime as datetime_module
import math
import statistics

from dynamislm.longitudinal.models import LongitudinalObservationEntry
from dynamislm.longitudinal.statistics.models import (
    MeasurementScaleSemanticKeyV1,
    MeasurementScaleSemantics,
    StatisticalNonComputable,
    StatisticalOperationDisposition,
    StatisticalResult,
    StatisticalSupport,
)
from dynamislm.longitudinal.statistics.registry import (
    RES69_ABSOLUTE_CHANGE_ESTIMATOR,
    RES69_ABSOLUTE_CHANGE_OPERATION,
    RES69_CHANGE_ESTIMAND,
    RES69_DIMENSIONLESS_UNIT,
    RES69_INTERCEPT_ESTIMAND,
    RES69_LOG_RATIO_ESTIMAND,
    RES69_LOG_RATIO_ESTIMATOR,
    RES69_LOG_RATIO_OPERATION,
    RES69_LOG_RATIO_UNIT,
    RES69_MAXIMUM_ESTIMAND,
    RES69_MEAN_ESTIMAND,
    RES69_MEDIAN_ESTIMAND,
    RES69_MINIMUM_ESTIMAND,
    RES69_OLS_ESTIMATOR,
    RES69_OLS_SLOPE_OPERATION,
    RES69_PERCENT_CHANGE_ESTIMAND,
    RES69_PERCENT_UNIT,
    RES69_RANGE_ESTIMAND,
    RES69_REFERENCE_WINDOW_DEVIATION_OPERATION,
    RES69_REFERENCE_Z_ESTIMAND,
    RES69_REFERENCE_Z_ESTIMATOR,
    RES69_RELATIVE_CHANGE_ESTIMAND,
    RES69_RELATIVE_CHANGE_ESTIMATOR,
    RES69_RELATIVE_CHANGE_OPERATION,
    RES69_SAMPLE_SD_ESTIMAND,
    RES69_SCALE_REGISTRY,
    RES69_SECOND_UNIT,
    RES69_SLOPE_ESTIMAND,
    RES69_UNIT_DERIVATION_OPERATION,
    RES69_WINDOW_DESCRIPTIVE_ESTIMATOR,
    RES69_WINDOW_DESCRIPTIVES_OPERATION,
    RES69_WITHIN_ATHLETE_SD_ESTIMATOR,
    RES69_WITHIN_ATHLETE_SD_OPERATION,
    MeasurementScaleRegistry,
)
from dynamislm.longitudinal.statistics.support import (
    StatisticalConstraintError,
    exact_common_unit,
    scalar_value,
    validate_comparable_entries,
    validate_statistical_support,
)
from dynamislm.longitudinal.statistics.validation import (
    make_estimate,
    make_result,
    refusal_for_exception,
    resolve_scale_semantics,
)
from dynamislm.measurement.identity import MetadataEntry, RegistryReference, UnitReference
from dynamislm.provenance.models import EvidenceReference
from dynamislm.refusal.models import RefusalResult
from dynamislm.serialization import canonical_hash


def _parameters(*items: tuple[str, str | int | float]) -> tuple[MetadataEntry, ...]:
    return tuple(MetadataEntry(key, value) for key, value in items)


def _evidence_references(support: StatisticalSupport) -> tuple[EvidenceReference, ...]:
    references = []
    for evidence in support.comparability_evidence:
        if evidence.result.rule_reference is not None:
            references.append(EvidenceReference(evidence.result.rule_reference))
    return tuple(dict.fromkeys(references))


def _validated_entries(
    support: StatisticalSupport,
    *,
    minimum: int,
) -> tuple[tuple[LongitudinalObservationEntry, ...], UnitReference, tuple[object, ...]]:
    validate_statistical_support(support)
    entries = support.included_entries
    if len(entries) < minimum:
        raise StatisticalConstraintError(
            f"at least {minimum} included observations are required",
            "RES69_DATA_ADEQUACY_INSUFFICIENT",
        )
    unit = _validated_common_unit(entries)
    authorities = validate_comparable_entries(support, entries)
    return entries, unit, authorities


def _validated_common_unit(
    entries: tuple[LongitudinalObservationEntry, ...],
) -> UnitReference:
    try:
        units = tuple(scalar_value(entry)[1] for entry in entries)
    except ValueError as exc:
        raise StatisticalConstraintError(
            "source result is not a finite scalar with an exact unit",
            "RES69_DATA_ADEQUACY_INSUFFICIENT",
        ) from exc
    unit = units[0]
    if any(item != unit for item in units[1:]):
        raise StatisticalConstraintError(
            "direct statistical arithmetic requires one exact common UnitReference",
            "RES69_UNIT_MISMATCH",
            missing_information=("registered deterministic unit conversion",),
        )
    return unit


def _pair_entries(
    support: StatisticalSupport,
    *,
    baseline_entry: LongitudinalObservationEntry | None = None,
    followup_entry: LongitudinalObservationEntry | None = None,
) -> tuple[
    LongitudinalObservationEntry, LongitudinalObservationEntry, UnitReference, tuple[object, ...]
]:
    if (baseline_entry is None) != (followup_entry is None):
        raise StatisticalConstraintError(
            "baseline and follow-up entries must be supplied together",
            "RES69_SUPPORT_MISMATCH",
        )
    if baseline_entry is None:
        entries, unit, authorities = _validated_entries(support, minimum=2)
    else:
        assert followup_entry is not None
        validate_statistical_support(support)
        selected_by_id = {entry.canonical_entry_id: entry for entry in support.included_entries}
        if (
            selected_by_id.get(baseline_entry.canonical_entry_id) != baseline_entry
            or selected_by_id.get(followup_entry.canonical_entry_id) != followup_entry
        ):
            raise StatisticalConstraintError(
                "baseline/follow-up entries must be exact included support entries",
                "RES69_SUPPORT_MISMATCH",
            )
        entries = (baseline_entry, followup_entry)
        unit = _validated_common_unit(entries)
        authorities = validate_comparable_entries(support, entries)
    if len(entries) != 2:
        raise StatisticalConstraintError(
            "the operation requires exactly two included observations",
            "RES69_ANALYSIS_DESIGN_MISMATCH",
        )
    first, second = entries
    if first.source_observation_id == second.source_observation_id:
        raise StatisticalConstraintError(
            "two-replicate or longitudinal pair contains one observation ID twice",
            "RES69_SUPPORT_MISMATCH",
        )
    if first.observed_at >= second.observed_at:
        code = (
            "RES69_DUPLICATE_TIMESTAMP"
            if first.observed_at == second.observed_at
            else "RES69_ANALYSIS_DESIGN_MISMATCH"
        )
        raise StatisticalConstraintError(
            "baseline/first observation must precede follow-up/second observation",
            code,
        )
    if first.observation.context.athlete_id != second.observation.context.athlete_id:
        raise StatisticalConstraintError(
            "longitudinal change requires one athlete",
            "RES69_ANALYSIS_DESIGN_MISMATCH",
        )
    return first, second, unit, authorities


def _scale_for_pair(
    support: StatisticalSupport,
    registry: MeasurementScaleRegistry,
) -> tuple[MeasurementScaleSemantics, MeasurementScaleSemanticKeyV1, UnitReference]:
    semantics, key, unit = resolve_scale_semantics(support, registry=registry)
    return semantics, key, unit


def _check_ratio_domain(
    baseline: float,
    followup: float,
    semantics: MeasurementScaleSemantics,
) -> None:
    if semantics.signed_value_policy.value == "STRICTLY_POSITIVE":
        if baseline <= 0 or followup <= 0:
            raise StatisticalConstraintError(
                "registered scale semantics require strictly positive ratio inputs",
                "RES69_SCALE_OPERATION_NOT_AUTHORIZED",
            )
    elif semantics.signed_value_policy.value == "NONNEGATIVE" and (baseline < 0 or followup < 0):
        raise StatisticalConstraintError(
            "registered scale semantics prohibit signed inputs",
            "RES69_SCALE_OPERATION_NOT_AUTHORIZED",
        )
    if semantics.denominator_policy.value == "STRICTLY_POSITIVE" and baseline <= 0:
        raise StatisticalConstraintError(
            "registered denominator policy requires a strictly positive baseline",
            "RES69_SCALE_OPERATION_NOT_AUTHORIZED",
        )
    if semantics.denominator_policy.value == "NONZERO" and baseline == 0:
        raise StatisticalConstraintError(
            "relative change has a zero denominator",
            "RES69_SCALE_OPERATION_NOT_AUTHORIZED",
        )


def _relative_change_value(baseline: float, followup: float) -> float:
    """Pure arithmetic helper; production authorization remains in the caller."""

    return (followup - baseline) / baseline


def _log_ratio_value(baseline: float, followup: float) -> float:
    """Pure log-ratio arithmetic helper; production authorization remains in the caller."""

    return math.log(followup) - math.log(baseline)


def calculate_absolute_change(
    support: StatisticalSupport,
    *,
    baseline_entry: LongitudinalObservationEntry | None = None,
    followup_entry: LongitudinalObservationEntry | None = None,
) -> StatisticalResult | RefusalResult:
    """Calculate follow-up minus baseline without interpretation."""

    claim = "calculate absolute longitudinal change"
    try:
        baseline, followup, unit, authorities = _pair_entries(
            support,
            baseline_entry=baseline_entry,
            followup_entry=followup_entry,
        )
        baseline_value, _ = scalar_value(baseline)
        followup_value, _ = scalar_value(followup)
        parameters = _parameters(
            ("baseline_entry_id", baseline.canonical_entry_id.qualified),
            ("followup_entry_id", followup.canonical_entry_id.qualified),
        )
        estimate = make_estimate(
            estimand=RES69_CHANGE_ESTIMAND,
            value=followup_value - baseline_value,
            unit=unit,
            estimator=RES69_ABSOLUTE_CHANGE_ESTIMATOR,
            parameters=parameters,
        )
        authority_refs = tuple(item for item in authorities if isinstance(item, RegistryReference))
        return make_result(
            support,
            operation=RES69_ABSOLUTE_CHANGE_OPERATION,
            estimator=RES69_ABSOLUTE_CHANGE_ESTIMATOR,
            estimates=(estimate,),
            parameters=parameters,
            authority_references=authority_refs,
            evidence_references=_evidence_references(support),
        )
    except (
        AttributeError,
        KeyError,
        TypeError,
        ValueError,
        ZeroDivisionError,
        OverflowError,
    ) as exc:
        return refusal_for_exception(claim, exc, support=support)


def calculate_relative_change(
    support: StatisticalSupport,
    *,
    registry: MeasurementScaleRegistry = RES69_SCALE_REGISTRY,
    ratio_scale: object | None = None,
    baseline_entry: LongitudinalObservationEntry | None = None,
    followup_entry: LongitudinalObservationEntry | None = None,
) -> StatisticalResult | RefusalResult:
    """Calculate one registered arithmetic ratio-change estimand.

    ``ratio_scale`` is accepted only as a compatibility surface and is never
    consulted for authorization; the registry is the sole scale authority.
    """

    del ratio_scale
    claim = "calculate arithmetic relative and percent longitudinal change"
    try:
        baseline, followup, _unit, authorities = _pair_entries(
            support,
            baseline_entry=baseline_entry,
            followup_entry=followup_entry,
        )
        semantics, key, _ = _scale_for_pair(support, registry)
        if not semantics.relative_change_authorized:
            raise StatisticalConstraintError(
                "registered scale semantics do not authorize arithmetic relative change",
                "RES69_SCALE_OPERATION_NOT_AUTHORIZED",
            )
        baseline_value, _ = scalar_value(baseline)
        followup_value, _ = scalar_value(followup)
        _check_ratio_domain(baseline_value, followup_value, semantics)
        relative = _relative_change_value(baseline_value, followup_value)
        percent = 100.0 * relative
        parameters = _parameters(
            ("baseline_entry_id", baseline.canonical_entry_id.qualified),
            ("followup_entry_id", followup.canonical_entry_id.qualified),
            ("scale_key", key.stable_key),
        )
        estimates = (
            make_estimate(
                estimand=RES69_RELATIVE_CHANGE_ESTIMAND,
                value=relative,
                unit=RES69_DIMENSIONLESS_UNIT,
                estimator=RES69_RELATIVE_CHANGE_ESTIMATOR,
                parameters=parameters,
            ),
            make_estimate(
                estimand=RES69_PERCENT_CHANGE_ESTIMAND,
                value=percent,
                unit=RES69_PERCENT_UNIT,
                estimator=RES69_RELATIVE_CHANGE_ESTIMATOR,
                parameters=parameters,
            ),
        )
        authority_refs = tuple(
            item
            for item in (*authorities, semantics.authority_reference)
            if isinstance(item, RegistryReference)
        )
        return make_result(
            support,
            operation=RES69_RELATIVE_CHANGE_OPERATION,
            estimator=RES69_RELATIVE_CHANGE_ESTIMATOR,
            estimates=estimates,
            parameters=parameters,
            authority_references=tuple(dict.fromkeys(authority_refs)),
            evidence_references=(*_evidence_references(support), *semantics.evidence_references),
            scale_semantic_key=key,
            scale_semantics_authority=semantics.authority_reference,
            scale_semantics_hash=canonical_hash(semantics),
            registry_version=registry.registry_version,
        )
    except (
        AttributeError,
        KeyError,
        TypeError,
        ValueError,
        ZeroDivisionError,
        OverflowError,
    ) as exc:
        return refusal_for_exception(claim, exc, support=support)


# Percent rendering is the same registered arithmetic ratio-change authority,
# not a second incompatible calculation.
calculate_percent_change = calculate_relative_change


def calculate_log_ratio_change(
    support: StatisticalSupport,
    *,
    registry: MeasurementScaleRegistry = RES69_SCALE_REGISTRY,
    log_allowed: object | None = None,
    baseline_entry: LongitudinalObservationEntry | None = None,
    followup_entry: LongitudinalObservationEntry | None = None,
) -> StatisticalResult | RefusalResult:
    """Calculate ln(follow-up / baseline) for registered positive support."""

    del log_allowed
    claim = "calculate logarithmic ratio change"
    try:
        baseline, followup, _unit, authorities = _pair_entries(
            support,
            baseline_entry=baseline_entry,
            followup_entry=followup_entry,
        )
        semantics, key, _ = _scale_for_pair(support, registry)
        if not semantics.log_ratio_authorized:
            raise StatisticalConstraintError(
                "registered scale semantics do not authorize log ratio",
                "RES69_SCALE_OPERATION_NOT_AUTHORIZED",
            )
        baseline_value, _ = scalar_value(baseline)
        followup_value, _ = scalar_value(followup)
        if baseline_value <= 0 or followup_value <= 0:
            raise StatisticalConstraintError(
                "log ratio requires strictly positive baseline and follow-up values",
                "RES69_NONPOSITIVE_LOG_INPUT",
            )
        value = _log_ratio_value(baseline_value, followup_value)
        parameters = _parameters(
            ("baseline_entry_id", baseline.canonical_entry_id.qualified),
            ("followup_entry_id", followup.canonical_entry_id.qualified),
            ("scale_key", key.stable_key),
        )
        estimate = make_estimate(
            estimand=RES69_LOG_RATIO_ESTIMAND,
            value=value,
            unit=RES69_LOG_RATIO_UNIT,
            estimator=RES69_LOG_RATIO_ESTIMATOR,
            parameters=parameters,
        )
        authority_refs = tuple(
            item
            for item in (*authorities, semantics.authority_reference)
            if isinstance(item, RegistryReference)
        )
        return make_result(
            support,
            operation=RES69_LOG_RATIO_OPERATION,
            estimator=RES69_LOG_RATIO_ESTIMATOR,
            estimates=(estimate,),
            parameters=parameters,
            authority_references=tuple(dict.fromkeys(authority_refs)),
            evidence_references=(*_evidence_references(support), *semantics.evidence_references),
            scale_semantic_key=key,
            scale_semantics_authority=semantics.authority_reference,
            scale_semantics_hash=canonical_hash(semantics),
            registry_version=registry.registry_version,
        )
    except (
        AttributeError,
        KeyError,
        TypeError,
        ValueError,
        ZeroDivisionError,
        OverflowError,
    ) as exc:
        return refusal_for_exception(claim, exc, support=support)


def _sample_sd(values: tuple[float, ...], mean: float | None = None) -> float:
    if len(values) < 2:
        raise ValueError("sample SD requires at least two values")
    average = mean if mean is not None else math.fsum(values) / len(values)
    return math.sqrt(math.fsum((value - average) ** 2 for value in values) / (len(values) - 1))


def calculate_window_descriptives(
    support: StatisticalSupport,
) -> StatisticalResult | RefusalResult:
    """Calculate mean, median, sample SD, min, max, and range for exact support."""

    claim = "calculate exact-window descriptive statistics"
    try:
        entries, unit, authorities = _validated_entries(support, minimum=1)
        values = tuple(scalar_value(entry)[0] for entry in entries)
        mean = math.fsum(values) / len(values)
        median = float(statistics.median(values))
        estimates = [
            make_estimate(
                estimand=RES69_MEAN_ESTIMAND,
                value=mean,
                unit=unit,
                estimator=RES69_WINDOW_DESCRIPTIVE_ESTIMATOR,
            ),
            make_estimate(
                estimand=RES69_MEDIAN_ESTIMAND,
                value=median,
                unit=unit,
                estimator=RES69_WINDOW_DESCRIPTIVE_ESTIMATOR,
            ),
        ]
        non_computable: tuple[StatisticalNonComputable, ...] = ()
        if len(values) >= 2:
            estimates.append(
                make_estimate(
                    estimand=RES69_SAMPLE_SD_ESTIMAND,
                    value=_sample_sd(values, mean),
                    unit=unit,
                    estimator=RES69_WINDOW_DESCRIPTIVE_ESTIMATOR,
                )
            )
        else:
            non_computable = (
                StatisticalNonComputable(
                    RES69_WINDOW_DESCRIPTIVES_OPERATION,
                    StatisticalOperationDisposition.REPRESENT_BUT_DO_NOT_COMPUTE,
                    "sample SD requires n >= 2",
                ),
            )
        estimates.extend(
            (
                make_estimate(
                    estimand=RES69_MINIMUM_ESTIMAND,
                    value=min(values),
                    unit=unit,
                    estimator=RES69_WINDOW_DESCRIPTIVE_ESTIMATOR,
                ),
                make_estimate(
                    estimand=RES69_MAXIMUM_ESTIMAND,
                    value=max(values),
                    unit=unit,
                    estimator=RES69_WINDOW_DESCRIPTIVE_ESTIMATOR,
                ),
                make_estimate(
                    estimand=RES69_RANGE_ESTIMAND,
                    value=max(values) - min(values),
                    unit=unit,
                    estimator=RES69_WINDOW_DESCRIPTIVE_ESTIMATOR,
                ),
            )
        )
        parameters = _parameters(
            ("n", len(values)), ("support_hash", support.canonical_support_hash)
        )
        authority_refs = tuple(item for item in authorities if isinstance(item, RegistryReference))
        return make_result(
            support,
            operation=RES69_WINDOW_DESCRIPTIVES_OPERATION,
            estimator=RES69_WINDOW_DESCRIPTIVE_ESTIMATOR,
            estimates=tuple(estimates),
            parameters=parameters,
            authority_references=authority_refs,
            non_computable=non_computable,
            evidence_references=_evidence_references(support),
        )
    except (
        AttributeError,
        KeyError,
        TypeError,
        ValueError,
        ZeroDivisionError,
        OverflowError,
    ) as exc:
        return refusal_for_exception(claim, exc, support=support)


def calculate_reference_window_deviation(
    support: StatisticalSupport,
) -> StatisticalResult | RefusalResult:
    """Standardize current value against an explicitly prior reference window."""

    claim = "calculate reference-window standardized deviation"
    try:
        validate_statistical_support(support)
        if support.current_entry_id is None or len(support.reference_entry_ids) < 2:
            raise StatisticalConstraintError(
                "reference deviation requires current plus at least two reference entries",
                "RES69_DATA_ADEQUACY_INSUFFICIENT",
            )
        by_id = {entry.canonical_entry_id: entry for entry in support.included_entries}
        current = by_id.get(support.current_entry_id)
        references = tuple(by_id[entry_id] for entry_id in support.reference_entry_ids)
        if current is None:
            raise StatisticalConstraintError(
                "current entry is absent from support",
                "RES69_SUPPORT_MISMATCH",
            )
        if any(reference.observed_at >= current.observed_at for reference in references):
            raise StatisticalConstraintError(
                "reference observations must precede the current observation",
                "RES69_ANALYSIS_DESIGN_MISMATCH",
            )
        entries = (*references, current)
        authorities = validate_comparable_entries(support, entries)
        exact_common_unit(entries)
        reference_values = tuple(scalar_value(entry)[0] for entry in references)
        current_value = scalar_value(current)[0]
        reference_mean = math.fsum(reference_values) / len(reference_values)
        reference_sd = _sample_sd(reference_values, reference_mean)
        if reference_sd <= 0:
            raise StatisticalConstraintError(
                "reference sample SD must be positive",
                "RES69_ZERO_REFERENCE_SD",
            )
        value = (current_value - reference_mean) / reference_sd
        parameters = _parameters(
            ("current_entry_id", current.canonical_entry_id.qualified),
            ("reference_count", len(references)),
            ("support_hash", support.canonical_support_hash),
        )
        estimate = make_estimate(
            estimand=RES69_REFERENCE_Z_ESTIMAND,
            value=value,
            unit=RES69_DIMENSIONLESS_UNIT,
            estimator=RES69_REFERENCE_Z_ESTIMATOR,
            parameters=parameters,
        )
        authority_refs = tuple(item for item in authorities if isinstance(item, RegistryReference))
        return make_result(
            support,
            operation=RES69_REFERENCE_WINDOW_DEVIATION_OPERATION,
            estimator=RES69_REFERENCE_Z_ESTIMATOR,
            estimates=(estimate,),
            parameters=parameters,
            authority_references=authority_refs,
            evidence_references=_evidence_references(support),
        )
    except (
        AttributeError,
        KeyError,
        TypeError,
        ValueError,
        ZeroDivisionError,
        OverflowError,
    ) as exc:
        return refusal_for_exception(claim, exc, support=support)


def calculate_descriptive_ols(
    support: StatisticalSupport,
) -> StatisticalResult | RefusalResult:
    """Calculate centered OLS intercept and slope using exact timestamps."""

    claim = "calculate descriptive timestamp OLS"
    try:
        entries, unit, authorities = _validated_entries(support, minimum=2)
        timestamps = tuple(entry.observed_at for entry in entries)
        if len(set(timestamps)) != len(timestamps):
            raise StatisticalConstraintError(
                "OLS requires distinct timestamps",
                "RES69_DUPLICATE_TIMESTAMP",
            )
        earliest = min(timestamps)
        x = tuple((at - earliest).total_seconds() for at in timestamps)
        y = tuple(scalar_value(entry)[0] for entry in entries)
        x_mean = math.fsum(x) / len(x)
        y_mean = math.fsum(y) / len(y)
        denominator = math.fsum((value - x_mean) ** 2 for value in x)
        if denominator <= 0:
            raise StatisticalConstraintError(
                "OLS timestamp denominator must be positive",
                "RES69_DUPLICATE_TIMESTAMP",
            )
        numerator = math.fsum(
            (x_value - x_mean) * (y_value - y_mean) for x_value, y_value in zip(x, y, strict=True)
        )
        slope = numerator / denominator
        intercept = y_mean - slope * x_mean
        from dynamislm.longitudinal.statistics.models import DerivedUnitReference

        slope_unit = DerivedUnitReference(
            numerator=unit,
            denominator=RES69_SECOND_UNIT,
            operation=RES69_UNIT_DERIVATION_OPERATION,
            display_label=f"{unit.display_label}/s",
        )
        parameters = _parameters(
            ("n", len(entries)),
            ("earliest_timestamp", earliest.astimezone(datetime_module.UTC).isoformat()),
            ("support_hash", support.canonical_support_hash),
        )
        estimates = (
            make_estimate(
                estimand=RES69_INTERCEPT_ESTIMAND,
                value=intercept,
                unit=unit,
                estimator=RES69_OLS_ESTIMATOR,
                parameters=parameters,
            ),
            make_estimate(
                estimand=RES69_SLOPE_ESTIMAND,
                value=slope,
                unit=slope_unit,
                estimator=RES69_OLS_ESTIMATOR,
                parameters=parameters,
            ),
        )
        authority_refs = tuple(item for item in authorities if isinstance(item, RegistryReference))
        return make_result(
            support,
            operation=RES69_OLS_SLOPE_OPERATION,
            estimator=RES69_OLS_ESTIMATOR,
            estimates=estimates,
            parameters=parameters,
            authority_references=authority_refs,
            evidence_references=_evidence_references(support),
        )
    except (
        AttributeError,
        KeyError,
        TypeError,
        ValueError,
        ZeroDivisionError,
        OverflowError,
    ) as exc:
        return refusal_for_exception(claim, exc, support=support)


def calculate_descriptive_within_athlete_sd(
    support: StatisticalSupport,
) -> StatisticalResult | RefusalResult:
    """Calculate descriptive within-athlete sample SD, not reliability error SD."""

    claim = "calculate descriptive within-athlete sample SD"
    try:
        entries, unit, authorities = _validated_entries(support, minimum=2)
        athlete_ids = {entry.observation.context.athlete_id for entry in entries}
        if len(athlete_ids) != 1:
            raise StatisticalConstraintError(
                "within-athlete SD requires one athlete",
                "RES69_ANALYSIS_DESIGN_MISMATCH",
            )
        values = tuple(scalar_value(entry)[0] for entry in entries)
        mean = math.fsum(values) / len(values)
        parameters = _parameters(
            ("n", len(values)), ("support_hash", support.canonical_support_hash)
        )
        estimate = make_estimate(
            estimand=RES69_SAMPLE_SD_ESTIMAND,
            value=_sample_sd(values, mean),
            unit=unit,
            estimator=RES69_WITHIN_ATHLETE_SD_ESTIMATOR,
            parameters=parameters,
        )
        authority_refs = tuple(item for item in authorities if isinstance(item, RegistryReference))
        return make_result(
            support,
            operation=RES69_WITHIN_ATHLETE_SD_OPERATION,
            estimator=RES69_WITHIN_ATHLETE_SD_ESTIMATOR,
            estimates=(estimate,),
            parameters=parameters,
            authority_references=authority_refs,
            evidence_references=_evidence_references(support),
        )
    except (
        AttributeError,
        KeyError,
        TypeError,
        ValueError,
        ZeroDivisionError,
        OverflowError,
    ) as exc:
        return refusal_for_exception(claim, exc, support=support)


# Explicit descriptive names used by the decision record.
calculate_reference_z = calculate_reference_window_deviation
calculate_ols_slope = calculate_descriptive_ols
calculate_within_athlete_sd = calculate_descriptive_within_athlete_sd
calculate_log_ratio = calculate_log_ratio_change


__all__ = [
    "calculate_absolute_change",
    "calculate_descriptive_ols",
    "calculate_descriptive_within_athlete_sd",
    "calculate_log_ratio",
    "calculate_log_ratio_change",
    "calculate_ols_slope",
    "calculate_percent_change",
    "calculate_reference_window_deviation",
    "calculate_reference_z",
    "calculate_relative_change",
    "calculate_window_descriptives",
    "calculate_within_athlete_sd",
]
