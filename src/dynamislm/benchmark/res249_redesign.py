"""RES-249 abstract A/B/C candidate-redesign benchmark.

Everything here operates on typed abstract commitments. No question, answer,
source, or engine bytes are authored, and no split membership is persisted:
exact-solver witnesses are validated in memory and reduced to digests.

The three strategies share one plan vocabulary, one plan-to-commitment
materializer, one capacity model, and one validator. They differ only in the
action families they may use, the root baseline they start from, and their
lexicographic objective.
"""

from __future__ import annotations

import time
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, replace
from typing import Any, Literal

from dynamislm.benchmark.constants import (
    CRITICAL_ERROR_CLASSES,
    CaseOrigin,
    RefusalDecision,
)
from dynamislm.benchmark.coverage import COVERAGE_MATRIX, coverage_manifest_digest
from dynamislm.benchmark.production import (
    FINAL_TARGET_CASES,
    PROSPECTIVE_SPLIT_COUNTS,
    ProductionAuthoringPlanItemV1,
    ProductionCandidateCommitmentV1,
    _build_exact_cp_model,
    _cluster_has_c18_refusal,
    _cluster_has_cell_obligation,
    _exact_aggregate_evidence,
    _exact_requirement_constraints,
    _ExactConstraint,
    _feasibility_clusters,
    _feasibility_row_eligible,
    _FeasibilityCluster,
    _row_by_capability,
    _split_lock_ranks,
    _validate_exact_rank_assignment,
    _validate_feasibility_item,
)
from dynamislm.benchmark.res225_repair import _mutation_role_from_parent
from dynamislm.serialization import canonical_hash, register_serializable_type

Strategy = Literal["CURRENT", "A", "B", "C"]
STRATEGIES: tuple[Strategy, ...] = ("CURRENT", "A", "B", "C")
REDESIGN_SCHEMA = "RES-249-ABSTRACT-REDESIGN@1.0.0"
PLACEHOLDER_SCHEMA = "RES-249-TYPED-PLACEHOLDER@1.0.0"

FROZEN_ORIGIN_COUNTS: tuple[tuple[CaseOrigin, int], ...] = (
    (CaseOrigin.EXPERT_AUTHORED_SEMANTIC, 240),
    (CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION, 40),
    (CaseOrigin.DETERMINISTIC_ENGINE_DERIVED, 31),
    (CaseOrigin.DETERMINISTIC_SYNTHETIC, 12),
    (CaseOrigin.ADVERSARIAL_MUTATION, 111),
)
MUTATION_LINEAGES = 37
MUTATION_CHILDREN_PER_LINEAGE = 3
PROTECTED_RANKS = (1, 2)
VH_ELIGIBLE_COMPONENTS_PER_CELL_MINIMUM = 2

# Lexicographic optimization levels use CP-SAT deterministic time, not wall time,
# so a bounded level stops at the same point on every run.
OPTIMIZER_DETERMINISTIC_TIME = 60.0
# interleave_search makes multi-worker CP-SAT deterministic.
OPTIMIZER_WORKERS = 8
EXACT_DETERMINISTIC_TIME = 120.0
EXACT_WORKERS = 8
MAX_ARRIVALS_PER_ROLE = 4


@dataclass(frozen=True, slots=True)
class OperatorSpec:
    """Frozen mutation operator authority mirrored from ``_mutation_lineage_specs``."""

    operator_id: str
    count: int
    root_capabilities: frozenset[str]
    excluded_families: frozenset[str] = frozenset()

    def admits(self, capability_id: str, benchmark_family: str) -> bool:
        return (
            capability_id in self.root_capabilities
            and benchmark_family not in self.excluded_families
        )


MUTATION_OPERATORS: tuple[OperatorSpec, ...] = (
    OperatorSpec("measurement-identity-trap", 7, frozenset({"C01", "C03", "C04"})),
    OperatorSpec("comparability-overreach", 7, frozenset({"C07"})),
    OperatorSpec("claim-boundary-overreach", 7, frozenset({"C09", "C15"})),
    OperatorSpec("safe-partial-refusal-trap", 8, frozenset({"C18"}), frozenset({"F01"})),
    OperatorSpec("error-correction-trap", 8, frozenset({"C17"})),
)


def operator_for_root(item: ProductionAuthoringPlanItemV1) -> str | None:
    """Return the unique operator a semantic root admits, if any."""

    if item.origin_class is not CaseOrigin.EXPERT_AUTHORED_SEMANTIC:
        return None
    matches = [
        spec.operator_id
        for spec in MUTATION_OPERATORS
        if spec.admits(item.capability_id, item.benchmark_family)
    ]
    if len(matches) > 1:
        raise ValueError("mutation operator root authority is ambiguous")
    return matches[0] if matches else None


def _sorted_ids(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted(values, key=lambda value: value.encode("utf-8")))


def _hex(payload: object, width: int = 20) -> str:
    return canonical_hash(payload).removeprefix("sha256:")[:width]


Cell = tuple[str, str]


def _cell(item: ProductionAuthoringPlanItemV1) -> Cell:
    return (item.capability_id, item.benchmark_family)


def all_cells() -> tuple[Cell, ...]:
    return tuple(
        (row.capability_id, family) for row in COVERAGE_MATRIX for family in row.benchmark_families
    )


@register_serializable_type
@dataclass(frozen=True, slots=True)
class LineageRecord:
    lineage_id: str
    operator_id: str
    root_candidate_id: str
    child_candidate_ids: tuple[str, ...]


@register_serializable_type
@dataclass(frozen=True, slots=True)
class SealedRedesignInputs:
    commitments: tuple[ProductionCandidateCommitmentV1, ...]
    colocation_pairs: tuple[tuple[str, str], ...]
    lineages: tuple[LineageRecord, ...]
    authority_fingerprint: str

    @property
    def items(self) -> dict[str, ProductionAuthoringPlanItemV1]:
        return {entry.candidate_id: entry.item for entry in self.commitments}

    @property
    def root_ids(self) -> frozenset[str]:
        return frozenset(item.root_candidate_id for item in self.lineages)


def derive_lineages(
    commitments: tuple[ProductionCandidateCommitmentV1, ...],
) -> tuple[LineageRecord, ...]:
    """Reconstruct ordered root -> child chains from mutation parent links."""

    items = {entry.candidate_id: entry.item for entry in commitments}
    by_lineage: dict[str, list[ProductionAuthoringPlanItemV1]] = defaultdict(list)
    for item in items.values():
        if item.origin_class is CaseOrigin.ADVERSARIAL_MUTATION:
            if item.mutation_lineage_id is None or item.parent_candidate_id is None:
                raise ValueError("mutation candidate lacks lineage or parent identity")
            by_lineage[item.mutation_lineage_id].append(item)
    lineages: list[LineageRecord] = []
    for lineage_id, members in by_lineage.items():
        member_ids = {item.candidate_id for item in members}
        roots = {
            item.parent_candidate_id
            for item in members
            if item.parent_candidate_id not in member_ids
        }
        if len(roots) != 1:
            raise ValueError("mutation lineage must descend from exactly one semantic root")
        root_id = next(iter(roots))
        if root_id is None or root_id not in items:
            raise ValueError("mutation lineage root is outside the sealed population")
        root = items[root_id]
        operator_id = operator_for_root(root)
        if operator_id is None:
            raise ValueError("mutation lineage root is not operator-compatible")
        child_by_parent = {item.parent_candidate_id: item for item in members}
        if len(child_by_parent) != len(members):
            raise ValueError("mutation lineage is not a single stage-ordered chain")
        chain: list[str] = []
        parent = root_id
        while parent in child_by_parent:
            child = child_by_parent[parent]
            chain.append(child.candidate_id)
            parent = child.candidate_id
        if len(chain) != len(members):
            raise ValueError("mutation lineage chain is disconnected")
        lineages.append(LineageRecord(lineage_id, operator_id, root_id, tuple(chain)))
    return tuple(sorted(lineages, key=lambda item: item.lineage_id.encode("utf-8")))


def _validate_lineage_shape(
    lineages: tuple[LineageRecord, ...],
    items: Mapping[str, ProductionAuthoringPlanItemV1],
) -> None:
    if len(lineages) != MUTATION_LINEAGES:
        raise ValueError("redesign requires exactly 37 mutation lineages")
    if any(len(item.child_candidate_ids) != MUTATION_CHILDREN_PER_LINEAGE for item in lineages):
        raise ValueError("redesign requires exactly three mutation children per lineage")
    roots = [item.root_candidate_id for item in lineages]
    if len(set(roots)) != len(roots):
        raise ValueError("one candidate cannot root multiple mutation lineages")
    counts = Counter(item.operator_id for item in lineages)
    if counts != Counter({spec.operator_id: spec.count for spec in MUTATION_OPERATORS}):
        raise ValueError("mutation operator lineage counts differ from frozen authority")
    for lineage in lineages:
        if operator_for_root(items[lineage.root_candidate_id]) != lineage.operator_id:
            raise ValueError("mutation operator is incompatible with its root capability")


def origin_counts(
    commitments: Iterable[ProductionCandidateCommitmentV1],
) -> tuple[tuple[str, int], ...]:
    counts = Counter(entry.item.origin_class for entry in commitments)
    return tuple((origin.value, counts[origin]) for origin, _expected in FROZEN_ORIGIN_COUNTS)


def seal_redesign_inputs(
    commitments: tuple[ProductionCandidateCommitmentV1, ...],
    colocation_pairs: tuple[tuple[str, str], ...],
) -> SealedRedesignInputs:
    """Bind the current 434-case design as the immutable benchmark authority."""

    ordered = tuple(sorted(commitments, key=lambda entry: entry.candidate_id.encode("utf-8")))
    ids = tuple(entry.candidate_id for entry in ordered)
    if len(ordered) != FINAL_TARGET_CASES or len(set(ids)) != FINAL_TARGET_CASES:
        raise ValueError("sealed redesign input requires 434 unique commitments")
    if origin_counts(ordered) != tuple(
        (origin.value, count) for origin, count in FROZEN_ORIGIN_COUNTS
    ):
        raise ValueError("sealed redesign input origin vector differs from frozen counts")
    pairs = tuple(colocation_pairs)
    id_set = set(ids)
    if any(left not in id_set or right not in id_set for left, right in pairs):
        raise ValueError("sealed co-location pair names an unknown candidate")
    lineages = derive_lineages(ordered)
    items = {entry.candidate_id: entry.item for entry in ordered}
    _validate_lineage_shape(lineages, items)
    fingerprint = canonical_hash(
        {
            "schema": REDESIGN_SCHEMA,
            "commitments": ordered,
            "colocation_pairs": pairs,
            "coverage_matrix_digest": coverage_manifest_digest(),
        }
    )
    return SealedRedesignInputs(ordered, pairs, lineages, fingerprint)


# ---------------------------------------------------------------------------
# Plan vocabulary and the common materializer
# ---------------------------------------------------------------------------

ACTION_FAMILIES = (
    "ROOT_RESELECTION",
    "LINEAGE_REPARENT",
    "ROOT_CONTENT_REPLACEMENT",
    "SEMANTIC_CELL_REASSIGNMENT",
    "SEMANTIC_TEMPLATE_REBIND",
)
# Families listed by RES-249 that are represented but inadmissible here, with
# the mechanical reason they cannot appear in a plan.
INADMISSIBLE_ACTION_FAMILIES: tuple[tuple[str, str], ...] = (
    (
        "LINEAGE_SIZE_REDUCTION",
        "frozen MUTATION_CHILDREN_PER_LINEAGE=3 and MUTATION_LINEAGES=37 fix all 111 "
        "mutation slots; no compensating lineage or slot can exist",
    ),
    (
        "SOURCE_CASE_REPLACEMENT",
        "no additional Phase-A source authority supply is demonstrated",
    ),
    (
        "ENGINE_CASE_REPLACEMENT",
        "no additional RES-71 reference-operation authority supply is demonstrated",
    ),
    (
        "SYNTHETIC_CASE_REPLACEMENT",
        "synthetic split seed locks are frozen authority",
    ),
)


@register_serializable_type
@dataclass(frozen=True, slots=True)
class Reassignment:
    candidate_id: str
    target_cell: Cell
    role_source_id: str


@register_serializable_type
@dataclass(frozen=True, slots=True)
class RedesignPlan:
    """Abstract design decisions relative to the sealed baseline."""

    roots: tuple[tuple[str, str], ...]  # (operator_id, root candidate ID), 37 entries
    root_replacements: tuple[str, ...] = ()
    reassignments: tuple[Reassignment, ...] = ()
    rebinds: tuple[str, ...] = ()

    def canonical(self) -> RedesignPlan:
        return RedesignPlan(
            roots=tuple(sorted(self.roots, key=lambda pair: (pair[0], pair[1].encode("utf-8")))),
            root_replacements=_sorted_ids(self.root_replacements),
            reassignments=tuple(
                sorted(self.reassignments, key=lambda item: item.candidate_id.encode("utf-8"))
            ),
            rebinds=_sorted_ids(self.rebinds),
        )


def current_plan(sealed: SealedRedesignInputs) -> RedesignPlan:
    return RedesignPlan(
        roots=tuple((item.operator_id, item.root_candidate_id) for item in sealed.lineages)
    ).canonical()


def _placeholder_hash(item: ProductionAuthoringPlanItemV1, reason: str) -> str:
    return canonical_hash({"schema": PLACEHOLDER_SCHEMA, "reason": reason, "item": item})


def _independent_binding(candidate_id: str) -> dict[str, str]:
    digest = _hex(("RES-249-INDEPENDENT-TEMPLATE", candidate_id))
    return {
        "expert_author_batch_id": f"PSE-V1-RES249-EXPERT-BATCH:{digest}",
        "protocol_template_id": f"PSE-V1-RES249-PROTOCOL-TEMPLATE:{digest}",
        "isolation_cluster_id": f"PSE-V1-RES249-SEMANTIC-CLUSTER:{digest}",
    }


def _rebind(item: ProductionAuthoringPlanItemV1) -> ProductionAuthoringPlanItemV1:
    binding = _independent_binding(item.candidate_id)
    return replace(
        item,
        expert_author_batch_id=binding["expert_author_batch_id"],
        protocol_template_ids=(binding["protocol_template_id"],),
        isolation_cluster_id=binding["isolation_cluster_id"],
    )


def reassigned_candidate_id(candidate_id: str, target_cell: Cell) -> str:
    capability_id, family = target_cell
    return (
        f"PSE-V1-CANDIDATE:SEM:{capability_id}:{family}:"
        f"R249-{_hex(('RES-249-REASSIGN', candidate_id, target_cell), 12)}"
    )


def new_lineage_id(root_id: str, operator_id: str) -> str:
    return "PSE-V1-MUTATION-LINEAGE:" + _hex(("RES-249-LINEAGE", root_id, operator_id))


@register_serializable_type
@dataclass(frozen=True, slots=True)
class AbstractProductionDesign:
    """Common typed result returned by every strategy."""

    strategy: str
    authority_fingerprint: str
    plan: RedesignPlan
    lineages: tuple[LineageRecord, ...]
    commitments: tuple[ProductionCandidateCommitmentV1, ...]
    colocation_pairs: tuple[tuple[str, str], ...]
    objective_trace: tuple[tuple[str, int], ...]
    design_digest: str
    commitments_digest: str


def materialize_plan(
    sealed: SealedRedesignInputs,
    plan: RedesignPlan,
    *,
    strategy: str,
    objective_trace: tuple[tuple[str, int], ...] = (),
) -> AbstractProductionDesign:
    """Apply a plan to typed metadata only; no candidate bytes are authored."""

    plan = plan.canonical()
    items = dict(sealed.items)
    changed: dict[str, str] = {}
    semantic = {
        cid
        for cid, item in items.items()
        if item.origin_class is CaseOrigin.EXPERT_AUTHORED_SEMANTIC
    }
    root_ids = [root for _operator, root in plan.roots]
    touched = [
        *plan.rebinds,
        *(item.candidate_id for item in plan.reassignments),
    ]
    if len(set(touched)) != len(touched):
        raise ValueError("redesign plan applies overlapping actions to one semantic slot")
    if set(touched) & set(root_ids):
        raise ValueError("redesign plan cannot reassign or rebind a mutation root")
    if not set(plan.root_replacements) <= set(root_ids):
        raise ValueError("root content replacement names a non-root candidate")
    if not set(touched) <= semantic:
        raise ValueError("redesign plan edits a non-semantic candidate")

    for candidate_id in plan.rebinds:
        items[candidate_id] = _rebind(items[candidate_id])
        changed[candidate_id] = "SEMANTIC_TEMPLATE_REBIND"
    for root_id in plan.root_replacements:
        items[root_id] = _rebind(items[root_id])
        changed[root_id] = "ROOT_CONTENT_REPLACEMENT"
    for move in plan.reassignments:
        source = sealed.items[move.role_source_id]
        if (
            move.role_source_id not in semantic
            or _cell(source) != move.target_cell
            or move.target_cell == _cell(sealed.items[move.candidate_id])
        ):
            raise ValueError("semantic reassignment must copy a sealed role from its target cell")
        new_id = reassigned_candidate_id(move.candidate_id, move.target_cell)
        if new_id in items:
            raise ValueError("semantic reassignment produced a colliding candidate ID")
        del items[move.candidate_id]
        items[new_id] = _rebind(
            replace(
                source,
                candidate_id=new_id,
                source_family_id=f"PSE-V1-SEMANTIC-FAMILY:{new_id}",
            )
        )
        changed[new_id] = "SEMANTIC_CELL_REASSIGNMENT"

    current_by_root = {item.root_candidate_id: item for item in sealed.lineages}
    template_child = items[sealed.lineages[0].child_candidate_ids[0]]
    lineages: list[LineageRecord] = []
    for operator_id, root_id in plan.roots:
        kept = current_by_root.get(root_id)
        if kept is not None and kept.operator_id == operator_id:
            if root_id not in plan.root_replacements:
                lineages.append(kept)
                continue
            lineage_id, child_ids = kept.lineage_id, kept.child_candidate_ids
        else:
            lineage_id = new_lineage_id(root_id, operator_id)
            suffix = lineage_id.rsplit(":", 1)[-1]
            child_ids = tuple(
                f"PSE-V1-CANDIDATE:MUT:{suffix}:{stage:02d}"
                for stage in range(1, MUTATION_CHILDREN_PER_LINEAGE + 1)
            )
        root = items[root_id]
        parent_id = root_id
        for stage, child_id in enumerate(child_ids, start=1):
            child = _mutation_role_from_parent(
                replace(template_child, candidate_id=child_id),
                root,
                target_parent_id=parent_id,
                target_lineage_id=lineage_id,
                stage=stage,
            )
            items[child_id] = child
            changed[child_id] = "MUTATION_CHILD_REGENERATED"
            parent_id = child_id
        lineages.append(LineageRecord(lineage_id, operator_id, root_id, child_ids))

    live_children = {cid for lineage in lineages for cid in lineage.child_candidate_ids}
    for cid in [
        cid
        for cid, item in items.items()
        if item.origin_class is CaseOrigin.ADVERSARIAL_MUTATION and cid not in live_children
    ]:
        del items[cid]

    sealed_hash = {entry.candidate_id: entry.candidate_payload_hash for entry in sealed.commitments}
    commitments = tuple(
        ProductionCandidateCommitmentV1(
            items[cid],
            _placeholder_hash(items[cid], changed[cid])
            if cid in changed or cid not in sealed_hash
            else sealed_hash[cid],
        )
        for cid in _sorted_ids(items)
    )
    ordered_lineages = tuple(sorted(lineages, key=lambda item: item.lineage_id.encode("utf-8")))
    _validate_lineage_shape(ordered_lineages, items)
    commitments_digest = canonical_hash(commitments)
    pairs = sealed.colocation_pairs
    design_digest = canonical_hash(
        {
            "schema": REDESIGN_SCHEMA,
            "authority_fingerprint": sealed.authority_fingerprint,
            "plan": plan,
            "lineages": ordered_lineages,
            "commitments_digest": commitments_digest,
            "colocation_pairs_digest": canonical_hash(pairs),
        }
    )
    return AbstractProductionDesign(
        strategy=strategy,
        authority_fingerprint=sealed.authority_fingerprint,
        plan=plan,
        lineages=ordered_lineages,
        commitments=commitments,
        colocation_pairs=pairs,
        objective_trace=objective_trace,
        design_digest=design_digest,
        commitments_digest=commitments_digest,
    )


# ---------------------------------------------------------------------------
# R1 protected-split exact-cover capacity diagnostic
# ---------------------------------------------------------------------------


def item_covers_own_cell(item: ProductionAuthoringPlanItemV1) -> bool:
    """True when the item can discharge its own CELL (and C18 refusal) obligation."""

    row = _row_by_capability(item.capability_id)
    probe = _FeasibilityCluster(
        isolation_cluster_id="probe",
        items=(item,),
        cluster_key="probe",
        preferred_rank=0,
        locked_rank=None,
    )
    if not _cluster_has_cell_obligation(probe, row, item.benchmark_family):
        return False
    if item.capability_id == "C18":
        return _cluster_has_c18_refusal(probe, item.benchmark_family)
    return True


def protected_split_ranks(component: _FeasibilityCluster) -> frozenset[int]:
    """Protected splits a component may enter under the exact-cover argument.

    Validation and Hidden each hold 87 cases for 87 cells, so every protected
    case must discharge a distinct cell. A component may enter a protected split
    only when all of its items cover their own cells, its cells are pairwise
    distinct, and no synthetic lock pins it elsewhere.
    """

    cells = Counter(_cell(item) for item in component.items)
    if max(cells.values()) > 1 or not all(item_covers_own_cell(i) for i in component.items):
        return frozenset()
    locks = _split_lock_ranks(component)
    if len(locks) > 1:
        return frozenset()
    if locks:
        return frozenset(PROTECTED_RANKS) & frozenset(locks)
    return frozenset(PROTECTED_RANKS)


@dataclass(frozen=True, slots=True)
class CellCapacity:
    cell: Cell
    vh_eligible_components: int
    protected_matching: int
    covering_components: int
    component_keys: tuple[str, ...]
    blocking_root_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CapacityReport:
    model: str
    cells: tuple[CellCapacity, ...]
    violating_cells: tuple[Cell, ...]
    matrix_digest: str

    @property
    def minimum(self) -> int:
        return min(item.vh_eligible_components for item in self.cells)


def _protected_matching(rank_sets: list[frozenset[int]]) -> int:
    """Maximum matching of distinct components onto Validation and Hidden."""

    best = 0
    for left in range(len(rank_sets)):
        if rank_sets[left]:
            best = max(best, 1)
        for right in range(left + 1, len(rank_sets)):
            if (1 in rank_sets[left] and 2 in rank_sets[right]) or (
                2 in rank_sets[left] and 1 in rank_sets[right]
            ):
                return 2
    return best


def protected_capacity(
    commitments: tuple[ProductionCandidateCommitmentV1, ...],
    colocation_pairs: tuple[tuple[str, str], ...] = (),
    *,
    root_ids: Iterable[str] = (),
) -> CapacityReport:
    """R1: count independently allocatable V/H components for every cell."""

    components = _feasibility_clusters(
        commitments,
        exact_shingle_colocation_pairs=colocation_pairs,
        allow_incompatible_locks=True,
    )
    roots = frozenset(root_ids)
    eligible: dict[Cell, list[tuple[str, frozenset[int]]]] = defaultdict(list)
    covering: Counter[Cell] = Counter()
    blockers: dict[Cell, set[str]] = defaultdict(set)
    for component in components:
        ranks = protected_split_ranks(component)
        component_roots = {item.candidate_id for item in component.items} & roots
        for cell in {_cell(item) for item in component.items if item_covers_own_cell(item)}:
            covering[cell] += 1
            if ranks:
                eligible[cell].append((component.cluster_key, ranks))
            else:
                blockers[cell].update(component_roots)
    cells = []
    for cell in all_cells():
        entries = sorted(eligible[cell])
        cells.append(
            CellCapacity(
                cell=cell,
                vh_eligible_components=len(entries),
                protected_matching=_protected_matching([ranks for _key, ranks in entries]),
                covering_components=covering[cell],
                component_keys=tuple(key for key, _ranks in entries),
                blocking_root_ids=_sorted_ids(blockers[cell]),
            )
        )
    violating = tuple(
        item.cell
        for item in cells
        if item.vh_eligible_components < VH_ELIGIBLE_COMPONENTS_PER_CELL_MINIMUM
        or item.protected_matching < 2
        or item.covering_components < 3
    )
    matrix_digest = canonical_hash(
        tuple(
            (
                item.cell,
                item.vh_eligible_components,
                item.protected_matching,
                item.covering_components,
                item.component_keys,
            )
            for item in cells
        )
    )
    return CapacityReport(
        model="COLOCATION" if colocation_pairs else "BASE",
        cells=tuple(cells),
        violating_cells=violating,
        matrix_digest=matrix_digest,
    )


# ---------------------------------------------------------------------------
# Exact model construction shared by every strategy
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ExactModel:
    kind: str
    components: tuple[_FeasibilityCluster, ...]
    constraints: tuple[_ExactConstraint, ...]
    model_digest: str


def build_exact_models(
    commitments: tuple[ProductionCandidateCommitmentV1, ...],
    colocation_pairs: tuple[tuple[str, str], ...],
) -> tuple[ExactModel, ExactModel]:
    """Build BASE and COLOCATION exactly as the production oracle does."""

    models = []
    for kind, pairs in (("BASE", ()), ("COLOCATION", colocation_pairs)):
        components = _feasibility_clusters(
            commitments,
            exact_shingle_colocation_pairs=pairs,
            allow_incompatible_locks=True,
        )
        constraints = _exact_requirement_constraints(components, components)
        digest = canonical_hash(
            {
                "kind": kind,
                "components": tuple((item.cluster_key, item.size) for item in components),
                "constraints": tuple(
                    (item.group_id, item.terms, item.lower, item.upper, item.equalities)
                    for item in constraints
                ),
            }
        )
        models.append(ExactModel(kind, components, constraints, digest))
    return models[0], models[1]


@dataclass(frozen=True, slots=True)
class ExactSolve:
    status: str
    ranks: tuple[int, ...] | None
    wall_seconds: float
    deterministic_time: float
    variables: int
    constraints: int
    witness_digest: str | None


def solve_exact(
    model: ExactModel,
    *,
    fixed: Mapping[int, int] | None = None,
    forbidden: Mapping[int, Iterable[int]] | None = None,
    deterministic_time: float | None = None,
    num_workers: int | None = None,
) -> ExactSolve:
    """Run CP-SAT on the shared exact model and validate any witness in memory.

    Every design uses the same configuration: deterministic interleaved
    multi-worker search, seed 0, presolve, no hints, deterministic-time bound.
    """

    from ortools.sat.python import cp_model

    started = time.monotonic()
    cp, variables = _build_exact_cp_model(
        len(model.components), model.constraints, fixed=dict(fixed or {})
    )
    for index, excluded in (forbidden or {}).items():
        for rank in excluded:
            cp.add(variables[index][rank] == 0)
    solver: Any = cp_model.CpSolver()
    workers = EXACT_WORKERS if num_workers is None else num_workers
    solver.parameters.num_search_workers = workers
    solver.parameters.interleave_search = workers > 1
    solver.parameters.random_seed = 0
    solver.parameters.cp_model_presolve = True
    solver.parameters.randomize_search = False
    solver.parameters.max_deterministic_time = (
        EXACT_DETERMINISTIC_TIME if deterministic_time is None else deterministic_time
    )
    raw = solver.solve(cp)
    name = solver.status_name(raw)
    ranks: tuple[int, ...] | None = None
    witness_digest = None
    if name in {"FEASIBLE", "OPTIMAL"}:
        ranks = tuple(
            next(rank for rank in range(3) if solver.value(row[rank])) for row in variables
        )
        validate_witness(model, ranks)
        witness_digest = canonical_hash(("RES-249-WITNESS", model.model_digest, ranks))
        name = "FEASIBLE"
    elif name not in {"INFEASIBLE"}:
        name = "UNKNOWN"
    proto = cp.proto
    return ExactSolve(
        status=name,
        ranks=ranks,
        wall_seconds=time.monotonic() - started,
        deterministic_time=float(solver.response_proto.deterministic_time),
        variables=len(proto.variables),
        constraints=len(proto.constraints),
        witness_digest=witness_digest,
    )


def validate_witness(model: ExactModel, ranks: tuple[int, ...]) -> None:
    """Re-check a split assignment against constraints and aggregate evidence."""

    _validate_exact_rank_assignment(len(model.components), model.constraints, list(ranks))
    _exact_aggregate_evidence(model.components, model.components, ranks)


# ---------------------------------------------------------------------------
# Scientific-authority gate and edit surface (mechanical, plan-independent)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ScientificGate:
    status: str
    failures: tuple[str, ...]


def scientific_gate(
    sealed: SealedRedesignInputs, design: AbstractProductionDesign
) -> ScientificGate:
    failures: list[str] = []
    sealed_items = sealed.items
    items = {entry.candidate_id: entry.item for entry in design.commitments}
    if design.authority_fingerprint != sealed.authority_fingerprint:
        failures.append("STALE_AUTHORITY_FINGERPRINT")
    if len(items) != FINAL_TARGET_CASES:
        failures.append("CANDIDATE_COUNT")
    if origin_counts(design.commitments) != origin_counts(sealed.commitments):
        failures.append("ORIGIN_COUNTS")
    try:
        _validate_lineage_shape(design.lineages, items)
    except ValueError as exc:
        failures.append(f"LINEAGES:{exc}")
    for lineage in design.lineages:
        parent_id = lineage.root_candidate_id
        for stage, child_id in enumerate(lineage.child_candidate_ids, start=1):
            child = items.get(child_id)
            root = items.get(lineage.root_candidate_id)
            if child is None or root is None:
                failures.append(f"LINEAGE_MEMBER_MISSING:{lineage.lineage_id}")
                break
            expected = _mutation_role_from_parent(
                child,
                root,
                target_parent_id=parent_id,
                target_lineage_id=lineage.lineage_id,
                stage=stage,
            )
            if expected != child:
                failures.append(f"MUTATION_ROLE_NOT_DERIVED_FROM_ROOT:{child_id}")
            parent_id = child_id
    fixed_origins = {
        CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION,
        CaseOrigin.DETERMINISTIC_ENGINE_DERIVED,
        CaseOrigin.DETERMINISTIC_SYNTHETIC,
    }
    sealed_by_id = {entry.candidate_id: entry for entry in sealed.commitments}
    design_by_id = {entry.candidate_id: entry for entry in design.commitments}
    for cid, entry in sealed_by_id.items():
        if entry.item.origin_class in fixed_origins and design_by_id.get(cid) != entry:
            failures.append(f"FIXED_AUTHORITY_CHANGED:{entry.item.origin_class.value}:{cid}")
    for entry in design.commitments:
        try:
            _validate_feasibility_item(entry.item)
        except ValueError as exc:
            failures.append(f"FROZEN_ROW_AUTHORITY:{entry.candidate_id}:{exc}")
        if entry.item.origin_class is CaseOrigin.EXPERT_AUTHORED_SEMANTIC:
            same_role = [
                other
                for other in sealed_items.values()
                if other.origin_class is CaseOrigin.EXPERT_AUTHORED_SEMANTIC
                and _cell(other) == _cell(entry.item)
                and _semantic_role(other) == _semantic_role(entry.item)
            ]
            if not same_role:
                failures.append(f"INVENTED_SEMANTIC_ROLE:{entry.candidate_id}")
    if design.colocation_pairs != sealed.colocation_pairs:
        failures.append("CONTAMINATION_COLOCATION_EDGES_CHANGED")
    if any(left not in items or right not in items for left, right in design.colocation_pairs):
        failures.append("CONTAMINATION_COLOCATION_EDGE_DROPPED")
    return ScientificGate("PASS" if not failures else "FAIL", tuple(failures))


def _semantic_role(item: ProductionAuthoringPlanItemV1) -> tuple[object, ...]:
    return (
        item.recipe_id,
        item.recipe_version,
        item.practitioner_question_class,
        item.scoring_profile,
        item.authority_class,
        item.authority_kinds,
        item.reachable_error_classes,
        item.adversarial_tags,
        item.refusal_decision,
        item.expected_answer_kind,
        item.safe_partial_support,
        item.difficulty,
        item.question_surface_variant_id,
    )


@dataclass(frozen=True, slots=True)
class EditSurface:
    semantic_root_identities_changed: int
    semantic_slots_reassigned: int
    semantic_slots_rebound: int
    root_contents_replaced: int
    mutation_lineages_reparented: int
    mutation_children_regenerated: int
    candidate_ids_changed: int
    candidate_hashes_changed: int
    author_batch_template_identities_changed: int
    source_cases_changed: int
    engine_cases_changed: int
    synthetic_cases_changed: int
    total_content_changes: int
    changed_candidate_ids_digest: str


def edit_surface(sealed: SealedRedesignInputs, design: AbstractProductionDesign) -> EditSurface:
    """Count unique changed slots from commitments alone (no double counting)."""

    before = {entry.candidate_id: entry for entry in sealed.commitments}
    after = {entry.candidate_id: entry for entry in design.commitments}
    new_ids = set(after) - set(before)
    rehashed = {
        cid
        for cid in set(after) & set(before)
        if after[cid].candidate_payload_hash != before[cid].candidate_payload_hash
    }
    changed = new_ids | rehashed

    def count(origin: CaseOrigin) -> int:
        return sum(after[cid].item.origin_class is origin for cid in changed)

    new_roots = {item.root_candidate_id for item in design.lineages} - sealed.root_ids
    reassigned = {
        cid
        for cid in new_ids
        if after[cid].item.origin_class is CaseOrigin.EXPERT_AUTHORED_SEMANTIC
    }
    roots = {item.root_candidate_id for item in design.lineages}
    rebound_semantic = {
        cid
        for cid in rehashed
        if after[cid].item.origin_class is CaseOrigin.EXPERT_AUTHORED_SEMANTIC
    }
    templates_changed = sum(
        1
        for cid, entry in after.items()
        if entry.item.origin_class is CaseOrigin.EXPERT_AUTHORED_SEMANTIC
        and (
            cid not in before
            or entry.item.protocol_template_ids != before[cid].item.protocol_template_ids
            or entry.item.expert_author_batch_id != before[cid].item.expert_author_batch_id
        )
    )
    return EditSurface(
        semantic_root_identities_changed=len(new_roots),
        semantic_slots_reassigned=len(reassigned),
        semantic_slots_rebound=len(rebound_semantic - roots),
        root_contents_replaced=len(rebound_semantic & roots),
        mutation_lineages_reparented=len(new_roots),
        mutation_children_regenerated=count(CaseOrigin.ADVERSARIAL_MUTATION),
        candidate_ids_changed=len(new_ids),
        candidate_hashes_changed=len(changed),
        author_batch_template_identities_changed=templates_changed,
        source_cases_changed=count(CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION),
        engine_cases_changed=count(CaseOrigin.DETERMINISTIC_ENGINE_DERIVED),
        synthetic_cases_changed=count(CaseOrigin.DETERMINISTIC_SYNTHETIC),
        total_content_changes=len(changed),
        changed_candidate_ids_digest=canonical_hash(_sorted_ids(changed)),
    )


# ---------------------------------------------------------------------------
# Shared capacity optimization model
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Features:
    """Coverage features a single item contributes when in a protected split."""

    cell: Cell | None
    tags: frozenset[tuple[str, str]]
    errors: frozenset[tuple[str, str]]
    critical: frozenset[str]


def _features(item: ProductionAuthoringPlanItemV1) -> _Features:
    row = _row_by_capability(item.capability_id)
    eligible = _feasibility_row_eligible(item, row)
    critical_values = {error.value for error in CRITICAL_ERROR_CLASSES}
    return _Features(
        cell=_cell(item) if item_covers_own_cell(item) else None,
        tags=frozenset((row.capability_id, tag) for tag in item.adversarial_tags if eligible)
        & frozenset((row.capability_id, tag) for tag in row.adversarial_tags),
        errors=frozenset(
            (row.capability_id, error.value)
            for error in item.reachable_error_classes
            if eligible and error in row.error_classes
        ),
        critical=frozenset(
            error.value
            for error in item.reachable_error_classes
            if eligible and error.value in critical_values
        ),
    )


def _feature_keys(features: _Features) -> set[tuple[str, ...]]:
    keys: set[tuple[str, ...]] = set()
    if features.cell is not None:
        keys.add(("CELL", *features.cell))
    keys.update(("TAG", *tag) for tag in features.tags)
    keys.update(("ERROR", *error) for error in features.errors)
    keys.update(("CRITICAL", error) for error in features.critical)
    return keys


def _required_protected_components() -> dict[tuple[str, ...], int]:
    required: dict[tuple[str, ...], int] = {}
    for row in COVERAGE_MATRIX:
        for family in row.benchmark_families:
            required[("CELL", row.capability_id, family)] = 2
        for tag in row.adversarial_tags:
            required[("TAG", row.capability_id, tag)] = 2
        for error in row.error_classes:
            required[("ERROR", row.capability_id, error.value)] = 2
    for error in CRITICAL_ERROR_CLASSES:
        required[("CRITICAL", error.value)] = 4
    return required


@dataclass(frozen=True, slots=True)
class ActionSpace:
    """Which plan families a strategy may use, relative to a root baseline."""

    root_reselection: bool
    reassignment: bool
    rebind: bool
    root_replacement: bool
    baseline_roots: tuple[tuple[str, str], ...]
    fixed_roots: bool = False
    rejected_roots: frozenset[str] = frozenset()
    removed_targets: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class _Objective:
    name: str
    sense: str  # "min" or "max"


class _CapacityModel:
    """CP-SAT model of necessary protected-split capacity under a plan.

    Every constraint here is a necessary condition of the exact BASE/COLOCATION
    models (see ``protected_split_ranks``); exact feasibility of the selected
    plan is always re-checked by the common validator.
    """

    def __init__(self, sealed: SealedRedesignInputs, space: ActionSpace) -> None:
        from ortools.sat.python import cp_model

        self.cp_model = cp_model
        self.sealed = sealed
        self.space = space
        model = cp_model.CpModel()
        self.model = model
        items = sealed.items
        self.items = items
        semantic = _sorted_ids(
            cid
            for cid, item in items.items()
            if item.origin_class is CaseOrigin.EXPERT_AUTHORED_SEMANTIC
        )
        self.semantic = semantic
        index = {cid: position for position, cid in enumerate(semantic)}
        self.index = index
        baseline_roots = {root for _operator, root in space.baseline_roots}

        # Root selection variables x[(operator, slot)].
        self.root_vars: dict[tuple[str, str], Any] = {}
        for spec in MUTATION_OPERATORS:
            for cid in semantic:
                if not spec.admits(*_cell(items[cid])):
                    continue
                if cid in space.rejected_roots:
                    continue
                if cid in space.removed_targets and cid not in baseline_roots:
                    continue
                if (space.fixed_roots or not space.root_reselection) and cid not in baseline_roots:
                    continue
                self.root_vars[(spec.operator_id, cid)] = model.new_bool_var(
                    f"root[{spec.operator_id}|{cid}]"
                )
            model.add(
                sum(var for (op, _cid), var in self.root_vars.items() if op == spec.operator_id)
                == spec.count
            )
        if space.fixed_roots or not space.root_reselection:
            for _operator, cid in space.baseline_roots:
                if cid in space.rejected_roots:
                    continue
                for (_op, root_id), var in self.root_vars.items():
                    if root_id == cid:
                        model.add(var == 1)
        self.is_root: dict[str, Any] = {}
        for cid in semantic:
            terms = [var for (_op, root_id), var in self.root_vars.items() if root_id == cid]
            if terms:
                is_root = model.new_bool_var(f"is_root[{cid}]")
                model.add(sum(terms) == is_root)
                self.is_root[cid] = is_root
        self.new_root = {cid: var for cid, var in self.is_root.items() if cid not in baseline_roots}

        # Root content replacement (root leaves its batch with new template).
        self.root_replace: dict[str, Any] = {}
        if space.root_replacement:
            for cid, var in self.is_root.items():
                if items[cid].isolation_cluster_id in self._multi_member_clusters():
                    replace_var = model.new_bool_var(f"root_replace[{cid}]")
                    model.add_implication(replace_var, var)
                    self.root_replace[cid] = replace_var

        # Semantic reassignment is modelled as independent departures (which
        # non-root slot is released) and arrivals (which sealed role variant a
        # new independent singleton copies). Any departure can author any
        # arrival, so only their counts are linked; pairing is canonical.
        self.role_sources = self._role_sources()
        self.depart: dict[str, Any] = {}
        self.arrive: dict[str, Any] = {}
        if space.reassignment:
            for cid in semantic:
                self.depart[cid] = model.new_bool_var(f"depart[{cid}]")
            for source_id in self.role_sources:
                self.arrive[source_id] = model.new_int_var(
                    0, MAX_ARRIVALS_PER_ROLE, f"arrive[{source_id}]"
                )
            model.add(sum(self.depart.values()) == sum(self.arrive.values()))
            # A slot cannot depart into its own cell (that is a rebind).
            by_cell: dict[Cell, list[str]] = defaultdict(list)
            for cid in semantic:
                by_cell[_cell(items[cid])].append(cid)
            for cell in by_cell:
                arrivals_here = [
                    self.arrive[src] for src in self.role_sources if _cell(items[src]) == cell
                ]
                departures_elsewhere = [
                    self.depart[cid] for cid in semantic if _cell(items[cid]) != cell
                ]
                model.add(sum(arrivals_here) <= sum(departures_elsewhere))
        self.moved = dict(self.depart)
        self.rebind: dict[str, Any] = {}
        if space.rebind:
            for cid in semantic:
                if items[cid].isolation_cluster_id in self._multi_member_clusters():
                    self.rebind[cid] = model.new_bool_var(f"rebind[{cid}]")
        for cid in semantic:
            exclusive = [
                var for var in (self.moved.get(cid), self.rebind.get(cid)) if var is not None
            ]
            root_var = self.is_root.get(cid)
            for var in exclusive:
                if root_var is not None:
                    model.add_implication(var, root_var.Not())
            if len(exclusive) > 1:
                model.add(sum(exclusive) <= 1)

        self.level_log: list[tuple[str, str, float]] = []
        self._build_capacity()

    def _multi_member_clusters(self) -> frozenset[str]:
        counts = Counter(self.items[cid].isolation_cluster_id for cid in self.semantic)
        return frozenset(key for key, value in counts.items() if value > 1)

    def _role_sources(self) -> tuple[str, ...]:
        """One canonical sealed representative per (cell, semantic role variant)."""

        chosen: dict[tuple[Cell, tuple[object, ...]], str] = {}
        for cid in self.semantic:
            key = (_cell(self.items[cid]), _semantic_role(self.items[cid]))
            chosen.setdefault(key, cid)
        return _sorted_ids(chosen.values())

    def _leaves(self, cid: str) -> list[Any]:
        return [
            var
            for var in (self.moved.get(cid), self.rebind.get(cid), self.root_replace.get(cid))
            if var is not None
        ]

    def _build_capacity(self) -> None:
        model = self.model
        items = self.items
        required = _required_protected_components()
        protected: dict[tuple[str, ...], list[Any]] = defaultdict(list)
        protected_fixed_v: Counter[tuple[str, ...]] = Counter()
        protected_fixed_h: Counter[tuple[str, ...]] = Counter()
        protected_fixed_both: Counter[tuple[str, ...]] = Counter()
        cover: dict[Cell, list[Any]] = defaultdict(list)
        cover_fixed: Counter[Cell] = Counter()

        # Fixed (non-semantic, non-mutation) COLOCATION components.
        semantic_or_mutation = {
            CaseOrigin.EXPERT_AUTHORED_SEMANTIC,
            CaseOrigin.ADVERSARIAL_MUTATION,
        }
        for component in _feasibility_clusters(
            self.sealed.commitments,
            exact_shingle_colocation_pairs=self.sealed.colocation_pairs,
            allow_incompatible_locks=True,
        ):
            if any(item.origin_class in semantic_or_mutation for item in component.items):
                if not all(item.origin_class in semantic_or_mutation for item in component.items):
                    raise ValueError("semantic component is co-located with fixed authority")
                continue
            ranks = protected_split_ranks(component)
            keys: set[tuple[str, ...]] = set()
            for item in component.items:
                keys |= _feature_keys(_features(item))
                if item_covers_own_cell(item):
                    cover_fixed[_cell(item)] += 1
            for key in keys:
                if ranks == frozenset(PROTECTED_RANKS):
                    protected_fixed_both[key] += 1
                elif ranks == frozenset({1}):
                    protected_fixed_v[key] += 1
                elif ranks == frozenset({2}):
                    protected_fixed_h[key] += 1

        # Semantic batch components (members that stay) and their eligibility.
        by_cluster: dict[str, list[str]] = defaultdict(list)
        for cid in self.semantic:
            by_cluster[items[cid].isolation_cluster_id].append(cid)
        self.eligible_vars: list[Any] = []
        self.stay: dict[str, Any] = {}
        self.blocked: dict[str, Any] = {}
        self.cluster_members: dict[str, tuple[str, ...]] = {}
        for cluster_id, members in sorted(by_cluster.items()):
            stays: dict[str, Any] = {}
            for cid in members:
                leaves = self._leaves(cid)
                if leaves:
                    stay = model.new_bool_var(f"stay[{cid}]")
                    model.add(sum(leaves) + stay == 1)
                else:
                    stay = model.new_constant(1)
                stays[cid] = stay
                self.stay[cid] = stay
            self.cluster_members[cluster_id] = tuple(members)
            eligible = model.new_bool_var(f"eligible[{cluster_id}]")
            self.eligible_vars.append(eligible)
            for cid in members:
                if not item_covers_own_cell(items[cid]):
                    model.add_implication(eligible, stays[cid].Not())
                root_var = self.is_root.get(cid)
                if root_var is not None:
                    # A root that stays carries its three same-cell children.
                    replaced = self.root_replace.get(cid)
                    blocked = model.new_bool_var(f"blocked[{cid}]")
                    self.blocked[cid] = blocked
                    if replaced is None:
                        model.add(blocked == root_var)
                    else:
                        model.add(blocked >= root_var - replaced)
                        model.add(blocked <= root_var)
                        model.add(blocked <= replaced.Not())
                    model.add_implication(eligible, blocked.Not())
            nonempty = [stays[cid] for cid in members]
            model.add(sum(nonempty) >= 1).only_enforce_if(eligible)
            feature_members: dict[tuple[str, ...], list[str]] = defaultdict(list)
            for cid in members:
                for key in _feature_keys(_features(items[cid])):
                    feature_members[key].append(cid)
                cover[_cell(items[cid])].append(stays[cid])
            for key, holders in feature_members.items():
                contribution = model.new_bool_var(f"contrib[{cluster_id}|{key}]")
                model.add_implication(contribution, eligible)
                model.add(sum(stays[cid] for cid in holders) >= 1).only_enforce_if(contribution)
                protected[key].append(contribution)

        # Singletons produced by rebind (same cell) and root replacement.
        for cid, var in self.rebind.items():
            for key in _feature_keys(_features(items[cid])):
                protected[key].append(var)
            cover[_cell(items[cid])].append(var)
        for cid, var in self.root_replace.items():
            cover[_cell(items[cid])].append(var)
        # Singletons produced by reassignment copy the role source's features.
        for source_id, var in self.arrive.items():
            source = items[source_id]
            for key in _feature_keys(_features(source)):
                protected[key].append(var)
            cover[_cell(source)].append(var)

        self.cell_capacity: dict[Cell, Any] = {
            cell: sum(protected.get(("CELL", *cell), []))
            + protected_fixed_both[("CELL", *cell)]
            + protected_fixed_v[("CELL", *cell)]
            + protected_fixed_h[("CELL", *cell)]
            for cell in all_cells()
        }
        # Capacity minima are soft with explicit deficits so an infeasible action
        # space still yields its least-deficient plan; every strategy ranks
        # CAPACITY_DEFICIT first, so a zero optimum means the minima hold.
        self.deficits: dict[tuple[str, ...], Any] = {}
        for key, minimum in sorted(required.items()):
            variable_terms = protected.get(key, [])
            both = protected_fixed_both[key]
            only_v = protected_fixed_v[key]
            only_h = protected_fixed_h[key]
            share = minimum // 2
            deficit = model.new_int_var(0, minimum, f"deficit[{key}]")
            self.deficits[key] = deficit
            model.add(sum(variable_terms) + both + only_v + only_h + deficit >= minimum)
            model.add(sum(variable_terms) + both + only_v + deficit >= share)
            model.add(sum(variable_terms) + both + only_h + deficit >= share)
        for cell in all_cells():
            deficit = model.new_int_var(0, 3, f"deficit[COVER|{cell}]")
            self.deficits[("COVER", *cell)] = deficit
            model.add(sum(cover[cell]) + cover_fixed[cell] + deficit >= 3)

    # -- objectives ----------------------------------------------------------

    def expression(self, name: str) -> Any:
        if name == "CAPACITY_DEFICIT":
            return sum(self.deficits.values())
        if name == "ROOTS_CHANGED":
            return sum(self.new_root.values())
        if name == "CHILDREN_REGENERATED":
            return 3 * sum(self._regenerated().values())
        if name == "CONTENT_CHANGES":
            return (
                3 * sum(self._regenerated().values())
                + sum(self.moved.values())
                + sum(self.rebind.values())
                + sum(self.root_replace.values())
            )
        if name == "REASSIGNMENTS":
            return sum(self.moved.values())
        if name == "PARENT_CHANGES":
            return sum(self.new_root.values()) + sum(self.root_replace.values())
        if name == "NEW_TEMPLATE_BINDINGS":
            return (
                sum(self.moved.values())
                + sum(self.rebind.values())
                + sum(self.root_replace.values())
            )
        if name == "DOWNSTREAM_ACTIONS":
            return (
                sum(self.moved.values())
                + sum(self.rebind.values())
                + sum(self.root_replace.values())
            )
        if name in {"ROOT_CELLS_CHANGED", "MAX_ROOTS_PER_CELL", "DISTRIBUTION_DEVIATION"}:
            return self._distribution(name)
        if name in {"MIN_CELL_CAPACITY", "CELLS_WITH_CAPACITY_GE3"}:
            return self._resilience(name)
        if name == "CANONICAL_TIE_BREAK":
            terms = []
            for (_op, cid), var in self.root_vars.items():
                terms.append((self.index[cid] + 1) * var)
            for cid, var in self.depart.items():
                terms.append((self.index[cid] + 1) * var)
            for source_id, var in self.arrive.items():
                terms.append((self.index[source_id] + 1) * var)
            for cid, var in self.rebind.items():
                terms.append((self.index[cid] + 1) * var)
            for cid, var in self.root_replace.items():
                terms.append((self.index[cid] + 1) * var)
            return sum(terms)
        raise ValueError(f"unknown RES-249 objective {name}")

    def _regenerated(self) -> dict[str, Any]:
        if not hasattr(self, "_regen_cache"):
            regen: dict[str, Any] = {}
            for cid in self.is_root:
                sources = [
                    var
                    for var in (self.new_root.get(cid), self.root_replace.get(cid))
                    if var is not None
                ]
                if not sources:
                    continue
                var = self.model.new_bool_var(f"regen[{cid}]")
                self.model.add_max_equality(var, sources)
                regen[cid] = var
            self._regen_cache = regen
        return self._regen_cache

    def _distribution(self, name: str) -> Any:
        model = self.model
        baseline_cells = Counter(_cell(self.items[root]) for _op, root in self.space.baseline_roots)
        root_cells: dict[Cell, list[Any]] = defaultdict(list)
        for cid, var in self.is_root.items():
            root_cells[_cell(self.items[cid])].append(var)
        if name == "MAX_ROOTS_PER_CELL":
            maximum = model.new_int_var(0, 37, "max_roots_per_cell")
            for terms in root_cells.values():
                model.add(sum(terms) <= maximum)
            return maximum
        deviations = []
        cells = set(root_cells) | set(baseline_cells)
        for cell in sorted(cells):
            count = sum(root_cells.get(cell, []))
            delta = model.new_int_var(0, 37, f"root_delta[{cell}]")
            model.add(delta >= count - baseline_cells[cell])
            model.add(delta >= baseline_cells[cell] - count)
            if name == "ROOT_CELLS_CHANGED":
                flag = model.new_bool_var(f"root_cell_changed[{cell}]")
                model.add(delta <= 37 * flag)
                deviations.append(flag)
            else:
                deviations.append(delta)
        if name == "DISTRIBUTION_DEVIATION":
            semantic_cells = Counter(_cell(self.items[cid]) for cid in self.semantic)
            for cell in sorted(semantic_cells):
                outflow = sum(
                    var for cid, var in self.depart.items() if _cell(self.items[cid]) == cell
                )
                inflow = sum(
                    var for src, var in self.arrive.items() if _cell(self.items[src]) == cell
                )
                delta = model.new_int_var(0, 240, f"semantic_delta[{cell}]")
                model.add(delta >= inflow - outflow)
                model.add(delta >= outflow - inflow)
                deviations.append(delta)
        return sum(deviations)

    def _resilience(self, name: str) -> Any:
        model = self.model
        if name == "MIN_CELL_CAPACITY":
            minimum = model.new_int_var(0, FINAL_TARGET_CASES, "min_cell_capacity")
            for expression in self.cell_capacity.values():
                model.add(minimum <= expression)
            return minimum
        flags = []
        for cell, expression in self.cell_capacity.items():
            flag = model.new_bool_var(f"capacity_ge3[{cell}]")
            model.add(expression >= 3).only_enforce_if(flag)
            flags.append(flag)
        return sum(flags)

    # -- solving -------------------------------------------------------------

    def _decision_variables(self) -> list[Any]:
        return [
            *self.root_vars.values(),
            *self.root_replace.values(),
            *self.depart.values(),
            *self.arrive.values(),
            *self.rebind.values(),
        ]

    def _pair_reassignments(
        self, departures: tuple[str, ...], arrivals: tuple[str, ...]
    ) -> tuple[Reassignment, ...]:
        """Canonically pair released slots with arriving roles across cells."""

        released = _sorted_ids(departures)
        roles = _sorted_ids(arrivals)
        if len(released) != len(roles):
            raise ValueError("reassignment departures and arrivals are unbalanced")
        owner: dict[int, int] = {}  # departure index -> arrival index

        def augment(arrival: int, seen: set[int]) -> bool:
            target = _cell(self.items[roles[arrival]])
            for departure, cid in enumerate(released):
                if departure in seen or _cell(self.items[cid]) == target:
                    continue
                seen.add(departure)
                if departure not in owner or augment(owner[departure], seen):
                    owner[departure] = arrival
                    return True
            return False

        for arrival in range(len(roles)):
            if not augment(arrival, set()):
                raise ValueError("reassignment arrivals cannot be paired across cells")
        by_arrival = {arrival: departure for departure, arrival in owner.items()}
        return tuple(
            Reassignment(
                released[by_arrival[arrival]],
                _cell(self.items[roles[arrival]]),
                roles[arrival],
            )
            for arrival in range(len(roles))
        )

    def add_nogood(self, plan: RedesignPlan) -> None:
        """Exclude exactly one previously selected decision vector."""

        model = self.model
        differs: list[Any] = []
        chosen_roots = set(plan.roots)
        for key, var in self.root_vars.items():
            differs.append(var.Not() if key in chosen_roots else var)
        for collection, selected in (
            (self.root_replace, set(plan.root_replacements)),
            (self.rebind, set(plan.rebinds)),
            (self.depart, {item.candidate_id for item in plan.reassignments}),
        ):
            for cid, var in collection.items():
                differs.append(var.Not() if cid in selected else var)
        arrivals = Counter(item.role_source_id for item in plan.reassignments)
        for source_id, var in self.arrive.items():
            flag = model.new_bool_var(f"arrival_differs[{source_id}|{len(self.level_log)}]")
            model.add(var != arrivals[source_id]).only_enforce_if(flag)
            model.add(var == arrivals[source_id]).only_enforce_if(flag.Not())
            differs.append(flag)
        model.add_bool_or(differs)

    def solve_lexicographic(
        self, objectives: tuple[_Objective, ...]
    ) -> tuple[RedesignPlan | None, tuple[tuple[str, int], ...], str]:
        cp_model = self.cp_model
        trace: list[tuple[str, int]] = []
        expressions = [(item, self.expression(item.name)) for item in objectives]
        expressions.append(
            (_Objective("CANONICAL_TIE_BREAK", "min"), self.expression("CANONICAL_TIE_BREAK"))
        )
        status_label = "OPTIMAL"
        solver: Any = None
        for objective, expression in expressions:
            if objective.sense == "min":
                self.model.minimize(expression)
            else:
                self.model.maximize(expression)
            solver = cp_model.CpSolver()
            solver.parameters.num_search_workers = OPTIMIZER_WORKERS
            solver.parameters.interleave_search = OPTIMIZER_WORKERS > 1
            solver.parameters.random_seed = 0
            solver.parameters.randomize_search = False
            solver.parameters.max_deterministic_time = OPTIMIZER_DETERMINISTIC_TIME
            status = solver.solve(self.model)
            name = solver.status_name(status)
            self.level_log.append(
                (objective.name, name, round(float(solver.response_proto.deterministic_time), 3))
            )
            if name == "INFEASIBLE":
                return None, tuple(trace), "INFEASIBLE"
            if name not in {"OPTIMAL", "FEASIBLE"}:
                return None, tuple(trace), "UNKNOWN"
            value = round(solver.objective_value)
            trace.append((objective.name, value))
            if name == "FEASIBLE":
                # Unproven level: keep the incumbent reachable without claiming
                # optimality by bounding rather than pinning the objective.
                status_label = "FEASIBLE_NOT_PROVEN_OPTIMAL"
                if objective.sense == "min":
                    self.model.add(expression <= value)
                else:
                    self.model.add(expression >= value)
            else:
                self.model.add(expression == value)
            self.model.clear_objective()  # type: ignore[no-untyped-call]
            self.model.clear_hints()  # type: ignore[no-untyped-call]
            for variable in self._decision_variables():
                self.model.add_hint(variable, solver.value(variable))
        plan = RedesignPlan(
            roots=tuple(key for key, var in self.root_vars.items() if solver.value(var)),
            root_replacements=tuple(
                cid for cid, var in self.root_replace.items() if solver.value(var)
            ),
            reassignments=self._pair_reassignments(
                tuple(cid for cid, var in self.depart.items() if solver.value(var)),
                tuple(
                    source
                    for source, var in self.arrive.items()
                    for _copy in range(solver.value(var))
                ),
            ),
            rebinds=tuple(cid for cid, var in self.rebind.items() if solver.value(var)),
        ).canonical()
        return plan, tuple(trace), status_label


@dataclass(frozen=True, slots=True)
class _ExactFeatures:
    """Production exact-model obligations a single item can discharge."""

    cell: Cell | None
    tags: frozenset[tuple[str, str]]
    errors: frozenset[tuple[str, str]]
    critical: frozenset[str]
    c18_family: str | None
    answerable: bool


def _exact_features(item: ProductionAuthoringPlanItemV1) -> _ExactFeatures:
    row = _row_by_capability(item.capability_id)
    probe = _FeasibilityCluster(
        isolation_cluster_id="probe",
        items=(item,),
        cluster_key="probe",
        preferred_rank=0,
        locked_rank=None,
    )
    eligible = _feasibility_row_eligible(item, row)
    critical_values = {error.value for error in CRITICAL_ERROR_CLASSES}
    return _ExactFeatures(
        cell=_cell(item)
        if _cluster_has_cell_obligation(probe, row, item.benchmark_family)
        else None,
        tags=frozenset(
            (row.capability_id, tag)
            for tag in item.adversarial_tags
            if eligible and tag in row.adversarial_tags
        ),
        errors=frozenset(
            (row.capability_id, error.value)
            for error in item.reachable_error_classes
            if eligible and error in row.error_classes
        ),
        critical=frozenset(
            error.value
            for error in item.reachable_error_classes
            if _feasibility_row_eligible(item, row) and error.value in critical_values
        ),
        c18_family=item.benchmark_family
        if item.capability_id == "C18" and _cluster_has_c18_refusal(probe, item.benchmark_family)
        else None,
        answerable=(
            item.refusal_decision is not RefusalDecision.REQUIRED
            and item.expected_answer_kind.value != "REFUSAL"
        ),
    )


def _exact_keys(features: _ExactFeatures) -> set[tuple[str, ...]]:
    keys: set[tuple[str, ...]] = set()
    if features.cell is not None:
        keys.add(("CELL", *features.cell))
    keys.update(("ROW_TAG", *tag) for tag in features.tags)
    keys.update(("ROW_ERROR", *error) for error in features.errors)
    if features.c18_family is not None:
        keys.add(("C18_REFUSAL", features.c18_family))
    if features.answerable:
        keys.add(("ANSWERABLE",))
    return keys


def _exact_requirement_keys() -> tuple[tuple[str, ...], ...]:
    keys: list[tuple[str, ...]] = [("ANSWERABLE",)]
    for row in COVERAGE_MATRIX:
        keys.extend(("CELL", row.capability_id, family) for family in row.benchmark_families)
        keys.extend(("ROW_TAG", row.capability_id, tag) for tag in row.adversarial_tags)
        keys.extend(("ROW_ERROR", row.capability_id, error.value) for error in row.error_classes)
    keys.extend(("C18_REFUSAL", family) for family in _row_by_capability("C18").benchmark_families)
    return tuple(keys)


class _AllocationModel(_CapacityModel):
    """Plan variables jointly with an exact COLOCATION split allocation.

    Each component that a plan can produce receives split-rank variables, and
    the production COLOCATION constraint families are imposed on the result:
    exact COUNT, CELL, ROW_TAG, ROW_ERROR, C18_REFUSAL, ANSWERABLE,
    SYNTHETIC_LOCK, and two-component CRITICAL redundancy in Validation and
    Hidden. A returned plan is therefore COLOCATION-feasible by construction;
    the common validator still re-checks BASE and COLOCATION independently.
    """

    def __init__(self, sealed: SealedRedesignInputs, space: ActionSpace) -> None:
        super().__init__(sealed, space)
        self._build_allocation()

    def _build_allocation(self) -> None:
        model = self.model
        items = self.items
        targets = tuple(count for _split, count in PROSPECTIVE_SPLIT_COUNTS)
        count_terms: list[list[Any]] = [[], [], []]
        feature_terms: dict[tuple[tuple[str, ...], int], list[Any]] = defaultdict(list)
        critical_terms: dict[tuple[str, int], list[Any]] = defaultdict(list)

        def ranks(name: str) -> tuple[Any, Any, Any]:
            row = tuple(model.new_bool_var(f"{name}[{rank}]") for rank in range(3))
            return row  # type: ignore[return-value]

        def add_item(
            item: ProductionAuthoringPlanItemV1, rank: int, literal: Any, weight: int = 1
        ) -> None:
            count_terms[rank].append(weight * literal)
            for key in _exact_keys(_exact_features(item)):
                feature_terms[(key, rank)].append(literal)

        # Fixed COLOCATION components keep their exact authority and locks.
        for component in _feasibility_clusters(
            self.sealed.commitments,
            exact_shingle_colocation_pairs=self.sealed.colocation_pairs,
            allow_incompatible_locks=True,
        ):
            if any(
                item.origin_class
                in {CaseOrigin.EXPERT_AUTHORED_SEMANTIC, CaseOrigin.ADVERSARIAL_MUTATION}
                for item in component.items
            ):
                continue
            row = ranks(f"fixed[{component.cluster_key}]")
            model.add_exactly_one(row)
            locks = _split_lock_ranks(component)
            for rank in range(3):
                if locks and rank not in locks:
                    model.add(row[rank] == 0)
                for item in component.items:
                    add_item(item, rank, row[rank])
                critical = set().union(*(_exact_features(i).critical for i in component.items))
                for error in critical:
                    critical_terms[(error, rank)].append(row[rank])

        # Semantic batch components with their staying members and root blocks.
        for cluster_id, members in sorted(self.cluster_members.items()):
            row = ranks(f"batch[{cluster_id}]")
            model.add_exactly_one(row)
            per_error: dict[str, list[Any]] = defaultdict(list)
            for cid in members:
                item = items[cid]
                stay = self.stay[cid]
                for rank in range(3):
                    present = model.new_bool_var(f"present[{cid}|{rank}]")
                    model.add_implication(present, stay)
                    model.add_implication(present, row[rank])
                    model.add_bool_or([present, stay.Not(), row[rank].Not()])
                    add_item(item, rank, present)
                    for error in _exact_features(item).critical:
                        per_error[f"{error}|{rank}"].append(present)
                blocked = self.blocked.get(cid)
                if blocked is not None:
                    # A staying root carries three same-cell children: Public only.
                    model.add_implication(blocked, row[0])
                    # Children copy the root role, hence its coverage features.
                    add_item(item, 0, blocked, MUTATION_CHILDREN_PER_LINEAGE)
            for key, literals in per_error.items():
                error, rank_text = key.split("|")
                rank = int(rank_text)
                has = model.new_bool_var(f"critical[{cluster_id}|{key}]")
                model.add(sum(literals) >= 1).only_enforce_if(has)
                model.add_implication(has, row[rank])
                critical_terms[(error, rank)].append(has)

        # Root content replacement: root plus children form a Public block.
        for cid, var in self.root_replace.items():
            add_item(items[cid], 0, var, 1 + MUTATION_CHILDREN_PER_LINEAGE)

        # Rebound semantic singletons.
        for cid, var in self.rebind.items():
            row = ranks(f"rebound[{cid}]")
            model.add(sum(row) == var)
            for rank in range(3):
                add_item(items[cid], rank, row[rank])
                for error in _exact_features(items[cid]).critical:
                    critical_terms[(error, rank)].append(row[rank])

        # Arriving reassigned singletons copying a sealed role variant.
        for source_id, count in self.arrive.items():
            split = [
                model.new_int_var(0, MAX_ARRIVALS_PER_ROLE, f"arrival[{source_id}|{rank}]")
                for rank in range(3)
            ]
            model.add(sum(split) == count)
            for rank in range(3):
                add_item(items[source_id], rank, split[rank])
                for error in _exact_features(items[source_id]).critical:
                    critical_terms[(error, rank)].append(split[rank])

        for rank in range(3):
            model.add(sum(count_terms[rank]) == targets[rank])
            for requirement in _exact_requirement_keys():
                model.add(sum(feature_terms.get((requirement, rank), [])) >= 1)
        for rank in PROTECTED_RANKS:
            for error in CRITICAL_ERROR_CLASSES:
                model.add(sum(critical_terms.get((error.value, rank), [])) >= 2)


# ---------------------------------------------------------------------------
# Strategies behind one interface
# ---------------------------------------------------------------------------

STRATEGY_OBJECTIVES: dict[str, tuple[_Objective, ...]] = {
    "A": (
        _Objective("CAPACITY_DEFICIT", "min"),
        _Objective("ROOTS_CHANGED", "min"),
        _Objective("ROOT_CELLS_CHANGED", "min"),
        _Objective("MAX_ROOTS_PER_CELL", "min"),
        _Objective("MIN_CELL_CAPACITY", "max"),
        _Objective("CELLS_WITH_CAPACITY_GE3", "max"),
    ),
    "B": (
        _Objective("CAPACITY_DEFICIT", "min"),
        _Objective("CONTENT_CHANGES", "min"),
        _Objective("ROOTS_CHANGED", "min"),
        _Objective("CHILDREN_REGENERATED", "min"),
        _Objective("REASSIGNMENTS", "min"),
        _Objective("PARENT_CHANGES", "min"),
        _Objective("NEW_TEMPLATE_BINDINGS", "min"),
        _Objective("DISTRIBUTION_DEVIATION", "min"),
    ),
    "C": (
        _Objective("CAPACITY_DEFICIT", "min"),
        _Objective("CONTENT_CHANGES", "min"),
        _Objective("CHILDREN_REGENERATED", "min"),
        _Objective("DOWNSTREAM_ACTIONS", "min"),
        _Objective("MIN_CELL_CAPACITY", "max"),
        _Objective("CELLS_WITH_CAPACITY_GE3", "max"),
    ),
}


def action_space(
    strategy: str,
    sealed: SealedRedesignInputs,
    *,
    baseline_roots: tuple[tuple[str, str], ...] | None = None,
    rejected_roots: frozenset[str] = frozenset(),
    removed_targets: frozenset[str] = frozenset(),
) -> ActionSpace:
    roots = baseline_roots or current_plan(sealed).roots
    if strategy == "A":
        return ActionSpace(True, False, False, False, roots, False, rejected_roots, removed_targets)
    if strategy == "B":
        return ActionSpace(True, True, True, True, roots, False, rejected_roots, removed_targets)
    if strategy == "C":
        return ActionSpace(False, True, True, True, roots, True, rejected_roots, removed_targets)
    raise ValueError(f"unknown RES-249 strategy {strategy}")


class RedesignInterruptedError(RuntimeError):
    """Raised by a progress callback to simulate an interrupted construction."""


def _design_from_model(
    sealed: SealedRedesignInputs,
    strategy: str,
    model: _CapacityModel,
    objectives: tuple[_Objective, ...],
    *,
    allocation_embedded: bool,
) -> AbstractProductionDesign | None:
    plan, trace, status = model.solve_lexicographic(objectives)
    if plan is None:
        return None
    return materialize_plan(
        sealed,
        plan,
        strategy=strategy,
        objective_trace=(
            *trace,
            ("OPTIMIZER_PROVEN_OPTIMAL", int(status == "OPTIMAL")),
            ("EXACT_ALLOCATION_EMBEDDED", int(allocation_embedded)),
        ),
    )


def _strategy_design(
    sealed: SealedRedesignInputs,
    strategy: str,
    space: ActionSpace,
    progress: Callable[[str], None] | None,
) -> AbstractProductionDesign | None:
    """Exact-allocation optimum; A alone falls back to its least-deficient plan."""

    if progress is not None:
        progress(f"{strategy}:optimize:exact")
    exact = _design_from_model(
        sealed,
        strategy,
        _AllocationModel(sealed, space),
        STRATEGY_OBJECTIVES[strategy],
        allocation_embedded=True,
    )
    if exact is not None or strategy != "A":
        return exact
    if progress is not None:
        progress(f"{strategy}:optimize:relaxed")
    return _design_from_model(
        sealed,
        strategy,
        _CapacityModel(sealed, space),
        STRATEGY_OBJECTIVES[strategy],
        allocation_embedded=False,
    )


def is_exact_allocation_design(design: AbstractProductionDesign) -> bool:
    return dict(design.objective_trace).get("EXACT_ALLOCATION_EMBEDDED") == 1


def build_redesign(
    strategy: Strategy,
    sealed: SealedRedesignInputs,
    *,
    expected_fingerprint: str | None = None,
    progress: Callable[[str], None] | None = None,
    rejected_roots: frozenset[str] = frozenset(),
    removed_targets: frozenset[str] = frozenset(),
) -> AbstractProductionDesign | None:
    """Common interface: build the abstract design for CURRENT, A, B, or C."""

    if expected_fingerprint is not None and expected_fingerprint != sealed.authority_fingerprint:
        raise ValueError("RES-249 sealed authority fingerprint is stale")
    if strategy == "CURRENT":
        return materialize_plan(sealed, current_plan(sealed), strategy="CURRENT")
    if strategy in {"A", "B"}:
        space = action_space(
            strategy, sealed, rejected_roots=rejected_roots, removed_targets=removed_targets
        )
        return _strategy_design(sealed, strategy, space, progress)
    if strategy == "C":
        first = build_redesign(
            "A",
            sealed,
            progress=progress,
            rejected_roots=rejected_roots,
            removed_targets=removed_targets,
        )
        if first is None:
            return None
        if is_exact_allocation_design(first):
            # A already satisfies every hard constraint: no downstream action.
            return materialize_plan(
                sealed,
                first.plan,
                strategy="C",
                objective_trace=(*first.objective_trace, ("DOWNSTREAM_ACTIONS", 0)),
            )
        space = action_space(
            "C",
            sealed,
            baseline_roots=first.plan.roots,
            rejected_roots=rejected_roots,
            removed_targets=removed_targets,
        )
        return _strategy_design(sealed, "C", space, progress)
    raise ValueError(f"unknown RES-249 strategy {strategy}")


def operator_root_upper_bounds(sealed: SealedRedesignInputs) -> dict[str, dict[str, int]]:
    """Solver-free pigeonhole bound on roots each operator can place under R1.

    A root's component carries three same-cell children, so it can never serve
    Validation/Hidden. Cell X therefore keeps at most (semantic slots - roots)
    + fixed eligible components, and R1 needs >= 2, giving
    roots(X) <= semantic(X) + fixed(X) - 2 (and <= semantic(X)).
    """

    items = sealed.items
    semantic = Counter(
        _cell(item)
        for item in items.values()
        if item.origin_class is CaseOrigin.EXPERT_AUTHORED_SEMANTIC
    )
    fixed: Counter[Cell] = Counter()
    for component in _feasibility_clusters(
        sealed.commitments,
        exact_shingle_colocation_pairs=sealed.colocation_pairs,
        allow_incompatible_locks=True,
    ):
        if any(
            item.origin_class
            in {CaseOrigin.EXPERT_AUTHORED_SEMANTIC, CaseOrigin.ADVERSARIAL_MUTATION}
            for item in component.items
        ) or not protected_split_ranks(component):
            continue
        for item in component.items:
            if item_covers_own_cell(item):
                fixed[_cell(item)] += 1
    bounds: dict[str, dict[str, int]] = {}
    for spec in MUTATION_OPERATORS:
        cells = [cell for cell in semantic if spec.admits(*cell)]
        bound = sum(max(0, min(semantic[cell], semantic[cell] + fixed[cell] - 2)) for cell in cells)
        bounds[spec.operator_id] = {
            "required": spec.count,
            "upper_bound": bound,
            "admitted_cells": len(cells),
            "feasible_under_r1": int(bound >= spec.count),
        }
    return bounds


def first_unused_compatible_parent(
    sealed: SealedRedesignInputs, design: AbstractProductionDesign
) -> str:
    """Deterministic target parent to remove when a design adds no new parents."""

    used = {lineage.root_candidate_id for lineage in design.lineages}
    for cid in _sorted_ids(sealed.items):
        item = sealed.items[cid]
        if cid not in used and operator_for_root(item) is not None:
            return cid
    raise ValueError("no unused operator-compatible target parent exists")
