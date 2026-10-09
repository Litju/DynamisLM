from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from dynamislm.benchmark.authoring import production_seed_namespace
from dynamislm.benchmark.authority_supply import (
    AUTHORITY_SUPPLY_SCHEMA,
    AUTHORITY_SUPPLY_SCHEMA_V1_2,
    AdditionalCapacityStatus,
    AuthoritySupplyInventoryV1,
    BackfillRequestKind,
    LaneCapacityStatus,
    ReserveCandidateLaneV1,
    ReserveDeficitKind,
    _source_cells_by_document,
)
from dynamislm.benchmark.constants import CRITICAL_ERROR_CLASSES, CaseOrigin, SplitName
from dynamislm.benchmark.production_exclusions import QualificationExclusionCommitmentV1
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
    MutationParentProvenance,
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
    PoolBackfillNeedV1,
    PoolPlanStatus,
    PoolReserveReceiptV1,
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
    mutation_parent_payload_hash: str | None = None,
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
        mutation_parent_payload_hash=mutation_parent_payload_hash,
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
        if item.mutation_lineage_id is not None:
            constraints.extend(
                (
                    SelectionConstraint(
                        constraint_id=f"RES258:MUTATION_PARENT:{item.candidate_id}",
                        authority_ref="test mutation parent provenance",
                        kind=ConstraintKind.MUTATION_PARENT_PROVENANCE,
                        candidate_ids=(item.candidate_id,),
                        related_id=item.mutation_parent_candidate_id,
                        related_payload_hash=item.mutation_parent_payload_hash,
                    ),
                    SelectionConstraint(
                        constraint_id=f"RES258:MUTATION_CELL:{item.candidate_id}",
                        authority_ref="test mutation parent cell",
                        kind=ConstraintKind.MUTATION_PARENT_CELL_INHERITANCE,
                        candidate_ids=(item.candidate_id,),
                        related_id=item.mutation_parent_candidate_id,
                        reason=item.mutation_cell_exception_authority_ref,
                    ),
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
    capacity_unit: str = "test candidate slot",
    authority_ref: str = "test governed authority lane",
    supported_cells: tuple[tuple[str, str], ...] = (("C01", "F01"),),
    identity_digests: tuple[str, ...] | None = None,
) -> ReserveCandidateLaneV1:
    return ReserveCandidateLaneV1(
        lane_id=lane_id,
        origin_class=origin,
        authority_ref=authority_ref,
        authority_digest=canonical_hash(("authority", lane_id)),
        capacity_unit=capacity_unit,
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
        # Planned slot geometry is only representable in historical v1.2 inventories.
        schema_version=(
            AUTHORITY_SUPPLY_SCHEMA_V1_2
            if planned_counts or mutation_lineages
            else AUTHORITY_SUPPLY_SCHEMA
        ),
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


@pytest.mark.parametrize("base_status", [FeasibilityStatus.INFEASIBLE, FeasibilityStatus.UNKNOWN])
def test_unresolved_or_infeasible_base_performs_no_removal_solves(
    monkeypatch: pytest.MonkeyPatch,
    base_status: FeasibilityStatus,
) -> None:
    from dynamislm.benchmark import selection_pool

    calls = 0

    def solve(*_args: Any, **_kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        return SimpleNamespace(status=base_status)

    monkeypatch.setattr(selection_pool, "solve_selection_feasibility", solve)
    baseline, removals = qualify_candidate_removal_reserve(
        _problem((_candidate("a"), _candidate("b")), final_count=1)
    )
    assert baseline.status is base_status
    assert removals == ()
    assert calls == 1


@pytest.mark.parametrize(
    ("base_status", "pool_status"),
    [
        (FeasibilityStatus.INFEASIBLE, PoolPlanStatus.BASE_INFEASIBLE),
        (FeasibilityStatus.UNKNOWN, PoolPlanStatus.UNKNOWN),
    ],
)
def test_nonfeasible_base_cannot_enter_removal_or_backfill_trials(
    monkeypatch: pytest.MonkeyPatch,
    base_status: FeasibilityStatus,
    pool_status: PoolPlanStatus,
) -> None:
    from dynamislm.benchmark import selection_pool

    monkeypatch.setattr(
        selection_pool,
        "_build_problem",
        lambda values, _parents: _problem(
            selection_pool._planning_candidates(values), final_count=1
        ),
    )
    calls = 0

    def solve(*_args: Any, **_kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        return SimpleNamespace(status=base_status)

    monkeypatch.setattr(selection_pool, "solve_selection_feasibility", solve)
    lane = _lane("source-lane")
    inventory = _inventory((lane,))
    repair = _candidate(
        "repair",
        origin=CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION,
        review=ReviewEligibility.APPROVED,
    )
    result = plan_variable_pool(
        (_candidate("a"), _candidate("b")),
        supply_inventory=inventory,
        materialized_backfill_candidates=(
            MaterializedBackfillCandidateV1(
                repair,
                lane.lane_id,
                "deliberately invalid authority binding",
                lane.authority_digest,
            ),
        ),
    )
    assert calls == 1
    assert result.receipt.status is pool_status
    assert result.receipt.baseline_feasibility_status is base_status
    assert result.receipt.base_diagnosis.problem_digest
    assert result.receipt.base_diagnosis.constraint_inventory_digest
    assert result.receipt.base_diagnosis.constraint_ids == ()
    assert result.receipt.checked_removal_count == 0
    assert result.receipt.backfill_candidate_count == 0
    assert result.receipt.backfill_requests == ()
    assert result.plan.candidates == (_candidate("a"), _candidate("b"))


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


def test_v13_inventory_does_not_derive_a_pool_floor_or_backfill_request() -> None:
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
    )
    assessment = assess_authority_supply_inventory(inventory)
    assert assessment.final_selection_bound == 434
    assert assessment.structural_pool_floor is None
    assert assessment.structural_backfill_requests == ()
    assert assessment.pool_n is None


def test_historical_v12_inventory_cannot_drive_current_supply_assessment() -> None:
    inventory = _inventory(
        planned_counts=(
            (CaseOrigin.EXPERT_AUTHORED_SEMANTIC, 240),
            (CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION, 40),
            (CaseOrigin.DETERMINISTIC_ENGINE_DERIVED, 31),
            (CaseOrigin.DETERMINISTIC_SYNTHETIC, 12),
            (CaseOrigin.ADVERSARIAL_MUTATION, 111),
        ),
        mutation_lineages=37,
    )
    with pytest.raises(ValueError, match="historical v1.2 inventory is preserved"):
        assess_authority_supply_inventory(inventory)


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
    assert result.receipt.status is PoolPlanStatus.BASE_INFEASIBLE


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


def test_mutation_repair_trial_keeps_removed_parent_provenance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dynamislm.benchmark import selection_pool
    from dynamislm.benchmark.selection_pool import SingleCandidateRemovalCheckV1

    parent = _candidate("parent-candidate")
    lineage = "mutation-lineage:parent-a"
    parent_hash = parent.payload_hash
    mutation = _candidate(
        "repair-mutation",
        origin=CaseOrigin.ADVERSARIAL_MUTATION,
        identities=(
            IsolationIdentity(IsolationIdentityKind.SOURCE_FAMILY, "family:mutation"),
            IsolationIdentity(IsolationIdentityKind.MUTATION_PARENT, parent.candidate_id),
            IsolationIdentity(IsolationIdentityKind.MUTATION_LINEAGE, lineage),
        ),
        mutation_lineage_id=lineage,
        mutation_parent_candidate_id=parent.candidate_id,
        mutation_parent_payload_hash=parent_hash,
    )
    lane = _lane(
        "mutation-parent-a",
        origin=CaseOrigin.ADVERSARIAL_MUTATION,
        capacity=None,
        status=LaneCapacityStatus.RULE_GOVERNED,
        identity_digests=tuple(
            sorted(
                (
                    _identity_digest("MUTATION_PARENT", parent.candidate_id),
                    _identity_digest("MUTATION_LINEAGE", lineage),
                )
            )
        ),
    )

    def build_small_problem(
        candidates: tuple[FinalSelectionCandidate, ...],
        parents: tuple[MutationParentProvenance, ...],
    ) -> FinalSelectionProblem:
        return replace(
            _problem(selection_pool._planning_candidates(candidates), final_count=1),
            parent_provenance_registry=parents,
        )

    monkeypatch.setattr(selection_pool, "_build_problem", build_small_problem)
    trial_parent_registry: list[tuple[str, ...]] = []

    def trial_solver(problem: FinalSelectionProblem, **_kwargs: Any) -> Any:
        candidate_ids = {item.candidate_id for item in problem.candidates}
        if "repair-mutation" in candidate_ids:
            trial_parent_registry.append(
                tuple(item.candidate_id for item in problem.parent_provenance_registry)
            )
        return SimpleNamespace(
            status=(
                FeasibilityStatus.FEASIBLE
                if "repair-mutation" in candidate_ids
                and any(
                    item.candidate_id == parent.candidate_id
                    for item in problem.parent_provenance_registry
                )
                else FeasibilityStatus.INFEASIBLE
            )
        )

    def qualify(problem: FinalSelectionProblem, **_kwargs: Any) -> tuple[Any, Any]:
        repairing = any(item.candidate_id == "repair-mutation" for item in problem.candidates)
        baseline = SimpleNamespace(status=FeasibilityStatus.FEASIBLE)
        removals = tuple(
            SingleCandidateRemovalCheckV1(
                canonical_hash(candidate.candidate_id),
                (
                    FeasibilityStatus.FEASIBLE
                    if repairing or candidate.candidate_id != parent.candidate_id
                    else FeasibilityStatus.INFEASIBLE
                ),
                "EXACT_FEASIBILITY_ORACLE",
                canonical_hash(("plan", candidate.candidate_id))
                if repairing or candidate.candidate_id != parent.candidate_id
                else None,
                canonical_hash(("validation", candidate.candidate_id))
                if repairing or candidate.candidate_id != parent.candidate_id
                else None,
            )
            for candidate in problem.candidates
        )
        return baseline, removals

    monkeypatch.setattr(selection_pool, "solve_selection_feasibility", trial_solver)
    monkeypatch.setattr(selection_pool, "qualify_candidate_removal_reserve", qualify)
    result = plan_variable_pool(
        (parent, _candidate("a"), _candidate("b")),
        supply_inventory=_inventory((lane,)),
        materialized_backfill_candidates=(
            MaterializedBackfillCandidateV1(
                mutation,
                lane.lane_id,
                lane.authority_ref,
                lane.authority_digest,
            ),
        ),
    )

    assert result.receipt.status is PoolPlanStatus.QUALIFIED
    assert result.plan.backfill_authorities[0][0] == "repair-mutation"
    assert trial_parent_registry
    assert all(parent.candidate_id in registry for registry in trial_parent_registry)


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


def test_v12_empty_lane_inventory_cannot_prove_current_expansion() -> None:
    inventory = _inventory(
        capacity_scope_complete=True,
        planned_counts=((CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION, 40),),
    )
    with pytest.raises(ValueError, match="historical v1.2 inventory is preserved"):
        assess_authority_supply_inventory(inventory)


def test_v13_supply_rejects_planned_slot_and_lineage_geometry() -> None:
    inventory = _inventory((_lane("source"),))
    assert inventory.schema_version == AUTHORITY_SUPPLY_SCHEMA
    assert not inventory.encodes_planned_geometry
    with pytest.raises(ValueError, match="planned slot or lineage geometry"):
        replace(
            inventory,
            planned_origin_counts=((CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION, 40),),
            inventory_digest="",
        )
    with pytest.raises(ValueError, match="planned slot or lineage geometry"):
        replace(inventory, planned_mutation_lineage_count=37, inventory_digest="")
    with pytest.raises(ValueError, match="planned slot or lineage geometry"):
        replace(
            inventory,
            reserve_candidate_lanes=(
                replace(_lane("source"), existing_planned_capacity=1, lane_digest=""),
            ),
            inventory_digest="",
        )


def test_v13_recipe_inventory_is_not_a_pool_target_or_capacity_ceiling() -> None:
    lanes = (
        *(_lane(f"source-{index:02d}") for index in range(41)),
        _lane(
            "source-existing-recipe",
            origin=CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION,
            status=LaneCapacityStatus.EXISTING_RECIPE_INVENTORY,
            capacity_unit="additional authorable source slot",
            authority_ref="additional authorable source lane",
        ),
        _lane(
            "engine-c16",
            origin=CaseOrigin.DETERMINISTIC_ENGINE_DERIVED,
            capacity=31,
            status=LaneCapacityStatus.EXISTING_RECIPE_INVENTORY,
            capacity_unit="additional authorable engine slot",
            authority_ref="additional authorable engine lane",
            supported_cells=(("C16", "F05"),),
        ),
        _lane(
            "expert-batch",
            origin=CaseOrigin.EXPERT_AUTHORED_SEMANTIC,
            capacity=240,
            status=LaneCapacityStatus.EXISTING_RECIPE_INVENTORY,
            capacity_unit="additional authorable expert slot",
            authority_ref="additional authorable expert lane",
        ),
        _lane(
            "synthetic-rule",
            origin=CaseOrigin.DETERMINISTIC_SYNTHETIC,
            capacity=None,
            status=LaneCapacityStatus.RULE_GOVERNED,
            supported_cells=(("C08", "F05"),),
        ),
        *(
            _lane(
                f"mutation-{index:02d}",
                origin=CaseOrigin.ADVERSARIAL_MUTATION,
                capacity=91 if index == 0 else 1,
                status=LaneCapacityStatus.EXISTING_RECIPE_INVENTORY,
                capacity_unit="additional authorable mutation slot",
                authority_ref="additional authorable mutation lane",
            )
            for index in range(21)
        ),
    )
    assessment = assess_authority_supply_inventory(_inventory(lanes))

    counts = dict(assessment.existing_authorized_recipe_count)
    additional = dict(assessment.additional_authorable_capacity)
    statuses = dict(assessment.capacity_status)
    engine = next(item for item in lanes if item.lane_id == "engine-c16")
    expert = next(item for item in lanes if item.lane_id == "expert-batch")
    mutation = next(item for item in lanes if item.lane_id == "mutation-00")
    source_recipe = next(item for item in lanes if item.lane_id == "source-existing-recipe")
    source_additional_lanes = tuple(
        item
        for item in lanes
        if item.origin_class is CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION
        and item.capacity_status is LaneCapacityStatus.AVAILABLE
    )
    assert counts[CaseOrigin.DETERMINISTIC_ENGINE_DERIVED] == 31
    assert counts[CaseOrigin.EXPERT_AUTHORED_SEMANTIC] == 240
    assert counts[CaseOrigin.ADVERSARIAL_MUTATION] == 111
    assert counts[CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION] == 1
    assert len(source_additional_lanes) == 41
    assert all(item.additional_authorable_capacity == 1 for item in source_additional_lanes)
    assert additional[CaseOrigin.DETERMINISTIC_ENGINE_DERIVED] is None
    assert additional[CaseOrigin.EXPERT_AUTHORED_SEMANTIC] is None
    assert additional[CaseOrigin.ADVERSARIAL_MUTATION] is None
    assert statuses[CaseOrigin.DETERMINISTIC_ENGINE_DERIVED] is (
        AdditionalCapacityStatus.GOVERNED_UNRESOLVED
    )
    assert engine.additional_authorable_capacity is None
    assert expert.additional_authorable_capacity is None
    assert mutation.additional_authorable_capacity is None
    assert source_recipe.existing_authorized_recipe_count == 1
    assert source_recipe.additional_authorable_capacity is None
    assert not engine.may_author_backfill
    assert not expert.may_author_backfill
    assert not mutation.may_author_backfill
    assert assessment.final_selection_bound == 434
    assert assessment.structural_pool_floor is None
    assert assessment.structural_backfill_requests == ()
    assert assessment.pool_n is None
    assert assessment.active_supply_schema == AUTHORITY_SUPPLY_SCHEMA


def test_nonfeasible_receipt_rejects_unresolved_backfill_needs_but_allows_deficits() -> None:
    receipt = plan_variable_pool(
        (
            _candidate("eligible"),
            _candidate("rejected", review=ReviewEligibility.REJECTED),
        )
    ).receipt
    assert receipt.baseline_feasibility_status is FeasibilityStatus.INFEASIBLE
    assert receipt.reserve_deficits
    need = PoolBackfillNeedV1(
        constraint_id="RES383:ADVERSARIAL_NEED",
        constraint_kind=ConstraintKind.ORIGIN_BOUNDS,
        present_candidate_count=0,
        required_candidate_count=1,
        missing_candidate_count=1,
        origin_class=CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION,
    )
    with pytest.raises(ValueError, match="non-feasible base cannot enter removal qualification"):
        replace(receipt, unresolved_backfill_needs=(need,))


def test_historical_v12_inventory_digest_is_unchanged_by_v13() -> None:
    lane = ReserveCandidateLaneV1(
        lane_id="source:x",
        origin_class=CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION,
        authority_ref="ref",
        authority_digest=canonical_hash("a"),
        capacity_unit="u",
        existing_planned_capacity=0,
        available_capacity=1,
        capacity_status=LaneCapacityStatus.AVAILABLE,
        supported_cells=(("C01", "F01"),),
    )
    inventory = AuthoritySupplyInventoryV1(
        schema_version=AUTHORITY_SUPPLY_SCHEMA_V1_2,
        atoms=(),
        reserve_candidate_lanes=(lane,),
        planned_origin_counts=((CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION, 40),),
        planned_mutation_lineage_count=37,
        materialized_candidate_count=0,
        evidence_bindings=(("X", canonical_hash("b")),),
        authority_inventory_complete=True,
        capacity_scope_complete=False,
    )
    # Pinned against the RES-383 anchor implementation (c689d5d) for the same inventory.
    assert inventory.encodes_planned_geometry
    assert inventory.inventory_digest == (
        "sha256:6c811ff6cf4806d00c3ac8c80a788b8cc6fc86a37480087e964a6a94eec9b2a3"
    )
    with pytest.raises(ValueError, match="v1.2 authority supply cannot use v1.3 recipe semantics"):
        replace(
            inventory,
            reserve_candidate_lanes=(
                replace(
                    lane,
                    capacity_status=LaneCapacityStatus.EXISTING_RECIPE_INVENTORY,
                    lane_digest="",
                ),
            ),
            inventory_digest="",
        )


def test_inventory_digest_is_canonical_and_rejects_tampering() -> None:
    inventory = _inventory((_lane("source"),))
    assert inventory.inventory_digest.startswith("sha256:")
    with pytest.raises(ValueError, match="does not match its contents"):
        replace(inventory, inventory_digest=canonical_hash("tampered"))


def _source_test_sha(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _source_row(pmcid: str, family_id: str) -> dict[str, object]:
    return {
        "pmcid": pmcid,
        "applicability_scope": "INDIRECT_MEASUREMENT_EVIDENCE",
        "source_family_identity": {
            "source_family_id": family_id,
            "family_digest": _source_test_sha(family_id),
        },
    }


def _source_support(capabilities: tuple[str, ...], families: tuple[str, ...]) -> dict[str, object]:
    return {
        "candidate_capabilities_retained": list(capabilities),
        "candidate_benchmark_families_retained": list(families),
    }


def _source_authority_fixture(monkeypatch: pytest.MonkeyPatch) -> dict[str, dict[str, object]]:
    from dynamislm.qualification import res115_authoring
    from dynamislm.qualification.res115_authoring import SourceSpanProposalV1

    accepted = (
        _source_row("PMC9000001", "family-cross"),
        _source_row("PMC9000002", "family-excluded"),
    )
    support = {
        "PMC9000001": _source_support(("C13", "C14"), ("F01", "F03")),
        "PMC9000002": _source_support(("C13",), ("F02",)),
    }

    def proposal(
        row: dict[str, object], support_row: dict[str, object], **kwargs: object
    ) -> tuple[SourceSpanProposalV1, ...]:
        capability = str(kwargs["capability_id"])
        family = str(kwargs["benchmark_family"])
        capabilities = support_row["candidate_capabilities_retained"]
        families = support_row["candidate_benchmark_families_retained"]
        if not isinstance(capabilities, list) or not isinstance(families, list):
            raise ValueError("test source tags are malformed")
        if capability not in capabilities or family not in families:
            return ()
        return (
            SourceSpanProposalV1(
                span_digest=_source_test_sha(f"{row['pmcid']}:{capability}:{family}"),
                locator="test-locator",
                text="test span",
                scope="test scope",
                support_rules=("test rule",),
                support_tags=(capability, family),
            ),
        )

    monkeypatch.setattr(
        res115_authoring,
        "_phase_a_source_inputs",
        lambda **_kwargs: (
            accepted,
            support,
            (),
            {"PMC9000001": (), "PMC9000002": ()},
        ),
    )
    monkeypatch.setattr(res115_authoring, "_source_tag_span_proposals", proposal)
    return {
        "document-cross": {
            **accepted[0],
            "retained_source_artifact": {"document_identity_id": "document-cross"},
        },
        "document-excluded": {
            **accepted[1],
            "retained_source_artifact": {"document_identity_id": "document-excluded"},
        },
    }


def _source_exclusion(span_digest: str) -> QualificationExclusionCommitmentV1:
    from dynamislm.benchmark.authoring import QUALIFICATION_CANDIDATE_ID_PREFIX
    from dynamislm.benchmark.contamination import exact_13_token_shingles, normalized_text_sha256
    from dynamislm.benchmark.production_exclusions import (
        QUALIFICATION_001B_BATCH_ID,
        QUALIFICATION_EXCLUSION_VERSION,
        QualificationExclusionCandidateV1,
        QualificationExclusionCommitmentV1,
        bind_qualification_exclusion_commitment,
    )

    question = "qualification span exclusion"
    entry = QualificationExclusionCandidateV1(
        candidate_id=QUALIFICATION_CANDIDATE_ID_PREFIX + "SOURCE-TEST",
        candidate_payload_hash=_source_test_sha("payload"),
        question_text=question,
        exact_question_sha256=_source_test_sha(question),
        normalized_question_sha256=normalized_text_sha256(question),
        question_13_token_shingle_hashes=tuple(sorted(exact_13_token_shingles(question))),
        seed_blocks=(),
        seed_namespaces=(),
        generator_seed_identities=(),
        mutation_lineage_ids=(),
        mutation_seed_values=(),
        evidence_span_identities=(("PSE-EVIDENCE:QUALIFICATION:source-test", span_digest),),
    )
    return bind_qualification_exclusion_commitment(
        QualificationExclusionCommitmentV1(
            batch_id=QUALIFICATION_001B_BATCH_ID,
            version=QUALIFICATION_EXCLUSION_VERSION,
            qualification_manifest_digest=_source_test_sha("manifest"),
            qualification_store_receipt_digest=_source_test_sha("store receipt"),
            authoring_plan_digest=_source_test_sha("authoring plan"),
            seed_input_digest=_source_test_sha("seed inputs"),
            candidate_count=1,
            entries=(entry,),
            commitment_digest=_source_test_sha("unbound"),
        )
    )


def test_source_reserve_ignores_proposal_tag_cross_products(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dynamislm.benchmark.production_authoring import eligible_production_source_selections

    accepted = _source_authority_fixture(monkeypatch)
    selections = eligible_production_source_selections(
        _source_exclusion(_source_test_sha("unrelated span")),
        external_root=Path("/test-external"),
    )
    cells = _source_cells_by_document(accepted, selections)

    assert cells == {
        "document-cross": (("C13", "F01"),),
        "document-excluded": (("C13", "F02"),),
    }


def test_qualification_excluded_source_span_cannot_create_a_reserve_lane(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dynamislm.benchmark.production_authoring import eligible_production_source_selections

    accepted = _source_authority_fixture(monkeypatch)
    exclusion = _source_exclusion(_source_test_sha("PMC9000002:C13:F02"))
    selections = eligible_production_source_selections(
        exclusion,
        external_root=Path("/test-external"),
    )
    cells = _source_cells_by_document(accepted, selections)

    assert "document-excluded" not in cells
    assert all(item.pmcid != "PMC9000002" for item in selections)


def test_source_inventory_cells_equal_production_eligible_selections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dynamislm.benchmark.production_authoring import eligible_production_source_selections

    accepted = _source_authority_fixture(monkeypatch)
    selections = eligible_production_source_selections(
        _source_exclusion(_source_test_sha("unrelated span")),
        external_root=Path("/test-external"),
    )
    inventory_cells = _source_cells_by_document(accepted, selections)
    authoring_cells: dict[str, set[tuple[str, str]]] = {}
    document_by_pmcid = {str(row["pmcid"]): document_id for document_id, row in accepted.items()}
    for selection in selections:
        document_id = document_by_pmcid[selection.pmcid]
        authoring_cells.setdefault(document_id, set()).add(
            (selection.capability_id, selection.benchmark_family)
        )

    assert inventory_cells == {
        document_id: tuple(sorted(cells)) for document_id, cells in authoring_cells.items()
    }


def _receipt_for(
    monkeypatch: pytest.MonkeyPatch,
    base_status: FeasibilityStatus,
    removal_status: FeasibilityStatus = FeasibilityStatus.FEASIBLE,
) -> PoolReserveReceiptV1:
    from dynamislm.benchmark import selection_pool

    monkeypatch.setattr(
        selection_pool,
        "_build_problem",
        lambda values, _parents: _problem(
            selection_pool._planning_candidates(values), final_count=1
        ),
    )
    statuses = iter((base_status, removal_status, removal_status))

    def solve(*_args: Any, **_kwargs: Any) -> Any:
        status = next(statuses)
        witness = status is FeasibilityStatus.FEASIBLE
        return SimpleNamespace(
            status=status,
            plan_digest=canonical_hash("plan") if witness else None,
            validation_digest=canonical_hash("validation") if witness else None,
        )

    monkeypatch.setattr(selection_pool, "solve_selection_feasibility", solve)
    return plan_variable_pool((_candidate("a"), _candidate("b"))).receipt


@pytest.mark.parametrize(
    "status",
    [item for item in PoolPlanStatus if item is not PoolPlanStatus.BASE_INFEASIBLE],
)
def test_infeasible_base_receipt_requires_base_infeasible_status(
    monkeypatch: pytest.MonkeyPatch, status: PoolPlanStatus
) -> None:
    receipt = _receipt_for(monkeypatch, FeasibilityStatus.INFEASIBLE)
    assert receipt.status is PoolPlanStatus.BASE_INFEASIBLE
    with pytest.raises(ValueError, match="BASE_INFEASIBLE status must equal|qualified pool"):
        replace(receipt, status=status, authority_exhaustion_proven=True)


@pytest.mark.parametrize(
    "status",
    [item for item in PoolPlanStatus if item is not PoolPlanStatus.UNKNOWN],
)
def test_unknown_base_receipt_requires_unknown_status(
    monkeypatch: pytest.MonkeyPatch, status: PoolPlanStatus
) -> None:
    receipt = _receipt_for(monkeypatch, FeasibilityStatus.UNKNOWN)
    assert receipt.status is PoolPlanStatus.UNKNOWN
    with pytest.raises(
        ValueError, match="BASE_INFEASIBLE status must equal|unknown base feasibility|qualified"
    ):
        replace(receipt, status=status, authority_exhaustion_proven=True)


def test_feasible_base_rejects_base_infeasible_and_keeps_unknown_removal_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    qualified = _receipt_for(monkeypatch, FeasibilityStatus.FEASIBLE)
    assert qualified.status is PoolPlanStatus.QUALIFIED
    with pytest.raises(ValueError, match="BASE_INFEASIBLE status must equal"):
        replace(qualified, status=PoolPlanStatus.BASE_INFEASIBLE)

    unknown = _receipt_for(monkeypatch, FeasibilityStatus.FEASIBLE, FeasibilityStatus.UNKNOWN)
    assert unknown.baseline_feasibility_status is FeasibilityStatus.FEASIBLE
    assert unknown.unknown_removal_count == 2
    assert unknown.status is PoolPlanStatus.UNKNOWN
    assert unknown.backfill_requests == ()
    with pytest.raises(ValueError, match="BASE_INFEASIBLE status must equal"):
        replace(unknown, status=PoolPlanStatus.BASE_INFEASIBLE)


def test_historical_v12_inventory_cannot_authorize_pool_planning_or_backfill() -> None:
    lane = _lane("source-lane")
    inventory = _inventory((lane,), planned_counts=((CaseOrigin.EXPERT_AUTHORED_SEMANTIC, 240),))
    assert inventory.encodes_planned_geometry
    repair = _candidate(
        "repair",
        origin=CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION,
        review=ReviewEligibility.APPROVED,
    )
    with pytest.raises(ValueError, match="decode-only evidence"):
        plan_variable_pool(
            (_candidate("a"), _candidate("b")),
            supply_inventory=inventory,
            materialized_backfill_candidates=(
                MaterializedBackfillCandidateV1(
                    repair, lane.lane_id, lane.authority_ref, lane.authority_digest
                ),
            ),
        )
