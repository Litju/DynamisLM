#!/usr/bin/env python3
"""Search and qualify a governed RES-407 extension of the immutable RES-405 pool."""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import os
import subprocess
import sys
import tempfile
from collections import Counter
from collections.abc import Callable, Iterator
from dataclasses import replace
from pathlib import Path, PurePosixPath
from typing import Any, cast

_REPOSITORY = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(_REPOSITORY), str(_REPOSITORY / "src")]

from dynamislm.benchmark.authority_supply import (  # noqa: E402
    AUTHORITY_SUPPLY_SCHEMA,
    AdditionalCapacityStatus,
    LaneCapacityStatus,
    ReserveCandidateLaneV1,
    build_live_authority_supply_inventory,
)
from dynamislm.benchmark.constants import CaseOrigin, SplitName  # noqa: E402
from dynamislm.benchmark.production_authoring import (  # noqa: E402
    PRODUCTION_SYNTHETIC_GENERATORS,
)
from dynamislm.benchmark.production_store import (  # noqa: E402
    DEFAULT_PRODUCTION_ROOT,
    read_external_production_json,
    replace_external_production_json,
    write_external_production_json,
)
from dynamislm.benchmark.public_repository import (  # noqa: E402
    validate_production_private_material_absent,
)
from dynamislm.benchmark.selection_contracts import (  # noqa: E402
    PSE_V1_POOL_FEASIBILITY_SOLVER_PROFILE_V1,
    FeasibilityStatus,
    ValidationStatus,
)
from dynamislm.benchmark.selection_pool import (  # noqa: E402
    MaterializedBackfillCandidateV1,
    _build_problem,
    _problem_without_candidate,
    validate_materialized_backfill_lane_binding,
)
from dynamislm.benchmark.selection_solver import solve_selection_feasibility  # noqa: E402
from dynamislm.benchmark.variable_pool import (  # noqa: E402
    ProductionAuthoringCandidatePoolV1,
    ProductionCandidateRecipeV1,
    RecipeAuthorityBasis,
    VariablePoolAuthoringPlanV1,
    _lane_identity_matches,
    materialize_variable_pool,
    project_variable_pool_selection_candidates,
    validate_variable_pre_review_pool,
)
from dynamislm.benchmark.variable_pool_store import (  # noqa: E402
    DYNAMISLM_EXECUTION_BASELINE,
    VariablePoolStoreReceiptV1,
    read_variable_pool_store,
    write_variable_pool_store,
)
from dynamislm.serialization import canonical_hash  # noqa: E402
from scripts import res406_pool_qualification as res406  # noqa: E402
from scripts import res451_base_infeasibility as res451  # noqa: E402

ENTRY_HEAD = "1935c25e4fe2774063ac2289807deae5d49b0d63"
BRANCH = "julitocrztuga/res-407-p4a-r2b-conditional-governed-backfill-after-a-typed"
RES405_RECEIPT_DIGEST = "sha256:8e4dfb324d0aab00196903229814170e0e1f16e54ec348082f57cedb74e65272"
ORIGINAL_PLAN_DIGEST = "sha256:e42cd6316da25f622203eb1a2340b34a56c4d3baa411773599d1f278b0bce845"
ORIGINAL_POOL_DIGEST = "sha256:cc901fe4bc1ecd2fe9f3a7f2d294b24c4201b647fe9645ea40a0a5c8ab19f7ca"
ORIGINAL_POOL_COUNT = 449
ORIGINAL_PROBLEM_DIGEST = "sha256:29b85a7b7518c09a40093326a4e4832c6cee7b564d4384806dc9fceeb0abc5c0"
RES406_RECEIPT_DIGEST = "sha256:38b2b8bf24479ca4734ab800d4905cf9ebdba8f3b3f8d6ce2ba946b25c501016"
RES451_MERGE_SHA = ENTRY_HEAD
RES451_RECEIPT_DIGEST = "sha256:5810515026f245cb7fd347ebb534290c8c764750830debe248c1589ac7fe7b3e"
RES451_CONFLICT_SET_DIGEST = (
    "sha256:95ab233b97a8e023deb959973d4ab38219d24153bb9e4cf41d03c09a06155f40"
)
RES451_STATIC_AUDIT_DIGEST = (
    "sha256:808909dea13112411c52d51d6e5a42fb8386027da1b377516589015ba77cb451"
)
RES451_PROBE_INVENTORY_DIGEST = (
    "sha256:6ca17dbe773c6365ebea92f9827087b905287a171a43fe0fc0484a7863bac102"
)
LIVE_SUPPLY_INVENTORY_DIGEST = (
    "sha256:4b7ee2d0f9b3f1b56a638b0b27aa01a5ba153e226f34c37bb995dd113292c616"
)
_CHECKPOINT_SCHEMA = "RES407-CHECKPOINT@1.0.0"
_FINAL_SCHEMA = "RES407-PRIVATE-RECEIPT@1.0.0"
_LINEAGE_SCHEMA = "RES407-REPAIRED-POOL-LINEAGE@1.0.0"
_SUMMARY_PATH = Path("reports/performance_science_eval/res407_governed_backfill.json")
_PUBLIC_RECEIPT_PATH = Path("docs/qualification/RES-407-ACCEPTANCE-RECEIPT.md")
Record = dict[str, Any]


def _git(*args: str) -> str:
    return subprocess.run(
        ("git", "-C", str(_REPOSITORY), *args),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _require_execution_tree(*, clean: bool) -> str:
    head = _git("rev-parse", "HEAD")
    if _git("branch", "--show-current") != BRANCH:
        raise ValueError("RES-407 runner is on the wrong branch")
    if _git("rev-parse", ENTRY_HEAD) != ENTRY_HEAD:
        raise ValueError("RES-407 entry head is missing")
    for ancestor in (ENTRY_HEAD, DYNAMISLM_EXECUTION_BASELINE):
        subprocess.run(
            ("git", "-C", str(_REPOSITORY), "merge-base", "--is-ancestor", ancestor, head),
            check=True,
            capture_output=True,
        )
    if clean and _git("status", "--porcelain=v1"):
        raise ValueError("RES-407 execution requires a clean committed runner tree")
    return head


def _checkpoint_root() -> str:
    return "/".join(
        (
            "production/variable-pools/backfill",
            ORIGINAL_PLAN_DIGEST.removeprefix("sha256:"),
            RES451_MERGE_SHA,
            LIVE_SUPPLY_INVENTORY_DIGEST.removeprefix("sha256:"),
            ORIGINAL_PROBLEM_DIGEST.removeprefix("sha256:"),
        )
    )


def _path(root: str, leaf: str) -> str:
    return f"{root}/{leaf}"


def _trial_relative(root: str, candidate_digests: tuple[str, ...]) -> str:
    return _path(
        root,
        f"trials/{len(candidate_digests):04d}-{canonical_hash(candidate_digests).removeprefix('sha256:')}.json",
    )


def _read_record(relative: str, production_root: Path) -> tuple[Record, str, int] | None:
    return res406._read_record(
        relative,
        repository_root=_REPOSITORY,
        production_root=production_root,
    )


def _wire_record(value: object) -> Record:
    normalized = res406._wire(value)
    if not isinstance(normalized, dict):
        raise ValueError("RES-407 checkpoint must serialize to a JSON object")
    return cast(Record, normalized)


def _write_or_reuse(relative: str, body: Record, production_root: Path) -> Record:
    normalized = _wire_record(body)
    expected = res406._bound(normalized)
    current = _read_record(relative, production_root)
    if current is not None:
        if current[0] != expected:
            raise ValueError(f"RES-407 checkpoint differs from current exact inputs: {relative}")
        return expected
    return res406._write_record(
        relative,
        normalized,
        repository_root=_REPOSITORY,
        production_root=production_root,
    )


def _replace_record(relative: str, body: Record, production_root: Path) -> Record:
    current = _read_record(relative, production_root)
    if current is None:
        raise ValueError(f"RES-407 receipt replacement target is missing: {relative}")
    record = res406._bound(_wire_record(body))
    replace_external_production_json(
        record,
        relative,
        expected_digest=current[1],
        repository_root=_REPOSITORY,
        production_root=production_root,
    )
    stored = _read_record(relative, production_root)
    if stored is None or stored[0] != record:
        raise ValueError("RES-407 receipt replacement did not round-trip")
    return record


def _write_typed_or_reuse(
    relative: str, value: Any, expected_type: type[Any], production_root: Path
) -> None:
    path = production_root / relative
    if path.exists():
        current, _digest, _size = read_external_production_json(
            relative,
            expected_type,
            repository_root=_REPOSITORY,
            production_root=production_root,
        )
        if current != value:
            raise ValueError(
                f"RES-407 typed option artifact differs from current inputs: {relative}"
            )
        return
    write_external_production_json(
        value,
        relative,
        repository_root=_REPOSITORY,
        production_root=production_root,
    )


def _diagnosis_record(inputs: Any, production_root: Path) -> Record:
    relative = "/".join(
        (
            "production/variable-pools/diagnosis",
            ORIGINAL_PLAN_DIGEST.removeprefix("sha256:"),
            res451.RES406_MERGE_SHA,
            ORIGINAL_PROBLEM_DIGEST.removeprefix("sha256:"),
            "final-private-diagnosis-receipt.json",
        )
    )
    record = res451._read_receipt(relative, _REPOSITORY, production_root)
    if record["receipt_digest"] != RES451_RECEIPT_DIGEST:
        raise ValueError("RES-451 private diagnosis receipt digest drift")
    if (
        record["conflict_set_digest"] != RES451_CONFLICT_SET_DIGEST
        or record["static_audit_digest"] != RES451_STATIC_AUDIT_DIGEST
        or record["probe_inventory_digest"] != RES451_PROBE_INVENTORY_DIGEST
        or record["root_cause_disposition"] != "POOL_DEFICIT"
        or record["base_status"] != FeasibilityStatus.INFEASIBLE.value
    ):
        raise ValueError("RES-451 diagnosis evidence differs from mission authority")
    _base, _static, conflict, evidence, _authority, _review, _probes, _root = (
        res451._make_diagnostic(inputs, run_base_solver=False, verify_probes=False)
    )
    if (
        conflict["conflict_set_digest"] != RES451_CONFLICT_SET_DIGEST
        or res406._bound(res451._final_body(evidence)) != record
    ):
        raise ValueError("RES-451 private diagnosis receipt does not reconstruct")
    return record


def _original_store_digest(inputs: Any, production_root: Path) -> str:
    directory = production_root / inputs.store_receipt.store_relative_path
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("RES-405 immutable store is unavailable or unsafe")
    files: list[tuple[str, str, int]] = []
    for parent, directories, filenames in os.walk(directory, followlinks=False):
        for name in directories:
            path = Path(parent) / name
            if path.is_symlink() or not path.is_dir():
                raise ValueError("RES-405 immutable store contains an unsafe directory")
        for name in filenames:
            path = Path(parent) / name
            if path.is_symlink() or not path.is_file():
                raise ValueError("RES-405 immutable store contains an unsafe artifact")
            payload = path.read_bytes()
            files.append(
                (
                    path.relative_to(directory).as_posix(),
                    "sha256:" + hashlib.sha256(payload).hexdigest(),
                    len(payload),
                )
            )
    files.sort(key=lambda item: item[0].encode())
    if len(files) != ORIGINAL_POOL_COUNT + 2:
        raise ValueError("RES-405 immutable store has an unexpected artifact count")
    return canonical_hash(tuple(files))


def _assert_original_store_unchanged(before: str, after: str) -> None:
    if before != after:
        raise ValueError("RES-405 immutable pool/store changed during RES-407")


def _pool_store_relative_path(plan_digest: str) -> str:
    return f"production/variable-pools/{plan_digest.removeprefix('sha256:')}"


def _lane_remaining(lane: ReserveCandidateLaneV1, consumed: int) -> int | None:
    if consumed < 0:
        raise ValueError("lane consumption cannot be negative")
    capacity = lane.additional_authorable_capacity
    if capacity is None:
        return None
    return max(0, capacity - consumed)


def _supply_enumeration(inputs: Any) -> tuple[Record, tuple[ReserveCandidateLaneV1, ...]]:
    inventory = build_live_authority_supply_inventory(
        repository_root=_REPOSITORY,
        production_root=inputs.production_root,
    )
    if (
        inventory.schema_version != AUTHORITY_SUPPLY_SCHEMA
        or inventory.inventory_digest != LIVE_SUPPLY_INVENTORY_DIGEST
        or inventory != inputs.inventory
    ):
        raise ValueError("current live v1.3 authority inventory differs from RES-405 authority")
    recipe_by_id = {item.candidate_id: item for item in inputs.plan.recipes}
    consumed: Counter[str] = Counter()
    for recipe in inputs.plan.recipes:
        matches = tuple(
            lane
            for lane in inventory.reserve_candidate_lanes
            if _lane_identity_matches(recipe, lane, recipe_by_id)
        )
        if len(matches) != 1:
            raise ValueError("RES-405 recipe does not resolve to exactly one live authority lane")
        consumed[matches[0].lane_id] += 1

    rows: list[Record] = []
    for lane in inventory.reserve_candidate_lanes:
        count = consumed[lane.lane_id]
        if lane.capacity_status is LaneCapacityStatus.EXISTING_RECIPE_INVENTORY:
            if count != lane.available_capacity:
                raise ValueError("RES-405 did not consume the exact existing recipe inventory")
        elif lane.capacity_status is LaneCapacityStatus.AVAILABLE:
            if count > (lane.available_capacity or 0):
                raise ValueError("RES-405 exceeded finite source lane capacity")
        elif lane.capacity_status is LaneCapacityStatus.EXHAUSTED and count:
            raise ValueError("RES-405 consumed a lane recorded as exhausted")
        rows.append(
            {
                "lane_id": lane.lane_id,
                "origin_class": lane.origin_class,
                "supported_cells": lane.supported_cells,
                "authority_ref": lane.authority_ref,
                "authority_digest": lane.authority_digest,
                "capacity_status": lane.capacity_status,
                "finite_capacity": lane.available_capacity,
                "existing_planned_capacity": lane.existing_planned_capacity,
                "capacity_rule": lane.capacity_rule,
                "isolation_identity_requirements": lane.isolation_identity_digests,
                "current_consumed_capacity": count,
                "remaining_capacity": (
                    None
                    if lane.available_capacity is None
                    else max(0, lane.available_capacity - count)
                ),
                "additional_authorable_capacity": lane.additional_authorable_capacity,
                "remaining_additional_authorable_capacity": _lane_remaining(lane, count),
                "additional_capacity_status": lane.additional_capacity_status,
                "authoring_mechanism": _lane_mechanism(lane),
            }
        )
    if sum(consumed.values()) != ORIGINAL_POOL_COUNT:
        raise ValueError("RES-405 lane accounting does not cover the exact immutable pool")
    body: Record = {
        "schema_version": _CHECKPOINT_SCHEMA,
        "inventory_digest": inventory.inventory_digest,
        "authority_inventory_complete": inventory.authority_inventory_complete,
        "capacity_scope_complete": inventory.capacity_scope_complete,
        "original_pool_digest": inputs.pool.pool_digest,
        "original_pool_count": inputs.pool.candidate_count,
        "lanes": rows,
        "lane_count": len(rows),
        "consumed_recipe_count": sum(consumed.values()),
    }
    return body, inventory.reserve_candidate_lanes


def _lane_mechanism(lane: ReserveCandidateLaneV1) -> str:
    return {
        CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION: (
            "Phase-A exact source selection through production_source_selection_universe and "
            "_author_source_packets"
        ),
        CaseOrigin.DETERMINISTIC_SYNTHETIC: (
            "registered generator through materialize_variable_pool and _author_synthetic_packets"
        ),
        CaseOrigin.DETERMINISTIC_ENGINE_DERIVED: "no additional recipe authority in current lane",
        CaseOrigin.EXPERT_AUTHORED_SEMANTIC: "no additional recipe authority in current lane",
        CaseOrigin.ADVERSARIAL_MUTATION: "no additional recipe authority in current lane",
    }[lane.origin_class]


def _repair_demand(diagnosis: Record) -> Record:
    evidence = diagnosis["root_cause_evidence"]
    slices = evidence["conflict_family_slices"]
    names = {item["family_id"] for item in slices}
    required = {
        "SPLIT_COUNT",
        "FEATURE_MINIMUM:CELL",
        "CONDITIONAL_COLOCATION / isolation",
    }
    if not required.issubset(names):
        raise ValueError("RES-451 conflict geometry does not match the mission repair scope")
    return {
        "schema_version": "RES407-TYPED-REPAIR-DEMAND@1.0.0",
        "original_problem_digest": ORIGINAL_PROBLEM_DIGEST,
        "res451_private_receipt_digest": RES451_RECEIPT_DIGEST,
        "conflict_set_digest": RES451_CONFLICT_SET_DIGEST,
        "root_cause_disposition": diagnosis["root_cause_disposition"],
        "conflict_family_slices": slices,
        "conflict_family_slices_digest": canonical_hash(slices),
        "candidate_authority_rule": (
            "materialize one deterministic option per current rule-governed generator lane and "
            "supported cell; retain the generator-mandated split lock and all current constraints"
        ),
        "protected_split_membership_allocated": False,
    }


def _synthetic_option_recipes(
    demand: Record,
    lanes: tuple[ReserveCandidateLaneV1, ...],
    original_plan: VariablePoolAuthoringPlanV1,
) -> tuple[ProductionCandidateRecipeV1, ...]:
    generators = {item.generator_family: item for item in PRODUCTION_SYNTHETIC_GENERATORS}
    existing_ids = {item.candidate_id for item in original_plan.recipes}
    recipes: list[ProductionCandidateRecipeV1] = []
    for lane in lanes:
        if (
            lane.origin_class is not CaseOrigin.DETERMINISTIC_SYNTHETIC
            or lane.additional_capacity_status is not AdditionalCapacityStatus.RULE_GOVERNED
        ):
            continue
        family_name = lane.lane_id.removeprefix("synthetic:")
        generator = generators.get(family_name)
        if generator is None or canonical_hash(generator) != lane.authority_digest:
            raise ValueError("synthetic lane has no exact registered materializer")
        split = next(
            (value for value in SplitName if family_name.endswith(value.value.lower())), None
        )
        if split is None:
            raise ValueError("synthetic authority lane does not mandate a recognized split lock")
        for capability, family in lane.supported_cells:
            if capability != "C08":
                raise ValueError(
                    "registered synthetic generator advertises an unsupported capability"
                )
            seed_block = (
                "res407-"
                + canonical_hash(
                    (demand["conflict_set_digest"], lane.lane_id, (capability, family))
                ).removeprefix("sha256:")[:48]
            )
            candidate_id = f"PSE-V1-CANDIDATE:RES407:SYNTH:{capability}:{family}:{split.value}"
            if candidate_id in existing_ids:
                raise ValueError("governed synthetic option collides with an original candidate ID")
            recipe = ProductionCandidateRecipeV1(
                candidate_id=candidate_id,
                origin_class=CaseOrigin.DETERMINISTIC_SYNTHETIC,
                capability_id=capability,
                benchmark_family=family,
                authority_basis=RecipeAuthorityBasis.GOVERNED_SUPPLY_LANE,
                authority_ref=lane.authority_ref,
                authority_digest=lane.authority_digest,
                lane_id=lane.lane_id,
                generator_family=generator.generator_family,
                split_lock=split,
                seed_block=seed_block,
            )
            if not _lane_identity_matches(
                recipe,
                lane,
                {
                    **{item.candidate_id: item for item in original_plan.recipes},
                    candidate_id: recipe,
                },
            ):
                raise ValueError("governed synthetic recipe does not bind its exact lane")
            recipes.append(recipe)
    result = tuple(sorted(recipes, key=lambda item: item.candidate_id.encode()))
    if len({item.candidate_id for item in result}) != len(result):
        raise ValueError("governed candidate options contain a duplicate identity")
    return result


def _option_digest(recipe: ProductionCandidateRecipeV1, packet: Any) -> str:
    return canonical_hash(
        {
            "candidate_identity_digest": canonical_hash(recipe.candidate_id),
            "candidate_payload_digest": packet.candidate_payload_hash,
            "recipe_digest": recipe.recipe_digest,
            "lane_id": recipe.lane_id,
            "lane_authority_digest": recipe.authority_digest,
        }
    )


def _option_order(options: tuple[Record, ...]) -> tuple[Record, ...]:
    return tuple(sorted(options, key=lambda item: item["candidate_digest"].encode()))


def _option_inventory_body(options: tuple[Record, ...], demand_digest: str) -> Record:
    return {
        "schema_version": _CHECKPOINT_SCHEMA,
        "original_pool_digest": ORIGINAL_POOL_DIGEST,
        "repair_demand_digest": demand_digest,
        "supply_inventory_digest": LIVE_SUPPLY_INVENTORY_DIGEST,
        "option_count": len(options),
        "options": tuple(
            {
                "candidate_id": item["candidate_id"],
                "candidate_digest": item["candidate_digest"],
                "candidate_payload_digest": item["candidate_payload_digest"],
                "origin_class": item["origin_class"],
                "cell": item["cell"],
                "lane_id": item["lane_id"],
                "lane_authority_ref": item["lane_authority_ref"],
                "lane_authority_digest": item["lane_authority_digest"],
                "recipe_digest": item["recipe_digest"],
            }
            for item in options
        ),
        "option_order": "candidate_digest ascending",
    }


def _addition_sets(options: tuple[Record, ...]) -> Iterator[tuple[Record, ...]]:
    ordered = _option_order(options)
    for size in range(1, len(ordered) + 1):
        yield from itertools.combinations(ordered, size)


def _search_repair_sets(
    options: tuple[Record, ...],
    evaluate: Callable[[tuple[Record, ...]], Record],
    *,
    superset_screen: Callable[[tuple[Record, ...]], Record] | None = None,
) -> tuple[tuple[Record, ...] | None, str, tuple[Record, ...]]:
    outcomes: list[Record] = []
    ordered = _option_order(options)
    if superset_screen is not None and ordered:
        screened = superset_screen(ordered)
        outcomes.append(screened)
        if screened["qualification_status"] == "UNKNOWN":
            return None, "UNKNOWN", tuple(outcomes)
        if screened["qualification_status"] == "INFEASIBLE":
            return None, "NO_FEASIBLE_SET_IN_BOUNDED_OPTIONS", tuple(outcomes)
        if screened["qualification_status"] != "BASE_FEASIBLE":
            raise ValueError("RES-407 maximum-set screen returned an invalid status")
    for selected in _addition_sets(options):
        result = evaluate(tuple(selected))
        outcomes.append(result)
        if result["qualification_status"] == "QUALIFIED":
            return tuple(selected), "QUALIFIED", tuple(outcomes)
        if result["qualification_status"] == "UNKNOWN":
            return None, "UNKNOWN", tuple(outcomes)
    return None, "NO_QUALIFIED_SET_IN_BOUNDED_OPTIONS", tuple(outcomes)


def _minimize_repair_set(
    selected: tuple[Record, ...],
    reduced_status: Callable[[tuple[Record, ...]], str],
) -> tuple[tuple[Record, ...], str]:
    retained = list(_option_order(selected))
    index = 0
    while index < len(retained):
        candidate = retained[index]
        reduced = tuple(item for item in retained if item is not candidate)
        status = reduced_status(reduced)
        if status == FeasibilityStatus.UNKNOWN.value:
            return tuple(retained), "UNKNOWN"
        if status == FeasibilityStatus.FEASIBLE.value:
            retained.pop(index)
            index = 0
        elif status == FeasibilityStatus.INFEASIBLE.value:
            index += 1
        else:
            raise ValueError("RES-407 minimization received an invalid exact solver status")
    return tuple(retained), "INCLUSION_MINIMAL_PROVEN"


def _authority_exhaustion_proven(
    inventory: Any,
    exact_demand: bool,
    materializable_option_count: int,
    remaining_finite_capacity: int,
) -> bool:
    return bool(
        exact_demand
        and inventory.authority_inventory_complete
        and inventory.capacity_scope_complete
        and materializable_option_count == 0
        and remaining_finite_capacity == 0
    )


def _qualification_status(
    *,
    checked: int,
    candidate_count: int,
    feasible: int,
    infeasible: int,
    unknown: int,
    critical_status: str,
    backfill_needs: tuple[Any, ...] | list[Any],
) -> str:
    if unknown:
        return "UNKNOWN"
    if (
        checked == candidate_count
        and feasible == candidate_count
        and infeasible == 0
        and critical_status == "PASS"
        and not backfill_needs
    ):
        return "QUALIFIED"
    return "NOT_QUALIFIED"


def _trial_body(
    *,
    inputs: Any,
    demand: Record,
    options: tuple[Record, ...],
    pool: ProductionAuthoringCandidatePoolV1,
    problem: Any,
    result: Any,
) -> Record:
    return {
        "schema_version": "RES407-REPAIR-SET-TRIAL@1.0.0",
        "original_pool_digest": inputs.pool.pool_digest,
        "diagnosis_receipt_digest": RES451_RECEIPT_DIGEST,
        "conflict_set_digest": RES451_CONFLICT_SET_DIGEST,
        "supply_inventory_digest": inputs.inventory.inventory_digest,
        "repair_demand_digest": canonical_hash(demand),
        "addition_candidate_digests": tuple(item["candidate_digest"] for item in options),
        "lane_authority_bindings": tuple(
            (
                item["candidate_digest"],
                item["lane_id"],
                item["lane_authority_digest"],
            )
            for item in options
        ),
        "addition_set_digest": canonical_hash(tuple(item["candidate_digest"] for item in options)),
        "resulting_plan_digest": pool.authoring_plan_digest,
        "resulting_pool_digest": pool.pool_digest,
        "resulting_problem_digest": problem.problem_digest,
        "solver_profile": res406._profile(),
        "status": result.status.value,
        "solver_version": result.solver_version,
        "plan_digest": result.plan_digest,
        "validation_digest": result.validation_digest,
        "validation_status": (
            None if result.validation_status is None else result.validation_status.value
        ),
    }


def _problem_for_options(
    inputs: Any,
    options: tuple[Record, ...],
    staged_projected: tuple[Any, ...],
) -> tuple[Any, Any, Any]:
    selected_ids = {item["candidate_id"] for item in options}
    original_ids = {item.candidate_id for item in inputs.pool.packets}
    packets = tuple(
        packet
        for packet in inputs.pool.packets + tuple(item["packet"] for item in options)
        if packet.candidate_id in original_ids or packet.candidate_id in selected_ids
    )
    recipes = tuple(
        sorted(
            (
                *inputs.plan.recipes,
                *(item["recipe"] for item in options),
            ),
            key=lambda item: item.candidate_id.encode(),
        )
    )
    plan = VariablePoolAuthoringPlanV1(
        supply_inventory_digest=inputs.inventory.inventory_digest,
        qualification_exclusion_digest=inputs.exclusion.commitment_digest,
        recipes=recipes,
    )
    pool = ProductionAuthoringCandidatePoolV1(
        authoring_plan_digest=plan.plan_digest,
        packets=tuple(sorted(packets, key=lambda item: item.candidate_id.encode())),
    )
    candidates = tuple(
        item
        for item in staged_projected
        if item.candidate_id in {packet.candidate_id for packet in packets}
    )
    problem = _build_problem(candidates, ())
    return plan, pool, problem


def _qualification_for_pool(
    inputs: Any,
    repair_root: str,
    plan: VariablePoolAuthoringPlanV1,
    pool: ProductionAuthoringCandidatePoolV1,
    problem: Any,
    base: Record,
    production_root: Path,
) -> tuple[Record, tuple[Record, ...]]:
    root = _path(repair_root, f"qualification/{problem.problem_digest.removeprefix('sha256:')}")
    records: list[Record] = []
    for index, candidate in enumerate(problem.candidates):
        scenario = _problem_without_candidate(problem, candidate.candidate_id)
        input_body = {
            "original_pool_digest": inputs.pool.pool_digest,
            "repair_plan_digest": plan.plan_digest,
            "repair_pool_digest": pool.pool_digest,
            "repair_problem_digest": problem.problem_digest,
            "candidate_index": index,
            "candidate_identity_digest": canonical_hash(candidate.candidate_id),
            "candidate_payload_digest": candidate.payload_hash,
            "scenario_problem_digest": scenario.problem_digest,
            "solver_profile": res406._profile(),
        }
        relative = _path(
            root,
            f"removals/{index:04d}-{canonical_hash(candidate.candidate_id).removeprefix('sha256:')}.json",
        )
        prior = _read_record(relative, production_root)
        if prior is not None:
            record = prior[0]
            expected = {"schema_version": "RES407-REMOVAL-RECEIPT@1.0.0", "input": input_body}
            if any(record.get(key) != value for key, value in expected.items()):
                raise ValueError("RES-407 removal checkpoint is bound to a different scenario")
        else:
            result = solve_selection_feasibility(
                scenario,
                solver_config=PSE_V1_POOL_FEASIBILITY_SOLVER_PROFILE_V1,
            )
            record = _write_or_reuse(
                relative,
                {
                    "schema_version": "RES407-REMOVAL-RECEIPT@1.0.0",
                    "input": input_body,
                    "status": result.status.value,
                    "proof_method": "EXACT_FEASIBILITY_ORACLE",
                    "plan_digest": result.plan_digest,
                    "validation_digest": result.validation_digest,
                },
                production_root,
            )
        if record.get("proof_method") != "EXACT_FEASIBILITY_ORACLE":
            raise ValueError("RES-407 removal receipt has the wrong proof method")
        res406._feasibility_status(record)
        records.append(record)
        if record["status"] == FeasibilityStatus.UNKNOWN.value:
            break
    statuses = Counter(item["status"] for item in records)
    if len(records) != len(problem.candidates) and not statuses[FeasibilityStatus.UNKNOWN.value]:
        raise ValueError("RES-407 did not check every candidate removal")
    reserve: Record
    if statuses[FeasibilityStatus.UNKNOWN.value]:
        reserve = {
            "critical_obligation_count": None,
            "critical_obligations_with_structural_reserve": None,
            "critical_reserve_status": "UNKNOWN",
            "backfill_needs": [],
            "reserve_deficits": [],
            "outcome": "UNKNOWN",
        }
    else:
        reserve = res406._reserve_result(
            replace(inputs, plan=plan, pool=pool, problem=problem),
            base,
            tuple(records),
            {"status": "PASS"},
        )
    critical_status = reserve["critical_reserve_status"]
    backfill_needs = reserve["backfill_needs"]
    if not isinstance(critical_status, str) or not isinstance(backfill_needs, list | tuple):
        raise ValueError("RES-407 reserve result has invalid typed fields")
    qualification_status = _qualification_status(
        checked=len(records),
        candidate_count=len(problem.candidates),
        feasible=statuses[FeasibilityStatus.FEASIBLE.value],
        infeasible=statuses[FeasibilityStatus.INFEASIBLE.value],
        unknown=statuses[FeasibilityStatus.UNKNOWN.value],
        critical_status=critical_status,
        backfill_needs=backfill_needs,
    )
    body = {
        "schema_version": "RES407-POOL-QUALIFICATION@1.0.0",
        "repair_plan_digest": plan.plan_digest,
        "repair_pool_digest": pool.pool_digest,
        "problem_digest": problem.problem_digest,
        "base_receipt_digest": base["receipt_digest"],
        "checked_removals": len(records),
        "feasible_removals": statuses[FeasibilityStatus.FEASIBLE.value],
        "infeasible_removals": statuses[FeasibilityStatus.INFEASIBLE.value],
        "unknown_removals": statuses[FeasibilityStatus.UNKNOWN.value],
        "critical_obligation_count": reserve["critical_obligation_count"],
        "critical_with_structural_reserve": reserve["critical_obligations_with_structural_reserve"],
        "critical_reserve_status": reserve["critical_reserve_status"],
        "backfill_needs": reserve["backfill_needs"],
        "reserve_deficits": reserve["reserve_deficits"],
        "outcome": reserve["outcome"],
        "qualification_status": qualification_status,
        "removal_receipt_digests": tuple(item["receipt_digest"] for item in records),
    }
    qualification = _write_or_reuse(
        _path(root, "qualification-receipt.json"), body, production_root
    )
    return qualification, tuple(records)


def _repair_option_inventory(
    inputs: Any,
    demand: Record,
    lanes: tuple[ReserveCandidateLaneV1, ...],
    repair_root: str,
    production_root: Path,
) -> tuple[tuple[Record, ...], VariablePoolAuthoringPlanV1, ProductionAuthoringCandidatePoolV1]:
    recipes = _synthetic_option_recipes(demand, lanes, inputs.plan)
    if not recipes:
        empty = ProductionAuthoringCandidatePoolV1(
            authoring_plan_digest=inputs.plan.plan_digest,
            packets=inputs.pool.packets,
        )
        return (), inputs.plan, empty
    staged_plan = VariablePoolAuthoringPlanV1(
        supply_inventory_digest=inputs.inventory.inventory_digest,
        qualification_exclusion_digest=inputs.exclusion.commitment_digest,
        recipes=tuple(
            sorted((*inputs.plan.recipes, *recipes), key=lambda item: item.candidate_id.encode())
        ),
    )
    staged_pool = materialize_variable_pool(
        staged_plan,
        supply_inventory=inputs.inventory,
        exclusion=inputs.exclusion,
        source_resolver=inputs.source_resolver,
        historical_inputs=inputs.historical_inputs,
        external_root=production_root,
    )
    if staged_pool.candidate_count != inputs.pool.candidate_count + len(recipes):
        raise ValueError("candidate staging changed the exact governed option count")
    if staged_pool.pool_digest == inputs.pool.pool_digest:
        raise ValueError("candidate staging did not create a distinct derived pool digest")
    projected = project_variable_pool_selection_candidates(
        staged_pool,
        source_resolver=inputs.source_resolver,
    )
    projected_by_id = {item.candidate_id: item for item in projected}
    packet_by_id = {item.candidate_id: item for item in staged_pool.packets}
    lane_by_id = {item.lane_id: item for item in lanes}
    options: list[Record] = []
    for recipe in recipes:
        packet = packet_by_id[recipe.candidate_id]
        candidate = projected_by_id[recipe.candidate_id]
        lane = lane_by_id[recipe.lane_id or ""]
        binding = MaterializedBackfillCandidateV1(
            candidate=candidate,
            lane_id=recipe.lane_id or "",
            authority_ref=recipe.authority_ref,
            authority_digest=recipe.authority_digest,
        )
        validate_materialized_backfill_lane_binding(binding, lane)
        if packet.review_status.value != "PENDING_HUMAN_REVIEW":
            raise ValueError("RES-407 candidate option is not pending human review")
        candidate_digest = _option_digest(recipe, packet)
        body = {
            "schema_version": "RES407-CANDIDATE-OPTION@1.0.0",
            "candidate_id": recipe.candidate_id,
            "candidate_digest": candidate_digest,
            "candidate_payload_digest": packet.candidate_payload_hash,
            "origin_class": recipe.origin_class,
            "cell": (recipe.capability_id, recipe.benchmark_family),
            "lane_id": lane.lane_id,
            "lane_authority_ref": lane.authority_ref,
            "lane_authority_digest": lane.authority_digest,
            "isolation_identity_requirements": lane.isolation_identity_digests,
            "candidate_isolation_digest": canonical_hash(packet.isolation),
            "contamination_commitment_digest": canonical_hash(packet.contamination),
            "provenance_digest": canonical_hash(packet.proposed_provenance),
            "review_status": packet.review_status,
            "recipe_digest": recipe.recipe_digest,
        }
        relative = _path(
            repair_root,
            f"candidate-options/{candidate_digest.removeprefix('sha256:')}.json",
        )
        option_record = _write_or_reuse(relative, body, production_root)
        _write_typed_or_reuse(
            _path(
                repair_root,
                f"candidate-options/{candidate_digest.removeprefix('sha256:')}/recipe.json",
            ),
            recipe,
            ProductionCandidateRecipeV1,
            production_root,
        )
        _write_typed_or_reuse(
            _path(
                repair_root,
                f"candidate-options/{candidate_digest.removeprefix('sha256:')}/packet.json",
            ),
            packet,
            type(packet),
            production_root,
        )
        options.append(
            {
                **option_record,
                "origin_class": recipe.origin_class,
                "cell": (recipe.capability_id, recipe.benchmark_family),
                "lane_id": lane.lane_id,
                "lane_authority_ref": lane.authority_ref,
                "lane_authority_digest": lane.authority_digest,
                "recipe_digest": recipe.recipe_digest,
                "recipe": recipe,
                "packet": packet,
                "selection_candidate": candidate,
            }
        )
    ordered = _option_order(tuple(options))
    if len({item["candidate_digest"] for item in ordered}) != len(ordered):
        raise ValueError("candidate option inventory repeats a payload identity")
    if len({item["candidate_payload_digest"] for item in ordered}) != len(ordered):
        raise ValueError("candidate option inventory repeats a candidate payload")
    return ordered, staged_plan, staged_pool


def _artifact_inventory(
    root: str, production_root: Path, extra_store: str | None
) -> tuple[tuple[str, str, int], ...]:
    from dynamislm.benchmark.qualification_store import _external_input_path, _safe_external_root

    external_root, _ = _safe_external_root(production_root, _REPOSITORY)
    result: list[tuple[str, str, int]] = []
    relative_roots = [PurePosixPath(root)]
    if extra_store is not None:
        relative_roots.append(PurePosixPath(extra_store))
    for relative_root in relative_roots:
        directory = _external_input_path(external_root, relative_root)
        if not directory.exists():
            continue
        for parent, directories, filenames in os.walk(directory, followlinks=False):
            for name in directories:
                path = Path(parent) / name
                if path.is_symlink() or not path.is_dir():
                    raise ValueError("RES-407 external checkpoint contains an unsafe directory")
            for name in filenames:
                path = Path(parent) / name
                if path.is_symlink() or not path.is_file():
                    raise ValueError("RES-407 external checkpoint contains an unsafe artifact")
                relative = path.relative_to(external_root).as_posix()
                if relative.endswith("final-private-res407-receipt.json"):
                    continue
                if relative == f"{root}/final-private-res407-receipt.json":
                    continue
                payload = path.read_bytes()
                result.append(
                    (relative, "sha256:" + hashlib.sha256(payload).hexdigest(), len(payload))
                )
    return tuple(sorted(set(result), key=lambda item: item[0].encode()))


def _public_payload(receipt: Record) -> Record:
    return {
        "mission": "RES-407",
        "entry_head": ENTRY_HEAD,
        "dynamislm_execution_baseline": DYNAMISLM_EXECUTION_BASELINE,
        "res405_receipt_digest": RES405_RECEIPT_DIGEST,
        "original_plan_digest": ORIGINAL_PLAN_DIGEST,
        "original_pool_digest": ORIGINAL_POOL_DIGEST,
        "original_pool_count": ORIGINAL_POOL_COUNT,
        "live_supply_inventory_digest": LIVE_SUPPLY_INVENTORY_DIGEST,
        "repair_demand_digest": receipt["repair_demand_digest"],
        "authorable_lane_count": receipt["authorable_lane_count"],
        "materializable_lane_count": receipt["materializable_lane_count"],
        "candidate_option_count": receipt["candidate_option_count"],
        "candidate_option_origin_counts": receipt["candidate_option_origin_counts"],
        "candidate_option_cell_counts": receipt["candidate_option_cell_counts"],
        "original_origin_counts": receipt["original_origin_counts"],
        "original_cell_counts": receipt["original_cell_counts"],
        "repaired_origin_counts": receipt["repaired_origin_counts"],
        "repaired_cell_counts": receipt["repaired_cell_counts"],
        "repair_trial_count": receipt["repair_trial_count"],
        "repair_set_digest": receipt["repair_set_digest"],
        "repair_set_size": receipt["retained_addition_count"],
        "repair_minimality_status": receipt["repair_minimality_status"],
        "repaired_plan_digest": receipt["repaired_plan_digest"],
        "repaired_pool_digest": receipt["repaired_pool_digest"],
        "repaired_pool_count": receipt["repaired_pool_count"],
        "addition_count": receipt["retained_addition_count"],
        "repaired_base_problem_digest": receipt["repaired_base_problem_digest"],
        "repaired_base_status": receipt["repaired_base_status"],
        "checked_removals": receipt["checked_removals"],
        "feasible_removals": receipt["feasible_removals"],
        "infeasible_removals": receipt["infeasible_removals"],
        "unknown_removals": receipt["unknown_removals"],
        "critical_obligation_count": receipt["critical_obligation_count"],
        "critical_with_structural_reserve": receipt["critical_with_structural_reserve"],
        "critical_reserve_status": receipt["critical_reserve_status"],
        "authority_exhaustion_category": receipt["authority_exhaustion_category"],
        "authority_exhaustion_proven": receipt["authority_exhaustion_proven"],
        "outcome": receipt["outcome"],
        "next": receipt["next"],
        "artifact_inventory_digest": receipt["artifact_inventory_digest"],
        "private_receipt_digest": receipt["receipt_digest"],
        "fresh_process_confirmation": receipt["fresh_process_confirmation"],
        "public_leak_guard": receipt["public_leak_guard"],
        "post_write_public_leak_guard": receipt["post_write_public_leak_guard"],
        "pool_original_mutated": False,
        "authority_changed": False,
        "human_review_performed": False,
        "final_splits_allocated": False,
    }


def _acceptance_text(payload: Record) -> str:
    lines = ["# RES-407 Governed Backfill Acceptance Receipt", "", "```text"]
    for key in sorted(payload, key=str.encode):
        value = payload[key]
        encoded = json.dumps(value, sort_keys=True) if isinstance(value, dict | list) else value
        lines.append(f"{key.upper()}={encoded}")
    lines.extend(("```", ""))
    return "\n".join(lines)


def _write_public(repository_root: Path, payload: Record) -> None:
    for relative, content in (
        (_SUMMARY_PATH, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"),
        (_PUBLIC_RECEIPT_PATH, _acceptance_text(payload)),
    ):
        path = repository_root / relative
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise ValueError(f"RES-407 public output path is unsafe: {relative}")
        path.parent.mkdir(parents=True, exist_ok=True)
        encoded = content.encode("utf-8")
        if path.is_file() and path.read_bytes() == encoded:
            continue
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
            ) as handle:
                temporary = Path(handle.name)
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()


def _run_qualification(repository_root: Path, production_root: Path) -> Record:
    runner_head = _require_execution_tree(clean=True)
    inputs = res451._load_inputs(repository_root, production_root)
    if (
        inputs.store_receipt.receipt_digest != RES405_RECEIPT_DIGEST
        or inputs.plan.plan_digest != ORIGINAL_PLAN_DIGEST
        or inputs.pool.pool_digest != ORIGINAL_POOL_DIGEST
        or inputs.pool.candidate_count != ORIGINAL_POOL_COUNT
        or inputs.problem.problem_digest != ORIGINAL_PROBLEM_DIGEST
        or inputs.inventory.inventory_digest != LIVE_SUPPLY_INVENTORY_DIGEST
    ):
        raise ValueError("RES-407 upstream authority reconstruction drift")
    diagnosis = _diagnosis_record(inputs, production_root)
    base_result = solve_selection_feasibility(
        inputs.problem,
        solver_config=PSE_V1_POOL_FEASIBILITY_SOLVER_PROFILE_V1,
    )
    if base_result.status is not FeasibilityStatus.INFEASIBLE:
        raise ValueError("RES-407 exact original base confirmation drifted from INFEASIBLE")
    demand = _repair_demand(diagnosis)
    demand_digest = canonical_hash(demand)
    repair_root = _checkpoint_root()
    demand_record = _write_or_reuse(
        _path(repair_root, "repair-demand.json"), demand, production_root
    )
    original_store_digest = _original_store_digest(inputs, production_root)
    supply_body, lanes = _supply_enumeration(inputs)
    supply_record = _write_or_reuse(
        _path(repair_root, "supply-enumeration.json"), supply_body, production_root
    )
    lane_rows = supply_body["lanes"]
    lane_row_by_id = {row["lane_id"]: row for row in lane_rows}
    authorable_lane_count = sum(
        lane.capacity_status is LaneCapacityStatus.RULE_GOVERNED
        or (
            lane.capacity_status is LaneCapacityStatus.AVAILABLE
            and (lane_row_by_id[lane.lane_id]["remaining_additional_authorable_capacity"] or 0) > 0
        )
        for lane in lanes
    )
    remaining_finite_capacity = sum(
        row["remaining_additional_authorable_capacity"] or 0
        for row in lane_rows
        if row["capacity_status"] is LaneCapacityStatus.AVAILABLE
    )

    base_trial_body = {
        "schema_version": "RES407-REPAIR-SET-TRIAL@1.0.0",
        "original_pool_digest": inputs.pool.pool_digest,
        "diagnosis_receipt_digest": RES451_RECEIPT_DIGEST,
        "conflict_set_digest": RES451_CONFLICT_SET_DIGEST,
        "supply_inventory_digest": inputs.inventory.inventory_digest,
        "repair_demand_digest": demand_digest,
        "addition_candidate_digests": (),
        "lane_authority_bindings": (),
        "addition_set_digest": canonical_hash(()),
        "resulting_plan_digest": inputs.plan.plan_digest,
        "resulting_pool_digest": inputs.pool.pool_digest,
        "resulting_problem_digest": inputs.problem.problem_digest,
        "solver_profile": res406._profile(),
        "status": base_result.status.value,
        "solver_version": base_result.solver_version,
        "plan_digest": base_result.plan_digest,
        "validation_digest": base_result.validation_digest,
        "validation_status": None,
    }
    base_trial = _write_or_reuse(
        _path(repair_root, f"trials/0000-{canonical_hash(()).removeprefix('sha256:')}.json"),
        base_trial_body,
        production_root,
    )

    print("RES407_REBUILD_STAGED_OPTIONS", flush=True)
    options, staged_plan, staged_pool = _repair_option_inventory(
        inputs, demand, lanes, repair_root, production_root
    )
    option_inventory_body = _option_inventory_body(options, demand_digest)
    option_inventory_record = _write_or_reuse(
        _path(repair_root, "candidate-option-inventory.json"),
        option_inventory_body,
        production_root,
    )
    staged_projected = project_variable_pool_selection_candidates(
        staged_pool,
        source_resolver=inputs.source_resolver,
    )
    original_ids = {item.candidate_id for item in inputs.problem.candidates}
    staged_original_problem = _build_problem(
        tuple(item for item in staged_projected if item.candidate_id in original_ids),
        (),
    )
    if staged_original_problem.problem_digest != inputs.problem.problem_digest:
        raise ValueError("candidate staging changed the immutable original selection problem")
    trial_results: dict[tuple[str, ...], Record] = {(): base_trial}
    qualification_results: dict[tuple[str, ...], Record] = {}
    minimization_records: list[Record] = []

    def evaluate(selected: tuple[Record, ...], *, base_only: bool = False) -> Record:
        candidate_digests = tuple(item["candidate_digest"] for item in selected)
        selected_key = tuple(candidate_digests)
        plan, pool, problem = _problem_for_options(inputs, selected, staged_projected)
        relative = _path(
            repair_root,
            f"trials/{len(selected):04d}-{canonical_hash(selected_key).removeprefix('sha256:')}.json",
        )
        prior = _read_record(relative, production_root)
        if prior is not None:
            record = prior[0]
            expected = _trial_body(
                inputs=inputs,
                demand=demand,
                options=selected,
                pool=pool,
                problem=problem,
                result=type(
                    "SavedResult",
                    (),
                    {
                        "status": FeasibilityStatus(record["status"]),
                        "solver_version": record["solver_version"],
                        "plan_digest": record["plan_digest"],
                        "validation_digest": record["validation_digest"],
                        "validation_status": (
                            None
                            if record.get("validation_status") is None
                            else ValidationStatus(record["validation_status"])
                        ),
                    },
                )(),
            )
            if any(record.get(key) != value for key, value in expected.items()):
                raise ValueError("RES-407 repair trial is stale or bound to different options")
            trial = record
        else:
            result = solve_selection_feasibility(
                problem,
                solver_config=PSE_V1_POOL_FEASIBILITY_SOLVER_PROFILE_V1,
            )
            trial = _write_or_reuse(
                relative,
                _trial_body(
                    inputs=inputs,
                    demand=demand,
                    options=selected,
                    pool=pool,
                    problem=problem,
                    result=result,
                ),
                production_root,
            )
        trial_results[selected_key] = trial
        print(
            f"RES407_TRIAL additions={len(selected)} status={trial['status']} "
            f"problem={problem.problem_digest}",
            flush=True,
        )
        if trial["status"] == FeasibilityStatus.UNKNOWN.value:
            return {"qualification_status": "UNKNOWN", "trial": trial}
        if trial["status"] == FeasibilityStatus.INFEASIBLE.value:
            return {"qualification_status": "INFEASIBLE", "trial": trial}
        if base_only:
            return {"qualification_status": "BASE_FEASIBLE", "trial": trial}
        base = {
            "receipt_digest": trial["receipt_digest"],
            "status": trial["status"],
            "proof_method": "EXACT_FEASIBILITY_ORACLE",
            "plan_digest": trial["plan_digest"],
            "validation_digest": trial["validation_digest"],
        }
        qualification, _removals = _qualification_for_pool(
            inputs, repair_root, plan, pool, problem, base, production_root
        )
        qualification_results[selected_key] = qualification

        def reduced_status(reduced_options: tuple[Record, ...]) -> str:
            reduced_key = tuple(item["candidate_digest"] for item in reduced_options)
            reduced = trial_results.get(reduced_key)
            if reduced is None:
                raise ValueError("RES-407 minimization lacks the exact reduced-set trial")
            return cast(str, reduced["status"])

        minimized, minimization_status = _minimize_repair_set(selected, reduced_status)
        if minimization_status == "UNKNOWN":
            return {"qualification_status": "UNKNOWN", "trial": trial}
        necessary = tuple(item["candidate_digest"] for item in minimized) == selected_key
        if necessary:
            for item in selected:
                reduced_key = tuple(
                    value for value in selected_key if value != item["candidate_digest"]
                )
                reduced = trial_results[reduced_key]
                if reduced["status"] != FeasibilityStatus.INFEASIBLE.value:
                    raise ValueError(
                        "RES-407 retained addition lacks an infeasible necessity trial"
                    )
                check = _write_or_reuse(
                    _path(
                        repair_root,
                        f"minimization/{canonical_hash(selected_key).removeprefix('sha256:')}/"
                        f"{item['candidate_digest'].removeprefix('sha256:')}.json",
                    ),
                    {
                        "schema_version": "RES407-NECESSITY-CHECK@1.0.0",
                        "repair_set_digest": canonical_hash(selected_key),
                        "removed_candidate_digest": item["candidate_digest"],
                        "reduced_addition_candidate_digests": reduced_key,
                        "reduced_trial_receipt_digest": reduced["receipt_digest"],
                        "reduced_status": reduced["status"],
                        "proof_method": "EXACT_FEASIBILITY_ORACLE",
                    },
                    production_root,
                )
                minimization_records.append(check)
        qualification_status = qualification["qualification_status"]
        if qualification_status == "QUALIFIED" and not necessary:
            qualification_status = "NOT_QUALIFIED"
        return {
            "qualification_status": qualification_status,
            "trial": trial,
            "qualification": qualification,
            "minimization_status": minimization_status,
        }

    selected, search_status, outcomes = _search_repair_sets(
        options,
        evaluate,
        superset_screen=lambda values: evaluate(values, base_only=True),
    )
    if selected is None and not options:
        authority_expansion = _authority_exhaustion_proven(
            inputs.inventory,
            bool(demand),
            0,
            remaining_finite_capacity,
        )
        outcome = "AUTHORITY_EXPANSION_REQUIRED" if authority_expansion else "NO_GOVERNED_REPAIR"
    elif search_status == "UNKNOWN":
        authority_expansion = False
        outcome = "UNKNOWN"
    elif selected is not None:
        authority_expansion = False
        outcome = "QUALIFIED"
    else:
        authority_expansion = False
        outcome = "UNKNOWN"

    retained_options = selected or ()
    retained_digests = tuple(item["candidate_digest"] for item in retained_options)
    repair_set_digest = canonical_hash(
        tuple(
            (item["candidate_digest"], item["lane_id"], item["lane_authority_digest"])
            for item in retained_options
        )
    )
    search_inventory_body = {
        "schema_version": "RES407-REPAIR-SEARCH-INVENTORY@1.0.0",
        "original_pool_digest": ORIGINAL_POOL_DIGEST,
        "diagnosis_receipt_digest": RES451_RECEIPT_DIGEST,
        "repair_demand_digest": demand_digest,
        "candidate_option_inventory_digest": option_inventory_record["receipt_digest"],
        "solver_profile": res406._profile(),
        "order": "maximum-option feasibility screen, then addition_count_then_candidate_digest",
        "subset_pruning_basis": (
            "infeasible full option set excludes every subset because omitted candidates "
            "can be assigned OUT"
            if search_status == "NO_FEASIBLE_SET_IN_BOUNDED_OPTIONS"
            else None
        ),
        "trial_receipt_digests": tuple(
            record["receipt_digest"] for _key, record in sorted(trial_results.items())
        ),
        "trial_records": tuple(
            (
                _trial_relative(repair_root, key),
                record["receipt_digest"],
                record["status"],
            )
            for key, record in sorted(trial_results.items())
        ),
        "qualification_receipt_digests": tuple(
            record["receipt_digest"] for _key, record in sorted(qualification_results.items())
        ),
        "qualification_records": tuple(
            (
                _path(
                    repair_root,
                    f"qualification/{record['problem_digest'].removeprefix('sha256:')}/qualification-receipt.json",
                ),
                record["receipt_digest"],
                record["qualification_status"],
            )
            for _key, record in sorted(qualification_results.items())
        ),
        "necessity_receipt_digests": tuple(
            record["receipt_digest"] for record in minimization_records
        ),
        "evaluated_set_count": len(trial_results) - 1,
    }
    search_inventory_record = _write_or_reuse(
        _path(repair_root, "repair-search-inventory.json"),
        search_inventory_body,
        production_root,
    )
    repair_set_body = {
        "schema_version": "RES407-REPAIR-SET-RECEIPT@1.0.0",
        "original_pool_digest": ORIGINAL_POOL_DIGEST,
        "diagnosis_receipt_digest": RES451_RECEIPT_DIGEST,
        "repair_demand_digest": demand_digest,
        "supply_inventory_digest": LIVE_SUPPLY_INVENTORY_DIGEST,
        "candidate_option_inventory_digest": option_inventory_record["receipt_digest"],
        "repair_search_inventory_digest": search_inventory_record["receipt_digest"],
        "addition_count": len(retained_options),
        "addition_candidate_digests": retained_digests,
        "lane_bindings": tuple(
            (item["candidate_digest"], item["lane_id"], item["lane_authority_digest"])
            for item in retained_options
        ),
        "repair_set_digest": repair_set_digest,
        "search_status": search_status,
        "search_trial_count": len(trial_results) - 1,
        "review_cost": None,
        "review_cost_authority": None,
        "minimality_status": (
            "INCLUSION_MINIMAL_PROVEN"
            if selected is not None
            and search_status == "QUALIFIED"
            and all(
                trial_results[tuple(value for value in retained_digests if value != item)]["status"]
                == FeasibilityStatus.INFEASIBLE.value
                for item in retained_digests
            )
            else "NOT_PROVEN"
        ),
        "necessity_receipt_digests": tuple(
            record["receipt_digest"] for record in minimization_records
        ),
    }
    repair_set_record = _write_or_reuse(
        _path(repair_root, "repair-set-receipt.json"), repair_set_body, production_root
    )

    repaired_plan = None
    repaired_pool = None
    repaired_problem = None
    repaired_base = None
    qualification = None
    store_receipt = None
    lineage_receipt = None
    final_qualification = {
        "checked_removals": 0,
        "feasible_removals": 0,
        "infeasible_removals": 0,
        "unknown_removals": 0,
        "critical_obligation_count": None,
        "critical_with_structural_reserve": None,
        "critical_reserve_status": "NOT_EVALUATED",
    }
    if selected is not None:
        selected_key = tuple(retained_digests)
        repaired_plan, repaired_pool, repaired_problem = _problem_for_options(
            inputs, selected, staged_projected
        )
        repaired_base = trial_results[selected_key]
        qualification = qualification_results[selected_key]
        final_qualification = {
            key: qualification[key]
            for key in (
                "checked_removals",
                "feasible_removals",
                "infeasible_removals",
                "unknown_removals",
                "critical_obligation_count",
                "critical_with_structural_reserve",
                "critical_reserve_status",
            )
        }
        if outcome == "QUALIFIED":
            validate_variable_pre_review_pool(
                repaired_pool,
                exclusion=inputs.exclusion,
                source_resolver=inputs.source_resolver,
            )
            store_receipt = write_variable_pool_store(
                repaired_plan,
                repaired_pool,
                supply_inventory=inputs.inventory,
                exclusion=inputs.exclusion,
                historical_input_digest=inputs.historical_inputs.input_digest,
                materialization_repository_head=runner_head,
                repository_root=repository_root,
                production_root=production_root,
                source_resolver=inputs.source_resolver,
            )
            if (
                store_receipt.store_relative_path
                != _pool_store_relative_path(repaired_plan.plan_digest)
                or store_receipt.store_relative_path == inputs.store_receipt.store_relative_path
            ):
                raise ValueError(
                    "RES-407 derived pool store did not get a new content-addressed path"
                )
            lineage_body = {
                "schema_version": _LINEAGE_SCHEMA,
                "res405_receipt_digest": RES405_RECEIPT_DIGEST,
                "original_plan_digest": ORIGINAL_PLAN_DIGEST,
                "original_pool_digest": ORIGINAL_POOL_DIGEST,
                "res451_private_diagnosis_receipt_digest": RES451_RECEIPT_DIGEST,
                "res451_conflict_set_digest": RES451_CONFLICT_SET_DIGEST,
                "repair_set_receipt_digest": repair_set_record["receipt_digest"],
                "repair_set_digest": repair_set_digest,
                "repaired_plan_digest": repaired_plan.plan_digest,
                "repaired_pool_digest": repaired_pool.pool_digest,
                "repaired_pool_count": repaired_pool.candidate_count,
                "addition_count": len(retained_options),
                "variable_pool_store_receipt_digest": store_receipt.receipt_digest,
            }
            lineage_receipt = _write_or_reuse(
                _path(repair_root, "repaired-pool-lineage-receipt.json"),
                lineage_body,
                production_root,
            )

    _assert_original_store_unchanged(
        original_store_digest,
        _original_store_digest(inputs, production_root),
    )
    if (
        build_live_authority_supply_inventory(
            repository_root=repository_root,
            production_root=production_root,
        )
        != inputs.inventory
    ):
        raise ValueError("live authority inventory changed during RES-407")

    authority_category = (
        "CAPACITY_SCOPE_INCOMPLETE"
        if not inputs.inventory.capacity_scope_complete
        else "NO_EXACT_GOVERNED_OPTIONS"
        if not options
        else "NOT_EXHAUSTED"
    )
    option_origin_counts = dict(Counter(item["origin_class"].value for item in options))
    option_cell_counts = dict(Counter(f"{item['cell'][0]}:{item['cell'][1]}" for item in options))
    original_origin_counts = {origin.value: count for origin, count in inputs.plan.origin_counts}
    original_cell_counts = dict(
        Counter(
            f"{packet.capability_id}:{packet.benchmark_family}" for packet in inputs.pool.packets
        )
    )
    repaired_origin_counts = (
        None
        if repaired_plan is None
        else {origin.value: count for origin, count in repaired_plan.origin_counts}
    )
    repaired_cell_counts = (
        None
        if repaired_pool is None
        else dict(
            Counter(
                f"{packet.capability_id}:{packet.benchmark_family}"
                for packet in repaired_pool.packets
            )
        )
    )
    retained_lane_bindings = tuple(
        (item["candidate_digest"], item["lane_id"], item["lane_authority_digest"])
        for item in retained_options
    )
    if selected is not None:
        assert repaired_plan is not None
        assert repaired_pool is not None
        assert repaired_problem is not None
        assert qualification is not None
        qual_root = _path(
            repair_root,
            f"qualification/{repaired_problem.problem_digest.removeprefix('sha256:')}",
        )
        # The receipt list is already exact and is read back in canonical candidate order.
        output: list[Record] = []
        for index, candidate in enumerate(repaired_problem.candidates):
            relative = _path(
                qual_root,
                f"removals/{index:04d}-{canonical_hash(candidate.candidate_id).removeprefix('sha256:')}.json",
            )
            item = _read_record(relative, production_root)
            if item is None:
                raise ValueError("RES-407 final qualification is missing a removal receipt")
            output.append(item[0])

    critical_receipt = None
    if selected is not None:
        assert repaired_pool is not None
        assert repaired_problem is not None
        assert qualification is not None
        critical_body = {
            "schema_version": "RES407-CRITICAL-RESERVE-RECEIPT@1.0.0",
            "repair_pool_digest": repaired_pool.pool_digest,
            "problem_digest": repaired_problem.problem_digest,
            "qualification_receipt_digest": qualification["receipt_digest"],
            "obligation_count": final_qualification["critical_obligation_count"],
            "obligations_with_structural_reserve": final_qualification[
                "critical_with_structural_reserve"
            ],
            "status": final_qualification["critical_reserve_status"],
        }
        critical_receipt = _write_or_reuse(
            _path(repair_root, "critical-reserve-receipt.json"),
            critical_body,
            production_root,
        )

    extra_store_path = store_receipt.store_relative_path if store_receipt is not None else None
    artifacts = _artifact_inventory(repair_root, production_root, extra_store_path)
    artifact_inventory_digest = canonical_hash(artifacts)
    repaired_plan_digest = None if repaired_plan is None else repaired_plan.plan_digest
    repaired_pool_digest = None if repaired_pool is None else repaired_pool.pool_digest
    repaired_problem_digest = None if repaired_problem is None else repaired_problem.problem_digest
    repaired_pool_count = None if repaired_pool is None else repaired_pool.candidate_count
    base_status = None if repaired_base is None else repaired_base["status"]
    final_body: Record = {
        "schema_version": _FINAL_SCHEMA,
        "mission": "RES-407",
        "entry_head": ENTRY_HEAD,
        "runner_head": runner_head,
        "execution_baseline": DYNAMISLM_EXECUTION_BASELINE,
        "res405_receipt_digest": RES405_RECEIPT_DIGEST,
        "original_plan_digest": ORIGINAL_PLAN_DIGEST,
        "original_pool_digest": ORIGINAL_POOL_DIGEST,
        "original_pool_count": ORIGINAL_POOL_COUNT,
        "original_problem_digest": ORIGINAL_PROBLEM_DIGEST,
        "original_base_status": base_result.status.value,
        "res406_private_receipt_digest": RES406_RECEIPT_DIGEST,
        "res451_private_diagnosis_receipt_digest": RES451_RECEIPT_DIGEST,
        "res451_conflict_set_digest": RES451_CONFLICT_SET_DIGEST,
        "live_supply_inventory_digest": LIVE_SUPPLY_INVENTORY_DIGEST,
        "authority_inventory_complete": inputs.inventory.authority_inventory_complete,
        "capacity_scope_complete": inputs.inventory.capacity_scope_complete,
        "repair_demand_digest": demand_digest,
        "repair_demand_checkpoint_digest": demand_record["receipt_digest"],
        "supply_enumeration_digest": supply_record["receipt_digest"],
        "authorable_lane_count": authorable_lane_count,
        "materializable_lane_count": len({item["lane_id"] for item in options}),
        "candidate_option_inventory_digest": option_inventory_record["receipt_digest"],
        "candidate_option_count": len(options),
        "candidate_option_origin_counts": option_origin_counts,
        "candidate_option_cell_counts": option_cell_counts,
        "original_origin_counts": original_origin_counts,
        "original_cell_counts": original_cell_counts,
        "repaired_origin_counts": repaired_origin_counts,
        "repaired_cell_counts": repaired_cell_counts,
        "repair_search_inventory_digest": search_inventory_record["receipt_digest"],
        "repair_trial_count": len(trial_results) - 1,
        "repair_set_receipt_digest": repair_set_record["receipt_digest"],
        "repair_set_digest": repair_set_digest,
        "retained_addition_count": len(retained_options),
        "retained_addition_digests": retained_digests,
        "retained_lane_bindings": retained_lane_bindings,
        "repair_minimality_status": repair_set_body["minimality_status"],
        "repaired_plan_digest": repaired_plan_digest,
        "repaired_pool_digest": repaired_pool_digest,
        "repaired_pool_count": repaired_pool_count,
        "repaired_pool_store_receipt_digest": (
            None if store_receipt is None else store_receipt.receipt_digest
        ),
        "repaired_pool_lineage_receipt_digest": (
            None if lineage_receipt is None else lineage_receipt["receipt_digest"]
        ),
        "repaired_pool_store_relative_path": (
            None if store_receipt is None else store_receipt.store_relative_path
        ),
        "repaired_base_problem_digest": repaired_problem_digest,
        "repaired_base_status": base_status,
        "checked_removals": final_qualification["checked_removals"],
        "feasible_removals": final_qualification["feasible_removals"],
        "infeasible_removals": final_qualification["infeasible_removals"],
        "unknown_removals": final_qualification["unknown_removals"],
        "critical_obligation_count": final_qualification["critical_obligation_count"],
        "critical_with_structural_reserve": final_qualification["critical_with_structural_reserve"],
        "critical_reserve_status": final_qualification["critical_reserve_status"],
        "critical_reserve_receipt_digest": (
            None if critical_receipt is None else critical_receipt["receipt_digest"]
        ),
        "authority_exhaustion_proven": authority_expansion,
        "authority_exhaustion_category": authority_category,
        "original_store_artifact_digest": original_store_digest,
        "original_pool_mutated": False,
        "authority_changed": False,
        "human_review_performed": False,
        "final_splits_allocated": False,
        "outcome": outcome,
        "next": "RES-408"
        if outcome == "QUALIFIED"
        else "STOP_FOR_GOVERNANCE"
        if outcome == "AUTHORITY_EXPANSION_REQUIRED"
        else "STOP",
        "fresh_process_confirmation": "PENDING",
        "public_leak_guard": "PASS",
        "post_write_public_leak_guard": "PENDING",
        "artifact_inventory": artifacts,
        "artifact_inventory_digest": artifact_inventory_digest,
        "checkpoint_path": repair_root,
    }
    private_material = res406._private_material(
        staged_plan,
        staged_pool,
        inputs.historical_inputs,
        inputs.exclusion,
    )
    leak_guard = validate_production_private_material_absent(
        private_material,
        repository_root=repository_root,
        candidate_count=staged_pool.candidate_count,
    )
    if leak_guard.status != "PASS":
        raise ValueError("RES-407 production private-material leak guard failed")
    final_body["public_leak_guard"] = leak_guard.status
    receipt_relative = _path(repair_root, "final-private-res407-receipt.json")
    final_record = _write_or_reuse(receipt_relative, final_body, production_root)
    if _artifact_inventory(repair_root, production_root, extra_store_path) != artifacts:
        raise ValueError("RES-407 artifact inventory changed while writing final receipt")

    # Publish the bound post-write guard result, then let a fresh process reconstruct the receipt.
    public_payload = _public_payload(final_record)
    _write_public(repository_root, public_payload)
    post_guard = validate_production_private_material_absent(
        private_material,
        repository_root=repository_root,
        candidate_count=staged_pool.candidate_count,
    )
    if post_guard.status != "PASS":
        raise ValueError("RES-407 post-write public leak scan failed")
    updated = {key: value for key, value in final_record.items() if key != "receipt_digest"}
    updated["post_write_public_leak_guard"] = post_guard.status
    final_record = _replace_record(receipt_relative, updated, production_root)
    _write_public(repository_root, _public_payload(final_record))

    confirmation_run = subprocess.run(
        (
            sys.executable,
            str(repository_root / "scripts/res407_governed_backfill.py"),
            "confirm",
            "--production-root",
            str(production_root),
            "--expected-receipt-digest",
            final_record["receipt_digest"],
        ),
        check=True,
        cwd=repository_root,
        capture_output=True,
        text=True,
    )
    confirmation = json.loads(confirmation_run.stdout)
    expected_final_digest = confirmation.get("anticipated_private_receipt_digest")
    confirmed_body = {key: value for key, value in final_record.items() if key != "receipt_digest"}
    confirmed_body["fresh_process_confirmation"] = "PASS"
    final_record = _replace_record(receipt_relative, confirmed_body, production_root)
    if final_record["receipt_digest"] != expected_final_digest:
        raise ValueError("fresh process predicted a different final RES-407 receipt digest")
    _write_public(repository_root, _public_payload(final_record))
    final_guard = validate_production_private_material_absent(
        private_material,
        repository_root=repository_root,
        candidate_count=staged_pool.candidate_count,
    )
    if final_guard.status != "PASS":
        raise ValueError("RES-407 final public output leak scan failed")
    _assert_original_store_unchanged(
        original_store_digest,
        _original_store_digest(inputs, production_root),
    )
    public_payload = _public_payload(final_record)
    print(json.dumps(public_payload, sort_keys=True, indent=2))
    return final_record


def _confirm(repository_root: Path, production_root: Path, expected_digest: str) -> Record:
    runner_head = _require_execution_tree(clean=False)
    inputs = res451._load_inputs(repository_root, production_root)
    diagnosis = _diagnosis_record(inputs, production_root)
    demand = _repair_demand(diagnosis)
    repair_root = _checkpoint_root()
    final = _read_record(_path(repair_root, "final-private-res407-receipt.json"), production_root)
    if final is None or final[0]["receipt_digest"] != expected_digest:
        raise ValueError("RES-407 private final receipt is missing or has a different digest")
    receipt = final[0]
    if (
        receipt["repair_demand_digest"] != canonical_hash(demand)
        or receipt["original_pool_digest"] != inputs.pool.pool_digest
        or receipt["live_supply_inventory_digest"] != inputs.inventory.inventory_digest
    ):
        raise ValueError("RES-407 fresh process reconstructed different authority inputs")
    supply_body, lanes = _supply_enumeration(inputs)
    supply_saved = _read_record(_path(repair_root, "supply-enumeration.json"), production_root)
    if (
        supply_saved is None
        or supply_saved[0]["receipt_digest"] != receipt["supply_enumeration_digest"]
    ):
        raise ValueError("RES-407 fresh process cannot reload the exact supply enumeration")
    if (
        res406._bound(_wire_record(supply_body))["receipt_digest"]
        != supply_saved[0]["receipt_digest"]
    ):
        raise ValueError("RES-407 fresh supply enumeration differs from its checkpoint")
    options, staged_plan, staged_pool = _repair_option_inventory(
        inputs,
        demand,
        lanes,
        repair_root,
        production_root,
    )
    option_inventory = _read_record(
        _path(repair_root, "candidate-option-inventory.json"), production_root
    )
    expected_option_inventory = _write_or_reuse(
        _path(repair_root, "candidate-option-inventory.json"),
        _option_inventory_body(options, canonical_hash(demand)),
        production_root,
    )
    if (
        option_inventory is None
        or option_inventory[0] != expected_option_inventory
        or option_inventory[0]["receipt_digest"] != receipt["candidate_option_inventory_digest"]
        or len(options) != receipt["candidate_option_count"]
    ):
        raise ValueError("RES-407 fresh process reconstructed a different candidate option set")
    staged_projected = project_variable_pool_selection_candidates(
        staged_pool,
        source_resolver=inputs.source_resolver,
    )
    original_ids = {item.candidate_id for item in inputs.problem.candidates}
    if (
        _build_problem(
            tuple(item for item in staged_projected if item.candidate_id in original_ids),
            (),
        ).problem_digest
        != inputs.problem.problem_digest
    ):
        raise ValueError("RES-407 fresh candidate staging changed the original selection problem")
    search_inventory = _read_record(
        _path(repair_root, "repair-search-inventory.json"), production_root
    )
    repair_set = _read_record(_path(repair_root, "repair-set-receipt.json"), production_root)
    if (
        search_inventory is None
        or repair_set is None
        or search_inventory[0]["receipt_digest"] != receipt["repair_search_inventory_digest"]
        or repair_set[0]["receipt_digest"] != receipt["repair_set_receipt_digest"]
        or repair_set[0]["repair_set_digest"] != receipt["repair_set_digest"]
    ):
        raise ValueError("RES-407 fresh process cannot reconstruct search or retained-set receipts")
    for relative, digest, status in search_inventory[0]["trial_records"]:
        saved_trial = _read_record(relative, production_root)
        if (
            saved_trial is None
            or saved_trial[0]["receipt_digest"] != digest
            or saved_trial[0]["status"] != status
        ):
            raise ValueError("RES-407 fresh process found a changed exact repair trial")
    for relative, digest, status in search_inventory[0]["qualification_records"]:
        qualified = _read_record(relative, production_root)
        if (
            qualified is None
            or qualified[0]["receipt_digest"] != digest
            or qualified[0]["qualification_status"] != status
        ):
            raise ValueError("RES-407 fresh process found a changed pool qualification receipt")

    base = solve_selection_feasibility(
        inputs.problem,
        solver_config=PSE_V1_POOL_FEASIBILITY_SOLVER_PROFILE_V1,
    )
    if (
        base.status.value != receipt["original_base_status"]
        or base.problem_digest != receipt["original_problem_digest"]
    ):
        raise ValueError("RES-407 fresh process changed original base status or digest")
    if base.status is not FeasibilityStatus.INFEASIBLE:
        raise ValueError("RES-407 fresh process did not reconfirm the original infeasible base")

    if receipt["outcome"] == "QUALIFIED":
        retained = set(receipt["retained_addition_digests"])
        selected = tuple(item for item in options if item["candidate_digest"] in retained)
        if len(selected) != receipt["retained_addition_count"] or not selected:
            raise ValueError("RES-407 fresh process cannot resolve the retained additions")
        plan, pool, problem = _problem_for_options(
            inputs,
            _option_order(selected),
            staged_projected,
        )
        if (
            plan.plan_digest != receipt["repaired_plan_digest"]
            or pool.pool_digest != receipt["repaired_pool_digest"]
            or pool.candidate_count != receipt["repaired_pool_count"]
            or problem.problem_digest != receipt["repaired_base_problem_digest"]
        ):
            raise ValueError("RES-407 fresh process reconstructed a different repaired pool")
        if pool.pool_digest == inputs.pool.pool_digest:
            raise ValueError("RES-407 repaired pool did not get a new content digest")
        validate_variable_pre_review_pool(
            pool,
            exclusion=inputs.exclusion,
            source_resolver=inputs.source_resolver,
        )
        store_relative = receipt["repaired_pool_store_relative_path"]
        if store_relative != _pool_store_relative_path(plan.plan_digest):
            raise ValueError("RES-407 repaired pool path is not content-addressed by its new plan")
        stored_receipt, _file_digest, _size = read_external_production_json(
            f"{store_relative}/receipt.json",
            VariablePoolStoreReceiptV1,
            repository_root=repository_root,
            production_root=production_root,
        )
        if stored_receipt.receipt_digest != receipt["repaired_pool_store_receipt_digest"]:
            raise ValueError("RES-407 fresh process found a different derived pool store receipt")
        stored_plan, stored_pool = read_variable_pool_store(
            stored_receipt,
            supply_inventory=inputs.inventory,
            exclusion=inputs.exclusion,
            historical_input_digest=inputs.historical_inputs.input_digest,
            repository_root=repository_root,
            production_root=production_root,
            source_resolver=inputs.source_resolver,
        )
        if stored_plan != plan or stored_pool != pool:
            raise ValueError("RES-407 content-addressed store differs from fresh reconstruction")

        repair_key = tuple(receipt["retained_addition_digests"])
        trial_read = _read_record(_trial_relative(repair_root, repair_key), production_root)
        if trial_read is None:
            raise ValueError("RES-407 fresh process cannot find the retained exact base witness")
        retained_trial = trial_read[0]
        repaired_base = solve_selection_feasibility(
            problem,
            solver_config=PSE_V1_POOL_FEASIBILITY_SOLVER_PROFILE_V1,
        )
        if (
            repaired_base.status is not FeasibilityStatus.FEASIBLE
            or repaired_base.problem_digest != problem.problem_digest
            or repaired_base.plan_digest != retained_trial["plan_digest"]
            or repaired_base.validation_digest != retained_trial["validation_digest"]
        ):
            raise ValueError("RES-407 fresh process changed the repaired base witness")

        qualification_root = _path(
            repair_root,
            f"qualification/{problem.problem_digest.removeprefix('sha256:')}",
        )
        removal_records: list[Record] = []
        for index, candidate in enumerate(problem.candidates):
            scenario = _problem_without_candidate(problem, candidate.candidate_id)
            relative = _path(
                qualification_root,
                f"removals/{index:04d}-{canonical_hash(candidate.candidate_id).removeprefix('sha256:')}.json",
            )
            saved = _read_record(relative, production_root)
            if saved is None:
                raise ValueError("RES-407 fresh process cannot find every removal receipt")
            record = saved[0]
            if (
                record["input"]["scenario_problem_digest"] != scenario.problem_digest
                or record["input"]["candidate_payload_digest"] != candidate.payload_hash
                or res406._feasibility_status(record) is not FeasibilityStatus.FEASIBLE
            ):
                raise ValueError("RES-407 fresh process found a changed or non-feasible removal")
            removal_records.append(record)

        fresh_removal_checks = []
        for index, candidate in res406._sample_candidates(problem):
            scenario = _problem_without_candidate(problem, candidate.candidate_id)
            fresh_removal = solve_selection_feasibility(
                scenario,
                solver_config=PSE_V1_POOL_FEASIBILITY_SOLVER_PROFILE_V1,
            )
            stored = removal_records[index]
            if (
                fresh_removal.status.value != stored["status"]
                or fresh_removal.plan_digest != stored["plan_digest"]
                or fresh_removal.validation_digest != stored["validation_digest"]
            ):
                raise ValueError("RES-407 fresh-process canonical removal confirmation drifted")
            fresh_removal_checks.append(
                (canonical_hash(candidate.candidate_id), fresh_removal.status.value)
            )

        base_record = {
            "receipt_digest": retained_trial["receipt_digest"],
            "status": retained_trial["status"],
            "proof_method": "EXACT_FEASIBILITY_ORACLE",
            "plan_digest": retained_trial["plan_digest"],
            "validation_digest": retained_trial["validation_digest"],
        }
        reserve = res406._reserve_result(
            replace(inputs, plan=plan, pool=pool, problem=problem),
            base_record,
            tuple(removal_records),
            {"status": "PASS"},
        )
        status_counts = Counter(record["status"] for record in removal_records)
        q_status = _qualification_status(
            checked=len(removal_records),
            candidate_count=len(problem.candidates),
            feasible=status_counts[FeasibilityStatus.FEASIBLE.value],
            infeasible=status_counts[FeasibilityStatus.INFEASIBLE.value],
            unknown=status_counts[FeasibilityStatus.UNKNOWN.value],
            critical_status=reserve["critical_reserve_status"],
            backfill_needs=reserve["backfill_needs"],
        )
        if q_status != "QUALIFIED":
            raise ValueError("RES-407 fresh process failed the full removal/critical qualification")
        qualification_read = _read_record(
            _path(qualification_root, "qualification-receipt.json"), production_root
        )
        expected_qualification = {
            "schema_version": "RES407-POOL-QUALIFICATION@1.0.0",
            "repair_plan_digest": plan.plan_digest,
            "repair_pool_digest": pool.pool_digest,
            "problem_digest": problem.problem_digest,
            "base_receipt_digest": retained_trial["receipt_digest"],
            "checked_removals": len(removal_records),
            "feasible_removals": status_counts[FeasibilityStatus.FEASIBLE.value],
            "infeasible_removals": status_counts[FeasibilityStatus.INFEASIBLE.value],
            "unknown_removals": status_counts[FeasibilityStatus.UNKNOWN.value],
            "critical_obligation_count": reserve["critical_obligation_count"],
            "critical_with_structural_reserve": reserve[
                "critical_obligations_with_structural_reserve"
            ],
            "critical_reserve_status": reserve["critical_reserve_status"],
            "backfill_needs": reserve["backfill_needs"],
            "reserve_deficits": reserve["reserve_deficits"],
            "outcome": reserve["outcome"],
            "qualification_status": q_status,
            "removal_receipt_digests": tuple(
                record["receipt_digest"] for record in removal_records
            ),
        }
        if qualification_read is None or qualification_read[0] != res406._bound(
            _wire_record(expected_qualification)
        ):
            raise ValueError("RES-407 fresh process could not reconstruct qualification receipt")
        if (
            stored_receipt.store_relative_path == inputs.store_receipt.store_relative_path
            or receipt["repaired_pool_lineage_receipt_digest"] is None
        ):
            raise ValueError("RES-407 derived pool path or lineage receipt is missing")
        lineage_read = _read_record(
            _path(repair_root, "repaired-pool-lineage-receipt.json"), production_root
        )
        if (
            lineage_read is None
            or lineage_read[0]["receipt_digest"] != receipt["repaired_pool_lineage_receipt_digest"]
            or lineage_read[0]["res405_receipt_digest"] != RES405_RECEIPT_DIGEST
            or lineage_read[0]["res451_private_diagnosis_receipt_digest"] != RES451_RECEIPT_DIGEST
            or lineage_read[0]["repair_set_receipt_digest"] != receipt["repair_set_receipt_digest"]
        ):
            raise ValueError("RES-407 repaired pool lineage receipt differs")
        if (
            receipt["checked_removals"] != len(problem.candidates)
            or receipt["feasible_removals"] != len(problem.candidates)
            or receipt["infeasible_removals"] != 0
            or receipt["unknown_removals"] != 0
            or receipt["critical_reserve_status"] != "PASS"
        ):
            raise ValueError("RES-407 final receipt does not bind complete pool qualification")
    elif any(
        receipt[key] is not None
        for key in ("repaired_plan_digest", "repaired_pool_digest", "repaired_base_problem_digest")
    ):
        raise ValueError("RES-407 non-qualified outcome unexpectedly retains a repaired pool")

    extra_store = receipt["repaired_pool_store_relative_path"]
    artifacts = _artifact_inventory(repair_root, production_root, extra_store)
    if canonical_hash(artifacts) != receipt["artifact_inventory_digest"] or tuple(
        artifacts
    ) != tuple(tuple(item) for item in receipt["artifact_inventory"]):
        raise ValueError("RES-407 fresh process found a changed artifact inventory")
    _assert_original_store_unchanged(
        receipt["original_store_artifact_digest"],
        _original_store_digest(inputs, production_root),
    )
    if receipt["runner_head"] != runner_head:
        raise ValueError("RES-407 runner head changed during fresh-process confirmation")
    body = {key: value for key, value in receipt.items() if key != "receipt_digest"}
    if canonical_hash(body) != receipt["receipt_digest"]:
        raise ValueError("RES-407 fresh process could not reconstruct the final receipt")
    if receipt["fresh_process_confirmation"] != "PENDING":
        raise ValueError("RES-407 final receipt was not awaiting fresh-process confirmation")
    body["fresh_process_confirmation"] = "PASS"
    return {
        "status": "PASS",
        "private_receipt_digest": receipt["receipt_digest"],
        "anticipated_private_receipt_digest": canonical_hash(body),
        "original_problem_digest": inputs.problem.problem_digest,
        "original_base_status": base.status.value,
        "repair_demand_digest": canonical_hash(demand),
    }


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("qualify", "confirm"))
    parser.add_argument("--production-root", type=Path, default=DEFAULT_PRODUCTION_ROOT)
    parser.add_argument("--expected-receipt-digest")
    return parser.parse_args()


def main() -> int:
    args = _arguments()
    production_root = args.production_root.resolve()
    if args.action == "confirm":
        if not args.expected_receipt_digest:
            raise ValueError("RES-407 confirm requires the expected private receipt digest")
        print(json.dumps(_confirm(_REPOSITORY, production_root, args.expected_receipt_digest)))
        return 0
    _run_qualification(_REPOSITORY, production_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
