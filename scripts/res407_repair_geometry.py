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
    RepairGeometry,
    SplitCapacityCertificate,
    capacity_problem,
    classify_archetype_repair,
    compute_split_capacity_envelope,
    derive_governed_archetypes,
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
        f"{legacy.RES451_MERGE_SHA}/geometry/v2"
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
            body = {
                "schema_version": "RES407-SPLIT-CAPACITY@1.0.0",
                "geometry_digest": geometry.geometry_digest,
                "ablation": ablate,
                "solver_config": config,
                "certificates": certificates,
                "certificate_digests": tuple(c.result_digest for c in certificates),
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
        if record["schema_version"] != "RES407-SPLIT-CAPACITY@1.0.0":
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
            "schema_version": "RES407-CAPACITY-ENVELOPE@1.0.0",
            "original_problem_digest": inputs.problem.problem_digest,
            "geometry_digest": geometry.geometry_digest,
            "capacity_records": records,
        },
        production_root,
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
