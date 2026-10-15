from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, cast

import pytest
from scripts import res407_c08_generator_qualification as previous
from scripts import res407_c08_repeat_authority as qualification

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


def _target() -> dict[str, Any]:
    return next(
        item
        for item in _structural_report()["archetype_contract_inventory"]
        if item["lane_id"] == qualification._LANE_ID and item["cell"] == ["C08", "F05"]
    )


def _authority(maximum: int | str | None) -> dict[str, Any]:
    return {
        "authorized_repeat_count_min": 1,
        "authorized_repeat_count_max": maximum,
    }


def _authorized_authority(maximum: int | str) -> dict[str, Any]:
    return {
        **_authority(maximum),
        "repeat_allocation_authority_status": "AUTHORIZED",
        "candidate_id_allocation_rule": qualification._CANDIDATE_ID_ALLOCATION_RULE,
        "seed_block_allocation_rule": qualification._SEED_BLOCK_ALLOCATION_RULE,
    }


def _plan() -> dict[str, Any]:
    return qualification.build_repeat_plan(
        _authorized_authority(48),
        target_archetype=_target(),
        repeat_authority_digest="sha256:" + "a" * 64,
        structural_contract_digest="sha256:" + "b" * 64,
    )


def _materialization_fixture() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    plan = _plan()
    relations = plan["required_relation_identities"]
    candidates = []
    for instance in plan["instances"]:
        candidate = {
            **instance,
            "payload_digest": canonical_hash(("payload", instance["ordinal"])),
            "contamination_identities": {
                "source_family": f"PSE-V1-SYNTHETIC-FAMILY:{instance['candidate_id']}",
                "general_artifact": f"candidate:{instance['candidate_id']}",
                "benchmark_artifact": f"candidate:{instance['candidate_id']}",
                "training_exclusion": f"qualification-exclusion:{instance['candidate_id']}",
                "expert_author_batch": relations["expert_author_batch"],
                "generator_seed_namespace": instance["seed_namespace"],
                "generator_seed_block": instance["seed_block"],
                "source_documents_artifacts_constructs_and_provider_ids": (),
            },
            "question": (
                f"q{instance['ordinal']} alpha bravo charlie delta echo foxtrot golf hotel "
                "india juliet kilo lima"
            ),
        }
        candidates.append(candidate)
    return candidates, plan


def test_repeat_authority_parser_preserves_unknown_and_derives_finite_statuses() -> None:
    unknown = qualification.parse_repeat_authority(_authority("UNKNOWN"))
    assert unknown["status"] == "UNKNOWN"
    assert unknown["authorized_repeat_count_min"] == 1
    assert unknown["authorized_repeat_count_max"] == "UNKNOWN"
    assert qualification.parse_repeat_authority(_authority(47))["status"] == (
        "PROVEN_INSUFFICIENT_FOR_48"
    )
    assert qualification.parse_repeat_authority(_authority(48))["count_bound_status"] == (
        "PROVEN_SUFFICIENT_FOR_48"
    )
    assert qualification.parse_repeat_authority(_authority(48))["status"] == "UNKNOWN"
    assert (
        qualification.parse_repeat_authority(
            _authorized_authority("UNBOUNDED_BY_CURRENT_AUTHORITY")
        )["status"]
        == "PROVEN_SUFFICIENT_FOR_48"
    )
    assert qualification.parse_repeat_authority(_authorized_authority(48))["status"] == (
        "PROVEN_SUFFICIENT_FOR_48"
    )
    with pytest.raises(ValueError, match="allowed bound"):
        qualification.parse_repeat_authority(_authority(None))


def test_ordinal_seed_and_candidate_derivation_is_deterministic_and_bound() -> None:
    authority_digest = "sha256:" + "a" * 64
    first = qualification.derive_ordinal_identity(0, authority_digest)
    assert first == qualification.derive_ordinal_identity(0, authority_digest)
    assert first != qualification.derive_ordinal_identity(1, authority_digest)
    assert (
        first["seed_block"]
        != qualification.derive_ordinal_identity(0, "sha256:" + "b" * 64)["seed_block"]
    )
    assert first["seed_namespace"].endswith("@" + first["seed_block"])
    with pytest.raises(ValueError, match="0..47"):
        qualification.derive_ordinal_identity(48, authority_digest)


def test_authorized_plan_has_48_unique_candidate_seed_and_namespace_identities() -> None:
    plan = _plan()
    instances = plan["instances"]
    assert len(instances) == 48
    assert tuple(item["ordinal"] for item in instances) == tuple(range(48))
    for field in ("candidate_id", "seed_block", "seed_namespace"):
        assert len({item[field] for item in instances}) == 48
    assert all(item["cell"] == ("C08", "F05") for item in instances)
    assert all(item["locked_split"] == "PUBLIC_DEVELOPMENT" for item in instances)
    assert all(item["authority_digest"] == "sha256:" + "a" * 64 for item in instances)
    assert plan["plan_digest"] == canonical_hash(
        {key: value for key, value in plan.items() if key != "plan_digest"}
    )


def test_finite_repeat_cap_blocks_plan_and_proves_structural_insufficiency() -> None:
    authority = _authorized_authority(47)
    assert qualification.current_c08_repair_capability(authority) == "PROVABLY_INSUFFICIENT"
    with pytest.raises(ValueError, match="proven sufficient"):
        qualification.build_repeat_plan(
            authority,
            target_archetype=_target(),
            repeat_authority_digest="sha256:" + "a" * 64,
            structural_contract_digest="sha256:" + "b" * 64,
        )


def test_unknown_repeat_authority_fails_closed_for_plan_and_capability() -> None:
    authority = _authority("UNKNOWN")
    assert qualification.current_c08_repair_capability(authority) == "UNRESOLVED"
    with pytest.raises(ValueError, match="proven sufficient"):
        qualification.build_repeat_plan(
            authority,
            target_archetype=_target(),
            repeat_authority_digest="sha256:" + "a" * 64,
            structural_contract_digest="sha256:" + "b" * 64,
        )


def test_collision_policy_rejects_payload_seed_and_relation_collisions() -> None:
    candidates, plan = _materialization_fixture()
    qualification.validate_materialization_collisions(
        candidates,
        plan=plan,
    )

    duplicate_payload = copy.deepcopy(candidates)
    duplicate_payload[1]["payload_digest"] = duplicate_payload[0]["payload_digest"]
    with pytest.raises(ValueError, match="payload_digest"):
        qualification.validate_materialization_collisions(
            duplicate_payload,
            plan=plan,
        )

    duplicate_seed = copy.deepcopy(candidates)
    duplicate_seed[1]["seed_block"] = duplicate_seed[0]["seed_block"]
    with pytest.raises(ValueError, match="seed_block"):
        qualification.validate_materialization_collisions(
            duplicate_seed,
            plan=plan,
        )

    duplicate_candidate = copy.deepcopy(candidates)
    duplicate_candidate[1]["candidate_id"] = duplicate_candidate[0]["candidate_id"]
    with pytest.raises(ValueError, match="candidate_id"):
        qualification.validate_materialization_collisions(
            duplicate_candidate,
            plan=plan,
        )

    duplicate_contamination = copy.deepcopy(candidates)
    duplicate_contamination[1]["contamination_identities"]["source_family"] = (
        duplicate_contamination[0]["contamination_identities"]["source_family"]
    )
    with pytest.raises(ValueError, match="source_family"):
        qualification.validate_materialization_collisions(
            duplicate_contamination,
            plan=plan,
        )

    changed_relation = copy.deepcopy(candidates)
    changed_relation[0]["relation_identities"]["isolation_cluster_id"] = "unexpected"
    with pytest.raises(ValueError, match="relation/colocation"):
        qualification.validate_materialization_collisions(
            changed_relation,
            plan=plan,
        )


def test_collision_policy_rejects_exact_shingle_collision_and_baseline_collision() -> None:
    candidates, plan = _materialization_fixture()
    shared = "one two three four five six seven eight nine ten eleven twelve thirteen"
    candidates[0]["question"] = shared + " alpha"
    candidates[1]["question"] = shared + " bravo"
    with pytest.raises(ValueError, match="shingle collision"):
        qualification.validate_materialization_collisions(
            candidates,
            plan=plan,
        )

    candidates, plan = _materialization_fixture()
    candidates[0]["question"] = shared + " alpha"
    with pytest.raises(ValueError, match="shingle collision"):
        qualification.validate_materialization_collisions(
            candidates,
            plan=plan,
            existing_questions={"existing": shared + " baseline"},
        )


def test_report_records_unknown_authority_without_materialization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    structural = _structural_report()
    generator = json.loads(
        Path("reports/performance_science_eval/res407_c08_generator_qualification.json").read_text(
            encoding="utf-8"
        )
    )
    sufficiency = json.loads(
        Path("reports/performance_science_eval/res407_real_c08_sufficiency.json").read_text(
            encoding="utf-8"
        )
    )
    monkeypatch.setattr(previous, "verify_persisted_digests", lambda _report: {"status": "PASS"})
    report = qualification._derive_report(structural, generator, sufficiency, {"status": "PASS"})

    assert report["repeat_authority_status"] == "UNKNOWN"
    assert report["repeat_plan_status"] == "NOT_CREATED_REPEAT_AUTHORITY_UNKNOWN"
    assert report["repeat_plan_digest"] is None
    assert report["planned_repeat_count"] == 0
    assert report["concrete_candidates_generated"] == 0
    assert report["seeds_materialized"] == 0
    assert report["candidate_materialization_invoked"] is False
    assert report["ready_for_materialization"] is False
    assert report["ready_for_authority_expansion"] is True
    assert report["report_digest"] == canonical_hash(
        {key: value for key, value in report.items() if key != "report_digest"}
    )


def test_persisted_repeat_authority_report_is_digest_bound_and_unmaterialized() -> None:
    report = json.loads(Path(qualification.REPORT_PATH).read_text(encoding="utf-8"))
    assert report["report_digest"] == canonical_hash(
        {key: value for key, value in report.items() if key != "report_digest"}
    )
    assert report["repeat_authority_status"] == "UNKNOWN"
    assert report["authorized_repeat_count_min"] == 1
    assert report["authorized_repeat_count_max"] == "UNKNOWN"
    assert report["repeat_plan_digest"] is None
    assert report["concrete_candidates_generated"] == 0
    assert report["seeds_materialized"] == 0
