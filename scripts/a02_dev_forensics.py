"""Read-only forensic diagnosis of retained A0.2 V2 development generations.

This module never rescored, normalizes, or rewrites a frozen run. It verifies the
retained bytes, reports every contract violation in each raw action (not only
the first parser error), runs separately labelled framing counterfactuals, and
compares extracted fields with the frozen gold intent. Counterfactual outcomes
are diagnostic evidence only; they never replace the original session score.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from dynamislm.claims.registry import RES70_CLAIM_POLICIES, ClaimAxis
from scripts import a02_dev_protocol, a02_experiment

E_ROOT = Path("/mnt/e/DynamisLM-A0").resolve()
SCHEMA = "RES541_A02_DEV_V2_FORENSIC_DIAGNOSIS_V1"
TOOL_CALL_OPEN = "<tool_call>"
TOOL_CALL_CLOSE = "</tool_call>"
GOLD_REFERENCE = re.compile(r"observation-[1-9][0-9]*")

# Framing counterfactuals. Each changes only characters outside the JSON value.
COUNTERFACTUALS = {
    "CF0_AS_GENERATED": "Raw decoded text exactly as retained.",
    "CF1_STRIP_SURROUNDING_WHITESPACE": "Surrounding whitespace removed; no other change.",
    "CF2_ADD_MISSING_TOOL_CALL_TAGS": (
        "Whitespace removed and the documented <tool_call></tool_call> framing added around "
        "otherwise unchanged text. This adds framing that the model did not emit."
    ),
}

TRANSPORT = "TRANSPORT_FORMAT"
SCHEMA_KIND = "SCHEMA_CONTRACT"
REPRESENTATION = "CLAIM_REPRESENTATION"
SEMANTIC = "SCIENTIFIC_SEMANTIC"
HARNESS = "HARNESS_CONTRACT_DEFECT"

_LADDER: dict[str, dict[str, int]] = {"measurement_levels": {}, "relationship_levels": {}}
for _policy in RES70_CLAIM_POLICIES:
    _axis = (
        "measurement_levels"
        if _policy.axis is ClaimAxis.MEASUREMENT_CHANGE
        else "relationship_levels"
    )
    _LADDER[_axis][_policy.level.value] = _policy.ordinal


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path.name}")
    return value


def _brace_balance(text: str) -> int:
    """Unclosed `{`/`[` depth outside JSON strings; negative means excess closers."""
    depth = 0
    in_string = False
    escaped = False
    for char in text:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char in "{[":
            depth += 1
        elif char in "}]":
            depth -= 1
    return depth


def _strict_object(text: str) -> dict[str, Any]:
    return a02_dev_protocol._json_object(text)


def _decode_value_at(text: str, key: str) -> tuple[bool, Any]:
    """Decode one complete JSON value following the first `"key": ` occurrence."""
    marker = f'"{key}":'
    index = text.find(marker)
    if index < 0:
        return False, None
    start = index + len(marker)
    while start < len(text) and text[start] in " \t\r\n":
        start += 1
    try:
        value, _ = json.JSONDecoder(object_pairs_hook=a02_dev_protocol._unique_pairs).raw_decode(
            text, start
        )
    except ValueError:
        return False, None
    return True, value


def extract_arguments(text: str) -> dict[str, Any]:
    """Recover only complete JSON values the model emitted; never repair content."""
    try:
        envelope = _strict_object(text)
        return {
            "method": "STRICT_ENVELOPE",
            "envelope_keys": sorted(envelope),
            "name": envelope.get("name"),
            "arguments": envelope.get("arguments"),
        }
    except ValueError:
        pass
    found_name, name = _decode_value_at(text, "name")
    found_args, arguments = _decode_value_at(text, "arguments")
    if found_args and isinstance(arguments, dict):
        return {
            "method": "ARGUMENTS_OBJECT_COMPLETE_ENVELOPE_INVALID",
            "envelope_keys": None,
            "name": name if found_name else None,
            "arguments": arguments,
        }
    partial: dict[str, Any] = {}
    args_index = text.find('"arguments":')
    scope = text[args_index:] if args_index >= 0 else text
    for key in (
        "schema",
        "objective",
        "analysis_class",
        "operation",
        "observations",
        "requested_claims",
    ):
        found, value = _decode_value_at(scope, key)
        if found:
            partial[key] = value
    if "requested_claims" not in partial:
        claims_index = scope.find('"requested_claims":')
        if claims_index >= 0:
            claims: dict[str, Any] = {}
            for axis in ("measurement_levels", "relationship_levels"):
                found, value = _decode_value_at(scope[claims_index:], axis)
                if found:
                    claims[axis] = value
            if claims:
                partial["requested_claims"] = claims
    return {
        "method": "PARTIAL_COMPLETE_FIELDS_ONLY",
        "envelope_keys": None,
        "name": name if found_name else None,
        "arguments": partial,
    }


def _parser_outcome(text: str) -> dict[str, Any]:
    try:
        a02_dev_protocol.parse_intent(text)
    except (TypeError, ValueError) as exc:
        return {"parse_valid": False, "first_error": str(exc)}
    return {"parse_valid": True, "first_error": None}


def counterfactuals(raw_text: str) -> dict[str, dict[str, Any]]:
    stripped = raw_text.strip()
    variants = {
        "CF0_AS_GENERATED": raw_text,
        "CF1_STRIP_SURROUNDING_WHITESPACE": stripped,
        "CF2_ADD_MISSING_TOOL_CALL_TAGS": (
            stripped
            if stripped.startswith(TOOL_CALL_OPEN) and stripped.endswith(TOOL_CALL_CLOSE)
            else f"{TOOL_CALL_OPEN}{stripped}{TOOL_CALL_CLOSE}"
        ),
    }
    return {
        name: {
            "description": COUNTERFACTUALS[name],
            "changed_from_raw": text != raw_text,
            **_parser_outcome(text),
        }
        for name, text in variants.items()
    }


def _registered_operation_containing(value: str) -> list[str]:
    return sorted(op for op in a02_dev_protocol._OPERATIONS if value and value in op)


def operation_analysis_pairs() -> dict[str, set[str]]:
    """Registered operation to analysis-class pairs, derived only from frozen gold intents."""
    pairs: dict[str, set[str]] = {}
    for case_id in a02_dev_protocol.load_profile()["case_ids"]:
        gold = a02_dev_protocol.expected_intent(case_id)
        if gold["operation"] is not None and gold["analysis_class"] is not None:
            pairs.setdefault(gold["operation"], set()).add(gold["analysis_class"])
    return pairs


def _claim_axis_diagnosis(axis: str, model: object, gold: list[str]) -> dict[str, Any]:
    ladder = _LADDER[axis]
    if not isinstance(model, list) or any(not isinstance(v, str) for v in model):
        return {"present": False, "exact": False, "gold": gold, "model": model}
    invalid = sorted(set(model) - set(ladder))
    gold_max = max((ladder[v] for v in gold), default=-1)
    above = sorted((v for v in model if ladder.get(v, -1) > gold_max), key=ladder.__getitem__)
    below_unrequested = sorted(
        (v for v in model if v not in gold and 0 <= ladder.get(v, -1) < gold_max),
        key=ladder.__getitem__,
    )
    model_max = max((ladder[v] for v in model if v in ladder), default=-1)
    return {
        "present": True,
        "model": model,
        "gold": gold,
        "exact": sorted(model) == sorted(gold),
        "gold_levels_preserved": set(gold) <= set(model),
        "missing_gold_levels": sorted(set(gold) - set(model)),
        "invalid_levels": invalid,
        "levels_above_requested_maximum": above,
        "unrequested_lower_prerequisite_levels": below_unrequested,
        "highest_level_matches_gold": model_max == gold_max,
        "model_lists_full_ladder_prefix": bool(model)
        and sorted(model, key=lambda v: ladder.get(v, 99))
        == [k for k, r in sorted(ladder.items(), key=lambda kv: kv[1]) if r <= model_max],
    }


def diagnose_action(
    *,
    case_id: str,
    raw_text: str,
    generation: dict[str, Any],
    request: dict[str, Any],
    gold: dict[str, Any],
    rendered_prompt: str,
    tool_call_token_ids: tuple[int, int],
    operation_pairs: dict[str, set[str]],
) -> dict[str, Any]:
    ids = generation["generated_token_ids"]
    findings: list[dict[str, str]] = []

    def finding(kind: str, code: str, detail: str) -> None:
        findings.append({"kind": kind, "code": code, "detail": detail})

    stripped = raw_text.strip()
    transport = {
        "starts_with_tool_call_tag": raw_text.startswith(TOOL_CALL_OPEN),
        "ends_with_tool_call_tag": raw_text.endswith(TOOL_CALL_CLOSE),
        "tool_call_open_token_emitted": tool_call_token_ids[0] in ids,
        "tool_call_close_token_emitted": tool_call_token_ids[1] in ids,
        "surrounding_whitespace": raw_text != stripped,
        "first_char": raw_text[:1],
        "eos_seen": generation["eos_seen"],
        "truncated": generation["truncated"],
        "generated_tokens": generation["generated_tokens"],
        "max_new_tokens": generation["max_new_tokens"],
        "unclosed_json_depth": _brace_balance(stripped),
    }
    if not transport["tool_call_open_token_emitted"] and not transport["starts_with_tool_call_tag"]:
        finding(TRANSPORT, "MISSING_TOOL_CALL_WRAPPER", "bare JSON; no <tool_call> token emitted")
    if transport["surrounding_whitespace"]:
        finding(TRANSPORT, "SURROUNDING_WHITESPACE", "text has leading or trailing whitespace")
    if transport["truncated"]:
        finding(TRANSPORT, "TRUNCATED_AT_TOKEN_CAP", "generation reached max_new_tokens")
    elif transport["unclosed_json_depth"] != 0:
        finding(
            TRANSPORT,
            "MALFORMED_JSON_UNBALANCED",
            f"EOS emitted with JSON depth {transport['unclosed_json_depth']}",
        )

    extracted = extract_arguments(stripped)
    args = extracted["arguments"] if isinstance(extracted["arguments"], dict) else {}
    if extracted["name"] != a02_dev_protocol.TOOL_NAME:
        finding(SCHEMA_KIND, "WRONG_TOOL_NAME", repr(extracted["name"]))
    required = set(gold)
    if extracted["method"] != "PARTIAL_COMPLETE_FIELDS_ONLY":
        extra = sorted(set(args) - required)
        missing = sorted(required - set(args))
        if extra or missing:
            finding(SCHEMA_KIND, "ARGUMENT_FIELDS_DIFFER", f"extra={extra} missing={missing}")
    if "schema" in args and args["schema"] != a02_dev_protocol.ACTION_SCHEMA:
        finding(
            SCHEMA_KIND,
            "WRONG_SCHEMA_CONSTANT",
            f"{args['schema']!r}; tool enum requires {a02_dev_protocol.ACTION_SCHEMA!r}",
        )

    fields: dict[str, Any] = {"extraction_method": extracted["method"]}
    if "objective" in args:
        fields["objective_exact"] = args["objective"] == gold["objective"]
        if not fields["objective_exact"]:
            finding(SEMANTIC, "OBJECTIVE_NOT_COPIED", repr(args["objective"]))

    for key, allowed in (
        ("analysis_class", a02_dev_protocol._ANALYSIS_CLASSES),
        ("operation", a02_dev_protocol._OPERATIONS),
    ):
        if key not in args:
            continue
        value = args[key]
        in_enum = value is None or (isinstance(value, str) and value in allowed)
        correct = value == gold[key]
        record: dict[str, Any] = {
            "value": value,
            "gold": gold[key],
            "in_enum": in_enum,
            "correct": correct,
        }
        if not in_enum:
            matches = _registered_operation_containing(value) if isinstance(value, str) else []
            record["registered_operations_containing_value"] = matches
            code = "INVENTED_ANALYSIS_CLASS" if key == "analysis_class" else "INVENTED_OPERATION"
            finding(SCHEMA_KIND, code, f"{value!r} is not a registered enum value")
            gold_operation = gold["operation"]
            identifiable = len(matches) == 1 and (
                matches[0] == gold_operation
                if key == "operation"
                else gold["analysis_class"] in operation_pairs.get(matches[0], set())
            )
            if identifiable:
                # The string is an unregistered fragment of exactly one registered operation
                # consistent with the gold intent. The calculation is identifiable, but no
                # credit is given and the string is never substituted with the registered ID.
                finding(
                    SCHEMA_KIND,
                    "ANALYSIS_OPERATION_CONFLATION"
                    if key == "analysis_class"
                    else "OPERATION_ID_ABBREVIATED",
                    f"{value!r} is a fragment of registered operation {matches[0]!r}",
                )
                record["meaning_identifiable_without_credit"] = True
            else:
                finding(SEMANTIC, f"{key.upper()}_WRONG", f"{value!r}; gold {gold[key]!r}")
        elif not correct:
            finding(SEMANTIC, f"{key.upper()}_WRONG", f"{value!r}; gold {gold[key]!r}")
        fields[key] = record

    request_units = [row.get("unit") for row in request["observations"]]
    if "observations" in args and isinstance(args["observations"], list):
        rows = args["observations"]
        dict_rows = [row for row in rows if isinstance(row, dict)]
        units = [row.get("unit") for row in dict_rows]
        extra_keys = sorted({k for row in dict_rows for k in row} - {"reference", "unit"})
        references = [row.get("reference") for row in dict_rows]
        fields["observations"] = {
            "count": len(rows),
            "gold_count": len(gold["observations"]),
            "request_count": len(request["observations"]),
            "units": units,
            "gold_units": [row["unit"] for row in gold["observations"]],
            "request_units": request_units,
            "extra_keys": extra_keys,
            "references": references,
        }
        if extra_keys:
            finding(SCHEMA_KIND, "OBSERVATION_EXTRA_FIELDS", f"{extra_keys}")
        if "value" in extra_keys:
            finding(SCHEMA_KIND, "OBSERVATION_VALUES_COPIED", "prompt forbids copying values")
        if any(not isinstance(r, str) or not GOLD_REFERENCE.fullmatch(r) for r in references):
            finding(SCHEMA_KIND, "OBSERVATION_REFERENCE_FORMAT", "not observation-N")
        if len(rows) != len(request["observations"]):
            finding(
                SEMANTIC,
                "OBSERVATION_COUNT_DIFFERS_FROM_REQUEST",
                f"{len(rows)} listed; request supplies {len(request['observations'])}",
            )
        elif units != request_units:
            finding(SEMANTIC, "UNIT_NOT_COPIED", f"{units}; request {request_units}")

    claims = args.get("requested_claims")
    if isinstance(claims, dict):
        axes = {}
        for axis in ("measurement_levels", "relationship_levels"):
            axes[axis] = _claim_axis_diagnosis(
                axis, claims.get(axis), gold["requested_claims"][axis]
            )
            diag = axes[axis]
            if not diag["present"]:
                continue
            if diag["missing_gold_levels"]:
                finding(SEMANTIC, "CLAIM_LEVEL_DROPPED", f"{axis}: {diag['missing_gold_levels']}")
            if diag["levels_above_requested_maximum"]:
                finding(
                    SEMANTIC,
                    "CLAIM_LEVEL_ESCALATED",
                    f"{axis}: {diag['levels_above_requested_maximum']}",
                )
            if diag["unrequested_lower_prerequisite_levels"]:
                finding(
                    REPRESENTATION,
                    "CLAIM_PREREQUISITE_LEVELS_LISTED",
                    f"{axis}: {diag['unrequested_lower_prerequisite_levels']}",
                )
        fields["requested_claims"] = axes
    elif extracted["method"] == "PARTIAL_COMPLETE_FIELDS_ONLY":
        fields["requested_claims"] = "NOT_EMITTED_BEFORE_TRUNCATION"

    if any(ref["reference"] not in rendered_prompt for ref in gold["observations"]):
        finding(
            HARNESS,
            "GOLD_REFERENCE_NOT_IN_PROMPT",
            "gold observation-N references are absent from the rendered prompt",
        )
    if '"schema":"RES403-MODEL-TRANSCRIPT-1"' in rendered_prompt:
        fields["prompt_contains_competing_schema_constant"] = True

    kinds = {row["kind"] for row in findings}
    model_kinds = kinds - {HARNESS}
    return {
        "case_id": case_id,
        "transport": transport,
        "counterfactuals": counterfactuals(raw_text),
        "fields": fields,
        "findings": findings,
        "failure_kinds": sorted(kinds),
        "formatting_or_schema_only": bool(model_kinds)
        and model_kinds <= {TRANSPORT, SCHEMA_KIND, REPRESENTATION},
        "has_scientific_semantic_error": SEMANTIC in kinds,
    }


def audit_gold_derivability() -> list[dict[str, Any]]:
    """Check every frozen gold field that must be copied is visible in the model input."""
    cases = json.loads(a02_experiment.CASES_PATH.read_bytes())["cases"]
    rows = []
    for case in cases:
        gold = a02_dev_protocol.expected_intent(case["case_id"])
        visible = a02_experiment.canonical(case["request"])
        refs = [row["reference"] for row in gold["observations"]]
        rows.append(
            {
                "case_id": case["case_id"],
                "gold_references": refs,
                "gold_references_visible": [ref for ref in refs if ref in visible],
                "objective_visible": gold["objective"] in visible,
                "attainable": all(ref in visible for ref in refs),
            }
        )
    return rows


def latency_and_budget(
    report: dict[str, Any], control: dict[str, Any], profile: dict[str, Any]
) -> dict[str, Any]:
    history = report["stage_history"]
    entry = next(e for e in history if e["stage"] == "REMOTE_INFERENCE_ENTRY")
    t0 = datetime.fromisoformat(entry["recorded_at_utc"])

    def offset(stage: str, status: str) -> float | None:
        for event in history:
            if event["stage"] == stage and event["status"] == status:
                moment = datetime.fromisoformat(event["recorded_at_utc"])
                return round((moment - t0).total_seconds(), 3)
        return None

    first_generation = offset(f"GENERATION:{report['cases'][0]['case_id']}", "STARTED")
    per_case = []
    for case in report["cases"]:
        started = offset(f"GENERATION:{case['case_id']}", "STARTED")
        completed = offset(f"GENERATION:{case['case_id']}", "COMPLETE")
        row = {"case_id": case["case_id"], "wall_seconds": None}
        if started is not None and completed is not None:
            row["wall_seconds"] = round(completed - started, 3)
        for key in ("action_generation", "final_generation"):
            gen = case[key]
            decode = gen["generation_latency_s"] - gen["first_token_latency_s"]
            row[key] = {
                "generated_tokens": gen["generated_tokens"],
                "max_new_tokens": gen["max_new_tokens"],
                "prompt_tokens": gen["prompt_tokens"],
                "first_token_latency_s": round(gen["first_token_latency_s"], 3),
                "generation_latency_s": round(gen["generation_latency_s"], 3),
                "decode_tokens_per_s_after_first": round((gen["generated_tokens"] - 1) / decode, 2)
                if decode > 0 and gen["generated_tokens"] > 1
                else None,
                "eos_seen": gen["eos_seen"],
                "truncated": gen["truncated"],
            }
        per_case.append(row)
    steady = [
        r["action_generation"]["decode_tokens_per_s_after_first"]
        for r in per_case
        if r["action_generation"]["decode_tokens_per_s_after_first"]
    ]
    decoding = profile["decoding"]
    planned = len(profile["case_ids"])
    max_tokens = planned * (decoding["action_max_new_tokens"] + decoding["final_max_new_tokens"])
    stage_timeout = control["remote_stage_timeouts_seconds"]["infer"]
    worker_timeout = next(
        c["timeout_seconds"] for c in report["remote_stage_commands"] if c["stage"] == "infer"
    )
    min_rate = min(steady) if steady else None
    return {
        "exec_timeout_seconds": control["exec_timeout_seconds"],
        "stage_timeouts_seconds": control["remote_stage_timeouts_seconds"],
        "prepare_stage_observed_seconds": _prepare_seconds(report),
        "infer_worker_timeout_seconds": worker_timeout,
        "pre_generation_overhead_seconds": first_generation,
        "pre_generation_overhead_breakdown_seconds": {
            stage: (
                None
                if offset(stage, "STARTED") is None or offset(stage, "COMPLETE") is None
                else round(offset(stage, "COMPLETE") - offset(stage, "STARTED"), 3)  # type: ignore[operator]
            )
            for stage in (
                "INFERENCE_RUNTIME_DEPENDENCY_CHECK",
                "GPU_RUNTIME_VALIDATION",
                "MODEL_ASSET_REUSE",
                "MODEL_LOADING",
            )
        },
        "generation_window_seconds": round(worker_timeout - (first_generation or 0), 3),
        "observed_completed_case_wall_seconds_total": round(
            sum(r["wall_seconds"] for r in per_case if r["wall_seconds"] is not None), 3
        ),
        "timeout_offset_seconds": offset(f"GENERATION:{report['current_case_id']}", "TIMEOUT"),
        "planned_generations": planned * 2,
        "observed_complete_generations": len(report["cases"]) * 2,
        "planned_worst_case_new_tokens": max_tokens,
        "observed_min_steady_decode_tokens_per_s": min_rate,
        "worst_case_decode_seconds_at_observed_min_rate": round(max_tokens / min_rate, 1)
        if min_rate
        else None,
        "worst_case_required_worker_seconds_at_observed_rate": round(
            (first_generation or 0) + max_tokens / min_rate, 1
        )
        if min_rate
        else None,
        "infer_stage_seconds_before_worker_margin": stage_timeout,
        "per_case": per_case,
    }


def _prepare_seconds(report: dict[str, Any]) -> float | None:
    history = report["stage_history"]
    start = next((e for e in history if e["stage"] == "REMOTE_PREPARE_ENTRY"), None)
    entry = next((e for e in history if e["stage"] == "REMOTE_INFERENCE_ENTRY"), None)
    if start is None or entry is None:
        return None
    prepared = [
        e
        for e in history
        if datetime.fromisoformat(e["recorded_at_utc"])
        < datetime.fromisoformat(entry["recorded_at_utc"])
    ]
    return round(
        (
            datetime.fromisoformat(prepared[-1]["recorded_at_utc"])
            - datetime.fromisoformat(start["recorded_at_utc"])
        ).total_seconds(),
        3,
    )


def _verify_run(run_dir: Path, score_path: Path) -> dict[str, Any]:
    root = run_dir.resolve()
    if not root.is_relative_to(E_ROOT) or not score_path.resolve().is_relative_to(E_ROOT):
        raise ValueError("forensic inputs must be read from E:")
    manifest = _read_json(root / "artifact-hashes.json")
    if manifest.get("run_id") != root.name or not isinstance(manifest.get("files"), list):
        raise ValueError("artifact manifest does not bind this run")
    for record in manifest["files"]:
        data = (root / record["name"]).read_bytes()
        if len(data) != record["bytes"] or sha256(data) != record["sha256"]:
            raise ValueError(f"artifact hash mismatch: {record['name']}")
    report_bytes = (root / "remote-report.json").read_bytes()
    score_bytes = score_path.read_bytes()
    score = json.loads(score_bytes)
    if (
        score.get("remote_report_sha256") != sha256(report_bytes)
        or score.get("run_id") != root.name
    ):
        raise ValueError("score receipt does not bind the retained remote report")
    return {
        "report": json.loads(report_bytes),
        "control": _read_json(root / "control.json"),
        "score": score,
        "hashes": {
            "artifact_manifest_sha256": sha256((root / "artifact-hashes.json").read_bytes()),
            "remote_report_sha256": sha256(report_bytes),
            "score_receipt_sha256": sha256(score_bytes),
        },
    }


def _verify_token_replay(tokenizer: Any, generation: dict[str, Any]) -> bool:
    ids = generation["generated_token_ids"]
    return bool(
        sha256(a02_dev_protocol.canonical(ids).encode()) == generation["generated_token_ids_sha256"]
        and len(ids) == generation["generated_tokens"]
        and tokenizer.decode(ids, skip_special_tokens=False)
        == generation["raw_with_special_tokens"]
        and tokenizer.decode(ids, skip_special_tokens=True) == generation["raw_text"]
    )


def build_diagnosis(run_dir: Path, score_path: Path, tokenizer: Any) -> dict[str, Any]:
    bundle = _verify_run(run_dir, score_path)
    report, score, control = bundle["report"], bundle["score"], bundle["control"]
    profile = a02_dev_protocol.load_profile()
    cases = {
        row["case_id"]: row for row in json.loads(a02_experiment.CASES_PATH.read_bytes())["cases"]
    }
    tool_ids = (
        tokenizer.convert_tokens_to_ids(TOOL_CALL_OPEN),
        tokenizer.convert_tokens_to_ids(TOOL_CALL_CLOSE),
    )
    scored = {row["case_id"]: row for row in score["case_results"]}
    pairs = operation_analysis_pairs()
    rows = []
    for case in report["cases"]:
        case_id = case["case_id"]
        action = case["action_generation"]
        raw = action["raw_text"]
        if (
            sha256(raw.encode()) != case["engine_response"]["action_sha256"]
            or sha256(raw.encode()) != scored[case_id]["raw_action_sha256"]
        ):
            raise ValueError(f"raw action hash differs from the scored record: {case_id}")
        row = diagnose_action(
            case_id=case_id,
            raw_text=raw,
            generation=action,
            request=cases[case_id]["request"],
            gold=a02_dev_protocol.expected_intent(case_id),
            rendered_prompt=action["prompt_text"],
            tool_call_token_ids=tool_ids,
            operation_pairs=pairs,
        )
        row["raw_action_sha256"] = sha256(raw.encode())
        row["token_replay_verified"] = _verify_token_replay(tokenizer, action) and (
            _verify_token_replay(tokenizer, case["final_generation"])
        )
        row["original_executor_reason_codes"] = case["engine_response"]["event"]["reason_codes"]
        row["original_parse_error_class"] = case["engine_response"]["event"]["metadata"].get(
            "parse_error"
        )
        final_raw = case["final_generation"]["raw_text"]
        row["final"] = {
            "raw_final_sha256": sha256(final_raw.encode()),
            "emits_json_or_tool_syntax": final_raw.lstrip().startswith("{"),
            "truncated": case["final_generation"]["truncated"],
            "original_grounded_under_fixed_rule": scored[case_id][
                "raw_final_grounded_under_fixed_rule"
            ],
        }
        rows.append(row)

    def count(predicate: Any) -> dict[str, int]:
        return {"numerator": sum(1 for r in rows if predicate(r)), "denominator": len(rows)}

    def code_count(code: str) -> int:
        return sum(1 for r in rows if any(f["code"] == code for f in r["findings"]))

    codes = sorted({f["code"] for r in rows for f in r["findings"]})
    return {
        "schema": SCHEMA,
        "status": "READ_ONLY_DIAGNOSIS_ORIGINAL_SCORE_UNCHANGED",
        "run_id": run_dir.resolve().name,
        "inputs": bundle["hashes"],
        "original_score_status": score["status"],
        "original_metrics_unchanged": score["metrics"],
        "observed_case_count": len(rows),
        "unobserved_case_ids": score["unobserved_case_ids"],
        "unobserved_cases_extrapolated": False,
        "counterfactual_definitions": COUNTERFACTUALS,
        "summary": {
            "counterfactual_parse_valid": {
                name: count(lambda r, n=name: r["counterfactuals"][n]["parse_valid"])
                for name in COUNTERFACTUALS
            },
            "formatting_or_schema_only_failures": count(lambda r: r["formatting_or_schema_only"]),
            "cases_with_scientific_semantic_error": count(
                lambda r: r["has_scientific_semantic_error"]
            ),
            "finding_case_counts": {code: code_count(code) for code in codes},
            "objective_copied_exactly": count(lambda r: r["fields"].get("objective_exact") is True),
            "analysis_class_correct": count(
                lambda r: r["fields"].get("analysis_class", {}).get("correct") is True
            ),
            "operation_correct": count(
                lambda r: r["fields"].get("operation", {}).get("correct") is True
            ),
            "final_emits_json_despite_instruction": count(
                lambda r: r["final"]["emits_json_or_tool_syntax"]
            ),
        },
        "gold_derivability_audit": audit_gold_derivability(),
        "latency_and_budget": latency_and_budget(report, control, profile),
        "cases": rows,
    }


def _load_tokenizer(path: Path) -> Any:
    profile = a02_dev_protocol.load_profile()
    for name, digest in profile["tokenizer"]["files"].items():
        if sha256((path / name).read_bytes()) != digest:
            raise ValueError(f"pinned tokenizer file differs: {name}")
    from transformers import AutoTokenizer  # type: ignore[import-not-found]

    return AutoTokenizer.from_pretrained(str(path), local_files_only=True)


def write_exclusive(path: Path, value: dict[str, Any]) -> str:
    data = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
    return sha256(data)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--score", type=Path, required=True)
    parser.add_argument("--tokenizer-dir", type=Path, default=E_ROOT / "a01/tokenizer")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    diagnosis = build_diagnosis(args.run_dir, args.score, _load_tokenizer(args.tokenizer_dir))
    if args.output is None:
        print(json.dumps(diagnosis, indent=2, sort_keys=True))
    else:
        print(write_exclusive(args.output, diagnosis))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
