"""Immutable, solver-independent contracts for PSE V1 final selection."""

from __future__ import annotations

import enum
import re
from dataclasses import dataclass

from dynamislm.benchmark.constants import CAPABILITY_IDS, FAMILY_IDS, CaseOrigin, SplitName
from dynamislm.serialization import canonical_hash, register_serializable_type

SELECTION_CONSTRAINT_SCHEMA = "PSE-V1-JOINT-SELECTION-CONSTRAINTS@1.0.0"
SELECTION_PLAN_VERSION = "PSE-V1-JOINT-SELECTION-PLAN@1.0.0"
SELECTION_RECEIPT_VERSION = "PSE-V1-JOINT-SELECTION-RECEIPT@1.0.0"
SELECTION_VALIDATOR_VERSION = "PSE-V1-JOINT-SELECTION-VALIDATOR@1.0.0"
SELECTION_PRODUCTION_SOLVER_PROFILE_VERSION = "PSE-V1-PRODUCTION-SELECTION-SOLVER@1.0.0"
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")


class AssignmentState(enum.StrEnum):
    OUT = "OUT"
    PUBLIC_DEVELOPMENT = SplitName.PUBLIC_DEVELOPMENT.value
    FROZEN_VALIDATION = SplitName.FROZEN_VALIDATION.value
    HIDDEN_FINAL = SplitName.HIDDEN_FINAL.value

    @property
    def split_name(self) -> SplitName | None:
        return None if self is AssignmentState.OUT else SplitName(self.value)


class ReviewEligibility(enum.StrEnum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    PENDING = "PENDING"
    UNAPPROVED = "UNAPPROVED"
    INVALID = "INVALID"


class FeatureKind(enum.StrEnum):
    CELL = "CELL"
    ROW_TAG = "ROW_TAG"
    ROW_ERROR = "ROW_ERROR"
    C18_REFUSAL = "C18_REFUSAL"
    ANSWERABLE = "ANSWERABLE"
    CRITICAL_ERROR = "CRITICAL_ERROR"


class BalanceDimension(enum.StrEnum):
    FAMILY = "FAMILY"
    CAPABILITY = "CAPABILITY"
    QUESTION_CLASS = "QUESTION_CLASS"
    ANSWER_OUTCOME = "ANSWER_OUTCOME"
    ORIGIN = "ORIGIN"
    DIFFICULTY = "DIFFICULTY"
    CRITICAL_ERROR_ELIGIBILITY = "CRITICAL_ERROR_ELIGIBILITY"
    TAG_CELL = "TAG_CELL"


class IsolationIdentityKind(enum.StrEnum):
    SOURCE_FAMILY = "source-family"
    SOURCE_DOCUMENT = "source-document"
    SOURCE_ARTIFACT = "source-artifact"
    GENERAL_ARTIFACT = "general-artifact"
    BENCHMARK_ARTIFACT = "benchmark-artifact"
    TRAINING_EXCLUSION = "training-exclusion"
    CONSTRUCT_TEST = "construct-test"
    PROVIDER_EXPORT = "provider-export"
    PROTOCOL_TEMPLATE = "protocol-template"
    EXPERT_AUTHOR_BATCH = "expert-author-batch"
    GENERATOR_FAMILY = "generator-family"
    GENERATOR_SEED_NAMESPACE = "seed-namespace"
    GENERATOR_SEED_BLOCK = "seed-block"
    MUTATION_LINEAGE = "mutation-lineage"
    MUTATION_PARENT = "mutation-parent-candidate"
    RES71_ENGINE_REFERENCE_CASE = "res71-engine-reference-case"


class RelationKind(enum.StrEnum):
    ISOLATION_CLUSTER = "ISOLATION_CLUSTER"
    ISOLATION_IDENTITY = "ISOLATION_IDENTITY"
    MUTATION_LINEAGE = "MUTATION_LINEAGE"
    MUTATION_PARENT = "MUTATION_PARENT"
    EXACT_SHINGLE = "EXACT_SHINGLE"


class ConstraintKind(enum.StrEnum):
    ONE_STATE_PER_CANDIDATE = "ONE_STATE_PER_CANDIDATE"
    FINAL_COUNT = "FINAL_COUNT"
    SPLIT_COUNT = "SPLIT_COUNT"
    FEATURE_MINIMUM = "FEATURE_MINIMUM"
    ORIGIN_BOUNDS = "ORIGIN_BOUNDS"
    MUTATION_LINEAGE_MINIMUM = "MUTATION_LINEAGE_MINIMUM"
    REVIEW_OUT_ONLY = "REVIEW_OUT_ONLY"
    QUALIFICATION_OUT_ONLY = "QUALIFICATION_OUT_ONLY"
    SYNTHETIC_SPLIT_LOCK = "SYNTHETIC_SPLIT_LOCK"
    CONDITIONAL_COLOCATION = "CONDITIONAL_COLOCATION"
    MUTATION_PARENT_PROVENANCE = "MUTATION_PARENT_PROVENANCE"
    MUTATION_PARENT_CELL_INHERITANCE = "MUTATION_PARENT_CELL_INHERITANCE"


class ObjectiveKind(enum.StrEnum):
    PROPORTIONAL_SPLIT_BALANCE = "PROPORTIONAL_SPLIT_BALANCE"
    HASH_CLUSTER_PREFERENCE = "HASH_CLUSTER_PREFERENCE"
    CANONICAL_ASSIGNMENT = "CANONICAL_ASSIGNMENT"


class SolveStatus(enum.StrEnum):
    OPTIMAL = "OPTIMAL"
    INFEASIBLE = "INFEASIBLE"
    UNKNOWN = "UNKNOWN"


class ValidationStatus(enum.StrEnum):
    VALID = "VALID"
    INVALID = "INVALID"


class FeasibilityStatus(enum.StrEnum):
    FEASIBLE = "FEASIBLE"
    INFEASIBLE = "INFEASIBLE"
    UNKNOWN = "UNKNOWN"


@register_serializable_type
@dataclass(frozen=True, slots=True)
class SelectionFeature:
    kind: FeatureKind
    key: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", FeatureKind(self.kind))
        sizes = {
            FeatureKind.CELL: 2,
            FeatureKind.ROW_TAG: 2,
            FeatureKind.ROW_ERROR: 2,
            FeatureKind.C18_REFUSAL: 1,
            FeatureKind.ANSWERABLE: 0,
            FeatureKind.CRITICAL_ERROR: 1,
        }
        if not isinstance(self.key, tuple) or len(self.key) != sizes[self.kind]:
            raise ValueError(f"{self.kind.value} feature has an invalid key")
        if any(not isinstance(value, str) or not value.strip() for value in self.key):
            raise ValueError("feature keys must be non-empty strings")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class SelectionBalanceCell:
    dimension: BalanceDimension
    key: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "dimension", BalanceDimension(self.dimension))
        expected_size = 2 if self.dimension is BalanceDimension.TAG_CELL else 1
        if not isinstance(self.key, tuple) or len(self.key) != expected_size:
            raise ValueError("balance cell has an invalid key")
        if any(not isinstance(value, str) or not value.strip() for value in self.key):
            raise ValueError("balance cell keys must be non-empty strings")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class IsolationIdentity:
    kind: IsolationIdentityKind
    identity: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", IsolationIdentityKind(self.kind))
        if not isinstance(self.identity, str) or not self.identity.strip():
            raise ValueError("isolation identity must be non-empty")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class MutationParentProvenance:
    candidate_id: str
    payload_hash: str
    cell: tuple[str, str]

    def __post_init__(self) -> None:
        if not isinstance(self.candidate_id, str) or not self.candidate_id.strip():
            raise ValueError("parent candidate_id must be non-empty")
        if _SHA256.fullmatch(self.payload_hash) is None:
            raise ValueError("parent payload_hash must be a canonical SHA-256 digest")
        if (
            not isinstance(self.cell, tuple)
            or len(self.cell) != 2
            or self.cell[0] not in CAPABILITY_IDS
            or self.cell[1] not in FAMILY_IDS
        ):
            raise ValueError("parent cell must be a frozen capability-family pair")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class FinalSelectionCandidate:
    candidate_id: str
    payload_hash: str
    origin_class: CaseOrigin
    review_eligibility: ReviewEligibility
    features: tuple[SelectionFeature, ...]
    balance_cells: tuple[SelectionBalanceCell, ...]
    isolation_cluster_id: str
    allocation_stratum: str
    cell: tuple[str, str]
    isolation_identities: tuple[IsolationIdentity, ...] = ()
    exact_shingle_digests: tuple[str, ...] = ()
    generator_seed_blocks: tuple[str, ...] = ()
    mutation_lineage_id: str | None = None
    mutation_parent_candidate_id: str | None = None
    mutation_parent_payload_hash: str | None = None
    mutation_cell_exception_authority_ref: str | None = None
    locked_split: SplitName | None = None
    qualification_excluded: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.candidate_id, str) or not self.candidate_id.strip():
            raise ValueError("candidate_id must be non-empty")
        if _SHA256.fullmatch(self.payload_hash) is None:
            raise ValueError("payload_hash must be a canonical SHA-256 digest")
        object.__setattr__(self, "origin_class", CaseOrigin(self.origin_class))
        object.__setattr__(self, "review_eligibility", ReviewEligibility(self.review_eligibility))
        if self.locked_split is not None:
            object.__setattr__(self, "locked_split", SplitName(self.locked_split))
        for name in ("isolation_cluster_id", "allocation_stratum"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name).strip():
                raise ValueError(f"{name} must be non-empty")
        for name, values in (
            ("features", self.features),
            ("balance_cells", self.balance_cells),
            ("isolation_identities", self.isolation_identities),
            ("exact_shingle_digests", self.exact_shingle_digests),
            ("generator_seed_blocks", self.generator_seed_blocks),
        ):
            if not isinstance(values, tuple) or len(set(values)) != len(values):
                raise ValueError(f"{name} must be an immutable tuple without duplicates")
        if self.features != tuple(sorted(self.features, key=lambda x: (x.kind.value, x.key))):
            raise ValueError("features must be canonically ordered")
        if self.balance_cells != tuple(
            sorted(self.balance_cells, key=lambda x: (x.dimension.value, x.key))
        ):
            raise ValueError("balance_cells must be canonically ordered")
        if self.isolation_identities != tuple(
            sorted(self.isolation_identities, key=lambda x: (x.kind.value, x.identity.encode()))
        ):
            raise ValueError("isolation_identities must be canonically ordered")
        if not any(
            item.kind is IsolationIdentityKind.SOURCE_FAMILY for item in self.isolation_identities
        ):
            raise ValueError("candidate requires a source-family isolation identity")
        if (
            not isinstance(self.cell, tuple)
            or len(self.cell) != 2
            or self.cell[0] not in CAPABILITY_IDS
            or self.cell[1] not in FAMILY_IDS
        ):
            raise ValueError("cell must be a frozen capability-family pair")
        if not self.exact_shingle_digests:
            raise ValueError("candidate requires retained exact-shingle identity")
        if any(_SHA256.fullmatch(value) is None for value in self.exact_shingle_digests):
            raise ValueError("exact shingle digests must be canonical SHA-256 digests")
        if any(
            not isinstance(value, str) or not value.strip() for value in self.generator_seed_blocks
        ):
            raise ValueError("generator_seed_blocks must contain non-empty strings")
        if not isinstance(self.qualification_excluded, bool):
            raise ValueError("qualification_excluded must be boolean")
        is_mutation = self.origin_class is CaseOrigin.ADVERSARIAL_MUTATION
        mutation_fields = (
            self.mutation_lineage_id,
            self.mutation_parent_candidate_id,
        )
        if is_mutation and any(not value for value in mutation_fields):
            raise ValueError("mutation candidates require lineage and parent identities")
        if not is_mutation and any(
            value is not None
            for value in (
                *mutation_fields,
                self.mutation_parent_payload_hash,
                self.mutation_cell_exception_authority_ref,
            )
        ):
            raise ValueError("only mutation candidates may bind mutation parent provenance")
        if self.mutation_parent_candidate_id == self.candidate_id:
            raise ValueError("mutation candidate cannot be its own parent")
        if (
            self.mutation_parent_payload_hash is not None
            and _SHA256.fullmatch(self.mutation_parent_payload_hash) is None
        ):
            raise ValueError("mutation parent payload hash must be a canonical SHA-256 digest")
        if (
            self.mutation_cell_exception_authority_ref is not None
            and not self.mutation_cell_exception_authority_ref.strip()
        ):
            raise ValueError("mutation cell exception requires an authority reference")
        if self.origin_class is CaseOrigin.DETERMINISTIC_SYNTHETIC and self.locked_split is None:
            raise ValueError("synthetic candidates require a split lock")
        if (
            self.origin_class is not CaseOrigin.DETERMINISTIC_SYNTHETIC
            and self.locked_split is not None
        ):
            raise ValueError("only synthetic candidates may carry a split lock")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class SelectionConstraint:
    constraint_id: str
    authority_ref: str
    kind: ConstraintKind
    candidate_ids: tuple[str, ...] = ()
    split: SplitName | None = None
    feature: SelectionFeature | None = None
    origin_class: CaseOrigin | None = None
    minimum: int | None = None
    maximum: int | None = None
    locked_split: SplitName | None = None
    relation_kind: RelationKind | None = None
    related_id: str | None = None
    related_payload_hash: str | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        if not self.constraint_id.strip() or not self.authority_ref.strip():
            raise ValueError("constraint_id and authority_ref must be non-empty")
        object.__setattr__(self, "kind", ConstraintKind(self.kind))
        if self.split is not None:
            object.__setattr__(self, "split", SplitName(self.split))
        if self.origin_class is not None:
            object.__setattr__(self, "origin_class", CaseOrigin(self.origin_class))
        if self.locked_split is not None:
            object.__setattr__(self, "locked_split", SplitName(self.locked_split))
        if self.relation_kind is not None:
            object.__setattr__(self, "relation_kind", RelationKind(self.relation_kind))
        if not isinstance(self.candidate_ids, tuple) or self.candidate_ids != tuple(
            sorted(set(self.candidate_ids), key=str.encode)
        ):
            raise ValueError("constraint candidate_ids must be sorted and unique")
        if any(not value.strip() for value in self.candidate_ids):
            raise ValueError("constraint candidate_ids must be non-empty")
        bounded = {
            ConstraintKind.FINAL_COUNT,
            ConstraintKind.SPLIT_COUNT,
            ConstraintKind.FEATURE_MINIMUM,
            ConstraintKind.ORIGIN_BOUNDS,
            ConstraintKind.MUTATION_LINEAGE_MINIMUM,
        }
        if self.kind in bounded:
            if self.minimum is None or self.minimum < 0:
                raise ValueError("bounded constraints require a non-negative minimum")
            if self.maximum is not None and self.maximum < self.minimum:
                raise ValueError("constraint maximum cannot be below its minimum")
        elif self.minimum is not None or self.maximum is not None:
            raise ValueError("this constraint kind cannot carry numeric bounds")
        if self.kind is ConstraintKind.ONE_STATE_PER_CANDIDATE:
            valid = len(self.candidate_ids) == 1
        elif self.kind in {ConstraintKind.FINAL_COUNT, ConstraintKind.MUTATION_LINEAGE_MINIMUM}:
            valid = not self.candidate_ids and self.split is None and self.feature is None
        elif self.kind is ConstraintKind.SPLIT_COUNT:
            valid = self.split is not None and not self.candidate_ids
        elif self.kind is ConstraintKind.FEATURE_MINIMUM:
            valid = self.split is not None and self.feature is not None
        elif self.kind is ConstraintKind.ORIGIN_BOUNDS:
            valid = self.origin_class is not None and not self.candidate_ids
        elif self.kind in {
            ConstraintKind.REVIEW_OUT_ONLY,
            ConstraintKind.QUALIFICATION_OUT_ONLY,
        }:
            valid = len(self.candidate_ids) == 1 and self.reason is not None
        elif self.kind is ConstraintKind.SYNTHETIC_SPLIT_LOCK:
            valid = len(self.candidate_ids) == 1 and self.locked_split is not None
        elif self.kind is ConstraintKind.CONDITIONAL_COLOCATION:
            valid = len(self.candidate_ids) >= 2 and self.relation_kind is not None
        elif self.kind in {
            ConstraintKind.MUTATION_PARENT_PROVENANCE,
            ConstraintKind.MUTATION_PARENT_CELL_INHERITANCE,
        }:
            valid = len(self.candidate_ids) == 1 and self.related_id is not None
        else:
            valid = False
        if not valid:
            raise ValueError(f"invalid fields for {self.kind.value} constraint")
        if (
            self.related_payload_hash is not None
            and _SHA256.fullmatch(self.related_payload_hash) is None
        ):
            raise ValueError("related_payload_hash must be a canonical SHA-256 digest")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class SelectionObjective:
    objective_id: str
    authority_ref: str
    kind: ObjectiveKind

    def __post_init__(self) -> None:
        if not self.objective_id.strip() or not self.authority_ref.strip():
            raise ValueError("objective_id and authority_ref must be non-empty")
        object.__setattr__(self, "kind", ObjectiveKind(self.kind))


@register_serializable_type
@dataclass(frozen=True, slots=True)
class AllocationCluster:
    cluster_id: str
    candidate_ids: tuple[str, ...]
    cluster_key: str
    preferred_split: SplitName

    def __post_init__(self) -> None:
        if not self.cluster_id.strip() or not self.candidate_ids:
            raise ValueError("allocation cluster requires an ID and members")
        if self.candidate_ids != tuple(sorted(set(self.candidate_ids), key=str.encode)):
            raise ValueError("allocation cluster members must be sorted and unique")
        if _SHA256.fullmatch(self.cluster_key) is None:
            raise ValueError("cluster_key must be a canonical SHA-256 digest")
        object.__setattr__(self, "preferred_split", SplitName(self.preferred_split))


@register_serializable_type
@dataclass(frozen=True, slots=True)
class SelectionConstraintSet:
    constraints: tuple[SelectionConstraint, ...]
    objectives: tuple[SelectionObjective, ...] = ()
    allocation_clusters: tuple[AllocationCluster, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.constraints, tuple) or not isinstance(self.objectives, tuple):
            raise ValueError("constraint and objective inventories must be tuples")
        ids = tuple(item.constraint_id for item in self.constraints)
        if ids != tuple(sorted(set(ids), key=str.encode)):
            raise ValueError("constraints must have unique, canonically ordered IDs")
        objective_ids = tuple(item.objective_id for item in self.objectives)
        if len(set(objective_ids)) != len(objective_ids):
            raise ValueError("objective IDs must be unique")
        if not isinstance(self.allocation_clusters, tuple):
            raise ValueError("allocation_clusters must be an immutable tuple")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class FinalSelectionProblem:
    candidates: tuple[FinalSelectionCandidate, ...]
    constraint_set: SelectionConstraintSet
    authority_digest: str
    parent_provenance_registry: tuple[MutationParentProvenance, ...] = ()

    def __post_init__(self) -> None:
        if _SHA256.fullmatch(self.authority_digest) is None:
            raise ValueError("authority_digest must be a canonical SHA-256 digest")
        if not isinstance(self.candidates, tuple) or not self.candidates:
            raise ValueError("final selection requires an immutable non-empty candidate pool")
        ordered = tuple(sorted(self.candidates, key=lambda item: item.candidate_id.encode()))
        ids = tuple(item.candidate_id for item in ordered)
        hashes = tuple(item.payload_hash for item in ordered)
        if len(set(ids)) != len(ids) or len(set(hashes)) != len(hashes):
            raise ValueError("candidate IDs and payload hashes must be unique")
        object.__setattr__(self, "candidates", ordered)
        if not isinstance(self.parent_provenance_registry, tuple):
            raise ValueError("parent provenance registry must be an immutable tuple")
        external_ids = tuple(item.candidate_id for item in self.parent_provenance_registry)
        if len(set(external_ids)) != len(external_ids):
            raise ValueError("parent provenance registry IDs must be unique")
        registry = {item.candidate_id: item for item in self.parent_provenance_registry}
        for candidate in ordered:
            binding = MutationParentProvenance(
                candidate.candidate_id,
                candidate.payload_hash,
                candidate.cell,
            )
            prior = registry.get(candidate.candidate_id)
            if prior is None:
                registry[candidate.candidate_id] = binding
                continue
            if prior.payload_hash != binding.payload_hash:
                raise ValueError("candidate payload hash conflicts with parent provenance registry")
            if prior.cell != binding.cell:
                raise ValueError("candidate cell conflicts with parent provenance registry")
        object.__setattr__(
            self,
            "parent_provenance_registry",
            tuple(
                binding
                for candidate_id, binding in sorted(registry.items(), key=lambda x: x[0].encode())
            ),
        )
        constraints = self.constraint_set.constraints
        one_state_ids = tuple(
            c.candidate_ids[0]
            for c in constraints
            if c.kind is ConstraintKind.ONE_STATE_PER_CANDIDATE
        )
        if len(one_state_ids) != len(ids) or set(one_state_ids) != set(ids):
            raise ValueError("constraint set must include one state constraint for every candidate")
        candidate_by_id = {item.candidate_id: item for item in ordered}
        review_constraints = {
            item.candidate_ids[0]: item
            for item in constraints
            if item.kind is ConstraintKind.REVIEW_OUT_ONLY
        }
        expected_review_out = {
            item.candidate_id
            for item in ordered
            if item.review_eligibility is not ReviewEligibility.APPROVED
        }
        if (
            sum(item.kind is ConstraintKind.REVIEW_OUT_ONLY for item in constraints)
            != len(expected_review_out)
            or set(review_constraints) != expected_review_out
            or any(
                review_constraints[candidate_id].reason
                != candidate_by_id[candidate_id].review_eligibility.value
                for candidate_id in expected_review_out
            )
        ):
            raise ValueError("review eligibility constraints do not match candidate statuses")
        qualification_constraints = {
            item.candidate_ids[0]: item
            for item in constraints
            if item.kind is ConstraintKind.QUALIFICATION_OUT_ONLY
        }
        expected_qualification_out = {
            item.candidate_id for item in ordered if item.qualification_excluded
        }
        if (
            sum(item.kind is ConstraintKind.QUALIFICATION_OUT_ONLY for item in constraints)
            != len(expected_qualification_out)
            or set(qualification_constraints) != expected_qualification_out
        ):
            raise ValueError("qualification constraints do not match candidate metadata")
        lock_constraints = {
            item.candidate_ids[0]: item
            for item in constraints
            if item.kind is ConstraintKind.SYNTHETIC_SPLIT_LOCK
        }
        expected_locks = {
            item.candidate_id
            for item in ordered
            if item.origin_class is CaseOrigin.DETERMINISTIC_SYNTHETIC
        }
        if (
            sum(item.kind is ConstraintKind.SYNTHETIC_SPLIT_LOCK for item in constraints)
            != len(expected_locks)
            or set(lock_constraints) != expected_locks
            or any(
                lock_constraints[candidate_id].locked_split
                != candidate_by_id[candidate_id].locked_split
                for candidate_id in expected_locks
            )
        ):
            raise ValueError("synthetic lock constraints do not match candidate metadata")
        mutation_ids = {
            item.candidate_id
            for item in ordered
            if item.origin_class is CaseOrigin.ADVERSARIAL_MUTATION
        }
        for kind in (
            ConstraintKind.MUTATION_PARENT_PROVENANCE,
            ConstraintKind.MUTATION_PARENT_CELL_INHERITANCE,
        ):
            proof_ids = tuple(
                constraint.candidate_ids[0] for constraint in constraints if constraint.kind is kind
            )
            if len(proof_ids) != len(mutation_ids) or set(proof_ids) != mutation_ids:
                raise ValueError(
                    f"constraint set must bind each mutation candidate to {kind.value}"
                )
        mutation_candidates = {
            candidate_id: candidate_by_id[candidate_id] for candidate_id in mutation_ids
        }
        parent_constraints = {
            item.candidate_ids[0]: item
            for item in constraints
            if item.kind is ConstraintKind.MUTATION_PARENT_PROVENANCE
        }
        cell_constraints = {
            item.candidate_ids[0]: item
            for item in constraints
            if item.kind is ConstraintKind.MUTATION_PARENT_CELL_INHERITANCE
        }
        if any(
            parent_constraints[candidate_id].related_id
            != mutation_candidates[candidate_id].mutation_parent_candidate_id
            or parent_constraints[candidate_id].related_payload_hash
            != mutation_candidates[candidate_id].mutation_parent_payload_hash
            or cell_constraints[candidate_id].related_id
            != mutation_candidates[candidate_id].mutation_parent_candidate_id
            or cell_constraints[candidate_id].reason
            != mutation_candidates[candidate_id].mutation_cell_exception_authority_ref
            for candidate_id in mutation_ids
        ):
            raise ValueError("mutation provenance constraints do not match candidate metadata")
        known_ids = set(ids)
        if any(
            candidate_id not in known_ids
            for constraint in constraints
            for candidate_id in constraint.candidate_ids
        ):
            raise ValueError("constraint references a candidate outside the pool")
        if any(
            candidate_id not in known_ids
            for cluster in self.constraint_set.allocation_clusters
            for candidate_id in cluster.candidate_ids
        ):
            raise ValueError("allocation cluster references a candidate outside the pool")

    @property
    def approved_pool_digest(self) -> str:
        eligible = tuple(
            (item.candidate_id, item.payload_hash)
            for item in self.candidates
            if item.review_eligibility is ReviewEligibility.APPROVED
            and not item.qualification_excluded
        )
        return canonical_hash(eligible)

    @property
    def constraint_inventory_digest(self) -> str:
        return canonical_hash(self.constraint_set)

    @property
    def problem_digest(self) -> str:
        return canonical_hash(
            {
                "schema": SELECTION_CONSTRAINT_SCHEMA,
                "authority_digest": self.authority_digest,
                "approved_pool_digest": self.approved_pool_digest,
                "candidates": self.candidates,
                "constraint_set": self.constraint_set,
                "parent_provenance_registry": self.parent_provenance_registry,
            }
        )


@register_serializable_type
@dataclass(frozen=True, slots=True)
class CandidateAssignment:
    candidate_id: str
    state: AssignmentState

    def __post_init__(self) -> None:
        if not self.candidate_id.strip():
            raise ValueError("assignment candidate_id must be non-empty")
        object.__setattr__(self, "state", AssignmentState(self.state))


@register_serializable_type
@dataclass(frozen=True, slots=True)
class FinalSelectionPlan:
    assignments: tuple[CandidateAssignment, ...]
    authority_digest: str
    problem_digest: str
    approved_pool_digest: str
    plan_digest: str = ""

    def __post_init__(self) -> None:
        for name in ("authority_digest", "problem_digest", "approved_pool_digest"):
            if _SHA256.fullmatch(getattr(self, name)) is None:
                raise ValueError(f"{name} must be a canonical SHA-256 digest")
        if not isinstance(self.assignments, tuple) or not self.assignments:
            raise ValueError("plan assignments must be a non-empty immutable tuple")
        ordered = tuple(sorted(self.assignments, key=lambda item: item.candidate_id.encode()))
        ids = tuple(item.candidate_id for item in ordered)
        if len(set(ids)) != len(ids):
            raise ValueError("plan assignments must contain each candidate once")
        object.__setattr__(self, "assignments", ordered)
        computed = canonical_hash(
            {
                "version": SELECTION_PLAN_VERSION,
                "authority_digest": self.authority_digest,
                "problem_digest": self.problem_digest,
                "approved_pool_digest": self.approved_pool_digest,
                "assignments": ordered,
            }
        )
        if self.plan_digest and self.plan_digest != computed:
            raise ValueError("plan_digest does not match the canonical assignments")
        object.__setattr__(self, "plan_digest", computed)


@register_serializable_type
@dataclass(frozen=True, slots=True)
class SelectionCoverageSummary:
    cells_by_split: tuple[tuple[SplitName, int], ...]
    row_tags_by_split: tuple[tuple[SplitName, int], ...]
    row_errors_by_split: tuple[tuple[SplitName, int], ...]
    c18_refusals_by_split: tuple[tuple[SplitName, int], ...]
    answerable_by_split: tuple[tuple[SplitName, int], ...]
    critical_classes_by_split: tuple[tuple[SplitName, int], ...]


@register_serializable_type
@dataclass(frozen=True, slots=True)
class SelectionIsolationSummary:
    relation_groups: int
    active_relation_groups: int
    cross_split_relation_groups: int
    allocation_clusters: int
    active_allocation_clusters: int


@register_serializable_type
@dataclass(frozen=True, slots=True)
class SelectionSummary:
    split_counts: tuple[tuple[SplitName, int], ...]
    out_count: int
    selected_origin_counts: tuple[tuple[CaseOrigin, int], ...]
    selected_mutation_lineages: int
    coverage: SelectionCoverageSummary
    isolation: SelectionIsolationSummary


@register_serializable_type
@dataclass(frozen=True, slots=True)
class SelectionValidationReceipt:
    validator_version: str
    status: ValidationStatus
    violated_constraint_ids: tuple[str, ...]
    plan_digest: str
    authority_digest: str
    validation_digest: str
    validation_wall_s: float
    summary: SelectionSummary


@register_serializable_type
@dataclass(frozen=True, slots=True)
class SelectionFeasibilityReceiptV1:
    receipt_version: str
    status: FeasibilityStatus
    solver_family: str
    solver_version: str
    solver_config: SelectionSolverConfig
    problem_digest: str
    candidate_pool_digest: str
    constraint_inventory_digest: str
    variable_count: int
    constraint_count: int
    wall_s: float
    deterministic_time_s: float
    plan_digest: str | None
    validation_status: ValidationStatus | None
    validation_digest: str | None
    summary: SelectionSummary | None
    diagnostics: tuple[SelectionDiagnostic, ...] = ()
    optimization_performed: bool = False
    canonicalization_performed: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", FeasibilityStatus(self.status))
        if self.validation_status is not None:
            object.__setattr__(self, "validation_status", ValidationStatus(self.validation_status))
        for name in (
            "problem_digest",
            "candidate_pool_digest",
            "constraint_inventory_digest",
        ):
            if _SHA256.fullmatch(getattr(self, name)) is None:
                raise ValueError(f"{name} must be a canonical SHA-256 digest")
        for value in (self.plan_digest, self.validation_digest):
            if value is not None and _SHA256.fullmatch(value) is None:
                raise ValueError("feasibility receipt contains a malformed digest")
        if self.optimization_performed or self.canonicalization_performed:
            raise ValueError(
                "feasibility-only receipts cannot report optimization or canonicalization"
            )
        if (
            self.variable_count < 0
            or self.constraint_count < 0
            or self.wall_s < 0
            or self.deterministic_time_s < 0
        ):
            raise ValueError("feasibility receipt counts and timings must be non-negative")
        if self.status is FeasibilityStatus.FEASIBLE and (
            self.plan_digest is None
            or self.validation_status is not ValidationStatus.VALID
            or self.validation_digest is None
            or self.summary is None
        ):
            raise ValueError("feasible receipt requires an independently validated witness")
        if self.status is not FeasibilityStatus.FEASIBLE and self.plan_digest is not None:
            raise ValueError("non-feasible receipt cannot accept a plan")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class SelectionSolverConfig:
    workers: int = 8
    random_seed: int = 369
    timeout_s: float = 30.0
    # 2 * (4**30 - 1) fits CP-SAT's signed 64-bit objective; larger chunks do not.
    canonical_chunk_size: int = 30
    cp_model_presolve: bool = True
    randomize_search: bool = False

    def __post_init__(self) -> None:
        if self.workers < 1 or self.timeout_s <= 0 or self.canonical_chunk_size < 1:
            raise ValueError("solver config must use positive worker, timeout, and chunk values")
        if self.canonical_chunk_size > 30:
            raise ValueError("canonical_chunk_size must fit the CP-SAT signed-integer objective")
        if not isinstance(self.cp_model_presolve, bool):
            raise ValueError("cp_model_presolve must be boolean")
        if not isinstance(self.randomize_search, bool):
            raise ValueError("randomize_search must be boolean")


# Qualified on production-shape pools with a validated production-shape warm start.
PSE_V1_PRODUCTION_SELECTION_SOLVER_PROFILE_V1 = SelectionSolverConfig(
    workers=8,
    random_seed=369,
    timeout_s=60.0,
    canonical_chunk_size=30,
    cp_model_presolve=False,
    randomize_search=False,
)

# PSE-V1-PRODUCTION-SELECTION-SOLVER@2.0.0 keeps base-4 chunk objectives
# below 2**53, where CP-SAT's double-valued objective and bound are exact.
PSE_V1_PRODUCTION_SELECTION_SOLVER_PROFILE_V2 = SelectionSolverConfig(
    workers=8,
    random_seed=369,
    timeout_s=120.0,
    canonical_chunk_size=15,
    cp_model_presolve=False,
    randomize_search=False,
)


@register_serializable_type
@dataclass(frozen=True, slots=True)
class SelectionDiagnostic:
    code: str
    message: str
    constraint_ids: tuple[str, ...] = ()


@register_serializable_type
@dataclass(frozen=True, slots=True)
class SelectionSolveReceipt:
    receipt_version: str
    solver_family: str
    solver_version: str
    solver_config: SelectionSolverConfig
    status: SolveStatus
    authority_digest: str
    problem_digest: str
    approved_pool_digest: str
    constraint_inventory_digest: str
    variable_count: int
    constraint_count: int
    warm_start_used: bool
    wall_s: float
    objective_optimization_wall_s: float
    canonicalization_wall_s: float
    deterministic_time_s: float
    peak_rss_mb: float
    balance_objective: int | None
    hash_preference_objective: int | None
    plan_digest: str | None
    validation_digest: str | None
    summary: SelectionSummary | None


@register_serializable_type
@dataclass(frozen=True, slots=True)
class FinalSelectionResult:
    plan: FinalSelectionPlan | None
    solve_receipt: SelectionSolveReceipt
    validation_receipt: SelectionValidationReceipt | None
    diagnostics: tuple[SelectionDiagnostic, ...]
