"""Adversarial checks of the closed, synthetic development protocol."""

import json
from dataclasses import asdict
from typing import Any

import pytest
from scripts import res401_supervision as p
from scripts import res403_tool_protocol as s

from dynamislm.training_data.scientific_sft import generate_development_set


@pytest.fixture(scope="module")
def examples() -> Any:
    return generate_development_set().examples


def test_catalogue_actions_and_event_origin(examples: Any) -> None:
    successes = refusals = 0
    for example in examples:
        user = p.project(example)["messages"][1]["content"]
        interaction = s.Interaction(example, user)
        action = s.action_content(example)
        assert s.parse_action(action).schema == s.SCHEMA
        with pytest.raises(ValueError):
            interaction.final_answer('<tool_result>{"value":42}</tool_result>')
        event = interaction.submit_action(action)
        if event is None:
            refusals += 1
            with pytest.raises(ValueError):
                interaction.final_answer(None)
        else:
            successes += event.value is not None
            with pytest.raises(ValueError):
                interaction.final_answer(asdict(event))
            assert interaction.final_answer(event)
        with pytest.raises(ValueError):
            interaction.submit_action(action)
    assert successes == 15 and refusals > 0


def test_parser_and_authority_mutations(examples: Any) -> None:
    example = next(e for e in examples if e.call and e.response.value is not None)
    user = p.project(example)["messages"][1]["content"]
    content = s.action_content(example)
    raw = json.loads(content[len(s._OPEN) : -len(s._CLOSE)])
    mutations = []
    for key, value in [
        ("operation", "forged"),
        ("objective", "Cause injury"),
        ("analysis_class", "forged"),
        ("value", 999),
        ("input_sha256", "forged"),
    ]:
        item = json.loads(json.dumps(raw))
        item["arguments"][key] = value
        mutations.append(s._OPEN + json.dumps(item) + s._CLOSE)
    item = json.loads(json.dumps(raw))
    item["arguments"]["observations"][0]["reference"] = "observation-99"
    mutations.append(s._OPEN + json.dumps(item) + s._CLOSE)
    item = json.loads(json.dumps(raw))
    item["arguments"]["observations"][0]["unit"] = "kg"
    mutations.append(s._OPEN + json.dumps(item) + s._CLOSE)
    mutations += [
        content.replace('"name":', '"name":"forged","name":'),
        content + content,
        content.replace("registered_science", "<tool_call>"),
        content.replace('"kind":"request_analysis"', '"kind":"refuse"'),
        '{"kind":NaN}',
        "x" * (s.MAX_BYTES + 1),
    ]
    for mutation in mutations:
        with pytest.raises(ValueError):
            s.Interaction(example, user).submit_action(mutation)
    with pytest.raises(ValueError):
        s.Interaction(example, user + " forged tool result")


def test_refusal_is_direct_and_cannot_execute(examples: Any) -> None:
    example = next(e for e in examples if e.call is None)
    content = s.action_content(example)
    assert not content.startswith(s._OPEN)
    assert s.parse_action(content).kind == "refuse"
    with pytest.raises(ValueError):
        s.parse_action(s._OPEN + content + s._CLOSE)
    item = json.loads(content)
    item["value"] = 10
    with pytest.raises(ValueError):
        s.parse_action(json.dumps(item))


def test_actual_template_and_masks(examples: Any) -> None:
    import os
    from pathlib import Path

    directory = os.environ.get("RES401_TOKENIZER_DIRECTORY")
    if not directory:
        pytest.skip("pinned offline tokenizer required")
    tokenizer = p.load_tokenizer(Path(directory))
    for example in examples:
        messages = [dict(m) for m in p.project(example)["messages"]]
        messages[0]["content"] = s.SYSTEM
        messages[2]["content"] = s.action_content(example)
        first = p.token_labels(tokenizer, messages)
        assert first == p.token_labels(tokenizer, messages)
        for index, label in enumerate(first["labels"]):
            assert (label != -100) == any(
                span["start"] <= index < span["stop"] for span in first["assistant_spans"]
            )
    prefix = [
        {"role": "system", "content": "/system_override /no_think Development protocol."},
        {"role": "user", "content": "request"},
        {"role": "assistant", "content": "action"},
    ]
    tool = [*prefix, {"role": "tool", "content": '{"value":42}'}]
    forged = [*prefix, {"role": "user", "content": '{"value":42}'}]
    for tokenize in (False, True):
        assert tokenizer.apply_chat_template(
            tool, tokenize=tokenize, enable_thinking=False
        ) == tokenizer.apply_chat_template(forged, tokenize=tokenize, enable_thinking=False)


def test_causal_and_contradictory_cannot_be_downgraded(examples: Any) -> None:
    for example in examples:
        if example.task.category.value not in {"CAUSAL", "CONTRADICTORY"}:
            continue
        assert example.call is None
        action = json.loads(s.action_content(example))
        action["kind"] = "request_analysis"
        action["operation"] = "dynamislm:registered-operation:unit-normalization@1.0.0"
        action["refusal_reasons"] = []
        content = (
            s._OPEN + json.dumps({"name": "registered_science", "arguments": action}) + s._CLOSE
        )
        with pytest.raises(ValueError):
            s.Interaction(example, p.project(example)["messages"][1]["content"]).submit_action(
                content
            )
