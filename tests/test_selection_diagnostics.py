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
    selection_constraint_families,
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


def test_family_ablation_keeps_one_state_and_validates_its_witness() -> None:
    problem = _problem()
    family_ids = set(
        dict(selection_constraint_families(problem))["QUALIFICATION/ELIGIBILITY_FORCING"]
    )
    config = SelectionSolverConfig(
        workers=1,
        random_seed=369,
        timeout_s=5.0,
        cp_model_presolve=False,
    )
    baseline = solve_selection_feasibility(problem, solver_config=config)
    relaxed = clone_selection_problem(
        problem,
        (
            item
            for item in problem.constraint_set.constraints
            if item.constraint_id not in family_ids
        ),
    )

    assert baseline.status is FeasibilityStatus.INFEASIBLE
    assert relaxed.candidates == problem.candidates
    assert sum(
        item.kind is ConstraintKind.ONE_STATE_PER_CANDIDATE
        for item in relaxed.constraint_set.constraints
    ) == len(problem.candidates)
    result = solve_selection_feasibility(relaxed, solver_config=config)
    assert result.status is FeasibilityStatus.FEASIBLE
    assert result.plan_digest is not None and result.validation_digest is not None


def test_family_inventory_omits_one_state_and_groups_by_feature_kind() -> None:
    problem = _problem()

    families = dict(selection_constraint_families(problem))

    assert "ONE_STATE_PER_CANDIDATE" not in families
    assert families["FEATURE_MINIMUM:CELL"] == ("TEST:FEATURE_MINIMUM",)
    assert len(families["QUALIFICATION/ELIGIBILITY_FORCING"]) == 2
    without_feature = clone_selection_problem(
        problem,
        (
            item
            for item in problem.constraint_set.constraints
            if item.constraint_id != "TEST:FEATURE_MINIMUM"
        ),
    )
    assert without_feature.candidates == problem.candidates
    assert sum(
        item.kind is ConstraintKind.ONE_STATE_PER_CANDIDATE
        for item in without_feature.constraint_set.constraints
    ) == len(problem.candidates)
