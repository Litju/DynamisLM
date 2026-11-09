from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from scripts import a02_v3_decision as decision
from scripts import a02_v3_synthetic as synthetic

PROTOCOL = decision.load_protocol()
HELDOUT = synthetic.generate(
    "HELDOUT",
    PROTOCOL["data"]["heldout_evaluation"]["seed"],
    PROTOCOL["data"]["heldout_evaluation"]["count"],
)
CRITICAL = set(PROTOCOL["decision_rule"]["critical_families"])


def _rows(
    rate: float, *, critical_rate: float | None = None, offset: int = 0
) -> list[dict[str, Any]]:
    """Deterministic rows: example i is exact when its rank falls under the rate."""
    rows = []
    for i, example in enumerate(HELDOUT):
        target = (
            critical_rate if critical_rate is not None and example["family"] in CRITICAL else rate
        )
        rank = ((i + offset) * 37) % 100
        rows.append(
            {
                "example": f"{example['split']}:{example['seed']}:{example['index']}",
                "family": example["family"],
                "exact": rank < target * 100,
            }
        )
    return rows


def test_protocol_is_preregistered_unauthorized_and_bound_to_regenerated_splits() -> None:
    assert PROTOCOL["status"] == "PREREGISTERED_NOT_AUTHORIZED"
    assert not any(PROTOCOL["authorization"][k] for k in ("gpu", "training", "session_005"))
    assert PROTOCOL["data"]["exposed_development_cases"]["role"].startswith(
        "DEVELOPMENT_DIAGNOSTIC_ONLY"
    )


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


def test_strong_zero_shot_adopts_repaired_contract_without_training() -> None:
    result = decision.decide(
        {"ZERO_SHOT_CONSTRAINED": _rows(0.95), "ZERO_SHOT_UNCONSTRAINED": _rows(0.40)}, PROTOCOL
    )
    assert result["decision"] == "ADOPT_REPAIRED_CONTRACT_WITH_CONSTRAINED_DECODING"
    assert result["syntax_attributable_gap_not_credited"] > 0.5


def test_weak_zero_shot_requires_the_adaptation_arm_before_any_choice() -> None:
    result = decision.decide({"ZERO_SHOT_CONSTRAINED": _rows(0.50)}, PROTOCOL)
    assert result["decision"] == "ADAPTATION_ARM_REQUIRED"


def test_strong_zero_shot_with_weak_critical_families_is_not_sufficient() -> None:
    result = decision.decide({"ZERO_SHOT_CONSTRAINED": _rows(0.99, critical_rate=0.60)}, PROTOCOL)
    assert result["decision"] == "ADAPTATION_ARM_REQUIRED"


def test_clear_adapted_gain_is_justified() -> None:
    result = decision.decide(
        {"ZERO_SHOT_CONSTRAINED": _rows(0.50), "ADAPTED_CONSTRAINED": _rows(0.92)}, PROTOCOL
    )
    assert result["decision"] == "ADAPTATION_JUSTIFIED"
    assert all(result["adaptation_checks"].values())
    assert result["gain_ci_lower"] > 0


def test_small_gain_is_not_justified() -> None:
    result = decision.decide(
        {"ZERO_SHOT_CONSTRAINED": _rows(0.80), "ADAPTED_CONSTRAINED": _rows(0.85)}, PROTOCOL
    )
    assert result["adaptation_checks"]["minimum_gain"] is False
    assert result["decision"] == "INCONCLUSIVE_NO_ADOPTION"


def test_gain_bought_with_a_critical_regression_is_rejected() -> None:
    result = decision.decide(
        {
            "ZERO_SHOT_CONSTRAINED": _rows(0.50, critical_rate=0.70),
            "ADAPTED_CONSTRAINED": _rows(0.99, critical_rate=0.40),
        },
        PROTOCOL,
    )
    assert result["adaptation_checks"]["critical_not_worse"] is False
    assert result["family_regressions"]
    assert result["decision"] != "ADAPTATION_JUSTIFIED"


def test_both_arms_weak_escalates_to_stronger_model_comparison() -> None:
    result = decision.decide(
        {"ZERO_SHOT_CONSTRAINED": _rows(0.30), "ADAPTED_CONSTRAINED": _rows(0.45)}, PROTOCOL
    )
    assert result["decision"] == "ESCALATE_TO_STRONGER_MODEL_COMPARISON"


def test_decision_requires_identical_complete_held_out_examples() -> None:
    rows = _rows(0.5)
    with pytest.raises(ValueError, match="identical held-out examples"):
        decision.decide(
            {"ZERO_SHOT_CONSTRAINED": rows, "ADAPTED_CONSTRAINED": list(reversed(rows))}, PROTOCOL
        )
    with pytest.raises(ValueError, match="complete preregistered"):
        decision.decide({"ZERO_SHOT_CONSTRAINED": rows[:-1]}, PROTOCOL)
    with pytest.raises(ValueError, match="identical held-out examples"):
        decision.decide({"ZERO_SHOT_CONSTRAINED": rows, "EXPOSED_TEN": rows}, PROTOCOL)


def test_bootstrap_lower_bound_is_deterministic_and_ordered() -> None:
    a = [True] * 60 + [False] * 40
    b = [True] * 40 + [False] * 60
    lower = decision._paired_bootstrap_lower(a, b, resamples=2000, seed=1, alpha=0.05)
    assert lower == decision._paired_bootstrap_lower(a, b, resamples=2000, seed=1, alpha=0.05)
    assert 0 < lower < 0.2
    assert decision._paired_bootstrap_lower(a, a, resamples=500, seed=1, alpha=0.05) == 0


def test_compute_estimate_matches_its_preregistered_inputs() -> None:
    estimate = PROTOCOL["compute_estimate"]
    assert decision.estimate_zero_shot_seconds(**estimate["inputs"]) == estimate["estimate"]
    assert estimate["estimate"]["total_seconds"] > 900
    with pytest.raises(ValueError, match="cached work"):
        decision.estimate_zero_shot_seconds(**{**estimate["inputs"], "cached_fed_tokens": 10})
