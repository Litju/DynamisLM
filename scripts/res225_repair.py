"""Diagnose, prove, and materialize the minimum RES-225 candidate repair."""

from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import sys
import threading
import time
from collections import Counter
from dataclasses import fields, is_dataclass, replace
from pathlib import Path
from typing import Any, cast

from pysat.examples.hitman import Atom, Hitman  # type: ignore[import-untyped]
from pysat.examples.rc2 import RC2  # type: ignore[import-untyped]
from pysat.formula import WCNF  # type: ignore[import-untyped]
from pysat.pb import EncType, PBEnc  # type: ignore[import-untyped]
from pysat.solvers import Solver  # type: ignore[import-untyped]

import dynamislm.benchmark.production_authoring as authoring
from dynamislm.benchmark.constants import CaseOrigin
from dynamislm.benchmark.coverage import COVERAGE_MATRIX
from dynamislm.benchmark.pre_review import candidate_scientific_projection
from dynamislm.benchmark.production import (
    PROSPECTIVE_SPLIT_COUNTS,
    ProductionCandidateCommitmentV1,
    ProductionExactFeasibilityReceiptV2,
    _exact_requirement_constraints,
    _feasibility_clusters,
    _validate_production_mutation_isolation_metadata,
    audit_production_duplicates,
    bind_production_exact_feasibility_receipt,
    validate_production_candidate_packet,
    validate_production_candidate_set,
    validate_production_exact_feasibility_receipt,
    validate_production_isolation,
    validate_production_origin_isolation_metadata,
)
from dynamislm.benchmark.production_authoring import (
    ProductionAuthoringDraftV1,
    ProductionAuthoringInputsV1,
    build_production_authoring_draft,
)
from dynamislm.benchmark.production_exclusions import (
    validate_production_candidate_set_against_qualification_exclusion,
)
from dynamislm.benchmark.production_store import (
    DEFAULT_PRODUCTION_ROOT,
    read_external_production_json,
    replace_external_production_json,
    write_external_production_json,
)
from dynamislm.benchmark.res223_topology import allocation_resilience_summary
from dynamislm.benchmark.res225_repair import (
    CoreModel,
    CoreSolveTimeoutError,
    PreservationAssumption,
    RepairAction,
    RES225RepairCheckpointV1,
    _enum,
    assumptions_for_repair,
    build_core_model,
    build_preservation_registry,
    make_abstract_design,
    run_exact_abstract_oracle,
    semantic_core_action_ids,
    shrink_unsat_core,
    solve_assumptions_limited,
)
from dynamislm.serialization import canonical_hash, canonical_json, from_canonical_json

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_ENTRY_HEAD = "cc8f52f16d26d4a3e5157b1f67d8ca22be6c99f9"
_RES224_BASE_PROOF_DIGEST = "1b52df4167c7f0d2cee266a2cbd7ad719de7180d7eca0f13e371f65db505dfe4"
_RES224_COLOCATION_PROOF_DIGEST = "838282d399dc5cfd6e03e71c93a5866a77c494d03e85d41e10c8c56c386e8309"
_MATERIALIZATION_PATH = "production/diagnostics/RES-225-materialization.private.json"
_PRIVATE_DIR = "production/diagnostics/RES-225"
_CHECKPOINT_PATH = f"{_PRIVATE_DIR}/repair-checkpoint.private.json"
_CHECKPOINT_SCHEMA = "RES-225-REPAIR-CHECKPOINT@1.1.0"
_EQUAL_REPAIR_LIMIT = 32
_MAX_CORE_ITERATIONS = 500
_MAX_EXACT_VARIANTS_PER_REPAIR = 16
_DEFAULT_ORACLE_TIME_BUDGET_SECONDS = 300.0
_WALL_CHECKPOINT_RESERVE_SECONDS = 2.0
_COST2_PRIMARY_CAP = 2
_CoreRecord = dict[str, Any]


class _CapturedExactCallError(Exception):
    pass


class _RepairSearchBlockedError(RuntimeError):
    pass


class _RepairSearchPausedError(RuntimeError):
    pass


def _progress(message: str) -> None:
    print(f"RES225_EVENT {message}", file=sys.stderr, flush=True)


def _emit_iteration(
    *,
    iteration: int,
    elapsed_seconds: float,
    cores_discovered: int,
    last_core_size: int | None,
    last_minimized_core_size: int | None,
    hitting_set_size: int,
    lower_bound: int,
    upper_bound: int | None,
    no_goods: int,
    best_repair_cardinality: int | None,
    oracle_calls: int,
    last_oracle_status: str,
    last_oracle_seconds: float,
    phase: str,
    checkpoint_digest: str,
) -> None:
    gap = _optimality_gap(lower_bound, upper_bound)
    print(
        "RES225_PROGRESS "
        + " ".join(
            (
                f"ITERATION={iteration}",
                f"ELAPSED={elapsed_seconds:.3f}",
                f"CORES_DISCOVERED={cores_discovered}",
                f"LAST_CORE_SIZE={last_core_size if last_core_size is not None else 'NONE'}",
                "LAST_MINIMIZED_CORE_SIZE="
                f"{last_minimized_core_size if last_minimized_core_size is not None else 'NONE'}",
                f"CURRENT_HITTING_SET_SIZE={hitting_set_size}",
                f"LOWER_BOUND={lower_bound}",
                f"UPPER_BOUND={upper_bound if upper_bound is not None else 'NONE'}",
                f"OPTIMALITY_GAP={gap if gap is not None else 'NONE'}",
                "BEST_REPAIR_CARDINALITY="
                f"{best_repair_cardinality if best_repair_cardinality is not None else 'NONE'}",
                f"ORACLE_CALLS={oracle_calls}",
                f"NO_GOODS={no_goods}",
                f"LAST_ORACLE_STATUS={last_oracle_status}",
                f"LAST_ORACLE_SECONDS={last_oracle_seconds:.3f}",
                f"CURRENT_PHASE={phase}",
                f"CHECKPOINT_DIGEST={checkpoint_digest}",
            )
        ),
        file=sys.stderr,
        flush=True,
    )


def _sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _private_write(
    production_root: Path,
    relative_path: str,
    payload: object,
) -> str:
    write_external_production_json(
        payload,
        relative_path,
        repository_root=_REPOSITORY_ROOT,
        production_root=production_root,
    )
    return _sha256((production_root / relative_path).read_bytes())


def _checkpoint_plain(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return {item.name: _checkpoint_plain(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, dict):
        return {str(key): _checkpoint_plain(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_checkpoint_plain(item) for item in value]
    return value


def _checkpoint_bind(payload: dict[str, Any]) -> dict[str, Any]:
    body = _checkpoint_plain(
        {
            key: value
            for key, value in payload.items()
            if key not in {"checkpoint_digest", "CHECKPOINT_DIGEST"}
        }
    )
    digest = canonical_hash(body)
    return {**body, "checkpoint_digest": digest, "CHECKPOINT_DIGEST": digest}


def _validate_checkpoint(
    checkpoint: object,
    *,
    expected_fingerprints: dict[str, str],
) -> dict[str, Any]:
    if not isinstance(checkpoint, dict):
        raise ValueError("RES-225 checkpoint must be a JSON object")
    checkpoint = cast(dict[str, Any], checkpoint)
    body = {
        key: value
        for key, value in checkpoint.items()
        if key not in {"checkpoint_digest", "CHECKPOINT_DIGEST"}
    }
    digest = canonical_hash(body)
    if (
        checkpoint.get("schema") != _CHECKPOINT_SCHEMA
        or checkpoint.get("checkpoint_digest") != digest
        or checkpoint.get("CHECKPOINT_DIGEST") != digest
    ):
        raise ValueError("RES-225 checkpoint schema/digest validation failed")
    if checkpoint.get("fingerprints") != expected_fingerprints:
        raise ValueError("RES-225 checkpoint is stale against the sealed repair inputs")
    for key in (
        "cores",
        "iteration_records",
        "exact_core_evidence",
        "excluded_exact_designs",
        "excluded_repair_families",
        "tested_repairs",
        "equality_records",
    ):
        if not isinstance(checkpoint.get(key), list | tuple):
            raise ValueError(f"RES-225 checkpoint field {key} is malformed")
    if not isinstance(checkpoint.get("iteration"), int) or checkpoint["iteration"] < 0:
        raise ValueError("RES-225 checkpoint iteration is malformed")
    if not isinstance(checkpoint.get("oracle_calls"), int) or checkpoint["oracle_calls"] < 0:
        raise ValueError("RES-225 checkpoint oracle count is malformed")
    if not isinstance(checkpoint.get("oracle_status_counts"), dict):
        raise ValueError("RES-225 checkpoint oracle status counts are malformed")
    if (
        not isinstance(checkpoint.get("elapsed_seconds"), int | float)
        or checkpoint["elapsed_seconds"] < 0
    ):
        raise ValueError("RES-225 checkpoint elapsed time is malformed")
    if not isinstance(checkpoint.get("phase"), str):
        raise ValueError("RES-225 checkpoint phase is malformed")
    required_progress = (
        "ITERATION",
        "ELAPSED",
        "CORES_DISCOVERED",
        "LAST_CORE_SIZE",
        "LAST_MINIMIZED_CORE_SIZE",
        "CURRENT_HITTING_SET_SIZE",
        "LOWER_BOUND",
        "UPPER_BOUND",
        "OPTIMALITY_GAP",
        "BEST_REPAIR_CARDINALITY",
        "ORACLE_CALLS",
        "NO_GOODS",
        "LAST_ORACLE_STATUS",
        "LAST_ORACLE_SECONDS",
        "CURRENT_PHASE",
    )
    if any(key not in checkpoint for key in required_progress):
        raise ValueError("RES-225 checkpoint proof-progress fields are incomplete")
    lower_bound = checkpoint["LOWER_BOUND"]
    upper_bound = checkpoint["UPPER_BOUND"]
    if type(lower_bound) is not int or (upper_bound is not None and type(upper_bound) is not int):
        raise ValueError("RES-225 checkpoint proof bounds are malformed")
    expected_gap = None if upper_bound is None else upper_bound - lower_bound
    if (
        (upper_bound is not None and upper_bound < lower_bound)
        or checkpoint["OPTIMALITY_GAP"] != expected_gap
        or checkpoint["BEST_REPAIR_CARDINALITY"] != upper_bound
        or checkpoint["NO_GOODS"] != checkpoint.get("no_goods")
        or checkpoint["CORES_DISCOVERED"] != len(checkpoint["cores"])
        or checkpoint["ORACLE_CALLS"] != checkpoint.get("oracle_calls")
        or checkpoint["ITERATION"] != checkpoint.get("iteration")
        or checkpoint["CURRENT_PHASE"] != checkpoint.get("phase")
        or checkpoint["CURRENT_HITTING_SET_SIZE"] != checkpoint.get("current_hitting_set_size")
    ):
        raise ValueError("RES-225 checkpoint proof-progress values are inconsistent")
    global_lower_bound = checkpoint.get("GLOBAL_PRIMARY_LOWER_BOUND", lower_bound)
    if type(global_lower_bound) is not int or global_lower_bound < lower_bound:
        raise ValueError("RES-225 checkpoint global primary lower bound is malformed")
    if upper_bound is not None and global_lower_bound > upper_bound:
        raise ValueError("RES-225 checkpoint global lower bound exceeds its incumbent")
    return checkpoint


def _write_checkpoint(
    production_root: Path,
    state: dict[str, Any],
    *,
    expected_file_digest: str | None = None,
) -> tuple[str, str]:
    encoded_state = dict(state)
    encoded_tests = []
    raw_tests = state.get("tested_repairs")
    if not isinstance(raw_tests, list | tuple):
        raise ValueError("RES-225 checkpoint tested-repair state is malformed")
    for raw_test in raw_tests:
        if not isinstance(raw_test, dict):
            raise ValueError("RES-225 checkpoint tested-repair record is malformed")
        item = dict(cast(dict[str, Any], raw_test))
        if "receipt" in item:
            item["receipt_json"] = canonical_json(item.pop("receipt"))
        encoded_tests.append(item)
    encoded_state["tested_repairs"] = tuple(encoded_tests)
    incumbent = encoded_state.get("incumbent")
    if isinstance(incumbent, dict) and "abstract_receipt" in incumbent:
        incumbent = dict(incumbent)
        incumbent["abstract_receipt_json"] = canonical_json(incumbent.pop("abstract_receipt"))
        encoded_state["incumbent"] = incumbent
    payload = _checkpoint_bind({"schema": _CHECKPOINT_SCHEMA, **encoded_state})
    checkpoint = RES225RepairCheckpointV1(_CHECKPOINT_SCHEMA, payload)
    if expected_file_digest is None:
        _relative, file_digest, _size = write_external_production_json(
            checkpoint,
            _CHECKPOINT_PATH,
            repository_root=_REPOSITORY_ROOT,
            production_root=production_root,
        )
    else:
        _relative, file_digest, _size = replace_external_production_json(
            checkpoint,
            _CHECKPOINT_PATH,
            expected_digest=expected_file_digest,
            repository_root=_REPOSITORY_ROOT,
            production_root=production_root,
        )
    return str(payload["CHECKPOINT_DIGEST"]), file_digest


def _read_checkpoint(
    production_root: Path,
    *,
    expected_fingerprints: dict[str, str],
) -> tuple[dict[str, Any], str, str]:
    wrapper, file_digest, _size = read_external_production_json(
        _CHECKPOINT_PATH,
        RES225RepairCheckpointV1,
        repository_root=_REPOSITORY_ROOT,
        production_root=production_root,
    )
    if wrapper.schema != _CHECKPOINT_SCHEMA:
        raise ValueError("RES-225 checkpoint wrapper schema is invalid")
    checkpoint = _validate_checkpoint(
        wrapper.payload,
        expected_fingerprints=expected_fingerprints,
    )
    checkpoint["tested_repairs"] = tuple(
        {
            **dict(item),
            **(
                {
                    "receipt": from_canonical_json(
                        str(item["receipt_json"]), ProductionExactFeasibilityReceiptV2
                    )
                }
                if "receipt_json" in item
                else {}
            ),
        }
        for item in checkpoint["tested_repairs"]
    )
    incumbent = checkpoint.get("incumbent")
    if isinstance(incumbent, dict) and "abstract_receipt_json" in incumbent:
        checkpoint["incumbent"] = {
            **incumbent,
            "abstract_receipt": from_canonical_json(
                str(incumbent["abstract_receipt_json"]), ProductionExactFeasibilityReceiptV2
            ),
        }
    return checkpoint, str(checkpoint["CHECKPOINT_DIGEST"]), file_digest


def _bind_plan(plan: dict[str, object]) -> dict[str, object]:
    return {
        **{key: value for key, value in plan.items() if key != "plan_digest"},
        "plan_digest": canonical_hash(
            {key: value for key, value in plan.items() if key != "plan_digest"}
        ),
    }


def _capture_current_design(
    production_root: Path,
) -> tuple[
    tuple[Any, ...],
    tuple[ProductionCandidateCommitmentV1, ...],
    tuple[tuple[str, str], ...],
]:
    captured: dict[str, Any] = {}
    authoring_runtime: Any = authoring
    original_validate = authoring_runtime.validate_production_exact_feasibility
    original_commitments = authoring_runtime._validate_production_candidate_set_and_commitments
    watched_paths = (
        production_root / "production/authoring_plan/private_inputs.json",
        production_root / "production/diagnostics/RES-223-repair-plan.private.json",
    )
    before = {path: _sha256(path.read_bytes()) for path in watched_paths}

    def capture_packets(packets: tuple[Any, ...], **kwargs: Any) -> Any:
        captured["packets"] = packets
        return original_commitments(packets, **kwargs)

    def capture_exact(
        commitments: tuple[ProductionCandidateCommitmentV1, ...],
        *,
        exact_shingle_colocation_pairs: tuple[tuple[str, str], ...],
        **_kwargs: object,
    ) -> Any:
        captured["commitments"] = commitments
        captured["pairs"] = exact_shingle_colocation_pairs
        raise _CapturedExactCallError

    authoring_runtime._validate_production_candidate_set_and_commitments = capture_packets
    authoring_runtime.validate_production_exact_feasibility = capture_exact
    try:
        build_production_authoring_draft(
            repository_root=_REPOSITORY_ROOT,
            production_root=production_root,
            _diagnostic_only=True,
        )
    except _CapturedExactCallError:
        pass
    finally:
        authoring_runtime._validate_production_candidate_set_and_commitments = original_commitments
        authoring_runtime.validate_production_exact_feasibility = original_validate
    after = {path: _sha256(path.read_bytes()) for path in watched_paths}
    if before != after:
        raise RuntimeError("RES-225 baseline reconstruction changed sealed RES-223 inputs")
    if set(captured) != {"packets", "commitments", "pairs"}:
        raise RuntimeError("RES-225 could not reconstruct the complete current candidate design")
    packets = tuple(captured["packets"])
    commitments = tuple(captured["commitments"])
    pairs = tuple(captured["pairs"])
    if len(packets) != 434 or len(commitments) != 434 or len(pairs) != 81:
        raise RuntimeError(
            "RES-225 baseline reconstruction differs from the certified 434-case input"
        )
    return packets, commitments, pairs


def _solver_core_ids(solver: Any, model: CoreModel) -> tuple[str, ...]:
    raw_core = solver.get_core()
    if not raw_core:
        raise RuntimeError("RES-225 solver returned UNSAT without semantic assumption literals")
    id_by_literal = {
        literal: assumption_id for assumption_id, literal in model.assumption_literals.items()
    }
    release_literals = set(model.release_variables.values())
    unknown = tuple(
        literal
        for literal in raw_core
        if literal not in id_by_literal and literal not in release_literals
    )
    if unknown:
        raise RuntimeError("RES-225 core contains a CNF/PB auxiliary literal")
    return tuple(
        sorted(
            {id_by_literal[literal] for literal in raw_core if literal in id_by_literal},
            key=lambda value: value.encode("utf-8"),
        )
    )


def _core_record(
    *,
    mode: str,
    assumption_ids: tuple[str, ...],
    action_ids: tuple[str, ...],
    source: str,
    model_digest: str,
) -> _CoreRecord:
    return {
        "mode": mode,
        "source": source,
        "assumption_ids": assumption_ids,
        "assumption_core_digest": canonical_hash(assumption_ids),
        "action_ids": action_ids,
        "action_core_digest": canonical_hash(action_ids),
        "semantic_model_digest": model_digest,
    }


def _initial_cores(
    models: dict[str, CoreModel],
    *,
    oracle_timeout_seconds: float,
    completed_records: tuple[_CoreRecord, ...] = (),
    on_core: Any = None,
    time_budget: Any = None,
) -> tuple[list[_CoreRecord], dict[str, Any]]:
    records: list[_CoreRecord] = [dict(item) for item in completed_records]
    completed_modes = {str(item["mode"]) for item in records}
    solvers: dict[str, Any] = {}
    for mode in ("BASE", "COLOCATION"):
        budget = oracle_timeout_seconds if time_budget is None else time_budget()
        deadline = time.monotonic() + min(oracle_timeout_seconds, budget)
        _progress(f"initial-core mode={mode} assumptions={len(models[mode].assumption_literals)}")
        model = models[mode]
        solver = Solver(name="g4", bootstrap_with=model.clauses)
        solvers[mode] = solver
        if mode in completed_modes:
            continue
        assumption_ids = tuple(
            sorted(model.assumption_literals, key=lambda value: value.encode("utf-8"))
        )
        all_literals = tuple(model.assumption_literals[item] for item in assumption_ids)
        if solve_assumptions_limited(solver, all_literals, deadline=deadline):
            raise RuntimeError(f"RES-224 certified {mode} UNSAT, but RES-225 baseline is SAT")
        raw_core = _solver_core_ids(solver, model)
        shrunk = shrink_unsat_core(solver, model, raw_core, deadline=deadline)
        action_ids = semantic_core_action_ids(shrunk, model.assumption_action_ids)
        _progress(
            f"initial-core-minimized mode={mode} "
            f"raw={len(raw_core)} minimized={len(shrunk)} actions={len(action_ids)}"
        )
        records.append(
            {
                **_core_record(
                    mode=mode,
                    assumption_ids=shrunk,
                    action_ids=action_ids,
                    source="ASSUMPTION_SOLVER_AND_DELETION_SHRINK",
                    model_digest=model.model_digest,
                ),
                "raw_assumption_core_size": len(raw_core),
                "minimized_assumption_core_size": len(shrunk),
            }
        )
        if on_core is not None:
            on_core(tuple(records), mode)
    return records, solvers


def _new_hitman(
    cores: list[_CoreRecord],
    weights: dict[str, int],
) -> tuple[Any, tuple[str, ...], int]:
    hitman = _hitman_from_cores(cores, weights)
    selected = _hitman_solution(hitman, weights)
    return hitman, selected, sum(weights[item] for item in selected)


def _hitman_from_cores(
    cores: list[_CoreRecord],
    weights: dict[str, int],
    blocked_sets: tuple[tuple[str, ...], ...] = (),
) -> Any:
    hitman = Hitman(htype="rc2", solver="g3")
    for core in cores:
        action_ids = tuple(core["action_ids"])
        if not action_ids:
            hitman.delete()
            raise RuntimeError("RES-225 discovered an UNSAT core with no authorized repair action")
        hitman.hit(action_ids, weights=weights)
    for blocked in blocked_sets:
        _block_hitman_repair(hitman, tuple(weights), blocked, weights)

    return hitman


def _block_hitman_repair(
    hitman: Any,
    action_ids: tuple[str, ...],
    repair_ids: tuple[str, ...],
    weights: dict[str, int],
) -> None:
    selected = set(repair_ids)
    hitman.add_hard(
        [Atom(action_id, sign=action_id not in selected) for action_id in action_ids],
        weights=weights,
    )


def _run_rc2_limited(rc2: Any, operation: Any, time_budget_seconds: float) -> Any:
    if time_budget_seconds <= 0:
        raise _RepairSearchBlockedError("RC2 time budget must be positive")
    solver = rc2.oracle
    timed_out = threading.Event()

    def interrupt() -> None:
        timed_out.set()
        solver.interrupt()

    timer = threading.Timer(time_budget_seconds, interrupt)
    timer.daemon = True
    timer.start()
    try:
        result = operation()
    finally:
        timer.cancel()
        solver.clear_interrupt()
    if result is None and timed_out.is_set():
        raise _RepairSearchBlockedError("RC2 oracle exceeded its time budget")
    return result


def _hitman_solution(
    hitman: Any,
    weights: dict[str, int],
    time_budget_seconds: float = _DEFAULT_ORACLE_TIME_BUDGET_SECONDS,
) -> tuple[str, ...]:
    selected_result = _run_rc2_limited(hitman.oracle, hitman.get, time_budget_seconds)
    if selected_result is None:
        raise _RepairSearchBlockedError("Hitman found no hitting set")
    selected = tuple(sorted(selected_result, key=lambda value: value.encode("utf-8")))
    return selected


def _new_wcnf(
    action_ids: tuple[str, ...],
    core_sets: tuple[tuple[str, ...], ...],
    weights: dict[str, int],
    blocked_sets: tuple[tuple[str, ...], ...] = (),
) -> tuple[WCNF, dict[str, int]]:
    formula = WCNF()
    variable_by_action = {action_id: index + 1 for index, action_id in enumerate(action_ids)}
    for core in core_sets:
        formula.append([variable_by_action[action_id] for action_id in core])
    for action_id in action_ids:
        formula.append([-variable_by_action[action_id]], weight=weights[action_id])
    for selected in blocked_sets:
        selected_set = set(selected)
        formula.append(
            [
                -variable_by_action[action_id]
                if action_id in selected_set
                else variable_by_action[action_id]
                for action_id in action_ids
            ]
        )
    return formula, variable_by_action


def _rc2_optimum(
    action_ids: tuple[str, ...],
    cores: list[_CoreRecord],
    weights: dict[str, int],
    time_budget_seconds: float = _DEFAULT_ORACLE_TIME_BUDGET_SECONDS,
    blocked_sets: tuple[tuple[str, ...], ...] = (),
) -> tuple[tuple[str, ...], int]:
    core_sets = tuple(tuple(item["action_ids"]) for item in cores)
    formula, variable_by_action = _new_wcnf(action_ids, core_sets, weights, blocked_sets)
    with RC2(formula, solver="g3") as rc2:
        model = _run_rc2_limited(rc2, rc2.compute, time_budget_seconds)
        if model is None:
            raise RuntimeError("RES-225 RC2 found no repair hitting all minimized cores")
        selected = tuple(
            sorted(
                (
                    action_id
                    for action_id, variable in variable_by_action.items()
                    if variable in model
                ),
                key=lambda value: value.encode("utf-8"),
            )
        )
        return selected, int(rc2.cost)


def _enumerate_minimum_hit_sets(
    action_ids: tuple[str, ...],
    cores: list[_CoreRecord],
    weights: dict[str, int],
    *,
    minimum_cost: int,
    limit: int,
    include: tuple[str, ...],
    time_budget_seconds: float = _DEFAULT_ORACLE_TIME_BUDGET_SECONDS,
    time_budget: Any = None,
    blocked_sets: tuple[tuple[str, ...], ...] = (),
) -> tuple[tuple[tuple[str, ...], ...], bool]:
    core_sets = tuple(tuple(item["action_ids"]) for item in cores)
    selected_sets: list[tuple[str, ...]] = []
    seen: set[tuple[str, ...]] = set()
    if include:
        selected_sets.append(include)
        seen.add(include)
    blocked = list(selected_sets)
    complete = True
    while True:
        formula, variable_by_action = _new_wcnf(
            action_ids,
            core_sets,
            weights,
            (*blocked_sets, *blocked),
        )
        with RC2(formula, solver="g3") as rc2:
            budget = time_budget_seconds if time_budget is None else time_budget()
            model = _run_rc2_limited(rc2, rc2.compute, budget)
            if model is None or int(rc2.cost) != minimum_cost:
                break
            selected = tuple(
                sorted(
                    (
                        action_id
                        for action_id, variable in variable_by_action.items()
                        if variable in model
                    ),
                    key=lambda value: value.encode("utf-8"),
                )
            )
        if len(selected_sets) >= limit:
            complete = False
            break
        if selected not in seen:
            selected_sets.append(selected)
            seen.add(selected)
        blocked.append(selected)
    return tuple(selected_sets), complete


def _exact_state(receipt: Any) -> str:
    statuses = (receipt.base_status, receipt.colocation_status)
    if "INFEASIBLE" in statuses:
        return "INFEASIBLE"
    if statuses == ("FEASIBLE", "FEASIBLE") and receipt.status == "FEASIBLE":
        return "FEASIBLE"
    if "UNKNOWN" in statuses or receipt.status == "BLOCKED":
        return "UNKNOWN"
    return "UNKNOWN"


def _independent_witness_digests(records: dict[str, dict[str, object]]) -> dict[str, str]:
    witnesses: dict[str, str] = {}
    for mode in ("BASE", "COLOCATION"):
        record = records.get(mode, {})
        digest = record.get("witness_digest")
        if (
            record.get("result") == "SAT"
            and record.get("witness_independently_validated") is True
            and isinstance(digest, str)
        ):
            witnesses[mode] = digest
    return witnesses


def _exact_repair_variant(
    commitments: tuple[ProductionCandidateCommitmentV1, ...],
    pairs: tuple[tuple[str, str], ...],
    actions: tuple[RepairAction, ...],
    selected_action_ids: tuple[str, ...],
    *,
    target_parent_by_action: dict[str, str],
    candidate_rank_hint: dict[str, int] | None,
    time_budget_seconds: float,
    canonicalize: bool = False,
    independent_validate: bool = False,
    production_root: Path | None = None,
    wall_deadline: float | None = None,
) -> tuple[
    str,
    Any,
    tuple[ProductionCandidateCommitmentV1, ...],
    tuple[tuple[str, str], ...],
    float,
    dict[str, Any] | None,
]:
    abstract_commitments, abstract_pairs = make_abstract_design(
        commitments,
        pairs,
        actions,
        selected_action_ids,
        target_parent_by_action=target_parent_by_action,
    )
    started = time.monotonic()

    def canonical_progress(done: int, total: int, state: str) -> None:
        _progress(f"canonical-self-reduction components={done}/{total} status={state}")

    receipt = run_exact_abstract_oracle(
        abstract_commitments,
        abstract_pairs,
        candidate_rank_hint=candidate_rank_hint,
        time_budget_seconds=time_budget_seconds,
        canonicalize=canonicalize,
        canonical_progress_callback=canonical_progress if canonicalize else None,
    )
    state = _exact_state(receipt)
    fallback_evidence: dict[str, Any] | None = None
    if (state == "UNKNOWN" or (state == "FEASIBLE" and independent_validate)) and not canonicalize:
        initial_state = state
        fallback_budget = time_budget_seconds
        if wall_deadline is not None:
            fallback_budget = min(
                fallback_budget,
                wall_deadline - time.monotonic() - _WALL_CHECKPOINT_RESERVE_SECONDS,
            )
        fallback_statuses, records = _independent_abstract_fallback(
            abstract_commitments,
            abstract_pairs,
            receipt=receipt,
            production_root=production_root,
            time_budget_seconds=max(0.0, fallback_budget),
            wall_deadline=wall_deadline,
        )
        if initial_state == "FEASIBLE":
            # An independent disagreement cannot turn a solver-feasible variant into a no-good.
            state = (
                "FEASIBLE"
                if (
                    fallback_statuses.get("BASE")
                    == fallback_statuses.get("COLOCATION")
                    == "FEASIBLE"
                    and len(_independent_witness_digests(records)) == 2
                )
                else "UNKNOWN"
            )
        else:
            base_status = fallback_statuses.get("BASE", receipt.base_status)
            colocation_status = fallback_statuses.get("COLOCATION", receipt.colocation_status)
            if "INFEASIBLE" in {base_status, colocation_status}:
                state = "INFEASIBLE"
                overall_status = "INFEASIBLE"
            elif (
                base_status == colocation_status == "FEASIBLE"
                and len(_independent_witness_digests(records)) == 2
            ):
                state = "FEASIBLE"
                overall_status = "FEASIBLE"
            else:
                state = "UNKNOWN"
                overall_status = "BLOCKED"
            receipt = bind_production_exact_feasibility_receipt(
                replace(
                    receipt,
                    status=overall_status,
                    base_status=base_status,
                    colocation_status=colocation_status,
                    canonical_self_reduction_status="NOT_RUN",
                    canonical_witness_digest=None,
                    hard_cell_count_by_split=(),
                    adversarial_tag_count_by_split=(),
                    reachable_error_count_by_split=(),
                    protected_critical_error_count_by_split=(),
                    answerable_case_count_by_split=(),
                    c18_refusal_cell_count_by_split=(),
                )
            )
        fallback_evidence = {
            "statuses": fallback_statuses,
            "records": records,
            "witness_digests": _independent_witness_digests(records),
            "digest": canonical_hash((fallback_statuses, records)),
        }
    return (
        state,
        receipt,
        abstract_commitments,
        abstract_pairs,
        time.monotonic() - started,
        fallback_evidence,
    )


def _independent_abstract_fallback(
    commitments: tuple[ProductionCandidateCommitmentV1, ...],
    pairs: tuple[tuple[str, str], ...],
    *,
    receipt: Any,
    production_root: Path | None,
    time_budget_seconds: float,
    wall_deadline: float | None = None,
) -> tuple[dict[str, str], dict[str, dict[str, object]]]:
    from scripts.res224_probes import _run_independent_pb

    if production_root is None:
        return {}, {}
    private_dir = production_root / _PRIVATE_DIR / "unknown-fallback"
    private_dir.mkdir(parents=True, exist_ok=True)
    base_components = _feasibility_clusters(commitments, allow_incompatible_locks=True)
    colocation_components = _feasibility_clusters(
        commitments,
        exact_shingle_colocation_pairs=pairs,
        allow_incompatible_locks=True,
    )
    base_constraints = _exact_requirement_constraints(base_components, base_components)
    colocation_constraints = _exact_requirement_constraints(
        colocation_components,
        colocation_components,
    )
    statuses = {"BASE": "UNKNOWN", "COLOCATION": "UNKNOWN"}
    records: dict[str, dict[str, object]] = {}
    started = time.monotonic()
    for mode, components, constraints in (
        ("BASE", base_components, base_constraints),
        ("COLOCATION", colocation_components, colocation_constraints),
    ):
        remaining = time_budget_seconds - (time.monotonic() - started)
        if wall_deadline is not None:
            remaining = min(
                remaining,
                wall_deadline - time.monotonic() - _WALL_CHECKPOINT_RESERVE_SECONDS,
            )
        if remaining <= 0:
            statuses[mode] = "UNKNOWN"
            records[mode] = {"result": "UNKNOWN", "reason": "TIME_BUDGET_EXHAUSTED"}
            continue
        record, _witness = _run_independent_pb(
            label=f"RES225_INDEPENDENT_{mode}_{canonical_hash(commitments)[:16]}",
            model_kind=mode,
            semantic_model_digest=(
                receipt.base_model_digest if mode == "BASE" else receipt.colocation_model_digest
            ),
            components=components,
            constraints=constraints,
            base_components=base_components,
            colocation_components=colocation_components,
            base_constraints=base_constraints,
            colocation_constraints=colocation_constraints,
            pairs=pairs,
            private_dir=private_dir,
            time_limit_seconds=remaining,
            proof_checker=shutil.which("drat-trim"),
        )
        records[mode] = record
        result = str(record.get("result", "UNKNOWN"))
        if result == "SAT" and record.get("witness_independently_validated") is True:
            statuses[mode] = "FEASIBLE"
        elif result == "UNSAT" and record.get("proof_check_status") == "PASS":
            statuses[mode] = "INFEASIBLE"
        else:
            statuses[mode] = "UNKNOWN"
    return statuses, records


def _exact_variant_nogood_clause(
    model: CoreModel,
    action_ids: tuple[str, ...],
    target_parent_by_action: dict[str, str],
) -> tuple[int, ...]:
    selected = set(action_ids)
    clause = [
        -literal if action_id in selected else literal
        for action_id, literal in sorted(model.release_variables.items())
    ]
    for action_id, target_id in sorted(target_parent_by_action.items()):
        try:
            clause.append(-model.target_variables[action_id][target_id])
        except KeyError as exc:
            raise ValueError("exact no-good names an unauthorized target-parent choice") from exc
    return tuple(sorted(clause, key=lambda literal: (abs(literal), literal < 0)))


def _exact_variant_exclusion_record(
    models: dict[str, CoreModel],
    action_ids: tuple[str, ...],
    target_parent_by_action: dict[str, str],
    receipt: Any,
) -> dict[str, Any]:
    clauses = {
        mode: _exact_variant_nogood_clause(
            model,
            action_ids,
            target_parent_by_action,
        )
        for mode, model in models.items()
    }
    if len(set(clauses.values())) != 1:
        raise RuntimeError("RES-225 exact no-good differs between BASE and COLOCATION models")
    clause = next(iter(clauses.values()))
    return {
        "action_ids": action_ids,
        "target_parent_by_action": dict(target_parent_by_action),
        "blocking_clause": clause,
        "blocking_clause_digest": canonical_hash(clause),
        "base_status": receipt.base_status,
        "colocation_status": receipt.colocation_status,
        "receipt_digest": receipt.receipt_digest,
    }


def _replay_exact_exclusions(
    exclusions: tuple[dict[str, Any], ...] | list[dict[str, Any]],
    models: dict[str, CoreModel],
    solvers: dict[str, Any],
) -> None:
    for exclusion in exclusions:
        action_ids = tuple(exclusion["action_ids"])
        target_map = dict(exclusion["target_parent_by_action"])
        expected = {
            mode: _exact_variant_nogood_clause(model, action_ids, target_map)
            for mode, model in models.items()
        }
        if len(set(expected.values())) != 1:
            raise ValueError("RES-225 exact exclusion differs between candidate models")
        clause = next(iter(expected.values()))
        if tuple(exclusion["blocking_clause"]) != clause or canonical_hash(clause) != exclusion.get(
            "blocking_clause_digest"
        ):
            raise ValueError("RES-225 checkpoint exact exclusion is stale")
        for mode, solver in solvers.items():
            solver.add_clause(list(expected[mode]))


def _append_unique_core(cores: list[_CoreRecord], core: _CoreRecord) -> None:
    action_digest = core["action_core_digest"]
    if any(item["action_core_digest"] == action_digest for item in cores):
        raise RuntimeError("RES-225 core-guided loop rediscovered a core without progress")
    cores.append(core)


def _append_unique_exact_exclusion(
    exclusions: list[dict[str, Any]], exclusion: dict[str, Any]
) -> None:
    digest = exclusion["blocking_clause_digest"]
    if any(item["blocking_clause_digest"] == digest for item in exclusions):
        raise RuntimeError("RES-225 exact-oracle loop rediscovered a blocked design")
    exclusions.append(exclusion)


def _append_unique_repair_family_exclusion(
    exclusions: list[dict[str, Any]],
    action_ids: tuple[str, ...],
    tested_variant_digests: tuple[str, ...],
) -> dict[str, Any]:
    digest = canonical_hash(action_ids)
    if any(item.get("repair_digest") == digest for item in exclusions):
        raise RuntimeError("RES-225 repair family was already exhausted")
    record = {
        "action_ids": action_ids,
        "repair_digest": digest,
        "tested_variant_digests": tested_variant_digests,
        "status": "ALL_EXACT_VARIANTS_PROVEN_INFEASIBLE",
    }
    exclusions.append(record)
    return record


def _enforce_variant_cap(attempts: int, limit: int, on_reached: Any) -> None:
    if attempts >= limit:
        on_reached()


def _repair_profile(
    commitments: tuple[ProductionCandidateCommitmentV1, ...],
    pairs: tuple[tuple[str, str], ...],
) -> dict[str, int]:
    base = _feasibility_clusters(commitments, allow_incompatible_locks=True)
    coloc = _feasibility_clusters(
        commitments,
        exact_shingle_colocation_pairs=pairs,
        allow_incompatible_locks=True,
    )
    counts: list[int] = []
    for components in (base, coloc):
        for row in COVERAGE_MATRIX:
            for family in row.benchmark_families:
                counts.append(
                    sum(
                        any(
                            item.capability_id == row.capability_id
                            and item.benchmark_family == family
                            for item in component.items
                        )
                        for component in components
                    )
                )
    return {
        "base_component_count": len(base),
        "colocation_component_count": len(coloc),
        "minimum_cell_eligible_component_count": min(counts),
        "total_cell_eligible_component_count": sum(counts),
    }


def _repair_primary_cost(repair_ids: tuple[str, ...], actions: dict[str, RepairAction]) -> int:
    return sum(actions[action_id].content_replacement_count for action_id in repair_ids)


def _released_candidate_ids(
    repair_ids: tuple[str, ...], actions: dict[str, RepairAction]
) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                candidate_id
                for action_id in repair_ids
                for candidate_id in actions[action_id].affected_candidate_ids
            },
            key=lambda value: value.encode("utf-8"),
        )
    )


def _origin_counts(
    commitments: tuple[ProductionCandidateCommitmentV1, ...],
) -> tuple[tuple[str, int], ...]:
    return tuple(
        sorted(
            (origin.value, count)
            for origin, count in Counter(item.item.origin_class for item in commitments).items()
        )
    )


def _minimum_hit_solution(
    cores: list[_CoreRecord],
    weights: dict[str, int],
    time_budget_seconds: float = _DEFAULT_ORACLE_TIME_BUDGET_SECONDS,
    blocked_sets: tuple[tuple[str, ...], ...] = (),
) -> tuple[str, ...]:
    if not cores:
        return ()
    hitman = _hitman_from_cores(cores, weights, blocked_sets)
    try:
        return _hitman_solution(hitman, weights, time_budget_seconds)
    finally:
        hitman.delete()


def _minimum_hit_cost(
    cores: list[_CoreRecord],
    weights: dict[str, int],
    time_budget_seconds: float = _DEFAULT_ORACLE_TIME_BUDGET_SECONDS,
) -> int:
    selected = _minimum_hit_solution(cores, weights, time_budget_seconds)
    return sum(weights[action_id] for action_id in selected)


def _optimality_gap(lower_bound: int, upper_bound: int | None) -> int | None:
    if lower_bound < 0 or (upper_bound is not None and upper_bound < lower_bound):
        raise ValueError("RES-225 proof bounds are invalid or crossed")
    return None if upper_bound is None else upper_bound - lower_bound


def _repair_score(
    selected: tuple[str, ...],
    actions_by_id: dict[str, RepairAction],
    profile: dict[str, int],
    target_parent_by_action: dict[str, str],
    before: tuple[ProductionCandidateCommitmentV1, ...],
    after: tuple[ProductionCandidateCommitmentV1, ...],
) -> tuple[object, ...]:
    old_items = {item.candidate_id: item.item for item in before}
    new_items = {item.candidate_id: item.item for item in after}
    origin_changes = sum(
        _enum(old_items[candidate_id].origin_class) != _enum(new_items[candidate_id].origin_class)
        for candidate_id in old_items
    )
    mutation_removals = sum(
        old_items[candidate_id].origin_class is CaseOrigin.ADVERSARIAL_MUTATION
        and new_items[candidate_id].origin_class is not CaseOrigin.ADVERSARIAL_MUTATION
        for candidate_id in old_items
    )
    semantic_reallocations = sum(
        (old_items[candidate_id].capability_id, old_items[candidate_id].benchmark_family)
        != (new_items[candidate_id].capability_id, new_items[candidate_id].benchmark_family)
        for candidate_id in old_items
    )
    parent_changes = sum(
        old_items[candidate_id].parent_candidate_id != new_items[candidate_id].parent_candidate_id
        for candidate_id in old_items
    )
    source_engine_changes = sum(
        (
            old_items[candidate_id].source_document_ids,
            old_items[candidate_id].source_artifact_ids,
            old_items[candidate_id].construct_test_identity_ids,
            old_items[candidate_id].provider_export_ids,
        )
        != (
            new_items[candidate_id].source_document_ids,
            new_items[candidate_id].source_artifact_ids,
            new_items[candidate_id].construct_test_identity_ids,
            new_items[candidate_id].provider_export_ids,
        )
        for candidate_id in old_items
    )
    distribution_deviation = 0
    for field in (
        "origin_class",
        "capability_id",
        "benchmark_family",
        "practitioner_question_class",
        "scoring_profile",
        "difficulty",
    ):
        old_counts = Counter(_enum(getattr(item, field)) for item in old_items.values())
        new_counts = Counter(_enum(getattr(item, field)) for item in new_items.values())
        distribution_deviation += sum(
            abs(old_counts[key] - new_counts[key]) for key in old_counts.keys() | new_counts.keys()
        )
    return (
        origin_changes,
        mutation_removals,
        semantic_reallocations,
        parent_changes,
        source_engine_changes,
        distribution_deviation,
        -profile["minimum_cell_eligible_component_count"],
        -profile["total_cell_eligible_component_count"],
        -profile["colocation_component_count"],
        -profile["base_component_count"],
        tuple(sorted(target_parent_by_action.items())),
        selected,
    )


def _core_hit_set_is_sat(
    solver: Any,
    model: CoreModel,
    selected_action_ids: tuple[str, ...],
    *,
    time_budget_seconds: float,
) -> tuple[str, tuple[str, ...], dict[str, str], dict[str, int], int, int, float]:
    started = time.monotonic()
    deadline = started + time_budget_seconds
    assumptions = assumptions_for_repair(model, selected_action_ids)
    try:
        is_sat = solve_assumptions_limited(solver, assumptions, deadline=deadline)
    except CoreSolveTimeoutError:
        return "UNKNOWN", (), {}, {}, 0, 0, time.monotonic() - started
    if is_sat:
        selected = set(selected_action_ids)
        selected_literals = {literal for literal in solver.get_model() if literal > 0}
        target_map: dict[str, str] = {}
        for action_id, target_by_id in sorted(model.target_variables.items()):
            if action_id not in selected:
                continue
            chosen = tuple(
                target_id
                for target_id, literal in target_by_id.items()
                if literal in selected_literals
            )
            if len(chosen) != 1:
                raise RuntimeError("RES-225 SAT witness has an invalid mutation-parent assignment")
            target_map[action_id] = chosen[0]
        candidate_rank_hint = {
            candidate_id: next(
                rank
                for rank, literal in enumerate(model.assignment_variables[index])
                if literal in selected_literals
            )
            for index, candidate_id in enumerate(model.candidate_ids)
        }
        return "SAT", (), target_map, candidate_rank_hint, 0, 0, time.monotonic() - started
    ids = _solver_core_ids(solver, model)
    selected_releases = tuple(
        model.release_variables[item]
        for item in sorted(selected_action_ids, key=lambda value: value.encode("utf-8"))
    )
    try:
        shrunk = shrink_unsat_core(
            solver,
            model,
            ids,
            forced_literals=selected_releases,
            deadline=deadline,
        )
    except CoreSolveTimeoutError:
        return "UNKNOWN", (), {}, {}, len(ids), 0, time.monotonic() - started
    return "UNSAT", shrunk, {}, {}, len(ids), len(shrunk), time.monotonic() - started


def _candidate_model_fallback(
    model: CoreModel,
    selected_action_ids: tuple[str, ...],
    *,
    extra_clauses: tuple[tuple[int, ...], ...],
    time_budget_seconds: float,
) -> tuple[str, tuple[str, ...], dict[str, str], dict[str, int], int, int, float]:
    try:
        solver = Solver(name="m22", bootstrap_with=(*model.clauses, *extra_clauses))
    except Exception:
        return "UNKNOWN", (), {}, {}, 0, 0, 0.0
    with solver:
        return _core_hit_set_is_sat(
            solver,
            model,
            selected_action_ids,
            time_budget_seconds=time_budget_seconds,
        )


def _release_cost_cap_clauses(
    model: CoreModel,
    content_replacement_costs: dict[str, int],
    maximum_cost: int,
) -> tuple[tuple[tuple[int, ...], ...], int]:
    if type(maximum_cost) is not int or maximum_cost < 0:
        raise ValueError("RES-225 primary cost cap must be a non-negative integer")
    if set(content_replacement_costs) != set(model.release_variables):
        raise ValueError("RES-225 primary cost weights differ from authorized release actions")
    if any(type(cost) is not int or cost < 0 for cost in content_replacement_costs.values()):
        raise ValueError("RES-225 primary cost weights must be non-negative integers")
    terms = tuple(
        (model.release_variables[action_id], cost)
        for action_id, cost in sorted(content_replacement_costs.items())
        if cost
    )
    total_cost = sum(cost for _literal, cost in terms)
    top_id = max(
        model.max_variable,
        max((abs(literal) for clause in model.clauses for literal in clause), default=0),
    )
    if maximum_cost >= total_cost:
        return (), top_id
    if not terms:
        return ((),), top_id
    encoded = PBEnc.leq(
        lits=[literal for literal, _cost in terms],
        weights=[cost for _literal, cost in terms],
        bound=maximum_cost,
        top_id=top_id,
        encoding=EncType.bdd,
    )
    return tuple(tuple(clause) for clause in encoded.clauses), max(top_id, encoded.nv)


def _decode_candidate_sat_repair(
    model: CoreModel,
    solver_model: tuple[int, ...] | list[int],
) -> tuple[tuple[str, ...], dict[str, str], dict[str, int]]:
    true_literals = {literal for literal in solver_model if literal > 0}
    action_ids = tuple(
        sorted(
            (
                action_id
                for action_id, literal in model.release_variables.items()
                if literal in true_literals
            ),
            key=lambda value: value.encode("utf-8"),
        )
    )
    selected = set(action_ids)
    target_parent_by_action: dict[str, str] = {}
    for action_id, target_by_id in sorted(model.target_variables.items()):
        if action_id not in selected:
            continue
        targets = tuple(
            target_id for target_id, literal in target_by_id.items() if literal in true_literals
        )
        if len(targets) != 1:
            raise RuntimeError("RES-225 SAT witness has an invalid mutation-parent assignment")
        target_parent_by_action[action_id] = targets[0]
    if len(model.candidate_ids) != len(model.assignment_variables):
        raise RuntimeError("RES-225 SAT witness has an incomplete candidate allocation model")
    rank_hint: dict[str, int] = {}
    for candidate_id, variables in zip(
        model.candidate_ids, model.assignment_variables, strict=True
    ):
        selected_ranks = tuple(
            rank for rank, literal in enumerate(variables) if literal in true_literals
        )
        if len(selected_ranks) != 1:
            raise RuntimeError("RES-225 SAT witness has an invalid split assignment")
        rank_hint[candidate_id] = selected_ranks[0]
    return action_ids, target_parent_by_action, rank_hint


def _candidate_model_dimacs(clauses: tuple[tuple[int, ...], ...], maximum_variable: int) -> bytes:
    normalized = tuple(
        sorted(
            (
                tuple(sorted(clause, key=lambda literal: (abs(literal), literal < 0)))
                for clause in clauses
            ),
            key=lambda clause: (len(clause), clause),
        )
    )
    max_var = max(
        maximum_variable,
        max((abs(literal) for clause in normalized for literal in clause), default=0),
    )
    body = "".join(
        " ".join(map(str, clause)) + (" " if clause else "") + "0\n" for clause in normalized
    )
    return f"p cnf {max_var} {len(normalized)}\n{body}".encode("ascii")


def _apply_primary_cost_closure_result(
    checkpoint: dict[str, Any], closure: dict[str, Any], *, primary_cost_cap: int
) -> dict[str, Any]:
    status = closure.get("status")
    core_lower_bound = int(checkpoint["LOWER_BOUND"])
    global_lower_bound = max(
        core_lower_bound,
        int(checkpoint.get("GLOBAL_PRIMARY_LOWER_BOUND", core_lower_bound)),
    )
    upper_bound = checkpoint["UPPER_BOUND"]
    if status == "UNSAT":
        if closure.get("proof_check_status") != "PASS":
            raise ValueError(
                "RES-225 cannot promote the global lower bound without a checked proof"
            )
        global_lower_bound = max(global_lower_bound, primary_cost_cap + 1)
        if upper_bound is not None and upper_bound < global_lower_bound:
            raise ValueError("RES-225 bounded UNSAT proof conflicts with the incumbent")
    elif status == "SAT":
        if (
            closure.get("repair_cost") != primary_cost_cap
            or closure.get("abstract_base_status") != "FEASIBLE"
            or closure.get("abstract_colocation_status") != "FEASIBLE"
            or closure.get("independent_witness_validation") != "PASS"
        ):
            raise ValueError("RES-225 SAT closure lacks a validated exact witness")
        if global_lower_bound > primary_cost_cap:
            raise ValueError("RES-225 bounded witness conflicts with the global lower bound")
        global_lower_bound = max(global_lower_bound, primary_cost_cap)
        upper_bound = primary_cost_cap
    elif status != "UNKNOWN":
        raise ValueError("RES-225 bounded closure status is invalid")

    updated = dict(checkpoint)
    updated["GLOBAL_PRIMARY_LOWER_BOUND"] = global_lower_bound
    updated["global_primary_lower_bound"] = global_lower_bound
    updated["UPPER_BOUND"] = upper_bound
    updated["upper_bound"] = upper_bound
    updated["OPTIMALITY_GAP"] = _optimality_gap(core_lower_bound, upper_bound)
    updated["optimality_gap"] = updated["OPTIMALITY_GAP"]
    updated["BEST_REPAIR_CARDINALITY"] = upper_bound
    updated["best_repair_cardinality"] = upper_bound
    return updated


def _apply_cost2_closure_result(
    checkpoint: dict[str, Any], closure: dict[str, Any]
) -> dict[str, Any]:
    return _apply_primary_cost_closure_result(
        checkpoint, closure, primary_cost_cap=_COST2_PRIMARY_CAP
    )


def _make_materialization_plan(
    *,
    production_root: Path,
    selected_action_ids: tuple[str, ...],
    actions: tuple[RepairAction, ...],
    assumptions: tuple[PreservationAssumption, ...],
    target_parent_by_action: dict[str, str],
    abstract_receipt: Any,
    selected_repair_digest: str,
    minimum_evidence_digest: str,
    iteration: int,
) -> dict[str, object]:
    _require_abstract_feasible(abstract_receipt)
    inputs, _file_digest, _size = read_external_production_json(
        "production/authoring_plan/private_inputs.json",
        ProductionAuthoringInputsV1,
        repository_root=_REPOSITORY_ROOT,
        production_root=production_root,
    )
    seeds = dict(inputs.scenario_seeds)
    action_by_id = {item.action_id: item for item in actions}
    records: list[dict[str, object]] = []
    for action_id in selected_action_ids:
        action = action_by_id[action_id]
        record: dict[str, object] = {
            "action_id": action_id,
            "action_family": action.action_family,
            "anchor_candidate_id": action.anchor_candidate_id,
            "affected_candidate_ids": action.affected_candidate_ids,
            "placeholder_digest": canonical_hash(action.placeholders),
            "authority_eligibility_digest": action.authority_eligibility_digest,
            "content_replacement_count": action.content_replacement_count,
        }
        if action.action_family == "EXPERT_SEMANTIC_CONTENT_REPLACEMENT":
            original_seed = seeds[action.anchor_candidate_id]
            record.update(
                {
                    "original_seed_sha256": hashlib.sha256(
                        original_seed.encode("ascii")
                    ).hexdigest(),
                    "replacement_seed": canonical_hash(
                        (
                            "RES-225-REPLACEMENT-SCENARIO@1",
                            action_id,
                            action.anchor_candidate_id,
                            original_seed,
                        )
                    ),
                    "new_author_batch_id": action.new_author_batch_id,
                    "new_protocol_template_id": action.new_protocol_template_id,
                    "new_isolation_cluster_id": action.new_isolation_cluster_id,
                }
            )
        elif action.action_family == "MUTATION_BRANCH_REPARENT":
            target_parent = target_parent_by_action[action_id]
            record.update(
                {
                    "old_parent_candidate_id": action.old_parent_candidate_id,
                    "old_mutation_lineage_id": action.old_mutation_lineage_id,
                    "target_parent_candidate_id": target_parent,
                    "new_mutation_lineage_id": dict(action.target_lineage_id_by_parent)[
                        target_parent
                    ],
                    "mutation_operator_id": action.mutation_operator_id,
                }
            )
        else:
            raise ValueError("RES-225 selected repair contains an unauthorized action family")
        records.append(record)
    plan: dict[str, object] = {
        "schema": "RES-225-MATERIALIZATION@1.0.0",
        "status": "AUTHORIZED",
        "iteration": iteration,
        "entry_head": _ENTRY_HEAD,
        "selected_action_ids": selected_action_ids,
        "selected_repair_digest": selected_repair_digest,
        "minimum_repair_evidence_digest": minimum_evidence_digest,
        "preservation_registry_digest": canonical_hash(assumptions),
        "abstract_base_status": abstract_receipt.base_status,
        "abstract_colocation_status": abstract_receipt.colocation_status,
        "abstract_canonical_witness_digest": abstract_receipt.canonical_witness_digest,
        "actions": tuple(records),
        "feasibility_membership_persisted": "NO",
        "final_split_allocation_performed": "NO",
        "production_store_promoted": "NO",
    }
    return _bind_plan(plan)


def _require_abstract_feasible(receipt: Any) -> None:
    if (
        receipt.base_status != "FEASIBLE"
        or receipt.colocation_status != "FEASIBLE"
        or receipt.status != "FEASIBLE"
        or receipt.canonical_self_reduction_status != "PASS"
        or receipt.canonical_witness_digest is None
    ):
        raise _RepairSearchBlockedError(
            "RES-225 materialization requires an exact canonical abstract witness"
        )


def _require_abstract_search_feasible(receipt: Any) -> None:
    if (
        receipt.base_status != "FEASIBLE"
        or receipt.colocation_status != "FEASIBLE"
        or receipt.status != "FEASIBLE"
        or receipt.canonical_self_reduction_status != "NOT_RUN"
        or receipt.canonical_witness_digest is not None
    ):
        raise _RepairSearchBlockedError("RES-225 search requires feasibility-only exact evidence")


def _write_authorized_materialization(
    production_root: Path,
    plan: dict[str, object],
) -> str:
    if (
        plan.get("abstract_base_status") != "FEASIBLE"
        or plan.get("abstract_colocation_status") != "FEASIBLE"
        or not plan.get("abstract_canonical_witness_digest")
    ):
        raise _RepairSearchBlockedError("RES-225 materialization plan lacks abstract exact proofs")
    return _private_write(production_root, _MATERIALIZATION_PATH, plan)


def _record_resilience(
    commitments: tuple[ProductionCandidateCommitmentV1, ...],
    pairs: tuple[tuple[str, str], ...],
) -> dict[str, Any]:
    base_components = _feasibility_clusters(commitments, allow_incompatible_locks=True)
    coloc_components = _feasibility_clusters(
        commitments,
        exact_shingle_colocation_pairs=pairs,
        allow_incompatible_locks=True,
    )
    components_by_mode = {"BASE": base_components, "COLOCATION": coloc_components}
    results: dict[str, Any] = {}
    for mode, components in components_by_mode.items():
        exact_model = build_core_model(
            commitments,
            pairs,
            (),
            (),
            mode=mode,
        )
        solver = Solver(name="g4", bootstrap_with=exact_model.clauses)
        candidate_index = {
            item.candidate_id: index
            for index, entry in enumerate(
                sorted(commitments, key=lambda value: value.candidate_id.encode("utf-8"))
            )
            for item in (entry.item,)
        }
        counts: list[tuple[str, str, int]] = []
        for row in COVERAGE_MATRIX:
            for family in row.benchmark_families:
                eligible = tuple(
                    component
                    for component in components
                    if any(
                        item.capability_id == row.capability_id and item.benchmark_family == family
                        for item in component.items
                    )
                )
                for rank, (split, _target) in enumerate(PROSPECTIVE_SPLIT_COUNTS):
                    forceable = 0
                    for component in eligible:
                        representative = component.items[0].candidate_id
                        variable = exact_model.assignment_variables[
                            candidate_index[representative]
                        ][rank]
                        forceable += solver.solve(assumptions=[variable])
                    counts.append((f"{row.capability_id}:{family}", split.value, forceable))
        results[mode] = {
            **allocation_resilience_summary(tuple(counts)),
            "forceable_counts_digest": canonical_hash(tuple(counts)),
            "obligation_count": len(counts),
        }
        solver.delete()
    results["diagnostic_digest"] = canonical_hash(results)
    return results


def _exact_final_sat_crosscheck(
    draft: ProductionAuthoringDraftV1,
    production_root: Path,
) -> dict[str, dict[str, object]]:
    from scripts.res224_probes import _run_independent_pb

    private_dir = production_root / _PRIVATE_DIR
    private_dir.mkdir(parents=True, exist_ok=True)
    base_components = _feasibility_clusters(draft.commitments, allow_incompatible_locks=True)
    colocation_components = _feasibility_clusters(
        draft.commitments,
        exact_shingle_colocation_pairs=draft.duplication_audit.exact_shingle_colocation_pairs,
        allow_incompatible_locks=True,
    )
    base_constraints = _exact_requirement_constraints(base_components, base_components)
    colocation_constraints = _exact_requirement_constraints(
        colocation_components,
        colocation_components,
    )
    checker = shutil.which("drat-trim")
    results: dict[str, dict[str, object]] = {}
    for mode, components, constraints, model_digest in (
        ("BASE", base_components, base_constraints, draft.feasibility_receipt.base_model_digest),
        (
            "COLOCATION",
            colocation_components,
            colocation_constraints,
            draft.feasibility_receipt.colocation_model_digest,
        ),
    ):
        record, _witness = _run_independent_pb(
            label=f"RES225_FINAL_{mode}",
            model_kind=mode,
            semantic_model_digest=model_digest,
            components=components,
            constraints=constraints,
            base_components=base_components,
            colocation_components=colocation_components,
            base_constraints=base_constraints,
            colocation_constraints=colocation_constraints,
            pairs=draft.duplication_audit.exact_shingle_colocation_pairs,
            private_dir=private_dir,
            time_limit_seconds=1800.0,
            proof_checker=checker,
        )
        results[mode] = record
    return results


def _final_authority_checks(
    draft: ProductionAuthoringDraftV1,
    exclusion: Any,
) -> dict[str, object]:
    authoring_runtime: Any = authoring
    resolver = authoring_runtime.build_res115_source_artifact_resolver()
    for packet in draft.packets:
        validate_production_candidate_packet(packet, source_resolver=resolver)
        validate_production_origin_isolation_metadata(packet)
    validate_production_candidate_set(draft.packets, source_resolver=resolver)
    validate_production_isolation(
        draft.commitments,
        defer_split_lock_conflicts=True,
        enforce_public_capacity=False,
    )
    _validate_production_mutation_isolation_metadata(draft.packets)
    validate_production_candidate_set_against_qualification_exclusion(
        draft.packets,
        exclusion,
        source_resolver=resolver,
    )
    duplication = audit_production_duplicates(draft.packets)
    if duplication != draft.duplication_audit:
        raise RuntimeError("RES-225 final duplication audit changed after materialization")
    if (
        duplication.candidate_count != 434
        or duplication.exact_question_duplicate_pairs
        or duplication.normalized_question_duplicate_pairs
        or duplication.blocking_fuzzy_overlap_pairs
        or duplication.unrelated_blocking_overlaps
    ):
        raise RuntimeError("RES-225 final candidate contamination audit failed")
    return {
        "candidate_validation": "PASS",
        "source_jats_authority": "PASS",
        "res71_authority": "PASS",
        "qualification_exclusion": "PASS",
        "origin_scoped_isolation": "PASS",
        "mutation_topology": "PASS",
        "res128_duplication_audit": "PASS",
        "retained_exact_shingle_graph_digest": canonical_hash(
            duplication.exact_shingle_colocation_pairs
        ),
        "retained_exact_shingle_pair_count": len(duplication.exact_shingle_colocation_pairs),
    }


def _verify_preserved_content(
    before_packets: tuple[Any, ...],
    after_packets: tuple[Any, ...],
    selected_candidate_ids: set[str],
) -> tuple[int, str]:
    from dynamislm.benchmark.pre_review import candidate_scientific_projection

    before = {packet.candidate_id: packet for packet in before_packets}
    after = {packet.candidate_id: packet for packet in after_packets}
    if set(before) != set(after) or len(after) != 434:
        raise RuntimeError("RES-225 materialization changed candidate identity or count")
    changed_ids = set()
    for candidate_id in sorted(before, key=lambda value: value.encode("utf-8")):
        old_digest = canonical_hash(candidate_scientific_projection(before[candidate_id]))
        new_digest = canonical_hash(candidate_scientific_projection(after[candidate_id]))
        if old_digest != new_digest:
            changed_ids.add(candidate_id)
    if changed_ids != selected_candidate_ids:
        raise RuntimeError("RES-225 materialization changed content outside selected replacements")
    return len(changed_ids), canonical_hash(tuple(sorted(changed_ids)))


def _write_acceptance_private_artifact(
    production_root: Path,
    payload: dict[str, object],
) -> str:
    return _private_write(
        production_root,
        f"{_PRIVATE_DIR}/RES-225-acceptance-evidence.private.json",
        payload,
    )


def _cost2_closure_record(
    *,
    status: str,
    proof_check_status: str,
    base_status: str,
    colocation_status: str,
    repairs_tested_total: int,
    exact_variant_nogoods: int,
    best_repair_digest: str,
    primary_cost_cap: int = _COST2_PRIMARY_CAP,
    lower_bound_before: int = _COST2_PRIMARY_CAP,
    **details: Any,
) -> dict[str, Any]:
    return {
        "schema": f"RES-225-COST{primary_cost_cap}-CLOSURE@1.0.0",
        "status": status,
        "terminal": bool(details.pop("terminal", False)),
        "primary_cost_cap": primary_cost_cap,
        "candidate_sat_solver": "MiniSat 2.2 via PySAT",
        "pb_encoding": "BDD",
        "independent_proof_solver": "Glucose 4 via PySAT",
        "lower_bound_before": lower_bound_before,
        "proof_check_status": proof_check_status,
        "abstract_base_status": base_status,
        "abstract_colocation_status": colocation_status,
        "repairs_tested_total": repairs_tested_total,
        "exact_variant_nogoods": exact_variant_nogoods,
        "best_repair_digest": best_repair_digest,
        **details,
    }


def _cost2_closure_receipt(
    checkpoint: dict[str, Any],
    closure: dict[str, Any],
    *,
    checkpoint_digest: str | None = None,
    primary_cost_cap: int = _COST2_PRIMARY_CAP,
) -> dict[str, object]:
    status = str(closure["status"])
    proven = (
        status == "SAT"
        and checkpoint.get("GLOBAL_PRIMARY_LOWER_BOUND") == primary_cost_cap
        and checkpoint.get("UPPER_BOUND") == primary_cost_cap
        and closure.get("independent_witness_validation") == "PASS"
    )
    result: dict[str, object] = {
        f"COST{primary_cost_cap}_CLOSURE_STATUS": status,
        "PROOF_CHECK": ("PASS" if closure.get("proof_check_status") == "PASS" else "NOT_RUN"),
        "UPPER_BOUND_AFTER": (
            checkpoint["UPPER_BOUND"] if checkpoint.get("UPPER_BOUND") is not None else "NONE"
        ),
        "MINIMUM_REPAIR_PROVEN": "YES" if proven else "NO",
        "MINIMUM_REPAIR_CARDINALITY": primary_cost_cap if proven else "NONE",
        f"COST{primary_cost_cap}_REPAIRS_TESTED": closure.get("repairs_tested_total", 0),
        "EXACT_VARIANT_NOGOODS": closure.get("exact_variant_nogoods", 0),
        "BEST_REPAIR_DIGEST": closure.get("best_repair_digest", "NONE"),
        "ABSTRACT_BASE_STATUS": closure.get("abstract_base_status", "NOT_RUN"),
        "ABSTRACT_COLOCATION_STATUS": closure.get("abstract_colocation_status", "NOT_RUN"),
        "CHECKPOINT_DIGEST": checkpoint_digest or checkpoint.get("CHECKPOINT_DIGEST", "NONE"),
        "QA": closure.get("qa_status", "NOT_RUN"),
        "NEXT": {
            "SAT": "SELECT_MINIMUM_REPAIR",
            "UNSAT": f"RESUME_COST{primary_cost_cap + 1}_SEARCH",
            "UNKNOWN": "RESUME_IHS_SEARCH",
        }[status],
    }
    lower_after = checkpoint.get("GLOBAL_PRIMARY_LOWER_BOUND", checkpoint["LOWER_BOUND"])
    if primary_cost_cap == _COST2_PRIMARY_CAP:
        result["LOWER_BOUND_BEFORE"] = closure.get("lower_bound_before", primary_cost_cap)
        result["LOWER_BOUND_AFTER"] = lower_after
        result["COST2_CLOSURE_STATUS"] = status
    else:
        result["GLOBAL_PRIMARY_LOWER_BOUND_BEFORE"] = closure.get(
            "lower_bound_before", primary_cost_cap
        )
        result["GLOBAL_PRIMARY_LOWER_BOUND_AFTER"] = lower_after
    return result


def _run_primary_cost_closure(
    production_root: Path,
    *,
    expected_checkpoint_digest: str,
    primary_cost_cap: int,
    max_wall_seconds: float,
    oracle_timeout_seconds: float = _DEFAULT_ORACLE_TIME_BUDGET_SECONDS,
    proof_checker: str | Path | None = None,
) -> dict[str, object]:
    if production_root.resolve().is_relative_to(_REPOSITORY_ROOT.resolve()):
        raise ValueError("RES-225 private artifacts must remain outside Git")
    if primary_cost_cap < 2:
        raise ValueError("RES-225 primary cost closure cap must be at least 2")
    if max_wall_seconds <= 0 or oracle_timeout_seconds <= 0:
        raise ValueError("RES-225 bounded closure budgets must be positive")
    if not expected_checkpoint_digest.startswith("sha256:"):
        raise ValueError("RES-225 bounded closure requires an expected checkpoint digest")

    from scripts.res224_probes import _write_private

    started = time.monotonic()
    wall_deadline = started + max_wall_seconds
    cost_label = f"COST{primary_cost_cap}"
    closure_key = f"cost{primary_cost_cap}_closure"
    _progress(f"cost{primary_cost_cap}-closure reconstructing-sealed-baseline")
    _before_packets, commitments, pairs = _capture_current_design(production_root)
    inputs, input_digest, _input_size = read_external_production_json(
        "production/authoring_plan/private_inputs.json",
        ProductionAuthoringInputsV1,
        repository_root=_REPOSITORY_ROOT,
        production_root=production_root,
    )
    assumptions, actions = build_preservation_registry(
        commitments,
        pairs,
        mutation_lineages=inputs.mutation_lineages,
    )
    models = {
        mode: build_core_model(commitments, pairs, assumptions, actions, mode=mode)
        for mode in ("BASE", "COLOCATION")
    }
    fingerprints = {
        "entry_head": _ENTRY_HEAD,
        "private_input_digest": input_digest,
        "preservation_registry_digest": canonical_hash(assumptions),
        "action_registry_digest": canonical_hash(actions),
        "base_model_digest": models["BASE"].model_digest,
        "colocation_model_digest": models["COLOCATION"].model_digest,
        "candidate_count": "434",
        "retained_shingle_pair_count": str(len(pairs)),
    }
    saved, _old_checkpoint_body_digest, checkpoint_file_digest = _read_checkpoint(
        production_root,
        expected_fingerprints=fingerprints,
    )
    if saved["CHECKPOINT_DIGEST"] != expected_checkpoint_digest:
        raise ValueError("RES-225 checkpoint differs from the authorized starting digest")
    prior_closure = saved.get(closure_key)
    if (
        primary_cost_cap == _COST2_PRIMARY_CAP
        and prior_closure is None
        and (
            saved["CORES_DISCOVERED"] != 1455
            or saved["LOWER_BOUND"] != 2
            or saved["UPPER_BOUND"] is not None
            or saved["ORACLE_CALLS"] != 1454
        )
    ):
        raise ValueError("RES-225 cost-2 closure starting proof state differs from authority")
    if primary_cost_cap == _COST2_PRIMARY_CAP:
        if isinstance(prior_closure, dict) and prior_closure.get("terminal") is True:
            return _cost2_closure_receipt(saved, prior_closure)
        starting_global_lower_bound = _COST2_PRIMARY_CAP
    else:
        certified_cost2 = saved.get("cost2_closure")
        if not (
            isinstance(certified_cost2, dict)
            and certified_cost2.get("schema") == "RES-225-COST2-CLOSURE@1.0.0"
            and certified_cost2.get("status") == "UNSAT"
            and certified_cost2.get("terminal") is True
            and certified_cost2.get("primary_cost_cap") == _COST2_PRIMARY_CAP
            and certified_cost2.get("proof_check_status") == "PASS"
        ):
            raise ValueError("RES-225 cost-3 closure requires the certified cost-2 UNSAT closure")
        if isinstance(prior_closure, dict) and prior_closure.get("terminal") is True:
            if prior_closure.get("status") in {"SAT", "UNSAT"}:
                return _cost2_closure_receipt(
                    saved, prior_closure, primary_cost_cap=primary_cost_cap
                )
        starting_global_lower_bound = primary_cost_cap
    if saved.get("GLOBAL_PRIMARY_LOWER_BOUND", saved["LOWER_BOUND"]) != starting_global_lower_bound:
        raise ValueError("RES-225 bounded closure checkpoint has a different global lower bound")
    if saved["UPPER_BOUND"] is not None:
        raise ValueError("RES-225 bounded closure checkpoint unexpectedly has an incumbent")

    action_by_id = {action.action_id: action for action in actions}
    costs = {action.action_id: action.content_replacement_count for action in actions}
    candidate_model = models["COLOCATION"]
    cap_clauses, maximum_variable = _release_cost_cap_clauses(
        candidate_model, costs, primary_cost_cap
    )
    exclusions: list[dict[str, Any]] = [dict(item) for item in saved["excluded_exact_designs"]]
    exact_variant_clauses: list[tuple[int, ...]] = []
    for exclusion in exclusions:
        expected_clause = _exact_variant_nogood_clause(
            candidate_model,
            tuple(exclusion["action_ids"]),
            dict(exclusion["target_parent_by_action"]),
        )
        clause = tuple(exclusion["blocking_clause"])
        if clause != expected_clause or canonical_hash(clause) != exclusion.get(
            "blocking_clause_digest"
        ):
            raise ValueError("RES-225 checkpoint exact-variant no-good is stale")
        exact_variant_clauses.append(clause)

    closure_dir = production_root / _PRIVATE_DIR / f"cost{primary_cost_cap}-closure"
    closure_dir.mkdir(parents=True, exist_ok=True)
    cnf_path = closure_dir / f"candidate-cost{primary_cost_cap}.cnf"
    proof_path = closure_dir / f"candidate-cost{primary_cost_cap}.drup"
    checker = (
        str(Path(proof_checker).resolve())
        if proof_checker is not None
        else shutil.which("drat-trim")
    )
    total_tested = int(
        prior_closure.get("repairs_tested_total", 0) if isinstance(prior_closure, dict) else 0
    )
    run_tested = 0
    status_counts: Counter[str] = Counter(saved.get("oracle_status_counts", {}))
    oracle_calls = int(saved["oracle_calls"])
    last_oracle_status = str(saved.get("last_oracle_status", "UNKNOWN"))
    last_oracle_seconds = float(saved.get("last_oracle_seconds", 0.0))
    elapsed_before = float(saved["elapsed_seconds"])
    last_base_status = "NOT_RUN"
    last_colocation_status = "NOT_RUN"
    best_repair_digest = "NONE"
    proof_check_status = "NOT_RUN"
    last_cost_model_digest = "NONE"
    last_cnf_digest = "NONE"
    pending_repair_digest = "NONE"

    def make_closure_record(**kwargs: Any) -> dict[str, Any]:
        return _cost2_closure_record(
            primary_cost_cap=primary_cost_cap,
            lower_bound_before=primary_cost_cap,
            **kwargs,
        )

    def checkpoint_closure(
        closure: dict[str, Any],
        *,
        phase: str,
        action_ids: tuple[str, ...] = (),
        target_map: dict[str, str] | None = None,
        repair_cost: int | None = None,
        final: bool = False,
    ) -> str:
        nonlocal saved, checkpoint_file_digest
        nonlocal oracle_calls, last_oracle_status, last_oracle_seconds
        state = dict(saved)
        if final:
            state = _apply_primary_cost_closure_result(
                state, closure, primary_cost_cap=primary_cost_cap
            )
        state.update(
            {
                closure_key: closure,
                "oracle_calls": oracle_calls,
                "ORACLE_CALLS": oracle_calls,
                "oracle_status_counts": dict(status_counts),
                "last_oracle_status": last_oracle_status,
                "LAST_ORACLE_STATUS": last_oracle_status,
                "last_oracle_seconds": last_oracle_seconds,
                "LAST_ORACLE_SECONDS": last_oracle_seconds,
                "phase": phase,
                "CURRENT_PHASE": phase,
                "elapsed_seconds": elapsed_before + time.monotonic() - started,
                "ELAPSED": elapsed_before + time.monotonic() - started,
                "no_goods": len(exclusions) + len(saved["excluded_repair_families"]),
                "NO_GOODS": len(exclusions) + len(saved["excluded_repair_families"]),
                "excluded_exact_designs": tuple(exclusions),
                "CURRENT_REPAIR_ACTION_IDS": action_ids,
                "current_repair_action_ids": action_ids,
                "current_target_parent_by_action": target_map or {},
                "current_hitting_set_cost": repair_cost,
            }
        )
        digest, checkpoint_file_digest = _write_checkpoint(
            production_root,
            state,
            expected_file_digest=checkpoint_file_digest,
        )
        checked_state, checked_digest, _checked_file_digest = _read_checkpoint(
            production_root,
            expected_fingerprints=fingerprints,
        )
        if checked_digest != digest or checked_state.get(closure_key) != closure:
            raise RuntimeError("RES-225 bounded closure checkpoint read-back failed")
        saved = dict(state)
        saved["CHECKPOINT_DIGEST"] = digest
        saved["checkpoint_digest"] = digest
        _progress(f"cost{primary_cost_cap}-closure checkpoint phase={phase} digest={digest}")
        return digest

    if (
        primary_cost_cap == 3
        and isinstance(prior_closure, dict)
        and prior_closure.get("status") == "UNKNOWN"
        and prior_closure.get("reason") == "UNVERIFIED_UNSAT:CHECKER_UNAVAILABLE"
        and checker is not None
    ):
        formula_clauses = (*candidate_model.clauses, *cap_clauses, *exact_variant_clauses)
        cnf_bytes = _candidate_model_dimacs(formula_clauses, maximum_variable)
        cost_model_digest = canonical_hash(
            {
                "candidate_model_digest": candidate_model.model_digest,
                "primary_cost_cap": primary_cost_cap,
                "content_replacement_costs": tuple(sorted(costs.items())),
                "cost_cap_clauses_digest": canonical_hash(cap_clauses),
                "exact_variant_no_good_digests": tuple(
                    canonical_hash(clause) for clause in exact_variant_clauses
                ),
                "cnf_digest": _sha256(cnf_bytes),
            }
        )
        if (
            prior_closure.get("cnf_digest") != _sha256(cnf_bytes)
            or prior_closure.get("cost_model_digest") != cost_model_digest
            or prior_closure.get("proof_path") != str(proof_path)
            or not cnf_path.is_file()
            or cnf_path.read_bytes() != cnf_bytes
            or not proof_path.is_file()
            or prior_closure.get("proof_digest") != _sha256(proof_path.read_bytes())
        ):
            raise ValueError("RES-225 cost-3 proof artifacts differ from the checkpoint")
        check_budget = min(
            oracle_timeout_seconds,
            wall_deadline - time.monotonic() - _WALL_CHECKPOINT_RESERVE_SECONDS,
        )
        checked_returncode: int | None = None
        checker_log = ""
        if check_budget > 0:
            try:
                recheck_result = subprocess.run(
                    [checker, str(cnf_path), str(proof_path)],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=check_budget,
                )
                checked_returncode = recheck_result.returncode
                checker_log = recheck_result.stdout + recheck_result.stderr
            except subprocess.TimeoutExpired:
                checker_log = "TIMEOUT"
        oracle_calls += 1
        status_counts[
            f"{cost_label}_PROOF_CHECKER_PASS"
            if checked_returncode == 0
            else f"{cost_label}_PROOF_CHECKER_FAIL"
            if checked_returncode is not None
            else f"{cost_label}_PROOF_CHECKER_UNKNOWN"
        ] += 1
        closure = dict(prior_closure)
        closure.update(
            {
                "status": "UNSAT" if checked_returncode == 0 else "UNKNOWN",
                "terminal": checked_returncode == 0,
                "proof_check_status": (
                    "PASS"
                    if checked_returncode == 0
                    else "FAIL"
                    if checked_returncode is not None
                    else "NOT_RUN"
                ),
                "proof_checker_digest": _sha256(Path(checker).read_bytes()),
                "proof_checker_returncode": checked_returncode,
                "proof_checker_log_digest": _sha256(checker_log.encode("utf-8")),
                "reason": (
                    "DRAT_PROOF_CHECKED"
                    if checked_returncode == 0
                    else "PROOF_CHECKER_FAILED"
                    if checked_returncode is not None
                    else "PROOF_CHECKER_TIME_LIMIT"
                ),
                "qa_status": "PASS" if checked_returncode == 0 else "CHECKPOINT_PASS",
            }
        )
        checkpoint_digest = checkpoint_closure(
            closure,
            phase=f"{cost_label}_CLOSURE_{closure['status']}",
            final=True,
        )
        return _cost2_closure_receipt(
            saved,
            closure,
            checkpoint_digest=checkpoint_digest,
            primary_cost_cap=primary_cost_cap,
        )

    while True:
        remaining = wall_deadline - time.monotonic()
        if remaining <= _WALL_CHECKPOINT_RESERVE_SECONDS:
            proof_check_status = "NOT_RUN"
            closure = make_closure_record(
                status="UNKNOWN",
                proof_check_status=proof_check_status,
                base_status=last_base_status,
                colocation_status=last_colocation_status,
                repairs_tested_total=total_tested + run_tested,
                exact_variant_nogoods=len(exclusions),
                best_repair_digest=best_repair_digest,
                pending_repair_digest=pending_repair_digest,
                cost_model_digest=last_cost_model_digest,
                cnf_digest=last_cnf_digest,
                reason="GLOBAL_WALL_TIME_LIMIT",
                qa_status="CHECKPOINT_PASS",
            )
            checkpoint_digest = checkpoint_closure(
                closure,
                phase=f"{cost_label}_CLOSURE_UNKNOWN",
                final=True,
            )
            return _cost2_closure_receipt(
                saved,
                closure,
                checkpoint_digest=checkpoint_digest,
                primary_cost_cap=primary_cost_cap,
            )

        formula_clauses = (
            *candidate_model.clauses,
            *cap_clauses,
            *exact_variant_clauses,
        )
        cnf_bytes = _candidate_model_dimacs(formula_clauses, maximum_variable)
        last_cnf_digest = _sha256(cnf_bytes)
        last_cost_model_digest = canonical_hash(
            {
                "candidate_model_digest": candidate_model.model_digest,
                "primary_cost_cap": primary_cost_cap,
                "content_replacement_costs": tuple(sorted(costs.items())),
                "cost_cap_clauses_digest": canonical_hash(cap_clauses),
                "exact_variant_no_good_digests": tuple(
                    canonical_hash(clause) for clause in exact_variant_clauses
                ),
                "cnf_digest": last_cnf_digest,
            }
        )
        _write_private(cnf_path, cnf_bytes)
        solver_budget = min(oracle_timeout_seconds, remaining - _WALL_CHECKPOINT_RESERVE_SECONDS)
        started_solve = time.monotonic()
        with Solver(
            name="m22",
            bootstrap_with=formula_clauses,
            use_timer=True,
        ) as solver:
            timer = threading.Timer(solver_budget, solver.interrupt)
            timer.daemon = True
            timer.start()
            try:
                solve_result = solver.solve_limited(expect_interrupt=True)
                witness_model = tuple(solver.get_model() or ()) if solve_result is True else ()
            finally:
                timer.cancel()
                solver.clear_interrupt()
        solve_seconds = time.monotonic() - started_solve
        oracle_calls += 1
        last_oracle_seconds = solve_seconds
        if solve_result is True:
            last_oracle_status = f"{cost_label}_SAT"
            status_counts[f"{cost_label}_SAT"] += 1
        elif solve_result is False:
            last_oracle_status = f"{cost_label}_UNSAT"
            status_counts[f"{cost_label}_UNSAT"] += 1
        else:
            last_oracle_status = f"{cost_label}_UNKNOWN"
            status_counts[f"{cost_label}_UNKNOWN"] += 1

        if solve_result is False:
            proof_digest = "NONE"
            proof_check_status = "NOT_RUN"
            proof_detail = "INDEPENDENT_PROOF_NOT_RUN"
            proof: list[str] | None = None
            proof_result: bool | None = None
            proof_budget = wall_deadline - time.monotonic() - _WALL_CHECKPOINT_RESERVE_SECONDS
            if proof_budget > 0:
                with Solver(
                    name="g4",
                    bootstrap_with=formula_clauses,
                    with_proof=True,
                    use_timer=True,
                ) as proof_solver:
                    proof_timer = threading.Timer(
                        min(oracle_timeout_seconds, proof_budget), proof_solver.interrupt
                    )
                    proof_timer.daemon = True
                    proof_timer.start()
                    try:
                        proof_result = proof_solver.solve_limited(expect_interrupt=True)
                        if proof_result is False:
                            proof = proof_solver.get_proof()
                    finally:
                        proof_timer.cancel()
                        proof_solver.clear_interrupt()
                oracle_calls += 1
                status_counts[
                    f"{cost_label}_PROOF_G4_UNSAT"
                    if proof_result is False
                    else f"{cost_label}_PROOF_G4_SAT"
                    if proof_result is True
                    else f"{cost_label}_PROOF_G4_UNKNOWN"
                ] += 1
                if proof_result is True:
                    proof_detail = "INDEPENDENT_SOLVER_DISAGREEMENT"
            if proof is not None:
                proof_bytes = ("\n".join(proof) + ("\n" if proof else "")).encode("ascii")
                _write_private(proof_path, proof_bytes)
                proof_digest = _sha256(proof_bytes)
                if checker is not None:
                    checker_remaining = (
                        wall_deadline - time.monotonic() - _WALL_CHECKPOINT_RESERVE_SECONDS
                    )
                    if checker_remaining > 0:
                        try:
                            checked = subprocess.run(
                                [checker, str(cnf_path), str(proof_path)],
                                check=False,
                                capture_output=True,
                                timeout=checker_remaining,
                            )
                            proof_detail = "PASS" if checked.returncode == 0 else "FAIL"
                            proof_check_status = proof_detail
                        except subprocess.TimeoutExpired:
                            proof_detail = "TIMEOUT"
                else:
                    proof_detail = "CHECKER_UNAVAILABLE"
            elif proof_result is False:
                proof_detail = "MISSING_OR_INCOMPLETE_PROOF"
            if proof_check_status == "PASS":
                terminal_status = "UNSAT"
                reason = "DRAT_PROOF_CHECKED"
            else:
                terminal_status = "UNKNOWN"
                reason = f"UNVERIFIED_UNSAT:{proof_detail}"
            closure = make_closure_record(
                status=terminal_status,
                proof_check_status=proof_check_status,
                base_status=last_base_status,
                colocation_status=last_colocation_status,
                repairs_tested_total=total_tested + run_tested,
                exact_variant_nogoods=len(exclusions),
                best_repair_digest=best_repair_digest,
                cost_model_digest=last_cost_model_digest,
                cnf_digest=last_cnf_digest,
                proof_digest=proof_digest,
                proof_path=str(proof_path),
                proof_checker_digest=(
                    _sha256(Path(checker).read_bytes()) if checker is not None else "NONE"
                ),
                reason=reason,
                terminal=(terminal_status != "UNKNOWN" or primary_cost_cap == _COST2_PRIMARY_CAP),
                qa_status="PASS" if terminal_status == "UNSAT" else "CHECKPOINT_PASS",
            )
            checkpoint_digest = checkpoint_closure(
                closure,
                phase=f"{cost_label}_CLOSURE_{terminal_status}",
                final=True,
            )
            return _cost2_closure_receipt(
                saved,
                closure,
                checkpoint_digest=checkpoint_digest,
                primary_cost_cap=primary_cost_cap,
            )

        if solve_result is None:
            closure = make_closure_record(
                status="UNKNOWN",
                proof_check_status="NOT_RUN",
                base_status=last_base_status,
                colocation_status=last_colocation_status,
                repairs_tested_total=total_tested + run_tested,
                exact_variant_nogoods=len(exclusions),
                best_repair_digest=best_repair_digest,
                cost_model_digest=last_cost_model_digest,
                cnf_digest=last_cnf_digest,
                reason="SAT_PB_TIME_LIMIT",
                terminal=(primary_cost_cap == _COST2_PRIMARY_CAP),
                qa_status="CHECKPOINT_PASS",
            )
            checkpoint_digest = checkpoint_closure(
                closure,
                phase=f"{cost_label}_CLOSURE_UNKNOWN",
                final=True,
            )
            return _cost2_closure_receipt(
                saved,
                closure,
                checkpoint_digest=checkpoint_digest,
                primary_cost_cap=primary_cost_cap,
            )

        repair_ids, target_map, rank_hint = _decode_candidate_sat_repair(
            candidate_model, witness_model
        )
        repair_cost = _repair_primary_cost(repair_ids, action_by_id)
        if repair_cost > primary_cost_cap:
            raise RuntimeError("RES-225 bounded SAT witness exceeds the global primary cost cap")
        repair_variant_digest = canonical_hash(
            {"action_ids": repair_ids, "target_parent_by_action": target_map}
        )
        pending_repair_digest = repair_variant_digest
        closure = make_closure_record(
            status="UNKNOWN",
            proof_check_status="NOT_RUN",
            base_status=last_base_status,
            colocation_status=last_colocation_status,
            repairs_tested_total=total_tested + run_tested,
            exact_variant_nogoods=len(exclusions),
            best_repair_digest=best_repair_digest,
            pending_repair_digest=pending_repair_digest,
            cost_model_digest=last_cost_model_digest,
            cnf_digest=last_cnf_digest,
            reason="EXACT_VALIDATION_PENDING",
        )
        checkpoint_closure(
            closure,
            phase=f"{cost_label}_EXACT_VALIDATION_PENDING",
            action_ids=repair_ids,
            target_map=target_map,
            repair_cost=repair_cost,
        )

        exact_budget = min(oracle_timeout_seconds, wall_deadline - time.monotonic())
        if exact_budget <= 0:
            continue
        exact_state, receipt, abstract_commitments, abstract_pairs, exact_seconds, fallback = (
            _exact_repair_variant(
                commitments,
                pairs,
                actions,
                repair_ids,
                target_parent_by_action=target_map,
                candidate_rank_hint=rank_hint,
                time_budget_seconds=exact_budget,
                canonicalize=False,
                independent_validate=True,
                production_root=production_root,
                wall_deadline=wall_deadline,
            )
        )
        run_tested += 1
        total_tested += 1
        oracle_calls += 1 + (len(fallback["records"]) if fallback is not None else 0)
        status_counts[f"{cost_label}_EXACT_{exact_state}"] += 1
        if fallback is not None:
            for validation in fallback["records"].values():
                status_counts[f"{cost_label}_RES224_{validation.get('result', 'UNKNOWN')}"] += 1
        last_oracle_status = f"{cost_label}_EXACT_{exact_state}"
        last_oracle_seconds = exact_seconds
        last_base_status = str(receipt.base_status)
        last_colocation_status = str(receipt.colocation_status)
        pending_repair_digest = "NONE"
        variant_record: dict[str, Any] = {
            "action_ids": repair_ids,
            "target_parent_by_action": target_map,
            "repair_variant_digest": repair_variant_digest,
            "minimum_content_replacement_cost": repair_cost,
            "receipt_digest": receipt.receipt_digest,
            "fallback_evidence": fallback,
        }

        if exact_state == "INFEASIBLE":
            exclusion = _exact_variant_exclusion_record(
                models,
                repair_ids,
                target_map,
                receipt,
            )
            _append_unique_exact_exclusion(exclusions, exclusion)
            exact_variant_clauses.append(tuple(exclusion["blocking_clause"]))
            variant_record["status"] = "EXACT_INFEASIBLE_VARIANT"
            saved["tested_repairs"] = (*tuple(saved["tested_repairs"]), variant_record)
            saved["exact_core_evidence"] = (
                *tuple(saved["exact_core_evidence"]),
                {"schema": "RES-225-EXACT-DESIGN-NO-GOOD@1", **exclusion},
            )
            closure = make_closure_record(
                status="UNKNOWN",
                proof_check_status="NOT_RUN",
                base_status=last_base_status,
                colocation_status=last_colocation_status,
                repairs_tested_total=total_tested,
                exact_variant_nogoods=len(exclusions),
                best_repair_digest=best_repair_digest,
                cost_model_digest=last_cost_model_digest,
                cnf_digest=last_cnf_digest,
                reason="EXACT_VARIANT_EXCLUDED",
            )
            checkpoint_closure(
                closure,
                phase=f"{cost_label}_EXACT_VARIANT_EXCLUDED",
                action_ids=repair_ids,
                target_map=target_map,
                repair_cost=repair_cost,
            )
            continue

        if exact_state == "FEASIBLE":
            _require_abstract_search_feasible(receipt)
            witness_digests = (
                _independent_witness_digests(fallback["records"]) if fallback is not None else {}
            )
            if set(witness_digests) != {"BASE", "COLOCATION"}:
                exact_state = "UNKNOWN"
            elif repair_cost != primary_cost_cap:
                raise RuntimeError(
                    "RES-225 bounded closure found a feasible repair below its proven bound"
                )
            else:
                assert fallback is not None
                best_repair_digest = repair_variant_digest
                profile = _repair_profile(abstract_commitments, abstract_pairs)
                released_ids = _released_candidate_ids(repair_ids, action_by_id)
                incumbent = {
                    "action_ids": repair_ids,
                    "target_parent_by_action": target_map,
                    "cardinality": repair_cost,
                    "repair_digest": canonical_hash(repair_ids),
                    "released_candidate_ids": released_ids,
                    "origin_counts_before": _origin_counts(commitments),
                    "origin_counts_after": _origin_counts(abstract_commitments),
                    "abstract_receipt": receipt,
                    "abstract_witness_digest": None,
                    "independent_witness_digests": witness_digests,
                    "independent_validation_records": fallback["records"],
                    "validation_evidence_digest": fallback["digest"],
                    "secondary_profile": profile,
                }
                variant_record.update(
                    {
                        "status": "FEASIBLE",
                        "receipt": receipt,
                        "released_candidate_ids": released_ids,
                        "secondary_profile": profile,
                    }
                )
                saved["tested_repairs"] = (*tuple(saved["tested_repairs"]), variant_record)
                saved["incumbent"] = incumbent
                saved["best_repair_cardinality"] = repair_cost
                saved["BEST_REPAIR_CARDINALITY"] = repair_cost
                closure = make_closure_record(
                    status="SAT",
                    proof_check_status="PASS",
                    base_status=last_base_status,
                    colocation_status=last_colocation_status,
                    repairs_tested_total=total_tested,
                    exact_variant_nogoods=len(exclusions),
                    best_repair_digest=best_repair_digest,
                    repair_cost=repair_cost,
                    independent_witness_validation="PASS",
                    independent_witness_digests=witness_digests,
                    cost_model_digest=last_cost_model_digest,
                    cnf_digest=last_cnf_digest,
                    reason="EXACT_BASE_AND_COLOCATION_WITNESSES_VALIDATED",
                    terminal=True,
                    qa_status="PASS",
                )
                checkpoint_digest = checkpoint_closure(
                    closure,
                    phase=f"{cost_label}_CLOSURE_SAT",
                    action_ids=repair_ids,
                    target_map=target_map,
                    repair_cost=repair_cost,
                    final=True,
                )
                return _cost2_closure_receipt(
                    saved,
                    closure,
                    checkpoint_digest=checkpoint_digest,
                    primary_cost_cap=primary_cost_cap,
                )

        variant_record["status"] = "UNKNOWN_VARIANT"
        variant_record["receipt"] = receipt
        saved["tested_repairs"] = (*tuple(saved["tested_repairs"]), variant_record)
        closure = make_closure_record(
            status="UNKNOWN",
            proof_check_status="NOT_RUN",
            base_status=last_base_status,
            colocation_status=last_colocation_status,
            repairs_tested_total=total_tested,
            exact_variant_nogoods=len(exclusions),
            best_repair_digest=best_repair_digest,
            cost_model_digest=last_cost_model_digest,
            cnf_digest=last_cnf_digest,
            reason="EXACT_VALIDATION_UNKNOWN",
            terminal=(primary_cost_cap == _COST2_PRIMARY_CAP),
            qa_status="CHECKPOINT_PASS",
        )
        checkpoint_digest = checkpoint_closure(
            closure,
            phase=f"{cost_label}_CLOSURE_UNKNOWN",
            action_ids=repair_ids,
            target_map=target_map,
            repair_cost=repair_cost,
            final=True,
        )
        return _cost2_closure_receipt(
            saved,
            closure,
            checkpoint_digest=checkpoint_digest,
            primary_cost_cap=primary_cost_cap,
        )


def run_cost2_closure(
    production_root: Path,
    *,
    expected_checkpoint_digest: str,
    max_wall_seconds: float,
    oracle_timeout_seconds: float = _DEFAULT_ORACLE_TIME_BUDGET_SECONDS,
    proof_checker: str | Path | None = None,
) -> dict[str, object]:
    return _run_primary_cost_closure(
        production_root,
        expected_checkpoint_digest=expected_checkpoint_digest,
        primary_cost_cap=_COST2_PRIMARY_CAP,
        max_wall_seconds=max_wall_seconds,
        oracle_timeout_seconds=oracle_timeout_seconds,
        proof_checker=proof_checker,
    )


def run_cost3_closure(
    production_root: Path,
    *,
    expected_checkpoint_digest: str,
    max_wall_seconds: float,
    oracle_timeout_seconds: float = _DEFAULT_ORACLE_TIME_BUDGET_SECONDS,
    proof_checker: str | Path | None = None,
) -> dict[str, object]:
    return _run_primary_cost_closure(
        production_root,
        expected_checkpoint_digest=expected_checkpoint_digest,
        primary_cost_cap=3,
        max_wall_seconds=max_wall_seconds,
        oracle_timeout_seconds=oracle_timeout_seconds,
        proof_checker=proof_checker,
    )


def run(
    production_root: Path,
    *,
    resume: bool = False,
    oracle_timeout_seconds: float = _DEFAULT_ORACLE_TIME_BUDGET_SECONDS,
    max_iterations: int = _MAX_CORE_ITERATIONS,
    max_exact_variants_per_repair: int = _MAX_EXACT_VARIANTS_PER_REPAIR,
    max_wall_seconds: float | None = None,
    materialize: bool = False,
) -> tuple[dict[str, object], int]:
    if production_root.resolve().is_relative_to(_REPOSITORY_ROOT.resolve()):
        raise ValueError("RES-225 private artifacts must remain outside Git")
    if (
        oracle_timeout_seconds <= 0
        or max_iterations <= 0
        or max_exact_variants_per_repair <= 0
        or (max_wall_seconds is not None and max_wall_seconds <= 0)
    ):
        raise ValueError("RES-225 search budgets must be positive")
    checkpoint_path = production_root / _CHECKPOINT_PATH
    if checkpoint_path.exists() and not resume:
        raise _RepairSearchBlockedError("RES-225 checkpoint exists; resume it explicitly")
    if resume and not checkpoint_path.is_file():
        raise ValueError("RES-225 --resume requested but no private checkpoint exists")

    run_started = time.monotonic()
    wall_deadline = None if max_wall_seconds is None else run_started + max_wall_seconds
    _progress("reconstructing-sealed-baseline")
    before_packets, commitments, pairs = _capture_current_design(production_root)
    _progress(f"baseline-ready candidates={len(commitments)} retained-edges={len(pairs)}")
    authoring_inputs, input_digest, _input_size = read_external_production_json(
        "production/authoring_plan/private_inputs.json",
        ProductionAuthoringInputsV1,
        repository_root=_REPOSITORY_ROOT,
        production_root=production_root,
    )
    assumptions, actions = build_preservation_registry(
        commitments,
        pairs,
        mutation_lineages=authoring_inputs.mutation_lineages,
    )
    assumptions_digest = canonical_hash(assumptions)
    actions_digest = canonical_hash(actions)
    models = {
        mode: build_core_model(commitments, pairs, assumptions, actions, mode=mode)
        for mode in ("BASE", "COLOCATION")
    }
    fingerprints = {
        "entry_head": _ENTRY_HEAD,
        "private_input_digest": input_digest,
        "preservation_registry_digest": assumptions_digest,
        "action_registry_digest": actions_digest,
        "base_model_digest": models["BASE"].model_digest,
        "colocation_model_digest": models["COLOCATION"].model_digest,
        "candidate_count": "434",
        "retained_shingle_pair_count": str(len(pairs)),
    }
    _progress(
        "semantic-models-ready "
        + " ".join(f"{mode}-clauses={len(model.clauses)}" for mode, model in models.items())
    )

    action_ids = tuple(action.action_id for action in actions)
    action_by_id = {item.action_id: item for item in actions}
    weights = {action.action_id: action.content_replacement_count for action in actions}
    cores: list[_CoreRecord] = []
    iteration_records: list[dict[str, Any]] = []
    exact_core_evidence: list[dict[str, Any]] = []
    excluded_exact_designs: list[dict[str, Any]] = []
    excluded_repair_families: list[dict[str, Any]] = []
    tested_repairs: list[dict[str, Any]] = []
    equality_records: list[dict[str, Any]] = []
    variant_counts: dict[str, int] = {}
    oracle_status_counts: Counter[str] = Counter()
    oracle_calls = 0
    iteration = 0
    initial_core_count = 0
    elapsed_before = 0.0
    last_core_size: int | None = None
    last_minimized_core_size: int | None = None
    last_oracle_status = "UNKNOWN"
    last_oracle_seconds = 0.0
    current_phase = "INITIAL_CORE_EXTRACTION"
    incumbent: dict[str, Any] | None = None
    primary_proof: dict[str, Any] | None = None
    lower_bound = 0
    global_primary_lower_bound = 0
    upper_bound: int | None = None
    current_hitting_set_size = 0
    current_hitting_set_actions: tuple[str, ...] = ()
    checkpoint_digest = "NONE"
    checkpoint_file_digest: str | None = None
    cost2_closure: dict[str, Any] | None = None

    if resume:
        saved, _checkpoint_body_digest, checkpoint_file_digest = _read_checkpoint(
            production_root,
            expected_fingerprints=fingerprints,
        )
        cores = [dict(item) for item in saved["cores"]]
        iteration_records = [dict(item) for item in saved["iteration_records"]]
        exact_core_evidence = [dict(item) for item in saved["exact_core_evidence"]]
        excluded_exact_designs = [dict(item) for item in saved["excluded_exact_designs"]]
        excluded_repair_families = [dict(item) for item in saved["excluded_repair_families"]]
        tested_repairs = [dict(item) for item in saved["tested_repairs"]]
        equality_records = [dict(item) for item in saved["equality_records"]]
        variant_counts = dict(saved.get("variant_counts", {}))
        oracle_status_counts.update(saved.get("oracle_status_counts", {}))
        oracle_calls = int(saved["oracle_calls"])
        iteration = int(saved["iteration"])
        initial_core_count = int(saved.get("initial_core_count", 0))
        elapsed_before = float(saved["elapsed_seconds"])
        lower_bound = int(saved["LOWER_BOUND"])
        global_primary_lower_bound = int(saved.get("GLOBAL_PRIMARY_LOWER_BOUND", lower_bound))
        saved_upper = saved["UPPER_BOUND"]
        upper_bound = None if saved_upper is None else int(saved_upper)
        last_core_size = saved.get("last_core_size")
        last_minimized_core_size = saved.get("last_minimized_core_size")
        last_oracle_status = str(saved.get("last_oracle_status", "UNKNOWN"))
        last_oracle_seconds = float(saved.get("last_oracle_seconds", 0.0))
        incumbent_value = saved.get("incumbent")
        if incumbent_value is not None:
            if not isinstance(incumbent_value, dict):
                raise ValueError("RES-225 checkpoint incumbent is malformed")
            incumbent = dict(incumbent_value)
        primary_value = saved.get("primary_proof")
        if primary_value is not None:
            if not isinstance(primary_value, dict):
                raise ValueError("RES-225 checkpoint primary proof is malformed")
            primary_proof = dict(primary_value)
        closure_value = saved.get("cost2_closure")
        if closure_value is not None:
            if not isinstance(closure_value, dict):
                raise ValueError("RES-225 checkpoint cost-2 closure is malformed")
            cost2_closure = dict(closure_value)
        checkpoint_digest = str(saved["CHECKPOINT_DIGEST"])
        if (
            saved.get("preservation_registry_digest") != assumptions_digest
            or saved.get("action_registry_digest") != actions_digest
            or saved.get("model_digests")
            != {mode: model.model_digest for mode, model in models.items()}
        ):
            raise ValueError("RES-225 checkpoint registry/model state differs from its authority")
        if (incumbent is None) != (upper_bound is None) or (
            incumbent is not None and int(incumbent["cardinality"]) != upper_bound
        ):
            raise ValueError("RES-225 checkpoint upper bound differs from its incumbent")
        _progress(
            "RESUME_RESTORED "
            f"CHECKPOINT_DIGEST={checkpoint_digest} "
            f"CORES_DISCOVERED={len(cores)} LOWER_BOUND={lower_bound} "
            f"UPPER_BOUND={upper_bound if upper_bound is not None else 'NONE'} "
            f"NO_GOODS={len(excluded_exact_designs) + len(excluded_repair_families)} "
            f"INCUMBENT={incumbent['repair_digest'] if incumbent is not None else 'NONE'} "
            f"ITERATION={iteration} ORACLE_CALLS={oracle_calls} "
            f"EXACT_VARIANTS={sum(variant_counts.values())}"
        )
    else:
        initial_core_count = 0
    run_iteration_start = iteration

    def elapsed() -> float:
        return elapsed_before + time.monotonic() - run_started

    def pause_for_wall(
        phase: str,
        action_ids: tuple[str, ...] = (),
        target_map: dict[str, str] | None = None,
        cost: int | None = None,
    ) -> None:
        save_checkpoint(
            phase,
            current_action_ids=action_ids,
            current_target_map=target_map,
            current_cost=cost,
        )
        emit(action_ids, cost or 0)
        raise _RepairSearchPausedError("RES-225 paused at the global wall-time budget")

    def ensure_wall(
        phase: str = "PAUSED_WALL_TIME",
        action_ids: tuple[str, ...] = (),
        target_map: dict[str, str] | None = None,
        cost: int | None = None,
    ) -> float:
        if wall_deadline is None:
            return oracle_timeout_seconds
        remaining = wall_deadline - time.monotonic()
        if remaining <= _WALL_CHECKPOINT_RESERVE_SECONDS:
            pause_for_wall(phase, action_ids, target_map, cost)
        return min(oracle_timeout_seconds, remaining - _WALL_CHECKPOINT_RESERVE_SECONDS)

    def wall_checkpoint_due() -> bool:
        return wall_deadline is not None and (
            wall_deadline - time.monotonic() <= _WALL_CHECKPOINT_RESERVE_SECONDS
        )

    def save_checkpoint(
        phase: str,
        *,
        current_action_ids: tuple[str, ...] = (),
        current_target_map: dict[str, str] | None = None,
        current_cost: int | None = None,
    ) -> str:
        nonlocal current_phase, checkpoint_digest, checkpoint_file_digest
        gap = _optimality_gap(lower_bound, upper_bound)
        elapsed_now = elapsed()
        state = {
            "fingerprints": fingerprints,
            "preservation_registry_digest": assumptions_digest,
            "action_registry_digest": actions_digest,
            "model_digests": {mode: model.model_digest for mode, model in models.items()},
            "preservation_registry": assumptions,
            "action_registry": actions,
            "cores": tuple(cores),
            "initial_core_count": initial_core_count,
            "iteration_records": tuple(iteration_records),
            "exact_core_evidence": tuple(exact_core_evidence),
            "excluded_exact_designs": tuple(excluded_exact_designs),
            "excluded_repair_families": tuple(excluded_repair_families),
            "tested_repairs": tuple(tested_repairs),
            "equality_records": tuple(equality_records),
            "variant_counts": variant_counts,
            "iteration": iteration,
            "elapsed_seconds": elapsed_now,
            "oracle_calls": oracle_calls,
            "oracle_status_counts": dict(oracle_status_counts),
            "last_core_size": last_core_size,
            "last_minimized_core_size": last_minimized_core_size,
            "last_oracle_status": last_oracle_status,
            "last_oracle_seconds": last_oracle_seconds,
            "phase": phase,
            "lower_bound": lower_bound,
            "upper_bound": upper_bound,
            "optimality_gap": gap,
            "no_goods": len(excluded_exact_designs) + len(excluded_repair_families),
            "current_hitting_set_action_ids": current_hitting_set_actions,
            "current_repair_action_ids": current_action_ids,
            "current_hitting_set_size": current_hitting_set_size,
            "current_hitting_set_cost": current_cost,
            "current_target_parent_by_action": current_target_map or {},
            "best_repair_cardinality": (upper_bound),
            "incumbent": incumbent,
            "primary_proof": primary_proof,
            "cost2_closure": cost2_closure,
            "hitman_core_registry_digest": canonical_hash(
                tuple(tuple(item["action_ids"]) for item in cores)
            ),
            "production_store_promoted": "NO",
            "feasibility_membership_persisted": "NO",
            "ITERATION": iteration,
            "ELAPSED": elapsed_now,
            "CORES_DISCOVERED": len(cores),
            "LAST_CORE_SIZE": last_core_size,
            "LAST_MINIMIZED_CORE_SIZE": last_minimized_core_size,
            "CURRENT_HITTING_SET_SIZE": current_hitting_set_size,
            "LOWER_BOUND": lower_bound,
            "GLOBAL_PRIMARY_LOWER_BOUND": global_primary_lower_bound,
            "global_primary_lower_bound": global_primary_lower_bound,
            "UPPER_BOUND": upper_bound,
            "OPTIMALITY_GAP": gap,
            "BEST_REPAIR_CARDINALITY": upper_bound,
            "ORACLE_CALLS": oracle_calls,
            "NO_GOODS": len(excluded_exact_designs) + len(excluded_repair_families),
            "LAST_ORACLE_STATUS": last_oracle_status,
            "LAST_ORACLE_SECONDS": last_oracle_seconds,
            "CURRENT_PHASE": phase,
        }
        checkpoint_digest, checkpoint_file_digest = _write_checkpoint(
            production_root,
            state,
            expected_file_digest=checkpoint_file_digest,
        )
        current_phase = phase
        _progress(f"CHECKPOINT phase={phase} digest={checkpoint_digest}")
        _emit_iteration(
            iteration=iteration,
            elapsed_seconds=elapsed_now,
            cores_discovered=len(cores),
            last_core_size=last_core_size,
            last_minimized_core_size=last_minimized_core_size,
            hitting_set_size=current_hitting_set_size,
            lower_bound=lower_bound,
            upper_bound=upper_bound,
            no_goods=len(excluded_exact_designs) + len(excluded_repair_families),
            best_repair_cardinality=upper_bound,
            oracle_calls=oracle_calls,
            last_oracle_status=last_oracle_status,
            last_oracle_seconds=last_oracle_seconds,
            phase=phase,
            checkpoint_digest=checkpoint_digest,
        )
        return checkpoint_digest

    def emit(iteration_action_ids: tuple[str, ...] = (), cost: int = 0) -> None:
        _emit_iteration(
            iteration=iteration,
            elapsed_seconds=elapsed(),
            cores_discovered=len(cores),
            last_core_size=last_core_size,
            last_minimized_core_size=last_minimized_core_size,
            hitting_set_size=current_hitting_set_size,
            lower_bound=lower_bound,
            upper_bound=upper_bound,
            no_goods=len(excluded_exact_designs) + len(excluded_repair_families),
            best_repair_cardinality=upper_bound,
            oracle_calls=oracle_calls,
            last_oracle_status=last_oracle_status,
            last_oracle_seconds=last_oracle_seconds,
            phase=current_phase,
            checkpoint_digest=checkpoint_digest,
        )

    def budgeted(
        operation: Any,
        *,
        phase: str = "PAUSED_WALL_TIME",
        action_ids: tuple[str, ...] = (),
        target_map: dict[str, str] | None = None,
        cost: int | None = None,
    ) -> Any:
        try:
            return operation()
        except (_RepairSearchBlockedError, CoreSolveTimeoutError):
            if (
                wall_deadline is not None
                and wall_deadline - time.monotonic() <= _WALL_CHECKPOINT_RESERVE_SECONDS
            ):
                pause_for_wall(phase, action_ids, target_map, cost)
            raise

    if resume:
        reconstructed_hitting_set = budgeted(
            lambda: _minimum_hit_solution(cores, weights, ensure_wall()),
            action_ids=tuple(saved.get("current_hitting_set_action_ids", ())),
            target_map=dict(saved.get("current_target_parent_by_action", {})),
            cost=saved.get("current_hitting_set_cost"),
        )
        reconstructed_lower_bound = sum(weights[item] for item in reconstructed_hitting_set)
        if reconstructed_lower_bound != lower_bound:
            raise ValueError("RES-225 checkpoint lower bound differs from its preserved cores")
        current_hitting_set_size = len(reconstructed_hitting_set)
        current_hitting_set_actions = tuple(reconstructed_hitting_set)

    if resume:
        completed_initial = tuple(cores[:initial_core_count])
        later_cores = cores[initial_core_count:]
    else:
        completed_initial = ()
        later_cores = []

    def initial_core_checkpoint(records: tuple[_CoreRecord, ...], _mode: str) -> None:
        nonlocal cores, initial_core_count, last_core_size, last_minimized_core_size
        nonlocal lower_bound, global_primary_lower_bound
        nonlocal current_hitting_set_size, current_hitting_set_actions
        initial_records = [dict(item) for item in records]
        next_cores = initial_records + later_cores
        latest = initial_records[-1]
        next_hitting_set = budgeted(
            lambda: _minimum_hit_solution(
                next_cores,
                weights,
                ensure_wall("PAUSED_WALL_TIME"),
            )
        )
        cores = next_cores
        initial_core_count = len(initial_records)
        last_core_size = int(latest["raw_assumption_core_size"])
        last_minimized_core_size = int(latest["minimized_assumption_core_size"])
        current_hitting_set_size = len(next_hitting_set)
        current_hitting_set_actions = tuple(next_hitting_set)
        lower_bound = sum(weights[item] for item in next_hitting_set)
        global_primary_lower_bound = max(global_primary_lower_bound, lower_bound)
        save_checkpoint("INITIAL_CORE_MINIMIZED")

    if resume and not completed_initial and cores:
        raise ValueError("RES-225 checkpoint core ordering is invalid")
    if not resume:
        save_checkpoint("INITIAL_CORE_EXTRACTION")
    try:
        initial_records, core_solvers = _initial_cores(
            models,
            oracle_timeout_seconds=oracle_timeout_seconds,
            completed_records=completed_initial,
            on_core=initial_core_checkpoint,
            time_budget=ensure_wall,
        )
    except CoreSolveTimeoutError:
        if wall_checkpoint_due():
            pause_for_wall("PAUSED_WALL_TIME")
        raise
    initial_core_count = len(initial_records)
    if not resume:
        cores = list(initial_records)
    else:
        cores = list(initial_records) + list(later_cores)
    _replay_exact_exclusions(excluded_exact_designs, models, core_solvers)

    excluded_repair_sets = tuple(tuple(item["action_ids"]) for item in excluded_repair_families)
    hitman = _hitman_from_cores(cores, weights, excluded_repair_sets)
    current_hitting_set_actions = budgeted(lambda: _hitman_solution(hitman, weights, ensure_wall()))
    current_hitting_set_size = len(current_hitting_set_actions)
    tested_variants: dict[
        tuple[str, ...],
        list[
            tuple[
                dict[str, str],
                Any,
                tuple[ProductionCandidateCommitmentV1, ...],
                tuple[tuple[str, str], ...],
            ]
        ],
    ] = {}
    tested_status: dict[tuple[str, ...], str] = {}
    feasible_variant_clauses: set[tuple[int, ...]] = set()
    for saved_test in tested_repairs:
        repair_ids = tuple(saved_test["action_ids"])
        status = str(saved_test["status"])
        tested_status[repair_ids] = status
        if status == "FEASIBLE":
            receipt = saved_test["receipt"]
            target_map = dict(saved_test["target_parent_by_action"])
            abstract_commitments, abstract_pairs = make_abstract_design(
                commitments,
                pairs,
                actions,
                repair_ids,
                target_parent_by_action=target_map,
            )
            tested_variants.setdefault(repair_ids, []).append(
                (target_map, receipt, abstract_commitments, abstract_pairs)
            )
            clause = _exact_variant_nogood_clause(models["COLOCATION"], repair_ids, target_map)
            if clause not in feasible_variant_clauses:
                feasible_variant_clauses.add(clause)
                core_solvers["COLOCATION"].add_clause(list(clause))

    def block_unknown(
        phase: str,
        repair_ids: tuple[str, ...] = (),
        target_map: dict[str, str] | None = None,
        current_cost: int | None = None,
    ) -> None:
        save_checkpoint(
            phase,
            current_action_ids=repair_ids,
            current_target_map=target_map,
            current_cost=current_cost,
        )
        emit(repair_ids, current_cost or 0)
        raise _RepairSearchBlockedError(f"RES-225 BLOCKED: {phase}; UNKNOWN is not accepted")

    def exact_attempt(
        repair_ids: tuple[str, ...],
        target_map: dict[str, str],
        rank_hint: dict[str, int],
        *,
        phase: str,
        current_cost: int,
    ) -> tuple[
        str,
        Any,
        tuple[ProductionCandidateCommitmentV1, ...],
        tuple[tuple[str, str], ...],
        dict[str, Any] | None,
    ]:
        nonlocal oracle_calls, last_oracle_status, last_oracle_seconds
        save_checkpoint(
            "EXACT_ORACLE_PENDING",
            current_action_ids=repair_ids,
            current_target_map=target_map,
            current_cost=current_cost,
        )
        state, receipt, abstract_commitments, abstract_pairs, exact_seconds, fallback = (
            _exact_repair_variant(
                commitments,
                pairs,
                actions,
                repair_ids,
                target_parent_by_action=target_map,
                candidate_rank_hint=rank_hint,
                time_budget_seconds=ensure_wall(phase, repair_ids, target_map, current_cost),
                independent_validate=phase == "CORE_GUIDED",
                production_root=production_root,
                wall_deadline=wall_deadline,
            )
        )
        oracle_calls += 1 + (len(fallback["records"]) if fallback is not None else 0)
        oracle_status_counts[state] += 1
        if fallback is not None:
            for record in fallback["records"].values():
                oracle_status_counts[f"RES224_{record.get('result', 'UNKNOWN')}"] += 1
        last_oracle_status = {"FEASIBLE": "SAT", "INFEASIBLE": "UNSAT", "UNKNOWN": "UNKNOWN"}[state]
        last_oracle_seconds = exact_seconds
        _progress(
            f"EXACT_ORACLE status={state} seconds={exact_seconds:.3f} "
            f"repair={canonical_hash(repair_ids)} phase={phase}"
        )
        return state, receipt, abstract_commitments, abstract_pairs, fallback

    if incumbent is None:
        save_checkpoint("CORE_GUIDED_READY")
        while True:
            if iteration - run_iteration_start >= max_iterations:
                block_unknown("BLOCKED_ITERATION_LIMIT")
            try:
                proposed = budgeted(lambda: _hitman_solution(hitman, weights, ensure_wall()))
            except _RepairSearchBlockedError:
                block_unknown("BLOCKED_HITMAN_ORACLE")
            current_hitting_set_size = len(proposed)
            current_hitting_set_actions = proposed
            proposed_cost = sum(weights[item] for item in proposed)
            iteration += 1
            candidate_started = time.monotonic()
            (
                candidate_status,
                relaxed_core,
                target_map,
                rank_hint,
                raw_core_size,
                minimized_core_size,
                _candidate_seconds,
            ) = _core_hit_set_is_sat(
                core_solvers["COLOCATION"],
                models["COLOCATION"],
                proposed,
                time_budget_seconds=ensure_wall("PAUSED_WALL_TIME", proposed),
            )
            oracle_calls += 1
            oracle_status_counts[candidate_status] += 1
            last_oracle_status = candidate_status
            last_oracle_seconds = time.monotonic() - candidate_started
            primary_candidate_status = candidate_status
            candidate_fallback_status: str | None = None
            if candidate_status == "UNKNOWN":
                fallback_started = time.monotonic()
                extra_clauses = (
                    *(tuple(item["blocking_clause"]) for item in excluded_exact_designs),
                    *tuple(feasible_variant_clauses),
                )
                fallback_result = _candidate_model_fallback(
                    models["COLOCATION"],
                    proposed,
                    extra_clauses=extra_clauses,
                    time_budget_seconds=ensure_wall(
                        "PAUSED_WALL_TIME", proposed, cost=proposed_cost
                    ),
                )
                (
                    candidate_status,
                    relaxed_core,
                    target_map,
                    rank_hint,
                    raw_core_size,
                    minimized_core_size,
                    _fallback_seconds,
                ) = fallback_result
                candidate_fallback_status = candidate_status
                oracle_calls += 1
                oracle_status_counts[f"MINISAT22_{candidate_status}"] += 1
                last_oracle_status = candidate_status
                last_oracle_seconds = time.monotonic() - candidate_started
                _progress(
                    f"candidate-model-fallback backend=MINISAT22 status={candidate_status} "
                    f"seconds={time.monotonic() - fallback_started:.3f}"
                )
            if wall_checkpoint_due():
                pause_for_wall("PAUSED_WALL_TIME", proposed, target_map, proposed_cost)
            record: dict[str, object] = {
                "iteration": iteration,
                "hitting_set_action_ids": proposed,
                "hitting_set_digest": canonical_hash(proposed),
                "minimum_content_replacement_cost": proposed_cost,
                "core_count_before_solve": len(cores),
                "candidate_level_exact_model_status": candidate_status,
                "candidate_primary_status": primary_candidate_status,
                "candidate_fallback_status": candidate_fallback_status,
                "candidate_oracle_seconds": last_oracle_seconds,
            }
            if candidate_status == "UNKNOWN":
                iteration_records.append(record)
                block_unknown(
                    "BLOCKED_CANDIDATE_MODEL_TIMEOUT", proposed, target_map, proposed_cost
                )
            if candidate_status == "UNSAT":
                last_core_size = raw_core_size
                last_minimized_core_size = minimized_core_size
                tested_variants_for_repair = tuple(
                    item
                    for item in tested_repairs
                    if tuple(item.get("action_ids", ())) == proposed
                    and item.get("status") == "EXACT_INFEASIBLE_VARIANT"
                )
                if tested_variants_for_repair:
                    try:
                        family_record = _append_unique_repair_family_exclusion(
                            excluded_repair_families,
                            proposed,
                            tuple(
                                canonical_hash(item["target_parent_by_action"])
                                for item in tested_variants_for_repair
                            ),
                        )
                    except RuntimeError:
                        block_unknown(
                            "BLOCKED_DUPLICATE_REPAIR_FAMILY",
                            proposed,
                            {},
                            proposed_cost,
                        )
                    _block_hitman_repair(hitman, action_ids, proposed, weights)
                    excluded_repair_sets = (*excluded_repair_sets, proposed)
                    current_hitting_set_actions = ()
                    current_hitting_set_size = 0
                    record["repair_family_no_good_digest"] = family_record["repair_digest"]
                    iteration_records.append(record)
                    save_checkpoint(
                        "REPAIR_FAMILY_EXCLUDED",
                        current_action_ids=proposed,
                        current_cost=proposed_cost,
                    )
                    emit(proposed, proposed_cost)
                    continue
                try:
                    core_action_ids = semantic_core_action_ids(
                        relaxed_core,
                        models["COLOCATION"].assumption_action_ids,
                    )
                except ValueError:
                    block_unknown(
                        "BLOCKED_CORE_WITHOUT_AUTHORIZED_ACTION", proposed, {}, proposed_cost
                    )
                core_record = {
                    **_core_record(
                        mode="COLOCATION",
                        assumption_ids=relaxed_core,
                        action_ids=core_action_ids,
                        source="REPAIR_CONDITIONED_ASSUMPTION_CORE_AND_SHRINK",
                        model_digest=models["COLOCATION"].model_digest,
                    ),
                    "raw_assumption_core_size": raw_core_size,
                    "minimized_assumption_core_size": minimized_core_size,
                }
                next_core_hitting_set = budgeted(
                    lambda core_values=(*cores, core_record),
                    selected=proposed,
                    cost=proposed_cost: _minimum_hit_solution(
                        core_values,
                        weights,
                        ensure_wall("PAUSED_WALL_TIME", selected, cost=cost),
                    ),
                    action_ids=proposed,
                    cost=proposed_cost,
                )
                next_current_hitting_set = budgeted(
                    lambda core_values=(*cores, core_record),
                    selected=proposed,
                    cost=proposed_cost,
                    blocked=excluded_repair_sets: _minimum_hit_solution(
                        core_values,
                        weights,
                        ensure_wall("PAUSED_WALL_TIME", selected, cost=cost),
                        blocked_sets=blocked,
                    ),
                    action_ids=proposed,
                    cost=proposed_cost,
                )
                try:
                    _append_unique_core(cores, core_record)
                except RuntimeError:
                    block_unknown("BLOCKED_DUPLICATE_CORE_NO_PROGRESS", proposed, {}, proposed_cost)
                hitman.hit(core_action_ids, weights=weights)
                new_lower_bound = sum(weights[item] for item in next_core_hitting_set)
                if new_lower_bound < lower_bound:
                    raise RuntimeError(
                        "RES-225 hitting-set lower bound decreased after adding a core"
                    )
                lower_bound = new_lower_bound
                global_primary_lower_bound = max(global_primary_lower_bound, lower_bound)
                current_hitting_set_actions = tuple(next_current_hitting_set)
                current_hitting_set_size = len(current_hitting_set_actions)
                record["new_core_digest"] = core_record["assumption_core_digest"]
                iteration_records.append(record)
                save_checkpoint(
                    "CORE_ADDED",
                    current_action_ids=proposed,
                    current_cost=proposed_cost,
                )
                emit(proposed, proposed_cost)
                continue

            last_core_size = raw_core_size or last_core_size
            last_minimized_core_size = minimized_core_size or last_minimized_core_size
            proposal_digest = canonical_hash(proposed)
            attempt_count = variant_counts.get(proposal_digest, 0)
            _enforce_variant_cap(
                attempt_count,
                max_exact_variants_per_repair,
                lambda selected=proposed,
                current_target_map=target_map,
                cost=proposed_cost: block_unknown(
                    "BLOCKED_EXACT_VARIANT_LIMIT", selected, current_target_map, cost
                ),
            )
            state, receipt, abstract_commitments, abstract_pairs, fallback = exact_attempt(
                proposed,
                target_map,
                rank_hint,
                phase="CORE_GUIDED",
                current_cost=proposed_cost,
            )
            if state == "UNKNOWN":
                tested_repairs.append(
                    {
                        "action_ids": proposed,
                        "target_parent_by_action": target_map,
                        "status": "UNKNOWN_VARIANT",
                        "receipt_digest": receipt.receipt_digest,
                        "fallback_evidence": fallback,
                    }
                )
                if wall_checkpoint_due():
                    pause_for_wall("PAUSED_WALL_TIME", proposed, target_map, proposed_cost)
                block_unknown("BLOCKED_EXACT_ORACLE_UNKNOWN", proposed, target_map, proposed_cost)
            variant_counts[proposal_digest] = attempt_count + 1
            if state == "INFEASIBLE":
                exact_exclusion = _exact_variant_exclusion_record(
                    models,
                    proposed,
                    target_map,
                    receipt,
                )
                try:
                    _append_unique_exact_exclusion(excluded_exact_designs, exact_exclusion)
                except RuntimeError:
                    block_unknown(
                        "BLOCKED_DUPLICATE_EXACT_VARIANT", proposed, target_map, proposed_cost
                    )
                for solver in core_solvers.values():
                    solver.add_clause(list(exact_exclusion["blocking_clause"]))
                exact_core_evidence.append(
                    {
                        "schema": "RES-225-EXACT-DESIGN-NO-GOOD@1",
                        **exact_exclusion,
                    }
                )
                tested_repairs.append(
                    {
                        "action_ids": proposed,
                        "target_parent_by_action": target_map,
                        "status": "EXACT_INFEASIBLE_VARIANT",
                        "receipt_digest": receipt.receipt_digest,
                        "fallback_evidence": fallback,
                    }
                )
                record.update(
                    {
                        "exact_target_parent_by_action": target_map,
                        "exact_target_status": "INFEASIBLE",
                        "blocking_clause_digest": exact_exclusion["blocking_clause_digest"],
                    }
                )
                iteration_records.append(record)
                save_checkpoint(
                    "EXACT_VARIANT_EXCLUDED",
                    current_action_ids=proposed,
                    current_target_map=target_map,
                    current_cost=proposed_cost,
                )
                emit(proposed, proposed_cost)
                continue

            _require_abstract_search_feasible(receipt)
            selected_profile = _repair_profile(abstract_commitments, abstract_pairs)
            upper_bound = proposed_cost
            released_candidate_ids = _released_candidate_ids(proposed, action_by_id)
            if len(released_candidate_ids) != proposed_cost:
                raise RuntimeError(
                    "RES-225 primary repair cost differs from released candidate slots"
                )
            incumbent = {
                "action_ids": proposed,
                "target_parent_by_action": target_map,
                "cardinality": proposed_cost,
                "repair_digest": canonical_hash(proposed),
                "released_candidate_ids": released_candidate_ids,
                "origin_counts_before": _origin_counts(commitments),
                "origin_counts_after": _origin_counts(abstract_commitments),
                "abstract_receipt": receipt,
                "abstract_witness_digest": receipt.canonical_witness_digest,
                "independent_witness_digests": (
                    fallback["witness_digests"] if fallback is not None else {}
                ),
                "independent_validation_records": (
                    fallback["records"] if fallback is not None else {}
                ),
                "validation_evidence_digest": (
                    fallback["digest"] if fallback is not None else receipt.receipt_digest
                ),
                "secondary_profile": selected_profile,
            }
            tested_repairs.append(
                {
                    "action_ids": proposed,
                    "target_parent_by_action": target_map,
                    "status": "FEASIBLE",
                    "receipt": receipt,
                    "fallback_evidence": fallback,
                    "released_candidate_ids": incumbent["released_candidate_ids"],
                    "origin_counts_before": incumbent["origin_counts_before"],
                    "origin_counts_after": incumbent["origin_counts_after"],
                    "secondary_profile": selected_profile,
                }
            )
            tested_variants.setdefault(proposed, []).append(
                (
                    target_map,
                    receipt,
                    abstract_commitments,
                    abstract_pairs,
                )
            )
            variant_clause = _exact_variant_nogood_clause(
                models["COLOCATION"], proposed, target_map
            )
            if variant_clause not in feasible_variant_clauses:
                feasible_variant_clauses.add(variant_clause)
                core_solvers["COLOCATION"].add_clause(list(variant_clause))
            tested_status[proposed] = "FEASIBLE"
            record.update(
                {
                    "exact_target_parent_by_action": target_map,
                    "abstract_base_status": receipt.base_status,
                    "abstract_colocation_status": receipt.colocation_status,
                    "abstract_canonical_self_reduction": receipt.canonical_self_reduction_status,
                }
            )
            iteration_records.append(record)
            save_checkpoint(
                "ABSTRACT_INCUMBENT_FEASIBLE",
                current_action_ids=proposed,
                current_target_map=target_map,
                current_cost=proposed_cost,
            )
            emit(proposed, proposed_cost)
            break

    if incumbent is None:
        raise _RepairSearchBlockedError("RES-225 has no exact-feasible abstract incumbent")
    selected_repair = tuple(incumbent["action_ids"])
    selected_target_parent_by_action = dict(incumbent["target_parent_by_action"])
    selected_receipt = incumbent["abstract_receipt"]
    selected_profile = dict(incumbent["secondary_profile"])
    selected_repair_digest = str(incumbent["repair_digest"])
    minimum_cost = int(incumbent["cardinality"])
    selected_abstract_commitments, selected_abstract_pairs = make_abstract_design(
        commitments,
        pairs,
        actions,
        selected_repair,
        target_parent_by_action=selected_target_parent_by_action,
    )
    _require_abstract_search_feasible(selected_receipt)
    if upper_bound != minimum_cost:
        raise RuntimeError("RES-225 incumbent upper bound differs from its released-slot cost")

    if primary_proof is None:
        hitman_selected = budgeted(
            lambda: _hitman_solution(hitman, weights, ensure_wall()),
            action_ids=selected_repair,
            target_map=selected_target_parent_by_action,
            cost=minimum_cost,
        )
        hitman_cost = sum(weights[item] for item in hitman_selected)
        rc2_selected, rc2_cost = budgeted(
            lambda: _rc2_optimum(
                action_ids,
                cores,
                weights,
                time_budget_seconds=ensure_wall(),
                blocked_sets=excluded_repair_sets,
            ),
            action_ids=selected_repair,
            target_map=selected_target_parent_by_action,
            cost=minimum_cost,
        )
        if hitman_cost != minimum_cost or rc2_cost != minimum_cost:
            block_unknown(
                "BLOCKED_PRIMARY_OPTIMUM_MISMATCH",
                selected_repair,
                selected_target_parent_by_action,
                minimum_cost,
            )
        additional_clauses = tuple(
            tuple(item["blocking_clause"]) for item in excluded_exact_designs
        )
        lower_bound_result, lower_bound_digest = budgeted(
            lambda: _independent_minimum_crosscheck(
                models["COLOCATION"],
                action_ids,
                weights,
                minimum_cost,
                additional_clauses=additional_clauses,
                time_budget_seconds=ensure_wall(),
            ),
            action_ids=selected_repair,
            target_map=selected_target_parent_by_action,
            cost=minimum_cost,
        )
        primary_proof = {
            "minimum_cost": minimum_cost,
            "hitman_selected": hitman_selected,
            "hitman_cost": hitman_cost,
            "rc2_selected": rc2_selected,
            "rc2_cost": rc2_cost,
            "lower_bound_result": lower_bound_result,
            "lower_bound_digest": lower_bound_digest,
            "objective": "MINIMIZE_RELEASED_CANDIDATE_SLOTS",
        }
        save_checkpoint(
            "PRIMARY_OPTIMUM_PROVEN",
            current_action_ids=selected_repair,
            current_target_map=selected_target_parent_by_action,
            current_cost=minimum_cost,
        )
    else:
        hitman_selected = tuple(primary_proof["hitman_selected"])
        hitman_cost = int(primary_proof["hitman_cost"])
        rc2_selected = tuple(primary_proof["rc2_selected"])
        rc2_cost = int(primary_proof["rc2_cost"])
        lower_bound_result = dict(primary_proof["lower_bound_result"])
        lower_bound_digest = str(primary_proof["lower_bound_digest"])
        if (
            int(primary_proof["minimum_cost"]) != minimum_cost
            or hitman_cost != minimum_cost
            or rc2_cost != minimum_cost
        ):
            raise ValueError("RES-225 checkpoint primary optimum no longer matches its bounds")

    equal_sets, equal_sets_complete = budgeted(
        lambda: _enumerate_minimum_hit_sets(
            action_ids,
            cores,
            weights,
            minimum_cost=minimum_cost,
            limit=_EQUAL_REPAIR_LIMIT,
            include=selected_repair,
            time_budget_seconds=ensure_wall(),
            time_budget=ensure_wall,
            blocked_sets=excluded_repair_sets,
        ),
        action_ids=selected_repair,
        target_map=selected_target_parent_by_action,
        cost=minimum_cost,
    )
    if not equal_sets_complete:
        save_checkpoint(
            "BLOCKED_EQUAL_MINIMUM_REPAIR_LIMIT",
            current_action_ids=selected_repair,
            current_target_map=selected_target_parent_by_action,
            current_cost=minimum_cost,
        )
        raise _RepairSearchBlockedError(
            "RES-225 equal-minimum repair comparison exceeded its bound"
        )
    feasible_ties: list[
        tuple[tuple[object, ...], tuple[str, ...], dict[str, str], Any, dict[str, int]]
    ] = []
    compared_digests = {str(item["repair_digest"]) for item in equality_records}
    for repair_ids, variants in tested_variants.items():
        for target_map, receipt, abstract_commitments, abstract_pairs in variants:
            profile = _repair_profile(abstract_commitments, abstract_pairs)
            score = _repair_score(
                repair_ids,
                action_by_id,
                profile,
                target_map,
                commitments,
                abstract_commitments,
            )
            feasible_ties.append((score, repair_ids, target_map, receipt, profile))

    for repair_ids in equal_sets:
        repair_digest = canonical_hash(repair_ids)
        if repair_digest in compared_digests:
            continue
        current_hitting_set_size = len(repair_ids)
        current_hitting_set_actions = repair_ids
        variants = tested_variants.setdefault(repair_ids, [])
        tested_maps = [
            dict(item["target_parent_by_action"])
            for item in tested_repairs
            if tuple(item.get("action_ids", ())) == repair_ids
            and item.get("status") in {"FEASIBLE", "EXACT_INFEASIBLE_VARIANT"}
        ]
        prior_status = tested_status.get(repair_ids)
        family_exhausted = prior_status in {"CANDIDATE_UNSAT", "VARIANTS_EXHAUSTED"}
        while not family_exhausted:
            if iteration - run_iteration_start >= max_iterations:
                block_unknown("BLOCKED_ITERATION_LIMIT", repair_ids, {}, minimum_cost)
            iteration += 1
            candidate_started = time.monotonic()
            (
                candidate_status,
                _core,
                target_map,
                rank_hint,
                raw_core_size,
                minimized_core_size,
                _candidate_seconds,
            ) = _core_hit_set_is_sat(
                core_solvers["COLOCATION"],
                models["COLOCATION"],
                repair_ids,
                time_budget_seconds=ensure_wall("PAUSED_WALL_TIME", repair_ids),
            )
            oracle_calls += 1
            oracle_status_counts[candidate_status] += 1
            last_oracle_status = candidate_status
            last_oracle_seconds = time.monotonic() - candidate_started
            tie_primary_candidate_status = candidate_status
            tie_candidate_fallback_status: str | None = None
            if candidate_status == "UNKNOWN":
                fallback_started = time.monotonic()
                extra_clauses = (
                    *(tuple(item["blocking_clause"]) for item in excluded_exact_designs),
                    *tuple(feasible_variant_clauses),
                )
                fallback_result = _candidate_model_fallback(
                    models["COLOCATION"],
                    repair_ids,
                    extra_clauses=extra_clauses,
                    time_budget_seconds=ensure_wall(
                        "PAUSED_WALL_TIME", repair_ids, cost=minimum_cost
                    ),
                )
                (
                    candidate_status,
                    _core,
                    target_map,
                    rank_hint,
                    raw_core_size,
                    minimized_core_size,
                    _fallback_seconds,
                ) = fallback_result
                tie_candidate_fallback_status = candidate_status
                oracle_calls += 1
                oracle_status_counts[f"MINISAT22_{candidate_status}"] += 1
                last_oracle_status = candidate_status
                last_oracle_seconds = time.monotonic() - candidate_started
                _progress(
                    f"candidate-model-fallback backend=MINISAT22 status={candidate_status} "
                    f"seconds={time.monotonic() - fallback_started:.3f}"
                )
            if wall_checkpoint_due():
                pause_for_wall("PAUSED_WALL_TIME", repair_ids, target_map, minimum_cost)
            if candidate_status == "UNKNOWN":
                iteration_records.append(
                    {
                        "iteration": iteration,
                        "hitting_set_action_ids": repair_ids,
                        "minimum_content_replacement_cost": minimum_cost,
                        "candidate_primary_status": tie_primary_candidate_status,
                        "candidate_fallback_status": tie_candidate_fallback_status,
                        "candidate_level_exact_model_status": "UNKNOWN",
                    }
                )
                block_unknown("BLOCKED_TIE_CANDIDATE_TIMEOUT", repair_ids, target_map, minimum_cost)
            if candidate_status == "UNSAT":
                family_exhausted = True
                tested_status[repair_ids] = (
                    "CANDIDATE_UNSAT" if not variants else "VARIANTS_EXHAUSTED"
                )
                if not variants:
                    tested_repairs.append(
                        {
                            "action_ids": repair_ids,
                            "status": "CANDIDATE_UNSAT",
                            "raw_core_size": raw_core_size,
                            "minimized_core_size": minimized_core_size,
                        }
                    )
                else:
                    tested_repairs.append(
                        {"action_ids": repair_ids, "status": "VARIANTS_EXHAUSTED"}
                    )
                iteration_records.append(
                    {
                        "iteration": iteration,
                        "hitting_set_action_ids": repair_ids,
                        "minimum_content_replacement_cost": minimum_cost,
                        "candidate_level_exact_model_status": "UNSAT",
                        "variant_family_exhausted": True,
                    }
                )
                save_checkpoint(
                    "MINIMUM_REPAIR_VARIANTS_EXHAUSTED",
                    current_action_ids=repair_ids,
                    current_cost=minimum_cost,
                )
                break

            repair_digest_for_count = canonical_hash(repair_ids)
            used = variant_counts.get(repair_digest_for_count, 0)
            _enforce_variant_cap(
                used,
                max_exact_variants_per_repair,
                lambda selected=repair_ids, current_target_map=target_map: block_unknown(
                    "BLOCKED_EXACT_VARIANT_LIMIT", selected, current_target_map, minimum_cost
                ),
            )
            save_checkpoint(
                "TIE_EXACT_ORACLE_PENDING",
                current_action_ids=repair_ids,
                current_target_map=target_map,
                current_cost=minimum_cost,
            )
            state, receipt, abstract_commitments, abstract_pairs, fallback = exact_attempt(
                repair_ids,
                target_map,
                rank_hint,
                phase="MINIMUM_REPAIR_VARIANT",
                current_cost=minimum_cost,
            )
            if state == "UNKNOWN":
                tested_repairs.append(
                    {
                        "action_ids": repair_ids,
                        "target_parent_by_action": target_map,
                        "status": "UNKNOWN_VARIANT",
                        "receipt_digest": receipt.receipt_digest,
                        "fallback_evidence": fallback,
                    }
                )
                if wall_checkpoint_due():
                    pause_for_wall("PAUSED_WALL_TIME", repair_ids, target_map, minimum_cost)
                block_unknown("BLOCKED_TIE_EXACT_UNKNOWN", repair_ids, target_map, minimum_cost)
            variant_counts[repair_digest_for_count] = used + 1
            tested_maps.append(target_map)
            iteration_record: dict[str, Any] = {
                "iteration": iteration,
                "hitting_set_action_ids": repair_ids,
                "minimum_content_replacement_cost": minimum_cost,
                "candidate_level_exact_model_status": "SAT",
                "candidate_primary_status": tie_primary_candidate_status,
                "candidate_fallback_status": tie_candidate_fallback_status,
                "target_parent_by_action": target_map,
                "exact_target_status": state,
            }
            if state == "INFEASIBLE":
                exact_exclusion = _exact_variant_exclusion_record(
                    models,
                    repair_ids,
                    target_map,
                    receipt,
                )
                try:
                    _append_unique_exact_exclusion(excluded_exact_designs, exact_exclusion)
                except RuntimeError:
                    block_unknown(
                        "BLOCKED_DUPLICATE_TIE_VARIANT", repair_ids, target_map, minimum_cost
                    )
                for solver in core_solvers.values():
                    solver.add_clause(list(exact_exclusion["blocking_clause"]))
                exact_core_evidence.append(
                    {"schema": "RES-225-EXACT-DESIGN-NO-GOOD@1", **exact_exclusion}
                )
                tested_repairs.append(
                    {
                        "action_ids": repair_ids,
                        "target_parent_by_action": target_map,
                        "status": "EXACT_INFEASIBLE_VARIANT",
                        "receipt_digest": receipt.receipt_digest,
                        "fallback_evidence": fallback,
                    }
                )
                iteration_records.append(iteration_record)
                save_checkpoint(
                    "TIE_EXACT_VARIANT_EXCLUDED",
                    current_action_ids=repair_ids,
                    current_target_map=target_map,
                    current_cost=minimum_cost,
                )
                continue

            _require_abstract_search_feasible(receipt)
            profile = _repair_profile(abstract_commitments, abstract_pairs)
            variants.append((target_map, receipt, abstract_commitments, abstract_pairs))
            tested_status[repair_ids] = "FEASIBLE"
            tested_repairs.append(
                {
                    "action_ids": repair_ids,
                    "target_parent_by_action": target_map,
                    "status": "FEASIBLE",
                    "receipt": receipt,
                    "fallback_evidence": fallback,
                    "secondary_profile": profile,
                }
            )
            variant_clause = _exact_variant_nogood_clause(
                models["COLOCATION"], repair_ids, target_map
            )
            if variant_clause not in feasible_variant_clauses:
                feasible_variant_clauses.add(variant_clause)
                core_solvers["COLOCATION"].add_clause(list(variant_clause))
            iteration_records.append(iteration_record)
            save_checkpoint(
                "TIE_REPAIR_VARIANT_FEASIBLE",
                current_action_ids=repair_ids,
                current_target_map=target_map,
                current_cost=minimum_cost,
            )

        variant_records: list[dict[str, object]] = []
        for target_map, receipt, abstract_commitments, abstract_pairs in variants:
            profile = _repair_profile(abstract_commitments, abstract_pairs)
            score = _repair_score(
                repair_ids,
                action_by_id,
                profile,
                target_map,
                commitments,
                abstract_commitments,
            )
            feasible_ties.append((score, repair_ids, target_map, receipt, profile))
            variant_records.append(
                {
                    "target_parent_by_action": target_map,
                    "abstract_base_status": receipt.base_status,
                    "abstract_colocation_status": receipt.colocation_status,
                    "abstract_canonical_self_reduction": receipt.canonical_self_reduction_status,
                    "secondary_profile": profile,
                    "secondary_score_digest": canonical_hash(score),
                }
            )
        equality_records.append(
            {
                "repair_action_ids": repair_ids,
                "repair_digest": repair_digest,
                "content_replacement_count": _repair_primary_cost(repair_ids, action_by_id),
                "target_variants_tested": variant_counts.get(canonical_hash(repair_ids), 0),
                "candidate_level_status": tested_status.get(repair_ids, "VARIANTS_EXHAUSTED"),
                "tested_target_parent_map_digests": tuple(
                    canonical_hash(item) for item in tested_maps
                ),
                "target_variant_results": tuple(variant_records),
                "target_variant_family_exhausted": family_exhausted,
                "result": "FEASIBLE" if variants else "INFEASIBLE",
            }
        )
        compared_digests.add(repair_digest)
        save_checkpoint(
            "MINIMUM_REPAIR_COMPARED",
            current_action_ids=repair_ids,
            current_cost=minimum_cost,
        )
        _progress(
            f"minimum-repair-compared index={len(equality_records)}/{len(equal_sets)} "
            f"actions={len(repair_ids)} feasible_variants={len(variants)}"
        )

    if not feasible_ties:
        raise _RepairSearchBlockedError(
            "RES-225 minimum repair comparison found no exact-feasible repair"
        )
    feasible_ties.sort(key=lambda item: item[0])
    selected_repair = feasible_ties[0][1]
    selected_target_parent_by_action = feasible_ties[0][2]
    selected_receipt = feasible_ties[0][3]
    selected_profile = feasible_ties[0][4]
    selected_repair_digest = canonical_hash(selected_repair)
    selected_abstract_commitments, selected_abstract_pairs = make_abstract_design(
        commitments,
        pairs,
        actions,
        selected_repair,
        target_parent_by_action=selected_target_parent_by_action,
    )
    _require_abstract_search_feasible(selected_receipt)
    minimum_cost = _repair_primary_cost(selected_repair, action_by_id)
    if minimum_cost != upper_bound:
        raise RuntimeError("RES-225 selected repair does not match its proven primary bounds")

    selected_score = feasible_ties[0][0]
    selected_validation = next(
        (
            item.get("fallback_evidence")
            for item in reversed(tested_repairs)
            if tuple(item.get("action_ids", ())) == selected_repair
            and dict(item.get("target_parent_by_action", {})) == selected_target_parent_by_action
            and item.get("status") == "FEASIBLE"
        ),
        None,
    )
    selected_witness_digests = (
        _independent_witness_digests(selected_validation.get("records", {}))
        if isinstance(selected_validation, dict)
        else {}
    )
    selected_validation_records = (
        dict(selected_validation.get("records", {}))
        if isinstance(selected_validation, dict)
        else {}
    )
    incumbent = {
        **incumbent,
        "action_ids": selected_repair,
        "target_parent_by_action": selected_target_parent_by_action,
        "cardinality": minimum_cost,
        "repair_digest": selected_repair_digest,
        "secondary_profile": selected_profile,
        "secondary_score": selected_score,
        "abstract_receipt": selected_receipt,
        "released_candidate_ids": _released_candidate_ids(selected_repair, action_by_id),
        "origin_counts_before": _origin_counts(commitments),
        "origin_counts_after": _origin_counts(selected_abstract_commitments),
        "independent_witness_digests": selected_witness_digests,
        "independent_validation_records": selected_validation_records,
        "validation_evidence_digest": (
            selected_validation.get("digest")
            if isinstance(selected_validation, dict) and len(selected_witness_digests) == 2
            else None
        ),
    }
    save_checkpoint(
        "SECONDARY_OPTIMUM_SELECTED",
        current_action_ids=selected_repair,
        current_target_map=selected_target_parent_by_action,
        current_cost=minimum_cost,
    )

    if len(selected_witness_digests) != 2:
        save_checkpoint(
            "INDEPENDENT_WITNESS_VALIDATION_PENDING",
            current_action_ids=selected_repair,
            current_target_map=selected_target_parent_by_action,
            current_cost=minimum_cost,
        )
        witness_statuses, witness_records = _independent_abstract_fallback(
            selected_abstract_commitments,
            selected_abstract_pairs,
            receipt=selected_receipt,
            production_root=production_root,
            time_budget_seconds=ensure_wall(
                "PAUSED_WALL_TIME", selected_repair, selected_target_parent_by_action, minimum_cost
            ),
            wall_deadline=wall_deadline,
        )
        selected_witness_digests = _independent_witness_digests(witness_records)
        incumbent["independent_witness_digests"] = selected_witness_digests
        incumbent["independent_validation_records"] = witness_records
        incumbent["validation_evidence_digest"] = canonical_hash(
            (witness_statuses, witness_records)
        )
        if (
            witness_statuses != {"BASE": "FEASIBLE", "COLOCATION": "FEASIBLE"}
            or len(selected_witness_digests) != 2
        ):
            save_checkpoint(
                "BLOCKED_ABSTRACT_WITNESS_CROSSCHECK",
                current_action_ids=selected_repair,
                current_target_map=selected_target_parent_by_action,
                current_cost=minimum_cost,
            )
            raise _RepairSearchBlockedError(
                "RES-225 independent BASE/COLOCATION allocation witness validation failed"
            )
        save_checkpoint(
            "ABSTRACT_WITNESS_INDEPENDENTLY_VALIDATED",
            current_action_ids=selected_repair,
            current_target_map=selected_target_parent_by_action,
            current_cost=minimum_cost,
        )

    if selected_receipt.canonical_self_reduction_status != "PASS":
        save_checkpoint(
            "CANONICALIZATION_PENDING",
            current_action_ids=selected_repair,
            current_target_map=selected_target_parent_by_action,
            current_cost=minimum_cost,
        )
        canonical_result = _exact_repair_variant(
            commitments,
            pairs,
            actions,
            selected_repair,
            target_parent_by_action=selected_target_parent_by_action,
            candidate_rank_hint=None,
            time_budget_seconds=ensure_wall(
                "PAUSED_WALL_TIME", selected_repair, selected_target_parent_by_action, minimum_cost
            ),
            canonicalize=True,
            production_root=production_root,
            wall_deadline=wall_deadline,
        )
        state, canonical_receipt, _canonical_commitments, _canonical_pairs, seconds, _fallback = (
            canonical_result
        )
        oracle_calls += 1
        oracle_status_counts[state] += 1
        last_oracle_status = {"FEASIBLE": "SAT", "INFEASIBLE": "UNSAT", "UNKNOWN": "UNKNOWN"}[state]
        last_oracle_seconds = seconds
        if wall_checkpoint_due():
            pause_for_wall(
                "PAUSED_WALL_TIME", selected_repair, selected_target_parent_by_action, minimum_cost
            )
        if state != "FEASIBLE" or canonical_receipt.canonical_self_reduction_status != "PASS":
            block_unknown(
                "BLOCKED_CANONICALIZATION_UNKNOWN",
                selected_repair,
                selected_target_parent_by_action,
                minimum_cost,
            )
        selected_receipt = canonical_receipt
        incumbent["abstract_receipt"] = selected_receipt
        incumbent["abstract_witness_digest"] = selected_receipt.canonical_witness_digest
        for saved_test in reversed(tested_repairs):
            if (
                tuple(saved_test.get("action_ids", ())) == selected_repair
                and dict(saved_test.get("target_parent_by_action", {}))
                == selected_target_parent_by_action
                and saved_test.get("status") == "FEASIBLE"
            ):
                saved_test["receipt"] = selected_receipt
                break
    _require_abstract_feasible(selected_receipt)

    minimum_evidence_digest = canonical_hash(
        {
            "preservation_registry_digest": assumptions_digest,
            "action_registry_digest": actions_digest,
            "minimized_cores": tuple(
                (item["assumption_core_digest"], item["action_core_digest"]) for item in cores
            ),
            "exact_design_exclusion_digests": tuple(
                item["blocking_clause_digest"] for item in excluded_exact_designs
            ),
            "repair_family_exclusion_digests": tuple(
                item["repair_digest"] for item in excluded_repair_families
            ),
            "primary_proof": primary_proof,
            "hitman_selected": hitman_selected,
            "hitman_cost": hitman_cost,
            "rc2_selected": rc2_selected,
            "rc2_cost": rc2_cost,
            "minimum_cost": minimum_cost,
            "lower_bound_digest": lower_bound_digest,
            "lower_bound_result": lower_bound_result,
            "selected_repair_digest": selected_repair_digest,
            "abstract_witness_digest": selected_receipt.canonical_witness_digest,
            "secondary_score": selected_score,
        }
    )
    save_checkpoint(
        "MINIMUM_REPAIR_PROVEN",
        current_action_ids=selected_repair,
        current_target_map=selected_target_parent_by_action,
        current_cost=minimum_cost,
    )

    if not materialize:
        save_checkpoint(
            "ABSTRACT_MINIMUM_READY",
            current_action_ids=selected_repair,
            current_target_map=selected_target_parent_by_action,
            current_cost=minimum_cost,
        )
        return {
            "STATUS": "ABSTRACT_MINIMUM_READY",
            "PRIMARY_OBJECTIVE": "MINIMIZE_RELEASED_CANDIDATE_SLOTS",
            "MINIMUM_REPAIR_CARDINALITY": minimum_cost,
            "MINIMUM_REPAIR_PROVEN": "YES",
            "MINIMUM_REPAIR_EVIDENCE_DIGEST": minimum_evidence_digest,
            "SELECTED_REPAIR_DIGEST": selected_repair_digest,
            "NO_GOODS": len(excluded_exact_designs) + len(excluded_repair_families),
            "ABSTRACT_BASE_EXACT_STATUS": selected_receipt.base_status,
            "ABSTRACT_COLOCATION_EXACT_STATUS": selected_receipt.colocation_status,
            "ABSTRACT_CANONICAL_WITNESS_DIGEST": selected_receipt.canonical_witness_digest,
            "CANONICAL_SELF_REDUCTION": selected_receipt.canonical_self_reduction_status,
            "CANDIDATES_MATERIALIZED": 0,
            "CHECKPOINT_DIGEST": checkpoint_digest,
        }, len(commitments)

    assumption_artifact_digest = _private_write(
        production_root,
        f"{_PRIVATE_DIR}/preservation-assumptions.private.json",
        {
            "schema": "RES-225-PRESERVATION-REGISTRY@1.0.0",
            "assumptions": assumptions,
            "registry_digest": assumptions_digest,
            "action_registry": actions,
            "action_registry_digest": actions_digest,
            "candidate_count": 434,
        },
    )
    cores_artifact_digest = _private_write(
        production_root,
        f"{_PRIVATE_DIR}/minimized-unsat-cores.private.json",
        {
            "schema": "RES-225-SEMANTIC-UNSAT-CORES@1.0.0",
            "cores": tuple(cores),
            "exact_oracle_shrinks": tuple(exact_core_evidence),
        },
    )
    abstract_artifact_digest = _private_write(
        production_root,
        f"{_PRIVATE_DIR}/abstract-minimum-repair.private.json",
        {
            "schema": "RES-225-ABSTRACT-MINIMUM-REPAIR@1.0.0",
            "selected_action_ids": selected_repair,
            "selected_target_parent_by_action": selected_target_parent_by_action,
            "selected_repair_digest": selected_repair_digest,
            "selected_placeholders": tuple(
                placeholder
                for action_id in selected_repair
                for placeholder in (
                    action_by_id[action_id].target_placeholders[
                        action_by_id[action_id].target_parent_candidate_ids.index(
                            selected_target_parent_by_action[action_id]
                        )
                        * len(action_by_id[action_id].affected_candidate_ids) : (
                            action_by_id[action_id].target_parent_candidate_ids.index(
                                selected_target_parent_by_action[action_id]
                            )
                            + 1
                        )
                        * len(action_by_id[action_id].affected_candidate_ids)
                    ]
                    if action_by_id[action_id].action_family == "MUTATION_BRANCH_REPARENT"
                    else action_by_id[action_id].placeholders
                )
            ),
            "base_status": selected_receipt.base_status,
            "colocation_status": selected_receipt.colocation_status,
            "canonical_witness_digest": selected_receipt.canonical_witness_digest,
            "minimum_cardinality": minimum_cost,
            "minimum_repair_proven": True,
            "minimum_repair_evidence_digest": minimum_evidence_digest,
            "equally_minimum_repairs_enumerated": len(equal_sets),
            "equally_minimum_comparisons": tuple(equality_records),
            "secondary_profile": selected_profile,
            "feasibility_membership_persisted": "NO",
        },
    )
    materialization_plan = _make_materialization_plan(
        production_root=production_root,
        selected_action_ids=selected_repair,
        actions=actions,
        assumptions=assumptions,
        target_parent_by_action=selected_target_parent_by_action,
        abstract_receipt=selected_receipt,
        selected_repair_digest=selected_repair_digest,
        minimum_evidence_digest=minimum_evidence_digest,
        iteration=1,
    )
    materialization_plan["origin_counts_before"] = tuple(
        sorted(
            (origin.value, count)
            for origin, count in Counter(c.item.origin_class for c in commitments).items()
        )
    )
    materialization_plan["plan_digest"] = canonical_hash(
        {key: value for key, value in materialization_plan.items() if key != "plan_digest"}
    )
    materialization_plan_digest = _write_authorized_materialization(
        production_root,
        materialization_plan,
    )

    baseline_content_digest = canonical_hash(
        tuple(
            (
                packet.candidate_id,
                canonical_hash(candidate_scientific_projection(packet)),
            )
            for packet in before_packets
        )
    )
    draft, qualification_exclusion = build_production_authoring_draft(
        repository_root=_REPOSITORY_ROOT,
        production_root=production_root,
    )
    selected_candidate_ids = {
        candidate_id
        for action_id in selected_repair
        for candidate_id in action_by_id[action_id].affected_candidate_ids
    }
    candidate_content_replacements, changed_candidates_digest = _verify_preserved_content(
        before_packets,
        draft.packets,
        selected_candidate_ids,
    )
    authority_checks = _final_authority_checks(draft, qualification_exclusion)
    exact_receipt = draft.feasibility_receipt
    validate_production_exact_feasibility_receipt(exact_receipt)
    if (
        exact_receipt.base_status != "FEASIBLE"
        or exact_receipt.colocation_status != "FEASIBLE"
        or exact_receipt.canonical_self_reduction_status != "PASS"
        or exact_receipt.canonical_witness_digest is None
        or exact_receipt.feasibility_membership_persisted
    ):
        raise RuntimeError("RES-225 final real-byte exact feasibility receipt failed")
    independent_sat = _exact_final_sat_crosscheck(draft, production_root)
    if any(
        independent_sat[mode].get("result") != "SAT"
        or independent_sat[mode].get("witness_independently_validated") is not True
        for mode in ("BASE", "COLOCATION")
    ):
        raise RuntimeError("RES-225 independent SAT witness cross-check failed")

    resilience = _record_resilience(
        draft.commitments,
        draft.duplication_audit.exact_shingle_colocation_pairs,
    )
    final_action_digest = canonical_hash(selected_repair)
    materialized_plan = _bind_plan({**materialization_plan, "status": "MATERIALIZED"})
    materialization_plan_digest = _write_authorized_materialization(
        production_root,
        materialized_plan,
    )
    effective_inputs_digest = _private_write(
        production_root,
        "production/authoring_plan/RES-225-effective-inputs.private.json",
        draft.inputs,
    )
    selected_packets = tuple(
        packet for packet in draft.packets if packet.candidate_id in selected_candidate_ids
    )
    selected_packets_digest = _private_write(
        production_root,
        "production/authoring_plan/RES-225-selected-replacements.private.json",
        selected_packets,
    )
    final_candidate_digest = canonical_hash(draft.commitments)
    final_origin_counts = Counter(item.item.origin_class for item in draft.commitments)
    before_origin_counts = Counter(item.item.origin_class for item in commitments)
    if final_origin_counts != before_origin_counts:
        raise RuntimeError("RES-225 materialization changed a hard origin count")
    if len(draft.packets) != 434 or exact_receipt.candidate_count != 434:
        raise RuntimeError("RES-225 final real-byte design changed N=434")
    if (
        draft.duplication_audit.exact_question_duplicate_pairs != 0
        or draft.duplication_audit.blocking_fuzzy_overlap_pairs != 0
    ):
        raise RuntimeError("RES-225 final real-byte contamination thresholds failed")
    lower_bound = lower_bound_result
    acceptance_receipt: dict[str, object] = {
        "MISSION": "RES-225-MINIMUM-CANDIDATE-DESIGN-REPAIR-001",
        "STATUS": "PASS",
        "ENTRY_HEAD": _ENTRY_HEAD,
        "FINAL_HEAD": "TO_BE_BOUND_AFTER_ATOMIC_COMMITS",
        "RES224_BASE_BEFORE": "INFEASIBLE",
        "RES224_COLOCATION_BEFORE": "INFEASIBLE",
        "RES224_PROOF_CHECK": "PASS",
        "PRESERVATION_ASSUMPTIONS": len(assumptions),
        "PRESERVATION_REGISTRY_DIGEST": assumptions_digest,
        "UNSAT_CORES_DISCOVERED": len(cores),
        "MINIMIZED_CORE_DIGESTS": tuple(item["assumption_core_digest"] for item in cores),
        "MINIMIZED_ACTION_CORE_DIGESTS": tuple(item["action_core_digest"] for item in cores),
        "HITTING_SET_ITERATIONS": len(iteration_records),
        "MINIMUM_REPAIR_CARDINALITY": minimum_cost,
        "PRIMARY_OBJECTIVE": "MINIMIZE_RELEASED_CANDIDATE_SLOTS",
        "MINIMUM_REPAIR_PROVEN": "YES",
        "EXACT_VARIANT_NO_GOODS": len(excluded_exact_designs),
        "REPAIR_FAMILY_NO_GOODS": len(excluded_repair_families),
        "NO_GOODS": len(excluded_exact_designs) + len(excluded_repair_families),
        "MINIMUM_REPAIR_EVIDENCE_DIGEST": minimum_evidence_digest,
        "LOWER_CARDINALITY_CROSSCHECK": lower_bound,
        "LOWER_CARDINALITY_CROSSCHECK_DIGEST": lower_bound_digest,
        "HITMAN_MINIMUM_COST": hitman_cost,
        "RC2_MINIMUM_COST": rc2_cost,
        "EQUALLY_MINIMUM_REPAIRS_ENUMERATED": len(equal_sets),
        "EQUAL_REPAIR_LIMIT": _EQUAL_REPAIR_LIMIT,
        "SELECTED_REPAIR_DIGEST": final_action_digest,
        "SELECTED_TARGET_PARENT_BY_ACTION": selected_target_parent_by_action,
        "RELEASED_CANDIDATE_SLOTS": candidate_content_replacements,
        "MUTATION_CHILDREN_RELEASED": sum(
            sum(
                placeholder.origin_class == CaseOrigin.ADVERSARIAL_MUTATION.value
                for placeholder in action_by_id[action_id].placeholders
            )
            for action_id in selected_repair
        ),
        "SEMANTIC_SLOTS_REALLOCATED": sum(
            action_by_id[action_id].action_family == "EXPERT_SEMANTIC_CONTENT_REPLACEMENT"
            for action_id in selected_repair
        ),
        "MUTATION_PARENTS_CHANGED": sum(
            action_by_id[action_id].action_family == "MUTATION_BRANCH_REPARENT"
            for action_id in selected_repair
        ),
        "SOURCE_SLOTS_CHANGED": 0,
        "ENGINE_SLOTS_CHANGED": 0,
        "ORIGIN_COUNTS_BEFORE": tuple(
            sorted((origin.value, count) for origin, count in before_origin_counts.items())
        ),
        "ORIGIN_COUNTS_AFTER": tuple(
            sorted((origin.value, count) for origin, count in final_origin_counts.items())
        ),
        "ABSTRACT_BASE_EXACT_STATUS": selected_receipt.base_status,
        "ABSTRACT_COLOCATION_EXACT_STATUS": selected_receipt.colocation_status,
        "ABSTRACT_CANONICAL_WITNESS_DIGEST": selected_receipt.canonical_witness_digest,
        "CANDIDATES_MATERIALIZED": candidate_content_replacements,
        "PRESERVED_CANDIDATE_CONTENT_CHANGED": "NO",
        "PRESERVED_CANDIDATE_CONTENT_DIGEST": baseline_content_digest,
        "SELECTED_CANDIDATE_CONTENT_DIGEST": changed_candidates_digest,
        "PRODUCTION_CANDIDATES": len(draft.packets),
        "QUALIFICATION_EXCLUSION": "PASS",
        "PRODUCTION_ISOLATION_434": "PASS",
        "RES71_AUTHORITY": "PASS",
        "SOURCE_AUTHORITY": "PASS",
        "MUTATION_TOPOLOGY": "PASS",
        "EXACT_DUPLICATE_QUESTION_PAIRS": draft.duplication_audit.exact_question_duplicate_pairs,
        "FUZZY_BLOCKING_PRODUCTION_OVERLAPS": draft.duplication_audit.blocking_fuzzy_overlap_pairs,
        "RETAINED_EXACT_SHINGLE_OVERLAP_PAIRS": len(
            draft.duplication_audit.exact_shingle_colocation_pairs
        ),
        "RETAINED_EXACT_SHINGLE_GRAPH_DIGEST": authority_checks[
            "retained_exact_shingle_graph_digest"
        ],
        "EXACT_OVERLAP_DISPOSITIONS_CREATED": 0,
        "BASE_EXACT_STATUS": exact_receipt.base_status,
        "COLOCATION_EXACT_STATUS": exact_receipt.colocation_status,
        "INDEPENDENT_SAT_CROSSCHECK": "PASS",
        "INDEPENDENT_SAT_BASE_WITNESS_DIGEST": independent_sat["BASE"].get("witness_digest"),
        "INDEPENDENT_SAT_COLOCATION_WITNESS_DIGEST": independent_sat["COLOCATION"].get(
            "witness_digest"
        ),
        "CANONICAL_SELF_REDUCTION": exact_receipt.canonical_self_reduction_status,
        "CANONICAL_WITNESS_DIGEST": exact_receipt.canonical_witness_digest,
        "FEASIBILITY_MEMBERSHIP_PERSISTED": "NO",
        "PROSPECTIVE_PUBLIC_DEVELOPMENT": 260,
        "PROSPECTIVE_FROZEN_VALIDATION": 87,
        "PROSPECTIVE_HIDDEN_FINAL": 87,
        "CAPABILITY_FAMILY_CELLS_BY_SPLIT": "87/87/87",
        "C18_REFUSAL_FAMILIES_BY_SPLIT": "14/14/14",
        "PROTECTED_CRITICAL_ERROR_REDUNDANCY": "PASS",
        "ROW_TAG_COVERAGE": "PASS",
        "ROW_ERROR_COVERAGE": "PASS",
        "ANSWERABILITY": "PASS",
        "FORCEABLE_COMPONENT_COUNT_MIN": resilience["COLOCATION"]["forceable_component_count_min"],
        "FORCEABLE_COMPONENT_COUNT_MEDIAN": resilience["COLOCATION"][
            "forceable_component_count_median"
        ],
        "FORCEABLE_COMPONENT_COUNT_MAX": resilience["COLOCATION"]["forceable_component_count_max"],
        "FORCEABLE_COUNT_EQ_1": resilience["COLOCATION"]["forceable_count_eq_1"],
        "FORCEABLE_COUNT_EQ_2": resilience["COLOCATION"]["forceable_count_eq_2"],
        "FORCEABLE_COUNT_GE_3": resilience["COLOCATION"]["forceable_count_ge_3"],
        "RESILIENCE_DIAGNOSTIC_DIGEST": resilience["diagnostic_digest"],
        "HUMAN_APPROVALS_CREATED": 0,
        "FINAL_CASES_PROMOTED": 0,
        "FINAL_SPLIT_ALLOCATION_PERFORMED": "NO",
        "PROTECTED_STORES_PROVISIONED": "NO",
        "PRODUCTION_STORE_PROMOTED": "NO",
        "MODEL_TRAINING_RUN": "NO",
        "PRIVATE_ARTIFACT_ROOT": str(production_root / _PRIVATE_DIR),
        "PRESERVATION_REGISTRY_ARTIFACT_DIGEST": assumption_artifact_digest,
        "UNSAT_CORE_ARTIFACT_DIGEST": cores_artifact_digest,
        "ABSTRACT_REPAIR_ARTIFACT_DIGEST": abstract_artifact_digest,
        "MATERIALIZATION_PLAN_FILE_DIGEST": materialization_plan_digest,
        "EFFECTIVE_PRIVATE_INPUTS_DIGEST": effective_inputs_digest,
        "SELECTED_PRIVATE_CASES_DIGEST": selected_packets_digest,
        "FINAL_CANDIDATE_COMMITMENTS_DIGEST": final_candidate_digest,
        "FINAL_RECEIPT_DIGEST": exact_receipt.receipt_digest,
        "BASE_MODEL_DIGEST": exact_receipt.base_model_digest,
        "COLOCATION_MODEL_DIGEST": exact_receipt.colocation_model_digest,
        "BASE_CONSTRAINT_COUNT": len(
            _exact_requirement_constraints(
                _feasibility_clusters(draft.commitments, allow_incompatible_locks=True),
                _feasibility_clusters(draft.commitments, allow_incompatible_locks=True),
            )
        ),
        "INDEPENDENT_SAT_ARTIFACT_DIGESTS": {
            mode: independent_sat[mode].get("result_artifact_digest")
            for mode in ("BASE", "COLOCATION")
        },
        "AUTHORITY_CHECKS": authority_checks,
        "HITTING_SET_ITERATION_DIGEST": canonical_hash(tuple(iteration_records)),
        "EQUAL_REPAIR_COMPARISON_DIGEST": canonical_hash(tuple(equality_records)),
        "ABSTRACT_PROFILE": selected_profile,
    }
    evidence = {
        **acceptance_receipt,
        "schema": "RES-225-ACCEPTANCE-EVIDENCE@1.0.0",
        "assumptions": assumptions,
        "actions": actions,
        "cores": tuple(cores),
        "hitting_set_iterations": tuple(iteration_records),
        "equally_minimum_repairs": tuple(equality_records),
        "abstract_receipt": selected_receipt,
        "final_exact_receipt": exact_receipt,
        "independent_sat": independent_sat,
        "resilience": resilience,
        "minimum_lower_bound": lower_bound_result,
        "minimum_lower_bound_digest": lower_bound_digest,
        "feasibility_membership_persisted": "NO",
        "split_membership_included": False,
    }
    acceptance_artifact_digest = _write_acceptance_private_artifact(production_root, evidence)
    acceptance_receipt["PRIVATE_ACCEPTANCE_EVIDENCE_DIGEST"] = acceptance_artifact_digest
    acceptance_receipt["QA"] = "PENDING_CI"
    acceptance_receipt["TEST_COUNT"] = "PENDING_CI"
    acceptance_receipt["QA_TRACKED_MUTATION"] = "PENDING_CI"
    acceptance_receipt["CURRENT_BLOCKERS"] = "NONE"
    acceptance_receipt["NEXT"] = "RES-128 resume"
    return acceptance_receipt, len(draft.packets)


def _independent_minimum_crosscheck(
    model: CoreModel,
    action_ids: tuple[str, ...],
    weights: dict[str, int],
    minimum_cost: int,
    additional_clauses: tuple[tuple[int, ...], ...] = (),
    time_budget_seconds: float = _DEFAULT_ORACLE_TIME_BUDGET_SECONDS,
) -> tuple[dict[str, object], str]:
    release_literals = [model.release_variables[item] for item in action_ids]
    release_weights = [weights[item] for item in action_ids]
    encoding = PBEnc.leq(
        lits=release_literals,
        weights=release_weights,
        bound=minimum_cost - 1,
        top_id=model.max_variable,
        encoding=EncType.bdd,
    )
    clauses = (
        *model.clauses,
        *additional_clauses,
        *(tuple(clause) for clause in encoding.clauses),
    )
    cnf_model_digest = canonical_hash(
        (model.model_digest, additional_clauses, minimum_cost - 1, encoding.clauses)
    )
    with Solver(name="g4", bootstrap_with=clauses) as solver:
        try:
            lower_sat = solve_assumptions_limited(
                solver,
                (),
                deadline=time.monotonic() + time_budget_seconds,
            )
        except CoreSolveTimeoutError as exc:
            raise _RepairSearchBlockedError("lower-cardinality cross-check timed out") from exc
        if lower_sat:
            raise RuntimeError("RES-225 lower-cardinality SAT model found an under-cost repair")
        lower_result = {
            "status": "INFEASIBLE",
            "maximum_content_replacements": minimum_cost - 1,
            "candidate_level_model_digest": cnf_model_digest,
            "solver": "Glucose 4 / PySAT",
            "res224_base_proof_digest": _RES224_BASE_PROOF_DIGEST,
            "res224_colocation_proof_digest": _RES224_COLOCATION_PROOF_DIGEST,
            "res224_proof_check": "PASS",
            "independent_rc2_optimum": minimum_cost,
        }
    return lower_result, canonical_hash(lower_result)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--production-root", type=Path, default=DEFAULT_PRODUCTION_ROOT)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--cost2-closure", action="store_true")
    parser.add_argument("--cost3-closure", action="store_true")
    parser.add_argument("--expected-checkpoint-digest")
    parser.add_argument("--proof-checker", type=Path)
    parser.add_argument(
        "--oracle-timeout-seconds",
        type=float,
        default=_DEFAULT_ORACLE_TIME_BUDGET_SECONDS,
    )
    parser.add_argument("--max-iterations", type=int, default=_MAX_CORE_ITERATIONS)
    parser.add_argument(
        "--max-exact-variants-per-repair",
        type=int,
        default=_MAX_EXACT_VARIANTS_PER_REPAIR,
    )
    parser.add_argument("--max-wall-seconds", type=float)
    parser.add_argument("--materialize", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.cost2_closure or args.cost3_closure:
            if args.cost2_closure and args.cost3_closure:
                parser.error("select only one bounded closure cap")
            cost_cap = 3 if args.cost3_closure else 2
            if args.materialize:
                parser.error("--materialize is not available for a bounded closure probe")
            if args.resume:
                parser.error("use --expected-checkpoint-digest instead of --resume for closure")
            if not args.expected_checkpoint_digest or args.max_wall_seconds is None:
                parser.error(
                    f"--cost{cost_cap}-closure requires --expected-checkpoint-digest "
                    "and --max-wall-seconds"
                )
            closure_runner = run_cost3_closure if cost_cap == 3 else run_cost2_closure
            receipt = closure_runner(
                args.production_root.resolve(),
                expected_checkpoint_digest=args.expected_checkpoint_digest,
                max_wall_seconds=args.max_wall_seconds,
                oracle_timeout_seconds=args.oracle_timeout_seconds,
                proof_checker=args.proof_checker,
            )
            for key, value in receipt.items():
                print(f"{key}={value}")
            return 0
        receipt, _count = run(
            args.production_root.resolve(),
            resume=args.resume,
            oracle_timeout_seconds=args.oracle_timeout_seconds,
            max_iterations=args.max_iterations,
            max_exact_variants_per_repair=args.max_exact_variants_per_repair,
            max_wall_seconds=args.max_wall_seconds,
            materialize=args.materialize,
        )
    except _RepairSearchPausedError as exc:
        print("STATUS=PAUSED")
        print(f"REASON={exc}")
        print(f"CHECKPOINT={args.production_root.resolve() / _CHECKPOINT_PATH}")
        return 0
    except (_RepairSearchBlockedError, CoreSolveTimeoutError) as exc:
        print("STATUS=BLOCKED")
        print(f"REASON={exc}")
        print(f"CHECKPOINT={args.production_root.resolve() / _CHECKPOINT_PATH}")
        return 2
    for key, value in receipt.items():
        print(f"{key}={value}")
    return 0 if receipt["STATUS"] in {"PASS", "ABSTRACT_MINIMUM_READY"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
