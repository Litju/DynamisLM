"""Independent derivation of every generated V3 gold action (RES-541).

The generator assigns gold by family. These tests check that gold against a separate,
closed-vocabulary adjudication of the model-visible objective and question text, which was
written from the text and never reads a family label.
"""

from __future__ import annotations

import collections
import copy
import json
from pathlib import Path
from typing import Any

import pytest
from scripts import a02_v3_contract as v3
from scripts import a02_v3_decision as decision
from scripts import a02_v3_gold as gold
from scripts import a02_v3_synthetic as synthetic

TRAIN = synthetic.generate("TRAIN", 541, 2800)
HELDOUT = synthetic.generate("HELDOUT", 5410, 280)
FAMILY_COUNT = 14


def _semantics() -> dict[str, Any]:
    document: dict[str, Any] = json.loads(gold.GENERATED_SEMANTICS_PATH.read_bytes())
    return document


def _install(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutate: Any) -> None:
    semantics = _semantics()
    mutate(semantics)
    path = tmp_path / "generated-semantics.json"
    path.write_text(json.dumps(semantics))
    monkeypatch.setattr(gold, "GENERATED_SEMANTICS_PATH", path)


def test_every_generated_example_is_independently_derived_and_none_is_skipped() -> None:
    for examples, per_family in ((TRAIN, 200), (HELDOUT, 20)):
        report = gold.verify_generated_gold(examples)
        assert report["examples"] == report["verified"] == len(examples)
        assert len(report["families"]) == FAMILY_COUNT
        assert set(report["families"].values()) == {per_family}


def test_derivation_is_not_vacuous_it_agrees_rather_than_refusing() -> None:
    """The exposed-case rules refuse every generated phrase; this authority must not."""
    outcomes: collections.Counter[str] = collections.Counter()
    for example in TRAIN + HELDOUT:
        try:
            gold.derive_generated_gold(example["request"])
            outcomes["derived"] += 1
        except gold.DerivationUnsupportedError:
            outcomes["refused"] += 1
    assert outcomes == {"derived": len(TRAIN) + len(HELDOUT)}


def test_combined_request_not_the_objective_alone_determines_gold() -> None:
    by_family = {e["family"]: e for e in HELDOUT}
    for family in ("QUESTION_ADDS_CAUSAL", "QUESTION_ADDS_PRACTICAL"):
        request = by_family[family]["request"]
        alone = copy.deepcopy(request)
        alone["question"] = alone["objective"]
        escalated = gold.derive_generated_gold(request)["action"]
        objective_only = gold.derive_generated_gold(alone)["action"]
        assert escalated["analysis_class"] == v3.NONE
        assert objective_only["analysis_class"] != v3.NONE
        assert escalated["target_claims"] != objective_only["target_claims"]


def _different_claims(claims: dict[str, list[str]]) -> dict[str, list[str]]:
    changed = copy.deepcopy(claims)
    changed["measurement"] = [] if claims["measurement"] else ["NUMERICAL_CHANGE"]
    assert changed != claims
    return changed


@pytest.mark.parametrize("family", sorted({e["family"] for e in HELDOUT}))
def test_a_wrong_generated_action_is_detected_in_every_family(family: str) -> None:
    example = copy.deepcopy(next(e for e in HELDOUT if e["family"] == family))
    gold_action = example["gold_action"]
    wrong_class = v3.NONE if gold_action["analysis_class"] != v3.NONE else "SCALAR_ABSOLUTE_CHANGE"
    for field, value in (
        ("analysis_class", wrong_class),
        ("observation_ids", []),
        ("operation", "NOT_THE_OPERATION"),
        ("target_claims", _different_claims(gold_action["target_claims"])),
    ):
        tampered = copy.deepcopy(example)
        tampered["gold_action"][field] = value
        with pytest.raises(gold.GeneratedGoldError, match="differs from derived gold"):
            gold.verify_generated_gold([tampered])


@pytest.mark.parametrize(
    ("field", "text"),
    [
        ("objective", "Compute a vibe quotient for the athlete."),
        ("objective", "Report how much jump height changed between the two tests; also why."),
        ("question", "Did the strength block cause the change, and does it matter?"),
        ("question", "Is it a worthwhile adaptation?"),
        ("question", "Prove it."),
    ],
)
def test_contradictory_or_unsupported_text_fails_closed_and_is_reported(
    field: str, text: str
) -> None:
    example = copy.deepcopy(HELDOUT[0])
    example["request"][field] = text
    with pytest.raises(gold.GeneratedGoldError, match="not derivable"):
        gold.verify_generated_gold([example])
    # The failure names the example, so it cannot disappear from coverage.
    with pytest.raises(gold.GeneratedGoldError, match="HELDOUT:5410:0"):
        gold.verify_generated_gold([example])


def test_an_unknown_measurement_name_in_a_template_fails_closed() -> None:
    example = copy.deepcopy(HELDOUT[0])
    example["request"]["objective"] = "Calculate the difference in warp speed between the tests."
    with pytest.raises(gold.GeneratedGoldError, match="outside the adjudicated vocabulary"):
        gold.verify_generated_gold([example])


def test_a_mixed_batch_reports_the_bad_example_rather_than_skipping_it() -> None:
    bad = copy.deepcopy(HELDOUT[3])
    bad["gold_action"]["observation_ids"] = ["observation-9"]
    with pytest.raises(gold.GeneratedGoldError, match="HELDOUT:5410:3"):
        gold.verify_generated_gold([*HELDOUT[:3], bad, *HELDOUT[4:]])


def test_load_protocol_refuses_a_generator_that_diverges_from_independent_gold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    protocol = decision.load_protocol()
    pinned = {
        protocol["data"][k]["split"]: protocol["data"][k]["manifest_sha256"]
        for k in ("training", "heldout_evaluation")
    }
    real = synthetic.make_example

    def tampered(split: str, seed: int, index: int) -> dict[str, Any]:
        example = real(split, seed, index)
        if (split, index) == ("HELDOUT", 0):
            example["gold_action"] = copy.deepcopy(example["gold_action"])
            example["gold_action"]["analysis_class"] = v3.NONE
        return example

    monkeypatch.setattr(synthetic, "make_example", tampered)
    # Defeat the manifest-hash pin so the independent-gold check is what must catch this.
    monkeypatch.setattr(synthetic, "manifest_sha256", lambda examples: pinned[examples[0]["split"]])
    with pytest.raises(gold.GeneratedGoldError, match="HELDOUT:5410:0"):
        decision.load_protocol()


def test_changing_an_authority_rule_changes_the_verdict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def weaken(semantics: dict[str, Any]) -> None:
        causal = next(r for r in semantics["rules"] if r["id"] == "OBJ_11")
        assert causal["relationship"] == ["CAUSAL_EVIDENCE"]
        causal["relationship"] = ["DESCRIPTIVE_CHANGE"]

    _install(tmp_path, monkeypatch, weaken)
    with pytest.raises(gold.GeneratedGoldError):
        gold.verify_generated_gold(HELDOUT)


def test_authority_is_written_from_text_and_never_cites_family_labels() -> None:
    semantics = _semantics()
    labels = {e["family"] for e in TRAIN if "_" in e["family"]}
    assert (
        len(labels) == FAMILY_COUNT - 3
    )  # the other three are single words shared with claim levels
    for rule in semantics["rules"]:
        text = " ".join((rule["id"], rule["phrase"], rule["justification"]))
        assert not any(label in text for label in labels), rule["id"]
    assert "family" not in json.dumps(semantics["rules"]).lower()
    assert not [key for key in semantics if "family" in key.lower()]
    assert semantics["closed_vocabulary"] is True
    assert all(rule["justification"] for rule in semantics["rules"])


def test_authority_covers_every_generator_template_exactly_once() -> None:
    semantics = _semantics()
    texts = [t for rule in semantics["rules"] for t in gold._closed_texts(rule, semantics)]
    assert len(texts) == len(set(texts))
    used_rules: set[str] = set()
    for example in TRAIN + HELDOUT:
        used_rules.update(
            gold.derive_generated_gold(example["request"])["justification"]["matched_rules"]
        )
    # Unused vocabulary would be unaudited authority.
    assert used_rules == {rule["id"] for rule in semantics["rules"]}


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda s: s.pop("measurement_names"), "unique measurement names"),
        (lambda s: s.update(measurement_names=["a", "a"]), "unique measurement names"),
        (lambda s: s["rules"][1].update(phrase=s["rules"][0]["phrase"]), "not unique"),
        (lambda s: s["rules"][0].update(measurement=["INVENTED"]), "unknown claim level"),
        (lambda s: s["rules"][0].update(justification=""), "lacks a justification"),
    ],
)
def test_closed_vocabulary_integrity_is_enforced(tmp_path: Path, mutate: Any, message: str) -> None:
    semantics = _semantics()
    mutate(semantics)
    path = tmp_path / "s.json"
    path.write_text(json.dumps(semantics))
    with pytest.raises(ValueError, match=message):
        gold.load_semantics(path)
