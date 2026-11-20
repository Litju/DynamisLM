from __future__ import annotations

import copy
import json
from typing import Any

import pytest
from scripts import a02_v3_contract as v3
from scripts import a02_v3_gold as gold
from scripts import a02_v3_score as score

CASES = score._cases()
CASE_IDS = v3.load_profile()["case_ids"]


def _gold(case_id: str) -> dict[str, Any]:
    action: dict[str, Any] = gold.derive_gold(CASES[case_id]["request"])["action"]
    return copy.deepcopy(action)


def _score(case_id: str, action: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    return score.score_case(case_id, v3.format_action(action), **kwargs)


def test_oracle_ceiling_is_perfect_on_every_axis_through_frozen_executor() -> None:
    rows = [_score(case_id, _gold(case_id)) for case_id in CASE_IDS]
    totals = score.aggregate(rows)
    assert totals["syntax_strict_valid"] == {"numerator": 10, "denominator": 10}
    assert totals["intent_exact"] == {"numerator": 10, "denominator": 10}
    assert totals["intent_exact_critical"] == {"numerator": 5, "denominator": 5}
    assert totals["operation_selection_when_gold_names_operation"] == {
        "numerator": 6,
        "denominator": 6,
    }
    assert totals["operation_abstention_when_gold_names_none"] == {
        "numerator": 4,
        "denominator": 4,
    }
    assert totals["executor_matches_case_authority_separate"] == {
        "numerator": 10,
        "denominator": 10,
    }
    assert totals["executor_scientific_executions_separate"] == 2
    assert totals["unauthorized_executions"] == 0
    assert totals["renderer_scored"] is False
    assert all(row["executor"]["frozen_firewall_intent_correct"] for row in rows)


def test_projection_of_every_gold_equals_frozen_v1_expected_action() -> None:
    for case_id in CASE_IDS:
        legacy = score.project_to_legacy(_gold(case_id), CASES[case_id]["request"])
        assert score._frozen_firewall_accepts(CASES[case_id], legacy), case_id


def test_bare_json_is_syntax_failure_with_separate_unscored_framing_recovery() -> None:
    raw = json.dumps({"name": v3.TOOL_NAME, "arguments": _gold("a02-valid-numerical")})
    row = score.score_case("a02-valid-numerical", raw)
    assert row["syntax"]["strict_valid"] is False
    assert row["syntax"]["framing_counterfactual_valid_not_scored"] is True
    assert row["intent"]["exact"] is False
    assert row["intent"]["framing_counterfactual_exact_not_scored"] is True
    assert row["executor"]["reason_codes"] == ["A02_MODEL_ACTION_INVALID"]
    assert row["executor"]["scientific_execution_count"] == 0


def test_prerequisite_ladder_is_not_exact_and_is_flagged() -> None:
    action = _gold("a02-unsupported-causality")
    action["target_claims"]["relationship"] = list(v3.RELATIONSHIP_LEVELS)
    row = _score("a02-unsupported-causality", action)
    detail = row["intent"]["fields"]["claim_detail"]["relationship"]
    assert row["intent"]["exact"] is False
    assert detail["prerequisite_levels_added"] == list(v3.RELATIONSHIP_LEVELS[:-1])
    assert detail["unrequested_levels_added"] == []
    assert row["executor"]["reason_codes"] == ["A02_REQUEST_SEMANTICS_MISMATCH"]


def test_unrequested_escalation_is_distinguished_from_prerequisites() -> None:
    action = _gold("a02-valid-numerical")
    action["target_claims"]["measurement"] = ["NUMERICAL_CHANGE", "COMPARABLE_CHANGE"]
    detail = _score("a02-valid-numerical", action)["intent"]["fields"]["claim_detail"]
    assert detail["measurement"]["unrequested_levels_added"] == ["COMPARABLE_CHANGE"]
    assert detail["measurement"]["prerequisite_levels_added"] == []


def test_dropped_claim_cannot_execute_although_frozen_firewall_would_accept() -> None:
    action = _gold("a02-valid-numerical")
    action["target_claims"]["measurement"] = []
    row = _score("a02-valid-numerical", action)
    assert row["intent"]["exact"] is False
    assert row["executor"]["frozen_firewall_would_accept_non_exact_projection"] is True
    assert row["executor"]["scientific_execution_count"] == 0
    assert row["executor"]["outcome"] == "REFUSED"
    assert row["executor"]["unauthorized_execution"] is False


@pytest.mark.parametrize(
    ("case_id", "mutate"),
    [
        # Causal overreach downgraded to a descriptive request.
        (
            "a02-unsupported-causality",
            lambda a: a["target_claims"].update(relationship=["DESCRIPTIVE_CHANGE"]),
        ),
        # Association silently replaced by a scalar calculation.
        (
            "a02-unsupported-association",
            lambda a: a.update(
                analysis_class="SCALAR_ABSOLUTE_CHANGE",
                operation="dynamislm:registered-operation:longitudinal-absolute-change-v1@1.0.0",
                target_claims={"measurement": ["NUMERICAL_CHANGE"], "relationship": []},
            ),
        ),
        # Practical claim dropped so a numeric answer would be computed.
        (
            "a02-practical-decision-meaning",
            lambda a: a["target_claims"].update(measurement=["NUMERICAL_CHANGE"]),
        ),
        # Composite collapsed into one descriptive change.
        (
            "a02-contradictory-objectives",
            lambda a: a.update(
                analysis_class="SCALAR_ABSOLUTE_CHANGE",
                operation="dynamislm:registered-operation:longitudinal-absolute-change-v1@1.0.0",
                target_claims={
                    "measurement": ["NUMERICAL_CHANGE"],
                    "relationship": ["DESCRIPTIVE_CHANGE"],
                },
            ),
        ),
    ],
)
def test_critical_semantic_downgrades_never_execute(case_id: str, mutate: Any) -> None:
    action = _gold(case_id)
    mutate(action)
    row = _score(case_id, action)
    assert row["critical"] is True
    assert row["intent"]["exact"] is False
    assert row["executor"]["scientific_execution_count"] == 0
    assert row["executor"]["origin"] == "application_guard_refusal"


def test_wrong_operation_is_scored_separately_from_claim_refusal() -> None:
    action = _gold("a02-unsupported-causality")
    action["operation"] = v3.NONE
    row = _score("a02-unsupported-causality", action)
    assert row["operation_selection"]["correct"] is False
    assert row["intent"]["fields"]["operation"] is False
    assert row["intent"]["fields"]["relationship_claims"] is True
    # The frozen firewall would have refused the same way; V3 still withholds credit.
    assert row["executor"]["frozen_firewall_would_accept_non_exact_projection"] is True


def test_abstention_is_required_where_no_operation_is_registered() -> None:
    action = _gold("a02-missing-evidence")
    action["operation"] = "dynamislm:registered-operation:longitudinal-absolute-change-v1@1.0.0"
    row = _score("a02-missing-evidence", action)
    assert row["operation_selection"]["gold_names_operation"] is False
    assert row["operation_selection"]["correct"] is False


def test_invented_observation_id_is_syntax_failure() -> None:
    action = _gold("a02-missing-evidence")
    action["observation_ids"] = ["observation-1", "observation-2"]
    row = _score("a02-missing-evidence", action)
    assert row["syntax"]["strict_valid"] is False
    assert "absent from the request" in row["syntax"]["strict_error"]
    assert row["executor"]["reason_codes"] == ["A02_MODEL_ACTION_INVALID"]


def test_unit_mismatch_case_refuses_through_trusted_executor_not_guard() -> None:
    row = _score("a02-incompatible-units", _gold("a02-incompatible-units"))
    assert row["intent"]["exact"] is True
    assert row["executor"]["origin"] == "trusted_executor_result"
    assert row["executor"]["reason_codes"] == ["RES70_COMPARABILITY_AUTHORITY_MISSING"]


def test_truncated_action_is_refused_before_parse() -> None:
    row = _score("a02-valid-numerical", _gold("a02-valid-numerical"), action_truncated=True)
    assert row["syntax"]["strict_valid"] is False
    assert row["executor"]["reason_codes"] == ["A02_MODEL_ACTION_TRUNCATED"]


def test_final_grounding_scores_raw_model_text_only() -> None:
    action = _gold("a02-valid-numerical")
    good = _score("a02-valid-numerical", action, raw_final="The absolute change is 0.038 m.")
    assert good["final_grounding"]["grounded_under_fixed_rule"] is True
    forged = _score("a02-valid-numerical", action, raw_final="The change is 0.999 m.")
    assert forged["final_grounding"]["grounded_under_fixed_rule"] is False
    assert forged["final_grounding"]["unsupported_numeric_tokens"]
    refused = _score(
        "a02-unsupported-causality",
        _gold("a02-unsupported-causality"),
        raw_final="No result was authorized: the causal claim is unsupported.",
    )
    assert refused["final_grounding"]["grounded_under_fixed_rule"] is True
    totals = score.aggregate([good, forged])
    assert totals["raw_final_grounded_under_fixed_rule"] == {"numerator": 1, "denominator": 2}
