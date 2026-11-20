from typing import Any

import pytest
from scripts.research_cli import demo


def test_synthetic_absolute_change_uses_registered_result() -> None:
    receipt, code = demo("absolute-change")
    assert code == 0
    result: Any = receipt["result"]
    decision: Any = receipt["admission"]
    assert receipt["proposal_origin"] == "SCRIPTED"
    assert result["estimates"][0]["value"] == 0.125
    assert result["estimates"][0]["unit"] == "m"
    assert decision["execution_authorized"] is decision["operation_executed"] is True
    assert decision["claim_status"] == "AUTHORIZED"
    assert demo("absolute-change") == (receipt, code)


@pytest.mark.parametrize(
    ("scenario", "reason"),
    [
        ("missing-evidence", "V3_SOURCE_PROVENANCE_UNRESOLVED"),
        ("unsupported-operation", "COMPUTATION_NOT_REGISTERED"),
        ("causal-escalation", "RES70_UNSUPPORTED_CAUSAL_CLAIM"),
        ("practical-escalation", "RES70_UNSUPPORTED_CLAIM_ESCALATION"),
    ],
)
def test_synthetic_refusal_never_dispatches(scenario: str, reason: str) -> None:
    receipt, code = demo(scenario)
    decision: Any = receipt["admission"]
    assert code == 2
    assert reason in decision["reason_codes"]
    assert decision["outcome"] == "REFUSED"
    assert decision["execution_authorized"] is decision["operation_executed"] is False
    assert receipt["result"] is None
