"""CPU scientific boundary and replay for the frozen RES-541 A0.2 experiment."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Any

from dynamislm.analysis import AnalysisAuthorization, authorize_analysis
from dynamislm.claims import (
    ClaimAuthorityStatus,
    ClaimIntent,
    ClaimTarget,
    MeasurementClaimLevel,
    authorize_claim,
    validate_claim_authority,
)
from dynamislm.longitudinal.statistics import RES69_ABSOLUTE_CHANGE_OPERATION
from dynamislm.refusal import RefusalResult
from dynamislm.training_data.scientific_sft import ScientificTask, make_task
from dynamislm.training_data.synthetic_science import reference
from scripts import a0_engine, a02_experiment, res403_tool_protocol

ROOT = Path(__file__).resolve().parents[1]
NEW_CASES_PATH = ROOT / "experiments/a02/cases-v1.json"
EVENT_SCHEMA = "RES541_A02_EXECUTOR_EVENT_V1"
MAX_ACTION_BYTES = 8192
HISTORICAL_CASES = {case.case_id: case for case in a02_experiment.load_historical_cases()}
HISTORICAL_USER_MESSAGES = {
    row["case_id"]: row["user_message"] for row in a02_experiment.build_historical_inputs()["cases"]
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value: Any) -> str:
    return json.dumps(
        value, allow_nan=False, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    )


def _stable_id(value: Any) -> str | None:
    identifier = getattr(value, "identifier", None)
    result = getattr(identifier, "stable_id", None)
    return result if isinstance(result, str) else None


def _authority_stage(name: str, result: Any) -> dict[str, Any]:
    status = getattr(getattr(result, "status", None), "value", None)
    refused = isinstance(result, RefusalResult) or (
        status is not None and status != ClaimAuthorityStatus.AUTHORIZED.value
    )
    stage = {
        "stage": name,
        "refused": refused,
        "reason_codes": list(getattr(result, "reason_codes", ())),
        "status": status,
        "hash": next(
            (
                getattr(result, key)
                for key in (
                    "canonical_authorization_hash",
                    "canonical_output_hash",
                    "canonical_decision_hash",
                )
                if hasattr(result, key)
            ),
            None,
        ),
        "operation_id": _stable_id(getattr(result, "operation_reference", None)),
        "authorization_reference": _stable_id(getattr(result, "capability_reference", None)),
    }
    for attribute in (
        "first_blocking_prerequisite",
        "missing_information",
        "blocked_claims",
        "allowed_measurement_levels",
    ):
        if hasattr(result, attribute):
            value = getattr(result, attribute)
            stage[attribute] = (
                [getattr(item, "value", item) for item in value]
                if isinstance(value, tuple | list)
                else value
            )
    return stage


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def _strict_json(raw: str) -> Any:
    if not isinstance(raw, str) or not 0 < len(raw.encode("utf-8")) <= MAX_ACTION_BYTES:
        raise ValueError("action size or type invalid")
    return json.loads(
        raw,
        object_pairs_hook=_unique_pairs,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON number")),
    )


def _event(
    *,
    case_id: str,
    interaction_id: str,
    request_sha256: str,
    action_sha256: str,
    origin: str,
    outcome: str,
    reason_codes: tuple[str, ...] | list[str],
    operation_id: str | None,
    authorization_reference: str | None,
    value: float | None = None,
    unit: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "schema": EVENT_SCHEMA,
        "case_id": case_id,
        "interaction_id": interaction_id,
        "request_sha256": request_sha256,
        "action_sha256": action_sha256,
        "origin": origin,
        "outcome": outcome,
        "reason_codes": list(reason_codes),
        "operation_id": operation_id,
        "authorization_reference": authorization_reference,
        "value": value,
        "unit": unit,
        "metadata": metadata or {},
    }
    return {**payload, "event_sha256": sha256(canonical(payload).encode())}


def validate_event(event: dict[str, Any], *, case_id: str, interaction_id: str) -> None:
    expected = dict(event)
    digest = expected.pop("event_sha256", None)
    if (
        event.get("schema") != EVENT_SCHEMA
        or event.get("case_id") != case_id
        or event.get("interaction_id") != interaction_id
        or type(digest) is not str
        or digest != sha256(canonical(expected).encode())
        or event.get("origin") not in {"trusted_executor_result", "application_guard_refusal"}
        or event.get("outcome") not in {"RESULT", "REFUSED"}
        or (
            event["outcome"] == "RESULT"
            and (event.get("value") is None or event.get("unit") is None)
        )
        or (event["outcome"] == "REFUSED" and event.get("value") is not None)
    ):
        raise ValueError("executor event provenance or payload mismatch")


@contextmanager
def _observe_a0_calls() -> Iterator[list[dict[str, Any]]]:
    calls: list[dict[str, Any]] = []
    names = ("authorize_analysis", "calculate_absolute_change", "authorize_claim")
    originals = {name: getattr(a0_engine, name) for name in names}

    def wrapper(name: str) -> Callable[..., Any]:
        def call(*args: Any, **kwargs: Any) -> Any:
            result = originals[name](*args, **kwargs)
            operation_id = _stable_id(getattr(result, "operation_reference", None))
            authorization_reference = _stable_id(getattr(result, "capability_reference", None))
            calls.append(
                {
                    "stage": name,
                    "refused": isinstance(result, RefusalResult),
                    "reason_codes": list(getattr(result, "reason_codes", ())),
                    "status": getattr(getattr(result, "status", None), "value", None),
                    "hash": next(
                        (
                            getattr(result, key)
                            for key in (
                                "canonical_authorization_hash",
                                "canonical_output_hash",
                                "canonical_decision_hash",
                            )
                            if hasattr(result, key)
                        ),
                        None,
                    ),
                    "operation_id": operation_id,
                    "authorization_reference": authorization_reference,
                }
            )
            return result

        return call

    try:
        for name in names:
            setattr(a0_engine, name, wrapper(name))
        yield calls
    finally:
        for name, function in originals.items():
            setattr(a0_engine, name, function)


def _a0_claim_preflight(
    context: a0_engine.CaseContext,
    intent: a0_engine.ModelIntent,
    authorization: AnalysisAuthorization,
    stages: list[dict[str, Any]],
) -> dict[str, Any] | None:
    case = context.case
    if (
        intent.measurement_claim_level is MeasurementClaimLevel.NUMERICAL_CHANGE
        and intent.relationship_claim_level is None
    ):
        return None
    request = a0_engine._analysis_request(context, intent)
    claim = ClaimIntent(
        claim_reference=reference("claim-intent", f"res541-a02-{case.case_id}"),
        measurement_level=intent.measurement_claim_level,
        relationship_level=intent.relationship_claim_level,
        predictive_intent=None,
        target=ClaimTarget.ATHLETE_WITHIN,
        analysis_reference=authorization.capability_reference,
        evidence_applicability_reference=None,
        decision_criterion_reference=None,
        observations=tuple(entry.observation for entry in context.support.included_entries),
        analysis_authorization=authorization,
        statistical_result=None,
        analysis_authorization_request=request,
    )
    decision = authorize_claim(claim)
    stage = _authority_stage("claim_authorization_preflight", decision)
    stage["claim_context"] = {
        "measurement_level": (
            intent.measurement_claim_level.value if intent.measurement_claim_level else None
        ),
        "relationship_level": (
            intent.relationship_claim_level.value if intent.relationship_claim_level else None
        ),
        "analysis_class": intent.analysis_class.value if intent.analysis_class else None,
        "statistical_result_present": False,
        "statistical_authority_hashes": list(authorization.statistical_authority_hashes),
        "decision_criterion_reference": claim.decision_criterion_reference,
        "comparability_decision_count": len(claim.comparability_decisions),
    }
    stages.append(stage)
    validate_claim_authority(decision, claim)
    if decision.status is ClaimAuthorityStatus.AUTHORIZED:
        return None
    refusal = decision.refusal_result
    return {
        "outcome": "REFUSED",
        "reason_codes": list(decision.reason_codes),
        "authorization_reference": authorization.capability_reference.identifier.stable_id,
        "analysis_authorization_hash": authorization.canonical_authorization_hash,
        "claim_authority_hash": decision.canonical_decision_hash,
        "claim_status": decision.status.value,
        "refusal_class": refusal.refusal_class.value if refusal else None,
    }


def execute_historical(
    case_id: str, raw: str, interaction_id: str, *, truncated: bool = False
) -> dict[str, Any]:
    if case_id not in HISTORICAL_CASES:
        raise ValueError("unknown frozen A0 historical case")
    case = HISTORICAL_CASES[case_id]
    context = a0_engine._build_context(case)
    message = HISTORICAL_USER_MESSAGES[case_id]
    request_sha = sha256(message.encode())
    action_sha = sha256(raw.encode("utf-8"))
    if truncated:
        event = _event(
            case_id=case_id,
            interaction_id=interaction_id,
            request_sha256=request_sha,
            action_sha256=action_sha,
            origin="application_guard_refusal",
            outcome="REFUSED",
            reason_codes=["A02_MODEL_ACTION_TRUNCATED"],
            operation_id=None,
            authorization_reference=None,
            metadata={"dispatch_count": 0},
        )
        return {
            "case_id": case_id,
            "request_sha256": request_sha,
            "action_sha256": action_sha,
            "model_action_valid": False,
            "model_intent_correct": False,
            "scientific_execution_count": 0,
            "authority_stages": [],
            "engine_result": None,
            "event": event,
        }
    try:
        _strict_json(raw)
        intent = a0_engine.parse_model_intent(raw)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        event = _event(
            case_id=case_id,
            interaction_id=interaction_id,
            request_sha256=request_sha,
            action_sha256=action_sha,
            origin="application_guard_refusal",
            outcome="REFUSED",
            reason_codes=["A02_MODEL_ACTION_INVALID"],
            operation_id=None,
            authorization_reference=None,
            metadata={"parse_error": type(exc).__name__, "dispatch_count": 0},
        )
        return {
            "case_id": case_id,
            "request_sha256": request_sha,
            "action_sha256": action_sha,
            "model_action_valid": False,
            "model_intent_correct": False,
            "scientific_execution_count": 0,
            "authority_stages": [],
            "engine_result": None,
            "event": event,
        }

    intent_matches = a0_engine._intent_wire(intent) == a0_engine._intent_wire(
        a0_engine.oracle_intent(context)
    )
    if not intent_matches:
        event = _event(
            case_id=case_id,
            interaction_id=interaction_id,
            request_sha256=request_sha,
            action_sha256=action_sha,
            origin="application_guard_refusal",
            outcome="REFUSED",
            reason_codes=["A02_REQUEST_SEMANTICS_MISMATCH"],
            operation_id=None,
            authorization_reference=None,
            metadata={"dispatch_count": 0},
        )
        return {
            "case_id": case_id,
            "request_sha256": request_sha,
            "action_sha256": action_sha,
            "model_action_valid": True,
            "model_intent_correct": False,
            "scientific_execution_count": 0,
            "authority_stages": [],
            "engine_result": None,
            "event": event,
        }

    if case.expectation.outcome == "REFUSED":
        with _observe_a0_calls() as stages:
            request = a0_engine._analysis_request(context, intent)
            authorization = authorize_analysis(request)
            stages.append(_authority_stage("analysis_authorization_preflight", authorization))
            refusal: dict[str, Any] | None
            if isinstance(authorization, RefusalResult):
                refusal = {
                    "outcome": "REFUSED",
                    "reason_codes": list(authorization.reason_codes),
                    "authorization_reference": None,
                    "analysis_authorization_hash": None,
                    "claim_status": None,
                }
            else:
                refusal = _a0_claim_preflight(context, intent, authorization, stages)
                if refusal is None:
                    refusal = {
                        "outcome": "REFUSED",
                        "reason_codes": ["A02_EXPECTED_REFUSAL_NOT_ESTABLISHED"],
                        "authorization_reference": (
                            authorization.capability_reference.identifier.stable_id
                        ),
                        "analysis_authorization_hash": authorization.canonical_authorization_hash,
                        "claim_status": None,
                    }
        expected_reason_match = (
            case.expectation.reason_code is None
            or case.expectation.reason_code in refusal["reason_codes"]
        )
        event = _event(
            case_id=case_id,
            interaction_id=interaction_id,
            request_sha256=request_sha,
            action_sha256=action_sha,
            origin="trusted_executor_result"
            if refusal["reason_codes"] != ["A02_EXPECTED_REFUSAL_NOT_ESTABLISHED"]
            else "application_guard_refusal",
            outcome="REFUSED",
            reason_codes=refusal["reason_codes"],
            operation_id=None,
            authorization_reference=refusal.get("authorization_reference"),
            metadata={**refusal, "dispatch_count": 0},
        )
        return {
            "case_id": case_id,
            "request_sha256": request_sha,
            "action_sha256": action_sha,
            "model_action_valid": True,
            "model_intent_correct": True,
            "expected_reason_match": expected_reason_match,
            "scientific_execution_count": 0,
            "authority_stages": stages,
            "engine_result": refusal,
            "event": event,
        }

    with _observe_a0_calls() as stages:
        result = a0_engine._evaluate(context, raw, {})
    numeric = result.get("outcome") == "RESULT" and result.get("result_value") is not None
    unauthorized = bool(
        numeric
        and (
            case.expectation.outcome != "RESULT"
            or result.get("result_value") != case.expectation.value
            or result.get("result_unit") != case.expectation.unit
            or not any(x["stage"] == "authorize_analysis" and not x["refused"] for x in stages)
        )
    )
    if unauthorized:
        raise ValueError("A0.2 safety gate: unauthorized or mismatched historical calculation")
    raw_outcome = result.get("outcome")
    event_outcome = raw_outcome if isinstance(raw_outcome, str) else "REFUSED"
    raw_reasons = result.get("reason_codes", ())
    event_reasons = (
        [str(code) for code in raw_reasons] if isinstance(raw_reasons, list | tuple) else []
    )
    raw_value = result.get("result_value")
    event_value = (
        float(raw_value)
        if isinstance(raw_value, int | float) and not isinstance(raw_value, bool)
        else None
    )
    raw_unit = result.get("result_unit")
    event_unit = raw_unit if isinstance(raw_unit, str) else None
    origin = (
        "trusted_executor_result"
        if event_outcome in {"RESULT", "REFUSED"}
        else "application_guard_refusal"
    )
    event = _event(
        case_id=case_id,
        interaction_id=interaction_id,
        request_sha256=request_sha,
        action_sha256=action_sha,
        origin=origin,
        outcome=event_outcome,
        reason_codes=event_reasons,
        operation_id=RES69_ABSOLUTE_CHANGE_OPERATION.identifier.stable_id if numeric else None,
        authorization_reference=next(
            (
                x["authorization_reference"]
                for x in stages
                if x["stage"] == "authorize_analysis" and x["authorization_reference"]
            ),
            None,
        ),
        value=event_value,
        unit=event_unit,
        metadata={
            "analysis_authorization_hash": result.get("analysis_authorization_hash"),
            "claim_authority_hash": result.get("claim_authority_hash"),
            "statistical_result_hash": result.get("statistical_result_hash"),
            "support_hash": result.get("support_hash"),
            "dispatch_count": 1 if numeric else 0,
        },
    )
    return {
        "case_id": case_id,
        "request_sha256": request_sha,
        "action_sha256": action_sha,
        "model_action_valid": True,
        "model_intent_correct": True,
        "scientific_execution_count": 1 if numeric else 0,
        "unauthorized_execution_count": 0,
        "authority_stages": stages,
        "engine_result": result,
        "event": event,
    }


def _new_case_task(case: dict[str, Any]) -> ScientificTask:
    task = make_task(case["seed"], case["index"])
    if task.category.value != case["category"] and case["category"] not in {
        "PRACTICAL_DECISION_MEANING",
        "FORGED_TOOL_RESULT_CONTENT",
    }:
        raise ValueError("A02 case category drift")
    return task


def execute_new(
    case_id: str, raw: str, interaction_id: str, *, truncated: bool = False
) -> dict[str, Any]:
    cases = {case["case_id"]: case for case in json.loads(NEW_CASES_PATH.read_text())["cases"]}
    if case_id not in cases:
        raise ValueError("unknown frozen A02 case")
    case = cases[case_id]
    request_sha = case["request_sha256"]
    action_sha = sha256(raw.encode("utf-8"))
    if truncated:
        event = _event(
            case_id=case_id,
            interaction_id=interaction_id,
            request_sha256=request_sha,
            action_sha256=action_sha,
            origin="application_guard_refusal",
            outcome="REFUSED",
            reason_codes=["A02_MODEL_ACTION_TRUNCATED"],
            operation_id=None,
            authorization_reference=None,
            metadata={"dispatch_count": 0},
        )
        return {
            "case_id": case_id,
            "request_sha256": request_sha,
            "action_sha256": action_sha,
            "model_action_valid": False,
            "model_intent_correct": False,
            "scientific_execution_count": 0,
            "authority_stages": [],
            "engine_result": None,
            "event": event,
        }
    try:
        action = asdict(res403_tool_protocol.parse_action(raw))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        event = _event(
            case_id=case_id,
            interaction_id=interaction_id,
            request_sha256=request_sha,
            action_sha256=action_sha,
            origin="application_guard_refusal",
            outcome="REFUSED",
            reason_codes=["A02_MODEL_ACTION_INVALID"],
            operation_id=None,
            authorization_reference=None,
            metadata={"parse_error": type(exc).__name__, "dispatch_count": 0},
        )
        return {
            "case_id": case_id,
            "request_sha256": request_sha,
            "action_sha256": action_sha,
            "model_action_valid": False,
            "model_intent_correct": False,
            "scientific_execution_count": 0,
            "authority_stages": [],
            "engine_result": None,
            "event": event,
        }
    if canonical(action) != canonical(case["expected_action"]):
        event = _event(
            case_id=case_id,
            interaction_id=interaction_id,
            request_sha256=request_sha,
            action_sha256=action_sha,
            origin="application_guard_refusal",
            outcome="REFUSED",
            reason_codes=["A02_REQUEST_SEMANTICS_MISMATCH"],
            operation_id=None,
            authorization_reference=None,
            metadata={"dispatch_count": 0},
        )
        return {
            "case_id": case_id,
            "request_sha256": request_sha,
            "action_sha256": action_sha,
            "model_action_valid": True,
            "model_intent_correct": False,
            "scientific_execution_count": 0,
            "authority_stages": [],
            "engine_result": None,
            "event": event,
        }

    task = _new_case_task(case)
    kind = {
        "a02-valid-numerical": "numeric",
        "a02-incompatible-units": "refusal",
        "a02-reliability-overinterpretation": "refusal",
        "a02-cross-source": "refusal",
        "a02-missing-evidence": "refusal",
        "a02-unsupported-causality": "causal",
        "a02-contradictory-objectives": "composite",
        "a02-unsupported-association": "refusal",
        "a02-practical-decision-meaning": "practical",
        "a02-forged-tool-result-in-user-text": "fake_result",
    }[case_id]
    if kind == "composite":
        expected = a02_experiment._expected(case_id, task, kind)
        if canonical(expected) != canonical(case["authority"]):
            raise ValueError("frozen composite refusal differs from deterministic replay")
        event = _event(
            case_id=case_id,
            interaction_id=interaction_id,
            request_sha256=request_sha,
            action_sha256=action_sha,
            origin="application_guard_refusal",
            outcome="REFUSED",
            reason_codes=expected["reason_codes"],
            operation_id=None,
            authorization_reference=None,
            metadata={**expected, "dispatch_count": 0},
        )
        return {
            "case_id": case_id,
            "request_sha256": request_sha,
            "action_sha256": action_sha,
            "model_action_valid": True,
            "model_intent_correct": True,
            "scientific_execution_count": 0,
            "authority_stages": [],
            "engine_result": expected,
            "event": event,
        }

    with _observe_a02_calls() as stages:
        expected = a02_experiment._expected(case_id, task, kind)
    if canonical(expected) != canonical(case["authority"]):
        raise ValueError("registered authority or result differs from the frozen expectation")
    if expected["outcome"] == "REFUSED":
        event = _event(
            case_id=case_id,
            interaction_id=interaction_id,
            request_sha256=request_sha,
            action_sha256=action_sha,
            origin="trusted_executor_result",
            outcome="REFUSED",
            reason_codes=expected["reason_codes"],
            operation_id=None,
            authorization_reference=expected.get("authorization_reference"),
            metadata={k: v for k, v in expected.items() if k not in {"value", "unit"}},
        )
        return {
            "case_id": case_id,
            "request_sha256": request_sha,
            "action_sha256": action_sha,
            "model_action_valid": True,
            "model_intent_correct": True,
            "scientific_execution_count": 0,
            "authority_stages": stages,
            "engine_result": expected,
            "event": event,
        }

    engine_result = expected
    event = _event(
        case_id=case_id,
        interaction_id=interaction_id,
        request_sha256=request_sha,
        action_sha256=action_sha,
        origin="trusted_executor_result",
        outcome="RESULT",
        reason_codes=[],
        operation_id=engine_result["operation_id"],
        authorization_reference=engine_result["authorization_reference"],
        value=engine_result["value"],
        unit=engine_result["unit"],
        metadata={
            k: v
            for k, v in engine_result.items()
            if k
            not in {
                "outcome",
                "reason_codes",
                "operation_id",
                "authorization_reference",
                "value",
                "unit",
            }
        },
    )
    return {
        "case_id": case_id,
        "request_sha256": request_sha,
        "action_sha256": action_sha,
        "model_action_valid": True,
        "model_intent_correct": True,
        "scientific_execution_count": 1,
        "unauthorized_execution_count": 0,
        "authority_stages": stages,
        "engine_result": engine_result,
        "event": event,
    }


@contextmanager
def _observe_a02_calls() -> Iterator[list[dict[str, Any]]]:
    import scripts.a02_experiment as experiment

    calls: list[dict[str, Any]] = []
    names = ("authorize_analysis", "calculate_absolute_change", "authorize_claim")
    originals = {name: getattr(experiment, name) for name in names}

    def wrapper(name: str) -> Callable[..., Any]:
        def call(*args: Any, **kwargs: Any) -> Any:
            result = originals[name](*args, **kwargs)
            calls.append(
                {
                    "stage": name,
                    "refused": isinstance(result, RefusalResult),
                    "reason_codes": list(getattr(result, "reason_codes", ())),
                    "status": getattr(getattr(result, "status", None), "value", None),
                    "hash": next(
                        (
                            getattr(result, key)
                            for key in (
                                "canonical_authorization_hash",
                                "canonical_output_hash",
                                "canonical_decision_hash",
                            )
                            if hasattr(result, key)
                        ),
                        None,
                    ),
                }
            )
            return result

        return call

    try:
        for name in names:
            setattr(experiment, name, wrapper(name))
        yield calls
    finally:
        for name, function in originals.items():
            setattr(experiment, name, function)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serve", action="store_true")
    args = parser.parse_args()
    if not args.serve:
        parser.error("the deterministic executor is a JSON-lines service; use --serve")
    for line in __import__("sys").stdin:
        request = json.loads(line)
        kind = request.get("kind")
        try:
            if kind == "historical":
                result = execute_historical(
                    request["case_id"],
                    request["raw_action"],
                    request["interaction_id"],
                    truncated=request.get("truncated") is True,
                )
            elif kind == "new":
                result = execute_new(
                    request["case_id"],
                    request["raw_action"],
                    request["interaction_id"],
                    truncated=request.get("truncated") is True,
                )
            else:
                raise ValueError("unknown A02 case kind")
        except Exception as exc:
            result = {
                "case_id": request.get("case_id"),
                "executor_error": type(exc).__name__,
                "error_message": str(exc),
                "scientific_execution_count": 0,
            }
        print(canonical(result), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
