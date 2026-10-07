from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from typing import Any

import pytest

from dynamislm.benchmark.authoring import production_seed_namespace
from dynamislm.benchmark.authority_supply import (
    AUTHORITY_SUPPLY_SCHEMA,
    AuthoritySupplyInventoryV1,
    BackfillRequestKind,
    LaneCapacityStatus,
    ReserveCandidateLaneV1,
    ReserveDeficitKind,
    SupplyAssessmentStatus,
)
from dynamislm.benchmark.constants import CRITICAL_ERROR_CLASSES, CaseOrigin, SplitName
from dynamislm.benchmark.selection_contracts import (
    PSE_V1_POOL_FEASIBILITY_SOLVER_PROFILE_V1,
    PSE_V1_PRODUCTION_SELECTION_SOLVER_PROFILE_V2,
    ConstraintKind,
    FeasibilityStatus,
    FeatureKind,
    FinalSelectionCandidate,
    FinalSelectionProblem,
    IsolationIdentity,
    IsolationIdentityKind,
    RelationKind,
    ReviewEligibility,
    SelectionConstraint,
    SelectionConstraintSet,
    SelectionFeature,
    SelectionSolverConfig,
    ValidationStatus,
)
from dynamislm.benchmark.selection_pool import (
    MaterializedBackfillCandidateV1,
    PoolPlanStatus,
    assess_authority_supply_inventory,
    derive_pool_backfill_needs,
    plan_variable_pool,
    qualify_candidate_removal_reserve,
    validate_materialized_backfill_lane_binding,
)
from dynamislm.benchmark.selection_solver import solve_selection_feasibility
from dynamislm.serialization import canonical_hash


def _candidate(
    candidate_id: str,
    *,
    critical: bool = False,
    origin: CaseOrigin = CaseOrigin.EXPERT_AUTHORED_SEMANTIC,
    review: ReviewEligibility = ReviewEligibility.APPROVED,
    excluded: bool = False,
    locked_split: SplitName | None = None,
    cell: tuple[str, str] = ("C01", "F01"),
    identities: tuple[IsolationIdentity, ...] | None = None,
    generator_seed_blocks: tuple[str, ...] = (),
    mutation_lineage_id: str | None = None,
    mutation_parent_candidate_id: str | None = None,
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
        qualification_excluded=excluded,
        locked_split=locked_split,
        mutation_lineage_id=mutation_lineage_id,
        mutation_parent_candidate_id=mutation_parent_candidate_id,
        generator_seed_blocks=generator_seed_blocks,
        features=features,
        balance_cells=(),
        isolation_cluster_id=f"cluster:{candidate_id}",
        allocation_stratum="res383-abstract",
        cell=cell,
        isolation_identities=tuple(
            sorted(
                identities
                or (
                    (
                        IsolationIdentity(
                            IsolationIdentityKind.SOURCE_FAMILY, "family:source-lane"
                        ),
                        IsolationIdentity(
                            IsolationIdentityKind.SOURCE_DOCUMENT, "document:source-lane"
                        ),
                    )
                    if origin is CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION
                    else (
                        IsolationIdentity(
                            IsolationIdentityKind.SOURCE_FAMILY,
                            f"family:{candidate_id}",
                        ),
                    )
                ),
                key=lambda item: (item.kind.value, item.identity.encode()),
            )
        ),
        exact_shingle_digests=(canonical_hash(("RES383-ABSTRACT-SHINGLE", candidate_id)),),
    )


def _problem(
    candidates: tuple[FinalSelectionCandidate, ...],
    *,
    final_count: int,
    critical_split: SplitName | None = None,
    source_minimum: int = 0,
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
    for item in candidates:
        if item.review_eligibility is not ReviewEligibility.APPROVED:
            constraints.append(
                SelectionConstraint(
                    constraint_id=f"RES258:REVIEW_OUT:{item.candidate_id}",
                    authority_ref="test review eligibility",
                    kind=ConstraintKind.REVIEW_OUT_ONLY,
                    candidate_ids=(item.candidate_id,),
                    reason=item.review_eligibility.value,
                )
            )
        if item.qualification_excluded:
            constraints.append(
                SelectionConstraint(
                    constraint_id=f"DR001:QUALIFICATION_OUT:{item.candidate_id}",
                    authority_ref="test qualification exclusion",
                    kind=ConstraintKind.QUALIFICATION_OUT_ONLY,
                    candidate_ids=(item.candidate_id,),
                )
            )
        if item.locked_split is not None:
            constraints.append(
                SelectionConstraint(
                    constraint_id=f"DR001:SYNTHETIC_LOCK:{item.candidate_id}",
                    authority_ref="test synthetic split lock",
                    kind=ConstraintKind.SYNTHETIC_SPLIT_LOCK,
                    candidate_ids=(item.candidate_id,),
                    locked_split=item.locked_split,
                )
            )
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
    if source_minimum:
        constraints.append(
            SelectionConstraint(
                constraint_id="RES126:SOURCE_MINIMUM",
                authority_ref="test source lower bound",
                kind=ConstraintKind.ORIGIN_BOUNDS,
                origin_class=CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION,
                minimum=source_minimum,
                maximum=final_count,
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


def _lane(
    lane_id: str,
    *,
    origin: CaseOrigin = CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION,
    capacity: int | None = 1,
    status: LaneCapacityStatus = LaneCapacityStatus.AVAILABLE,
    supported_cells: tuple[tuple[str, str], ...] = (("C01", "F01"),),
    identity_digests: tuple[str, ...] | None = None,
) -> ReserveCandidateLaneV1:
    return ReserveCandidateLaneV1(
        lane_id=lane_id,
        origin_class=origin,
        authority_ref="test governed authority lane",
        authority_digest=canonical_hash(("authority", lane_id)),
        capacity_unit="test candidate slot",
        existing_planned_capacity=0,
        available_capacity=capacity,
        capacity_status=status,
        capacity_rule=("test governed capacity rule" if capacity is None else None),
        supported_cells=supported_cells,
        isolation_identity_digests=identity_digests
        or (
            (
                canonical_hash(("SOURCE_FAMILY", "family:source-lane")),
                canonical_hash(("SOURCE_DOCUMENT", "document:source-lane")),
            )
            if origin is CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION
            else ()
        ),
    )


def _inventory(
    lanes: tuple[ReserveCandidateLaneV1, ...] = (),
    *,
    planned_counts: tuple[tuple[CaseOrigin, int], ...] = (),
    mutation_lineages: int = 0,
    capacity_scope_complete: bool = False,
) -> AuthoritySupplyInventoryV1:
    return AuthoritySupplyInventoryV1(
        schema_version=AUTHORITY_SUPPLY_SCHEMA,
        atoms=(),
        reserve_candidate_lanes=tuple(sorted(lanes, key=lambda item: item.lane_id.encode())),
        planned_origin_counts=tuple(
            sorted(planned_counts, key=lambda item: item[0].value.encode())
        ),
        planned_mutation_lineage_count=mutation_lineages,
        materialized_candidate_count=0,
        evidence_bindings=(),
        authority_inventory_complete=True,
        capacity_scope_complete=capacity_scope_complete,
    )


def _with_identity(
    candidate: FinalSelectionCandidate,
    kind: IsolationIdentityKind,
    identity: str,
) -> FinalSelectionCandidate:
    identities = tuple(
        sorted(
            {
                *(item for item in candidate.isolation_identities if item.kind is not kind),
                IsolationIdentity(kind, identity),
            },
            key=lambda item: (item.kind.value, item.identity.encode()),
        )
    )
    return replace(candidate, isolation_identities=identities)


def _identity_digest(*parts: object) -> str:
    return canonical_hash(parts)


def test_materialized_backfill_binding_requires_exact_cell_and_origin_identities() -> None:
    source = _candidate("source", origin=CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION)
    source_lane = _lane(
        "source",
        identity_digests=tuple(
            sorted(
                (
                    _identity_digest("SOURCE_FAMILY", "family:source-lane"),
                    _identity_digest("SOURCE_DOCUMENT", "document:source-lane"),
                )
            )
        ),
    )
    cross_product_lane = _lane(
        "source-exact-pairs",
        supported_cells=(("C01", "F01"), ("C02", "F02")),
    )

    engine_ref = "res71-reference-a"
    engine = _candidate(
        "engine",
        origin=CaseOrigin.DETERMINISTIC_ENGINE_DERIVED,
        cell=("C08", "F05"),
        identities=(
            IsolationIdentity(IsolationIdentityKind.SOURCE_FAMILY, "family:engine"),
            IsolationIdentity(IsolationIdentityKind.RES71_ENGINE_REFERENCE_CASE, engine_ref),
        ),
    )
    engine_lane = _lane(
        "engine",
        origin=engine.origin_class,
        supported_cells=(engine.cell,),
        identity_digests=(_identity_digest("RES71_ENGINE_REFERENCE_CASE", engine_ref),),
    )

    generator_family = "res115-synthetic-refusal-hidden_final"
    split = SplitName.HIDDEN_FINAL
    namespace = production_seed_namespace(split, "res115.synthetic-refusal", "1.0.0", "block-001")
    synthetic = _candidate(
        "synthetic",
        origin=CaseOrigin.DETERMINISTIC_SYNTHETIC,
        cell=("C08", "F05"),
        locked_split=split,
        generator_seed_blocks=("block-001",),
        identities=(
            IsolationIdentity(IsolationIdentityKind.SOURCE_FAMILY, "family:synthetic"),
            IsolationIdentity(IsolationIdentityKind.GENERATOR_FAMILY, generator_family),
            IsolationIdentity(IsolationIdentityKind.GENERATOR_SEED_NAMESPACE, namespace),
        ),
    )
    synthetic_lane = _lane(
        "synthetic",
        origin=synthetic.origin_class,
        supported_cells=(synthetic.cell,),
        identity_digests=tuple(
            sorted(
                (
                    _identity_digest("SYNTHETIC_GENERATOR", "res115.synthetic-refusal", "1.0.0"),
                    _identity_digest("GENERATOR_FAMILY", generator_family),
                    _identity_digest("SYNTHETIC_SPLIT_LOCK", split.value),
                )
            )
        ),
    )

    expert_batch = "expert-batch-a"
    template = "protocol-template-a"
    expert_cluster = "expert-cluster-a"
    expert = _candidate(
        "expert",
        identities=(
            IsolationIdentity(IsolationIdentityKind.SOURCE_FAMILY, "family:expert"),
            IsolationIdentity(IsolationIdentityKind.EXPERT_AUTHOR_BATCH, expert_batch),
            IsolationIdentity(IsolationIdentityKind.PROTOCOL_TEMPLATE, template),
        ),
    )
    expert = replace(expert, isolation_cluster_id=expert_cluster)
    expert_lane = _lane(
        "expert",
        origin=expert.origin_class,
        identity_digests=tuple(
            sorted(
                (
                    _identity_digest("EXPERT_BATCH", expert_batch),
                    _identity_digest("PROTOCOL_TEMPLATE", template),
                    _identity_digest("EXPERT_ISOLATION_CLUSTER", expert_cluster),
                )
            )
        ),
    )

    parent = "parent-candidate-a"
    lineage = "mutation-lineage-a"
    mutation = _candidate(
        "mutation",
        origin=CaseOrigin.ADVERSARIAL_MUTATION,
        identities=(
            IsolationIdentity(IsolationIdentityKind.SOURCE_FAMILY, "family:mutation"),
            IsolationIdentity(IsolationIdentityKind.MUTATION_PARENT, parent),
            IsolationIdentity(IsolationIdentityKind.MUTATION_LINEAGE, lineage),
        ),
        mutation_parent_candidate_id=parent,
        mutation_lineage_id=lineage,
    )
    mutation_lane = _lane(
        "mutation",
        origin=mutation.origin_class,
        identity_digests=tuple(
            sorted(
                (
                    _identity_digest("MUTATION_PARENT", parent),
                    _identity_digest("MUTATION_LINEAGE", lineage),
                )
            )
        ),
    )

    for candidate, lane in (
        (source, source_lane),
        (engine, engine_lane),
        (synthetic, synthetic_lane),
        (expert, expert_lane),
        (mutation, mutation_lane),
    ):
        binding = MaterializedBackfillCandidateV1(
            candidate, lane.lane_id, lane.authority_ref, lane.authority_digest
        )
        validate_materialized_backfill_lane_binding(binding, lane)

    source_binding = MaterializedBackfillCandidateV1(
        source, source_lane.lane_id, source_lane.authority_ref, source_lane.authority_digest
    )
    wrong_candidates = (
        replace(source, cell=("C02", "F01")),
        _candidate(
            "cross-cell",
            origin=CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION,
            cell=("C01", "F02"),
        ),
        _with_identity(source, IsolationIdentityKind.SOURCE_DOCUMENT, "document:other"),
        _with_identity(source, IsolationIdentityKind.SOURCE_FAMILY, "family:other"),
        _with_identity(
            engine, IsolationIdentityKind.RES71_ENGINE_REFERENCE_CASE, "res71-reference-b"
        ),
        _with_identity(
            synthetic,
            IsolationIdentityKind.GENERATOR_FAMILY,
            "another-synthetic-generator-family",
        ),
        _with_identity(
            synthetic,
            IsolationIdentityKind.GENERATOR_SEED_NAMESPACE,
            production_seed_namespace(
                split,
                "another-synthetic-generator",
                "1.0.0",
                "block-001",
            ),
        ),
        replace(
            _with_identity(
                synthetic,
                IsolationIdentityKind.GENERATOR_SEED_NAMESPACE,
                production_seed_namespace(
                    SplitName.PUBLIC_DEVELOPMENT,
                    "res115.synthetic-refusal",
                    "1.0.0",
                    "block-002",
                ),
            ),
            locked_split=SplitName.PUBLIC_DEVELOPMENT,
            generator_seed_blocks=("block-002",),
        ),
        _with_identity(expert, IsolationIdentityKind.EXPERT_AUTHOR_BATCH, "expert-batch-b"),
        replace(
            _with_identity(mutation, IsolationIdentityKind.MUTATION_LINEAGE, "mutation-lineage-b"),
            mutation_lineage_id="mutation-lineage-b",
        ),
    )
    lanes = (
        source_lane,
        cross_product_lane,
        source_lane,
        source_lane,
        engine_lane,
        synthetic_lane,
        synthetic_lane,
        synthetic_lane,
        expert_lane,
        mutation_lane,
    )
    for candidate, lane in zip(wrong_candidates, lanes, strict=True):
        binding = replace(
            source_binding,
            candidate=candidate,
            lane_id=lane.lane_id,
            authority_ref=lane.authority_ref,
            authority_digest=lane.authority_digest,
        )
        with pytest.raises(ValueError, match="backfill candidate"):
            validate_materialized_backfill_lane_binding(binding, lane)


def test_feasibility_only_returns_independently_validated_witness() -> None:
    problem = _problem((_candidate("a"), _candidate("b")), final_count=1)
    receipt = solve_selection_feasibility(problem)
    assert receipt.status is FeasibilityStatus.FEASIBLE
    assert receipt.validation_status is ValidationStatus.VALID
    assert receipt.plan_digest is not None
    assert receipt.optimization_performed is False
    assert receipt.canonicalization_performed is False


def test_named_pool_profile_solves_a_locked_critical_selection() -> None:
    reference_identity = IsolationIdentity(
        IsolationIdentityKind.RES71_ENGINE_REFERENCE_CASE,
        "res71-profile-fixture-reference",
    )
    paired = tuple(
        replace(
            _candidate(candidate_id, critical=candidate_id in {"a", "c"}),
            isolation_identities=tuple(
                sorted(
                    (*_candidate(candidate_id).isolation_identities, reference_identity),
                    key=lambda item: (item.kind.value, item.identity.encode()),
                )
            ),
        )
        for candidate_id in ("a", "b")
    )
    problem = _problem(
        (
            *paired,
            _candidate(
                "c",
                critical=True,
                origin=CaseOrigin.DETERMINISTIC_SYNTHETIC,
                locked_split=SplitName.FROZEN_VALIDATION,
            ),
        ),
        final_count=2,
        critical_split=SplitName.FROZEN_VALIDATION,
    )
    relation = SelectionConstraint(
        constraint_id="DR001:CONDITIONAL_COLOCATION:RES71_FIXTURE",
        authority_ref="test RES-71 co-location",
        kind=ConstraintKind.CONDITIONAL_COLOCATION,
        candidate_ids=("a", "b"),
        relation_kind=RelationKind.ISOLATION_IDENTITY,
    )
    constraints = tuple(
        sorted(
            (*problem.constraint_set.constraints, relation),
            key=lambda item: item.constraint_id.encode(),
        )
    )
    problem = replace(
        problem,
        constraint_set=replace(problem.constraint_set, constraints=constraints),
    )
    receipt = solve_selection_feasibility(
        problem,
        solver_config=PSE_V1_POOL_FEASIBILITY_SOLVER_PROFILE_V1,
    )
    assert receipt.status is FeasibilityStatus.FEASIBLE
    assert receipt.solver_config == PSE_V1_POOL_FEASIBILITY_SOLVER_PROFILE_V1


def test_feasibility_only_rejects_a_witness_denied_by_the_semantic_validator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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


def test_pool_qualification_rejects_generic_solver_configuration() -> None:
    problem = _problem((_candidate("a"), _candidate("b")), final_count=1)
    with pytest.raises(ValueError, match="named pool-feasibility solver profile"):
        qualify_candidate_removal_reserve(problem, solver_config=SelectionSolverConfig())


def test_each_single_candidate_removal_has_an_exact_feasible_solution() -> None:
    problem = _problem((_candidate("a"), _candidate("b")), final_count=1)
    baseline, removals = qualify_candidate_removal_reserve(problem)
    assert baseline.status is FeasibilityStatus.FEASIBLE
    assert len(removals) == 2
    assert all(item.status is FeasibilityStatus.FEASIBLE for item in removals)
    assert baseline.solver_config == PSE_V1_POOL_FEASIBILITY_SOLVER_PROFILE_V1


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


def test_payload_free_lane_has_no_candidate_payload_or_shingle_fields() -> None:
    lane = _lane("source-lane")
    assert lane.may_author_backfill
    assert not hasattr(lane, "payload_hash")
    assert not hasattr(lane, "exact_shingle_digests")
    assert lane.lane_digest.startswith("sha256:")


def test_inventory_reports_floor_and_requests_without_claiming_derived_pool_size() -> None:
    inventory = _inventory(
        (
            _lane("source", origin=CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION),
            _lane(
                "synthetic",
                origin=CaseOrigin.DETERMINISTIC_SYNTHETIC,
                capacity=None,
                status=LaneCapacityStatus.RULE_GOVERNED,
            ),
        ),
        planned_counts=(
            (CaseOrigin.EXPERT_AUTHORED_SEMANTIC, 240),
            (CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION, 40),
            (CaseOrigin.DETERMINISTIC_ENGINE_DERIVED, 31),
            (CaseOrigin.DETERMINISTIC_SYNTHETIC, 12),
            (CaseOrigin.ADVERSARIAL_MUTATION, 111),
        ),
        mutation_lineages=37,
    )
    assessment = assess_authority_supply_inventory(inventory)
    count_requests = {
        item.required_origin: item
        for item in assessment.backfill_requests
        if item.request_kind is BackfillRequestKind.CONSTRAINT_MINIMUM
    }
    assert assessment.status is SupplyAssessmentStatus.BACKFILL_REQUIRED
    assert assessment.planned_candidate_count == 434
    assert assessment.materialized_candidate_count == 0
    assert assessment.usable_reserve_capacity_count == 0
    assert assessment.known_structural_pool_floor == 436
    assert assessment.derived_pool_n is None
    assert count_requests[CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION].requested_capacity == 1
    assert count_requests[CaseOrigin.DETERMINISTIC_SYNTHETIC].requested_capacity == 1
    assert assessment.exact_qualification_status is SupplyAssessmentStatus.METADATA_REQUIRED
    with pytest.raises(ValueError, match="complete proof of exhausted governed lanes"):
        replace(assessment, status=SupplyAssessmentStatus.AUTHORITY_EXPANSION_REQUIRED)


def test_missing_count_lane_is_not_expansion_without_complete_capacity_scope() -> None:
    inventory = _inventory(
        planned_counts=((CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION, 40),),
    )
    assert (
        assess_authority_supply_inventory(inventory).status
        is SupplyAssessmentStatus.METADATA_REQUIRED
    )


def test_planner_backfills_only_from_a_bound_lane_and_qualifies_removals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dynamislm.benchmark import selection_pool

    monkeypatch.setattr(
        selection_pool,
        "_build_problem",
        lambda values, _parents: _problem(
            selection_pool._planning_candidates(values), final_count=1, source_minimum=1
        ),
    )
    initial = (
        _candidate("expert-a", review=ReviewEligibility.PENDING),
        _candidate(
            "source-a",
            origin=CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION,
            review=ReviewEligibility.PENDING,
        ),
    )
    lane = _lane("source-lane")
    inventory = _inventory((lane,))
    backfill = MaterializedBackfillCandidateV1(
        candidate=_candidate(
            "source-b",
            origin=CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION,
            review=ReviewEligibility.PENDING,
        ),
        lane_id=lane.lane_id,
        authority_ref=lane.authority_ref,
        authority_digest=lane.authority_digest,
    )
    result = plan_variable_pool(
        initial,
        supply_inventory=inventory,
        materialized_backfill_candidates=(backfill,),
        solver_config=PSE_V1_POOL_FEASIBILITY_SOLVER_PROFILE_V1,
    )
    assert result.receipt.status is PoolPlanStatus.QUALIFIED
    assert result.receipt.initial_candidate_count == 2
    assert result.receipt.candidate_count == 3
    assert result.receipt.backfill_candidate_count == 1
    assert result.receipt.eligible_candidate_count == 3
    assert result.receipt.usable_reserve_candidate_count == 2
    assert result.plan.backfill_authorities[0][1] == "source-lane"
    assert all(
        candidate.review_eligibility is ReviewEligibility.PENDING
        for candidate in result.plan.candidates
    )
    assert result.receipt.human_review_performed is False
    assert result.receipt.protected_membership_persisted is False


def test_rejected_and_excluded_candidates_do_not_count_as_reserve() -> None:
    candidates = (
        _candidate("eligible"),
        _candidate("rejected", review=ReviewEligibility.REJECTED),
        _candidate("excluded", excluded=True),
    )
    result = plan_variable_pool(candidates)
    assert result.receipt.candidate_count == 3
    assert result.receipt.eligible_candidate_count == 1
    assert result.receipt.usable_reserve_candidate_count == 0
    assert result.receipt.status is PoolPlanStatus.METADATA_REQUIRED


def test_exact_removal_failure_returns_request_for_governed_lane_and_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dynamislm.benchmark import selection_pool

    original_build = selection_pool._build_problem
    original_qualify = selection_pool.qualify_candidate_removal_reserve
    monkeypatch.setattr(
        selection_pool,
        "_build_problem",
        lambda values, parents: _problem(
            selection_pool._planning_candidates(values), final_count=1
        ),
    )

    def exact(
        problem: FinalSelectionProblem, *, solver_config: SelectionSolverConfig | None = None
    ) -> tuple[Any, Any]:
        from dynamislm.benchmark.selection_pool import SingleCandidateRemovalCheckV1

        baseline = solve_selection_feasibility(
            _problem((_candidate("x"), _candidate("y")), final_count=1),
            solver_config=PSE_V1_POOL_FEASIBILITY_SOLVER_PROFILE_V1,
        )
        if len(problem.candidates) == 2:
            failed = SingleCandidateRemovalCheckV1(
                canonical_hash(problem.candidates[0].candidate_id),
                FeasibilityStatus.INFEASIBLE,
                "EXACT_FEASIBILITY_ORACLE",
            )
            passed = SingleCandidateRemovalCheckV1(
                canonical_hash(problem.candidates[1].candidate_id),
                FeasibilityStatus.FEASIBLE,
                "EXACT_FEASIBILITY_ORACLE",
                canonical_hash("plan"),
                canonical_hash("validation"),
            )
            return baseline, (failed, passed)
        return baseline, tuple(
            SingleCandidateRemovalCheckV1(
                canonical_hash(item.candidate_id),
                FeasibilityStatus.FEASIBLE,
                "EXACT_FEASIBILITY_ORACLE",
                canonical_hash(("plan", item.candidate_id)),
                canonical_hash(("validation", item.candidate_id)),
            )
            for item in problem.candidates
        )

    monkeypatch.setattr(selection_pool, "qualify_candidate_removal_reserve", exact)
    lane = _lane("source-lane")
    inventory = _inventory((lane,))
    result = plan_variable_pool(
        (_candidate("a"), _candidate("b")),
        supply_inventory=inventory,
        materialized_backfill_candidates=(
            MaterializedBackfillCandidateV1(
                _candidate("c", origin=lane.origin_class),
                lane.lane_id,
                lane.authority_ref,
                lane.authority_digest,
            ),
        ),
    )
    assert result.receipt.status is PoolPlanStatus.QUALIFIED
    assert result.receipt.backfill_candidate_count == 1
    monkeypatch.setattr(selection_pool, "_build_problem", original_build)
    monkeypatch.setattr(selection_pool, "qualify_candidate_removal_reserve", original_qualify)


def test_exact_interaction_backfill_requires_feasibility_witness_then_uses_review_cost(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dynamislm.benchmark import selection_pool
    from dynamislm.benchmark.selection_pool import SingleCandidateRemovalCheckV1

    monkeypatch.setattr(
        selection_pool,
        "_build_problem",
        lambda values, _parents: _problem(
            selection_pool._planning_candidates(values), final_count=1
        ),
    )
    trial_ids: set[str] = set()

    def feasibility(problem: FinalSelectionProblem, **_kwargs: Any) -> Any:
        ids = {item.candidate_id for item in problem.candidates}
        trial_ids.update(ids.intersection({"unrelated", "repair-pending", "repair-z", "repair-b"}))
        return SimpleNamespace(
            status=(
                FeasibilityStatus.FEASIBLE
                if ids.intersection({"repair-pending", "repair-z", "repair-b"})
                else FeasibilityStatus.INFEASIBLE
            )
        )

    def qualify(problem: FinalSelectionProblem, **_kwargs: Any) -> tuple[Any, Any]:
        baseline = SimpleNamespace(status=FeasibilityStatus.FEASIBLE)
        repairing = any(item.candidate_id.startswith("repair-") for item in problem.candidates)
        removals = tuple(
            SingleCandidateRemovalCheckV1(
                canonical_hash(item.candidate_id),
                (
                    FeasibilityStatus.FEASIBLE
                    if repairing or item.candidate_id != "a"
                    else FeasibilityStatus.INFEASIBLE
                ),
                "EXACT_FEASIBILITY_ORACLE",
                canonical_hash(("plan", item.candidate_id))
                if repairing or item.candidate_id != "a"
                else None,
                canonical_hash(("validation", item.candidate_id))
                if repairing or item.candidate_id != "a"
                else None,
            )
            for item in problem.candidates
        )
        return baseline, removals

    monkeypatch.setattr(selection_pool, "solve_selection_feasibility", feasibility)
    monkeypatch.setattr(selection_pool, "qualify_candidate_removal_reserve", qualify)
    lanes = (
        _lane("a-arbitrary"),
        _lane("b-pending"),
        _lane("b-approved"),
        _lane("z-approved"),
    )
    bindings = tuple(
        MaterializedBackfillCandidateV1(
            _candidate(
                candidate_id,
                origin=CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION,
                review=review,
            ),
            lane.lane_id,
            lane.authority_ref,
            lane.authority_digest,
        )
        for candidate_id, review, lane in (
            ("unrelated", ReviewEligibility.PENDING, lanes[0]),
            ("repair-pending", ReviewEligibility.PENDING, lanes[1]),
            ("repair-b", ReviewEligibility.APPROVED, lanes[2]),
            ("repair-z", ReviewEligibility.APPROVED, lanes[3]),
        )
    )
    result = plan_variable_pool(
        (_candidate("a"), _candidate("b"), _candidate("c")),
        supply_inventory=_inventory(lanes),
        materialized_backfill_candidates=bindings,
    )
    assert trial_ids == {"unrelated", "repair-pending", "repair-b", "repair-z"}
    assert result.receipt.status is PoolPlanStatus.QUALIFIED
    assert result.receipt.backfill_candidate_count == 1
    assert result.plan.backfill_authorities[0][0] == "repair-b"
    assert result.plan.backfill_authorities[0][1] == "b-approved"


def test_exact_removal_failure_without_materialized_metadata_is_unresolved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dynamislm.benchmark import selection_pool
    from dynamislm.benchmark.selection_pool import SingleCandidateRemovalCheckV1

    monkeypatch.setattr(
        selection_pool,
        "_build_problem",
        lambda values, parents: _problem(
            selection_pool._planning_candidates(values), final_count=1
        ),
    )

    def exact(
        problem: FinalSelectionProblem, *, solver_config: SelectionSolverConfig | None = None
    ) -> tuple[Any, Any]:
        baseline = solve_selection_feasibility(
            _problem((_candidate("x"), _candidate("y")), final_count=1),
            solver_config=PSE_V1_POOL_FEASIBILITY_SOLVER_PROFILE_V1,
        )
        removals = tuple(
            SingleCandidateRemovalCheckV1(
                canonical_hash(item.candidate_id),
                FeasibilityStatus.INFEASIBLE,
                "EXACT_FEASIBILITY_ORACLE",
            )
            for item in problem.candidates[:1]
        ) + tuple(
            SingleCandidateRemovalCheckV1(
                canonical_hash(item.candidate_id),
                FeasibilityStatus.FEASIBLE,
                "EXACT_FEASIBILITY_ORACLE",
                canonical_hash(("plan", item.candidate_id)),
                canonical_hash(("validation", item.candidate_id)),
            )
            for item in problem.candidates[1:]
        )
        return baseline, removals

    monkeypatch.setattr(selection_pool, "qualify_candidate_removal_reserve", exact)
    lane = _lane("source-lane")
    result = plan_variable_pool(
        (_candidate("a"), _candidate("b"), _candidate("c")),
        supply_inventory=_inventory((lane,)),
    )
    assert result.receipt.status is PoolPlanStatus.METADATA_REQUIRED
    assert result.receipt.candidate_count == result.receipt.initial_candidate_count == 3
    assert result.receipt.backfill_candidate_count == 0
    assert (
        result.receipt.reserve_deficits[0].deficit_kind
        is ReserveDeficitKind.EXACT_REMOVAL_INFEASIBLE
    )
    request = result.receipt.backfill_requests[0]
    assert request.request_kind is BackfillRequestKind.EXACT_SELECTION_INTERACTION
    assert request.lane_ids == (lane.lane_id,)
    assert request.requires_candidate_metadata is True


def test_complete_empty_lane_inventory_can_prove_expansion() -> None:
    inventory = _inventory(
        capacity_scope_complete=True,
        planned_counts=((CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION, 40),),
    )
    assessment = assess_authority_supply_inventory(inventory)
    assert assessment.status is SupplyAssessmentStatus.AUTHORITY_EXPANSION_REQUIRED


def test_inventory_digest_is_canonical_and_rejects_tampering() -> None:
    inventory = _inventory((_lane("source"),))
    assert inventory.inventory_digest.startswith("sha256:")
    with pytest.raises(ValueError, match="does not match its contents"):
        replace(inventory, inventory_digest=canonical_hash("tampered"))
