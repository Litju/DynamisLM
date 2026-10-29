"""Adversarial synthetic CPU checks for RES-414's public evaluation boundary."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import replace
from typing import Any

import pytest

from scripts import res414_runner as runner

D = "1" * 64
GIT = "a" * 40


class StubModel:
    def __init__(self, responses: dict[str, Any]) -> None:
        self.responses = responses
        self.requests: list[runner.ModelRequest] = []

    def generate(self, request: runner.ModelRequest) -> str:
        self.requests.append(request)
        answer = self.responses[request.case_id]
        if isinstance(answer, Exception):
            raise answer
        return answer  # type: ignore[no-any-return]


class StubScorer:
    scorer_id = "test-only-exact-scoring"
    scorer_sha256 = D

    def score(
        self, reference: Mapping[str, object], response: Mapping[str, object]
    ) -> runner.Score:
        match = response == reference
        return runner.Score(
            "PASS" if match else "FAIL", () if match else ("DIAGNOSTIC_MISMATCH",)
        )


def case(case_id: str, request: str = "Question about a jump") -> runner.PublicSyntheticCase:
    return runner.PublicSyntheticCase(
        case_id=case_id,
        message=request,
        reference_json='{"decision":"ANSWER","fields":{"value":0.125}}',
    )


def spec(cases: tuple[runner.PublicSyntheticCase, ...]) -> runner.RunSpec:
    return runner.RunSpec(
        run_id="synthetic-run-1",
        suite_id="res414-synthetic-dev-1",
        suite_sha256=runner.suite_sha256(cases),
        model_id="test-stub",
        model_revision=D,
        tokenizer_revision=D,
        scorer_id=StubScorer.scorer_id,
        scorer_sha256=D,
        source_revision=GIT,
        environment_sha256=D,
        seed=414,
    )


def raw(value: float = 0.125) -> str:
    return json.dumps({"decision": "ANSWER", "fields": {"value": value}})


def test_public_stub_end_to_end_and_byte_identical_rescore() -> None:
    cases = (case("alpha", "Confidential-looking but synthetic prompt"), case("beta"))
    model = StubModel({"alpha": raw(), "beta": raw(0.5)})
    evidence = runner.execute(spec(cases), cases, model, StubScorer())
    assert [r.verdict for r in evidence.receipt.case_results] == ["PASS", "FAIL"]
    assert evidence.receipt.qualification == "DEVELOPMENT_ONLY_NOT_PSE_QUALIFIED"
    assert runner.verify_replay(evidence, cases, StubScorer()) == evidence.receipt
    assert runner.rescore(spec(cases), cases, evidence.responses, StubScorer()) == evidence.receipt
    assert [r.case_id for r in model.requests] == ["alpha", "beta"]
    assert not hasattr(model.requests[0], "reference_json")
    published = evidence.receipt.json()
    for secret in ("Confidential-looking but synthetic prompt", "value", raw()):
        assert secret not in published
    assert json.loads(published)["receipt_sha256"] == evidence.receipt.receipt_sha256


@pytest.mark.parametrize(
    "message",
    [
        "{",
        "[]",
        "{}",
        '{"decision":"ANSWER","fields":[]}',
        '{"decision":"ANSWER","fields":{},"decision":"ANSWER"}',
        '{"decision":"ANSWER","fields":{"value":NaN}}',
        '{"decision":"EXECUTE","fields":{}}',
        '{"decision":"REFUSE","fields":{"value":5}}',
        '{"decision":"ANSWER","fields":{},"extra":true}',
        '{"decision":"ANSWER","fields":{},"refusal":{"reason":"incorrect"}}',
    ],
)
def test_invalid_model_response_cannot_be_scored_as_pass(message: str) -> None:
    cases = (case("alpha"),)
    evidence = runner.execute(spec(cases), cases, StubModel({"alpha": message}), StubScorer())
    result = evidence.receipt.case_results[0]
    assert result.state == "INVALID_RESPONSE"
    assert result.verdict is None


@pytest.mark.parametrize("bad", [RuntimeError("private traceback"), {}, "x" * 17000])
def test_model_errors_are_counted_but_never_disclosed(bad: object) -> None:
    cases = (case("alpha"),)
    evidence = runner.execute(spec(cases), cases, StubModel({"alpha": bad}), StubScorer())
    result = evidence.receipt.case_results[0]
    assert result.state == "MODEL_ERROR" and result.verdict is None
    assert "private traceback" not in evidence.receipt.json()
    assert runner.verify_replay(evidence, cases, StubScorer()) == evidence.receipt


@pytest.mark.parametrize(
    "split,origin",
    [
        ("HIDDEN_FINAL", "DETERMINISTIC_SYNTHETIC"),
        ("FROZEN_VALIDATION", "DETERMINISTIC_SYNTHETIC"),
        ("PUBLIC_DEVELOPMENT", "EXPERT_AUTHORED"),
        ("PUBLIC_DEVELOPMENT", "SOURCE_BACKED"),
    ],
)
def test_protected_and_non_synthetic_cases_fail_closed(split: str, origin: str) -> None:
    with pytest.raises(ValueError, match="only synthetic"):
        runner.PublicSyntheticCase("a", "prompt", "{}", split, origin)


def test_suite_binding_checked_before_model_execution() -> None:
    cases = (case("alpha"),)
    model = StubModel({"alpha": raw()})
    with pytest.raises(ValueError, match="suite changed"):
        runner.execute(spec(cases), (case("alpha", "changed"),), model, StubScorer())
    assert model.requests == []


def test_sorted_unique_manifest_and_bounds() -> None:
    cases = (case("alpha"), case("beta"))
    for bad in ((cases[1], cases[0]), (cases[0], cases[0]), ()):
        with pytest.raises(ValueError):
            runner.suite_sha256(bad)
    with pytest.raises(ValueError):
        runner.PublicSyntheticCase("bad id", "p", "{}")
    with pytest.raises(ValueError):
        runner.PublicSyntheticCase("alpha", "p", '{"x":1,"x":2}')
    with pytest.raises(ValueError):
        runner.PublicSyntheticCase("alpha", "p" * 9000, "{}")


def test_model_and_scorer_version_bindings_fail_closed() -> None:
    cases = (case("alpha"),)
    s = spec(cases)
    model = StubModel({"alpha": raw()})
    with pytest.raises(ValueError, match="trusted scorer identity"):
        runner.execute(replace(s, scorer_sha256="2" * 64), cases, model, StubScorer())
    assert model.requests == []
    with pytest.raises(ValueError):
        replace(s, source_revision="unknown")
    with pytest.raises(ValueError):
        replace(s, seed=True)


def test_missing_duplicate_reordered_or_extra_rescore_responses_are_rejected() -> None:
    cases = (case("alpha"), case("beta"))
    s = spec(cases)
    for rs in (
        (),
        (runner.RawResponse("alpha", raw()),),
        (runner.RawResponse("alpha", raw()), runner.RawResponse("alpha", raw())),
        (runner.RawResponse("beta", raw()), runner.RawResponse("alpha", raw())),
        (
            runner.RawResponse("alpha", raw()),
            runner.RawResponse("beta", raw()),
            runner.RawResponse("extra", raw()),
        ),
    ):
        with pytest.raises(ValueError):
            runner.rescore(s, cases, rs, StubScorer())


def test_tampered_transcript_or_receipt_is_detected() -> None:
    cases = (case("alpha"),)
    ev = runner.execute(spec(cases), cases, StubModel({"alpha": raw()}), StubScorer())
    altered = replace(ev, responses=(runner.RawResponse("alpha", raw(999)),))
    with pytest.raises(ValueError, match="REPLAY_DIVERGENCE"):
        runner.verify_replay(altered, cases, StubScorer())
    altered_receipt = replace(ev.receipt, receipt_sha256="0" * 64)
    with pytest.raises(ValueError, match="REPLAY_DIVERGENCE"):
        runner.verify_replay(replace(ev, receipt=altered_receipt), cases, StubScorer())


def test_trusted_scorer_errors_never_become_passes() -> None:
    cases = (case("alpha"),)

    class BrokenScorer(StubScorer):
        def score(
            self, reference: Mapping[str, object], response: Mapping[str, object]
        ) -> runner.Score:
            raise RuntimeError("broken trusted scorer")

    with pytest.raises(RuntimeError):
        runner.execute(spec(cases), cases, StubModel({"alpha": raw()}), BrokenScorer())


def test_valid_but_incomplete_answer_is_scored_as_wrong() -> None:
    cases = (case("alpha"),)
    evidence = runner.execute(
        spec(cases),
        cases,
        StubModel({"alpha": '{"decision":"ANSWER","fields":{}}'}),
        StubScorer(),
    )
    assert evidence.receipt.case_results[0].state == "SCORED"
    assert evidence.receipt.case_results[0].verdict == "FAIL"


def test_refusal_is_scored_by_trusted_port_not_by_runner() -> None:
    cases = (case("alpha"),)
    result = runner.execute(
        spec(cases),
        cases,
        StubModel(
            {
                "alpha": (
                    '{"decision":"REFUSE","fields":{},'
                    '"refusal":{"reason":"NO_AUTHORITY"}}'
                )
            }
        ),
        StubScorer(),
    )
    assert result.receipt.case_results[0].state == "SCORED"
    assert result.receipt.case_results[0].verdict == "FAIL"
    assert result.receipt.qualification == runner.QUALIFICATION
