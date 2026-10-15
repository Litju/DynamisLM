from __future__ import annotations

import json
from pathlib import Path
from typing import Any, NoReturn, cast

import pytest
from scripts import res407_c08_generator_qualification as previous
from scripts import res407_real_c08_sufficiency as sufficiency

from dynamislm.benchmark import production_authoring, variable_pool
from dynamislm.qualification import res115_authoring
from dynamislm.serialization import canonical_hash


@pytest.fixture(scope="module")
def inputs() -> tuple[dict[str, Any], Any, tuple[Any, ...]]:
    structural_report = json.loads(
        Path(previous.STRUCTURAL_REPORT_PATH).read_text(encoding="utf-8")
    )
    geometry = previous.verify_persisted_digests(structural_report)["geometry"]
    _record, archetypes = previous._archetype_evidence()
    return structural_report, geometry, archetypes


def test_inventory_derives_all_12_exact_real_feature_contracts(
    inputs: tuple[dict[str, Any], Any, tuple[Any, ...]],
) -> None:
    structural_report, geometry, archetypes = inputs
    inventory = sufficiency.derive_real_archetype_inventory(archetypes, geometry.problem)
    by_key = {(item["lane_id"], item["cell"]): item for item in inventory}

    assert len(by_key) == 12
    assert set(item["cell"][1] for item in inventory) == {"F05", "F06", "F13", "F14"}
    for item in inventory:
        family = item["cell"][1]
        assert (
            item["row_tags"]
            == {
                "F05": ("NONFINITE_INPUT",),
                "F06": ("UNREGISTERED_OPERATION",),
                "F13": ("WRONG_GRAVITY",),
                "F14": ("LM_ARITHMETIC",),
            }[family]
        )
        assert item["row_errors"] == (
            "FALSE_SCIENTIFIC_ACCEPTANCE",
            "INVENTED_NUMERICAL_SCIENCE",
        )
        assert item["critical_errors"] == item["row_errors"]
        assert item["answerable"] is False
        assert item["answer_kind"] == "REFUSAL"
        assert item["refusal_decision"] == "REQUIRED"
        assert item["origin"] == "DETERMINISTIC_SYNTHETIC"
        assert item["split_lock"] in {"PUBLIC_DEVELOPMENT", "FROZEN_VALIDATION", "HIDDEN_FINAL"}
        assert item["mandatory_colocation"]["expert_author_batch"] == (
            "ALL_12_REAL_C08_ARCHETYPES_SHARE_ONE_SPLIT"
        )
        assert item["repeat_authority_maximum"] == "UNKNOWN"
        assert item["repeat_ordinal_in_candidate_id"] is False
        assert item["repeat_ordinal_in_seed_block_rule"] is False

    report = json.loads(sufficiency.REPORT_PATH.read_text(encoding="utf-8"))
    assert canonical_hash(inventory) == report["real_c08_archetype_inventory_digest"]
    assert report["real_c08_archetype_count"] == 12
    assert report["previous_optimistic_c08_min_additions"] == 48


def test_real_coupling_matches_existing_pool_and_shared_author_batch(
    inputs: tuple[dict[str, Any], Any, tuple[Any, ...]],
) -> None:
    _structural_report, geometry, archetypes = inputs
    inventory = sufficiency.derive_real_archetype_inventory(archetypes, geometry.problem)
    signatures = sufficiency._build_signatures(inventory, archetypes)
    groups = sufficiency.build_aggregate_colocation_groups(inventory, signatures, geometry.problem)
    author_batch = next(
        item
        for item in groups
        if any(relation[0] == "expert-author-batch" for relation in item["relation_identities"])
    )
    assert len(author_batch["signature_ids"]) == 12
    assert author_batch["existing_candidate_ids"] == ()
    lane_groups = [item for item in groups if len(item["signature_ids"]) == 4]
    assert len(lane_groups) == 3
    assert {len(item["existing_candidate_ids"]) for item in lane_groups} == {4}
    assert all(
        set(item["signature_ids"]).issubset({sig.signature_id for sig in signatures})
        for item in groups
    )


def test_repeat_optimistic_model_uses_saturation_and_no_shingle_edges(
    inputs: tuple[dict[str, Any], Any, tuple[Any, ...]],
) -> None:
    structural_report, geometry, archetypes = inputs
    inventory = sufficiency.derive_real_archetype_inventory(archetypes, geometry.problem)
    model, signatures, bounds, groups = sufficiency._build_model(
        geometry, archetypes, inventory, structural_report
    )
    proof = sufficiency._repeat_optimistic_proof(inventory, bounds, groups, structural_report)
    assert len(model.additions) == 12
    assert len(model.recourse) == 36
    assert len(model.geometry.problem.candidates) == 449
    assert proof["status"] == "PASS"
    assert proof["real_feasible_set_subset_diagnostic_model"] is True
    assert proof["repeat_optimistic_model_subset_previous_optimistic_c08_model"] is True
    assert proof["all_12_shared_author_batch_coupling_retained"] is True
    assert all(item["valid_subset_row"] for item in proof["rows"])
    assert proof["previous_optimistic_c08_lower_bound"]["minimum_additions"] == 48
    assert all(item["no_new_shingle_collision_assumed"] for item in proof["rows"])
    assert {item.upper_bound for item in bounds} == {87, 260}
    assert all(item.lane_capacity is None for item in signatures)


def test_persisted_sufficiency_result_is_aggregate_and_does_not_materialize() -> None:
    report = json.loads(sufficiency.REPORT_PATH.read_text(encoding="utf-8"))
    sufficiency.verify_report(report)
    assert report["sufficiency_model"]["archetype_count_variables"] == 12
    assert report["sufficiency_model"]["aggregate_split_recourse_variables"] == 36
    assert report["sufficiency_model"]["candidate_replica_variables"] == 0
    assert report["candidate_materialization_invoked"] is False
    assert report["concrete_candidates_generated"] == 0
    assert report["seeds_generated"] == 0
    assert report["human_review_invoked"] is False
    assert report["final_allocation_performed"] is False
    assert report["real_c08_structural_status"] == "FEASIBLE"
    assert report["cardinality_optimality"] == "PROVEN"
    assert report["cardinality_proof"]["k_minus_1_status"] == "INFEASIBLE"
    assert report["cardinality_proof"]["k_status"] == "FEASIBLE"
    assert report["previous_optimistic_f05_witness_comparison"]["status"] == ("NOT_REALIZABLE")
    missing = {
        tuple(item["key"])[1]
        for item in report["previous_optimistic_f05_witness_comparison"][
            "missing_optimistic_features"
        ]
    }
    assert missing == {"LM_ARITHMETIC", "UNREGISTERED_OPERATION", "WRONG_GRAVITY"}
    actual = next(
        item
        for item in report["real_c08_archetype_inventory"]
        if item["lane_id"] == "synthetic:pse-v1-synthetic-refusal-public_development"
        and item["cell"] == ["C08", "F05"]
    )
    assert report["real_c08_repair_vector"][0]["selection_features"] == actual["selection_features"]
    assert (
        sum(item["count"] for item in report["real_c08_repair_vector"])
        == (report["real_c08_min_additions"])
    )


def test_unknown_does_not_claim_expansion_and_infeasible_does() -> None:
    assert sufficiency.capability_from_status("INFEASIBLE") == "PROVABLY_INSUFFICIENT"
    assert sufficiency.capability_from_status("UNKNOWN") == "UNRESOLVED"
    assert sufficiency.capability_from_status("FEASIBLE") == "UNRESOLVED"
    assert sufficiency.authority_expansion_required("INFEASIBLE") is True
    assert sufficiency.authority_expansion_required("UNKNOWN") is False
    assert sufficiency.authority_expansion_required("FEASIBLE") is False


def test_contract_derivation_never_materializes_candidates_or_seeds(
    inputs: tuple[dict[str, Any], Any, tuple[Any, ...]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*_args: object, **_kwargs: object) -> NoReturn:
        raise AssertionError("structural qualification must not materialize candidates or seeds")

    monkeypatch.setattr(production_authoring, "_author_synthetic_packets", fail)
    monkeypatch.setattr(variable_pool, "materialize_variable_pool", fail)
    monkeypatch.setattr(res115_authoring, "generate_synthetic_unregistered_operation_context", fail)
    _structural_report, geometry, archetypes = inputs
    inventory = sufficiency.derive_real_archetype_inventory(archetypes, geometry.problem)

    assert len(inventory) == 12


def test_feasible_diagnostic_still_leaves_repeat_authority_unresolved() -> None:
    report = cast(dict[str, Any], json.loads(sufficiency.REPORT_PATH.read_text(encoding="utf-8")))
    assert report["real_c08_structural_status"] == "FEASIBLE"
    assert report["current_c08_repair_capability"] == "UNRESOLVED"
    assert report["next_step"] == "QUALIFY_REPEAT_AUTHORITY_FOR_WINNING_VECTOR"
    assert report["ready_for_materialization"] is False
    assert report["ready_for_authority_expansion"] is False
