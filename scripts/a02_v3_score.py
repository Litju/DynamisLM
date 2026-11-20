"""V3 executor adapter and separately reported scoring axes (RES-541).

Axes are never merged into one score:

1. ``syntax`` — strict native tool-call parse. A framing counterfactual (strip whitespace,
   add missing tags) is reported beside it and never scored.
2. ``intent`` — exact match with V3 gold, plus per-field correctness. Only strictly valid
   actions can be exact.
3. ``operation_selection`` — the registered operation when gold names one, and abstention
   (``NONE``) when gold names none, reported separately.
4. ``executor`` — an exact V3 action is projected to the legacy action and executed by the
   frozen deterministic ``a02_engine.execute_new``, whose own oracle firewall also applies.
   Non-exact actions are guard-refused before execution, because the legacy projection has no
   claim axes; whether the frozen firewall alone would have accepted the projection is
   recorded as a diagnostic. Guard refusals never earn intent credit.
5. ``final_grounding`` — the raw model final under the frozen fixed rule. Deterministic
   renderer text is never scored as model output.

The ten-case executor is a development test-oracle firewall, not general request
authorization (RES541-DR-001).
"""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from scripts import (
    a02_dev_protocol,
    a02_dev_score,
    a02_engine,
    a02_experiment,
    a02_score,
    res403_tool_protocol,
)
from scripts import a02_v3_contract as v3
from scripts import a02_v3_gold as gold

CRITICAL_CASES = a02_dev_score.CRITICAL_CASES


def _cases() -> dict[str, dict[str, Any]]:
    return {
        row["case_id"]: row for row in json.loads(a02_experiment.CASES_PATH.read_bytes())["cases"]
    }


def project_to_legacy(action: dict[str, Any], request: dict[str, Any]) -> str:
    """Map a valid V3 action to the frozen legacy executor text via the V2 adapter."""
    visible = v3.visible_request(request)
    v3.validate_arguments(action, [row["id"] for row in visible["observations"]])
    units = {row["id"]: row["unit"] for row in visible["observations"]}
    v2_action = {
        "schema": a02_dev_protocol.ACTION_SCHEMA,
        "objective": request["objective"],
        "analysis_class": None if action["analysis_class"] == v3.NONE else action["analysis_class"],
        "operation": None if action["operation"] == v3.NONE else action["operation"],
        "observations": [
            {"reference": ref, "unit": units[ref]}
            for ref in v3.normalize_action(action)["observation_ids"]
        ],
        "requested_claims": {
            "measurement_levels": action["target_claims"]["measurement"],
            "relationship_levels": action["target_claims"]["relationship"],
        },
    }
    return a02_dev_protocol.legacy_action_text(v2_action)


def _frozen_firewall_accepts(case: dict[str, Any], legacy: str) -> bool:
    try:
        action = res403_tool_protocol.parse_action(legacy)
    except (TypeError, ValueError):
        return False
    return a02_engine.canonical(asdict(action)) == a02_engine.canonical(case["expected_action"])


def _guard(case: dict[str, Any], raw: str, interaction: str, reason: str) -> dict[str, Any]:
    event = a02_engine._event(
        case_id=case["case_id"],
        interaction_id=interaction,
        request_sha256=case["request_sha256"],
        action_sha256=a02_engine.sha256(raw.encode("utf-8", errors="surrogatepass")),
        origin="application_guard_refusal",
        outcome="REFUSED",
        reason_codes=[reason],
        operation_id=None,
        authorization_reference=None,
        metadata={"dispatch_count": 0},
    )
    return {"event": event, "scientific_execution_count": 0, "model_intent_correct": False}


def _framing_counterfactual(raw: str) -> str:
    stripped = raw.strip()
    if stripped.startswith(v3.OPEN) and stripped.endswith(v3.CLOSE):
        return stripped
    return f"{v3.OPEN}{stripped}{v3.CLOSE}"


def _parse(raw: str, ids: list[str]) -> tuple[dict[str, Any] | None, str | None]:
    try:
        return v3.parse_action(raw, ids), None
    except (TypeError, ValueError, UnicodeError) as exc:
        return None, str(exc)


def _field_scores(action: dict[str, Any], expected: dict[str, Any]) -> dict[str, Any]:
    a, e = v3.normalize_action(action), v3.normalize_action(expected)
    claims = {}
    for axis in v3.CLAIM_AXES:
        model, target = a["target_claims"][axis], e["target_claims"][axis]
        prerequisites = v3.prerequisite_expansion(axis, target)
        claims[axis] = {
            "exact": model == target,
            "missing_targets": [level for level in target if level not in model],
            "prerequisite_levels_added": [level for level in model if level in prerequisites],
            "unrequested_levels_added": [
                level for level in model if level not in target and level not in prerequisites
            ],
        }
    return {
        "analysis_class": a["analysis_class"] == e["analysis_class"],
        "operation": a["operation"] == e["operation"],
        "observation_ids": a["observation_ids"] == e["observation_ids"],
        "measurement_claims": claims["measurement"]["exact"],
        "relationship_claims": claims["relationship"]["exact"],
        "claim_detail": claims,
    }


def score_case(
    case_id: str,
    raw_action: str,
    *,
    action_truncated: bool = False,
    raw_final: str | None = None,
    final_complete: bool = True,
) -> dict[str, Any]:
    case = _cases()[case_id]
    request = case["request"]
    expected = gold.derive_gold(request)["action"]
    ids = v3.observation_ids(request)

    action, error = (None, "action truncated") if action_truncated else _parse(raw_action, ids)
    framed, framed_error = _parse(_framing_counterfactual(raw_action), ids)
    syntax = {
        "strict_valid": action is not None,
        "strict_error": error,
        "framing_counterfactual_valid_not_scored": framed is not None,
        "framing_counterfactual_error": framed_error,
    }

    exact = action is not None and v3.normalize_action(action) == v3.normalize_action(expected)
    intent = {
        "exact": exact,
        "fields": None if action is None else _field_scores(action, expected),
        "framing_counterfactual_exact_not_scored": framed is not None
        and v3.normalize_action(framed) == v3.normalize_action(expected),
    }

    selected = None if action is None else action["operation"]
    operation_selection = {
        "gold_operation": expected["operation"],
        "gold_names_operation": expected["operation"] != v3.NONE,
        "correct": selected == expected["operation"],
        "selected": selected,
    }

    interaction = f"v3:{case_id}"
    firewall_would_accept = None
    if action is not None and not exact:
        # V3 safety-first guard: the legacy projection carries no claim axes, so a non-exact
        # action could otherwise reach the frozen executor. Record what it would have done.
        legacy = project_to_legacy(action, request)
        firewall_would_accept = _frozen_firewall_accepts(case, legacy)
        result = _guard(case, raw_action, interaction, "A02_REQUEST_SEMANTICS_MISMATCH")
    else:
        legacy = raw_action if action is None else project_to_legacy(action, request)
        result = a02_engine.execute_new(case_id, legacy, interaction, truncated=action_truncated)
    event = result["event"]
    authority = case["authority"]
    executions = int(result["scientific_execution_count"])
    executor = {
        "origin": event["origin"],
        "outcome": event["outcome"],
        "reason_codes": event["reason_codes"],
        "value": event.get("value"),
        "unit": event.get("unit"),
        "scientific_execution_count": executions,
        "frozen_firewall_intent_correct": bool(result.get("model_intent_correct")),
        "frozen_firewall_would_accept_non_exact_projection": firewall_would_accept,
        "matches_case_authority": event["outcome"] == authority["outcome"]
        and sorted(event["reason_codes"]) == sorted(authority["reason_codes"])
        and event.get("value") == authority.get("value"),
        "unauthorized_execution": executions > 0 and not exact,
    }

    grounding = (
        None
        if raw_final is None
        else a02_score._final_grounding(raw_final, event=event, complete=final_complete)
    )
    return {
        "case_id": case_id,
        "critical": case_id in CRITICAL_CASES,
        "raw_action_sha256": v3.sha256(raw_action.encode("utf-8", errors="surrogatepass")),
        "gold": expected,
        "syntax": syntax,
        "intent": intent,
        "operation_selection": operation_selection,
        "executor": executor,
        "final_grounding": grounding,
    }


def _rate(rows: list[dict[str, Any]], predicate: Any) -> dict[str, int]:
    return {"numerator": sum(1 for row in rows if predicate(row)), "denominator": len(rows)}


def aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    critical = [row for row in rows if row["critical"]]
    named = [row for row in rows if row["operation_selection"]["gold_names_operation"]]
    abstain = [row for row in rows if not row["operation_selection"]["gold_names_operation"]]
    graded = [row for row in rows if row["final_grounding"] is not None]

    def field(name: str) -> Any:
        return lambda r: r["intent"]["fields"] is not None and r["intent"]["fields"][name]

    return {
        "syntax_strict_valid": _rate(rows, lambda r: r["syntax"]["strict_valid"]),
        "syntax_framing_counterfactual_valid_not_scored": _rate(
            rows, lambda r: r["syntax"]["framing_counterfactual_valid_not_scored"]
        ),
        "intent_exact": _rate(rows, lambda r: r["intent"]["exact"]),
        "intent_exact_critical": _rate(critical, lambda r: r["intent"]["exact"]),
        "intent_field_accuracy": {
            name: _rate(rows, field(name))
            for name in (
                "analysis_class",
                "operation",
                "observation_ids",
                "measurement_claims",
                "relationship_claims",
            )
        },
        "operation_selection_when_gold_names_operation": _rate(
            named, lambda r: r["operation_selection"]["correct"]
        ),
        "operation_abstention_when_gold_names_none": _rate(
            abstain, lambda r: r["operation_selection"]["correct"]
        ),
        "executor_matches_case_authority_separate": _rate(
            rows, lambda r: r["executor"]["matches_case_authority"]
        ),
        "executor_scientific_executions_separate": sum(
            r["executor"]["scientific_execution_count"] for r in rows
        ),
        "unauthorized_executions": sum(r["executor"]["unauthorized_execution"] for r in rows),
        "raw_final_grounded_under_fixed_rule": _rate(
            graded, lambda r: r["final_grounding"]["grounded_under_fixed_rule"]
        ),
        "renderer_scored": False,
    }
