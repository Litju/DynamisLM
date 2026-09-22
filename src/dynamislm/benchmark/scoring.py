"""Deterministic structured scorers and error-event reporting."""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from collections.abc import Mapping
from dataclasses import dataclass

from dynamislm.benchmark._immutable import FrozenMap, freeze_mapping
from dynamislm.benchmark.constants import (
    CRITICAL_ERROR_CLASSES,
    HIGH_ERROR_CLASSES,
    ErrorClass,
    ErrorSeverity,
    FieldScoreStatus,
    RefusalDecision,
    ScoringProfile,
    TaskOutcome,
)
from dynamislm.benchmark.contracts import (
    BenchmarkCaseV1,
    ErrorEvent,
    FieldScore,
    ScoreResult,
    ScoringContract,
)
from dynamislm.benchmark.validation import validate_case
from dynamislm.serialization import canonical_hash


@dataclass(frozen=True, slots=True)
class ScorerProfileDefinition:
    profile_id: ScoringProfile
    version: str
    semantics: str
    required_structured_fields: tuple[str, ...]


SCORER_PROFILE_DEFINITIONS: dict[ScoringProfile, ScorerProfileDefinition] = {
    ScoringProfile.NUMERIC_TOLERANCE_V1: ScorerProfileDefinition(
        ScoringProfile.NUMERIC_TOLERANCE_V1,
        "1.0.0",
        (
            "finite scalar; abs_error <= abs_tol OR relative_error <= rel_tol when expected != 0; "
            "exact unit"
        ),
        ("numeric_value", "unit"),
    ),
    ScoringProfile.CLASSIFICATION_V1: ScorerProfileDefinition(
        ScoringProfile.CLASSIFICATION_V1,
        "1.0.0",
        "exact controlled label/set match with frozen case aliases",
        ("fields",),
    ),
    ScoringProfile.STRUCTURED_FIELDS_V1: ScorerProfileDefinition(
        ScoringProfile.STRUCTURED_FIELDS_V1,
        "1.0.0",
        "independent required-field scoring with case critical-field policy",
        ("fields",),
    ),
    ScoringProfile.EVIDENCE_SPAN_V1: ScorerProfileDefinition(
        ScoringProfile.EVIDENCE_SPAN_V1,
        "1.0.0",
        "exact or registered-normalized source span plus scope/applicability",
        ("source_span", "scope", "applicability"),
    ),
    ScoringProfile.COMPARABILITY_V1: ScorerProfileDefinition(
        ScoringProfile.COMPARABILITY_V1,
        "1.0.0",
        "exact state plus separately scored dimensions/reasons/conditions/transformations",
        ("state",),
    ),
    ScoringProfile.REFUSAL_V1: ScorerProfileDefinition(
        ScoringProfile.REFUSAL_V1,
        "1.0.0",
        "decision, class, reasons, blocked claim, missing information and safe description",
        (
            "refusal_class",
            "reason_codes",
            "blocked_claim",
            "missing_information",
            "safe_description",
        ),
    ),
    ScoringProfile.CAUSAL_BOUNDARY_V1: ScorerProfileDefinition(
        ScoringProfile.CAUSAL_BOUNDARY_V1,
        "1.0.0",
        "claim level and prohibited causal/latent language are structured fields",
        ("claim_level",),
    ),
    ScoringProfile.CALIBRATION_V1: ScorerProfileDefinition(
        ScoringProfile.CALIBRATION_V1,
        "1.0.0",
        "optional registered probability vector; not scored without a declared sample floor",
        ("probabilities",),
    ),
}


def scorer_profile_definition(profile: ScoringProfile | str) -> ScorerProfileDefinition:
    try:
        resolved = ScoringProfile(profile)
    except ValueError as exc:
        raise ValueError(f"unknown scorer profile: {profile}") from exc
    return SCORER_PROFILE_DEFINITIONS[resolved]


def scorer_profile_digest(profile: ScoringProfile | str) -> str:
    definition = scorer_profile_definition(profile)
    return canonical_hash(
        {
            "profile_id": definition.profile_id,
            "version": definition.version,
            "semantics": definition.semantics,
            "required_structured_fields": definition.required_structured_fields,
        }
    )


def validate_scoring_contract(contract: ScoringContract) -> None:
    if not isinstance(contract, ScoringContract):
        raise TypeError("scoring contract must be ScoringContract")
    definition = scorer_profile_definition(contract.profile_id)
    if contract.profile_version != definition.version:
        raise ValueError("scoring contract profile version is stale")
    unknown = set(contract.error_class_rules) - set(ErrorClass)
    if unknown:
        raise ValueError(f"unknown scorer error class: {sorted(unknown)}")


@dataclass(frozen=True, slots=True)
class CandidateAnswer:
    """Structured candidate output accepted by the deterministic scorer."""

    decision: str
    fields: Mapping[str, object]
    refusal: Mapping[str, object] | None = None
    claims: tuple[str, ...] = ()
    probabilities: Mapping[str, float] | None = None

    def __post_init__(self) -> None:
        if self.decision not in {"ANSWER", "REFUSE", "REFUSAL", "REFUSED"}:
            raise ValueError("candidate decision must be ANSWER or REFUSE")
        object.__setattr__(self, "fields", freeze_mapping(self.fields, "fields"))
        if self.refusal is not None:
            object.__setattr__(self, "refusal", freeze_mapping(self.refusal, "refusal"))
        if not isinstance(self.claims, tuple) or any(not item.strip() for item in self.claims):
            raise ValueError("candidate claims must be a tuple of non-empty strings")
        if self.probabilities is not None:
            probabilities = {key: float(value) for key, value in self.probabilities.items()}
            if any(not math.isfinite(value) or value < 0 for value in probabilities.values()):
                raise ValueError("candidate probabilities must be finite and non-negative")
            object.__setattr__(self, "probabilities", FrozenMap(probabilities))

    @property
    def is_refusal(self) -> bool:
        return self.decision in {"REFUSE", "REFUSAL", "REFUSED"}


def coerce_candidate_answer(value: CandidateAnswer | Mapping[str, object]) -> CandidateAnswer:
    if isinstance(value, CandidateAnswer):
        return value
    if not isinstance(value, Mapping):
        raise TypeError("candidate output must be CandidateAnswer or a mapping")
    decision_value = value.get("decision", value.get("outcome", "ANSWER"))
    if not isinstance(decision_value, str):
        raise ValueError("candidate decision must be a string")
    fields_value = value.get("fields", {})
    if not isinstance(fields_value, Mapping):
        raise ValueError("candidate fields must be a mapping")
    normalized_fields = dict(fields_value)
    if "unit" in value and "unit" not in normalized_fields:
        normalized_fields["unit"] = value["unit"]
    refusal_value = value.get("refusal")
    if refusal_value is not None and not isinstance(refusal_value, Mapping):
        raise ValueError("candidate refusal must be a mapping")
    claims_value = value.get("claims", ())
    if not isinstance(claims_value, tuple | list):
        raise ValueError("candidate claims must be an ordered sequence")
    probabilities_value = value.get("probabilities")
    if probabilities_value is not None and not isinstance(probabilities_value, Mapping):
        raise ValueError("candidate probabilities must be a mapping")
    return CandidateAnswer(
        decision=decision_value,
        fields=normalized_fields,
        refusal=refusal_value,
        claims=tuple(str(item) for item in claims_value),
        probabilities=probabilities_value,
    )


def _actual_field(candidate: CandidateAnswer, field_id: str) -> object | None:
    if field_id in candidate.fields:
        return candidate.fields[field_id]
    if candidate.refusal is not None and field_id in candidate.refusal:
        return candidate.refusal[field_id]
    return None


def _numeric_value(value: object) -> tuple[float, str | None] | None:
    if isinstance(value, Mapping):
        raw = value.get("value")
        unit = value.get("unit")
        if isinstance(raw, bool) or not isinstance(raw, int | float):
            return None
        if unit is not None and not isinstance(unit, str):
            return None
        return float(raw), unit
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value), None


def _same_value(expected: object, actual: object, aliases: tuple[str, ...] = ()) -> bool:
    if expected == actual:
        return True
    if isinstance(expected, str) and isinstance(actual, str):
        return actual in {expected, *aliases}
    if isinstance(expected, tuple | list) and isinstance(actual, tuple | list):
        return set(expected) == set(actual)
    return False


def _numeric_match(
    expected: object,
    actual: object,
    *,
    unit: str,
    absolute_tolerance: float,
    relative_tolerance: float,
) -> tuple[bool, str]:
    expected_number = _numeric_value(expected)
    actual_number = _numeric_value(actual)
    if expected_number is None or actual_number is None:
        return False, "numeric field is not a finite scalar/value-unit object"
    expected_value, expected_unit = expected_number
    actual_value, actual_unit = actual_number
    if not math.isfinite(expected_value) or not math.isfinite(actual_value):
        return False, "numeric output and expected value must be finite"
    if expected_unit is not None and expected_unit != unit:
        return False, "expected unit does not match registered tolerance unit"
    if actual_unit != unit:
        return False, "unit mismatch; no unregistered conversion is performed"
    error = abs(actual_value - expected_value)
    if error <= absolute_tolerance:
        return True, "absolute tolerance passed"
    if expected_value != 0 and error / abs(expected_value) <= relative_tolerance:
        return True, "relative tolerance passed"
    return False, "numeric value is outside the registered tolerance"


def _error_for_field(case: BenchmarkCaseV1, field_id: str, actual: object | None) -> ErrorEvent:
    lower = field_id.lower()
    if lower in {"comparability_state", "state", "comparability"}:
        error_class = ErrorClass.FALSE_COMPARABILITY_ACCEPTANCE
    elif "claim" in lower or "causal" in lower:
        error_class = ErrorClass.CAUSAL_OVERCLAIM
    elif "analysis" in lower or "estimand" in lower:
        error_class = ErrorClass.WRONG_ANALYSIS_CLASS
    elif "within" in lower or "between" in lower or "level_of_analysis" in lower:
        error_class = ErrorClass.BETWEEN_TO_WITHIN_MISINFERENCE
    elif "origin" in lower or "direct" in lower or "derived" in lower:
        error_class = ErrorClass.DIRECT_DERIVED_COLLAPSE
    elif "latent" in lower or "physiolog" in lower or "readiness" in lower or "fatigue" in lower:
        error_class = ErrorClass.UNSUPPORTED_LATENT_OR_PHYSIOLOGICAL_INFERENCE
    elif "numeric" in lower or "value" in lower or "result" in lower:
        error_class = ErrorClass.INVENTED_NUMERICAL_SCIENCE
    else:
        error_class = ErrorClass.WRONG_MEASUREMENT_IDENTITY
    severity = (
        ErrorSeverity.CRITICAL.value
        if error_class in CRITICAL_ERROR_CLASSES
        else ErrorSeverity.HIGH.value
        if error_class in HIGH_ERROR_CLASSES
        else ErrorSeverity.BEHAVIOR.value
    )
    return ErrorEvent(
        case_id=case.case_id,
        error_class=error_class,
        severity=severity,
        field_id=field_id,
        evidence=f"required structured field {field_id!r} did not satisfy the frozen authority",
    )


def _refusal_field_scores(
    case: BenchmarkCaseV1, candidate: CandidateAnswer
) -> tuple[FieldScore, ...]:
    expected = case.refusal_expectation
    actual = candidate.refusal or {}
    expected_values: dict[str, object] = {
        "blocked_claim": expected.blocked_claim,
        "refusal_class": expected.refusal_class.value if expected.refusal_class else None,
        "reason_codes": expected.reason_codes,
        "missing_information": expected.missing_information,
        "safe_description": expected.what_can_still_be_safely_described,
    }
    scores: list[FieldScore] = []
    for field_id, expected_value in expected_values.items():
        actual_value = actual.get(field_id)
        if actual_value is None:
            status = FieldScoreStatus.MISSING
            reason = "required refusal field is missing"
        elif field_id in {"reason_codes", "missing_information", "safe_description"}:
            actual_items = tuple(actual_value) if isinstance(actual_value, tuple | list) else ()
            expected_items = tuple(expected_value) if isinstance(expected_value, tuple) else ()
            status = (
                FieldScoreStatus.CORRECT
                if set(expected_items).issubset(set(actual_items))
                else FieldScoreStatus.WRONG
            )
            reason = (
                "refusal set matches"
                if status is FieldScoreStatus.CORRECT
                else "refusal set is incomplete or wrong"
            )
        else:
            status = (
                FieldScoreStatus.CORRECT
                if actual_value == expected_value
                else FieldScoreStatus.WRONG
            )
            reason = (
                "refusal field matches"
                if status is FieldScoreStatus.CORRECT
                else "refusal field differs"
            )
        scores.append(FieldScore(field_id, status, expected_value, actual_value, reason))
    return tuple(scores)


def score_case(
    case: BenchmarkCaseV1,
    candidate: CandidateAnswer | Mapping[str, object],
    *,
    validate_authority: bool = True,
) -> ScoreResult:
    """Score structured output with no model-as-judge or prose interpretation."""

    if validate_authority:
        validate_case(case)
    validate_scoring_contract(case.scoring_contract)
    answer = coerce_candidate_answer(candidate)
    expected_refusal = case.refusal_expectation.decision is RefusalDecision.REQUIRED
    refusal_decision_correct = answer.is_refusal if expected_refusal else not answer.is_refusal
    field_scores: list[FieldScore] = []
    errors: list[ErrorEvent] = []

    if expected_refusal:
        field_scores.extend(_refusal_field_scores(case, answer))
    else:
        if answer.is_refusal:
            errors.append(
                ErrorEvent(
                    case_id=case.case_id,
                    error_class=ErrorClass.OVER_REFUSAL,
                    severity=ErrorSeverity.BEHAVIOR.value,
                    field_id=None,
                    evidence="candidate refused a claim not marked refusal-required",
                )
            )
        for field_id in case.expected_answer.required_field_ids:
            expected_value = case.expected_answer.expected_fields.get(field_id)
            actual_value = _actual_field(answer, field_id)
            if actual_value is None:
                field_scores.append(
                    FieldScore(
                        field_id,
                        FieldScoreStatus.MISSING,
                        expected_value,
                        None,
                        "required field is missing",
                    )
                )
                continue
            if case.scoring_contract.profile_id is ScoringProfile.NUMERIC_TOLERANCE_V1:
                tolerance = case.tolerance_contract
                assert tolerance is not None
                numeric_actual = actual_value
                if not isinstance(actual_value, Mapping) and "unit" in answer.fields:
                    numeric_actual = {
                        "value": actual_value,
                        "unit": answer.fields["unit"],
                    }
                matched, reason = _numeric_match(
                    expected_value,
                    numeric_actual,
                    unit=tolerance.unit,
                    absolute_tolerance=tolerance.absolute_tolerance,
                    relative_tolerance=tolerance.relative_tolerance,
                )
            else:
                aliases = tuple(case.expected_answer.accepted_aliases.get(field_id, ()))
                matched = _same_value(expected_value, actual_value, aliases)
                reason = (
                    "field matches frozen structured answer"
                    if matched
                    else "field differs from frozen structured answer"
                )
            field_scores.append(
                FieldScore(
                    field_id,
                    FieldScoreStatus.CORRECT if matched else FieldScoreStatus.WRONG,
                    expected_value,
                    actual_value,
                    reason,
                )
            )
            if not matched:
                errors.append(_error_for_field(case, field_id, actual_value))

        for field_id in case.expected_answer.prohibited_claims:
            if field_id in answer.claims:
                errors.append(
                    ErrorEvent(
                        case_id=case.case_id,
                        error_class=ErrorClass.CAUSAL_OVERCLAIM,
                        severity=ErrorSeverity.CRITICAL.value,
                        field_id=field_id,
                        evidence="candidate emitted a structured prohibited claim",
                    )
                )

    if expected_refusal and not refusal_decision_correct:
        errors.append(
            ErrorEvent(
                case_id=case.case_id,
                error_class=ErrorClass.FALSE_SCIENTIFIC_ACCEPTANCE,
                severity=ErrorSeverity.CRITICAL.value,
                field_id=None,
                evidence="candidate accepted a claim whose frozen contract requires refusal",
            )
        )
    if expected_refusal and answer.is_refusal:
        required_fields = {
            item.field_id for item in field_scores if item.status is FieldScoreStatus.CORRECT
        }
        if len(required_fields) < len(field_scores):
            errors.append(
                ErrorEvent(
                    case_id=case.case_id,
                    error_class=ErrorClass.UNDER_SPECIFIED_REFUSAL,
                    severity=ErrorSeverity.BEHAVIOR.value,
                    field_id=None,
                    evidence=(
                        "refusal decision is correct but the structured refusal contract "
                        "is incomplete"
                    ),
                )
            )

    has_critical_or_high = any(
        event.error_class in (*CRITICAL_ERROR_CLASSES, *HIGH_ERROR_CLASSES) for event in errors
    )
    all_fields_correct = bool(field_scores) and all(
        field.status is FieldScoreStatus.CORRECT for field in field_scores
    )
    if expected_refusal:
        if refusal_decision_correct and all_fields_correct and not has_critical_or_high:
            outcome = TaskOutcome.REFUSAL_CORRECT
        elif refusal_decision_correct and not has_critical_or_high:
            outcome = TaskOutcome.PARTIAL
        else:
            outcome = TaskOutcome.REFUSAL_INCORRECT
    elif answer.is_refusal:
        outcome = TaskOutcome.REFUSAL_INCORRECT
    elif has_critical_or_high or any(
        field.status is FieldScoreStatus.WRONG for field in field_scores
    ):
        outcome = TaskOutcome.FAIL
    elif all_fields_correct:
        outcome = TaskOutcome.PASS
    else:
        outcome = TaskOutcome.PARTIAL
    return ScoreResult(
        case_id=case.case_id,
        outcome=outcome,
        field_scores=tuple(field_scores),
        error_events=tuple(errors),
        primary_decision_correct=(
            refusal_decision_correct
            and (
                not errors
                or not any(
                    event.error_class in (*CRITICAL_ERROR_CLASSES, *HIGH_ERROR_CLASSES)
                    for event in errors
                )
            )
        ),
        refusal_decision_correct=refusal_decision_correct,
    )


@dataclass(frozen=True, slots=True)
class ErrorEventReport:
    events: tuple[ErrorEvent, ...]
    counts: Mapping[str, int]
    eligible_denominators: Mapping[str, int]
    rates: Mapping[str, float]
    by_split: Mapping[str, Mapping[str, int]]

    def __post_init__(self) -> None:
        object.__setattr__(self, "counts", freeze_mapping(self.counts, "counts"))
        object.__setattr__(
            self,
            "eligible_denominators",
            freeze_mapping(self.eligible_denominators, "eligible_denominators"),
        )
        object.__setattr__(self, "rates", freeze_mapping(self.rates, "rates"))
        object.__setattr__(
            self,
            "by_split",
            FrozenMap(
                {
                    key: freeze_mapping(value, f"by_split.{key}")
                    for key, value in self.by_split.items()
                }
            ),
        )


def build_error_event_report(
    results: tuple[ScoreResult, ...],
    cases: tuple[BenchmarkCaseV1, ...] | None = None,
) -> ErrorEventReport:
    case_by_id = {case.case_id: case for case in cases or ()}
    counts = Counter(event.error_class.value for result in results for event in result.error_events)
    denominators: Counter[str] = Counter()
    for case in cases or ():
        for error_class in case.scoring_contract.error_class_rules:
            denominators[error_class.value] += 1
    for error_class in ErrorClass:
        denominators.setdefault(error_class.value, 0)
        counts.setdefault(error_class.value, 0)
    rates = {
        error_class: (
            counts[error_class] / denominators[error_class] if denominators[error_class] else 0.0
        )
        for error_class in counts
    }
    by_split: dict[str, Counter[str]] = defaultdict(Counter)
    for result in results:
        matched_case = case_by_id.get(result.case_id)
        split_name = "UNBOUND"
        if matched_case is not None and matched_case.split.split_name is not None:
            split_name = matched_case.split.split_name.value
        for event in result.error_events:
            by_split[split_name][event.error_class.value] += 1
    return ErrorEventReport(
        events=tuple(event for result in results for event in result.error_events),
        counts=dict(counts),
        eligible_denominators=dict(denominators),
        rates=rates,
        by_split={key: dict(value) for key, value in by_split.items()},
    )


__all__ = [
    "SCORER_PROFILE_DEFINITIONS",
    "CandidateAnswer",
    "ErrorEventReport",
    "ScorerProfileDefinition",
    "build_error_event_report",
    "coerce_candidate_answer",
    "score_case",
    "scorer_profile_definition",
    "scorer_profile_digest",
    "validate_scoring_contract",
]
