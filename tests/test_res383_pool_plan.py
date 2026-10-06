from __future__ import annotations

from types import SimpleNamespace

import pytest

from dynamislm.benchmark.constants import CRITICAL_ERROR_CLASSES, CaseOrigin, SplitName
from dynamislm.benchmark.selection_contracts import (
    PSE_V1_PRODUCTION_SELECTION_SOLVER_PROFILE_V2,
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
    ValidationStatus,
)
from dynamislm.benchmark.selection_pool import (
    GovernedBackfillCandidateV1,
    derive_pool_backfill_needs,
    plan_variable_pool,
    qualify_candidate_removal_reserve,
)
from dynamislm.benchmark.selection_solver import solve_selection_feasibility
from dynamislm.serialization import canonical_hash


def _candidate(
    candidate_id: str,
    *,
    critical: bool = False,
    origin: CaseOrigin = CaseOrigin.EXPERT_AUTHORED_SEMANTIC,
    review: ReviewEligibility = ReviewEligibility.APPROVED,
) -> FinalSelectionCandidate:
    features = (
        (SelectionFeature(FeatureKind.CRITICAL_ERROR, (CRITICAL_ERROR_CLASSES[0].value,)),)
        if critical
        else ()
    )
    return FinalSelectionCandidate(
        candidate_id=candidate_id,
        payload_hash=canonical_hash(("RES383-ABSTRACT", candidate_id)),
        origin_class=origin,
        review_eligibility=review,
        features=features,
        balance_cells=(),
        isolation_cluster_id=f"cluster:{candidate_id}",
        allocation_stratum="res383-abstract",
        cell=("C01", "F01"),
        isolation_identities=(
            IsolationIdentity(IsolationIdentityKind.SOURCE_FAMILY, f"family:{candidate_id}"),
        ),
        exact_shingle_digests=(canonical_hash(("RES383-ABSTRACT-SHINGLE", candidate_id)),),
    )


def _problem(
    candidates: tuple[FinalSelectionCandidate, ...],
    *,
    final_count: int,
    critical_split: SplitName | None = None,
) -> FinalSelectionProblem:
    constraints = [
        SelectionConstraint(
            constraint_id=f"RES369:ONE_STATE:{item.candidate_id}",
            authority_ref="RES-369 one four-state assignment per candidate",
            kind=ConstraintKind.ONE_STATE_PER_CANDIDATE,
            candidate_ids=(item.candidate_id,),
        )
        for item in candidates
    ]
    constraints.extend(
        (
            SelectionConstraint(
                constraint_id="RES258:FINAL_SELECTED_N",
                authority_ref="test final count",
                kind=ConstraintKind.FINAL_COUNT,
                minimum=final_count,
                maximum=final_count,
            ),
            *(
                SelectionConstraint(
                    constraint_id=f"RES258:SPLIT_COUNT:{split.value}",
                    authority_ref="test split count",
                    kind=ConstraintKind.SPLIT_COUNT,
                    split=split,
                    minimum=(
                        final_count
                        if split is (critical_split or SplitName.PUBLIC_DEVELOPMENT)
                        else 0
                    ),
                    maximum=(
                        final_count
                        if split is (critical_split or SplitName.PUBLIC_DEVELOPMENT)
                        else 0
                    ),
                )
                for split in SplitName
            ),
        )
    )
    if critical_split is not None:
        constraints.append(
            SelectionConstraint(
                constraint_id="DR001:CRITICAL_TEST",
                authority_ref="test critical minimum",
                kind=ConstraintKind.FEATURE_MINIMUM,
                split=critical_split,
                feature=SelectionFeature(
                    FeatureKind.CRITICAL_ERROR,
                    (CRITICAL_ERROR_CLASSES[0].value,),
                ),
                minimum=1,
            )
        )
    return FinalSelectionProblem(
        candidates=candidates,
        constraint_set=SelectionConstraintSet(
            constraints=tuple(sorted(constraints, key=lambda item: item.constraint_id.encode()))
        ),
        authority_digest=canonical_hash("RES383-TEST-AUTHORITY"),
    )


def test_feasibility_only_returns_independently_validated_witness() -> None:
    problem = _problem((_candidate("a"), _candidate("b")), final_count=1)
    receipt = solve_selection_feasibility(problem)
    assert receipt.status is FeasibilityStatus.FEASIBLE
    assert receipt.validation_status.value == "VALID"
    assert receipt.plan_digest is not None
    assert receipt.optimization_performed is False
    assert receipt.canonicalization_performed is False


def test_feasibility_only_rejects_a_witness_denied_by_the_semantic_validator(monkeypatch) -> None:
    from dynamislm.benchmark import selection_solver

    problem = _problem((_candidate("a"), _candidate("b")), final_count=1)
    monkeypatch.setattr(
        selection_solver,
        "validate_final_selection",
        lambda *_args: SimpleNamespace(
            status=ValidationStatus.INVALID,
            validation_digest=canonical_hash("RES383-REJECTED-WITNESS"),
            summary=None,
            violated_constraint_ids=("DR001:ADVERSARIAL_REJECTION",),
        ),
    )
    receipt = solve_selection_feasibility(problem)
    assert receipt.status is FeasibilityStatus.UNKNOWN
    assert receipt.plan_digest is None
    assert receipt.diagnostics[0].code == "SEMANTIC_VALIDATION_FAILED"


def test_production_profile_v2_is_reserved_for_final_canonical_confirmation() -> None:
    problem = _problem((_candidate("a"), _candidate("b")), final_count=1)
    with pytest.raises(ValueError, match="reserved for final canonical confirmation"):
        solve_selection_feasibility(
            problem,
            solver_config=PSE_V1_PRODUCTION_SELECTION_SOLVER_PROFILE_V2,
        )


def test_each_single_candidate_removal_has_an_exact_feasible_solution() -> None:
    problem = _problem((_candidate("a"), _candidate("b")), final_count=1)
    baseline, removals = qualify_candidate_removal_reserve(problem)
    assert baseline.status is FeasibilityStatus.FEASIBLE
    assert len(removals) == 2
    assert all(item.status is FeasibilityStatus.FEASIBLE for item in removals)


def test_final_count_lower_bound_is_an_exact_removal_failure() -> None:
    problem = _problem((_candidate("only"),), final_count=1)
    baseline, removals = qualify_candidate_removal_reserve(problem)
    assert baseline.status is FeasibilityStatus.FEASIBLE
    assert len(removals) == 1
    assert removals[0].status is FeasibilityStatus.INFEASIBLE
    assert removals[0].proof_method == "FINAL_COUNT_LOWER_BOUND"


def test_critical_reserve_need_is_two_candidates_per_feature_and_split() -> None:
    problem = _problem(
        (_candidate("only-critical", critical=True),),
        final_count=1,
        critical_split=SplitName.FROZEN_VALIDATION,
    )
    needs = derive_pool_backfill_needs(problem)
    by_id = {item.constraint_id: item for item in needs}
    assert by_id["DR001:CRITICAL_TEST"].present_candidate_count == 1
    assert by_id["DR001:CRITICAL_TEST"].required_candidate_count == 2
    assert by_id["DR001:CRITICAL_TEST"].missing_candidate_count == 1


def test_critical_reserve_requires_exact_feasibility_after_either_removal() -> None:
    problem = _problem(
        (_candidate("critical-a", critical=True), _candidate("critical-b", critical=True)),
        final_count=1,
        critical_split=SplitName.FROZEN_VALIDATION,
    )
    baseline, removals = qualify_candidate_removal_reserve(problem)
    assert baseline.status is FeasibilityStatus.FEASIBLE
    assert len(removals) == 2
    assert all(item.status is FeasibilityStatus.FEASIBLE for item in removals)


def test_planner_keeps_review_pending_and_adds_only_governed_backfill_for_a_need() -> None:
    initial = (
        _candidate("expert-a", review=ReviewEligibility.PENDING),
        _candidate("expert-b", review=ReviewEligibility.PENDING),
    )
    source_backfill = GovernedBackfillCandidateV1(
        _candidate(
            "source-backfill",
            origin=CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION,
            review=ReviewEligibility.PENDING,
        ),
        authority_ref="Phase-A supported source metadata",
        authority_digest=canonical_hash("RES383-TEST-PHASE-A"),
    )
    result = plan_variable_pool(initial, governed_backfill_candidates=(source_backfill,))

    assert result.receipt.status.value == "AUTHORITY_EXPANSION_REQUIRED"
    assert result.receipt.initial_candidate_count == 2
    assert result.receipt.candidate_count == 3
    assert result.receipt.backfill_candidate_count == 1
    assert result.plan.backfill_authorities[0][0] == "source-backfill"
    assert all(
        candidate.review_eligibility is ReviewEligibility.PENDING
        for candidate in result.plan.candidates
        if candidate.candidate_id in {"expert-a", "expert-b"}
    )
    assert result.receipt.human_review_performed is False
    assert result.receipt.protected_membership_persisted is False
