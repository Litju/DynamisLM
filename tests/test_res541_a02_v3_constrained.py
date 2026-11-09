from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import pytest
from scripts import a02_v3_constrained as constrained
from scripts import a02_v3_contract as v3
from scripts import a02_v3_gold as gold
from scripts import a02_v3_score as score

CASES = score._cases()
CASE_IDS = v3.load_profile()["case_ids"]


def _encode(text: str) -> list[int]:
    return [ord(char) for char in text]


def _target_text(request: dict[str, Any], action: dict[str, Any]) -> str:
    result = constrained.decode(
        request=request,
        prompt_ids=[],
        encode=_encode,
        chooser=constrained.target_chooser(action),
    )
    text: str = result["text"]
    return text


def _oracle_scorer(target: str) -> constrained.SequenceLogprob:
    """Log-probability 0 for continuations consistent with ``target``, otherwise -1."""

    def score(ids: Sequence[int], start: int) -> float:
        text = "".join(chr(i) for i in ids)
        return 0.0 if target.startswith(text) else -1.0

    return score


@pytest.mark.parametrize("case_id", CASE_IDS)
def test_model_chooser_recovers_any_action_the_scorer_prefers(case_id: str) -> None:
    request = CASES[case_id]["request"]
    expected = gold.derive_gold(request)["action"]
    target = _target_text(request, expected)
    result = constrained.decode(
        request=request,
        prompt_ids=[],
        encode=_encode,
        chooser=constrained.model_chooser(_oracle_scorer(target)),
    )
    assert result["action"] == expected
    assert result["text"] == target
    assert v3.parse_action(result["text"], v3.observation_ids(request)) == expected
    assert 0 < result["scorer_calls"] <= constrained.max_scorer_calls(request)
    row = score.score_case(case_id, result["text"])
    assert row["syntax"]["strict_valid"] and row["intent"]["exact"]


def test_constrained_output_is_schema_valid_even_for_a_wrong_scorer() -> None:
    request = CASES["a02-unsupported-causality"]["request"]
    result = constrained.decode(
        request=request,
        prompt_ids=[1, 2, 3],
        encode=_encode,
        chooser=constrained.model_chooser(lambda ids, start: 0.0),
    )
    # All ties: the first canonical option wins at every choice point.
    assert result["action"] == {
        "analysis_class": v3.ANALYSIS_CLASSES[0],
        "observation_ids": ["observation-1", "observation-2"],
        "operation": v3.EXPOSED_OPERATIONS[0],
        "target_claims": {
            "measurement": list(v3.MEASUREMENT_LEVELS),
            "relationship": list(v3.RELATIONSHIP_LEVELS),
        },
    }
    row = score.score_case("a02-unsupported-causality", result["text"])
    # Syntax control: valid output, yet no intent credit for a wrong choice.
    assert row["syntax"]["strict_valid"] is True
    assert row["intent"]["exact"] is False
    assert row["executor"]["scientific_execution_count"] == 0


def test_scorer_receives_prompt_and_prefix_and_option_ids_only() -> None:
    request = CASES["a02-valid-numerical"]["request"]
    seen: list[tuple[int, int]] = []

    def scorer(ids: Sequence[int], start: int) -> float:
        assert list(ids[:2]) == [7, 8]
        seen.append((len(ids), start))
        return -float(len(ids) - start)

    result = constrained.decode(
        request=request,
        prompt_ids=[7, 8],
        encode=_encode,
        chooser=constrained.model_chooser(scorer),
    )
    assert all(length > start >= 2 for length, start in seen)
    assert result["token_ids"] == _encode(result["text"])
    assert "".join(result["pieces"]) == result["text"]


def test_single_option_points_are_forced_without_scoring() -> None:
    request = CASES["a02-missing-evidence"]["request"]
    calls: list[int] = []

    def scorer(ids: Sequence[int], start: int) -> float:
        calls.append(start)
        return 0.0

    result = constrained.decode(
        request=request, prompt_ids=[], encode=_encode, chooser=constrained.model_chooser(scorer)
    )
    forced = [c for c in result["choices"] if len(c["options"]) == 1]
    assert forced and all(c["scores"] == [0.0] for c in forced)
    assert len(calls) == result["scorer_calls"]


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_scores_fail_closed(bad: float) -> None:
    with pytest.raises(ValueError, match="non-finite"):
        constrained.decode(
            request=CASES["a02-valid-numerical"]["request"],
            prompt_ids=[],
            encode=_encode,
            chooser=constrained.model_chooser(lambda ids, start: bad),
        )


def test_chooser_cannot_escape_the_grammar() -> None:
    def rogue(walk: Any, field: str, options: list[str]) -> tuple[str, list[float]]:
        return '"INVENTED"', []

    with pytest.raises(ValueError, match="outside the grammar"):
        constrained.decode(
            request=CASES["a02-valid-numerical"]["request"],
            prompt_ids=[],
            encode=_encode,
            chooser=rogue,
        )


def test_max_scorer_calls_bounds_an_adversarial_scorer() -> None:
    for case_id in CASE_IDS:
        request = CASES[case_id]["request"]
        # Prefers every item over the close, maximizing the number of choice points.
        result = constrained.decode(
            request=request,
            prompt_ids=[],
            encode=_encode,
            chooser=constrained.model_chooser(
                lambda ids, start: -1.0 if chr(ids[-1]) == "]" else 0.0
            ),
        )
        assert result["scorer_calls"] == constrained.max_scorer_calls(request)


def test_decoded_text_is_compact_json_inside_native_framing() -> None:
    request = CASES["a02-valid-numerical"]["request"]
    text = _target_text(request, gold.derive_gold(request)["action"])
    body = json.loads(text[len(v3.OPEN) : -len(v3.CLOSE)])
    assert list(body) == ["name", "arguments"]
    # Ids are decided before the operation, which depends on how many are referenced.
    assert list(body["arguments"]) == [
        "analysis_class",
        "observation_ids",
        "operation",
        "target_claims",
    ]


def test_options_are_scored_from_a_shared_start_under_merging_tokenization() -> None:
    """A tokenizer that merges '",' and '"]' across the prefix/option boundary."""
    merges = {'",': 1_000_001, '"]': 1_000_002}

    def encode(text: str) -> list[int]:
        ids, index = [], 0
        while index < len(text):
            pair = text[index : index + 2]
            if pair in merges:
                ids.append(merges[pair])
                index += 2
            else:
                ids.append(ord(text[index]))
                index += 1
        return ids

    starts: list[int] = []

    def scorer(ids: Sequence[int], start: int) -> float:
        starts.append(start)
        return 0.0

    request = CASES["a02-valid-numerical"]["request"]
    result = constrained.decode(
        request=request,
        prompt_ids=[5, 6],
        encode=encode,
        chooser=constrained.model_chooser(scorer),
    )
    # The closing quote of the previous value merges with the next separator, so the
    # shared start backs off into the prefix and that token is re-scored for every option.
    assert result["max_rescored_prefix_tokens"] >= 1
    assert all(start >= 2 for start in starts)
    assert result["token_ids"] == encode(result["text"])
    assert v3.parse_action(result["text"], v3.observation_ids(request)) == result["action"]
