"""Pure semantic validation for joint final-selection plans."""

from __future__ import annotations

import time
from collections import Counter

from dynamislm.benchmark.constants import SPLIT_ORDER, CaseOrigin, SplitName
from dynamislm.benchmark.selection_contracts import (
    SELECTION_VALIDATOR_VERSION,
    AssignmentState,
    ConstraintKind,
    FeatureKind,
    FinalSelectionPlan,
    FinalSelectionProblem,
    SelectionConstraint,
    SelectionCoverageSummary,
    SelectionIsolationSummary,
    SelectionSummary,
    SelectionValidationReceipt,
    ValidationStatus,
)
from dynamislm.serialization import canonical_hash


def _constraint_satisfied(
    constraint: SelectionConstraint,
    problem: FinalSelectionProblem,
    assignments: dict[str, AssignmentState],
) -> bool:
    candidates = {item.candidate_id: item for item in problem.candidates}
    selected = {
        candidate_id
        for candidate_id, state in assignments.items()
        if state is not AssignmentState.OUT
    }
    if constraint.kind is ConstraintKind.ONE_STATE_PER_CANDIDATE:
        return len(constraint.candidate_ids) == 1 and constraint.candidate_ids[0] in assignments
    if constraint.kind is ConstraintKind.FINAL_COUNT:
        count = len(selected)
    elif constraint.kind is ConstraintKind.SPLIT_COUNT:
        count = sum(state.split_name is constraint.split for state in assignments.values())
    elif constraint.kind is ConstraintKind.FEATURE_MINIMUM:
        assert constraint.split is not None and constraint.feature is not None
        count = sum(
            assignments.get(candidate.candidate_id) is not None
            and assignments[candidate.candidate_id].split_name is constraint.split
            and constraint.feature in candidate.features
            for candidate in problem.candidates
        )
    elif constraint.kind is ConstraintKind.ORIGIN_BOUNDS:
        assert constraint.origin_class is not None
        count = sum(
            candidate_id in selected
            and candidates[candidate_id].origin_class is constraint.origin_class
            for candidate_id in assignments
            if candidate_id in candidates
        )
    elif constraint.kind is ConstraintKind.MUTATION_LINEAGE_MINIMUM:
        lineages = {
            candidates[candidate_id].mutation_lineage_id
            for candidate_id in selected
            if candidate_id in candidates
            and candidates[candidate_id].origin_class is CaseOrigin.ADVERSARIAL_MUTATION
            and candidates[candidate_id].mutation_lineage_id is not None
        }
        count = len(lineages)
    elif constraint.kind in {
        ConstraintKind.REVIEW_OUT_ONLY,
        ConstraintKind.QUALIFICATION_OUT_ONLY,
    }:
        return assignments.get(constraint.candidate_ids[0]) is AssignmentState.OUT
    elif constraint.kind is ConstraintKind.SYNTHETIC_SPLIT_LOCK:
        state = assignments.get(constraint.candidate_ids[0], AssignmentState.OUT)
        return state is AssignmentState.OUT or state.split_name is constraint.locked_split
    elif constraint.kind is ConstraintKind.CONDITIONAL_COLOCATION:
        placed = {
            assignments[candidate_id]
            for candidate_id in constraint.candidate_ids
            if candidate_id in assignments and assignments[candidate_id] is not AssignmentState.OUT
        }
        return len(placed) <= 1
    else:
        candidate_id = constraint.candidate_ids[0]
        candidate = candidates[candidate_id]
        if assignments.get(candidate_id, AssignmentState.OUT) is AssignmentState.OUT:
            return True
        if constraint.kind is ConstraintKind.MUTATION_PARENT_CELL_INHERITANCE:
            if candidate.mutation_parent_candidate_id != constraint.related_id:
                return False
            if constraint.reason != candidate.mutation_cell_exception_authority_ref:
                return False
            registry = {item.candidate_id: item for item in problem.parent_provenance_registry}
            parent = registry.get(constraint.related_id or "")
            if parent is None:
                return False
            return (
                candidate.cell == parent.cell
                or candidate.mutation_cell_exception_authority_ref is not None
            )
        assert constraint.kind is ConstraintKind.MUTATION_PARENT_PROVENANCE
        if candidate.mutation_parent_candidate_id != constraint.related_id:
            return False
        if candidate.mutation_parent_payload_hash is None:
            return False
        registry = {item.candidate_id: item for item in problem.parent_provenance_registry}
        parent = registry.get(constraint.related_id or "")
        return (
            constraint.related_payload_hash == candidate.mutation_parent_payload_hash
            and parent is not None
            and parent.payload_hash == candidate.mutation_parent_payload_hash
        )
    assert constraint.minimum is not None
    return count >= constraint.minimum and (
        constraint.maximum is None or count <= constraint.maximum
    )


def _summary(
    problem: FinalSelectionProblem,
    assignments: dict[str, AssignmentState],
) -> SelectionSummary:
    candidates = {item.candidate_id: item for item in problem.candidates}
    selected_ids = {
        candidate_id
        for candidate_id, state in assignments.items()
        if state is not AssignmentState.OUT and candidate_id in candidates
    }
    split_counts = tuple(
        (split, sum(state.split_name is split for state in assignments.values()))
        for split in SPLIT_ORDER
    )
    origin_counter: Counter[CaseOrigin] = Counter(
        candidates[candidate_id].origin_class for candidate_id in selected_ids
    )
    selected_lineages = {
        candidates[candidate_id].mutation_lineage_id
        for candidate_id in selected_ids
        if candidates[candidate_id].origin_class is CaseOrigin.ADVERSARIAL_MUTATION
        and candidates[candidate_id].mutation_lineage_id is not None
    }
    feature_counts: dict[tuple[FeatureKind, SplitName], int] = {}
    for constraint in problem.constraint_set.constraints:
        if (
            constraint.kind is ConstraintKind.FEATURE_MINIMUM
            and constraint.feature is not None
            and constraint.split is not None
            and _constraint_satisfied(constraint, problem, assignments)
        ):
            key = (constraint.feature.kind, constraint.split)
            feature_counts[key] = feature_counts.get(key, 0) + 1

    def by_feature(kind: FeatureKind) -> tuple[tuple[SplitName, int], ...]:
        return tuple((split, feature_counts.get((kind, split), 0)) for split in SPLIT_ORDER)

    relation_constraints = tuple(
        item
        for item in problem.constraint_set.constraints
        if item.kind is ConstraintKind.CONDITIONAL_COLOCATION
    )
    active_relations = 0
    crossing_relations = 0
    for constraint in relation_constraints:
        placed = {
            assignments[candidate_id]
            for candidate_id in constraint.candidate_ids
            if candidate_id in assignments and assignments[candidate_id] is not AssignmentState.OUT
        }
        active_relations += bool(placed)
        crossing_relations += len(placed) > 1
    active_clusters = sum(
        any(
            assignments.get(candidate_id, AssignmentState.OUT) is not AssignmentState.OUT
            for candidate_id in cluster.candidate_ids
        )
        for cluster in problem.constraint_set.allocation_clusters
    )
    return SelectionSummary(
        split_counts=split_counts,
        out_count=sum(state is AssignmentState.OUT for state in assignments.values()),
        selected_origin_counts=tuple((origin, origin_counter[origin]) for origin in CaseOrigin),
        selected_mutation_lineages=len(selected_lineages),
        coverage=SelectionCoverageSummary(
            cells_by_split=by_feature(FeatureKind.CELL),
            row_tags_by_split=by_feature(FeatureKind.ROW_TAG),
            row_errors_by_split=by_feature(FeatureKind.ROW_ERROR),
            c18_refusals_by_split=by_feature(FeatureKind.C18_REFUSAL),
            answerable_by_split=by_feature(FeatureKind.ANSWERABLE),
            critical_classes_by_split=by_feature(FeatureKind.CRITICAL_ERROR),
        ),
        isolation=SelectionIsolationSummary(
            relation_groups=len(relation_constraints),
            active_relation_groups=active_relations,
            cross_split_relation_groups=crossing_relations,
            allocation_clusters=len(problem.constraint_set.allocation_clusters),
            active_allocation_clusters=active_clusters,
        ),
    )


def validate_final_selection(
    problem: FinalSelectionProblem,
    plan: FinalSelectionPlan,
) -> SelectionValidationReceipt:
    """Validate a proposed plan using only typed semantics, never CP-SAT."""

    started = time.perf_counter()
    assignments = {item.candidate_id: item.state for item in plan.assignments}
    violations: set[str] = set()
    candidate_ids = {item.candidate_id for item in problem.candidates}
    if plan.authority_digest != problem.authority_digest:
        violations.add("PLAN:AUTHORITY_BINDING")
    if plan.problem_digest != problem.problem_digest:
        violations.add("PLAN:PROBLEM_BINDING")
    if plan.approved_pool_digest != problem.approved_pool_digest:
        violations.add("PLAN:APPROVED_POOL_BINDING")
    if set(assignments) != candidate_ids:
        violations.add("PLAN:ASSIGNMENT_SET")
    for constraint in problem.constraint_set.constraints:
        if not _constraint_satisfied(constraint, problem, assignments):
            violations.add(constraint.constraint_id)
    summary = _summary(problem, assignments)
    ordered_violations = tuple(sorted(violations, key=str.encode))
    status = ValidationStatus.INVALID if ordered_violations else ValidationStatus.VALID
    validation_digest = canonical_hash(
        {
            "version": SELECTION_VALIDATOR_VERSION,
            "status": status,
            "violations": ordered_violations,
            "plan_digest": plan.plan_digest,
            "authority_digest": problem.authority_digest,
            "summary": summary,
        }
    )
    return SelectionValidationReceipt(
        validator_version=SELECTION_VALIDATOR_VERSION,
        status=status,
        violated_constraint_ids=ordered_violations,
        plan_digest=plan.plan_digest,
        authority_digest=problem.authority_digest,
        validation_digest=validation_digest,
        validation_wall_s=time.perf_counter() - started,
        summary=summary,
    )


__all__ = ["validate_final_selection"]
