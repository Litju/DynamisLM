#!/usr/bin/env python3
"""Build RES-523's proposed repeat-allocation protocol and campaign plan."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

_REPOSITORY = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(_REPOSITORY), str(_REPOSITORY / "src")]

from dynamislm.benchmark.authoring import production_seed_namespace  # noqa: E402
from dynamislm.benchmark.constants import CaseOrigin, SplitName  # noqa: E402
from dynamislm.benchmark.production import (  # noqa: E402
    _CANDIDATE_ID,
    PRODUCTION_CANDIDATE_ID_PREFIX,
    _candidate_id,
)
from dynamislm.benchmark.variable_pool import (  # noqa: E402
    ProductionCandidateRecipeV1,
    RecipeAuthorityBasis,
)
from dynamislm.qualification.repeat_allocation import (  # noqa: E402
    RepeatAllocationApprovalReceipt,
    RepeatAllocationPlan,
    RepeatAllocationProtocol,
    RepeatApprovalStatus,
    derive_planned_seed_block_identity,
    derive_repeat_candidate_id,
    repeat_collision_policy,
    validate_repeat_allocation_approval,
)
from dynamislm.serialization import canonical_hash  # noqa: E402

ENTRY_HEAD = "8b868aa3d2a6c2f661b2a41c0bc3b8be616e422e"
APPROVED_PLAN_DIGEST = "sha256:240edcc8afe8f44c9d7fbd82b6c46b4e40408e329cf943d949beeabaa90f4398"
APPROVED_PROTOCOL_DIGEST = "sha256:21230fb9bca4e70224973fe6d8d862cac31c0d9d1e1d621a5883efe75b32a140"
APPROVED_COLLISION_POLICY_DIGEST = (
    "sha256:e2cdbdd0788e497cb7bde3187192cbd93b5592ed10d0cd10f990a2fa12b7647c"
)
PROPOSED_REPORT_DIGEST = "sha256:5e86635316946cc476312af6fd2772ceff28db4a5563f04e0b353fbe8b84df50"
REPORT_PATH = Path("reports/performance_science_eval/res523_repeat_allocation_authority.json")
REPLACEMENT_REPORT_PATH = Path(
    "reports/performance_science_eval/res523_repeat_allocation_replacement_proposal.json"
)
PROTOCOL_SCHEMA = "PSE-REPEAT-ALLOCATION-PROTOCOL@1.0.0"
PLAN_SCHEMA = "RES523-REPEAT-ALLOCATION-PLAN@1.0.0"
REPLACEMENT_PLAN_SCHEMA = "RES523-REPEAT-ALLOCATION-PLAN@2.0.0"
REPORT_SCHEMA = "RES523-REPEAT-ALLOCATION-AUTHORITY@1.0.0"
REPLACEMENT_REPORT_SCHEMA = "RES523-REPEAT-ALLOCATION-REPLACEMENT-PROPOSAL@1.0.0"
APPROVAL_RECEIPT_SCHEMA = "RES523-ALLOCATION-APPROVAL-RECEIPT@1.0.0"
LANE_ID = "synthetic:pse-v1-synthetic-refusal-public_development"
CAPABILITY = "C08"
FAMILY = "F05"
LOCKED_SPLIT = "PUBLIC_DEVELOPMENT"
REQUESTED_COUNT = 48
ORDINAL_SEMANTICS_VERSION = "PSE-REPEAT-ORDINAL-ZERO-BASED@1.0.0"
SEED_BLOCK_DERIVATION_VERSION = "PSE-REPEAT-SEED-BLOCK@1.0.0"
LEGACY_CANDIDATE_ID_DERIVATION_VERSION = "PSE-REPEAT-CANDIDATE-ID@1.0.0"
CANDIDATE_ID_DERIVATION_VERSION = "PSE-REPEAT-CANDIDATE-ID@2.0.0"
COLLISION_POLICY_VERSION = "PSE-REPEAT-COLLISION-POLICY@1.0.0"
HISTORICAL_CANDIDATE_ID_PREFIX = "PSE-V1-CANDIDATE:RES407:SYNTH:"
NEW_CANDIDATE_ID_PREFIX = "PSE-V1-REPEAT-CANDIDATE:"
REPLACEMENT_CANDIDATE_ID_PREFIX = "PSE-V1-CANDIDATE:RES523:REPEAT:"
ORIGINAL_REPORT_DIGEST = "sha256:b7f6e1d97762f425651c0840317d315fd74c9f9cf13063798c6a3cffae377648"

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


def _protocol(
    parent: dict[str, Any],
    *,
    candidate_id_derivation_version: str = LEGACY_CANDIDATE_ID_DERIVATION_VERSION,
) -> RepeatAllocationProtocol:
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
        "candidate_id_derivation_version": candidate_id_derivation_version,
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
    proposal = {**record, "report_digest": canonical_hash(record)}
    if (
        protocol.protocol_version != "1.0.0"
        or protocol.authority_digest != APPROVED_PROTOCOL_DIGEST
        or plan.allocation_plan_digest != APPROVED_PLAN_DIGEST
        or plan.requested_count != REQUESTED_COUNT
        or plan.authorized_ordinals != tuple(range(REQUESTED_COUNT))
        or len(seed_block_ids) != REQUESTED_COUNT
        or len(set(seed_block_ids)) != REQUESTED_COUNT
        or len(candidate_ids) != REQUESTED_COUNT
        or len(set(candidate_ids)) != REQUESTED_COUNT
        or len(collisions) != 0
        or policy_digest != APPROVED_COLLISION_POLICY_DIGEST
        or proposal["report_digest"] != PROPOSED_REPORT_DIGEST
    ):
        raise ValueError("approved RES-523 proposal differs from its exact owner-authorized scope")

    approval = RepeatAllocationApprovalReceipt(
        schema_version=APPROVAL_RECEIPT_SCHEMA,
        reviewed_allocation_plan_digest=plan.allocation_plan_digest,
        reviewed_repeat_protocol_digest=protocol.authority_digest,
        allocation_plan_status="FROZEN",
        owner_approval_required=True,
        owner_approval_status=RepeatApprovalStatus.APPROVED,
        approval_basis=(
            "User-provided statement that the project owner approved this exact allocation plan."
        ),
    )
    validate_repeat_allocation_approval(
        approval,
        allocation_plan_digest=APPROVED_PLAN_DIGEST,
        repeat_protocol_digest=APPROVED_PROTOCOL_DIGEST,
    )
    frozen = {
        **proposal,
        "allocation_plan_status": approval.allocation_plan_status,
        "owner_approval_status": approval.owner_approval_status.value,
        "ready_for_owner_approval": False,
        "ready_for_materialization": True,
        "repeat_protocol_version": protocol.protocol_version,
        "approved_proposal_report_digest": proposal["report_digest"],
        "approval_receipt": approval.to_record(),
        "approval_receipt_digest": approval.approval_receipt_digest,
    }
    frozen.pop("report_digest")
    return {**frozen, "report_digest": canonical_hash(frozen)}


def _typed_protocol(record: dict[str, Any]) -> RepeatAllocationProtocol:
    values = dict(record)
    values["approval_status"] = RepeatApprovalStatus(values["approval_status"])
    return RepeatAllocationProtocol(**values)


def _typed_plan(record: dict[str, Any]) -> RepeatAllocationPlan:
    values = dict(record)
    values["authorized_ordinals"] = tuple(values["authorized_ordinals"])
    values["owner_approval_status"] = RepeatApprovalStatus(values["owner_approval_status"])
    return RepeatAllocationPlan(**values)


def _planned_identities(
    protocol: RepeatAllocationProtocol,
    plan: RepeatAllocationPlan,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    seed_blocks = tuple(
        derive_planned_seed_block_identity(
            protocol,
            plan.allocation_authority_digest,
            lane_id=plan.lane_id,
            capability=plan.capability,
            family=plan.family,
            locked_split=plan.locked_split,
            ordinal=ordinal,
        )
        for ordinal in plan.authorized_ordinals
    )
    candidate_ids = tuple(
        derive_repeat_candidate_id(
            protocol,
            plan,
            seed_block_identity=seed_blocks[ordinal],
            ordinal=ordinal,
        )
        for ordinal in plan.authorized_ordinals
    )
    return seed_blocks, candidate_ids


def _validate_production_recipes(
    protocol: RepeatAllocationProtocol,
    plan: RepeatAllocationPlan,
    seed_blocks: tuple[str, ...],
    candidate_ids: tuple[str, ...],
) -> tuple[str, ...]:
    recipes: list[ProductionCandidateRecipeV1] = []
    for seed_block, candidate_id in zip(seed_blocks, candidate_ids, strict=True):
        _candidate_id(candidate_id)
        if _CANDIDATE_ID.fullmatch(candidate_id) is None:
            raise ValueError("production candidate-ID regex rejected a planned identity")
        recipes.append(
            ProductionCandidateRecipeV1(
                candidate_id=candidate_id,
                origin_class=CaseOrigin.DETERMINISTIC_SYNTHETIC,
                capability_id=plan.capability,
                benchmark_family=plan.family,
                authority_basis=RecipeAuthorityBasis.GOVERNED_SUPPLY_LANE,
                authority_ref=plan.parent_lane_authority_ref,
                authority_digest=protocol.parent_lane_authority_digest,
                lane_id=plan.lane_id,
                generator_family=protocol.generator_family,
                split_lock=SplitName(plan.locked_split),
                seed_block=seed_block,
            )
        )
        production_seed_namespace(
            SplitName(plan.locked_split),
            protocol.generator_id,
            protocol.generator_version,
            seed_block,
        )
    return tuple(item.recipe_digest for item in recipes)


def build_replacement_report() -> dict[str, Any]:
    original = _checked_report(REPORT_PATH, "report_digest")
    if (
        original.get("report_digest") != ORIGINAL_REPORT_DIGEST
        or original.get("allocation_plan_digest") != APPROVED_PLAN_DIGEST
        or original.get("owner_approval_status") != "APPROVED"
        or original.get("allocation_plan_status") != "FROZEN"
        or build_report() != original
    ):
        raise ValueError("the original approved RES-523 plan or report changed")

    original_protocol = _typed_protocol(original["repeat_protocol"])
    original_plan = _typed_plan(original["allocation_plan"])
    old_seed_blocks, old_candidate_ids = _planned_identities(original_protocol, original_plan)
    old_identity_rejections = 0
    for candidate_id in old_candidate_ids:
        try:
            _candidate_id(candidate_id)
        except ValueError:
            old_identity_rejections += 1
        else:
            raise ValueError("the original repeat ID unexpectedly passes production identity")
    if old_identity_rejections != REQUESTED_COUNT:
        raise ValueError("original repeat candidate IDs are not uniformly production-incompatible")

    parent = {
        "lane_id": original_plan.lane_id,
        "authority_ref": original_plan.parent_lane_authority_ref,
        "authority_digest": original_plan.parent_lane_authority_digest,
        "lane_digest": original_plan.parent_lane_digest,
        "archetype_digest": original_plan.parent_archetype_digest,
        "generator_id": original_plan.generator_id,
        "generator_family": original_plan.generator_family,
        "generator_version": original_plan.generator_version,
    }
    protocol = _protocol(
        parent,
        candidate_id_derivation_version=CANDIDATE_ID_DERIVATION_VERSION,
    )

    authority_body: dict[str, Any] = original_plan.to_record()
    for key in (
        "allocation_authority_digest",
        "seed_block_identity_inventory_digest",
        "allocation_plan_digest",
    ):
        authority_body.pop(key)
    authority_body.update(
        {
            "schema_version": REPLACEMENT_PLAN_SCHEMA,
            "repeat_protocol_digest": protocol.authority_digest,
            "candidate_id_derivation_version": protocol.candidate_id_derivation_version,
        }
    )
    allocation_authority_digest = canonical_hash(authority_body)
    seed_blocks = tuple(
        derive_planned_seed_block_identity(
            protocol,
            allocation_authority_digest,
            lane_id=LANE_ID,
            capability=CAPABILITY,
            family=FAMILY,
            locked_split=LOCKED_SPLIT,
            ordinal=ordinal,
        )
        for ordinal in range(REQUESTED_COUNT)
    )
    if len(set(seed_blocks)) != REQUESTED_COUNT:
        raise ValueError("replacement seed-block identity collision; stop without replacement")
    seed_inventory_digest = canonical_hash(seed_blocks)
    plan_body: dict[str, Any] = {
        **authority_body,
        "allocation_authority_digest": allocation_authority_digest,
        "seed_block_identity_inventory_digest": seed_inventory_digest,
    }
    plan_record: dict[str, Any] = {
        **plan_body,
        "authorized_ordinals": tuple(plan_body["authorized_ordinals"]),
        "owner_approval_status": RepeatApprovalStatus.PENDING,
        "allocation_plan_digest": canonical_hash(plan_body),
    }
    plan = RepeatAllocationPlan(**plan_record)
    seed_blocks, candidate_ids = _planned_identities(protocol, plan)
    if (
        len(candidate_ids) != REQUESTED_COUNT
        or len(set(candidate_ids)) != REQUESTED_COUNT
        or not all(item.startswith(REPLACEMENT_CANDIDATE_ID_PREFIX) for item in candidate_ids)
    ):
        raise ValueError(
            "replacement candidate identities are not unique in the approved namespace"
        )

    tracked_historical_ids = _historical_candidate_ids()
    legacy_one_per_cell_id = f"{HISTORICAL_CANDIDATE_ID_PREFIX}{CAPABILITY}:{FAMILY}:{LOCKED_SPLIT}"
    historical_ids = tuple(sorted(set(tracked_historical_ids) | {legacy_one_per_cell_id}))
    collisions = set(candidate_ids).intersection(historical_ids)
    if collisions:
        raise ValueError("replacement IDs collide with historical candidate identities")
    if REPLACEMENT_CANDIDATE_ID_PREFIX.startswith(HISTORICAL_CANDIDATE_ID_PREFIX) or (
        HISTORICAL_CANDIDATE_ID_PREFIX.startswith(REPLACEMENT_CANDIDATE_ID_PREFIX)
    ):
        raise ValueError("replacement and historical candidate namespaces overlap")

    recipe_digests = _validate_production_recipes(protocol, plan, seed_blocks, candidate_ids)
    generator = _checked_report(GENERATOR_QUALIFICATION_REF, "qualification_digest")
    identity_formulas = generator["instance_identity_formulas"]
    source_family_ids = tuple(
        f"PSE-V1-SYNTHETIC-FAMILY:{candidate_id}" for candidate_id in candidate_ids
    )
    artifact_ids = tuple(f"candidate:{candidate_id}" for candidate_id in candidate_ids)
    training_exclusion_ids = tuple(
        f"qualification-exclusion:{candidate_id}" for candidate_id in candidate_ids
    )
    seed_namespaces = tuple(
        production_seed_namespace(
            SplitName(LOCKED_SPLIT), protocol.generator_id, protocol.generator_version, seed_block
        )
        for seed_block in seed_blocks
    )
    if any(
        len(set(values)) != REQUESTED_COUNT
        for values in (
            source_family_ids,
            artifact_ids,
            training_exclusion_ids,
            seed_namespaces,
        )
    ):
        raise ValueError("replacement identity-derived contamination keys are not unique")

    structural = _checked_report(STRUCTURAL_COMPARISON_REF, "receipt_digest")
    sufficiency = _checked_report(SUFFICIENCY_REF, "report_digest")
    prior_repeat = _checked_report(PRIOR_REPEAT_AUTHORITY_REF, "report_digest")
    winning = tuple(
        row
        for row in sufficiency["real_c08_repair_vector"]
        if row.get("lane_id") == LANE_ID and row.get("cell") == [CAPABILITY, FAMILY]
    )
    if (
        len(winning) != 1
        or winning[0].get("count") != REQUESTED_COUNT
        or winning[0].get("split_lock") != LOCKED_SPLIT
        or winning[0].get("split_counts") != [[LOCKED_SPLIT, REQUESTED_COUNT]]
        or winning[0].get("origin") != CaseOrigin.DETERMINISTIC_SYNTHETIC.value
        or winning[0].get("selection_features") != generator.get("real_feature_vector")
        or identity_formulas.get("generator_family") != protocol.generator_family
        or identity_formulas.get("isolation_cluster_id")
        != f"PSE-V1-SYNTHETIC-CLUSTER:{LOCKED_SPLIT}"
    ):
        raise ValueError("RES-407 structural witness no longer identifies one replacement row")
    selection_features = winning[0]["selection_features"]

    original_authority = original_plan.to_record()
    proposed_authority = plan.to_record()
    preserved_fields = (
        "lane_id",
        "capability",
        "family",
        "locked_split",
        "requested_count",
        "authorized_ordinals",
        "structural_comparison_ref",
        "structural_comparison_report_digest",
        "structural_result_ref",
        "structural_report_digest",
        "generator_qualification_ref",
        "generator_qualification_report_digest",
        "prior_repeat_authority_ref",
        "prior_repeat_authority_report_digest",
        "prior_repeat_authority_status",
        "structural_status",
        "structural_min_additions",
        "cardinality_optimality",
        "k_minus_1",
        "k_minus_1_status",
        "k_minus_1_trial_digest",
        "k",
        "k_status",
        "k_trial_digest",
        "parent_lane_authority_ref",
        "parent_lane_authority_digest",
        "parent_lane_digest",
        "parent_archetype_digest",
        "generator_id",
        "generator_family",
        "generator_version",
        "ordinal_semantics_version",
        "seed_block_derivation_version",
        "collision_policy_version",
        "collision_policy_digest",
        "historical_candidate_id_inventory_digest",
        "historical_candidate_id_count",
        "historical_namespace_collision_count",
        "owner_approval_required",
        "owner_approval_status",
    )
    if any(original_authority[key] != proposed_authority[key] for key in preserved_fields):
        raise ValueError("replacement changed a non-ID RES-523 authority field")

    record: dict[str, Any] = {
        "schema_version": REPLACEMENT_REPORT_SCHEMA,
        "mission": "RES-523 production-compatible C08 repeat allocation replacement proposal",
        "supersession": {
            "original_plan_ref": REPORT_PATH.as_posix(),
            "original_report_digest": original["report_digest"],
            "original_allocation_plan_digest": original["allocation_plan_digest"],
            "original_allocation_plan_status": original["allocation_plan_status"],
            "original_owner_approval_status": original["owner_approval_status"],
            "original_plan_production_identity_compatible": False,
            "original_ids_rejected_by_production_identity_validator": old_identity_rejections,
            "replacement_supersedes_original_for_execution": True,
            "approval_transfer": "NONE; replacement owner approval remains PENDING",
        },
        "repeat_protocol": protocol.to_record(),
        "repeat_protocol_digest": protocol.authority_digest,
        "allocation_plan": plan.to_record(),
        "allocation_plan_status": plan.status,
        "allocation_plan_digest": plan.allocation_plan_digest,
        "allocation_plan_count": plan.requested_count,
        "allocation_ordinal_range": f"0..{plan.requested_count - 1}",
        "ordinal_inventory": list(plan.authorized_ordinals),
        "seed_block_derivation_version": protocol.seed_block_derivation_version,
        "planned_seed_block_count": len(seed_blocks),
        "unique_seed_block_identities": len(set(seed_blocks)),
        "seed_block_identity_inventory_digest": seed_inventory_digest,
        "candidate_id_derivation_version": protocol.candidate_id_derivation_version,
        "candidate_id_prefix": REPLACEMENT_CANDIDATE_ID_PREFIX,
        "planned_candidate_id_count": len(candidate_ids),
        "unique_candidate_ids": len(set(candidate_ids)),
        "candidate_id_inventory_digest": canonical_hash(candidate_ids),
        "planned_identities": [
            {
                "ordinal": ordinal,
                "candidate_id": candidate_ids[ordinal],
                "seed_block_identity": seed_blocks[ordinal],
            }
            for ordinal in plan.authorized_ordinals
        ],
        "production_validation": {
            "identity_validator": "dynamislm.benchmark.production._candidate_id",
            "identity_regex": _CANDIDATE_ID.pattern,
            "maximum_id_length": len(PRODUCTION_CANDIDATE_ID_PREFIX) + 128,
            "identity_valid_count": len(candidate_ids),
            "recipe_validator": "ProductionCandidateRecipeV1.__post_init__",
            "recipe_valid_count": len(recipe_digests),
            "recipe_digest_inventory_digest": canonical_hash(recipe_digests),
            "seed_namespace_valid_count": len(seed_namespaces),
            "candidate_payloads_generated": 0,
        },
        "historical_collision_check": {
            "tracked_candidate_id_source": HISTORICAL_CANDIDATES_REF.as_posix(),
            "tracked_candidate_id_count": len(tracked_historical_ids),
            "legacy_one_per_cell_id": legacy_one_per_cell_id,
            "historical_inventory_digest": canonical_hash(historical_ids),
            "historical_id_count_including_legacy": len(historical_ids),
            "historical_id_collisions": len(collisions),
            "historical_namespace_prefix": HISTORICAL_CANDIDATE_ID_PREFIX,
            "replacement_namespace_prefix": REPLACEMENT_CANDIDATE_ID_PREFIX,
            "namespace_prefixes_disjoint": True,
        },
        "source_authority_compatibility": {
            "source_reports": [
                {
                    "role": "structural comparison",
                    "ref": STRUCTURAL_COMPARISON_REF.as_posix(),
                    "digest": structural["receipt_digest"],
                },
                {
                    "role": "RES-407 C08 sufficiency and cardinality proof",
                    "ref": SUFFICIENCY_REF.as_posix(),
                    "digest": sufficiency["report_digest"],
                },
                {
                    "role": "production generator qualification",
                    "ref": GENERATOR_QUALIFICATION_REF.as_posix(),
                    "digest": generator["qualification_digest"],
                },
                {
                    "role": "prior repeat authority",
                    "ref": PRIOR_REPEAT_AUTHORITY_REF.as_posix(),
                    "digest": prior_repeat["report_digest"],
                    "status": prior_repeat["repeat_authority_status"],
                },
            ],
            "original_plan_digest_preserved": original["allocation_plan_digest"],
            "parent_lane_authority_digest": plan.parent_lane_authority_digest,
            "parent_lane_digest": plan.parent_lane_digest,
            "parent_archetype_digest": plan.parent_archetype_digest,
            "generator": {
                "generator_id": plan.generator_id,
                "generator_family": plan.generator_family,
                "generator_version": plan.generator_version,
            },
            "preserved_plan_fields": list(preserved_fields),
            "structural_vector_digest": sufficiency["real_c08_repair_vector_digest"],
        },
        "structural_compatibility": {
            "count": plan.requested_count,
            "ordinals": list(plan.authorized_ordinals),
            "lane_id": plan.lane_id,
            "cell": [plan.capability, plan.family],
            "split": plan.locked_split,
            "selection_features": selection_features,
            "selection_features_digest": canonical_hash(tuple(selection_features)),
            "selection_features_preserved": True,
            "identity_derived_contamination_keys": {
                "source_family": identity_formulas["contamination_identities"]["source_family"],
                "general_and_benchmark_artifact": identity_formulas["contamination_identities"][
                    "general_artifact"
                ],
                "training_exclusion": identity_formulas["contamination_identities"][
                    "training_exclusion"
                ],
                "all_three_unique_for_48_ids": True,
            },
            "shared_colocation_identities_unchanged": {
                "isolation_cluster_id": identity_formulas["isolation_cluster_id"],
                "generator_family": identity_formulas["generator_family"],
                "expert_author_batch": identity_formulas["contamination_identities"][
                    "expert_author_batch"
                ],
            },
            "existing_449_relation_compatibility": {
                "candidate_count": generator["existing_449_relation_summary"]["candidate_count"],
                "matching_generator_family_count": generator["existing_449_relation_summary"][
                    "matching_generator_family_count"
                ],
                "matching_public_cluster_count": generator["existing_449_relation_summary"][
                    "matching_public_cluster_count"
                ],
                "matching_author_batch_count": generator["existing_449_relation_summary"][
                    "matching_author_batch_count"
                ],
                "new_to_existing_relation_semantics": generator["existing_449_relation_summary"][
                    "new_to_existing_relation_semantics"
                ],
            },
            "seed_block_and_seed_namespace_unique_for_48_ids": True,
            "exact_13_token_shingle_relationships": "UNKNOWN_UNTIL_MATERIALIZATION",
            "structural_proof_assumptions_preserved": True,
        },
        "digest_dependency_check": {
            "allocation_authority_digest_inputs_exclude_seed_and_candidate_ids": True,
            "seed_block_identities_derive_from_allocation_authority_digest": True,
            "allocation_plan_digest_commits_seed_identity_inventory_not_candidate_ids": True,
            "candidate_ids_derive_from_final_plan_digest_and_seed_block_identities": True,
            "candidate_ids_excluded_from_plan_payload": True,
            "report_digest_commits_plan_and_candidate_id_inventory_after_derivation": True,
            "circular_dependency": False,
        },
        "collision_policy": original["collision_policy"],
        "collision_policy_digest": original["collision_policy_digest"],
        "owner_approval_required": True,
        "owner_approval_status": RepeatApprovalStatus.PENDING.value,
        "ready_for_owner_approval": True,
        "ready_for_materialization": False,
        "candidate_materialization_invoked": False,
        "concrete_candidates_generated": 0,
        "seeds_materialized": 0,
    }
    if (
        plan.requested_count != REQUESTED_COUNT
        or plan.authorized_ordinals != tuple(range(REQUESTED_COUNT))
        or (plan.capability, plan.family, plan.locked_split) != (CAPABILITY, FAMILY, LOCKED_SPLIT)
        or plan.status != "PROPOSED"
        or plan.owner_approval_status is not RepeatApprovalStatus.PENDING
        or protocol.approval_status is not RepeatApprovalStatus.PENDING
    ):
        raise ValueError("replacement proposal changed locked scope or approval state")
    return {**record, "report_digest": canonical_hash(record)}


def main() -> int:
    report = build_replacement_report()
    path = _REPOSITORY / REPLACEMENT_REPORT_PATH
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"REPEAT_PROTOCOL_DIGEST={report['repeat_protocol_digest']}")
    print(f"ALLOCATION_PLAN_DIGEST={report['allocation_plan_digest']}")
    print(f"COLLISION_POLICY_DIGEST={report['collision_policy_digest']}")
    print(f"REPORT_DIGEST={report['report_digest']}")
    print("ALLOCATION_PLAN_STATUS=PROPOSED")
    print("OWNER_APPROVAL_STATUS=PENDING")
    print("CONCRETE_CANDIDATES_GENERATED=0")
    print("SEEDS_MATERIALIZED=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
