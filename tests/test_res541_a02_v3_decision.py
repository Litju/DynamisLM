from __future__ import annotations

import copy
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from scripts import a02_v3_contract as v3
from scripts import a02_v3_decision as decision

PROTOCOL = decision.load_protocol()
FAST = copy.deepcopy(PROTOCOL)
FAST["decision_rule"]["statistics"]["resamples"] = 600
HELDOUT = decision.heldout_examples(PROTOCOL)
CRITICAL = set(PROTOCOL["decision_rule"]["critical_families"])
MODEL = PROTOCOL["candidate_model"]


def _wrong(example: dict[str, Any]) -> str:
    action = copy.deepcopy(example["gold_action"])
    action["analysis_class"] = (
        "SCALAR_ABSOLUTE_CHANGE"
        if action["analysis_class"] != "SCALAR_ABSOLUTE_CHANGE"
        else "RELIABILITY_RANDOM_ERROR_COMPARISON"
    )
    return v3.format_action(action)


def _records(arm: str, correct: Callable[[int, dict[str, Any]], bool]) -> list[dict[str, Any]]:
    return [
        decision.make_record(
            protocol=PROTOCOL,
            arm=arm,
            example=example,
            raw_output=example["target_text"] if correct(i, example) else _wrong(example),
            truncated=False,
            model=MODEL,
        )
        for i, example in enumerate(HELDOUT)
    ]


def _rate(rate: float, critical_rate: float | None = None, offset: int = 0) -> Any:
    def correct(i: int, example: dict[str, Any]) -> bool:
        target = (
            critical_rate if critical_rate is not None and example["family"] in CRITICAL else rate
        )
        return ((i + offset) * 37) % 100 < target * 100

    return correct


def _zero(zc: float, zu: float = 0.3, **kw: Any) -> dict[str, list[dict[str, Any]]]:
    return {
        "ZERO_SHOT_CONSTRAINED": _records("ZERO_SHOT_CONSTRAINED", _rate(zc, **kw)),
        "ZERO_SHOT_UNCONSTRAINED": _records("ZERO_SHOT_UNCONSTRAINED", _rate(zu)),
    }


# ---- evidence binding ---------------------------------------------------------------


def test_correctness_is_recomputed_from_raw_output_not_reported_fields() -> None:
    records = _records("ZERO_SHOT_CONSTRAINED", lambda i, e: True)
    records[0]["exact"] = False  # an unbound field is ignored
    rows = decision.bind_arm(PROTOCOL, "ZERO_SHOT_CONSTRAINED", records)
    assert all(row["exact"] for row in rows)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda r: r.pop(), "example set differs"),
        (lambda r: r.append(copy.deepcopy(r[0])), "duplicated"),
        (lambda r: r.__setitem__(slice(0, 2), [r[1], r[0]]), "preregistered order"),
        (lambda r: r[3].update(example_id="HELDOUT:5410:9999"), "example set differs"),
        (lambda r: r[3].update(family="RELIABILITY"), "family label differs"),
        (lambda r: r[3].update(request_sha256="0" * 64), "request differs"),
        (lambda r: r[3].update(raw_output=r[3]["raw_output"] + " "), "raw output hash differs"),
        (lambda r: r[3].update(model_revision="main"), "model_revision differs"),
        (lambda r: r[3].update(protocol_sha256="0" * 64), "protocol_sha256 differs"),
        (lambda r: r[3].update(contract_profile_sha256="0" * 64), "contract_profile_sha256"),
        (lambda r: r[3].update(arm="ZERO_SHOT_UNCONSTRAINED"), "arm differs"),
        (lambda r: r[3].update(decoder="native"), "decoder differs"),
        (lambda r: r[3].update(schema="X"), "schema differs"),
    ],
)
def test_substituted_mislabelled_duplicated_or_missing_evidence_is_rejected(
    mutate: Callable[[list[dict[str, Any]]], Any], message: str
) -> None:
    records = _records("ZERO_SHOT_CONSTRAINED", lambda i, e: True)
    mutate(records)
    with pytest.raises(decision.EvidenceError, match=message):
        decision.bind_arm(PROTOCOL, "ZERO_SHOT_CONSTRAINED", records)


def test_substituting_another_examples_request_and_output_is_rejected() -> None:
    records = _records("ZERO_SHOT_CONSTRAINED", lambda i, e: True)
    other = records[1]
    records[0] = {**other, "example_id": records[0]["example_id"], "family": records[0]["family"]}
    with pytest.raises(decision.EvidenceError, match="request differs"):
        decision.bind_arm(PROTOCOL, "ZERO_SHOT_CONSTRAINED", records)


def test_switched_arm_evidence_is_rejected() -> None:
    evidence = _zero(0.5)
    swapped = {
        "ZERO_SHOT_CONSTRAINED": evidence["ZERO_SHOT_UNCONSTRAINED"],
        "ZERO_SHOT_UNCONSTRAINED": evidence["ZERO_SHOT_CONSTRAINED"],
    }
    with pytest.raises(decision.EvidenceError, match="arm differs"):
        decision.decide(swapped, FAST)


def test_invalid_constrained_output_is_a_decoder_fault_not_a_miss() -> None:
    records = _records("ZERO_SHOT_CONSTRAINED", lambda i, e: True)
    raw = "not a tool call"
    records[0].update(raw_output=raw, raw_output_sha256=v3.sha256(raw.encode()))
    with pytest.raises(decision.EvidenceError, match="constrained output is invalid"):
        decision.bind_arm(PROTOCOL, "ZERO_SHOT_CONSTRAINED", records)


def test_invalid_and_truncated_native_outputs_count_as_misses() -> None:
    records = _records("ZERO_SHOT_UNCONSTRAINED", lambda i, e: True)
    raw = json.dumps({"name": v3.TOOL_NAME, "arguments": HELDOUT[0]["gold_action"]})
    records[0].update(raw_output=raw, raw_output_sha256=v3.sha256(raw.encode()))
    records[1]["truncated"] = True
    rows = decision.bind_arm(PROTOCOL, "ZERO_SHOT_UNCONSTRAINED", records)
    assert rows[0]["strict_valid"] is False and rows[0]["exact"] is False
    assert rows[1]["strict_valid"] is False and rows[1]["exact"] is False
    assert all(row["exact"] for row in rows[2:])


def test_both_zero_shot_arms_are_required() -> None:
    with pytest.raises(decision.EvidenceError, match="both zero-shot arms"):
        decision.decide({"ZERO_SHOT_CONSTRAINED": _zero(0.9)["ZERO_SHOT_CONSTRAINED"]}, FAST)


# ---- two-stage rule -------------------------------------------------------------------


def test_stage_1_adopts_repaired_contract_and_reports_uncredited_gaps() -> None:
    result = decision.decide(_zero(0.95, zu=0.40), FAST)
    assert result["stage"] == 1
    assert result["decision"] == "ADOPT_REPAIRED_CONTRACT_WITH_CONSTRAINED_DECODING"
    assert result["strict_parse_valid_gap"] == 0.0  # both arms emitted valid syntax here
    assert result["decoder_condition_exact_gap"]["value"] > 0.5
    assert "not syntax alone" in result["decoder_condition_exact_gap"]["interpretation"]
    assert "syntax_attributable_gap_not_credited" not in result
    assert result["claim_ceiling"] == PROTOCOL["claim_ceiling"]


def test_stage_1_failure_is_only_eligibility_never_benefit() -> None:
    result = decision.decide(_zero(0.5), FAST)
    assert result["stage"] == 1
    assert result["decision"] == "ELIGIBLE_FOR_ADAPTATION_EXPERIMENT"
    assert "adaptation_checks" not in result


def test_weak_critical_families_block_stage_1_adoption() -> None:
    result = decision.decide(_zero(0.99, critical_rate=0.6), FAST)
    assert result["decision"] == "ELIGIBLE_FOR_ADAPTATION_EXPERIMENT"


def test_stage_2_requires_the_constrained_adapted_arm() -> None:
    evidence = {
        **_zero(0.5),
        "ADAPTED_UNCONSTRAINED": _records("ADAPTED_UNCONSTRAINED", _rate(0.9)),
    }
    with pytest.raises(decision.EvidenceError, match="constrained adapted arm"):
        decision.decide(evidence, FAST)


def test_stage_2_demonstrates_benefit_only_with_observed_adapted_gain() -> None:
    evidence = {**_zero(0.5), "ADAPTED_CONSTRAINED": _records("ADAPTED_CONSTRAINED", _rate(0.92))}
    result = decision.decide(evidence, FAST)
    assert result["stage"] == 2
    assert result["decision"] == "ADAPTATION_BENEFIT_DEMONSTRATED"
    bounds = result["gain_lower_bounds"]
    assert bounds["governing"] == min(bounds["item"], bounds["template_clustered"]) > 0


def test_small_gain_is_not_demonstrated() -> None:
    evidence = {**_zero(0.8), "ADAPTED_CONSTRAINED": _records("ADAPTED_CONSTRAINED", _rate(0.85))}
    result = decision.decide(evidence, FAST)
    assert result["adaptation_checks"]["minimum_gain"] is False
    assert result["decision"] == "ADAPTATION_BENEFIT_NOT_DEMONSTRATED"


def test_gain_bought_with_critical_regression_is_rejected() -> None:
    evidence = {
        **_zero(0.5, critical_rate=0.7),
        "ADAPTED_CONSTRAINED": _records("ADAPTED_CONSTRAINED", _rate(0.99, critical_rate=0.4)),
    }
    result = decision.decide(evidence, FAST)
    assert result["adaptation_checks"]["critical_not_worse"] is False
    assert result["family_regressions"]
    assert result["decision"] != "ADAPTATION_BENEFIT_DEMONSTRATED"


def test_both_arms_weak_escalates_to_stronger_model_comparison() -> None:
    evidence = {**_zero(0.3), "ADAPTED_CONSTRAINED": _records("ADAPTED_CONSTRAINED", _rate(0.45))}
    assert decision.decide(evidence, FAST)["decision"] == "ESCALATE_TO_STRONGER_MODEL_COMPARISON"


# ---- statistics -----------------------------------------------------------------------


def test_template_clustered_bound_is_more_conservative_under_template_correlation() -> None:
    clusters = [f"t{i // 20}" for i in range(280)]
    # The adapted arm wins only on whole templates: strongly template-correlated outcomes.
    adapted = [int(c[1:]) % 2 == 0 for c in clusters]
    base = [False] * 280
    item = decision.paired_bootstrap_lower(adapted, base, resamples=2000, seed=1, alpha=0.05)
    clustered = decision.clustered_bootstrap_lower(
        adapted, base, clusters, resamples=2000, seed=1, alpha=0.05
    )
    assert clustered < item


def test_bootstrap_bounds_are_deterministic() -> None:
    a = [True] * 60 + [False] * 40
    b = [True] * 40 + [False] * 60
    clusters = [f"c{i % 10}" for i in range(100)]
    one = decision.clustered_bootstrap_lower(a, b, clusters, resamples=500, seed=3, alpha=0.05)
    assert one == decision.clustered_bootstrap_lower(
        a, b, clusters, resamples=500, seed=3, alpha=0.05
    )
    assert decision.paired_bootstrap_lower(a, a, resamples=300, seed=1, alpha=0.05) == 0


def test_wilson_interval_matches_reference_values() -> None:
    low, high = decision.wilson(18, 20)
    assert low == pytest.approx(0.6990, abs=1e-3) and high == pytest.approx(0.9721, abs=1e-3)
    assert decision.wilson(0, 0) == (0.0, 1.0)


def test_report_discloses_template_cluster_count_and_per_family_intervals() -> None:
    result = decision.decide(_zero(0.5), FAST)
    assert result["template_clusters"] < len(HELDOUT)
    family = result["ZERO_SHOT_CONSTRAINED"]["family"]
    assert len(family) == 14 and all(v["n"] == 20 for v in family.values())


def test_cluster_design_reports_real_heldout_cluster_structure() -> None:
    design = decision.cluster_design(
        [{"template": e["template_id"]} for e in HELDOUT]  # same key the bound rows carry
    )
    assert design["items"] == 280 and design["template_clusters"] == 15
    assert 1 <= design["effective_clusters"] <= design["template_clusters"]
    assert design["min_cluster_items"] < design["max_cluster_items"]
    assert design["effective_clusters"] < design["template_clusters"]  # unequal sizes cost clusters


def test_cluster_design_effective_count_equals_cluster_count_for_equal_sizes() -> None:
    rows = [{"template": f"t{i % 7}"} for i in range(70)]
    assert decision.cluster_design(rows)["effective_clusters"] == pytest.approx(7.0)
    assert decision.cluster_design([{"template": "only"}] * 5)["effective_clusters"] == 1.0


def test_report_discloses_single_arm_bounds_without_changing_the_decision() -> None:
    result = decision.decide(_zero(0.95), FAST)
    assert result["decision"] == "ADOPT_REPAIRED_CONTRACT_WITH_CONSTRAINED_DECODING"
    for arm in decision.ZERO_SHOT_ARMS:
        bounds = result[arm]["exact_lower_bounds"]
        assert bounds["governing"] == min(bounds["item"], bounds["template_clustered"])
        assert bounds["governing"] <= result[arm]["exact"]
    assert result["cluster_design"]["template_clusters"] == result["template_clusters"]
    assert "point estimates" in result["sufficiency_basis"]


def test_template_correlated_success_shows_a_clustered_bound_below_the_item_bound() -> None:
    template = {e["template_id"]: i for i, e in enumerate(HELDOUT)}
    winners = {t for n, t in enumerate(sorted(template)) if n % 6 != 0}  # 12 of 15 templates win
    zc = _records("ZERO_SHOT_CONSTRAINED", lambda _i, e: e["template_id"] in winners)
    zu = _records("ZERO_SHOT_UNCONSTRAINED", _rate(0.3))
    result = decision.decide({"ZERO_SHOT_CONSTRAINED": zc, "ZERO_SHOT_UNCONSTRAINED": zu}, FAST)
    bounds = result["ZERO_SHOT_CONSTRAINED"]["exact_lower_bounds"]
    assert bounds["template_clustered"] < bounds["item"]
    # A decision that rests on a point estimate must not hide how weak the bound is.
    assert bounds["governing"] < result["ZERO_SHOT_CONSTRAINED"]["exact"] - 0.05


# ---- protocol -------------------------------------------------------------------------


def test_protocol_is_preregistered_unauthorized_and_amended_before_observations() -> None:
    assert PROTOCOL["status"] == "PREREGISTERED_NOT_AUTHORIZED"
    assert not any(PROTOCOL["authorization"][k] for k in ("gpu", "training", "session_005"))
    assert all(a["recorded_before_model_observations"] for a in PROTOCOL["amendments"])
    assert PROTOCOL["decision_rule"]["statistics"]["resamples"] == 10000


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        (("data", "heldout_evaluation", "manifest_sha256"), "0" * 64, "manifest differs"),
        (("data", "training", "seed"), 542, "manifest differs"),
        (("contract_profile_sha256",), "0" * 64, "not bound"),
        (("schema",), "X", "schema differs"),
    ],
)
def test_protocol_tampering_is_detected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, path: tuple[str, ...], value: Any, message: str
) -> None:
    protocol = copy.deepcopy(PROTOCOL)
    target = protocol
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    altered = tmp_path / "protocol.json"
    altered.write_text(json.dumps(protocol))
    monkeypatch.setattr(decision, "PROTOCOL_PATH", altered)
    with pytest.raises(ValueError, match=message):
        decision.load_protocol()


def test_compute_estimate_matches_its_preregistered_inputs() -> None:
    estimate = PROTOCOL["compute_estimate"]
    assert decision.estimate_zero_shot_seconds(**estimate["inputs"]) == estimate["estimate"]
    assert estimate["estimate"]["total_seconds"] > 900
    with pytest.raises(ValueError, match="cached work"):
        decision.estimate_zero_shot_seconds(**{**estimate["inputs"], "cached_fed_tokens": 10})
