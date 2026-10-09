#!/usr/bin/env python3
"""Qualify the immutable RES-405 candidate pool for RES-406."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, replace
from importlib import import_module
from importlib.metadata import version
from pathlib import Path, PurePosixPath
from typing import Any

from dynamislm.benchmark.authority_supply import (
    AUTHORITY_SUPPLY_SCHEMA,
    ReserveDeficitKind,
    ReserveDeficitV1,
)
from dynamislm.benchmark.constants import CaseOrigin
from dynamislm.benchmark.production_exclusions import QualificationExclusionCommitmentV1
from dynamislm.benchmark.production_store import (
    DEFAULT_PRODUCTION_ROOT,
    read_external_production_json,
    write_external_production_json,
)
from dynamislm.benchmark.public_repository import validate_production_private_material_absent
from dynamislm.benchmark.selection_contracts import (
    POOL_FEASIBILITY_SOLVER_PROFILE_VERSION,
    PSE_V1_POOL_FEASIBILITY_SOLVER_PROFILE_V1,
    ConstraintKind,
    FeasibilityStatus,
    FeatureKind,
    FinalSelectionProblem,
)
from dynamislm.benchmark.selection_pool import (
    _base_diagnosis,
    _build_problem,
    _exact_deficits_and_requests,
    _problem_without_candidate,
    derive_pool_backfill_needs,
)
from dynamislm.benchmark.selection_solver import solve_selection_feasibility
from dynamislm.benchmark.variable_pool import (
    ProductionAuthoringCandidatePoolV1,
    VariablePoolAuthoringPlanV1,
    production_authoring_candidate_pool_digest,
    project_variable_pool_selection_candidates,
    variable_pool_authoring_plan_digest,
)
from dynamislm.benchmark.variable_pool_store import (
    DYNAMISLM_EXECUTION_BASELINE,
    VariablePoolStoreReceiptV1,
    _read_candidate_for_binding,
    read_variable_pool_store,
    validate_variable_pool_store_receipt,
)
from dynamislm.serialization import (
    SERIALIZATION_VERSION,
    canonical_hash,
    canonical_json,
    type_identifier,
)

_res405 = import_module(
    f"{__package__}.res405_variable_pool" if __package__ else "res405_variable_pool"
)
_build_authority = _res405._build_authority
_private_material = _res405._private_material

ENTRY_HEAD = "b6b4722c189117302057a27adb4d62dcfaa3a288"
RES405_RECEIPT_DIGEST = "sha256:8e4dfb324d0aab00196903229814170e0e1f16e54ec348082f57cedb74e65272"
PLAN_DIGEST = "sha256:e42cd6316da25f622203eb1a2340b34a56c4d3baa411773599d1f278b0bce845"
POOL_DIGEST = "sha256:cc901fe4bc1ecd2fe9f3a7f2d294b24c4201b647fe9645ea40a0a5c8ab19f7ca"
SUPPLY_INVENTORY_DIGEST = "sha256:4b7ee2d0f9b3f1b56a638b0b27aa01a5ba153e226f34c37bb995dd113292c616"
QUALIFICATION_EXCLUSION_DIGEST = (
    "sha256:5bcc5da6fe959a66b819eb4a6c45326f82b06c4660a114de5f20aa3adf3b6343"
)
POOL_COUNT = 449
BRANCH = "julitocrztuga/res-406-p4a-r2-candidate-level-pool-qualification-exact-single"
PROFILE_NAME = "PSE_V1_POOL_FEASIBILITY_SOLVER_PROFILE_V1"
PROFILE_VERSION = POOL_FEASIBILITY_SOLVER_PROFILE_VERSION
_SUMMARY_PATH = Path("reports/performance_science_eval/res406_pool_qualification.json")
_PUBLIC_RECEIPT_PATH = Path("docs/qualification/RES-406-ACCEPTANCE-RECEIPT.md")
_BASE_SCHEMA = "RES406-BASE-FEASIBILITY-RECEIPT@1.0.0"
_REMOVAL_SCHEMA = "RES406-SINGLE-REMOVAL-RECEIPT@1.0.0"
_CONFIRM_SCHEMA = "RES406-FRESH-PROCESS-CONFIRMATION@1.0.0"
_FINAL_SCHEMA = "RES406-POOL-QUALIFICATION-RECEIPT@1.0.0"
Record = dict[str, Any]


@dataclass(frozen=True, slots=True)
class QualificationInputs:
    repository_root: Path
    production_root: Path
    runner_head: str
    store_receipt: VariablePoolStoreReceiptV1
    plan: VariablePoolAuthoringPlanV1
    pool: ProductionAuthoringCandidatePoolV1
    inventory: Any
    historical_inputs: Any
    exclusion: QualificationExclusionCommitmentV1
    source_resolver: Any
    problem: FinalSelectionProblem


def _git(repository_root: Path, *args: str) -> str:
    return subprocess.run(
        ("git", "-C", str(repository_root), *args),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _require_execution_tree(repository_root: Path) -> str:
    head = _git(repository_root, "rev-parse", "HEAD")
    if _git(repository_root, "branch", "--show-current") != BRANCH:
        raise ValueError("RES-406 runner is on the wrong branch")
    entry = _git(repository_root, "rev-parse", ENTRY_HEAD)
    if entry != ENTRY_HEAD:
        raise ValueError("RES-406 entry authority is not the exact PR #39 merge commit")
    parents = _git(repository_root, "rev-list", "--parents", "-n", "1", ENTRY_HEAD).split()
    if len(parents) != 3 or parents[1] != DYNAMISLM_EXECUTION_BASELINE:
        raise ValueError("RES-406 entry head does not bind the declared execution baseline")
    subprocess.run(
        ("git", "-C", str(repository_root), "merge-base", "--is-ancestor", ENTRY_HEAD, head),
        check=True,
        capture_output=True,
    )
    subprocess.run(
        (
            "git",
            "-C",
            str(repository_root),
            "merge-base",
            "--is-ancestor",
            DYNAMISLM_EXECUTION_BASELINE,
            head,
        ),
        check=True,
        capture_output=True,
    )
    if _git(repository_root, "status", "--porcelain=v1"):
        raise ValueError("RES-406 execution requires a clean tracked and untracked worktree")
    return head


def _store_plan_and_packets(
    repository_root: Path,
    production_root: Path,
    receipt: VariablePoolStoreReceiptV1,
) -> tuple[VariablePoolAuthoringPlanV1, ProductionAuthoringCandidatePoolV1]:
    relative = receipt.store_relative_path
    plan, _digest, _size = read_external_production_json(
        f"{relative}/authoring-plan.json",
        VariablePoolAuthoringPlanV1,
        repository_root=repository_root,
        production_root=production_root,
    )
    if (
        plan.plan_digest != PLAN_DIGEST
        or plan.plan_digest != variable_pool_authoring_plan_digest(plan)
        or len(receipt.candidate_file_digests) != POOL_COUNT
    ):
        raise ValueError("RES-405 stored authoring plan or candidate inventory is not exact")
    packets = tuple(
        _read_candidate_for_binding(
            receipt,
            candidate_id,
            expected_digest,
            repository_root,
            production_root,
        )
        for candidate_id, expected_digest in receipt.candidate_file_digests
    )
    if tuple(item.candidate_id for item in plan.recipes) != tuple(
        item.candidate_id for item in packets
    ):
        raise ValueError("RES-405 stored packets differ from the exact authoring plan ordering")
    pool = ProductionAuthoringCandidatePoolV1(
        authoring_plan_digest=plan.plan_digest,
        packets=packets,
        pool_digest=receipt.materialized_pool_digest,
    )
    if (
        pool.candidate_count != POOL_COUNT
        or pool.pool_digest != POOL_DIGEST
        or pool.pool_digest != production_authoring_candidate_pool_digest(pool)
    ):
        raise ValueError("RES-405 stored packets do not match the immutable pool digest")
    return plan, pool


def _load_inputs(repository_root: Path, production_root: Path) -> QualificationInputs:
    receipt_path = f"production/variable-pools/{PLAN_DIGEST.removeprefix('sha256:')}/receipt.json"
    receipt, _file_digest, _size = read_external_production_json(
        receipt_path,
        VariablePoolStoreReceiptV1,
        repository_root=repository_root,
        production_root=production_root,
    )
    validate_variable_pool_store_receipt(receipt)
    if (
        receipt.receipt_digest != RES405_RECEIPT_DIGEST
        or receipt.execution_baseline != DYNAMISLM_EXECUTION_BASELINE
        or receipt.variable_pool_authoring_plan_digest != PLAN_DIGEST
        or receipt.materialized_pool_digest != POOL_DIGEST
        or receipt.supply_inventory_digest != SUPPLY_INVENTORY_DIGEST
        or receipt.qualification_exclusion_digest != QUALIFICATION_EXCLUSION_DIGEST
        or receipt.candidate_count != POOL_COUNT
    ):
        raise ValueError(
            "RES-405 private store receipt differs from the immutable mission authority"
        )

    # Read and hash the committed plan and packets before rebuilding live authority.
    raw_plan, raw_pool = _store_plan_and_packets(repository_root, production_root, receipt)
    inventory, historical_inputs, exclusion, source_resolver, _external_root = _build_authority(
        repository_root, production_root
    )
    if (
        inventory.schema_version != AUTHORITY_SUPPLY_SCHEMA
        or inventory.inventory_digest != SUPPLY_INVENTORY_DIGEST
        or exclusion.commitment_digest != QUALIFICATION_EXCLUSION_DIGEST
        or receipt.historical_input_digest != historical_inputs.input_digest
    ):
        raise ValueError("live v1.3 authority does not match the RES-405 store receipt")
    plan, pool = read_variable_pool_store(
        receipt,
        supply_inventory=inventory,
        exclusion=exclusion,
        historical_input_digest=historical_inputs.input_digest,
        repository_root=repository_root,
        production_root=production_root,
        source_resolver=source_resolver,
    )
    if plan != raw_plan or pool != raw_pool:
        raise ValueError("authority-bound RES-405 read differs from the earlier exact store read")

    projected = project_variable_pool_selection_candidates(pool, source_resolver=source_resolver)
    if len(projected) != POOL_COUNT:
        raise ValueError("RES-369 metadata projection changed the exact pool count")
    problem = _build_problem(projected, ())
    if len(problem.candidates) != POOL_COUNT:
        raise ValueError("RES-369 final-selection problem changed candidate count")
    return QualificationInputs(
        repository_root=repository_root,
        production_root=production_root,
        runner_head=_git(repository_root, "rev-parse", "HEAD"),
        store_receipt=receipt,
        plan=plan,
        pool=pool,
        inventory=inventory,
        historical_inputs=historical_inputs,
        exclusion=exclusion,
        source_resolver=source_resolver,
        problem=problem,
    )


def _profile(*, public: bool = False) -> Record:
    config = PSE_V1_POOL_FEASIBILITY_SOLVER_PROFILE_V1
    values: Record = {
        "name": PROFILE_NAME,
        "version": PROFILE_VERSION,
        "workers": config.workers,
        "timeout_s": config.timeout_s,
        "canonical_chunk_size": config.canonical_chunk_size,
        "cp_model_presolve": config.cp_model_presolve,
        "randomize_search": config.randomize_search,
    }
    if not public:
        values["random_seed"] = config.random_seed
    return values


def _profile_key() -> str:
    return canonical_hash(_profile())


def _checkpoint_root(problem: FinalSelectionProblem) -> str:
    return "/".join(
        (
            "production/variable-pools/qualification",
            PLAN_DIGEST.removeprefix("sha256:"),
            ENTRY_HEAD,
            _profile_key().removeprefix("sha256:"),
            problem.problem_digest.removeprefix("sha256:"),
        )
    )


def _path(root: str, name: str) -> str:
    return f"{root}/{name}"


def _wire(value: object) -> object:
    return json.loads(canonical_json(value))["payload"]


def _bound(body: Mapping[str, Any]) -> Record:
    return {**body, "receipt_digest": canonical_hash(body)}


def _verify_bound(record: Record) -> None:
    digest = record.get("receipt_digest")
    body = {key: value for key, value in record.items() if key != "receipt_digest"}
    if not isinstance(digest, str) or digest != canonical_hash(body):
        raise ValueError("RES-406 checkpoint receipt digest mismatch")


def _read_record(
    relative: str,
    *,
    repository_root: Path,
    production_root: Path,
) -> tuple[Record, str, int] | None:
    from dynamislm.benchmark.qualification_store import (
        _external_input_path,
        _safe_external_root,
    )

    root, _repository = _safe_external_root(production_root, repository_root)
    path = _external_input_path(root, PurePosixPath(relative))
    if not path.exists():
        return None
    payload = path.read_bytes()
    try:
        envelope = json.loads(payload)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError("RES-406 checkpoint JSON is invalid") from exc
    if (
        not isinstance(envelope, dict)
        or envelope.get("serialization_version") != SERIALIZATION_VERSION
        or envelope.get("type") != type_identifier(dict)
        or not isinstance(envelope.get("payload"), dict)
    ):
        raise ValueError("RES-406 checkpoint has the wrong canonical JSON type")
    record = envelope["payload"]
    decoded = payload.decode("utf-8")
    if canonical_json(record) + "\n" != decoded:
        raise ValueError("RES-406 checkpoint is not canonical JSON")
    _verify_bound(record)
    return record, "sha256:" + hashlib.sha256(payload).hexdigest(), len(payload)


def _write_record(
    relative: str,
    body: Mapping[str, Any],
    *,
    repository_root: Path,
    production_root: Path,
) -> Record:
    record = _bound(body)
    write_external_production_json(
        record,
        relative,
        repository_root=repository_root,
        production_root=production_root,
    )
    stored = _read_record(
        relative,
        repository_root=repository_root,
        production_root=production_root,
    )
    if stored is None or stored[0] != record:
        raise ValueError("RES-406 checkpoint did not round-trip exactly")
    return record


def _base_input(inputs: QualificationInputs) -> Record:
    return {
        "entry_head": ENTRY_HEAD,
        "runner_head": inputs.runner_head,
        "execution_baseline": DYNAMISLM_EXECUTION_BASELINE,
        "res405_receipt_digest": RES405_RECEIPT_DIGEST,
        "plan_digest": PLAN_DIGEST,
        "pool_digest": POOL_DIGEST,
        "supply_inventory_digest": SUPPLY_INVENTORY_DIGEST,
        "qualification_exclusion_digest": QUALIFICATION_EXCLUSION_DIGEST,
        "candidate_count": POOL_COUNT,
        "problem_digest": inputs.problem.problem_digest,
        "constraint_inventory_digest": inputs.problem.constraint_inventory_digest,
        "solver_profile": _profile(),
        "solver_version": version("ortools"),
    }


def _base_receipt(
    inputs: QualificationInputs,
    relative: str,
    *,
    reuse: bool,
) -> Record:
    existing = _read_record(
        relative,
        repository_root=inputs.repository_root,
        production_root=inputs.production_root,
    )
    if existing is not None:
        record = existing[0]
        saved_head = record.get("input", {}).get("runner_head")
        if not isinstance(saved_head, str):
            raise ValueError("RES-406 base checkpoint has no runner Git head")
        subprocess.run(
            (
                "git",
                "-C",
                str(inputs.repository_root),
                "merge-base",
                "--is-ancestor",
                saved_head,
                _git(inputs.repository_root, "rev-parse", "HEAD"),
            ),
            check=True,
            capture_output=True,
        )
        effective_inputs = replace(inputs, runner_head=saved_head)
        expected_input = _base_input(effective_inputs)
        if record.get("schema_version") != _BASE_SCHEMA or record.get("input") != expected_input:
            raise ValueError("RES-406 base checkpoint does not match the exact current problem")
        if not reuse:
            raise ValueError("RES-406 base receipt already exists")
        return record

    expected_input = _base_input(inputs)
    result = solve_selection_feasibility(
        inputs.problem,
        solver_config=PSE_V1_POOL_FEASIBILITY_SOLVER_PROFILE_V1,
    )
    body: Record = {
        "schema_version": _BASE_SCHEMA,
        "input": expected_input,
        "status": result.status.value,
        "proof_method": "EXACT_FEASIBILITY_ORACLE",
        "plan_digest": result.plan_digest,
        "validation_digest": result.validation_digest,
        "validation_status": None
        if result.validation_status is None
        else result.validation_status.value,
        "diagnostic_codes": [item.code for item in result.diagnostics],
    }
    return _write_record(
        relative,
        body,
        repository_root=inputs.repository_root,
        production_root=inputs.production_root,
    )


def _removal_relative(root: str, index: int, candidate_id: str) -> str:
    identity_digest = canonical_hash(candidate_id).removeprefix("sha256:")
    return _path(root, f"removals/{index:04d}-{identity_digest}.json")


def _removal_input(
    inputs: QualificationInputs,
    index: int,
    candidate_id: str,
    candidate_digest: str,
    scenario: FinalSelectionProblem,
) -> Record:
    return {
        **_base_input(inputs),
        "candidate_index": index,
        "candidate_id": candidate_id,
        "candidate_digest": candidate_digest,
        "candidate_identity_digest": canonical_hash(candidate_id),
        "scenario_problem_digest": scenario.problem_digest,
    }


def _removal_receipt(
    inputs: QualificationInputs,
    root: str,
    index: int,
    candidate: Any,
    scenario: FinalSelectionProblem,
) -> Record:
    relative = _removal_relative(root, index, candidate.candidate_id)
    expected_input = _removal_input(
        inputs,
        index,
        candidate.candidate_id,
        candidate.payload_hash,
        scenario,
    )
    existing = _read_record(
        relative,
        repository_root=inputs.repository_root,
        production_root=inputs.production_root,
    )
    if existing is not None:
        record = existing[0]
        if record.get("schema_version") != _REMOVAL_SCHEMA or record.get("input") != expected_input:
            raise ValueError("RES-406 removal checkpoint does not match the exact scenario")
        return record

    result = solve_selection_feasibility(
        scenario,
        solver_config=PSE_V1_POOL_FEASIBILITY_SOLVER_PROFILE_V1,
    )
    return _write_record(
        relative,
        {
            "schema_version": _REMOVAL_SCHEMA,
            "input": expected_input,
            "status": result.status.value,
            "proof_method": "EXACT_FEASIBILITY_ORACLE",
            "plan_digest": result.plan_digest,
            "validation_digest": result.validation_digest,
        },
        repository_root=inputs.repository_root,
        production_root=inputs.production_root,
    )


def _feasibility_status(record: Record) -> FeasibilityStatus:
    status = FeasibilityStatus(record["status"])
    if record.get("proof_method") != "EXACT_FEASIBILITY_ORACLE":
        raise ValueError("RES-406 feasibility checkpoint has the wrong proof method")
    if status is FeasibilityStatus.FEASIBLE and not all(
        isinstance(record.get(key), str) and record[key].startswith("sha256:")
        for key in ("plan_digest", "validation_digest")
    ):
        raise ValueError("RES-406 feasible checkpoint lacks its validated witness digests")
    if status is not FeasibilityStatus.FEASIBLE and record.get("plan_digest") is not None:
        raise ValueError("RES-406 non-feasible checkpoint contains an accepted plan")
    return status


def _removal_checks(
    inputs: QualificationInputs,
    base: Record,
    records: tuple[Record, ...],
) -> tuple[Any, ...]:
    from dynamislm.benchmark.selection_pool import SingleCandidateRemovalCheckV1

    if _feasibility_status(base) is not FeasibilityStatus.FEASIBLE:
        return ()
    candidates = inputs.problem.candidates
    if len(records) != len(candidates):
        raise ValueError("RES-406 removal receipt count differs from the exact pool")
    checks = []
    for candidate, record in zip(candidates, records, strict=True):
        if record["input"]["candidate_id"] != candidate.candidate_id:
            raise ValueError("RES-406 removal receipt ordering differs from canonical candidates")
        checks.append(
            SingleCandidateRemovalCheckV1(
                candidate_digest=canonical_hash(candidate.candidate_id),
                status=_feasibility_status(record),
                proof_method=str(record["proof_method"]),
                plan_digest=record["plan_digest"],
                validation_digest=record["validation_digest"],
            )
        )
    return tuple(checks)


def _reserve_result(
    inputs: QualificationInputs,
    base: Record,
    records: tuple[Record, ...],
    confirmation: Record,
) -> Record:
    status = _feasibility_status(base)
    diagnosis = _base_diagnosis(inputs.problem, status)
    if status is not FeasibilityStatus.FEASIBLE:
        deficits: tuple[ReserveDeficitV1, ...] = (
            ReserveDeficitV1(
                deficit_kind=(
                    ReserveDeficitKind.EXACT_BASELINE_INFEASIBLE
                    if status is FeasibilityStatus.INFEASIBLE
                    else ReserveDeficitKind.EXACT_ORACLE_UNKNOWN
                ),
                scenario_digest=inputs.problem.problem_digest,
            ),
        )
        return {
            "base_diagnosis": _wire(diagnosis),
            "removal_checks": [],
            "removal_records": [],
            "critical_obligation_count": None,
            "critical_obligations_with_structural_reserve": None,
            "critical_reserve_status": "NOT_EVALUATED",
            "backfill_needs": [],
            "reserve_deficits": [_wire(item) for item in deficits],
            "backfill_requests": [],
            "outcome": "BASE_INFEASIBLE" if status is FeasibilityStatus.INFEASIBLE else "UNKNOWN",
        }

    checks = _removal_checks(inputs, base, records)
    needs = derive_pool_backfill_needs(inputs.problem)
    critical_constraints = tuple(
        constraint
        for constraint in inputs.problem.constraint_set.constraints
        if constraint.kind is ConstraintKind.FEATURE_MINIMUM
        and constraint.feature is not None
        and constraint.feature.kind is FeatureKind.CRITICAL_ERROR
    )
    needs_by_id = {need.constraint_id for need in needs}
    critical_with_reserve = sum(
        constraint.constraint_id not in needs_by_id for constraint in critical_constraints
    )
    removal_checks = tuple(checks)
    deficits, requests = _exact_deficits_and_requests(
        inputs.problem,
        _selection_receipt_view(base),
        removal_checks,
        inputs.inventory,
    )
    if any(check.status is FeasibilityStatus.UNKNOWN for check in removal_checks):
        outcome = "UNKNOWN"
        requests = ()
    elif all(check.status is FeasibilityStatus.FEASIBLE for check in removal_checks) and not needs:
        outcome = "QUALIFIED"
    else:
        no_lanes = any(not request.lane_ids for request in requests)
        if (
            no_lanes
            and inputs.inventory.authority_inventory_complete
            and inputs.inventory.capacity_scope_complete
        ):
            outcome = "AUTHORITY_EXPANSION_REQUIRED"
        elif needs and any(request.lane_ids for request in requests):
            outcome = "BACKFILL_REQUIRED"
        else:
            outcome = "METADATA_REQUIRED"
    if confirmation.get("status") != "PASS":
        outcome = "UNKNOWN"
        requests = ()
    return {
        "base_diagnosis": _wire(diagnosis),
        "removal_checks": removal_checks,
        "removal_records": list(records),
        "critical_obligation_count": len(critical_constraints),
        "critical_obligations_with_structural_reserve": critical_with_reserve,
        "critical_reserve_status": "PASS"
        if critical_with_reserve == len(critical_constraints)
        else "DEFICIT",
        "backfill_needs": [_wire(need) for need in needs],
        "reserve_deficits": [_wire(item) for item in deficits],
        "backfill_requests": [_wire(item) for item in requests],
        "outcome": outcome,
    }


def _selection_receipt_view(record: Record) -> Any:
    from types import SimpleNamespace

    return SimpleNamespace(status=_feasibility_status(record))


def _sample_candidates(problem: FinalSelectionProblem) -> tuple[tuple[int, Any], ...]:
    first_by_origin: dict[CaseOrigin, tuple[int, Any]] = {}
    for index, candidate in enumerate(problem.candidates):
        first_by_origin.setdefault(candidate.origin_class, (index, candidate))
    return tuple(
        first_by_origin[key] for key in sorted(first_by_origin, key=lambda item: item.value)
    )


def _confirmation_relative(root: str) -> str:
    return _path(root, "fresh-process-confirmation.json")


def _confirm_in_fresh_process(
    inputs: QualificationInputs,
    checkpoint_root: str,
    base: Record,
    removal_records: tuple[Record, ...],
) -> Record:
    relative = _confirmation_relative(checkpoint_root)
    existing = _read_record(
        relative,
        repository_root=inputs.repository_root,
        production_root=inputs.production_root,
    )
    if existing is not None:
        record = existing[0]
        if (
            record.get("schema_version") != _CONFIRM_SCHEMA
            or record.get("input", {}).get("base_receipt_digest") != base["receipt_digest"]
            or record.get("input", {}).get("problem_digest") != inputs.problem.problem_digest
        ):
            raise ValueError("RES-406 fresh-process confirmation checkpoint is stale")
        return record

    subprocess.run(
        (
            sys.executable,
            str(inputs.repository_root / "scripts/res406_pool_qualification.py"),
            "confirm",
            "--production-root",
            str(inputs.production_root),
            "--expected-problem-digest",
            inputs.problem.problem_digest,
        ),
        check=True,
        cwd=inputs.repository_root,
    )
    result = _read_record(
        relative,
        repository_root=inputs.repository_root,
        production_root=inputs.production_root,
    )
    if result is None:
        raise ValueError("RES-406 fresh process did not write its confirmation receipt")
    return result[0]


def _confirm_action(repository_root: Path, production_root: Path, expected_problem: str) -> int:
    inputs = _load_inputs(repository_root, production_root)
    if inputs.problem.problem_digest != expected_problem:
        raise ValueError("RES-406 fresh process rebuilt a different exact selection problem")
    root = _checkpoint_root(inputs.problem)
    base_read = _read_record(
        _path(root, "base-receipt.json"),
        repository_root=repository_root,
        production_root=production_root,
    )
    if base_read is None:
        raise ValueError("RES-406 fresh process cannot find the base receipt")
    base = base_read[0]
    fresh_process_head = inputs.runner_head
    saved_base_head = base.get("input", {}).get("runner_head")
    if not isinstance(saved_base_head, str):
        raise ValueError("RES-406 base checkpoint has no runner Git head")
    inputs = replace(inputs, runner_head=saved_base_head)
    if base["input"] != _base_input(inputs):
        raise ValueError("RES-406 fresh process base receipt is bound to different solver inputs")
    fresh_base = solve_selection_feasibility(
        inputs.problem,
        solver_config=PSE_V1_POOL_FEASIBILITY_SOLVER_PROFILE_V1,
    )
    samples: list[Record] = []
    pass_status = (
        fresh_base.status.value == base["status"]
        and fresh_base.plan_digest == base["plan_digest"]
        and fresh_base.validation_digest == base["validation_digest"]
    )
    if (
        fresh_base.status is FeasibilityStatus.FEASIBLE
        and base["status"] == FeasibilityStatus.FEASIBLE.value
    ):
        for index, candidate in _sample_candidates(inputs.problem):
            scenario = _problem_without_candidate(inputs.problem, candidate.candidate_id)
            result = solve_selection_feasibility(
                scenario,
                solver_config=PSE_V1_POOL_FEASIBILITY_SOLVER_PROFILE_V1,
            )
            saved = _read_record(
                _removal_relative(root, index, candidate.candidate_id),
                repository_root=repository_root,
                production_root=production_root,
            )
            if saved is None:
                raise ValueError("RES-406 fresh process sample has no main-run receipt")
            matches = (
                result.status.value == saved[0].get("status")
                and result.plan_digest == saved[0].get("plan_digest")
                and result.validation_digest == saved[0].get("validation_digest")
            )
            pass_status &= matches
            samples.append(
                {
                    "candidate_digest": candidate.payload_hash,
                    "candidate_identity_digest": canonical_hash(candidate.candidate_id),
                    "scenario_problem_digest": scenario.problem_digest,
                    "expected_status": saved[0]["status"],
                    "observed_status": result.status.value,
                    "plan_digest": result.plan_digest,
                    "validation_digest": result.validation_digest,
                    "status_match": matches,
                }
            )
    elif base["status"] == FeasibilityStatus.FEASIBLE.value:
        pass_status = False
    body = {
        "schema_version": _CONFIRM_SCHEMA,
        "input": {
            "entry_head": ENTRY_HEAD,
            "runner_head": fresh_process_head,
            "res405_receipt_digest": RES405_RECEIPT_DIGEST,
            "plan_digest": PLAN_DIGEST,
            "pool_digest": POOL_DIGEST,
            "problem_digest": inputs.problem.problem_digest,
            "base_receipt_digest": base["receipt_digest"],
            "solver_profile": _profile(),
            "solver_version": fresh_base.solver_version,
        },
        "status": "PASS" if pass_status else "FAIL",
        "base_status": fresh_base.status.value,
        "base_plan_digest": fresh_base.plan_digest,
        "base_validation_digest": fresh_base.validation_digest,
        "sample_count": len(samples),
        "samples": samples,
    }
    _write_record(
        _confirmation_relative(root),
        body,
        repository_root=repository_root,
        production_root=production_root,
    )
    print(f"FRESH_PROCESS_CONFIRMATION={body['status']}")
    return 0


def _checkpoint_inventory(
    inputs: QualificationInputs,
    checkpoint_root: str,
    base: Record,
    removals: tuple[Record, ...],
    confirmation: Record,
) -> tuple[tuple[str, str, int], ...]:
    relative_paths = [_path(checkpoint_root, "base-receipt.json")]
    if _feasibility_status(base) is FeasibilityStatus.FEASIBLE:
        relative_paths.extend(
            _removal_relative(checkpoint_root, index, candidate.candidate_id)
            for index, candidate in enumerate(inputs.problem.candidates)
        )
        if len(removals) != len(inputs.problem.candidates):
            raise ValueError("RES-406 checkpoint inventory lacks all 449 removals")
    relative_paths.append(_confirmation_relative(checkpoint_root))
    inventory = []
    for relative in relative_paths:
        result = _read_record(
            relative,
            repository_root=inputs.repository_root,
            production_root=inputs.production_root,
        )
        if result is None:
            raise ValueError("RES-406 checkpoint inventory references a missing receipt")
        inventory.append((relative, result[1], result[2]))

    from dynamislm.benchmark.qualification_store import _external_input_path, _safe_external_root

    external_root, _repo = _safe_external_root(inputs.production_root, inputs.repository_root)
    directory = _external_input_path(external_root, PurePosixPath(checkpoint_root))
    expected_files = {
        str(PurePosixPath(path).relative_to(PurePosixPath(checkpoint_root)))
        for path in relative_paths
    } | {"final-receipt.json"}
    actual_files: set[str] = set()
    for parent, directories, filenames in os.walk(directory, followlinks=False):
        for name in directories:
            path = Path(parent) / name
            if path.is_symlink() or not path.is_dir():
                raise ValueError("RES-406 checkpoint has an unsafe directory")
        for name in filenames:
            path = Path(parent) / name
            if path.is_symlink() or not path.is_file():
                raise ValueError("RES-406 checkpoint contains an unsafe artifact")
            actual_files.add(path.relative_to(directory).as_posix())
    if actual_files not in (expected_files - {"final-receipt.json"}, expected_files):
        raise ValueError("RES-406 checkpoint contains unexpected or incomplete artifacts")
    return tuple(inventory)


def _public_outcome(outcome: str) -> str:
    return {
        "QUALIFIED": "RES-408",
        "BACKFILL_REQUIRED": "RES-407",
        "METADATA_REQUIRED": "RES-407",
        "AUTHORITY_EXPANSION_REQUIRED": "RES-407",
        "BASE_INFEASIBLE": "STOP",
        "UNKNOWN": "STOP",
    }[outcome]


def _final_body(
    inputs: QualificationInputs,
    checkpoint_root: str,
    base: Record,
    removals: tuple[Record, ...],
    confirmation: Record,
    inventory: tuple[tuple[str, str, int], ...],
) -> Record:
    result = _reserve_result(inputs, base, removals, confirmation)
    inventory_digest = canonical_hash(inventory)
    return {
        "schema_version": _FINAL_SCHEMA,
        "mission": "RES-406",
        "entry_head": ENTRY_HEAD,
        "runner_head": base["input"]["runner_head"],
        "fresh_process_runner_head": confirmation["input"]["runner_head"],
        "execution_baseline": DYNAMISLM_EXECUTION_BASELINE,
        "res405_receipt_digest": RES405_RECEIPT_DIGEST,
        "plan_digest": PLAN_DIGEST,
        "pool_digest": POOL_DIGEST,
        "supply_inventory_digest": SUPPLY_INVENTORY_DIGEST,
        "qualification_exclusion_digest": QUALIFICATION_EXCLUSION_DIGEST,
        "candidate_count": POOL_COUNT,
        "problem_digest": inputs.problem.problem_digest,
        "solver_profile": _profile(),
        "solver_version": base["input"]["solver_version"],
        "base_status": base["status"],
        "base_plan_digest": base["plan_digest"],
        "base_validation_digest": base["validation_digest"],
        "base_diagnosis": result["base_diagnosis"],
        "checked_removal_count": len(removals),
        "feasible_removal_count": sum(item["status"] == "FEASIBLE" for item in removals),
        "infeasible_removal_count": sum(item["status"] == "INFEASIBLE" for item in removals),
        "unknown_removal_count": sum(item["status"] == "UNKNOWN" for item in removals),
        "critical_obligation_count": result["critical_obligation_count"],
        "critical_obligations_with_structural_reserve": result[
            "critical_obligations_with_structural_reserve"
        ],
        "critical_reserve_status": result["critical_reserve_status"],
        "reserve_deficits": result["reserve_deficits"],
        "backfill_needs": result["backfill_needs"],
        "backfill_requests": result["backfill_requests"],
        "backfill_execution": "NONE",
        "fresh_process_confirmation": {
            "status": confirmation["status"],
            "receipt_digest": confirmation["receipt_digest"],
            "sample_count": confirmation["sample_count"],
        },
        "checkpoint_path": checkpoint_root,
        "artifact_inventory": [list(item) for item in inventory],
        "artifact_inventory_digest": inventory_digest,
        "outcome": result["outcome"],
        "next": _public_outcome(result["outcome"]),
    }


def _verify_final_receipt(
    inputs: QualificationInputs,
    checkpoint_root: str,
    base: Record,
    removals: tuple[Record, ...],
    confirmation: Record,
) -> Record:
    _validate_confirmation(inputs, base, removals, confirmation)
    inventory = _checkpoint_inventory(inputs, checkpoint_root, base, removals, confirmation)
    expected = _bound(_final_body(inputs, checkpoint_root, base, removals, confirmation, inventory))
    stored = _read_record(
        _path(checkpoint_root, "final-receipt.json"),
        repository_root=inputs.repository_root,
        production_root=inputs.production_root,
    )
    if stored is None or stored[0] != expected:
        raise ValueError("RES-406 final qualification receipt failed canonical reconstruction")
    return expected


def _validate_confirmation(
    inputs: QualificationInputs,
    base: Record,
    removals: tuple[Record, ...],
    confirmation: Record,
) -> None:
    fresh_process_head = confirmation.get("input", {}).get("runner_head")
    if not isinstance(fresh_process_head, str):
        raise ValueError("RES-406 fresh-process confirmation has no runner Git head")
    current_head = _git(inputs.repository_root, "rev-parse", "HEAD")
    for ancestor, descendant in (
        (base["input"]["runner_head"], fresh_process_head),
        (fresh_process_head, current_head),
    ):
        subprocess.run(
            (
                "git",
                "-C",
                str(inputs.repository_root),
                "merge-base",
                "--is-ancestor",
                ancestor,
                descendant,
            ),
            check=True,
            capture_output=True,
        )
    expected_input = {
        "entry_head": ENTRY_HEAD,
        "runner_head": fresh_process_head,
        "res405_receipt_digest": RES405_RECEIPT_DIGEST,
        "plan_digest": PLAN_DIGEST,
        "pool_digest": POOL_DIGEST,
        "problem_digest": inputs.problem.problem_digest,
        "base_receipt_digest": base["receipt_digest"],
        "solver_profile": _profile(),
        "solver_version": version("ortools"),
    }
    if (
        confirmation.get("schema_version") != _CONFIRM_SCHEMA
        or confirmation.get("input") != expected_input
    ):
        raise ValueError("RES-406 fresh-process confirmation has stale solver or problem inputs")
    fresh_status = FeasibilityStatus(confirmation["base_status"])
    base_matches = (
        fresh_status is _feasibility_status(base)
        and confirmation.get("base_plan_digest") == base.get("plan_digest")
        and confirmation.get("base_validation_digest") == base.get("validation_digest")
    )
    expected_samples = (
        _sample_candidates(inputs.problem)
        if fresh_status is FeasibilityStatus.FEASIBLE
        and _feasibility_status(base) is FeasibilityStatus.FEASIBLE
        else ()
    )
    samples = confirmation.get("samples")
    if not isinstance(samples, list) or len(samples) != len(expected_samples):
        raise ValueError("RES-406 fresh-process confirmation sample inventory is incomplete")
    sample_matches = True
    for (index, candidate), sample in zip(expected_samples, samples, strict=True):
        scenario = _problem_without_candidate(inputs.problem, candidate.candidate_id)
        if len(removals) != POOL_COUNT:
            raise ValueError("RES-406 fresh-process sample cannot bind all removal receipts")
        saved = removals[index]
        match = (
            sample.get("candidate_digest") == candidate.payload_hash
            and sample.get("candidate_identity_digest") == canonical_hash(candidate.candidate_id)
            and sample.get("scenario_problem_digest") == scenario.problem_digest
            and sample.get("expected_status") == saved.get("status")
            and sample.get("observed_status") == saved.get("status")
            and sample.get("plan_digest") == saved.get("plan_digest")
            and sample.get("validation_digest") == saved.get("validation_digest")
        )
        if sample.get("status_match") is not match:
            raise ValueError("RES-406 fresh-process sample receipt is internally inconsistent")
        sample_matches &= match
    expected_result = "PASS" if base_matches and sample_matches else "FAIL"
    if (
        confirmation.get("sample_count") != len(expected_samples)
        or confirmation.get("status") != expected_result
    ):
        raise ValueError("RES-406 fresh-process confirmation result does not reconstruct")


def _verify_action(repository_root: Path, production_root: Path) -> int:
    inputs = _load_inputs(repository_root, production_root)
    root = _checkpoint_root(inputs.problem)
    base_read = _read_record(
        _path(root, "base-receipt.json"),
        repository_root=repository_root,
        production_root=production_root,
    )
    if base_read is None:
        raise ValueError("RES-406 final receipt has no base checkpoint")
    base = base_read[0]
    saved_head = base.get("input", {}).get("runner_head")
    if not isinstance(saved_head, str):
        raise ValueError("RES-406 base checkpoint has no runner Git head")
    subprocess.run(
        (
            "git",
            "-C",
            str(repository_root),
            "merge-base",
            "--is-ancestor",
            saved_head,
            _git(repository_root, "rev-parse", "HEAD"),
        ),
        check=True,
        capture_output=True,
    )
    inputs = replace(inputs, runner_head=saved_head)
    if base["input"] != _base_input(inputs):
        raise ValueError("RES-406 final receipt's base inputs no longer reconstruct")
    removals: tuple[Record, ...] = ()
    if _feasibility_status(base) is FeasibilityStatus.FEASIBLE:
        removal_records = []
        for index, candidate in enumerate(inputs.problem.candidates):
            result = _read_record(
                _removal_relative(root, index, candidate.candidate_id),
                repository_root=repository_root,
                production_root=production_root,
            )
            if result is None:
                raise ValueError("RES-406 final receipt is missing a removal checkpoint")
            scenario = _problem_without_candidate(inputs.problem, candidate.candidate_id)
            if result[0].get("input") != _removal_input(
                inputs, index, candidate.candidate_id, candidate.payload_hash, scenario
            ):
                raise ValueError("RES-406 final receipt has a removal bound to stale problem input")
            _feasibility_status(result[0])
            removal_records.append(result[0])
        removals = tuple(removal_records)
    confirmation_result = _read_record(
        _confirmation_relative(root),
        repository_root=repository_root,
        production_root=production_root,
    )
    if confirmation_result is None:
        raise ValueError("RES-406 final receipt is missing fresh-process confirmation")
    confirmation = confirmation_result[0]
    final = _verify_final_receipt(inputs, root, base, removals, confirmation)
    print(
        json.dumps(
            {
                "FINAL_RECEIPT_DIGEST": final["receipt_digest"],
                "ARTIFACT_INVENTORY_DIGEST": final["artifact_inventory_digest"],
                "RECONSTRUCTION": "PASS",
            },
            sort_keys=True,
        )
    )
    return 0


def _public_payload(final: Record, leak_guard: Any) -> Record:
    deficit_counts = Counter(item["deficit_kind"] for item in final["reserve_deficits"])
    request_counts = Counter(item["request_kind"] for item in final["backfill_requests"])
    return {
        "mission": "RES-406",
        "entry_head": ENTRY_HEAD,
        "execution_baseline": DYNAMISLM_EXECUTION_BASELINE,
        "res405_receipt_digest": RES405_RECEIPT_DIGEST,
        "plan_digest": PLAN_DIGEST,
        "pool_digest": POOL_DIGEST,
        "supply_inventory_digest": SUPPLY_INVENTORY_DIGEST,
        "qualification_exclusion_digest": QUALIFICATION_EXCLUSION_DIGEST,
        "candidate_count": POOL_COUNT,
        "selection_problem_digest": final["problem_digest"],
        "solver_profile": _profile(public=True),
        "public_leak_guard": leak_guard.status,
        "public_leak_guard_head": leak_guard.repository_head,
        "public_repository_artifact_digest": leak_guard.repository_artifact_digest,
        "base_status": final["base_status"],
        "base_plan_digest": final["base_plan_digest"],
        "base_validation_digest": final["base_validation_digest"],
        "checked_removals": final["checked_removal_count"],
        "feasible_removals": final["feasible_removal_count"],
        "infeasible_removals": final["infeasible_removal_count"],
        "unknown_removals": final["unknown_removal_count"],
        "critical_obligation_count": final["critical_obligation_count"],
        "critical_with_structural_reserve": final["critical_obligations_with_structural_reserve"],
        "reserve_status": final["critical_reserve_status"],
        "typed_deficit_categories": dict(sorted(deficit_counts.items())),
        "backfill_need_count": len(final["backfill_needs"]),
        "backfill_request_categories": dict(sorted(request_counts.items())),
        "fresh_process_confirmation": final["fresh_process_confirmation"]["status"],
        "artifact_inventory_digest": final["artifact_inventory_digest"],
        "private_qualification_receipt_digest": final["receipt_digest"],
        "checkpoint_path": final["checkpoint_path"],
        "outcome": final["outcome"],
        "next": final["next"],
        "dr001_changed": False,
        "pool_mutated": False,
    }


def _write_public_outputs(repository_root: Path, final: Record, leak_guard: Any) -> None:
    summary = _public_payload(final, leak_guard)
    summary_path = repository_root / _SUMMARY_PATH
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    if summary_path.is_symlink() or (summary_path.exists() and not summary_path.is_file()):
        raise ValueError("RES-406 public summary path is unsafe")
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )
    deficit_text = json.dumps(summary["typed_deficit_categories"], sort_keys=True)
    critical_count = final["critical_obligation_count"]
    critical_count_text = "NOT_EVALUATED" if critical_count is None else str(critical_count)
    critical_reserve_count = final["critical_obligations_with_structural_reserve"]
    critical_reserve_count_text = (
        "NOT_EVALUATED" if critical_reserve_count is None else str(critical_reserve_count)
    )
    reserve_statement = (
        f"The base selection problem was {final['base_status']}; "
        "critical reserve was not evaluated."
        if final["critical_reserve_status"] == "NOT_EVALUATED"
        else "The existing DR-001 final minimum remains unchanged. Critical reserve is "
        "reported as structural pool capacity against current final obligations."
    )
    lines = (
        "# RES-406 Acceptance Receipt",
        "",
        "```text",
        "MISSION=RES-406",
        f"ENTRY_HEAD={ENTRY_HEAD}",
        f"DYNAMISLM_EXECUTION_BASELINE={DYNAMISLM_EXECUTION_BASELINE}",
        f"RES405_RECEIPT_DIGEST={RES405_RECEIPT_DIGEST}",
        f"PLAN_DIGEST={PLAN_DIGEST}",
        f"POOL_DIGEST={POOL_DIGEST}",
        f"POOL_COUNT={POOL_COUNT}",
        f"SOLVER_PROFILE={PROFILE_NAME}",
        f"SOLVER_PROFILE_VERSION={PROFILE_VERSION}",
        f"BASE_STATUS={final['base_status']}",
        f"BASE_PROBLEM_DIGEST={final['problem_digest']}",
        f"BASE_PLAN_DIGEST={final['base_plan_digest']}",
        f"BASE_VALIDATION_DIGEST={final['base_validation_digest']}",
        f"CHECKED_REMOVALS={final['checked_removal_count']}",
        f"FEASIBLE_REMOVALS={final['feasible_removal_count']}",
        f"INFEASIBLE_REMOVALS={final['infeasible_removal_count']}",
        f"UNKNOWN_REMOVALS={final['unknown_removal_count']}",
        f"CRITICAL_OBLIGATION_COUNT={critical_count_text}",
        f"CRITICAL_WITH_STRUCTURAL_RESERVE={critical_reserve_count_text}",
        f"RESERVE_STATUS={final['critical_reserve_status']}",
        f"TYPED_DEFICIT_CATEGORIES={deficit_text}",
        f"BACKFILL_NEED_COUNT={len(final['backfill_needs'])}",
        f"BACKFILL_REQUEST_COUNT={len(final['backfill_requests'])}",
        f"FRESH_PROCESS_CONFIRMATION={final['fresh_process_confirmation']['status']}",
        f"CHECKPOINT_PATH={final['checkpoint_path']}",
        f"ARTIFACT_INVENTORY_DIGEST={final['artifact_inventory_digest']}",
        f"PRIVATE_QUALIFICATION_RECEIPT_DIGEST={final['receipt_digest']}",
        f"PUBLIC_LEAK_GUARD={leak_guard.status}",
        f"PUBLIC_LEAK_GUARD_HEAD={leak_guard.repository_head}",
        f"PUBLIC_REPOSITORY_ARTIFACT_DIGEST={leak_guard.repository_artifact_digest}",
        f"OUTCOME={final['outcome']}",
        f"NEXT={final['next']}",
        "DR001_CHANGED=NO",
        "POOL_MUTATED=NO",
        "BACKFILL_EXECUTED=NO",
        "```",
        "",
        reserve_statement,
        "Private candidate packets and source text remain in the external store.",
        "",
    )
    receipt_path = repository_root / _PUBLIC_RECEIPT_PATH
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    if receipt_path.is_symlink() or (receipt_path.exists() and not receipt_path.is_file()):
        raise ValueError("RES-406 public receipt path is unsafe")
    receipt_path.write_text("\n".join(lines), encoding="utf-8")


def _qualify(repository_root: Path, production_root: Path) -> int:
    runner_head = _require_execution_tree(repository_root)
    inputs = _load_inputs(repository_root, production_root)
    if inputs.runner_head != runner_head:
        raise ValueError("RES-406 runner head changed during input reconstruction")
    checkpoint_root = _checkpoint_root(inputs.problem)
    base_relative = _path(checkpoint_root, "base-receipt.json")
    base = _base_receipt(inputs, base_relative, reuse=True)
    base_status = _feasibility_status(base)
    removal_records: tuple[Record, ...] = ()
    if base_status is FeasibilityStatus.FEASIBLE:
        gathered = []
        for index, candidate in enumerate(inputs.problem.candidates):
            scenario = _problem_without_candidate(inputs.problem, candidate.candidate_id)
            gathered.append(_removal_receipt(inputs, checkpoint_root, index, candidate, scenario))
        removal_records = tuple(gathered)

    confirmation = _confirm_in_fresh_process(inputs, checkpoint_root, base, removal_records)
    inventory = _checkpoint_inventory(inputs, checkpoint_root, base, removal_records, confirmation)
    final_body = _final_body(
        inputs, checkpoint_root, base, removal_records, confirmation, inventory
    )
    final = _bound(final_body)
    final_relative = _path(checkpoint_root, "final-receipt.json")
    existing_final = _read_record(
        final_relative,
        repository_root=repository_root,
        production_root=production_root,
    )
    if existing_final is None:
        _write_record(
            final_relative,
            final_body,
            repository_root=repository_root,
            production_root=production_root,
        )
    elif existing_final[0] != final:
        raise ValueError("RES-406 existing final receipt differs from canonical reconstruction")

    subprocess.run(
        (
            sys.executable,
            str(repository_root / "scripts/res406_pool_qualification.py"),
            "verify",
            "--production-root",
            str(production_root),
        ),
        check=True,
        cwd=repository_root,
    )
    leak_guard = validate_production_private_material_absent(
        _private_material(inputs.plan, inputs.pool, inputs.historical_inputs, inputs.exclusion),
        repository_root=repository_root,
        candidate_count=POOL_COUNT,
    )
    if leak_guard.status != "PASS":
        raise ValueError("RES-406 production private-material leak guard failed")
    _write_public_outputs(repository_root, final, leak_guard)
    final_leak_guard = validate_production_private_material_absent(
        _private_material(inputs.plan, inputs.pool, inputs.historical_inputs, inputs.exclusion),
        repository_root=repository_root,
        candidate_count=POOL_COUNT,
    )
    if final_leak_guard.status != "PASS":
        raise ValueError("RES-406 post-write production private-material leak scan failed")
    summary = _public_payload(final, leak_guard)
    result = {
        "ENTRY_HEAD": ENTRY_HEAD,
        "RES405_RECEIPT_DIGEST": RES405_RECEIPT_DIGEST,
        "PLAN_DIGEST": PLAN_DIGEST,
        "POOL_DIGEST": POOL_DIGEST,
        "SUPPLY_INVENTORY_DIGEST": SUPPLY_INVENTORY_DIGEST,
        "QUALIFICATION_EXCLUSION_DIGEST": QUALIFICATION_EXCLUSION_DIGEST,
        "POOL_COUNT": POOL_COUNT,
        "SOLVER_PROFILE": PROFILE_NAME,
        "BASE_STATUS": summary["base_status"],
        "BASE_PROBLEM_DIGEST": final["problem_digest"],
        "BASE_PLAN_DIGEST": summary["base_plan_digest"],
        "BASE_VALIDATION_DIGEST": summary["base_validation_digest"],
        "CHECKED_REMOVALS": summary["checked_removals"],
        "FEASIBLE_REMOVALS": summary["feasible_removals"],
        "INFEASIBLE_REMOVALS": summary["infeasible_removals"],
        "UNKNOWN_REMOVALS": summary["unknown_removals"],
        "CRITICAL_OBLIGATION_COUNT": summary["critical_obligation_count"],
        "CRITICAL_WITH_STRUCTURAL_RESERVE": summary["critical_with_structural_reserve"],
        "RESERVE_STATUS": summary["reserve_status"],
        "TYPED_DEFICITS": summary["typed_deficit_categories"],
        "BACKFILL_NEEDS": summary["backfill_need_count"],
        "BACKFILL_REQUESTS": summary["backfill_request_categories"],
        "CHECKPOINT_PATH": checkpoint_root,
        "PRIVATE_QUALIFICATION_RECEIPT_DIGEST": final["receipt_digest"],
        "FRESH_PROCESS_CONFIRMATION": confirmation["status"],
        "PUBLIC_LEAK_GUARD": leak_guard.status,
        "PUBLIC_LEAK_GUARD_HEAD": leak_guard.repository_head,
        "PUBLIC_REPOSITORY_ARTIFACT_DIGEST": leak_guard.repository_artifact_digest,
        "POST_WRITE_PUBLIC_LEAK_GUARD": final_leak_guard.status,
        "POST_WRITE_PUBLIC_LEAK_GUARD_HEAD": final_leak_guard.repository_head,
        "POST_WRITE_PUBLIC_REPOSITORY_ARTIFACT_DIGEST": final_leak_guard.repository_artifact_digest,
        "OUTCOME": final["outcome"],
        "NEXT": final["next"],
    }
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("qualify", "confirm", "verify"))
    parser.add_argument("--production-root", type=Path, default=DEFAULT_PRODUCTION_ROOT)
    parser.add_argument("--expected-problem-digest")
    return parser.parse_args()


def main() -> int:
    args = _arguments()
    repository_root = Path(__file__).resolve().parents[1]
    production_root = args.production_root.resolve()
    if args.action == "qualify":
        return _qualify(repository_root, production_root)
    if args.action == "confirm":
        if not args.expected_problem_digest:
            raise ValueError("fresh confirmation requires the expected exact problem digest")
        return _confirm_action(repository_root, production_root, args.expected_problem_digest)
    return _verify_action(repository_root, production_root)


if __name__ == "__main__":
    raise SystemExit(main())
