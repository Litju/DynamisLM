"""CPU conformance checks against the independently retained A0.2 preflight."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from huggingface_hub import snapshot_download
from scripts import a02_engine, a02_experiment, a02_preflight, a02_prompt, a02_remote, a02_score

from dynamislm.serialization import canonical_json

ROOT = Path(__file__).resolve().parents[1]
FROZEN_PATH = ROOT / "experiments/a02/prompt-conformance-v1.json"
TOKENIZER_PATH = Path("/mnt/e/DynamisLM-A0/a01/tokenizer")
MODEL_ID = "HuggingFaceTB/SmolLM3-3B"
MODEL_REVISION = "a07cc9a04f16550a088caea529712d1d335b0ac1"
FROZEN = json.loads(FROZEN_PATH.read_text())
PROTOCOL = json.loads((ROOT / "experiments/a02/protocol-v1.json").read_text())
CASES = json.loads((ROOT / "experiments/a02/cases-v1.json").read_text())["cases"]
CASE_BY_ID = {case["case_id"]: case for case in CASES}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture(scope="module")
def tokenizer() -> Any:
    pins = PROTOCOL["model"]["tokenizer_files"]
    local = TOKENIZER_PATH
    if not local.is_dir() or any(
        not (local / name).is_file() or _sha((local / name).read_bytes()) != expected
        for name, expected in pins.items()
    ):
        local = Path(
            snapshot_download(
                repo_id=MODEL_ID,
                revision=MODEL_REVISION,
                allow_patterns=list(pins),
            )
        )
    actual = {name: _sha((local / name).read_bytes()) for name in pins}
    assert actual == pins

    from transformers import AutoTokenizer  # type: ignore[import-not-found]

    loaded = AutoTokenizer.from_pretrained(
        local, local_files_only=True, trust_remote_code=False, use_fast=True
    )
    assert loaded.chat_template == (local / "chat_template.jinja").read_text()
    return loaded


def _assert_frozen(rendered: str, token_ids: list[int], frozen: dict[str, Any]) -> None:
    assert rendered == frozen["rendered_prompt"]
    assert token_ids == frozen["prompt_token_ids"]
    assert len(token_ids) == frozen["prompt_tokens"]
    assert _sha(rendered.encode("utf-8")) == frozen["rendered_prompt_sha256"]
    assert _sha(canonical_json(token_ids).encode("utf-8")) == frozen["prompt_token_ids_sha256"]


def test_actual_pinned_tokenizer_reproduces_all_26_frozen_action_prompts(
    tokenizer: Any,
) -> None:
    assert FROZEN["source_preflight_sha256"] == PROTOCOL["tokenizer_preflight"]["artifact_sha256"]
    assert FROZEN["tokenizer_revision"] == MODEL_REVISION
    assert FROZEN["tokenizer_files"] == PROTOCOL["model"]["tokenizer_files"]
    assert FROZEN["model_weights_loaded"] is False
    assert FROZEN["gpu_allocated"] is False

    historical = json.loads((ROOT / "experiments/a02/historical-inputs-v1.json").read_text())[
        "cases"
    ]
    assert len(FROZEN["historical_cases"]) == 16
    assert len(FROZEN["new_action_cases"]) == 10
    historical_by_id = {row["case_id"]: row for row in historical}
    historical_system = (ROOT / "experiments/a01/system-prompt-v1.txt").read_text().rstrip("\n")
    for frozen in FROZEN["historical_cases"]:
        row = historical_by_id[frozen["case_id"]]
        assert row["user_message_sha256"] == frozen["user_message_sha256"]
        messages = [
            {"role": "system", "content": historical_system},
            {"role": "user", "content": row["user_message"]},
        ]
        token_ids, rendered = a02_preflight._render(
            tokenizer, messages, a02_preflight.TEMPLATE_DATES["historical"]
        )
        _assert_frozen(rendered, token_ids, frozen)

    action_system = (ROOT / "experiments/a02/system-action-v1.txt").read_text().rstrip("\n")
    for frozen in FROZEN["new_action_cases"]:
        case = CASE_BY_ID[frozen["case_id"]]
        assert case["request_sha256"] == frozen["request_sha256"]
        prompt = a02_prompt.build_action_prompt(tokenizer, case["request"], action_system)
        _assert_frozen(prompt["rendered_prompt"], prompt["prompt_token_ids"], frozen)


def test_previous_plain_json_action_prompt_is_rejected(tokenizer: Any) -> None:
    frozen = FROZEN["new_action_cases"][0]
    case = CASE_BY_ID[frozen["case_id"]]
    system = (ROOT / "experiments/a02/system-action-v1.txt").read_text().rstrip("\n")
    plain_request = a02_score.canonical(case["request"])
    user_message = a02_remote._message_envelope("untrusted_user_input", plain_request)
    token_ids, rendered = a02_preflight._render(
        tokenizer,
        [{"role": "system", "content": system}, {"role": "user", "content": user_message}],
        a02_prompt.ACTION_TEMPLATE_DATE,
    )
    assert rendered != frozen["rendered_prompt"]
    assert token_ids != frozen["prompt_token_ids"]
    with pytest.raises(ValueError, match="differs from frozen input contract"):
        a02_prompt.verify_frozen_prompt(rendered, token_ids, frozen, case["case_id"])


def _generation(prompt: dict[str, Any], tokenizer: Any, raw_text: str) -> dict[str, Any]:
    generated_ids = [
        *tokenizer.encode(raw_text, add_special_tokens=False),
        tokenizer.eos_token_id,
    ]
    return {
        "seed": 541,
        "do_sample": False,
        "num_beams": 1,
        "max_new_tokens": 128,
        "template_date": a02_prompt.ACTION_TEMPLATE_DATE.strftime("%d %B %Y"),
        "generation_latency_s": 0.25,
        "prompt_text": prompt["rendered_prompt"],
        "prompt_sha256": prompt["rendered_prompt_sha256"],
        "prompt_token_ids": prompt["prompt_token_ids"],
        "prompt_token_ids_sha256": prompt["prompt_token_ids_sha256"],
        "prompt_tokens": prompt["prompt_tokens"],
        "generated_token_ids": generated_ids,
        "generated_token_ids_sha256": _sha(a02_score.canonical(generated_ids).encode()),
        "generated_tokens": len(generated_ids),
        "raw_text": tokenizer.decode(generated_ids, skip_special_tokens=True),
        "raw_with_special_tokens": tokenizer.decode(generated_ids, skip_special_tokens=False),
        "eos_seen": True,
        "truncated": False,
    }


def _synthetic_model_refusal() -> str:
    action = {
        "schema": "RES403-SCIENTIFIC-ACTION-1",
        "kind": "refuse",
        "objective": "Do not infer unsupported causality.",
        "analysis_class": None,
        "operation": None,
        "observations": [],
        "refusal_reasons": ["UNSUPPORTED_CAUSALITY"],
    }
    return json.dumps(action, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def test_correct_serialized_prompt_passes_scoring_admission_and_old_prompt_does_not(
    tokenizer: Any,
) -> None:
    frozen = FROZEN["new_action_cases"][0]
    case = CASE_BY_ID[frozen["case_id"]]
    system = (ROOT / "experiments/a02/system-action-v1.txt").read_text().rstrip("\n")
    prompt = a02_prompt.build_action_prompt(tokenizer, case["request"], system)
    generation = _generation(prompt, tokenizer, _synthetic_model_refusal())
    decoded = a02_score._verify_generation(
        generation,
        prompt["messages"],
        tokenizer,
        a02_prompt.ACTION_TEMPLATE_DATE,
        128,
        1024,
        {
            "seed": 541,
            "do_sample": False,
            "num_beams": 1,
        },
        frozen_prompt=frozen,
    )
    assert decoded["prompt_sha256"] == frozen["rendered_prompt_sha256"]
    a02_prompt.verify_frozen_prompt(
        generation["prompt_text"], generation["prompt_token_ids"], frozen, case["case_id"]
    )

    interaction_id = "synthetic-prompt-admission"
    executor = a02_engine.execute_new(
        case["case_id"], generation["raw_text"], interaction_id, truncated=False
    )
    scorer_action_messages, _ = a02_score._prompt_messages(
        kind="new",
        case_id=case["case_id"],
        row={"user_message": a02_score.canonical(case["request"])},
        raw_action=generation["raw_text"],
        event=executor["event"],
    )
    assert scorer_action_messages == prompt["messages"]
    replay_row = {
        "interaction_id": interaction_id,
        "action_generation": generation,
        "engine_response": executor,
    }
    assert a02_score._replay_engine("new", case["case_id"], replay_row) == executor

    plain_request = a02_score.canonical(case["request"])
    old_messages = [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": a02_remote._message_envelope("untrusted_user_input", plain_request),
        },
    ]
    old_ids, old_rendered = a02_preflight._render(
        tokenizer, old_messages, a02_prompt.ACTION_TEMPLATE_DATE
    )
    old_prompt = {
        "rendered_prompt": old_rendered,
        "rendered_prompt_sha256": _sha(old_rendered.encode()),
        "prompt_token_ids": old_ids,
        "prompt_token_ids_sha256": _sha(canonical_json(old_ids).encode()),
        "prompt_tokens": len(old_ids),
    }
    old_prompt["prompt_token_ids_sha256"] = _sha(a02_score.canonical(old_ids).encode())
    old_generation = _generation(old_prompt, tokenizer, generation["raw_text"])
    old_row = {**replay_row, "action_generation": old_generation}
    assert a02_score._replay_engine("new", case["case_id"], old_row) == executor
    with pytest.raises(ValueError, match="does not reproduce through the pinned tokenizer"):
        a02_score._verify_generation(
            old_generation,
            prompt["messages"],
            tokenizer,
            a02_prompt.ACTION_TEMPLATE_DATE,
            128,
            1024,
            {"seed": 541, "do_sample": False, "num_beams": 1},
        )
    with pytest.raises(ValueError, match="differs from frozen input contract"):
        a02_prompt.verify_frozen_prompt(old_rendered, old_ids, frozen, case["case_id"])


def test_remote_runtime_stops_before_generation_on_frozen_prompt_mismatch() -> None:
    class TensorRow:
        def tolist(self) -> list[int]:
            return [101]

    class TensorBatch:
        def __getitem__(self, _index: int) -> TensorRow:
            return TensorRow()

        def to(self, _device: str) -> TensorBatch:
            return self

    class RuntimeTokenizer:
        eos_token_id = 0

        def apply_chat_template(self, _messages: Any, *, tokenize: bool, **kwargs: Any) -> Any:
            if not tokenize:
                return "<rendered>"
            if kwargs.get("return_dict"):
                return {"input_ids": TensorBatch(), "attention_mask": TensorBatch()}
            return [101]

        def encode(self, _rendered: str, *, add_special_tokens: bool) -> list[int]:
            assert add_special_tokens is False
            return [101]

    class RuntimeModel:
        device = "cpu"

        def generate(self, **_kwargs: Any) -> None:
            raise AssertionError("generation must not run for a prompt mismatch")

    with pytest.raises(ValueError, match="differs from frozen input contract"):
        a02_remote._generate(
            RuntimeModel(),
            RuntimeTokenizer(),
            object(),
            [{"role": "system", "content": "synthetic"}],
            cap=128,
            template_date=a02_prompt.ACTION_TEMPLATE_DATE,
            frozen_prompt={"case_id": "synthetic-mismatch", "rendered_prompt": "wrong"},
        )


def test_final_prompt_uses_model_action_and_executor_event_not_gold_action(tokenizer: Any) -> None:
    case = CASE_BY_ID["a02-unsupported-causality"]
    model_action = _synthetic_model_refusal()
    executor = a02_engine.execute_new(
        case["case_id"], model_action, "synthetic-model-action-final-stage", truncated=False
    )
    event = executor["event"]
    final_text = a02_experiment.final_request_text(case["request"])
    messages = a02_preflight._final_messages(
        user_text=final_text,
        action_text=model_action,
        event_text=a02_preflight._model_event(event),
        origin=event["origin"],
    )
    summary = {
        "origin": event["origin"],
        "outcome": event["outcome"],
        "reason_codes": event["reason_codes"],
        "value": event["value"],
        "unit": event["unit"],
        "claim_scope": "NUMERICAL_CHANGE_ONLY"
        if event["outcome"] == "RESULT"
        else "NO_RESULT_AUTHORIZED",
    }
    runtime_messages = [
        {
            "role": "system",
            "content": (ROOT / "experiments/a02/system-final-v1.txt").read_text().rstrip("\n"),
        },
        {
            "role": "user",
            "content": a02_remote._message_envelope("untrusted_user_input", final_text),
        },
        {
            "role": "assistant",
            "content": a02_remote._message_envelope("model_action_proposal", model_action),
        },
        {"role": "tool", "content": a02_remote._canonical(summary)},
    ]
    assert messages == runtime_messages
    ids, rendered = a02_preflight._render(tokenizer, messages, a02_prompt.ACTION_TEMPLATE_DATE)
    assert ids == tokenizer.encode(rendered, add_special_tokens=False)
    assert messages[2]["content"] == runtime_messages[2]["content"]
    assert event["origin"] in messages[3]["content"]
