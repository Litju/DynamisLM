"""CP-SAT encoding for the solver-independent final-selection problem."""

from __future__ import annotations

import sys
import time
from collections import defaultdict
from importlib.metadata import version
from typing import Any

from ortools.sat.python import cp_model

from dynamislm.benchmark.constants import SPLIT_ORDER, CaseOrigin, SplitName
from dynamislm.benchmark.selection_contracts import (
    SELECTION_RECEIPT_VERSION,
    AssignmentState,
    CandidateAssignment,
    ConstraintKind,
    FinalSelectionPlan,
    FinalSelectionProblem,
    FinalSelectionResult,
    ObjectiveKind,
    SelectionDiagnostic,
    SelectionSolverConfig,
    SelectionSolveReceipt,
    SolveStatus,
    ValidationStatus,
)
from dynamislm.benchmark.selection_validation import validate_final_selection

try:
    import resource
except ImportError:  # pragma: no cover - resource is unavailable on Windows
    resource = None  # type: ignore[assignment]

_SOLVER_FAMILY = "OR-TOOLS-CP-SAT"
_STATE_ORDER = (
    AssignmentState.OUT,
    AssignmentState.PUBLIC_DEVELOPMENT,
    AssignmentState.FROZEN_VALIDATION,
    AssignmentState.HIDDEN_FINAL,
)
_STATE_RANK = {state: rank for rank, state in enumerate(_STATE_ORDER)}


def _new_solver(config: SelectionSolverConfig) -> Any:
    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = config.workers
    solver.parameters.random_seed = config.random_seed
    solver.parameters.randomize_search = config.randomize_search
    solver.parameters.max_time_in_seconds = config.timeout_s
    solver.parameters.cp_model_presolve = config.cp_model_presolve
    return solver


def _peak_rss_mb() -> float:
    if resource is None:
        return 0.0
    maximum = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return maximum / (1024 * 1024 if sys.platform == "darwin" else 1024)


def _status_name(solver: Any, status: Any) -> str:
    return str(solver.status_name(status))


def _selection_literals(
    assignment_vars: dict[tuple[str, AssignmentState], Any], candidate_id: str
) -> list[Any]:
    return [
        assignment_vars[(candidate_id, state)]
        for state in _STATE_ORDER
        if state is not AssignmentState.OUT
    ]


def _model_for(
    problem: FinalSelectionProblem,
) -> tuple[
    Any,
    dict[tuple[str, AssignmentState], Any],
    Any | None,
    Any | None,
]:
    model = cp_model.CpModel()
    assignment_vars: dict[tuple[str, AssignmentState], Any] = {}
    candidates = problem.candidates
    by_id = {item.candidate_id: item for item in candidates}
    for index, candidate in enumerate(candidates):
        states = tuple(
            model.new_bool_var(f"a[{index},{rank}]") for rank in range(len(_STATE_ORDER))
        )
        model.add_exactly_one(states)
        for state, variable in zip(_STATE_ORDER, states, strict=True):
            assignment_vars[(candidate.candidate_id, state)] = variable

    lineages: dict[str, list[str]] = defaultdict(list)
    for candidate in candidates:
        if (
            candidate.origin_class is CaseOrigin.ADVERSARIAL_MUTATION
            and candidate.mutation_lineage_id is not None
        ):
            lineages[candidate.mutation_lineage_id].append(candidate.candidate_id)

    for constraint in problem.constraint_set.constraints:
        if constraint.kind is ConstraintKind.ONE_STATE_PER_CANDIDATE:
            continue
        if constraint.kind is ConstraintKind.FINAL_COUNT:
            assert constraint.minimum is not None
            if constraint.maximum == constraint.minimum == len(candidates):
                for candidate in candidates:
                    model.add(assignment_vars[(candidate.candidate_id, AssignmentState.OUT)] == 0)
                continue
            terms = [
                variable
                for candidate in candidates
                for variable in _selection_literals(assignment_vars, candidate.candidate_id)
            ]
        elif constraint.kind is ConstraintKind.SPLIT_COUNT:
            assert constraint.split is not None
            state = AssignmentState(constraint.split.value)
            terms = [assignment_vars[(candidate.candidate_id, state)] for candidate in candidates]
        elif constraint.kind is ConstraintKind.FEATURE_MINIMUM:
            assert constraint.split is not None and constraint.feature is not None
            state = AssignmentState(constraint.split.value)
            terms = [
                assignment_vars[(candidate.candidate_id, state)]
                for candidate in candidates
                if constraint.feature in candidate.features
            ]
        elif constraint.kind is ConstraintKind.ORIGIN_BOUNDS:
            assert constraint.origin_class is not None
            terms = [
                variable
                for candidate in candidates
                if candidate.origin_class is constraint.origin_class
                for variable in _selection_literals(assignment_vars, candidate.candidate_id)
            ]
        elif constraint.kind is ConstraintKind.MUTATION_LINEAGE_MINIMUM:
            lineage_selected: list[Any] = []
            for index, members in enumerate(sorted(lineages.values(), key=lambda ids: tuple(ids))):
                selected = model.new_bool_var(f"lineage[{index}]")
                member_terms = [
                    variable
                    for candidate_id in members
                    for variable in _selection_literals(assignment_vars, candidate_id)
                ]
                model.add(sum(member_terms) >= 1).only_enforce_if(selected)
                model.add(sum(member_terms) == 0).only_enforce_if(selected.Not())
                lineage_selected.append(selected)
            terms = lineage_selected
        elif constraint.kind in {
            ConstraintKind.REVIEW_OUT_ONLY,
            ConstraintKind.QUALIFICATION_OUT_ONLY,
        }:
            model.add(assignment_vars[(constraint.candidate_ids[0], AssignmentState.OUT)] == 1)
            continue
        elif constraint.kind is ConstraintKind.SYNTHETIC_SPLIT_LOCK:
            assert constraint.locked_split is not None
            candidate_id = constraint.candidate_ids[0]
            for split in SPLIT_ORDER:
                if split is not constraint.locked_split:
                    model.add(assignment_vars[(candidate_id, AssignmentState(split.value))] == 0)
            continue
        elif constraint.kind is ConstraintKind.CONDITIONAL_COLOCATION:
            split_indicators = [
                model.new_bool_var(f"colocate[{constraint.constraint_id},{rank}]")
                for rank, _split in enumerate(SPLIT_ORDER)
            ]
            for indicator, split in zip(split_indicators, SPLIT_ORDER, strict=True):
                state = AssignmentState(split.value)
                terms = [
                    assignment_vars[(candidate_id, state)]
                    for candidate_id in constraint.candidate_ids
                ]
                for term in terms:
                    model.add(term <= indicator)
                model.add(indicator <= sum(terms))
            model.add(sum(split_indicators) <= 1)
            continue
        elif constraint.kind is ConstraintKind.MUTATION_PARENT_PROVENANCE:
            candidate = by_id[constraint.candidate_ids[0]]
            registry = {item.candidate_id: item for item in problem.parent_provenance_registry}
            parent = registry.get(constraint.related_id or "")
            if (
                candidate.mutation_parent_candidate_id != constraint.related_id
                or candidate.mutation_parent_payload_hash is None
                or constraint.related_payload_hash != candidate.mutation_parent_payload_hash
                or parent is None
                or parent.payload_hash != candidate.mutation_parent_payload_hash
            ):
                model.add(assignment_vars[(candidate.candidate_id, AssignmentState.OUT)] == 1)
            continue
        else:
            assert constraint.kind is ConstraintKind.MUTATION_PARENT_CELL_INHERITANCE
            candidate = by_id[constraint.candidate_ids[0]]
            registry = {item.candidate_id: item for item in problem.parent_provenance_registry}
            parent = registry.get(constraint.related_id or "")
            if (
                candidate.mutation_parent_candidate_id != constraint.related_id
                or constraint.reason != candidate.mutation_cell_exception_authority_ref
                or parent is None
                or (
                    candidate.cell != parent.cell
                    and candidate.mutation_cell_exception_authority_ref is None
                )
            ):
                model.add(assignment_vars[(candidate.candidate_id, AssignmentState.OUT)] == 1)
            continue
        assert constraint.minimum is not None
        model.add(sum(terms) >= constraint.minimum)
        if constraint.maximum is not None:
            model.add(sum(terms) <= constraint.maximum)

    targets: dict[SplitName, int] = {}
    for constraint in problem.constraint_set.constraints:
        if constraint.kind is ConstraintKind.SPLIT_COUNT:
            assert constraint.split is not None and constraint.minimum is not None
            targets[constraint.split] = constraint.minimum
    final_count = next(
        constraint.minimum
        for constraint in problem.constraint_set.constraints
        if constraint.kind is ConstraintKind.FINAL_COUNT
    )
    assert final_count is not None
    balance_terms: list[Any] = []
    if any(
        objective.kind is ObjectiveKind.PROPORTIONAL_SPLIT_BALANCE
        for objective in problem.constraint_set.objectives
    ):
        balance_cells = sorted(
            {cell for candidate in candidates for cell in candidate.balance_cells},
            key=lambda item: (item.dimension.value, item.key),
        )
        for cell_index, cell in enumerate(balance_cells):
            feature_candidates = [
                candidate for candidate in candidates if cell in candidate.balance_cells
            ]
            total_selected: Any = (
                len(feature_candidates)
                if len(candidates) == final_count
                else sum(
                    variable
                    for candidate in feature_candidates
                    for variable in _selection_literals(assignment_vars, candidate.candidate_id)
                )
            )
            for split_index, split in enumerate(SPLIT_ORDER):
                state = AssignmentState(split.value)
                split_count = sum(
                    assignment_vars[(candidate.candidate_id, state)]
                    for candidate in feature_candidates
                )
                target = targets[split]
                bound = final_count * final_count + target * final_count
                deviation = model.new_int_var(0, bound, f"balance[{cell_index},{split_index}]")
                model.add_abs_equality(
                    deviation, final_count * split_count - target * total_selected
                )
                balance_terms.append(deviation)
    balance_objective = sum(balance_terms) if balance_terms else None

    hash_terms: list[Any] = []
    if any(
        objective.kind is ObjectiveKind.HASH_CLUSTER_PREFERENCE
        for objective in problem.constraint_set.objectives
    ):
        for cluster in problem.constraint_set.allocation_clusters:
            for split in SPLIT_ORDER:
                if split is cluster.preferred_split:
                    continue
                state = AssignmentState(split.value)
                hash_terms.extend(
                    assignment_vars[(candidate_id, state)] for candidate_id in cluster.candidate_ids
                )
    hash_objective = sum(hash_terms) if hash_terms else None
    return model, assignment_vars, balance_objective, hash_objective


def _solve_once(model: Any, config: SelectionSolverConfig) -> tuple[Any, str, float]:
    solver = _new_solver(config)
    status = solver.solve(model)
    deterministic = float(solver.response_proto.deterministic_time)
    name = _status_name(solver, status)
    if name == "MODEL_INVALID":
        return solver, f"MODEL_INVALID: {model.validate()}", deterministic
    return solver, name, deterministic


def _refresh_hints(
    model: Any,
    solver: Any,
) -> None:
    model.clear_hints()
    for index in range(len(model.proto.variables)):
        variable = model.get_int_var_from_proto_index(index)
        model.add_hint(variable, int(solver.value(variable)))


def _complete_plan_hint(
    model: Any,
    assignment_vars: dict[tuple[str, AssignmentState], Any],
    problem: FinalSelectionProblem,
    plan: FinalSelectionPlan,
    config: SelectionSolverConfig,
) -> tuple[bool, float]:
    """Complete a semantic witness with derived CP-SAT helper-variable values."""

    hint_model = model.clone()
    assignments = {item.candidate_id: item.state for item in plan.assignments}
    for candidate in problem.candidates:
        for state in _STATE_ORDER:
            index = assignment_vars[(candidate.candidate_id, state)].index
            hint_model.add(
                hint_model.get_bool_var_from_proto_index(index)
                == int(assignments[candidate.candidate_id] is state)
            )
    solver, status, deterministic = _solve_once(hint_model, config)
    if status not in {"OPTIMAL", "FEASIBLE"}:
        return False, deterministic
    for index in range(len(model.proto.variables)):
        variable = model.get_int_var_from_proto_index(index)
        hint_value = hint_model.get_int_var_from_proto_index(index)
        model.add_hint(variable, int(solver.value(hint_value)))
    return True, deterministic


def solve_final_selection(
    problem: FinalSelectionProblem,
    *,
    solver_config: SelectionSolverConfig | None = None,
    initial_plan_hint: FinalSelectionPlan | None = None,
) -> FinalSelectionResult:
    """Solve, canonicalize, decode, then independently validate a final plan."""

    started = time.perf_counter()
    if solver_config is None:
        solver_config = SelectionSolverConfig()
    model, assignment_vars, balance_objective, hash_objective = _model_for(problem)
    variable_count = len(model.proto.variables)
    constraint_count = len(model.proto.constraints)
    deterministic_time = 0.0
    balance_value: int | None = None
    hash_value: int | None = None
    plan: FinalSelectionPlan | None = None
    validation = None
    diagnostics: tuple[SelectionDiagnostic, ...] = ()
    objective_optimization_wall_s = 0.0
    canonicalization_wall = 0.0
    solver_wall_s = 0.0
    warm_start_used = False

    if (
        initial_plan_hint is not None
        and validate_final_selection(problem, initial_plan_hint).status is ValidationStatus.VALID
    ):
        warm_start_used, hint_deterministic = _complete_plan_hint(
            model,
            assignment_vars,
            problem,
            initial_plan_hint,
            solver_config,
        )
        deterministic_time += hint_deterministic

    solver, status, deterministic = _solve_once(model, solver_config)
    deterministic_time += deterministic
    if status == "INFEASIBLE":
        solve_status = SolveStatus.INFEASIBLE
        diagnostics = (
            SelectionDiagnostic(
                "SELECTION_INFEASIBLE",
                "CP-SAT proved the assignment problem infeasible.",
            ),
        )
    elif status not in {"OPTIMAL", "FEASIBLE"}:
        solve_status = SolveStatus.UNKNOWN
        diagnostics = (
            SelectionDiagnostic(
                "SELECTION_UNKNOWN",
                f"CP-SAT returned {status}; no plan was accepted.",
            ),
        )
    else:
        _refresh_hints(model, solver)
        optimization_started = time.perf_counter()
        objective_values = {
            ObjectiveKind.PROPORTIONAL_SPLIT_BALANCE: balance_objective,
            ObjectiveKind.HASH_CLUSTER_PREFERENCE: hash_objective,
        }
        canonical_status = "OPTIMAL"
        for objective in problem.constraint_set.objectives:
            expression = objective_values.get(objective.kind)
            if expression is None:
                continue
            model.minimize(expression)
            solver, objective_status, deterministic = _solve_once(model, solver_config)
            deterministic_time += deterministic
            if objective_status != "OPTIMAL":
                canonical_status = f"{objective.objective_id}:{objective_status}"
                break
            value = solver.value(expression)
            model.add(expression == value)
            model.clear_objective()
            _refresh_hints(model, solver)
            if objective.kind is ObjectiveKind.PROPORTIONAL_SPLIT_BALANCE:
                balance_value = value
            else:
                hash_value = value

        objective_optimization_wall_s = time.perf_counter() - optimization_started
        candidates = problem.candidates
        if canonical_status == "OPTIMAL":
            canonicalization_started = time.perf_counter()
            for start in range(0, len(candidates), solver_config.canonical_chunk_size):
                chunk = candidates[start : start + solver_config.canonical_chunk_size]
                expression = sum(
                    _STATE_RANK[state]
                    * (4 ** (len(chunk) - 1 - offset))
                    * assignment_vars[(candidate.candidate_id, state)]
                    for offset, candidate in enumerate(chunk)
                    for state in _STATE_ORDER
                )
                model.minimize(expression)
                solver, objective_status, deterministic = _solve_once(model, solver_config)
                deterministic_time += deterministic
                if objective_status != "OPTIMAL":
                    canonical_status = f"CANONICAL_CHUNK:{start}:{objective_status}"
                    break
                value = solver.value(expression)
                model.add(expression == value)
                model.clear_objective()
                _refresh_hints(model, solver)
            canonicalization_wall = time.perf_counter() - canonicalization_started

        solver_wall_s = time.perf_counter() - started
        if canonical_status != "OPTIMAL":
            solve_status = SolveStatus.UNKNOWN
            diagnostics = (
                SelectionDiagnostic(
                    "CANONICALIZATION_UNKNOWN",
                    "Canonicalization returned "
                    f"{canonical_status}; the incumbent was not accepted.",
                ),
            )
        else:
            assignments = tuple(
                (candidate.candidate_id, state)
                for candidate in candidates
                for state in _STATE_ORDER
                if solver.boolean_value(assignment_vars[(candidate.candidate_id, state)])
            )
            plan = FinalSelectionPlan(
                assignments=tuple(
                    CandidateAssignment(
                        candidate_id=candidate_id,
                        state=state,
                    )
                    for candidate_id, state in assignments
                ),
                authority_digest=problem.authority_digest,
                problem_digest=problem.problem_digest,
                approved_pool_digest=problem.approved_pool_digest,
            )
            validation = validate_final_selection(problem, plan)
            if validation.status is ValidationStatus.INVALID:
                solve_status = SolveStatus.UNKNOWN
                diagnostics = (
                    SelectionDiagnostic(
                        "SEMANTIC_VALIDATION_FAILED",
                        "The independent validator rejected the CP-SAT plan.",
                        validation.violated_constraint_ids,
                    ),
                )
                plan = None
            else:
                solve_status = SolveStatus.OPTIMAL
    if solver_wall_s == 0.0:
        solver_wall_s = time.perf_counter() - started
    receipt = SelectionSolveReceipt(
        receipt_version=SELECTION_RECEIPT_VERSION,
        solver_family=_SOLVER_FAMILY,
        solver_version=version("ortools"),
        solver_config=solver_config,
        status=solve_status,
        authority_digest=problem.authority_digest,
        problem_digest=problem.problem_digest,
        approved_pool_digest=problem.approved_pool_digest,
        constraint_inventory_digest=problem.constraint_inventory_digest,
        variable_count=variable_count,
        constraint_count=constraint_count,
        warm_start_used=warm_start_used,
        wall_s=solver_wall_s,
        objective_optimization_wall_s=objective_optimization_wall_s,
        canonicalization_wall_s=canonicalization_wall,
        deterministic_time_s=deterministic_time,
        peak_rss_mb=_peak_rss_mb(),
        balance_objective=balance_value,
        hash_preference_objective=hash_value,
        plan_digest=(
            plan.plan_digest
            if plan is not None
            else (validation.plan_digest if validation is not None else None)
        ),
        validation_digest=validation.validation_digest if validation else None,
        summary=validation.summary if validation else None,
    )
    return FinalSelectionResult(
        plan=plan,
        solve_receipt=receipt,
        validation_receipt=validation,
        diagnostics=diagnostics,
    )


__all__ = ["solve_final_selection"]
