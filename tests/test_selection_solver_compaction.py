from itertools import product

from dynamislm.benchmark.constants import SPLIT_ORDER, CaseOrigin, SplitName
from dynamislm.benchmark.selection_contracts import (
    PSE_V1_POOL_FEASIBILITY_SOLVER_PROFILE_V1,
    PSE_V1_PRODUCTION_SELECTION_SOLVER_PROFILE_V1,
    PSE_V1_PRODUCTION_SELECTION_SOLVER_PROFILE_V2,
    AssignmentState,
    ConstraintKind,
    FeasibilityStatus,
    FinalSelectionProblem,
    RelationKind,
    ReviewEligibility,
    SelectionConstraint,
    SelectionSolverConfig,
    SolveStatus,
    ValidationStatus,
)
from dynamislm.benchmark.selection_solver import (
    _model_for,
    _solve_once,
    solve_final_selection,
    solve_selection_feasibility,
)
from dynamislm.benchmark.selection_validation import validate_final_selection
from dynamislm.serialization import canonical_hash
from test_res369_selection import _candidate, _toy_problem

PUBLIC = SplitName.PUBLIC_DEVELOPMENT
VALIDATION = SplitName.FROZEN_VALIDATION
_FAST_CONFIG = SelectionSolverConfig(workers=1, timeout_s=5.0)


def _relation() -> SelectionConstraint:
    return SelectionConstraint(
        "TEST:COLOCATION",
        "synthetic compact-encoding fixture",
        ConstraintKind.CONDITIONAL_COLOCATION,
        candidate_ids=("a", "b"),
        relation_kind=RelationKind.ISOLATION_CLUSTER,
    )


def _model_status(problem: FinalSelectionProblem, *, compact: bool) -> str:
    model, _assignments, _balance, _hash = _model_for(
        problem,
        include_objectives=False,
        compact_candidate_states=compact,
        compact_colocation_indicators=compact,
    )
    return _solve_once(model, _FAST_CONFIG)[1]


def test_default_model_and_solver_entrypoints_keep_production_encoding() -> None:
    related = _toy_problem(
        (_candidate("a"), _candidate("b")),
        ((PUBLIC, 1), (VALIDATION, 1)),
        extra=(_relation(),),
    )
    default_model, _assignments, _balance, _hash = _model_for(related, include_objectives=False)
    compact_model, _assignments, _balance, _hash = _model_for(
        related,
        include_objectives=False,
        compact_candidate_states=True,
        compact_colocation_indicators=True,
    )
    assert (len(default_model.proto.variables), len(default_model.proto.constraints)) == (11, 18)
    assert (len(compact_model.proto.variables), len(compact_model.proto.constraints)) == (9, 15)
    assert _solve_once(default_model, _FAST_CONFIG)[1] == "INFEASIBLE"
    assert _solve_once(compact_model, _FAST_CONFIG)[1] == "INFEASIBLE"

    feasible = _toy_problem((_candidate("only"),), ((PUBLIC, 1),))
    production_model, _assignments, _balance, _hash = _model_for(feasible)
    assert _solve_once(production_model, _FAST_CONFIG)[1] == "OPTIMAL"

    final_result = solve_final_selection(feasible)
    assert final_result.solve_receipt.status is SolveStatus.OPTIMAL
    assert final_result.solve_receipt.solver_config == SelectionSolverConfig()
    assert final_result.solve_receipt.variable_count == len(production_model.proto.variables)
    assert final_result.solve_receipt.constraint_count == len(production_model.proto.constraints)
    assert final_result.plan is not None
    assert {item.candidate_id: item.state for item in final_result.plan.assignments} == {
        "only": AssignmentState.PUBLIC_DEVELOPMENT
    }
    assert final_result.validation_receipt is not None
    assert final_result.validation_receipt.status is ValidationStatus.VALID
    assert validate_final_selection(feasible, final_result.plan).status is ValidationStatus.VALID

    feasibility_result = solve_selection_feasibility(feasible)
    assert feasibility_result.status is FeasibilityStatus.FEASIBLE
    assert feasibility_result.validation_status is ValidationStatus.VALID
    assert feasibility_result.solver_config == SelectionSolverConfig()
    assert feasibility_result.variable_count == len(production_model.proto.variables)
    assert feasibility_result.constraint_count == len(production_model.proto.constraints)

    infeasible = _toy_problem((_candidate("only"),), ((PUBLIC, 2),))
    assert _model_status(infeasible, compact=False) == "INFEASIBLE"
    assert _model_status(infeasible, compact=True) == "INFEASIBLE"
    assert solve_final_selection(infeasible).solve_receipt.status is SolveStatus.INFEASIBLE
    assert solve_selection_feasibility(infeasible).status is FeasibilityStatus.INFEASIBLE


def test_production_solver_profiles_are_unchanged() -> None:
    assert PSE_V1_PRODUCTION_SELECTION_SOLVER_PROFILE_V1 == SelectionSolverConfig(
        workers=8,
        random_seed=369,
        timeout_s=60.0,
        canonical_chunk_size=30,
        cp_model_presolve=False,
        randomize_search=False,
    )
    assert PSE_V1_PRODUCTION_SELECTION_SOLVER_PROFILE_V2 == SelectionSolverConfig(
        workers=8,
        random_seed=369,
        timeout_s=120.0,
        canonical_chunk_size=15,
        cp_model_presolve=False,
        randomize_search=False,
    )
    assert PSE_V1_POOL_FEASIBILITY_SOLVER_PROFILE_V1 == SelectionSolverConfig(
        workers=8,
        random_seed=369,
        timeout_s=120.0,
        canonical_chunk_size=30,
        cp_model_presolve=False,
        randomize_search=False,
    )


def test_compact_candidate_states_match_all_four_original_states() -> None:
    state_fixtures = (
        (AssignmentState.OUT, ()),
        (AssignmentState.PUBLIC_DEVELOPMENT, ((PUBLIC, 1),)),
        (AssignmentState.FROZEN_VALIDATION, ((VALIDATION, 1),)),
        (AssignmentState.HIDDEN_FINAL, ((SplitName.HIDDEN_FINAL, 1),)),
    )
    for expected_state, split_counts in state_fixtures:
        problem = _toy_problem((_candidate("state"),), split_counts)
        expected = tuple(int(state is expected_state) for state in AssignmentState)
        for compact in (False, True):
            model, assignments, _balance, _hash = _model_for(
                problem,
                include_objectives=False,
                compact_candidate_states=compact,
                compact_colocation_indicators=compact,
            )
            solver, status, _deterministic = _solve_once(model, _FAST_CONFIG)
            assert status == "OPTIMAL"
            assert (
                tuple(int(solver.value(assignments[("state", state)])) for state in AssignmentState)
                == expected
            )


def test_compact_out_expression_obeys_out_only_constraints() -> None:
    mutation = _candidate(
        "mutation",
        origin=CaseOrigin.ADVERSARIAL_MUTATION,
        lineage="missing-lineage",
        parent_id="missing-parent",
        parent_hash=canonical_hash("missing-parent"),
    )
    blocked = (
        _candidate("review", review=ReviewEligibility.PENDING),
        _candidate("qualification", excluded=True),
        mutation,
    )
    problem = _toy_problem(
        (*blocked, _candidate("approved-a"), _candidate("approved-b")),
        ((PUBLIC, 2),),
    )
    kinds = {item.kind for item in problem.constraint_set.constraints}
    assert ConstraintKind.REVIEW_OUT_ONLY in kinds
    assert ConstraintKind.QUALIFICATION_OUT_ONLY in kinds
    assert ConstraintKind.MUTATION_PARENT_PROVENANCE in kinds

    for compact in (False, True):
        model, assignments, _balance, _hash = _model_for(
            problem,
            include_objectives=False,
            compact_candidate_states=compact,
            compact_colocation_indicators=compact,
        )
        solver, status, _deterministic = _solve_once(model, _FAST_CONFIG)
        assert status == "OPTIMAL"
        assert all(
            solver.value(assignments[(item.candidate_id, AssignmentState.OUT)]) == 1
            for item in blocked
        )
        assert (
            sum(
                solver.value(assignments[(candidate_id, AssignmentState.PUBLIC_DEVELOPMENT)])
                for candidate_id in ("approved-a", "approved-b")
            )
            == 2
        )


def test_compact_colocation_preserves_every_two_member_assignment_projection() -> None:
    candidates = (_candidate("a"), _candidate("b"))
    edge = _relation()
    for states in product(tuple(AssignmentState), repeat=2):
        selected_counts = {
            split: sum(state is AssignmentState(split.value) for state in states)
            for split in SPLIT_ORDER
        }
        split_counts = tuple((split, count) for split, count in selected_counts.items() if count)
        problem = _toy_problem(candidates, split_counts, extra=(edge,))
        selected_splits = {state for state in states if state is not AssignmentState.OUT}
        expected_feasible = len(selected_splits) <= 1

        for compact in (False, True):
            model, assignments, _balance, _hash = _model_for(
                problem,
                include_objectives=False,
                compact_candidate_states=compact,
                compact_colocation_indicators=compact,
            )
            for candidate, state in zip(candidates, states, strict=True):
                model.add(assignments[(candidate.candidate_id, state)] == 1)
            _solver, status, _deterministic = _solve_once(model, _FAST_CONFIG)
            assert status in ({"OPTIMAL", "FEASIBLE"} if expected_feasible else {"INFEASIBLE"})


def test_compact_colocation_requires_indicator_for_selected_split_member() -> None:
    problem = _toy_problem(
        (_candidate("a"), _candidate("b")),
        ((PUBLIC, 1),),
        extra=(_relation(),),
    )
    model, assignments, _balance, _hash = _model_for(
        problem,
        include_objectives=False,
        compact_candidate_states=True,
        compact_colocation_indicators=True,
    )
    indicator_name = f"colocate[TEST:COLOCATION,{SPLIT_ORDER.index(PUBLIC)}]"
    indicator_index = next(
        index
        for index, variable in enumerate(model.proto.variables)
        if variable.name == indicator_name
    )
    indicator = model.get_bool_var_from_proto_index(indicator_index)
    model.add(assignments[("a", AssignmentState.PUBLIC_DEVELOPMENT)] == 1)
    model.add(indicator == 0)
    assert _solve_once(model, _FAST_CONFIG)[1] == "INFEASIBLE"
