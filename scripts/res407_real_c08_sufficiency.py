#!/usr/bin/env python3
"""Prove real C08 structural sufficiency with aggregate repeat counts only."""

from __future__ import annotations

import hashlib
import json
import sys
from collections import defaultdict
from dataclasses import fields
from importlib.metadata import version
from pathlib import Path
from typing import Any

_REPOSITORY = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(_REPOSITORY), str(_REPOSITORY / "src")]

from dynamislm.benchmark.constants import (  # noqa: E402
    CRITICAL_ERROR_CLASSES,
    SPLIT_ORDER,
    CaseOrigin,
    ExpectedAnswerKind,
    RefusalDecision,
    ScoringProfile,
    SplitName,
)
from dynamislm.benchmark.coverage import COVERAGE_MATRIX  # noqa: E402
from dynamislm.benchmark.production import PRODUCTION_AUTHORING_PROCESS_ID  # noqa: E402
from dynamislm.benchmark.production_authoring import (  # noqa: E402
    PRODUCTION_SYNTHETIC_GENERATORS,
    SYNTHETIC_GENERATOR_ID,
    SYNTHETIC_GENERATOR_VERSION,
    _production_adversarial_tags,
)
from dynamislm.benchmark.repair_geometry import (  # noqa: E402
    REPAIR_MASTER_SOLVER_CONFIG,
    RepairGeometry,
    RepairSignature,
    _structural_repair_model,
    derive_archetype_saturation_bounds,
    solve_repair_cardinality_decision,
)
from dynamislm.benchmark.scoring_paths import reachable_error_classes  # noqa: E402
from dynamislm.benchmark.selection_contracts import (  # noqa: E402
    AssignmentState,
    FeatureKind,
    IsolationIdentityKind,
    RelationKind,
    SelectionFeature,
    SelectionSolverConfig,
)
from dynamislm.qualification.res115_authoring import (  # noqa: E402
    AUTHORING_PROCESS_ID,
    _production_authoring_engine_references,
    _required_reference_refusal_fields,
    _scoring_contract,
)
from dynamislm.serialization import canonical_hash  # noqa: E402
from scripts import res407_c08_generator_qualification as previous  # noqa: E402
from scripts import res407_repair_geometry as geometry_script  # noqa: E402

REPORT_PATH = Path("reports/performance_science_eval/res407_real_c08_sufficiency.json")
_SCHEMA = "RES407-REAL-C08-STRUCTURAL-SUFFICIENCY@1.0.0"
_FAMILIES = ("F05", "F06", "F13", "F14")
_SOURCE_FILES = (
    "scripts/res407_c08_generator_qualification.py",
    "scripts/res407_governed_backfill.py",
    "scripts/res407_real_c08_sufficiency.py",
    "src/dynamislm/benchmark/authoring.py",
    "src/dynamislm/benchmark/coverage.py",
    "src/dynamislm/benchmark/production.py",
    "src/dynamislm/benchmark/production_authoring.py",
    "src/dynamislm/benchmark/repair_geometry.py",
    "src/dynamislm/benchmark/scoring_paths.py",
    "src/dynamislm/benchmark/selection_constraints.py",
    "src/dynamislm/benchmark/selection_solver.py",
    "src/dynamislm/qualification/res115_authoring.py",
)
_SOLVER_CONFIG = SelectionSolverConfig(
    workers=8,
    random_seed=REPAIR_MASTER_SOLVER_CONFIG.random_seed,
    timeout_s=300.0,
    cp_model_presolve=True,
)


def _wire_feature(feature: SelectionFeature) -> dict[str, Any]:
    return {"kind": feature.kind.value, "key": feature.key}


def derive_family_feature_contract(family: str) -> dict[str, Any]:
    """Derive selection features from the fixed C08 authoring and scorer path."""

    row = next(item for item in COVERAGE_MATRIX if item.capability_id == "C08")
    if family not in _FAMILIES or family not in row.benchmark_families:
        raise ValueError("family is outside the fixed C08 synthetic generator contract")
    if (
        CaseOrigin.DETERMINISTIC_SYNTHETIC not in row.case_origins
        or ScoringProfile.STRUCTURED_FIELDS_V1 not in row.scorer_profiles
    ):
        raise ValueError("C08 registry no longer authorizes deterministic structured refusal cases")

    _engine_reference, rfd_refusal_reference, generic_refusal_reference = (
        _production_authoring_engine_references()
    )
    reference = rfd_refusal_reference if family in {"F06", "F13"} else generic_refusal_reference
    answer, refusal = _required_reference_refusal_fields(
        reference,
        question="RES-407 structural feature derivation only.",
        safe_description="No numeric result is authorized.",
    )
    scoring = _scoring_contract(
        profile=ScoringProfile.STRUCTURED_FIELDS_V1,
        row=row,
        required_fields=answer.required_field_ids,
        refusal_decision=refusal.decision,
        prohibited_claims=answer.prohibited_claims,
    )
    errors = reachable_error_classes(
        scoring,
        refusal_decision=refusal.decision,
        prohibited_claims=answer.prohibited_claims,
    )
    row_errors = errors.intersection(row.error_classes)
    tags = set(_production_adversarial_tags("C08", family))
    row_tags = tags.intersection(row.adversarial_tags)
    features: set[SelectionFeature] = set()
    features.update(SelectionFeature(FeatureKind.ROW_TAG, ("C08", tag)) for tag in row_tags)
    features.update(
        SelectionFeature(FeatureKind.ROW_ERROR, ("C08", error.value)) for error in row_errors
    )
    if row_tags and row_errors:
        features.add(SelectionFeature(FeatureKind.CELL, ("C08", family)))
    features.update(
        SelectionFeature(FeatureKind.CRITICAL_ERROR, (error.value,))
        for error in errors.intersection(CRITICAL_ERROR_CLASSES)
    )
    if (
        answer.kind is not ExpectedAnswerKind.REFUSAL
        or refusal.decision is not RefusalDecision.REQUIRED
    ):
        raise ValueError("current C08 synthetic path lost its required non-numeric refusal")
    if not row_tags or not row_errors:
        raise ValueError(
            "current C08 synthetic path no longer satisfies selection cell eligibility"
        )

    ordered = tuple(sorted(features, key=lambda item: (item.kind.value, item.key)))
    return {
        "family": family,
        "reference_case_id": reference.case_id,
        "answer_kind": answer.kind.value,
        "refusal_decision": refusal.decision.value,
        "answerable": False,
        "row_tags": tuple(
            sorted(item.key[1] for item in ordered if item.kind is FeatureKind.ROW_TAG)
        ),
        "row_errors": tuple(
            sorted(item.key[1] for item in ordered if item.kind is FeatureKind.ROW_ERROR)
        ),
        "critical_errors": tuple(
            sorted(item.key[0] for item in ordered if item.kind is FeatureKind.CRITICAL_ERROR)
        ),
        "features": tuple(_wire_feature(item) for item in ordered),
        "feature_contract_digest": canonical_hash(tuple(_wire_feature(item) for item in ordered)),
    }


def _matching_candidates(problem: Any, *, relation_kind: str, identity: str) -> tuple[Any, ...]:
    if relation_kind == RelationKind.ISOLATION_CLUSTER.value:
        return tuple(item for item in problem.candidates if item.isolation_cluster_id == identity)
    identity_kind = IsolationIdentityKind(relation_kind)
    return tuple(
        candidate
        for candidate in problem.candidates
        if any(
            item.kind is identity_kind and item.identity == identity
            for item in candidate.isolation_identities
        )
    )


def derive_real_archetype_inventory(
    archetypes: tuple[Any, ...], problem: Any
) -> tuple[dict[str, Any], ...]:
    """Derive all 12 fixed feature, split, origin, and identity contracts."""

    row = next(item for item in COVERAGE_MATRIX if item.capability_id == "C08")
    if set(row.benchmark_families) != set(_FAMILIES):
        raise ValueError("live C08 family support changed")
    generators = {item.generator_family: item for item in PRODUCTION_SYNTHETIC_GENERATORS}
    family_contracts = {family: derive_family_feature_contract(family) for family in _FAMILIES}
    inventory = []
    for archetype in archetypes:
        lane_id, cell = archetype.lane_id, archetype.cell
        family = cell[1]
        split = archetype.locked_split
        if (
            cell[0] != "C08"
            or family not in family_contracts
            or split is None
            or lane_id != f"synthetic:pse-v1-synthetic-refusal-{split.value.lower()}"
            or archetype.origin is not CaseOrigin.DETERMINISTIC_SYNTHETIC
            or archetype.capacity_status.value != "RULE_GOVERNED"
            or archetype.remaining_finite_capacity is not None
        ):
            raise ValueError("live C08 archetype no longer matches its split-family authority")
        generator = generators.get(lane_id.removeprefix("synthetic:"))
        if generator is None or (generator.generator_id, generator.version) != (
            SYNTHETIC_GENERATOR_ID,
            SYNTHETIC_GENERATOR_VERSION,
        ):
            raise ValueError("C08 archetype does not bind the current registered generator")
        features = family_contracts[family]
        cluster = f"PSE-V1-SYNTHETIC-CLUSTER:{split.value}"
        relation_keys = (
            (RelationKind.ISOLATION_CLUSTER.value, cluster),
            (IsolationIdentityKind.GENERATOR_FAMILY.value, generator.generator_family),
            (IsolationIdentityKind.EXPERT_AUTHOR_BATCH.value, AUTHORING_PROCESS_ID),
        )
        relation_rows = []
        for relation_kind, identity in relation_keys:
            matching = _matching_candidates(problem, relation_kind=relation_kind, identity=identity)
            if any(candidate.locked_split is not split for candidate in matching):
                raise ValueError("existing C08 coupling group crosses the archetype split lock")
            relation_rows.append(
                {
                    "relation_kind": relation_kind,
                    "identity": identity,
                    "existing_449_member_count": len(matching),
                    "existing_449_member_splits": tuple(
                        sorted(
                            {candidate.locked_split.value for candidate in matching},
                            key=str.encode,
                        )
                    ),
                }
            )
        inventory.append(
            {
                "lane_id": lane_id,
                "cell": cell,
                "row_tags": features["row_tags"],
                "row_errors": features["row_errors"],
                "critical_errors": features["critical_errors"],
                "answerable": features["answerable"],
                "answer_kind": features["answer_kind"],
                "refusal_decision": features["refusal_decision"],
                "reference_case_id": features["reference_case_id"],
                "selection_features": features["features"],
                "feature_contract_digest": features["feature_contract_digest"],
                "split_lock": split.value,
                "origin": archetype.origin.value,
                "generator_id": generator.generator_id,
                "generator_version": generator.version,
                "generator_family": generator.generator_family,
                "generator_output_contract": generator.output_contract,
                "authoring_process_id": PRODUCTION_AUTHORING_PROCESS_ID,
                "mandatory_relation_identities": relation_keys,
                "mandatory_relation_evidence": tuple(relation_rows),
                "mandatory_colocation": {
                    "split_cluster": "ALL_SELECTED_MEMBERS_SHARE_ONE_SPLIT",
                    "generator_family": "ALL_SELECTED_MEMBERS_SHARE_ONE_SPLIT",
                    "expert_author_batch": "ALL_12_REAL_C08_ARCHETYPES_SHARE_ONE_SPLIT",
                    "repeat_seed_blocks": "UNIQUE_PER_REPEAT; REUSE_REJECTED",
                    "exact_13_token_shingles": "UNKNOWN; NO_NEW_COLLISION_ASSUMED_IN_TEST_MODEL",
                },
                "repeat_authority_maximum": "UNKNOWN",
                "current_recipe_options_per_lane_cell": 1,
                "repeat_ordinal_in_candidate_id": False,
                "repeat_ordinal_in_seed_block_rule": False,
                "seed_namespace_template": (
                    f"PSE-V1/{split.value}/{SYNTHETIC_GENERATOR_ID}:"
                    f"{SYNTHETIC_GENERATOR_VERSION}@{{seed_block}}"
                ),
                "seed_block_rule": (
                    "Unique authorized seed blocks are required; current helper has no repeat "
                    "ordinal or finite repeat maximum. Diagnostic repeats are granted distinct "
                    "candidate-derived IDs and blocks while retaining shared identities above."
                ),
                "selection_contract_basis": (
                    "_production_adversarial_tags; _required_reference_refusal_fields; "
                    "_scoring_contract; reachable_error_classes; "
                    "production commitment feature adapter"
                ),
            }
        )
    result = tuple(sorted(inventory, key=lambda item: (item["lane_id"].encode(), item["cell"])))
    expected = {
        (f"synthetic:pse-v1-synthetic-refusal-{split.value.lower()}", ("C08", family))
        for split in SPLIT_ORDER
        for family in _FAMILIES
    }
    observed = {(item["lane_id"], item["cell"]) for item in result}
    if len(result) != 12 or observed != expected:
        raise ValueError("real C08 archetype inventory is not the exact 3-by-4 contract")
    return result


def build_aggregate_colocation_groups(
    inventory: tuple[dict[str, Any], ...], signatures: tuple[RepairSignature, ...], problem: Any
) -> tuple[dict[str, Any], ...]:
    """Map shared identities to exact base members and aggregate archetype counts."""

    signature_by_key = {(item.lane_id, item.cell): item for item in signatures}
    groups: dict[tuple[str, str], dict[str, set[str]]] = {}
    for item in inventory:
        signature = signature_by_key[item["lane_id"], item["cell"]]
        for relation_kind, identity in item["mandatory_relation_identities"]:
            key = (relation_kind, identity)
            group = groups.setdefault(key, {"signature_ids": set(), "candidate_ids": set()})
            group["signature_ids"].add(signature.signature_id)
    rows_by_members: dict[tuple[tuple[str, ...], tuple[str, ...]], set[tuple[str, str]]] = {}
    for (relation_kind, identity), members in groups.items():
        existing = _matching_candidates(problem, relation_kind=relation_kind, identity=identity)
        members["candidate_ids"].update(item.candidate_id for item in existing)
        signature_ids = tuple(sorted(members["signature_ids"], key=str.encode))
        candidate_ids = tuple(sorted(members["candidate_ids"], key=str.encode))
        if len(signature_ids) + len(candidate_ids) < 2:
            continue
        key = (signature_ids, candidate_ids)
        rows_by_members.setdefault(key, set()).add((relation_kind, identity))
    return tuple(
        {
            "signature_ids": signature_ids,
            "existing_candidate_ids": candidate_ids,
            "relation_identities": tuple(sorted(identities)),
            "group_digest": canonical_hash(
                {
                    "signature_ids": signature_ids,
                    "existing_candidate_ids": candidate_ids,
                    "relation_identities": tuple(sorted(identities)),
                }
            ),
        }
        for (signature_ids, candidate_ids), identities in sorted(rows_by_members.items())
    )


def _build_signatures(
    inventory: tuple[dict[str, Any], ...], archetypes: tuple[Any, ...]
) -> tuple[RepairSignature, ...]:
    archetype_by_key = {(item.lane_id, item.cell): item for item in archetypes}
    signatures = []
    for contract in inventory:
        archetype = archetype_by_key[contract["lane_id"], contract["cell"]]
        signatures.append(
            RepairSignature(
                origin=CaseOrigin(contract["origin"]),
                cell=tuple(contract["cell"]),
                guaranteed_features=tuple(
                    SelectionFeature(FeatureKind(item["kind"]), tuple(item["key"]))
                    for item in contract["selection_features"]
                ),
                split_compatibility=(SplitName(contract["split_lock"]),),
                relation_behavior=(
                    "SHARED_SPLIT_CLUSTER; SHARED_GENERATOR_FAMILY; "
                    "SHARED_EXPERT_AUTHOR_BATCH; UNKNOWN_SHINGLE_RELATIONS_RELAXED"
                ),
                isolation_identity_behavior=(
                    "SHARED_SPLIT_CLUSTER_GENERATOR_FAMILY_AND_EXPERT_AUTHOR_BATCH"
                ),
                lineage_behavior="NOT_MUTATION",
                lane_id=contract["lane_id"],
                lane_capacity=archetype.remaining_finite_capacity,
                capacity_status=archetype.capacity_status,
            )
        )
    return tuple(sorted(signatures, key=lambda item: item.signature_id))


def _add_aggregate_colocation_constraints(
    structural_model: Any, groups: tuple[dict[str, Any], ...]
) -> None:
    model = structural_model.model
    final_n = structural_model.final_n
    for index, group in enumerate(groups):
        indicators = []
        signature_ids = set(group["signature_ids"])
        for split in SPLIT_ORDER:
            indicator = model.new_bool_var(f"aggregate_colocate[{index},{split.value}]")
            indicators.append(indicator)
            terms = [
                structural_model.recourse[signature_id, split] for signature_id in signature_ids
            ]
            state = AssignmentState(split.value)
            terms.extend(
                structural_model.assignments[candidate_id, state]
                for candidate_id in group["existing_candidate_ids"]
            )
            model.add(sum(terms) <= final_n * indicator)
        model.add(sum(indicators) <= 1)


def _solver_config_wire(config: SelectionSolverConfig) -> dict[str, Any]:
    return {item.name: getattr(config, item.name) for item in fields(config)}


def _decision_model_digest(structural_model: Any, maximum_additions: int) -> str:
    model = structural_model.model.clone()
    additions = [
        model.get_int_var_from_proto_index(variable.index)
        for variable in structural_model.additions.values()
    ]
    model.add(sum(additions) <= maximum_additions)
    # OR-Tools 9.15 exposes this proto through its stable text form.
    encoded = str(model.proto).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _solve_decision(structural_model: Any, maximum_additions: int) -> tuple[Any, str]:
    structural_model.assignment_hint = ()
    structural_model.repair_hint = ()
    structural_model.hint_source_trial_digest = None
    model_digest = _decision_model_digest(structural_model, maximum_additions)
    trial = solve_repair_cardinality_decision(
        structural_model,
        maximum_additions,
        solver_config=_SOLVER_CONFIG,
    )
    return trial, model_digest


def _trial_wire(trial: Any, model_digest: str) -> dict[str, Any]:
    diagnostics = trial.diagnostics
    return {
        "maximum_additions": trial.maximum_additions,
        "minimum_additions": trial.minimum_additions,
        "status": trial.status,
        "solver_status": None if diagnostics is None else diagnostics.solver_status,
        "trial_digest": trial.trial_digest,
        "decision_model_digest": model_digest,
        "geometry_digest": trial.geometry_digest,
        "signature_inventory_digest": trial.signature_inventory_digest,
        "solver_profile_version": trial.solver_profile_version,
        "solver_version": trial.solver_version,
        "solver_config": _solver_config_wire(trial.solver_config),
        "incumbent_addition_count": (
            None if diagnostics is None else diagnostics.incumbent_addition_count
        ),
        "best_objective_bound": None if diagnostics is None else diagnostics.best_objective_bound,
        "conflicts": None if diagnostics is None else diagnostics.conflicts,
        "branches": None if diagnostics is None else diagnostics.branches,
        "deterministic_time": None if diagnostics is None else diagnostics.deterministic_time,
        "wall_time_seconds": None if diagnostics is None else diagnostics.wall_seconds,
        "model_variables": None if diagnostics is None else diagnostics.model_variable_count,
        "model_constraints": None if diagnostics is None else diagnostics.constraint_count,
        "lower_bound_source_trial_digest": trial.lower_bound_source_trial_digest,
    }


def _canonical_vector(
    trial: Any, signatures: tuple[RepairSignature, ...]
) -> tuple[dict[str, Any], ...]:
    counts = {item.signature.signature_id: item for item in trial.witness}
    return tuple(
        {
            "lane_id": signature.lane_id,
            "cell": signature.cell,
            "origin": signature.origin.value,
            "split_lock": signature.split_compatibility[0].value,
            "count": counts[signature.signature_id].total_count,
            "split_counts": tuple(
                (split.value, count) for split, count in counts[signature.signature_id].split_counts
            ),
            "selection_features": tuple(
                _wire_feature(feature) for feature in signature.guaranteed_features
            ),
        }
        for signature in sorted(signatures, key=lambda item: (item.lane_id or "", item.cell))
        if signature.signature_id in counts
    )


def _repeat_counts(
    vector: tuple[dict[str, Any], ...], inventory: tuple[dict[str, Any], ...]
) -> tuple[dict[str, Any], ...]:
    counts = {(item["lane_id"], tuple(item["cell"])): item["count"] for item in vector}
    return tuple(
        {
            "lane_id": item["lane_id"],
            "cell": item["cell"],
            "required_repeat_count": counts.get((item["lane_id"], tuple(item["cell"])), 0),
        }
        for item in inventory
    )


def _previous_optimistic_lower_bound(structural_report: dict[str, Any]) -> dict[str, Any]:
    trials = structural_report["cardinality_trials"]
    lower = next(
        item
        for item in trials
        if item["maximum_additions"] == 47 and item["status"] == "INFEASIBLE"
    )
    upper = next(
        item for item in trials if item["maximum_additions"] == 48 and item["status"] == "FEASIBLE"
    )
    proof = structural_report["optimistic_c08_relaxation_proof"]
    if (
        structural_report["optimistic_c08_min_additions"] != 48
        or lower["signature_inventory_digest"] != proof["signature_inventory_digest"]
        or upper["signature_inventory_digest"] != proof["signature_inventory_digest"]
        or structural_report["optimistic_c08_relaxation_proof_status"] != "PASS"
        or sum(item["count"] for item in structural_report["optimistic_c08_repair_vector"]) != 48
    ):
        raise ValueError("previous 48-addition optimistic C08 lower-bound proof is stale")
    return {
        "minimum_additions": 48,
        "status": "PROVEN",
        "lower_trial_digest": lower["trial_digest"],
        "upper_trial_digest": upper["trial_digest"],
        "optimistic_signature_inventory_digest": proof["signature_inventory_digest"],
        "optimistic_relaxation_proof_digest": proof["proof_digest"],
        "optimistic_witness_digest": structural_report["optimistic_c08_vector_digest"],
        "structural_report_receipt_digest": structural_report["receipt_digest"],
    }


def _compare_previous_optimistic_f05_witness(
    inventory: tuple[dict[str, Any], ...], structural_report: dict[str, Any]
) -> dict[str, Any]:
    real = next(
        item
        for item in inventory
        if item["lane_id"] == "synthetic:pse-v1-synthetic-refusal-public_development"
        and item["cell"] == ("C08", "F05")
    )
    real_features = {(item["kind"], tuple(item["key"])) for item in real["selection_features"]}
    optimistic = set(previous._optimistic_features(structural_report))
    missing = tuple(sorted(optimistic - real_features))
    return {
        "status": "NOT_REALIZABLE" if missing else "REALIZABLE",
        "scope": "PREVIOUS 48xC08:F05/PUBLIC OPTIMISTIC FEATURE WITNESS",
        "real_f05_feature_contract_digest": real["feature_contract_digest"],
        "missing_optimistic_features": tuple({"kind": kind, "key": key} for kind, key in missing),
        "structural_comparison_receipt_digest": structural_report["receipt_digest"],
    }


def _assert_real_saturation_inherits_previous_bounds(
    real_bounds: tuple[Any, ...], structural_report: dict[str, Any]
) -> None:
    prior = {
        (item["lane_id"], tuple(item["cell"]), item["split"]): item["upper_bound"]
        for item in structural_report["saturation_proof"]["archetype_bounds"]
    }
    current = {
        (item.lane_id, item.cell, item.split.value): item.upper_bound for item in real_bounds
    }
    if current != prior:
        raise ValueError(
            "real archetype saturation differs from the prior proven structural bounds"
        )


def _build_model(
    geometry: RepairGeometry,
    archetypes: tuple[Any, ...],
    inventory: tuple[dict[str, Any], ...],
    structural_report: dict[str, Any],
) -> tuple[Any, tuple[RepairSignature, ...], tuple[Any, ...], tuple[dict[str, Any], ...]]:
    signatures = _build_signatures(inventory, archetypes)
    bounds = derive_archetype_saturation_bounds(geometry, signatures)
    _assert_real_saturation_inherits_previous_bounds(bounds, structural_report)
    upper_bounds = {item.signature_id: item.upper_bound for item in bounds}
    structural_model = _structural_repair_model(
        geometry, signatures, signature_upper_bounds=upper_bounds
    )
    relation_groups = build_aggregate_colocation_groups(inventory, signatures, geometry.problem)
    _add_aggregate_colocation_constraints(structural_model, relation_groups)
    return structural_model, signatures, bounds, relation_groups


def _repeat_optimistic_proof(
    inventory: tuple[dict[str, Any], ...],
    bounds: tuple[Any, ...],
    groups: tuple[dict[str, Any], ...],
    structural_report: dict[str, Any],
) -> dict[str, Any]:
    c08_row = next(item for item in COVERAGE_MATRIX if item.capability_id == "C08")
    maximal_features_by_cell = {
        ("C08", family): {
            (FeatureKind.CELL.value, ("C08", family)),
            *((FeatureKind.ROW_TAG.value, ("C08", tag)) for tag in c08_row.adversarial_tags),
            *(
                (FeatureKind.ROW_ERROR.value, ("C08", error.value))
                for error in c08_row.error_classes
            ),
            *(
                (FeatureKind.CRITICAL_ERROR.value, (error.value,))
                for error in c08_row.error_classes
                if error in CRITICAL_ERROR_CLASSES
            ),
        }
        for family in _FAMILIES
    }
    prior_contracts = {
        (item["lane_id"], tuple(item["cell"])): item
        for item in structural_report["archetype_contract_inventory"]
    }
    prior_relaxation_rows = {
        item["archetype_digest"]: item
        for item in structural_report["optimistic_c08_relaxation_proof"]["rows"]
    }
    proof_rows = []
    for item in inventory:
        matching_bounds = next(
            bound
            for bound in bounds
            if bound.lane_id == item["lane_id"] and bound.cell == tuple(item["cell"])
        )
        row = {
            "lane_id": item["lane_id"],
            "cell": item["cell"],
            "feature_contract_digest": item["feature_contract_digest"],
            "exact_feature_contract_retained": canonical_hash(tuple(item["selection_features"]))
            == item["feature_contract_digest"],
            "features_subset_previous_maximal_c08_profile": {
                (feature["kind"], tuple(feature["key"])) for feature in item["selection_features"]
            }
            <= maximal_features_by_cell[tuple(item["cell"])],
            "origin_retained": item["origin"],
            "split_lock_retained": item["split_lock"],
            "saturation_upper_bound": matching_bounds.upper_bound,
            "mandatory_relation_identity_count": len(item["mandatory_relation_identities"]),
            "shared_author_batch_identity_retained": AUTHORING_PROCESS_ID
            in {key[1] for key in item["mandatory_relation_identities"]},
            "prior_split_cluster_and_generator_family_contract_retained": (
                prior_relaxation_rows[
                    prior_contracts[item["lane_id"], tuple(item["cell"])]["archetype_digest"]
                ]["valid_overapproximation_row"]
            ),
            "no_new_shingle_collision_assumed": True,
        }
        row["valid_subset_row"] = all(
            (
                row["exact_feature_contract_retained"],
                row["features_subset_previous_maximal_c08_profile"],
                row["origin_retained"] == CaseOrigin.DETERMINISTIC_SYNTHETIC.value,
                row["split_lock_retained"] in {split.value for split in SPLIT_ORDER},
                row["saturation_upper_bound"] > 0,
                row["mandatory_relation_identity_count"] == 3,
                row["shared_author_batch_identity_retained"],
                row["prior_split_cluster_and_generator_family_contract_retained"],
                row["no_new_shingle_collision_assumed"],
            )
        )
        proof_rows.append(row)
    subset_previous_model = all(
        item["features_subset_previous_maximal_c08_profile"]
        and item["prior_split_cluster_and_generator_family_contract_retained"]
        for item in proof_rows
    )
    shared_batch_groups = tuple(
        group
        for group in groups
        if any(
            key[0] == IsolationIdentityKind.EXPERT_AUTHOR_BATCH.value
            for key in group["relation_identities"]
        )
    )
    shared_batch_coupling_retained = (
        len(shared_batch_groups) == 1 and len(shared_batch_groups[0]["signature_ids"]) == 12
    )
    inclusion_proven = (
        len(proof_rows) == 12
        and subset_previous_model
        and shared_batch_coupling_retained
        and all(item["valid_subset_row"] for item in proof_rows)
    )
    body = {
        "status": "PASS" if inclusion_proven else "PARTIAL",
        "claim": "REAL_C08_FEASIBLE_SET_SUBSET_REPEAT_OPTIMISTIC_C08_MODEL",
        "scope": "12 CURRENT REAL C08 ARCHETYPES; AGGREGATE COUNTS THROUGH STRUCTURAL SATURATION",
        "real_archetype_inventory_digest": canonical_hash(inventory),
        "previous_saturation_proof_digest": structural_report["saturation_proof_digest"],
        "previous_optimistic_c08_lower_bound": _previous_optimistic_lower_bound(structural_report),
        "retained_authority": (
            "ALL FIXED ROW_TAG, ROW_ERROR, CRITICAL_ERROR, ANSWERABLE/REFUSAL, CELL, ORIGIN, "
            "SPLIT LOCK, GENERATOR-FAMILY, SPLIT-CLUSTER, AND AUTHOR-BATCH SEMANTICS"
        ),
        "favorable_relaxations": (
            "Repeat availability is granted up to each previously proven structural saturation "
            "bound; this is diagnostic, not repeat-count authority.",
            "Distinct candidate-derived IDs and seed blocks are granted per hypothetical repeat; "
            "shared generator-family, split-cluster, and expert-author-batch identities "
            "remain coupled.",
            "No new exact 13-token shingle collision is assumed.",
            "Unknown review/approval and other non-selection qualification gates are "
            "assumed available.",
        ),
        "seed_identity_behavior": (
            "Seed blocks and split-qualified namespaces remain unique per repeat; they do not "
            "erase shared family, author-batch, or cluster identities."
        ),
        "aggregate_colocation_group_digest": canonical_hash(groups),
        "aggregate_colocation_group_count": len(groups),
        "all_12_shared_author_batch_coupling_retained": shared_batch_coupling_retained,
        "rows": tuple(proof_rows),
        "real_feasible_set_subset_diagnostic_model": inclusion_proven,
        "repeat_optimistic_model_subset_previous_optimistic_c08_model": subset_previous_model,
    }
    body["proof_digest"] = canonical_hash(body)
    return body


def _ideal_lower_bound(geometry: RepairGeometry) -> dict[str, Any]:
    _signatures, _vector, proof = geometry_script._accepted_ideal_witness(geometry)
    return {
        "minimum_additions": proof["minimum_additions"],
        "status": "PROVEN",
        "proof_digest": proof["ideal_result_digest"],
        "lower_trial_digest": proof["lower_trial_digest"],
        "upper_trial_digest": proof["upper_trial_digest"],
    }


def _minimize_after_feasible(
    structural_model: Any,
    signatures: tuple[RepairSignature, ...],
    initial_trial: Any,
    initial_digest: str,
) -> tuple[str, int | None, tuple[dict[str, Any], ...], dict[str, Any], tuple[dict[str, Any], ...]]:
    trials = [_trial_wire(initial_trial, initial_digest)]
    initial_count = initial_trial.diagnostics.incumbent_addition_count
    if initial_count is None:
        raise ValueError("feasible sufficiency solve omitted its aggregate addition count")

    lower_bound = 47
    upper_bound = initial_count
    upper_witness = initial_trial
    if upper_bound < lower_bound:
        raise ValueError("real witness contradicts the proven optimistic-C08 lower bound")
    if upper_bound == lower_bound:
        final_trial, digest = _solve_decision(structural_model, upper_bound)
        trials.append(_trial_wire(final_trial, digest))
        if final_trial.status != "FEASIBLE":
            return "UNKNOWN", None, _canonical_vector(initial_trial, signatures), {}, tuple(trials)
        upper_witness = final_trial

    low_trial = None
    while upper_bound - lower_bound > 1:
        midpoint = (lower_bound + upper_bound) // 2
        trial, digest = _solve_decision(structural_model, midpoint)
        trials.append(_trial_wire(trial, digest))
        if trial.status == "INFEASIBLE":
            lower_bound = midpoint
            low_trial = trial
        elif trial.status == "FEASIBLE":
            count = trial.diagnostics.incumbent_addition_count
            if count is None or count <= lower_bound:
                raise ValueError("cardinality witness contradicts the preceding infeasible bound")
            upper_bound = count
            upper_witness = trial
        else:
            return (
                "UNKNOWN",
                None,
                _canonical_vector(upper_witness, signatures),
                {
                    "proven_lower_bound_exclusive": lower_bound,
                    "feasible_upper_bound": upper_bound,
                    "unknown_trial_digest": trial.trial_digest,
                    "unknown_trial_diagnostics": trials[-1],
                },
                tuple(trials),
            )

    if low_trial is None or low_trial.maximum_additions != upper_bound - 1:
        low_trial, low_digest = _solve_decision(structural_model, upper_bound - 1)
        trials.append(_trial_wire(low_trial, low_digest))
    if low_trial.status != "INFEASIBLE":
        if low_trial.status == "FEASIBLE":
            raise ValueError(
                "adjacent lower cardinality bound is feasible; minimization must continue"
            )
        return (
            "UNKNOWN",
            None,
            _canonical_vector(upper_witness, signatures),
            {
                "proven_lower_bound_exclusive": lower_bound,
                "feasible_upper_bound": upper_bound,
                "unknown_trial_digest": low_trial.trial_digest,
                "unknown_trial_diagnostics": trials[-1],
            },
            tuple(trials),
        )
    final_trial, final_digest = _solve_decision(structural_model, upper_bound)
    trials.append(_trial_wire(final_trial, final_digest))
    if final_trial.status != "FEASIBLE":
        return (
            "UNKNOWN",
            None,
            _canonical_vector(upper_witness, signatures),
            {
                "proven_lower_bound_exclusive": upper_bound - 1,
                "feasible_upper_bound": upper_bound,
                "unknown_trial_digest": final_trial.trial_digest,
                "unknown_trial_diagnostics": trials[-1],
            },
            tuple(trials),
        )
    count = final_trial.diagnostics.incumbent_addition_count
    if count != upper_bound:
        raise ValueError("K feasibility witness does not contain exactly K additions")
    vector = _canonical_vector(final_trial, signatures)
    exactness = {
        "status": "PROVEN",
        "minimum_additions": upper_bound,
        "k_minus_1_status": "INFEASIBLE",
        "k_minus_1_trial_digest": low_trial.trial_digest,
        "k_status": "FEASIBLE",
        "k_trial_digest": final_trial.trial_digest,
        "inherited_optimistic_lower_bound": 48,
        "global_ideal_lower_bound": 12,
    }
    return "PROVEN", upper_bound, vector, exactness, tuple(trials)


def _source_code_digests() -> tuple[dict[str, str], ...]:
    return tuple(
        {
            "path": relative,
            "sha256": "sha256:" + hashlib.sha256((_REPOSITORY / relative).read_bytes()).hexdigest(),
        }
        for relative in _SOURCE_FILES
    )


def capability_from_status(status: str) -> str:
    if status == "INFEASIBLE":
        return "PROVABLY_INSUFFICIENT"
    return "UNRESOLVED"


def authority_expansion_required(status: str) -> bool:
    return status == "INFEASIBLE"


def build_report() -> dict[str, Any]:
    structural_report = json.loads(
        (_REPOSITORY / previous.STRUCTURAL_REPORT_PATH).read_text(encoding="utf-8")
    )
    digest_verification = previous.verify_persisted_digests(structural_report)
    geometry: RepairGeometry = digest_verification["geometry"]
    archetype_record, archetypes = previous._archetype_evidence()
    inventory = derive_real_archetype_inventory(archetypes, geometry.problem)
    inventory_digest = canonical_hash(inventory)
    structural_model, signatures, saturation_bounds, groups = _build_model(
        geometry, archetypes, inventory, structural_report
    )
    relaxation_proof = _repeat_optimistic_proof(
        inventory, saturation_bounds, groups, structural_report
    )
    if relaxation_proof["status"] != "PASS":
        raise ValueError("real C08 feasible-set inclusion proof is incomplete")

    saturation = {
        "per_archetype_bounds": tuple(
            {
                "lane_id": item.lane_id,
                "cell": item.cell,
                "split": item.split.value,
                "upper_bound": item.upper_bound,
                "limits": item.limits,
            }
            for item in saturation_bounds
        ),
        "joint_upper_bound": structural_model.final_n,
        "authority_repeat_maximum": "UNKNOWN",
        "basis_digest": structural_report["saturation_proof_digest"],
    }
    sufficiency_trial, sufficiency_model_digest = _solve_decision(
        structural_model, structural_model.final_n
    )
    sufficiency = _trial_wire(sufficiency_trial, sufficiency_model_digest)
    structural_status = sufficiency_trial.status
    if structural_status == "FEASIBLE":
        cardinality_status, minimum, vector, optimality, trials = _minimize_after_feasible(
            structural_model,
            signatures,
            sufficiency_trial,
            sufficiency_model_digest,
        )
    else:
        cardinality_status, minimum, vector, optimality, trials = (
            "NOT_RUN",
            None,
            (),
            {},
            (sufficiency,),
        )

    if structural_status == "INFEASIBLE":
        missing_capabilities = _derive_missing_capabilities(inventory, geometry)
        outcome = "AUTHORITY_EXPANSION_REQUIRED"
        next_step = "DESIGN_AND_QUALIFY_TYPED_C08_AUTHORITY_EXPANSION"
    elif structural_status == "FEASIBLE":
        missing_capabilities = ()
        outcome = "REPEAT_AUTHORITY_QUALIFICATION_REQUIRED"
        next_step = "QUALIFY_REPEAT_AUTHORITY_FOR_WINNING_VECTOR"
    else:
        missing_capabilities = ()
        outcome = "SOLVER_STATUS_UNKNOWN"
        next_step = "REPLAY_OR_STRENGTHEN_EXACT_STRUCTURAL_FEASIBILITY_MODEL"

    vector_digest = canonical_hash(vector) if vector else None
    report = {
        "schema_version": _SCHEMA,
        "mission": "RES-407 REAL-C08 structural sufficiency test",
        "entry_head": "c227b1f8184112fff3c10e5d00d3815baa4cfa96",
        "geometry_digest": geometry.geometry_digest,
        "problem_digest": geometry.problem.problem_digest,
        "structural_comparison_receipt_digest": structural_report["receipt_digest"],
        "governed_archetype_inventory_digest": archetype_record["archetype_inventory_digest"],
        "real_c08_archetype_count": len(inventory),
        "real_c08_archetype_inventory": inventory,
        "real_c08_archetype_inventory_digest": inventory_digest,
        "feature_contract_derivation": (
            "Derived for all four families from current authoring references, "
            "fixed required-refusal builder, scorer attribution, reachable error paths, "
            "production adversarial-tag mapping, "
            "and the selection feature adapter; no candidate or seed was generated."
        ),
        "mandatory_aggregate_colocation_groups": groups,
        "mandatory_aggregate_colocation_group_digest": canonical_hash(groups),
        "repeat_optimistic_relaxation_proof": relaxation_proof,
        "repeat_optimistic_relaxation_proof_status": relaxation_proof["status"],
        "repeat_optimistic_relaxation_proof_digest": relaxation_proof["proof_digest"],
        "saturation": saturation,
        "previous_optimistic_c08_min_additions": 48,
        "previous_optimistic_c08_lower_bound": _previous_optimistic_lower_bound(structural_report),
        "previous_optimistic_f05_witness_comparison": _compare_previous_optimistic_f05_witness(
            inventory, structural_report
        ),
        "global_ideal_lower_bound": _ideal_lower_bound(geometry),
        "instance_identity_formulas": {
            "candidate_id": (
                "PSE-V1-CANDIDATE:RES407:SYNTH:{capability}:{family}:{split}; no repeat ordinal"
            ),
            "isolation_cluster_id": "PSE-V1-SYNTHETIC-CLUSTER:{split}",
            "source_family_id": "PSE-V1-SYNTHETIC-FAMILY:{candidate_id}",
            "generator_family": "pse-v1-synthetic-refusal-{split_lowercase}",
            "expert_author_batch_id": AUTHORING_PROCESS_ID,
            "seed_namespace": (
                f"PSE-V1/{{split}}/{SYNTHETIC_GENERATOR_ID}:"
                f"{SYNTHETIC_GENERATOR_VERSION}@{{seed_block}}"
            ),
            "seed_block": (
                "res407-{canonical_hash(conflict_set_digest, lane_id, cell)[:48]}; no ordinal"
            ),
            "candidate_artifact_ids": "candidate:{candidate_id}",
            "training_exclusion_id": "qualification-exclusion:{candidate_id}",
        },
        "sufficiency_model": {
            "question": ("ANY feasible augmentation within repeat-optimistic saturation?"),
            "status": structural_status,
            "variable_count": sufficiency_trial.diagnostics.model_variable_count,
            "constraint_count": sufficiency_trial.diagnostics.constraint_count,
            "model_digest": sufficiency_model_digest,
            "archetype_count_variables": len(structural_model.additions),
            "aggregate_split_recourse_variables": len(structural_model.recourse),
            "candidate_replica_variables": 0,
            "recourse": "EXACT_EXISTING_449_ASSIGNMENT_PLUS_AGGREGATE_SPLIT_COUNTS",
            "decision_only_no_cardinality_objective": True,
            "solver": sufficiency,
        },
        "real_c08_structural_status": structural_status,
        "real_c08_min_additions": minimum,
        "real_c08_repair_vector": vector,
        "real_c08_repair_vector_digest": vector_digest,
        "required_repeat_counts_per_lane_cell": _repeat_counts(vector, inventory),
        "cardinality_optimality": cardinality_status,
        "cardinality_proof": optimality,
        "cardinality_trials": trials,
        "current_c08_repair_capability": capability_from_status(structural_status),
        "current_c08_repair_capability_reason": (
            "The repeat-optimistic model determines structural feasibility only. The authorized "
            "repeat maximum remains UNKNOWN, so feasible structural counts are "
            "not current authority."
            if structural_status != "INFEASIBLE"
            else (
                "The exact real-feature, split-locked, coupled model is "
                "infeasible even at saturation."
            )
        ),
        "missing_governed_capabilities": missing_capabilities,
        "outcome": outcome,
        "next_step": next_step,
        "candidate_materialization_invoked": False,
        "concrete_candidates_generated": 0,
        "seeds_generated": 0,
        "human_review_invoked": False,
        "final_allocation_performed": False,
        "ready_for_materialization": False,
        "ready_for_authority_expansion": authority_expansion_required(structural_status),
        "digest_verification": {
            "status": digest_verification["status"],
            "verified_previous_digest_fields": digest_verification["verified_digest_fields"],
            "verified_previous_archetype_count": digest_verification[
                "verified_archetype_digest_count"
            ],
        },
        "source_code_evidence": _source_code_digests(),
        "source_code_evidence_digest": canonical_hash(_source_code_digests()),
        "solver_version": version("ortools"),
        "solver_config": _solver_config_wire(_SOLVER_CONFIG),
    }
    report["report_digest"] = canonical_hash(report)
    return report


def _derive_missing_capabilities(
    inventory: tuple[dict[str, Any], ...], geometry: RepairGeometry
) -> tuple[dict[str, Any], ...]:
    """Type ideal-domain gaps without claiming them when the real model is feasible."""

    _ideal_signatures, ideal_vector, ideal_proof = geometry_script._accepted_ideal_witness(geometry)
    ideal_cells = {item.signature.cell for item in ideal_vector}
    real_cells = {tuple(item["cell"]) for item in inventory}
    ideal_features = {
        (feature.kind.value, feature.key)
        for item in ideal_vector
        for feature in item.signature.guaranteed_features
    }
    real_features = {
        (feature["kind"], tuple(feature["key"]))
        for item in inventory
        for feature in item["selection_features"]
    }
    missing = []
    unsupported_cells = tuple(sorted(ideal_cells - real_cells))
    if unsupported_cells:
        missing.append(
            {
                "capability_kind": "CAPABILITY_FAMILY_SUPPORT",
                "required_behavior": tuple(
                    f"CELL:{cell[0]}:{cell[1]}" for cell in unsupported_cells
                ),
                "current_behavior": "C08_ONLY:F05,F06,F13,F14",
                "evidence": ideal_proof["ideal_result_digest"],
            }
        )
    unsupported_features = ideal_features - real_features
    unsupported_by_kind: dict[str, list[tuple[str, ...]]] = defaultdict(list)
    for kind, key in unsupported_features:
        unsupported_by_kind[kind].append(key)
    for kind in (
        FeatureKind.ROW_TAG.value,
        FeatureKind.ROW_ERROR.value,
        FeatureKind.CRITICAL_ERROR.value,
    ):
        if unsupported_by_kind[kind]:
            missing.append(
                {
                    "capability_kind": kind,
                    "required_behavior": tuple(sorted(unsupported_by_kind[kind])),
                    "current_behavior": "C08_ONLY:F05,F06,F13,F14_FIXED_FEATURES",
                    "evidence": ideal_proof["ideal_result_digest"],
                }
            )
    if unsupported_by_kind[FeatureKind.ANSWERABLE.value]:
        missing.append(
            {
                "capability_kind": "ANSWERABLE_PROFILE",
                "required_behavior": "ANSWERABLE",
                "current_behavior": "REQUIRED_NON_NUMERIC_REFUSAL_FOR_ALL_12_ARCHETYPES",
                "evidence": ideal_proof["ideal_result_digest"],
            }
        )
    ideal_origins = {item.signature.origin.value for item in ideal_vector}
    real_origins = {item["origin"] for item in inventory}
    if ideal_origins - real_origins:
        missing.append(
            {
                "capability_kind": "ORIGIN_SUPPORT",
                "required_behavior": tuple(sorted(ideal_origins - real_origins)),
                "current_behavior": "DETERMINISTIC_SYNTHETIC_ONLY",
                "evidence": ideal_proof["ideal_result_digest"],
            }
        )
    ideal_splits = {split.value for item in ideal_vector for split, _count in item.split_counts}
    if len(ideal_splits) > 1 and len(ideal_vector) > 1:
        missing.append(
            {
                "capability_kind": "SPLIT_SCOPED_INDEPENDENCE",
                "required_behavior": "INDEPENDENT_SELECTION_ACROSS_"
                + "+".join(sorted(ideal_splits)),
                "current_behavior": (
                    "ONE_SPLIT_LOCK_PER_ARCHETYPE; ALL_12_SHARE_ONE_EXPERT_AUTHOR_BATCH"
                ),
                "evidence": ideal_proof["ideal_result_digest"],
            }
        )
    if any(item.signature.isolation_identity_behavior == "FRESH_UNIQUE" for item in ideal_vector):
        missing.append(
            {
                "capability_kind": "ISOLATION_IDENTITY_AND_RELATION_GEOMETRY",
                "required_behavior": "FRESH_UNIQUE_INDEPENDENT_FROM_BASE_AND_OTHER_ADDITIONS",
                "current_behavior": (
                    "SHARED_SPLIT_CLUSTER; SHARED_GENERATOR_FAMILY; SHARED_EXPERT_AUTHOR_BATCH"
                ),
                "evidence": ideal_proof["ideal_result_digest"],
            }
        )
    return tuple(missing)


def verify_report(report: dict[str, Any]) -> None:
    if (
        canonical_hash({key: value for key, value in report.items() if key != "report_digest"})
        != report["report_digest"]
    ):
        raise ValueError("real C08 report digest mismatch")
    if (
        canonical_hash(tuple(report["real_c08_archetype_inventory"]))
        != report["real_c08_archetype_inventory_digest"]
    ):
        raise ValueError("real C08 archetype inventory digest mismatch")
    proof = report["repeat_optimistic_relaxation_proof"]
    if (
        canonical_hash({key: value for key, value in proof.items() if key != "proof_digest"})
        != proof["proof_digest"]
        or proof["proof_digest"] != report["repeat_optimistic_relaxation_proof_digest"]
        or proof["status"] != "PASS"
        or proof["real_feasible_set_subset_diagnostic_model"] is not True
        or proof["repeat_optimistic_model_subset_previous_optimistic_c08_model"] is not True
    ):
        raise ValueError("repeat-optimistic relaxation proof digest or claim mismatch")
    source_evidence = _source_code_digests()
    if tuple(report["source_code_evidence"]) != source_evidence or report[
        "source_code_evidence_digest"
    ] != canonical_hash(source_evidence):
        raise ValueError("real C08 source-code evidence is stale")


def main() -> None:
    report = build_report()
    verify_report(report)
    path = _REPOSITORY / REPORT_PATH
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"REAL_C08_ARCHETYPE_INVENTORY_DIGEST={report['real_c08_archetype_inventory_digest']}")
    print(
        "REPEAT_OPTIMISTIC_RELAXATION_PROOF_DIGEST="
        f"{report['repeat_optimistic_relaxation_proof_digest']}"
    )
    print(f"REAL_C08_STRUCTURAL_STATUS={report['real_c08_structural_status']}")
    print("CONCRETE_CANDIDATES_GENERATED=0")
    print("SEEDS_GENERATED=0")


if __name__ == "__main__":
    main()
