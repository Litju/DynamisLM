from __future__ import annotations

import datetime as datetime_module
import json
import math
from dataclasses import replace

import pytest

from dynamislm import (
    build_longitudinal_observation_entry,
    build_longitudinal_record,
    build_multi_source_analysis_input,
    canonical_hash,
    canonical_json,
    from_canonical_json,
)
from dynamislm.football.models import AthleteIdentity
from dynamislm.longitudinal.models import (
    LongitudinalAthletePerformanceRecord,
    LongitudinalObservationEntry,
    LongitudinalRecordOrigin,
    MultiSourceAnalysisInput,
    MultiSourceAnalysisScope,
)
from dynamislm.longitudinal.statistics import (
    RES69_METHOD_COMPARISON_DESIGN_OPERATION,
    RES69_RELIABILITY_DESIGN_OPERATION,
    RES69_REPLICATE_ORDERING,
    RES69_SCALE_REGISTRY,
    RES69_SCALE_SEMANTICS_AUTHORITY,
    AuthorityStatus,
    DenominatorPolicy,
    MeasurementScaleKind,
    MeasurementScaleRegistry,
    MeasurementScaleSemanticKeyV1,
    MeasurementScaleSemantics,
    MethodComparisonDesignAuthority,
    MethodComparisonPair,
    MissingnessPolicy,
    ReliabilityDesignAuthority,
    ReliabilityErrorScale,
    ReliabilityQuestion,
    ReliabilityReplicatePair,
    RES69ReasonCode,
    ScaleAuthorityOrigin,
    SignedValuePolicy,
    StableUnderlyingQuantityStatus,
    StatisticalResult,
    StatisticalSupport,
    StatisticalWindow,
    SupportEntryExclusion,
    SupportExclusionReason,
    SystematicTrialEffectAssessment,
    SystematicTrialEffectStatus,
    build_count_window_support,
    build_method_comparison_design_authority,
    build_method_comparison_design_evidence,
    build_reference_window_support,
    build_reliability_design_authority,
    build_reliability_design_evidence,
    build_statistical_support,
    build_time_window_support,
    calculate_absolute_change,
    calculate_bland_altman_summary,
    calculate_descriptive_ols,
    calculate_descriptive_within_athlete_sd,
    calculate_log_ratio_change,
    calculate_log_scale_typical_error,
    calculate_raw_relative_error_percent,
    calculate_reference_window_deviation,
    calculate_relative_change,
    calculate_sem_from_icc,
    calculate_two_replicate_random_error,
    calculate_window_descriptives,
    refuse_bland_altman_interpretation,
    request_classical_bland_altman_limits,
)
from dynamislm.measurement.cmj.registry import METER
from dynamislm.measurement.identity import (
    InstanceIdentifier,
    RegistryReference,
    ScientificIdentifier,
    SemanticIdentity,
    UnitReference,
)
from dynamislm.measurement.result import ResultStatus
from dynamislm.provenance.models import EvidenceReference
from dynamislm.refusal.models import RefusalResult
from test_longitudinal import (
    ATHLETE,
    OTHER_ATHLETE,
    UTC,
    _entry,
    _instance,
    _reference,
    _session,
)


def _synthetic_unit(key: str, label: str) -> UnitReference:
    return UnitReference(ScientificIdentifier("synthetic-res69", "unit", key, "1.0.0"), label)


CENTIMETER = _synthetic_unit("centimeter", "cm")


def _with_unit(
    entry: LongitudinalObservationEntry,
    unit: UnitReference = METER,
    *,
    identity_id: ScientificIdentifier | None = None,
    semantic: SemanticIdentity | None = None,
    status: ResultStatus | None = None,
) -> LongitudinalObservationEntry:
    identity = entry.observation.identity
    if identity_id is not None:
        identity = replace(identity, identity_id=identity_id)
    if semantic is not None:
        identity = replace(identity, semantic=semantic)
    result = replace(entry.observation.result, unit=unit)
    if status is not None:
        result = replace(result, status=status)
    observation = replace(entry.observation, identity=identity, result=result)
    return build_longitudinal_observation_entry(
        observation,
        entry.football_context,
        entry.source_qualification_bindings,
    )


def _entries(
    values: tuple[float, ...],
    *,
    prefix: str,
    athlete: AthleteIdentity = ATHLETE,
    unit: UnitReference = METER,
    method: str = "same-method",
    day: int = 1,
) -> tuple[LongitudinalObservationEntry, ...]:
    session = _session(
        f"{prefix}-session",
        datetime_module.datetime(2026, 9, day, 9, tzinfo=UTC),
    )
    result: list[LongitudinalObservationEntry] = []
    for index, value in enumerate(values):
        source = _entry(
            f"{prefix}-{index}",
            athlete=athlete,
            session=session,
            observed_at=datetime_module.datetime(2026, 9, day, 10, index, tzinfo=UTC),
            value=value,
            device_key="same-device",
            processing_method_key=method,
            processing_key=f"{prefix}-processing-{index}",
        )
        result.append(_with_unit(source, unit))
    return tuple(result)


def _record(
    entries: tuple[LongitudinalObservationEntry, ...],
) -> LongitudinalAthletePerformanceRecord:
    return build_longitudinal_record(
        entries[0].football_context.athlete,
        entries,
        LongitudinalRecordOrigin.SYNTHETIC_DETERMINISTIC,
    )


def _input(
    entries: tuple[LongitudinalObservationEntry, ...],
) -> MultiSourceAnalysisInput:
    return build_multi_source_analysis_input(
        entries[0].football_context.athlete,
        entries,
        MultiSourceAnalysisScope.SAME_SESSION,
    )


def _support(
    entries: tuple[LongitudinalObservationEntry, ...],
    *,
    included: tuple[LongitudinalObservationEntry, ...] | None = None,
    excluded: tuple[SupportEntryExclusion, ...] = (),
    window: StatisticalWindow | None = None,
    current_entry_id: InstanceIdentifier | None = None,
    reference_entry_ids: tuple[InstanceIdentifier, ...] = (),
) -> StatisticalSupport:
    record = _record(entries)
    return build_statistical_support(
        _input(entries),
        entries if included is None else included,
        source_records=(record,),
        excluded_entries=excluded,
        missingness_policy=MissingnessPolicy.NO_IMPUTATION_NO_ZERO_FILL,
        window=window,
        current_entry_id=current_entry_id,
        reference_entry_ids=reference_entry_ids,
    )


def _synthetic_scale_registry(entry: LongitudinalObservationEntry) -> MeasurementScaleRegistry:
    unit = entry.observation.result.unit
    assert unit is not None
    key = MeasurementScaleSemanticKeyV1.from_measurement_identity(
        entry.observation.identity,
        unit,
    )
    semantics = MeasurementScaleSemantics(
        semantic_key=key,
        scale_kind=MeasurementScaleKind.RATIO,
        meaningful_zero=True,
        signed_value_policy=SignedValuePolicy.STRICTLY_POSITIVE,
        denominator_policy=DenominatorPolicy.STRICTLY_POSITIVE,
        relative_change_authorized=True,
        log_ratio_authorized=True,
        raw_relative_error_authorized=True,
        log_error_authorized=True,
        authority_reference=RES69_SCALE_SEMANTICS_AUTHORITY,
        evidence_references=(EvidenceReference(_reference("evidence", "synthetic-scale")),),
        authority_origin=ScaleAuthorityOrigin.SYNTHETIC_TEST,
        rationale="Synthetic test-only scale authority; not production evidence.",
    )
    return RES69_SCALE_REGISTRY.with_synthetic_entry(semantics)


def _is_refusal(value: object, code: RES69ReasonCode) -> bool:
    return isinstance(value, RefusalResult) and code.value in value.reason_codes


def _reliability_fixture() -> tuple[
    StatisticalSupport,
    ReliabilityDesignAuthority,
    tuple[LongitudinalObservationEntry, ...],
    tuple[LongitudinalAthletePerformanceRecord, ...],
    tuple[ReliabilityReplicatePair, ...],
]:
    first = _entries((10.0, 12.0), prefix="reliability-a", athlete=ATHLETE)
    second = _entries((20.0, 23.0), prefix="reliability-b", athlete=OTHER_ATHLETE, day=2)
    entries = (*first, *second)
    records = (_record(first), _record(second))
    inputs = (_input(first), _input(second))
    support = build_statistical_support(
        inputs,
        entries,
        source_records=records,
        missingness_policy=MissingnessPolicy.NO_IMPUTATION_NO_ZERO_FILL,
    )
    pairs = (
        ReliabilityReplicatePair.from_entries(
            first[0], first[1], occasion_id=_instance("occasion", "a")
        ),
        ReliabilityReplicatePair.from_entries(
            second[0], second[1], occasion_id=_instance("occasion", "b")
        ),
    )
    authority = _build_reliability_authority(support, entries, records, pairs)
    return support, authority, entries, records, pairs


def _build_reliability_authority(
    support: StatisticalSupport,
    entries: tuple[LongitudinalObservationEntry, ...],
    records: tuple[LongitudinalAthletePerformanceRecord, ...],
    pairs: tuple[ReliabilityReplicatePair, ...],
    *,
    error_scale: ReliabilityErrorScale = ReliabilityErrorScale.RAW_ABSOLUTE,
    balanced_design: bool = True,
    replicate_ordering: RegistryReference | None = None,
) -> ReliabilityDesignAuthority:
    first = entries[0]
    protocol = first.observation.identity.semantic.protocol
    assert protocol is not None
    evidence = build_reliability_design_evidence(
        support=support,
        source_records=records,
        study_identity=_reference("study", "reliability-study"),
        replicate_pairs=pairs,
        replicate_ordering=replicate_ordering or RES69_REPLICATE_ORDERING,
        target_measurement_identity_ids=tuple(
            entry.observation.identity.identity_id for entry in entries
        ),
        target_construct=first.observation.identity.semantic.construct,
        target_test_family=first.observation.identity.semantic.test_family,
        target_measurand=first.observation.identity.semantic.measurand,
        target_metric_definition=first.observation.identity.semantic.metric_definition,
        target_unit=METER,
        protocol_reference=protocol,
        evidence_references=(EvidenceReference(_reference("evidence", "reliability-design")),),
        repeatability_question=ReliabilityQuestion.REPEATABILITY,
        stable_underlying_quantity=StableUnderlyingQuantityStatus.SUPPORTED,
        systematic_trial_effect=SystematicTrialEffectAssessment(
            SystematicTrialEffectStatus.SYSTEMATIC_EFFECT_PRESENT,
            (EvidenceReference(_reference("evidence", "systematic-effect")),),
            "The protocol assessed a systematic trial effect; the mean shift remains "
            "separate from random error.",
        ),
        error_scale=error_scale,
        missingness_policy=MissingnessPolicy.NO_IMPUTATION_NO_ZERO_FILL,
        balanced_design=balanced_design,
        producing_method=RES69_RELIABILITY_DESIGN_OPERATION,
    )
    return build_reliability_design_authority(evidence)


def test_absolute_relative_percent_and_log_ratio_gold_cases() -> None:
    entries = _entries((10.0, 12.0), prefix="change")
    support = _support(entries)
    absolute = calculate_absolute_change(support)
    assert isinstance(absolute, StatisticalResult)
    assert absolute.estimate("change").value == 2.0
    assert absolute.estimate("change").unit == METER

    registry = _synthetic_scale_registry(entries[0])
    relative = calculate_relative_change(support, registry=registry)
    assert isinstance(relative, StatisticalResult)
    assert relative.estimate("relative-change").value == pytest.approx(0.2)
    assert relative.estimate("percent-change").value == pytest.approx(20.0)
    log_ratio = calculate_log_ratio_change(support, registry=registry)
    assert isinstance(log_ratio, StatisticalResult)
    assert log_ratio.estimate("log-ratio").value == pytest.approx(math.log(1.2))


def test_exact_unit_and_identity_rules_fail_closed() -> None:
    entries = _entries((10.0, 12.0), prefix="unit-mismatch")
    changed = _with_unit(entries[1], CENTIMETER)
    result = calculate_absolute_change(_support((entries[0], changed)))
    assert _is_refusal(result, RES69ReasonCode.UNIT_MISMATCH)

    semantic = replace(
        entries[1].observation.identity.semantic,
        metric_definition=_reference("metric", "different-metric"),
    )
    identity_changed = _with_unit(entries[1], semantic=semantic)
    result = calculate_absolute_change(_support((entries[0], identity_changed)))
    assert _is_refusal(result, RES69ReasonCode.IDENTITY_UNRESOLVED)

    invalid = _with_unit(entries[1], status=ResultStatus.INVALID)
    result = calculate_absolute_change(_support((entries[0], invalid)))
    assert isinstance(result, RefusalResult)
    assert result.observation_ids

    reversed_result = calculate_absolute_change(
        _support(entries),
        baseline_entry=entries[1],
        followup_entry=entries[0],
    )
    assert isinstance(reversed_result, RefusalResult)


def test_scale_registry_requires_registered_semantics_and_ignores_caller_flags() -> None:
    entries = _entries((10.0, 12.0), prefix="scale-gate")
    support = _support(entries)
    assert _is_refusal(
        calculate_relative_change(support, ratio_scale=True),
        RES69ReasonCode.SCALE_SEMANTICS_UNREGISTERED,
    )
    semantics_registry = _synthetic_scale_registry(entries[0])
    result = calculate_relative_change(support, registry=semantics_registry, ratio_scale=True)
    assert isinstance(result, StatisticalResult)

    interval = replace(
        semantics_registry.entries[-1],
        scale_kind=MeasurementScaleKind.INTERVAL,
        meaningful_zero=False,
        signed_value_policy=SignedValuePolicy.SIGNED,
        denominator_policy=DenominatorPolicy.NONZERO,
        relative_change_authorized=False,
        log_ratio_authorized=False,
        raw_relative_error_authorized=False,
        log_error_authorized=False,
    )
    interval_registry = MeasurementScaleRegistry(
        tuple(
            item
            for item in semantics_registry.entries
            if item.semantic_key != interval.semantic_key
        )
    ).with_synthetic_entry(interval)
    assert _is_refusal(
        calculate_relative_change(support, registry=interval_registry),
        RES69ReasonCode.SCALE_OPERATION_NOT_AUTHORIZED,
    )


def test_scale_key_uses_semantics_not_instance_identity() -> None:
    first, second = _entries((10.0, 12.0), prefix="scale-key")
    first_unit = first.observation.result.unit
    second_unit = second.observation.result.unit
    assert first_unit is not None and second_unit is not None
    first_key = MeasurementScaleSemanticKeyV1.from_measurement_identity(
        first.observation.identity,
        first_unit,
    )
    second_key = MeasurementScaleSemanticKeyV1.from_measurement_identity(
        second.observation.identity,
        second_unit,
    )
    assert first.observation.identity.identity_id != second.observation.identity.identity_id
    assert first_key == second_key
    assert first_key.stable_key == second_key.stable_key


def test_count_time_and_one_value_window_descriptives() -> None:
    entries = _entries((1.0, 3.0, 5.0), prefix="window")
    record = _record(entries)
    analysis_input = _input(entries)
    count_support = build_count_window_support(analysis_input, 2, source_records=(record,))
    result = calculate_window_descriptives(count_support)
    assert isinstance(result, StatisticalResult)
    assert result.estimate("mean").value == pytest.approx(4.0)
    assert result.estimate("median").value == pytest.approx(4.0)
    assert result.estimate("sample-sd").value == pytest.approx(math.sqrt(2.0))
    assert result.estimate("minimum").value == 3.0
    assert result.estimate("maximum").value == 5.0
    assert result.estimate("range").value == 2.0
    assert len(count_support.excluded_entries) == 1

    time_support = build_time_window_support(
        analysis_input,
        entries[1].observed_at,
        entries[2].observed_at,
        start_inclusive=True,
        end_inclusive=False,
        source_records=(record,),
    )
    time_result = calculate_window_descriptives(time_support)
    assert isinstance(time_result, StatisticalResult)
    assert time_result.estimate("mean").value == 3.0
    assert time_support.window.end_inclusive is False

    one_support = build_statistical_support(
        analysis_input,
        (entries[0],),
        source_records=(record,),
        excluded_entries=(
            SupportEntryExclusion.from_entry(entries[1], SupportExclusionReason.NOT_SELECTED),
            SupportEntryExclusion.from_entry(entries[2], SupportExclusionReason.NOT_SELECTED),
        ),
    )
    one_result = calculate_window_descriptives(one_support)
    assert isinstance(one_result, StatisticalResult)
    assert one_result.estimate("range").value == 0.0
    assert one_result.non_computable


def test_missing_window_entries_cannot_be_silently_dropped() -> None:
    entries = _entries((1.0, 2.0, 3.0), prefix="missing-window")
    with pytest.raises(ValueError, match="explicit"):
        build_statistical_support(
            _input(entries),
            entries[:2],
            source_records=(_record(entries),),
        )


def test_reference_window_deviation_excludes_current_and_rejects_zero_sd() -> None:
    entries = _entries((1.0, 3.0, 5.0), prefix="reference")
    support = build_reference_window_support(
        _input(entries), entries[2], entries[:2], source_records=(_record(entries),)
    )
    result = calculate_reference_window_deviation(support)
    assert isinstance(result, StatisticalResult)
    assert result.estimate("reference-window-z").value == pytest.approx(3.0 / math.sqrt(2.0))
    assert entries[2].canonical_entry_id not in support.reference_entry_ids

    zero = _entries((2.0, 2.0, 3.0), prefix="reference-zero")
    result = calculate_reference_window_deviation(
        build_reference_window_support(
            _input(zero), zero[2], zero[:2], source_records=(_record(zero),)
        )
    )
    assert _is_refusal(result, RES69ReasonCode.ZERO_REFERENCE_SD)


def test_ols_uses_exact_irregular_timestamps_and_rejects_duplicates() -> None:
    entries = _entries((2.0, 8.0, 23.0), prefix="ols-irregular")
    irregular = tuple(
        build_longitudinal_observation_entry(
            replace(
                entry.observation,
                context=replace(
                    entry.observation.context,
                    observed_at=datetime_module.datetime(2026, 9, 1, 10, tzinfo=UTC)
                    + datetime_module.timedelta(seconds=seconds),
                ),
            ),
            entry.football_context,
            entry.source_qualification_bindings,
        )
        for entry, seconds in zip(entries, (0, 2, 7), strict=True)
    )
    result = calculate_descriptive_ols(_support(irregular))
    assert isinstance(result, StatisticalResult)
    assert result.estimate("ols-intercept").value == pytest.approx(2.0)
    assert result.estimate("ols-slope").value == pytest.approx(3.0)
    assert result.estimate("ols-intercept").unit == METER
    from dynamislm.longitudinal.statistics import DerivedUnitReference

    slope_unit = result.estimate("ols-slope").unit
    assert isinstance(slope_unit, DerivedUnitReference)
    assert slope_unit.numerator == METER

    duplicate = _with_unit(entries[1])
    duplicate = build_longitudinal_observation_entry(
        replace(
            duplicate.observation,
            context=replace(duplicate.observation.context, observed_at=entries[0].observed_at),
        ),
        duplicate.football_context,
        duplicate.source_qualification_bindings,
    )
    result = calculate_descriptive_ols(_support((entries[0], duplicate)))
    assert _is_refusal(result, RES69ReasonCode.DUPLICATE_TIMESTAMP)


def test_descriptive_within_athlete_sd_is_distinct_from_reliability() -> None:
    result = calculate_descriptive_within_athlete_sd(
        _support(_entries((1.0, 3.0, 5.0), prefix="sd"))
    )
    assert isinstance(result, StatisticalResult)
    assert result.estimate("sample-sd").value == pytest.approx(2.0)
    assert result.estimate("sample-sd").estimator.identifier.key == "within-athlete-sample-sd-v1"


def test_two_replicate_random_error_and_source_bound_gate() -> None:
    support, authority, _entries_value, _records, _pairs = _reliability_fixture()
    result = calculate_two_replicate_random_error(support, authority)
    assert isinstance(result, StatisticalResult)
    assert result.estimate("mean-trial-shift").value == pytest.approx(2.5)
    assert result.estimate("sd-difference").value == pytest.approx(math.sqrt(0.5))
    assert result.estimate("random-error-sd").value == pytest.approx(0.5)
    assert authority.is_source_bound
    unverified = replace(
        authority, authority_status=AuthorityStatus.UNVERIFIED, authority_token=None
    )
    assert _is_refusal(
        calculate_two_replicate_random_error(support, unverified),
        RES69ReasonCode.RELIABILITY_AUTHORITY_REQUIRED,
    )


def test_reliability_n_one_unbalanced_and_wrong_order_refuse() -> None:
    entries = _entries((10.0, 12.0), prefix="reliability-one")
    support = _support(entries)
    pair = ReliabilityReplicatePair.from_entries(entries[0], entries[1])
    authority = _build_reliability_authority(support, entries, (_record(entries),), (pair,))
    assert _is_refusal(
        calculate_two_replicate_random_error(support, authority),
        RES69ReasonCode.DATA_ADEQUACY_INSUFFICIENT,
    )

    unbalanced = _build_reliability_authority(
        support, entries, (_record(entries),), (pair,), balanced_design=False
    )
    assert isinstance(calculate_two_replicate_random_error(support, unbalanced), RefusalResult)

    wrong_order = _reference("replicate-ordering", "wrong")
    with pytest.raises(ValueError):
        _build_reliability_authority(
            support,
            entries,
            (_record(entries),),
            (pair,),
            replicate_ordering=wrong_order,
        )


def test_raw_relative_error_uses_only_derived_pooled_grand_mean() -> None:
    support, authority, entries, records, pairs = _reliability_fixture()
    raw_authority = _build_reliability_authority(
        support, entries, records, pairs, error_scale=ReliabilityErrorScale.RAW_RELATIVE
    )
    result = calculate_raw_relative_error_percent(
        support,
        raw_authority,
        registry=_synthetic_scale_registry(entries[0]),
    )
    assert isinstance(result, StatisticalResult)
    assert result.estimate("raw-pooled-grand-mean").value == pytest.approx(16.25)
    assert result.estimate("raw-relative-error-percent").value == pytest.approx(100.0 * 0.5 / 16.25)
    supplied = calculate_raw_relative_error_percent(
        support,
        raw_authority,
        registry=_synthetic_scale_registry(entries[0]),
        denominator=1.0,
    )
    assert _is_refusal(supplied, RES69ReasonCode.SUPPORT_MISMATCH)

    log_authority = _build_reliability_authority(
        support, entries, records, pairs, error_scale=ReliabilityErrorScale.LOG_MULTIPLICATIVE
    )
    assert _is_refusal(
        calculate_raw_relative_error_percent(
            support, log_authority, registry=_synthetic_scale_registry(entries[0])
        ),
        RES69ReasonCode.ANALYSIS_DESIGN_MISMATCH,
    )


def test_log_typical_error_has_factor_interval_not_symmetric_percent() -> None:
    support, authority, entries, records, pairs = _reliability_fixture()
    log_authority = _build_reliability_authority(
        support, entries, records, pairs, error_scale=ReliabilityErrorScale.LOG_MULTIPLICATIVE
    )
    result = calculate_log_scale_typical_error(
        support,
        log_authority,
        registry=_synthetic_scale_registry(entries[0]),
    )
    assert isinstance(result, StatisticalResult)
    te = result.estimate("log-typical-error").value
    lower = result.estimate("lower-factor").value
    upper = result.estimate("upper-factor").value
    assert upper == pytest.approx(math.exp(te))
    assert lower == pytest.approx(1.0 / upper)
    assert result.estimate("lower-percent").value == pytest.approx(100.0 * (1.0 - lower))
    assert result.estimate("upper-percent").value == pytest.approx(100.0 * (upper - 1.0))
    assert result.estimate("lower-percent").value != pytest.approx(
        result.estimate("upper-percent").value
    )

    negative = _entries((0.0, 1.0), prefix="log-negative")
    support_negative = _support(negative)
    negative_authority = _build_reliability_authority(
        support_negative,
        negative,
        (_record(negative),),
        (ReliabilityReplicatePair.from_entries(negative[0], negative[1]),),
        error_scale=ReliabilityErrorScale.LOG_MULTIPLICATIVE,
    )
    result = calculate_log_scale_typical_error(
        support_negative,
        negative_authority,
        registry=_synthetic_scale_registry(negative[0]),
    )
    assert isinstance(result, RefusalResult)


def test_sem_from_icc_remains_non_callable() -> None:
    result = calculate_sem_from_icc()
    assert _is_refusal(result, RES69ReasonCode.OPERATION_NOT_REGISTERED)


def _method_comparison_fixture() -> tuple[
    StatisticalSupport,
    MethodComparisonDesignAuthority,
    tuple[LongitudinalObservationEntry, ...],
    tuple[LongitudinalAthletePerformanceRecord, ...],
]:
    common_a = ScientificIdentifier("synthetic-res69", "measurement-identity", "method-a", "1.0.0")
    common_b = ScientificIdentifier("synthetic-res69", "measurement-identity", "method-b", "1.0.0")

    def pair_entries(
        prefix: str,
        athlete: AthleteIdentity,
        day: int,
    ) -> tuple[LongitudinalObservationEntry, ...]:
        session = _session(
            f"{prefix}-session",
            datetime_module.datetime(2026, 9, day, 9, tzinfo=UTC),
        )
        method_a = _with_unit(
            _entry(
                f"{prefix}-a",
                athlete=athlete,
                session=session,
                observed_at=datetime_module.datetime(2026, 9, day, 10, tzinfo=UTC),
                value=10.0 if athlete is ATHLETE else 20.0,
                device_key="method-a-device",
                processing_method_key="method-a",
                processing_key=f"{prefix}-a-processing",
            ),
            identity_id=common_a,
        )
        method_b = _with_unit(
            _entry(
                f"{prefix}-b",
                athlete=athlete,
                session=session,
                observed_at=datetime_module.datetime(2026, 9, day, 10, 1, tzinfo=UTC),
                value=12.0 if athlete is ATHLETE else 23.0,
                device_key="method-b-device",
                processing_method_key="method-b",
                processing_key=f"{prefix}-b-processing",
            ),
            identity_id=common_b,
        )
        return method_a, method_b

    first = pair_entries("ba-a", ATHLETE, 1)
    second = pair_entries("ba-b", OTHER_ATHLETE, 2)
    entries = (*first, *second)
    records = (_record(first), _record(second))
    inputs = (_input(first), _input(second))
    support = build_statistical_support(
        inputs,
        entries,
        source_records=records,
        missingness_policy=MissingnessPolicy.NO_IMPUTATION_NO_ZERO_FILL,
    )
    pairs = (
        MethodComparisonPair.from_entries(
            first[0], first[1], occasion_id=_instance("occasion", "ba-a")
        ),
        MethodComparisonPair.from_entries(
            second[0], second[1], occasion_id=_instance("occasion", "ba-b")
        ),
    )
    evidence = build_method_comparison_design_evidence(
        support=support,
        source_records=records,
        design_identity=_reference("study", "method-comparison"),
        pairs=pairs,
        method_a_identity=common_a,
        method_b_identity=common_b,
        target_construct=first[0].observation.identity.semantic.construct,
        target_measurand=first[0].observation.identity.semantic.measurand,
        metric_a_definition=first[0].observation.identity.semantic.metric_definition,
        metric_b_definition=first[1].observation.identity.semantic.metric_definition,
        unit_a=METER,
        unit_b=METER,
        evidence_references=(EvidenceReference(_reference("evidence", "method-comparison")),),
        producing_method=RES69_METHOD_COMPARISON_DESIGN_OPERATION,
    )
    return support, build_method_comparison_design_authority(evidence), entries, records


def test_bland_altman_summary_is_narrow_and_allows_method_difference() -> None:
    support, authority, _entries_value, _records = _method_comparison_fixture()
    result = calculate_bland_altman_summary(support, authority)
    assert isinstance(result, StatisticalResult)
    assert result.estimate("ba-bias").value == pytest.approx(2.5)
    assert result.estimate("ba-sd-difference").value == pytest.approx(math.sqrt(0.5))
    assert all("loa" not in estimate.estimand.identifier.key for estimate in result.estimates)
    assert _is_refusal(
        request_classical_bland_altman_limits(support, authority),
        RES69ReasonCode.CLASSICAL_LOA_DEFERRED,
    )
    assert _is_refusal(
        refuse_bland_altman_interpretation(support),
        RES69ReasonCode.INTERPRETATION_NOT_AUTHORIZED,
    )


def test_method_comparison_direct_mint_and_unit_mismatch_are_blocked() -> None:
    support, authority, entries, records = _method_comparison_fixture()
    unverified = replace(
        authority, authority_status=AuthorityStatus.UNVERIFIED, authority_token=None
    )
    assert _is_refusal(
        calculate_bland_altman_summary(support, unverified),
        RES69ReasonCode.METHOD_COMPARISON_AUTHORITY_REQUIRED,
    )
    bad_evidence = build_method_comparison_design_evidence(
        support=support,
        source_records=records,
        design_identity=_reference("study", "ba-bad-unit"),
        pairs=authority.pairs,
        method_a_identity=authority.method_a_identity,
        method_b_identity=authority.method_b_identity,
        target_construct=authority.target_construct,
        target_measurand=authority.target_measurand,
        metric_a_definition=authority.metric_a_definition,
        metric_b_definition=authority.metric_b_definition,
        unit_a=METER,
        unit_b=CENTIMETER,
        evidence_references=authority.evidence_references,
        producing_method=RES69_METHOD_COMPARISON_DESIGN_OPERATION,
    )
    with pytest.raises(ValueError, match="exact common units"):
        build_method_comparison_design_authority(bad_evidence)


def test_v3_round_trip_and_tamper_rejection() -> None:
    support, authority, _entries_value, _records, _pairs = _reliability_fixture()
    result = calculate_two_replicate_random_error(support, authority)
    assert isinstance(result, StatisticalResult)
    for value in (support, authority, result):
        serialized = canonical_json(value)
        restored = from_canonical_json(serialized, type(value))
        assert restored == value
        assert canonical_json(restored) == serialized
        assert canonical_hash(restored) == canonical_hash(value)

    wire = json.loads(canonical_json(support))
    wire["payload"]["support_hash"] = "sha256:" + "0" * 64
    with pytest.raises(ValueError):
        from_canonical_json(json.dumps(wire), StatisticalSupport)

    authority_wire = json.loads(canonical_json(authority))
    authority_wire["payload"]["source_evidence_hash"] = "sha256:" + "1" * 64
    with pytest.raises(ValueError):
        from_canonical_json(json.dumps(authority_wire), ReliabilityDesignAuthority)
