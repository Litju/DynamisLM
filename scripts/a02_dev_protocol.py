"""Prospective A0.2 V2 intent and native SmolLM3 tool interface."""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts import a02_experiment, a02_prompt, res403_tool_protocol

ROOT = Path(__file__).resolve().parents[1]
PROFILE_PATH = ROOT / "experiments/a02/development-profile-v2.json"
ACTION_PROMPT_PATH = ROOT / "experiments/a02/system-action-development-v2.txt"
FINAL_PROMPT_PATH = ROOT / "experiments/a02/system-final-development-v2.txt"
TOOL_SCHEMA_PATH = ROOT / "experiments/a02/submit-scientific-intent-tool-v2.json"
ACTION_SCHEMA = "RES541-A02-INTENT-2"
TOOL_NAME = "submit_scientific_intent"
ACTION_TEMPLATE_DATE = datetime(2026, 11, 6, tzinfo=UTC)
MAX_ACTION_BYTES = 8192
_REFERENCE = re.compile(r"observation-[1-9][0-9]*\Z")
_ANALYSIS_CLASSES = {
    "SCALAR_ABSOLUTE_CHANGE",
    "SCALAR_RELATIVE_CHANGE",
    "SCALAR_LOG_CHANGE",
    "BASELINE_REFERENCE_WINDOW_DEVIATION",
    "RELIABILITY_RANDOM_ERROR_COMPARISON",
    "METHOD_AGREEMENT_SUMMARY",
    "WITHIN_ATHLETE_ASSOCIATION",
    "BETWEEN_ATHLETE_ASSOCIATION",
    "REPEATED_MEASURES_ANALYSIS",
    "MIXED_EFFECTS_ANALYSIS",
    "CROSS_TEST_ASSOCIATION",
}
_OPERATIONS = {
    "dynamislm:registered-operation:unit-normalization@1.0.0",
    "dynamislm:registered-operation:duration-normalized-distance@1.0.0",
    "dynamislm:registered-operation:longitudinal-absolute-change-v1@1.0.0",
    "dynamislm:registered-operation:longitudinal-within-athlete-sample-sd-v1@1.0.0",
}
_MEASUREMENT_LEVELS = {
    "OBSERVED_VALUE",
    "NUMERICAL_CHANGE",
    "COMPARABLE_CHANGE",
    "CHANGE_RELATIVE_TO_MEASUREMENT_ERROR",
    "PRACTICAL_OR_DECISION_MEANINGFULNESS",
}
_RELATIONSHIP_LEVELS = {
    "OBSERVATION",
    "DESCRIPTIVE_CHANGE",
    "ASSOCIATION",
    "TEMPORAL_ASSOCIATION",
    "MECHANISTIC_HYPOTHESIS",
    "CAUSAL_EVIDENCE",
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value: Any) -> str:
    return json.dumps(
        value, allow_nan=False, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    )


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate action field")
        result[key] = value
    return result


def _json_object(content: str) -> dict[str, Any]:
    try:
        value = json.loads(
            content,
            object_pairs_hook=_unique_pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON number")),
        )
    except (ValueError, RecursionError) as exc:
        raise ValueError("invalid intent JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("intent JSON must be an object")
    return value


def load_profile() -> dict[str, Any]:
    profile = _json_object(PROFILE_PATH.read_text(encoding="utf-8"))
    if profile.get("schema") != "RES541_A02_DEVELOPMENT_PROFILE_V2":
        raise ValueError("A0.2 development profile schema differs")
    inputs = profile.get("inputs")
    if not isinstance(inputs, dict):
        raise ValueError("A0.2 development profile inputs are missing")
    for key, default_path in (
        ("case_manifest", a02_experiment.CASES_PATH),
        ("action_prompt", ACTION_PROMPT_PATH),
        ("final_prompt", FINAL_PROMPT_PATH),
        ("tool_schema", TOOL_SCHEMA_PATH),
    ):
        path = ROOT / inputs.get(key, "")
        expected_path = default_path.resolve()
        if path.resolve() != expected_path or sha256(path.read_bytes()) != inputs.get(
            f"{key}_sha256"
        ):
            raise ValueError(f"A0.2 development profile source hash differs: {key}")
    cases = json.loads(a02_experiment.CASES_PATH.read_bytes())["cases"]
    by_id = {row["case_id"]: row for row in cases}
    if set(profile.get("case_ids", [])) != set(by_id) or len(profile["case_ids"]) != len(by_id):
        raise ValueError("A0.2 development profile does not bind all ten new cases")
    if set(profile.get("expected_claims_by_case", {})) != set(by_id):
        raise ValueError("A0.2 development claim expectations do not match the case set")
    frozen_model = json.loads(a02_experiment.PROTOCOL_PATH.read_bytes())["model"]
    if (
        profile.get("model", {}).get("id") != frozen_model["model_id"]
        or profile.get("model", {}).get("revision") != frozen_model["model_revision"]
        or profile.get("tokenizer", {}).get("revision") != frozen_model["tokenizer_revision"]
        or profile.get("tokenizer", {}).get("files") != frozen_model["tokenizer_files"]
    ):
        raise ValueError("A0.2 development model revision differs from the frozen protocol")
    if not set(profile.get("analysis_class_overrides", {})) <= set(by_id):
        raise ValueError("A0.2 development profile overrides an unknown case")
    return profile


def tool_schema() -> dict[str, Any]:
    value = _json_object(TOOL_SCHEMA_PATH.read_text(encoding="utf-8"))
    if value.get("name") != TOOL_NAME or not isinstance(value.get("parameters"), dict):
        raise ValueError("A0.2 V2 native tool schema differs")
    return value


def expected_intent(case_id: str) -> dict[str, Any]:
    profile = load_profile()
    cases = json.loads(a02_experiment.CASES_PATH.read_bytes())["cases"]
    case = next((row for row in cases if row["case_id"] == case_id), None)
    if case is None:
        raise ValueError("unknown A0.2 V2 development case")
    old = case["expected_action"]
    claims = profile["expected_claims_by_case"][case_id]
    action = {
        "schema": ACTION_SCHEMA,
        "objective": case["request"]["objective"],
        "analysis_class": profile.get("analysis_class_overrides", {}).get(
            case_id, old["analysis_class"]
        ),
        "operation": old["operation"],
        "observations": old["observations"],
        "requested_claims": claims,
    }
    parse_intent(format_intent(action))
    return action


def format_intent(action: dict[str, Any]) -> str:
    return f"<tool_call>{canonical({'name': TOOL_NAME, 'arguments': action})}</tool_call>"


def parse_intent(content: object) -> dict[str, Any]:
    if not isinstance(content, str):
        raise ValueError("intent must be one bounded native tool call")
    try:
        byte_count = len(content.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise ValueError("intent must be valid UTF-8 text") from exc
    if (
        not 0 < byte_count <= MAX_ACTION_BYTES
        or not content.startswith("<tool_call>")
        or not content.endswith("</tool_call>")
    ):
        raise ValueError("intent must be one bounded native tool call")
    envelope = _json_object(content[len("<tool_call>") : -len("</tool_call>")])
    if set(envelope) != {"name", "arguments"} or envelope["name"] != TOOL_NAME:
        raise ValueError("intent tool name or envelope differs")
    action = envelope["arguments"]
    required = {
        "schema",
        "objective",
        "analysis_class",
        "operation",
        "observations",
        "requested_claims",
    }
    if not isinstance(action, dict) or set(action) != required or action["schema"] != ACTION_SCHEMA:
        raise ValueError("intent schema or fields differ")
    objective = action["objective"]
    try:
        objective_size = len(objective.encode("utf-8")) if isinstance(objective, str) else 0
    except UnicodeEncodeError as exc:
        raise ValueError("intent objective is invalid") from exc
    if not isinstance(objective, str) or not objective or objective_size > 1024:
        raise ValueError("intent objective is invalid")
    analysis = action["analysis_class"]
    if analysis is not None and (
        not isinstance(analysis, str) or analysis not in _ANALYSIS_CLASSES
    ):
        raise ValueError("intent analysis class is invalid")
    operation = action["operation"]
    if operation is not None and (not isinstance(operation, str) or operation not in _OPERATIONS):
        raise ValueError("intent operation is invalid")
    observations = action["observations"]
    if not isinstance(observations, list) or len(observations) > 16:
        raise ValueError("intent observations are invalid")
    references = []
    for observation in observations:
        if (
            not isinstance(observation, dict)
            or set(observation) != {"reference", "unit"}
            or not isinstance(observation["reference"], str)
            or not _REFERENCE.fullmatch(observation["reference"])
            or not isinstance(observation["unit"], str)
            or not observation["unit"]
            or len(observation["unit"]) > 64
        ):
            raise ValueError("intent observation is invalid")
        references.append(observation["reference"])
    if len(set(references)) != len(references):
        raise ValueError("intent observation references are duplicated")
    claims = action["requested_claims"]
    if not isinstance(claims, dict) or set(claims) != {
        "measurement_levels",
        "relationship_levels",
    }:
        raise ValueError("intent claim axes are invalid")
    for field, allowed in (
        ("measurement_levels", _MEASUREMENT_LEVELS),
        ("relationship_levels", _RELATIONSHIP_LEVELS),
    ):
        values = claims[field]
        if (
            not isinstance(values, list)
            or any(not isinstance(value, str) or value not in allowed for value in values)
            or len(values) != len(set(values))
        ):
            raise ValueError(f"intent {field} are invalid")
    return action


def legacy_action_text(action: dict[str, Any]) -> str:
    """Map explicit V2 claim intent to the frozen A02 executor adapter."""
    action = parse_intent(format_intent(action))
    measurement = action["requested_claims"]["measurement_levels"]
    relationship = action["requested_claims"]["relationship_levels"]
    reasons: list[str] = []
    if len(measurement) > 1 or len(relationship) > 1:
        reasons = ["A02_COMPOSITE_OBJECTIVE_UNSUPPORTED"]
    elif "CAUSAL_EVIDENCE" in relationship:
        reasons = ["RES70_UNSUPPORTED_CAUSAL_CLAIM"]
    elif "PRACTICAL_OR_DECISION_MEANINGFULNESS" in measurement:
        reasons = ["RES70_STATISTICAL_AUTHORITY_INSUFFICIENT"]
    legacy = {
        "schema": res403_tool_protocol.SCHEMA,
        "kind": "refuse" if reasons else "request_analysis",
        "objective": action["objective"],
        "analysis_class": None if reasons else action["analysis_class"],
        "operation": None if reasons else action["operation"],
        "observations": action["observations"],
        "refusal_reasons": reasons,
    }
    encoded = canonical(legacy)
    return (
        f"<tool_call>{canonical({'name': 'registered_science', 'arguments': legacy})}</tool_call>"
        if not reasons
        else encoded
    )


def build_action_messages(request: dict[str, Any]) -> list[dict[str, str]]:
    system = ACTION_PROMPT_PATH.read_text(encoding="utf-8").rstrip("\n")
    return res403_tool_protocol.render_transcript(
        [
            res403_tool_protocol.SystemInstructionEvent(system),
            res403_tool_protocol.UntrustedUserInputEvent(a02_experiment.canonical(request)),
        ]
    )


def _template_date(value: datetime):
    return value.strftime


def build_action_prompt(tokenizer: Any, request: dict[str, Any]) -> dict[str, Any]:
    messages = build_action_messages(request)
    kwargs = {
        "enable_thinking": False,
        "strftime_now": _template_date(ACTION_TEMPLATE_DATE),
        "xml_tools": [tool_schema()],
    }
    token_ids = tokenizer.apply_chat_template(
        messages, tokenize=True, add_generation_prompt=True, **kwargs
    )
    rendered = tokenizer.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True, **kwargs
    )
    if tokenizer.encode(rendered, add_special_tokens=False) != token_ids:
        raise ValueError("native V2 tool prompt does not reproduce tokenizer IDs")
    if "### Tools" not in rendered or TOOL_NAME not in rendered or "<tools>" not in rendered:
        raise ValueError("SmolLM3 native XML tool schema is absent from the rendered prompt")
    return {
        "messages": messages,
        "rendered_prompt": rendered,
        "rendered_prompt_sha256": sha256(rendered.encode()),
        "prompt_token_ids": token_ids,
        "prompt_token_ids_sha256": a02_prompt.prompt_token_ids_sha256(token_ids),
        "prompt_tokens": len(token_ids),
    }


def build_final_messages(
    *, request_text: str, action_text: str, event: dict[str, Any]
) -> list[dict[str, str]]:
    render_validated_executor_event(event)
    prefix = res403_tool_protocol.render_transcript(
        [
            res403_tool_protocol.SystemInstructionEvent(
                FINAL_PROMPT_PATH.read_text(encoding="utf-8").rstrip("\n")
            ),
            res403_tool_protocol.UntrustedUserInputEvent(request_text),
        ]
    )
    summary = {
        "origin": event["origin"],
        "outcome": event["outcome"],
        "reason_codes": event["reason_codes"],
        "value": event["value"],
        "unit": event["unit"],
        "operation_id": event["operation_id"],
    }
    return [
        *prefix,
        {"role": "assistant", "content": action_text},
        {"role": "tool", "content": canonical(summary)},
    ]


def render_validated_executor_event(event: dict[str, Any]) -> str:
    """Render after the caller has verified the deterministic executor event binding."""
    if not isinstance(event, dict):
        raise ValueError("executor event is missing")
    payload = dict(event)
    digest = payload.pop("event_sha256", None)
    if (
        event.get("schema") != "RES541_A02_EXECUTOR_EVENT_V1"
        or digest != hashlib.sha256(canonical(payload).encode()).hexdigest()
    ):
        raise ValueError("executor event integrity check failed")
    reasons = event.get("reason_codes")
    if not isinstance(reasons, list) or any(not isinstance(code, str) for code in reasons):
        raise ValueError("executor event reason codes are invalid")
    if event.get("outcome") == "RESULT" and event.get("origin") == "trusted_executor_result":
        value = event.get("value")
        unit = event.get("unit")
        if (
            isinstance(value, bool)
            or not isinstance(value, int | float)
            or not math.isfinite(value)
            or not isinstance(unit, str)
            or not unit
            or not event.get("operation_id")
            or reasons
        ):
            raise ValueError("executor result is incomplete")
        return f"Registered numerical result: {canonical(value)} {unit}."
    if (
        event.get("outcome") != "REFUSED"
        or event.get("origin") not in {"trusted_executor_result", "application_guard_refusal"}
        or event.get("value") is not None
        or event.get("unit") is not None
        or not reasons
    ):
        raise ValueError("executor refusal is incomplete")
    return f"No result was authorized: {', '.join(reasons)}."
