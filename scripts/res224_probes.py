"""Run private, instrumented RES-224 exact-feasibility probes."""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import dynamislm.benchmark.production_authoring as authoring
from dynamislm.benchmark.constants import (
    CRITICAL_ERROR_CLASSES,
    ExpectedAnswerKind,
    RefusalDecision,
)
from dynamislm.benchmark.coverage import COVERAGE_MATRIX
from dynamislm.benchmark.production import (
    PRODUCTION_EXACT_SOLVER_CONFIG,
    ProductionCandidateCommitmentV1,
    _build_exact_cp_model,
    _canonical_split_ranks,
    _cluster_has_c18_refusal,
    _cluster_has_cell_obligation,
    _exact_aggregate_evidence,
    _exact_completion_status,
    _exact_cp_model_proto,
    _exact_model_digest,
    _exact_requirement_constraints,
    _ExactConstraint,
    _feasibility_clusters,
    _feasibility_row_eligible,
    _FeasibilityCluster,
    _row_by_capability,
    _split_lock_ranks,
    _validate_feasibility_item,
)
from dynamislm.benchmark.production_store import DEFAULT_PRODUCTION_ROOT
from dynamislm.serialization import canonical_hash

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_TIME_BUDGETS = (60, 300, 900, 3600)
_PROGRESSIVE_SECONDS = 300.0
_MULTIWORKER_SECONDS = 900.0


class _CapturedExactCallError(Exception):
    pass


def _sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _write_private(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _capture_current_commitments(
    production_root: Path,
) -> tuple[tuple[ProductionCandidateCommitmentV1, ...], tuple[tuple[str, str], ...]]:
    captured: dict[str, Any] = {}
    authoring_module: Any = authoring
    original: object = authoring_module.validate_production_exact_feasibility

    def capture(
        commitments: tuple[ProductionCandidateCommitmentV1, ...],
        *,
        exact_shingle_colocation_pairs: tuple[tuple[str, str], ...],
        **_kwargs: object,
    ) -> object:
        captured["commitments"] = commitments
        captured["pairs"] = exact_shingle_colocation_pairs
        raise _CapturedExactCallError

    state_paths = (
        production_root / "production/authoring_plan/private_inputs.json",
        production_root / "production/diagnostics/RES-223-repair-plan.private.json",
    )
    before = {path: _sha256(path.read_bytes()) for path in state_paths}
    authoring_module.validate_production_exact_feasibility = capture
    try:
        authoring.build_production_authoring_draft(
            repository_root=_REPOSITORY_ROOT,
            production_root=production_root,
            _diagnostic_only=True,
        )
    except _CapturedExactCallError:
        pass
    finally:
        authoring_module.validate_production_exact_feasibility = original
    after = {path: _sha256(path.read_bytes()) for path in state_paths}
    if before != after:
        raise RuntimeError("RES-224 reconstruction changed RES-223 private authoring state")
    if "commitments" not in captured or "pairs" not in captured:
        raise RuntimeError("RES-224 could not reconstruct the canonical commitments")
    commitments = tuple(captured["commitments"])
    pairs = tuple(captured["pairs"])
    if len(commitments) != 434 or len(pairs) != 81:
        raise RuntimeError("RES-224 reconstructed an unexpected benchmark population")
    for commitment in commitments:
        _validate_feasibility_item(commitment.item)
    return commitments, pairs


def _groups(constraints: tuple[_ExactConstraint, ...], *prefixes: str) -> frozenset[str]:
    return frozenset(
        item.group_id
        for item in constraints
        if any(item.group_id.startswith(prefix) for prefix in prefixes)
    )


def _constraint_digest(constraints: tuple[_ExactConstraint, ...]) -> str:
    return canonical_hash(
        tuple(
            (item.group_id, item.terms, item.lower, item.upper, item.equalities)
            for item in constraints
        )
    )


def _constraint_subset_digest(
    constraints: tuple[_ExactConstraint, ...], active_group_ids: frozenset[str]
) -> str:
    return _constraint_digest(
        tuple(item for item in constraints if item.group_id in active_group_ids)
    )


def _rank_map(
    components: tuple[_FeasibilityCluster, ...], ranks: tuple[int, ...]
) -> dict[str, int]:
    return {
        item.candidate_id: rank
        for component, rank in zip(components, ranks, strict=True)
        for item in component.items
    }


def _check_rank_assignment(
    ranks: tuple[int, ...],
    component_count: int,
    constraints: tuple[_ExactConstraint, ...],
) -> None:
    if len(ranks) != component_count or any(rank not in range(3) for rank in ranks):
        raise ValueError("solver witness has invalid component ranks")
    for constraint in constraints:
        if constraint.equalities:
            if any(ranks[left] != ranks[right] for left, right in constraint.equalities):
                raise ValueError("solver witness violates a canonical co-location equality")
            continue
        value = sum(
            coefficient for index, rank, coefficient in constraint.terms if ranks[index] == rank
        )
        if constraint.lower is not None and value < constraint.lower:
            raise ValueError("solver witness violates a canonical lower bound")
        if constraint.upper is not None and value > constraint.upper:
            raise ValueError("solver witness violates a canonical upper bound")


def _validate_artifact_binding(
    model_bytes: bytes,
    expected_model_digest: str,
    proof_bytes: bytes,
    expected_proof_digest: str,
) -> None:
    if not model_bytes or _sha256(model_bytes) != expected_model_digest:
        raise ValueError("proof artifact is bound to a different or empty model")
    if not proof_bytes or _sha256(proof_bytes) != expected_proof_digest:
        raise ValueError("proof artifact digest is invalid")


def _project_ranks(
    source: tuple[_FeasibilityCluster, ...],
    source_ranks: tuple[int, ...],
    target: tuple[_FeasibilityCluster, ...],
) -> tuple[int, ...] | None:
    by_candidate = _rank_map(source, source_ranks)
    result: list[int] = []
    for component in target:
        values = {by_candidate[item.candidate_id] for item in component.items}
        if len(values) != 1:
            return None
        result.append(next(iter(values)))
    return tuple(result)


def _majority_project_ranks(
    source: tuple[_FeasibilityCluster, ...],
    source_ranks: tuple[int, ...],
    target: tuple[_FeasibilityCluster, ...],
) -> tuple[int, ...]:
    by_candidate = _rank_map(source, source_ranks)
    result = []
    for component in target:
        counts = Counter(by_candidate[item.candidate_id] for item in component.items)
        result.append(max(range(3), key=lambda rank: (counts[rank], -rank)))
    return tuple(result)


def _validate_rank_witness(
    *,
    ranks: tuple[int, ...],
    components: tuple[_FeasibilityCluster, ...],
    constraints: tuple[_ExactConstraint, ...],
    base_components: tuple[_FeasibilityCluster, ...],
    colocation_components: tuple[_FeasibilityCluster, ...],
    base_constraints: tuple[_ExactConstraint, ...],
    colocation_constraints: tuple[_ExactConstraint, ...],
    pairs: tuple[tuple[str, str], ...],
) -> str:
    _check_rank_assignment(ranks, len(components), constraints)
    base_ranks = _project_ranks(components, ranks, base_components)
    if base_ranks is None:
        raise ValueError("solver witness splits an atomic base component")
    _check_rank_assignment(base_ranks, len(base_components), base_constraints)
    colocated_ranks = _project_ranks(components, ranks, colocation_components)
    if colocated_ranks is None:
        colocated_ranks = _project_ranks(base_components, base_ranks, colocation_components)
    if colocated_ranks is not None:
        _check_rank_assignment(colocated_ranks, len(colocation_components), colocation_constraints)
        colocated_by_candidate = _rank_map(colocation_components, colocated_ranks)
        if any(
            colocated_by_candidate[left] != colocated_by_candidate[right] for left, right in pairs
        ):
            raise ValueError("solver witness violates a retained co-location pair")
    _exact_aggregate_evidence(
        base_components,
        colocation_components if colocated_ranks is not None else base_components,
        base_ranks,
    )
    return canonical_hash(tuple(ranks))


def _component_signature(
    component: _FeasibilityCluster,
    index: int,
    constraints: tuple[_ExactConstraint, ...],
    base_signature: str,
    co_location_role: str,
) -> tuple[object, ...]:
    row_tags = tuple(
        sorted(
            (row.capability_id, tag)
            for row in COVERAGE_MATRIX
            for tag in row.adversarial_tags
            if any(
                _feasibility_row_eligible(item, row) and tag in item.adversarial_tags
                for item in component.items
            )
        )
    )
    row_errors = tuple(
        sorted(
            (row.capability_id, error.value)
            for row in COVERAGE_MATRIX
            for error in row.error_classes
            if any(
                _feasibility_row_eligible(item, row) and error in item.reachable_error_classes
                for item in component.items
            )
        )
    )
    cells = tuple(
        sorted(
            (row.capability_id, family)
            for row in COVERAGE_MATRIX
            for family in row.benchmark_families
            if _cluster_has_cell_obligation(component, row, family)
        )
    )
    c18 = tuple(
        sorted(
            family
            for family in _row_by_capability("C18").benchmark_families
            if _cluster_has_c18_refusal(component, family)
        )
    )
    critical = tuple(
        sorted(
            error.value
            for error in CRITICAL_ERROR_CLASSES
            if any(
                _feasibility_row_eligible(item, _row_by_capability(item.capability_id))
                and error in item.reachable_error_classes
                for item in component.items
            )
        )
    )
    contribution_vector = tuple(
        (
            constraint.group_id,
            sum(coefficient for idx, _rank, coefficient in constraint.terms if idx == index),
        )
        for constraint in constraints
        if any(idx == index for idx, _rank, _coefficient in constraint.terms)
    )
    answerable = any(
        item.refusal_decision is not RefusalDecision.REQUIRED
        and item.expected_answer_kind is not ExpectedAnswerKind.REFUSAL
        for item in component.items
    )
    return (
        component.size,
        _split_lock_ranks(component),
        cells,
        row_tags,
        row_errors,
        c18,
        critical,
        answerable,
        base_signature,
        co_location_role,
        contribution_vector,
    )


def _graph_canonical_digest(
    node_labels: tuple[str, ...],
    edges: tuple[tuple[int, int, int], ...],
    unique_salt: str,
) -> str:
    if len(node_labels) > 8:
        return canonical_hash({"unsupported_size": len(node_labels), "unique": unique_salt})
    encodings = []
    for order in itertools.permutations(range(len(node_labels))):
        inverse = {old: new for new, old in enumerate(order)}
        encodings.append(
            canonical_hash(
                {
                    "nodes": tuple(node_labels[index] for index in order),
                    "edges": tuple(
                        sorted(
                            (
                                min(inverse[left], inverse[right]),
                                max(inverse[left], inverse[right]),
                                count,
                            )
                            for left, right, count in edges
                        )
                    ),
                }
            )
        )
    return min(encodings)


def _exchangeability_classes(
    base_components: tuple[_FeasibilityCluster, ...],
    colocation_components: tuple[_FeasibilityCluster, ...],
    colocation_constraints: tuple[_ExactConstraint, ...],
    pairs: tuple[tuple[str, str], ...],
) -> tuple[tuple[tuple[int, ...], ...], dict[str, object], tuple[str, ...]]:
    base_index_by_candidate = {
        item.candidate_id: index
        for index, component in enumerate(base_components)
        for item in component.items
    }
    edge_counts: Counter[tuple[int, int]] = Counter()
    for left_id, right_id in pairs:
        left, right = base_index_by_candidate[left_id], base_index_by_candidate[right_id]
        edge_counts[(min(left, right), max(left, right))] += 1
    base_constraints = _exact_requirement_constraints(base_components, base_components)
    base_labels = tuple(
        canonical_hash(_component_signature(component, index, base_constraints, "", ""))
        for index, component in enumerate(base_components)
    )
    grouped: dict[tuple[object, ...], list[int]] = defaultdict(list)
    signature_by_index: list[str] = []
    for index, component in enumerate(colocation_components):
        members = tuple(
            sorted({base_index_by_candidate[item.candidate_id] for item in component.items})
        )
        local_index = {member: position for position, member in enumerate(members)}
        local_edges = tuple(
            (local_index[left], local_index[right], count)
            for (left, right), count in edge_counts.items()
            if left in local_index and right in local_index
        )
        graph_digest = _graph_canonical_digest(
            tuple(base_labels[member] for member in members),
            local_edges,
            component.cluster_key,
        )
        role = canonical_hash(
            {
                "base_component_sizes": tuple(
                    sorted(base_components[member].size for member in members)
                ),
                "retained_pair_count": sum(count for _left, _right, count in local_edges),
                "component_graph": graph_digest,
            }
        )
        signature = _component_signature(
            component,
            index,
            colocation_constraints,
            canonical_hash(tuple(sorted(base_labels[member] for member in members))),
            role,
        )
        grouped[signature].append(index)
        signature_by_index.append(canonical_hash(signature))
    classes = tuple(
        tuple(indices)
        for _signature, indices in sorted(grouped.items(), key=lambda item: canonical_hash(item[0]))
    )
    sizes = Counter(map(len, classes))
    summary = {
        "exchangeability_class_count": len(classes),
        "largest_exchangeability_class": max(map(len, classes), default=0),
        "class_size_distribution": tuple(sorted(sizes.items())),
        "components_within_nontrivial_classes": sum(
            len(group) for group in classes if len(group) > 1
        ),
    }
    return classes, summary, tuple(signature_by_index)


def _validate_symmetry_breaker(
    classes: tuple[tuple[int, ...], ...],
    signatures: tuple[str, ...],
    constraints: tuple[_ExactConstraint, ...],
) -> None:
    seen: set[int] = set()
    for group in classes:
        if len(group) < 2 or tuple(sorted(set(group))) != group:
            raise ValueError("symmetry classes must be ordered, unique, and non-singleton")
        if group[-1] >= len(signatures) or any(index in seen for index in group):
            raise ValueError("symmetry classes overlap or contain an invalid component")
        seen.update(group)
        if len({signatures[index] for index in group}) != 1:
            raise ValueError("symmetry breaker groups nonexchangeable allocation components")
        if any(
            left in group or right in group
            for constraint in constraints
            for left, right in constraint.equalities
        ):
            raise ValueError("symmetry breaker crosses a co-location equality")


def _exact_three_equivalence() -> tuple[bool, str]:
    cases = tuple(itertools.product(range(3), repeat=3))
    for assignment in cases:
        old = all(any(rank == split for rank in assignment) for split in range(3))
        new = all(sum(rank == split for rank in assignment) == 1 for split in range(3))
        if old != new:
            return False, canonical_hash((cases, assignment, old, new))
    return True, canonical_hash({"assignments": cases, "equivalent": True})


def _canonical_telemetry_rollup(trace: list[dict[str, object]]) -> dict[str, object]:
    totals: dict[str, int | float] = {}
    for field in (
        "wall_time",
        "user_time",
        "deterministic_time",
        "num_booleans",
        "num_conflicts",
        "num_branches",
        "num_binary_propagations",
        "num_integer_propagations",
        "num_restarts",
        "num_lp_iterations",
    ):
        values = [value for row in trace if isinstance((value := row.get(field)), int | float)]
        totals[field] = sum(values)
    return {
        "solve_count": len(trace),
        "status_counts": dict(Counter(str(row.get("oracle_status")) for row in trace)),
        "telemetry_totals": totals,
        "unordered_subsolve_telemetry_digest": canonical_hash(
            tuple(
                sorted(
                    canonical_hash(
                        {
                            field: row.get(field)
                            for field in (
                                "oracle_status",
                                "wall_time",
                                "user_time",
                                "deterministic_time",
                                "num_booleans",
                                "num_conflicts",
                                "num_branches",
                                "num_binary_propagations",
                                "num_integer_propagations",
                                "num_restarts",
                                "num_lp_iterations",
                            )
                        }
                    )
                    for row in trace
                )
            )
        ),
    }


def _pb_model_bytes(
    component_count: int,
    constraints: tuple[_ExactConstraint, ...],
) -> tuple[bytes, tuple[tuple[int, ...], ...], tuple[tuple[int, ...], ...], int]:
    from pysat.pb import EncType, PBEnc  # type: ignore[import-not-found]

    clauses: list[list[int]] = []
    variable_map = tuple(
        tuple(index * 3 + rank + 1 for rank in range(3)) for index in range(component_count)
    )
    top_id = 3 * component_count

    def add_pb(method: Any, lits: list[int], weights: list[int], bound: int) -> None:
        nonlocal top_id
        encoded = method(
            lits=lits,
            weights=weights,
            bound=bound,
            top_id=top_id,
            encoding=EncType.bdd,
        )
        clauses.extend(list(clause) for clause in encoded.clauses)
        top_id = max(top_id, encoded.nv)

    for row in variable_map:
        clauses.append(list(row))
        clauses.extend(
            [-row[left], -row[right]] for left, right in itertools.combinations(range(3), 2)
        )
    for constraint in constraints:
        if constraint.equalities:
            for left, right in constraint.equalities:
                for rank in range(3):
                    left_var, right_var = variable_map[left][rank], variable_map[right][rank]
                    clauses.extend(([-left_var, right_var], [left_var, -right_var]))
            continue
        if not constraint.terms:
            impossible = (constraint.lower is not None and constraint.lower > 0) or (
                constraint.upper is not None and constraint.upper < 0
            )
            if impossible:
                clauses.append([])
            continue
        lits = [variable_map[index][rank] for index, rank, _coefficient in constraint.terms]
        weights = [coefficient for _index, _rank, coefficient in constraint.terms]
        if any(weight <= 0 for weight in weights):
            raise ValueError("RES-224 PB conversion received a nonpositive coefficient")
        if constraint.lower is not None and constraint.upper == constraint.lower:
            add_pb(PBEnc.equals, lits, weights, constraint.lower)
        else:
            if constraint.lower is not None:
                if constraint.lower == 1 and all(weight == 1 for weight in weights):
                    clauses.append(lits)
                else:
                    add_pb(PBEnc.geq, lits, weights, constraint.lower)
            if constraint.upper is not None:
                add_pb(PBEnc.leq, lits, weights, constraint.upper)

    normalized = tuple(
        sorted(
            tuple(sorted(clause, key=lambda literal: (abs(literal), literal < 0)))
            for clause in clauses
        )
    )
    max_var = max(
        top_id,
        max((abs(literal) for clause in normalized for literal in clause), default=0),
    )
    dimacs = f"p cnf {max_var} {len(normalized)}\n" + "".join(
        " ".join(map(str, clause)) + (" " if clause else "") + "0\n" for clause in normalized
    )
    return dimacs.encode("ascii"), variable_map, normalized, max_var


def _run_independent_pb(
    *,
    label: str,
    model_kind: str,
    semantic_model_digest: str,
    components: tuple[_FeasibilityCluster, ...],
    constraints: tuple[_ExactConstraint, ...],
    base_components: tuple[_FeasibilityCluster, ...],
    colocation_components: tuple[_FeasibilityCluster, ...],
    base_constraints: tuple[_ExactConstraint, ...],
    colocation_constraints: tuple[_ExactConstraint, ...],
    pairs: tuple[tuple[str, str], ...],
    private_dir: Path,
    time_limit_seconds: float,
    proof_checker: str | None,
) -> tuple[dict[str, object], tuple[int, ...] | None]:
    try:
        from importlib.metadata import version

        from pysat.solvers import Solver  # type: ignore[import-not-found]
    except ImportError:
        return {"result": "NOT_RUN_BACKEND_UNAVAILABLE"}, None
    try:
        cnf_bytes, variable_map, clauses, max_var = _pb_model_bytes(len(components), constraints)
    except ImportError:
        return {"result": "NOT_RUN_PB_ENCODER_UNAVAILABLE"}, None

    cnf_path = private_dir / f"{label}.cnf"
    proof_path = private_dir / f"{label}.drup"
    _write_private(cnf_path, cnf_bytes)
    cnf_digest = _sha256(cnf_bytes)
    started = time.monotonic()
    solver_stats: dict[str, int] = {}
    solver_elapsed: float | None = None
    witness: tuple[int, ...] | None = None
    proof_digest = "NONE"
    proof_check_status = "NOT_APPLICABLE"
    checker_log_digest = "NONE"
    with Solver(
        name="g4",
        bootstrap_with=clauses,
        with_proof=True,
        use_timer=True,
    ) as solver:
        timer = threading.Timer(time_limit_seconds, solver.interrupt)
        timer.daemon = True
        timer.start()
        try:
            sat_result = solver.solve_limited(expect_interrupt=True)
        finally:
            timer.cancel()
            solver_stats = solver.accum_stats()
            solver_elapsed = solver.time()
        if sat_result is True:
            assignment = {literal for literal in solver.get_model() or () if literal > 0}
            ranks = []
            for row in variable_map:
                selected = [rank for rank, variable in enumerate(row) if variable in assignment]
                if len(selected) != 1:
                    raise ValueError("independent SAT model has an incomplete split assignment")
                ranks.append(selected[0])
            witness = tuple(ranks)
            witness_digest = _validate_rank_witness(
                ranks=witness,
                components=components,
                constraints=constraints,
                base_components=base_components,
                colocation_components=colocation_components,
                base_constraints=base_constraints,
                colocation_constraints=colocation_constraints,
                pairs=pairs,
            )
            result = "SAT"
        elif sat_result is False:
            proof = solver.get_proof()
            if not proof or proof[-1].strip() != "0":
                proof_check_status = "MISSING_OR_INCOMPLETE"
            else:
                proof_bytes = ("\n".join(proof) + "\n").encode("ascii")
                _write_private(proof_path, proof_bytes)
                proof_digest = _sha256(proof_bytes)
                _validate_artifact_binding(cnf_bytes, cnf_digest, proof_bytes, proof_digest)
                if proof_checker is None:
                    proof_check_status = "CHECKER_UNAVAILABLE"
                else:
                    checked = subprocess.run(
                        [proof_checker, str(cnf_path), str(proof_path)],
                        check=False,
                        capture_output=True,
                        timeout=time_limit_seconds,
                    )
                    proof_check_status = "PASS" if checked.returncode == 0 else "FAIL"
                    checker_log_digest = _sha256(checked.stdout + checked.stderr)
            result = "UNSAT"
        else:
            result = "UNKNOWN"

    record: dict[str, object] = {
        "result": result,
        "semantic_model_digest": semantic_model_digest,
        "cnf_model_digest": cnf_digest,
        "cnf_path": str(cnf_path.relative_to(private_dir.parent.parent)),
        "cnf_variable_count": max_var,
        "cnf_clause_count": len(clauses),
        "solver": "Glucose 4 via PySAT",
        "pysat_version": version("python-sat"),
        "pypblib_version": version("pypblib"),
        "pb_encoding": "BDD",
        "time_limit_seconds": time_limit_seconds,
        "wall_time": time.monotonic() - started,
        "solver_time": solver_elapsed,
        "solver_stats": solver_stats,
        "proof_path": str(proof_path.relative_to(private_dir.parent.parent))
        if proof_digest != "NONE"
        else "NONE",
        "proof_certificate_digest": proof_digest,
        "proof_check_status": proof_check_status,
    }
    if proof_check_status in {"PASS", "FAIL"}:
        record["proof_checker_log_digest"] = checker_log_digest
    if witness is not None:
        record["witness_independently_validated"] = True
        record["witness_digest"] = witness_digest
    record["result_digest"] = canonical_hash(record)
    result_bytes = json.dumps(record, sort_keys=True, separators=(",", ":")).encode("utf-8")
    result_path = private_dir / f"{label}.result.json"
    _write_private(result_path, result_bytes)
    record["result_artifact_digest"] = _sha256(result_bytes)
    record["result_artifact_path"] = str(result_path.relative_to(private_dir.parent.parent))
    return record, witness


def _first_boundary(records: list[dict[str, object]]) -> str:
    previous: object = None
    for item in records:
        status = item["oracle_status"]
        if previous == "FEASIBLE" and status in {"UNKNOWN", "INFEASIBLE"}:
            return str(item["label"])
        previous = status
    return "NONE_OBSERVED"


def _capture_digest_state(root: Path) -> dict[str, str]:
    paths = (
        root / "production/authoring_plan/private_inputs.json",
        root / "production/diagnostics/RES-223-repair-plan.private.json",
    )
    return {path.name: _sha256(path.read_bytes()) for path in paths}


def run(
    production_root: Path,
    proof_checker: str | Path | None = None,
) -> dict[str, object]:
    repository = _REPOSITORY_ROOT.resolve()
    root = production_root.resolve()
    if root.is_relative_to(repository):
        raise ValueError("RES-224 private probes must remain outside Git")
    private_dir = root / "production/diagnostics/RES-224"
    state_before = _capture_digest_state(root)
    commitments, pairs = _capture_current_commitments(root)
    state_after_reconstruction = _capture_digest_state(root)
    if state_before != state_after_reconstruction:
        raise RuntimeError("RES-224 changed the canonical RES-223 authoring inputs")

    base_components = _feasibility_clusters(commitments, allow_incompatible_locks=True)
    colocation_components = _feasibility_clusters(
        commitments,
        exact_shingle_colocation_pairs=pairs,
        allow_incompatible_locks=True,
    )
    base_constraints = _exact_requirement_constraints(base_components, base_components)
    colocation_constraints = _exact_requirement_constraints(
        colocation_components, colocation_components
    )
    base_model_digest = _exact_model_digest(
        canonical_hash(commitments),
        base_components,
        base_constraints,
        edge_digest=canonical_hash(()),
    )
    colocation_model_digest = _exact_model_digest(
        canonical_hash(commitments),
        colocation_components,
        colocation_constraints,
        edge_digest=canonical_hash(pairs),
    )
    summary: dict[str, Any] = {
        "schema": "RES-224-PRIVATE-PROBES@1.0.0",
        "entry_head": "7cfbb7a73a91090c86d728d68c0614224f60cf9e",
        "implementation_head": "79904ed1da9c0f5f351330b878b4570d035c8a48",
        "receipt_binding_head": "7cfbb7a73a91090c86d728d68c0614224f60cf9e",
        "commitments_digest": canonical_hash(commitments),
        "co_location_edge_digest": canonical_hash(pairs),
        "base_model_digest": base_model_digest,
        "colocation_model_digest": colocation_model_digest,
        "base_constraint_inventory_digest": _constraint_digest(base_constraints),
        "colocation_constraint_inventory_digest": _constraint_digest(colocation_constraints),
        "solver_config_digest": canonical_hash(PRODUCTION_EXACT_SOLVER_CONFIG),
        "base_component_count": len(base_components),
        "colocation_component_count": len(colocation_components),
        "colocation_component_size_distribution": tuple(
            sorted(Counter(component.size for component in colocation_components).items())
        ),
        "preserved_private_state_digests": state_before,
        "model_exports": {},
        "progressive_submodels": {},
        "constraint_ladder": [],
        "time_probes": {},
        "hint_ablation": {},
        "multiworker_probes": {},
        "authority_rechecks": {},
        "symmetry": {},
        "three_cell_strengthening": {},
        "proof_escalation": {},
        "validated_witness_digests": {},
    }

    def save() -> None:
        _write_private(
            private_dir / "RES-224-probes.private.json",
            json.dumps(summary, sort_keys=True, separators=(",", ":")).encode("utf-8"),
        )

    for label, count, constraints in (
        ("BASE", len(base_components), base_constraints),
        ("COLOCATION", len(colocation_components), colocation_constraints),
    ):
        model, _variables = _build_exact_cp_model(count, constraints)
        proto = _exact_cp_model_proto(model)
        path = private_dir / f"{label}-canonical-model.pb"
        _write_private(path, proto)
        summary["model_exports"][label] = {
            "path": path.name,
            "sha256": _sha256(proto),
            "size_bytes": len(proto),
        }
    save()

    run_records: dict[str, dict[str, object]] = {}
    witnesses: dict[tuple[str, str], tuple[int, ...]] = {}

    def solve(
        label: str,
        model_kind: str,
        components: tuple[_FeasibilityCluster, ...],
        constraints: tuple[_ExactConstraint, ...],
        *,
        active_group_ids: frozenset[str] | None = None,
        hint: tuple[int, ...] | None = None,
        budget: float = 60.0,
        workers: int = 1,
        random_seed: int | None = 0,
        cp_model_presolve: bool | None = True,
        randomize_search: bool | None = False,
        default_search: bool = False,
        strengthen_cell_groups: frozenset[str] = frozenset(),
        symmetry_classes: tuple[tuple[int, ...], ...] = (),
        store_in: dict[str, object] | None = None,
    ) -> tuple[str, tuple[int, ...] | None]:
        solved_ranks: list[int] = []
        telemetry: dict[str, object] = {}
        logs: list[str] = []
        status = _exact_completion_status(
            len(components),
            constraints,
            active_group_ids=active_group_ids,
            hint=hint,
            solved_ranks=solved_ranks,
            max_time_in_seconds=budget,
            num_search_workers=workers,
            random_seed=random_seed,
            cp_model_presolve=cp_model_presolve,
            randomize_search=randomize_search,
            log_search_progress=True,
            solve_label=label,
            telemetry=telemetry,
            solve_log=logs,
            strengthen_cell_groups=strengthen_cell_groups,
            symmetry_classes=symmetry_classes,
            default_search=default_search,
        )
        log_content = logs[-1].encode("utf-8") if logs else b""
        log_path = private_dir / "logs" / f"{label}.log"
        _write_private(log_path, log_content)
        if telemetry.get("solve_log_digest") != _sha256(log_content):
            raise RuntimeError("persisted CP-SAT log bytes differ from their telemetry digest")
        if telemetry.get("solve_log_digest") != _sha256(log_content):
            raise RuntimeError("persisted CP-SAT log bytes differ from their telemetry digest")
        record: dict[str, object] = {
            **telemetry,
            "label": label,
            "model_kind": model_kind,
            "full_constraint_model": active_group_ids is None
            or active_group_ids == frozenset(item.group_id for item in constraints),
            "semantic_model_digest": (
                base_model_digest if model_kind == "BASE" else colocation_model_digest
            ),
            "constraint_set_digest": telemetry.get("constraint_set_digest"),
            "oracle_status": status,
            "hint_mode": "NO_HINT" if hint is None else label.rsplit("_", 1)[-1],
            "hint_present": hint is not None,
            "default_portfolio_search": default_search,
            "private_log_path": str(log_path.relative_to(root)),
        }
        run_records[label] = record
        if store_in is not None:
            store_in[label] = record
        ranks = tuple(solved_ranks) if status == "FEASIBLE" else None
        if ranks is not None:
            active_constraints = tuple(
                item
                for item in constraints
                if active_group_ids is None or item.group_id in active_group_ids
            )
            if record["full_constraint_model"]:
                witness_digest = _validate_rank_witness(
                    ranks=ranks,
                    components=components,
                    constraints=active_constraints,
                    base_components=base_components,
                    colocation_components=colocation_components,
                    base_constraints=base_constraints,
                    colocation_constraints=colocation_constraints,
                    pairs=pairs,
                )
                record["witness_independently_validated"] = True
                summary["validated_witness_digests"][label] = witness_digest
            else:
                _check_rank_assignment(ranks, len(components), active_constraints)
                witness_digest = canonical_hash(ranks)
                record["relaxed_witness_validated"] = True
            record["witness_digest"] = witness_digest
            witnesses[(model_kind, label)] = ranks
        save()
        print(
            f"{label}={status} "
            f"DTIME={telemetry.get('deterministic_time')} "
            f"LOG={telemetry.get('solve_log_digest')}",
            flush=True,
        )
        return status, ranks

    # Progressive hint-only models, in the same sequence as the RES-223 path.
    base_preferred = tuple(component.preferred_rank for component in base_components)
    coloc_preferred = tuple(component.preferred_rank for component in colocation_components)
    latest_base_hint: tuple[int, ...] | None = base_preferred
    latest_colocation_hint: tuple[int, ...] | None = coloc_preferred
    progress_specs = (
        (
            "BASE_CELLS_ONLY",
            "BASE",
            base_components,
            base_constraints,
            _groups(base_constraints, "CELL:"),
            "base",
        ),
        (
            "COLOCATION_CELLS_ONLY",
            "COLOCATION",
            colocation_components,
            colocation_constraints,
            _groups(colocation_constraints, "CELL:"),
            "colocation",
        ),
        (
            "COLOCATION_COUNT_CELL_LOCKS",
            "COLOCATION",
            colocation_components,
            colocation_constraints,
            _groups(colocation_constraints, "CELL:", "COUNT:", "SYNTHETIC_LOCK:"),
            "colocation",
        ),
        (
            "COLOCATION_COUNT_LOCKS",
            "COLOCATION",
            colocation_components,
            colocation_constraints,
            _groups(colocation_constraints, "COUNT:", "SYNTHETIC_LOCK:"),
            "colocation",
        ),
        (
            "COLOCATION_NONCRITICAL",
            "COLOCATION",
            colocation_components,
            colocation_constraints,
            frozenset(
                item.group_id
                for item in colocation_constraints
                if not item.group_id.startswith("CRITICAL:")
            ),
            "colocation",
        ),
    )
    for label, model_kind, components, constraints, active, kind in progress_specs:
        hint = latest_base_hint if kind == "base" else latest_colocation_hint
        status, ranks = solve(
            f"PROGRESSIVE_{label}",
            model_kind,
            components,
            constraints,
            active_group_ids=active,
            hint=hint,
            budget=_PROGRESSIVE_SECONDS,
            store_in=summary["progressive_submodels"],
        )
        if status == "FEASIBLE" and ranks is not None:
            if kind == "base":
                latest_base_hint = ranks
            else:
                latest_colocation_hint = ranks
                latest_base_hint = _project_ranks(colocation_components, ranks, base_components)

    # Surface both existing full solves with the progressive hint carried forward.
    base_status, base_solution = solve(
        "PROGRESSIVE_BASE_FULL",
        "BASE",
        base_components,
        base_constraints,
        hint=latest_base_hint,
        budget=60.0,
        store_in=summary["progressive_submodels"],
    )
    if (
        base_status == "FEASIBLE"
        and base_solution is not None
        and run_records["PROGRESSIVE_COLOCATION_CELLS_ONLY"]["oracle_status"] != "FEASIBLE"
        and run_records["PROGRESSIVE_COLOCATION_COUNT_CELL_LOCKS"]["oracle_status"] != "FEASIBLE"
    ):
        latest_colocation_hint = _majority_project_ranks(
            base_components, base_solution, colocation_components
        )
    colocation_status, colocation_solution = solve(
        "PROGRESSIVE_COLOCATION_FULL",
        "COLOCATION",
        colocation_components,
        colocation_constraints,
        hint=latest_colocation_hint,
        budget=60.0,
        store_in=summary["progressive_submodels"],
    )

    # Controlled base constraint ladder, then the co-location authority model.
    ladder_prefixes = (
        ("L0_CELL", ("CELL:",)),
        ("L1_CELL_COUNT", ("CELL:", "COUNT:")),
        ("L2_SYNTHETIC_LOCK", ("CELL:", "COUNT:", "SYNTHETIC_LOCK:")),
        ("L3_C18_REFUSAL", ("CELL:", "COUNT:", "SYNTHETIC_LOCK:", "C18_REFUSAL:")),
        ("L4_ROW_TAG", ("CELL:", "COUNT:", "SYNTHETIC_LOCK:", "C18_REFUSAL:", "ROW_TAG:")),
        (
            "L5_ROW_ERROR",
            ("CELL:", "COUNT:", "SYNTHETIC_LOCK:", "C18_REFUSAL:", "ROW_TAG:", "ROW_ERROR:"),
        ),
        (
            "L6_CRITICAL",
            (
                "CELL:",
                "COUNT:",
                "SYNTHETIC_LOCK:",
                "C18_REFUSAL:",
                "ROW_TAG:",
                "ROW_ERROR:",
                "CRITICAL:",
            ),
        ),
        (
            "L7_BASE_FULL",
            (
                "CELL:",
                "COUNT:",
                "SYNTHETIC_LOCK:",
                "C18_REFUSAL:",
                "ROW_TAG:",
                "ROW_ERROR:",
                "CRITICAL:",
                "ANSWERABLE:",
            ),
        ),
    )
    ladder_records: list[dict[str, object]] = []
    for label, prefixes in ladder_prefixes:
        active = _groups(base_constraints, *prefixes)
        solve(
            label,
            "BASE",
            base_components,
            base_constraints,
            active_group_ids=active,
            budget=60.0,
        )
        ladder_records.append(run_records[label])
        summary["constraint_ladder"] = ladder_records
        save()
    solve(
        "L8_COLOCATION_FULL",
        "COLOCATION",
        colocation_components,
        colocation_constraints,
        budget=60.0,
    )
    ladder_records.append(run_records["L8_COLOCATION_FULL"])
    summary["constraint_ladder"] = ladder_records
    summary["constraint_ladder_first_boundary"] = _first_boundary(ladder_records)
    save()

    # Fixed-seed, single-worker time probes on the exact no-hint full models.
    for model_kind, components, constraints in (
        ("BASE", base_components, base_constraints),
        ("COLOCATION", colocation_components, colocation_constraints),
    ):
        for seconds in _TIME_BUDGETS:
            label = f"TIME_{model_kind}_{seconds}S_NO_HINT"
            solve(
                label,
                model_kind,
                components,
                constraints,
                budget=float(seconds),
                workers=1,
                random_seed=0,
                cp_model_presolve=True,
                randomize_search=False,
                store_in=summary["time_probes"],
            )

    # Hint ablation; hints affect only the model's advisory solution_hint field.
    base_cell_hint = next(
        (
            ranks
            for (kind, label), ranks in witnesses.items()
            if kind == "BASE" and label == "PROGRESSIVE_BASE_CELLS_ONLY"
        ),
        None,
    )
    coloc_cell_hint = next(
        (
            ranks
            for (kind, label), ranks in witnesses.items()
            if kind == "COLOCATION" and label == "PROGRESSIVE_COLOCATION_CELLS_ONLY"
        ),
        None,
    )
    count_cell_hint = next(
        (
            ranks
            for (kind, label), ranks in witnesses.items()
            if label == "PROGRESSIVE_COLOCATION_COUNT_CELL_LOCKS"
        ),
        None,
    )
    noncritical_hint = next(
        (
            ranks
            for (kind, label), ranks in witnesses.items()
            if label == "PROGRESSIVE_COLOCATION_NONCRITICAL"
        ),
        None,
    )
    ablations = (
        ("NO_HINT", None, None),
        ("COMPONENT_PREFERRED_RANK_HINT", base_preferred, coloc_preferred),
        (
            "BASE_CELL_FEASIBLE_HINT",
            base_cell_hint,
            _project_ranks(base_components, base_cell_hint, colocation_components)
            if base_cell_hint
            else None,
        ),
        (
            "COLOCATION_CELL_FEASIBLE_HINT",
            _project_ranks(colocation_components, coloc_cell_hint, base_components)
            if coloc_cell_hint
            else None,
            coloc_cell_hint,
        ),
        (
            "COUNT_CELL_LOCK_HINT",
            _project_ranks(colocation_components, count_cell_hint, base_components)
            if count_cell_hint
            else None,
            count_cell_hint,
        ),
        (
            "NONCRITICAL_HINT",
            _project_ranks(colocation_components, noncritical_hint, base_components)
            if noncritical_hint
            else None,
            noncritical_hint,
        ),
    )
    for mode, base_hint, coloc_hint in ablations:
        for model_kind, components, constraints, hint in (
            ("BASE", base_components, base_constraints, base_hint),
            ("COLOCATION", colocation_components, colocation_constraints, coloc_hint),
        ):
            if mode == "NO_HINT":
                ref = summary["time_probes"][f"TIME_{model_kind}_60S_NO_HINT"]
                summary["hint_ablation"][f"{model_kind}_{mode}"] = {
                    **ref,
                    "reused_from": f"TIME_{model_kind}_60S_NO_HINT",
                }
                continue
            label = f"HINT_{model_kind}_{mode}"
            if hint is None:
                summary["hint_ablation"][f"{model_kind}_{mode}"] = {
                    "oracle_status": "NOT_AVAILABLE",
                    "hint_mode": mode,
                    "constraint_set_digest": canonical_hash(
                        (
                            base_model_digest if model_kind == "BASE" else colocation_model_digest,
                            "FULL_CONSTRAINTS",
                        )
                    ),
                }
                continue
            solve(
                label,
                model_kind,
                components,
                constraints,
                hint=hint,
                budget=60.0,
                store_in=summary["hint_ablation"],
            )
            run_records[label]["hint_mode"] = mode

    # Default portfolio probes, changing only the worker count and diagnostic budget.
    for model_kind, components, constraints in (
        ("BASE", base_components, base_constraints),
        ("COLOCATION", colocation_components, colocation_constraints),
    ):
        for workers in (8, 16):
            label = f"MULTIWORKER_{model_kind}_{workers}"
            solve(
                label,
                model_kind,
                components,
                constraints,
                budget=_MULTIWORKER_SECONDS,
                workers=workers,
                random_seed=None,
                cp_model_presolve=None,
                randomize_search=None,
                default_search=True,
                store_in=summary["multiworker_probes"],
            )

    # Exact component signatures and proven component-order symmetry breaking.
    classes, symmetry_summary, component_signatures = _exchangeability_classes(
        base_components, colocation_components, colocation_constraints, pairs
    )
    proven_classes = tuple(group for group in classes if len(group) > 1)
    _validate_symmetry_breaker(proven_classes, component_signatures, colocation_constraints)
    symmetry_proof_digest = canonical_hash(
        {
            "class_signatures": tuple(component_signatures[group[0]] for group in proven_classes),
            "class_sizes": tuple(len(group) for group in proven_classes),
            "constraint_digest": _constraint_digest(colocation_constraints),
            "proof": "equal full constraint contributions and internal co-location graph",
        }
    )
    summary["symmetry"] = {
        **symmetry_summary,
        "solver_symmetry_log_digest": run_records["PROGRESSIVE_COLOCATION_FULL"][
            "solver_symmetry_log_digest"
        ],
        "solver_symmetry_log_lines": run_records["PROGRESSIVE_COLOCATION_FULL"][
            "solver_symmetry_log_lines"
        ],
        "applied": bool(proven_classes),
        "proof_digest": symmetry_proof_digest if proven_classes else "NONE",
        "permutation_invariance_proven": bool(proven_classes),
    }
    if proven_classes:
        solve(
            "SYMMETRY_COLOCATION_FULL",
            "COLOCATION",
            colocation_components,
            colocation_constraints,
            budget=60.0,
            symmetry_classes=proven_classes,
        )
        summary["symmetry"]["with_breaker"] = run_records["SYMMETRY_COLOCATION_FULL"]
        summary["symmetry"]["without_breaker"] = run_records["TIME_COLOCATION_60S_NO_HINT"]
    save()

    # The local exhaustive proof is run before the equivalent linear strengthening.
    equivalent, equivalence_digest = _exact_three_equivalence()
    base_exact_three_groups = frozenset(
        constraint.group_id
        for constraint in base_constraints
        if constraint.group_id.startswith("CELL:") and len(constraint.terms) == 3
    )
    colocation_exact_three_groups = frozenset(
        constraint.group_id
        for constraint in colocation_constraints
        if constraint.group_id.startswith("CELL:") and len(constraint.terms) == 3
    )
    strengthened_record: dict[str, object] = {
        "equivalence_status": "PASS" if equivalent else "FAIL",
        "equivalence_digest": equivalence_digest,
        "exhaustive_assignments_checked": 27,
        "base_exactly_three_cell_count": len(
            {group.rsplit(":", 1)[0] for group in base_exact_three_groups}
        ),
        "colocation_exactly_three_cell_count": len(
            {group.rsplit(":", 1)[0] for group in colocation_exact_three_groups}
        ),
        "model_solution_set_changed": "NO" if equivalent else "UNKNOWN",
        "base_strengthened_group_digest": canonical_hash(tuple(sorted(base_exact_three_groups))),
        "colocation_strengthened_group_digest": canonical_hash(
            tuple(sorted(colocation_exact_three_groups))
        ),
    }
    if not equivalent:
        raise RuntimeError(
            "exactly-three-cell coverage strengthening failed exhaustive equivalence"
        )
    if base_exact_three_groups:
        solve(
            "THREE_CELL_STRENGTHENED_BASE_300S",
            "BASE",
            base_components,
            base_constraints,
            budget=300.0,
            strengthen_cell_groups=base_exact_three_groups,
        )
        strengthened_record["base_strengthened_run"] = run_records[
            "THREE_CELL_STRENGTHENED_BASE_300S"
        ]
        strengthened_record["base_baseline_run"] = run_records["TIME_BASE_300S_NO_HINT"]
        strengthened_record["base_status_comparison"] = (
            run_records["TIME_BASE_300S_NO_HINT"]["oracle_status"],
            run_records["THREE_CELL_STRENGTHENED_BASE_300S"]["oracle_status"],
        )
    if colocation_exact_three_groups:
        solve(
            "THREE_CELL_STRENGTHENED_COLOCATION_300S",
            "COLOCATION",
            colocation_components,
            colocation_constraints,
            budget=300.0,
            strengthen_cell_groups=colocation_exact_three_groups,
        )
        strengthened_record["colocation_strengthened_run"] = run_records[
            "THREE_CELL_STRENGTHENED_COLOCATION_300S"
        ]
        strengthened_record["colocation_baseline_run"] = run_records["TIME_COLOCATION_300S_NO_HINT"]
        strengthened_record["colocation_status_comparison"] = (
            run_records["TIME_COLOCATION_300S_NO_HINT"]["oracle_status"],
            run_records["THREE_CELL_STRENGTHENED_COLOCATION_300S"]["oracle_status"],
        )
    if not base_exact_three_groups and not colocation_exact_three_groups:
        strengthened_record["strengthened_run"] = "NOT_APPLIED_NO_EXACTLY_THREE_CELLS"
    summary["three_cell_strengthening"] = strengthened_record
    save()

    # Reuse only validated complete full-model witnesses; keep rank vectors in memory.
    validated_full_witnesses: dict[str, tuple[int, ...]] = {}
    for (model_kind, label), ranks in witnesses.items():
        if run_records[label]["full_constraint_model"]:
            validated_full_witnesses.setdefault(model_kind, ranks)

    proof_checker_path = (
        str(Path(proof_checker).resolve())
        if proof_checker is not None
        else shutil.which("drat-trim")
    )
    independent_results: dict[str, dict[str, object]] = {}
    for model_kind, components, constraints, model_digest in (
        ("BASE", base_components, base_constraints, base_model_digest),
        (
            "COLOCATION",
            colocation_components,
            colocation_constraints,
            colocation_model_digest,
        ),
    ):
        full_records = tuple(
            record
            for record in run_records.values()
            if record["model_kind"] == model_kind and record["full_constraint_model"]
        )
        multiworker_records: dict[str, Any] = summary["multiworker_probes"]
        multiworker_infeasible = any(
            record["model_kind"] == model_kind and record["oracle_status"] == "INFEASIBLE"
            for record in multiworker_records.values()
        )
        exact_infeasible = any(record["oracle_status"] == "INFEASIBLE" for record in full_records)
        needs_independent = (
            multiworker_infeasible
            or exact_infeasible
            or (
                model_kind not in validated_full_witnesses
                and any(record["oracle_status"] == "UNKNOWN" for record in full_records)
            )
        )
        if not needs_independent:
            independent_results[model_kind] = {"result": "NOT_REQUIRED"}
            continue
        record, witness = _run_independent_pb(
            label=f"RES224_{model_kind}_GLUCOSE4",
            model_kind=model_kind,
            semantic_model_digest=model_digest,
            components=components,
            constraints=constraints,
            base_components=base_components,
            colocation_components=colocation_components,
            base_constraints=base_constraints,
            colocation_constraints=colocation_constraints,
            pairs=pairs,
            private_dir=private_dir,
            time_limit_seconds=3600.0,
            proof_checker=proof_checker_path,
        )
        independent_results[model_kind] = record
        if witness is not None:
            validated_full_witnesses.setdefault(model_kind, witness)
        summary["proof_escalation"][model_kind] = record
        save()

    # Feed any independently validated full witness back through the fixed authority config.
    authority_hints: dict[str, tuple[int, ...]] = {}
    if "COLOCATION" in validated_full_witnesses:
        coloc_hint = validated_full_witnesses["COLOCATION"]
        base_hint = _project_ranks(colocation_components, coloc_hint, base_components)
        if base_hint is None:
            raise ValueError("validated co-location witness does not project to BASE components")
        authority_hints = {"BASE": base_hint, "COLOCATION": coloc_hint}
        validated_full_witnesses.setdefault("BASE", base_hint)
    elif "BASE" in validated_full_witnesses:
        base_hint = validated_full_witnesses["BASE"]
        authority_hints = {
            "BASE": base_hint,
            "COLOCATION": _majority_project_ranks(
                base_components, base_hint, colocation_components
            ),
        }

    for model_kind, components, constraints in (
        ("BASE", base_components, base_constraints),
        ("COLOCATION", colocation_components, colocation_constraints),
    ):
        hint = authority_hints.get(model_kind)
        if hint is None:
            summary["authority_rechecks"][model_kind] = {
                "oracle_status": "NOT_RUN_NO_VALIDATED_FULL_WITNESS"
            }
            continue
        label = f"AUTHORITY_{model_kind}_VALIDATED_WITNESS_HINT"
        solve(
            label,
            model_kind,
            components,
            constraints,
            hint=hint,
            budget=60.0,
            workers=1,
            random_seed=0,
            cp_model_presolve=True,
            randomize_search=False,
            store_in=summary["authority_rechecks"],
        )
        if (model_kind, label) in witnesses:
            validated_full_witnesses.setdefault(model_kind, witnesses[(model_kind, label)])

    def model_final_status(model_kind: str) -> str:
        if model_kind in validated_full_witnesses:
            return "FEASIBLE"
        independent = independent_results.get(model_kind, {})
        if independent.get("result") == "UNSAT" and independent.get("proof_check_status") == "PASS":
            return "INFEASIBLE"
        if any(
            record["model_kind"] == model_kind
            and record["full_constraint_model"]
            and record["oracle_status"] == "INFEASIBLE"
            for record in run_records.values()
        ):
            return "INFEASIBLE"
        return "UNKNOWN"

    final_status = {
        "BASE": model_final_status("BASE"),
        "COLOCATION": model_final_status("COLOCATION"),
    }
    summary["final_status"] = final_status
    summary["independent_solver_used"] = any(
        item.get("result")
        not in {"NOT_REQUIRED", "NOT_RUN_BACKEND_UNAVAILABLE", "NOT_RUN_PB_ENCODER_UNAVAILABLE"}
        for item in independent_results.values()
    )
    summary["independent_result"] = {
        key: item.get("result", "NOT_RUN") for key, item in independent_results.items()
    }
    summary["proof_certificate_digest"] = {
        key: item.get("proof_certificate_digest", "NONE")
        for key, item in independent_results.items()
    }

    canonical_attempt_status = "NOT_RUN"
    canonical_digest = "NONE"
    if final_status == {"BASE": "FEASIBLE", "COLOCATION": "FEASIBLE"}:
        canonical_hint = validated_full_witnesses["COLOCATION"]
        canonical_trace: list[dict[str, object]] = []
        canonical_attempt_status, canonical_ranks = _canonical_split_ranks(
            len(colocation_components),
            colocation_constraints,
            canonical_hint,
            solve_trace=canonical_trace,
        )
        summary["canonical_self_reduction_telemetry"] = _canonical_telemetry_rollup(canonical_trace)
        if canonical_attempt_status == "PASS" and canonical_ranks is not None:
            canonical_digest = _validate_rank_witness(
                ranks=canonical_ranks,
                components=colocation_components,
                constraints=colocation_constraints,
                base_components=base_components,
                colocation_components=colocation_components,
                base_constraints=base_constraints,
                colocation_constraints=colocation_constraints,
                pairs=pairs,
            )
            summary["canonical_self_reduction"] = "PASS"
        else:
            summary["canonical_self_reduction"] = "NOT_RUN"
            summary["canonical_attempt_status"] = "BLOCKED"
    else:
        summary["canonical_self_reduction"] = "NOT_RUN"
    summary["canonical_witness_digest"] = canonical_digest

    multiworker_records = summary["multiworker_probes"]
    multiworker_crosscheck_incomplete = any(
        record["oracle_status"] == "INFEASIBLE"
        and independent_results.get(model_kind, {}).get("result") not in {"SAT", "UNSAT"}
        for model_kind in ("BASE", "COLOCATION")
        for record in multiworker_records.values()
        if record["model_kind"] == model_kind
    )
    inconsistent_solver_results = any(
        (
            model_kind in validated_full_witnesses
            and any(
                record["model_kind"] == model_kind
                and record["full_constraint_model"]
                and record["oracle_status"] == "INFEASIBLE"
                for record in run_records.values()
            )
        )
        or (
            model_kind in validated_full_witnesses
            and independent_results.get(model_kind, {}).get("result") == "UNSAT"
        )
        for model_kind in ("BASE", "COLOCATION")
    )
    if inconsistent_solver_results:
        mission_status = "FAIL"
        next_action = "further proof escalation"
    elif final_status == {"BASE": "FEASIBLE", "COLOCATION": "FEASIBLE"}:
        if summary["canonical_self_reduction"] == "PASS":
            mission_status = "PASS"
            next_action = "RES-128 resume"
        else:
            mission_status = "BLOCKED"
            next_action = "further proof escalation"
    elif "INFEASIBLE" in final_status.values():
        all_conclusive = all(status != "UNKNOWN" for status in final_status.values())
        all_unsat_verified = all(
            status != "INFEASIBLE"
            or independent_results.get(model_kind, {}).get("proof_check_status") == "PASS"
            for model_kind, status in final_status.items()
        )
        mission_status = (
            "PASS"
            if all_conclusive and all_unsat_verified and not multiworker_crosscheck_incomplete
            else "BLOCKED"
        )
        next_action = (
            "candidate-design repair" if mission_status == "PASS" else "further proof escalation"
        )
    else:
        mission_status = "BLOCKED"
        next_action = "further proof escalation"
    summary["mission_status"] = mission_status
    summary["next"] = next_action
    summary["probe_payload_digest"] = _sha256(
        json.dumps(summary, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    save()
    probe_file_digest = _sha256((private_dir / "RES-224-probes.private.json").read_bytes())
    state_after = _capture_digest_state(root)
    if state_after != state_before:
        raise RuntimeError("RES-224 changed the RES-223 authoring inputs during probes")
    summary["probe_artifact_digest"] = probe_file_digest
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--production-root", type=Path, default=DEFAULT_PRODUCTION_ROOT)
    parser.add_argument("--proof-checker", type=Path)
    args = parser.parse_args(argv)
    summary = run(args.production_root, proof_checker=args.proof_checker)
    print(f"BASE_MODEL_DIGEST={summary['base_model_digest']}")
    print(f"COLOCATION_MODEL_DIGEST={summary['colocation_model_digest']}")
    print(f"PRIVATE_PROBE_FILE_DIGEST={summary['probe_artifact_digest']}")
    print(f"PRIVATE_PROBE_PAYLOAD_DIGEST={summary['probe_payload_digest']}")
    print(f"BASE_FINAL_STATUS={summary['final_status']['BASE']}")  # type: ignore[index]
    print(f"COLOCATION_FINAL_STATUS={summary['final_status']['COLOCATION']}")  # type: ignore[index]
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
