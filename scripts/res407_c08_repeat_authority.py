#!/usr/bin/env python3
"""Qualify RES-407 C08 repeat authority without generating candidates or seeds."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

_REPOSITORY = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(_REPOSITORY), str(_REPOSITORY / "src")]

from dynamislm.benchmark.authoring import (  # noqa: E402
    production_seed_namespace,
    question_classes_for_cell,
)
from dynamislm.benchmark.constants import SplitName  # noqa: E402
from dynamislm.benchmark.production_authoring import (  # noqa: E402
    _SYNTHETIC_QUESTION_FOCUS,
    _production_adversarial_tags,
)
from dynamislm.qualification.res115_authoring import (  # noqa: E402
    AUTHORING_PROCESS_ID,
    _production_authoring_engine_references,
)
from dynamislm.serialization import canonical_hash  # noqa: E402
from scripts import res407_c08_generator_qualification as previous  # noqa: E402

ENTRY_HEAD = "856db4adff14531b568397d07c8d17f46824a93a"
REPORT_PATH = Path("reports/performance_science_eval/res407_c08_repeat_authority.json")
STRUCTURAL_REPORT_PATH = Path(
    "reports/performance_science_eval/res407_governed_structural_comparison.json"
)
GENERATOR_REPORT_PATH = Path(
    "reports/performance_science_eval/res407_c08_generator_qualification.json"
)
SUFFICIENCY_REPORT_PATH = Path("reports/performance_science_eval/res407_real_c08_sufficiency.json")
_SCHEMA = "RES407-C08-REPEAT-AUTHORITY@1.0.0"
_PLAN_SCHEMA = "RES407-C08-48-REPEAT-PLAN@1.0.0"
_REQUIRED_REPEAT_COUNT = 48
_LANE_ID = "synthetic:pse-v1-synthetic-refusal-public_development"
_CELL = ("C08", "F05")
_SPLIT = SplitName.PUBLIC_DEVELOPMENT
_GENERATOR_ID = "pse-v1-unregistered-operation-context"
_GENERATOR_VERSION = "1.0.0"
_CANDIDATE_ID_ALLOCATION_RULE = (
    "PSE-V1-CANDIDATE:RES407:SYNTH:C08:F05:PUBLIC_DEVELOPMENT:"
    "R{ordinal:02d}:{allocation_digest[:16]}"
)
_SEED_BLOCK_ALLOCATION_RULE = (
    "res407-{allocation_digest[:48]}; allocation_digest binds the authority digest and ordinal"
)
_EXPECTED_SHARED_CONTAMINATION = frozenset({"expert_author_batch"})
_EXPECTED_CONTAMINATION_KINDS = frozenset(
    {
        "source_family",
        "general_artifact",
        "benchmark_artifact",
        "training_exclusion",
        "expert_author_batch",
        "generator_seed_namespace",
        "generator_seed_block",
        "source_documents_artifacts_constructs_and_provider_ids",
    }
)
_SOURCE_FILES = (
    "scripts/res407_c08_repeat_authority.py",
    "scripts/res407_governed_backfill.py",
    "scripts/res407_repair_geometry.py",
    "scripts/res407_c08_generator_qualification.py",
    "scripts/res407_real_c08_sufficiency.py",
    "src/dynamislm/benchmark/authoring.py",
    "src/dynamislm/benchmark/authority_supply.py",
    "src/dynamislm/benchmark/contamination.py",
    "src/dynamislm/benchmark/production.py",
    "src/dynamislm/benchmark/production_authoring.py",
    "src/dynamislm/benchmark/coverage.py",
    "src/dynamislm/qualification/res115_authoring.py",
    "docs/architecture/PERFORMANCE_SCIENCE_EVAL_PRE_REVIEW_V1.md",
    "docs/decisions/RES21-DR-001-performance-science-eval-v1.md",
    "docs/qualification/RES-407-ACCEPTANCE-RECEIPT.md",
    "docs/qualification/RES-407-STRUCTURAL-GEOMETRY.md",
)


def _without(record: Mapping[str, Any], key: str) -> dict[str, Any]:
    return {name: value for name, value in record.items() if name != key}


def parse_repeat_authority(record: Mapping[str, Any]) -> dict[str, Any]:
    """Parse only explicit repeat bounds; null capacity never means unbounded."""

    minimum = record.get("authorized_repeat_count_min")
    maximum = record.get("authorized_repeat_count_max")
    if type(minimum) is not int or minimum < 1:
        raise ValueError("authorized repeat minimum must be a positive integer")
    if type(maximum) is int:
        if maximum < minimum:
            raise ValueError("authorized repeat maximum is below its minimum")
        bound_status = (
            "PROVEN_INSUFFICIENT_FOR_48"
            if maximum < _REQUIRED_REPEAT_COUNT
            else "PROVEN_SUFFICIENT_FOR_48"
        )
    elif maximum == "UNBOUNDED_BY_CURRENT_AUTHORITY":
        bound_status = "PROVEN_SUFFICIENT_FOR_48"
    elif maximum == "UNKNOWN":
        bound_status = "UNKNOWN"
    else:
        raise ValueError("authorized repeat maximum must be an integer or an allowed bound")
    allocation_authorized = (
        record.get("repeat_allocation_authority_status") == "AUTHORIZED"
        and record.get("candidate_id_allocation_rule") == _CANDIDATE_ID_ALLOCATION_RULE
        and record.get("seed_block_allocation_rule") == _SEED_BLOCK_ALLOCATION_RULE
    )
    status = (
        "PROVEN_INSUFFICIENT_FOR_48"
        if bound_status == "PROVEN_INSUFFICIENT_FOR_48"
        else (
            "PROVEN_SUFFICIENT_FOR_48"
            if bound_status == "PROVEN_SUFFICIENT_FOR_48" and allocation_authorized
            else "UNKNOWN"
        )
    )
    return {
        "status": status,
        "count_bound_status": bound_status,
        "allocation_authorized": allocation_authorized,
        "authorized_repeat_count_min": minimum,
        "authorized_repeat_count_max": maximum,
    }


def current_c08_repair_capability(repeat_authority: Mapping[str, Any]) -> str:
    parsed = parse_repeat_authority(repeat_authority)
    if parsed["status"] == "PROVEN_INSUFFICIENT_FOR_48":
        return "PROVABLY_INSUFFICIENT"
    if parsed["status"] == "PROVEN_SUFFICIENT_FOR_48":
        return "PROVEN_SUFFICIENT_FOR_48"
    return "UNRESOLVED"


def derive_ordinal_identity(ordinal: int, authority_digest: str) -> dict[str, Any]:
    """Derive a hypothetical repeat identity; this does not create a seed."""

    if type(ordinal) is not int or not 0 <= ordinal < _REQUIRED_REPEAT_COUNT:
        raise ValueError("repeat ordinal must be an integer in 0..47")
    if re.fullmatch(r"sha256:[0-9a-f]{64}", authority_digest) is None:
        raise ValueError("repeat allocation requires a SHA-256 authority digest")
    allocation_basis = {
        "schema": _PLAN_SCHEMA,
        "repeat_authority_digest": authority_digest,
        "lane_id": _LANE_ID,
        "cell": _CELL,
        "locked_split": _SPLIT.value,
        "generator_id": _GENERATOR_ID,
        "generator_version": _GENERATOR_VERSION,
        "ordinal": ordinal,
    }
    allocation_digest = canonical_hash(allocation_basis).removeprefix("sha256:")
    seed_block = f"res407-{allocation_digest[:48]}"
    candidate_id = (
        f"PSE-V1-CANDIDATE:RES407:SYNTH:C08:F05:PUBLIC_DEVELOPMENT:"
        f"R{ordinal:02d}:{allocation_digest[:16]}"
    )
    return {
        "ordinal": ordinal,
        "candidate_id": candidate_id,
        "seed_block": seed_block,
        "seed_namespace": production_seed_namespace(
            _SPLIT, _GENERATOR_ID, _GENERATOR_VERSION, seed_block
        ),
        "allocation_digest": f"sha256:{allocation_digest}",
    }


def build_repeat_plan(
    repeat_authority: Mapping[str, Any],
    *,
    target_archetype: Mapping[str, Any],
    repeat_authority_digest: str,
    structural_contract_digest: str,
) -> dict[str, Any]:
    """Build the exact 48-identity plan only under proven repeat authority."""

    parsed = parse_repeat_authority(repeat_authority)
    if parsed["status"] != "PROVEN_SUFFICIENT_FOR_48":
        raise ValueError(
            "48-repeat plan requires count and ordinal-allocation authority proven sufficient"
        )
    if (
        target_archetype.get("lane_id") != _LANE_ID
        or tuple(target_archetype.get("cell", ())) != _CELL
        or target_archetype.get("locked_split") != _SPLIT.value
    ):
        raise ValueError("repeat plan target differs from the qualified C08:F05 public archetype")
    generator_contract = {
        "authority_ref": target_archetype["authority_ref"],
        "generator_authority_digest": target_archetype["authority_digest"],
        "lane_digest": target_archetype["lane_digest"],
        "lane_id": _LANE_ID,
        "generator_id": target_archetype["generator_id"],
        "generator_version": target_archetype["generator_version"],
        "generator_family": target_archetype["generator_family"],
        "output_contract": target_archetype["generator_contract"],
    }
    required_relations = {
        "isolation_cluster_id": f"PSE-V1-SYNTHETIC-CLUSTER:{_SPLIT.value}",
        "generator_family": target_archetype["generator_family"],
        "expert_author_batch": AUTHORING_PROCESS_ID,
    }
    instances = tuple(
        {
            **derive_ordinal_identity(ordinal, repeat_authority_digest),
            "lane_id": _LANE_ID,
            "cell": _CELL,
            "locked_split": _SPLIT.value,
            "generator_contract": generator_contract,
            "authority_digest": repeat_authority_digest,
            "generator_authority_digest": target_archetype["authority_digest"],
            "structural_contract_digest": structural_contract_digest,
            "relation_identities": required_relations,
        }
        for ordinal in range(_REQUIRED_REPEAT_COUNT)
    )
    for key in ("candidate_id", "seed_block", "seed_namespace"):
        values = tuple(item[key] for item in instances)
        if len(set(values)) != _REQUIRED_REPEAT_COUNT:
            raise ValueError(f"repeat plan contains duplicate {key}")
    body = {
        "schema_version": _PLAN_SCHEMA,
        "status": "PLANNED_NOT_EXECUTED",
        "required_repeat_count": _REQUIRED_REPEAT_COUNT,
        "required_relation_identities": required_relations,
        "instances": instances,
    }
    return {**body, "plan_digest": canonical_hash(body)}


def collision_policy() -> dict[str, Any]:
    return {
        "version": "RES407-C08-REPEAT-COLLISION-POLICY@1.0.0",
        "reject_duplicate_fields": (
            "candidate_id",
            "payload_digest",
            "seed_block",
            "seed_namespace",
        ),
        "reject_unexpected_contamination_identity_collisions": True,
        "allowed_shared_batch_identity": "expert_author_batch",
        "required_exact_relation_identities": (
            "isolation_cluster_id",
            "generator_family",
            "expert_author_batch",
        ),
        "exact_13_token_shingles": "reject staged-to-staged and staged-to-existing collisions",
        "structural_contract": (
            "require exact lane, cell, split, generator, authority, and relation match"
        ),
        "failure_action": (
            "STOP_AND_INVALIDATE_THE_WHOLE_MATERIALIZATION_ATTEMPT; never substitute a seed"
        ),
    }


def _identity_values(value: Any) -> tuple[str, ...]:
    if value is None or value == () or value == []:
        return ()
    if isinstance(value, str) and value:
        return (value,)
    if isinstance(value, tuple | list) and all(isinstance(item, str) and item for item in value):
        return tuple(value)
    raise ValueError("contamination identities must be non-empty strings or string sequences")


def validate_materialization_collisions(
    candidates: Sequence[Mapping[str, Any]],
    *,
    plan: Mapping[str, Any],
    existing_identity_values: Mapping[str, Sequence[str]] | None = None,
    existing_questions: Mapping[str, str] | None = None,
) -> None:
    """Fail closed on identity, payload, relation, or exact-shingle collisions."""

    if plan.get("status") != "PLANNED_NOT_EXECUTED" or canonical_hash(
        _without(plan, "plan_digest")
    ) != plan.get("plan_digest"):
        raise ValueError("materialization requires a valid, authorized repeat plan")
    planned = plan.get("instances")
    if (
        not isinstance(planned, Sequence)
        or isinstance(planned, str)
        or len(planned) != _REQUIRED_REPEAT_COUNT
        or len(candidates) != _REQUIRED_REPEAT_COUNT
        or not all(isinstance(item, Mapping) for item in planned)
        or not all(isinstance(item, Mapping) for item in candidates)
    ):
        raise ValueError("materialization candidate count differs from the 48-repeat plan")
    ordinals = tuple(item.get("ordinal") for item in candidates)
    if any(type(ordinal) is not int for ordinal in ordinals):
        raise ValueError("materialization repeat ordinals must be integers")
    by_ordinal = {item.get("ordinal"): item for item in candidates}
    if set(by_ordinal) != set(range(_REQUIRED_REPEAT_COUNT)):
        raise ValueError("materialization ordinals differ from the repeat plan")
    planned_by_ordinal = {item["ordinal"]: item for item in planned}
    match_fields = (
        "candidate_id",
        "allocation_digest",
        "seed_block",
        "seed_namespace",
        "lane_id",
        "cell",
        "locked_split",
        "generator_contract",
        "authority_digest",
        "generator_authority_digest",
        "structural_contract_digest",
        "relation_identities",
    )
    for ordinal, candidate in by_ordinal.items():
        expected = planned_by_ordinal.get(ordinal)
        mismatch = next(
            (
                key
                for key in match_fields
                if expected is None or candidate.get(key) != expected.get(key)
            ),
            None,
        )
        if mismatch == "relation_identities":
            raise ValueError("materialized relation/colocation identities differ from the plan")
        if mismatch is not None:
            raise ValueError(f"materialized identity differs from its plan: {mismatch}")

    existing = existing_identity_values or {}
    for field in ("candidate_id", "payload_digest", "seed_block", "seed_namespace"):
        values = tuple(item.get(field) for item in candidates)
        if any(not isinstance(value, str) or not value for value in values):
            raise ValueError(f"materialization candidate is missing {field}")
        if len(set(values)) != len(values) or set(values).intersection(existing.get(field, ())):
            raise ValueError(f"materialization collision: {field}")

    for candidate in candidates:
        if candidate.get("relation_identities") != plan.get("required_relation_identities"):
            raise ValueError("materialized relation/colocation identities differ from the contract")

    contamination: dict[str, list[str]] = {kind: [] for kind in _EXPECTED_CONTAMINATION_KINDS}
    for candidate in candidates:
        identities = candidate.get("contamination_identities")
        if not isinstance(identities, Mapping) or set(identities) != _EXPECTED_CONTAMINATION_KINDS:
            raise ValueError("materialization candidate lacks contamination identities")
        candidate_id = candidate["candidate_id"]
        expected_contamination = {
            "source_family": f"PSE-V1-SYNTHETIC-FAMILY:{candidate_id}",
            "general_artifact": f"candidate:{candidate_id}",
            "benchmark_artifact": f"candidate:{candidate_id}",
            "training_exclusion": f"qualification-exclusion:{candidate_id}",
            "expert_author_batch": plan["required_relation_identities"]["expert_author_batch"],
            "generator_seed_namespace": candidate["seed_namespace"],
            "generator_seed_block": candidate["seed_block"],
            "source_documents_artifacts_constructs_and_provider_ids": (),
        }
        contamination_mismatch = next(
            (
                kind
                for kind, value in expected_contamination.items()
                if identities.get(kind) != value
            ),
            None,
        )
        if contamination_mismatch is not None:
            raise ValueError(
                "materialized contamination identity differs from the plan: "
                f"{contamination_mismatch}"
            )
        for kind, value in identities.items():
            contamination.setdefault(kind, []).extend(_identity_values(value))
    for kind, identity_values in contamination.items():
        if kind in _EXPECTED_SHARED_CONTAMINATION:
            if len(set(identity_values)) > 1 or set(identity_values).intersection(
                existing.get(kind, ())
            ):
                raise ValueError(f"unexpected shared contamination identity: {kind}")
        elif len(set(identity_values)) != len(identity_values) or set(identity_values).intersection(
            existing.get(kind, ())
        ):
            raise ValueError(f"materialization collision: contamination identity {kind}")

    from scripts.res407_c08_generator_qualification import check_exact_shingle_independence

    questions: dict[str, str] = {}
    for item in candidates:
        candidate_id, question = item.get("candidate_id"), item.get("question")
        if not isinstance(candidate_id, str) or not isinstance(question, str) or not question:
            raise ValueError("materialization candidate lacks question text for shingle checking")
        questions[candidate_id] = question
    check_exact_shingle_independence(questions, dict(existing_questions or {}))


def _source_code_evidence() -> tuple[dict[str, str], ...]:
    return tuple(
        {
            "path": relative,
            "sha256": "sha256:" + hashlib.sha256((_REPOSITORY / relative).read_bytes()).hexdigest(),
        }
        for relative in _SOURCE_FILES
    )


def _checked_report(path: Path, digest_key: str) -> dict[str, Any]:
    report: Any = json.loads((_REPOSITORY / path).read_text(encoding="utf-8"))
    if not isinstance(report, dict):
        raise ValueError(f"persisted RES-407 report must be an object: {path.as_posix()}")
    if canonical_hash(_without(report, digest_key)) != report.get(digest_key):
        raise ValueError(f"persisted RES-407 report digest mismatch: {path.as_posix()}")
    return report


def _derive_report(
    structural: dict[str, Any],
    generator_report: dict[str, Any],
    sufficiency: dict[str, Any],
    verification: Mapping[str, Any],
) -> dict[str, Any]:
    target = next(
        item
        for item in structural["archetype_contract_inventory"]
        if item["lane_id"] == _LANE_ID and item["cell"] == list(_CELL)
    )
    repeat_record = previous.repeat_authority(target)
    if repeat_record != generator_report["repeat_authority"]:
        raise ValueError("current repeat authority differs from the persisted qualification")
    repeat = parse_repeat_authority(repeat_record)
    winning = tuple(
        item
        for item in sufficiency["real_c08_repair_vector"]
        if item["lane_id"] == _LANE_ID and item["cell"] == list(_CELL)
    )
    if (
        sufficiency["real_c08_structural_status"] != "FEASIBLE"
        or sufficiency["real_c08_min_additions"] != _REQUIRED_REPEAT_COUNT
        or sufficiency["cardinality_optimality"] != "PROVEN"
        or len(winning) != 1
        or winning[0]["count"] != _REQUIRED_REPEAT_COUNT
        or winning[0]["split_lock"] != _SPLIT.value
        or winning[0]["split_counts"] != [[_SPLIT.value, _REQUIRED_REPEAT_COUNT]]
    ):
        raise ValueError("accepted structural witness no longer matches the 48-repeat target")
    _engine_reference, _rfd_reference, generic_refusal = _production_authoring_engine_references()
    if generic_refusal.status.value != "REFUSAL":
        raise ValueError("current F05 generic template is not bound to a refusal reference")
    protocol_template = {
        "reference": "live RES-71 no-operation refusal reference",
        "reference_case_id": generic_refusal.case_id,
        "reference_status": generic_refusal.status.value,
        "family": "F05 generic-refusal path",
        "seed_to_context": "_scenario_ids(seed_block) and _production_synthetic_context",
        "question_classes": tuple(item.value for item in question_classes_for_cell("C08", "F05")),
        "adversarial_tags": _production_adversarial_tags("C08", "F05"),
        "f05_question_focus": _SYNTHETIC_QUESTION_FOCUS["F05"],
        "question_template": (
            "_production_synthetic_question with the registered C08:F05 focus and adversarial tag"
        ),
        "numeric_gold_generated": False,
    }

    source_evidence = _source_code_evidence()
    evidence = {
        "entry_head": ENTRY_HEAD,
        "structural_report_receipt_digest": structural["receipt_digest"],
        "generator_qualification_digest": generator_report["qualification_digest"],
        "real_c08_sufficiency_report_digest": sufficiency["report_digest"],
        "governed_archetype_contract_digest": structural["governed_archetype_contract_digest"],
        "live_supply_inventory_digest": structural["live_supply_inventory_digest"],
        "external_digest_verification": {
            key: value
            for key, value in verification.items()
            if key not in {"geometry", "archetype_record"}
        },
        "repeat_authority_source": repeat_record,
        "source_code_evidence": source_evidence,
        "source_code_evidence_digest": canonical_hash(source_evidence),
    }
    evidence_digest = canonical_hash(evidence)
    distinctness = {
        "required_unique": (
            "candidate_id",
            "payload_digest",
            "seed_block",
            "seed_namespace",
            "source_family",
            "candidate_artifact_ids",
            "training_exclusion_ids",
        ),
        "candidate_id_derivation": (
            "candidate ID binds RES-407, C08:F05, PUBLIC_DEVELOPMENT, and repeat ordinal"
        ),
        "seed_identity": (
            "unique seed block and split-qualified namespace; candidate ID uniqueness alone "
            "is insufficient"
        ),
        "generator_identity": {
            "generator_id": target["generator_id"],
            "generator_version": target["generator_version"],
            "generator_family": target["generator_family"],
        },
        "source_family_derivation": "PSE-V1-SYNTHETIC-FAMILY:{candidate_id}",
        "author_batch": "shared agent-process:codex:RES-115-CASE-AUTHORING-001B",
        "isolation_cluster": "shared PSE-V1-SYNTHETIC-CLUSTER:PUBLIC_DEVELOPMENT",
        "expected_shared_identity_kinds": (
            "isolation_cluster_id",
            "generator_family",
            "expert_author_batch",
        ),
        "structural_binding": {
            "lane_id": _LANE_ID,
            "cell": _CELL,
            "locked_split": _SPLIT.value,
            "structural_contract_digest": sufficiency["real_c08_repair_vector_digest"],
        },
        "exact_shingles": (
            "must be collision-free within the staged batch and against the existing 449"
        ),
    }
    distinctness_digest = canonical_hash(distinctness)
    policy = collision_policy()
    policy_digest = canonical_hash(policy)

    plan: dict[str, Any] | None = None
    if repeat["status"] == "PROVEN_SUFFICIENT_FOR_48":
        plan = build_repeat_plan(
            repeat_record,
            target_archetype=target,
            repeat_authority_digest=evidence_digest,
            structural_contract_digest=sufficiency["real_c08_repair_vector_digest"],
        )
        plan_status = "PLANNED_NOT_EXECUTED"
    elif repeat["status"] == "PROVEN_INSUFFICIENT_FOR_48":
        plan_status = "NOT_CREATED_REPEAT_CAP_BELOW_48"
    else:
        plan_status = "NOT_CREATED_REPEAT_AUTHORITY_UNKNOWN"

    capability = current_c08_repair_capability(repeat_record)
    body = {
        "schema_version": _SCHEMA,
        "mission": "RES-407 C08 48-repeat authority qualification",
        "entry_head": ENTRY_HEAD,
        "repeat_authority_status": repeat["status"],
        "authorized_repeat_count_min": repeat["authorized_repeat_count_min"],
        "authorized_repeat_count_max": repeat["authorized_repeat_count_max"],
        "repeat_authority_evidence": evidence,
        "repeat_authority_evidence_digest": evidence_digest,
        "authoring_authority_trace": {
            "lane": {
                "lane_id": target["lane_id"],
                "lane_digest": target["lane_digest"],
                "capacity_status": target["capacity_semantics"]["status"],
                "capacity_certainty": target["capacity_semantics"]["certainty"],
                "capacity_unit": "unique split-locked synthetic seed block",
                "capacity_rule": target["capacity_semantics"]["rule"],
                "remaining_finite_capacity": target["capacity_semantics"][
                    "remaining_finite_capacity"
                ],
                "seed_namespace_behavior": target["seed_namespace_behavior"],
                "implemented_recipe_path_multiplicity": target[
                    "implemented_recipe_path_multiplicity"
                ],
            },
            "generator": {
                "generator_id": target["generator_id"],
                "generator_version": target["generator_version"],
                "generator_family": target["generator_family"],
                "output_contract": target["generator_contract"],
                "authority_digest": target["authority_digest"],
            },
            "protocol_template": protocol_template,
            "seed_namespace": "PSE-V1/{split}/{generator_id}:{version}@{seed_block}",
            "current_seed_block_rule": repeat_record["seed_block_allocation_rule"],
            "current_candidate_id_rule": repeat_record["candidate_id_allocation_rule"],
            "repeat_semantics": {
                "implemented_options_per_lane_cell": repeat_record[
                    "current_recipe_options_per_lane_cell"
                ],
                "candidate_id_has_repeat_ordinal": repeat_record["repeat_ordinal_in_candidate_id"],
                "seed_block_rule_has_repeat_ordinal": repeat_record[
                    "repeat_ordinal_in_seed_block_rule"
                ],
                "seed_reuse_forbidden": repeat_record["seed_reuse_forbidden"],
                "authorized_repeat_count": "UNSPECIFIED",
            },
            "existing_relation_evidence": {
                key: generator_report["existing_449_relation_summary"][key]
                for key in (
                    "candidate_count",
                    "matching_public_cluster_count",
                    "matching_generator_family_count",
                    "matching_author_batch_count",
                    "new_to_existing_relation_semantics",
                    "finding",
                )
            },
            "isolation_guarantees": target["isolation_guarantees"],
            "relation_behavior": target["relation_behavior"],
            "governance_evidence": {
                "historical_acceptance_receipt": "docs/qualification/RES-407-ACCEPTANCE-RECEIPT.md",
                "structural_geometry": "docs/qualification/RES-407-STRUCTURAL-GEOMETRY.md",
                "current_generator_report_digest": generator_report["qualification_digest"],
            },
        },
        "distinctness_contract": distinctness,
        "distinctness_contract_digest": distinctness_digest,
        "repeat_plan_status": plan_status,
        "repeat_plan": plan,
        "repeat_plan_digest": None if plan is None else plan["plan_digest"],
        "planned_repeat_count": 0 if plan is None else _REQUIRED_REPEAT_COUNT,
        "collision_policy": policy,
        "collision_policy_digest": policy_digest,
        "current_c08_repair_capability": capability,
        "current_c08_repair_capability_reason": (
            "The accepted structural minimum is 48. Current repeat authority has no numeric "
            "maximum; "
            "the rule-governed lane and implementation capacity do not establish permission for 48."
            if repeat["status"] == "UNKNOWN"
            else (
                "Derived from the explicit authorized repeat bound and the accepted "
                "48-addition structural minimum."
            )
        ),
        "accepted_structural_witness": {
            "status": sufficiency["real_c08_structural_status"],
            "minimum_additions": sufficiency["real_c08_min_additions"],
            "cardinality_optimality": sufficiency["cardinality_optimality"],
            "vector_digest": sufficiency["real_c08_repair_vector_digest"],
            "vector": winning,
            "optimization_rerun": False,
        },
        "concrete_candidates_generated": 0,
        "seeds_materialized": 0,
        "candidate_materialization_invoked": False,
        "ready_for_materialization": plan is not None,
        "ready_for_authority_expansion": plan is None,
        "next_step": (
            "MATERIALIZATION_MAY_BE_PLANNED_AFTER_AUTHORITY_REVIEW"
            if plan is not None
            else "EXPAND_REPEAT_AND_SEED_BLOCK_AUTHORITY_THEN_REQUALIFY"
        ),
    }
    body["report_digest"] = canonical_hash(body)
    return body


def build_report() -> dict[str, Any]:
    structural = _checked_report(STRUCTURAL_REPORT_PATH, "receipt_digest")
    generator_report = _checked_report(GENERATOR_REPORT_PATH, "qualification_digest")
    sufficiency = _checked_report(SUFFICIENCY_REPORT_PATH, "report_digest")
    verification = previous.verify_persisted_digests(structural)
    return _derive_report(structural, generator_report, sufficiency, verification)


def main() -> None:
    report = build_report()
    path = _REPOSITORY / REPORT_PATH
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"REPEAT_AUTHORITY_STATUS={report['repeat_authority_status']}")
    print(f"AUTHORIZED_REPEAT_COUNT_MIN={report['authorized_repeat_count_min']}")
    print(f"AUTHORIZED_REPEAT_COUNT_MAX={report['authorized_repeat_count_max']}")
    print(f"DISTINCTNESS_CONTRACT_DIGEST={report['distinctness_contract_digest']}")
    print(f"REPEAT_AUTHORITY_EVIDENCE_DIGEST={report['repeat_authority_evidence_digest']}")
    print(f"C08_48_REPEAT_PLAN_STATUS={report['repeat_plan_status']}")
    print(f"C08_48_REPEAT_PLAN_DIGEST={report['repeat_plan_digest']}")
    print(f"PLANNED_REPEAT_COUNT={report['planned_repeat_count']}")
    print(f"COLLISION_POLICY_DIGEST={report['collision_policy_digest']}")
    print(f"CURRENT_C08_REPAIR_CAPABILITY={report['current_c08_repair_capability']}")
    print(f"CONCRETE_CANDIDATES_GENERATED={report['concrete_candidates_generated']}")
    print(f"SEEDS_MATERIALIZED={report['seeds_materialized']}")
    print(f"REPORT_DIGEST={report['report_digest']}")


if __name__ == "__main__":
    main()
