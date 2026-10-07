"""Variable metadata-only pool planning and single-removal reserve proof."""

from __future__ import annotations

import enum
import re
from dataclasses import dataclass, replace

from dynamislm.benchmark.authoring import parse_production_seed_namespace
from dynamislm.benchmark.authority_supply import (
    AuthoritySupplyAssessmentV1,
    AuthoritySupplyInventoryV1,
    BackfillRequestKind,
    BackfillRequestV1,
    ReserveCandidateLaneV1,
    ReserveDeficitKind,
    ReserveDeficitV1,
    SupplyAssessmentStatus,
)
from dynamislm.benchmark.constants import CaseOrigin, SplitName
from dynamislm.benchmark.selection_constraints import (
    _ORIGIN_BOUNDS,
    FINAL_CASE_COUNT,
    MUTATION_LINEAGE_MINIMUM,
    _allocation_clusters,
    build_final_selection_problem,
)
from dynamislm.benchmark.selection_contracts import (
    POOL_FEASIBILITY_SOLVER_PROFILE_VERSION,
    PSE_V1_POOL_FEASIBILITY_SOLVER_PROFILE_V1,
    ConstraintKind,
    FeasibilityStatus,
    FeatureKind,
    FinalSelectionCandidate,
    FinalSelectionProblem,
    IsolationIdentityKind,
    MutationParentProvenance,
    ReviewEligibility,
    SelectionConstraint,
    SelectionConstraintSet,
    SelectionFeasibilityReceiptV1,
    SelectionSolverConfig,
)
from dynamislm.benchmark.selection_solver import solve_selection_feasibility
from dynamislm.serialization import canonical_hash, register_serializable_type

_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
POOL_METADATA_PLAN_VERSION = "PSE-V1-VARIABLE-POOL-METADATA-PLAN@1.0.0"
POOL_RESERVE_RECEIPT_VERSION = "PSE-V1-SINGLE-REMOVAL-RESERVE-RECEIPT@1.0.0"
POOL_SUPPLY_ASSESSMENT_VERSION = "PSE-V1-POOL-SUPPLY-ASSESSMENT@1.0.0"


class PoolPlanStatus(enum.StrEnum):
    QUALIFIED = "QUALIFIED"
    BACKFILL_REQUIRED = "BACKFILL_REQUIRED"
    METADATA_REQUIRED = "METADATA_REQUIRED"
    AUTHORITY_EXPANSION_REQUIRED = "AUTHORITY_EXPANSION_REQUIRED"
    UNKNOWN = "UNKNOWN"


class CriticalReserveStatus(enum.StrEnum):
    QUALIFIED = "QUALIFIED"
    BACKFILL_REQUIRED = "BACKFILL_REQUIRED"
    METADATA_REQUIRED = "METADATA_REQUIRED"
    AUTHORITY_EXPANSION_REQUIRED = "AUTHORITY_EXPANSION_REQUIRED"
    UNKNOWN = "UNKNOWN"


@register_serializable_type
@dataclass(frozen=True, slots=True)
class MaterializedBackfillCandidateV1:
    candidate: FinalSelectionCandidate
    lane_id: str
    authority_ref: str
    authority_digest: str

    def __post_init__(self) -> None:
        if (
            not self.lane_id.strip()
            or not self.authority_ref.strip()
            or _SHA256.fullmatch(self.authority_digest) is None
        ):
            raise ValueError(
                "materialized backfill candidate requires a lane and digested authority"
            )


@register_serializable_type
@dataclass(frozen=True, slots=True)
class PoolBackfillNeedV1:
    constraint_id: str
    constraint_kind: ConstraintKind
    present_candidate_count: int
    required_candidate_count: int
    missing_candidate_count: int
    origin_class: CaseOrigin | None = None
    split: SplitName | None = None
    feature_kind: FeatureKind | None = None
    feature_key: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "constraint_kind", ConstraintKind(self.constraint_kind))
        if self.origin_class is not None:
            object.__setattr__(self, "origin_class", CaseOrigin(self.origin_class))
        if self.split is not None:
            object.__setattr__(self, "split", SplitName(self.split))
        if self.feature_kind is not None:
            object.__setattr__(self, "feature_kind", FeatureKind(self.feature_kind))
        if (
            not self.constraint_id.strip()
            or self.present_candidate_count < 0
            or self.required_candidate_count < 1
            or self.missing_candidate_count < 1
            or self.present_candidate_count + self.missing_candidate_count
            != self.required_candidate_count
        ):
            raise ValueError("pool backfill need counts are inconsistent")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class PoolMetadataPlanV1:
    candidates: tuple[FinalSelectionCandidate, ...]
    parent_provenance_registry: tuple[MutationParentProvenance, ...]
    backfill_authorities: tuple[tuple[str, str, str, str], ...]
    plan_digest: str = ""

    def __post_init__(self) -> None:
        if not self.candidates:
            raise ValueError("pool metadata plan requires at least one candidate")
        ordered = tuple(sorted(self.candidates, key=lambda item: item.candidate_id.encode()))
        ids = tuple(item.candidate_id for item in ordered)
        hashes = tuple(item.payload_hash for item in ordered)
        if len(set(ids)) != len(ids) or len(set(hashes)) != len(hashes):
            raise ValueError("pool metadata plan candidate identities must be unique")
        object.__setattr__(self, "candidates", ordered)
        parent_ids = tuple(item.candidate_id for item in self.parent_provenance_registry)
        if parent_ids != tuple(sorted(set(parent_ids), key=str.encode)):
            raise ValueError("pool parent provenance must be unique and canonically ordered")
        if self.backfill_authorities != tuple(
            sorted(set(self.backfill_authorities), key=lambda item: item[0].encode())
        ):
            raise ValueError("backfill authority bindings must be unique and candidate ordered")
        known_ids = set(ids)
        if any(
            candidate_id not in known_ids
            for candidate_id, _lane, _ref, _digest in self.backfill_authorities
        ):
            raise ValueError("backfill authority binding references a candidate outside the pool")
        if any(
            not lane_id.strip() or not authority_ref.strip() or _SHA256.fullmatch(digest) is None
            for _candidate, lane_id, authority_ref, digest in self.backfill_authorities
        ):
            raise ValueError("backfill authority binding is malformed")
        computed = canonical_hash(
            {
                "version": POOL_METADATA_PLAN_VERSION,
                "candidates": ordered,
                "parent_provenance_registry": self.parent_provenance_registry,
                "backfill_authorities": self.backfill_authorities,
            }
        )
        if self.plan_digest and self.plan_digest != computed:
            raise ValueError("pool metadata plan digest does not match its metadata")
        object.__setattr__(self, "plan_digest", computed)


@register_serializable_type
@dataclass(frozen=True, slots=True)
class SingleCandidateRemovalCheckV1:
    candidate_digest: str
    status: FeasibilityStatus
    proof_method: str
    plan_digest: str | None = None
    validation_digest: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", FeasibilityStatus(self.status))
        if _SHA256.fullmatch(self.candidate_digest) is None:
            raise ValueError("removal check requires a candidate identity digest")
        for digest in (self.plan_digest, self.validation_digest):
            if digest is not None and _SHA256.fullmatch(digest) is None:
                raise ValueError("removal check contains a malformed digest")
        if self.status is FeasibilityStatus.FEASIBLE and (
            self.proof_method != "EXACT_FEASIBILITY_ORACLE"
            or self.plan_digest is None
            or self.validation_digest is None
        ):
            raise ValueError("feasible removal check requires an exact validated witness")
        if self.status is not FeasibilityStatus.FEASIBLE and self.plan_digest is not None:
            raise ValueError("non-feasible removal check cannot accept a plan")
        if self.status is FeasibilityStatus.INFEASIBLE and self.proof_method not in {
            "EXACT_FEASIBILITY_ORACLE",
            "FINAL_COUNT_LOWER_BOUND",
        }:
            raise ValueError("infeasible removal check has no exact proof method")
        if (
            self.status is FeasibilityStatus.UNKNOWN
            and self.proof_method != "EXACT_FEASIBILITY_ORACLE"
        ):
            raise ValueError("unknown removal check must come from the exact feasibility oracle")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class PoolReserveReceiptV1:
    receipt_version: str
    status: PoolPlanStatus
    pool_plan_digest: str
    initial_candidate_count: int
    candidate_count: int
    backfill_candidate_count: int
    final_target_count: int
    eligible_candidate_count: int
    usable_reserve_candidate_count: int
    supply_inventory_digest: str | None
    authority_inventory_complete: bool
    capacity_scope_complete: bool
    solver_profile_version: str
    baseline_feasibility_status: FeasibilityStatus | None
    checked_removal_count: int
    feasible_removal_count: int
    infeasible_removal_count: int
    unknown_removal_count: int
    removal_case_digest: str
    critical_obligation_count: int
    critical_obligations_with_structural_reserve: int
    independent_critical_reserve_status: CriticalReserveStatus
    unresolved_backfill_needs: tuple[PoolBackfillNeedV1, ...]
    reserve_deficits: tuple[ReserveDeficitV1, ...]
    backfill_requests: tuple[BackfillRequestV1, ...]
    status_reasons: tuple[str, ...]
    authority_exhaustion_proven: bool = False
    review_eligibility_assumption: str = "PENDING_OR_UNAPPROVED_AS_POOL_CAPACITY_ONLY"
    human_review_performed: bool = False
    protected_membership_persisted: bool = False
    canonicalization_performed: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", PoolPlanStatus(self.status))
        if self.baseline_feasibility_status is not None:
            object.__setattr__(
                self,
                "baseline_feasibility_status",
                FeasibilityStatus(self.baseline_feasibility_status),
            )
        object.__setattr__(
            self,
            "independent_critical_reserve_status",
            CriticalReserveStatus(self.independent_critical_reserve_status),
        )
        counts = (
            self.initial_candidate_count,
            self.candidate_count,
            self.backfill_candidate_count,
            self.final_target_count,
            self.eligible_candidate_count,
            self.usable_reserve_candidate_count,
            self.checked_removal_count,
            self.feasible_removal_count,
            self.infeasible_removal_count,
            self.unknown_removal_count,
            self.critical_obligation_count,
            self.critical_obligations_with_structural_reserve,
        )
        if any(value < 0 for value in counts):
            raise ValueError("pool receipt counts must be non-negative")
        if (
            _SHA256.fullmatch(self.pool_plan_digest) is None
            or _SHA256.fullmatch(self.removal_case_digest) is None
            or self.candidate_count != self.initial_candidate_count + self.backfill_candidate_count
            or self.eligible_candidate_count > self.candidate_count
            or self.usable_reserve_candidate_count
            != max(0, self.eligible_candidate_count - self.final_target_count)
            or (
                self.supply_inventory_digest is not None
                and _SHA256.fullmatch(self.supply_inventory_digest) is None
            )
            or not self.solver_profile_version.strip()
        ):
            raise ValueError("pool receipt digest or candidate counts are inconsistent")
        if self.status is PoolPlanStatus.AUTHORITY_EXPANSION_REQUIRED and (
            not self.authority_exhaustion_proven
            or self.supply_inventory_digest is None
            or not self.authority_inventory_complete
            or not self.capacity_scope_complete
        ):
            raise ValueError(
                "authority expansion requires complete proof of exhausted governed lanes"
            )
        if self.human_review_performed or self.protected_membership_persisted:
            raise ValueError("pool planning cannot perform review or persist final membership")
        if self.canonicalization_performed:
            raise ValueError("pool reserve qualification cannot canonicalize a final plan")
        if (
            self.feasible_removal_count + self.infeasible_removal_count + self.unknown_removal_count
            != self.checked_removal_count
        ):
            raise ValueError("pool removal outcome counts do not equal checked cases")
        if self.status is PoolPlanStatus.QUALIFIED and (
            self.baseline_feasibility_status is not FeasibilityStatus.FEASIBLE
            or self.checked_removal_count != self.candidate_count
            or self.feasible_removal_count != self.candidate_count
            or self.unresolved_backfill_needs
            or self.backfill_requests
            or self.independent_critical_reserve_status is not CriticalReserveStatus.QUALIFIED
            or self.critical_obligations_with_structural_reserve != self.critical_obligation_count
        ):
            raise ValueError("qualified pool receipt must prove every removal and critical reserve")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class PoolPlanningResultV1:
    plan: PoolMetadataPlanV1
    receipt: PoolReserveReceiptV1

    def __post_init__(self) -> None:
        if (
            self.plan.plan_digest != self.receipt.pool_plan_digest
            or len(self.plan.candidates) != self.receipt.candidate_count
        ):
            raise ValueError("pool planning result and receipt do not match")


def _authorable_lanes(
    inventory: AuthoritySupplyInventoryV1,
    origin: CaseOrigin | None = None,
) -> tuple[ReserveCandidateLaneV1, ...]:
    return tuple(
        lane
        for lane in inventory.reserve_candidate_lanes
        if lane.may_author_backfill and (origin is None or lane.origin_class is origin)
    )


def assess_authority_supply_inventory(
    inventory: AuthoritySupplyInventoryV1,
) -> AuthoritySupplyAssessmentV1:
    """Report count-derived requests before any candidate metadata is materialized."""

    planned = dict(inventory.planned_origin_counts)
    deficits: list[ReserveDeficitV1] = []
    requests: list[BackfillRequestV1] = []
    origin_missing: dict[CaseOrigin, int] = {}
    for origin, minimum, _maximum in _ORIGIN_BOUNDS:
        if minimum == 0:
            continue
        present = planned.get(origin, 0)
        required = minimum + 1
        missing = max(0, required - present)
        if not missing:
            continue
        deficit = ReserveDeficitV1(
            deficit_kind=ReserveDeficitKind.STRUCTURAL_COUNT,
            constraint_id=f"RES126:ORIGIN:{origin.value}",
            required_count=required,
            observed_count=present,
        )
        lanes = _authorable_lanes(inventory, origin)
        deficits.append(deficit)
        requests.append(
            BackfillRequestV1(
                request_kind=BackfillRequestKind.CONSTRAINT_MINIMUM,
                deficit_digest=deficit.deficit_digest,
                lane_ids=tuple(lane.lane_id for lane in lanes),
                requested_capacity=missing,
                required_origin=origin,
                constraint_id=deficit.constraint_id,
                requires_candidate_metadata=True,
            )
        )
        origin_missing[origin] = missing

    lineage_required = MUTATION_LINEAGE_MINIMUM + 1
    lineage_missing = max(0, lineage_required - inventory.planned_mutation_lineage_count)
    if lineage_missing:
        deficit = ReserveDeficitV1(
            deficit_kind=ReserveDeficitKind.STRUCTURAL_COUNT,
            constraint_id="RES258:MUTATION_LINEAGES_MINIMUM",
            required_count=lineage_required,
            observed_count=inventory.planned_mutation_lineage_count,
        )
        lanes = _authorable_lanes(inventory, CaseOrigin.ADVERSARIAL_MUTATION)
        deficits.append(deficit)
        requests.append(
            BackfillRequestV1(
                request_kind=BackfillRequestKind.CONSTRAINT_MINIMUM,
                deficit_digest=deficit.deficit_digest,
                lane_ids=tuple(lane.lane_id for lane in lanes),
                requested_capacity=lineage_missing,
                required_origin=CaseOrigin.ADVERSARIAL_MUTATION,
                constraint_id=deficit.constraint_id,
                requires_candidate_metadata=True,
            )
        )

    final_missing = max(0, FINAL_CASE_COUNT + 1 - inventory.planned_candidate_count)
    non_mutation_missing = sum(
        count
        for origin, count in origin_missing.items()
        if origin is not CaseOrigin.ADVERSARIAL_MUTATION
    )
    mutation_missing = max(origin_missing.get(CaseOrigin.ADVERSARIAL_MUTATION, 0), lineage_missing)
    origin_additional = non_mutation_missing + mutation_missing
    additional = max(final_missing, origin_additional)
    total_only_missing = max(0, final_missing - origin_additional)
    if total_only_missing:
        deficit = ReserveDeficitV1(
            deficit_kind=ReserveDeficitKind.STRUCTURAL_COUNT,
            constraint_id="RES258:FINAL_SELECTED_N",
            required_count=FINAL_CASE_COUNT + 1,
            observed_count=inventory.planned_candidate_count,
        )
        lanes = _authorable_lanes(inventory)
        deficits.append(deficit)
        requests.append(
            BackfillRequestV1(
                request_kind=BackfillRequestKind.CONSTRAINT_MINIMUM,
                deficit_digest=deficit.deficit_digest,
                lane_ids=tuple(lane.lane_id for lane in lanes),
                requested_capacity=total_only_missing,
                constraint_id=deficit.constraint_id,
                requires_candidate_metadata=True,
            )
        )

    metadata_deficit = ReserveDeficitV1(
        deficit_kind=ReserveDeficitKind.METADATA_UNRESOLVED,
        scenario_digest=inventory.inventory_digest,
    )
    metadata_lanes = _authorable_lanes(inventory)
    deficits.append(metadata_deficit)
    requests.append(
        BackfillRequestV1(
            request_kind=BackfillRequestKind.CANDIDATE_METADATA,
            deficit_digest=metadata_deficit.deficit_digest,
            lane_ids=tuple(lane.lane_id for lane in metadata_lanes),
            requested_capacity=None,
            scenario_digest=inventory.inventory_digest,
            requires_candidate_metadata=True,
        )
    )

    no_lane_request = any(
        request.request_kind is not BackfillRequestKind.CANDIDATE_METADATA and not request.lane_ids
        for request in requests
    )
    if (
        no_lane_request
        and inventory.authority_inventory_complete
        and inventory.capacity_scope_complete
    ):
        status = SupplyAssessmentStatus.AUTHORITY_EXPANSION_REQUIRED
    elif any(
        request.request_kind is BackfillRequestKind.CONSTRAINT_MINIMUM and request.lane_ids
        for request in requests
    ):
        status = SupplyAssessmentStatus.BACKFILL_REQUIRED
    else:
        status = SupplyAssessmentStatus.METADATA_REQUIRED
    return AuthoritySupplyAssessmentV1(
        assessment_version=POOL_SUPPLY_ASSESSMENT_VERSION,
        status=status,
        inventory_digest=inventory.inventory_digest,
        planned_candidate_count=inventory.planned_candidate_count,
        materialized_candidate_count=inventory.materialized_candidate_count,
        usable_reserve_capacity_count=0,
        final_target_count=FINAL_CASE_COUNT,
        known_structural_pool_floor=inventory.planned_candidate_count + additional,
        derived_pool_n=None,
        backfill_requests=tuple(requests),
        unresolved_deficits=tuple(deficits),
        exact_qualification_status=SupplyAssessmentStatus.METADATA_REQUIRED,
        authority_inventory_complete=inventory.authority_inventory_complete,
        capacity_scope_complete=inventory.capacity_scope_complete,
    )


def _planning_candidates(
    candidates: tuple[FinalSelectionCandidate, ...],
) -> tuple[FinalSelectionCandidate, ...]:
    # Pending metadata is treated as potentially eligible for pool-capacity planning only.
    return tuple(
        replace(candidate, review_eligibility=ReviewEligibility.APPROVED)
        if candidate.review_eligibility in {ReviewEligibility.PENDING, ReviewEligibility.UNAPPROVED}
        else candidate
        for candidate in candidates
    )


def _build_problem(
    candidates: tuple[FinalSelectionCandidate, ...],
    parent_registry: tuple[MutationParentProvenance, ...],
) -> FinalSelectionProblem:
    # Only the ephemeral oracle view treats pending slots as eligible capacity.
    return build_final_selection_problem(
        _planning_candidates(candidates),
        parent_provenance_registry=parent_registry,
    )


def _eligible(candidate: FinalSelectionCandidate) -> bool:
    return (
        candidate.review_eligibility is ReviewEligibility.APPROVED
        and not candidate.qualification_excluded
    )


def validate_materialized_backfill_lane_binding(
    binding: MaterializedBackfillCandidateV1,
    lane: ReserveCandidateLaneV1,
) -> None:
    """Fail closed unless the candidate matches the lane's exact cell and authority identities."""

    candidate = binding.candidate
    if (
        binding.lane_id != lane.lane_id
        or not lane.may_author_backfill
        or lane.origin_class is not candidate.origin_class
        or lane.authority_ref != binding.authority_ref
        or lane.authority_digest != binding.authority_digest
        or candidate.cell not in lane.supported_cells
    ):
        raise ValueError(
            "materialized backfill candidate does not match an available authority lane"
        )

    identity_tags = {
        IsolationIdentityKind.SOURCE_FAMILY: "SOURCE_FAMILY",
        IsolationIdentityKind.SOURCE_DOCUMENT: "SOURCE_DOCUMENT",
        IsolationIdentityKind.RES71_ENGINE_REFERENCE_CASE: "RES71_ENGINE_REFERENCE_CASE",
        IsolationIdentityKind.EXPERT_AUTHOR_BATCH: "EXPERT_BATCH",
        IsolationIdentityKind.PROTOCOL_TEMPLATE: "PROTOCOL_TEMPLATE",
        IsolationIdentityKind.GENERATOR_FAMILY: "GENERATOR_FAMILY",
        IsolationIdentityKind.MUTATION_LINEAGE: "MUTATION_LINEAGE",
        IsolationIdentityKind.MUTATION_PARENT: "MUTATION_PARENT",
    }
    candidate_identity_digests: dict[str, set[str]] = {}
    candidate_identity_values: dict[str, set[str]] = {}
    for identity in candidate.isolation_identities:
        tag = identity_tags.get(identity.kind)
        if tag is not None:
            candidate_identity_values.setdefault(tag, set()).add(identity.identity)
            candidate_identity_digests.setdefault(tag, set()).add(
                canonical_hash((tag, identity.identity))
            )
    if candidate.origin_class is CaseOrigin.EXPERT_AUTHORED_SEMANTIC:
        candidate_identity_digests.setdefault("EXPERT_ISOLATION_CLUSTER", set()).add(
            canonical_hash(("EXPERT_ISOLATION_CLUSTER", candidate.isolation_cluster_id))
        )
    elif candidate.origin_class is CaseOrigin.DETERMINISTIC_SYNTHETIC:
        namespaces = tuple(
            identity.identity
            for identity in candidate.isolation_identities
            if identity.kind is IsolationIdentityKind.GENERATOR_SEED_NAMESPACE
        )
        if len(namespaces) != 1 or candidate.locked_split is None:
            raise ValueError(
                "synthetic backfill candidate lacks its exact generator and split lock"
            )
        namespace = parse_production_seed_namespace(namespaces[0])
        if namespace.split_name is not candidate.locked_split:
            raise ValueError(
                "synthetic backfill candidate seed namespace conflicts with its split lock"
            )
        if namespace.seed_block not in candidate.generator_seed_blocks:
            raise ValueError("synthetic backfill candidate omits its bound generator seed block")
        candidate_identity_digests.setdefault("SYNTHETIC_GENERATOR", set()).add(
            canonical_hash(
                ("SYNTHETIC_GENERATOR", namespace.generator_id, namespace.generator_version)
            )
        )
        candidate_identity_digests.setdefault("SYNTHETIC_SPLIT_LOCK", set()).add(
            canonical_hash(("SYNTHETIC_SPLIT_LOCK", candidate.locked_split))
        )
    elif candidate.origin_class is CaseOrigin.ADVERSARIAL_MUTATION and (
        candidate.mutation_parent_candidate_id
        not in candidate_identity_values.get("MUTATION_PARENT", set())
        or candidate.mutation_lineage_id
        not in candidate_identity_values.get("MUTATION_LINEAGE", set())
    ):
        raise ValueError("mutation candidate fields conflict with its lane lineage identities")

    required_identity_tags = {
        CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION: ("SOURCE_FAMILY", "SOURCE_DOCUMENT"),
        CaseOrigin.DETERMINISTIC_ENGINE_DERIVED: ("RES71_ENGINE_REFERENCE_CASE",),
        CaseOrigin.DETERMINISTIC_SYNTHETIC: (
            "SYNTHETIC_GENERATOR",
            "GENERATOR_FAMILY",
            "SYNTHETIC_SPLIT_LOCK",
        ),
        CaseOrigin.EXPERT_AUTHORED_SEMANTIC: (
            "EXPERT_BATCH",
            "PROTOCOL_TEMPLATE",
            "EXPERT_ISOLATION_CLUSTER",
        ),
        CaseOrigin.ADVERSARIAL_MUTATION: ("MUTATION_PARENT", "MUTATION_LINEAGE"),
    }
    lane_identities = set(lane.isolation_identity_digests)
    if (
        not all(
            candidate_identity_digests.get(tag)
            for tag in required_identity_tags[candidate.origin_class]
        )
        or not lane_identities.issubset(
            {digest for digests in candidate_identity_digests.values() for digest in digests}
        )
        or any(
            not lane_identities.intersection(candidate_identity_digests[tag])
            for tag in required_identity_tags[candidate.origin_class]
        )
    ):
        raise ValueError(
            "materialized backfill candidate lacks the lane's required authority identities"
        )


def derive_pool_backfill_needs(problem: FinalSelectionProblem) -> tuple[PoolBackfillNeedV1, ...]:
    """Derive necessary capacity before exact single-candidate-removal checks."""

    candidates = tuple(item for item in problem.candidates if _eligible(item))
    needs: list[PoolBackfillNeedV1] = []
    for constraint in problem.constraint_set.constraints:
        if constraint.kind is ConstraintKind.FINAL_COUNT:
            assert constraint.minimum is not None
            target = constraint.minimum + 1
            present = len(candidates)
        elif constraint.kind is ConstraintKind.ORIGIN_BOUNDS:
            assert constraint.origin_class is not None and constraint.minimum is not None
            if constraint.minimum == 0:
                continue
            target = constraint.minimum + 1
            present = sum(item.origin_class is constraint.origin_class for item in candidates)
        elif constraint.kind is ConstraintKind.MUTATION_LINEAGE_MINIMUM:
            assert constraint.minimum is not None
            target = constraint.minimum + 1
            present = len(
                {
                    item.mutation_lineage_id
                    for item in candidates
                    if item.origin_class is CaseOrigin.ADVERSARIAL_MUTATION
                    and item.mutation_lineage_id is not None
                }
            )
        elif constraint.kind is ConstraintKind.FEATURE_MINIMUM:
            assert constraint.minimum is not None
            assert constraint.feature is not None and constraint.split is not None
            if constraint.minimum == 0:
                continue
            target = constraint.minimum + 1
            present = sum(
                constraint.feature in item.features
                and (item.locked_split is None or item.locked_split is constraint.split)
                for item in candidates
            )
        else:
            continue
        if present < target:
            needs.append(
                PoolBackfillNeedV1(
                    constraint_id=constraint.constraint_id,
                    constraint_kind=constraint.kind,
                    present_candidate_count=present,
                    required_candidate_count=target,
                    missing_candidate_count=target - present,
                    origin_class=constraint.origin_class,
                    split=constraint.split,
                    feature_kind=(constraint.feature.kind if constraint.feature else None),
                    feature_key=(constraint.feature.key if constraint.feature else ()),
                )
            )
    return tuple(sorted(needs, key=lambda item: item.constraint_id.encode()))


def _contributes(
    candidate: FinalSelectionCandidate,
    need: PoolBackfillNeedV1,
    pool: tuple[FinalSelectionCandidate, ...],
) -> bool:
    if not _eligible(candidate):
        return False
    if need.constraint_kind is ConstraintKind.FINAL_COUNT:
        return True
    if need.constraint_kind is ConstraintKind.ORIGIN_BOUNDS:
        return candidate.origin_class is need.origin_class
    if need.constraint_kind is ConstraintKind.FEATURE_MINIMUM:
        feature_matches = any(
            feature.kind is need.feature_kind and feature.key == need.feature_key
            for feature in candidate.features
        )
        return feature_matches and (
            candidate.locked_split is None or candidate.locked_split is need.split
        )
    if need.constraint_kind is ConstraintKind.MUTATION_LINEAGE_MINIMUM:
        existing = {
            item.mutation_lineage_id
            for item in pool
            if item.origin_class is CaseOrigin.ADVERSARIAL_MUTATION
        }
        return (
            candidate.origin_class is CaseOrigin.ADVERSARIAL_MUTATION
            and candidate.mutation_lineage_id is not None
            and candidate.mutation_lineage_id not in existing
        )
    return False


def _problem_without_candidate(
    problem: FinalSelectionProblem,
    candidate_id: str,
) -> FinalSelectionProblem:
    candidates = tuple(item for item in problem.candidates if item.candidate_id != candidate_id)
    one_state = next(
        item
        for item in problem.constraint_set.constraints
        if item.kind is ConstraintKind.ONE_STATE_PER_CANDIDATE
    )
    constraints: list[SelectionConstraint] = [
        replace(
            one_state,
            constraint_id=f"RES369:ONE_STATE:{candidate.candidate_id}",
            candidate_ids=(candidate.candidate_id,),
        )
        for candidate in candidates
    ]
    for constraint in problem.constraint_set.constraints:
        if constraint.kind is ConstraintKind.ONE_STATE_PER_CANDIDATE:
            continue
        if constraint.kind is ConstraintKind.CONDITIONAL_COLOCATION:
            members = tuple(item for item in constraint.candidate_ids if item != candidate_id)
            if len(members) < 2:
                continue
            if members != constraint.candidate_ids:
                constraint = replace(
                    constraint,
                    constraint_id=(
                        "RES383:REMOVAL_RELATION:"
                        + canonical_hash((constraint.constraint_id, members)).removeprefix(
                            "sha256:"
                        )[:24]
                    ),
                    candidate_ids=members,
                )
            constraints.append(constraint)
        elif candidate_id not in constraint.candidate_ids:
            constraints.append(constraint)
    ordered_constraints = tuple(sorted(constraints, key=lambda item: item.constraint_id.encode()))
    constraint_set = SelectionConstraintSet(
        constraints=ordered_constraints,
        objectives=problem.constraint_set.objectives,
        allocation_clusters=_allocation_clusters(candidates),
    )
    return FinalSelectionProblem(
        candidates=candidates,
        constraint_set=constraint_set,
        authority_digest=problem.authority_digest,
        parent_provenance_registry=problem.parent_provenance_registry,
    )


def _pool_solver_config(config: SelectionSolverConfig | None) -> SelectionSolverConfig:
    if config is None:
        return PSE_V1_POOL_FEASIBILITY_SOLVER_PROFILE_V1
    if config != PSE_V1_POOL_FEASIBILITY_SOLVER_PROFILE_V1:
        raise ValueError("pool qualification requires the named pool-feasibility solver profile")
    return config


def qualify_candidate_removal_reserve(
    problem: FinalSelectionProblem,
    *,
    solver_config: SelectionSolverConfig | None = None,
) -> tuple[
    SelectionFeasibilityReceiptV1,
    tuple[SingleCandidateRemovalCheckV1, ...],
]:
    """Require an exact, independently validated solution after every one-item removal."""

    solver_config = _pool_solver_config(solver_config)
    baseline = solve_selection_feasibility(problem, solver_config=solver_config)
    if baseline.status is not FeasibilityStatus.FEASIBLE:
        return baseline, ()
    final_target = next(
        item.minimum
        for item in problem.constraint_set.constraints
        if item.kind is ConstraintKind.FINAL_COUNT
    )
    assert final_target is not None
    removals: list[SingleCandidateRemovalCheckV1] = []
    for candidate in problem.candidates:
        candidate_digest = canonical_hash(candidate.candidate_id)
        if len(problem.candidates) - 1 < final_target:
            removals.append(
                SingleCandidateRemovalCheckV1(
                    candidate_digest,
                    FeasibilityStatus.INFEASIBLE,
                    "FINAL_COUNT_LOWER_BOUND",
                )
            )
            continue
        receipt = solve_selection_feasibility(
            _problem_without_candidate(problem, candidate.candidate_id),
            solver_config=solver_config,
        )
        removals.append(
            SingleCandidateRemovalCheckV1(
                candidate_digest,
                receipt.status,
                "EXACT_FEASIBILITY_ORACLE",
                receipt.plan_digest,
                receipt.validation_digest,
            )
        )
    return baseline, tuple(removals)


def _deficit_requests_for_need(
    need: PoolBackfillNeedV1,
    inventory: AuthoritySupplyInventoryV1 | None,
    *,
    scenario_digest: str | None = None,
    removed_candidate_digest: str | None = None,
) -> tuple[ReserveDeficitV1, BackfillRequestV1]:
    deficit = ReserveDeficitV1(
        deficit_kind=ReserveDeficitKind.STRUCTURAL_COUNT,
        constraint_id=need.constraint_id,
        scenario_digest=scenario_digest,
        removed_candidate_digest=removed_candidate_digest,
        required_count=need.required_candidate_count,
        observed_count=need.present_candidate_count,
        affected_constraint_ids=(need.constraint_id,),
    )
    lanes = _authorable_lanes(inventory, need.origin_class) if inventory else ()
    request = BackfillRequestV1(
        request_kind=BackfillRequestKind.CONSTRAINT_MINIMUM,
        deficit_digest=deficit.deficit_digest,
        lane_ids=tuple(lane.lane_id for lane in lanes),
        requested_capacity=need.missing_candidate_count,
        required_origin=need.origin_class,
        constraint_id=need.constraint_id,
        split=need.split,
        feature_kind=need.feature_kind,
        feature_key=need.feature_key,
        scenario_digest=scenario_digest,
        requires_candidate_metadata=True,
    )
    return deficit, request


def _exact_deficits_and_requests(
    problem: FinalSelectionProblem,
    baseline: SelectionFeasibilityReceiptV1,
    removals: tuple[SingleCandidateRemovalCheckV1, ...],
    inventory: AuthoritySupplyInventoryV1 | None,
) -> tuple[tuple[ReserveDeficitV1, ...], tuple[BackfillRequestV1, ...]]:
    deficits: list[ReserveDeficitV1] = []
    requests: list[BackfillRequestV1] = []
    all_lanes = _authorable_lanes(inventory) if inventory else ()
    if baseline.status is FeasibilityStatus.INFEASIBLE:
        scenario_digest = problem.problem_digest
        deficit = ReserveDeficitV1(
            deficit_kind=ReserveDeficitKind.EXACT_BASELINE_INFEASIBLE,
            scenario_digest=scenario_digest,
        )
        deficits.append(deficit)
        requests.append(
            BackfillRequestV1(
                request_kind=BackfillRequestKind.EXACT_SELECTION_INTERACTION,
                deficit_digest=deficit.deficit_digest,
                lane_ids=tuple(lane.lane_id for lane in all_lanes),
                requested_capacity=None,
                scenario_digest=scenario_digest,
                requires_candidate_metadata=True,
            )
        )
        return tuple(deficits), tuple(requests)
    if baseline.status is FeasibilityStatus.UNKNOWN:
        return (
            (
                ReserveDeficitV1(
                    deficit_kind=ReserveDeficitKind.EXACT_ORACLE_UNKNOWN,
                    scenario_digest=problem.problem_digest,
                ),
            ),
            (),
        )
    candidates_by_digest = {canonical_hash(item.candidate_id): item for item in problem.candidates}
    for removal in removals:
        if removal.status is FeasibilityStatus.FEASIBLE:
            continue
        scenario_digest = canonical_hash((problem.problem_digest, removal.candidate_digest))
        if removal.status is FeasibilityStatus.UNKNOWN:
            deficits.append(
                ReserveDeficitV1(
                    deficit_kind=ReserveDeficitKind.EXACT_ORACLE_UNKNOWN,
                    scenario_digest=scenario_digest,
                    removed_candidate_digest=removal.candidate_digest,
                )
            )
            continue
        without = _problem_without_candidate(
            problem,
            candidates_by_digest[removal.candidate_digest].candidate_id,
        )
        needs = derive_pool_backfill_needs(without)
        if needs:
            for need in needs:
                deficit, request = _deficit_requests_for_need(
                    need,
                    inventory,
                    scenario_digest=scenario_digest,
                    removed_candidate_digest=removal.candidate_digest,
                )
                deficits.append(deficit)
                requests.append(request)
            continue
        interaction_digest = canonical_hash((scenario_digest, without.problem_digest))
        deficit = ReserveDeficitV1(
            deficit_kind=ReserveDeficitKind.EXACT_REMOVAL_INFEASIBLE,
            scenario_digest=interaction_digest,
            removed_candidate_digest=removal.candidate_digest,
        )
        deficits.append(deficit)
        requests.append(
            BackfillRequestV1(
                request_kind=BackfillRequestKind.EXACT_SELECTION_INTERACTION,
                deficit_digest=deficit.deficit_digest,
                lane_ids=tuple(lane.lane_id for lane in all_lanes),
                requested_capacity=None,
                scenario_digest=interaction_digest,
                requires_candidate_metadata=True,
            )
        )
    return tuple(deficits), tuple(requests)


def plan_variable_pool(
    initial_candidates: tuple[FinalSelectionCandidate, ...],
    *,
    supply_inventory: AuthoritySupplyInventoryV1 | None = None,
    materialized_backfill_candidates: tuple[MaterializedBackfillCandidateV1, ...] = (),
    parent_provenance_registry: tuple[MutationParentProvenance, ...] = (),
    solver_config: SelectionSolverConfig | None = None,
) -> PoolPlanningResultV1:
    """Retry exact reserve failures from governed lanes, stopping at missing metadata."""

    if not initial_candidates:
        raise ValueError("pool planning requires existing candidate metadata")
    solver_config = _pool_solver_config(solver_config)
    initial = tuple(sorted(initial_candidates, key=lambda item: item.candidate_id.encode()))
    if len({item.candidate_id for item in initial}) != len(initial):
        raise ValueError("initial pool candidate IDs must be unique")
    initial_ids = {item.candidate_id for item in initial}
    initial_hashes = {item.payload_hash for item in initial}
    available = tuple(
        sorted(
            materialized_backfill_candidates,
            key=lambda item: (item.lane_id.encode(), item.candidate.candidate_id.encode()),
        )
    )
    available_ids = tuple(item.candidate.candidate_id for item in available)
    backfill_hashes = tuple(item.candidate.payload_hash for item in available)
    if len(set(available_ids)) != len(available_ids) or len(set(backfill_hashes)) != len(
        backfill_hashes
    ):
        raise ValueError("materialized backfill candidate identities must be unique")
    if set(available_ids).intersection(initial_ids) or set(backfill_hashes).intersection(
        initial_hashes
    ):
        raise ValueError("backfill candidate duplicates an initial pool identity")
    if available and supply_inventory is None:
        raise ValueError("materialized backfill candidates require a bound authority inventory")
    lanes = (
        {lane.lane_id: lane for lane in supply_inventory.reserve_candidate_lanes}
        if supply_inventory
        else {}
    )
    use_counts: dict[str, int] = {}
    for binding in available:
        lane = lanes.get(binding.lane_id)
        if lane is None:
            raise ValueError("materialized backfill candidate references an unknown authority lane")
        validate_materialized_backfill_lane_binding(binding, lane)
        use_counts[binding.lane_id] = use_counts.get(binding.lane_id, 0) + 1
        if (
            lane.available_capacity is not None
            and use_counts[binding.lane_id] > lane.available_capacity
        ):
            raise ValueError("materialized backfill candidates exceed their governed lane capacity")

    pool = list(initial)
    remaining = {item.candidate.candidate_id: item for item in available}
    used_authorities: dict[str, tuple[str, str, str]] = {}
    final_problem: FinalSelectionProblem | None = None
    unresolved: tuple[PoolBackfillNeedV1, ...] = ()
    deficits: tuple[ReserveDeficitV1, ...] = ()
    requests: tuple[BackfillRequestV1, ...] = ()
    baseline: SelectionFeasibilityReceiptV1 | None = None
    removals: tuple[SingleCandidateRemovalCheckV1, ...] = ()

    while True:
        baseline = None
        removals = ()
        deficits = ()
        requests = ()
        final_problem = _build_problem(tuple(pool), parent_provenance_registry)
        unresolved = derive_pool_backfill_needs(final_problem)
        if unresolved:
            scored = []
            effective_pool = _planning_candidates(tuple(pool))
            for candidate_id, binding in remaining.items():
                lane = lanes[binding.lane_id]
                if not lane.may_author_backfill:
                    continue
                candidate = _planning_candidates((binding.candidate,))[0]
                score = sum(_contributes(candidate, need, effective_pool) for need in unresolved)
                if score:
                    scored.append((score, candidate_id.encode(), candidate_id, binding))
            if scored:
                _score, _key, candidate_id, binding = min(
                    scored, key=lambda item: (-item[0], item[1])
                )
                pool.append(binding.candidate)
                used_authorities[candidate_id] = (
                    binding.lane_id,
                    binding.authority_ref,
                    binding.authority_digest,
                )
                del remaining[candidate_id]
                continue
            generated = tuple(
                _deficit_requests_for_need(need, supply_inventory) for need in unresolved
            )
            deficits = tuple(item[0] for item in generated)
            requests = tuple(item[1] for item in generated)
            break

        baseline, removals = qualify_candidate_removal_reserve(
            final_problem,
            solver_config=solver_config,
        )
        if baseline.status is FeasibilityStatus.UNKNOWN or any(
            item.status is FeasibilityStatus.UNKNOWN for item in removals
        ):
            deficits, requests = _exact_deficits_and_requests(
                final_problem, baseline, removals, supply_inventory
            )
            break
        if baseline.status is FeasibilityStatus.FEASIBLE and all(
            item.status is FeasibilityStatus.FEASIBLE for item in removals
        ):
            break
        deficits, requests = _exact_deficits_and_requests(
            final_problem, baseline, removals, supply_inventory
        )
        candidates_by_digest = {
            canonical_hash(item.candidate_id): item for item in final_problem.candidates
        }
        failed_scenarios = []
        if baseline.status is FeasibilityStatus.INFEASIBLE:
            failed_scenarios.append(final_problem)
        else:
            failed_scenarios.extend(
                _problem_without_candidate(
                    final_problem,
                    candidates_by_digest[removal.candidate_digest].candidate_id,
                )
                for removal in removals
                if removal.status is FeasibilityStatus.INFEASIBLE
            )
        viable: list[MaterializedBackfillCandidateV1] = []
        for binding in remaining.values():
            if not _eligible(_planning_candidates((binding.candidate,))[0]):
                continue
            restores_failed_scenario = False
            for scenario in failed_scenarios:
                trial = solve_selection_feasibility(
                    _build_problem(
                        (*scenario.candidates, binding.candidate),
                        parent_provenance_registry,
                    ),
                    solver_config=solver_config,
                )
                restores_failed_scenario |= trial.status is FeasibilityStatus.FEASIBLE
            if restores_failed_scenario:
                viable.append(binding)
        if not viable:
            break
        next_candidate = min(
            viable,
            key=lambda item: (
                item.candidate.review_eligibility is not ReviewEligibility.APPROVED,
                item.lane_id.encode(),
                item.candidate.candidate_id.encode(),
            ),
        )
        pool.append(next_candidate.candidate)
        used_authorities[next_candidate.candidate.candidate_id] = (
            next_candidate.lane_id,
            next_candidate.authority_ref,
            next_candidate.authority_digest,
        )
        del remaining[next_candidate.candidate.candidate_id]

    assert final_problem is not None
    final_target = next(
        item.minimum
        for item in final_problem.constraint_set.constraints
        if item.kind is ConstraintKind.FINAL_COUNT
    )
    assert final_target is not None
    plan = PoolMetadataPlanV1(
        candidates=tuple(pool),
        parent_provenance_registry=final_problem.parent_provenance_registry,
        backfill_authorities=tuple(
            sorted(
                [
                    (candidate_id, lane_id, authority_ref, authority_digest)
                    for candidate_id, (
                        lane_id,
                        authority_ref,
                        authority_digest,
                    ) in used_authorities.items()
                ],
                key=lambda item: item[0].encode(),
            )
        ),
    )
    critical_constraints = tuple(
        item
        for item in final_problem.constraint_set.constraints
        if item.kind is ConstraintKind.FEATURE_MINIMUM
        and item.feature is not None
        and item.feature.kind is FeatureKind.CRITICAL_ERROR
    )
    needs_by_id = {item.constraint_id for item in unresolved}
    critical_ready = sum(item.constraint_id not in needs_by_id for item in critical_constraints)
    unknown = baseline is not None and (
        baseline.status is FeasibilityStatus.UNKNOWN
        or any(item.status is FeasibilityStatus.UNKNOWN for item in removals)
    )
    exact_qualified = (
        baseline is not None
        and baseline.status is FeasibilityStatus.FEASIBLE
        and all(item.status is FeasibilityStatus.FEASIBLE for item in removals)
    )
    if exact_qualified and not unresolved:
        status = PoolPlanStatus.QUALIFIED
    elif unknown:
        status = PoolPlanStatus.UNKNOWN
    else:
        empty_lane_request = any(not item.lane_ids for item in requests)
        exhausted = bool(
            supply_inventory
            and supply_inventory.authority_inventory_complete
            and supply_inventory.capacity_scope_complete
            and empty_lane_request
        )
        if exhausted:
            status = PoolPlanStatus.AUTHORITY_EXPANSION_REQUIRED
        elif unresolved and any(item.lane_ids for item in requests):
            status = PoolPlanStatus.BACKFILL_REQUIRED
        else:
            status = PoolPlanStatus.METADATA_REQUIRED
    if status is PoolPlanStatus.QUALIFIED:
        critical_status = CriticalReserveStatus.QUALIFIED
    elif status is PoolPlanStatus.UNKNOWN:
        critical_status = CriticalReserveStatus.UNKNOWN
    elif status is PoolPlanStatus.AUTHORITY_EXPANSION_REQUIRED:
        critical_status = CriticalReserveStatus.AUTHORITY_EXPANSION_REQUIRED
    elif any(item.feature_kind is FeatureKind.CRITICAL_ERROR for item in unresolved) or any(
        item.request_kind is BackfillRequestKind.EXACT_SELECTION_INTERACTION for item in requests
    ):
        critical_status = CriticalReserveStatus.METADATA_REQUIRED
    elif unresolved:
        critical_status = CriticalReserveStatus.BACKFILL_REQUIRED
    else:
        critical_status = CriticalReserveStatus.METADATA_REQUIRED

    status_reasons = tuple(
        [
            f"{need.constraint_id}: missing {need.missing_candidate_count} "
            "eligible metadata candidate(s)"
            for need in unresolved
        ]
        + [
            f"{deficit.deficit_kind.value}: exact deficit {deficit.deficit_digest}"
            for deficit in deficits
        ]
    )
    removal_digest = canonical_hash(removals)
    eligible_count = sum(_eligible(candidate) for candidate in _planning_candidates(tuple(pool)))
    receipt = PoolReserveReceiptV1(
        receipt_version=POOL_RESERVE_RECEIPT_VERSION,
        status=status,
        pool_plan_digest=plan.plan_digest,
        initial_candidate_count=len(initial),
        candidate_count=len(pool),
        backfill_candidate_count=len(used_authorities),
        final_target_count=final_target,
        eligible_candidate_count=eligible_count,
        usable_reserve_candidate_count=max(0, eligible_count - final_target),
        supply_inventory_digest=supply_inventory.inventory_digest if supply_inventory else None,
        authority_inventory_complete=(
            supply_inventory.authority_inventory_complete if supply_inventory else False
        ),
        capacity_scope_complete=supply_inventory.capacity_scope_complete
        if supply_inventory
        else False,
        solver_profile_version=POOL_FEASIBILITY_SOLVER_PROFILE_VERSION,
        baseline_feasibility_status=baseline.status if baseline else None,
        checked_removal_count=len(removals),
        feasible_removal_count=sum(item.status is FeasibilityStatus.FEASIBLE for item in removals),
        infeasible_removal_count=sum(
            item.status is FeasibilityStatus.INFEASIBLE for item in removals
        ),
        unknown_removal_count=sum(item.status is FeasibilityStatus.UNKNOWN for item in removals),
        removal_case_digest=removal_digest,
        critical_obligation_count=len(critical_constraints),
        critical_obligations_with_structural_reserve=critical_ready,
        independent_critical_reserve_status=critical_status,
        unresolved_backfill_needs=unresolved,
        reserve_deficits=deficits,
        backfill_requests=requests,
        status_reasons=status_reasons,
        authority_exhaustion_proven=status is PoolPlanStatus.AUTHORITY_EXPANSION_REQUIRED,
    )
    return PoolPlanningResultV1(plan=plan, receipt=receipt)


__all__ = [
    "CriticalReserveStatus",
    "MaterializedBackfillCandidateV1",
    "PoolBackfillNeedV1",
    "PoolMetadataPlanV1",
    "PoolPlanStatus",
    "PoolPlanningResultV1",
    "PoolReserveReceiptV1",
    "SingleCandidateRemovalCheckV1",
    "assess_authority_supply_inventory",
    "derive_pool_backfill_needs",
    "plan_variable_pool",
    "qualify_candidate_removal_reserve",
]
