"""Solver-independent support audits for final-selection diagnosis."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from dynamislm.benchmark.constants import SPLIT_ORDER
from dynamislm.benchmark.selection_contracts import (
    ConstraintKind,
    FeatureKind,
    FinalSelectionProblem,
    SelectionConstraint,
    SelectionConstraintSet,
)
from dynamislm.serialization import canonical_hash


def _support_ids(
    constraint: SelectionConstraint, problem: FinalSelectionProblem
) -> tuple[str, ...]:
    candidates = problem.candidates
    if constraint.kind is ConstraintKind.FINAL_COUNT:
        return tuple(item.candidate_id for item in candidates)
    if constraint.kind is ConstraintKind.SPLIT_COUNT:
        return tuple(item.candidate_id for item in candidates)
    if constraint.kind is ConstraintKind.FEATURE_MINIMUM:
        assert constraint.feature is not None
        return tuple(
            item.candidate_id for item in candidates if constraint.feature in item.features
        )
    if constraint.kind is ConstraintKind.ORIGIN_BOUNDS:
        assert constraint.origin_class is not None
        return tuple(
            item.candidate_id for item in candidates if item.origin_class is constraint.origin_class
        )
    if constraint.kind is ConstraintKind.MUTATION_LINEAGE_MINIMUM:
        return tuple(
            item.candidate_id for item in candidates if item.mutation_lineage_id is not None
        )
    return constraint.candidate_ids


def _forced_out_reasons(problem: FinalSelectionProblem) -> dict[str, tuple[str, ...]]:
    reasons: dict[str, set[str]] = {}
    candidates = {item.candidate_id: item for item in problem.candidates}
    parents = {item.candidate_id: item for item in problem.parent_provenance_registry}
    for constraint in problem.constraint_set.constraints:
        if constraint.kind in {
            ConstraintKind.REVIEW_OUT_ONLY,
            ConstraintKind.QUALIFICATION_OUT_ONLY,
        }:
            reasons.setdefault(constraint.candidate_ids[0], set()).add(constraint.constraint_id)
        elif constraint.kind is ConstraintKind.MUTATION_PARENT_PROVENANCE:
            candidate = candidates[constraint.candidate_ids[0]]
            parent = parents.get(constraint.related_id or "")
            if (
                candidate.mutation_parent_candidate_id != constraint.related_id
                or candidate.mutation_parent_payload_hash is None
                or constraint.related_payload_hash != candidate.mutation_parent_payload_hash
                or parent is None
                or parent.payload_hash != candidate.mutation_parent_payload_hash
            ):
                reasons.setdefault(candidate.candidate_id, set()).add(constraint.constraint_id)
        elif constraint.kind is ConstraintKind.MUTATION_PARENT_CELL_INHERITANCE:
            candidate = candidates[constraint.candidate_ids[0]]
            parent = parents.get(constraint.related_id or "")
            if (
                candidate.mutation_parent_candidate_id != constraint.related_id
                or constraint.reason != candidate.mutation_cell_exception_authority_ref
                or parent is None
                or (
                    candidate.cell != parent.cell
                    and candidate.mutation_cell_exception_authority_ref is None
                )
            ):
                reasons.setdefault(candidate.candidate_id, set()).add(constraint.constraint_id)
    return {
        candidate_id: tuple(sorted(ids, key=str.encode)) for candidate_id, ids in reasons.items()
    }


def selection_support_audit(problem: FinalSelectionProblem) -> tuple[dict[str, Any], ...]:
    """Measure local support without solving or changing selection authority."""

    by_id = {item.candidate_id: item for item in problem.candidates}
    forced_out = _forced_out_reasons(problem)
    rows: list[dict[str, Any]] = []
    for constraint in problem.constraint_set.constraints:
        support_ids = _support_ids(constraint, problem)
        support = tuple(by_id[candidate_id] for candidate_id in support_ids)
        selectable = tuple(item for item in support if item.candidate_id not in forced_out)
        if constraint.kind in {ConstraintKind.SPLIT_COUNT, ConstraintKind.FEATURE_MINIMUM}:
            assert constraint.split is not None
            lock_compatible = tuple(
                item
                for item in selectable
                if item.locked_split is None or item.locked_split is constraint.split
            )
        elif constraint.kind is ConstraintKind.CONDITIONAL_COLOCATION:
            lock_compatible = selectable
            per_split = tuple(
                sum(item.locked_split is None or item.locked_split is split for item in selectable)
                for split in SPLIT_ORDER
            )
            max_support = max(per_split, default=0)
        else:
            lock_compatible = selectable

        if constraint.kind is ConstraintKind.MUTATION_LINEAGE_MINIMUM:
            max_support = len(
                {
                    item.mutation_lineage_id
                    for item in lock_compatible
                    if item.mutation_lineage_id is not None
                }
            )
        elif constraint.kind is not ConstraintKind.CONDITIONAL_COLOCATION:
            max_support = len(lock_compatible)

        minimum = constraint.minimum
        unique_lineages = {
            item.mutation_lineage_id for item in support if item.mutation_lineage_id is not None
        }
        rows.append(
            {
                "constraint_id": constraint.constraint_id,
                "authority_ref": constraint.authority_ref,
                "kind": constraint.kind.value,
                "split": (
                    constraint.split.value
                    if constraint.split is not None
                    else (
                        None if constraint.locked_split is None else constraint.locked_split.value
                    )
                ),
                "locked_split": (
                    None if constraint.locked_split is None else constraint.locked_split.value
                ),
                "relation_kind": (
                    None if constraint.relation_kind is None else constraint.relation_kind.value
                ),
                "feature_kind": (
                    None if constraint.feature is None else constraint.feature.kind.value
                ),
                "feature_key": [] if constraint.feature is None else list(constraint.feature.key),
                "origin": None
                if constraint.origin_class is None
                else constraint.origin_class.value,
                "minimum": constraint.minimum,
                "maximum": constraint.maximum,
                "related_id": constraint.related_id,
                "related_payload_hash": constraint.related_payload_hash,
                "reason": constraint.reason,
                "raw_support_candidate_count": len(support),
                "maximum_support_compatible_with_split_locks": max_support,
                "forced_out_count": sum(item.candidate_id in forced_out for item in support),
                "unique_supporting_isolation_groups": len(
                    {item.isolation_cluster_id for item in support}
                ),
                "unique_mutation_lineages": len(unique_lineages),
                "individually_impossible": minimum is not None and max_support < minimum,
                "supporting_candidate_ids": list(support_ids),
                "forced_out_constraint_ids": sorted(
                    {
                        constraint_id
                        for candidate_id in support_ids
                        for constraint_id in forced_out.get(candidate_id, ())
                    },
                    key=str.encode,
                ),
                "lock_excluded_candidate_ids": sorted(
                    {
                        item.candidate_id
                        for item in selectable
                        if constraint.split is not None
                        and item.locked_split is not None
                        and item.locked_split is not constraint.split
                    },
                    key=str.encode,
                ),
            }
        )
    return tuple(rows)


def selection_support_audit_digest(rows: tuple[dict[str, Any], ...]) -> str:
    return canonical_hash(rows)


def selection_constraint_families(
    problem: FinalSelectionProblem,
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Return present hard-constraint families, keeping one-state constraints separate."""

    constraints = problem.constraint_set.constraints
    families: list[tuple[str, tuple[str, ...]]] = []
    groups: tuple[tuple[str, tuple[SelectionConstraint, ...]], ...] = (
        (
            "FINAL_COUNT",
            tuple(item for item in constraints if item.kind is ConstraintKind.FINAL_COUNT),
        ),
        (
            "SPLIT_COUNT",
            tuple(item for item in constraints if item.kind is ConstraintKind.SPLIT_COUNT),
        ),
        *(
            (
                f"FEATURE_MINIMUM:{feature_kind.value}",
                tuple(
                    item
                    for item in constraints
                    if item.kind is ConstraintKind.FEATURE_MINIMUM
                    and item.feature is not None
                    and item.feature.kind is feature_kind
                ),
            )
            for feature_kind in FeatureKind
        ),
        (
            "ORIGIN_BOUNDS",
            tuple(item for item in constraints if item.kind is ConstraintKind.ORIGIN_BOUNDS),
        ),
        (
            "MUTATION_LINEAGE_MINIMUM",
            tuple(
                item for item in constraints if item.kind is ConstraintKind.MUTATION_LINEAGE_MINIMUM
            ),
        ),
        (
            "SYNTHETIC_SPLIT_LOCK",
            tuple(item for item in constraints if item.kind is ConstraintKind.SYNTHETIC_SPLIT_LOCK),
        ),
        (
            "CONDITIONAL_COLOCATION / isolation",
            tuple(
                item for item in constraints if item.kind is ConstraintKind.CONDITIONAL_COLOCATION
            ),
        ),
        (
            "MUTATION_PARENT_PROVENANCE",
            tuple(
                item
                for item in constraints
                if item.kind is ConstraintKind.MUTATION_PARENT_PROVENANCE
            ),
        ),
        (
            "MUTATION_PARENT_CELL_INHERITANCE",
            tuple(
                item
                for item in constraints
                if item.kind is ConstraintKind.MUTATION_PARENT_CELL_INHERITANCE
            ),
        ),
        (
            "QUALIFICATION/ELIGIBILITY_FORCING",
            tuple(
                item
                for item in constraints
                if item.kind
                in {
                    ConstraintKind.REVIEW_OUT_ONLY,
                    ConstraintKind.QUALIFICATION_OUT_ONLY,
                }
            ),
        ),
    )
    for family_id, members in groups:
        if members:
            families.append(
                (
                    family_id,
                    tuple(sorted((item.constraint_id for item in members), key=str.encode)),
                )
            )
    return tuple(families)


def clone_selection_problem(
    problem: FinalSelectionProblem,
    constraints: Iterable[SelectionConstraint],
) -> FinalSelectionProblem:
    """Build a diagnostic-only exact view that bypasses constructor completeness checks."""

    retained = tuple(sorted(constraints, key=lambda item: item.constraint_id.encode("utf-8")))
    expected_one_state = {
        item.constraint_id
        for item in problem.constraint_set.constraints
        if item.kind is ConstraintKind.ONE_STATE_PER_CANDIDATE
    }
    retained_one_state = {
        item.constraint_id
        for item in retained
        if item.kind is ConstraintKind.ONE_STATE_PER_CANDIDATE
    }
    if retained_one_state != expected_one_state:
        raise ValueError("diagnostic problems must keep every one-state constraint active")
    ids = tuple(item.constraint_id for item in retained)
    if len(ids) != len(set(ids)):
        raise ValueError("diagnostic problem constraint IDs must be unique")

    # The public constructor intentionally rejects incomplete authority inventories. A
    # counterfactual must use the production solver/validator with selected IDs removed.
    clone = object.__new__(FinalSelectionProblem)
    object.__setattr__(clone, "candidates", problem.candidates)
    object.__setattr__(
        clone,
        "constraint_set",
        SelectionConstraintSet(
            constraints=retained,
            objectives=problem.constraint_set.objectives,
            allocation_clusters=problem.constraint_set.allocation_clusters,
        ),
    )
    object.__setattr__(clone, "authority_digest", problem.authority_digest)
    object.__setattr__(clone, "parent_provenance_registry", problem.parent_provenance_registry)
    return clone


__all__ = [
    "clone_selection_problem",
    "selection_constraint_families",
    "selection_support_audit",
    "selection_support_audit_digest",
]
