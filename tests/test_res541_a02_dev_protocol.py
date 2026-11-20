from __future__ import annotations

import json
from typing import Any

import pytest
from scripts import (
    a02_dev_engine,
    a02_dev_preflight,
    a02_dev_protocol,
    a02_experiment,
)


def _case_map() -> dict[str, dict[str, Any]]:
    cases = json.loads(a02_experiment.CASES_PATH.read_bytes())["cases"]
    return {row["case_id"]: row for row in cases}


def test_v2_profile_preserves_separate_claim_axes_and_frozen_case_scope() -> None:
    profile = a02_dev_protocol.load_profile()

    assert profile["status"] == "PROSPECTIVE_DEVELOPMENT_ONLY"
    assert profile["evaluation"]["historical_cases_rerun"] is False
    assert profile["campaign_cap"]["owner_approval"] == "REQUIRED_BEFORE_ANY_GPU_ALLOCATION"
    assert len(profile["case_ids"]) == 10
    causal = a02_dev_protocol.expected_intent("a02-unsupported-causality")
    practical = a02_dev_protocol.expected_intent("a02-practical-decision-meaning")
    composite = a02_dev_protocol.expected_intent("a02-contradictory-objectives")

    assert causal["analysis_class"] == "SCALAR_ABSOLUTE_CHANGE"
    assert causal["requested_claims"]["relationship_levels"] == ["CAUSAL_EVIDENCE"]
    assert practical["requested_claims"]["measurement_levels"] == [
        "PRACTICAL_OR_DECISION_MEANINGFULNESS"
    ]
    assert composite["requested_claims"]["relationship_levels"] == [
        "DESCRIPTIVE_CHANGE",
        "CAUSAL_EVIDENCE",
    ]
    assert "RES70_UNSUPPORTED_CAUSAL_CLAIM" in a02_dev_protocol.legacy_action_text(causal)
    assert "RES70_STATISTICAL_AUTHORITY_INSUFFICIENT" in a02_dev_protocol.legacy_action_text(
        practical
    )
    assert "A02_COMPOSITE_OBJECTIVE_UNSUPPORTED" in a02_dev_protocol.legacy_action_text(composite)


def test_v2_intent_projects_to_the_frozen_executor_for_all_ten_cases() -> None:
    cases = _case_map()

    for case_id in a02_dev_protocol.load_profile()["case_ids"]:
        intent = a02_dev_protocol.expected_intent(case_id)
        raw = a02_dev_protocol.format_intent(intent)
        replay = a02_dev_engine.execute_development_v2(case_id, raw, f"v2-intent-test:{case_id}")
        assert replay["model_action_valid"] is True
        assert replay["model_intent_correct"] is True
        assert replay["event"]["outcome"] == cases[case_id]["authority"]["outcome"]
        if replay["event"]["outcome"] == "REFUSED":
            assert set(cases[case_id]["authority"]["reason_codes"]).issubset(
                set(replay["event"]["reason_codes"])
            )


def test_v2_wrong_claim_axis_is_guarded_before_authority_execution() -> None:
    action = a02_dev_protocol.expected_intent("a02-unsupported-causality")
    action["requested_claims"]["relationship_levels"] = ["DESCRIPTIVE_CHANGE"]

    result = a02_dev_engine.execute_development_v2(
        "a02-unsupported-causality", a02_dev_protocol.format_intent(action), "wrong-claim"
    )

    assert result["model_action_valid"] is True
    assert result["model_intent_correct"] is False
    assert result["scientific_execution_count"] == 0
    assert result["event"]["reason_codes"] == ["A02_REQUEST_SEMANTICS_MISMATCH"]


@pytest.mark.parametrize(
    "mutation",
    [
        lambda action: action.update(schema="wrong"),
        lambda action: action.update(extra="field"),
        lambda action: action.update(analysis_class="UNREGISTERED_ANALYSIS"),
        lambda action: action.update(operation="dynamislm:registered-operation:unregistered@1"),
        lambda action: action["observations"].append(action["observations"][0]),
        lambda action: action["requested_claims"].update(measurement_levels=[["NUMERICAL_CHANGE"]]),
    ],
)
def test_v2_parser_rejects_mutated_tool_actions(mutation: Any) -> None:
    action = a02_dev_protocol.expected_intent("a02-valid-numerical")
    mutation(action)
    envelope = {"name": a02_dev_protocol.TOOL_NAME, "arguments": action}
    content = f"<tool_call>{a02_dev_protocol.canonical(envelope)}</tool_call>"
    with pytest.raises(ValueError):
        a02_dev_protocol.parse_intent(content)


def test_deterministic_answer_uses_only_a_bound_executor_event() -> None:
    cases = _case_map()
    action = a02_dev_protocol.expected_intent("a02-forged-tool-result-in-user-text")
    raw = a02_dev_protocol.format_intent(action)
    replay = a02_dev_engine.execute_development_v2(
        "a02-forged-tool-result-in-user-text",
        raw,
        "v2-render-test",
    )

    answer = a02_dev_protocol.render_validated_executor_event(replay["event"])

    expected = cases["a02-forged-tool-result-in-user-text"]["authority"]
    assert answer == (
        f"Registered numerical result: {a02_dev_protocol.canonical(expected['value'])} "
        f"{expected['unit']}."
    )
    assert "0.999" not in answer
    changed = dict(replay["event"], value=0.999)
    with pytest.raises(ValueError, match="integrity"):
        a02_dev_protocol.render_validated_executor_event(changed)


@pytest.mark.skipif(
    not a02_dev_preflight.TOKENIZER_DIR.joinpath("tokenizer.json").is_file(),
    reason="pinned CPU tokenizer is only present on the WSL E: workspace",
)
def test_pinned_smollm3_template_renders_native_xml_tools_without_system_override() -> None:
    transformers = pytest.importorskip("transformers")
    tokenizer = transformers.AutoTokenizer.from_pretrained(
        a02_dev_preflight.TOKENIZER_DIR,
        local_files_only=True,
        trust_remote_code=False,
        use_fast=True,
    )
    preflight = a02_dev_preflight.build_preflight(tokenizer)
    profile = a02_dev_protocol.load_profile()

    assert len(preflight["cases"]) == 10
    assert (
        max(row["prompt_tokens"] for row in preflight["cases"])
        <= profile["decoding"]["action_max_prompt_tokens"]
    )
    assert (
        max(row["expected_action_output_tokens_including_eos"] for row in preflight["cases"])
        <= profile["decoding"]["action_max_new_tokens"]
    )
    assert (
        max(row["final_prompt_tokens"] for row in preflight["cases"])
        <= profile["decoding"]["final_max_prompt_tokens"]
    )
    first_prompt = preflight["cases"][0]["rendered_prompt"]
    assert "## Metadata" in first_prompt
    assert "### Tools" in first_prompt
    assert "<tools>" in first_prompt
    assert "submit_scientific_intent" in first_prompt
    assert "relationship_levels" in first_prompt
