"""Construction and validation of exact RES-69 statistical support."""

from __future__ import annotations

import datetime as datetime_module
import math
from collections.abc import Iterable

from dynamislm.comparability.models import (
    ComparabilityRequest,
    ComparabilityResult,
    ComparabilityState,
)
from dynamislm.longitudinal.models import (
    LongitudinalAthletePerformanceRecord,
    LongitudinalObservationEntry,
    MultiSourceAnalysisInput,
)
from dynamislm.longitudinal.statistics.models import (
    MethodComparisonMethodKeyV1,
    MissingnessPolicy,
    StatisticalComparabilityEvidence,
    StatisticalSourceRecordReference,
    StatisticalSupport,
    StatisticalSupportWindowKind,
    StatisticalWindow,
    SupportEntryExclusion,
    SupportExclusionReason,
)
from dynamislm.measurement.identity import InstanceIdentifier, UnitReference
from dynamislm.measurement.result import (
    QualityStatus,
    ResultStatus,
    ScalarValue,
)
from dynamislm.population._authority import compute_source_authority, validate_source_decision


class StatisticalConstraintError(ValueError):
    """Internal fail-closed constraint carrying its RES-69 refusal code."""

    def __init__(
        self,
        message: str,
        code: str,
        *,
        missing_information: tuple[str, ...] = (),
    ) -> None:
        super().__init__(message)
        self.code = code
        self.missing_information = missing_information


def _entry_sort_key(entry: LongitudinalObservationEntry) -> tuple[str, str, str]:
    return (
        entry.observed_at.astimezone(datetime_module.UTC).isoformat(timespec="microseconds"),
        entry.source_observation_id.qualified,
        entry.canonical_entry_hash,
    )


def _normalise_inputs(
    analysis_input: MultiSourceAnalysisInput | tuple[MultiSourceAnalysisInput, ...],
) -> tuple[MultiSourceAnalysisInput, ...]:
    if isinstance(analysis_input, MultiSourceAnalysisInput):
        return (analysis_input,)
    if not isinstance(analysis_input, tuple) or not analysis_input:
        raise ValueError("analysis_input must be a MultiSourceAnalysisInput or non-empty tuple")
    if any(not isinstance(item, MultiSourceAnalysisInput) for item in analysis_input):
        raise ValueError("analysis_input tuple must contain MultiSourceAnalysisInput values")
    return tuple(
        sorted(
            analysis_input,
            key=lambda item: (item.athlete.athlete_id.qualified, item.input_id.qualified),
        )
    )


def _record_references(
    source_records: tuple[LongitudinalAthletePerformanceRecord, ...],
) -> tuple[StatisticalSourceRecordReference, ...]:
    if not isinstance(source_records, tuple) or not source_records:
        raise ValueError("source_records must be a non-empty immutable tuple")
    references = tuple(
        StatisticalSourceRecordReference.from_record(item) for item in source_records
    )
    return tuple(sorted(references, key=lambda item: item.record_id.qualified))


def _all_input_entries(
    inputs: tuple[MultiSourceAnalysisInput, ...],
) -> dict[str, LongitudinalObservationEntry]:
    result: dict[str, LongitudinalObservationEntry] = {}
    for analysis_input in inputs:
        for entry in analysis_input.entries:
            key = entry.canonical_entry_id.qualified
            previous = result.get(key)
            if previous is not None and previous != entry:
                raise ValueError("analysis inputs contain conflicting entry content")
            result[key] = entry
    return result


def _validate_source_records(
    inputs: tuple[MultiSourceAnalysisInput, ...],
    source_records: tuple[LongitudinalAthletePerformanceRecord, ...],
) -> None:
    records_by_entry: dict[str, list[tuple[str, str]]] = {}
    expected_athletes = {item.athlete.athlete_id for item in inputs}
    for record in source_records:
        if record.athlete.athlete_id not in expected_athletes:
            raise ValueError("source record athlete is absent from the analysis inputs")
        if record.record_id is None:
            raise ValueError("source record must have a canonical ID")
        record_hash = record.canonical_record_hash
        for entry in record.entries:
            records_by_entry.setdefault(entry.canonical_entry_id.qualified, []).append(
                (entry.canonical_entry_hash, record_hash)
            )
    for entry in _all_input_entries(inputs).values():
        matches = records_by_entry.get(entry.canonical_entry_id.qualified, ())
        if not any(entry.canonical_entry_hash == entry_hash for entry_hash, _ in matches):
            raise ValueError("source records do not cover every exact analysis-input entry")


def _validate_source_qualification(inputs: tuple[MultiSourceAnalysisInput, ...]) -> None:
    for entry in _all_input_entries(inputs).values():
        for binding in entry.source_qualification_bindings:
            decision = binding.canonical_source_decision
            expected = compute_source_authority(decision.source)
            validate_source_decision(decision, expected)


def build_statistical_support(
    analysis_input: MultiSourceAnalysisInput | tuple[MultiSourceAnalysisInput, ...],
    included_entries: Iterable[LongitudinalObservationEntry],
    *,
    source_records: tuple[LongitudinalAthletePerformanceRecord, ...],
    excluded_entries: Iterable[SupportEntryExclusion] = (),
    missingness_policy: MissingnessPolicy = MissingnessPolicy.NO_IMPUTATION_NO_ZERO_FILL,
    window: StatisticalWindow | None = None,
    comparability_evidence: tuple[StatisticalComparabilityEvidence, ...] = (),
    current_entry_id: InstanceIdentifier | None = None,
    reference_entry_ids: tuple[InstanceIdentifier, ...] = (),
) -> StatisticalSupport:
    """Build support only when included and excluded entry coverage is explicit."""

    inputs = _normalise_inputs(analysis_input)
    all_entries = _all_input_entries(inputs)
    included = tuple(sorted(tuple(included_entries), key=_entry_sort_key))
    excluded = tuple(
        sorted(tuple(excluded_entries), key=lambda item: item.reference.entry_id.qualified)
    )
    comparability_evidence = tuple(
        sorted(
            comparability_evidence,
            key=lambda item: tuple(identifier.qualified for identifier in item.pair_ids),
        )
    )
    if not included:
        raise ValueError("included_entries must not be empty")
    if not isinstance(excluded, tuple):
        excluded = tuple(excluded)
    if not excluded and {item.canonical_entry_id.qualified for item in included} != set(
        all_entries
    ):
        raise ValueError("omitted entries require explicit SupportEntryExclusion values")
    if window is None:
        window = StatisticalWindow(StatisticalSupportWindowKind.FULL_SUPPORT)
    records = tuple(source_records)
    _validate_source_records(inputs, records)
    _validate_source_qualification(inputs)
    support = StatisticalSupport(
        analysis_inputs=inputs,
        included_entries=included,
        excluded_entries=excluded,
        missingness_policy=missingness_policy,
        window=window,
        source_records=_record_references(records),
        comparability_evidence=comparability_evidence,
        current_entry_id=current_entry_id,
        reference_entry_ids=reference_entry_ids,
    )
    return support


def build_comparability_evidence(
    request: ComparabilityRequest,
    result: ComparabilityResult,
) -> StatisticalComparabilityEvidence:
    """Bind an existing authoritative comparability result to its exact request."""

    return StatisticalComparabilityEvidence(request=request, result=result)


def _outside_window_exclusions(
    inputs: tuple[MultiSourceAnalysisInput, ...],
    included_ids: set[str],
) -> tuple[SupportEntryExclusion, ...]:
    return tuple(
        SupportEntryExclusion.from_entry(entry, SupportExclusionReason.OUTSIDE_WINDOW)
        for entry in _all_input_entries(inputs).values()
        if entry.canonical_entry_id.qualified not in included_ids
    )


def build_count_window_support(
    analysis_input: MultiSourceAnalysisInput,
    count: int,
    *,
    source_records: tuple[LongitudinalAthletePerformanceRecord, ...],
    missingness_policy: MissingnessPolicy = MissingnessPolicy.NO_IMPUTATION_NO_ZERO_FILL,
    comparability_evidence: tuple[StatisticalComparabilityEvidence, ...] = (),
) -> StatisticalSupport:
    """Select the latest exact count of entries, recording all other entries."""

    if isinstance(count, bool) or not isinstance(count, int) or count < 1:
        raise ValueError("count must be a positive integer")
    ordered = tuple(sorted(analysis_input.entries, key=_entry_sort_key))
    if count > len(ordered):
        raise ValueError("count window exceeds available entries")
    selected = ordered[-count:]
    return build_statistical_support(
        analysis_input,
        selected,
        source_records=source_records,
        excluded_entries=_outside_window_exclusions(
            (analysis_input,),
            {entry.canonical_entry_id.qualified for entry in selected},
        ),
        missingness_policy=missingness_policy,
        window=StatisticalWindow(StatisticalSupportWindowKind.COUNT_WINDOW, count=count),
        comparability_evidence=comparability_evidence,
    )


def _in_time_window(
    entry: LongitudinalObservationEntry,
    start: datetime_module.datetime,
    end: datetime_module.datetime,
    start_inclusive: bool,
    end_inclusive: bool,
) -> bool:
    at = entry.observed_at
    left = at >= start if start_inclusive else at > start
    right = at <= end if end_inclusive else at < end
    return left and right


def build_time_window_support(
    analysis_input: MultiSourceAnalysisInput,
    start: datetime_module.datetime,
    end: datetime_module.datetime,
    *,
    start_inclusive: bool = True,
    end_inclusive: bool = True,
    source_records: tuple[LongitudinalAthletePerformanceRecord, ...],
    missingness_policy: MissingnessPolicy = MissingnessPolicy.NO_IMPUTATION_NO_ZERO_FILL,
    comparability_evidence: tuple[StatisticalComparabilityEvidence, ...] = (),
) -> StatisticalSupport:
    """Select entries using exact timestamp bounds and inclusivity."""

    window = StatisticalWindow(
        StatisticalSupportWindowKind.TIME_WINDOW,
        start=start,
        end=end,
        start_inclusive=start_inclusive,
        end_inclusive=end_inclusive,
    )
    selected = tuple(
        entry
        for entry in analysis_input.entries
        if _in_time_window(entry, start, end, start_inclusive, end_inclusive)
    )
    return build_statistical_support(
        analysis_input,
        selected,
        source_records=source_records,
        excluded_entries=_outside_window_exclusions(
            (analysis_input,),
            {entry.canonical_entry_id.qualified for entry in selected},
        ),
        missingness_policy=missingness_policy,
        window=window,
        comparability_evidence=comparability_evidence,
    )


def build_pair_support(
    analysis_input: MultiSourceAnalysisInput,
    first: LongitudinalObservationEntry,
    second: LongitudinalObservationEntry,
    *,
    source_records: tuple[LongitudinalAthletePerformanceRecord, ...],
    missingness_policy: MissingnessPolicy = MissingnessPolicy.NO_IMPUTATION_NO_ZERO_FILL,
    comparability_evidence: tuple[StatisticalComparabilityEvidence, ...] = (),
) -> StatisticalSupport:
    """Build an exact two-entry support with explicit non-selected entries."""

    selected_ids = {first.canonical_entry_id.qualified, second.canonical_entry_id.qualified}
    return build_statistical_support(
        analysis_input,
        (first, second),
        source_records=source_records,
        excluded_entries=_outside_window_exclusions((analysis_input,), selected_ids),
        missingness_policy=missingness_policy,
        comparability_evidence=comparability_evidence,
    )


def build_reference_window_support(
    analysis_input: MultiSourceAnalysisInput,
    current: LongitudinalObservationEntry,
    reference_entries: Iterable[LongitudinalObservationEntry],
    *,
    source_records: tuple[LongitudinalAthletePerformanceRecord, ...],
    missingness_policy: MissingnessPolicy = MissingnessPolicy.NO_IMPUTATION_NO_ZERO_FILL,
    comparability_evidence: tuple[StatisticalComparabilityEvidence, ...] = (),
) -> StatisticalSupport:
    """Build support with an explicit current entry and prior reference entries."""

    references = tuple(sorted(tuple(reference_entries), key=_entry_sort_key))
    selected = (*references, current)
    selected_ids = {entry.canonical_entry_id.qualified for entry in selected}
    if len(selected_ids) != len(selected):
        raise ValueError("reference support entries must be unique")
    return build_statistical_support(
        analysis_input,
        selected,
        source_records=source_records,
        excluded_entries=_outside_window_exclusions((analysis_input,), selected_ids),
        missingness_policy=missingness_policy,
        comparability_evidence=comparability_evidence,
        current_entry_id=current.canonical_entry_id,
        reference_entry_ids=tuple(entry.canonical_entry_id for entry in references),
    )


def validate_statistical_support(support: StatisticalSupport) -> None:
    """Fail closed on support identity, source qualification, or hash mismatch."""

    if not isinstance(support, StatisticalSupport):
        raise ValueError("support must be a StatisticalSupport")
    if not support.source_records:
        raise ValueError("authoritative statistical support requires source-record references")
    expected_id = InstanceIdentifier(
        "statistical-support",
        support.canonical_support_hash.removeprefix("sha256:"),
    )
    if support.canonical_support_id != expected_id:
        raise ValueError("support ID does not match its support hash")
    _validate_source_qualification(support.analysis_inputs)
    all_entries = _all_input_entries(support.analysis_inputs)
    for entry in support.included_entries:
        if all_entries.get(entry.canonical_entry_id.qualified) != entry:
            raise ValueError("support included entry is not an exact RES-62 entry")
    for item in support.excluded_entries:
        if all_entries.get(item.reference.entry_id.qualified) is None:
            raise ValueError("support exclusion is not an exact RES-62 entry")


def scalar_value(entry: LongitudinalObservationEntry) -> tuple[float, UnitReference]:
    """Return one valid finite scalar and its exact source unit for internal calculators."""

    if not isinstance(entry, LongitudinalObservationEntry):
        raise ValueError("entry must be a LongitudinalObservationEntry")
    observation = entry.observation
    result = observation.result
    if result.status is not ResultStatus.VALID:
        raise ValueError("source result is not valid")
    if result.quality.status is QualityStatus.REJECTED:
        raise ValueError("source result quality is rejected")
    if not isinstance(result.value, ScalarValue):
        raise ValueError("statistical operation requires scalar source results")
    value = result.value.value
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError("source scalar must be numeric and not boolean")
    numeric = float(value)
    if not math.isfinite(numeric):
        raise ValueError("source scalar must be finite")
    if result.unit is None:
        raise ValueError("source result must carry an exact UnitReference")
    return numeric, result.unit


def exact_common_unit(entries: tuple[LongitudinalObservationEntry, ...]) -> UnitReference:
    if not entries:
        raise ValueError("at least one entry is required")
    units = tuple(scalar_value(entry)[1] for entry in entries)
    first = units[0]
    if any(unit != first for unit in units[1:]):
        raise ValueError("exact common UnitReference is required; conversion is not registered")
    return first


def measurement_target_signature(entry: LongitudinalObservationEntry) -> tuple[object, ...]:
    identity = entry.observation.identity
    return (
        identity.semantic.construct.identifier,
        identity.semantic.test_family.identifier,
        identity.semantic.measurand.identifier,
        identity.semantic.metric_definition.identifier,
    )


def _method_signature(entry: LongitudinalObservationEntry) -> MethodComparisonMethodKeyV1:
    identity = entry.observation.identity
    _value, unit = scalar_value(entry)
    return MethodComparisonMethodKeyV1.from_measurement_identity(identity, unit)


def validate_comparable_entries(
    support: StatisticalSupport,
    entries: tuple[LongitudinalObservationEntry, ...],
) -> tuple[object, ...]:
    """Require exact units and complete pairwise comparability authority."""

    if len(entries) < 1:
        raise StatisticalConstraintError(
            "comparability requires at least one entry",
            "RES69_DATA_ADEQUACY_INSUFFICIENT",
        )
    try:
        exact_common_unit(entries)
    except ValueError as exc:
        raise StatisticalConstraintError(
            "direct statistical arithmetic requires one exact common UnitReference",
            "RES69_UNIT_MISMATCH",
            missing_information=("registered deterministic unit conversion",),
        ) from exc
    targets = tuple(measurement_target_signature(entry) for entry in entries)
    if any(target != targets[0] for target in targets[1:]):
        raise StatisticalConstraintError(
            "entries do not share the same construct, test family, measurand, and metric",
            "RES69_IDENTITY_UNRESOLVED",
            missing_information=("one intended target measurement identity",),
        )
    evidence_by_pair: dict[frozenset[str], StatisticalComparabilityEvidence] = {}
    for evidence in support.comparability_evidence:
        pair = frozenset(item.qualified for item in evidence.pair_ids)
        if len(pair) != 2:
            raise StatisticalConstraintError(
                "comparability evidence must identify two distinct observations",
                "RES69_SUPPORT_MISMATCH",
            )
        if pair in evidence_by_pair and evidence_by_pair[pair] != evidence:
            raise StatisticalConstraintError(
                "conflicting comparability evidence was supplied for one observation pair",
                "RES69_REGISTRY_INTEGRITY_FAILURE",
            )
        evidence_by_pair[pair] = evidence

    references: list[object] = []
    for index, left in enumerate(entries):
        for right in entries[index + 1 :]:
            pair = frozenset(
                (left.source_observation_id.qualified, right.source_observation_id.qualified)
            )
            if _method_signature(left) == _method_signature(right):
                from dynamislm.longitudinal.statistics.registry import (
                    RES69_EXACT_SEMANTIC_COMPARABILITY_RULE,
                )

                references.append(RES69_EXACT_SEMANTIC_COMPARABILITY_RULE)
                continue
            evidence_for_pair = evidence_by_pair.get(pair)
            if evidence_for_pair is None:
                raise StatisticalConstraintError(
                    "material method/device differences require complete pairwise "
                    "comparability evidence",
                    "RES69_COMPARABILITY_UNESTABLISHED",
                    missing_information=(
                        "authoritative comparability evidence for every material pair",
                    ),
                )
            if evidence_for_pair.result.state not in (
                ComparabilityState.COMPARABLE,
                ComparabilityState.COMPARABLE_WITH_CONDITIONS,
            ):
                raise StatisticalConstraintError(
                    "comparability evidence is not affirmative",
                    "RES69_COMPARABILITY_UNESTABLISHED",
                )
            assert evidence_for_pair.result.rule_reference is not None
            references.append(evidence_for_pair.result.rule_reference)
    return tuple(references)


__all__ = [
    "build_comparability_evidence",
    "build_count_window_support",
    "build_pair_support",
    "build_reference_window_support",
    "build_statistical_support",
    "build_time_window_support",
    "exact_common_unit",
    "measurement_target_signature",
    "scalar_value",
    "validate_comparable_entries",
    "validate_statistical_support",
]
