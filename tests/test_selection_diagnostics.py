from __future__ import annotations

from dynamislm.benchmark.constants import CaseOrigin, SplitName
from dynamislm.benchmark.selection_contracts import (
    ConstraintKind,
    FeasibilityStatus,
    FeatureKind,
    FinalSelectionCandidate,
    FinalSelectionProblem,
    IsolationIdentity,
    IsolationIdentityKind,
    ReviewEligibility,
    SelectionConstraint,
    SelectionConstraintSet,
    SelectionFeature,
    SelectionSolverConfig,
)
from dynamislm.benchmark.selection_diagnostics import (
    clone_selection_problem,
    final_count_forced_out_core,
    selection_support_audit,
)
from dynamislm.benchmark.selection_solver import solve_selection_feasibility
from dynamislm.serialization import canonical_hash


def _problem() -> FinalSelectionProblem:
    feature = SelectionFeature(FeatureKind.CELL, ("C01", "F01"))
    candidates = tuple(
        FinalSelectionCandidate(
            candidate_id=f"candidate-{index}",
            payload_hash=canonical_hash(("synthetic-diagnostic", index)),
            origin_class=CaseOrigin.EXPERT_AUTHORED_SEMANTIC,
            review_eligibility=ReviewEligibility.PENDING,
            features=(feature,),
            balance_cells=(),
            isolation_cluster_id=f"cluster-{index}",
            allocation_stratum="synthetic-diagnostic",
            cell=("C01", "F01"),
            isolation_identities=(
                IsolationIdentity(
                    IsolationIdentityKind.SOURCE_FAMILY,
                    f"family-{index}",
                ),
            ),
            exact_shingle_digests=(canonical_hash(("shingle", index)),),
        )
        for index in range(2)
    )
    constraints = [
        SelectionConstraint(
            f"TEST:ONE_STATE:{candidate.candidate_id}",
            "synthetic diagnostic fixture",
            ConstraintKind.ONE_STATE_PER_CANDIDATE,
            candidate_ids=(candidate.candidate_id,),
        )
        for candidate in candidates
    ]
    constraints.extend(
        (
            SelectionConstraint(
                "TEST:FINAL_COUNT",
                "synthetic diagnostic fixture",
                ConstraintKind.FINAL_COUNT,
                minimum=2,
                maximum=2,
            ),
            SelectionConstraint(
                "TEST:SPLIT_COUNT",
                "synthetic diagnostic fixture",
                ConstraintKind.SPLIT_COUNT,
                split=SplitName.PUBLIC_DEVELOPMENT,
                minimum=2,
                maximum=2,
            ),
            SelectionConstraint(
                "TEST:FEATURE_MINIMUM",
                "synthetic diagnostic fixture",
                ConstraintKind.FEATURE_MINIMUM,
                split=SplitName.PUBLIC_DEVELOPMENT,
                feature=feature,
                minimum=1,
            ),
            *(
                SelectionConstraint(
                    f"TEST:REVIEW_OUT:{candidate.candidate_id}",
                    "synthetic diagnostic fixture",
                    ConstraintKind.REVIEW_OUT_ONLY,
                    candidate_ids=(candidate.candidate_id,),
                    reason=ReviewEligibility.PENDING.value,
                )
                for candidate in candidates
            ),
        )
    )
    return FinalSelectionProblem(
        candidates=candidates,
        constraint_set=SelectionConstraintSet(
            tuple(sorted(constraints, key=lambda item: item.constraint_id.encode()))
        ),
        authority_digest=canonical_hash("synthetic diagnostic authority"),
    )


def test_static_support_audit_finds_forced_out_feature_deficit() -> None:
    problem = _problem()

    feature_row = next(
        row
        for row in selection_support_audit(problem)
        if row["constraint_id"] == "TEST:FEATURE_MINIMUM"
    )

    assert feature_row["raw_support_candidate_count"] == 2
    assert feature_row["maximum_support_compatible_with_split_locks"] == 0
    assert feature_row["forced_out_count"] == 2
    assert feature_row["individually_impossible"] is True


def test_final_count_forced_out_core_replays_and_is_subset_minimal() -> None:
    problem = _problem()
    core_ids = final_count_forced_out_core(problem)
    assert core_ids is not None
    core = clone_selection_problem(
        problem,
        (
            item
            for item in problem.constraint_set.constraints
            if item.kind is ConstraintKind.ONE_STATE_PER_CANDIDATE or item.constraint_id in core_ids
        ),
    )
    config = SelectionSolverConfig(
        workers=1,
        random_seed=369,
        timeout_s=5.0,
        cp_model_presolve=False,
    )

    assert (
        solve_selection_feasibility(core, solver_config=config).status
        is FeasibilityStatus.INFEASIBLE
    )
    for removed_id in core_ids:
        reduced = clone_selection_problem(
            problem,
            (
                item
                for item in problem.constraint_set.constraints
                if item.kind is ConstraintKind.ONE_STATE_PER_CANDIDATE
                or (item.constraint_id in core_ids and item.constraint_id != removed_id)
            ),
        )
        assert (
            solve_selection_feasibility(reduced, solver_config=config).status
            is FeasibilityStatus.FEASIBLE
        )
