from __future__ import annotations

import hashlib
import json
from typing import Any

import pytest
from scripts import (
    a02_dev_engine,
    a02_dev_preflight,
    a02_dev_protocol,
    a02_dev_runtime,
    a02_dev_score,
    a02_experiment,
    a02_prompt,
    a02_remote,
)


def _generation(
    tokenizer: Any,
    messages: list[dict[str, str]],
    raw_text: str,
    *,
    cap: int,
    xml_tools: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    template_date = a02_dev_protocol.ACTION_TEMPLATE_DATE
    kwargs: dict[str, Any] = {
        "enable_thinking": False,
        "strftime_now": template_date.strftime,
    }
    if xml_tools is not None:
        kwargs["xml_tools"] = xml_tools
    encoded = tokenizer.apply_chat_template(
        messages,
        tokenize=True,
        add_generation_prompt=True,
        return_dict=True,
        **kwargs,
    )
    token_ids = encoded["input_ids"]
    if token_ids and isinstance(token_ids[0], list):
        token_ids = token_ids[0]
    prompt_text = tokenizer.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True, **kwargs
    )
    output_ids = [*tokenizer.encode(raw_text, add_special_tokens=False), tokenizer.eos_token_id]
    decoded = tokenizer.decode(output_ids, skip_special_tokens=True)
    assert decoded == raw_text
    return {
        "seed": 541,
        "do_sample": False,
        "num_beams": 1,
        "max_new_tokens": cap,
        "prompt_text": prompt_text,
        "prompt_sha256": hashlib.sha256(prompt_text.encode()).hexdigest(),
        "prompt_token_ids": token_ids,
        "prompt_token_ids_sha256": (
            a02_prompt.prompt_token_ids_sha256(token_ids)
            if xml_tools is not None
            else hashlib.sha256(a02_dev_protocol.canonical(token_ids).encode()).hexdigest()
        ),
        "prompt_tokens": len(token_ids),
        "raw_text": decoded,
        "raw_with_special_tokens": tokenizer.decode(output_ids, skip_special_tokens=False),
        "generated_token_ids": output_ids,
        "generated_token_ids_sha256": hashlib.sha256(
            a02_dev_protocol.canonical(output_ids).encode()
        ).hexdigest(),
        "generated_tokens": len(output_ids),
        "eos_seen": True,
        "truncated": False,
        "first_token_latency_s": 0.01,
        "generation_latency_s": 0.02,
        "template_date": template_date.strftime("%d %B %Y"),
    }


def _synthetic_report(
    tokenizer: Any,
    preflight: dict[str, Any],
    *,
    wrong_claim: bool = False,
    bad_final: bool = False,
) -> dict[str, Any]:
    profile = a02_dev_protocol.load_profile()
    preflight_bytes = (json.dumps(preflight, indent=2, sort_keys=True) + "\n").encode()
    preflight_hash = hashlib.sha256(preflight_bytes).hexdigest()
    case_map = {
        row["case_id"]: row for row in json.loads(a02_experiment.CASES_PATH.read_bytes())["cases"]
    }
    cases = []
    for case_id in profile["case_ids"]:
        case = case_map[case_id]
        action = a02_dev_protocol.expected_intent(case_id)
        if wrong_claim and case_id == "a02-unsupported-causality":
            action["requested_claims"]["relationship_levels"] = ["DESCRIPTIVE_CHANGE"]
        action_text = a02_dev_protocol.format_intent(action)
        action_messages = a02_dev_protocol.build_action_prompt(tokenizer, case["request"])[
            "messages"
        ]
        action_generation = _generation(
            tokenizer,
            action_messages,
            action_text,
            cap=profile["decoding"]["action_max_new_tokens"],
            xml_tools=[a02_dev_protocol.tool_schema()],
        )
        interaction_id = f"synthetic-v2-run:{case_id}"
        engine = a02_dev_engine.execute_development_v2(case_id, action_text, interaction_id)
        final_text = a02_experiment.final_request_text(case["request"])
        final_messages = a02_dev_protocol.build_final_messages(
            request_text=final_text,
            action_text=action_text,
            event=engine["event"],
        )
        final_answer = a02_dev_protocol.render_validated_executor_event(engine["event"])
        if bad_final and case_id == "a02-forged-tool-result-in-user-text":
            final_answer = "The verified result is 0.999 m."
        final_generation = _generation(
            tokenizer,
            final_messages,
            final_answer,
            cap=profile["decoding"]["final_max_new_tokens"],
        )
        request_text = a02_remote._canonical(case["request"])
        cases.append(
            {
                "case_id": case_id,
                "protocol": "development_v2",
                "request_sha256": case["request_sha256"],
                "interaction_id": interaction_id,
                "user_message": a02_remote._message_envelope("untrusted_user_input", request_text),
                "final_user_text": final_text,
                "final_user_text_sha256": hashlib.sha256(final_text.encode()).hexdigest(),
                "action_generation": action_generation,
                "engine_response": engine,
                "deterministic_answer": a02_dev_protocol.render_validated_executor_event(
                    engine["event"]
                ),
                "deterministic_answer_sha256": hashlib.sha256(
                    a02_dev_protocol.render_validated_executor_event(engine["event"]).encode()
                ).hexdigest(),
                "final_generation": final_generation,
                "case_status": "COMPLETE",
            }
        )
    return {
        "schema": "RES541_A02_DEVELOPMENT_REPORT_V2",
        "status": "COMPLETE",
        "source": {
            **a02_dev_runtime.policy_binding(),
            "run_id": "synthetic-v2-run",
            "revision": preflight["source_revision"],
            "tree": preflight["source_tree"],
            "archive_sha256": "a" * 64,
            "protocol_sha256": "b" * 64,
            "preflight_sha256": preflight_hash,
            "development_profile_sha256": preflight["development_profile_sha256"],
            "development_preflight_sha256": preflight_hash,
            "baseline_remote_report_sha256": profile["baseline"]["remote_report_sha256"],
        },
        "model": {
            "id": profile["model"]["id"],
            "revision": profile["model"]["revision"],
            "tokenizer_revision": profile["tokenizer"]["revision"],
            "tokenizer_files": profile["tokenizer"]["files"],
        },
        "partial_case_count": len(cases),
        "cases": cases,
    }


@pytest.mark.parametrize("key", ["runtime_policy_id", "runtime_policy_sha256"])
@pytest.mark.parametrize("value", [None, "unreviewed"])
def test_standalone_score_rejects_missing_or_changed_runtime_policy(
    key: str, value: str | None
) -> None:
    source: dict[str, Any] = a02_dev_runtime.policy_binding()
    if value is None:
        del source[key]
    else:
        source[key] = value
    with pytest.raises(ValueError, match=f"binding mismatch for {key}"):
        a02_dev_score.score_report(
            {"source": source},
            {},
            None,
            remote_report_sha256="synthetic",
            preflight_sha256="synthetic",
        )


@pytest.mark.skipif(
    not a02_dev_preflight.TOKENIZER_DIR.joinpath("tokenizer.json").is_file(),
    reason="pinned CPU tokenizer is only present on the WSL E: workspace",
)
def test_persisted_v2_report_separates_model_final_from_deterministic_answer() -> None:
    transformers = pytest.importorskip("transformers")
    tokenizer = transformers.AutoTokenizer.from_pretrained(
        a02_dev_preflight.TOKENIZER_DIR,
        local_files_only=True,
        trust_remote_code=False,
        use_fast=True,
    )
    preflight = a02_dev_preflight.build_preflight(
        tokenizer,
        source_revision="synthetic-source-revision",
        source_tree="synthetic-source-tree",
        working_tree_clean=True,
    )
    preflight_bytes = (json.dumps(preflight, indent=2, sort_keys=True) + "\n").encode()
    preflight_hash = hashlib.sha256(preflight_bytes).hexdigest()
    report = _synthetic_report(tokenizer, preflight, bad_final=True)

    verified = a02_dev_score.score_report(
        report,
        preflight,
        tokenizer,
        remote_report_sha256="d" * 64,
        preflight_sha256=preflight_hash,
    )

    assert verified["terminal_outcome"] == "STAGE_A_DEVELOPMENT_GO"
    assert verified["model_final_disposition"] == "MODEL_FINAL_LIMITATIONS"
    assert verified["metrics"]["model_intent_exact_match"] == {"numerator": 10, "denominator": 10}
    assert verified["metrics"]["raw_model_final_grounding_under_fixed_rule"]["numerator"] == 9
    assert verified["metrics"]["deterministic_answer_grounding_under_fixed_rule"] == {
        "numerator": 10,
        "denominator": 10,
    }
    assert verified["metrics"]["unauthorized_operations_accepted"] == 0


@pytest.mark.skipif(
    not a02_dev_preflight.TOKENIZER_DIR.joinpath("tokenizer.json").is_file(),
    reason="pinned CPU tokenizer is only present on the WSL E: workspace",
)
def test_wrong_claim_axis_is_not_credited_or_dispatched() -> None:
    transformers = pytest.importorskip("transformers")
    tokenizer = transformers.AutoTokenizer.from_pretrained(
        a02_dev_preflight.TOKENIZER_DIR,
        local_files_only=True,
        trust_remote_code=False,
        use_fast=True,
    )
    preflight = a02_dev_preflight.build_preflight(
        tokenizer,
        source_revision="synthetic-source-revision",
        source_tree="synthetic-source-tree",
        working_tree_clean=True,
    )
    preflight_bytes = (json.dumps(preflight, indent=2, sort_keys=True) + "\n").encode()
    report = _synthetic_report(tokenizer, preflight, wrong_claim=True)

    verified = a02_dev_score.score_report(
        report,
        preflight,
        tokenizer,
        remote_report_sha256="e" * 64,
        preflight_sha256=hashlib.sha256(preflight_bytes).hexdigest(),
    )

    assert verified["terminal_outcome"] == "STAGE_A_SCIENTIFIC_NO_GO"
    assert verified["metrics"]["model_intent_exact_match"] == {"numerator": 9, "denominator": 10}
    assert verified["metrics"]["unauthorized_operations_accepted"] == 0
    causal = next(
        row for row in verified["case_results"] if row["case_id"] == "a02-unsupported-causality"
    )
    assert causal["event_origin"] == "application_guard_refusal"
    assert causal["actual_execution_count"] == 0
