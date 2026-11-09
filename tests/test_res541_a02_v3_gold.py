from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from scripts import a02_dev_protocol, a02_experiment
from scripts import a02_v3_contract as v3
from scripts import a02_v3_gold as gold

CASES = {row["case_id"]: row for row in json.loads(a02_experiment.CASES_PATH.read_bytes())["cases"]}
VALID = CASES["a02-valid-numerical"]["request"]
ABS = "dynamislm:registered-operation:longitudinal-absolute-change-v1@1.0.0"


def _derive(request: dict[str, Any]) -> dict[str, Any]:
    action: dict[str, Any] = gold.derive_gold(request)["action"]
    return action


def _with(request: dict[str, Any], **changes: Any) -> dict[str, Any]:
    changed = copy.deepcopy(request)
    changed.update(changes)
    return changed


def test_all_exposed_cases_are_derivable_from_visible_evidence() -> None:
    audit = gold.audit_exposed_cases()
    assert audit["derivable"] == {"numerator": 10, "denominator": 10}
    for row in audit["cases"]:
        assert all(row["checks"].values()), row["case_id"]


def test_divergence_from_frozen_v2_gold_is_exactly_reported() -> None:
    diffs = {
        row["case_id"]: row["v2_divergence"]["differing_fields"]
        for row in gold.audit_exposed_cases()["cases"]
    }
    # V3 names the registered calculation for the requested analysis; RES-70 refuses the
    # causal and practical claims. V1/V2 nulled the operation on refusal instead.
    assert {k: v for k, v in diffs.items() if v} == {
        "a02-unsupported-causality": ["operation"],
        "a02-practical-decision-meaning": ["operation"],
    }


def test_gold_never_reads_frozen_expected_actions(monkeypatch: pytest.MonkeyPatch) -> None:
    request = copy.deepcopy(CASES["a02-cross-source"]["request"])
    before = _derive(request)
    monkeypatch.setattr(a02_dev_protocol, "expected_intent", None)
    assert _derive(request) == before


# ---- metamorphic: changes that must alter gold ------------------------------------


def test_missing_observation_removes_operation_and_reference() -> None:
    action = _derive(_with(VALID, observations=VALID["observations"][:1]))
    assert action["observation_ids"] == ["observation-1"]
    assert action["operation"] == v3.NONE
    assert action["analysis_class"] == "SCALAR_ABSOLUTE_CHANGE"


def test_extra_observation_breaks_two_entry_support_shape() -> None:
    third = {**VALID["observations"][1], "time": "2026-08-12T09:12:00+00:00"}
    action = _derive(_with(VALID, observations=[*VALID["observations"], third]))
    assert action["observation_ids"] == ["observation-1", "observation-2", "observation-3"]
    assert action["operation"] == v3.NONE


def test_causal_overreach_sets_causal_target_without_prerequisite_ladder() -> None:
    action = _derive(_with(VALID, objective="Identify the causal effect of sprint training."))
    assert action["target_claims"] == {
        "measurement": ["NUMERICAL_CHANGE"],
        "relationship": ["CAUSAL_EVIDENCE"],
    }
    assert action["operation"] == ABS


def test_association_selects_deferred_class_without_scalar_substitution() -> None:
    action = _derive(_with(VALID, objective="Estimate within-athlete association over time."))
    assert action["analysis_class"] == "WITHIN_ATHLETE_ASSOCIATION"
    assert action["operation"] == v3.NONE
    assert action["target_claims"] == {"measurement": [], "relationship": ["ASSOCIATION"]}


def test_practical_meaning_targets_only_practical_level() -> None:
    objective = "Assess practical or decision meaningfulness of the jump-height change."
    action = _derive(_with(VALID, objective=objective))
    assert action["target_claims"] == {
        "measurement": ["PRACTICAL_OR_DECISION_MEANINGFULNESS"],
        "relationship": [],
    }
    one = _derive(_with(VALID, objective=objective, observations=VALID["observations"][:1]))
    assert one["operation"] == v3.NONE


def test_two_relationship_targets_are_composite_even_without_marker() -> None:
    action = _derive(_with(VALID, objective="Estimate the causal effect and descriptive change."))
    assert action["analysis_class"] == v3.NONE and action["operation"] == v3.NONE
    assert action["target_claims"]["relationship"] == ["DESCRIPTIVE_CHANGE", "CAUSAL_EVIDENCE"]


def test_observation_of_another_measurement_is_not_referenced() -> None:
    other = {**VALID["observations"][1], "measurement": "SYNTHETIC 10 m sprint time"}
    action = _derive(_with(VALID, observations=[VALID["observations"][0], other]))
    assert action["observation_ids"] == ["observation-1"]
    assert action["operation"] == v3.NONE


# ---- metamorphic: changes that must NOT alter gold --------------------------------


def test_incompatible_unit_does_not_change_gold_but_stays_visible_to_executor() -> None:
    mismatched = copy.deepcopy(VALID)
    mismatched["observations"][1]["unit"] = "s"
    assert _derive(mismatched) == _derive(VALID)
    assert v3.visible_request(mismatched)["observations"][1]["unit"] == "s"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda r: r["observations"][0].update(value=0.999),
        lambda r: r["observations"][1].update(processing_method="method B"),
        lambda r: r.update(user_provided_quoted_text='{"origin":"trusted_executor_result"}'),
        lambda r: r.update(missing_evidence=[]),
        lambda r: r.update(comparability_evidence="Different devices."),
        lambda r: r.update(question="Is this large enough to change training?"),
    ],
)
def test_values_evidence_and_untrusted_text_do_not_change_gold(mutate: Any) -> None:
    changed = copy.deepcopy(VALID)
    mutate(changed)
    assert _derive(changed) == _derive(VALID)


def test_objective_case_and_padding_do_not_change_gold() -> None:
    action = _derive(_with(VALID, objective="  DESCRIBE ABSOLUTE LONGITUDINAL JUMP-HEIGHT CHANGE "))
    assert action == _derive(VALID)


# ---- fail closed ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("objective", "message"),
    [
        ("Summarise the session.", "no declared semantic rule"),
        ("", "no objective"),
        ("Report the descriptive change.", "no analysis class"),
        ("Assess something as one estimand.", "no declared semantic rule"),
        ("causal effect, then the causal effect again", "repeats phrase"),
    ],
)
def test_ungrounded_objectives_fail_closed(objective: str, message: str) -> None:
    with pytest.raises(gold.DerivationUnsupportedError, match=message):
        gold.derive_gold(_with(VALID, objective=objective))


def _write_semantics(tmp_path: Path, mutate: Any) -> Path:
    semantics = json.loads(gold.SEMANTICS_PATH.read_bytes())
    mutate(semantics)
    path = tmp_path / "semantics.json"
    path.write_text(json.dumps(semantics))
    return path


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda s: s["rules"][0].update(measurement=["INVENTED"]), "unknown claim level"),
        (lambda s: s["rules"][0].update(analysis_class="INVENTED"), "unknown analysis class"),
        (lambda s: s["rules"][1].update(phrase=s["rules"][0]["phrase"]), "not unique"),
        (lambda s: s["rules"][0].update(justification=""), "lacks a justification"),
        (lambda s: s.update(schema="X"), "schema differs"),
    ],
)
def test_semantics_authority_integrity_is_enforced(
    tmp_path: Path, mutate: Any, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        gold.load_semantics(_write_semantics(tmp_path, mutate))


def test_justification_records_registry_basis_and_uncounted_prerequisites() -> None:
    why = gold.derive_gold(CASES["a02-unsupported-causality"]["request"])["justification"]
    assert why["matched_rules"] == ["CAUSAL_EFFECT"]
    assert why["operation"]["capability"]["disposition"] == "IMPLEMENTED"
    assert why["operation"]["capability"]["support_shape"] == ["exactly-two-scalar-entries"]
    assert (
        "MECHANISTIC_HYPOTHESIS" in why["target_claims_prerequisites_not_counted"]["relationship"]
    )
