#!/usr/bin/env python3
"""Build RES-523's proposed repeat-allocation protocol and campaign plan."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

_REPOSITORY = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(_REPOSITORY), str(_REPOSITORY / "src")]

from dynamislm.qualification.repeat_allocation import (  # noqa: E402
    RepeatAllocationPlan,
    RepeatAllocationProtocol,
    RepeatApprovalStatus,
    derive_planned_seed_block_identity,
    derive_repeat_candidate_id,
    repeat_collision_policy,
)
from dynamislm.serialization import canonical_hash  # noqa: E402

ENTRY_HEAD = "8b868aa3d2a6c2f661b2a41c0bc3b8be616e422e"
REPORT_PATH = Path("reports/performance_science_eval/res523_repeat_allocation_authority.json")
PROTOCOL_SCHEMA = "PSE-REPEAT-ALLOCATION-PROTOCOL@1.0.0"
PLAN_SCHEMA = "RES523-REPEAT-ALLOCATION-PLAN@1.0.0"
REPORT_SCHEMA = "RES523-REPEAT-ALLOCATION-AUTHORITY@1.0.0"
LANE_ID = "synthetic:pse-v1-synthetic-refusal-public_development"
CAPABILITY = "C08"
FAMILY = "F05"
LOCKED_SPLIT = "PUBLIC_DEVELOPMENT"
REQUESTED_COUNT = 48
ORDINAL_SEMANTICS_VERSION = "PSE-REPEAT-ORDINAL-ZERO-BASED@1.0.0"
SEED_BLOCK_DERIVATION_VERSION = "PSE-REPEAT-SEED-BLOCK@1.0.0"
CANDIDATE_ID_DERIVATION_VERSION = "PSE-REPEAT-CANDIDATE-ID@1.0.0"
COLLISION_POLICY_VERSION = "PSE-REPEAT-COLLISION-POLICY@1.0.0"
HISTORICAL_CANDIDATE_ID_PREFIX = "PSE-V1-CANDIDATE:RES407:SYNTH:"
NEW_CANDIDATE_ID_PREFIX = "PSE-V1-REPEAT-CANDIDATE:"

STRUCTURAL_COMPARISON_REF = Path(
    "reports/performance_science_eval/res407_governed_structural_comparison.json"
)
SUFFICIENCY_REF = Path("reports/performance_science_eval/res407_real_c08_sufficiency.json")
GENERATOR_QUALIFICATION_REF = Path(
    "reports/performance_science_eval/res407_c08_generator_qualification.json"
)
PRIOR_REPEAT_AUTHORITY_REF = Path(
    "reports/performance_science_eval/res407_c08_repeat_authority.json"
)
HISTORICAL_CANDIDATES_REF = Path("registries/performance_science_eval/candidates.jsonl")


def _without(record: dict[str, Any], key: str) -> dict[str, Any]:
    return {name: value for name, value in record.items() if name != key}


def _checked_report(path: Path, digest_key: str) -> dict[str, Any]:
    report: Any = json.loads((_REPOSITORY / path).read_text(encoding="utf-8"))
    if not isinstance(report, dict) or canonical_hash(_without(report, digest_key)) != report.get(
        digest_key
    ):
        raise ValueError(f"persisted upstream report digest mismatch: {path.as_posix()}")
    return report


def _protocol(parent: dict[str, Any]) -> RepeatAllocationProtocol:
    body: dict[str, Any] = {
        "schema_version": PROTOCOL_SCHEMA,
        "protocol_version": "1.0.0",
        "parent_lane_id": parent["lane_id"],
        "parent_lane_authority_ref": parent["authority_ref"],
        "parent_lane_authority_digest": parent["authority_digest"],
        "parent_lane_digest": parent["lane_digest"],
        "parent_archetype_digest": parent["archetype_digest"],
        "generator_id": parent["generator_id"],
        "generator_family": parent["generator_family"],
        "generator_version": parent["generator_version"],
        "allowed_capability": CAPABILITY,
        "allowed_family": FAMILY,
        "allowed_locked_split": LOCKED_SPLIT,
        "ordinal_semantics_version": ORDINAL_SEMANTICS_VERSION,
        "seed_block_derivation_version": SEED_BLOCK_DERIVATION_VERSION,
        "candidate_id_derivation_version": CANDIDATE_ID_DERIVATION_VERSION,
        "collision_policy_version": COLLISION_POLICY_VERSION,
        "approval_required": True,
        "approval_status": RepeatApprovalStatus.PENDING,
    }
    return RepeatAllocationProtocol(**body, authority_digest=canonical_hash(body))


def _historical_candidate_ids() -> tuple[str, ...]:
    path = _REPOSITORY / HISTORICAL_CANDIDATES_REF
    rows = tuple(json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line)
    ids = tuple(row.get("candidate_id") for row in rows)
    if any(not isinstance(candidate_id, str) or not candidate_id for candidate_id in ids):
        raise ValueError("historical candidate registry contains a missing candidate ID")
    if len(set(ids)) != len(ids):
        raise ValueError("historical candidate registry contains duplicate candidate IDs")
    return ids


def build_report() -> dict[str, Any]:
    structural = _checked_report(STRUCTURAL_COMPARISON_REF, "receipt_digest")
    sufficiency = _checked_report(SUFFICIENCY_REF, "report_digest")
    generator = _checked_report(GENERATOR_QUALIFICATION_REF, "qualification_digest")
    prior_repeat = _checked_report(PRIOR_REPEAT_AUTHORITY_REF, "report_digest")

    parents = tuple(
        row
        for row in structural["archetype_contract_inventory"]
        if row.get("lane_id") == LANE_ID and row.get("cell") == [CAPABILITY, FAMILY]
    )
    if len(parents) != 1:
        raise ValueError("RES-407 must identify exactly one parent lane/cell authority")
    parent = parents[0]
    proof = sufficiency["cardinality_proof"]
    winning = tuple(
        row
        for row in sufficiency["real_c08_repair_vector"]
        if row.get("lane_id") == LANE_ID and row.get("cell") == [CAPABILITY, FAMILY]
    )
    if (
        sufficiency.get("real_c08_structural_status") != "FEASIBLE"
        or sufficiency.get("real_c08_min_additions") != REQUESTED_COUNT
        or sufficiency.get("cardinality_optimality") != "PROVEN"
        or proof.get("status") != "PROVEN"
        or proof.get("minimum_additions") != REQUESTED_COUNT
        or proof.get("k_minus_1_status") != "INFEASIBLE"
        or proof.get("k_status") != "FEASIBLE"
        or len(winning) != 1
        or winning[0].get("count") != REQUESTED_COUNT
        or winning[0].get("split_lock") != LOCKED_SPLIT
        or winning[0].get("split_counts") != [[LOCKED_SPLIT, REQUESTED_COUNT]]
        or parent.get("locked_split") != LOCKED_SPLIT
    ):
        raise ValueError("RES-407 structural result no longer proves the requested plan")
    if prior_repeat.get("repeat_authority_status") != "UNKNOWN":
        raise ValueError("RES-407 repeat authority is no longer in the expected UNKNOWN state")
    if generator.get("repeat_authority", {}).get("authorized_repeat_count_max") != "UNKNOWN":
        raise ValueError("RES-407 generator qualification no longer records an unknown repeat cap")

    protocol = _protocol(parent)
    policy = repeat_collision_policy()
    policy_digest = canonical_hash(policy)
    tracked_historical_ids = _historical_candidate_ids()
    legacy_one_per_cell_id = f"{HISTORICAL_CANDIDATE_ID_PREFIX}{CAPABILITY}:{FAMILY}:{LOCKED_SPLIT}"
    historical_ids = tuple(sorted(set(tracked_historical_ids) | {legacy_one_per_cell_id}))
    historical_inventory_digest = canonical_hash(historical_ids)
    authorized_ordinals = tuple(range(REQUESTED_COUNT))

    authority_body: dict[str, Any] = {
        "schema_version": PLAN_SCHEMA,
        "status": "PROPOSED",
        "lane_id": LANE_ID,
        "capability": CAPABILITY,
        "family": FAMILY,
        "locked_split": LOCKED_SPLIT,
        "requested_count": REQUESTED_COUNT,
        "authorized_ordinals": authorized_ordinals,
        "structural_comparison_ref": STRUCTURAL_COMPARISON_REF.as_posix(),
        "structural_comparison_report_digest": structural["receipt_digest"],
        "structural_result_ref": SUFFICIENCY_REF.as_posix(),
        "structural_report_digest": sufficiency["report_digest"],
        "generator_qualification_ref": GENERATOR_QUALIFICATION_REF.as_posix(),
        "generator_qualification_report_digest": generator["qualification_digest"],
        "prior_repeat_authority_ref": PRIOR_REPEAT_AUTHORITY_REF.as_posix(),
        "prior_repeat_authority_report_digest": prior_repeat["report_digest"],
        "prior_repeat_authority_status": "UNKNOWN",
        "structural_status": sufficiency["real_c08_structural_status"],
        "structural_min_additions": sufficiency["real_c08_min_additions"],
        "cardinality_optimality": sufficiency["cardinality_optimality"],
        "k_minus_1": REQUESTED_COUNT - 1,
        "k_minus_1_status": proof["k_minus_1_status"],
        "k_minus_1_trial_digest": proof["k_minus_1_trial_digest"],
        "k": REQUESTED_COUNT,
        "k_status": proof["k_status"],
        "k_trial_digest": proof["k_trial_digest"],
        "parent_lane_authority_ref": protocol.parent_lane_authority_ref,
        "parent_lane_authority_digest": protocol.parent_lane_authority_digest,
        "parent_lane_digest": protocol.parent_lane_digest,
        "parent_archetype_digest": protocol.parent_archetype_digest,
        "generator_id": protocol.generator_id,
        "generator_family": protocol.generator_family,
        "generator_version": protocol.generator_version,
        "repeat_protocol_digest": protocol.authority_digest,
        "ordinal_semantics_version": protocol.ordinal_semantics_version,
        "seed_block_derivation_version": protocol.seed_block_derivation_version,
        "candidate_id_derivation_version": protocol.candidate_id_derivation_version,
        "collision_policy_version": protocol.collision_policy_version,
        "collision_policy_digest": policy_digest,
        "historical_candidate_id_inventory_digest": historical_inventory_digest,
        "historical_candidate_id_count": len(historical_ids),
        "historical_namespace_collision_count": 0,
        "owner_approval_required": True,
        "owner_approval_status": RepeatApprovalStatus.PENDING,
    }
    allocation_authority_digest = canonical_hash(authority_body)
    seed_block_ids = tuple(
        derive_planned_seed_block_identity(
            protocol,
            allocation_authority_digest,
            lane_id=LANE_ID,
            capability=CAPABILITY,
            family=FAMILY,
            locked_split=LOCKED_SPLIT,
            ordinal=ordinal,
        )
        for ordinal in authorized_ordinals
    )
    if len(set(seed_block_ids)) != REQUESTED_COUNT:
        raise ValueError("planned seed-block identity collision; stop without replacement")
    seed_inventory_digest = canonical_hash(seed_block_ids)
    plan_body = {
        **authority_body,
        "allocation_authority_digest": allocation_authority_digest,
        "seed_block_identity_inventory_digest": seed_inventory_digest,
    }
    plan = RepeatAllocationPlan(
        **plan_body,
        allocation_plan_digest=canonical_hash(plan_body),
    )
    candidate_ids = tuple(
        derive_repeat_candidate_id(
            protocol,
            plan,
            seed_block_identity=seed_block_ids[ordinal],
            ordinal=ordinal,
        )
        for ordinal in authorized_ordinals
    )
    if len(set(candidate_ids)) != REQUESTED_COUNT:
        raise ValueError("planned candidate-ID collision; stop without replacement")
    if not all(candidate_id.startswith(NEW_CANDIDATE_ID_PREFIX) for candidate_id in candidate_ids):
        raise ValueError("candidate derivation entered an unexpected namespace")
    collisions = set(candidate_ids).intersection(historical_ids)
    if collisions:
        raise ValueError("historical candidate namespace collision; stop without replacement")

    upstream = {
        "structural_comparison_ref": STRUCTURAL_COMPARISON_REF.as_posix(),
        "structural_comparison_report_digest": structural["receipt_digest"],
        "structural_result_ref": SUFFICIENCY_REF.as_posix(),
        "structural_result_report_digest": sufficiency["report_digest"],
        "generator_qualification_ref": GENERATOR_QUALIFICATION_REF.as_posix(),
        "generator_qualification_report_digest": generator["qualification_digest"],
        "prior_repeat_authority_ref": PRIOR_REPEAT_AUTHORITY_REF.as_posix(),
        "prior_repeat_authority_report_digest": prior_repeat["report_digest"],
        "current_repeat_authority_status": "UNKNOWN",
        "k_minus_1_infeasible_trial_digest": proof["k_minus_1_trial_digest"],
        "k_feasible_trial_digest": proof["k_trial_digest"],
        "existing_candidate_pool_count": generator["existing_449_relation_summary"][
            "candidate_count"
        ],
    }
    historical = {
        "tracked_candidate_id_source": HISTORICAL_CANDIDATES_REF.as_posix(),
        "tracked_candidate_id_count": len(tracked_historical_ids),
        "historical_inventory_digest_including_legacy_one_per_cell_id": historical_inventory_digest,
        "legacy_candidate_id_prefix": HISTORICAL_CANDIDATE_ID_PREFIX,
        "new_candidate_id_prefix": NEW_CANDIDATE_ID_PREFIX,
        "namespace_prefixes_disjoint": True,
        "collision_count": len(collisions),
    }
    record: dict[str, Any] = {
        "schema_version": REPORT_SCHEMA,
        "mission": "RES-523 Freeze C08 Synthetic Repeat Allocation Authority",
        "entry_head": ENTRY_HEAD,
        "upstream_authority": upstream,
        "repeat_authority_status_before_proposal": "UNKNOWN",
        "repeat_protocol": protocol.to_record(),
        "repeat_protocol_digest": protocol.authority_digest,
        "allocation_plan": plan.to_record(),
        "allocation_plan_status": plan.status,
        "allocation_plan_count": plan.requested_count,
        "allocation_ordinal_range": f"0..{plan.requested_count - 1}",
        "ordinal_inventory": list(plan.authorized_ordinals),
        "allocation_plan_digest": plan.allocation_plan_digest,
        "seed_block_derivation_version": protocol.seed_block_derivation_version,
        "planned_seed_block_count": len(seed_block_ids),
        "unique_seed_block_identities": len(set(seed_block_ids)),
        "seed_block_identity_inventory_digest": seed_inventory_digest,
        "candidate_id_derivation_version": protocol.candidate_id_derivation_version,
        "planned_candidate_id_count": len(candidate_ids),
        "unique_candidate_ids": len(set(candidate_ids)),
        "candidate_id_inventory_digest": canonical_hash(candidate_ids),
        "historical_namespace_collisions": len(collisions),
        "historical_namespace_check": historical,
        "collision_policy": policy,
        "collision_policy_digest": policy_digest,
        "distinctness_contract": {
            "guaranteed_before_materialization": [
                "unique ordinal",
                "unique planned seed-block identity",
                "unique planned candidate ID",
                "exact lane/cell/split binding",
            ],
            "not_guaranteed_before_materialization": [
                "unique payload",
                "no shingle collision",
                "no contamination collision",
                "no unexpected relation edges",
                "exact generated text independence",
            ],
        },
        "owner_approval_required": True,
        "owner_approval_status": RepeatApprovalStatus.PENDING.value,
        "candidate_materialization_invoked": False,
        "concrete_candidates_generated": 0,
        "seeds_materialized": 0,
        "ready_for_owner_approval": True,
        "ready_for_materialization": False,
    }
    return {**record, "report_digest": canonical_hash(record)}


def main() -> int:
    report = build_report()
    path = _REPOSITORY / REPORT_PATH
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"REPEAT_PROTOCOL_DIGEST={report['repeat_protocol_digest']}")
    print(f"ALLOCATION_PLAN_DIGEST={report['allocation_plan_digest']}")
    print(f"COLLISION_POLICY_DIGEST={report['collision_policy_digest']}")
    print("ALLOCATION_PLAN_STATUS=PROPOSED")
    print("OWNER_APPROVAL_STATUS=PENDING")
    print("CONCRETE_CANDIDATES_GENERATED=0")
    print("SEEDS_MATERIALIZED=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
