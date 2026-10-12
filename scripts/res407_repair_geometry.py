#!/usr/bin/env python3
"""Persist structural RES-407 diagnostics without authoring candidate packets."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from importlib.metadata import version
from pathlib import Path
from typing import Any

_REPOSITORY = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(_REPOSITORY), str(_REPOSITORY / "src")]

from dynamislm.benchmark.constants import SplitName  # noqa: E402
from dynamislm.benchmark.production_store import DEFAULT_PRODUCTION_ROOT  # noqa: E402
from dynamislm.benchmark.public_repository import (  # noqa: E402
    validate_production_private_material_absent,
)
from dynamislm.benchmark.repair_geometry import (  # noqa: E402
    CAPACITY_RELAXATION,
    REPAIR_MASTER_SOLVER_CONFIG,
    RepairGeometry,
    RepairMasterResult,
    SplitCapacityCertificate,
    archetype_structural_contracts,
    bind_split_capacity_certificate,
    build_ideal_repair_signatures,
    build_optimistic_c08_signatures,
    capacity_problem,
    classify_archetype_repair,
    compare_ideal_to_governed_c08,
    compute_split_capacity_envelope,
    derive_governed_archetypes,
    solve_structural_repair_master,
    structural_bottleneck_evidence,
)
from dynamislm.benchmark.selection_contracts import (  # noqa: E402
    AssignmentState,
    ConstraintKind,
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


def run(production_root: Path, *, replay: bool = False) -> dict[str, Any]:
    legacy._require_execution_tree(clean=False)
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
    master_record = _structural_master_record(
        geometry, archetypes, records, production_root, replay=replay
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
        "IDEAL_REPAIR_STATUS": master_record["ideal_repair_status"],
        "IDEAL_MIN_ADDITIONS": master_record["ideal_min_additions"],
        "IDEAL_REPAIR_SIGNATURES": master_record["ideal_repair_signatures"],
        "IDEAL_REPAIR_DIGEST": master_record["ideal_repair_digest"],
        "ARCHETYPE_STRUCTURAL_CONTRACT_DIGEST": master_record[
            "archetype_structural_contract_digest"
        ],
        "GOVERNED_MASTER_STATUS": master_record["governed_master_status"],
        "GOVERNED_MIN_ADDITIONS": master_record["governed_min_additions"],
        "GOVERNED_REPAIR_VECTOR": master_record["governed_repair_vector"],
        "GOVERNED_REPAIR_DIGEST": master_record["governed_repair_digest"],
        "OPTIMALITY_SCOPE": master_record["optimality_scope"],
        "CURRENT_C08_REPAIR_CAPABILITY": master_record["current_c08_repair_capability"],
        "MISSING_GOVERNED_CAPABILITIES": master_record["missing_governed_capabilities"],
        "MISSING_GOVERNED_CAPABILITIES_STATUS": (
            "COMPLETE"
            if master_record["ideal_repair_status"] == "OPTIMAL"
            else "UNRESOLVED_NO_OPTIMAL_IDEAL_VECTOR"
        ),
        "capacity_certificate_binding_digests": [
            digest
            for capacity_record in records
            for digest in capacity_record["certificate_binding_digests"]
        ],
        "optimistic_c08_master_status": master_record["optimistic_c08_master_status"],
        "optimistic_c08_min_additions": master_record["optimistic_c08_min_additions"],
        "optimistic_c08_repair_digest": master_record["optimistic_c08_repair_digest"],
        "structural_master_record_digest": master_record["receipt_digest"],
        "concrete_candidates_materialized": False,
        "removal_sweep_run": False,
    }
    return summary


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
