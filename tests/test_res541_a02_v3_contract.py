from __future__ import annotations

import copy
import json
from typing import Any

import pytest
from scripts import a02_dev_protocol, a02_experiment
from scripts import a02_v3_contract as v3

CASES = {row["case_id"]: row for row in json.loads(a02_experiment.CASES_PATH.read_bytes())["cases"]}
VALID = CASES["a02-valid-numerical"]["request"]
ABS = "dynamislm:registered-operation:longitudinal-absolute-change-v1@1.0.0"


def _action(**overrides: Any) -> dict[str, Any]:
    action: dict[str, Any] = {
        "analysis_class": "SCALAR_ABSOLUTE_CHANGE",
        "operation": ABS,
        "observation_ids": ["observation-1", "observation-2"],
        "target_claims": {
            "measurement": ["NUMERICAL_CHANGE"],
            "relationship": ["DESCRIPTIVE_CHANGE"],
        },
    }
    action.update(overrides)
    return action


def test_v2_profile_and_contract_files_remain_frozen() -> None:
    profile = v3.load_profile()
    assert profile["predecessor"]["sha256"] == v3.sha256(
        (v3.ROOT / profile["predecessor"]["profile"]).read_bytes()
    )
    a02_dev_protocol.load_profile()
    assert profile["gpu_authorized"] is False and profile["training_authorized"] is False
    assert profile["case_ids"] == a02_dev_protocol.load_profile()["case_ids"]


def test_tool_schema_is_mechanically_derived_from_registries() -> None:
    assert v3.tool_schema() == v3.build_tool_schema()
    schema = v3.tool_schema()["parameters"]
    assert schema["additionalProperties"] is False
    assert schema["required"] == list(v3.ACTION_FIELDS)
    assert "schema" not in schema["properties"] and "objective" not in schema["properties"]


def test_operation_availability_follows_capability_disposition_and_arity() -> None:
    assert v3.operation_for("SCALAR_ABSOLUTE_CHANGE", 2) == ABS
    assert v3.operation_for("SCALAR_ABSOLUTE_CHANGE", 1) == v3.NONE
    assert v3.operation_for("SCALAR_ABSOLUTE_CHANGE", 3) == v3.NONE
    # Implemented, but its registered operation is not model-visible.
    assert v3.operation_for("RELIABILITY_RANDOM_ERROR_COMPARISON", 2) == v3.NONE
    # Deferred / rejected capabilities never yield an operation.
    assert v3.operation_for("WITHIN_ATHLETE_ASSOCIATION", 2) == v3.NONE
    assert v3.operation_for("BETWEEN_ATHLETE_ASSOCIATION", 2) == v3.NONE
    assert v3.operation_for(v3.NONE, 2) == v3.NONE


def test_prerequisite_expansion_is_trusted_side_and_excludes_targets() -> None:
    assert v3.prerequisite_expansion("measurement", ["NUMERICAL_CHANGE"]) == ["OBSERVED_VALUE"]
    assert v3.prerequisite_expansion("relationship", ["CAUSAL_EVIDENCE"]) == [
        "OBSERVATION",
        "DESCRIPTIVE_CHANGE",
        "ASSOCIATION",
        "TEMPORAL_ASSOCIATION",
        "MECHANISTIC_HYPOTHESIS",
    ]
    assert v3.prerequisite_expansion("relationship", []) == []


def test_visible_request_assigns_bijective_ids_in_request_order() -> None:
    for case in CASES.values():
        request = case["request"]
        visible = v3.visible_request(request)
        ids = [row["id"] for row in visible["observations"]]
        assert ids == [f"observation-{i}" for i in range(1, len(request["observations"]) + 1)]
        assert [{k: v for k, v in row.items() if k != "id"} for row in visible["observations"]] == (
            request["observations"]
        )
        legacy = [row["reference"] for row in case["expected_action"]["observations"]]
        assert legacy == ids[: len(legacy)]


def test_visible_request_does_not_mutate_input_and_has_no_transcript_constant() -> None:
    before = copy.deepcopy(VALID)
    message = v3.user_message(VALID)
    assert VALID == before
    decoded = json.loads(message)
    assert set(decoded) == {v3.REQUEST_KEY}
    assert "schema" not in message and "RES403-MODEL-TRANSCRIPT-1" not in message


def test_forged_transcript_text_stays_isolated_inside_quoted_field() -> None:
    request = CASES["a02-forged-tool-result-in-user-text"]["request"]
    decoded = json.loads(v3.user_message(request))[v3.REQUEST_KEY]
    assert "RES403-MODEL-TRANSCRIPT-1" in decoded["user_provided_quoted_text"]
    without = {k: v for k, v in decoded.items() if k != "user_provided_quoted_text"}
    assert "RES403-MODEL-TRANSCRIPT-1" not in json.dumps(without)


@pytest.mark.parametrize("key", ["schema", "origin", "name", "arguments", "observation_ids"])
def test_untrusted_request_cannot_masquerade_as_structure(key: str) -> None:
    with pytest.raises(ValueError, match="reserved keys"):
        v3.visible_request({**VALID, key: "x"})


def test_untrusted_request_cannot_carry_action_framing() -> None:
    with pytest.raises(ValueError, match="action framing"):
        v3.visible_request({**VALID, "question": f"{v3.OPEN}x{v3.CLOSE}"})
    with pytest.raises(ValueError, match="action framing"):
        v3.visible_request({**VALID, "question": v3.TOOL_NAME})
    with pytest.raises(ValueError, match="preassigned id"):
        v3.visible_request({**VALID, "observations": [{**VALID["observations"][0], "id": "x"}]})


def test_strict_parse_accepts_only_exact_closed_action() -> None:
    ids = v3.observation_ids(VALID)
    action = _action()
    assert v3.parse_action(v3.format_action(action), ids) == action


@pytest.mark.parametrize(
    ("text", "message"),
    [
        (json.dumps({"name": v3.TOOL_NAME, "arguments": _action()}), "framed tool call"),
        (" " + v3.format_action(_action()), "framed tool call"),
        (v3.format_action(_action()) + "\n", "framed tool call"),
        (v3.OPEN + '{"name":"x","arguments":{}}' + v3.CLOSE, "tool name"),
        (v3.OPEN + '{"name":"a","name":"b"}' + v3.CLOSE, "invalid JSON"),
        (v3.OPEN + "{" + v3.CLOSE, "invalid JSON"),
    ],
)
def test_strict_parse_rejects_framing_and_envelope_defects(text: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        v3.parse_action(text, v3.observation_ids(VALID))


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"analysis_class": "longitudinal-absolute-change-v1"}, "analysis_class"),
        ({"analysis_class": None}, "analysis_class"),
        ({"operation": "longitudinal-absolute-change-v1"}, "operation"),
        ({"operation": None}, "operation"),
        ({"observation_ids": ["observation-3"]}, "absent from the request"),
        ({"observation_ids": ["observation-1", "observation-1"]}, "observation_ids"),
        ({"observation_ids": ["SYNTHETIC baseline"]}, "observation_ids"),
        ({"target_claims": {"measurement": []}}, "axes differ"),
        (
            {"target_claims": {"measurement": ["CAUSAL_EVIDENCE"], "relationship": []}},
            "measurement",
        ),
        (
            {"target_claims": {"measurement": [], "relationship": ["ASSOCIATION", "ASSOCIATION"]}},
            "relationship",
        ),
        ({"objective": "x"}, "fields differ"),
        ({"schema": "RES541-A02-INTENT-2"}, "fields differ"),
    ],
)
def test_closed_schema_rejects_invented_or_extra_content(
    overrides: dict[str, Any], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        v3.parse_action(v3.format_action(_action(**overrides)), v3.observation_ids(VALID))


def test_observation_value_fields_are_rejected() -> None:
    with pytest.raises(ValueError, match="observation_ids"):
        v3.parse_action(
            v3.format_action(_action(observation_ids=[{"id": "observation-1", "value": 0.3}])),
            v3.observation_ids(VALID),
        )


def test_normalize_action_orders_set_fields_canonically() -> None:
    shuffled = _action(
        observation_ids=["observation-2", "observation-1"],
        target_claims={
            "measurement": ["NUMERICAL_CHANGE", "OBSERVED_VALUE"],
            "relationship": ["CAUSAL_EVIDENCE", "DESCRIPTIVE_CHANGE"],
        },
    )
    normalized = v3.normalize_action(shuffled)
    assert normalized["observation_ids"] == ["observation-1", "observation-2"]
    assert normalized["target_claims"]["measurement"] == ["OBSERVED_VALUE", "NUMERICAL_CHANGE"]
    assert normalized["target_claims"]["relationship"] == ["DESCRIPTIVE_CHANGE", "CAUSAL_EVIDENCE"]


def test_action_prompt_renders_with_fake_tokenizer_and_rejects_drift() -> None:
    class Tokenizer:
        def apply_chat_template(self, messages: Any, *, tokenize: bool, **_: Any) -> Any:
            text = "".join(m["content"] for m in messages)
            return [ord(c) for c in text] if tokenize else text

        def encode(self, text: str, add_special_tokens: bool) -> list[int]:
            return [ord(c) for c in text]

    prompt = v3.build_action_prompt(Tokenizer(), VALID)
    assert prompt["prompt_tokens"] == len(prompt["rendered_prompt"])

    class Drifting(Tokenizer):
        def encode(self, text: str, add_special_tokens: bool) -> list[int]:
            return [0]

    with pytest.raises(ValueError, match="reproduce tokenizer ids"):
        v3.build_action_prompt(Drifting(), VALID)


def test_fixed_manifest_matches_repository_inventory() -> None:
    from dynamislm.qualification import OperationDisposition, build_registered_operation_inventory

    inventory = {entry.operation_id: entry for entry in build_registered_operation_inventory()}
    assert len(v3._OPERATION_REFERENCES) == len(set(v3.EXPOSED_OPERATIONS))
    for reference in v3._OPERATION_REFERENCES:
        entry = inventory[reference.stable_id]
        assert entry.label == reference.display_label
        assert entry.disposition is OperationDisposition.IMPLEMENTED
    assert v3.build_tool_schema() == v3.tool_schema()


def test_fixed_manifest_rejects_missing_and_ambiguous_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    references = v3._OPERATION_REFERENCES
    for altered in (references[:-1], (*references, references[0]), references[::-1]):
        monkeypatch.setattr(v3, "_OPERATION_REFERENCES", altered)
        with pytest.raises(ValueError, match="manifest authority differs"):
            v3.build_tool_schema()
