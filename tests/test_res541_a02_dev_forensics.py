from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from scripts import a02_dev_forensics as forensics
from scripts import a02_dev_protocol, a02_experiment

TOOL_IDS = (128015, 128016)
CASES = {row["case_id"]: row for row in json.loads(a02_experiment.CASES_PATH.read_bytes())["cases"]}


def _generation(*, ids: list[int] | None = None, truncated: bool = False) -> dict[str, Any]:
    ids = ids if ids is not None else [5018, 128012]
    return {
        "generated_token_ids": ids,
        "eos_seen": not truncated,
        "truncated": truncated,
        "generated_tokens": len(ids),
        "max_new_tokens": 256,
    }


def _envelope(arguments: dict[str, Any]) -> str:
    return json.dumps({"name": a02_dev_protocol.TOOL_NAME, "arguments": arguments})


def _diagnose(case_id: str, raw: str, **generation: Any) -> dict[str, Any]:
    return forensics.diagnose_action(
        case_id=case_id,
        raw_text=raw,
        generation=_generation(**generation),
        request=CASES[case_id]["request"],
        gold=a02_dev_protocol.expected_intent(case_id),
        rendered_prompt="prompt without gold references",
        tool_call_token_ids=TOOL_IDS,
        operation_pairs=forensics.operation_analysis_pairs(),
    )


def _codes(row: dict[str, Any]) -> set[str]:
    return {finding["code"] for finding in row["findings"]}


def test_positive_control_bare_gold_json_is_recovered_only_by_labelled_framing() -> None:
    gold = a02_dev_protocol.expected_intent("a02-valid-numerical")
    result = forensics.counterfactuals(_envelope(gold))
    assert result["CF0_AS_GENERATED"]["parse_valid"] is False
    assert result["CF1_STRIP_SURROUNDING_WHITESPACE"]["parse_valid"] is False
    assert result["CF2_ADD_MISSING_TOOL_CALL_TAGS"]["parse_valid"] is True
    assert result["CF2_ADD_MISSING_TOOL_CALL_TAGS"]["changed_from_raw"] is True


def test_positive_control_whitespace_only_framing_is_recovered_by_strip() -> None:
    raw = "\n" + a02_dev_protocol.format_intent(
        a02_dev_protocol.expected_intent("a02-valid-numerical")
    )
    result = forensics.counterfactuals(raw + "\n")
    assert result["CF0_AS_GENERATED"]["parse_valid"] is False
    assert result["CF1_STRIP_SURROUNDING_WHITESPACE"]["parse_valid"] is True


def test_counterfactual_does_not_repair_wrong_schema_constant_or_fields() -> None:
    gold = a02_dev_protocol.expected_intent("a02-valid-numerical")
    wrong = {**gold, "schema": "RES403-MODEL-TRANSCRIPT-1"}
    result = forensics.counterfactuals(_envelope(wrong))
    assert not any(row["parse_valid"] for row in result.values())
    assert result["CF2_ADD_MISSING_TOOL_CALL_TAGS"]["first_error"] == (
        "intent schema or fields differ"
    )


def test_session_shaped_valid_case_is_schema_failure_not_semantic_and_gets_no_credit() -> None:
    args = {
        "schema": "RES403-MODEL-TRANSCRIPT-1",
        "objective": "Describe absolute longitudinal jump-height change only.",
        "analysis_class": "longitudinal-absolute-change-v1",
        "operation": "longitudinal-absolute-change-v1",
        "observations": [
            {"reference": "SYNTHETIC baseline", "unit": "m", "value": 0.304},
            {"reference": "SYNTHETIC follow-up", "unit": "m", "value": 0.342},
        ],
        "requested_claims": {
            "measurement_levels": ["OBSERVED_VALUE", "NUMERICAL_CHANGE"],
            "relationship_levels": ["OBSERVATION", "DESCRIPTIVE_CHANGE"],
        },
    }
    row = _diagnose("a02-valid-numerical", _envelope(args))
    assert {
        "MISSING_TOOL_CALL_WRAPPER",
        "WRONG_SCHEMA_CONSTANT",
        "INVENTED_ANALYSIS_CLASS",
        "ANALYSIS_OPERATION_CONFLATION",
        "OPERATION_ID_ABBREVIATED",
        "OBSERVATION_VALUES_COPIED",
        "CLAIM_PREREQUISITE_LEVELS_LISTED",
        "GOLD_REFERENCE_NOT_IN_PROMPT",
    } <= _codes(row)
    assert row["formatting_or_schema_only"] is True
    assert row["has_scientific_semantic_error"] is False
    assert row["fields"]["analysis_class"]["correct"] is False
    assert row["fields"]["operation"]["correct"] is False
    assert not any(cf["parse_valid"] for cf in row["counterfactuals"].values())


def test_unit_miscopy_and_fabricated_observation_are_semantic_errors() -> None:
    gold = a02_dev_protocol.expected_intent("a02-incompatible-units")
    units = {**gold, "observations": [{"reference": "observation-1", "unit": "m"}] * 2}
    row = _diagnose("a02-incompatible-units", _envelope(units))
    assert "UNIT_NOT_COPIED" in _codes(row)
    assert row["has_scientific_semantic_error"] is True

    missing = a02_dev_protocol.expected_intent("a02-missing-evidence")
    fabricated = {
        **missing,
        "observations": [
            {"reference": "observation-1", "unit": "m"},
            {"reference": "observation-2", "unit": "m"},
        ],
    }
    row = _diagnose("a02-missing-evidence", _envelope(fabricated))
    assert "OBSERVATION_COUNT_DIFFERS_FROM_REQUEST" in _codes(row)
    assert row["has_scientific_semantic_error"] is True


def test_registered_but_wrong_operation_and_class_are_semantic_substitutions() -> None:
    gold = a02_dev_protocol.expected_intent("a02-unsupported-association")
    wrong = {
        **gold,
        "analysis_class": "RELIABILITY_RANDOM_ERROR_COMPARISON",
        "operation": next(op for op in a02_dev_protocol._OPERATIONS if "within-athlete" in op),
    }
    row = _diagnose("a02-unsupported-association", _envelope(wrong))
    assert {"ANALYSIS_CLASS_WRONG", "OPERATION_WRONG"} <= _codes(row)
    assert row["has_scientific_semantic_error"] is True


def test_invented_operation_fragment_without_gold_operation_is_semantic() -> None:
    gold = a02_dev_protocol.expected_intent("a02-missing-evidence")
    assert gold["operation"] is None
    row = _diagnose(
        "a02-missing-evidence", _envelope({**gold, "operation": "longitudinal-absolute-change-v1"})
    )
    assert "OPERATION_WRONG" in _codes(row)
    assert "OPERATION_ID_ABBREVIATED" not in _codes(row)


def test_claim_escalation_is_distinguished_from_prerequisite_listing() -> None:
    gold = a02_dev_protocol.expected_intent("a02-unsupported-causality")
    claims = {
        "measurement_levels": ["OBSERVED_VALUE", "NUMERICAL_CHANGE", "COMPARABLE_CHANGE"],
        "relationship_levels": ["OBSERVATION", "CAUSAL_EVIDENCE"],
    }
    row = _diagnose("a02-unsupported-causality", _envelope({**gold, "requested_claims": claims}))
    axes = row["fields"]["requested_claims"]
    assert axes["measurement_levels"]["levels_above_requested_maximum"] == ["COMPARABLE_CHANGE"]
    assert axes["measurement_levels"]["unrequested_lower_prerequisite_levels"] == ["OBSERVED_VALUE"]
    assert axes["relationship_levels"]["gold_levels_preserved"] is True
    assert axes["relationship_levels"]["levels_above_requested_maximum"] == []
    assert {"CLAIM_LEVEL_ESCALATED", "CLAIM_PREREQUISITE_LEVELS_LISTED"} <= _codes(row)

    dropped = {"measurement_levels": ["NUMERICAL_CHANGE"], "relationship_levels": []}
    row = _diagnose("a02-unsupported-causality", _envelope({**gold, "requested_claims": dropped}))
    assert "CLAIM_LEVEL_DROPPED" in _codes(row)


def test_malformed_envelope_extracts_only_complete_arguments_object() -> None:
    gold = a02_dev_protocol.expected_intent("a02-contradictory-objectives")
    raw = _envelope(gold)[:-1]
    extracted = forensics.extract_arguments(raw)
    assert extracted["method"] == "ARGUMENTS_OBJECT_COMPLETE_ENVELOPE_INVALID"
    assert extracted["envelope_keys"] is None
    assert extracted["arguments"] == gold
    row = _diagnose("a02-contradictory-objectives", raw)
    assert "MALFORMED_JSON_UNBALANCED" in _codes(row)
    assert row["counterfactuals"]["CF2_ADD_MISSING_TOOL_CALL_TAGS"]["first_error"] == (
        "invalid intent JSON"
    )


def test_truncated_action_recovers_only_complete_values_and_invents_nothing() -> None:
    gold = a02_dev_protocol.expected_intent("a02-unsupported-association")
    raw = _envelope(gold)
    cut = raw[: raw.index('"relationship_levels"') + len('"relationship_levels')]
    row = _diagnose("a02-unsupported-association", cut, truncated=True)
    assert row["fields"]["extraction_method"] == "PARTIAL_COMPLETE_FIELDS_ONLY"
    assert "TRUNCATED_AT_TOKEN_CAP" in _codes(row)
    assert "MALFORMED_JSON_UNBALANCED" not in _codes(row)
    assert row["fields"]["requested_claims"]["relationship_levels"]["present"] is False
    assert row["fields"]["requested_claims"]["measurement_levels"]["model"] == []
    assert "ARGUMENT_FIELDS_DIFFER" not in _codes(row)


def test_emitted_tool_call_token_is_not_reported_missing() -> None:
    raw = a02_dev_protocol.format_intent(a02_dev_protocol.expected_intent("a02-valid-numerical"))
    row = _diagnose("a02-valid-numerical", raw, ids=[128015, 5018, 128016, 128012])
    assert "MISSING_TOOL_CALL_WRAPPER" not in _codes(row)
    assert row["counterfactuals"]["CF0_AS_GENERATED"]["parse_valid"] is True


def test_diagnosis_does_not_mutate_gold_or_request() -> None:
    gold = a02_dev_protocol.expected_intent("a02-valid-numerical")
    request = CASES["a02-valid-numerical"]["request"]
    gold_before, request_before = copy.deepcopy(gold), copy.deepcopy(request)
    forensics.diagnose_action(
        case_id="a02-valid-numerical",
        raw_text=_envelope({**gold, "operation": "x"}),
        generation=_generation(),
        request=request,
        gold=gold,
        rendered_prompt="",
        tool_call_token_ids=TOOL_IDS,
        operation_pairs=forensics.operation_analysis_pairs(),
    )
    assert gold == gold_before and request == request_before


def test_frozen_v2_gold_references_are_not_derivable_from_any_request() -> None:
    audit = forensics.audit_gold_derivability()
    assert len(audit) == 10
    assert all(row["attainable"] is False for row in audit)
    assert all(row["gold_references_visible"] == [] for row in audit)
    assert all(row["objective_visible"] for row in audit)


def test_operation_pairs_are_derived_from_frozen_gold_only() -> None:
    assert forensics.operation_analysis_pairs() == {
        "dynamislm:registered-operation:longitudinal-absolute-change-v1@1.0.0": {
            "SCALAR_ABSOLUTE_CHANGE"
        }
    }


def test_claim_ladder_uses_canonical_res70_ordinals() -> None:
    assert forensics._LADDER["measurement_levels"]["OBSERVED_VALUE"] == 0
    assert forensics._LADDER["measurement_levels"]["PRACTICAL_OR_DECISION_MEANINGFULNESS"] == 4
    assert forensics._LADDER["relationship_levels"]["CAUSAL_EVIDENCE"] == 5
    assert set(forensics._LADDER["relationship_levels"]) == a02_dev_protocol._RELATIONSHIP_LEVELS


def _stage(stage: str, status: str, second: float) -> dict[str, str]:
    return {
        "stage": stage,
        "status": status,
        "recorded_at_utc": f"2026-11-07T18:00:{second:06.3f}+00:00",
    }


def _generation_timing(tokens: int, first: float, total: float) -> dict[str, Any]:
    return {
        "generated_tokens": tokens,
        "max_new_tokens": 256,
        "prompt_tokens": 1000,
        "first_token_latency_s": first,
        "generation_latency_s": total,
        "eos_seen": True,
        "truncated": False,
    }


def test_latency_budget_reports_worst_case_requirement_without_imputing_cases() -> None:
    report = {
        "stage_history": [
            _stage("REMOTE_PREPARE_ENTRY", "STARTED", 0),
            _stage("REMOTE_PREPARE", "COMPLETE", 5),
            _stage("REMOTE_INFERENCE_ENTRY", "STARTED", 10),
            _stage("MODEL_LOADING", "STARTED", 11),
            _stage("MODEL_LOADING", "COMPLETE", 20),
            _stage("GENERATION:a02-valid-numerical", "STARTED", 20),
            _stage("GENERATION:a02-valid-numerical", "COMPLETE", 31),
            _stage("GENERATION:a02-incompatible-units", "STARTED", 31),
            _stage("GENERATION:a02-incompatible-units", "TIMEOUT", 40),
        ],
        "cases": [
            {
                "case_id": "a02-valid-numerical",
                "action_generation": _generation_timing(201, 0.5, 10.5),
                "final_generation": _generation_timing(11, 0.2, 0.7),
            }
        ],
        "current_case_id": "a02-incompatible-units",
        "remote_stage_commands": [{"stage": "infer", "timeout_seconds": 30}],
    }
    control = {"exec_timeout_seconds": 100, "remote_stage_timeouts_seconds": {"infer": 60}}
    profile = a02_dev_protocol.load_profile()
    result = forensics.latency_and_budget(report, control, profile)
    assert result["pre_generation_overhead_seconds"] == 10.0
    assert result["prepare_stage_observed_seconds"] == 5.0
    assert result["generation_window_seconds"] == 20.0
    assert result["observed_min_steady_decode_tokens_per_s"] == 20.0
    assert result["planned_worst_case_new_tokens"] == 10 * (256 + 96)
    assert result["worst_case_required_worker_seconds_at_observed_rate"] == 10 + 3520 / 20
    assert result["timeout_offset_seconds"] == 30.0
    assert result["observed_complete_generations"] == 2
    assert result["planned_generations"] == 20


def test_run_verification_rejects_non_e_paths_and_unbound_receipts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(ValueError, match="read from E:"):
        forensics._verify_run(tmp_path, tmp_path / "score.json")
    monkeypatch.setattr(forensics, "E_ROOT", tmp_path.resolve())
    run = tmp_path / "run-x"
    run.mkdir()
    report = b'{"cases": []}'
    (run / "remote-report.json").write_bytes(report)
    (run / "control.json").write_text("{}")
    manifest = {
        "run_id": "run-x",
        "files": [
            {
                "name": "remote-report.json",
                "bytes": len(report),
                "sha256": hashlib.sha256(report).hexdigest(),
            }
        ],
    }
    (run / "artifact-hashes.json").write_text(json.dumps(manifest))
    score = tmp_path / "score.json"
    score.write_text(json.dumps({"run_id": "run-x", "remote_report_sha256": "0" * 64}))
    with pytest.raises(ValueError, match="does not bind"):
        forensics._verify_run(run, score)
    score.write_text(
        json.dumps({"run_id": "run-x", "remote_report_sha256": hashlib.sha256(report).hexdigest()})
    )
    assert forensics._verify_run(run, score)["report"] == {"cases": []}
    (run / "remote-report.json").write_bytes(report + b" ")
    with pytest.raises(ValueError, match="artifact hash mismatch"):
        forensics._verify_run(run, score)


def test_receipt_writer_refuses_to_overwrite(tmp_path: Path) -> None:
    path = tmp_path / "receipt.json"
    digest = forensics.write_exclusive(path, {"a": 1})
    assert digest == hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(FileExistsError):
        forensics.write_exclusive(path, {"a": 2})
    assert json.loads(path.read_bytes()) == {"a": 1}
