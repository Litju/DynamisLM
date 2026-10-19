#!/usr/bin/env python3
"""Persist structural RES-407 diagnostics without authoring candidate packets."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import replace
from importlib.metadata import version
from pathlib import Path
from typing import Any

_REPOSITORY = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(_REPOSITORY), str(_REPOSITORY / "src")]

from dynamislm.benchmark.constants import (  # noqa: E402
    CRITICAL_ERROR_CLASSES,
    SPLIT_ORDER,
    CaseOrigin,
    SplitName,
)
from dynamislm.benchmark.coverage import COVERAGE_MATRIX  # noqa: E402
from dynamislm.benchmark.production_store import DEFAULT_PRODUCTION_ROOT  # noqa: E402
from dynamislm.benchmark.public_repository import (  # noqa: E402
    validate_production_private_material_absent,
)
from dynamislm.benchmark.repair_geometry import (  # noqa: E402
    CAPACITY_RELAXATION,
    REPAIR_MASTER_SOLVER_CONFIG,
    RES407_STRUCTURAL_REPAIR_MASTER_PROFILE_V1,
    RepairCardinalityTrial,
    RepairGeometry,
    RepairMasterResult,
    RepairSignature,
    RepairSignatureCount,
    SplitCapacityCertificate,
    _structural_repair_model,
    archetype_structural_contracts,
    bind_split_capacity_certificate,
    build_compact_ideal_repair_signatures,
    build_ideal_repair_signatures,
    build_optimistic_c08_signatures,
    capacity_problem,
    classify_archetype_repair,
    compare_ideal_to_governed_c08,
    compute_split_capacity_envelope,
    derive_archetype_saturation_bounds,
    derive_governed_archetypes,
    solve_repair_cardinality_decision,
    solve_structural_repair_master,
    structural_bottleneck_evidence,
)
from dynamislm.benchmark.selection_contracts import (  # noqa: E402
    AssignmentState,
    ConstraintKind,
    FeatureKind,
    SelectionFeature,
    SelectionSolverConfig,
    ValidationStatus,
)
from dynamislm.benchmark.selection_validation import validate_final_selection  # noqa: E402
from dynamislm.serialization import (  # noqa: E402
    SERIALIZATION_VERSION,
    canonical_hash,
    from_canonical_json,
    type_identifier,
)
from scripts import res406_pool_qualification as res406  # noqa: E402
from scripts import res407_governed_backfill as legacy  # noqa: E402
from scripts import res451_base_infeasibility as res451  # noqa: E402

_IDEAL_MASTER_SCOPE = (
    "GLOBAL_OVER_IDEAL_SELECTION_RELEVANT_SIGNATURES; additions are independent; "
    "total additions <= FINAL_N=434 because no feasible assignment selects more"
)
_OPTIMISTIC_C08_SCOPE = (
    "CURRENT_12_C08_ARCHETYPES; optimistic maximal C08 feature support and independent "
    "relations; split locks and lane capacities retained; total additions <= FINAL_N=434"
)
_GOVERNED_MASTER_SCOPE = (
    "NO_OPTIMALITY_CLAIM: guaranteed feature vector and contamination/shingle behavior "
    "are unknown; the current 12 archetypes cannot be modeled as exact repeated y[a] counts"
)
_STRUCTURAL_COMPARISON_SCHEMA = "RES407-GOVERNED-STRUCTURAL-COMPARISON@1.4.0"
_IDEAL_REPORT_PATH = Path("reports/performance_science_eval/res407_repair_geometry.json")


def _decode_ideal_vector(
    signatures: tuple[RepairSignature, ...],
    raw_vector: Any,
    minimum: int,
) -> tuple[RepairSignatureCount, ...]:
    catalog = {item.signature_id: item for item in signatures}
    vector = []
    seen: set[str] = set()
    for item in raw_vector:
        signature_id = item.get("signature_digest")
        signature = catalog.get(signature_id)
        if signature is None or signature_id in seen:
            raise ValueError("ideal winner contains an unknown or duplicate signature")
        seen.add(signature_id)
        split_counts = tuple(
            (SplitName(split_name), int(count))
            for split_name, count in sorted(
                item["split_counts"].items(),
                key=lambda pair: SPLIT_ORDER.index(SplitName(pair[0])),
            )
        )
        if sum(count for _split, count in split_counts) != item.get("count") or any(
            count < 1 or split not in signature.split_compatibility for split, count in split_counts
        ):
            raise ValueError("ideal winner counts do not match its signature")
        vector.append(RepairSignatureCount(signature, split_counts))
    result = tuple(sorted(vector, key=lambda item: item.signature.signature_id))
    if sum(item.total_count for item in result) != minimum:
        raise ValueError("ideal winner vector does not match its proven minimum")
    return result


def _accepted_ideal_witness(
    geometry: RepairGeometry,
) -> tuple[tuple[RepairSignature, ...], tuple[RepairSignatureCount, ...], dict[str, Any]]:
    report = json.loads((_REPOSITORY / _IDEAL_REPORT_PATH).read_text(encoding="utf-8"))
    if report.get("repair_geometry_digest") != geometry.geometry_digest:
        raise ValueError("accepted ideal result belongs to different repair geometry")
    if report.get("ideal_cardinality_optimality") != "PROVEN":
        raise ValueError("ideal cardinality lower bound is not proven")
    minimum = report.get("ideal_min_additions")
    if not isinstance(minimum, int) or minimum < 1:
        raise ValueError("accepted ideal minimum is malformed")
    signatures = build_compact_ideal_repair_signatures(geometry)
    catalog_digest = canonical_hash(signatures)
    trials = report.get("ideal_cardinality_trials")
    if not isinstance(trials, list):
        raise ValueError("accepted ideal result lacks cardinality trials")
    lower = next(
        (
            trial
            for trial in trials
            if trial.get("maximum_additions") == minimum - 1 and trial.get("status") == "INFEASIBLE"
        ),
        None,
    )
    upper = next(
        (
            trial
            for trial in trials
            if trial.get("maximum_additions") == minimum and trial.get("status") == "FEASIBLE"
        ),
        None,
    )
    if lower is None or upper is None:
        raise ValueError("accepted ideal result lacks adjacent infeasible/feasible proofs")
    if any(trial.get("signature_inventory_digest") != catalog_digest for trial in (lower, upper)):
        raise ValueError("accepted ideal trials do not bind the current compact signature domain")
    winning_vector = _decode_ideal_vector(
        signatures, report.get("ideal_repair_signatures", ()), minimum
    )
    proof = {
        "status": "PASS",
        "minimum_additions": minimum,
        "cardinality_optimality": report["ideal_cardinality_optimality"],
        "geometry_digest": geometry.geometry_digest,
        "signature_count": len(signatures),
        "signature_inventory_digest": catalog_digest,
        "lower_trial_digest": lower["trial_digest"],
        "upper_trial_digest": upper["trial_digest"],
        "ideal_result_digest": report["ideal_repair_digest"],
        "ideal_cardinality_result_digest": report["ideal_cardinality_result_digest"],
        "winning_vector_digest": canonical_hash(winning_vector),
    }
    return signatures, winning_vector, proof


def _ideal_winner_inventory(
    geometry: RepairGeometry,
    vector: tuple[RepairSignatureCount, ...],
) -> tuple[dict[str, Any], ...]:
    feature_constraints = geometry.constraints(ConstraintKind.FEATURE_MINIMUM)
    final_count = next(
        item
        for item in geometry.problem.constraint_set.constraints
        if item.kind is ConstraintKind.FINAL_COUNT
    )
    split_constraints = {
        item.split: item
        for item in geometry.problem.constraint_set.constraints
        if item.kind is ConstraintKind.SPLIT_COUNT
    }
    inventory = []
    for item in vector:
        signature = item.signature
        support_by_split = []
        for split, count in item.split_counts:
            constraint_ids = tuple(
                sorted(
                    (
                        constraint.constraint_id
                        for constraint in feature_constraints
                        if constraint.split is split
                        and constraint.feature in signature.guaranteed_features
                    ),
                    key=str.encode,
                )
            )
            support_by_split.append(
                {
                    "split": split.value,
                    "count": count,
                    "split_count_constraint": split_constraints[split].constraint_id,
                    "feature_minimum_constraints": constraint_ids,
                }
            )
        feature_kinds = {feature.kind for feature in signature.guaranteed_features}
        answerability = (
            "ANSWERABLE_PROFILE"
            if FeatureKind.ANSWERABLE in feature_kinds
            else (
                "C18_REFUSAL_PROFILE"
                if FeatureKind.C18_REFUSAL in feature_kinds
                else "NO_ANSWERABILITY_OR_REFUSAL_FEATURE_CLAIM"
            )
        )
        inventory.append(
            {
                "signature_digest": signature.signature_id,
                "count": item.total_count,
                "capability": signature.cell[0],
                "family": signature.cell[1],
                "cell": signature.cell,
                "guaranteed_features": tuple(
                    {"kind": feature.kind.value, "key": feature.key}
                    for feature in signature.guaranteed_features
                ),
                "answerability_refusal_behavior": answerability,
                "origin_semantics": signature.origin.value,
                "split_compatibility": tuple(
                    split.value for split in signature.split_compatibility
                ),
                "split_counts": tuple(support_by_split),
                "isolation_assumption": signature.isolation_identity_behavior,
                "relation_assumption": signature.relation_behavior,
                "contamination_assumption": (
                    "NO_NEW_CONTAMINATION_OR_EXACT_SHINGLE_EDGES; IDEAL RELAXATION"
                ),
                "why_this_signature_contributes": (
                    "It supplies the listed cell, row-tag, row-error, critical-error, and "
                    "answerability requirements in its allocated split(s); each counted unit "
                    f"also occupies one of FINAL_COUNT={final_count.minimum} selected slots. "
                    "The joint K-1 infeasibility proof, rather than this row alone, establishes "
                    "the 12-unit minimum."
                ),
            }
        )
    return tuple(inventory)


def _governed_archetype_contract_inventory(
    geometry: RepairGeometry,
    archetypes: tuple[Any, ...],
) -> tuple[dict[str, Any], ...]:
    contracts = {
        (item.lane_id, item.cell): item
        for item in archetype_structural_contracts(geometry, archetypes)
    }
    rows = []
    for archetype in archetypes:
        contract = contracts[archetype.lane_id, archetype.cell]
        split = archetype.locked_split
        if split is None or archetype.cell[0] != "C08":
            raise ValueError("live C08 archetype lacks its guaranteed split lock or C08 cell")
        cluster_id = f"PSE-V1-SYNTHETIC-CLUSTER:{split.value}"
        prior_members = tuple(
            candidate
            for candidate in geometry.problem.candidates
            if candidate.isolation_cluster_id == cluster_id
        )
        prior_lock_counts: dict[str, int] = {}
        for candidate in prior_members:
            lock = (
                candidate.locked_split.value if candidate.locked_split is not None else "UNLOCKED"
            )
            prior_lock_counts[lock] = prior_lock_counts.get(lock, 0) + 1
        rows.append(
            {
                "archetype_digest": canonical_hash(archetype),
                "lane_id": archetype.lane_id,
                "authority_ref": archetype.authority_ref,
                "authority_digest": archetype.authority_digest,
                "lane_digest": archetype.lane_digest,
                "origin": archetype.origin.value,
                "cell": archetype.cell,
                "locked_split": split.value,
                "guaranteed_features": archetype.guaranteed_features,
                "feature_vector_complete": archetype.feature_behavior_complete,
                "answerability_refusal_semantics": {
                    "certainty": "GUARANTEED",
                    "value": "NON_NUMERIC_REFUSAL_CONTEXT; NUMERIC ANSWER FORBIDDEN",
                    "authority": archetype.materializer_contract,
                },
                "generator_family": archetype.lane_id.removeprefix("synthetic:"),
                "generator_id": archetype.materializer_identity,
                "generator_version": archetype.materializer_version,
                "generator_contract": archetype.materializer_contract,
                "seed_namespace_behavior": {
                    "certainty": "BOUNDED",
                    "value": "UNIQUE SEED BLOCK PER AUTHORIZED LANE UNIT; REPEAT COUNT UNSPECIFIED",
                    "rule": archetype.capacity_rule,
                },
                "implemented_recipe_path_multiplicity": {
                    "certainty": "BOUNDED",
                    "options_per_lane_cell": 1,
                    "repeat_ordinal_in_candidate_id": False,
                    "repeat_ordinal_in_seed_block_rule": False,
                    "evidence": (
                        "The existing RES-407 option helper _synthetic_option_recipes "
                        "emits one recipe per supported lane cell and binds its ID and seed "
                        "block to lane/cell, with no repeated-instance ordinal."
                    ),
                },
                "isolation_guarantees": {
                    "certainty": "GUARANTEED",
                    "identity_requirement_digests": archetype.identity_requirements,
                    "fresh_independent_identity": False,
                },
                "contamination_shingle_guarantees": {
                    "certainty": "UNKNOWN",
                    "value": "EXACT SHINGLE COLLISIONS AND CONTENT CONTAMINATION NOT RULED OUT",
                },
                "relation_behavior": {
                    "certainty": "GUARANTEED",
                    "value": archetype.relation_behavior_guarantee,
                    "prior_cluster_member_count": len(prior_members),
                    "prior_cluster_member_locks": tuple(sorted(prior_lock_counts.items())),
                    "other_relation_behavior": "UNKNOWN",
                },
                "repeated_instance_independence_interchangeability": {
                    "certainty": "UNKNOWN",
                    "independent": False,
                    "interchangeable": None,
                },
                "capacity_semantics": {
                    "certainty": "BOUNDED",
                    "status": archetype.capacity_status.value,
                    "remaining_finite_capacity": archetype.remaining_finite_capacity,
                    "rule": archetype.capacity_rule,
                },
                "structural_property_claims": tuple(
                    {
                        "property": claim.field,
                        "classification": claim.certainty.value,
                        "value": claim.value,
                        "evidence": claim.evidence,
                    }
                    for claim in contract.claims
                ),
            }
        )
    return tuple(sorted(rows, key=lambda item: (item["lane_id"].encode(), item["cell"])))


def _ideal_relaxation_proof(
    geometry: RepairGeometry,
    ideal_signatures: tuple[RepairSignature, ...],
    archetypes: tuple[Any, ...],
) -> dict[str, Any]:
    mappings = []
    failures = []
    feature_maxima = tuple(
        constraint.constraint_id
        for constraint in geometry.constraints(ConstraintKind.FEATURE_MINIMUM)
        if constraint.maximum is not None
    )
    for archetype in archetypes:
        matches = tuple(
            signature
            for signature in ideal_signatures
            if signature.cell == archetype.cell
            and signature.origin is archetype.origin
            and archetype.locked_split in signature.split_compatibility
            and set(archetype.guaranteed_features).issubset(signature.guaranteed_features)
        )
        if not matches:
            failures.append(archetype.lane_id + ":" + ":".join(archetype.cell))
            continue
        selected = min(
            matches,
            key=lambda item: (-len(item.guaranteed_features), item.signature_id),
        )
        mappings.append(
            {
                "archetype_digest": canonical_hash(archetype),
                "lane_id": archetype.lane_id,
                "cell": archetype.cell,
                "origin": archetype.origin.value,
                "locked_split": archetype.locked_split.value,
                "ideal_signature_digest": selected.signature_id,
                "guaranteed_feature_superset": True,
                "ideal_answerable_feature": any(
                    feature.kind is FeatureKind.ANSWERABLE
                    for feature in selected.guaranteed_features
                ),
                "ideal_relation_behavior": selected.relation_behavior,
                "ideal_isolation_behavior": selected.isolation_identity_behavior,
                "dominance": (
                    "CELL, ORIGIN, AND SPLIT RETAINED; IDEAL FEATURES/IDENTITIES ARE "
                    "MORE PERMISSIVE; REAL REFUSAL DOES NOT CLAIM ANSWERABILITY"
                ),
            }
        )
    status = (
        "PASS"
        if not failures and not feature_maxima and len(mappings) == len(archetypes)
        else "PARTIAL"
    )
    proof = {
        "status": status,
        "scope": "CURRENT LIVE V1.3 RESIDUAL GOVERNED ARCHETYPES ONLY",
        "geometry_digest": geometry.geometry_digest,
        "ideal_signature_inventory_digest": canonical_hash(ideal_signatures),
        "archetype_inventory_digest": canonical_hash(archetypes),
        "feature_maximum_constraints": feature_maxima,
        "mappings": tuple(
            sorted(
                mappings, key=lambda item: item["lane_id"].encode() + repr(item["cell"]).encode()
            )
        ),
        "unmapped_archetypes": tuple(sorted(failures, key=str.encode)),
        "hard_constraint_dominance": (
            "FINAL_COUNT and ORIGIN_BOUNDS remain exact; SYNTHETIC_SPLIT_LOCK is retained; "
            "the ideal feature profile is a superset of current guaranteed features; "
            "no FEATURE_MINIMUM maximum exists in this bound problem, so added typed features "
            "cannot reduce feasibility; ideal fresh identities and omitted relation/contamination "
            "edges only relax assignment restrictions; review/qualification is assumed satisfied. "
            "Synthetic additions remain NOT_MUTATION, so mutation-lineage requirements apply "
            "only to the unchanged base problem. Current unknown output features are not counted "
            "as guarantees. Future authorities are outside this proof scope."
        ),
    }
    proof["proof_digest"] = canonical_hash(proof)
    return proof


def _capability_gap(
    geometry: RepairGeometry,
    vector: tuple[RepairSignatureCount, ...],
    archetypes: tuple[Any, ...],
) -> dict[str, Any]:
    current_cells = {item.cell for item in archetypes}
    current_origins = {item.origin for item in archetypes}
    current_features = {feature for item in archetypes for feature in item.guaranteed_features}
    locks_by_cell: dict[tuple[str, str], set[SplitName]] = {}
    for archetype in archetypes:
        if archetype.locked_split is not None:
            locks_by_cell.setdefault(archetype.cell, set()).add(archetype.locked_split)
    rows = []
    for item in vector:
        signature = item.signature
        dimensions = []
        if signature.cell not in current_cells:
            dimensions.append(
                {
                    "dimension": "CELL",
                    "status": "NO_MATCH",
                    "required": signature.cell,
                    "available": tuple(sorted(current_cells)),
                }
            )
        if signature.origin not in current_origins:
            dimensions.append(
                {
                    "dimension": "ORIGIN",
                    "status": "NO_MATCH",
                    "required": signature.origin.value,
                    "available": tuple(sorted(origin.value for origin in current_origins)),
                }
            )
        missing_features = tuple(
            feature for feature in signature.guaranteed_features if feature not in current_features
        )
        if missing_features:
            dimensions.append(
                {
                    "dimension": "GUARANTEED_FEATURES",
                    "status": "PARTIAL" if signature.cell in current_cells else "NO_MATCH",
                    "required": tuple(
                        (feature.kind.value, feature.key) for feature in missing_features
                    ),
                    "available_guaranteed_features": tuple(
                        (feature.kind.value, feature.key)
                        for feature in sorted(current_features, key=lambda f: (f.kind.value, f.key))
                    ),
                }
            )
        required_splits = {split for split, _count in item.split_counts}
        available_splits = locks_by_cell.get(signature.cell, set())
        if required_splits - available_splits:
            dimensions.append(
                {
                    "dimension": "SPLIT_LOCK",
                    "status": "PARTIAL" if available_splits else "NO_MATCH",
                    "required": tuple(
                        split.value
                        for split in sorted(required_splits, key=lambda s: SPLIT_ORDER.index(s))
                    ),
                    "available_for_required_cell": tuple(
                        split.value
                        for split in sorted(available_splits, key=lambda s: SPLIT_ORDER.index(s))
                    ),
                }
            )
        if FeatureKind.ANSWERABLE in {feature.kind for feature in signature.guaranteed_features}:
            dimensions.append(
                {
                    "dimension": "ANSWERABILITY_REFUSAL",
                    "status": "NO_MATCH",
                    "required": "ANSWERABLE",
                    "available": "GUARANTEED_NON_NUMERIC_REFUSAL_CONTEXT",
                }
            )
        dimensions.extend(
            (
                {
                    "dimension": "FRESH_ISOLATION",
                    "status": "PARTIAL",
                    "required": "FRESH_UNIQUE",
                    "available": "SHARED_SPLIT_AND_GENERATOR_FAMILY",
                },
                {
                    "dimension": "REPEATED_INSTANCE_INTERCHANGEABILITY",
                    "status": "UNKNOWN",
                    "required": "STRUCTURALLY_INTERCHANGEABLE",
                    "available": "UNKNOWN",
                },
                {
                    "dimension": "CONTAMINATION_AND_SHINGLES",
                    "status": "UNKNOWN",
                    "required": "NO_NEW_CONTAMINATION_OR_SHINGLE_EDGE",
                    "available": "UNKNOWN",
                },
                {
                    "dimension": "RELATION_COUPLING",
                    "status": "PARTIAL",
                    "required": "INDEPENDENT_FROM_BASE_AND_OTHER_ADDITIONS",
                    "available": "SHARED_SPLIT_CLUSTER; OTHER RELATIONS UNKNOWN",
                },
            )
        )
        classification = "NO_MATCH" if signature.cell not in current_cells else "PARTIAL"
        rows.append(
            {
                "ideal_signature_digest": signature.signature_id,
                "count": item.total_count,
                "cell": signature.cell,
                "origin": signature.origin.value,
                "required_features": tuple(
                    (feature.kind.value, feature.key) for feature in signature.guaranteed_features
                ),
                "selected_splits": tuple(
                    (split.value, count) for split, count in item.split_counts
                ),
                "classification": classification,
                "mismatches": tuple(dimensions),
            }
        )
    gap = {
        "scope": "WINNING IDEAL SIGNATURES VERSUS CURRENT DERIVED V1.3 C08 ARCHETYPES",
        "geometry_digest": geometry.geometry_digest,
        "archetype_inventory_digest": canonical_hash(archetypes),
        "requirements": tuple(rows),
        "inference": "DIAGNOSTIC_ONLY; FEASIBILITY IS DECIDED BY THE OPTIMISTIC SATURATION MASTER",
    }
    gap["gap_digest"] = canonical_hash(gap)
    return gap


def _optimistic_c08_relaxation_proof(
    geometry: RepairGeometry,
    archetypes: tuple[Any, ...],
    signatures: tuple[RepairSignature, ...],
) -> dict[str, Any]:
    rows = {row.capability_id: row for row in COVERAGE_MATRIX}
    arch_by_key = {(item.lane_id, item.cell): item for item in archetypes}
    proof_rows: list[dict[str, Any]] = []
    failures = []
    feature_maxima = tuple(
        constraint.constraint_id
        for constraint in geometry.constraints(ConstraintKind.FEATURE_MINIMUM)
        if constraint.maximum is not None
    )
    for signature in signatures:
        archetype = arch_by_key.get((signature.lane_id, signature.cell))
        if archetype is None or archetype.locked_split is None:
            failures.append(signature.signature_id)
            continue
        row = rows.get(signature.cell[0])
        if row is None:
            failures.append(signature.signature_id)
            continue
        expected_features = {
            SelectionFeature(FeatureKind.CELL, signature.cell),
            *(
                SelectionFeature(FeatureKind.ROW_TAG, (signature.cell[0], tag))
                for tag in row.adversarial_tags
            ),
            *(
                SelectionFeature(FeatureKind.ROW_ERROR, (signature.cell[0], error.value))
                for error in row.error_classes
            ),
            *(
                SelectionFeature(FeatureKind.CRITICAL_ERROR, (error.value,))
                for error in row.error_classes
                if error in CRITICAL_ERROR_CLASSES
            ),
        }
        matching_cluster = f"PSE-V1-SYNTHETIC-CLUSTER:{archetype.locked_split.value}"
        prior = tuple(
            candidate
            for candidate in geometry.problem.candidates
            if candidate.isolation_cluster_id == matching_cluster
        )
        prior_locks_match = all(
            candidate.locked_split is archetype.locked_split for candidate in prior
        )
        valid = (
            signature.origin is archetype.origin is CaseOrigin.DETERMINISTIC_SYNTHETIC
            and signature.split_compatibility == (archetype.locked_split,)
            and set(signature.guaranteed_features) == expected_features
            and FeatureKind.ANSWERABLE
            not in {feature.kind for feature in signature.guaranteed_features}
            and signature.isolation_identity_behavior == "SHARED_SPLIT_AND_GENERATOR_FAMILY"
            and "SHARED_SPLIT_LOCKED_CLUSTER" in signature.relation_behavior
            and "UNKNOWN_SHINGLE_RELATIONS_RELAXED" in signature.relation_behavior
            and "non-numeric" in (archetype.materializer_contract or "").lower()
            and "refusal" in (archetype.materializer_contract or "").lower()
            and prior_locks_match
            and set(archetype.guaranteed_features).issubset(signature.guaranteed_features)
            and not any(
                constraint.maximum is not None
                and constraint.split is archetype.locked_split
                and constraint.feature in signature.guaranteed_features
                for constraint in geometry.constraints(ConstraintKind.FEATURE_MINIMUM)
            )
        )
        if not valid:
            failures.append(signature.signature_id)
        proof_rows.append(
            {
                "signature_digest": signature.signature_id,
                "archetype_digest": canonical_hash(archetype),
                "cell": signature.cell,
                "split_lock_retained": signature.split_compatibility == (archetype.locked_split,),
                "numeric_answerability_not_granted": FeatureKind.ANSWERABLE
                not in {feature.kind for feature in signature.guaranteed_features},
                "shared_identity_behavior_retained": signature.isolation_identity_behavior,
                "prior_matching_cluster_count": len(prior),
                "prior_matching_cluster_locks_match": prior_locks_match,
                "unknown_shingle_relations_relaxed": True,
                "valid_overapproximation_row": valid,
            }
        )
    proof = {
        "status": "PASS" if not failures and len(proof_rows) == len(archetypes) else "PARTIAL",
        "claim": "REAL_C08_FEASIBLE_SET_SUBSET_OPTIMISTIC_C08_FEASIBLE_SET",
        "scope": "CURRENT LIVE V1.3 C08 ARCHETYPES UNDER TYPED SELECTION CONSTRAINTS",
        "geometry_digest": geometry.geometry_digest,
        "archetype_inventory_digest": canonical_hash(archetypes),
        "signature_inventory_digest": canonical_hash(signatures),
        "feature_maximum_constraints": feature_maxima,
        "retained_authority": (
            "C08 CELL, DETERMINISTIC_SYNTHETIC ORIGIN, EXACT SPLIT LOCK, NON-NUMERIC REFUSAL, "
            "SHARED SPLIT/FAMILY IDENTITIES, AND ANY FINITE LANE CAPACITY"
        ),
        "relaxed_uncertainty": (
            "Feature vector is raised to the maximal C08 taxonomy profile; "
            "repeat interchangeability "
            "is assumed only in this abstraction; unknown shingle/content couplings are omitted. "
            "Known split-cluster members are all locked to the same split, so retaining that lock "
            "preserves the known colocation behavior without individual hypothetical candidates."
        ),
        "rows": tuple(sorted(proof_rows, key=lambda item: item["signature_digest"])),
        "unproven_rows": tuple(sorted(failures, key=str.encode)),
    }
    proof["proof_digest"] = canonical_hash(proof)
    return proof


def _search_optimistic_cardinality(
    structural_model: Any,
    *,
    lower_bound: int,
    saturation_bound: int,
    solver_config: SelectionSolverConfig,
) -> dict[str, Any]:
    if lower_bound < 0 or saturation_bound < lower_bound:
        raise ValueError("cardinality search bounds must include the ideal lower bound")
    trials: list[RepairCardinalityTrial] = []

    def decide(
        maximum: int,
        *,
        minimum: int = 0,
        proof: RepairCardinalityTrial | None = None,
    ) -> RepairCardinalityTrial:
        trial = solve_repair_cardinality_decision(
            structural_model,
            maximum,
            minimum_additions=minimum,
            lower_bound_proof=proof,
            solver_config=solver_config,
        )
        trials.append(trial)
        return trial

    def exact_feasible_upper(
        trial: RepairCardinalityTrial,
        *,
        low: int,
        low_proof: RepairCardinalityTrial,
    ) -> tuple[RepairCardinalityTrial | None, str | None]:
        current = trial
        while current.status == "FEASIBLE":
            assert current.diagnostics is not None
            incumbent = current.diagnostics.incumbent_addition_count
            if incumbent is None or incumbent < low + 1:
                raise ValueError("optimistic witness contradicts the preceding infeasible bound")
            if current.maximum_additions == incumbent:
                return current, None
            current = decide(
                incumbent,
                minimum=low + 1,
                proof=low_proof,
            )
            if current.status == "UNKNOWN":
                return None, "UNKNOWN"
            if current.status == "INFEASIBLE":
                raise ValueError("reported feasible incumbent failed its exact cardinality replay")
        return None, current.status

    first = decide(lower_bound)
    if first.status == "FEASIBLE":
        assert first.diagnostics is not None
        if first.diagnostics.incumbent_addition_count != lower_bound:
            raise ValueError("governed feasibility contradicts the ideal lower-bound proof")
        return {
            "status": "FEASIBLE",
            "minimum_additions": lower_bound,
            "repair_vector": first.witness,
            "trials": tuple(trials),
            "infeasible_at_saturation": False,
            "lower_bound_trial": None,
        }
    if saturation_bound == lower_bound:
        return {
            "status": "INFEASIBLE" if first.status == "INFEASIBLE" else "UNKNOWN",
            "minimum_additions": None,
            "repair_vector": (),
            "trials": tuple(trials),
            "infeasible_at_saturation": first.status == "INFEASIBLE",
        }
    if first.status == "UNKNOWN":
        saturated = decide(saturation_bound)
        if saturated.status == "INFEASIBLE":
            return {
                "status": "INFEASIBLE",
                "minimum_additions": None,
                "repair_vector": (),
                "trials": tuple(trials),
                "infeasible_at_saturation": True,
            }
        return {
            "status": "UNKNOWN",
            "minimum_additions": None,
            "repair_vector": (),
            "trials": tuple(trials),
            "infeasible_at_saturation": False,
        }

    saturated = decide(saturation_bound)
    if saturated.status == "INFEASIBLE":
        return {
            "status": "INFEASIBLE",
            "minimum_additions": None,
            "repair_vector": (),
            "trials": tuple(trials),
            "infeasible_at_saturation": True,
        }
    if saturated.status == "UNKNOWN":
        return {
            "status": "UNKNOWN",
            "minimum_additions": None,
            "repair_vector": (),
            "trials": tuple(trials),
            "infeasible_at_saturation": False,
        }

    upper, _outcome = exact_feasible_upper(saturated, low=lower_bound, low_proof=first)
    if upper is None:
        return {
            "status": "UNKNOWN",
            "minimum_additions": None,
            "repair_vector": (),
            "trials": tuple(trials),
            "infeasible_at_saturation": False,
        }
    low = lower_bound
    low_proof = first
    high = upper.maximum_additions
    high_trial = upper
    while high - low > 1:
        middle = (low + high) // 2
        trial = decide(middle, minimum=low + 1, proof=low_proof)
        if trial.status == "UNKNOWN":
            return {
                "status": "UNKNOWN",
                "minimum_additions": None,
                "repair_vector": (),
                "trials": tuple(trials),
                "infeasible_at_saturation": False,
            }
        if trial.status == "INFEASIBLE":
            low, low_proof = middle, trial
            continue
        exact, _outcome = exact_feasible_upper(trial, low=low, low_proof=low_proof)
        if exact is None:
            return {
                "status": "UNKNOWN",
                "minimum_additions": None,
                "repair_vector": (),
                "trials": tuple(trials),
                "infeasible_at_saturation": False,
            }
        high, high_trial = exact.maximum_additions, exact
    if high_trial.maximum_additions != low + 1 or high_trial.status != "FEASIBLE":
        raise ValueError("cardinality search did not finish with adjacent infeasible/feasible K")
    return {
        "status": "FEASIBLE",
        "minimum_additions": high,
        "repair_vector": high_trial.witness,
        "trials": tuple(trials),
        "infeasible_at_saturation": False,
        "lower_bound_trial": low_proof,
    }


def _canonicalize_governed_vector(
    structural_model: Any,
    count: int,
    solver_config: SelectionSolverConfig,
    lower_bound_trial: RepairCardinalityTrial | None = None,
) -> tuple[RepairSignatureCount, ...]:
    # One worker, fixed seed, and sorted model construction make this witness reproducible.
    trial = solve_repair_cardinality_decision(
        structural_model,
        count,
        minimum_additions=count if lower_bound_trial is not None else 0,
        lower_bound_proof=lower_bound_trial,
        solver_config=replace(solver_config, workers=1),
    )
    if trial.status != "FEASIBLE" or sum(item.total_count for item in trial.witness) != count:
        raise ValueError("single-worker governed-vector replay was not exact and feasible")
    return trial.witness


def _current_c08_capability(search: dict[str, Any]) -> str:
    if search["status"] == "INFEASIBLE" and search["infeasible_at_saturation"]:
        return "PROVABLY_INSUFFICIENT"
    return "UNRESOLVED"


def _cardinality_trial_inventory(
    trials: tuple[RepairCardinalityTrial, ...],
) -> tuple[dict[str, Any], ...]:
    rows = []
    for trial in trials:
        diagnostics = trial.diagnostics
        rows.append(
            {
                "minimum_additions": trial.minimum_additions,
                "maximum_additions": trial.maximum_additions,
                "status": trial.status,
                "solver_profile_version": trial.solver_profile_version,
                "solver_config": trial.solver_config,
                "solver_version": trial.solver_version,
                "geometry_digest": trial.geometry_digest,
                "signature_inventory_digest": trial.signature_inventory_digest,
                "trial_digest": trial.trial_digest,
                "lower_bound_source_trial_digest": trial.lower_bound_source_trial_digest,
                "hint_source_trial_digest": trial.hint_source_trial_digest,
                "witness_digest": canonical_hash(trial.witness) if trial.witness else None,
                "diagnostics": (
                    None
                    if diagnostics is None
                    else {
                        "model_variable_count": diagnostics.model_variable_count,
                        "boolean_variable_count": diagnostics.boolean_variable_count,
                        "integer_variable_count": diagnostics.integer_variable_count,
                        "constraint_count": diagnostics.constraint_count,
                        "objective_term_count": diagnostics.objective_term_count,
                        "solver_status": diagnostics.solver_status,
                        "feasible_incumbent_present": diagnostics.feasible_incumbent_present,
                        "incumbent_addition_count": diagnostics.incumbent_addition_count,
                        "best_objective_bound": diagnostics.best_objective_bound,
                        "absolute_gap": diagnostics.absolute_gap,
                        "conflicts": diagnostics.conflicts,
                        "branches": diagnostics.branches,
                        "restarts": diagnostics.restarts,
                        "wall_seconds": diagnostics.wall_seconds,
                        "deterministic_time": diagnostics.deterministic_time,
                        "unknown_classification": diagnostics.unknown_classification,
                    }
                ),
            }
        )
    return tuple(rows)


def _structural_comparison_record(
    geometry: RepairGeometry,
    archetypes: tuple[Any, ...],
    *,
    live_supply_inventory_digest: str,
    production_root: Path,
    relative_root: str,
    replay: bool,
) -> dict[str, Any]:
    ideal_signatures, ideal_vector, ideal_proof = _accepted_ideal_witness(geometry)
    ideal_inventory = _ideal_winner_inventory(geometry, ideal_vector)
    archetype_contracts = _governed_archetype_contract_inventory(geometry, archetypes)
    archetype_contract_digest = canonical_hash(archetype_contracts)
    dominance = _ideal_relaxation_proof(geometry, ideal_signatures, archetypes)
    gap = _capability_gap(geometry, ideal_vector, archetypes)
    optimistic_signatures = build_optimistic_c08_signatures(geometry, archetypes)
    optimistic_proof = _optimistic_c08_relaxation_proof(geometry, archetypes, optimistic_signatures)
    saturation_bounds = derive_archetype_saturation_bounds(geometry, optimistic_signatures)
    saturation_by_id = {item.signature_id: item.upper_bound for item in saturation_bounds}
    final_n = next(
        constraint.minimum
        for constraint in geometry.problem.constraint_set.constraints
        if constraint.kind is ConstraintKind.FINAL_COUNT
    )
    assert final_n is not None
    saturation_total = min(final_n, sum(item.upper_bound for item in saturation_bounds))
    saturation_proof = {
        "method": (
            "For each split-locked archetype, y[a] cannot exceed FINAL_COUNT, its SPLIT_COUNT "
            "maximum, its ORIGIN_BOUNDS maximum, any applicable FEATURE_MINIMUM maximum, or "
            "finite lane capacity. The master also retains the joint FINAL_COUNT equality."
        ),
        "final_count": final_n,
        "archetype_bounds": saturation_bounds,
        "joint_saturation_bound": saturation_total,
        "no_arbitrary_cap": True,
    }
    saturation_proof["proof_digest"] = canonical_hash(saturation_proof)
    relative = f"{relative_root}/governed-structural-comparison.v1.4.json"
    previous = legacy._read_record(relative, production_root)
    binding_keys = (
        "schema_version",
        "geometry_digest",
        "problem_digest",
        "live_supply_inventory_digest",
        "governed_archetype_contract_digest",
        "ideal_winning_vector_digest",
        "ideal_relaxation_proof_digest",
        "optimistic_c08_relaxation_proof_digest",
        "saturation_proof_digest",
    )
    expected_binding = {
        "schema_version": _STRUCTURAL_COMPARISON_SCHEMA,
        "geometry_digest": geometry.geometry_digest,
        "problem_digest": geometry.problem.problem_digest,
        "live_supply_inventory_digest": live_supply_inventory_digest,
        "governed_archetype_contract_digest": archetype_contract_digest,
        "ideal_winning_vector_digest": ideal_proof["winning_vector_digest"],
        "ideal_relaxation_proof_digest": dominance["proof_digest"],
        "optimistic_c08_relaxation_proof_digest": optimistic_proof["proof_digest"],
        "saturation_proof_digest": saturation_proof["proof_digest"],
    }
    if previous is not None and not replay:
        if any(previous[0].get(key) != value for key, value in expected_binding.items()):
            raise ValueError("stored governed structural comparison is bound to different evidence")
        return previous[0]
    proof_ready = (
        dominance["status"] == "PASS"
        and optimistic_proof["status"] == "PASS"
        and len(saturation_bounds) == len(optimistic_signatures) == len(archetypes)
    )
    model = None
    model_evidence: dict[str, Any] = {
        "model_built": False,
        "variable_count": None,
        "constraint_count": None,
        "archetype_count_variables": None,
        "recourse_count_variables": None,
        "candidate_replica_variables": 0,
    }
    if proof_ready:
        model = _structural_repair_model(
            geometry,
            optimistic_signatures,
            signature_upper_bounds=saturation_by_id,
        )
        names = tuple(variable.name for variable in model.model.proto.variables)
        model_evidence = {
            "model_built": True,
            "variable_count": len(model.model.proto.variables),
            "constraint_count": len(model.model.proto.constraints),
            "archetype_count_variables": sum(name.startswith("y[") for name in names),
            "recourse_count_variables": sum(name.startswith("z[") for name in names),
            "candidate_replica_variables": sum("repair_candidate" in name for name in names),
            "first_stage": "INTEGER_COUNTS_Y[A]",
            "recourse": "EXACT_BASE_ASSIGNMENT_PLUS_AGGREGATE_SPLIT_COUNTS",
        }
        search = _search_optimistic_cardinality(
            model,
            lower_bound=int(ideal_proof["minimum_additions"]),
            saturation_bound=saturation_total,
            solver_config=RES407_STRUCTURAL_REPAIR_MASTER_PROFILE_V1,
        )
    else:
        search = {
            "status": "UNKNOWN",
            "minimum_additions": None,
            "repair_vector": (),
            "trials": (),
            "infeasible_at_saturation": False,
            "lower_bound_trial": None,
            "reason": "A required relaxation or saturation proof did not pass.",
        }
    optimistic_vector = tuple(search["repair_vector"])
    vector_solver_config: SelectionSolverConfig | None = None
    if search["status"] == "FEASIBLE":
        assert model is not None and search["minimum_additions"] is not None
        optimistic_vector = _canonicalize_governed_vector(
            model,
            search["minimum_additions"],
            RES407_STRUCTURAL_REPAIR_MASTER_PROFILE_V1,
            search.get("lower_bound_trial"),
        )
        vector_solver_config = replace(RES407_STRUCTURAL_REPAIR_MASTER_PROFILE_V1, workers=1)
    optimistic_vector_summary = tuple(
        {
            "signature_digest": item.signature.signature_id,
            "lane_id": item.signature.lane_id,
            "capability": item.signature.cell[0],
            "family": item.signature.cell[1],
            "cell": item.signature.cell,
            "origin": item.signature.origin.value,
            "locked_split": item.signature.split_compatibility[0].value,
            "count": item.total_count,
            "split_counts": tuple((split.value, count) for split, count in item.split_counts),
            "optimistic_feature_support": tuple(
                (feature.kind.value, feature.key) for feature in item.signature.guaranteed_features
            ),
            "feature_semantics": "OPTIMISTIC_MAXIMUM; NOT A REAL GENERATOR GUARANTEE",
        }
        for item in optimistic_vector
    )
    missing: tuple[dict[str, Any], ...] = ()
    if _current_c08_capability(search) == "PROVABLY_INSUFFICIENT":
        missing = tuple(
            {
                "capability": item["capability"],
                "family": item["family"],
                "cell": item["cell"],
                "count_in_ideal_witness": item["count"],
                "origin": item["origin_semantics"],
                "guaranteed_features": item["guaranteed_features"],
                "answerability_refusal_behavior": item["answerability_refusal_behavior"],
                "split_compatibility": item["split_compatibility"],
                "selected_split_counts": item["split_counts"],
                "isolation_assumption": item["isolation_assumption"],
                "relation_assumption": item["relation_assumption"],
                "contamination_assumption": item["contamination_assumption"],
                "ideal_signature_digest": item["signature_digest"],
                "necessity_scope": (
                    "WITNESS-BACKED CAPABILITY IN ONE PROVEN OPTIMAL VECTOR; "
                    "INDIVIDUAL REQUIREMENT UNIQUENESS IS NOT CLAIMED"
                ),
            }
            for item in ideal_inventory
        )
    if search["status"] == "FEASIBLE":
        blockers = []
        if any(item.total_count > 1 for item in optimistic_vector):
            blockers.append("THE_OPTIMAL_VECTOR_REPEATS_AT_LEAST_ONE_LANE_CELL")
            blockers.append("EXISTING_OPTION_BUILDER_HAS_NO_REPEATED_INSTANCE_ORDINAL")
        if any(not item.feature_behavior_complete for item in archetypes):
            blockers.append("EXACT_REPEATED_INSTANCE_FEATURE_VECTOR_IS_UNKNOWN")
        if any(
            item.capacity_status.value == "RULE_GOVERNED" and item.remaining_finite_capacity is None
            for item in archetypes
        ):
            blockers.append("RULE_GOVERNED_REPEAT_COUNT_IS_UNSPECIFIED")
        if any(item.materializer_contract is None for item in archetypes):
            blockers.append("MATERIALIZER_OUTPUT_CONTRACT_IS_INCOMPLETE")
        if any(
            claim["classification"] == "UNKNOWN"
            and claim["property"] == "contamination_and_shingles"
            for row in archetype_contracts
            for claim in row["structural_property_claims"]
        ):
            blockers.append("CONTAMINATION_AND_SHINGLE_BEHAVIOR_IS_UNKNOWN")
        concrete_vector_instantiability = {
            "status": "NOT_ESTABLISHED" if blockers else "ESTABLISHED",
            "existing_option_builder_can_emit_vector": all(
                item.total_count <= 1 for item in optimistic_vector
            ),
            "blockers": tuple(blockers),
        }
    else:
        concrete_vector_instantiability = {
            "status": "NO_FEASIBLE_OPTIMISTIC_VECTOR",
            "existing_option_builder_can_emit_vector": False,
            "blockers": (),
        }
    comparison = {
        "schema_version": _STRUCTURAL_COMPARISON_SCHEMA,
        "continuation_entry_head": "63ffb1c69c34647f10974d0500dee8a2f24dfbce",
        "geometry_digest": geometry.geometry_digest,
        "problem_digest": geometry.problem.problem_digest,
        "live_supply_inventory_digest": live_supply_inventory_digest,
        "authorable_lane_count": len({item.lane_id for item in archetypes}),
        "governed_archetype_count": len(archetypes),
        "archetype_cells": tuple(sorted({item.cell for item in archetypes})),
        "archetype_contract_inventory": archetype_contracts,
        "governed_archetype_contract_digest": archetype_contract_digest,
        "ideal_signature_count": len(ideal_signatures),
        "ideal_signature_inventory_digest": ideal_proof["signature_inventory_digest"],
        "ideal_min_additions": ideal_proof["minimum_additions"],
        "ideal_cardinality_optimality": ideal_proof["cardinality_optimality"],
        "ideal_winning_vector": ideal_inventory,
        "ideal_winning_vector_digest": ideal_proof["winning_vector_digest"],
        "ideal_result_digest": ideal_proof["ideal_result_digest"],
        "ideal_relaxation_proof_status": dominance["status"],
        "ideal_relaxation_proof": dominance,
        "ideal_relaxation_proof_digest": dominance["proof_digest"],
        "capability_gap": gap,
        "capability_gap_digest": gap["gap_digest"],
        "optimistic_c08_relaxation_proof_status": optimistic_proof["status"],
        "optimistic_c08_relaxation_proof": optimistic_proof,
        "optimistic_c08_relaxation_proof_digest": optimistic_proof["proof_digest"],
        "archetype_saturation_bounds": saturation_bounds,
        "saturation_proof": saturation_proof,
        "saturation_proof_digest": saturation_proof["proof_digest"],
        "model_evidence": model_evidence,
        "solver_config": RES407_STRUCTURAL_REPAIR_MASTER_PROFILE_V1,
        "cardinality_trials": _cardinality_trial_inventory(search["trials"]),
        "optimistic_c08_status": search["status"],
        "optimistic_c08_min_additions": search["minimum_additions"],
        "optimistic_c08_repair_vector": optimistic_vector_summary,
        "optimistic_c08_repair_vector_typed": optimistic_vector,
        "optimistic_c08_vector_digest": canonical_hash(optimistic_vector)
        if optimistic_vector
        else None,
        "optimistic_c08_vector_report_digest": canonical_hash(optimistic_vector_summary)
        if optimistic_vector_summary
        else None,
        "optimistic_c08_vector_solver_config": vector_solver_config,
        "current_c08_repair_capability": _current_c08_capability(search),
        "missing_governed_capabilities": missing,
        "concrete_vector_instantiability": concrete_vector_instantiability,
        "concrete_candidates_generated": 0,
        "seeds_generated": 0,
        "human_review_invoked": False,
        "final_split_assignment_performed": False,
        "candidate_materialization_invoked": False,
    }
    if previous is not None:
        previous_body = previous[0]
        if any(previous_body.get(key) != comparison.get(key) for key in binding_keys):
            raise ValueError("stored governed structural comparison is bound to different evidence")
        if not replay:
            return previous_body
        stable_keys = (
            *binding_keys,
            "ideal_min_additions",
            "optimistic_c08_status",
            "optimistic_c08_min_additions",
            "optimistic_c08_vector_digest",
            "current_c08_repair_capability",
            "missing_governed_capabilities",
        )
        expected = legacy._wire_record({key: comparison[key] for key in stable_keys})
        if any(previous_body.get(key) != expected[key] for key in stable_keys):
            raise ValueError("fresh structural comparison replay disagrees with stored result")
        return previous_body
    return legacy._write_or_reuse(relative, comparison, production_root)


def _structural_master_record(
    geometry: RepairGeometry,
    archetypes: tuple[Any, ...],
    capacity_records: list[dict[str, Any]],
    production_root: Path,
    *,
    replay: bool,
) -> dict[str, Any]:
    contracts = archetype_structural_contracts(geometry, archetypes)
    contract_digest = canonical_hash(contracts)
    archetype_digest = canonical_hash(archetypes)
    relative = (
        "production/variable-pools/backfill/"
        f"{legacy.ORIGINAL_PLAN_DIGEST.removeprefix('sha256:')}/"
        f"{legacy.RES451_MERGE_SHA}/geometry/v3/structural-augmentation-master.json"
    )
    previous = legacy._read_record(relative, production_root)
    if previous is not None and not replay:
        record = previous[0]
        expected_bindings = [
            binding
            for capacity_record in capacity_records
            for binding in capacity_record["certificate_bindings"]
        ]
        if (
            record.get("schema_version") != "RES407-STRUCTURAL-AUGMENTATION-MASTER@1.0.0"
            or record.get("geometry_digest") != geometry.geometry_digest
            or record.get("archetype_inventory_digest") != archetype_digest
            or record.get("archetype_structural_contract_digest") != contract_digest
            or record.get("capacity_certificate_semantics") != "PASS"
            or record.get("capacity_certificate_bindings") != expected_bindings
            or record.get("concrete_candidates_materialized") is not False
            or record.get("removal_sweep_run") is not False
        ):
            raise ValueError("stored structural master is bound to different inputs")
        if (
            record.get("ideal_repair_status") != "UNKNOWN"
            or record.get("ideal_min_additions") is not None
            or record.get("ideal_repair_signatures")
            or record.get("optimistic_c08_master_status") != "UNKNOWN"
            or record.get("optimistic_c08_min_additions") is not None
            or record.get("optimistic_c08_repair_vector")
        ):
            raise ValueError("stored structural master is not a reusable unresolved result")
        expected_results = (
            RepairMasterResult(
                status="UNKNOWN",
                minimum_additions=None,
                repair_vector=(),
                solver_config=REPAIR_MASTER_SOLVER_CONFIG,
                solver_version=version("ortools"),
                objective="MINIMIZE_TOTAL_ADDED_STRUCTURAL_UNITS",
                objective_bound=None,
                geometry_digest=geometry.geometry_digest,
                signature_catalog_digest=canonical_hash(build_ideal_repair_signatures(geometry)),
                optimality_scope=_IDEAL_MASTER_SCOPE,
            ),
            RepairMasterResult(
                status="UNKNOWN",
                minimum_additions=None,
                repair_vector=(),
                solver_config=REPAIR_MASTER_SOLVER_CONFIG,
                solver_version=version("ortools"),
                objective="MINIMIZE_TOTAL_ADDED_STRUCTURAL_UNITS",
                objective_bound=None,
                geometry_digest=geometry.geometry_digest,
                signature_catalog_digest=canonical_hash(
                    build_optimistic_c08_signatures(geometry, archetypes)
                ),
                optimality_scope=_OPTIMISTIC_C08_SCOPE,
            ),
            RepairMasterResult(
                status="UNRESOLVED",
                minimum_additions=None,
                repair_vector=(),
                solver_config=REPAIR_MASTER_SOLVER_CONFIG,
                solver_version=version("ortools"),
                objective="MINIMIZE_TOTAL_ADDED_STRUCTURAL_UNITS",
                objective_bound=None,
                geometry_digest=geometry.geometry_digest,
                signature_catalog_digest=canonical_hash((archetypes, contracts)),
                optimality_scope=_GOVERNED_MASTER_SCOPE,
            ),
        )
        if tuple(
            record.get(key)
            for key in (
                "ideal_repair_digest",
                "optimistic_c08_repair_digest",
                "governed_repair_digest",
            )
        ) != tuple(result.result_digest for result in expected_results):
            raise ValueError("stored unresolved master result digests do not replay")
        return record

    ideal_result = solve_structural_repair_master(
        geometry,
        build_ideal_repair_signatures(geometry),
        solver_config=REPAIR_MASTER_SOLVER_CONFIG,
        optimality_scope=_IDEAL_MASTER_SCOPE,
    )
    optimistic_c08_result = solve_structural_repair_master(
        geometry,
        build_optimistic_c08_signatures(geometry, archetypes),
        solver_config=REPAIR_MASTER_SOLVER_CONFIG,
        optimality_scope=_OPTIMISTIC_C08_SCOPE,
    )
    c08_capability = (
        "PROVABLY_INSUFFICIENT" if optimistic_c08_result.status == "INFEASIBLE" else "UNRESOLVED"
    )
    governed_result = RepairMasterResult(
        status="UNRESOLVED",
        minimum_additions=None,
        repair_vector=(),
        solver_config=REPAIR_MASTER_SOLVER_CONFIG,
        solver_version=version("ortools"),
        objective="MINIMIZE_TOTAL_ADDED_STRUCTURAL_UNITS",
        objective_bound=None,
        geometry_digest=geometry.geometry_digest,
        signature_catalog_digest=canonical_hash((archetypes, contracts)),
        optimality_scope=_GOVERNED_MASTER_SCOPE,
    )
    missing_capabilities = compare_ideal_to_governed_c08(ideal_result, archetypes)
    return legacy._write_or_reuse(
        relative,
        {
            "schema_version": "RES407-STRUCTURAL-AUGMENTATION-MASTER@1.0.0",
            "geometry_digest": geometry.geometry_digest,
            "archetype_inventory_digest": archetype_digest,
            "capacity_certificate_semantics": "PASS",
            "capacity_certificate_bindings": [
                binding for record in capacity_records for binding in record["certificate_bindings"]
            ],
            "ideal_repair_status": ideal_result.status,
            "ideal_min_additions": ideal_result.minimum_additions,
            "ideal_repair_signatures": ideal_result.repair_vector,
            "ideal_repair_digest": ideal_result.result_digest,
            "archetype_structural_contracts": contracts,
            "archetype_structural_contract_digest": contract_digest,
            "governed_master_status": governed_result.status,
            "governed_min_additions": governed_result.minimum_additions,
            "governed_repair_vector": governed_result.repair_vector,
            "governed_repair_digest": governed_result.result_digest,
            "optimality_scope": governed_result.optimality_scope,
            "optimistic_c08_master_status": optimistic_c08_result.status,
            "optimistic_c08_min_additions": optimistic_c08_result.minimum_additions,
            "optimistic_c08_repair_vector": optimistic_c08_result.repair_vector,
            "optimistic_c08_repair_digest": optimistic_c08_result.result_digest,
            "current_c08_repair_capability": c08_capability,
            "missing_governed_capabilities": missing_capabilities,
            "robust_master_architecture": {
                "first_stage": "GOVERNED_ARCHETYPE_ADDITION_COUNTS_Y[A]",
                "recourse": "EXACT_BENCHMARK_ASSIGNMENT",
                "initial_scenarios": ("BASE",),
                "oracle": "EXACT_FINAL_SELECTION_PROBLEM_FEASIBILITY",
                "scenario_generation": (
                    "Add a failed removal scenario to the master when the exact oracle finds one."
                ),
                "final_proof": "EXHAUSTIVE_REMOVAL_SWEEP_AFTER_SCENARIO_CONVERGENCE",
            },
            "concrete_candidates_materialized": False,
            "removal_sweep_run": False,
        },
        production_root,
    )


def _run_geometry(production_root: Path, *, replay: bool = False) -> dict[str, Any]:
    inputs = res451._load_inputs(_REPOSITORY, production_root)
    if inputs.problem.problem_digest != legacy.ORIGINAL_PROBLEM_DIGEST:
        raise ValueError("original problem authority drift")
    legacy._diagnosis_record(inputs, production_root)
    before = legacy._original_store_digest(inputs, production_root)
    supply, _lanes = legacy._supply_enumeration(inputs)
    geometry = RepairGeometry(inputs.problem)
    archetypes = derive_governed_archetypes(
        inputs.inventory,
        tuple((r["lane_id"], r["current_consumed_capacity"]) for r in supply["lanes"]),
    )
    classification = classify_archetype_repair(geometry, archetypes)
    root = (
        f"production/variable-pools/backfill/"
        f"{legacy.ORIGINAL_PLAN_DIGEST.removeprefix('sha256:')}/"
        f"{legacy.RES451_MERGE_SHA}/geometry/v3"
    )
    geometry_record = legacy._write_or_reuse(
        f"{root}/repair-geometry.json",
        {
            "schema_version": "RES407-REPAIR-GEOMETRY@1.0.0",
            "geometry_digest": geometry.geometry_digest,
            "geometry": geometry,
        },
        production_root,
    )
    inventory_record = legacy._write_or_reuse(
        f"{root}/governed-archetype-inventory.json",
        {
            "schema_version": "RES407-REPAIR-ARCHETYPES@1.0.0",
            "live_supply_inventory_digest": inputs.inventory.inventory_digest,
            "consumption": supply,
            "archetype_inventory_digest": canonical_hash(archetypes),
            "archetypes": archetypes,
            "classification": classification,
        },
        production_root,
    )
    config = SelectionSolverConfig(workers=8, timeout_s=120.0, cp_model_presolve=True)
    cases = (
        ("current", (), tuple(SplitName)),
        (
            "without-colocation",
            (ConstraintKind.CONDITIONAL_COLOCATION,),
            (SplitName.PUBLIC_DEVELOPMENT,),
        ),
        (
            "without-feature-minima",
            (ConstraintKind.FEATURE_MINIMUM,),
            (SplitName.PUBLIC_DEVELOPMENT,),
        ),
    )
    records = []
    for name, ablate, splits in cases:
        relative = f"{root}/capacity-{name}.json"
        previous = legacy._read_record(relative, production_root)
        # Resumption retains the exact witness; replay compares certified objectives.
        if previous is None or replay:
            print(f"RES407_GEOMETRY_SOLVE={name}", flush=True)
            certificates = compute_split_capacity_envelope(
                geometry,
                splits=splits,
                ablate=ablate,
                solver_config=config,
            )
            capacity_bindings = tuple(
                bind_split_capacity_certificate(geometry, certificate, ablate=ablate)
                for certificate in certificates
            )
            body = {
                "schema_version": "RES407-SPLIT-CAPACITY@1.1.0",
                "geometry_digest": geometry.geometry_digest,
                "ablation": ablate,
                "solver_config": config,
                "certificates": certificates,
                "certificate_digests": tuple(c.result_digest for c in certificates),
                "certificate_bindings": capacity_bindings,
                "certificate_binding_digests": tuple(
                    binding.binding_digest for binding in capacity_bindings
                ),
                "bottlenecks": tuple(
                    structural_bottleneck_evidence(geometry, c) for c in certificates
                ),
            }
            if previous is None:
                record = legacy._write_or_reuse(relative, body, production_root)
            else:
                record = previous[0]
                if [c.maximum for c in certificates] != [
                    c["maximum"] for c in record["certificates"]
                ]:
                    raise ValueError("fresh-process capacity replay disagrees")
        else:
            record = previous[0]
        if record["schema_version"] != "RES407-SPLIT-CAPACITY@1.1.0":
            raise ValueError("stored capacity schema drift")
        if record["geometry_digest"] != geometry.geometry_digest:
            raise ValueError("stored capacity geometry drift")
        if record["solver_config"] != legacy._wire_record(config):
            raise ValueError("stored capacity solver configuration drift")
        if record["ablation"] != res406._wire(ablate):
            raise ValueError("stored capacity ablation drift")
        active = capacity_problem(geometry, ablate)
        expected_relaxed = tuple(
            sorted(
                c.constraint_id
                for c in inputs.problem.constraint_set.constraints
                if c.constraint_id
                not in {x.constraint_id for x in active.constraint_set.constraints}
            )
        )
        decoded = tuple(
            from_canonical_json(
                json.dumps(
                    {
                        "serialization_version": SERIALIZATION_VERSION,
                        "type": type_identifier(SplitCapacityCertificate),
                        "payload": payload,
                    }
                ),
                SplitCapacityCertificate,
            )
            for payload in record["certificates"]
        )
        if tuple(c.split for c in decoded) != splits:
            raise ValueError("stored capacity split inventory drift")
        if list(record["certificate_digests"]) != [c.result_digest for c in decoded]:
            raise ValueError("stored capacity result digest drift")
        expected_bindings = tuple(
            bind_split_capacity_certificate(geometry, certificate, ablate=ablate)
            for certificate in decoded
        )
        if record.get("certificate_bindings") != res406._wire(expected_bindings):
            raise ValueError("stored capacity semantic binding drift")
        if record.get("certificate_binding_digests") != [
            binding.binding_digest for binding in expected_bindings
        ]:
            raise ValueError("stored capacity semantic digest drift")
        for c in decoded:
            if (
                c.original_problem_digest != inputs.problem.problem_digest
                or c.original_constraint_inventory_digest
                != inputs.problem.constraint_inventory_digest
                or c.active_constraint_inventory_digest != active.constraint_inventory_digest
                or c.relaxed_constraint_ids != expected_relaxed
                or c.solver_config != config
                or c.solver_version != version("ortools")
                or c.relaxation_definition != CAPACITY_RELAXATION
                or c.required
                != next(
                    x.minimum
                    for x in geometry.constraints(ConstraintKind.SPLIT_COUNT)
                    if x.split is c.split
                )
            ):
                raise ValueError("stored capacity authority drift")
            if validate_final_selection(active, c.witness).status is not ValidationStatus.VALID:
                raise ValueError("stored capacity witness is invalid")
            if c.maximum != sum(
                a.state is AssignmentState(c.split.value) for a in c.witness.assignments
            ):
                raise ValueError("stored objective disagrees with witness")
        if record["bottlenecks"] != res406._wire(
            tuple(structural_bottleneck_evidence(geometry, c) for c in decoded)
        ):
            raise ValueError("stored structural support evidence drift")
        records.append(record)
    envelope = legacy._write_or_reuse(
        f"{root}/split-capacity-envelope.json",
        {
            "schema_version": "RES407-CAPACITY-ENVELOPE@1.1.0",
            "original_problem_digest": inputs.problem.problem_digest,
            "geometry_digest": geometry.geometry_digest,
            "capacity_records": records,
        },
        production_root,
    )
    # The v3 master checkpoint predates the refusal-safe C08 abstraction; keep it historical.
    comparison_record = _structural_comparison_record(
        geometry,
        archetypes,
        live_supply_inventory_digest=inputs.inventory.inventory_digest,
        production_root=production_root,
        relative_root=root,
        replay=replay,
    )
    legacy._assert_original_store_unchanged(
        before, legacy._original_store_digest(inputs, production_root)
    )
    guard = validate_production_private_material_absent(
        res406._private_material(
            inputs.plan, inputs.pool, inputs.historical_inputs, inputs.exclusion
        ),
        repository_root=_REPOSITORY,
        candidate_count=inputs.pool.candidate_count,
    )
    if guard.status != "PASS":
        raise ValueError("RES-407 geometry production private-material leak guard failed")
    current = records[0]["certificates"]
    summary = {
        "repair_geometry_digest": geometry.geometry_digest,
        "capacity_certificate_digest": envelope["receipt_digest"],
        "geometry_record_digest": geometry_record["receipt_digest"],
        "archetype_record_digest": inventory_record["receipt_digest"],
        "repair_archetype_inventory_digest": canonical_hash(archetypes),
        "authorable_lane_count": len({a.lane_id for a in archetypes}),
        "repair_archetype_count": len(archetypes),
        "current_c08_archetype_repair_classification": classification.classification.value,
        "classification_evidence": classification.evidence,
        "split_capacities": {
            c["split"]: {
                "required": c["required"],
                "maximum": c["maximum"],
                "capacity_deficit": max(0, c["required"] - c["maximum"]),
            }
            for c in current
        },
        "public_max_without_colocation": records[1]["certificates"][0]["maximum"],
        "public_max_without_feature_minima": records[2]["certificates"][0]["maximum"],
        "pool_original_mutated": False,
        "old_brute_force_path_reachable": False,
        "external_namespace": root,
        "CAPACITY_CERTIFICATE_SEMANTICS": "PASS",
        "IDEAL_REPAIR_STATUS": "OPTIMAL",
        "IDEAL_MIN_ADDITIONS": comparison_record["ideal_min_additions"],
        "IDEAL_REPAIR_SIGNATURES": comparison_record["ideal_winning_vector"],
        "IDEAL_REPAIR_DIGEST": comparison_record["ideal_result_digest"],
        "IDEAL_WINNING_VECTOR_DIGEST": comparison_record["ideal_winning_vector_digest"],
        "IDEAL_SIGNATURE_COUNT": comparison_record["ideal_signature_count"],
        "IDEAL_CARDINALITY_OPTIMALITY": comparison_record["ideal_cardinality_optimality"],
        "IDEAL_RELAXATION_PROOF_STATUS": comparison_record["ideal_relaxation_proof_status"],
        "IDEAL_RELAXATION_PROOF_DIGEST": comparison_record["ideal_relaxation_proof_digest"],
        "GOVERNED_ARCHETYPE_COUNT": comparison_record["governed_archetype_count"],
        "GOVERNED_ARCHETYPE_CONTRACT_DIGEST": comparison_record[
            "governed_archetype_contract_digest"
        ],
        "CAPABILITY_GAP_DIGEST": comparison_record["capability_gap_digest"],
        "OPTIMISTIC_C08_RELAXATION_PROOF_STATUS": comparison_record[
            "optimistic_c08_relaxation_proof_status"
        ],
        "OPTIMISTIC_C08_RELAXATION_PROOF_DIGEST": comparison_record[
            "optimistic_c08_relaxation_proof_digest"
        ],
        "ARCHETYPE_SATURATION_BOUNDS": comparison_record["archetype_saturation_bounds"],
        "SATURATION_PROOF_DIGEST": comparison_record["saturation_proof_digest"],
        "CARDINALITY_TRIALS": comparison_record["cardinality_trials"],
        "OPTIMISTIC_C08_STATUS": comparison_record["optimistic_c08_status"],
        "OPTIMISTIC_C08_MIN_ADDITIONS": comparison_record["optimistic_c08_min_additions"],
        "OPTIMISTIC_C08_VECTOR": comparison_record["optimistic_c08_repair_vector"],
        "OPTIMISTIC_C08_VECTOR_DIGEST": comparison_record["optimistic_c08_vector_digest"],
        "ARCHETYPE_STRUCTURAL_CONTRACT_DIGEST": comparison_record[
            "governed_archetype_contract_digest"
        ],
        "GOVERNED_MASTER_STATUS": "UNRESOLVED",
        "GOVERNED_MIN_ADDITIONS": None,
        "GOVERNED_REPAIR_VECTOR": (),
        "GOVERNED_REPAIR_DIGEST": None,
        "OPTIMALITY_SCOPE": _GOVERNED_MASTER_SCOPE,
        "CURRENT_C08_REPAIR_CAPABILITY": comparison_record["current_c08_repair_capability"],
        "CONCRETE_VECTOR_INSTANTIABILITY": comparison_record["concrete_vector_instantiability"],
        "MISSING_GOVERNED_CAPABILITIES": comparison_record["missing_governed_capabilities"],
        "MISSING_GOVERNED_CAPABILITIES_STATUS": (
            "WITNESS_BACKED_NOT_UNIQUE"
            if comparison_record["ideal_min_additions"] is not None
            else "UNRESOLVED_NO_OPTIMAL_IDEAL_VECTOR"
        ),
        "capacity_certificate_binding_digests": [
            digest
            for capacity_record in records
            for digest in capacity_record["certificate_binding_digests"]
        ],
        "optimistic_c08_master_status": comparison_record["optimistic_c08_status"],
        "optimistic_c08_min_additions": comparison_record["optimistic_c08_min_additions"],
        "optimistic_c08_repair_digest": comparison_record["optimistic_c08_vector_digest"],
        "structural_comparison_record_digest": comparison_record["receipt_digest"],
        "historical_structural_master_record_preserved": True,
        "concrete_candidates_materialized": False,
        "concrete_candidates_generated": 0,
        "seeds_generated": 0,
        "CONCRETE_CANDIDATES_GENERATED": 0,
        "SEEDS_GENERATED": 0,
        "READY_FOR_MATERIALIZATION": False,
        "READY_FOR_AUTHORITY_EXPANSION": (
            comparison_record["current_c08_repair_capability"] == "PROVABLY_INSUFFICIENT"
        ),
        "removal_sweep_run": False,
    }
    return summary


def run(production_root: Path, *, replay: bool = False) -> dict[str, Any]:
    legacy._require_execution_tree(clean=False)
    return _run_geometry(production_root, replay=replay)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--production-root", type=Path, default=DEFAULT_PRODUCTION_ROOT)
    parser.add_argument("--replay", action="store_true")
    parser.add_argument("--fresh-process", action="store_true")
    args = parser.parse_args()
    summary = run(args.production_root.resolve(), replay=args.replay)
    if args.fresh_process:
        result = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "--production-root",
                str(args.production_root.resolve()),
                "--replay",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        replay_summary = json.loads(result.stdout.splitlines()[-1])
        if replay_summary != json.loads(json.dumps(summary)):
            raise ValueError("fresh-process diagnostic summary drift")
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
