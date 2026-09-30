"""Semantic core-guided candidate-design diagnosis for RES-225."""

from __future__ import annotations

import hashlib
import itertools
import threading
import time
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any

from dynamislm.benchmark.constants import (
    CRITICAL_ERROR_CLASSES,
    CaseOrigin,
    ExpectedAnswerKind,
    RefusalDecision,
)
from dynamislm.benchmark.coverage import COVERAGE_MATRIX
from dynamislm.benchmark.production import (
    PROSPECTIVE_SPLIT_COUNTS,
    ProductionAuthoringPlanItemV1,
    ProductionCandidateCommitmentV1,
    ProductionExactFeasibilityReceiptV2,
    _cluster_has_c18_refusal,
    _cluster_has_cell_obligation,
    _exact_requirement_constraints,
    _feasibility_clusters,
    _feasibility_row_eligible,
    _FeasibilityCluster,
    _production_question_surface_variant_id,
    _row_by_capability,
    validate_production_exact_feasibility,
)
from dynamislm.serialization import canonical_hash, register_serializable_type

ORIGIN_BOUNDS = (
    (CaseOrigin.EXPERT_AUTHORED_SEMANTIC, 0, 240),
    (CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION, 40, None),
    (CaseOrigin.DETERMINISTIC_ENGINE_DERIVED, 30, None),
    (CaseOrigin.DETERMINISTIC_SYNTHETIC, 12, None),
    (CaseOrigin.ADVERSARIAL_MUTATION, 60, None),
)
_ACTION_PREFIX = "RES-225-ACTION:"


class CoreSolveTimeoutError(RuntimeError):
    pass


def solve_assumptions_limited(
    solver: Any,
    assumptions: tuple[int, ...] | list[int],
    *,
    deadline: float | None,
) -> bool:
    if deadline is None:
        return bool(solver.solve(assumptions=assumptions))
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise CoreSolveTimeoutError("semantic assumption solve exceeded its time budget")
    timer = threading.Timer(remaining, solver.interrupt)
    timer.daemon = True
    timer.start()
    try:
        result = solver.solve_limited(assumptions=assumptions, expect_interrupt=True)
    finally:
        timer.cancel()
        solver.clear_interrupt()
    if result is None:
        raise CoreSolveTimeoutError("semantic assumption solve exceeded its time budget")
    return bool(result)


@dataclass(frozen=True, slots=True)
class PreservationAssumption:
    assumption_id: str
    assumption_class: str
    candidate_ids: tuple[str, ...]
    current_origin: str
    current_cell: str
    component_key: str
    scientific_authority_dependencies: tuple[str, ...]
    release_requires_new_content: bool
    release_affects_mutation_descendants: bool
    action_id: str | None


@dataclass(frozen=True, slots=True)
class AbstractReplacementPlaceholder:
    candidate_id: str
    capability_id: str
    benchmark_family: str
    origin_class: str
    practitioner_question_class: str
    scoring_profile: str
    authority_class: str
    authority_kinds: tuple[str, ...]
    adversarial_tags: tuple[str, ...]
    reachable_errors: tuple[str, ...]
    refusal_decision: str
    expected_answer_kind: str
    safe_partial_support: bool
    difficulty: str
    expected_isolation_behavior: str
    authority_availability_proof: str


@dataclass(frozen=True, slots=True)
class RepairAction:
    action_id: str
    action_family: str
    anchor_candidate_id: str
    affected_candidate_ids: tuple[str, ...]
    content_replacement_count: int
    current_component_key: str
    new_author_batch_id: str
    new_protocol_template_id: str
    new_isolation_cluster_id: str
    placeholders: tuple[AbstractReplacementPlaceholder, ...]
    scientific_justification: str
    authority_eligibility_digest: str
    materialization_requirements: tuple[str, ...]
    target_parent_candidate_ids: tuple[str, ...] = ()
    target_lineage_id_by_parent: tuple[tuple[str, str], ...] = ()
    target_placeholders: tuple[AbstractReplacementPlaceholder, ...] = ()
    old_parent_candidate_id: str | None = None
    old_mutation_lineage_id: str | None = None
    mutation_operator_id: str | None = None


@dataclass(frozen=True, slots=True)
class CoreModel:
    mode: str
    clauses: tuple[tuple[int, ...], ...]
    max_variable: int
    candidate_ids: tuple[str, ...]
    assignment_variables: tuple[tuple[int, int, int], ...]
    release_variables: dict[str, int]
    target_variables: dict[str, dict[str, int]]
    assumption_literals: dict[str, int]
    assumption_action_ids: dict[str, str]
    action_ids_by_literal: dict[int, str]
    model_digest: str
    action_weights: dict[str, int]
    hard_constraint_digest: str


@register_serializable_type
@dataclass(frozen=True, slots=True)
class RES225RepairCheckpointV1:
    schema: str
    payload: Any


def _enum(value: object) -> str:
    return str(getattr(value, "value", value))


def _authority_dependencies(item: ProductionAuthoringPlanItemV1) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                *item.authority_kinds,
                *item.source_document_ids,
                *item.source_artifact_ids,
                *item.construct_test_identity_ids,
                *item.provider_export_ids,
                *item.protocol_template_ids,
            },
            key=lambda value: value.encode("utf-8"),
        )
    )


def _engine_reference(item: ProductionAuthoringPlanItemV1) -> str:
    return next(
        iter(
            item.construct_test_identity_ids
            or item.provider_export_ids
            or item.source_artifact_ids
            or item.authority_kinds
        ),
        "RES-71-AUTHORITY",
    )


def _semantic_role_signature(item: ProductionAuthoringPlanItemV1) -> tuple[object, ...]:
    return (
        _enum(item.scoring_profile),
        item.authority_class,
        tuple(item.authority_kinds),
    )


def _mutation_role_from_parent(
    current: ProductionAuthoringPlanItemV1,
    target: ProductionAuthoringPlanItemV1,
    *,
    target_parent_id: str,
    target_lineage_id: str,
    stage: int,
) -> ProductionAuthoringPlanItemV1:
    mutation_parent_kind = next(
        (kind for kind in current.authority_kinds if kind == "MUTATION_PARENT"),
        "MUTATION_PARENT",
    )
    return replace(
        current,
        recipe_id=target.recipe_id,
        recipe_version=target.recipe_version,
        capability_id=target.capability_id,
        benchmark_family=target.benchmark_family,
        practitioner_question_class=target.practitioner_question_class,
        scoring_profile=target.scoring_profile,
        authority_class=target.authority_class,
        authority_kinds=tuple(
            sorted(
                {*target.authority_kinds, mutation_parent_kind},
                key=lambda value: value.encode("utf-8"),
            )
        ),
        reachable_error_classes=target.reachable_error_classes,
        adversarial_tags=target.adversarial_tags,
        source_family_id=target.source_family_id,
        source_document_ids=target.source_document_ids,
        source_artifact_ids=target.source_artifact_ids,
        construct_test_identity_ids=target.construct_test_identity_ids,
        provider_export_ids=target.provider_export_ids,
        protocol_template_ids=target.protocol_template_ids,
        expert_author_batch_id=target.expert_author_batch_id,
        author_id=target.author_id,
        mutation_lineage_id=target_lineage_id,
        parent_candidate_id=target_parent_id,
        isolation_cluster_id=target.isolation_cluster_id,
        allocation_stratum=(f"{target.capability_id}:{target.benchmark_family}:MUTATION-{stage}"),
        refusal_decision=target.refusal_decision,
        expected_answer_kind=target.expected_answer_kind,
        safe_partial_support=target.safe_partial_support,
        question_surface_variant_id=_production_question_surface_variant_id(
            CaseOrigin.ADVERSARIAL_MUTATION,
            target.capability_id,
            target.benchmark_family,
        ),
    )


def _placeholder(item: ProductionAuthoringPlanItemV1) -> AbstractReplacementPlaceholder:
    if item.origin_class is CaseOrigin.EXPERT_AUTHORED_SEMANTIC:
        availability = f"frozen-recipe:{item.recipe_id}@{item.recipe_version}"
        isolation = "new-independent-expert-cluster"
    elif item.origin_class is CaseOrigin.ADVERSARIAL_MUTATION:
        availability = f"preserved-lineage:{item.mutation_lineage_id}"
        isolation = "new-cluster-with-original-parent-lineage"
    elif item.origin_class is CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION:
        availability = "current-phase-a-span-only; replacement-source-not-authorized"
        isolation = "source-evidence-bound"
    elif item.origin_class is CaseOrigin.DETERMINISTIC_ENGINE_DERIVED:
        availability = "current-res71-reference-only; replacement-operation-not-authorized"
        isolation = "res71-reference-bound"
    elif item.origin_class is CaseOrigin.DETERMINISTIC_SYNTHETIC:
        availability = "registered-generator-and-current-split-seed-lock"
        isolation = "generator-and-split-lock-bound"
    else:
        availability = "unavailable"
        isolation = "unavailable"
    return AbstractReplacementPlaceholder(
        candidate_id=item.candidate_id,
        capability_id=item.capability_id,
        benchmark_family=item.benchmark_family,
        origin_class=_enum(item.origin_class),
        practitioner_question_class=_enum(item.practitioner_question_class),
        scoring_profile=_enum(item.scoring_profile),
        authority_class=item.authority_class,
        authority_kinds=tuple(item.authority_kinds),
        adversarial_tags=tuple(item.adversarial_tags),
        reachable_errors=tuple(_enum(error) for error in item.reachable_error_classes),
        refusal_decision=_enum(item.refusal_decision),
        expected_answer_kind=_enum(item.expected_answer_kind),
        safe_partial_support=item.safe_partial_support,
        difficulty=_enum(item.difficulty),
        expected_isolation_behavior=isolation,
        authority_availability_proof=availability,
    )


def build_preservation_registry(
    commitments: tuple[ProductionCandidateCommitmentV1, ...],
    exact_shingle_colocation_pairs: tuple[tuple[str, str], ...],
    mutation_lineages: tuple[Any, ...] = (),
) -> tuple[tuple[PreservationAssumption, ...], tuple[RepairAction, ...]]:
    """Build stable semantic assumptions and typed role-preserving actions."""

    items = {entry.candidate_id: entry.item for entry in commitments}
    base_components = _feasibility_clusters(commitments, allow_incompatible_locks=True)
    colocation_components = _feasibility_clusters(
        commitments,
        exact_shingle_colocation_pairs=exact_shingle_colocation_pairs,
        allow_incompatible_locks=True,
    )
    component_key_by_candidate = {
        item.candidate_id: component.cluster_key
        for component in base_components
        for item in component.items
    }
    coloc_component_key_by_candidate = {
        item.candidate_id: component.cluster_key
        for component in colocation_components
        for item in component.items
    }
    children_by_parent: dict[str, list[str]] = defaultdict(list)
    for item in items.values():
        if item.parent_candidate_id is not None:
            children_by_parent[item.parent_candidate_id].append(item.candidate_id)

    def mutation_descendants(parent_id: str) -> tuple[str, ...]:
        pending = list(children_by_parent.get(parent_id, ()))
        descendants: set[str] = set()
        while pending:
            child_id = pending.pop()
            if child_id in descendants:
                continue
            descendants.add(child_id)
            pending.extend(children_by_parent.get(child_id, ()))
        return tuple(sorted(descendants, key=lambda value: value.encode("utf-8")))

    actions: list[RepairAction] = []
    action_by_candidate: dict[str, str] = {}
    for item in sorted(items.values(), key=lambda value: value.candidate_id.encode("utf-8")):
        if item.origin_class is not CaseOrigin.EXPERT_AUTHORED_SEMANTIC:
            continue
        descendants = mutation_descendants(item.candidate_id)
        if descendants:
            continue
        affected = (item.candidate_id, *descendants)
        action_payload = {
            "action_family": "EXPERT_SEMANTIC_CONTENT_REPLACEMENT",
            "anchor_candidate_id": item.candidate_id,
            "affected_candidate_ids": affected,
            "cell": (item.capability_id, item.benchmark_family),
            "role": _placeholder(item),
            "authority_dependencies": _authority_dependencies(item),
        }
        action_id = _ACTION_PREFIX + canonical_hash(action_payload).removeprefix("sha256:")[:24]
        suffix = action_id.rsplit(":", 1)[-1]
        action = RepairAction(
            action_id=action_id,
            action_family="EXPERT_SEMANTIC_CONTENT_REPLACEMENT",
            anchor_candidate_id=item.candidate_id,
            affected_candidate_ids=affected,
            content_replacement_count=len(affected),
            current_component_key=component_key_by_candidate[item.candidate_id],
            new_author_batch_id=f"PSE-V1-RES225-EXPERT-BATCH:{suffix}",
            new_protocol_template_id=f"PSE-V1-RES225-PROTOCOL-TEMPLATE:{suffix}",
            new_isolation_cluster_id=f"PSE-V1-RES225-SEMANTIC-CLUSTER:{suffix}",
            placeholders=tuple(_placeholder(items[candidate_id]) for candidate_id in affected),
            scientific_justification=(
                "Reauthor the expert-authored semantic slot from its existing frozen cell recipe, "
                "authority kinds, scoring profile, refusal role, error obligations, and tags; "
                "give it an independent deterministic scenario context. Mutation descendants, "
                "when present, are regenerated from the changed parent and retain their lineage."
            ),
            authority_eligibility_digest=canonical_hash(
                (item.recipe_id, item.recipe_version, _authority_dependencies(item))
            ),
            materialization_requirements=(
                "derive replacement scenario seed from the action ID",
                "split only the selected semantic slot from its expert batch",
                "regenerate only selected mutation descendants from the changed parent",
                "revalidate authority, lineage, contamination, and candidate hashes",
            ),
        )
        actions.append(action)
        for candidate_id in affected:
            if candidate_id in action_by_candidate:
                raise ValueError("RES-225 replacement actions overlap candidate slots")
            action_by_candidate[candidate_id] = action_id

    operator_capabilities = {
        "measurement-identity-trap": frozenset({"C01", "C03", "C04"}),
        "comparability-overreach": frozenset({"C07"}),
        "claim-boundary-overreach": frozenset({"C09", "C15"}),
        "safe-partial-refusal-trap": frozenset({"C18"}),
        "error-correction-trap": frozenset({"C17"}),
    }
    lineage_root_ids = {item.parent_candidate_id for item in mutation_lineages}
    for lineage in sorted(mutation_lineages, key=lambda item: item.lineage_id.encode("utf-8")):
        root_parent = items[lineage.parent_candidate_id]
        children = tuple(lineage.child_candidate_ids)
        allowed_capabilities = operator_capabilities.get(lineage.operator_id, frozenset())
        if root_parent.capability_id not in allowed_capabilities:
            raise ValueError("RES-225 mutation operator has no frozen capability compatibility map")
        target_parents = tuple(
            sorted(
                (
                    item
                    for item in items.values()
                    if item.candidate_id in lineage_root_ids
                    and item.candidate_id != lineage.parent_candidate_id
                    and item.origin_class is CaseOrigin.EXPERT_AUTHORED_SEMANTIC
                    and item.capability_id in allowed_capabilities
                    and CaseOrigin.ADVERSARIAL_MUTATION
                    in _row_by_capability(item.capability_id).case_origins
                    and _semantic_role_signature(item) == _semantic_role_signature(root_parent)
                    and component_key_by_candidate[item.candidate_id]
                    != component_key_by_candidate[lineage.parent_candidate_id]
                ),
                key=lambda item: (
                    len(
                        next(
                            c.items
                            for c in base_components
                            if item.candidate_id in {x.candidate_id for x in c.items}
                        )
                    ),
                    item.candidate_id.encode("utf-8"),
                ),
            )
        )
        if not target_parents:
            continue
        target_ids = tuple(item.candidate_id for item in target_parents)
        target_lineage_ids = tuple(
            (
                item.candidate_id,
                "PSE-V1-MUTATION-LINEAGE:"
                + canonical_hash(
                    (lineage.lineage_id, children, item.candidate_id, lineage.operator_id)
                ).removeprefix("sha256:")[:20],
            )
            for item in target_parents
        )
        target_lineage_by_parent = dict(target_lineage_ids)
        target_placeholders = tuple(
            _placeholder(
                _mutation_role_from_parent(
                    items[child_id],
                    parent,
                    target_parent_id=(parent.candidate_id if stage == 1 else children[stage - 2]),
                    target_lineage_id=target_lineage_by_parent[parent.candidate_id],
                    stage=stage,
                )
            )
            for parent in target_parents
            for stage, child_id in enumerate(children, start=1)
        )
        action_payload = {
            "action_family": "MUTATION_BRANCH_REPARENT",
            "lineage_id": lineage.lineage_id,
            "old_parent_candidate_id": lineage.parent_candidate_id,
            "child_candidate_ids": children,
            "target_parent_candidate_ids": target_ids,
            "operator_id": lineage.operator_id,
            "compatible_role_digest": canonical_hash(_semantic_role_signature(root_parent)),
        }
        action_id = _ACTION_PREFIX + canonical_hash(action_payload).removeprefix("sha256:")[:24]
        suffix = action_id.rsplit(":", 1)[-1]
        action = RepairAction(
            action_id=action_id,
            action_family="MUTATION_BRANCH_REPARENT",
            anchor_candidate_id=children[0],
            affected_candidate_ids=children,
            content_replacement_count=len(children),
            current_component_key=component_key_by_candidate[lineage.parent_candidate_id],
            new_author_batch_id=f"PARENT-BOUND:{suffix}",
            new_protocol_template_id=f"PARENT-BOUND:{suffix}",
            new_isolation_cluster_id=f"PARENT-BOUND:{suffix}",
            placeholders=tuple(_placeholder(items[child_id]) for child_id in children),
            scientific_justification=(
                "Reauthor the complete mutation-descendant branch from one registered compatible "
                "expert parent; preserve mutation count, operator, authority lineage, and the "
                "stage-ordered parent/child chain."
            ),
            authority_eligibility_digest=canonical_hash(
                (
                    lineage.lineage_id,
                    lineage.operator_id,
                    _semantic_role_signature(root_parent),
                    tuple(
                        (item.candidate_id, _authority_dependencies(item))
                        for item in target_parents
                    ),
                )
            ),
            materialization_requirements=(
                "select one registered compatible expert parent",
                "move all three descendants to one new mutation lineage",
                "remove the emptied old lineage record",
                "regenerate descendants topologically and revalidate each scientific delta",
            ),
            target_parent_candidate_ids=target_ids,
            target_lineage_id_by_parent=target_lineage_ids,
            target_placeholders=target_placeholders,
            old_parent_candidate_id=lineage.parent_candidate_id,
            old_mutation_lineage_id=lineage.lineage_id,
            mutation_operator_id=lineage.operator_id,
        )
        actions.append(action)
        for child_id in children:
            if child_id in action_by_candidate:
                raise ValueError("RES-225 mutation branch action overlaps another candidate action")
            action_by_candidate[child_id] = action_id

    assumptions: list[PreservationAssumption] = []
    for candidate_id, item in sorted(items.items(), key=lambda pair: pair[0].encode("utf-8")):
        owner = action_by_candidate.get(candidate_id)
        dependencies = _authority_dependencies(item)
        current_component = component_key_by_candidate[candidate_id]
        assumptions.append(
            PreservationAssumption(
                assumption_id=f"KEEP_CANDIDATE_SLOT:{candidate_id}",
                assumption_class="CANDIDATE_SLOT",
                candidate_ids=(candidate_id,),
                current_origin=_enum(item.origin_class),
                current_cell=f"{item.capability_id}:{item.benchmark_family}",
                component_key=current_component,
                scientific_authority_dependencies=dependencies,
                release_requires_new_content=True,
                release_affects_mutation_descendants=bool(children_by_parent.get(candidate_id)),
                action_id=owner,
            )
        )
        if item.origin_class is CaseOrigin.EXPERT_AUTHORED_SEMANTIC:
            assumptions.append(
                PreservationAssumption(
                    assumption_id=(
                        f"KEEP_SEMANTIC_SLOT:{candidate_id}:{item.capability_id}:"
                        f"{item.benchmark_family}"
                    ),
                    assumption_class="SEMANTIC_SLOT_ASSIGNMENT",
                    candidate_ids=(candidate_id,),
                    current_origin=_enum(item.origin_class),
                    current_cell=f"{item.capability_id}:{item.benchmark_family}",
                    component_key=current_component,
                    scientific_authority_dependencies=dependencies,
                    release_requires_new_content=True,
                    release_affects_mutation_descendants=bool(children_by_parent.get(candidate_id)),
                    action_id=owner,
                )
            )
        elif item.origin_class is CaseOrigin.ADVERSARIAL_MUTATION:
            assumptions.append(
                PreservationAssumption(
                    assumption_id=f"KEEP_MUTATION_CHILD:{candidate_id}",
                    assumption_class="MUTATION_CHILD",
                    candidate_ids=(candidate_id,),
                    current_origin=_enum(item.origin_class),
                    current_cell=f"{item.capability_id}:{item.benchmark_family}",
                    component_key=current_component,
                    scientific_authority_dependencies=dependencies,
                    release_requires_new_content=True,
                    release_affects_mutation_descendants=False,
                    action_id=owner,
                )
            )
        elif item.origin_class is CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION:
            assumptions.append(
                PreservationAssumption(
                    assumption_id=(
                        f"KEEP_SOURCE_SLOT:{candidate_id}:{item.source_family_id}:"
                        f"{item.capability_id}:{item.benchmark_family}"
                    ),
                    assumption_class="SOURCE_SLOT",
                    candidate_ids=(candidate_id,),
                    current_origin=_enum(item.origin_class),
                    current_cell=f"{item.capability_id}:{item.benchmark_family}",
                    component_key=current_component,
                    scientific_authority_dependencies=dependencies,
                    release_requires_new_content=True,
                    release_affects_mutation_descendants=False,
                    action_id=None,
                )
            )
        elif item.origin_class is CaseOrigin.DETERMINISTIC_ENGINE_DERIVED:
            assumptions.append(
                PreservationAssumption(
                    assumption_id=(
                        f"KEEP_ENGINE_SLOT:{candidate_id}:{_engine_reference(item)}:"
                        f"{item.capability_id}:{item.benchmark_family}"
                    ),
                    assumption_class="ENGINE_SLOT",
                    candidate_ids=(candidate_id,),
                    current_origin=_enum(item.origin_class),
                    current_cell=f"{item.capability_id}:{item.benchmark_family}",
                    component_key=current_component,
                    scientific_authority_dependencies=dependencies,
                    release_requires_new_content=True,
                    release_affects_mutation_descendants=False,
                    action_id=None,
                )
            )
    lineages = {
        (item.mutation_lineage_id, item.parent_candidate_id)
        for item in items.values()
        if item.mutation_lineage_id is not None and item.parent_candidate_id is not None
    }
    for lineage_id, parent_id in sorted(lineages):
        parent = items[parent_id]
        child_id = next(
            candidate_id
            for candidate_id, item in items.items()
            if item.mutation_lineage_id == lineage_id and item.parent_candidate_id == parent_id
        )
        relation_action_id = action_by_candidate.get(child_id)
        relation_action = next(
            (action for action in actions if action.action_id == relation_action_id),
            None,
        )
        if (
            relation_action is not None
            and relation_action.action_family == "MUTATION_BRANCH_REPARENT"
            and parent_id != relation_action.old_parent_candidate_id
        ):
            relation_action_id = None
        assumptions.append(
            PreservationAssumption(
                assumption_id=f"KEEP_MUTATION_PARENT:{lineage_id}:{parent_id}",
                assumption_class="MUTATION_PARENT_RELATION",
                candidate_ids=(parent_id, child_id),
                current_origin=_enum(parent.origin_class),
                current_cell=f"{parent.capability_id}:{parent.benchmark_family}",
                component_key=component_key_by_candidate[parent_id],
                scientific_authority_dependencies=_authority_dependencies(parent),
                release_requires_new_content=False,
                release_affects_mutation_descendants=False,
                action_id=relation_action_id,
            )
        )
    assumptions_tuple = tuple(
        sorted(assumptions, key=lambda item: item.assumption_id.encode("utf-8"))
    )
    if len({item.assumption_id for item in assumptions_tuple}) != len(assumptions_tuple):
        raise ValueError("RES-225 semantic preservation assumption IDs are not unique")
    expected_actions = {
        item.candidate_id
        for item in items.values()
        if item.origin_class is CaseOrigin.EXPERT_AUTHORED_SEMANTIC
        and not mutation_descendants(item.candidate_id)
    } | {
        action.anchor_candidate_id
        for action in actions
        if action.action_family == "MUTATION_BRANCH_REPARENT"
    }
    if {action.anchor_candidate_id for action in actions} != expected_actions:
        raise ValueError("RES-225 action registry differs from its authorized candidate slots")
    if any(
        action.current_component_key != component_key_by_candidate[action.anchor_candidate_id]
        for action in actions
    ):
        raise ValueError("RES-225 repair action is stale against its current base component")
    if not coloc_component_key_by_candidate:
        raise ValueError("RES-225 action registry is missing the retained co-location graph")
    return assumptions_tuple, tuple(
        sorted(actions, key=lambda item: item.action_id.encode("utf-8"))
    )


class _CNFBuilder:
    def __init__(self, clauses: list[list[int]], top_id: int) -> None:
        self.clauses = clauses
        self.top_id = top_id

    def fresh(self) -> int:
        self.top_id += 1
        return self.top_id

    def add_and(self, literals: tuple[int, ...] | list[int]) -> int:
        variable = self.fresh()
        if not literals:
            self.clauses.append([-variable])
            return variable
        self.clauses.extend([[-variable, literal] for literal in literals])
        self.clauses.append([variable, *(-literal for literal in literals)])
        return variable

    def add_or(self, literals: tuple[int, ...] | list[int]) -> int:
        variable = self.fresh()
        if not literals:
            self.clauses.append([-variable])
            return variable
        self.clauses.extend([[-literal, variable] for literal in literals])
        self.clauses.append([-variable, *literals])
        return variable

    def add_pb(
        self,
        literals: list[int],
        weights: list[int],
        *,
        lower: int | None,
        upper: int | None,
    ) -> None:
        from pysat.pb import EncType, PBEnc  # type: ignore[import-untyped]

        if not literals:
            if (lower is not None and lower > 0) or (upper is not None and upper < 0):
                self.clauses.append([])
            return
        if any(weight <= 0 for weight in weights):
            raise ValueError("RES-225 candidate PB weights must be positive")
        if lower is not None and lower == upper:
            encoded = PBEnc.equals(
                lits=literals,
                weights=weights,
                bound=lower,
                top_id=self.top_id,
                encoding=EncType.bdd,
            )
            self.clauses.extend([list(clause) for clause in encoded.clauses])
            self.top_id = max(self.top_id, encoded.nv)
            return
        if lower is not None:
            encoded = PBEnc.geq(
                lits=literals,
                weights=weights,
                bound=lower,
                top_id=self.top_id,
                encoding=EncType.bdd,
            )
            self.clauses.extend([list(clause) for clause in encoded.clauses])
            self.top_id = max(self.top_id, encoded.nv)
        if upper is not None:
            encoded = PBEnc.leq(
                lits=literals,
                weights=weights,
                bound=upper,
                top_id=self.top_id,
                encoding=EncType.bdd,
            )
            self.clauses.extend([list(clause) for clause in encoded.clauses])
            self.top_id = max(self.top_id, encoded.nv)


def _add_equal_assignment(
    clauses: list[list[int]],
    left: tuple[int, int, int],
    right: tuple[int, int, int],
    relax_literals: tuple[int, ...] = (),
) -> None:
    for rank in range(3):
        clauses.append([*relax_literals, -left[rank], right[rank]])
        clauses.append([*relax_literals, left[rank], -right[rank]])


def build_core_model(
    commitments: tuple[ProductionCandidateCommitmentV1, ...],
    exact_shingle_colocation_pairs: tuple[tuple[str, str], ...],
    assumptions: tuple[PreservationAssumption, ...],
    actions: tuple[RepairAction, ...],
    *,
    mode: str,
    include_critical: bool = True,
    included_obligation_prefixes: frozenset[str] | None = None,
) -> CoreModel:
    """Encode hard allocation contracts with finite, typed reparent alternatives."""

    if mode not in {"BASE", "COLOCATION"}:
        raise ValueError("RES-225 core model mode is invalid")
    commitments = tuple(sorted(commitments, key=lambda item: item.candidate_id.encode("utf-8")))
    items = {entry.candidate_id: entry.item for entry in commitments}
    candidate_index = {candidate_id: index for index, candidate_id in enumerate(items)}
    if len(items) != 434:
        raise ValueError("RES-225 core model requires exactly 434 candidate slots")
    actions = tuple(sorted(actions, key=lambda item: item.action_id.encode("utf-8")))
    action_by_id = {action.action_id: action for action in actions}
    action_by_candidate = {
        candidate_id: action.action_id
        for action in actions
        for candidate_id in action.affected_candidate_ids
    }
    if len(action_by_candidate) != sum(len(action.affected_candidate_ids) for action in actions):
        raise ValueError("RES-225 actions overlap candidate slots")

    assignment_variables = tuple(
        (3 * index + 1, 3 * index + 2, 3 * index + 3) for index in range(len(items))
    )
    release_variables = {
        action.action_id: 3 * len(items) + index + 1 for index, action in enumerate(actions)
    }
    next_variable = 3 * len(items) + len(actions)
    target_variables: dict[str, dict[str, int]] = {}
    for action in actions:
        if action.action_family != "MUTATION_BRANCH_REPARENT":
            continue
        target_variables[action.action_id] = {}
        for target_id in action.target_parent_candidate_ids:
            next_variable += 1
            target_variables[action.action_id][target_id] = next_variable

    releasable_assumptions = tuple(item for item in assumptions if item.action_id is not None)
    assumption_literals = {
        item.assumption_id: next_variable + index + 1
        for index, item in enumerate(releasable_assumptions)
    }
    assumption_action_ids = {
        item.assumption_id: item.action_id or "" for item in releasable_assumptions
    }
    action_ids_by_literal = {
        release_variables[action_id]: action_id for action_id in release_variables
    }
    clauses: list[list[int]] = []
    builder = _CNFBuilder(clauses, next_variable + len(assumption_literals))
    for assignment in assignment_variables:
        clauses.append(list(assignment))
        clauses.extend(
            [-assignment[left], -assignment[right]]
            for left, right in itertools.combinations(range(3), 2)
        )
    for assumption_id, selector in assumption_literals.items():
        release = release_variables[assumption_action_ids[assumption_id]]
        clauses.extend(([selector, release], [-selector, -release]))
    for action_id, target_by_id in target_variables.items():
        release = release_variables[action_id]
        targets = tuple(target_by_id.values())
        clauses.append([-release, *targets])
        clauses.extend([-target, release] for target in targets)
        clauses.extend([-left, -right] for left, right in itertools.combinations(targets, 2))

    origin_counts = Counter(item.origin_class for item in items.values())
    if len(items) != 434 or any(
        origin_counts[origin] < minimum or (maximum is not None and origin_counts[origin] > maximum)
        for origin, minimum, maximum in ORIGIN_BOUNDS
    ):
        clauses.append([])

    singleton_components = tuple(
        _FeasibilityCluster(
            isolation_cluster_id=item.isolation_cluster_id,
            items=(item,),
            cluster_key=item.candidate_id,
            preferred_rank=0,
            locked_rank=None,
        )
        for item in items.values()
    )
    static_constraints = tuple(
        constraint
        for constraint in _exact_requirement_constraints(
            singleton_components,
            singleton_components,
        )
        if constraint.group_id.startswith(("COUNT:", "SYNTHETIC_LOCK:"))
    )
    for constraint in static_constraints:
        literals = [
            assignment_variables[index][rank] for index, rank, _coefficient in constraint.terms
        ]
        weights = [coefficient for _index, _rank, coefficient in constraint.terms]
        builder.add_pb(
            literals,
            weights,
            lower=constraint.lower,
            upper=constraint.upper,
        )

    members_by_isolation: dict[str, list[str]] = defaultdict(list)
    for item in items.values():
        members_by_isolation[item.isolation_cluster_id].append(item.candidate_id)
    role_options: dict[
        str,
        tuple[tuple[ProductionAuthoringPlanItemV1, int | None, str], ...],
    ] = {}
    for candidate_id, item in items.items():
        candidate_action_id = action_by_candidate.get(candidate_id)
        candidate_action = (
            action_by_id[candidate_action_id] if candidate_action_id is not None else None
        )
        if candidate_action is None:
            role_options[candidate_id] = ((item, None, item.isolation_cluster_id),)
            continue
        if candidate_action.action_family == "EXPERT_SEMANTIC_CONTENT_REPLACEMENT":
            release = release_variables[candidate_action.action_id]
            replacement = replace(
                item,
                isolation_cluster_id=candidate_action.new_isolation_cluster_id,
                expert_author_batch_id=candidate_action.new_author_batch_id,
                protocol_template_ids=(candidate_action.new_protocol_template_id,),
            )
            role_options[candidate_id] = (
                (item, -release, item.isolation_cluster_id),
                (replacement, release, replacement.isolation_cluster_id),
            )
            continue
        if candidate_action.action_family != "MUTATION_BRANCH_REPARENT":
            raise ValueError("RES-225 action family has no finite role-option encoding")
        release = release_variables[candidate_action.action_id]
        mutation_role_options: list[tuple[ProductionAuthoringPlanItemV1, int | None, str]] = [
            (item, -release, item.isolation_cluster_id)
        ]
        for target_id, target_literal in target_variables[candidate_action.action_id].items():
            target = items[target_id]
            parent_id = target_id
            lineage_id = dict(candidate_action.target_lineage_id_by_parent)[target_id]
            for stage, child_id in enumerate(candidate_action.affected_candidate_ids, start=1):
                if child_id != candidate_id:
                    continue
                parent_id = (
                    target_id if stage == 1 else candidate_action.affected_candidate_ids[stage - 2]
                )
                role = _mutation_role_from_parent(
                    item,
                    target,
                    target_parent_id=parent_id,
                    target_lineage_id=lineage_id,
                    stage=stage,
                )
                mutation_role_options.append((role, target_literal, target.isolation_cluster_id))
        role_options[candidate_id] = tuple(mutation_role_options)

    def role_assignment(candidate_id: str, rank: int, selector: int | None) -> int:
        assigned = assignment_variables[candidate_index[candidate_id]][rank]
        return assigned if selector is None else builder.add_and((assigned, selector))

    def row_cell_eligible(item: ProductionAuthoringPlanItemV1, row: Any, family: str) -> bool:
        return _cluster_has_cell_obligation(
            _FeasibilityCluster(
                isolation_cluster_id=item.isolation_cluster_id,
                items=(item,),
                cluster_key=item.candidate_id,
                preferred_rank=0,
                locked_rank=None,
            ),
            row,
            family,
        )

    def require_one(literals: list[int]) -> None:
        builder.add_pb(literals, [1] * len(literals), lower=1, upper=None)

    def include_obligation(prefix: str) -> bool:
        return included_obligation_prefixes is None or prefix in included_obligation_prefixes

    for rank, _split_target in enumerate(PROSPECTIVE_SPLIT_COUNTS):
        if include_obligation("ANSWERABLE:"):
            require_one(
                [
                    role_assignment(candidate_id, rank, selector)
                    for candidate_id, available_roles in role_options.items()
                    for role, selector, _destination in available_roles
                    if role.refusal_decision is not RefusalDecision.REQUIRED
                    and role.expected_answer_kind is not ExpectedAnswerKind.REFUSAL
                ]
            )
        for row in COVERAGE_MATRIX:
            if include_obligation("CELL:"):
                for family in row.benchmark_families:
                    require_one(
                        [
                            role_assignment(candidate_id, rank, selector)
                            for candidate_id, available_roles in role_options.items()
                            for role, selector, _destination in available_roles
                            if row_cell_eligible(role, row, family)
                        ]
                    )
            if include_obligation("ROW_TAG:"):
                for tag in row.adversarial_tags:
                    require_one(
                        [
                            role_assignment(candidate_id, rank, selector)
                            for candidate_id, available_roles in role_options.items()
                            for role, selector, _destination in available_roles
                            if _feasibility_row_eligible(role, row) and tag in role.adversarial_tags
                        ]
                    )
            if include_obligation("ROW_ERROR:"):
                for error in row.error_classes:
                    require_one(
                        [
                            role_assignment(candidate_id, rank, selector)
                            for candidate_id, available_roles in role_options.items()
                            for role, selector, _destination in available_roles
                            if _feasibility_row_eligible(role, row)
                            and error in role.reachable_error_classes
                        ]
                    )
        c18_row = _row_by_capability("C18")
        if include_obligation("C18_REFUSAL:"):
            for family in c18_row.benchmark_families:
                require_one(
                    [
                        role_assignment(candidate_id, rank, selector)
                        for candidate_id, available_roles in role_options.items()
                        for role, selector, _destination in available_roles
                        if _cluster_has_c18_refusal(
                            _FeasibilityCluster(
                                isolation_cluster_id=role.isolation_cluster_id,
                                items=(role,),
                                cluster_key=role.candidate_id,
                                preferred_rank=0,
                                locked_rank=None,
                            ),
                            family,
                        )
                    ]
                )

    # Existing atomic groups and the old parent edge remain hard while kept.
    for members in members_by_isolation.values():
        for left_id, right_id in itertools.combinations(
            sorted(members, key=lambda value: value.encode("utf-8")), 2
        ):
            isolation_relax = tuple(
                sorted(
                    {
                        release_variables[action_by_candidate[candidate_id]]
                        for candidate_id in (left_id, right_id)
                        if candidate_id in action_by_candidate
                    }
                )
            )
            _add_equal_assignment(
                clauses,
                assignment_variables[candidate_index[left_id]],
                assignment_variables[candidate_index[right_id]],
                isolation_relax,
            )
    for item in items.values():
        if item.parent_candidate_id is None:
            continue
        parent_action_id = action_by_candidate.get(item.candidate_id)
        parent_action = action_by_id[parent_action_id] if parent_action_id is not None else None
        parent_relax: tuple[int, ...] = ()
        if (
            parent_action_id is not None
            and parent_action is not None
            and parent_action.action_family == "MUTATION_BRANCH_REPARENT"
            and item.candidate_id == parent_action.affected_candidate_ids[0]
        ):
            parent_relax = (release_variables[parent_action_id],)
        _add_equal_assignment(
            clauses,
            assignment_variables[candidate_index[item.candidate_id]],
            assignment_variables[candidate_index[item.parent_candidate_id]],
            parent_relax,
        )
    for action in actions:
        if action.action_family == "MUTATION_BRANCH_REPARENT":
            for target_id, target_literal in target_variables[action.action_id].items():
                parent_id = target_id
                for child_id in action.affected_candidate_ids:
                    _add_equal_assignment(
                        clauses,
                        assignment_variables[candidate_index[child_id]],
                        assignment_variables[candidate_index[parent_id]],
                        (-target_literal,),
                    )
                    parent_id = child_id

    coloc_edges = exact_shingle_colocation_pairs if mode == "COLOCATION" else ()
    for left_id, right_id in coloc_edges:
        relax = tuple(
            sorted(
                {
                    release_variables[action_by_candidate[candidate_id]]
                    for candidate_id in (left_id, right_id)
                    if candidate_id in action_by_candidate
                }
            )
        )
        _add_equal_assignment(
            clauses,
            assignment_variables[candidate_index[left_id]],
            assignment_variables[candidate_index[right_id]],
            relax,
        )

    base_nodes = {("BASE", isolation_id) for isolation_id in members_by_isolation}
    action_nodes = {
        ("ACTION", action.action_id)
        for action in actions
        if action.action_family == "EXPERT_SEMANTIC_CONTENT_REPLACEMENT"
    }
    nodes = tuple(sorted(base_nodes | action_nodes))
    for rank in (1, 2):
        for error in CRITICAL_ERROR_CLASSES if include_critical else ():
            side_by_node = {node: builder.fresh() for node in nodes}
            critical_terms_by_node: dict[tuple[str, str], list[int]] = {node: [] for node in nodes}
            for candidate_id, candidate_role_options in role_options.items():
                critical_action_id = action_by_candidate.get(candidate_id)
                critical_action = (
                    action_by_id[critical_action_id] if critical_action_id is not None else None
                )
                for (
                    critical_role,
                    critical_selector,
                    critical_destination,
                ) in candidate_role_options:
                    if not (
                        _feasibility_row_eligible(
                            critical_role,
                            _row_by_capability(critical_role.capability_id),
                        )
                        and error in critical_role.reachable_error_classes
                    ):
                        continue
                    if (
                        critical_action is not None
                        and critical_action.action_family == "EXPERT_SEMANTIC_CONTENT_REPLACEMENT"
                    ):
                        release = release_variables[critical_action.action_id]
                        location = (
                            ("BASE", critical_destination)
                            if critical_selector == -release
                            else ("ACTION", critical_action.action_id)
                        )
                        selected_literal = -release if critical_selector == -release else release
                        term = builder.add_and(
                            (
                                assignment_variables[candidate_index[candidate_id]][rank],
                                selected_literal,
                            )
                        )
                    else:
                        location = ("BASE", critical_destination)
                        term = role_assignment(candidate_id, rank, critical_selector)
                    critical_terms_by_node[location].append(term)
            left_terms: list[int] = []
            right_terms: list[int] = []
            for node in nodes:
                critical = builder.add_or(critical_terms_by_node[node])
                left_terms.append(builder.add_and((critical, -side_by_node[node])))
                right_terms.append(builder.add_and((critical, side_by_node[node])))
            clauses.extend((left_terms, right_terms))
            if mode == "COLOCATION":
                for left_id, right_id in coloc_edges:
                    left_component = items[left_id].isolation_cluster_id
                    right_component = items[right_id].isolation_cluster_id
                    if left_component == right_component:
                        continue
                    relax = tuple(
                        sorted(
                            {
                                release_variables[action_by_candidate[candidate_id]]
                                for candidate_id in (left_id, right_id)
                                if candidate_id in action_by_candidate
                            }
                        )
                    )
                    side_left = side_by_node[("BASE", left_component)]
                    side_right = side_by_node[("BASE", right_component)]
                    clauses.extend(
                        (
                            [*relax, -side_left, side_right],
                            [*relax, side_left, -side_right],
                        )
                    )

    hard_digest = canonical_hash(
        {
            "static_requirement_constraints": tuple(
                (item.group_id, item.terms, item.lower, item.upper, item.equalities)
                for item in static_constraints
            ),
            "dynamic_role_domains": tuple(
                (
                    candidate_id,
                    tuple(
                        (
                            role.capability_id,
                            role.benchmark_family,
                            role.adversarial_tags,
                            role.reachable_error_classes,
                        )
                        for role, _selector, _destination in candidate_role_options
                    ),
                )
                for candidate_id, candidate_role_options in role_options.items()
            ),
            "origin_bounds": tuple(
                (_enum(origin), lower, upper) for origin, lower, upper in ORIGIN_BOUNDS
            ),
            "critical_error_classes": tuple(_enum(error) for error in CRITICAL_ERROR_CLASSES),
            "retained_shingle_edges": coloc_edges,
        }
    )
    canonical_clauses = tuple(
        sorted(
            (tuple(clause) for clause in clauses),
            key=lambda clause: (len(clause), clause),
        )
    )
    dimacs = f"p cnf {builder.top_id} {len(canonical_clauses)}\n" + "".join(
        " ".join(map(str, clause)) + (" " if clause else "") + "0\n" for clause in canonical_clauses
    )
    model_digest = "sha256:" + hashlib.sha256(dimacs.encode("ascii")).hexdigest()
    return CoreModel(
        mode=mode,
        clauses=canonical_clauses,
        max_variable=builder.top_id,
        candidate_ids=tuple(items),
        assignment_variables=assignment_variables,
        release_variables=release_variables,
        target_variables=target_variables,
        assumption_literals=assumption_literals,
        assumption_action_ids=assumption_action_ids,
        action_ids_by_literal=action_ids_by_literal,
        model_digest=model_digest,
        action_weights={action.action_id: action.content_replacement_count for action in actions},
        hard_constraint_digest=hard_digest,
    )


def shrink_unsat_core(
    solver: Any,
    model: CoreModel,
    assumption_ids: tuple[str, ...],
    *,
    forced_literals: tuple[int, ...] = (),
    deadline: float | None = None,
    max_checks: int | None = 8,
) -> tuple[str, ...]:
    """Deterministically reduce a valid semantic core with bounded SAT checks."""

    if max_checks is not None and max_checks < 0:
        raise ValueError("core reduction check limit cannot be negative")
    core = list(sorted(set(assumption_ids), key=lambda value: value.encode("utf-8")))
    if solve_assumptions_limited(
        solver,
        [*forced_literals, *(model.assumption_literals[item] for item in core)],
        deadline=deadline,
    ):
        raise ValueError("RES-225 attempted to shrink a satisfiable assumption set")
    checks = 0
    for assumption_id in tuple(core):
        if max_checks is not None and checks >= max_checks:
            break
        trial = [item for item in core if item != assumption_id]
        checks += 1
        if not solve_assumptions_limited(
            solver,
            [*forced_literals, *(model.assumption_literals[item] for item in trial)],
            deadline=deadline,
        ):
            core = trial
    result = tuple(core)
    if solve_assumptions_limited(
        solver,
        [*forced_literals, *(model.assumption_literals[item] for item in result)],
        deadline=deadline,
    ):
        raise ValueError("RES-225 reduced core failed its UNSAT recheck")
    return result


def semantic_core_action_ids(
    core_assumption_ids: tuple[str, ...],
    assumption_action_ids: dict[str, str],
) -> tuple[str, ...]:
    try:
        actions = {assumption_action_ids[item] for item in core_assumption_ids}
    except KeyError as exc:
        raise ValueError("RES-225 UNSAT core contains a non-semantic assumption ID") from exc
    if not actions or "" in actions:
        raise ValueError("RES-225 UNSAT core has no authorized candidate-design release action")
    return tuple(sorted(actions, key=lambda value: value.encode("utf-8")))


def assumptions_for_repair(
    model: CoreModel, selected_action_ids: tuple[str, ...]
) -> tuple[int, ...]:
    selected = set(selected_action_ids)
    keep_literals = tuple(
        model.assumption_literals[assumption_id]
        for assumption_id, owner in sorted(
            model.assumption_action_ids.items(), key=lambda item: item[0].encode("utf-8")
        )
        if owner not in selected
    )
    release_literals = tuple(
        model.release_variables[action_id]
        for action_id in sorted(selected, key=lambda value: value.encode("utf-8"))
    )
    return (*keep_literals, *release_literals)


def make_abstract_design(
    commitments: tuple[ProductionCandidateCommitmentV1, ...],
    exact_shingle_colocation_pairs: tuple[tuple[str, str], ...],
    actions: tuple[RepairAction, ...],
    selected_action_ids: tuple[str, ...],
    target_parent_by_action: dict[str, str] | None = None,
) -> tuple[tuple[ProductionCandidateCommitmentV1, ...], tuple[tuple[str, str], ...]]:
    """Instantiate typed placeholders without authoring question or answer text."""

    action_by_id = {item.action_id: item for item in actions}
    if len(set(selected_action_ids)) != len(selected_action_ids) or not set(
        selected_action_ids
    ) <= set(action_by_id):
        raise ValueError("RES-225 selected repair names an unknown or duplicate action")
    change_by_candidate: dict[str, RepairAction] = {}
    for action_id in selected_action_ids:
        action = action_by_id[action_id]
        for candidate_id in action.affected_candidate_ids:
            if candidate_id in change_by_candidate:
                raise ValueError("RES-225 selected repair overlaps candidate content slots")
            change_by_candidate[candidate_id] = action
    target_parent_by_action = target_parent_by_action or {}
    items_by_id = {entry.candidate_id: entry.item for entry in commitments}
    updated_items = dict(items_by_id)
    for action_id in selected_action_ids:
        action = action_by_id[action_id]
        if action.action_family == "EXPERT_SEMANTIC_CONTENT_REPLACEMENT":
            updated_items[action.anchor_candidate_id] = replace(
                updated_items[action.anchor_candidate_id],
                isolation_cluster_id=action.new_isolation_cluster_id,
                expert_author_batch_id=action.new_author_batch_id,
                protocol_template_ids=(action.new_protocol_template_id,),
            )
    for action_id in selected_action_ids:
        action = action_by_id[action_id]
        if action.action_family != "MUTATION_BRANCH_REPARENT":
            continue
        target_id = target_parent_by_action.get(action_id)
        if target_id is None:
            target_id = action.target_parent_candidate_ids[0]
        if target_id not in action.target_parent_candidate_ids:
            raise ValueError("RES-225 mutation action selected an unauthorized parent")
        target = updated_items[target_id]
        new_lineage_id = dict(action.target_lineage_id_by_parent)[target_id]
        parent_id = target_id
        for stage, candidate_id in enumerate(action.affected_candidate_ids, start=1):
            updated_items[candidate_id] = _mutation_role_from_parent(
                updated_items[candidate_id],
                target,
                target_parent_id=parent_id,
                target_lineage_id=new_lineage_id,
                stage=stage,
            )
            parent_id = candidate_id

    updated: list[ProductionCandidateCommitmentV1] = []
    for commitment in commitments:
        selected_action = change_by_candidate.get(commitment.candidate_id)
        if selected_action is None:
            updated.append(commitment)
            continue
        item = updated_items[commitment.candidate_id]
        materialization_target_id = target_parent_by_action.get(selected_action.action_id)
        placeholder_hash = canonical_hash(
            {
                "placeholder_schema": "RES-225-TYPED-REPLACEMENT@1",
                "action_id": selected_action.action_id,
                "candidate_id": commitment.candidate_id,
                "target_parent_candidate_id": materialization_target_id,
                "role": next(
                    placeholder
                    for placeholder in selected_action.placeholders
                    if placeholder.candidate_id == commitment.candidate_id
                ),
            }
        )
        updated.append(ProductionCandidateCommitmentV1(item, placeholder_hash))
    replaced_ids = set(change_by_candidate)
    retained_pairs = tuple(
        pair for pair in exact_shingle_colocation_pairs if not set(pair).intersection(replaced_ids)
    )
    if len(updated) != 434 or len({item.candidate_id for item in updated}) != 434:
        raise ValueError("RES-225 abstract action changed the fixed candidate slot count")
    counts = Counter(item.item.origin_class for item in updated)
    for origin, minimum, maximum in ORIGIN_BOUNDS:
        if counts[origin] < minimum or (maximum is not None and counts[origin] > maximum):
            raise ValueError("RES-225 abstract action violates a hard candidate-origin bound")
    return tuple(updated), retained_pairs


def run_exact_abstract_oracle(
    commitments: tuple[ProductionCandidateCommitmentV1, ...],
    exact_shingle_colocation_pairs: tuple[tuple[str, str], ...],
    *,
    candidate_rank_hint: dict[str, int] | None = None,
    canonicalize: bool = False,
    canonical_progress_callback: Callable[[int, int, str], None] | None = None,
    time_budget_seconds: float = 300.0,
) -> ProductionExactFeasibilityReceiptV2:
    """Use the production BASE + COLOCATION exact authority on typed placeholders."""

    return validate_production_exact_feasibility(
        commitments,
        exact_shingle_colocation_pairs=exact_shingle_colocation_pairs,
        defer_colocation_conflict_reduction=True,
        use_legacy_hint=False,
        run_c03_f04_diagnostic=False,
        candidate_rank_hint=candidate_rank_hint,
        canonical_self_reduction_backend="GLUCOSE",
        run_canonical_self_reduction=canonicalize,
        canonical_progress_callback=canonical_progress_callback,
        oracle_time_limit_seconds=time_budget_seconds,
    ).receipt
