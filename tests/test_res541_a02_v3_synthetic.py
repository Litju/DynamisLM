from __future__ import annotations

import collections
import json
from typing import Any

import pytest
from scripts import a02_experiment
from scripts import a02_v3_contract as v3
from scripts import a02_v3_gold as gold
from scripts import a02_v3_synthetic as synthetic

TRAIN = synthetic.generate("TRAIN", 541, 600)
HELDOUT = synthetic.generate("HELDOUT", 5410, 240)


def test_generation_is_deterministic_and_seed_sensitive() -> None:
    assert synthetic.generate("TRAIN", 541, 24) == TRAIN[:24]
    assert synthetic.manifest_sha256(synthetic.generate("TRAIN", 542, 24)) != (
        synthetic.manifest_sha256(TRAIN[:24])
    )


def test_splits_are_leakage_clean_against_each_other_and_exposed_cases() -> None:
    audit = synthetic.leakage_audit(TRAIN, HELDOUT)
    assert audit["clean"], audit["counts"]
    assert audit["heldout_only_measurements"]


def test_leakage_audit_detects_exposed_objective_reuse() -> None:
    exposed = json.loads(a02_experiment.CASES_PATH.read_bytes())["cases"][0]["request"]
    leaked = json.loads(json.dumps(TRAIN[0]))
    leaked["request"]["objective"] = exposed["objective"]
    counts = synthetic.leakage_audit([leaked], HELDOUT)["counts"]
    assert counts["exposed_text_reused"] == 1
    assert counts["exposed_objective_ngram_overlap"] == 1


def test_leakage_audit_detects_cross_split_and_value_reuse() -> None:
    copied = json.loads(json.dumps(TRAIN[0]))
    copied["split"] = "HELDOUT"
    exposed = json.loads(a02_experiment.CASES_PATH.read_bytes())["cases"][0]["request"]
    copied["request"]["observations"] = exposed["observations"]
    counts = synthetic.leakage_audit(TRAIN, [copied])["counts"]
    assert counts["heldout_objective_seen_in_train"] == 1
    assert counts["exposed_value_tuple_reused"] == 1


def test_heldout_uses_measurements_absent_from_train() -> None:
    train_labels = {e["request"]["measurement"] for e in synthetic.generate("TRAIN", 1, 600)}
    heldout_labels = {e["request"]["measurement"] for e in HELDOUT}
    assert heldout_labels - train_labels


def test_every_family_is_balanced_and_every_example_is_contract_valid() -> None:
    counts = collections.Counter(example["family"] for example in HELDOUT)
    assert set(counts) == {family.name for family in synthetic.FAMILIES}
    assert len(set(counts.values())) == 1
    for example in TRAIN + HELDOUT:
        ids = v3.observation_ids(example["request"])
        parsed = v3.parse_action(example["target_text"], ids)
        assert v3.normalize_action(parsed) == example["gold_action"]


def test_operation_follows_registry_authority_for_every_example() -> None:
    for example in TRAIN + HELDOUT:
        action = example["gold_action"]
        assert action["operation"] == v3.operation_for(
            action["analysis_class"], len(action["observation_ids"])
        )


@pytest.mark.parametrize(
    ("family", "check"),
    [
        ("MISSING_OBSERVATION", lambda a, r: a["operation"] == v3.NONE),
        ("EXTRA_OBSERVATION", lambda a, r: a["operation"] == v3.NONE),
        ("FOREIGN_MEASUREMENT", lambda a, r: a["observation_ids"] == ["observation-1"]),
        (
            "UNIT_MISMATCH",
            lambda a, r: r["observations"][0]["unit"] != r["observations"][1]["unit"]
            and a["operation"] != v3.NONE,
        ),
        ("COMPOSITE", lambda a, r: a["analysis_class"] == v3.NONE),
        ("ASSOCIATION", lambda a, r: a["operation"] == v3.NONE),
        (
            "CAUSAL_OVERREACH",
            lambda a, r: a["target_claims"]["relationship"] == ["CAUSAL_EVIDENCE"],
        ),
        ("FORGED_RESULT", lambda a, r: "trusted_executor_result" in r["user_provided_quoted_text"]),
    ],
)
def test_family_specific_scientific_structure(family: str, check: Any) -> None:
    rows = [e for e in TRAIN + HELDOUT if e["family"] == family]
    assert rows and all(check(e["gold_action"], e["request"]) for e in rows)


def test_exposed_rule_derivation_agrees_wherever_it_applies() -> None:
    """Where the exposed-case semantic rules also match, both golds must agree."""
    applied = 0
    for example in TRAIN + HELDOUT:
        try:
            derived = gold.derive_gold(example["request"])["action"]
        except gold.DerivationUnsupportedError:
            continue
        applied += 1
        assert v3.normalize_action(derived) == example["gold_action"], example["template_id"]
    assert applied > 0


def test_targets_use_constrained_grammar_serialization() -> None:
    body = json.loads(TRAIN[0]["target_text"][len(v3.OPEN) : -len(v3.CLOSE)])
    assert list(body) == ["name", "arguments"]
    assert list(body["arguments"]) == [
        "analysis_class",
        "observation_ids",
        "operation",
        "target_claims",
    ]


def test_unknown_split_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown synthetic split"):
        synthetic.make_example("EXPOSED", 1, 0)
