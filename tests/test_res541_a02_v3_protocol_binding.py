"""The V3 protocol's identity claims must equal what the code actually enforces (RES-541)."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from scripts import a02_v3_decision as decision
from scripts import a02_v3_execution as execution
from scripts import a02_v3_worker as worker

PROTOCOL = decision.load_protocol()
EXECUTION = PROTOCOL["execution"]
PREFLIGHT = {
    "schema": "RES541_A02_V3_CPU_PREFLIGHT_V1",
    "max_constrained_scorer_calls": 69,
    "max_prompt_tokens": 1508,
    "gpu_allocated": False,
    "weights_loaded": False,
}


def _altered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, path: tuple[str, ...], value: Any
) -> None:
    protocol = copy.deepcopy(PROTOCOL)
    target = protocol
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    altered = tmp_path / "protocol.json"
    altered.write_text(json.dumps(protocol))
    monkeypatch.setattr(decision, "PROTOCOL_PATH", altered)


def test_no_authorization_of_any_kind_is_granted() -> None:
    assert not any(v for k, v in PROTOCOL["authorization"].items() if isinstance(v, bool))
    assert PROTOCOL["authorization"]["campaign_allowance"] is False
    assert EXECUTION["campaign_allowance"]["exists"] is False
    assert PROTOCOL["status"] == "PREREGISTERED_NOT_AUTHORIZED"


def test_work_list_pin_equals_the_generated_ordered_list() -> None:
    items = worker.work_items(PROTOCOL)
    pinned = EXECUTION["work_list"]
    assert (len(items), worker.work_list_sha256(items)) == (pinned["items"], pinned["sha256"])
    assert pinned["items"] == 581


@pytest.mark.parametrize(
    "value", [{"items": 580}, {"sha256": "0" * 64}], ids=["count", "ordered-list-hash"]
)
def test_a_changed_work_list_pin_is_refused(value: dict[str, Any]) -> None:
    altered = copy.deepcopy(PROTOCOL)
    altered["execution"]["work_list"].update(value)
    with pytest.raises(worker.CheckpointError, match="preregistered ordered list"):
        worker.work_items(altered)


def test_a_reordered_work_list_would_change_the_pinned_hash() -> None:
    items = worker.work_items(PROTOCOL)
    swapped = [items[0], items[2], items[1], *items[3:]]
    assert worker.work_list_sha256(swapped) != EXECUTION["work_list"]["sha256"]


def test_bound_identities_equal_the_code_constants() -> None:
    bound = EXECUTION["bound_identities"]
    assert bound["arm_decoders"] == decision.ARM_DECODER
    assert bound["record_schema"] == decision.RECORD_SCHEMA
    assert bound["checkpoint_schema"] == worker.CHECKPOINT_SCHEMA
    assert bound["exposed_record_schema"] == worker.EXPOSED_SCHEMA
    assert bound["qualification_schema"] == worker.QUALIFICATION_SCHEMA
    assert bound["hash_chain_genesis"] == worker.GENESIS
    assert bound["contract_profile_sha256"] == PROTOCOL["contract_profile_sha256"]


def test_calibration_selection_is_pinned_and_disjoint_from_protected_data() -> None:
    declared = PROTOCOL["data"]["calibration"]
    assert declared["indices"] == list(worker.CALIBRATION_INDICES)
    assert declared["split"] == PROTOCOL["data"]["training"]["split"] == "TRAIN"
    altered = copy.deepcopy(PROTOCOL)
    altered["data"]["calibration"]["indices"] = [0, 1, 2]
    with pytest.raises(worker.CheckpointError, match="preregistered selection"):
        worker.calibration_examples(altered)


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        (("data", "generated_semantics", "sha256"), "0" * 64, "generated-phrasing semantics"),
        (
            ("data", "generated_semantics", "path"),
            "experiments/a02/objective-semantics-v3.json",
            "generated-phrasing semantics",
        ),
    ],
)
def test_generated_semantics_pin_is_enforced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, path: tuple[str, ...], value: Any, message: str
) -> None:
    _altered(tmp_path, monkeypatch, path, value)
    with pytest.raises(ValueError, match=message):
        decision.load_protocol()


def test_session_budget_equals_the_plan_code_and_fits_the_maximum_nine_sessions() -> None:
    plan = execution.build_plan(PROTOCOL, PREFLIGHT, execution.RuntimeBounds())
    budget = EXECUTION["session_budget"]
    assert budget["work_items"] == plan["work_items"] == 581
    assert budget["packed_sessions"] == plan["packed_sessions"] == 9
    assert budget["sessions"] == plan["session_count"] == 10
    assert budget["reserve_sessions"] == plan["reserve_sessions"] == 1
    assert budget["robustness"] == plan["robustness"]
    assert budget["scorer_call_bound"] == plan["scorer_call_bound"]
    assert budget["scorer_call_bound"]["used_for_pricing"] == 73
    assert budget["item_cost_bounds_seconds"] == plan["item_cost_bounds_seconds"]
    assert budget["generation_seconds_per_session"] == plan["generation_seconds_per_session"]
    assert budget["worst_case_generation_seconds"] == plan["worst_case_generation_seconds"]
    for key in (
        "per_session_cap",
        "cumulative_cap",
        "expected_at_observed_t4_rate",
        "expected_if_every_allowed_session_runs",
    ):
        assert budget["compute_units"][key] == plan["compute_units"][key]
    assert budget["capacity_seconds"] == 10 * plan["generation_seconds_per_session"]
    assert budget["slack_seconds"] == pytest.approx(
        budget["capacity_seconds"] - budget["worst_case_generation_seconds"], abs=0.1
    )
    assert budget["slack_seconds"] >= plan["generation_seconds_per_session"]
    assert (
        budget["compute_units"]["expected_at_observed_t4_rate"]
        < (budget["compute_units"]["cumulative_cap"])
    )


def test_allowance_contract_fields_equal_the_code() -> None:
    allowance = EXECUTION["campaign_allowance"]
    assert allowance["schema"] == execution.ALLOWANCE_SCHEMA
    assert allowance["fields"] == sorted(execution.ALLOWANCE_KEYS)


def test_pinned_cluster_design_equals_the_real_heldout_design() -> None:
    design = decision.cluster_design(
        [{"template": e["template_id"]} for e in decision.heldout_examples(PROTOCOL)]
    )
    pinned = PROTOCOL["decision_rule"]["statistics"]["cluster_design_heldout"]
    assert pinned["items"] == design["items"] == 280
    assert pinned["template_clusters"] == design["template_clusters"] == 15
    assert pinned["effective_clusters"] == pytest.approx(design["effective_clusters"], abs=0.01)
    assert pinned["effective_clusters"] < 9


def test_every_amendment_precedes_observations_and_the_caveats_are_disclosed() -> None:
    assert all(a["recorded_before_model_observations"] for a in PROTOCOL["amendments"])
    limits = " ".join(EXECUTION["qualification_limits"])
    for phrase in ("tiny randomly initialised", "once, in session 1", "unverified"):
        assert phrase in limits
    ceiling = PROTOCOL["claim_ceiling"]
    for phrase in ("15 template clusters", "unverified", "tiny random model"):
        assert phrase in ceiling
    assert "lower bound" in PROTOCOL["decision_rule"]["statistics"]["sufficiency_basis"]


def test_amendment_p5_preserves_the_original_rule_and_precedes_observations() -> None:
    amendment = next(a for a in PROTOCOL["amendments"] if a["id"].startswith("P5-"))
    assert amendment["recorded_before_model_observations"] is True
    old = amendment["supersedes"]
    assert (
        old["zero_shot_sufficient"]["exact"],
        old["zero_shot_sufficient"]["critical_exact"],
    ) == (
        0.9,
        0.9,
    )
    assert "lower_bound" not in old["zero_shot_sufficient"]  # the original is kept verbatim
    assert old["stage_1_otherwise"] == "ELIGIBLE_FOR_ADAPTATION_EXPERIMENT"
    assert len(old["protocol_sha256_before_amendment"]) == 64
    rule = PROTOCOL["decision_rule"]["zero_shot_sufficient"]
    assert rule["thresholds_frozen"].startswith("No threshold may be changed after")
    assert (
        PROTOCOL["decision_rule"]["stage_1_otherwise"] == "ADAPTATION_STUDY_ELIGIBLE_NOT_AUTHORIZED"
    )
    assert rule["inconclusive_decision"] == "INCONCLUSIVE_INSUFFICIENT_INDEPENDENT_EVIDENCE"
