"""RES-369 joint selection qualification using typed abstract candidates only."""

from __future__ import annotations

from dataclasses import replace
from itertools import product
from typing import Any

import pytest

from dynamislm.benchmark.authoring import AUTHORING_RECIPE_REGISTRY, question_classes_for_cell
from dynamislm.benchmark.constants import (
    CRITICAL_ERROR_CLASSES,
    SPLIT_ORDER,
    CaseOrigin,
    DifficultyLevel,
    ExpectedAnswerKind,
    RefusalDecision,
    SplitName,
)
from dynamislm.benchmark.contracts import ContaminationBinding
from dynamislm.benchmark.coverage import COVERAGE_MATRIX
from dynamislm.benchmark.pre_review import CandidateReviewStatus, HumanReviewDecision
from dynamislm.benchmark.production import (
    PRODUCTION_AUTHORING_PROCESS_ID,
    ProductionAuthoringPlanItemV1,
    ProductionCandidateCommitmentV1,
)
from dynamislm.benchmark.selection_constraints import (
    FINAL_CASE_COUNT,
    FINAL_SPLIT_COUNTS,
    build_final_selection_problem,
    build_final_selection_problem_from_commitments,
)
from dynamislm.benchmark.selection_contracts import (
    AssignmentState,
    BalanceDimension,
    CandidateAssignment,
    ConstraintKind,
    FeatureKind,
    FinalSelectionCandidate,
    FinalSelectionPlan,
    FinalSelectionProblem,
    IsolationIdentity,
    IsolationIdentityKind,
    MutationParentProvenance,
    RelationKind,
    ReviewEligibility,
    SelectionBalanceCell,
    SelectionConstraint,
    SelectionConstraintSet,
    SelectionFeature,
    SelectionObjective,
    SelectionSolverConfig,
    SolveStatus,
    ValidationStatus,
)
from dynamislm.benchmark.selection_solver import solve_final_selection
from dynamislm.benchmark.selection_validation import validate_final_selection
from dynamislm.serialization import canonical_hash

_SHA = "sha256:" + "a" * 64
_ROWS = {row.capability_id: row for row in COVERAGE_MATRIX}
_CELL_ROWS = {
    (row.capability_id, family): row for row in COVERAGE_MATRIX for family in row.benchmark_families
}


def _candidate(
    candidate_id: str,
    *,
    origin: CaseOrigin = CaseOrigin.EXPERT_AUTHORED_SEMANTIC,
    features: tuple[SelectionFeature, ...] = (),
    review: ReviewEligibility = ReviewEligibility.APPROVED,
    cluster: str | None = None,
    identities: tuple[IsolationIdentity, ...] = (),
    exact_shingles: tuple[str, ...] = (),
    lineage: str | None = None,
    parent_id: str | None = None,
    parent_hash: str | None = None,
    cell: tuple[str, str] | None = None,
    cell_exception_authority: str | None = None,
    locked_split: SplitName | None = None,
    excluded: bool = False,
    balance_cells: tuple[SelectionBalanceCell, ...] = (),
) -> FinalSelectionCandidate:
    candidate_cell = cell
    if candidate_cell is None:
        feature_cell = next(
            (feature.key for feature in features if feature.kind is FeatureKind.CELL),
            None,
        )
        candidate_cell = (
            (feature_cell[0], feature_cell[1]) if feature_cell is not None else ("C01", "F01")
        )
    return FinalSelectionCandidate(
        candidate_id=candidate_id,
        payload_hash=canonical_hash(("RES369-ABSTRACT", candidate_id)),
        origin_class=origin,
        review_eligibility=review,
        features=tuple(sorted(set(features), key=lambda item: (item.kind.value, item.key))),
        balance_cells=tuple(
            sorted(set(balance_cells), key=lambda item: (item.dimension.value, item.key))
        ),
        isolation_cluster_id=cluster or f"cluster:{candidate_id}",
        allocation_stratum="synthetic-abstract",
        isolation_identities=tuple(
            sorted(
                set(identities)
                or {
                    IsolationIdentity(
                        IsolationIdentityKind.SOURCE_FAMILY,
                        f"family:{candidate_id}",
                    )
                },
                key=lambda item: (item.kind.value, item.identity.encode()),
            )
        ),
        exact_shingle_digests=tuple(
            sorted(set(exact_shingles) or {canonical_hash(("ABSTRACT-SHINGLE", candidate_id))})
        ),
        mutation_lineage_id=lineage,
        mutation_parent_candidate_id=parent_id,
        mutation_parent_payload_hash=parent_hash,
        cell=candidate_cell,
        mutation_cell_exception_authority_ref=cell_exception_authority,
        locked_split=locked_split,
        qualification_excluded=excluded,
    )


def _toy_problem(
    candidates: tuple[FinalSelectionCandidate, ...],
    split_counts: tuple[tuple[SplitName, int], ...],
    *,
    extra: tuple[SelectionConstraint, ...] = (),
    parent_registry: tuple[MutationParentProvenance, ...] = (),
    objectives: tuple[SelectionObjective, ...] = (),
) -> FinalSelectionProblem:
    constraints = [
        SelectionConstraint(
            f"TEST:ONE_STATE:{candidate.candidate_id}",
            "RES-369 test fixture",
            ConstraintKind.ONE_STATE_PER_CANDIDATE,
            candidate_ids=(candidate.candidate_id,),
        )
        for candidate in candidates
    ]
    target = sum(count for _split, count in split_counts)
    constraints.extend(
        (
            SelectionConstraint(
                "TEST:FINAL_COUNT",
                "RES-369 test fixture",
                ConstraintKind.FINAL_COUNT,
                minimum=target,
                maximum=target,
            ),
            *(
                SelectionConstraint(
                    f"TEST:SPLIT:{split.value}",
                    "RES-369 test fixture",
                    ConstraintKind.SPLIT_COUNT,
                    split=split,
                    minimum=count,
                    maximum=count,
                )
                for split, count in split_counts
            ),
            *extra,
        )
    )
    review_out_ids = {
        constraint.candidate_ids[0]
        for constraint in constraints
        if constraint.kind is ConstraintKind.REVIEW_OUT_ONLY
    }
    qualification_out_ids = {
        constraint.candidate_ids[0]
        for constraint in constraints
        if constraint.kind is ConstraintKind.QUALIFICATION_OUT_ONLY
    }
    locked_ids = {
        constraint.candidate_ids[0]
        for constraint in constraints
        if constraint.kind is ConstraintKind.SYNTHETIC_SPLIT_LOCK
    }
    for candidate in candidates:
        if (
            candidate.review_eligibility is not ReviewEligibility.APPROVED
            and candidate.candidate_id not in review_out_ids
        ):
            constraints.append(
                _constraint(
                    f"TEST:REVIEW_OUT:{candidate.candidate_id}",
                    ConstraintKind.REVIEW_OUT_ONLY,
                    candidate_ids=(candidate.candidate_id,),
                    reason=candidate.review_eligibility.value,
                )
            )
        if candidate.qualification_excluded and candidate.candidate_id not in qualification_out_ids:
            constraints.append(
                _constraint(
                    f"TEST:QUALIFICATION_OUT:{candidate.candidate_id}",
                    ConstraintKind.QUALIFICATION_OUT_ONLY,
                    candidate_ids=(candidate.candidate_id,),
                    reason="QUALIFICATION_EXCLUDED",
                )
            )
        if candidate.locked_split is not None and candidate.candidate_id not in locked_ids:
            constraints.append(
                _constraint(
                    f"TEST:SYNTHETIC_LOCK:{candidate.candidate_id}",
                    ConstraintKind.SYNTHETIC_SPLIT_LOCK,
                    candidate_ids=(candidate.candidate_id,),
                    locked_split=candidate.locked_split,
                )
            )
    proven_candidates = {
        constraint.candidate_ids[0]
        for constraint in constraints
        if constraint.kind is ConstraintKind.MUTATION_PARENT_PROVENANCE
    }
    cell_bound_candidates = {
        constraint.candidate_ids[0]
        for constraint in constraints
        if constraint.kind is ConstraintKind.MUTATION_PARENT_CELL_INHERITANCE
    }
    for candidate in candidates:
        if candidate.mutation_lineage_id is not None:
            if candidate.candidate_id not in proven_candidates:
                constraints.append(
                    _constraint(
                        f"TEST:PARENT_PROVENANCE:{candidate.candidate_id}",
                        ConstraintKind.MUTATION_PARENT_PROVENANCE,
                        candidate_ids=(candidate.candidate_id,),
                        related_id=candidate.mutation_parent_candidate_id,
                        related_hash=candidate.mutation_parent_payload_hash,
                    )
                )
            if candidate.candidate_id in cell_bound_candidates:
                continue
            constraints.append(
                _constraint(
                    f"TEST:PARENT_CELL:{candidate.candidate_id}",
                    ConstraintKind.MUTATION_PARENT_CELL_INHERITANCE,
                    candidate_ids=(candidate.candidate_id,),
                    related_id=candidate.mutation_parent_candidate_id,
                    reason=candidate.mutation_cell_exception_authority_ref,
                )
            )
    constraints.sort(key=lambda item: item.constraint_id.encode())
    return FinalSelectionProblem(
        candidates=candidates,
        constraint_set=SelectionConstraintSet(tuple(constraints), objectives),
        authority_digest=canonical_hash("RES369-TEST-AUTHORITY"),
        parent_provenance_registry=parent_registry,
    )


def _plan(
    problem: FinalSelectionProblem,
    assignments: dict[str, AssignmentState],
) -> FinalSelectionPlan:
    return FinalSelectionPlan(
        assignments=tuple(
            CandidateAssignment(candidate_id, state) for candidate_id, state in assignments.items()
        ),
        authority_digest=problem.authority_digest,
        problem_digest=problem.problem_digest,
        approved_pool_digest=problem.approved_pool_digest,
    )


def _small_oracle(problem: FinalSelectionProblem) -> bool:
    for states in product(tuple(AssignmentState), repeat=len(problem.candidates)):
        assignment = {
            candidate.candidate_id: state
            for candidate, state in zip(problem.candidates, states, strict=True)
        }
        if (
            validate_final_selection(problem, _plan(problem, assignment)).status
            is ValidationStatus.VALID
        ):
            return True
    return False


def _feature_for_cell(
    capability: str,
    family: str,
    origin: CaseOrigin,
) -> tuple[SelectionFeature, ...]:
    row = _CELL_ROWS[(capability, family)]
    features: set[SelectionFeature] = set()
    if origin in row.case_origins:
        features.add(SelectionFeature(FeatureKind.CELL, (capability, family)))
        features.update(
            SelectionFeature(FeatureKind.ROW_TAG, (capability, tag)) for tag in row.adversarial_tags
        )
        features.update(
            SelectionFeature(FeatureKind.ROW_ERROR, (capability, error.value))
            for error in row.error_classes
        )
        features.update(
            SelectionFeature(FeatureKind.CRITICAL_ERROR, (error.value,))
            for error in row.error_classes
            if error in CRITICAL_ERROR_CLASSES
        )
    if capability == "C18":
        features.add(SelectionFeature(FeatureKind.C18_REFUSAL, (family,)))
    else:
        features.add(SelectionFeature(FeatureKind.ANSWERABLE))
    return tuple(sorted(features, key=lambda item: (item.kind.value, item.key)))


def _balance_cells(
    capability: str,
    family: str,
    origin: CaseOrigin,
    features: tuple[SelectionFeature, ...],
) -> tuple[SelectionBalanceCell, ...]:
    row = _CELL_ROWS[(capability, family)]
    question_class = question_classes_for_cell(capability, family)[0].value
    values = {
        SelectionBalanceCell(BalanceDimension.CAPABILITY, (capability,)),
        SelectionBalanceCell(BalanceDimension.FAMILY, (family,)),
        SelectionBalanceCell(BalanceDimension.QUESTION_CLASS, (question_class,)),
        SelectionBalanceCell(
            BalanceDimension.ANSWER_OUTCOME,
            ("REFUSAL" if capability == "C18" else "ANSWER",),
        ),
        SelectionBalanceCell(BalanceDimension.ORIGIN, (origin.value,)),
        SelectionBalanceCell(BalanceDimension.DIFFICULTY, (DifficultyLevel.EASY.value,)),
        SelectionBalanceCell(
            BalanceDimension.CRITICAL_ERROR_ELIGIBILITY,
            (
                "ELIGIBLE"
                if any(feature.kind is FeatureKind.CRITICAL_ERROR for feature in features)
                else "NOT_ELIGIBLE",
            ),
        ),
    }
    values.update(
        SelectionBalanceCell(BalanceDimension.TAG_CELL, (capability, tag))
        for tag in row.adversarial_tags
    )
    return tuple(sorted(values, key=lambda cell: (cell.dimension.value, cell.key)))


def _production_shape_candidates() -> tuple[
    tuple[FinalSelectionCandidate, ...], tuple[MutationParentProvenance, ...]
]:
    cell_variants: dict[tuple[str, str], list[CaseOrigin]] = {}
    target_cell = ("C01", "F01")
    for cell, _row in _CELL_ROWS.items():
        if cell[0] == "C08":
            cell_variants[cell] = [CaseOrigin.DETERMINISTIC_SYNTHETIC] * 3
        elif cell[0] == "C16":
            cell_variants[cell] = [CaseOrigin.DETERMINISTIC_ENGINE_DERIVED] * 3
        else:
            cell_variants[cell] = [CaseOrigin.EXPERT_AUTHORED_SEMANTIC] * 3
    source_cells = [
        cell
        for cell, row in sorted(_CELL_ROWS.items())
        if cell[0] not in {"C08", "C16"}
        and cell != target_cell
        and CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION in row.case_origins
    ]
    engine_cells = [
        cell
        for cell, row in sorted(_CELL_ROWS.items())
        if cell[0] not in {"C08", "C16"}
        and cell != target_cell
        and CaseOrigin.DETERMINISTIC_ENGINE_DERIVED in row.case_origins
    ]
    assert len(source_cells) >= 40 and len(engine_cells) >= 23
    for cell in source_cells[:40]:
        cell_variants[cell][0] = CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION
    for cell in engine_cells[:23]:
        cell_variants[cell][1] = CaseOrigin.DETERMINISTIC_ENGINE_DERIVED

    candidates: list[FinalSelectionCandidate] = []

    def add(
        candidate_id: str,
        cell: tuple[str, str],
        origin: CaseOrigin,
        *,
        variant: int = 0,
        lock: SplitName | None = None,
        cluster: str | None = None,
        identity: str | None = None,
        lineage: str | None = None,
        parent_id: str | None = None,
        parent_hash: str | None = None,
    ) -> None:
        features = _feature_for_cell(cell[0], cell[1], origin)
        identities = [
            IsolationIdentity(
                IsolationIdentityKind.SOURCE_FAMILY,
                identity or f"family:{candidate_id}",
            )
        ]
        if lineage:
            identities.append(IsolationIdentity(IsolationIdentityKind.MUTATION_LINEAGE, lineage))
        if parent_id:
            identities.append(IsolationIdentity(IsolationIdentityKind.MUTATION_PARENT, parent_id))

        candidates.append(
            _candidate(
                candidate_id,
                origin=origin,
                features=features,
                cluster=cluster,
                identities=tuple(identities),
                lineage=lineage,
                parent_id=parent_id,
                parent_hash=parent_hash,
                locked_split=lock,
                balance_cells=_balance_cells(cell[0], cell[1], origin, features),
                cell=cell,
            )
        )

    for (capability, family), origins in sorted(cell_variants.items()):
        for variant, origin in enumerate(origins):
            if (capability, family) == target_cell:
                candidate_id = ("000-trap-a", "001-trap-d", "zzz-alternative")[variant]
                shared_identity = "shared:select-first-trap" if variant == 0 else None
                cluster = "cluster:select-first-trap" if variant == 0 else None
            else:
                candidate_id = f"cell:{capability}:{family}:{variant}"
                shared_identity = None
                cluster = None
            lock = SPLIT_ORDER[variant] if capability == "C08" else None
            add(
                candidate_id,
                (capability, family),
                origin,
                variant=variant,
                lock=lock,
                cluster=cluster,
                identity=shared_identity,
            )

    source_extra_cell = next(
        cell
        for cell, row in sorted(_CELL_ROWS.items())
        if cell not in {target_cell, ("C02", "F02"), ("C01", "F03")}
        and CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION in row.case_origins
    )
    for index in range(56):
        add(
            f"extra:expert:{index:03d}",
            ("C02", "F02"),
            CaseOrigin.EXPERT_AUTHORED_SEMANTIC,
        )
    for index in range(2):
        add(
            f"extra:source:{index:03d}",
            source_extra_cell,
            CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION,
        )
    for index in range(3):
        add(
            f"extra:synthetic:{index:03d}",
            ("C08", "F05"),
            CaseOrigin.DETERMINISTIC_SYNTHETIC,
            lock=SplitName.PUBLIC_DEVELOPMENT,
        )

    mutation_cells = [
        cell
        for cell, row in sorted(_CELL_ROWS.items())
        if cell not in {target_cell, ("C02", "F02"), ("C01", "F03"), source_extra_cell}
        and CaseOrigin.ADVERSARIAL_MUTATION in row.case_origins
    ][:28]
    assert len(mutation_cells) == 28
    parent_registry: list[MutationParentProvenance] = []
    for index, cell in enumerate(mutation_cells):
        lineage = f"lineage:{index:02d}"
        parent_id = f"external-parent:{index:02d}"
        parent_hash = canonical_hash(("RES369-ABSTRACT-PARENT", parent_id))
        parent_registry.append(MutationParentProvenance(parent_id, parent_hash, cell))
        for child in range(4):
            candidate_id = f"mutation:{index:02d}:{child}"
            add(
                candidate_id,
                cell,
                CaseOrigin.ADVERSARIAL_MUTATION,
                cluster=f"cluster:{lineage}",
                lineage=lineage,
                parent_id=parent_id,
                parent_hash=parent_hash,
            )
    assert len(candidates) == FINAL_CASE_COUNT
    return tuple(candidates), tuple(parent_registry)


def _production_oversupply_with_rejection() -> tuple[
    tuple[FinalSelectionCandidate, ...],
    tuple[MutationParentProvenance, ...],
    str,
    str,
]:
    base, parent_registry = _production_shape_candidates()
    rejected_id = "cell:C01:F03:0"
    rejected = next(item for item in base if item.candidate_id == rejected_id)
    reserve = replace(
        rejected,
        candidate_id="reserve:rejection-backfill",
        payload_hash=canonical_hash("RES369-ABSTRACT-RESERVE"),
        isolation_cluster_id="cluster:reserve:rejection-backfill",
        isolation_identities=(
            IsolationIdentity(
                IsolationIdentityKind.SOURCE_FAMILY,
                "family:reserve:rejection-backfill",
            ),
        ),
    )
    trap = next(item for item in base if item.candidate_id == "000-trap-a")
    alternate = replace(
        trap,
        candidate_id="000-trap-b",
        payload_hash=canonical_hash("RES369-ABSTRACT-SELECT-FIRST-TRAP"),
        review_eligibility=ReviewEligibility.APPROVED,
        isolation_cluster_id=trap.isolation_cluster_id,
        isolation_identities=trap.isolation_identities,
    )
    changed = tuple(
        replace(item, review_eligibility=ReviewEligibility.REJECTED)
        if item.candidate_id == rejected_id
        else item
        for item in base
    )
    pool = (*changed, reserve, alternate)
    return tuple(pool), parent_registry, rejected_id, reserve.candidate_id


def _production_shape_hint(problem: FinalSelectionProblem) -> FinalSelectionPlan:
    assignments: dict[str, AssignmentState] = {}
    for candidate in problem.candidates:
        candidate_id = candidate.candidate_id
        if (
            candidate.review_eligibility is not ReviewEligibility.APPROVED
            or candidate.qualification_excluded
            or candidate_id == "000-trap-b"
        ):
            assignments[candidate_id] = AssignmentState.OUT
        elif candidate_id == "000-trap-a":
            assignments[candidate_id] = AssignmentState.PUBLIC_DEVELOPMENT
        elif candidate_id == "001-trap-d":
            assignments[candidate_id] = AssignmentState.FROZEN_VALIDATION
        elif candidate_id == "zzz-alternative":
            assignments[candidate_id] = AssignmentState.HIDDEN_FINAL
        elif candidate_id.startswith("cell:"):
            variant = int(candidate_id.rsplit(":", 1)[1])
            assignments[candidate_id] = AssignmentState(SPLIT_ORDER[variant].value)
        else:
            assignments[candidate_id] = AssignmentState.PUBLIC_DEVELOPMENT
    return _plan(problem, assignments)


def _constraint(
    constraint_id: str,
    kind: ConstraintKind,
    *,
    candidate_ids: tuple[str, ...] = (),
    split: SplitName | None = None,
    feature: SelectionFeature | None = None,
    origin: CaseOrigin | None = None,
    minimum: int | None = None,
    maximum: int | None = None,
    locked_split: SplitName | None = None,
    relation: RelationKind | None = None,
    related_id: str | None = None,
    related_hash: str | None = None,
    reason: str | None = None,
) -> SelectionConstraint:
    return SelectionConstraint(
        constraint_id=constraint_id,
        authority_ref="RES-369 test authority",
        kind=kind,
        candidate_ids=tuple(sorted(candidate_ids, key=str.encode)),
        split=split,
        feature=feature,
        origin_class=origin,
        minimum=minimum,
        maximum=maximum,
        locked_split=locked_split,
        relation_kind=relation,
        related_id=related_id,
        related_payload_hash=related_hash,
        reason=reason,
    )


@pytest.mark.parametrize(
    "case",
    (
        "feature",
        "origin",
        "review",
        "qualification",
        "lock",
        "lineage",
        "lineage_duplicate",
        "parent",
        "colocation",
    ),
)
def test_small_n_cp_sat_matches_exhaustive_assignment_oracle(case: str) -> None:
    cell = SelectionFeature(FeatureKind.CELL, ("C01", "F01"))
    candidates: tuple[FinalSelectionCandidate, ...]
    extra: tuple[SelectionConstraint, ...]
    targets: tuple[tuple[SplitName, int], ...]
    parent_registry: tuple[MutationParentProvenance, ...] = ()
    if case == "feature":
        candidates = (_candidate("a", features=(cell,)), _candidate("b"))
        extra = (
            _constraint(
                "feature",
                ConstraintKind.FEATURE_MINIMUM,
                split=SplitName.PUBLIC_DEVELOPMENT,
                feature=cell,
                minimum=1,
            ),
        )
        targets = ((SplitName.PUBLIC_DEVELOPMENT, 1),)
    elif case == "origin":
        candidates = (
            _candidate("expert", origin=CaseOrigin.EXPERT_AUTHORED_SEMANTIC),
            _candidate("source", origin=CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION),
        )
        extra = (
            _constraint(
                "source-min",
                ConstraintKind.ORIGIN_BOUNDS,
                origin=CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION,
                minimum=1,
                maximum=1,
            ),
            _constraint(
                "expert-max",
                ConstraintKind.ORIGIN_BOUNDS,
                origin=CaseOrigin.EXPERT_AUTHORED_SEMANTIC,
                minimum=0,
                maximum=0,
            ),
        )
        targets = ((SplitName.PUBLIC_DEVELOPMENT, 1),)
    elif case == "review":
        candidates = (
            _candidate("approved"),
            _candidate("rejected", review=ReviewEligibility.REJECTED),
        )
        extra = (
            _constraint(
                "rejected-out",
                ConstraintKind.REVIEW_OUT_ONLY,
                candidate_ids=("rejected",),
                reason="REJECTED",
            ),
        )
        targets = ((SplitName.PUBLIC_DEVELOPMENT, 1),)
    elif case == "qualification":
        candidates = (_candidate("eligible"), _candidate("qualification", excluded=True))
        extra = (
            _constraint(
                "qualification-out",
                ConstraintKind.QUALIFICATION_OUT_ONLY,
                candidate_ids=("qualification",),
                reason="QUALIFICATION_EXCLUDED",
            ),
        )
        targets = ((SplitName.PUBLIC_DEVELOPMENT, 1),)
    elif case == "lock":
        candidates = (
            _candidate(
                "synthetic",
                origin=CaseOrigin.DETERMINISTIC_SYNTHETIC,
                locked_split=SplitName.HIDDEN_FINAL,
            ),
            _candidate("public"),
        )
        extra = (
            _constraint(
                "synthetic-lock",
                ConstraintKind.SYNTHETIC_SPLIT_LOCK,
                candidate_ids=("synthetic",),
                locked_split=SplitName.HIDDEN_FINAL,
            ),
        )
        targets = ((SplitName.PUBLIC_DEVELOPMENT, 1),)
    elif case == "lineage":
        parent1 = MutationParentProvenance("p1", _SHA, ("C01", "F01"))
        parent2 = MutationParentProvenance("p2", "sha256:" + "b" * 64, ("C01", "F01"))
        parent_registry = (parent1, parent2)
        candidates = (
            _candidate(
                "mut-a",
                origin=CaseOrigin.ADVERSARIAL_MUTATION,
                lineage="L1",
                parent_id="p1",
                parent_hash=_SHA,
            ),
            _candidate(
                "mut-b",
                origin=CaseOrigin.ADVERSARIAL_MUTATION,
                lineage="L1",
                parent_id="p1",
                parent_hash=_SHA,
            ),
            _candidate(
                "mut-c",
                origin=CaseOrigin.ADVERSARIAL_MUTATION,
                lineage="L2",
                parent_id="p2",
                parent_hash="sha256:" + "b" * 64,
            ),
        )
        extra = (
            _constraint("lineages", ConstraintKind.MUTATION_LINEAGE_MINIMUM, minimum=2),
            *(
                _constraint(
                    f"proof:{candidate.candidate_id}",
                    ConstraintKind.MUTATION_PARENT_PROVENANCE,
                    candidate_ids=(candidate.candidate_id,),
                    related_id=candidate.mutation_parent_candidate_id,
                    related_hash=candidate.mutation_parent_payload_hash,
                )
                for candidate in candidates
            ),
        )
        targets = ((SplitName.PUBLIC_DEVELOPMENT, 2),)
    elif case == "lineage_duplicate":
        parent_hash = canonical_hash("same parent")
        parent_registry = (MutationParentProvenance("same-parent", parent_hash, ("C01", "F01")),)
        candidates = (
            _candidate(
                "mut-a",
                origin=CaseOrigin.ADVERSARIAL_MUTATION,
                lineage="L1",
                parent_id="same-parent",
                parent_hash=parent_hash,
            ),
            _candidate(
                "mut-b",
                origin=CaseOrigin.ADVERSARIAL_MUTATION,
                lineage="L1",
                parent_id="same-parent",
                parent_hash=parent_hash,
            ),
        )
        extra = (_constraint("lineages", ConstraintKind.MUTATION_LINEAGE_MINIMUM, minimum=2),)
        targets = ((SplitName.PUBLIC_DEVELOPMENT, 2),)
    elif case == "parent":
        parent_hash = canonical_hash("parent payload")
        parent = _candidate("parent", review=ReviewEligibility.REJECTED)
        parent_hash = parent.payload_hash
        candidates = (
            _candidate(
                "child",
                origin=CaseOrigin.ADVERSARIAL_MUTATION,
                lineage="L1",
                parent_id="parent",
                parent_hash=parent_hash,
            ),
            parent,
        )
        extra = (
            _constraint(
                "parent-out",
                ConstraintKind.REVIEW_OUT_ONLY,
                candidate_ids=("parent",),
                reason="REJECTED",
            ),
            _constraint(
                "parent-proof",
                ConstraintKind.MUTATION_PARENT_PROVENANCE,
                candidate_ids=("child",),
                related_id="parent",
                related_hash=parent_hash,
            ),
            _constraint(
                "conditional-parent",
                ConstraintKind.CONDITIONAL_COLOCATION,
                candidate_ids=("child", "parent"),
                relation=RelationKind.MUTATION_PARENT,
            ),
            _constraint("lineage-min", ConstraintKind.MUTATION_LINEAGE_MINIMUM, minimum=1),
        )
        targets = ((SplitName.PUBLIC_DEVELOPMENT, 1),)
    else:
        candidates = (
            _candidate(
                "related-a",
                identities=(IsolationIdentity(IsolationIdentityKind.SOURCE_FAMILY, "shared"),),
                cluster="shared",
            ),
            _candidate(
                "related-b",
                identities=(IsolationIdentity(IsolationIdentityKind.SOURCE_FAMILY, "shared"),),
                cluster="shared",
            ),
            _candidate("independent"),
        )
        extra = (
            _constraint(
                "same-split",
                ConstraintKind.CONDITIONAL_COLOCATION,
                candidate_ids=("related-a", "related-b"),
                relation=RelationKind.ISOLATION_IDENTITY,
            ),
        )
        targets = ((SplitName.PUBLIC_DEVELOPMENT, 1), (SplitName.FROZEN_VALIDATION, 1))
    problem = _toy_problem(
        candidates,
        targets,
        extra=extra,
        parent_registry=parent_registry,
    )
    expected = _small_oracle(problem)
    result = solve_final_selection(problem)
    assert (result.solve_receipt.status is not SolveStatus.INFEASIBLE) is expected
    if expected:
        assert result.plan is not None
        assert validate_final_selection(problem, result.plan).status is ValidationStatus.VALID


def test_conditional_relations_allow_one_member_out_and_reject_cross_split() -> None:
    relation = _constraint(
        "same-split",
        ConstraintKind.CONDITIONAL_COLOCATION,
        candidate_ids=("a", "b"),
        relation=RelationKind.EXACT_SHINGLE,
    )
    one_selected = _toy_problem(
        (_candidate("a", exact_shingles=(_SHA,)), _candidate("b", exact_shingles=(_SHA,))),
        ((SplitName.PUBLIC_DEVELOPMENT, 1),),
        extra=(relation,),
    )
    one_result = solve_final_selection(one_selected)
    assert one_result.plan is not None
    assert sum(item.state is AssignmentState.OUT for item in one_result.plan.assignments) == 1

    both_selected = _toy_problem(
        (_candidate("a"), _candidate("b")),
        ((SplitName.PUBLIC_DEVELOPMENT, 1), (SplitName.FROZEN_VALIDATION, 1)),
        extra=(relation,),
    )
    crossing = _plan(
        both_selected,
        {"a": AssignmentState.PUBLIC_DEVELOPMENT, "b": AssignmentState.FROZEN_VALIDATION},
    )
    assert validate_final_selection(both_selected, crossing).status is ValidationStatus.INVALID
    assert solve_final_selection(both_selected).solve_receipt.status is SolveStatus.INFEASIBLE


def test_synthetic_lock_blocks_wrong_split_when_candidate_is_required() -> None:
    problem = _toy_problem(
        (
            _candidate(
                "locked-synthetic",
                origin=CaseOrigin.DETERMINISTIC_SYNTHETIC,
                locked_split=SplitName.HIDDEN_FINAL,
            ),
        ),
        ((SplitName.PUBLIC_DEVELOPMENT, 1),),
        extra=(
            _constraint(
                "synthetic-lock",
                ConstraintKind.SYNTHETIC_SPLIT_LOCK,
                candidate_ids=("locked-synthetic",),
                locked_split=SplitName.HIDDEN_FINAL,
            ),
        ),
    )
    assert solve_final_selection(problem).solve_receipt.status is SolveStatus.INFEASIBLE


def test_review_statuses_are_out_only_and_exact_shingles_form_conditional_groups() -> None:
    candidates = tuple(
        _candidate(
            status.value.lower(),
            review=status,
            exact_shingles=(_SHA,),
        )
        for status in (
            ReviewEligibility.APPROVED,
            ReviewEligibility.REJECTED,
            ReviewEligibility.PENDING,
            ReviewEligibility.UNAPPROVED,
            ReviewEligibility.INVALID,
        )
    )
    problem = build_final_selection_problem(candidates)
    review_constraints = {
        constraint.candidate_ids[0]: constraint
        for constraint in problem.constraint_set.constraints
        if constraint.kind is ConstraintKind.REVIEW_OUT_ONLY
    }
    assert set(review_constraints) == {candidate.candidate_id for candidate in candidates[1:]}
    shingle_groups = tuple(
        constraint
        for constraint in problem.constraint_set.constraints
        if constraint.kind is ConstraintKind.CONDITIONAL_COLOCATION
        and constraint.relation_kind is RelationKind.EXACT_SHINGLE
    )
    assert len(shingle_groups) == 1
    assert shingle_groups[0].candidate_ids == tuple(
        sorted((candidate.candidate_id for candidate in candidates), key=str.encode)
    )


def test_missing_parent_provenance_is_infeasible_and_child_can_be_selected_without_parent() -> None:
    child = _candidate(
        "child",
        origin=CaseOrigin.ADVERSARIAL_MUTATION,
        lineage="L1",
        parent_id="external-parent",
        parent_hash=_SHA,
    )
    proof = _constraint(
        "parent-proof",
        ConstraintKind.MUTATION_PARENT_PROVENANCE,
        candidate_ids=("child",),
        related_id="external-parent",
        related_hash=_SHA,
    )
    lineage = _constraint("lineage-min", ConstraintKind.MUTATION_LINEAGE_MINIMUM, minimum=1)
    missing = _toy_problem((child,), ((SplitName.PUBLIC_DEVELOPMENT, 1),), extra=(proof, lineage))
    assert solve_final_selection(missing).solve_receipt.status is SolveStatus.INFEASIBLE

    parent = _candidate("parent", review=ReviewEligibility.REJECTED)
    parent_hash = parent.payload_hash
    child = replace(
        child,
        mutation_parent_candidate_id="parent",
        mutation_parent_payload_hash=parent_hash,
    )
    resolved_proof = _constraint(
        "resolved-parent-proof",
        ConstraintKind.MUTATION_PARENT_PROVENANCE,
        candidate_ids=("child",),
        related_id="parent",
        related_hash=parent_hash,
    )
    constraints = (
        resolved_proof,
        lineage,
        _constraint(
            "parent-out",
            ConstraintKind.REVIEW_OUT_ONLY,
            candidate_ids=("parent",),
            reason="REJECTED",
        ),
        _constraint(
            "parent-colocation",
            ConstraintKind.CONDITIONAL_COLOCATION,
            candidate_ids=("child", "parent"),
            relation=RelationKind.MUTATION_PARENT,
        ),
    )
    valid = _toy_problem(
        (child, parent),
        ((SplitName.PUBLIC_DEVELOPMENT, 1),),
        extra=constraints,
    )
    result = solve_final_selection(valid)
    assert result.plan is not None
    assert dict((item.candidate_id, item.state) for item in result.plan.assignments) == {
        "child": AssignmentState.PUBLIC_DEVELOPMENT,
        "parent": AssignmentState.OUT,
    }


def test_out_only_invalid_mutation_does_not_block_an_eligible_selection() -> None:
    invalid_child = _candidate(
        "invalid-child",
        origin=CaseOrigin.ADVERSARIAL_MUTATION,
        review=ReviewEligibility.INVALID,
        lineage="unresolved-lineage",
        parent_id="missing-parent",
    )
    problem = _toy_problem(
        (invalid_child, _candidate("eligible")),
        ((SplitName.PUBLIC_DEVELOPMENT, 1),),
    )
    result = solve_final_selection(problem)
    assert result.plan is not None
    assignments = {item.candidate_id: item.state for item in result.plan.assignments}
    assert assignments["invalid-child"] is AssignmentState.OUT
    assert assignments["eligible"] is AssignmentState.PUBLIC_DEVELOPMENT


def test_mutation_cell_inheritance_requires_explicit_exception_authority() -> None:
    parent = _candidate("parent", review=ReviewEligibility.REJECTED, cell=("C01", "F01"))
    child = _candidate(
        "child",
        origin=CaseOrigin.ADVERSARIAL_MUTATION,
        lineage="L1",
        parent_id="parent",
        parent_hash=parent.payload_hash,
        cell=("C02", "F02"),
    )
    constraints = (
        _constraint(
            "parent-out",
            ConstraintKind.REVIEW_OUT_ONLY,
            candidate_ids=("parent",),
            reason="REJECTED",
        ),
        _constraint(
            "parent-proof",
            ConstraintKind.MUTATION_PARENT_PROVENANCE,
            candidate_ids=("child",),
            related_id="parent",
            related_hash=parent.payload_hash,
        ),
        _constraint(
            "parent-cell",
            ConstraintKind.MUTATION_PARENT_CELL_INHERITANCE,
            candidate_ids=("child",),
            related_id="parent",
        ),
        _constraint("lineage-min", ConstraintKind.MUTATION_LINEAGE_MINIMUM, minimum=1),
    )
    blocked = _toy_problem(
        (child, parent),
        ((SplitName.PUBLIC_DEVELOPMENT, 1),),
        extra=constraints,
    )
    assert solve_final_selection(blocked).solve_receipt.status is SolveStatus.INFEASIBLE

    exception_ref = "RES-258:operator-specific-cell-inheritance-exception"
    child = replace(child, mutation_cell_exception_authority_ref=exception_ref)
    exception_constraints = tuple(
        replace(item, reason=exception_ref) if item.constraint_id == "parent-cell" else item
        for item in constraints
    )
    allowed = _toy_problem(
        (child, parent),
        ((SplitName.PUBLIC_DEVELOPMENT, 1),),
        extra=exception_constraints,
    )
    result = solve_final_selection(allowed)
    assert result.plan is not None
    assert validate_final_selection(allowed, result.plan).status is ValidationStatus.VALID


def test_unknown_is_unresolved_and_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    problem = _toy_problem((_candidate("a"),), ((SplitName.PUBLIC_DEVELOPMENT, 1),))

    def unknown(_model: Any, _config: SelectionSolverConfig) -> tuple[object, str, float]:
        return object(), "UNKNOWN", 0.0

    monkeypatch.setattr("dynamislm.benchmark.selection_solver._solve_once", unknown)
    result = solve_final_selection(problem)
    assert result.solve_receipt.status is SolveStatus.UNKNOWN
    assert result.plan is None
    assert result.validation_receipt is None


def test_canonical_plan_is_stable_five_of_five() -> None:
    problem = _toy_problem(
        (_candidate("a"), _candidate("b"), _candidate("c")),
        ((SplitName.PUBLIC_DEVELOPMENT, 1), (SplitName.FROZEN_VALIDATION, 1)),
    )
    digests = tuple(solve_final_selection(problem).plan.plan_digest for _ in range(5))  # type: ignore[union-attr]
    assert len(set(digests)) == 1


def test_joint_solver_does_not_call_legacy_phase_e_allocator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dynamislm.benchmark import split

    def forbidden(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("legacy split allocator called by final selection")

    monkeypatch.setattr(split, "allocate_splits", forbidden)
    problem = _toy_problem((_candidate("a"),), ((SplitName.PUBLIC_DEVELOPMENT, 1),))
    result = solve_final_selection(problem)
    assert result.plan is not None


def test_fixed_434_abstract_qualification_and_resource_receipt() -> None:
    candidates, parent_registry = _production_shape_candidates()
    problem = build_final_selection_problem(candidates, parent_provenance_registry=parent_registry)
    result = solve_final_selection(
        problem,
        initial_plan_hint=_production_shape_hint(problem),
        solver_config=SelectionSolverConfig(timeout_s=60, cp_model_presolve=False),
    )
    assert result.solve_receipt.status is SolveStatus.OPTIMAL
    assert result.plan is not None and result.validation_receipt is not None
    assert result.validation_receipt.status is ValidationStatus.VALID
    assert sum(item.state is not AssignmentState.OUT for item in result.plan.assignments) == 434
    assert result.validation_receipt.summary.split_counts == FINAL_SPLIT_COUNTS
    assert result.validation_receipt.summary.selected_mutation_lineages == 28
    assert result.solve_receipt.variable_count >= len(candidates) * 4
    assert result.solve_receipt.constraint_count > 0
    assert result.solve_receipt.wall_s > 0
    assert result.solve_receipt.objective_optimization_wall_s > 0
    assert result.solve_receipt.canonicalization_wall_s > 0
    assert result.solve_receipt.deterministic_time_s > 0
    assert result.solve_receipt.peak_rss_mb > 0
    assert result.solve_receipt.warm_start_used
    assert result.validation_receipt.validation_wall_s > 0


def test_oversupply_sequential_counterexample_and_rejection_removal() -> None:
    pool, parent_registry, rejected_id, reserve_id = _production_oversupply_with_rejection()
    problem = build_final_selection_problem(pool, parent_provenance_registry=parent_registry)
    assert len(pool) > FINAL_CASE_COUNT
    assert (
        sum(
            item.review_eligibility is ReviewEligibility.APPROVED
            and not item.qualification_excluded
            for item in pool
        )
        == FINAL_CASE_COUNT + 1
    )

    config = SelectionSolverConfig(timeout_s=60, cp_model_presolve=False)
    result = solve_final_selection(
        problem,
        initial_plan_hint=_production_shape_hint(problem),
        solver_config=config,
    )
    assert result.solve_receipt.status is SolveStatus.OPTIMAL
    assert result.plan is not None and result.validation_receipt is not None
    assignments = {item.candidate_id: item.state for item in result.plan.assignments}
    assert sum(state is not AssignmentState.OUT for state in assignments.values()) == 434
    assert assignments[rejected_id] is AssignmentState.OUT
    assert assignments[reserve_id] is not AssignmentState.OUT
    assert result.validation_receipt.status is ValidationStatus.VALID
    assert result.validation_receipt.summary.split_counts == FINAL_SPLIT_COUNTS

    eligible = tuple(
        sorted(
            (
                item
                for item in pool
                if item.review_eligibility is ReviewEligibility.APPROVED
                and not item.qualification_excluded
            ),
            key=lambda item: item.candidate_id.encode(),
        )
    )
    select_first = eligible[:FINAL_CASE_COUNT]
    assert "000-trap-a" in {item.candidate_id for item in select_first}
    assert "000-trap-b" in {item.candidate_id for item in select_first}
    assert "zzz-alternative" not in {item.candidate_id for item in select_first}
    sequential_problem = build_final_selection_problem(
        select_first,
        parent_provenance_registry=parent_registry,
    )
    assert (
        solve_final_selection(
            sequential_problem,
            solver_config=SelectionSolverConfig(cp_model_presolve=False),
        ).solve_receipt.status
        is SolveStatus.INFEASIBLE
    )


def test_commitment_adapter_uses_typed_review_and_coverage_features() -> None:
    row = _ROWS["C01"]
    recipe = next(
        recipe
        for recipe in AUTHORING_RECIPE_REGISTRY
        if (recipe.capability_id, "F01") == ("C01", "F01")
    )
    item = ProductionAuthoringPlanItemV1(
        candidate_id="PSE-V1-CANDIDATE:res369-adapter",
        recipe_id=recipe.recipe_id,
        recipe_version=recipe.recipe_version,
        capability_id="C01",
        benchmark_family="F01",
        practitioner_question_class=question_classes_for_cell("C01", "F01")[0],
        origin_class=CaseOrigin.EXPERT_AUTHORED_SEMANTIC,
        scoring_profile=recipe.scorers[0],
        authority_class="EXPERT_SEMANTIC",
        authority_kinds=("EXPERT_RUBRIC",),
        reachable_error_classes=tuple(sorted(row.error_classes, key=lambda item: item.value)),
        adversarial_tags=tuple(sorted(row.adversarial_tags)),
        source_family_id="source-family:res369-adapter",
        source_document_ids=("source-document:res369-adapter",),
        source_artifact_ids=("source-artifact:res369-adapter",),
        construct_test_identity_ids=("construct:res369-adapter",),
        provider_export_ids=("provider-export:res369-adapter",),
        protocol_template_ids=("template:res369-adapter",),
        expert_author_batch_id="expert-batch:res369-adapter",
        author_id=PRODUCTION_AUTHORING_PROCESS_ID,
        generator_id=None,
        generator_version=None,
        generator_family=None,
        seed_namespace=None,
        seed_block=None,
        mutation_lineage_id=None,
        parent_candidate_id=None,
        isolation_cluster_id="cluster:res369-adapter",
        allocation_stratum="C01:F01",
        refusal_decision=RefusalDecision.PROHIBITED,
        expected_answer_kind=ExpectedAnswerKind.ANSWER,
        safe_partial_support=False,
        difficulty=DifficultyLevel.EASY,
    )
    commitment = ProductionCandidateCommitmentV1(item, canonical_hash("adapter-payload"))
    contamination = ContaminationBinding(
        source_artifact_ids=item.source_artifact_ids,
        document_ids=item.source_document_ids,
        source_family_id=item.source_family_id,
        provider_export_id="provider-export:res369-adapter",
        protocol_template_id="template:res369-adapter",
        expert_author_batch_id="expert-batch:res369-adapter",
        artifact_ids=("general-artifact:res369-adapter",),
        source_content_sha256=None,
        normalized_text_sha256=None,
        exact_shingle_digest=_SHA,
        fuzzy_fingerprint=_SHA,
        semantic_cluster_id=None,
        generator_namespace=None,
        generator_seed_block=None,
        benchmark_artifact_ids=("benchmark-artifact:res369-adapter",),
        training_exclusion_ids=("training-exclusion:res369-adapter",),
        construct_test_identity_ids=item.construct_test_identity_ids,
    )
    with pytest.raises(ValueError, match="complete contamination binding"):
        build_final_selection_problem_from_commitments(
            (commitment,),
            review_eligibility={item.candidate_id: HumanReviewDecision.APPROVED},
            contamination_bindings={},
        )
    problem = build_final_selection_problem_from_commitments(
        (commitment,),
        review_eligibility={item.candidate_id: HumanReviewDecision.APPROVED},
        contamination_bindings={item.candidate_id: contamination},
    )
    candidate = problem.candidates[0]
    assert candidate.review_eligibility is ReviewEligibility.APPROVED
    assert SelectionFeature(FeatureKind.CELL, ("C01", "F01")) in candidate.features
    assert SelectionFeature(FeatureKind.ANSWERABLE) in candidate.features
    assert candidate.exact_shingle_digests == (_SHA,)
    assert {identity.kind for identity in candidate.isolation_identities} >= {
        IsolationIdentityKind.SOURCE_FAMILY,
        IsolationIdentityKind.PROTOCOL_TEMPLATE,
        IsolationIdentityKind.GENERAL_ARTIFACT,
        IsolationIdentityKind.BENCHMARK_ARTIFACT,
        IsolationIdentityKind.TRAINING_EXCLUSION,
    }
    pending_problem = build_final_selection_problem_from_commitments(
        (commitment,),
        review_eligibility={item.candidate_id: CandidateReviewStatus.PENDING_HUMAN_REVIEW},
        contamination_bindings={item.candidate_id: contamination},
    )
    assert pending_problem.candidates[0].review_eligibility is ReviewEligibility.PENDING
    assert any(
        constraint.kind is ConstraintKind.REVIEW_OUT_ONLY
        for constraint in pending_problem.constraint_set.constraints
    )
