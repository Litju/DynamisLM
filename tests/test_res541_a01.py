"""Adversarial CPU checks for the separately frozen prompt experiment."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest
from scripts import a0_colab_inference as inference
from scripts import a0_engine as engine
from scripts import a01_experiment as a01

from dynamislm import AnalysisClass, MeasurementClaimLevel, RelationshipClaimLevel


def oracle(case: engine.Case) -> str:
    return a01.compact(engine._model_intent_wire(engine.oracle_intent(engine._build_context(case))))


def test_frozen_prompt_examples_enums_and_original_a0_are_intact() -> None:
    a01.verify_freeze()
    examples = [engine.parse_model_intent(text) for text in a01.demonstrations()]
    assert len(examples) == 3
    assert examples[0] == examples[1]
    assert examples[0].baseline_role is engine.ObservationRole.BASELINE
    assert examples[0].followup_role is engine.ObservationRole.FOLLOWUP
    prompt = a01.PROMPT_PATH.read_text()
    assert "EXECUTE means SUBMIT_FOR_AUTHORIZATION" in prompt
    for enum in (
        AnalysisClass,
        MeasurementClaimLevel,
        RelationshipClaimLevel,
        engine.ObservationRole,
    ):
        assert all(member.value in prompt for member in enum)
    original = engine.prepare_cases()["cases"]
    assert isinstance(original, list)
    assert a01.prepared(engine.load_cases()) == [
        {"case_id": row["case_id"], "user_message": row["user_message"]} for row in original
    ]


@pytest.mark.parametrize(
    "mutation",
    [
        {"x": None},
        {"r": "null"},
        {"m": "SCALAR_ABSOLUTE_CHANGE"},
        {"a": "AnalysisClass enum value"},
        {"a": "UNKNOWN"},
        {"b": "BASELINE|FOLLOWUP|null"},
        {"b": 1},
        {"v": True},
        {"v": 1.0},
        {"m": None, "r": None},
        {"result": 0.125},
    ],
)
def test_typed_boundary_rejects_imitation_and_injected_results(mutation: dict[str, Any]) -> None:
    case = engine.load_cases()[0]
    value = json.loads(oracle(case))
    value.update(mutation)
    raw = a01.compact(value)
    with pytest.raises(ValueError):
        engine.parse_model_intent(raw)
    row = a01.observe(case, raw)
    assert row["parser_fallback"] and row["final_safety"]
    assert not row["explicit_model_refusal"]
    assert all(not calls for calls in row["stages"].values())


@pytest.mark.parametrize(
    "raw",
    [
        "{",
        '```json\n{"v":1,"d":"REFUSE","x":"UNSUPPORTED_ANALYSIS"}\n```',
        '{"v":1,"d":"REFUSE","x":"MISSING_EVIDENCE|UNSUPPORTED_ANALYSIS"}',
        '{"v":1,"d":"REFUSE","x":null}',
        '{"v":1,"d":"EXECUTE","a":"SCALAR_ABSOLUTE_CHANGE"}',
    ],
)
def test_malformed_and_wrong_field_sets_fail_closed(raw: str) -> None:
    row = a01.observe(engine.load_cases()[0], raw)
    assert row["parser_fallback"] and row["final_safety"]
    assert row["final"]["reason_codes"] == ("A0_MODEL_INTENT_INVALID",)


def test_explicit_model_refusal_is_not_canonical_authority_refusal() -> None:
    case = engine.load_cases()[7]
    row = a01.observe(case, '{"v":1,"d":"REFUSE","x":"MISSING_EVIDENCE"}')
    assert row["explicit_model_refusal"] and not row["parser_fallback"]
    assert not row["expected_canonical_reason_match"]
    assert all(not calls for calls in row["stages"].values())
    summary = a01.summarize([row])
    assert summary["numeric_integrity"] == {"numerator": 0, "denominator": 0, "rate": None}
    assert summary["analysis_authorization_refusals"] == 0
    assert summary["expected_canonical_refusals_passed"] == {"numerator": 0, "denominator": 1}
    assert summary["model_unmappable_refusal_precision"]["numerator"] == 0


def test_all_frozen_controls_have_independent_values_and_exact_authority_outcomes() -> None:
    cases = engine.load_cases(a01.CONTROLS_PATH)
    original = engine.load_cases()
    assert len(cases) == 12
    assert not {case.case_id for case in cases} & {case.case_id for case in original}
    assert not {case.request for case in cases} & {case.request for case in original}
    old_pairs = {tuple(spec.value for spec in case.observations) for case in original}
    assert all(tuple(spec.value for spec in case.observations) not in old_pairs for case in cases)
    previous = sys.getprofile()
    rows = [a01.observe(case, oracle(case)) for case in cases]
    assert sys.getprofile() is previous
    assert all(row["expected_outcome_match"] and row["final_safety"] for row in rows)
    assert all(
        row["expected_canonical_reason_match"]
        for row in rows
        if row["final"]["outcome"] == "REFUSED"
    )
    summary = a01.summarize(rows)
    assert summary["analysis_authorization_calls"] == 12
    assert summary["registered_calculation_calls"] == 5
    assert summary["claim_authorization_calls"] == 5
    assert summary["claim_authorization_refusals"] == 0
    assert summary["claim_authorization_partial_authorizations"] == 1
    assert summary["numeric_integrity"] == {"numerator": 4, "denominator": 4, "rate": 1.0}
    assert summary["expected_numeric_cases_passed"] == {"numerator": 4, "denominator": 4}
    assert summary["expected_canonical_refusals_passed"] == {"numerator": 8, "denominator": 8}
    assert summary["model_unmappable_refusal_precision"]["rate"] is None
    causal = next(row for row in rows if row["case_id"] == "a01-control-causal")
    assert causal["stages"]["registered_calculation"][0]["hash"]
    assert causal["stages"]["claim_authorization"][0]["status"] == "PARTIALLY_AUTHORIZED"
    assert causal["final"]["result_value"] is None


def test_swapped_roles_are_typed_but_cannot_release_numbers() -> None:
    case = engine.load_cases(a01.CONTROLS_PATH)[0]
    value = json.loads(oracle(case))
    value["b"], value["f"] = value["f"], value["b"]
    row = a01.observe(case, a01.compact(value))
    assert row["typed_valid"] and row["final_safety"]
    assert not row["final"]["intent_matches_expectation"]
    assert len(row["stages"]["analysis_authorization"]) == 1
    assert not row["stages"]["registered_calculation"]
    assert row["final"]["reason_codes"] == ("RES70_REGISTRY_INTEGRITY_FAILURE",)


def test_retired_all_missing_control_is_an_authoring_error_not_a_canonical_refusal() -> None:
    cases = engine.load_cases(a01.ROOT / "experiments/a01/controls-v1.json")
    case = next(case for case in cases if case.case_id == "a01-control-neither-value")
    with pytest.raises(ValueError, match="included_entries must not be empty"):
        engine._build_context(case)


def test_freeze_tampering_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    freeze = json.loads(a01.FREEZE_PATH.read_text())
    freeze["files"]["experiments/a01/system-prompt-v1.txt"] = "0" * 64
    path = tmp_path / "bad-freeze.json"
    path.write_text(json.dumps(freeze))
    monkeypatch.setattr(a01, "FREEZE_PATH", path)
    with pytest.raises(ValueError, match="frozen experiment file changed"):
        a01.verify_freeze()


def test_host_artifacts_reject_d_and_unmounted_e(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValueError, match="host artifacts"):
        a01.e_path(Path("/mnt/d/a01.json"))
    monkeypatch.setattr(Path, "is_mount", lambda _: False)
    with pytest.raises(ValueError, match="host artifacts"):
        a01.e_path(Path("/mnt/e/DynamisLM-A0/a01/receipt.json"))


def test_raw_output_scoring_preserves_layers_and_rejects_wrong_provenance() -> None:
    cases = engine.load_cases(a01.CONTROLS_PATH)
    document = dict(
        schema=engine.OUTPUT_SCHEMA,
        status="COMPLETE",
        model_id=inference.MODEL_ID,
        model_revision=inference.MODEL_REVISION,
        intent_schema=engine.INTENT_SCHEMA,
        prompt_version=a01.PROMPT_VERSION,
        system_prompt_sha256=a01.sha256(a01.PROMPT_PATH.read_bytes()),
        cases=[dict(case_id=case.case_id, raw_text=oracle(case)) for case in cases],
    )
    raw_rows = document["cases"]
    assert isinstance(raw_rows, list)
    raw_rows[0]["raw_text"] = "{"
    raw_rows[1]["raw_text"] = '{"v":1,"d":"REFUSE","x":"MISSING_EVIDENCE"}'
    score = a01.score_model_outputs(document, "a01_controls")
    assert score["summary"]["parser_fallback"] == 1
    assert score["summary"]["explicit_model_refusal"] == 1
    assert score["summary"]["final_safety"] == 12
    assert score["summary"]["expected_numeric_cases_passed"] == {"numerator": 2, "denominator": 4}
    assert score["inference_provenance"]["model_revision"] == inference.MODEL_REVISION
    raw_rows[1]["case_id"] = raw_rows[0]["case_id"]
    with pytest.raises(ValueError, match="duplicate"):
        a01.score_model_outputs(document, "a01_controls")
    document["system_prompt_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="frozen A0.1"):
        a01.score_model_outputs(document, "a01_controls")


@pytest.mark.skipif(
    not os.environ.get("RES541_A01_TOKENIZER_DIR"),
    reason="actual pinned tokenizer and private postmortem live on owner E: storage",
)
def test_actual_pinned_tokenizer_all_inputs_and_historical_postmortem() -> None:
    receipt = a01.qualify(
        Path(os.environ["RES541_A01_TOKENIZER_DIR"]),
        Path("/mnt/e/DynamisLM-A0/reports/res541-a0-20261023-040456z-report.json"),
        Path("/mnt/e/DynamisLM-A0/reviews/res541-a0-20261023-040456z-postmortem-v1"),
    )
    assert len(receipt["lengths"]) == 28
    assert max(row["prompt_tokens"] for row in receipt["lengths"]) <= 1024
    assert receipt["max_output_tokens_including_eos"] <= 64
    assert receipt["baseline"]["scorer_reconstruction"] == "EXACT"
    assert receipt["baseline"]["evidence_unchanged"]
