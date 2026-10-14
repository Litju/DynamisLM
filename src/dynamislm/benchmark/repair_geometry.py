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
    POOL_FEASIBILITY_SOLVER_PROFILE_VERSION,
    PSE_V1_POOL_FEASIBILITY_SOLVER_PROFILE_V1,
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
class ArchetypeSaturationBound:
    signature_id: str
    lane_id: str
    cell: tuple[str, str]
    origin: CaseOrigin
    split: SplitName
    upper_bound: int
    limits: tuple[tuple[str, int], ...]


def derive_archetype_saturation_bounds(
    geometry: RepairGeometry,
    signatures: tuple[RepairSignature, ...],
) -> tuple[ArchetypeSaturationBound, ...]:
    constraints = geometry.problem.constraint_set.constraints
    final_n = next(
        constraint.minimum
        for constraint in constraints
        if constraint.kind is ConstraintKind.FINAL_COUNT
    )
    assert final_n is not None
    split_maxima = {
        constraint.split: constraint.maximum
        for constraint in constraints
        if constraint.kind is ConstraintKind.SPLIT_COUNT
    }
    origin_maxima = {
        constraint.origin_class: constraint.maximum
        for constraint in constraints
        if constraint.kind is ConstraintKind.ORIGIN_BOUNDS
    }
    feature_maxima = tuple(
        constraint
        for constraint in constraints
        if constraint.kind is ConstraintKind.FEATURE_MINIMUM and constraint.maximum is not None
    )
    bounds = []
    for signature in signatures:
        if len(signature.split_compatibility) != 1:
            raise ValueError("per-archetype saturation requires one split-locked signature")
        (split,) = signature.split_compatibility
        limits = [("FINAL_COUNT", final_n)]
        split_maximum = split_maxima.get(split)
        if split_maximum is not None:
            limits.append((f"SPLIT_COUNT:{split.value}", split_maximum))
        origin_maximum = origin_maxima.get(signature.origin)
        if origin_maximum is not None:
            limits.append((f"ORIGIN_MAXIMUM:{signature.origin.value}", origin_maximum))
        if signature.lane_capacity is not None:
            limits.append((f"LANE_CAPACITY:{signature.lane_id}", signature.lane_capacity))
        for constraint in feature_maxima:
            if constraint.split is split and constraint.feature in signature.guaranteed_features:
                assert constraint.maximum is not None
                limits.append((f"FEATURE_MAXIMUM:{constraint.constraint_id}", constraint.maximum))
        upper_bound = min(limit for _name, limit in limits)
        if upper_bound < 0:
            raise ValueError("archetype saturation bound cannot be negative")
        bounds.append(
            ArchetypeSaturationBound(
                signature_id=signature.signature_id,
                lane_id=signature.lane_id or "",
                cell=signature.cell,
                origin=signature.origin,
                split=split,
                upper_bound=upper_bound,
                limits=tuple(sorted(limits, key=lambda item: item[0].encode())),
            )
        )
    return tuple(sorted(bounds, key=lambda item: item.signature_id))


@register_serializable_type
@dataclass(frozen=True, slots=True)
class RepairMasterDiagnostics:
    model_variable_count: int
    boolean_variable_count: int
    integer_variable_count: int
    constraint_count: int
    objective_term_count: int
    solver_status: str
    feasible_incumbent_present: bool
    incumbent_addition_count: int | None
    best_objective_bound: float | None
    absolute_gap: float | None
    conflicts: int
    branches: int
    restarts: int
    wall_seconds: float
    deterministic_time: float
    unknown_classification: str | None
    solver_profile_version: str = "UNVERSIONED"
    source_relation_constraint_count: int = 0
    unique_relation_member_set_count: int = 0
    redundant_relation_constraints_removed: int = 0
    relation_compaction_digest: str = ""


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
    solver_diagnostics: RepairMasterDiagnostics | None = None
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


@register_serializable_type
@dataclass(frozen=True, slots=True)
class RepairCardinalityTrial:
    maximum_additions: int
    status: str
    solver_profile_version: str
    solver_config: SelectionSolverConfig
    solver_version: str
    geometry_digest: str
    signature_inventory_digest: str
    diagnostics: RepairMasterDiagnostics | None
    minimum_additions: int = 0
    witness: tuple[RepairSignatureCount, ...] = ()
    lower_bound_source_trial_digest: str | None = None
    proof_source_schema: str | None = None
    proof_source_digest: str | None = None
    proof_source_problem_digest: str | None = None
    proof_source_constraint_inventory_digest: str | None = None
    proof_source_status: str | None = None
    proof_source_method: str | None = None
    hint_source_trial_digest: str | None = None
    trial_digest: str = ""

    def __post_init__(self) -> None:
        if self.maximum_additions < 0 or self.status not in {"FEASIBLE", "INFEASIBLE", "UNKNOWN"}:
            raise ValueError("invalid structural cardinality decision trial")
        if not 0 <= self.minimum_additions <= self.maximum_additions:
            raise ValueError("invalid structural cardinality interval")
        if (self.minimum_additions == 0) != (self.lower_bound_source_trial_digest is None):
            raise ValueError("positive cardinality lower bounds require their infeasibility proof")
        if self.status == "FEASIBLE":
            if self.diagnostics is None or not self.diagnostics.feasible_incumbent_present:
                raise ValueError("feasible cardinality trial requires a solver witness")
            if self.diagnostics.solver_status not in {"FEASIBLE", "OPTIMAL"}:
                raise ValueError("feasible cardinality trial has a non-feasible solver status")
            if (
                sum(item.total_count for item in self.witness)
                != self.diagnostics.incumbent_addition_count
                or sum(item.total_count for item in self.witness) < self.minimum_additions
                or sum(item.total_count for item in self.witness) > self.maximum_additions
            ):
                raise ValueError("feasible cardinality trial witness does not match its budget")
        if self.status != "FEASIBLE" and self.witness:
            raise ValueError("non-feasible cardinality trial cannot contain a repair witness")
        if self.status == "INFEASIBLE":
            if self.diagnostics is not None and self.diagnostics.solver_status != "INFEASIBLE":
                raise ValueError(
                    "infeasible cardinality trial requires an exact infeasibility proof"
                )
            if self.diagnostics is None and not all(
                (
                    self.maximum_additions == 0,
                    self.proof_source_schema,
                    self.proof_source_digest,
                    self.proof_source_problem_digest,
                    self.proof_source_constraint_inventory_digest,
                    self.proof_source_status == "INFEASIBLE",
                    self.proof_source_method == "EXACT_FEASIBILITY_ORACLE",
                )
            ):
                raise ValueError("inherited infeasibility proof lacks exact source bindings")
        elif self.status == "UNKNOWN" and (
            self.diagnostics is None or self.diagnostics.solver_status != "UNKNOWN"
        ):
            raise ValueError("unknown cardinality trial must retain its UNKNOWN solver response")
        elif self.diagnostics is None:
            raise ValueError("only inherited zero-addition infeasibility may omit diagnostics")
        digest = canonical_hash(
            {
                "maximum_additions": self.maximum_additions,
                "minimum_additions": self.minimum_additions,
                "status": self.status,
                "solver_profile_version": self.solver_profile_version,
                "solver_config": self.solver_config,
                "solver_version": self.solver_version,
                "geometry_digest": self.geometry_digest,
                "signature_inventory_digest": self.signature_inventory_digest,
                "diagnostics": self.diagnostics,
                "witness": self.witness,
                "lower_bound_source_trial_digest": self.lower_bound_source_trial_digest,
                "proof_source_schema": self.proof_source_schema,
                "proof_source_digest": self.proof_source_digest,
                "proof_source_problem_digest": self.proof_source_problem_digest,
                "proof_source_constraint_inventory_digest": (
                    self.proof_source_constraint_inventory_digest
                ),
                "proof_source_status": self.proof_source_status,
                "proof_source_method": self.proof_source_method,
                "hint_source_trial_digest": self.hint_source_trial_digest,
            }
        )
        if self.trial_digest and self.trial_digest != digest:
            raise ValueError("cardinality trial digest does not match its evidence")
        object.__setattr__(self, "trial_digest", digest)


@register_serializable_type
@dataclass(frozen=True, slots=True)
class IdealRepairCardinalityResult:
    status: str
    minimum_additions: int | None
    repair_vector: tuple[RepairSignatureCount, ...]
    profile_version: str
    solver_config: SelectionSolverConfig
    solver_version: str
    signature_count: int
    signature_inventory_digest: str
    geometry_digest: str
    model_is_relaxation: bool
    relaxation_definition: str
    trials: tuple[RepairCardinalityTrial, ...]
    lower_proof: RepairCardinalityTrial | None
    upper_proof: RepairCardinalityTrial | None
    optimality_scope: str
    result_digest: str = ""

    def __post_init__(self) -> None:
        if self.status not in {"OPTIMAL", "INFEASIBLE", "UNKNOWN"}:
            raise ValueError("invalid ideal repair cardinality result status")
        if not self.model_is_relaxation or not self.relaxation_definition:
            raise ValueError("ideal repair cardinality model must declare its relaxation")
        trials_by_digest = {trial.trial_digest: trial for trial in self.trials}
        if len(trials_by_digest) != len(self.trials):
            raise ValueError("ideal cardinality search contains duplicate trial receipts")
        for trial in self.trials:
            if trial.minimum_additions == 0:
                continue
            source = trials_by_digest.get(trial.lower_bound_source_trial_digest or "")
            if (
                source is None
                or source.status != "INFEASIBLE"
                or source.maximum_additions != trial.minimum_additions - 1
                or source.geometry_digest != trial.geometry_digest
                or source.signature_inventory_digest != trial.signature_inventory_digest
            ):
                raise ValueError("cardinality trial lower bound lacks its retained proof chain")
        if self.status == "OPTIMAL":
            if (
                self.lower_proof is not None
                and self.lower_proof.trial_digest not in trials_by_digest
            ) or (
                self.upper_proof is not None
                and self.upper_proof.trial_digest not in trials_by_digest
            ):
                raise ValueError("optimality receipts must be retained in the trial inventory")
            if self.minimum_additions is None or self.upper_proof is None:
                raise ValueError(
                    "optimal cardinality result requires its minimum and feasible proof"
                )
            if self.upper_proof.status != "FEASIBLE" or (
                self.upper_proof.maximum_additions != self.minimum_additions
            ):
                raise ValueError("optimal cardinality upper proof does not match the minimum")
            if self.minimum_additions == 0:
                if self.lower_proof is not None:
                    raise ValueError("zero minimum uses the nonnegative-domain lower proof")
            elif (
                self.lower_proof is None
                or self.lower_proof.status != "INFEASIBLE"
                or self.lower_proof.maximum_additions != self.minimum_additions - 1
            ):
                raise ValueError("optimal cardinality lower proof must establish K-1 infeasible")
            if sum(item.total_count for item in self.repair_vector) != self.minimum_additions:
                raise ValueError("canonical ideal witness does not contain exactly K additions")
        elif self.minimum_additions is not None or self.repair_vector:
            raise ValueError("non-optimal cardinality result cannot claim a minimum or vector")
        if self.status == "INFEASIBLE" and (
            self.lower_proof is None
            or self.lower_proof.status != "INFEASIBLE"
            or self.upper_proof is not None
        ):
            raise ValueError("infeasible ideal result requires a terminal infeasible proof")
        digest = canonical_hash(
            {
                "status": self.status,
                "minimum_additions": self.minimum_additions,
                "repair_vector": self.repair_vector,
                "profile_version": self.profile_version,
                "solver_config": self.solver_config,
                "solver_version": self.solver_version,
                "signature_count": self.signature_count,
                "signature_inventory_digest": self.signature_inventory_digest,
                "geometry_digest": self.geometry_digest,
                "model_is_relaxation": self.model_is_relaxation,
                "relaxation_definition": self.relaxation_definition,
                "trials": self.trials,
                "lower_proof": self.lower_proof,
                "upper_proof": self.upper_proof,
                "optimality_scope": self.optimality_scope,
            }
        )
        if self.result_digest and self.result_digest != digest:
            raise ValueError("ideal cardinality result digest does not match its evidence")
        object.__setattr__(self, "result_digest", digest)

    @property
    def model_variable_count(self) -> int | None:
        diagnostic = next(
            (trial.diagnostics for trial in reversed(self.trials) if trial.diagnostics is not None),
            None,
        )
        return None if diagnostic is None else diagnostic.model_variable_count

    @property
    def model_constraint_count(self) -> int | None:
        diagnostic = next(
            (trial.diagnostics for trial in reversed(self.trials) if trial.diagnostics is not None),
            None,
        )
        return None if diagnostic is None else diagnostic.constraint_count

    @property
    def cardinality_optimality(self) -> str:
        return "PROVEN" if self.status == "OPTIMAL" else "NOT_PROVEN"

    @property
    def ideal_repair_digest(self) -> str:
        return canonical_hash(
            {
                "schema": "RES407-IDEAL-REPAIR-WITNESS@1.0.0",
                "status": self.status,
                "geometry_digest": self.geometry_digest,
                "signature_inventory_digest": self.signature_inventory_digest,
                "minimum_additions": self.minimum_additions,
                "repair_vector": self.repair_vector,
                "optimality_scope": self.optimality_scope,
            }
        )


REPAIR_MASTER_SOLVER_CONFIG = SelectionSolverConfig(
    workers=1, random_seed=369, timeout_s=120.0, cp_model_presolve=True
)
RES407_STRUCTURAL_REPAIR_MASTER_PROFILE_VERSION = "RES407-STRUCTURAL-REPAIR-MASTER@1.0.0"
RES407_STRUCTURAL_REPAIR_MASTER_PROFILE_V1 = SelectionSolverConfig(
    workers=8, random_seed=369, timeout_s=300.0, cp_model_presolve=True
)
IDEAL_REPAIR_IS_RELAXATION = True
IDEAL_REPAIR_RELAXATION_DEFINITION = (
    "Typed maximum feature support per authorized cell/origin, flexible non-synthetic splits, "
    "fresh independent identity, no new colocation or contamination edges; existing 449 "
    "candidates and all hard benchmark rules remain exact."
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
    isolation_identity_behavior: str = "FRESH_UNIQUE",
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
        isolation_identity_behavior=isolation_identity_behavior,
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
    signatures: list[RepairSignature] = []
    for cell, origin, features in _cell_feature_profiles(geometry):
        split_options = (
            tuple((split,) for split in SPLIT_ORDER)
            if origin is CaseOrigin.DETERMINISTIC_SYNTHETIC
            else (SPLIT_ORDER,)
        )
        for splits in split_options:
            signatures.append(_signature(origin, cell, features, splits))
    return tuple(sorted(set(signatures), key=lambda item: item.signature_id))


def build_compact_ideal_repair_signatures(
    geometry: RepairGeometry,
) -> tuple[RepairSignature, ...]:
    """Build maximal, canonical feature signatures without dominated answerability variants."""

    answerable_has_maximum = any(
        constraint.feature == SelectionFeature(FeatureKind.ANSWERABLE)
        and constraint.maximum is not None
        for constraint in geometry.constraints(ConstraintKind.FEATURE_MINIMUM)
    )
    signatures: list[RepairSignature] = []
    for cell, origin, features in _cell_feature_profiles(geometry):
        capability = cell[0]
        if (
            capability != "C18"
            and origin is not CaseOrigin.DETERMINISTIC_SYNTHETIC
            and not answerable_has_maximum
            and SelectionFeature(FeatureKind.ANSWERABLE) not in features
        ):
            continue
        splits = (
            tuple((split,) for split in SPLIT_ORDER)
            if origin is CaseOrigin.DETERMINISTIC_SYNTHETIC
            else (SPLIT_ORDER,)
        )
        signatures.extend(_signature(origin, cell, features, allowed) for allowed in splits)
    return tuple(sorted(set(signatures), key=lambda item: item.signature_id))


@dataclass(slots=True)
class _StructuralRepairModel:
    geometry: RepairGeometry
    model: Any
    assignments: dict[tuple[str, AssignmentState], Any]
    additions: dict[str, Any]
    recourse: dict[tuple[str, SplitName], Any]
    signatures: tuple[RepairSignature, ...]
    final_n: int
    source_relation_constraint_count: int
    unique_relation_member_set_count: int
    relation_compaction_digest: str
    assignment_hint: tuple[tuple[str, AssignmentState], ...] = ()
    repair_hint: tuple[RepairSignatureCount, ...] = ()
    hint_source_trial_digest: str | None = None


def _structural_repair_model(
    geometry: RepairGeometry,
    signatures: tuple[RepairSignature, ...],
    *,
    signature_upper_bounds: dict[str, int] | None = None,
) -> _StructuralRepairModel:
    signatures = tuple(sorted(set(signatures), key=lambda item: item.signature_id))
    problem = geometry.problem
    final_n = next(
        constraint.minimum
        for constraint in problem.constraint_set.constraints
        if constraint.kind is ConstraintKind.FINAL_COUNT
    )
    assert final_n is not None
    signature_upper_bounds = signature_upper_bounds or {}
    if set(signature_upper_bounds) - {item.signature_id for item in signatures} or any(
        bound < 0 or bound > final_n for bound in signature_upper_bounds.values()
    ):
        raise ValueError("signature saturation bounds do not match this structural model")
    source_relations = geometry.constraints(ConstraintKind.CONDITIONAL_COLOCATION)
    relation_classes: dict[tuple[str, ...], list[str]] = defaultdict(list)
    for relation in source_relations:
        relation_classes[relation.candidate_ids].append(relation.constraint_id)
    maximal_relation_sets: set[tuple[str, ...]] = {
        members
        for members in relation_classes
        if not any(frozenset(members) < frozenset(other) for other in relation_classes)
    }
    relation_compaction_digest = canonical_hash(
        {
            "source_classes": tuple(
                (members, tuple(sorted(ids, key=str.encode)))
                for members, ids in sorted(relation_classes.items())
            ),
            "retained_maximal_member_sets": tuple(sorted(maximal_relation_sets)),
            "equivalence": "A conditional-colocation superset subsumes every member subset.",
        }
    )
    seen_relation_sets: set[tuple[str, ...]] = set()
    local_constraints = []
    for constraint in problem.constraint_set.constraints:
        if constraint.kind in _REPAIR_GLOBAL_CONSTRAINTS:
            continue
        if constraint.kind is ConstraintKind.CONDITIONAL_COLOCATION:
            if constraint.candidate_ids not in maximal_relation_sets:
                continue
            if constraint.candidate_ids in seen_relation_sets:
                continue
            seen_relation_sets.add(constraint.candidate_ids)
        local_constraints.append(constraint)
    local_problem = clone_selection_problem(problem, local_constraints)
    model, assignments, _balance, _hash = _model_for(
        local_problem,
        include_objectives=False,
        compact_colocation_indicators=True,
        compact_candidate_states=True,
    )
    additions: dict[str, Any] = {}
    recourse: dict[tuple[str, SplitName], Any] = {}
    lane_capacities: dict[str, int | None] = {}
    for signature in signatures:
        cap = signature.lane_capacity
        if signature.lane_id is not None:
            prior = lane_capacities.setdefault(signature.lane_id, cap)
            if prior != cap:
                raise ValueError("archetypes in one lane disagree on remaining lane capacity")
        upper = min(
            final_n,
            final_n if cap is None else cap,
            signature_upper_bounds.get(signature.signature_id, final_n),
        )
        addition = model.new_int_var(0, upper, f"y[{signature.signature_id[:12]}]")
        additions[signature.signature_id] = addition
        split_counts = []
        for split in SPLIT_ORDER:
            compatible = split in signature.split_compatibility
            allocation = model.new_int_var(
                0,
                upper if compatible else 0,
                f"z[{signature.signature_id[:12]},{split.value}]",
            )
            recourse[signature.signature_id, split] = allocation
            split_counts.append(allocation)
            if not compatible:
                model.add(allocation == 0)
        # This bound follows from nonnegative z and sum(z) <= y below.
        model.add(sum(split_counts) <= addition)
        # Base-only independent units with no selected placement can be deleted from y.
        model.add(addition <= sum(split_counts))
    for lane_id, capacity in lane_capacities.items():
        if capacity is not None:
            model.add(
                sum(
                    additions[signature.signature_id]
                    for signature in signatures
                    if signature.lane_id == lane_id
                )
                <= capacity
            )
    model.add(sum(additions.values()) <= final_n)

    candidates = problem.candidates
    placed_states = (
        AssignmentState.PUBLIC_DEVELOPMENT,
        AssignmentState.FROZEN_VALIDATION,
        AssignmentState.HIDDEN_FINAL,
    )
    for signature in signatures:
        if signature.lineage_behavior != "UNIQUE_PER_ADDITION_WITH_SAME_CELL_PARENT":
            continue
        for split in SPLIT_ORDER:
            mutation_count = recourse[signature.signature_id, split]
            parent_terms = [
                assignments[candidate.candidate_id, AssignmentState(split.value)]
                for candidate in candidates
                if candidate.cell == signature.cell
            ]
            parent_terms.extend(
                recourse[parent_signature.signature_id, split]
                for parent_signature in signatures
                if parent_signature.cell == signature.cell
                and parent_signature.lineage_behavior == "NOT_MUTATION"
            )
            if parent_terms:
                model.add(mutation_count <= final_n * sum(parent_terms))
            else:
                model.add(mutation_count == 0)

    for constraint in problem.constraint_set.constraints:
        if constraint.kind is ConstraintKind.FINAL_COUNT:
            assert constraint.minimum is not None
            if constraint.maximum != constraint.minimum:
                raise ValueError("repair master requires an exact FINAL_COUNT equality")
            model.add(
                sum(
                    assignments[candidate.candidate_id, split]
                    for candidate in candidates
                    for split in placed_states
                )
                + sum(recourse.values())
                == constraint.minimum
            )
        elif constraint.kind is ConstraintKind.SPLIT_COUNT:
            assert constraint.split is not None and constraint.minimum is not None
            if constraint.maximum != constraint.minimum:
                raise ValueError("repair master requires exact SPLIT_COUNT equalities")
            state = AssignmentState(constraint.split.value)
            model.add(
                sum(assignments[candidate.candidate_id, state] for candidate in candidates)
                + sum(
                    recourse[signature.signature_id, constraint.split] for signature in signatures
                )
                == constraint.minimum
            )
        elif constraint.kind is ConstraintKind.FEATURE_MINIMUM:
            assert constraint.split is not None and constraint.feature is not None
            base_count = sum(
                assignments[candidate.candidate_id, AssignmentState(constraint.split.value)]
                for candidate in candidates
                if constraint.feature in candidate.features
            )
            repair_count = sum(
                recourse[signature.signature_id, constraint.split]
                for signature in signatures
                if constraint.feature in signature.guaranteed_features
            )
            assert constraint.minimum is not None
            model.add(base_count + repair_count >= constraint.minimum)
            if constraint.maximum is not None:
                model.add(base_count + repair_count <= constraint.maximum)
        elif constraint.kind is ConstraintKind.ORIGIN_BOUNDS:
            assert constraint.origin_class is not None and constraint.minimum is not None
            base_count = sum(
                assignments[candidate.candidate_id, split]
                for candidate in candidates
                if candidate.origin_class is constraint.origin_class
                for split in placed_states
            )
            repair_count = sum(
                recourse[signature.signature_id, split]
                for signature in signatures
                if signature.origin is constraint.origin_class
                for split in SPLIT_ORDER
            )
            model.add(base_count + repair_count >= constraint.minimum)
            if constraint.maximum is not None:
                model.add(base_count + repair_count <= constraint.maximum)
        elif constraint.kind is ConstraintKind.MUTATION_LINEAGE_MINIMUM:
            assert constraint.minimum is not None
            lineages: dict[str, list[Any]] = defaultdict(list)
            for candidate in candidates:
                if (
                    candidate.origin_class is CaseOrigin.ADVERSARIAL_MUTATION
                    and candidate.mutation_lineage_id is not None
                ):
                    lineages[candidate.mutation_lineage_id].extend(
                        assignments[candidate.candidate_id, split] for split in placed_states
                    )
            lineage_vars = []
            for index, lineage_id in enumerate(sorted(lineages, key=str.encode)):
                members = lineages[lineage_id]
                present = model.new_bool_var(f"existing_lineage[{index}]")
                model.add(sum(members) >= 1).only_enforce_if(present)
                model.add(sum(members) == 0).only_enforce_if(present.Not())
                lineage_vars.append(present)
            new_lineages = sum(
                recourse[signature.signature_id, split]
                for signature in signatures
                if signature.lineage_behavior == "UNIQUE_PER_ADDITION_WITH_SAME_CELL_PARENT"
                for split in SPLIT_ORDER
            )
            model.add(sum(lineage_vars) + new_lineages >= constraint.minimum)

    return _StructuralRepairModel(
        geometry,
        model,
        assignments,
        additions,
        recourse,
        signatures,
        final_n,
        len(source_relations),
        len(maximal_relation_sets),
        relation_compaction_digest,
    )


def solve_repair_cardinality_decision(
    structural_model: _StructuralRepairModel,
    maximum_additions: int,
    *,
    minimum_additions: int = 0,
    lower_bound_proof: RepairCardinalityTrial | None = None,
    solver_config: SelectionSolverConfig = RES407_STRUCTURAL_REPAIR_MASTER_PROFILE_V1,
) -> RepairCardinalityTrial:
    if not 0 <= maximum_additions <= structural_model.final_n:
        raise ValueError("cardinality decision budget must be within FINAL_N")
    if not 0 <= minimum_additions <= maximum_additions:
        raise ValueError("cardinality decision interval must be within FINAL_N")
    if minimum_additions == 0:
        if lower_bound_proof is not None:
            raise ValueError("zero lower bound cannot carry an infeasibility proof")
    elif (
        lower_bound_proof is None
        or lower_bound_proof.status != "INFEASIBLE"
        or lower_bound_proof.maximum_additions != minimum_additions - 1
        or lower_bound_proof.geometry_digest != structural_model.geometry.geometry_digest
        or lower_bound_proof.signature_inventory_digest
        != canonical_hash(structural_model.signatures)
    ):
        raise ValueError("cardinality lower bound lacks its exact preceding infeasibility proof")
    model = structural_model.model.clone()
    additions = {
        signature_id: model.get_int_var_from_proto_index(variable.index)
        for signature_id, variable in structural_model.additions.items()
    }
    recourse = {
        key: model.get_int_var_from_proto_index(variable.index)
        for key, variable in structural_model.recourse.items()
    }
    model.add(sum(additions.values()) <= maximum_additions)
    if minimum_additions:
        model.add(sum(additions.values()) >= minimum_additions)
    if structural_model.hint_source_trial_digest is not None:
        states = dict(structural_model.assignment_hint)
        for candidate in structural_model.geometry.problem.candidates:
            state = states[candidate.candidate_id]
            for split in SPLIT_ORDER:
                original = structural_model.assignments[
                    candidate.candidate_id, AssignmentState(split.value)
                ]
                model.add_hint(
                    model.get_bool_var_from_proto_index(original.index),
                    int(state is AssignmentState(split.value)),
                )
        counts = {
            signature_id: dict(item.split_counts)
            for signature_id, item in (
                (item.signature.signature_id, item) for item in structural_model.repair_hint
            )
        }
        for signature_id, variable in additions.items():
            model.add_hint(
                variable,
                sum(counts.get(signature_id, {}).values()),
            )
        for (signature_id, split), variable in recourse.items():
            model.add_hint(variable, counts.get(signature_id, {}).get(split, 0))
    proto = model.proto
    domains = tuple(tuple(variable.domain) for variable in proto.variables)
    boolean_count = sum(domain == (0, 1) for domain in domains)
    solver, raw_status, _deterministic = _solve_once(model, solver_config)
    response = solver.response_proto
    has_solution = bool(response.solution)
    decision_status = (
        "INFEASIBLE" if raw_status == "INFEASIBLE" else ("FEASIBLE" if has_solution else "UNKNOWN")
    )
    witness: tuple[RepairSignatureCount, ...] = ()
    incumbent = None
    if has_solution:
        counts_by_signature: dict[str, list[tuple[SplitName, int]]] = defaultdict(list)
        for (signature_id, split), variable in recourse.items():
            count = int(solver.value(variable))
            if count:
                counts_by_signature[signature_id].append((split, count))
        signature_by_id = {item.signature_id: item for item in structural_model.signatures}
        witness = tuple(
            RepairSignatureCount(
                signature_by_id[signature_id],
                tuple(sorted(counts, key=lambda item: SPLIT_ORDER.index(item[0]))),
            )
            for signature_id, counts in sorted(counts_by_signature.items())
        )
        incumbent = sum(item.total_count for item in witness)
        selected_additions = sum(int(solver.value(variable)) for variable in additions.values())
        if selected_additions != incumbent or selected_additions > maximum_additions:
            raise ValueError("cardinality witness has unused or over-budget repair additions")
    diagnostics = RepairMasterDiagnostics(
        model_variable_count=len(domains),
        boolean_variable_count=boolean_count,
        integer_variable_count=len(domains) - boolean_count,
        constraint_count=len(proto.constraints),
        objective_term_count=len(proto.objective.vars),
        solver_status=raw_status,
        feasible_incumbent_present=has_solution,
        incumbent_addition_count=incumbent,
        best_objective_bound=None,
        absolute_gap=None,
        conflicts=int(response.num_conflicts),
        branches=int(response.num_branches),
        restarts=int(response.num_restarts),
        wall_seconds=float(response.wall_time),
        deterministic_time=float(response.deterministic_time),
        unknown_classification=classify_repair_master_unknown(raw_status, has_solution, None),
        solver_profile_version=RES407_STRUCTURAL_REPAIR_MASTER_PROFILE_VERSION,
        source_relation_constraint_count=structural_model.source_relation_constraint_count,
        unique_relation_member_set_count=structural_model.unique_relation_member_set_count,
        redundant_relation_constraints_removed=(
            structural_model.source_relation_constraint_count
            - structural_model.unique_relation_member_set_count
        ),
        relation_compaction_digest=structural_model.relation_compaction_digest,
    )
    trial = RepairCardinalityTrial(
        maximum_additions=maximum_additions,
        minimum_additions=minimum_additions,
        status=decision_status,
        solver_profile_version=RES407_STRUCTURAL_REPAIR_MASTER_PROFILE_VERSION,
        solver_config=solver_config,
        solver_version=version("ortools"),
        geometry_digest=structural_model.geometry.geometry_digest,
        signature_inventory_digest=canonical_hash(structural_model.signatures),
        diagnostics=diagnostics,
        witness=witness,
        lower_bound_source_trial_digest=(
            None if lower_bound_proof is None else lower_bound_proof.trial_digest
        ),
        hint_source_trial_digest=structural_model.hint_source_trial_digest,
    )
    if decision_status == "FEASIBLE":
        state_hints = []
        for candidate in structural_model.geometry.problem.candidates:
            state = next(
                (
                    AssignmentState(split.value)
                    for split in SPLIT_ORDER
                    if solver.value(
                        structural_model.assignments[
                            candidate.candidate_id, AssignmentState(split.value)
                        ]
                    )
                ),
                AssignmentState.OUT,
            )
            state_hints.append((candidate.candidate_id, state))
        structural_model.assignment_hint = tuple(state_hints)
        structural_model.repair_hint = witness
        structural_model.hint_source_trial_digest = trial.trial_digest
    return trial


def solve_ideal_repair_minimum(
    geometry: RepairGeometry,
    *,
    signatures: tuple[RepairSignature, ...] | None = None,
    solver_config: SelectionSolverConfig = RES407_STRUCTURAL_REPAIR_MASTER_PROFILE_V1,
    zero_addition_infeasibility_proof: RepairCardinalityTrial | None = None,
) -> IdealRepairCardinalityResult:
    signature_inventory = tuple(
        sorted(
            set(
                build_compact_ideal_repair_signatures(geometry)
                if signatures is None
                else signatures
            ),
            key=lambda item: item.signature_id,
        )
    )
    model = _structural_repair_model(geometry, signature_inventory)
    inventory_digest = canonical_hash(signature_inventory)
    trials_by_k: dict[int, RepairCardinalityTrial] = {}
    trials: list[RepairCardinalityTrial] = []

    if zero_addition_infeasibility_proof is not None:
        proof = zero_addition_infeasibility_proof
        if (
            proof.maximum_additions != 0
            or proof.status != "INFEASIBLE"
            or proof.diagnostics is not None
            or proof.geometry_digest != geometry.geometry_digest
            or proof.signature_inventory_digest != inventory_digest
            or proof.proof_source_schema != "RES406-BASE-FEASIBILITY-RECEIPT@1.0.0"
            or proof.proof_source_status != "INFEASIBLE"
            or proof.proof_source_method != "EXACT_FEASIBILITY_ORACLE"
            or proof.solver_profile_version != POOL_FEASIBILITY_SOLVER_PROFILE_VERSION
            or proof.solver_config != PSE_V1_POOL_FEASIBILITY_SOLVER_PROFILE_V1
            or proof.solver_version != version("ortools")
            or proof.proof_source_problem_digest != geometry.problem.problem_digest
            or proof.proof_source_constraint_inventory_digest
            != geometry.problem.constraint_inventory_digest
        ):
            raise ValueError("inherited zero-addition proof does not bind this exact geometry")
        trials_by_k[0] = proof
        trials.append(proof)

    def decide(
        k: int,
        *,
        lower_bound_proof: RepairCardinalityTrial | None = None,
    ) -> RepairCardinalityTrial:
        cached = trials_by_k.get(k)
        if cached is not None:
            if cached.status != "FEASIBLE" or (
                cached.diagnostics is not None
                and cached.diagnostics.incumbent_addition_count is not None
                and cached.diagnostics.incumbent_addition_count <= k
            ):
                return cached
        minimum = 0 if lower_bound_proof is None else lower_bound_proof.maximum_additions + 1
        trial = solve_repair_cardinality_decision(
            model,
            k,
            minimum_additions=minimum,
            lower_bound_proof=lower_bound_proof,
            solver_config=solver_config,
        )
        trials_by_k[k] = trial
        trials.append(trial)
        return trial

    def result(
        status: str,
        *,
        minimum: int | None = None,
        vector: tuple[RepairSignatureCount, ...] = (),
        lower: RepairCardinalityTrial | None = None,
        upper: RepairCardinalityTrial | None = None,
        scope: str,
    ) -> IdealRepairCardinalityResult:
        return IdealRepairCardinalityResult(
            status=status,
            minimum_additions=minimum,
            repair_vector=vector,
            profile_version=RES407_STRUCTURAL_REPAIR_MASTER_PROFILE_VERSION,
            solver_config=solver_config,
            solver_version=version("ortools"),
            signature_count=len(signature_inventory),
            signature_inventory_digest=inventory_digest,
            geometry_digest=geometry.geometry_digest,
            model_is_relaxation=IDEAL_REPAIR_IS_RELAXATION,
            relaxation_definition=IDEAL_REPAIR_RELAXATION_DEFINITION,
            trials=tuple(trials),
            lower_proof=lower,
            upper_proof=upper,
            optimality_scope=scope,
        )

    scope = (
        "IDEAL_RELAXATION; finite canonical signature domain; total additions <= FINAL_N="
        f"{model.final_n}; feasibility monotone in K because K is an upper bound"
    )
    zero = trials_by_k.get(0) or decide(0)
    if zero.status == "UNKNOWN":
        return result("UNKNOWN", scope=scope)
    if zero.status == "FEASIBLE":
        return result("OPTIMAL", minimum=0, vector=zero.witness, upper=zero, scope=scope)

    low = zero
    k = 1
    high: RepairCardinalityTrial | None = None
    while True:
        trial = decide(k, lower_bound_proof=low)
        if trial.status == "UNKNOWN":
            return result("UNKNOWN", lower=low, upper=high, scope=scope)
        if trial.status == "INFEASIBLE":
            low = trial
            if k == model.final_n:
                return result("INFEASIBLE", lower=low, scope=scope)
            k = min(model.final_n, 2 * k)
            continue
        high = trial
        assert high.diagnostics is not None
        while high.diagnostics.incumbent_addition_count is not None and (
            high.diagnostics.incumbent_addition_count < high.maximum_additions
        ):
            smaller_k = high.diagnostics.incumbent_addition_count
            if smaller_k <= low.maximum_additions:
                raise ValueError("feasible witness contradicts the proven infeasible lower bound")
            smaller = decide(smaller_k, lower_bound_proof=low)
            if smaller.status == "UNKNOWN":
                return result("UNKNOWN", lower=low, upper=smaller, scope=scope)
            if smaller.status != "FEASIBLE":
                raise ValueError("normalized feasible witness did not replay at its cardinality")
            high = smaller
        break

    while high.maximum_additions - low.maximum_additions > 1:
        middle = (low.maximum_additions + high.maximum_additions) // 2
        trial = decide(middle, lower_bound_proof=low)
        if trial.status == "UNKNOWN":
            return result("UNKNOWN", lower=low, upper=high, scope=scope)
        if trial.status == "INFEASIBLE":
            low = trial
            continue
        high = trial
        assert high.diagnostics is not None
        while high.diagnostics.incumbent_addition_count is not None and (
            high.diagnostics.incumbent_addition_count < high.maximum_additions
        ):
            smaller_k = high.diagnostics.incumbent_addition_count
            if smaller_k <= low.maximum_additions:
                raise ValueError("feasible witness contradicts the proven infeasible lower bound")
            smaller = decide(smaller_k, lower_bound_proof=low)
            if smaller.status == "UNKNOWN":
                return result("UNKNOWN", lower=low, upper=smaller, scope=scope)
            if smaller.status != "FEASIBLE":
                raise ValueError("normalized feasible witness did not replay at its cardinality")
            high = smaller

    assert high.maximum_additions == low.maximum_additions + 1
    return result(
        "OPTIMAL",
        minimum=high.maximum_additions,
        vector=high.witness,
        lower=low,
        upper=high,
        scope=scope,
    )


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
                relation_behavior=(
                    "SHARED_SPLIT_LOCKED_CLUSTER; UNKNOWN_SHINGLE_RELATIONS_RELAXED"
                ),
                isolation_identity_behavior="SHARED_SPLIT_AND_GENERATOR_FAMILY",
                lane_id=archetype.lane_id,
                lane_capacity=archetype.remaining_finite_capacity,
                capacity_status=archetype.capacity_status,
            )
        )
    return tuple(sorted(set(signatures), key=lambda item: item.signature_id))


def classify_repair_master_unknown(
    solver_status: str,
    feasible_incumbent: bool,
    best_objective_bound: float | None,
) -> str | None:
    if solver_status != "UNKNOWN":
        return None
    if feasible_incumbent:
        return "FEASIBLE_INCUMBENT_NOT_PROVEN_OPTIMAL"
    if best_objective_bound is not None and best_objective_bound > 0:
        return "BOUND_ONLY_NO_INCUMBENT"
    return "NO_USEFUL_BOUND_OR_INCUMBENT"


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
    proto = model.proto
    variable_domains = tuple(tuple(variable.domain) for variable in proto.variables)
    variable_count = len(variable_domains)
    boolean_count = sum(domain == (0, 1) for domain in variable_domains)
    solver, status, _deterministic = _solve_once(model, solver_config)
    response = solver.response_proto
    feasible_incumbent = bool(response.solution)
    incumbent = int(solver.value(objective)) if feasible_incumbent else None
    best_bound = (
        float(response.best_objective_bound)
        if status in {"OPTIMAL", "FEASIBLE", "UNKNOWN"}
        else None
    )
    diagnostics = RepairMasterDiagnostics(
        model_variable_count=variable_count,
        boolean_variable_count=boolean_count,
        integer_variable_count=variable_count - boolean_count,
        constraint_count=len(proto.constraints),
        objective_term_count=len(proto.objective.vars),
        solver_status=status,
        feasible_incumbent_present=feasible_incumbent,
        incumbent_addition_count=incumbent,
        best_objective_bound=best_bound,
        absolute_gap=(
            None if incumbent is None or best_bound is None else abs(incumbent - best_bound)
        ),
        conflicts=int(response.num_conflicts),
        branches=int(response.num_branches),
        restarts=int(response.num_restarts),
        wall_seconds=float(response.wall_time),
        deterministic_time=float(response.deterministic_time),
        unknown_classification=classify_repair_master_unknown(
            status, feasible_incumbent, best_bound
        ),
    )
    solver_version = version("ortools")
    minimum = None
    bound = None
    vector: tuple[RepairSignatureCount, ...] = ()
    if status == "OPTIMAL":
        minimum = int(solver.value(objective))
        assert best_bound is not None
        bound = int(best_bound)
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
        solver_diagnostics=diagnostics,
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
