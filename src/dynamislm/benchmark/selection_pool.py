"""Variable metadata-only pool planning and single-removal reserve proof."""

from __future__ import annotations

import enum
import re
from dataclasses import dataclass, replace

from dynamislm.benchmark.constants import CaseOrigin, SplitName
from dynamislm.benchmark.selection_constraints import (
    _allocation_clusters,
    build_final_selection_problem,
)
from dynamislm.benchmark.selection_contracts import (
    ConstraintKind,
    FeasibilityStatus,
    FeatureKind,
    FinalSelectionCandidate,
    FinalSelectionProblem,
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


class PoolPlanStatus(enum.StrEnum):
    QUALIFIED = "QUALIFIED"
    AUTHORITY_EXPANSION_REQUIRED = "AUTHORITY_EXPANSION_REQUIRED"
    UNKNOWN = "UNKNOWN"


class CriticalReserveStatus(enum.StrEnum):
    QUALIFIED = "QUALIFIED"
    AUTHORITY_EXPANSION_REQUIRED = "AUTHORITY_EXPANSION_REQUIRED"
    UNKNOWN = "UNKNOWN"


@register_serializable_type
@dataclass(frozen=True, slots=True)
class GovernedBackfillCandidateV1:
    candidate: FinalSelectionCandidate
    authority_ref: str
    authority_digest: str

    def __post_init__(self) -> None:
        if not self.authority_ref.strip() or _SHA256.fullmatch(self.authority_digest) is None:
            raise ValueError("backfill candidate requires a named, digested authority")


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
    backfill_authorities: tuple[tuple[str, str, str], ...]
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
            for candidate_id, _ref, _digest in self.backfill_authorities
        ):
            raise ValueError("backfill authority binding references a candidate outside the pool")
        if any(
            not authority_ref.strip() or _SHA256.fullmatch(digest) is None
            for _candidate, authority_ref, digest in self.backfill_authorities
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
    reserve_candidate_count: int
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
    authority_expansion_reasons: tuple[str, ...]
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
            self.reserve_candidate_count,
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
            or self.reserve_candidate_count
            != max(0, self.candidate_count - self.final_target_count)
        ):
            raise ValueError("pool receipt digest or candidate counts are inconsistent")
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


def qualify_candidate_removal_reserve(
    problem: FinalSelectionProblem,
    *,
    solver_config: SelectionSolverConfig | None = None,
) -> tuple[
    SelectionFeasibilityReceiptV1,
    tuple[SingleCandidateRemovalCheckV1, ...],
]:
    """Require an exact, independently validated solution after every one-item removal."""

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


def plan_variable_pool(
    initial_candidates: tuple[FinalSelectionCandidate, ...],
    *,
    governed_backfill_candidates: tuple[GovernedBackfillCandidateV1, ...] = (),
    parent_provenance_registry: tuple[MutationParentProvenance, ...] = (),
    solver_config: SelectionSolverConfig | None = None,
) -> PoolPlanningResultV1:
    """Add only backfill that addresses a measured bound, then prove every removal."""

    if not initial_candidates:
        raise ValueError("pool planning requires existing candidate metadata")
    initial = tuple(sorted(initial_candidates, key=lambda item: item.candidate_id.encode()))
    if len({item.candidate_id for item in initial}) != len(initial):
        raise ValueError("initial pool candidate IDs must be unique")
    available = tuple(
        sorted(governed_backfill_candidates, key=lambda item: item.candidate.candidate_id.encode())
    )
    available_ids = tuple(item.candidate.candidate_id for item in available)
    if len(set(available_ids)) != len(available_ids):
        raise ValueError("governed backfill candidate IDs must be unique")
    initial_ids = {item.candidate_id for item in initial}
    initial_hashes = {item.payload_hash for item in initial}
    backfill_hashes = tuple(item.candidate.payload_hash for item in available)
    if any(item.candidate.candidate_id in initial_ids for item in available) or set(
        backfill_hashes
    ).intersection(initial_hashes):
        raise ValueError("backfill candidate duplicates an initial pool identity")
    if len(set(backfill_hashes)) != len(backfill_hashes):
        raise ValueError("governed backfill candidate payload identities must be unique")
    pool = list(initial)
    used_authorities: dict[str, tuple[str, str]] = {}
    remaining = {item.candidate.candidate_id: item for item in available}

    while True:
        problem = _build_problem(tuple(pool), parent_provenance_registry)
        needs = derive_pool_backfill_needs(problem)
        if not needs:
            break
        scored = []
        for candidate_id, binding in remaining.items():
            candidate = _planning_candidates((binding.candidate,))[0]
            effective_pool = _planning_candidates(tuple(pool))
            score = sum(_contributes(candidate, need, effective_pool) for need in needs)
            if score:
                scored.append((score, candidate_id.encode(), candidate_id, binding))
        if not scored:
            break
        _score, _key, candidate_id, binding = min(scored, key=lambda item: (-item[0], item[1]))
        pool.append(binding.candidate)
        used_authorities[candidate_id] = (binding.authority_ref, binding.authority_digest)
        del remaining[candidate_id]

    final_problem = _build_problem(tuple(pool), parent_provenance_registry)
    unresolved = derive_pool_backfill_needs(final_problem)
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
                    (candidate_id, authority_ref, authority_digest)
                    for candidate_id, (authority_ref, authority_digest) in used_authorities.items()
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
    needs_by_id = {item.constraint_id: item for item in unresolved}
    critical_ready = sum(item.constraint_id not in needs_by_id for item in critical_constraints)
    reasons = tuple(
        f"{need.constraint_id}: missing {need.missing_candidate_count} "
        "eligible metadata candidate(s)"
        for need in unresolved
    )
    if unresolved:
        status = PoolPlanStatus.AUTHORITY_EXPANSION_REQUIRED
        baseline = None
        removals: tuple[SingleCandidateRemovalCheckV1, ...] = ()
        critical_status = CriticalReserveStatus.AUTHORITY_EXPANSION_REQUIRED
    else:
        baseline, removals = qualify_candidate_removal_reserve(
            final_problem,
            solver_config=solver_config,
        )
        if baseline.status is FeasibilityStatus.UNKNOWN or any(
            item.status is FeasibilityStatus.UNKNOWN for item in removals
        ):
            status = PoolPlanStatus.UNKNOWN
            critical_status = CriticalReserveStatus.UNKNOWN
        elif baseline.status is FeasibilityStatus.INFEASIBLE:
            status = PoolPlanStatus.AUTHORITY_EXPANSION_REQUIRED
            critical_status = CriticalReserveStatus.AUTHORITY_EXPANSION_REQUIRED
            reasons = ("exact baseline joint feasibility is INFEASIBLE",)
        elif baseline.status is FeasibilityStatus.FEASIBLE and all(
            item.status is FeasibilityStatus.FEASIBLE for item in removals
        ):
            status = PoolPlanStatus.QUALIFIED
            critical_status = CriticalReserveStatus.QUALIFIED
        else:
            status = PoolPlanStatus.AUTHORITY_EXPANSION_REQUIRED
            critical_status = CriticalReserveStatus.AUTHORITY_EXPANSION_REQUIRED
            failed = sum(item.status is FeasibilityStatus.INFEASIBLE for item in removals)
            reasons = (f"exact joint feasibility failed for {failed} single-candidate removal(s)",)

    removal_digest = canonical_hash(removals)
    receipt = PoolReserveReceiptV1(
        receipt_version=POOL_RESERVE_RECEIPT_VERSION,
        status=status,
        pool_plan_digest=plan.plan_digest,
        initial_candidate_count=len(initial),
        candidate_count=len(pool),
        backfill_candidate_count=len(used_authorities),
        final_target_count=final_target,
        reserve_candidate_count=max(0, len(pool) - final_target),
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
        authority_expansion_reasons=reasons,
    )
    return PoolPlanningResultV1(plan=plan, receipt=receipt)


__all__ = [
    "CriticalReserveStatus",
    "GovernedBackfillCandidateV1",
    "PoolBackfillNeedV1",
    "PoolMetadataPlanV1",
    "PoolPlanStatus",
    "PoolPlanningResultV1",
    "PoolReserveReceiptV1",
    "SingleCandidateRemovalCheckV1",
    "derive_pool_backfill_needs",
    "plan_variable_pool",
    "qualify_candidate_removal_reserve",
]
