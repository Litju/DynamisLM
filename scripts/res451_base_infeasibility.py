#!/usr/bin/env python3
"""Diagnose the exact immutable RES-405 pool's RES-369 selection infeasibility."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import Any

_REPOSITORY = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(_REPOSITORY), str(_REPOSITORY / "src")]

from dynamislm.benchmark.production_store import (  # noqa: E402
    DEFAULT_PRODUCTION_ROOT,
)
from dynamislm.benchmark.public_repository import (  # noqa: E402
    validate_production_private_material_absent,
)
from dynamislm.benchmark.selection_constraints import _review_eligibility  # noqa: E402
from dynamislm.benchmark.selection_contracts import (  # noqa: E402
    PSE_V1_POOL_FEASIBILITY_SOLVER_PROFILE_V1,
    ConstraintKind,
    FeasibilityStatus,
    FinalSelectionProblem,
)
from dynamislm.benchmark.selection_diagnostics import (  # noqa: E402
    clone_selection_problem,
    constraint_rows_by_id,
    final_count_forced_out_core,
    selection_support_audit,
    selection_support_audit_digest,
)
from dynamislm.benchmark.selection_solver import solve_selection_feasibility  # noqa: E402
from dynamislm.serialization import canonical_hash  # noqa: E402
from scripts import res406_pool_qualification as res406  # noqa: E402

ENTRY_HEAD = "37472376aed4e3e9f55a3e14515f2932c6c98797"
RES406_MERGE_SHA = ENTRY_HEAD
RES406_PRIVATE_RECEIPT_DIGEST = (
    "sha256:38b2b8bf24479ca4734ab800d4905cf9ebdba8f3b3f8d6ce2ba946b25c501016"
)
RES405_RECEIPT_DIGEST = "sha256:8e4dfb324d0aab00196903229814170e0e1f16e54ec348082f57cedb74e65272"
PLAN_DIGEST = "sha256:e42cd6316da25f622203eb1a2340b34a56c4d3baa411773599d1f278b0bce845"
POOL_DIGEST = "sha256:cc901fe4bc1ecd2fe9f3a7f2d294b24c4201b647fe9645ea40a0a5c8ab19f7ca"
BASE_PROBLEM_DIGEST = "sha256:29b85a7b7518c09a40093326a4e4832c6cee7b564d4384806dc9fceeb0abc5c0"
POOL_COUNT = 449
_SUMMARY_PATH = Path("reports/performance_science_eval/res451_base_infeasibility_diagnosis.json")
_PUBLIC_RECEIPT_PATH = Path("docs/qualification/RES-451-ACCEPTANCE-RECEIPT.md")
_BASE_SCHEMA = "RES451-BASE-CONFIRMATION@1.0.0"
_AUDIT_SCHEMA = "RES451-STATIC-AUDIT@1.0.0"
_CONFLICT_SCHEMA = "RES451-CONFLICT-VERIFICATION@1.0.0"
_FINAL_SCHEMA = "RES451-PRIVATE-DIAGNOSIS-RECEIPT@1.0.0"
_CORE_PROFILE_NAME = "PSE_V1_POOL_FEASIBILITY_SOLVER_PROFILE_V1_SINGLE_WORKER_REPLAY"
_CORE_SOLVER_CONFIG = replace(PSE_V1_POOL_FEASIBILITY_SOLVER_PROFILE_V1, workers=1)
Record = dict[str, Any]


def _checkpoint_root(problem: FinalSelectionProblem) -> str:
    return "/".join(
        (
            "production/variable-pools/diagnosis",
            PLAN_DIGEST.removeprefix("sha256:"),
            RES406_MERGE_SHA,
            problem.problem_digest.removeprefix("sha256:"),
        )
    )


def _checkpoint_path(root: str, name: str) -> str:
    return f"{root}/{name}"


def _binding(inputs: Any) -> Record:
    return {
        "entry_head": ENTRY_HEAD,
        "res406_merge_sha": RES406_MERGE_SHA,
        "res406_private_receipt_digest": RES406_PRIVATE_RECEIPT_DIGEST,
        "res405_receipt_digest": RES405_RECEIPT_DIGEST,
        "plan_digest": PLAN_DIGEST,
        "pool_digest": POOL_DIGEST,
        "base_problem_digest": inputs.problem.problem_digest,
        "base_constraint_inventory_digest": inputs.problem.constraint_inventory_digest,
        "solver_profile": res406._profile(),
    }


def _verify_res406_authority(inputs: Any) -> None:
    if (
        inputs.store_receipt.receipt_digest != RES405_RECEIPT_DIGEST
        or inputs.pool.pool_digest != POOL_DIGEST
        or inputs.pool.candidate_count != POOL_COUNT
        or inputs.problem.problem_digest != BASE_PROBLEM_DIGEST
    ):
        raise ValueError("RES-451 exact pool or base problem authority drift")

    old_root = res406._checkpoint_root(inputs.problem)
    base_read = res406._read_record(
        res406._path(old_root, "base-receipt.json"),
        repository_root=inputs.repository_root,
        production_root=inputs.production_root,
    )
    if base_read is None:
        raise ValueError("RES-406 exact base checkpoint is missing")
    base = base_read[0]
    saved_head = base.get("input", {}).get("runner_head")
    if not isinstance(saved_head, str):
        raise ValueError("RES-406 base checkpoint lacks its runner head")
    bound_inputs = replace(inputs, runner_head=saved_head)
    if base.get("input") != res406._base_input(bound_inputs):
        raise ValueError("RES-406 base checkpoint is not bound to the exact pool problem")

    confirmation_read = res406._read_record(
        res406._confirmation_relative(old_root),
        repository_root=inputs.repository_root,
        production_root=inputs.production_root,
    )
    if confirmation_read is None:
        raise ValueError("RES-406 fresh-process confirmation is missing")
    final = res406._verify_final_receipt(
        bound_inputs,
        old_root,
        base,
        (),
        confirmation_read[0],
    )
    if (
        final.get("receipt_digest") != RES406_PRIVATE_RECEIPT_DIGEST
        or final.get("base_status") != FeasibilityStatus.INFEASIBLE.value
        or final.get("problem_digest") != BASE_PROBLEM_DIGEST
        or final.get("pool_digest") != POOL_DIGEST
        or final.get("res405_receipt_digest") != RES405_RECEIPT_DIGEST
    ):
        raise ValueError("RES-406 authoritative qualification receipt does not reconstruct")

    with (inputs.repository_root / res406._SUMMARY_PATH).open(encoding="utf-8") as source:
        public_res406 = json.load(source)
    if public_res406.get("private_qualification_receipt_digest") != RES406_PRIVATE_RECEIPT_DIGEST:
        raise ValueError("RES-406 public summary does not bind its authoritative receipt")


def _load_inputs(repository_root: Path, production_root: Path) -> Any:
    inputs = res406._load_inputs(repository_root, production_root)
    _verify_res406_authority(inputs)
    return inputs


def _base_result_digest(result: Any) -> str:
    return canonical_hash(
        {
            "status": result.status.value,
            "problem_digest": result.problem_digest,
            "candidate_pool_digest": result.candidate_pool_digest,
            "constraint_inventory_digest": result.constraint_inventory_digest,
            "solver_profile": res406._profile(),
            "solver_version": result.solver_version,
            "plan_digest": result.plan_digest,
            "validation_digest": result.validation_digest,
        }
    )


def _write_or_reuse(
    relative: str, body: Record, *, repository_root: Path, production_root: Path
) -> Record:
    expected = res406._bound(body)
    current = res406._read_record(
        relative,
        repository_root=repository_root,
        production_root=production_root,
    )
    if current is not None:
        if current[0] != expected:
            raise ValueError(
                f"RES-451 checkpoint does not exactly match current inputs: {relative}"
            )
        return expected
    return res406._write_record(
        relative,
        body,
        repository_root=repository_root,
        production_root=production_root,
    )


def _base_checkpoint(inputs: Any, root: str, *, run_solver: bool) -> Record:
    relative = _checkpoint_path(root, "base-confirmation.json")
    binding = _binding(inputs)
    existing = res406._read_record(
        relative,
        repository_root=inputs.repository_root,
        production_root=inputs.production_root,
    )
    if existing is not None:
        record = existing[0]
        if record.get("schema_version") != _BASE_SCHEMA or record.get("input") != binding:
            raise ValueError("RES-451 base checkpoint is stale or bound to different inputs")
        if run_solver:
            result = solve_selection_feasibility(
                inputs.problem,
                solver_config=PSE_V1_POOL_FEASIBILITY_SOLVER_PROFILE_V1,
            )
            if result.status.value != record.get("status") or _base_result_digest(
                result
            ) != record.get("result_digest"):
                raise ValueError("fresh exact base confirmation differs from its checkpoint")
        return record

    result = solve_selection_feasibility(
        inputs.problem,
        solver_config=PSE_V1_POOL_FEASIBILITY_SOLVER_PROFILE_V1,
    )
    body = {
        "schema_version": _BASE_SCHEMA,
        "input": binding,
        "status": result.status.value,
        "proof_method": "EXACT_FEASIBILITY_ORACLE",
        "solver_version": result.solver_version,
        "result_digest": _base_result_digest(result),
        "plan_digest": result.plan_digest,
        "validation_digest": result.validation_digest,
        "validation_status": (
            None if result.validation_status is None else result.validation_status.value
        ),
    }
    return _write_or_reuse(
        relative,
        body,
        repository_root=inputs.repository_root,
        production_root=inputs.production_root,
    )


def _review_projection_evidence(inputs: Any) -> Record:
    packet_by_id = {item.candidate_id: item for item in inputs.pool.packets}
    candidate_by_id = {item.candidate_id: item for item in inputs.problem.candidates}
    mismatches = []
    packet_counts: Counter[str] = Counter()
    projection_counts: Counter[str] = Counter()
    for candidate_id, packet in packet_by_id.items():
        packet_status = packet.review_status.value
        projected = candidate_by_id[candidate_id].review_eligibility
        packet_counts[packet_status] += 1
        projection_counts[projected.value] += 1
        if _review_eligibility(packet.review_status) is not projected:
            mismatches.append(
                {
                    "candidate_id": candidate_id,
                    "packet_review_status": packet_status,
                    "projected_review_eligibility": projected.value,
                }
            )
    return {
        "packet_review_status_counts": dict(sorted(packet_counts.items())),
        "projected_review_eligibility_counts": dict(sorted(projection_counts.items())),
        "projection_mismatch_count": len(mismatches),
        "projection_mismatches": mismatches,
    }


def _static_summary(rows: tuple[Record, ...]) -> Record:
    direct = tuple(row for row in rows if row["individually_impossible"])
    by_kind: dict[str, list[Record]] = {}
    for row in rows:
        by_kind.setdefault(row["kind"], []).append(row)

    feature_support = []
    for feature_kind in (
        "CELL",
        "ROW_TAG",
        "ROW_ERROR",
        "C18_REFUSAL",
        "ANSWERABLE",
        "CRITICAL_ERROR",
    ):
        kind_rows = [
            row
            for row in rows
            if row["kind"] == "FEATURE_MINIMUM" and row["feature_kind"] == feature_kind
        ]
        for split in sorted({row["split"] for row in kind_rows if row["split"] is not None}):
            split_rows = [row for row in kind_rows if row["split"] == split]
            feature_support.append(
                {
                    "feature_kind": feature_kind,
                    "split": split,
                    "constraint_count": len(split_rows),
                    "minimum_total": sum(row["minimum"] or 0 for row in split_rows),
                    "raw_support_count_sum": sum(
                        row["raw_support_candidate_count"] for row in split_rows
                    ),
                    "max_lock_compatible_support_sum": sum(
                        row["maximum_support_compatible_with_split_locks"] for row in split_rows
                    ),
                    "forced_out_support_count_sum": sum(
                        row["forced_out_count"] for row in split_rows
                    ),
                    "direct_deficit_count": sum(
                        row["individually_impossible"] for row in split_rows
                    ),
                }
            )

    selected_kinds = (
        ConstraintKind.FINAL_COUNT.value,
        ConstraintKind.SPLIT_COUNT.value,
        ConstraintKind.ORIGIN_BOUNDS.value,
        ConstraintKind.MUTATION_LINEAGE_MINIMUM.value,
    )
    bounded_rows = [
        {
            key: row[key]
            for key in (
                "constraint_id",
                "authority_ref",
                "kind",
                "split",
                "feature_kind",
                "feature_key",
                "origin",
                "minimum",
                "maximum",
                "raw_support_candidate_count",
                "maximum_support_compatible_with_split_locks",
                "forced_out_count",
                "unique_supporting_isolation_groups",
                "unique_mutation_lineages",
                "individually_impossible",
            )
        }
        for row in rows
        if row["kind"] in selected_kinds
    ]
    lock_rows = by_kind.get(ConstraintKind.SYNTHETIC_SPLIT_LOCK.value, [])
    relation_rows = by_kind.get(ConstraintKind.CONDITIONAL_COLOCATION.value, [])
    return {
        "constraint_count": len(rows),
        "constraint_kind_counts": dict(sorted((key, len(value)) for key, value in by_kind.items())),
        "bounded_obligations": bounded_rows,
        "feature_support": feature_support,
        "direct_structural_deficits": [
            {
                key: row[key]
                for key in (
                    "constraint_id",
                    "authority_ref",
                    "kind",
                    "split",
                    "feature_kind",
                    "feature_key",
                    "origin",
                    "minimum",
                    "maximum",
                    "raw_support_candidate_count",
                    "maximum_support_compatible_with_split_locks",
                    "forced_out_count",
                )
            }
            for row in direct
        ],
        "direct_structural_deficit_count": len(direct),
        "synthetic_split_lock_count": len(lock_rows),
        "synthetic_split_lock_forced_out_count": sum(row["forced_out_count"] for row in lock_rows),
        "conditional_colocation_count": len(relation_rows),
        "conditional_colocation_member_count_sum": sum(
            row["raw_support_candidate_count"] for row in relation_rows
        ),
    }


def _authority_arithmetic(problem: FinalSelectionProblem) -> Record:
    constraints = problem.constraint_set.constraints
    final = next(item for item in constraints if item.kind is ConstraintKind.FINAL_COUNT)
    splits = tuple(item for item in constraints if item.kind is ConstraintKind.SPLIT_COUNT)
    origins = tuple(item for item in constraints if item.kind is ConstraintKind.ORIGIN_BOUNDS)
    lineage = next(
        item for item in constraints if item.kind is ConstraintKind.MUTATION_LINEAGE_MINIMUM
    )
    assert final.minimum is not None and final.maximum is not None
    split_min = sum(item.minimum or 0 for item in splits)
    split_max = sum(
        item.maximum if item.maximum is not None else len(problem.candidates) for item in splits
    )
    origin_min = sum(item.minimum or 0 for item in origins)
    origin_max = sum(
        item.maximum if item.maximum is not None else len(problem.candidates) for item in origins
    )
    conflicts = []
    if split_min > final.maximum or split_max < final.minimum:
        conflicts.append("FINAL_COUNT_VS_SPLIT_COUNT_TOTALS")
    if origin_min > final.maximum or origin_max < final.minimum:
        conflicts.append("FINAL_COUNT_VS_ORIGIN_BOUNDS_TOTALS")
    if (lineage.minimum or 0) > final.maximum:
        conflicts.append("MUTATION_LINEAGE_MINIMUM_EXCEEDS_FINAL_COUNT_MAXIMUM")
    return {
        "final_count_minimum": final.minimum,
        "final_count_maximum": final.maximum,
        "split_minimum_total": split_min,
        "split_maximum_total": split_max,
        "origin_minimum_total": origin_min,
        "origin_maximum_total": origin_max,
        "mutation_lineage_minimum": lineage.minimum,
        "authority_arithmetic_conflicts": conflicts,
    }


def _core_profile() -> Record:
    return {
        "name": _CORE_PROFILE_NAME,
        "base_profile": res406._profile(),
        "workers": _CORE_SOLVER_CONFIG.workers,
        "random_seed": _CORE_SOLVER_CONFIG.random_seed,
        "timeout_s": _CORE_SOLVER_CONFIG.timeout_s,
        "canonical_chunk_size": _CORE_SOLVER_CONFIG.canonical_chunk_size,
        "cp_model_presolve": _CORE_SOLVER_CONFIG.cp_model_presolve,
        "randomize_search": _CORE_SOLVER_CONFIG.randomize_search,
    }


def _replay_result(problem: FinalSelectionProblem) -> Record:
    result = solve_selection_feasibility(problem, solver_config=_CORE_SOLVER_CONFIG)
    witness = {
        "plan_digest": result.plan_digest,
        "validation_digest": result.validation_digest,
    }
    return {
        "status": result.status.value,
        "problem_digest": result.problem_digest,
        "active_constraint_inventory_digest": result.constraint_inventory_digest,
        "solver_version": result.solver_version,
        **witness,
        "result_digest": canonical_hash(
            {
                "status": result.status.value,
                "problem_digest": result.problem_digest,
                "constraint_inventory_digest": result.constraint_inventory_digest,
                "solver_profile": _core_profile(),
                "solver_version": result.solver_version,
                **witness,
            }
        ),
    }


def _conflict_record(inputs: Any, root: str, rows: tuple[Record, ...]) -> Record:
    constraint_ids = final_count_forced_out_core(inputs.problem)
    if constraint_ids is None:
        raise ValueError("no deterministic final-count forced-OUT conflict can be established")
    one_state_ids = {
        item.constraint_id
        for item in inputs.problem.constraint_set.constraints
        if item.kind is ConstraintKind.ONE_STATE_PER_CANDIDATE
    }
    core_rows = constraint_rows_by_id(inputs.problem, constraint_ids)
    keep_ids = one_state_ids.union(constraint_ids)
    core_problem = clone_selection_problem(
        inputs.problem,
        (
            item
            for item in inputs.problem.constraint_set.constraints
            if item.constraint_id in keep_ids
        ),
    )
    active_replay = _replay_result(core_problem)
    if active_replay["status"] != FeasibilityStatus.INFEASIBLE.value:
        raise ValueError("reported conflict constraints did not replay as INFEASIBLE")

    deletion_trials = []
    for removed_id in constraint_ids:
        reduced_problem = clone_selection_problem(
            inputs.problem,
            (
                item
                for item in inputs.problem.constraint_set.constraints
                if item.kind is ConstraintKind.ONE_STATE_PER_CANDIDATE
                or (item.constraint_id in constraint_ids and item.constraint_id != removed_id)
            ),
        )
        result = _replay_result(reduced_problem)
        if result["status"] != FeasibilityStatus.FEASIBLE.value:
            raise ValueError(f"removing conflict member did not prove feasibility: {removed_id}")
        deletion_trials.append({"removed_constraint_id": removed_id, **result})

    audit_by_id = {item["constraint_id"]: item for item in rows}
    conflict_rows = tuple(audit_by_id[item.constraint_id] for item in core_rows)
    conflict_digest = canonical_hash(
        {
            "kind": "SUBSET_MINIMAL_CONFLICT_SET",
            "always_active_family": "ONE_STATE_PER_CANDIDATE",
            "constraints": conflict_rows,
        }
    )
    replay = {
        "active_constraints": active_replay,
        "member_removal_trials": deletion_trials,
        "subset_minimality": "PROVEN",
    }
    replay["replay_digest"] = canonical_hash(replay)
    body = {
        "schema_version": _CONFLICT_SCHEMA,
        "input": {
            **_binding(inputs),
            "base_status": FeasibilityStatus.INFEASIBLE.value,
            "core_replay_solver_profile": _core_profile(),
            "static_audit_digest": selection_support_audit_digest(rows),
            "retained_constraint_inventory_digest": core_problem.constraint_inventory_digest,
            "conflict_constraint_ids": list(constraint_ids),
        },
        "kind": "SUBSET_MINIMAL_CONFLICT_SET",
        "constraints": list(conflict_rows),
        "conflict_set_digest": conflict_digest,
        "replay": replay,
    }
    return _write_or_reuse(
        _checkpoint_path(root, "conflict-verification.json"),
        body,
        repository_root=inputs.repository_root,
        production_root=inputs.production_root,
    )


def _artifact_inventory(inputs: Any, root: str) -> tuple[tuple[str, str, int], ...]:
    relative_paths = (
        _checkpoint_path(root, "base-confirmation.json"),
        _checkpoint_path(root, "static-audit.json"),
        _checkpoint_path(root, "conflict-verification.json"),
    )
    inventory = []
    for relative in relative_paths:
        record = res406._read_record(
            relative,
            repository_root=inputs.repository_root,
            production_root=inputs.production_root,
        )
        if record is None:
            raise ValueError(f"diagnosis checkpoint missing from inventory: {relative}")
        inventory.append((relative, record[1], record[2]))
    return tuple(inventory)


def _diagnosis_evidence(
    inputs: Any,
    root: str,
    base: Record,
    static: Record,
    conflict: Record,
    authority_check: Record,
    review_evidence: Record,
) -> Record:
    inventory = _artifact_inventory(inputs, root)
    probe_inventory_digest = canonical_hash(())
    final_count = next(
        row for row in static["constraints"] if row["kind"] == ConstraintKind.FINAL_COUNT.value
    )
    evidence = {
        "entry_head": ENTRY_HEAD,
        "res406_merge_sha": RES406_MERGE_SHA,
        "res406_private_receipt_digest": RES406_PRIVATE_RECEIPT_DIGEST,
        "res405_receipt_digest": RES405_RECEIPT_DIGEST,
        "pool_digest": POOL_DIGEST,
        "base_problem_digest": BASE_PROBLEM_DIGEST,
        "base_constraint_inventory_digest": inputs.problem.constraint_inventory_digest,
        "solver_profile": res406._profile(),
        "base_status": base["status"],
        "static_audit_digest": static["static_audit_digest"],
        "probe_inventory_digest": probe_inventory_digest,
        "conflict_set_kind": conflict["kind"],
        "conflict_constraint_ids": conflict["input"]["conflict_constraint_ids"],
        "conflict_set_digest": conflict["conflict_set_digest"],
        "conflict_replay_digest": conflict["replay"]["replay_digest"],
        "authority_arithmetic": authority_check,
        "review_projection_evidence_digest": canonical_hash(review_evidence),
        "packet_review_status_counts": review_evidence["packet_review_status_counts"],
        "projected_review_eligibility_counts": review_evidence[
            "projected_review_eligibility_counts"
        ],
        "review_projection_mismatch_count": review_evidence["projection_mismatch_count"],
        "final_count_required": final_count["minimum"],
        "final_count_maximum_support": final_count["maximum_support_compatible_with_split_locks"],
        "final_count_forced_out_count": final_count["forced_out_count"],
        "artifact_inventory": [list(item) for item in inventory],
        "artifact_inventory_digest": canonical_hash(inventory),
        "checkpoint_path": root,
        "family_probes_run": 0,
        "families_whose_relaxation_is_feasible": [],
        "families_still_infeasible": "NOT_RUN_STATIC_PROOF",
        "unknown_probes": [],
    }
    evidence["reconstruction_digest"] = canonical_hash(evidence)
    return evidence


def _final_body(evidence: Record) -> Record:
    body: Record = {
        "schema_version": _FINAL_SCHEMA,
        "mission": "RES-451",
        "entry_head": ENTRY_HEAD,
        "res406_merge_sha": RES406_MERGE_SHA,
        "res406_private_receipt_digest": RES406_PRIVATE_RECEIPT_DIGEST,
        "res405_receipt_digest": RES405_RECEIPT_DIGEST,
        "pool_digest": POOL_DIGEST,
        "base_problem_digest": BASE_PROBLEM_DIGEST,
        "base_constraint_inventory_digest": evidence["base_constraint_inventory_digest"],
        "solver_profile": res406._profile(),
        "base_status": evidence["base_status"],
        "static_audit_digest": evidence["static_audit_digest"],
        "probe_inventory_digest": evidence["probe_inventory_digest"],
        "conflict_set_kind": evidence["conflict_set_kind"],
        "conflict_constraint_ids": evidence["conflict_constraint_ids"],
        "conflict_set_digest": evidence["conflict_set_digest"],
        "conflict_replay_digest": evidence["conflict_replay_digest"],
        "root_cause_disposition": "POOL_DEFICIT",
        "root_cause_evidence": {
            "pool_candidate_count": POOL_COUNT,
            "packet_review_status_counts": evidence["packet_review_status_counts"],
            "projected_review_eligibility_counts": evidence["projected_review_eligibility_counts"],
            "review_projection_evidence_digest": evidence["review_projection_evidence_digest"],
            "review_projection_mismatch_count": evidence["review_projection_mismatch_count"],
            "authority_arithmetic_conflicts": evidence["authority_arithmetic"][
                "authority_arithmetic_conflicts"
            ],
            "final_count_required": evidence["final_count_required"],
            "final_count_maximum_support": evidence["final_count_maximum_support"],
            "final_count_forced_out_count": evidence["final_count_forced_out_count"],
        },
        "next_authorized_action": "NONE; RES-451 grants diagnosis authority only",
        "artifact_inventory_digest": evidence["artifact_inventory_digest"],
        "artifact_inventory_scope": (
            "external diagnosis checkpoints, excluding this receipt and public outputs"
        ),
        "checkpoint_path": evidence["checkpoint_path"],
        "fresh_process_confirmation": {
            "status": "PASS",
            "reconstruction_digest": evidence["reconstruction_digest"],
        },
        "pool_mutated": False,
        "authority_changed": False,
        "backfill_executed": False,
    }
    return body


def _make_diagnostic(
    inputs: Any, *, run_base_solver: bool
) -> tuple[Record, Record, Record, Record, Record, Record, str]:
    if inputs.problem.problem_digest != BASE_PROBLEM_DIGEST:
        raise ValueError("RES-451 base problem digest drift; stop diagnosis")
    root = _checkpoint_root(inputs.problem)
    base = _base_checkpoint(inputs, root, run_solver=run_base_solver)
    if base.get("status") != FeasibilityStatus.INFEASIBLE.value:
        raise ValueError("RES-451 base is no longer INFEASIBLE; stop with drift evidence")

    rows = selection_support_audit(inputs.problem)
    static_summary = _static_summary(rows)
    static_digest = selection_support_audit_digest(rows)
    static_body = {
        "schema_version": _AUDIT_SCHEMA,
        "input": {
            **_binding(inputs),
            "active_constraint_inventory_digest": inputs.problem.constraint_inventory_digest,
        },
        "static_audit_digest": static_digest,
        "static_summary": static_summary,
        "constraints": list(rows),
    }
    static = _write_or_reuse(
        _checkpoint_path(root, "static-audit.json"),
        static_body,
        repository_root=inputs.repository_root,
        production_root=inputs.production_root,
    )

    authority_check = _authority_arithmetic(inputs.problem)
    review_evidence = _review_projection_evidence(inputs)
    final_count_row = next(row for row in rows if row["kind"] == ConstraintKind.FINAL_COUNT.value)
    expected_packet_statuses = {"PENDING_HUMAN_REVIEW": POOL_COUNT}
    expected_projection_statuses = {"PENDING": POOL_COUNT}
    if (
        not final_count_row["individually_impossible"]
        or final_count_row["maximum_support_compatible_with_split_locks"] != 0
        or review_evidence["projection_mismatch_count"]
        or review_evidence["packet_review_status_counts"] != expected_packet_statuses
        or review_evidence["projected_review_eligibility_counts"] != expected_projection_statuses
        or authority_check["authority_arithmetic_conflicts"]
    ):
        raise ValueError(
            "static evidence does not establish the expected direct pool deficit; "
            "stop for further diagnosis"
        )

    conflict = _conflict_record(inputs, root, rows)
    evidence = _diagnosis_evidence(
        inputs,
        root,
        base,
        static,
        conflict,
        authority_check,
        review_evidence,
    )
    return base, static, conflict, evidence, authority_check, review_evidence, root


def _confirm(repository_root: Path, production_root: Path) -> Record:
    inputs = _load_inputs(repository_root, production_root)
    base, static, conflict, evidence, _authority, _review, root = _make_diagnostic(
        inputs,
        run_base_solver=True,
    )
    final = _read_receipt(
        _checkpoint_path(root, "final-private-diagnosis-receipt.json"),
        repository_root,
        production_root,
    )
    expected = res406._bound(_final_body(evidence))
    if final != expected:
        raise ValueError("fresh process did not reconstruct the exact private diagnosis receipt")
    return {
        "status": "PASS",
        "base_status": base["status"],
        "base_problem_digest": inputs.problem.problem_digest,
        "static_audit_digest": static["static_audit_digest"],
        "conflict_set_digest": conflict["conflict_set_digest"],
        "conflict_replay_digest": conflict["replay"]["replay_digest"],
        "private_diagnosis_receipt_digest": final["receipt_digest"],
        "reconstruction_digest": evidence["reconstruction_digest"],
    }


def _read_receipt(relative: str, repository_root: Path, production_root: Path) -> Record:
    value = res406._read_record(
        relative,
        repository_root=repository_root,
        production_root=production_root,
    )
    if value is None:
        raise ValueError(f"required RES-451 private receipt is missing: {relative}")
    return value[0]


def _public_constraint_row(row: Record) -> Record:
    public = {
        key: row[key]
        for key in (
            "authority_ref",
            "kind",
            "split",
            "feature_kind",
            "feature_key",
            "origin",
            "minimum",
            "maximum",
            "raw_support_candidate_count",
            "maximum_support_compatible_with_split_locks",
            "forced_out_count",
            "unique_supporting_isolation_groups",
            "unique_mutation_lineages",
        )
    }
    if row["kind"] in {
        ConstraintKind.REVIEW_OUT_ONLY.value,
        ConstraintKind.QUALIFICATION_OUT_ONLY.value,
    }:
        public["constraint_id"] = (
            f"{row['kind']}:sha256:{canonical_hash(row['constraint_id']).removeprefix('sha256:')}"
        )
        public["candidate_scoped_constraint_id_redacted"] = True
    else:
        public["constraint_id"] = row["constraint_id"]
    return public


def _public_payload(
    inputs: Any,
    base: Record,
    static: Record,
    conflict: Record,
    evidence: Record,
    leak_guard: Any,
) -> Record:
    audit_rows = static["constraints"]
    audit_by_id = {item["constraint_id"]: item for item in audit_rows}
    conflict_rows = [
        _public_constraint_row(audit_by_id[item])
        for item in conflict["input"]["conflict_constraint_ids"]
    ]
    review_evidence = _review_projection_evidence(inputs)
    summary = static["static_summary"]
    return {
        "schema_version": "RES451-BASE-INFEASIBILITY-DIAGNOSIS@1.0.0",
        "mission": "RES-451",
        "entry_head": ENTRY_HEAD,
        "res406_merge_sha": RES406_MERGE_SHA,
        "res406_private_receipt_digest": RES406_PRIVATE_RECEIPT_DIGEST,
        "res405_receipt_digest": RES405_RECEIPT_DIGEST,
        "pool_digest": POOL_DIGEST,
        "pool_count": POOL_COUNT,
        "base_problem_digest": BASE_PROBLEM_DIGEST,
        "base_constraint_inventory_digest": inputs.problem.constraint_inventory_digest,
        "solver_profile": res406._profile(public=True),
        "base_status": base["status"],
        "static_audit_digest": static["static_audit_digest"],
        "static_direct_deficit_count": summary["direct_structural_deficit_count"],
        "static_direct_deficits": summary["direct_structural_deficits"],
        "bounded_obligation_support": summary["bounded_obligations"],
        "feature_support": summary["feature_support"],
        "synthetic_split_lock_count": summary["synthetic_split_lock_count"],
        "synthetic_split_lock_forced_out_count": summary["synthetic_split_lock_forced_out_count"],
        "conditional_colocation_count": summary["conditional_colocation_count"],
        "conditional_colocation_member_count_sum": summary[
            "conditional_colocation_member_count_sum"
        ],
        "review_status_counts": review_evidence["packet_review_status_counts"],
        "projected_review_eligibility_counts": review_evidence[
            "projected_review_eligibility_counts"
        ],
        "review_projection_mismatch_count": review_evidence["projection_mismatch_count"],
        "authority_arithmetic": evidence["authority_arithmetic"],
        "family_probes_run": 0,
        "family_probes_skipped_reason": (
            "static direct support deficit proves the exact base infeasible"
        ),
        "families_whose_relaxation_is_feasible": [],
        "families_still_infeasible": "NOT_RUN_STATIC_PROOF",
        "unknown_probes": [],
        "conflict_set_kind": conflict["kind"],
        "conflict_constraint_ids": [row["constraint_id"] for row in conflict_rows],
        "conflict_constraints": conflict_rows,
        "conflict_set_digest": conflict["conflict_set_digest"],
        "conflict_replay": {
            "status": "PASS",
            "active_set_status": conflict["replay"]["active_constraints"]["status"],
            "member_removal_count": len(conflict["replay"]["member_removal_trials"]),
            "member_removal_statuses": sorted(
                {item["status"] for item in conflict["replay"]["member_removal_trials"]}
            ),
            "subset_minimality": conflict["replay"]["subset_minimality"],
        },
        "root_cause_disposition": "POOL_DEFICIT",
        "root_cause_summary": (
            f"All {POOL_COUNT} pre-review packets remain pending human review and project to "
            f"PENDING. RES-369 therefore forces every candidate OUT; the "
            f"{evidence['final_count_required']}-case final-count minimum has maximum support "
            f"{evidence['final_count_maximum_support']}. The constraint bounds are "
            "arithmetically coherent, and the review projection matches packet metadata."
        ),
        "next_authorized_action": "NONE; RES-451 grants diagnosis authority only",
        "probe_inventory_digest": evidence["probe_inventory_digest"],
        "conflict_replay_digest": conflict["replay"]["replay_digest"],
        "private_diagnosis_receipt_digest": evidence["private_diagnosis_receipt_digest"],
        "artifact_inventory_digest": evidence["artifact_inventory_digest"],
        "checkpoint_path": evidence["checkpoint_path"],
        "fresh_process_confirmation": "PASS",
        "public_leak_guard": leak_guard.status,
        "public_leak_guard_head": leak_guard.repository_head,
        "public_repository_artifact_digest": leak_guard.repository_artifact_digest,
        "pool_mutated": False,
        "authority_changed": False,
        "backfill_executed": False,
    }


def _write_public_outputs(repository_root: Path, summary: Record) -> None:
    for relative, content in (
        (_SUMMARY_PATH, json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n"),
        (_PUBLIC_RECEIPT_PATH, _acceptance_receipt(summary)),
    ):
        path = repository_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise ValueError(f"RES-451 public output path is unsafe: {relative}")
        path.write_text(content, encoding="utf-8")


def _acceptance_receipt(summary: Record) -> str:
    lines = (
        "# RES-451 Base Infeasibility Diagnosis",
        "",
        "```text",
        "MISSION=RES-451",
        f"ENTRY_HEAD={summary['entry_head']}",
        f"RES406_MERGE_SHA={summary['res406_merge_sha']}",
        f"RES406_PRIVATE_RECEIPT_DIGEST={summary['res406_private_receipt_digest']}",
        f"RES405_RECEIPT_DIGEST={summary['res405_receipt_digest']}",
        f"POOL_DIGEST={summary['pool_digest']}",
        f"POOL_COUNT={summary['pool_count']}",
        f"BASE_PROBLEM_DIGEST={summary['base_problem_digest']}",
        f"BASE_CONSTRAINT_INVENTORY_DIGEST={summary['base_constraint_inventory_digest']}",
        f"SOLVER_PROFILE={summary['solver_profile']['name']}",
        f"BASE_STATUS={summary['base_status']}",
        f"STATIC_DIRECT_DEFICIT_COUNT={summary['static_direct_deficit_count']}",
        f"STATIC_AUDIT_DIGEST={summary['static_audit_digest']}",
        f"FAMILY_PROBES_RUN={summary['family_probes_run']}",
        f"FAMILY_PROBES_SKIPPED_REASON={summary['family_probes_skipped_reason']}",
        f"CONFLICT_SET_KIND={summary['conflict_set_kind']}",
        f"CONFLICT_SET_DIGEST={summary['conflict_set_digest']}",
        f"CONFLICT_REPLAY={summary['conflict_replay']['status']}",
        f"SUBSET_MINIMALITY={summary['conflict_replay']['subset_minimality']}",
        f"ROOT_CAUSE_DISPOSITION={summary['root_cause_disposition']}",
        f"PRIVATE_DIAGNOSIS_RECEIPT_DIGEST={summary['private_diagnosis_receipt_digest']}",
        f"ARTIFACT_INVENTORY_DIGEST={summary['artifact_inventory_digest']}",
        f"CHECKPOINT_PATH={summary['checkpoint_path']}",
        f"FRESH_PROCESS_CONFIRMATION={summary['fresh_process_confirmation']}",
        f"PUBLIC_LEAK_GUARD={summary['public_leak_guard']}",
        "POOL_MUTATED=NO",
        "AUTHORITY_CHANGED=NO",
        "BACKFILL_EXECUTED=NO",
        f"NEXT_AUTHORIZED_ACTION={summary['next_authorized_action']}",
        "```",
        "",
        summary["root_cause_summary"],
        "",
        "The candidate-scoped review constraint references are redacted as hashes in this public "
        "receipt. Exact conflict rows and candidate identifiers are retained only in the external "
        "private diagnosis receipt.",
        "",
    )
    return "\n".join(lines)


def _run_diagnose(repository_root: Path, production_root: Path) -> Record:
    inputs = _load_inputs(repository_root, production_root)
    base, static, conflict, evidence, authority_check, review_evidence, root = _make_diagnostic(
        inputs,
        run_base_solver=False,
    )
    expected_reconstruction_digest = evidence["reconstruction_digest"]
    private_body = _final_body(evidence)
    private_relative = _checkpoint_path(root, "final-private-diagnosis-receipt.json")
    private_record = _write_or_reuse(
        private_relative,
        private_body,
        repository_root=repository_root,
        production_root=production_root,
    )
    evidence["private_diagnosis_receipt_digest"] = private_record["receipt_digest"]
    if evidence["reconstruction_digest"] != expected_reconstruction_digest:
        raise ValueError("private receipt reconstruction binding changed unexpectedly")

    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join(
        item for item in (str(_REPOSITORY / "src"), environment.get("PYTHONPATH", "")) if item
    )
    fresh = subprocess.run(
        (
            sys.executable,
            str(_REPOSITORY / "scripts/res451_base_infeasibility.py"),
            "confirm",
            "--production-root",
            str(production_root),
        ),
        cwd=repository_root,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    confirmation = json.loads(fresh.stdout)
    if (
        confirmation.get("status") != "PASS"
        or confirmation.get("private_diagnosis_receipt_digest") != private_record["receipt_digest"]
        or confirmation.get("reconstruction_digest") != expected_reconstruction_digest
    ):
        raise ValueError("fresh-process RES-451 reconstruction disagreed with the current receipt")

    private_material = res406._private_material(
        inputs.plan,
        inputs.pool,
        inputs.historical_inputs,
        inputs.exclusion,
    )
    leak_guard = validate_production_private_material_absent(
        private_material,
        repository_root=repository_root,
        candidate_count=POOL_COUNT,
    )
    summary = _public_payload(inputs, base, static, conflict, evidence, leak_guard)
    _write_public_outputs(repository_root, summary)
    post_write_guard = validate_production_private_material_absent(
        private_material,
        repository_root=repository_root,
        candidate_count=POOL_COUNT,
    )
    if post_write_guard.status != "PASS":
        raise ValueError("post-write RES-451 public leak scan failed")

    return {
        "ENTRY_HEAD": ENTRY_HEAD,
        "FINAL_HEAD": subprocess.run(
            ("git", "-C", str(repository_root), "rev-parse", "HEAD"),
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip(),
        "RES405_RECEIPT_DIGEST": RES405_RECEIPT_DIGEST,
        "POOL_DIGEST": POOL_DIGEST,
        "BASE_PROBLEM_DIGEST": BASE_PROBLEM_DIGEST,
        "BASE_CONSTRAINT_INVENTORY_DIGEST": inputs.problem.constraint_inventory_digest,
        "BASE_RECONFIRMATION": base["status"],
        "STATIC_DIRECT_DEFICITS": summary["static_direct_deficit_count"],
        "STATIC_AUDIT_DIGEST": summary["static_audit_digest"],
        "FAMILY_PROBES_RUN": 0,
        "FAMILIES_WHOSE_RELAXATION_IS_FEASIBLE": [],
        "FAMILIES_STILL_INFEASIBLE": "NOT_RUN_STATIC_PROOF",
        "UNKNOWN_PROBES": [],
        "CONFLICT_SET_KIND": conflict["kind"],
        "CONFLICT_CONSTRAINT_IDS": summary["conflict_constraint_ids"],
        "CONFLICT_SET_DIGEST": conflict["conflict_set_digest"],
        "CONFLICT_REPLAY": "PASS",
        "SUBSET_MINIMALITY": conflict["replay"]["subset_minimality"],
        "ROOT_CAUSE_DISPOSITION": summary["root_cause_disposition"],
        "ROOT_CAUSE_SUMMARY": summary["root_cause_summary"],
        "POOL_MUTATED": "NO",
        "AUTHORITY_CHANGED": "NO",
        "BACKFILL_EXECUTED": "NO",
        "PRIVATE_DIAGNOSIS_RECEIPT_DIGEST": private_record["receipt_digest"],
        "ARTIFACT_INVENTORY_DIGEST": summary["artifact_inventory_digest"],
        "CHECKPOINT_PATH": root,
        "FRESH_PROCESS_CONFIRMATION": "PASS",
        "PUBLIC_LEAK_GUARD": leak_guard.status,
        "POST_WRITE_PUBLIC_LEAK_GUARD": post_write_guard.status,
        "FOCUSED_TESTS": "NOT_RUN_BY_RUNNER",
        "FULL_CI": "NOT_RUN_BY_RUNNER",
        "QA_TRACKED_MUTATION": "NOT_CHECKED_BY_RUNNER",
        "NEXT_AUTHORIZED_ACTION": summary["next_authorized_action"],
        "READY_FOR_PR": "NO",
    }


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("diagnose", "confirm"))
    parser.add_argument("--production-root", type=Path, default=DEFAULT_PRODUCTION_ROOT)
    return parser.parse_args()


def main() -> int:
    arguments = _arguments()
    repository_root = _REPOSITORY
    if arguments.action == "confirm":
        result = _confirm(repository_root, arguments.production_root)
    else:
        result = _run_diagnose(repository_root, arguments.production_root)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
