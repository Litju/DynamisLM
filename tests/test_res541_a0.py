from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest
from scripts import a0_colab, a0_colab_inference, a0_engine


def _oracle_outputs() -> dict[str, object]:
    model_cases: list[dict[str, object]] = []
    for case in a0_engine.load_cases():
        context = a0_engine._build_context(case)
        model_cases.append(
            {
                "case_id": case.case_id,
                "raw_text": json.dumps(a0_engine._intent_wire(a0_engine.oracle_intent(context))),
                "prompt_sha256": "0" * 64,
                "prompt_tokens": 32,
                "generated_tokens": 18,
                "latency_ms": 100.0,
                "first_token_latency_ms": 20.0,
                "failure_category": None,
            }
        )
    return {
        "schema": a0_engine.OUTPUT_SCHEMA,
        "status": "COMPLETE",
        "model_id": "HuggingFaceTB/SmolLM3-3B",
        "model_revision": "a07cc9a04f16550a088caea529712d1d335b0ac1",
        "cases": model_cases,
    }


def test_a0_cpu_oracle_exercises_exact_operation_and_registered_refusals() -> None:
    cases = a0_engine.load_cases()
    assert len(cases) == 16
    report = a0_engine.score_outputs(_oracle_outputs(), source_revision="a" * 40)

    assert report["status"] == "PASS"
    assert report["scope"] == "SYNTHETIC_DEVELOPMENT_ONLY"
    metrics = report["metrics"]
    assert isinstance(metrics, dict)
    assert metrics["typed_intent_valid"] == {"numerator": 16, "denominator": 16}
    assert metrics["registered_tool_dispatch_success"] == {"numerator": 7, "denominator": 7}
    assert metrics["refusal_precision"] == {
        "true_positive": 9,
        "false_positive": 0,
        "denominator": 9,
    }
    assert metrics["refusal_recall"] == {
        "true_positive": 9,
        "false_negative": 0,
        "denominator": 9,
    }
    rows = report["cases"]
    assert isinstance(rows, list)
    assert all(row["outcome_matches_expectation"] for row in rows)
    assert all(row["intent_matches_expectation"] for row in rows)
    assert all(row["result_value"] is None for row in rows if row["outcome"] == "REFUSED")


def test_model_output_cannot_supply_a_number_or_extra_field() -> None:
    outputs = _oracle_outputs()
    model_cases = outputs["cases"]
    assert isinstance(model_cases, list)
    model_cases[0]["raw_text"] = json.dumps(
        {
            **json.loads(str(model_cases[0]["raw_text"])),
            "value": 999.0,
        }
    )

    report = a0_engine.score_outputs(outputs, source_revision="b" * 40)
    rows = cast(list[dict[str, object]], report["cases"])
    first = rows[0]

    assert first["outcome"] == "REFUSED"
    assert first["reason_codes"] == ("A0_MODEL_INTENT_INVALID",)
    assert first["result_value"] is None
    assert first["analysis_dispatched"] is False


def test_swapped_entry_references_fail_closed_after_authorization() -> None:
    outputs = _oracle_outputs()
    model_cases = outputs["cases"]
    assert isinstance(model_cases, list)
    intent = json.loads(str(model_cases[0]["raw_text"]))
    intent["baseline_role"], intent["followup_role"] = (
        intent["followup_role"],
        intent["baseline_role"],
    )
    model_cases[0]["raw_text"] = json.dumps(intent)

    report = a0_engine.score_outputs(outputs, source_revision="c" * 40)
    rows = cast(list[dict[str, object]], report["cases"])
    first = rows[0]

    assert first["outcome"] == "REFUSED"
    codes = cast(tuple[str, ...], first["reason_codes"])
    assert "RES70_REGISTRY_INTEGRITY_FAILURE" in codes
    assert first["result_value"] is None


def test_unknown_analysis_class_is_rejected_by_typed_boundary() -> None:
    case = a0_engine.load_cases()[0]
    context = a0_engine._build_context(case)
    intent = a0_engine._intent_wire(a0_engine.oracle_intent(context))
    intent["analysis_class"] = "MODEL_WRITTEN_PYTHON"

    with pytest.raises(ValueError, match="typed value"):
        a0_engine.parse_model_intent(json.dumps(intent))


def test_colab_quota_gate_requires_positive_balance_and_no_active_assignment() -> None:
    usage = "Current balance: 262.07 compute units\nActive assignments: 0"
    assert a0_colab._parse_usage_output(usage) == "262.07"
    assert a0_colab._confirmation_phrase("262.07").endswith(
        "max=900s | cases=16 | tokens=64 | gpu=T4"
    )
    with pytest.raises(a0_colab.RunError, match="positive compute-unit balance"):
        a0_colab._parse_usage_output("Current balance: 0.00 compute units\nActive assignments: 0")
    with pytest.raises(a0_colab.RunError, match="active assignment"):
        a0_colab._parse_usage_output("Current balance: 262.07 compute units\nActive assignments: 1")
    assert a0_colab._is_mission_branch("res-541-a0", f"origin/{a0_colab.BRANCH}")
    assert not a0_colab._is_mission_branch("other-work", "origin/main")


def test_colab_model_prompt_preparation_stays_within_the_approved_case_bound(
    tmp_path: Path,
) -> None:
    path = tmp_path / "prepared.json"
    path.write_text(json.dumps(a0_engine.prepare_cases()), encoding="utf-8")

    cases = a0_colab_inference._load_prepared(path)

    assert len(cases) == 16
    assert all("Available synthetic evidence:" in case["user_message"] for case in cases)


def test_token_streamer_ignores_prompt_and_times_first_generated_token() -> None:
    streamer = a0_colab_inference.TimingStreamer()
    streamer.put(object())
    assert streamer.first_token_at is None
    streamer.put(object())
    assert streamer.first_token_at is not None
