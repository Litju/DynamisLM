"""Exact, diagnostic selection geometry; never allocates production membership."""

from __future__ import annotations

import enum
from dataclasses import dataclass, replace
from importlib.metadata import version

from dynamislm.benchmark.authority_supply import (
    AdditionalCapacityStatus,
    AuthoritySupplyInventoryV1,
    ReserveCandidateLaneV1,
)
from dynamislm.benchmark.constants import SPLIT_ORDER, CaseOrigin, SplitName
from dynamislm.benchmark.production_authoring import PRODUCTION_SYNTHETIC_GENERATORS
from dynamislm.benchmark.selection_contracts import (
    AssignmentState,
    CandidateAssignment,
    ConstraintKind,
    FeatureKind,
    FinalSelectionPlan,
    FinalSelectionProblem,
    SelectionConstraint,
    SelectionFeature,
    SelectionSolverConfig,
    ValidationStatus,
)
from dynamislm.benchmark.selection_diagnostics import clone_selection_problem
from dynamislm.benchmark.selection_solver import _model_for, _solve_once
from dynamislm.benchmark.selection_validation import validate_final_selection
from dynamislm.serialization import canonical_hash, register_serializable_type


@register_serializable_type
@dataclass(frozen=True, slots=True)
class RepairGeometry:
    # Retain the complete typed problem, including identities, hyperedges and parents.
    problem: FinalSelectionProblem

    @property
    def geometry_digest(self) -> str:
        return canonical_hash(self)

    def constraints(self, kind: ConstraintKind) -> tuple[SelectionConstraint, ...]:
        return tuple(c for c in self.problem.constraint_set.constraints if c.kind is kind)


@register_serializable_type
@dataclass(frozen=True, slots=True)
class SplitCapacityCertificate:
    original_problem_digest: str
    original_constraint_inventory_digest: str
    active_constraint_inventory_digest: str
    relaxed_constraint_ids: tuple[str, ...]
    relaxation_definition: str
    split: SplitName
    required: int
    solver_config: SelectionSolverConfig
    solver_version: str
    optimality_status: str
    maximum: int
    witness: FinalSelectionPlan

    def __post_init__(self) -> None:
        object.__setattr__(self, "split", SplitName(self.split))
        if self.optimality_status != "OPTIMAL":
            raise ValueError("capacity requires exact OPTIMAL proof")
        if self.maximum < 0 or self.required < 0:
            raise ValueError("capacity counts must be nonnegative")
        if self.relaxed_constraint_ids != tuple(sorted(set(self.relaxed_constraint_ids))):
            raise ValueError("relaxed constraint IDs must be sorted and unique")

    @property
    def result_digest(self) -> str:
        return canonical_hash(self)


CAPACITY_RELAXATION = (
    "Remove ALL SPLIT_COUNT equalities: final count plus the other two equalities "
    "would fix the target by subtraction. Keep FINAL_COUNT and every other hard "
    "constraint except explicitly listed diagnostic ablations. Ignore soft objectives."
)
CAPACITY_SOLVER_CONFIG = SelectionSolverConfig(timeout_s=120.0)


def capacity_problem(
    geometry: RepairGeometry, ablate: tuple[ConstraintKind, ...] = ()
) -> FinalSelectionProblem:
    if any(
        k not in {ConstraintKind.CONDITIONAL_COLOCATION, ConstraintKind.FEATURE_MINIMUM}
        for k in ablate
    ):
        raise ValueError("unsupported capacity ablation")
    return clone_selection_problem(
        geometry.problem,
        (
            c
            for c in geometry.problem.constraint_set.constraints
            if c.kind not in (ConstraintKind.SPLIT_COUNT, *ablate)
        ),
    )


def compute_split_capacity_envelope(
    geometry: RepairGeometry,
    *,
    splits: tuple[SplitName, ...] = SPLIT_ORDER,
    ablate: tuple[ConstraintKind, ...] = (),
    solver_config: SelectionSolverConfig = CAPACITY_SOLVER_CONFIG,
) -> tuple[SplitCapacityCertificate, ...]:
    # V3 decodes a float-annotated timeout as float; bind its canonical representation.
    solver_config = replace(solver_config, timeout_s=float(solver_config.timeout_s))
    problem = geometry.problem
    active = capacity_problem(geometry, ablate)
    retained = {c.constraint_id for c in active.constraint_set.constraints}
    relaxed = tuple(
        sorted(
            c.constraint_id
            for c in problem.constraint_set.constraints
            if c.constraint_id not in retained
        )
    )
    certificates = []
    for split in splits:
        model, variables, _, _ = _model_for(active, include_objectives=False)
        state = AssignmentState(split.value)
        objective = sum(variables[c.candidate_id, state] for c in active.candidates)
        model.maximize(objective)
        solver, status, _ = _solve_once(model, solver_config)
        if status != "OPTIMAL":
            raise ValueError(f"{split.value} capacity has no exact OPTIMAL proof: {status}")
        maximum = int(solver.value(objective))
        if solver.best_objective_bound != maximum:
            raise ValueError("capacity OPTIMAL objective and bound disagree")
        plan = FinalSelectionPlan(
            assignments=tuple(
                CandidateAssignment(
                    c.candidate_id,
                    next(s for s in AssignmentState if solver.value(variables[c.candidate_id, s])),
                )
                for c in active.candidates
            ),
            authority_digest=active.authority_digest,
            problem_digest=active.problem_digest,
            approved_pool_digest=active.approved_pool_digest,
        )
        if validate_final_selection(active, plan).status is not ValidationStatus.VALID:
            raise ValueError("capacity witness failed independent validation")
        (requirement,) = (
            c.minimum for c in geometry.constraints(ConstraintKind.SPLIT_COUNT) if c.split is split
        )
        assert requirement is not None
        certificates.append(
            SplitCapacityCertificate(
                problem.problem_digest,
                problem.constraint_inventory_digest,
                active.constraint_inventory_digest,
                relaxed,
                CAPACITY_RELAXATION,
                split,
                requirement,
                solver_config,
                version("ortools"),
                status,
                maximum,
                plan,
            )
        )
    return tuple(certificates)


@register_serializable_type
@dataclass(frozen=True, slots=True)
class CoverageSupport:
    """Available support is raw pool incidence; selected support is the validated witness."""

    constraint_id: str
    required: int
    selected_support: int
    available_support: int
    lock_excluded_support: int
    intersecting_relation_count: int


@register_serializable_type
@dataclass(frozen=True, slots=True)
class StructuralBottleneckEvidence:
    capacity_certificate_digest: str
    required: int
    maximum: int
    capacity_deficit: int
    conditional_colocation_relation_count: int
    selected_count: int
    selected_locked_count: int
    coverage: tuple[CoverageSupport, ...]


def structural_bottleneck_evidence(
    geometry: RepairGeometry, certificate: SplitCapacityCertificate
) -> StructuralBottleneckEvidence:
    if certificate.original_problem_digest != geometry.problem.problem_digest:
        raise ValueError("capacity certificate belongs to another geometry")
    assignments = {a.candidate_id: a.state for a in certificate.witness.assignments}
    relaxed = set(certificate.relaxed_constraint_ids)
    relations = tuple(
        c
        for c in geometry.constraints(ConstraintKind.CONDITIONAL_COLOCATION)
        if c.constraint_id not in relaxed
    )
    rows = []
    for c in geometry.constraints(ConstraintKind.FEATURE_MINIMUM):
        if c.constraint_id in relaxed:
            continue
        support = tuple(x for x in geometry.problem.candidates if c.feature in x.features)
        ids = {x.candidate_id for x in support}
        assert c.minimum is not None and c.split is not None
        rows.append(
            CoverageSupport(
                c.constraint_id,
                c.minimum,
                sum(assignments[x.candidate_id] is AssignmentState(c.split.value) for x in support),
                len(support),
                sum(x.locked_split is not None and x.locked_split is not c.split for x in support),
                sum(bool(ids.intersection(r.candidate_ids)) for r in relations),
            )
        )
    selected = tuple(
        x
        for x in geometry.problem.candidates
        if assignments[x.candidate_id] is not AssignmentState.OUT
    )
    return StructuralBottleneckEvidence(
        certificate.result_digest,
        certificate.required,
        certificate.maximum,
        max(0, certificate.required - certificate.maximum),
        len(relations),
        len(selected),
        sum(x.locked_split is not None for x in selected),
        tuple(rows),
    )


class RepairClassification(enum.StrEnum):
    DIRECT_REPAIR_CAPABLE = "DIRECT_REPAIR_CAPABLE"
    INDIRECT_REPAIR_CAPABLE = "INDIRECT_REPAIR_CAPABLE"
    STRUCTURALLY_IRRELEVANT = "STRUCTURALLY_IRRELEVANT"
    UNRESOLVED = "UNRESOLVED"


@register_serializable_type
@dataclass(frozen=True, slots=True)
class RepairArchetype:
    lane_id: str
    origin: CaseOrigin
    cell: tuple[str, str]
    locked_split: SplitName | None
    guaranteed_features: tuple[SelectionFeature, ...]
    feature_behavior_complete: bool
    authority_ref: str
    authority_digest: str
    lane_digest: str
    identity_requirements: tuple[str, ...]
    relation_behavior_guarantee: str | None
    fresh_independent_identity_guaranteed: bool | None
    capacity_status: AdditionalCapacityStatus
    remaining_finite_capacity: int | None
    capacity_rule: str | None
    materializer_identity: str | None
    materializer_version: str | None
    materializer_contract: str | None
    currently_materializable: bool | None

    def __post_init__(self) -> None:
        if self.remaining_finite_capacity is not None and self.remaining_finite_capacity < 0:
            raise ValueError("remaining finite capacity cannot be negative")
        if self.capacity_status is AdditionalCapacityStatus.RULE_GOVERNED:
            if self.remaining_finite_capacity is not None or not self.capacity_rule:
                raise ValueError("rule-governed capacity is not concrete finite supply")


def remaining_lane_capacity(lane: ReserveCandidateLaneV1, consumed: int) -> int | None:
    if consumed < 0:
        raise ValueError("consumption cannot be negative")
    capacity = lane.additional_authorable_capacity
    return None if capacity is None else max(0, capacity - consumed)


def derive_governed_archetypes(
    inventory: AuthoritySupplyInventoryV1,
    consumed: tuple[tuple[str, int], ...],
) -> tuple[RepairArchetype, ...]:
    counts = dict(consumed)
    if (
        len(counts) != len(consumed)
        or any(n < 0 for n in counts.values())
        or set(counts) != {lane.lane_id for lane in inventory.reserve_candidate_lanes}
    ):
        raise ValueError("invalid lane consumption inventory")
    generators = {g.generator_family: g for g in PRODUCTION_SYNTHETIC_GENERATORS}
    result = []
    for lane in sorted(inventory.reserve_candidate_lanes, key=lambda x: x.lane_id):
        remaining = remaining_lane_capacity(lane, counts[lane.lane_id])
        if not lane.may_author_backfill or remaining == 0:
            continue
        generator = generators.get(lane.lane_id.removeprefix("synthetic:"))
        if generator is not None and canonical_hash(generator) != lane.authority_digest:
            raise ValueError("generator authority drift")
        split = None
        if generator is not None:
            (split,) = (
                s for s in SPLIT_ORDER if generator.generator_family.endswith(s.value.lower())
            )
        for cell in lane.supported_cells:
            result.append(
                RepairArchetype(
                    lane.lane_id,
                    lane.origin_class,
                    cell,
                    split,
                    (),
                    False,
                    lane.authority_ref,
                    lane.authority_digest,
                    lane.lane_digest,
                    lane.isolation_identity_digests,
                    # Shared split cluster is guaranteed; shingle collisions remain unknown.
                    "shared production synthetic split cluster; other relations unknown"
                    if generator is not None
                    else None,
                    False if generator is not None else None,
                    lane.additional_capacity_status,
                    remaining,
                    lane.capacity_rule,
                    generator.generator_id if generator else None,
                    generator.version if generator else None,
                    generator.output_contract if generator else None,
                    True if generator else None,
                )
            )
    return tuple(result)


@register_serializable_type
@dataclass(frozen=True, slots=True)
class ArchetypeRepairEvidence:
    geometry_digest: str
    archetype_inventory_digest: str
    classification: RepairClassification
    potentially_supported_coverage_ids: tuple[str, ...]
    unsupported_row_coverage_ids: tuple[str, ...]
    evidence: tuple[str, ...]


def classify_archetype_repair(
    geometry: RepairGeometry, archetypes: tuple[RepairArchetype, ...]
) -> ArchetypeRepairEvidence:
    registered = {
        (g.generator_id, g.version, g.output_contract) for g in PRODUCTION_SYNTHETIC_GENERATORS
    }
    if not archetypes or any(
        a.cell[0] != "C08"
        or a.origin is not CaseOrigin.DETERMINISTIC_SYNTHETIC
        or (a.materializer_identity, a.materializer_version, a.materializer_contract)
        not in registered
        for a in archetypes
    ):
        return ArchetypeRepairEvidence(
            geometry.geometry_digest,
            canonical_hash(archetypes),
            RepairClassification.UNRESOLVED,
            (),
            (),
            ("Behavior outside the evidenced C08 refusal contracts remains unknown.",),
        )
    capabilities = {a.cell[0] for a in archetypes}
    coverage = geometry.constraints(ConstraintKind.FEATURE_MINIMUM)
    potential = tuple(
        c.constraint_id
        for c in coverage
        if c.feature is not None
        and (
            c.feature.kind is FeatureKind.CRITICAL_ERROR
            or (c.feature.key and c.feature.key[0] in capabilities)
        )
    )
    unsupported = tuple(
        c.constraint_id
        for c in coverage
        if c.feature is not None
        and (
            c.feature.kind is FeatureKind.C18_REFUSAL
            or (
                c.feature.kind in {FeatureKind.CELL, FeatureKind.ROW_TAG, FeatureKind.ROW_ERROR}
                and c.feature.key[0] not in capabilities
            )
        )
    )
    return ArchetypeRepairEvidence(
        geometry.geometry_digest,
        canonical_hash(archetypes),
        RepairClassification.UNRESOLVED,
        potential,
        unsupported,
        (
            "Split-locked additions can occupy their own split and displace existing selections.",
            "C08 refusal supply cannot directly cover other capability rows or ANSWERABLE.",
            "Shared split clusters do not guarantee independent isolation; "
            "shingle relations unknown.",
            "Feature guarantees are incomplete: no concrete seed is extrapolated to a full domain.",
            "No augmentation proof establishes sufficient repair or impossibility; "
            "authority expansion remains unresolved.",
        ),
    )
