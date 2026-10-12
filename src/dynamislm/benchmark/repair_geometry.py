"""Exact, diagnostic selection geometry; never allocates production membership."""

from __future__ import annotations

import enum
from collections import defaultdict
from dataclasses import dataclass, replace
from importlib.metadata import version
from typing import Any

from dynamislm.benchmark.authority_supply import (
    AdditionalCapacityStatus,
    AuthoritySupplyInventoryV1,
    ReserveCandidateLaneV1,
)
from dynamislm.benchmark.constants import (
    CRITICAL_ERROR_CLASSES,
    SPLIT_ORDER,
    CaseOrigin,
    SplitName,
)
from dynamislm.benchmark.coverage import COVERAGE_MATRIX
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


@register_serializable_type
@dataclass(frozen=True, slots=True)
class SplitCapacityCertificateBinding:
    """Explicit semantic binding around the stable V3 capacity certificate."""

    original_problem_digest: str
    relaxed_constraint_ids: tuple[str, ...]
    retained_constraint_ids: tuple[str, ...]
    retained_constraint_inventory_digest: str
    final_count: int
    solver_config: SelectionSolverConfig
    solver_version: str
    objective: str
    objective_value: int
    objective_bound: int
    optimality_status: str
    result_digest: str
    binding_digest: str = ""

    def __post_init__(self) -> None:
        if self.relaxed_constraint_ids != tuple(sorted(set(self.relaxed_constraint_ids))):
            raise ValueError("relaxed constraint IDs must be sorted and unique")
        if self.retained_constraint_ids != tuple(sorted(set(self.retained_constraint_ids))):
            raise ValueError("retained constraint IDs must be sorted and unique")
        if not self.objective.startswith("MAXIMIZE_TARGET_SPLIT_COUNT:"):
            raise ValueError("capacity objective must name the target split count")
        if self.final_count < 0 or self.objective_value < 0:
            raise ValueError("capacity counts must be nonnegative")
        if self.optimality_status != "OPTIMAL" or self.objective_bound != self.objective_value:
            raise ValueError("capacity binding requires an exact optimality proof")
        digest = canonical_hash(
            {
                "original_problem_digest": self.original_problem_digest,
                "relaxed_constraint_ids": self.relaxed_constraint_ids,
                "retained_constraint_ids": self.retained_constraint_ids,
                "retained_constraint_inventory_digest": self.retained_constraint_inventory_digest,
                "final_count": self.final_count,
                "solver_config": self.solver_config,
                "solver_version": self.solver_version,
                "objective": self.objective,
                "objective_value": self.objective_value,
                "objective_bound": self.objective_bound,
                "optimality_status": self.optimality_status,
                "result_digest": self.result_digest,
            }
        )
        if self.binding_digest and self.binding_digest != digest:
            raise ValueError("capacity binding digest does not match its evidence")
        object.__setattr__(self, "binding_digest", digest)


def bind_split_capacity_certificate(
    geometry: RepairGeometry,
    certificate: SplitCapacityCertificate,
    *,
    ablate: tuple[ConstraintKind, ...] = (),
) -> SplitCapacityCertificateBinding:
    active = capacity_problem(geometry, ablate)
    if certificate.original_problem_digest != geometry.problem.problem_digest:
        raise ValueError("capacity certificate belongs to another problem")
    final_count = next(
        c.minimum
        for c in geometry.problem.constraint_set.constraints
        if c.kind is ConstraintKind.FINAL_COUNT
    )
    assert final_count is not None
    retained_ids = tuple(sorted(c.constraint_id for c in active.constraint_set.constraints))
    original_ids = {
        constraint.constraint_id for constraint in geometry.problem.constraint_set.constraints
    }
    expected_relaxed = tuple(sorted(original_ids - set(retained_ids)))
    if (
        certificate.relaxed_constraint_ids != expected_relaxed
        or certificate.active_constraint_inventory_digest != active.constraint_inventory_digest
    ):
        raise ValueError("capacity certificate does not bind the exact relaxed and retained sets")
    return SplitCapacityCertificateBinding(
        original_problem_digest=certificate.original_problem_digest,
        relaxed_constraint_ids=certificate.relaxed_constraint_ids,
        retained_constraint_ids=retained_ids,
        retained_constraint_inventory_digest=certificate.active_constraint_inventory_digest,
        final_count=final_count,
        solver_config=certificate.solver_config,
        solver_version=certificate.solver_version,
        objective=f"MAXIMIZE_TARGET_SPLIT_COUNT:{certificate.split.value}",
        objective_value=certificate.maximum,
        objective_bound=certificate.maximum,
        optimality_status=certificate.optimality_status,
        result_digest=certificate.result_digest,
    )


class ContractCertainty(enum.StrEnum):
    GUARANTEED = "GUARANTEED"
    BOUNDED = "BOUNDED"
    UNKNOWN = "UNKNOWN"


@register_serializable_type
@dataclass(frozen=True, slots=True)
class ArchetypeContractClaim:
    field: str
    certainty: ContractCertainty
    value: str
    evidence: str


@register_serializable_type
@dataclass(frozen=True, slots=True)
class ArchetypeStructuralContract:
    lane_id: str
    cell: tuple[str, str]
    claims: tuple[ArchetypeContractClaim, ...]
    contract_digest: str = ""

    def __post_init__(self) -> None:
        if tuple(claim.field for claim in self.claims) != tuple(
            sorted({claim.field for claim in self.claims}, key=str.encode)
        ):
            raise ValueError("archetype contract claims must be uniquely ordered")
        digest = canonical_hash({"lane_id": self.lane_id, "cell": self.cell, "claims": self.claims})
        if self.contract_digest and self.contract_digest != digest:
            raise ValueError("archetype structural contract digest mismatch")
        object.__setattr__(self, "contract_digest", digest)


def archetype_structural_contracts(
    geometry: RepairGeometry,
    archetypes: tuple[RepairArchetype, ...],
) -> tuple[ArchetypeStructuralContract, ...]:
    generators = {item.generator_family: item for item in PRODUCTION_SYNTHETIC_GENERATORS}
    contracts = []
    for archetype in archetypes:
        generator = generators.get(archetype.lane_id.removeprefix("synthetic:"))
        if generator is None:
            claims = (
                ArchetypeContractClaim(
                    "cell_binding",
                    ContractCertainty.GUARANTEED,
                    f"{archetype.cell[0]}:{archetype.cell[1]}",
                    "The governed lane explicitly lists this capability-family cell.",
                ),
                ArchetypeContractClaim(
                    "exact_feature_vector",
                    ContractCertainty.UNKNOWN,
                    "UNKNOWN",
                    "No registered generator contract resolves this archetype's feature vector.",
                ),
                ArchetypeContractClaim(
                    "interchangeability",
                    ContractCertainty.UNKNOWN,
                    "UNKNOWN",
                    "Repeated source-lane recipes have no shared structural output contract.",
                ),
                ArchetypeContractClaim(
                    "split_lock",
                    ContractCertainty.UNKNOWN,
                    "UNKNOWN",
                    "No exact generator family determines this archetype's split lock.",
                ),
                ArchetypeContractClaim(
                    "unique_fresh_isolation_identity",
                    ContractCertainty.UNKNOWN,
                    "UNKNOWN",
                    "The lane does not guarantee fresh independent isolation identities.",
                ),
                ArchetypeContractClaim(
                    "unique_seed_block_identity",
                    ContractCertainty.UNKNOWN,
                    "UNKNOWN",
                    "No registered generator seed-block contract applies.",
                ),
                ArchetypeContractClaim(
                    "relation_coupling_prior_candidates",
                    ContractCertainty.UNKNOWN,
                    "UNKNOWN",
                    "Relation overlap with current candidates is not established.",
                ),
                ArchetypeContractClaim(
                    "relation_coupling_repeated_instances",
                    ContractCertainty.UNKNOWN,
                    "UNKNOWN",
                    "Relation overlap between repeated instances is not established.",
                ),
                ArchetypeContractClaim(
                    "contamination_and_shingles",
                    ContractCertainty.UNKNOWN,
                    "UNKNOWN",
                    "Contamination and exact shingle behavior require materialized content.",
                ),
            )
        else:
            split = archetype.locked_split
            assert split is not None
            family_identity = any(
                identity.kind.value == "generator-family"
                and identity.identity == generator.generator_family
                for candidate in geometry.problem.candidates
                for identity in candidate.isolation_identities
            )
            cluster_id = f"PSE-V1-SYNTHETIC-CLUSTER:{split.value}"
            cluster_overlap = any(
                candidate.isolation_cluster_id == cluster_id
                for candidate in geometry.problem.candidates
            )
            prior_relation = (
                "PRESENT" if family_identity or cluster_overlap else "NO_KNOWN_IDENTITY_MATCH"
            )
            claims = (
                ArchetypeContractClaim(
                    "cell_binding",
                    ContractCertainty.GUARANTEED,
                    f"{archetype.cell[0]}:{archetype.cell[1]}",
                    "The governed lane explicitly lists this capability-family cell.",
                ),
                ArchetypeContractClaim(
                    "contamination_and_shingles",
                    ContractCertainty.UNKNOWN,
                    "UNKNOWN",
                    "No generated prose is available; exact shingle collisions are not ruled out.",
                ),
                ArchetypeContractClaim(
                    "exact_feature_vector",
                    ContractCertainty.UNKNOWN,
                    "UNKNOWN",
                    "The output contract promises a C08 refusal context, "
                    "not a complete feature vector.",
                ),
                ArchetypeContractClaim(
                    "interchangeability",
                    ContractCertainty.UNKNOWN,
                    "UNKNOWN",
                    "Feature and shingle behavior can vary with seed-block content.",
                ),
                ArchetypeContractClaim(
                    "relation_coupling_prior_candidates",
                    ContractCertainty.BOUNDED,
                    prior_relation,
                    "Known identity matches are checked against the pool; "
                    "shingle coupling remains unknown.",
                ),
                ArchetypeContractClaim(
                    "relation_coupling_repeated_instances",
                    ContractCertainty.GUARANTEED,
                    "SHARED_SPLIT_CLUSTER_AND_GENERATOR_FAMILY",
                    "The authoring path gives each instance this split cluster "
                    "and generator identity.",
                ),
                ArchetypeContractClaim(
                    "split_lock",
                    ContractCertainty.GUARANTEED,
                    split.value,
                    "The generator family and governed recipes require this split lock.",
                ),
                ArchetypeContractClaim(
                    "unique_fresh_isolation_identity",
                    ContractCertainty.GUARANTEED,
                    "FALSE; SHARED_SPLIT_AND_FAMILY_IDENTITIES",
                    "Fresh independence is false; repeated instances share split "
                    "and generator identities.",
                ),
                ArchetypeContractClaim(
                    "unique_seed_block_identity",
                    ContractCertainty.BOUNDED,
                    "UNIQUE_PER_AUTHORIZED_LANE_UNIT; REPEAT_COUNT_UNSPECIFIED",
                    "The lane requires unique blocks, but does not define a repeat count "
                    "or allocation sequence.",
                ),
            )
        contracts.append(
            ArchetypeStructuralContract(
                archetype.lane_id,
                archetype.cell,
                tuple(sorted(claims, key=lambda claim: claim.field.encode())),
            )
        )
    return tuple(sorted(contracts, key=lambda item: (item.lane_id.encode(), item.cell)))


@register_serializable_type
@dataclass(frozen=True, slots=True)
class RepairSignature:
    origin: CaseOrigin
    cell: tuple[str, str]
    guaranteed_features: tuple[SelectionFeature, ...]
    split_compatibility: tuple[SplitName, ...]
    relation_behavior: str
    isolation_identity_behavior: str
    lineage_behavior: str
    lane_id: str | None = None
    lane_capacity: int | None = None
    capacity_status: AdditionalCapacityStatus | None = None
    signature_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "origin", CaseOrigin(self.origin))
        object.__setattr__(
            self,
            "guaranteed_features",
            tuple(sorted(set(self.guaranteed_features), key=lambda f: (f.kind.value, f.key))),
        )
        object.__setattr__(
            self,
            "split_compatibility",
            tuple(s for s in SPLIT_ORDER if s in self.split_compatibility),
        )
        if not self.split_compatibility:
            raise ValueError("repair signature must support at least one split")
        if self.origin is CaseOrigin.DETERMINISTIC_SYNTHETIC and len(self.split_compatibility) != 1:
            raise ValueError("synthetic repair signatures must preserve one split lock")
        if self.lane_capacity is not None and self.lane_capacity < 0:
            raise ValueError("lane capacity cannot be negative")
        digest = canonical_hash(
            {
                "origin": self.origin,
                "cell": self.cell,
                "guaranteed_features": self.guaranteed_features,
                "split_compatibility": self.split_compatibility,
                "relation_behavior": self.relation_behavior,
                "isolation_identity_behavior": self.isolation_identity_behavior,
                "lineage_behavior": self.lineage_behavior,
                "lane_id": self.lane_id,
                "lane_capacity": self.lane_capacity,
                "capacity_status": self.capacity_status,
            }
        )
        if self.signature_id and self.signature_id != digest:
            raise ValueError("repair signature ID does not match its behavior")
        object.__setattr__(self, "signature_id", digest)


@register_serializable_type
@dataclass(frozen=True, slots=True)
class RepairSignatureCount:
    signature: RepairSignature
    split_counts: tuple[tuple[SplitName, int], ...]

    @property
    def total_count(self) -> int:
        return sum(count for _split, count in self.split_counts)


@register_serializable_type
@dataclass(frozen=True, slots=True)
class RepairMasterResult:
    status: str
    minimum_additions: int | None
    repair_vector: tuple[RepairSignatureCount, ...]
    solver_config: SelectionSolverConfig
    solver_version: str
    objective: str
    objective_bound: int | None
    geometry_digest: str
    signature_catalog_digest: str
    optimality_scope: str
    result_digest: str = ""

    def __post_init__(self) -> None:
        if self.status == "OPTIMAL":
            if self.minimum_additions is None or self.objective_bound != self.minimum_additions:
                raise ValueError("optimal repair result requires a matching objective bound")
        elif self.minimum_additions is not None or self.repair_vector:
            raise ValueError("non-optimal repair result cannot claim a minimum or repair vector")
        if tuple(item.signature.signature_id for item in self.repair_vector) != tuple(
            sorted(item.signature.signature_id for item in self.repair_vector)
        ):
            raise ValueError("repair vector must use deterministic signature ordering")
        digest = canonical_hash(
            {
                "status": self.status,
                "minimum_additions": self.minimum_additions,
                "repair_vector": self.repair_vector,
                "solver_config": self.solver_config,
                "solver_version": self.solver_version,
                "objective": self.objective,
                "objective_bound": self.objective_bound,
                "geometry_digest": self.geometry_digest,
                "signature_catalog_digest": self.signature_catalog_digest,
                "optimality_scope": self.optimality_scope,
            }
        )
        if self.result_digest and self.result_digest != digest:
            raise ValueError("repair master digest does not match its evidence")
        object.__setattr__(self, "result_digest", digest)


REPAIR_MASTER_SOLVER_CONFIG = SelectionSolverConfig(
    workers=1, random_seed=369, timeout_s=120.0, cp_model_presolve=True
)
_REPAIR_GLOBAL_CONSTRAINTS = {
    ConstraintKind.FINAL_COUNT,
    ConstraintKind.SPLIT_COUNT,
    ConstraintKind.FEATURE_MINIMUM,
    ConstraintKind.ORIGIN_BOUNDS,
    ConstraintKind.MUTATION_LINEAGE_MINIMUM,
}


def _signature(
    origin: CaseOrigin,
    cell: tuple[str, str],
    features: tuple[SelectionFeature, ...],
    splits: tuple[SplitName, ...],
    *,
    relation_behavior: str = "INDEPENDENT_FROM_BASE_AND_OTHER_ADDITIONS",
    lane_id: str | None = None,
    lane_capacity: int | None = None,
    capacity_status: AdditionalCapacityStatus | None = None,
) -> RepairSignature:
    return RepairSignature(
        origin=origin,
        cell=cell,
        guaranteed_features=features,
        split_compatibility=splits,
        relation_behavior=relation_behavior,
        isolation_identity_behavior="FRESH_UNIQUE",
        lineage_behavior=(
            "UNIQUE_PER_ADDITION_WITH_SAME_CELL_PARENT"
            if origin is CaseOrigin.ADVERSARIAL_MUTATION
            else "NOT_MUTATION"
        ),
        lane_id=lane_id,
        lane_capacity=lane_capacity,
        capacity_status=capacity_status,
    )


def _cell_feature_profiles(
    geometry: RepairGeometry,
) -> tuple[tuple[tuple[str, str], CaseOrigin, tuple[SelectionFeature, ...]], ...]:
    cells = tuple(
        sorted(
            {
                (constraint.feature.key[0], constraint.feature.key[1])
                for constraint in geometry.constraints(ConstraintKind.FEATURE_MINIMUM)
                if constraint.feature is not None and constraint.feature.kind is FeatureKind.CELL
            }
        )
    )
    rows = {row.capability_id: row for row in COVERAGE_MATRIX}
    profiles: list[tuple[tuple[str, str], CaseOrigin, tuple[SelectionFeature, ...]]] = []
    for cell in cells:
        capability, family = cell
        row = rows[capability]
        base = {
            SelectionFeature(FeatureKind.CELL, cell),
            *(
                SelectionFeature(FeatureKind.ROW_TAG, (capability, tag))
                for tag in row.adversarial_tags
            ),
            *(
                SelectionFeature(FeatureKind.ROW_ERROR, (capability, error.value))
                for error in row.error_classes
            ),
            *(
                SelectionFeature(FeatureKind.CRITICAL_ERROR, (error.value,))
                for error in row.error_classes
                if error in CRITICAL_ERROR_CLASSES
            ),
        }
        if capability == "C18":
            variants = (
                tuple(
                    sorted(
                        base | {SelectionFeature(FeatureKind.C18_REFUSAL, (family,))},
                        key=lambda feature: (feature.kind.value, feature.key),
                    )
                ),
                tuple(
                    sorted(
                        base | {SelectionFeature(FeatureKind.ANSWERABLE)},
                        key=lambda feature: (feature.kind.value, feature.key),
                    )
                ),
            )
        else:
            variants = (
                tuple(
                    sorted(
                        base | {SelectionFeature(FeatureKind.ANSWERABLE)},
                        key=lambda feature: (feature.kind.value, feature.key),
                    )
                ),
                tuple(sorted(base, key=lambda feature: (feature.kind.value, feature.key))),
            )
        for origin in sorted(row.case_origins, key=lambda item: item.value.encode()):
            # Current C08 synthetic authority is refusal-only; other origins retain both profiles.
            allowed = (
                variants[:1]
                if capability == "C08" and origin is CaseOrigin.DETERMINISTIC_SYNTHETIC
                else variants
            )
            profiles.extend((cell, origin, features) for features in allowed)
    return tuple(
        sorted(
            set(profiles),
            key=lambda item: (
                item[0],
                item[1].value.encode(),
                tuple((feature.kind.value, feature.key) for feature in item[2]),
            ),
        )
    )


def build_ideal_repair_signatures(geometry: RepairGeometry) -> tuple[RepairSignature, ...]:
    signatures = []
    for cell, origin, features in _cell_feature_profiles(geometry):
        split_options = (
            tuple((split,) for split in SPLIT_ORDER)
            if origin is CaseOrigin.DETERMINISTIC_SYNTHETIC
            else (SPLIT_ORDER,)
        )
        for splits in split_options:
            signatures.append(_signature(origin, cell, features, splits))
    return tuple(sorted(set(signatures), key=lambda item: item.signature_id))


def build_optimistic_c08_signatures(
    geometry: RepairGeometry,
    archetypes: tuple[RepairArchetype, ...],
) -> tuple[RepairSignature, ...]:
    del geometry  # All additions are bounded by current C08 lane authority and its feature rows.
    rows = {row.capability_id: row for row in COVERAGE_MATRIX}
    signatures = []
    for archetype in archetypes:
        if archetype.origin is not CaseOrigin.DETERMINISTIC_SYNTHETIC:
            continue
        row = rows.get(archetype.cell[0])
        if row is None or archetype.cell[0] != "C08" or archetype.locked_split is None:
            continue
        if archetype.capacity_status not in {
            AdditionalCapacityStatus.AVAILABLE,
            AdditionalCapacityStatus.RULE_GOVERNED,
        }:
            continue
        features = {
            SelectionFeature(FeatureKind.CELL, archetype.cell),
            *(SelectionFeature(FeatureKind.ROW_TAG, ("C08", tag)) for tag in row.adversarial_tags),
            *(
                SelectionFeature(FeatureKind.ROW_ERROR, ("C08", error.value))
                for error in row.error_classes
            ),
            *(
                SelectionFeature(FeatureKind.CRITICAL_ERROR, (error.value,))
                for error in row.error_classes
                if error in CRITICAL_ERROR_CLASSES
            ),
        }
        signatures.append(
            _signature(
                archetype.origin,
                archetype.cell,
                tuple(features),
                (archetype.locked_split,),
                relation_behavior="OPTIMISTICALLY_INDEPENDENT_RELAXATION",
                lane_id=archetype.lane_id,
                lane_capacity=archetype.remaining_finite_capacity,
                capacity_status=archetype.capacity_status,
            )
        )
    return tuple(sorted(set(signatures), key=lambda item: item.signature_id))


def solve_structural_repair_master(
    geometry: RepairGeometry,
    signatures: tuple[RepairSignature, ...],
    *,
    solver_config: SelectionSolverConfig = REPAIR_MASTER_SOLVER_CONFIG,
    optimality_scope: str,
) -> RepairMasterResult:
    """Minimize abstract structural additions against exact typed hard authority."""

    signatures = tuple(sorted(set(signatures), key=lambda item: item.signature_id))
    if not optimality_scope.strip():
        raise ValueError("repair master requires an explicit optimality scope")
    problem = geometry.problem
    final_n = next(
        constraint.minimum
        for constraint in problem.constraint_set.constraints
        if constraint.kind is ConstraintKind.FINAL_COUNT
    )
    assert final_n is not None
    local_problem = clone_selection_problem(
        problem,
        (
            constraint
            for constraint in problem.constraint_set.constraints
            if constraint.kind not in _REPAIR_GLOBAL_CONSTRAINTS
        ),
    )
    model, assignment_vars, _balance, _hash = _model_for(local_problem, include_objectives=False)
    by_signature_split: dict[tuple[str, SplitName], Any] = {}
    lane_groups: dict[str, list[Any]] = defaultdict(list)
    lane_capacities: dict[str, int | None] = {}
    for signature in signatures:
        cap = signature.lane_capacity
        if signature.lane_id is not None:
            if signature.lane_id in lane_capacities and lane_capacities[signature.lane_id] != cap:
                raise ValueError("archetypes in one lane disagree on remaining lane capacity")
            lane_capacities[signature.lane_id] = cap
        upper = min(final_n, final_n if cap is None else cap)
        for split in signature.split_compatibility:
            variable = model.new_int_var(
                0, upper, f"y[{signature.signature_id[:12]},{split.value}]"
            )
            by_signature_split[signature.signature_id, split] = variable
            if signature.lane_id is not None:
                lane_groups[signature.lane_id].append(variable)
    for lane_id, variables in lane_groups.items():
        capacity = lane_capacities[lane_id]
        if capacity is not None:
            model.add(sum(variables) <= capacity)

    def added(signature: RepairSignature, split: SplitName) -> Any:
        return by_signature_split.get((signature.signature_id, split), 0)

    additions = list(by_signature_split.values())
    model.add(sum(additions) <= final_n)
    candidates = problem.candidates
    placed_states = (
        AssignmentState.PUBLIC_DEVELOPMENT,
        AssignmentState.FROZEN_VALIDATION,
        AssignmentState.HIDDEN_FINAL,
    )
    global_constraints = tuple(
        constraint
        for constraint in problem.constraint_set.constraints
        if constraint.kind in _REPAIR_GLOBAL_CONSTRAINTS
    )
    for constraint in global_constraints:
        if constraint.kind is ConstraintKind.FINAL_COUNT:
            assert constraint.minimum is not None
            if constraint.maximum != constraint.minimum:
                raise ValueError("repair master requires an exact FINAL_COUNT equality")
            base_count = sum(
                assignment_vars[candidate.candidate_id, state]
                for candidate in candidates
                for state in placed_states
            )
            model.add(base_count + sum(additions) == constraint.minimum)
        elif constraint.kind is ConstraintKind.SPLIT_COUNT:
            assert constraint.split is not None and constraint.minimum is not None
            if constraint.maximum != constraint.minimum:
                raise ValueError("repair master requires exact SPLIT_COUNT equalities")
            state = AssignmentState(constraint.split.value)
            base_count = sum(
                assignment_vars[candidate.candidate_id, state] for candidate in candidates
            )
            add_count = sum(added(signature, constraint.split) for signature in signatures)
            model.add(base_count + add_count == constraint.minimum)
        elif constraint.kind is ConstraintKind.FEATURE_MINIMUM:
            assert constraint.split is not None and constraint.feature is not None
            base_count = sum(
                assignment_vars[candidate.candidate_id, AssignmentState(constraint.split.value)]
                for candidate in candidates
                if constraint.feature in candidate.features
            )
            add_count = sum(
                added(signature, constraint.split)
                for signature in signatures
                if constraint.feature in signature.guaranteed_features
            )
            assert constraint.minimum is not None
            model.add(base_count + add_count >= constraint.minimum)
            if constraint.maximum is not None:
                model.add(base_count + add_count <= constraint.maximum)
        elif constraint.kind is ConstraintKind.ORIGIN_BOUNDS:
            assert constraint.origin_class is not None and constraint.minimum is not None
            base_count = sum(
                assignment_vars[candidate.candidate_id, state]
                for candidate in candidates
                if candidate.origin_class is constraint.origin_class
                for state in placed_states
            )
            add_count = sum(
                added(signature, split)
                for signature in signatures
                if signature.origin is constraint.origin_class
                for split in signature.split_compatibility
            )
            model.add(base_count + add_count >= constraint.minimum)
            if constraint.maximum is not None:
                model.add(base_count + add_count <= constraint.maximum)
        elif constraint.kind is ConstraintKind.MUTATION_LINEAGE_MINIMUM:
            assert constraint.minimum is not None
            lineages: dict[str, list[Any]] = defaultdict(list)
            for candidate in candidates:
                if (
                    candidate.origin_class is CaseOrigin.ADVERSARIAL_MUTATION
                    and candidate.mutation_lineage_id is not None
                ):
                    lineages[candidate.mutation_lineage_id].extend(
                        assignment_vars[candidate.candidate_id, state] for state in placed_states
                    )
            lineage_vars = []
            for index, lineage_id in enumerate(sorted(lineages, key=str.encode)):
                members = lineages[lineage_id]
                present = model.new_bool_var(f"existing_lineage[{index}]")
                model.add(sum(members) >= 1).only_enforce_if(present)
                model.add(sum(members) == 0).only_enforce_if(present.Not())
                lineage_vars.append(present)
            new_lineages = []
            for signature in signatures:
                if signature.lineage_behavior != "UNIQUE_PER_ADDITION_WITH_SAME_CELL_PARENT":
                    continue
                for split in signature.split_compatibility:
                    mutation_count = added(signature, split)
                    parent_terms = [
                        assignment_vars[candidate.candidate_id, AssignmentState(split.value)]
                        for candidate in candidates
                        if candidate.cell == signature.cell
                    ]
                    parent_terms.extend(
                        added(parent_signature, split)
                        for parent_signature in signatures
                        if parent_signature.cell == signature.cell
                        and parent_signature.lineage_behavior == "NOT_MUTATION"
                        and split in parent_signature.split_compatibility
                    )
                    if parent_terms:
                        model.add(mutation_count <= final_n * sum(parent_terms))
                    else:
                        model.add(mutation_count == 0)
                    new_lineages.append(mutation_count)
            model.add(sum(lineage_vars) + sum(new_lineages) >= constraint.minimum)

    objective = sum(additions)
    model.minimize(objective)
    solver, status, _deterministic = _solve_once(model, solver_config)
    solver_version = version("ortools")
    minimum = None
    bound = None
    vector: tuple[RepairSignatureCount, ...] = ()
    if status == "OPTIMAL":
        minimum = int(solver.value(objective))
        bound = int(solver.best_objective_bound)
        if bound != minimum:
            raise ValueError("repair master OPTIMAL status has a non-matching objective bound")
        counts = []
        for signature in signatures:
            split_counts = tuple(
                (split, int(solver.value(added(signature, split))))
                for split in signature.split_compatibility
                if solver.value(added(signature, split))
            )
            if split_counts:
                counts.append(RepairSignatureCount(signature, split_counts))
        vector = tuple(sorted(counts, key=lambda item: item.signature.signature_id))
    normalized_status = {
        "OPTIMAL": "OPTIMAL",
        "INFEASIBLE": "INFEASIBLE",
        "FEASIBLE": "FEASIBLE_NOT_OPTIMAL",
    }.get(status, "UNKNOWN")
    return RepairMasterResult(
        status=normalized_status,
        minimum_additions=minimum,
        repair_vector=vector,
        solver_config=solver_config,
        solver_version=solver_version,
        objective="MINIMIZE_TOTAL_ADDED_STRUCTURAL_UNITS",
        objective_bound=bound,
        geometry_digest=geometry.geometry_digest,
        signature_catalog_digest=canonical_hash(signatures),
        optimality_scope=optimality_scope,
    )


@register_serializable_type
@dataclass(frozen=True, slots=True)
class MissingGovernedCapability:
    capability_kind: str
    required_behavior: str
    current_behavior: str
    ideal_signature_ids: tuple[str, ...]


def compare_ideal_to_governed_c08(
    ideal: RepairMasterResult,
    archetypes: tuple[RepairArchetype, ...],
) -> tuple[MissingGovernedCapability, ...]:
    if ideal.status != "OPTIMAL":
        return ()
    rows: dict[tuple[str, str, str], set[str]] = {}

    def add(kind: str, required: str, current: str, signature_id: str) -> None:
        rows.setdefault((kind, required, current), set()).add(signature_id)

    current_cells = {item.cell for item in archetypes}
    current_origins = {item.origin for item in archetypes}
    current_features = {feature for item in archetypes for feature in item.guaranteed_features}
    for item in ideal.repair_vector:
        signature = item.signature
        if signature.cell not in current_cells:
            add(
                "CELL_SUPPORT",
                f"CELL:{signature.cell[0]}:{signature.cell[1]}",
                "C08_ONLY",
                signature.signature_id,
            )
        if signature.origin not in current_origins:
            add(
                "ORIGIN",
                signature.origin.value,
                "DETERMINISTIC_SYNTHETIC_ONLY",
                signature.signature_id,
            )
        for feature in signature.guaranteed_features:
            if feature not in current_features:
                add(
                    "GUARANTEED_FEATURE",
                    f"{feature.kind.value}:{':'.join(feature.key)}",
                    "UNKNOWN_OR_NOT_GUARANTEED",
                    signature.signature_id,
                )
        compatible = {
            split
            for archetype in archetypes
            if archetype.cell == signature.cell and archetype.origin is signature.origin
            for split in (archetype.locked_split,)
            if split is not None
        }
        if set(signature.split_compatibility) - compatible:
            add(
                "SPLIT_COMPATIBILITY",
                ",".join(split.value for split in signature.split_compatibility),
                ",".join(split.value for split in sorted(compatible, key=lambda s: s.value))
                or "NO_MATCHING_ARCHETYPE",
                signature.signature_id,
            )
        if signature.isolation_identity_behavior == "FRESH_UNIQUE" and any(
            archetype.fresh_independent_identity_guaranteed is not True
            for archetype in archetypes
            if archetype.cell == signature.cell
        ):
            add(
                "ISOLATION_IDENTITY",
                "FRESH_UNIQUE_INDEPENDENT",
                "SHARED_SPLIT_CLUSTER; FRESH_INDEPENDENCE_NOT_GUARANTEED",
                signature.signature_id,
            )
        if signature.lineage_behavior == "UNIQUE_PER_ADDITION_WITH_SAME_CELL_PARENT":
            add(
                "MUTATION_LINEAGE",
                "UNIQUE_LINEAGE_WITH_VALID_SAME_CELL_PARENT",
                "NO_GOVERNED_C08_MUTATION_LANE",
                signature.signature_id,
            )
        if signature.relation_behavior == "INDEPENDENT_FROM_BASE_AND_OTHER_ADDITIONS":
            add(
                "RELATION_BEHAVIOR",
                "NO_COLOCATION_OR_SHINGLE_COUPLING",
                "SPLIT_CLUSTER_COUPLING_GUARANTEED; SHINGLE_BEHAVIOR_UNKNOWN",
                signature.signature_id,
            )
    return tuple(
        MissingGovernedCapability(kind, required, current, tuple(sorted(ids)))
        for (kind, required, current), ids in sorted(rows.items())
    )


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
