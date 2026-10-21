"""Python 3.12 CPU authority engine for the RES-541 A0 synthetic experiment."""

from __future__ import annotations

import hashlib
import importlib
import json
import math
import sys
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path
from typing import Any, cast

from dynamislm import (
    AnalysisAuthorizationRequest,
    AnalysisClass,
    AnalysisEstimandLevel,
    AnalysisLevelIdentity,
    AnalysisUnitOfAnalysis,
    ClaimIntent,
    ClaimTarget,
    MeasurementClaimLevel,
    RelationshipClaimLevel,
    authorize_analysis,
    authorize_claim,
    build_longitudinal_observation_entry,
    build_longitudinal_record,
    build_multi_source_analysis_input,
    validate_analysis_authorization,
    validate_claim_authority,
)
from dynamislm.claims.models import ClaimAuthorityStatus
from dynamislm.longitudinal.models import (
    LongitudinalObservationEntry,
    LongitudinalRecordOrigin,
    MultiSourceAnalysisScope,
)
from dynamislm.longitudinal.statistics import (
    RES69_ABSOLUTE_CHANGE_ESTIMATOR,
    RES69_ABSOLUTE_CHANGE_OPERATION,
    StatisticalSupport,
    StatisticalUnitReference,
    SupportEntryExclusion,
    SupportExclusionReason,
    build_statistical_support,
    calculate_absolute_change,
    validate_statistical_result,
    validate_statistical_support,
)
from dynamislm.measurement.identity import (
    InstanceIdentifier,
    UnitReference,
)
from dynamislm.measurement.result import ResultStatus, ScalarValue
from dynamislm.refusal.models import RefusalResult

ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = ROOT / "experiments" / "a0" / "cases.json"

# shortcut: A0 reuses RES-69 test builders; extract if another workflow needs them.
sys.path.insert(0, str(ROOT / "tests"))
_fixture_helpers = importlib.import_module("test_longitudinal_statistics")
ATHLETE: Any = _fixture_helpers.ATHLETE
CENTIMETER: Any = _fixture_helpers.CENTIMETER
METER: Any = _fixture_helpers.METER
OTHER_ATHLETE: Any = _fixture_helpers.OTHER_ATHLETE
_entries: Any = _fixture_helpers._entries
_reference: Any = _fixture_helpers._reference
_with_unit: Any = _fixture_helpers._with_unit

CASE_SCHEMA = "RES541_A0_CASES_V1"
PREPARED_SCHEMA = "RES541_A0_PREPARED_CASES_V1"
OUTPUT_SCHEMA = "RES541_A0_MODEL_OUTPUTS_V1"
REPORT_SCHEMA = "RES541_A0_REPORT_V1"
INTENT_SCHEMA = "RES541_A0_INTENT_V1"
MAX_CASES = 16
MIN_CASES = 12
MAX_MODEL_OUTPUT_CHARS = 4096


class ModelDecision(StrEnum):
    EXECUTE = "EXECUTE"
    REFUSE = "REFUSE"


class ObservationRole(StrEnum):
    BASELINE = "BASELINE"
    FOLLOWUP = "FOLLOWUP"


class ModelRefusalReason(StrEnum):
    MISSING_EVIDENCE = "MISSING_EVIDENCE"
    UNSUPPORTED_ANALYSIS = "UNSUPPORTED_ANALYSIS"
    CLAIM_EXCEEDS_EVIDENCE = "CLAIM_EXCEEDS_EVIDENCE"


@dataclass(frozen=True, slots=True)
class ObservationSpec:
    role: str
    athlete: str
    value: float | None
    unit: str | None
    metric: str
    status: str


@dataclass(frozen=True, slots=True)
class Expectation:
    outcome: str
    analysis_class: AnalysisClass
    measurement_claim_level: MeasurementClaimLevel | None
    relationship_claim_level: RelationshipClaimLevel | None
    value: float | None
    unit: str | None
    reason_code: str | None


@dataclass(frozen=True, slots=True)
class Case:
    case_id: str
    request: str
    observations: tuple[ObservationSpec, ...]
    expectation: Expectation


@dataclass(frozen=True, slots=True)
class ModelIntent:
    decision: ModelDecision
    analysis_class: AnalysisClass | None
    baseline_role: ObservationRole | None
    followup_role: ObservationRole | None
    measurement_claim_level: MeasurementClaimLevel | None
    relationship_claim_level: RelationshipClaimLevel | None
    refusal_reason: ModelRefusalReason | None


@dataclass(frozen=True, slots=True)
class CaseContext:
    case: Case
    support: StatisticalSupport
    entries_by_role: dict[str, LongitudinalObservationEntry]


def _object(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"{field} must be an object with string keys")
    return cast(dict[str, Any], value)


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value


def _string_values(value: object) -> tuple[str, ...]:
    if not isinstance(value, tuple | list):
        return ()
    return tuple(str(item) for item in value)


def _optional_enum[T: StrEnum](enum_type: type[T], value: object, field: str) -> T | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string or null")
    try:
        return enum_type(value)
    except ValueError as exc:
        raise ValueError(f"{field} is not a registered {enum_type.__name__}") from exc


def load_cases(path: Path = CASES_PATH) -> tuple[Case, ...]:
    document = _object(json.loads(path.read_text(encoding="utf-8")), "case document")
    if document.get("schema") != CASE_SCHEMA:
        raise ValueError("unsupported A0 case schema")
    if document.get("population") != "SYNTHETIC_DEVELOPMENT_ONLY":
        raise ValueError("A0 cases must be marked SYNTHETIC_DEVELOPMENT_ONLY")
    raw_cases = document.get("cases")
    if not isinstance(raw_cases, list) or not MIN_CASES <= len(raw_cases) <= MAX_CASES:
        raise ValueError(f"A0 requires between {MIN_CASES} and {MAX_CASES} cases")

    cases: list[Case] = []
    seen: set[str] = set()
    for raw_case in raw_cases:
        item = _object(raw_case, "case")
        case_id = _text(item.get("case_id"), "case_id")
        if case_id in seen:
            raise ValueError(f"duplicate A0 case ID {case_id!r}")
        seen.add(case_id)
        request = _text(item.get("request"), "request")
        raw_observations = item.get("observations")
        if not isinstance(raw_observations, list) or not raw_observations:
            raise ValueError(f"{case_id}: observations must be a non-empty list")
        observations: list[ObservationSpec] = []
        roles: set[str] = set()
        for raw_observation in raw_observations:
            observation = _object(raw_observation, "observation")
            role = _text(observation.get("role"), "observation.role")
            if role not in {"BASELINE", "FOLLOWUP"} or role in roles:
                raise ValueError(f"{case_id}: observation roles must be unique baseline/follow-up")
            roles.add(role)
            athlete = _text(observation.get("athlete"), "observation.athlete")
            if athlete not in {"A", "B"}:
                raise ValueError(f"{case_id}: only synthetic subjects A and B are supported")
            status = observation.get("status", "VALID")
            if status not in {"VALID", "MISSING"}:
                raise ValueError(f"{case_id}: observation status must be VALID or MISSING")
            raw_value = observation.get("value")
            if status == "MISSING":
                if raw_value is not None:
                    raise ValueError(f"{case_id}: missing observations must not carry a value")
                value = None
            else:
                if isinstance(raw_value, bool) or not isinstance(raw_value, int | float):
                    raise ValueError(f"{case_id}: valid observation values must be numeric")
                value = float(raw_value)
                if not math.isfinite(value):
                    raise ValueError(f"{case_id}: observation values must be finite")
            unit = observation.get("unit")
            if unit not in {None, "m", "cm"}:
                raise ValueError(f"{case_id}: unit must be m, cm, or null")
            observations.append(
                ObservationSpec(
                    role=role,
                    athlete=athlete,
                    value=value,
                    unit=unit,
                    metric=_text(observation.get("metric"), "observation.metric"),
                    status=status,
                )
            )

        expected_raw = _object(item.get("expectation"), "expectation")
        outcome = _text(expected_raw.get("outcome"), "expectation.outcome")
        if outcome not in {"RESULT", "REFUSED"}:
            raise ValueError(f"{case_id}: expectation outcome must be RESULT or REFUSED")
        expected_value = expected_raw.get("value")
        if expected_value is not None:
            if isinstance(expected_value, bool) or not isinstance(expected_value, int | float):
                raise ValueError(f"{case_id}: expected value must be numeric or null")
            expected_value = float(expected_value)
            if not math.isfinite(expected_value):
                raise ValueError(f"{case_id}: expected value must be finite")
        expectation = Expectation(
            outcome=outcome,
            analysis_class=AnalysisClass(
                _text(expected_raw.get("analysis_class"), "analysis_class")
            ),
            measurement_claim_level=_optional_enum(
                MeasurementClaimLevel,
                expected_raw.get("measurement_claim_level"),
                "measurement_claim_level",
            ),
            relationship_claim_level=_optional_enum(
                RelationshipClaimLevel,
                expected_raw.get("relationship_claim_level"),
                "relationship_claim_level",
            ),
            value=expected_value,
            unit=expected_raw.get("unit"),
            reason_code=expected_raw.get("reason_code"),
        )
        if (
            expectation.measurement_claim_level is None
            and expectation.relationship_claim_level is None
        ):
            raise ValueError(f"{case_id}: an expected claim axis is required")
        if outcome == "RESULT" and (expectation.value is None or expectation.unit is None):
            raise ValueError(f"{case_id}: expected results require an independent value and unit")
        if outcome == "REFUSED" and not isinstance(expectation.reason_code, str):
            raise ValueError(f"{case_id}: expected refusals require a reason code")
        cases.append(Case(case_id, request, tuple(observations), expectation))
    return tuple(cases)


def _unit(spec: ObservationSpec) -> UnitReference:
    if spec.unit == "m" or spec.unit is None:
        return cast(UnitReference, METER)
    if spec.unit == "cm":
        return cast(UnitReference, CENTIMETER)
    raise ValueError(f"unsupported synthetic unit {spec.unit!r}")


def _build_context(case: Case) -> CaseContext:
    athletes = {spec.athlete for spec in case.observations}
    entries: list[LongitudinalObservationEntry] = []
    entry_specs: list[tuple[ObservationSpec, LongitudinalObservationEntry, bool]] = []
    if len(athletes) == 1:
        athlete = ATHLETE if next(iter(athletes)) == "A" else OTHER_ATHLETE
        base_entries = _entries(
            tuple(spec.value if spec.value is not None else 0.0 for spec in case.observations),
            prefix=f"res541-a0-{case.case_id}",
            athlete=athlete,
            method="res541-a0-synthetic-method",
        )
        entries.extend(base_entries)
        entry_specs.extend(
            (spec, entry, True) for spec, entry in zip(case.observations, base_entries, strict=True)
        )
    else:
        for index, spec in enumerate(case.observations):
            athlete = ATHLETE if spec.athlete == "A" else OTHER_ATHLETE
            day = 1 if spec.role == "BASELINE" else 2
            pair = _entries(
                (spec.value if spec.value is not None else 0.0,) * 2,
                prefix=f"res541-a0-{case.case_id}-{index}",
                athlete=athlete,
                method="res541-a0-synthetic-method",
                day=day,
            )
            entries.extend(pair)
            entry_specs.extend(((spec, pair[0], True), (spec, pair[1], False)))

    entries_by_role: dict[str, LongitudinalObservationEntry] = {}
    adjusted: list[LongitudinalObservationEntry] = []
    selected_entry_ids: set[str] = set()
    for spec, entry, selected in entry_specs:
        unit = _unit(spec)
        semantic = replace(
            entry.observation.identity.semantic,
            metric_definition=_reference("metric", spec.metric, f"synthetic {spec.metric}"),
        )
        updated = _with_unit(entry, unit, semantic=semantic)
        if spec.status == "MISSING":
            observation = replace(
                updated.observation,
                result=replace(
                    updated.observation.result,
                    value=ScalarValue("MISSING"),
                    status=ResultStatus.MISSING,
                ),
            )
            updated = build_longitudinal_observation_entry(
                observation,
                updated.football_context,
                updated.source_qualification_bindings,
            )
        if spec.unit is None:
            observation = replace(
                updated.observation,
                result=replace(updated.observation.result, unit=None),
            )
            updated = build_longitudinal_observation_entry(
                observation,
                updated.football_context,
                updated.source_qualification_bindings,
            )
        adjusted.append(updated)
        if selected:
            entries_by_role[spec.role] = updated
            selected_entry_ids.add(updated.canonical_entry_id.qualified)

    grouped: dict[str, list[LongitudinalObservationEntry]] = {}
    for entry in adjusted:
        grouped.setdefault(entry.observation.context.athlete_id.qualified, []).append(entry)
    input_records = []
    source_records = []
    for athlete_key in sorted(grouped):
        athlete_entries = tuple(grouped[athlete_key])
        athlete = athlete_entries[0].football_context.athlete
        scope = (
            MultiSourceAnalysisScope.SAME_SESSION
            if len(athletes) == 1
            else MultiSourceAnalysisScope.WITHIN_SEASON
        )
        input_records.append(
            build_multi_source_analysis_input(
                athlete,
                athlete_entries,
                scope,
            )
        )
        source_records.append(
            build_longitudinal_record(
                athlete,
                athlete_entries,
                LongitudinalRecordOrigin.SYNTHETIC_DETERMINISTIC,
            )
        )
    included = tuple(
        entry
        for entry in adjusted
        if entry.canonical_entry_id.qualified in selected_entry_ids
        and entry.observation.result.status is ResultStatus.VALID
    )
    excluded = tuple(
        SupportEntryExclusion.from_entry(
            entry,
            SupportExclusionReason.MISSING_VALUE
            if entry.observation.result.status is ResultStatus.MISSING
            else SupportExclusionReason.NOT_SELECTED,
        )
        for entry in adjusted
        if entry.canonical_entry_id.qualified not in selected_entry_ids
        or entry.observation.result.status is ResultStatus.MISSING
    )
    support = build_statistical_support(
        tuple(input_records),
        included,
        source_records=tuple(source_records),
        excluded_entries=excluded,
    )
    validate_statistical_support(support)
    return CaseContext(case, support, entries_by_role)


def prepare_cases() -> dict[str, object]:
    prepared: list[dict[str, object]] = []
    for case in load_cases():
        context = _build_context(case)
        observations: list[dict[str, object]] = []
        for spec in case.observations:
            entry = context.entries_by_role[spec.role]
            observations.append(
                {
                    "role": spec.role,
                    "entry_id": entry.canonical_entry_id.qualified,
                    "observation_id": entry.source_observation_id.qualified,
                    "athlete_id": entry.observation.context.athlete_id.qualified,
                    "value": spec.value,
                    "unit": spec.unit,
                    "status": spec.status,
                    "metric_definition": (
                        entry.observation.identity.semantic.metric_definition.stable_id
                    ),
                }
            )
        evidence = "\n".join(
            f"{row['role']} entry_id={row['entry_id']} observation_id={row['observation_id']} "
            f"athlete_id={row['athlete_id']} value={row['value']} unit={row['unit']} "
            f"status={row['status']} "
            f"metric_definition={row['metric_definition']}"
            for row in observations
        )
        prepared.append(
            {
                "case_id": case.case_id,
                "user_message": (
                    f"Request: {case.request}\nAvailable synthetic evidence:\n{evidence}"
                ),
                "observations": observations,
            }
        )
    return {
        "schema": PREPARED_SCHEMA,
        "population": "SYNTHETIC_DEVELOPMENT_ONLY",
        "cases": prepared,
    }


def parse_model_intent(raw_text: str) -> ModelIntent:
    if not isinstance(raw_text, str) or not raw_text.strip():
        raise ValueError("model output is empty")
    if len(raw_text) > MAX_MODEL_OUTPUT_CHARS:
        raise ValueError("model output exceeds the character bound")
    value = _object(json.loads(raw_text), "model intent")
    try:
        version = value.get("v")
        if not isinstance(version, int) or isinstance(version, bool) or version != 1:
            raise ValueError("model intent schema version must be 1")
        decision = ModelDecision(_text(value.get("d"), "d"))
        if decision is ModelDecision.EXECUTE:
            fields = {"v", "d", "a", "b", "f", "m", "r"}
            if set(value) != fields:
                raise ValueError("execute intent has an unexpected field set")
            analysis_class = _optional_enum(AnalysisClass, value.get("a"), "a")
            baseline_role = _optional_enum(ObservationRole, value.get("b"), "b")
            followup_role = _optional_enum(ObservationRole, value.get("f"), "f")
            measurement = _optional_enum(MeasurementClaimLevel, value.get("m"), "m")
            relationship = _optional_enum(RelationshipClaimLevel, value.get("r"), "r")
            refusal_reason = None
        else:
            if set(value) != {"v", "d", "x"}:
                raise ValueError("refusal intent has an unexpected field set")
            analysis_class = None
            baseline_role = None
            followup_role = None
            measurement = None
            relationship = None
            refusal_reason = _optional_enum(ModelRefusalReason, value.get("x"), "x")
    except ValueError as exc:
        raise ValueError("model intent contains an invalid typed value") from exc
    if decision is ModelDecision.EXECUTE:
        if analysis_class is None or (measurement is None and relationship is None):
            raise ValueError("execute intents require an analysis class and claim axis")
    elif refusal_reason is None:
        raise ValueError("refusal intents require a registered refusal reason")
    return ModelIntent(
        decision,
        analysis_class,
        baseline_role,
        followup_role,
        measurement,
        relationship,
        refusal_reason,
    )


def _intent_wire(intent: ModelIntent) -> dict[str, str | None]:
    return {
        "schema": INTENT_SCHEMA,
        "decision": intent.decision.value,
        "analysis_class": intent.analysis_class.value if intent.analysis_class else None,
        "baseline_role": intent.baseline_role.value if intent.baseline_role else None,
        "followup_role": intent.followup_role.value if intent.followup_role else None,
        "measurement_claim_level": (
            intent.measurement_claim_level.value if intent.measurement_claim_level else None
        ),
        "relationship_claim_level": (
            intent.relationship_claim_level.value if intent.relationship_claim_level else None
        ),
        "refusal_reason": intent.refusal_reason.value if intent.refusal_reason else None,
    }


def _model_intent_wire(intent: ModelIntent) -> dict[str, str | int | None]:
    if intent.decision is ModelDecision.REFUSE:
        return {
            "v": 1,
            "d": intent.decision.value,
            "x": intent.refusal_reason.value if intent.refusal_reason else None,
        }
    return {
        "v": 1,
        "d": intent.decision.value,
        "a": intent.analysis_class.value if intent.analysis_class else None,
        "b": intent.baseline_role.value if intent.baseline_role else None,
        "f": intent.followup_role.value if intent.followup_role else None,
        "m": intent.measurement_claim_level.value if intent.measurement_claim_level else None,
        "r": intent.relationship_claim_level.value if intent.relationship_claim_level else None,
    }


def oracle_intent(context: CaseContext) -> ModelIntent:
    expected = context.case.expectation
    baseline = context.entries_by_role.get("BASELINE")
    followup = context.entries_by_role.get("FOLLOWUP")
    return ModelIntent(
        ModelDecision.EXECUTE,
        expected.analysis_class,
        ObservationRole.BASELINE if baseline is not None else None,
        ObservationRole.FOLLOWUP if followup is not None else None,
        expected.measurement_claim_level,
        expected.relationship_claim_level,
        None,
    )


def _analysis_request(context: CaseContext, intent: ModelIntent) -> AnalysisAuthorizationRequest:
    assert intent.analysis_class is not None
    support = context.support
    return AnalysisAuthorizationRequest(
        request_id=InstanceIdentifier("analysis-authorization-request", context.case.case_id),
        analysis_class=intent.analysis_class,
        support=support,
        support_reference=None,
        observations=tuple(entry.observation for entry in support.included_entries),
        identity_hashes=(),
        comparability_decisions=(),
        requested_level=AnalysisLevelIdentity(
            unit_of_analysis=AnalysisUnitOfAnalysis.ATHLETE,
            estimand_level=AnalysisEstimandLevel.WITHIN_ATHLETE,
            subject_key="athlete_id",
            clustering_keys=("session_id",),
        ),
        evidence_applicability=None,
        context_references=(),
    )


def _refusal(
    *,
    codes: tuple[str, ...],
    message: str,
    analysis_hash: str | None = None,
    claim_status: str | None = None,
    support_hash: str | None = None,
    refusal_class: str | None = None,
    blocked_claim: str | None = None,
    missing_information: tuple[str, ...] = (),
    safe_descriptions: tuple[str, ...] = (),
) -> dict[str, object]:
    final_text = " ".join(safe_descriptions) if safe_descriptions else message
    return {
        "outcome": "REFUSED",
        "reason_codes": codes,
        "refusal_class": refusal_class,
        "blocked_claim": blocked_claim,
        "missing_information": missing_information or (message,),
        "safe_descriptions": safe_descriptions,
        "analysis_authorization_hash": analysis_hash,
        "claim_authority_status": claim_status,
        "support_hash": support_hash,
        "result_value": None,
        "result_unit": None,
        "statistical_result_hash": None,
        "user_visible_text": f"Refused: {final_text}",
    }


def _refusal_from_result(refusal: RefusalResult, message: str) -> dict[str, object]:
    return _refusal(
        codes=refusal.reason_codes,
        message=message,
        support_hash=None,
        refusal_class=refusal.refusal_class.value,
        blocked_claim=refusal.blocked_claim,
        missing_information=refusal.missing_information,
        safe_descriptions=refusal.what_can_still_be_safely_described,
    )


def _evaluate(
    context: CaseContext,
    raw_text: str,
    metadata: dict[str, Any],
) -> dict[str, object]:
    case = context.case
    try:
        intent = parse_model_intent(raw_text)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        outcome = _refusal(
            codes=("A0_MODEL_INTENT_INVALID",),
            message="model output did not match the bounded typed intent schema",
            support_hash=context.support.canonical_support_hash,
        )
        return {
            "case_id": case.case_id,
            **outcome,
            "model_intent_valid": False,
            "intent_matches_expectation": False,
            "parse_error_category": type(exc).__name__,
            "analysis_dispatched": False,
            **metadata,
        }
    wire_intent = _intent_wire(intent)
    expected_intent = oracle_intent(context)
    intent_matches = wire_intent == _intent_wire(expected_intent)
    if intent.decision is ModelDecision.REFUSE:
        assert intent.refusal_reason is not None
        outcome = _refusal(
            codes=(f"A0_MODEL_REFUSED_{intent.refusal_reason.value}",),
            message="the model requested a refusal; no scientific operation was dispatched",
            support_hash=context.support.canonical_support_hash,
        )
        return {
            "case_id": case.case_id,
            **outcome,
            "model_intent_valid": True,
            "intent_matches_expectation": intent_matches,
            "model_intent": wire_intent,
            "analysis_dispatched": False,
            **metadata,
        }

    assert intent.analysis_class is not None
    request = _analysis_request(context, intent)
    authorization = authorize_analysis(request)
    if isinstance(authorization, RefusalResult):
        return {
            "case_id": case.case_id,
            **_refusal_from_result(
                authorization,
                "the canonical RES-70 analysis authority refused the request",
            ),
            "model_intent_valid": True,
            "intent_matches_expectation": intent_matches,
            "model_intent": wire_intent,
            "analysis_dispatched": False,
            **metadata,
        }

    validate_analysis_authorization(authorization, request)
    if intent.analysis_class is not AnalysisClass.SCALAR_ABSOLUTE_CHANGE:
        return {
            "case_id": case.case_id,
            **_refusal(
                codes=("A0_OPERATION_OUTSIDE_MISSION_SCOPE",),
                message="A0 permits only the registered scalar absolute-change operation",
                analysis_hash=authorization.canonical_authorization_hash,
                support_hash=context.support.canonical_support_hash,
            ),
            "model_intent_valid": True,
            "intent_matches_expectation": intent_matches,
            "model_intent": wire_intent,
            "analysis_dispatched": False,
            **metadata,
        }

    baseline = context.entries_by_role.get("BASELINE")
    followup = context.entries_by_role.get("FOLLOWUP")
    if (
        baseline is None
        or followup is None
        or intent.baseline_role is not ObservationRole.BASELINE
        or intent.followup_role is not ObservationRole.FOLLOWUP
    ):
        return {
            "case_id": case.case_id,
            **_refusal(
                codes=("RES70_REGISTRY_INTEGRITY_FAILURE",),
                message="model-selected entries do not match the exact baseline/follow-up support",
                analysis_hash=authorization.canonical_authorization_hash,
                support_hash=context.support.canonical_support_hash,
            ),
            "model_intent_valid": True,
            "intent_matches_expectation": intent_matches,
            "model_intent": wire_intent,
            "analysis_dispatched": False,
            **metadata,
        }

    if (
        authorization.operation_reference != RES69_ABSOLUTE_CHANGE_OPERATION
        or authorization.estimator_reference != RES69_ABSOLUTE_CHANGE_ESTIMATOR
    ):
        return {
            "case_id": case.case_id,
            **_refusal(
                codes=("RES70_REGISTRY_INTEGRITY_FAILURE",),
                message="canonical capability does not resolve to the pinned A0 operation",
                analysis_hash=authorization.canonical_authorization_hash,
                support_hash=context.support.canonical_support_hash,
            ),
            "model_intent_valid": True,
            "intent_matches_expectation": intent_matches,
            "model_intent": wire_intent,
            "analysis_dispatched": False,
            **metadata,
        }

    result = calculate_absolute_change(
        context.support,
        baseline_entry=baseline,
        followup_entry=followup,
    )
    if isinstance(result, RefusalResult):
        return {
            "case_id": case.case_id,
            **_refusal_from_result(result, "the canonical RES-69 operation refused the support"),
            "model_intent_valid": True,
            "intent_matches_expectation": intent_matches,
            "model_intent": wire_intent,
            "analysis_authorization_hash": authorization.canonical_authorization_hash,
            "analysis_dispatched": True,
            **metadata,
        }
    validate_statistical_result(result)
    estimate = result.estimates[0]
    if (
        result.operation != authorization.operation_reference
        or result.analysis_run.estimator != authorization.estimator_reference
        or result.analysis_run.support_hash != context.support.canonical_support_hash
    ):
        return {
            "case_id": case.case_id,
            **_refusal(
                codes=("RES70_REGISTRY_INTEGRITY_FAILURE",),
                message="RES-69 result does not match its exact authorized operation and support",
                analysis_hash=authorization.canonical_authorization_hash,
                support_hash=context.support.canonical_support_hash,
            ),
            "model_intent_valid": True,
            "intent_matches_expectation": intent_matches,
            "model_intent": wire_intent,
            "analysis_dispatched": True,
            **metadata,
        }

    claim = ClaimIntent(
        claim_reference=_reference(
            "claim-intent", f"res541-a0-{case.case_id}", "A0 synthetic claim"
        ),
        measurement_level=intent.measurement_claim_level,
        relationship_level=intent.relationship_claim_level,
        predictive_intent=None,
        target=ClaimTarget.ATHLETE_WITHIN,
        analysis_reference=authorization.capability_reference,
        evidence_applicability_reference=None,
        decision_criterion_reference=None,
        observations=tuple(entry.observation for entry in context.support.included_entries),
        analysis_authorization=authorization,
        statistical_result=result,
        analysis_authorization_request=request,
    )
    claim_result = authorize_claim(claim)
    validate_claim_authority(claim_result, claim)
    if (
        claim_result.status is not ClaimAuthorityStatus.AUTHORIZED
        or intent.measurement_claim_level is not MeasurementClaimLevel.NUMERICAL_CHANGE
        or intent.relationship_claim_level is not None
    ):
        codes = claim_result.reason_codes or ("A0_CLAIM_OUTSIDE_MISSION_SCOPE",)
        message = (
            "RES-70 claim authority did not authorize the requested numerical-change-only claim"
        )
        claim_refusal = claim_result.refusal_result
        return {
            "case_id": case.case_id,
            **_refusal(
                codes=codes,
                message=message,
                analysis_hash=authorization.canonical_authorization_hash,
                claim_status=claim_result.status.value,
                support_hash=context.support.canonical_support_hash,
                refusal_class=(
                    claim_refusal.refusal_class.value if claim_refusal is not None else None
                ),
                blocked_claim=(claim_refusal.blocked_claim if claim_refusal is not None else None),
                missing_information=claim_result.missing_information,
                safe_descriptions=claim_result.safe_descriptions,
            ),
            "model_intent_valid": True,
            "intent_matches_expectation": intent_matches,
            "model_intent": wire_intent,
            "analysis_dispatched": True,
            "claim_authority_hash": claim_result.canonical_decision_hash,
            **metadata,
        }

    unit: StatisticalUnitReference = estimate.unit
    unit_label = unit.display_label
    value = estimate.value
    rendered = format(value, ".12g")
    return {
        "case_id": case.case_id,
        "outcome": "RESULT",
        "reason_codes": (),
        "missing_information": (),
        "model_intent_valid": True,
        "intent_matches_expectation": intent_matches,
        "model_intent": wire_intent,
        "analysis_authorization_hash": authorization.canonical_authorization_hash,
        "claim_authority_hash": claim_result.canonical_decision_hash,
        "claim_authority_status": claim_result.status.value,
        "analysis_dispatched": True,
        "support_hash": context.support.canonical_support_hash,
        "statistical_result_hash": result.canonical_output_hash,
        "result_value": value,
        "result_unit": unit_label,
        "user_visible_text": (
            f"Follow-up minus baseline equals {rendered} {unit_label}. The registered result is "
            "a numerical change only and does not assess improvement, meaningfulness, readiness, "
            "fatigue, or causality."
        ),
        **metadata,
    }


def score_outputs(
    model_outputs: dict[str, Any],
    *,
    source_revision: str,
    runtime: dict[str, object] | None = None,
    resource: dict[str, object] | None = None,
) -> dict[str, object]:
    if model_outputs.get("schema") != OUTPUT_SCHEMA:
        raise ValueError("unsupported A0 model-output schema")
    if model_outputs.get("status") != "COMPLETE":
        raise ValueError("A0 model inference did not complete")
    if (
        model_outputs.get("model_id") != "HuggingFaceTB/SmolLM3-3B"
        or model_outputs.get("model_revision") != "a07cc9a04f16550a088caea529712d1d335b0ac1"
        or model_outputs.get("intent_schema") != INTENT_SCHEMA
    ):
        raise ValueError("model outputs do not match the pinned model and intent schema")
    raw_outputs = model_outputs.get("cases")
    if not isinstance(raw_outputs, list):
        raise ValueError("model outputs must contain a case list")
    output_by_id: dict[str, dict[str, Any]] = {}
    for raw in raw_outputs:
        item = _object(raw, "model output")
        case_id = _text(item.get("case_id"), "model output case_id")
        if case_id in output_by_id:
            raise ValueError(f"duplicate model output for {case_id!r}")
        output_by_id[case_id] = item

    cases = load_cases()
    expected_ids = {case.case_id for case in cases}
    if set(output_by_id) != expected_ids:
        raise ValueError("model output case IDs do not exactly match the frozen A0 cases")
    rows: list[dict[str, object]] = []
    for case in cases:
        output = output_by_id[case.case_id]
        raw_text = output.get("raw_text")
        if not isinstance(raw_text, str):
            raw_text = ""
        metadata = {
            key: output.get(key)
            for key in (
                "prompt_sha256",
                "prompt_tokens",
                "generated_tokens",
                "latency_ms",
                "first_token_latency_ms",
                "failure_category",
            )
        }
        context = _build_context(case)
        row = _evaluate(context, raw_text, metadata)
        row["model_role_bindings"] = {
            role: context.entries_by_role[role].canonical_entry_id.qualified
            for role in ("BASELINE", "FOLLOWUP")
            if role in context.entries_by_role
        }
        row["support_included_entry_ids"] = [
            entry.canonical_entry_id.qualified for entry in context.support.included_entries
        ]
        row["support_observation_ids"] = [
            entry.source_observation_id.qualified for entry in context.support.included_entries
        ]
        row["support_exclusions"] = [
            {
                "entry_id": item.reference.entry_id.qualified,
                "observation_id": item.reference.observation_id.qualified,
                "reason": item.reason.value,
            }
            for item in context.support.excluded_entries
        ]
        row["model_output_sha256"] = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
        row["raw_model_output"] = raw_text[:MAX_MODEL_OUTPUT_CHARS]
        expected = case.expectation
        actual_outcome = row["outcome"]
        row["outcome_matches_expectation"] = actual_outcome == expected.outcome
        raw_codes = row.get("reason_codes", ())
        actual_codes = tuple(raw_codes) if isinstance(raw_codes, tuple | list) else ()
        row["reason_code_matches_expectation"] = (
            expected.reason_code is None
            if expected.outcome == "RESULT"
            else expected.reason_code is not None and expected.reason_code in actual_codes
        )
        value_matches = (
            row.get("result_value") == expected.value and row.get("result_unit") == expected.unit
        )
        row["numeric_expectation_matches"] = value_matches if expected.outcome == "RESULT" else None
        rows.append(row)

    total = len(cases)
    result_cases = tuple(case for case in cases if case.expectation.outcome == "RESULT")
    refusal_cases = tuple(case for case in cases if case.expectation.outcome == "REFUSED")
    outcomes_by_id = {str(row["case_id"]): row for row in rows}
    tp = sum(outcomes_by_id[case.case_id]["outcome"] == "REFUSED" for case in refusal_cases)
    fp = sum(outcomes_by_id[case.case_id]["outcome"] == "REFUSED" for case in result_cases)
    fn = len(refusal_cases) - tp
    numeric_rows = tuple(row for row in rows if row["result_value"] is not None)
    wrong_values = sum(row["numeric_expectation_matches"] is not True for row in numeric_rows)
    boundary_violations = sum(
        outcomes_by_id[case.case_id]["outcome"] == "RESULT" for case in refusal_cases
    )
    correct_results = sum(
        outcomes_by_id[case.case_id]["outcome"] == "RESULT"
        and outcomes_by_id[case.case_id]["numeric_expectation_matches"] is True
        for case in result_cases
    )
    correct_refusals = sum(
        outcomes_by_id[case.case_id]["outcome"] == "REFUSED"
        and outcomes_by_id[case.case_id]["reason_code_matches_expectation"] is True
        for case in refusal_cases
    )
    valid_intents = sum(row["model_intent_valid"] is True for row in rows)
    matching_intents = sum(row["intent_matches_expectation"] is True for row in rows)
    system_failures = tuple(
        str(row["failure_category"])
        for row in rows
        if isinstance(row.get("failure_category"), str) and row["failure_category"]
    )
    dispatched = sum(
        outcomes_by_id[case.case_id]["analysis_dispatched"] is True for case in result_cases
    )
    latencies: list[float] = []
    first_token_latencies: list[float] = []
    generated_tokens = 0
    prompt_tokens = 0
    for row in rows:
        latency = row.get("latency_ms")
        first_token_latency = row.get("first_token_latency_ms")
        generated_count = row.get("generated_tokens")
        prompt_count = row.get("prompt_tokens")
        if isinstance(latency, int | float):
            latencies.append(float(latency))
        if isinstance(first_token_latency, int | float):
            first_token_latencies.append(float(first_token_latency))
        if isinstance(generated_count, int) and not isinstance(generated_count, bool):
            generated_tokens += generated_count
        if isinstance(prompt_count, int) and not isinstance(prompt_count, bool):
            prompt_tokens += prompt_count
    full_match = (
        all(row["outcome_matches_expectation"] for row in rows)
        and all(row["reason_code_matches_expectation"] for row in rows)
        and all(
            row["numeric_expectation_matches"] is True for row in rows if row["outcome"] == "RESULT"
        )
        and all(row["intent_matches_expectation"] for row in rows)
        and boundary_violations == 0
        and wrong_values == 0
    )
    has_numeric_success = correct_results > 0
    has_authority_refusal = any(
        row["outcome"] == "REFUSED"
        and any(
            str(code).startswith(("RES69_", "RES70_", "COMPUTATION_NOT_REGISTERED"))
            for code in _string_values(row.get("reason_codes"))
        )
        for row in rows
    )
    run_status = (
        "NO_GO"
        if system_failures
        else "PASS"
        if full_match
        else "PASS_WITH_LIMITATIONS"
        if has_numeric_success
        and has_authority_refusal
        and boundary_violations == 0
        and wrong_values == 0
        else "NO_GO"
    )
    error_categories: dict[str, int] = {}
    for row in rows:
        failure_category = row.get("failure_category")
        if isinstance(failure_category, str) and failure_category:
            error_categories[failure_category] = error_categories.get(failure_category, 0) + 1
        for code in _string_values(row.get("reason_codes")):
            error_categories[str(code)] = error_categories.get(str(code), 0) + 1
    return {
        "schema": REPORT_SCHEMA,
        "status": run_status,
        "scope": "SYNTHETIC_DEVELOPMENT_ONLY",
        "source_revision": source_revision,
        "case_manifest_sha256": hashlib.sha256(CASES_PATH.read_bytes()).hexdigest(),
        "intent_schema": INTENT_SCHEMA,
        "model": {
            "id": "HuggingFaceTB/SmolLM3-3B",
            "revision": "a07cc9a04f16550a088caea529712d1d335b0ac1",
            "training_or_fine_tuning": False,
        },
        "runtime": runtime or {},
        "resource": resource or {},
        "decoding": {
            "do_sample": False,
            "num_beams": 1,
            "max_new_tokens_per_case": 64,
            "max_prompt_tokens": 1024,
            "seed": 541,
        },
        "metrics": {
            "case_count": total,
            "typed_intent_valid": {"numerator": valid_intents, "denominator": total},
            "intent_task_match": {"numerator": matching_intents, "denominator": total},
            "registered_tool_dispatch_success": {
                "numerator": dispatched,
                "denominator": len(result_cases),
            },
            "numeric_authority_integrity": {
                "matching_values": len(numeric_rows) - wrong_values,
                "reported_values": len(numeric_rows),
                "incorrect_or_invented_values": wrong_values,
            },
            "refusal_precision": {
                "true_positive": tp,
                "false_positive": fp,
                "denominator": tp + fp,
            },
            "refusal_recall": {
                "true_positive": tp,
                "false_negative": fn,
                "denominator": len(refusal_cases),
            },
            "refusal_expected_cases": len(refusal_cases),
            "boundary_violations": boundary_violations,
            "expected_numeric_cases_passed": {
                "numerator": correct_results,
                "denominator": len(result_cases),
            },
            "expected_refusal_cases_passed": {
                "numerator": correct_refusals,
                "denominator": len(refusal_cases),
            },
            "mean_generation_latency_ms": sum(latencies) / len(latencies) if latencies else None,
            "mean_first_token_latency_ms": (
                sum(first_token_latencies) / len(first_token_latencies)
                if first_token_latencies
                else None
            ),
            "prompt_tokens_total": prompt_tokens,
            "generated_tokens_total": generated_tokens,
            "failure_categories": error_categories,
            "system_failure_count": len(system_failures),
            "confidence_limits": "not estimated; this is a small development-only suite",
        },
        "cases": rows,
    }


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "score"))
    parser.add_argument("--model-outputs", type=Path)
    parser.add_argument("--source-revision", default="LOCAL_CPU_VALIDATION")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.command == "prepare":
        document = prepare_cases()
    else:
        if args.model_outputs is None:
            parser.error("score requires --model-outputs")
        outputs = _object(
            json.loads(args.model_outputs.read_text(encoding="utf-8")), "model outputs"
        )
        runtime = outputs.get("runtime")
        document = score_outputs(
            outputs,
            source_revision=args.source_revision,
            runtime=runtime if isinstance(runtime, dict) else None,
        )
    rendered = json.dumps(document, indent=2, sort_keys=True) + "\n"
    if args.output is None:
        sys.stdout.write(rendered)
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
