from __future__ import annotations

import json
from pathlib import Path
from typing import Any, NoReturn, cast

import pytest
from scripts import res407_c08_generator_qualification as qualification

from dynamislm.benchmark import production_authoring, variable_pool
from dynamislm.benchmark.production_authoring import PRODUCTION_SYNTHETIC_GENERATOR_DIGEST
from dynamislm.serialization import canonical_hash


def _structural_report() -> dict[str, Any]:
    return cast(
        dict[str, Any],
        json.loads(
            Path(
                "reports/performance_science_eval/res407_governed_structural_comparison.json"
            ).read_text(encoding="utf-8")
        ),
    )


def _f05_contract_row() -> dict[str, Any]:
    report = _structural_report()
    return next(
        item
        for item in report["archetype_contract_inventory"]
        if item["lane_id"] == qualification._C08_F05_LANE and item["cell"] == ["C08", "F05"]
    )


def test_rule_governed_capacity_does_not_claim_an_unbounded_repeat_count() -> None:
    result = qualification.repeat_authority(_f05_contract_row())

    assert result["authorized_repeat_count_min"] == 1
    assert result["authorized_repeat_count_max"] == "UNKNOWN"
    assert result["status"] == "UNKNOWN"
    assert result["capacity_status"] == "RULE_GOVERNED"
    assert result["seed_reuse_forbidden"] is True
    assert result["current_recipe_options_per_lane_cell"] == 1
    assert result["repeat_ordinal_in_candidate_id"] is False


def test_f05_feature_contract_is_derived_from_the_fixed_authoring_and_scorer_path() -> None:
    features = {
        (feature.kind.value, feature.key) for feature in qualification.derive_c08_f05_features()
    }

    assert features == {
        ("CELL", ("C08", "F05")),
        ("CRITICAL_ERROR", ("FALSE_SCIENTIFIC_ACCEPTANCE",)),
        ("CRITICAL_ERROR", ("INVENTED_NUMERICAL_SCIENCE",)),
        ("ROW_ERROR", ("C08", "FALSE_SCIENTIFIC_ACCEPTANCE")),
        ("ROW_ERROR", ("C08", "INVENTED_NUMERICAL_SCIENCE")),
        ("ROW_TAG", ("C08", "NONFINITE_INPUT")),
    }


def test_seed_namespaces_are_distinct_only_when_seed_blocks_are_distinct() -> None:
    first = qualification.instance_identity_contract("candidate-a", "a" * 48)
    second = qualification.instance_identity_contract("candidate-b", "b" * 48)

    assert first["isolation_cluster_id"] == second["isolation_cluster_id"]
    assert first["generator_family"] == second["generator_family"]
    assert (
        first["shared_contamination_author_batch_id"]
        == second["shared_contamination_author_batch_id"]
    )
    assert first["source_family_id"] != second["source_family_id"]
    assert first["seed_namespace"] != second["seed_namespace"]
    assert first["seed_block"] != second["seed_block"]
    formulas = qualification.instance_identity_formulas()
    assert formulas["source_family_id"] == "PSE-V1-SYNTHETIC-FAMILY:{candidate_id}"
    assert formulas["isolation_cluster_id"] == ("PSE-V1-SYNTHETIC-CLUSTER:PUBLIC_DEVELOPMENT")
    assert (
        formulas["contamination_identities"]["expert_author_batch"]
        == (first["shared_contamination_author_batch_id"])
    )


def test_repeated_instances_are_coupled_by_cluster_and_generator_family() -> None:
    relations = qualification.relationship_semantics()

    assert relations["isolation_cluster_id"]["status"] == "GUARANTEED_COUPLED"
    assert relations["GENERATOR_FAMILY"]["status"] == "GUARANTEED_COUPLED"
    assert relations["SOURCE_FAMILY"]["status"] == "CONDITIONAL"
    assert relations["GENERATOR_SEED_BLOCK"]["status"] == "CONDITIONAL"
    assert relations["CONDITIONAL_COLOCATION"]["status"] == "GUARANTEED_COUPLED"


def test_shingle_check_fails_closed_on_new_to_new_and_new_to_existing_overlap() -> None:
    shared = "one two three four five six seven eight nine ten eleven twelve thirteen"
    with pytest.raises(ValueError, match="shingle collision"):
        qualification.check_exact_shingle_independence(
            {"new-a": shared + " alpha", "new-b": shared + " beta"},
            {},
        )
    with pytest.raises(ValueError, match="shingle collision"):
        qualification.check_exact_shingle_independence(
            {"new": shared + " fresh"},
            {"old": shared + " baseline"},
        )


def test_shingle_check_ignores_baseline_collisions_but_rejects_missing_evidence() -> None:
    baseline = "one two three four five six seven eight nine ten eleven twelve thirteen"
    fresh = "alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo lima mike november"
    qualification.check_exact_shingle_independence(
        {"new": fresh},
        {"old-a": baseline + " alpha", "old-b": baseline + " beta"},
    )
    with pytest.raises(ValueError, match="no complete 13-token shingle"):
        qualification.check_exact_shingle_independence({"new": "too short"}, {})


def test_less_than_48_authorized_units_proves_insufficiency() -> None:
    assert qualification.capability_from_repeat_bound(47) == "PROVABLY_INSUFFICIENT"


def test_unknown_repeat_bound_never_implies_insufficiency() -> None:
    assert qualification.capability_from_repeat_bound(None) == "UNRESOLVED"
    assert qualification.capability_from_repeat_bound(48) == "UNRESOLVED"


def test_f05_does_not_dominate_the_optimistic_witness_feature_vector() -> None:
    report = qualification.derive_qualification(
        _structural_report(),
        existing_relations={"candidate_count": 449},
    )

    assert report["optimistic_feature_dominance_status"] == (
        "NO_REAL_VECTOR_MISSES_OPTIMISTIC_FEATURES"
    )
    missing = {
        item["key"][-1]
        for item in report["optimistic_feature_classification"]
        if item["classification"] == "NOT_GUARANTEED"
    }
    assert missing == {"LM_ARITHMETIC", "UNREGISTERED_OPERATION", "WRONG_GRAVITY"}
    assert report["c08_48_materialization_plan_digest"] is None


def test_qualification_does_not_invoke_candidate_or_seed_materialization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*_args: object, **_kwargs: object) -> NoReturn:
        raise AssertionError("qualification must not materialize candidates")

    monkeypatch.setattr(production_authoring, "_author_synthetic_packets", fail)
    monkeypatch.setattr(variable_pool, "materialize_variable_pool", fail)
    report = qualification.derive_qualification(
        _structural_report(),
        existing_relations={"candidate_count": 449},
    )

    assert report["c08_48_realizability"] == "PROVABLY_NOT_REALIZABLE"
    assert report["current_c08_repair_capability"] == "UNRESOLVED"
    assert report["concrete_candidates_generated"] == 0
    assert report["seeds_generated"] == 0
    assert report["candidate_materialization_invoked"] is False
    assert report["optimization_or_candidate_subset_search_rerun"] is False
    assert canonical_hash(report) != ""


def test_persisted_qualification_digest_binds_verified_authority_evidence() -> None:
    report = json.loads(qualification.QUALIFICATION_REPORT_PATH.read_text(encoding="utf-8"))
    digest = report.pop("qualification_digest")

    assert canonical_hash(report) == digest
    assert report["governed_archetype_contract_digest"] == (
        "sha256:fcec9490f3dee9483d9106f0ddb228a8dca2d4d3dc7dee8c10cb73a5fb761e01"
    )
    assert report["digest_verification"]["status"] == "PASS"
    assert report["digest_verification"]["verified_archetype_digest_count"] == 12
    assert len(report["digest_verification"]["verified_digest_fields"]) == 14
    relations = report["existing_449_relation_summary"]
    assert relations["candidate_count"] == 449
    assert relations["matching_public_cluster_count"] == 4
    assert relations["matching_f05_cell_count"] == 1
    assert relations["incident_conditional_colocation_group_counts"] == {
        "ISOLATION_CLUSTER": 1,
        "ISOLATION_IDENTITY": 1,
    }
    assert relations["incident_exact_shingle_group_count"] == 0
    assert tuple(report["source_code_evidence"]) == qualification._source_code_digests()
    assert report["source_code_evidence_digest"] == canonical_hash(
        qualification._source_code_digests()
    )
    assert report["synthetic_generator_registry_digest"] == (PRODUCTION_SYNTHETIC_GENERATOR_DIGEST)
    assert report["concrete_candidates_generated"] == 0
    assert report["seeds_generated"] == 0
    assert report["candidate_materialization_invoked"] is False
