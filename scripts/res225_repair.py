"""Diagnose, prove, and materialize the minimum RES-225 candidate repair."""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
import threading
import time
from collections import Counter
from pathlib import Path
from typing import Any, cast

from pysat.examples.hitman import Hitman  # type: ignore[import-untyped]
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
    write_external_production_json,
)
from dynamislm.benchmark.res223_topology import allocation_resilience_summary
from dynamislm.benchmark.res225_repair import (
    CoreModel,
    CoreSolveTimeoutError,
    PreservationAssumption,
    RepairAction,
    RES225RepairCheckpointV1,
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
_EQUAL_REPAIR_LIMIT = 32
_MAX_CORE_ITERATIONS = 500
_MAX_EXACT_VARIANTS_PER_REPAIR = 16
_DEFAULT_ORACLE_TIME_BUDGET_SECONDS = 300.0
_CoreRecord = dict[str, Any]


class _CapturedExactCallError(Exception):
    pass


class _RepairSearchBlockedError(RuntimeError):
    pass


def _progress(message: str) -> None:
    print(f"RES225_PROGRESS {message}", file=sys.stderr, flush=True)


def _emit_iteration(
    *,
    iteration: int,
    elapsed_seconds: float,
    cores_discovered: int,
    last_core_size: int | None,
    last_minimized_core_size: int | None,
    hitting_set_size: int,
    best_repair_cardinality: int | None,
    oracle_calls: int,
    last_oracle_status: str,
    last_oracle_seconds: float,
    phase: str,
) -> None:
    _progress(
        " ".join(
            (
                f"ITERATION={iteration}",
                f"ELAPSED={elapsed_seconds:.3f}",
                f"CORES_DISCOVERED={cores_discovered}",
                f"LAST_CORE_SIZE={last_core_size if last_core_size is not None else 'NONE'}",
                "LAST_MINIMIZED_CORE_SIZE="
                f"{last_minimized_core_size if last_minimized_core_size is not None else 'NONE'}",
                f"CURRENT_HITTING_SET_SIZE={hitting_set_size}",
                "BEST_REPAIR_CARDINALITY="
                f"{best_repair_cardinality if best_repair_cardinality is not None else 'NONE'}",
                f"ORACLE_CALLS={oracle_calls}",
                f"LAST_ORACLE_STATUS={last_oracle_status}",
                f"LAST_ORACLE_SECONDS={last_oracle_seconds:.3f}",
                f"CURRENT_PHASE={phase}",
            )
        )
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
    if isinstance(value, dict):
        return {str(key): _checkpoint_plain(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_checkpoint_plain(item) for item in value]
    return value


def _checkpoint_bind(payload: dict[str, Any]) -> dict[str, Any]:
    body = _checkpoint_plain(
        {key: value for key, value in payload.items() if key != "checkpoint_digest"}
    )
    return {**body, "checkpoint_digest": canonical_hash(body)}


def _validate_checkpoint(
    checkpoint: object,
    *,
    expected_fingerprints: dict[str, str],
) -> dict[str, Any]:
    if not isinstance(checkpoint, dict):
        raise ValueError("RES-225 checkpoint must be a JSON object")
    checkpoint = cast(dict[str, Any], checkpoint)
    if checkpoint.get("schema") != "RES-225-REPAIR-CHECKPOINT@1.0.0" or checkpoint.get(
        "checkpoint_digest"
    ) != canonical_hash(
        {key: value for key, value in checkpoint.items() if key != "checkpoint_digest"}
    ):
        raise ValueError("RES-225 checkpoint schema/digest validation failed")
    if checkpoint.get("fingerprints") != expected_fingerprints:
        raise ValueError("RES-225 checkpoint is stale against the sealed repair inputs")
    for key in (
        "cores",
        "iteration_records",
        "exact_core_evidence",
        "excluded_exact_designs",
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
    return checkpoint


def _write_checkpoint(production_root: Path, state: dict[str, Any]) -> str:
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
    payload = _checkpoint_bind({"schema": "RES-225-REPAIR-CHECKPOINT@1.0.0", **encoded_state})
    return _private_write(
        production_root,
        _CHECKPOINT_PATH,
        RES225RepairCheckpointV1("RES-225-REPAIR-CHECKPOINT@1.0.0", payload),
    )


def _read_checkpoint(
    production_root: Path,
    *,
    expected_fingerprints: dict[str, str],
) -> tuple[dict[str, Any], str]:
    wrapper, digest, _size = read_external_production_json(
        _CHECKPOINT_PATH,
        RES225RepairCheckpointV1,
        repository_root=_REPOSITORY_ROOT,
        production_root=production_root,
    )
    if wrapper.schema != "RES-225-REPAIR-CHECKPOINT@1.0.0":
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
    return checkpoint, digest


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
) -> tuple[list[_CoreRecord], dict[str, Any]]:
    records: list[_CoreRecord] = [dict(item) for item in completed_records]
    completed_modes = {str(item["mode"]) for item in records}
    solvers: dict[str, Any] = {}
    for mode in ("BASE", "COLOCATION"):
        deadline = time.monotonic() + oracle_timeout_seconds
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
) -> Any:
    hitman = Hitman(htype="rc2", solver="g3")
    for core in cores:
        action_ids = tuple(core["action_ids"])
        if not action_ids:
            hitman.delete()
            raise RuntimeError("RES-225 discovered an UNSAT core with no authorized repair action")
        hitman.hit(action_ids, weights=weights)

    return hitman


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
) -> tuple[tuple[str, ...], int]:
    core_sets = tuple(tuple(item["action_ids"]) for item in cores)
    formula, variable_by_action = _new_wcnf(action_ids, core_sets, weights)
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
            tuple(blocked),
        )
        with RC2(formula, solver="g3") as rc2:
            model = _run_rc2_limited(rc2, rc2.compute, time_budget_seconds)
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
    if "UNKNOWN" in statuses or receipt.status == "BLOCKED":
        return "UNKNOWN"
    if statuses == ("FEASIBLE", "FEASIBLE") and receipt.status == "FEASIBLE":
        return "FEASIBLE"
    if "INFEASIBLE" in statuses:
        return "INFEASIBLE"
    return "UNKNOWN"


def _exact_repair_variant(
    commitments: tuple[ProductionCandidateCommitmentV1, ...],
    pairs: tuple[tuple[str, str], ...],
    actions: tuple[RepairAction, ...],
    selected_action_ids: tuple[str, ...],
    *,
    target_parent_by_action: dict[str, str],
    candidate_rank_hint: dict[str, int],
    time_budget_seconds: float,
) -> tuple[
    str,
    Any,
    tuple[ProductionCandidateCommitmentV1, ...],
    tuple[tuple[str, str], ...],
    float,
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
        canonical_progress_callback=canonical_progress,
    )
    return (
        _exact_state(receipt),
        receipt,
        abstract_commitments,
        abstract_pairs,
        time.monotonic() - started,
    )


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


def _repair_score(
    selected: tuple[str, ...],
    actions_by_id: dict[str, RepairAction],
    profile: dict[str, int],
    target_parent_by_action: dict[str, str],
) -> tuple[object, ...]:
    mutation_children = sum(
        sum(
            placeholder.origin_class == CaseOrigin.ADVERSARIAL_MUTATION.value
            for placeholder in actions_by_id[action_id].placeholders
        )
        for action_id in selected
    )
    return (
        -profile["minimum_cell_eligible_component_count"],
        -profile["total_cell_eligible_component_count"],
        -profile["colocation_component_count"],
        -profile["base_component_count"],
        mutation_children,
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
        forced = list(assumptions)
        target_map: dict[str, str] = {}
        for action_id, target_by_id in sorted(model.target_variables.items()):
            if action_id not in selected:
                continue
            for target_id, target_literal in sorted(target_by_id.items()):
                try:
                    target_sat = solve_assumptions_limited(
                        solver,
                        (*forced, target_literal),
                        deadline=deadline,
                    )
                except CoreSolveTimeoutError:
                    return "UNKNOWN", (), {}, {}, 0, 0, time.monotonic() - started
                if target_sat:
                    target_map[action_id] = target_id
                    forced.append(target_literal)
                    break
            else:
                raise RuntimeError("RES-225 could not canonicalize a satisfiable target assignment")
        selected_literals = {literal for literal in solver.get_model() if literal > 0}
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


def run(
    production_root: Path,
    *,
    resume: bool = False,
    oracle_timeout_seconds: float = _DEFAULT_ORACLE_TIME_BUDGET_SECONDS,
    max_iterations: int = _MAX_CORE_ITERATIONS,
    max_exact_variants_per_repair: int = _MAX_EXACT_VARIANTS_PER_REPAIR,
) -> tuple[dict[str, object], int]:
    if production_root.resolve().is_relative_to(_REPOSITORY_ROOT.resolve()):
        raise ValueError("RES-225 private artifacts must remain outside Git")
    if oracle_timeout_seconds <= 0 or max_iterations <= 0 or max_exact_variants_per_repair <= 0:
        raise ValueError("RES-225 search budgets must be positive")
    checkpoint_path = production_root / _CHECKPOINT_PATH
    if checkpoint_path.exists() and not resume:
        raise _RepairSearchBlockedError("RES-225 checkpoint exists; resume it explicitly")
    if resume and not checkpoint_path.is_file():
        raise ValueError("RES-225 --resume requested but no private checkpoint exists")

    run_started = time.monotonic()
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

    if resume:
        saved, _checkpoint_file_digest = _read_checkpoint(
            production_root,
            expected_fingerprints=fingerprints,
        )
        cores = [dict(item) for item in saved["cores"]]
        iteration_records = [dict(item) for item in saved["iteration_records"]]
        exact_core_evidence = [dict(item) for item in saved["exact_core_evidence"]]
        excluded_exact_designs = [dict(item) for item in saved["excluded_exact_designs"]]
        tested_repairs = [dict(item) for item in saved["tested_repairs"]]
        equality_records = [dict(item) for item in saved["equality_records"]]
        variant_counts = dict(saved.get("variant_counts", {}))
        oracle_status_counts.update(saved.get("oracle_status_counts", {}))
        oracle_calls = int(saved["oracle_calls"])
        iteration = int(saved["iteration"])
        initial_core_count = int(saved.get("initial_core_count", 0))
        elapsed_before = float(saved["elapsed_seconds"])
        last_core_size = saved.get("last_core_size")
        last_minimized_core_size = saved.get("last_minimized_core_size")
        last_oracle_status = str(saved.get("last_oracle_status", "UNKNOWN"))
        last_oracle_seconds = float(saved.get("last_oracle_seconds", 0.0))
        incumbent_value = saved.get("incumbent")
        if incumbent_value is not None:
            if not isinstance(incumbent_value, dict):
                raise ValueError("RES-225 checkpoint incumbent is malformed")
            incumbent = dict(incumbent_value)
    else:
        initial_core_count = 0

    def elapsed() -> float:
        return elapsed_before + time.monotonic() - run_started

    def save_checkpoint(
        phase: str,
        *,
        current_action_ids: tuple[str, ...] = (),
        current_target_map: dict[str, str] | None = None,
        current_cost: int | None = None,
    ) -> str:
        nonlocal current_phase
        state = {
            "fingerprints": fingerprints,
            "cores": tuple(cores),
            "initial_core_count": initial_core_count,
            "iteration_records": tuple(iteration_records),
            "exact_core_evidence": tuple(exact_core_evidence),
            "excluded_exact_designs": tuple(excluded_exact_designs),
            "tested_repairs": tuple(tested_repairs),
            "equality_records": tuple(equality_records),
            "variant_counts": variant_counts,
            "iteration": iteration,
            "elapsed_seconds": elapsed(),
            "oracle_calls": oracle_calls,
            "oracle_status_counts": dict(oracle_status_counts),
            "last_core_size": last_core_size,
            "last_minimized_core_size": last_minimized_core_size,
            "last_oracle_status": last_oracle_status,
            "last_oracle_seconds": last_oracle_seconds,
            "phase": phase,
            "current_hitting_set_action_ids": current_action_ids,
            "current_hitting_set_size": len(current_action_ids),
            "current_hitting_set_cost": current_cost,
            "current_target_parent_by_action": current_target_map or {},
            "best_repair_cardinality": (
                incumbent["cardinality"] if incumbent is not None else None
            ),
            "incumbent": incumbent,
            "hitman_core_registry_digest": canonical_hash(
                tuple(tuple(item["action_ids"]) for item in cores)
            ),
            "production_store_promoted": "NO",
            "feasibility_membership_persisted": "NO",
        }
        digest = _write_checkpoint(production_root, state)
        current_phase = phase
        _progress(f"CHECKPOINT phase={phase} digest={digest}")
        return digest

    def emit(iteration_action_ids: tuple[str, ...] = (), cost: int = 0) -> None:
        _emit_iteration(
            iteration=iteration,
            elapsed_seconds=elapsed(),
            cores_discovered=len(cores),
            last_core_size=last_core_size,
            last_minimized_core_size=last_minimized_core_size,
            hitting_set_size=len(iteration_action_ids),
            best_repair_cardinality=(
                int(incumbent["cardinality"]) if incumbent is not None else None
            ),
            oracle_calls=oracle_calls,
            last_oracle_status=last_oracle_status,
            last_oracle_seconds=last_oracle_seconds,
            phase=current_phase,
        )

    if resume:
        completed_initial = tuple(cores[:initial_core_count])
        later_cores = cores[initial_core_count:]
    else:
        completed_initial = ()
        later_cores = []

    def initial_core_checkpoint(records: tuple[_CoreRecord, ...], _mode: str) -> None:
        nonlocal cores, initial_core_count, last_core_size, last_minimized_core_size
        initial_records = [dict(item) for item in records]
        cores = initial_records + later_cores
        initial_core_count = len(initial_records)
        latest = initial_records[-1]
        last_core_size = int(latest["raw_assumption_core_size"])
        last_minimized_core_size = int(latest["minimized_assumption_core_size"])
        save_checkpoint("INITIAL_CORE_MINIMIZED")

    if resume and not completed_initial and cores:
        raise ValueError("RES-225 checkpoint core ordering is invalid")
    if not resume:
        save_checkpoint("INITIAL_CORE_EXTRACTION")
    initial_records, core_solvers = _initial_cores(
        models,
        oracle_timeout_seconds=oracle_timeout_seconds,
        completed_records=completed_initial,
        on_core=initial_core_checkpoint,
    )
    initial_core_count = len(initial_records)
    if not resume:
        cores = list(initial_records)
    else:
        cores = list(initial_records) + list(later_cores)
    _replay_exact_exclusions(excluded_exact_designs, models, core_solvers)

    hitman = _hitman_from_cores(cores, weights)
    tested_variants: dict[
        tuple[str, ...],
        tuple[
            dict[str, str],
            Any,
            tuple[ProductionCandidateCommitmentV1, ...],
            tuple[tuple[str, str], ...],
        ],
    ] = {}
    tested_status: dict[tuple[str, ...], str] = {}
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
            tested_variants[repair_ids] = (
                target_map,
                receipt,
                abstract_commitments,
                abstract_pairs,
            )

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
    ) -> tuple[str, Any, tuple[ProductionCandidateCommitmentV1, ...], tuple[tuple[str, str], ...]]:
        nonlocal oracle_calls, last_oracle_status, last_oracle_seconds
        save_checkpoint(
            "EXACT_ORACLE_PENDING",
            current_action_ids=repair_ids,
            current_target_map=target_map,
            current_cost=current_cost,
        )
        state, receipt, abstract_commitments, abstract_pairs, exact_seconds = _exact_repair_variant(
            commitments,
            pairs,
            actions,
            repair_ids,
            target_parent_by_action=target_map,
            candidate_rank_hint=rank_hint,
            time_budget_seconds=oracle_timeout_seconds,
        )
        oracle_calls += 1
        oracle_status_counts[state] += 1
        last_oracle_status = {"FEASIBLE": "SAT", "INFEASIBLE": "UNSAT", "UNKNOWN": "UNKNOWN"}[state]
        last_oracle_seconds = exact_seconds
        _progress(
            f"EXACT_ORACLE status={state} seconds={exact_seconds:.3f} "
            f"repair={canonical_hash(repair_ids)} phase={phase}"
        )
        return state, receipt, abstract_commitments, abstract_pairs

    if incumbent is None:
        save_checkpoint("CORE_GUIDED_READY")
        while True:
            if iteration >= max_iterations:
                block_unknown("BLOCKED_ITERATION_LIMIT")
            proposed = _hitman_solution(hitman, weights, oracle_timeout_seconds)
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
                time_budget_seconds=oracle_timeout_seconds,
            )
            oracle_calls += 1
            oracle_status_counts[candidate_status] += 1
            last_oracle_status = candidate_status
            last_oracle_seconds = time.monotonic() - candidate_started
            record: dict[str, object] = {
                "iteration": iteration,
                "hitting_set_action_ids": proposed,
                "hitting_set_digest": canonical_hash(proposed),
                "minimum_content_replacement_cost": proposed_cost,
                "core_count_before_solve": len(cores),
                "candidate_level_exact_model_status": candidate_status,
                "candidate_oracle_seconds": last_oracle_seconds,
            }
            if candidate_status == "UNKNOWN":
                block_unknown(
                    "BLOCKED_CANDIDATE_MODEL_TIMEOUT", proposed, target_map, proposed_cost
                )
            if candidate_status == "UNSAT":
                last_core_size = raw_core_size
                last_minimized_core_size = minimized_core_size
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
                try:
                    _append_unique_core(cores, core_record)
                except RuntimeError:
                    block_unknown("BLOCKED_DUPLICATE_CORE_NO_PROGRESS", proposed, {}, proposed_cost)
                hitman.hit(core_action_ids, weights=weights)
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
            if attempt_count >= max_exact_variants_per_repair:
                block_unknown("BLOCKED_EXACT_VARIANT_LIMIT", proposed, target_map, proposed_cost)
            state, receipt, abstract_commitments, abstract_pairs = exact_attempt(
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
                    }
                )
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

            _require_abstract_feasible(receipt)
            selected_profile = _repair_profile(abstract_commitments, abstract_pairs)
            incumbent = {
                "action_ids": proposed,
                "target_parent_by_action": target_map,
                "cardinality": proposed_cost,
                "repair_digest": canonical_hash(proposed),
                "abstract_receipt": receipt,
                "abstract_witness_digest": receipt.canonical_witness_digest,
                "secondary_profile": selected_profile,
            }
            tested_repairs.append(
                {
                    "action_ids": proposed,
                    "target_parent_by_action": target_map,
                    "status": "FEASIBLE",
                    "receipt": receipt,
                    "secondary_profile": selected_profile,
                }
            )
            tested_variants[proposed] = (
                target_map,
                receipt,
                abstract_commitments,
                abstract_pairs,
            )
            tested_status[proposed] = "FEASIBLE"
            record.update(
                {
                    "exact_target_parent_by_action": target_map,
                    "abstract_base_status": receipt.base_status,
                    "abstract_colocation_status": receipt.colocation_status,
                    "abstract_canonical_witness_digest": receipt.canonical_witness_digest,
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
    _require_abstract_feasible(selected_receipt)

    equal_sets, equal_sets_complete = _enumerate_minimum_hit_sets(
        action_ids,
        cores,
        weights,
        minimum_cost=minimum_cost,
        limit=_EQUAL_REPAIR_LIMIT,
        include=selected_repair,
        time_budget_seconds=oracle_timeout_seconds,
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
    for repair_ids, cached in tested_variants.items():
        if canonical_hash(repair_ids) not in compared_digests:
            continue
        target_map, receipt, abstract_commitments, abstract_pairs = cached
        profile = _repair_profile(abstract_commitments, abstract_pairs)
        score = _repair_score(repair_ids, action_by_id, profile, target_map)
        feasible_ties.append((score, repair_ids, target_map, receipt, profile))
    for repair_ids in equal_sets:
        repair_digest = canonical_hash(repair_ids)
        if repair_digest in compared_digests:
            continue
        tie_candidate_status = tested_status.get(repair_ids)
        variants: list[
            tuple[
                dict[str, str],
                Any,
                tuple[ProductionCandidateCommitmentV1, ...],
                tuple[tuple[str, str], ...],
            ]
        ] = []
        tested_maps: list[dict[str, str]] = []
        if tie_candidate_status == "FEASIBLE":
            cached = tested_variants[repair_ids]
            variants = [cached]
            tested_maps = [cached[0]]
        elif tie_candidate_status != "CANDIDATE_UNSAT":
            tie_attempts = 0
            while tie_attempts < max_exact_variants_per_repair:
                if iteration >= max_iterations:
                    block_unknown("BLOCKED_ITERATION_LIMIT", repair_ids, {}, minimum_cost)
                iteration += 1
                candidate_started = time.monotonic()
                (
                    tie_status,
                    tie_core,
                    tie_target_map,
                    tie_rank_hint,
                    raw_core_size,
                    minimized_core_size,
                    _candidate_seconds,
                ) = _core_hit_set_is_sat(
                    core_solvers["COLOCATION"],
                    models["COLOCATION"],
                    repair_ids,
                    time_budget_seconds=oracle_timeout_seconds,
                )
                oracle_calls += 1
                oracle_status_counts[tie_status] += 1
                last_oracle_status = tie_status
                last_oracle_seconds = time.monotonic() - candidate_started
                if tie_status == "UNKNOWN":
                    block_unknown("BLOCKED_TIE_CANDIDATE_TIMEOUT", repair_ids, {}, minimum_cost)
                if tie_status == "UNSAT":
                    tested_status[repair_ids] = "CANDIDATE_UNSAT"
                    tested_repairs.append(
                        {
                            "action_ids": repair_ids,
                            "status": "CANDIDATE_UNSAT",
                            "raw_core_size": raw_core_size,
                            "minimized_core_size": minimized_core_size,
                        }
                    )
                    save_checkpoint(
                        "MINIMUM_REPAIR_CANDIDATE_UNSAT",
                        current_action_ids=repair_ids,
                        current_cost=minimum_cost,
                    )
                    break
                candidate_digest = canonical_hash(repair_ids)
                used = variant_counts.get(candidate_digest, 0)
                if used >= max_exact_variants_per_repair:
                    block_unknown(
                        "BLOCKED_TIE_VARIANT_LIMIT", repair_ids, tie_target_map, minimum_cost
                    )
                save_checkpoint(
                    "TIE_EXACT_ORACLE_PENDING",
                    current_action_ids=repair_ids,
                    current_target_map=tie_target_map,
                    current_cost=minimum_cost,
                )
                state, receipt, abstract_commitments, abstract_pairs, exact_seconds = (
                    _exact_repair_variant(
                        commitments,
                        pairs,
                        actions,
                        repair_ids,
                        target_parent_by_action=tie_target_map,
                        candidate_rank_hint=tie_rank_hint,
                        time_budget_seconds=oracle_timeout_seconds,
                    )
                )
                oracle_calls += 1
                oracle_status_counts[state] += 1
                last_oracle_status = {
                    "FEASIBLE": "SAT",
                    "INFEASIBLE": "UNSAT",
                    "UNKNOWN": "UNKNOWN",
                }[state]
                last_oracle_seconds = exact_seconds
                tested_maps.append(tie_target_map)
                if state == "UNKNOWN":
                    tested_repairs.append(
                        {
                            "action_ids": repair_ids,
                            "target_parent_by_action": tie_target_map,
                            "status": "UNKNOWN_VARIANT",
                        }
                    )
                    block_unknown(
                        "BLOCKED_TIE_EXACT_UNKNOWN", repair_ids, tie_target_map, minimum_cost
                    )
                variant_counts[candidate_digest] = used + 1
                if state == "INFEASIBLE":
                    exact_exclusion = _exact_variant_exclusion_record(
                        models,
                        repair_ids,
                        tie_target_map,
                        receipt,
                    )
                    try:
                        _append_unique_exact_exclusion(excluded_exact_designs, exact_exclusion)
                    except RuntimeError:
                        block_unknown(
                            "BLOCKED_DUPLICATE_TIE_VARIANT",
                            repair_ids,
                            tie_target_map,
                            minimum_cost,
                        )
                    for solver in core_solvers.values():
                        solver.add_clause(list(exact_exclusion["blocking_clause"]))
                    exact_core_evidence.append(
                        {"schema": "RES-225-EXACT-DESIGN-NO-GOOD@1", **exact_exclusion}
                    )
                    tested_repairs.append(
                        {
                            "action_ids": repair_ids,
                            "target_parent_by_action": tie_target_map,
                            "status": "EXACT_INFEASIBLE_VARIANT",
                            "receipt_digest": receipt.receipt_digest,
                        }
                    )
                    save_checkpoint(
                        "TIE_EXACT_VARIANT_EXCLUDED",
                        current_action_ids=repair_ids,
                        current_target_map=tie_target_map,
                        current_cost=minimum_cost,
                    )
                    emit(repair_ids, minimum_cost)
                    tie_attempts += 1
                    continue
                _require_abstract_feasible(receipt)
                profile = _repair_profile(abstract_commitments, abstract_pairs)
                variants = [(tie_target_map, receipt, abstract_commitments, abstract_pairs)]
                tested_variants[repair_ids] = variants[0]
                tested_status[repair_ids] = "FEASIBLE"
                tested_repairs.append(
                    {
                        "action_ids": repair_ids,
                        "target_parent_by_action": tie_target_map,
                        "status": "FEASIBLE",
                        "receipt": receipt,
                        "secondary_profile": profile,
                    }
                )
                save_checkpoint(
                    "TIE_REPAIR_FEASIBLE",
                    current_action_ids=repair_ids,
                    current_target_map=tie_target_map,
                    current_cost=minimum_cost,
                )
                tie_attempts += 1
                break
            if not variants and tested_status.get(repair_ids) != "CANDIDATE_UNSAT":
                block_unknown("BLOCKED_TIE_VARIANT_LIMIT", repair_ids, {}, minimum_cost)
        variant_records: list[dict[str, object]] = []
        for target_map, receipt, abstract_commitments, abstract_pairs in variants:
            profile = _repair_profile(abstract_commitments, abstract_pairs)
            score = _repair_score(repair_ids, action_by_id, profile, target_map)
            feasible_ties.append((score, repair_ids, target_map, receipt, profile))
            variant_records.append(
                {
                    "target_parent_by_action": target_map,
                    "abstract_base_status": receipt.base_status,
                    "abstract_colocation_status": receipt.colocation_status,
                    "abstract_canonical_witness_digest": receipt.canonical_witness_digest,
                    "secondary_profile": profile,
                    "secondary_score_digest": canonical_hash(score),
                }
            )
        equality_records.append(
            {
                "repair_action_ids": repair_ids,
                "repair_digest": repair_digest,
                "content_replacement_count": sum(weights[item] for item in repair_ids),
                "target_variants_tested": len(tested_maps),
                "candidate_level_status": tested_status.get(repair_ids, "FEASIBLE"),
                "tested_target_parent_map_digests": tuple(
                    canonical_hash(item) for item in tested_maps
                ),
                "target_variant_results": tuple(variant_records),
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
            f"actions={len(repair_ids)} feasible={len(variants)}"
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
    _require_abstract_feasible(selected_receipt)
    minimum_cost = sum(weights[item] for item in selected_repair)
    hitman_selected = _hitman_solution(hitman, weights, oracle_timeout_seconds)
    hitman_cost = sum(weights[item] for item in hitman_selected)
    rc2_selected, rc2_cost = _rc2_optimum(
        action_ids,
        cores,
        weights,
        time_budget_seconds=oracle_timeout_seconds,
    )
    if hitman_cost != minimum_cost or rc2_cost != minimum_cost:
        block_unknown(
            "BLOCKED_MINIMUM_HITTING_SET_MISMATCH",
            selected_repair,
            selected_target_parent_by_action,
            minimum_cost,
        )

    additional_clauses = tuple(tuple(item["blocking_clause"]) for item in excluded_exact_designs)
    lower_bound_result, lower_bound_digest = _independent_minimum_crosscheck(
        models["COLOCATION"],
        action_ids,
        weights,
        minimum_cost,
        additional_clauses=additional_clauses,
        time_budget_seconds=oracle_timeout_seconds,
    )
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
            "hitman_selected": hitman_selected,
            "hitman_cost": hitman_cost,
            "rc2_selected": rc2_selected,
            "rc2_cost": rc2_cost,
            "minimum_cost": minimum_cost,
            "lower_bound_digest": lower_bound_digest,
            "lower_bound_result": lower_bound_result,
            "selected_repair_digest": selected_repair_digest,
            "abstract_witness_digest": selected_receipt.canonical_witness_digest,
        }
    )
    save_checkpoint(
        "MINIMUM_REPAIR_PROVEN",
        current_action_ids=selected_repair,
        current_target_map=selected_target_parent_by_action,
        current_cost=minimum_cost,
    )

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
        "MINIMUM_REPAIR_PROVEN": "YES",
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
    args = parser.parse_args(argv)
    try:
        receipt, _count = run(
            args.production_root.resolve(),
            resume=args.resume,
            oracle_timeout_seconds=args.oracle_timeout_seconds,
            max_iterations=args.max_iterations,
            max_exact_variants_per_repair=args.max_exact_variants_per_repair,
        )
    except (_RepairSearchBlockedError, CoreSolveTimeoutError) as exc:
        print("STATUS=BLOCKED")
        print(f"REASON={exc}")
        print(f"CHECKPOINT={args.production_root.resolve() / _CHECKPOINT_PATH}")
        return 2
    for key, value in receipt.items():
        print(f"{key}={value}")
    return 0 if receipt["STATUS"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
