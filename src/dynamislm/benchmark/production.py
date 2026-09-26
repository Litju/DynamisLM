"""Production-candidate contracts, kept separate from qualification batches."""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, fields, replace
from pathlib import PurePosixPath

from dynamislm.benchmark.authoring import (
    _AUTHORITY_CLASS_BY_KIND,
    ACTIVE_SCORERS,
    AUTHORING_RECIPE_REGISTRY,
    authoring_recipe_registry_digest,
    parse_production_seed_namespace,
    question_classes_for_cell,
)
from dynamislm.benchmark.constants import (
    CAPABILITY_IDS,
    CRITICAL_ERROR_CLASSES,
    FAMILY_IDS,
    CaseOrigin,
    DifficultyLevel,
    ErrorClass,
    ExpectedAnswerKind,
    PractitionerQuestionClass,
    RefusalDecision,
    ScoringProfile,
    SplitName,
)
from dynamislm.benchmark.coverage import (
    COVERAGE_MATRIX,
    CoverageRow,
    coverage_manifest_digest,
)
from dynamislm.benchmark.pre_review import (
    CandidateReviewPacket,
    validate_candidate_review_packet,
    validate_candidate_set,
)
from dynamislm.benchmark.scoring_paths import reachable_error_classes
from dynamislm.benchmark.source_artifacts import SourceArtifactResolver
from dynamislm.serialization import canonical_hash, register_serializable_type

PRODUCTION_CANDIDATE_ID_PREFIX = "PSE-V1-CANDIDATE:"
PRODUCTION_BATCH_ID = "PSE-V1-PRODUCTION/RES-115-CASE-AUTHORING-001C"
PRODUCTION_AUTHORING_PROCESS_ID = "agent-process:codex:RES-115-CASE-AUTHORING-001C"
PRODUCTION_AUTHORING_PLAN_VERSION = "pse-production-authoring-plan@1.0.0"
PRODUCTION_BATCH_MANIFEST_VERSION = "pse-production-batch@1.0.0"
FINAL_TARGET_CASES = 434
PROSPECTIVE_SPLIT_COUNTS = (
    (SplitName.PUBLIC_DEVELOPMENT, 260),
    (SplitName.FROZEN_VALIDATION, 87),
    (SplitName.HIDDEN_FINAL, 87),
)
_SHA256 = re.compile(r"sha256:[0-9a-f]{64}\Z")
_CANDIDATE_ID = re.compile(r"PSE-V1-CANDIDATE:[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")


def _strings(values: tuple[str, ...], name: str) -> None:
    if not isinstance(values, tuple) or any(
        not isinstance(item, str) or not item for item in values
    ):
        raise ValueError(f"{name} must be an immutable tuple of non-empty strings")
    if values != tuple(sorted(set(values), key=lambda item: item.encode("utf-8"))):
        raise ValueError(f"{name} must use unique canonical UTF-8 ordering")


def _optional_text(value: str | None, name: str) -> None:
    if value is not None and (not isinstance(value, str) or not value.strip()):
        raise ValueError(f"{name} must be non-empty when provided")


def _candidate_id(value: str) -> None:
    if _CANDIDATE_ID.fullmatch(value) is None:
        raise ValueError("production candidate ID must use PSE-V1-CANDIDATE:<stable-id>")


def _authority_classes(authority_kinds: tuple[str, ...]) -> frozenset[str]:
    return frozenset(
        authority_class
        for kind in authority_kinds
        if (authority_class := _AUTHORITY_CLASS_BY_KIND.get(kind)) is not None
    )


@register_serializable_type
@dataclass(frozen=True, slots=True)
class ProductionAuthoringPlanItemV1:
    """Private metadata commitment for one planned production candidate."""

    candidate_id: str
    recipe_id: str
    recipe_version: str
    capability_id: str
    benchmark_family: str
    practitioner_question_class: PractitionerQuestionClass
    origin_class: CaseOrigin
    scoring_profile: ScoringProfile
    authority_class: str
    authority_kinds: tuple[str, ...]
    reachable_error_classes: tuple[ErrorClass, ...]
    adversarial_tags: tuple[str, ...]
    source_family_id: str
    source_document_ids: tuple[str, ...]
    source_artifact_ids: tuple[str, ...]
    construct_test_identity_ids: tuple[str, ...]
    provider_export_ids: tuple[str, ...]
    protocol_template_ids: tuple[str, ...]
    expert_author_batch_id: str | None
    author_id: str
    generator_id: str | None
    generator_version: str | None
    generator_family: str | None
    seed_namespace: str | None
    seed_block: str | None
    mutation_lineage_id: str | None
    parent_candidate_id: str | None
    isolation_cluster_id: str
    allocation_stratum: str
    refusal_decision: RefusalDecision
    expected_answer_kind: ExpectedAnswerKind
    safe_partial_support: bool
    difficulty: DifficultyLevel

    def __post_init__(self) -> None:
        _candidate_id(self.candidate_id)
        object.__setattr__(
            self,
            "practitioner_question_class",
            PractitionerQuestionClass(self.practitioner_question_class),
        )
        object.__setattr__(self, "origin_class", CaseOrigin(self.origin_class))
        object.__setattr__(self, "scoring_profile", ScoringProfile(self.scoring_profile))
        object.__setattr__(self, "refusal_decision", RefusalDecision(self.refusal_decision))
        object.__setattr__(
            self, "expected_answer_kind", ExpectedAnswerKind(self.expected_answer_kind)
        )
        object.__setattr__(self, "difficulty", DifficultyLevel(self.difficulty))
        for name in (
            "recipe_id",
            "recipe_version",
            "source_family_id",
            "author_id",
            "isolation_cluster_id",
            "allocation_stratum",
            "authority_class",
        ):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} must be non-empty")
        if self.capability_id not in CAPABILITY_IDS or self.benchmark_family not in FAMILY_IDS:
            raise ValueError("production plan item has an unknown capability/family cell")
        if self.practitioner_question_class not in question_classes_for_cell(
            self.capability_id, self.benchmark_family
        ):
            raise ValueError("production plan item question class is invalid for its cell")
        if self.scoring_profile not in ACTIVE_SCORERS:
            raise ValueError("production plan item requires an active V1 scorer")
        if not self.authority_kinds or self.authority_class not in _authority_classes(
            self.authority_kinds
        ):
            raise ValueError("production plan item authority class is not bound by its kinds")
        for name in (
            "authority_kinds",
            "adversarial_tags",
            "source_document_ids",
            "source_artifact_ids",
            "construct_test_identity_ids",
            "provider_export_ids",
            "protocol_template_ids",
        ):
            _strings(getattr(self, name), name)
        if not self.reachable_error_classes or any(
            not isinstance(item, ErrorClass) for item in self.reachable_error_classes
        ):
            raise ValueError("production plan item requires reachable frozen error classes")
        if self.reachable_error_classes != tuple(
            sorted(set(self.reachable_error_classes), key=lambda item: item.value.encode("utf-8"))
        ):
            raise ValueError("reachable error classes must be unique and canonically ordered")
        for name in (
            "expert_author_batch_id",
            "generator_id",
            "generator_version",
            "generator_family",
            "seed_namespace",
            "seed_block",
            "mutation_lineage_id",
            "parent_candidate_id",
        ):
            _optional_text(getattr(self, name), name)
        if (
            self.origin_class
            in {
                CaseOrigin.EXPERT_AUTHORED_SEMANTIC,
                CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION,
            }
            and self.author_id != PRODUCTION_AUTHORING_PROCESS_ID
        ):
            raise ValueError(
                "semantic/source proposed gold must identify the 001C authoring process"
            )
        if self.origin_class is CaseOrigin.EXPERT_AUTHORED_SEMANTIC:
            if self.expert_author_batch_id is None:
                raise ValueError("expert semantic candidate requires a bounded author batch")
            if self.expert_author_batch_id == PRODUCTION_AUTHORING_PROCESS_ID:
                raise ValueError("global 001C process identity cannot be an expert author batch")
            if not self.protocol_template_ids:
                raise ValueError("template-driven semantic candidate requires protocol/template ID")
        synthetic_fields = (
            self.generator_id,
            self.generator_version,
            self.generator_family,
            self.seed_namespace,
            self.seed_block,
        )
        if self.origin_class is CaseOrigin.DETERMINISTIC_SYNTHETIC:
            if any(value is None for value in synthetic_fields):
                raise ValueError(
                    "synthetic production candidate requires exact generator/seed metadata"
                )
            parsed = parse_production_seed_namespace(self.seed_namespace or "")
            if (
                parsed.generator_id,
                parsed.generator_version,
                parsed.seed_block,
            ) != (self.generator_id, self.generator_version, self.seed_block):
                raise ValueError("synthetic seed namespace conflicts with generator metadata")
        elif any(value is not None for value in synthetic_fields):
            raise ValueError(
                "non-synthetic production candidate cannot carry generator seed metadata"
            )
        if self.origin_class is CaseOrigin.ADVERSARIAL_MUTATION:
            if self.mutation_lineage_id is None or self.parent_candidate_id is None:
                raise ValueError("mutation candidate requires parent and lineage identities")
        elif self.mutation_lineage_id is not None or self.parent_candidate_id is not None:
            raise ValueError("non-mutation candidate cannot carry mutation lineage")
        if self.expected_answer_kind is ExpectedAnswerKind.REFUSAL and (
            self.refusal_decision is not RefusalDecision.REQUIRED
        ):
            raise ValueError("refusal answer kind requires a refusal-required commitment")
        if not isinstance(self.safe_partial_support, bool):
            raise ValueError("safe_partial_support must be boolean")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class ProductionAuthoringPlanV1:
    batch_id: str
    plan_version: str
    authoring_process_id: str
    target_case_count: int
    coverage_matrix_digest: str
    recipe_registry_digest: str
    qualification_exclusion_digest: str
    items: tuple[ProductionAuthoringPlanItemV1, ...]
    plan_digest: str

    def __post_init__(self) -> None:
        if self.batch_id != PRODUCTION_BATCH_ID:
            raise ValueError("production authoring plan must use the 001C batch identity")
        if self.plan_version != PRODUCTION_AUTHORING_PLAN_VERSION:
            raise ValueError("unsupported production authoring plan version")
        if self.authoring_process_id != PRODUCTION_AUTHORING_PROCESS_ID:
            raise ValueError("production authoring plan must bind the distinct 001C process")
        if self.target_case_count != FINAL_TARGET_CASES or len(self.items) != FINAL_TARGET_CASES:
            raise ValueError("production authoring plan must contain exactly 434 candidates")
        if any(not isinstance(item, ProductionAuthoringPlanItemV1) for item in self.items):
            raise ValueError("production authoring plan requires typed metadata items")
        for name in (
            "coverage_matrix_digest",
            "recipe_registry_digest",
            "qualification_exclusion_digest",
            "plan_digest",
        ):
            if _SHA256.fullmatch(getattr(self, name)) is None:
                raise ValueError(f"{name} must be a SHA-256 digest")
        ids = tuple(item.candidate_id for item in self.items)
        if ids != tuple(sorted(set(ids), key=lambda item: item.encode("utf-8"))):
            raise ValueError("production plan items must use unique canonical candidate-ID order")


def production_authoring_plan_digest(plan: ProductionAuthoringPlanV1) -> str:
    return canonical_hash(
        {item.name: getattr(plan, item.name) for item in fields(plan) if item.name != "plan_digest"}
    )


def bind_production_authoring_plan(plan: ProductionAuthoringPlanV1) -> ProductionAuthoringPlanV1:
    return replace(plan, plan_digest=production_authoring_plan_digest(plan))


def validate_production_authoring_plan(plan: ProductionAuthoringPlanV1) -> None:
    if plan.coverage_matrix_digest != coverage_manifest_digest():
        raise ValueError("production plan is stale against the frozen coverage matrix")
    if plan.recipe_registry_digest != authoring_recipe_registry_digest():
        raise ValueError("production plan is stale against the authoring recipe registry")
    if plan.plan_digest != production_authoring_plan_digest(plan):
        raise ValueError("production authoring plan digest mismatch")
    recipe_by_id = {item.recipe_id: item for item in AUTHORING_RECIPE_REGISTRY}
    for item in plan.items:
        recipe = recipe_by_id.get(item.recipe_id)
        if recipe is None or recipe.recipe_version != item.recipe_version:
            raise ValueError("production plan references an unknown authoring recipe")
        if (recipe.capability_id, recipe.benchmark_family) != (
            item.capability_id,
            item.benchmark_family,
        ):
            raise ValueError("production plan recipe identity differs from its candidate cell")
        if (
            item.origin_class not in recipe.origins
            or item.scoring_profile not in recipe.scorers
            or item.authority_class not in _authority_classes(recipe.authority_kinds)
            or not set(item.authority_kinds).intersection(recipe.authority_kinds)
        ):
            raise ValueError("production plan exceeds its registered cell authority")
        row = next(entry for entry in COVERAGE_MATRIX if entry.capability_id == item.capability_id)
        if (
            item.origin_class not in row.case_origins
            or not set(item.reachable_error_classes).issubset(row.error_classes)
            or not set(item.adversarial_tags).issubset(row.adversarial_tags)
        ):
            raise ValueError("production plan metadata exceeds the frozen coverage row")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class ProductionCandidateCommitmentV1:
    item: ProductionAuthoringPlanItemV1
    candidate_payload_hash: str

    def __post_init__(self) -> None:
        if not isinstance(self.item, ProductionAuthoringPlanItemV1):
            raise ValueError("production commitment requires typed plan metadata")
        if _SHA256.fullmatch(self.candidate_payload_hash) is None:
            raise ValueError("candidate payload hash must be a SHA-256 digest")

    @property
    def candidate_id(self) -> str:
        return self.item.candidate_id


def build_production_candidate_commitment(
    packet: CandidateReviewPacket,
    *,
    source_resolver: SourceArtifactResolver | None = None,
) -> ProductionCandidateCommitmentV1:
    """Derive a payload-free commitment from one validated pending packet."""

    validate_production_candidate_packet(packet, source_resolver=source_resolver)
    item = production_plan_item_from_packet(packet)
    return ProductionCandidateCommitmentV1(item, packet.candidate_payload_hash)


def production_plan_item_from_packet(
    packet: CandidateReviewPacket,
) -> ProductionAuthoringPlanItemV1:
    provenance = packet.proposed_provenance
    contamination = packet.contamination
    authority_kinds = tuple(
        sorted(
            {item.authority_kind for item in packet.authority},
            key=lambda item: item.encode("utf-8"),
        )
    )
    authority_class_candidates = _authority_classes(authority_kinds)
    if not authority_class_candidates:
        raise ValueError("production candidate has no registered authority class")
    authority_class = sorted(authority_class_candidates, key=lambda item: item.encode("utf-8"))[0]
    recipes = {
        (item.capability_id, item.benchmark_family): item for item in AUTHORING_RECIPE_REGISTRY
    }
    recipe = recipes.get((packet.capability_id, packet.benchmark_family))
    if recipe is None:
        raise ValueError("production candidate cell has no frozen authoring recipe")
    source_document_ids = tuple(
        sorted(
            {
                item.document_identity.document_id
                for item in packet.source_evidence_refs
                if item.document_identity is not None
            },
            key=lambda item: item.encode("utf-8"),
        )
    )
    return ProductionAuthoringPlanItemV1(
        candidate_id=packet.candidate_id,
        recipe_id=recipe.recipe_id,
        recipe_version=recipe.recipe_version,
        capability_id=packet.capability_id,
        benchmark_family=packet.benchmark_family,
        practitioner_question_class=packet.practitioner_question_class,
        origin_class=provenance.origin_class,
        scoring_profile=packet.scoring_contract.profile_id,
        authority_class=authority_class,
        authority_kinds=authority_kinds,
        reachable_error_classes=tuple(
            sorted(
                reachable_error_classes(
                    packet.scoring_contract,
                    refusal_decision=packet.refusal_contract.decision,
                    prohibited_claims=packet.proposed_expected_answer.prohibited_claims,
                ),
                key=lambda item: item.value.encode("utf-8"),
            )
        ),
        adversarial_tags=tuple(
            sorted(set(packet.adversarial_tags), key=lambda item: item.encode("utf-8"))
        ),
        source_family_id=packet.isolation.source_family_id,
        source_document_ids=source_document_ids,
        source_artifact_ids=tuple(
            sorted(set(contamination.source_artifact_ids), key=lambda item: item.encode("utf-8"))
        ),
        construct_test_identity_ids=tuple(
            sorted(
                set(contamination.construct_test_identity_ids),
                key=lambda item: item.encode("utf-8"),
            )
        ),
        provider_export_ids=(contamination.provider_export_id,)
        if contamination.provider_export_id
        else (),
        protocol_template_ids=(contamination.protocol_template_id,)
        if contamination.protocol_template_id
        else (),
        expert_author_batch_id=contamination.expert_author_batch_id,
        author_id=provenance.author_id,
        generator_id=provenance.generator_id,
        generator_version=provenance.generator_version,
        generator_family=provenance.generator_family,
        seed_namespace=provenance.seed_namespace,
        seed_block=provenance.seed_block,
        mutation_lineage_id=provenance.mutation_lineage_id,
        parent_candidate_id=(
            packet.parent_candidate_binding.parent_candidate_id
            if packet.parent_candidate_binding is not None
            else None
        ),
        isolation_cluster_id=packet.isolation.isolation_cluster_id,
        allocation_stratum=packet.isolation.allocation_stratum,
        refusal_decision=packet.refusal_contract.decision,
        expected_answer_kind=packet.proposed_expected_answer.kind,
        safe_partial_support=bool(
            packet.refusal_contract.what_can_still_be_safely_described
            and (
                packet.refusal_contract.safe_lower_claim_level is not None
                or packet.claim_contract.safe_lower_claim_levels
                or packet.proposed_expected_answer.safe_lower_level_descriptions
            )
        ),
        difficulty=packet.difficulty.level,
    )


def validate_production_candidate_packet(
    packet: CandidateReviewPacket,
    *,
    source_resolver: SourceArtifactResolver | None = None,
) -> None:
    """Keep production packets pending and bind synthetic seeds before review."""

    if not isinstance(packet, CandidateReviewPacket):
        raise TypeError("packet must be CandidateReviewPacket")
    _candidate_id(packet.candidate_id)
    if (
        packet.proposed_provenance.origin_class
        in {
            CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION,
            CaseOrigin.EXPERT_AUTHORED_SEMANTIC,
        }
        and packet.proposed_provenance.author_id != PRODUCTION_AUTHORING_PROCESS_ID
    ):
        raise ValueError("production semantic/source material must remain agent-authored")
    has_source = bool(packet.source_evidence_refs or packet.input.evidence_excerpts)
    if has_source and source_resolver is None:
        raise ValueError("production source candidate requires the sealed Phase-A source resolver")
    validate_candidate_review_packet(packet, source_resolver=source_resolver)
    if packet.proposed_provenance.origin_class is CaseOrigin.DETERMINISTIC_SYNTHETIC:
        provenance = packet.proposed_provenance
        parsed = parse_production_seed_namespace(provenance.seed_namespace or "")
        if (parsed.generator_id, parsed.generator_version, parsed.seed_block) != (
            provenance.generator_id,
            provenance.generator_version,
            provenance.seed_block,
        ):
            raise ValueError("production synthetic namespace differs from generator metadata")
        if parsed.split_name not in {split for split, _count in PROSPECTIVE_SPLIT_COUNTS}:
            raise ValueError("synthetic seed split is not in the frozen target")
    if has_source:
        from dynamislm.benchmark.res115_authoring import validate_res115_source_applicability

        validate_res115_source_applicability(packet)


@dataclass(frozen=True, slots=True)
class ProductionIsolationValidationV1:
    candidate_count: int
    atomic_cluster_count: int
    cluster_size_distribution: tuple[tuple[int, int], ...]
    isolation_identity_count: int
    status: str = "PASS"


def _isolation_values(item: ProductionAuthoringPlanItemV1) -> tuple[tuple[str, str], ...]:
    values: set[tuple[str, str]] = {("source-family", item.source_family_id)}
    for kind, entries in (
        ("source-document", item.source_document_ids),
        ("source-artifact", item.source_artifact_ids),
        ("construct-test", item.construct_test_identity_ids),
        ("provider-export", item.provider_export_ids),
        ("protocol-template", item.protocol_template_ids),
    ):
        values.update((kind, entry) for entry in entries)
    for kind, value in (
        ("expert-author-batch", item.expert_author_batch_id),
        ("generator-family", item.generator_family),
        ("mutation-lineage", item.mutation_lineage_id),
    ):
        if value is not None:
            values.add((kind, value))
    if item.seed_namespace is not None:
        values.add(("seed-namespace", item.seed_namespace))
    if item.seed_block is not None:
        values.add(("seed-block", item.seed_block))
    if item.parent_candidate_id is not None:
        values.add(("mutation-parent-candidate", item.parent_candidate_id))
    return tuple(sorted(values, key=lambda pair: (pair[0].encode(), pair[1].encode())))


def validate_production_isolation(
    commitments: tuple[ProductionCandidateCommitmentV1, ...],
) -> ProductionIsolationValidationV1:
    """Require each declared identity to resolve to one atomic cluster."""

    if not commitments:
        raise ValueError("production isolation requires candidate commitments")
    items = tuple(item.item for item in commitments)
    ids = tuple(item.candidate_id for item in items)
    hashes = tuple(item.candidate_payload_hash for item in commitments)
    if len(set(ids)) != len(ids) or len(set(hashes)) != len(hashes):
        raise ValueError("production candidate IDs and payload hashes must be unique")
    candidate_clusters = {item.candidate_id: item.isolation_cluster_id for item in items}
    identity_cluster: dict[tuple[str, str], str] = {}
    cluster_members: dict[str, list[ProductionAuthoringPlanItemV1]] = defaultdict(list)
    template_batches: dict[str, set[str]] = defaultdict(set)
    source_document_family: dict[str, str] = {}
    generator_locks: dict[str, set[SplitName]] = defaultdict(set)
    for item in items:
        cluster_members[item.isolation_cluster_id].append(item)
        for identity in _isolation_values(item):
            prior_cluster = identity_cluster.setdefault(identity, item.isolation_cluster_id)
            if prior_cluster != item.isolation_cluster_id:
                raise ValueError(f"production {identity[0]} fragmented across isolation clusters")
        for document_id in item.source_document_ids:
            prior_family = source_document_family.setdefault(document_id, item.source_family_id)
            if prior_family != item.source_family_id:
                raise ValueError(
                    "one source document is assigned to multiple Phase-A source families"
                )
        if item.origin_class is CaseOrigin.EXPERT_AUTHORED_SEMANTIC:
            for template_id in item.protocol_template_ids:
                template_batches[template_id].add(item.expert_author_batch_id or "")
        if item.origin_class is CaseOrigin.DETERMINISTIC_SYNTHETIC:
            parsed = parse_production_seed_namespace(item.seed_namespace or "")
            generator_locks[item.generator_family or ""].add(parsed.split_name)
    if any(len(batches) > 1 for batches in template_batches.values()):
        raise ValueError("one shared protocol/template was fragmented across expert batches")
    if any(len(splits) > 1 for splits in generator_locks.values()):
        raise ValueError("generator family conflicts with split-qualified seed namespaces")
    for cluster_id, members in cluster_members.items():
        if len(members) > 260:
            raise ValueError(f"atomic cluster {cluster_id} exceeds the public target capacity")
    for item in items:
        if (
            item.parent_candidate_id is not None
            and candidate_clusters.get(item.parent_candidate_id) != item.isolation_cluster_id
        ):
            raise ValueError("mutation lineage is fragmented from its parent candidate cluster")
    size_counts: dict[int, int] = defaultdict(int)
    for members in cluster_members.values():
        size_counts[len(members)] += 1
    distribution = tuple(sorted(size_counts.items()))
    return ProductionIsolationValidationV1(
        candidate_count=len(items),
        atomic_cluster_count=len(cluster_members),
        cluster_size_distribution=distribution,
        isolation_identity_count=len(identity_cluster),
    )


PRODUCTION_FEASIBILITY_ALGORITHM = "PSE-V1-PRE-REVIEW-FEASIBILITY@1.0.0"


class ProductionFeasibilityBlocked(ValueError):  # noqa: N818 - status is part of the gate contract
    """Raised when the exact pre-review production commitments have no witness."""


@dataclass(frozen=True, slots=True)
class _FeasibilityCluster:
    isolation_cluster_id: str
    items: tuple[ProductionAuthoringPlanItemV1, ...]
    cluster_key: str
    preferred_rank: int
    locked_rank: int | None

    @property
    def size(self) -> int:
        return len(self.items)


@register_serializable_type
@dataclass(frozen=True, slots=True)
class ProductionFeasibilityReceiptV1:
    status: str
    algorithm_id: str
    candidate_count: int
    target_counts: tuple[tuple[SplitName, int], ...]
    atomic_cluster_count: int
    cluster_size_distribution: tuple[tuple[int, int], ...]
    hard_cell_count_by_split: tuple[tuple[SplitName, int], ...]
    adversarial_tag_count_by_split: tuple[tuple[SplitName, int], ...]
    reachable_error_count_by_split: tuple[tuple[SplitName, int], ...]
    protected_critical_error_count_by_split: tuple[tuple[SplitName, int], ...]
    answerable_case_count_by_split: tuple[tuple[SplitName, int], ...]
    c18_refusal_cell_count_by_split: tuple[tuple[SplitName, int], ...]
    commitments_digest: str
    feasibility_witness_digest: str
    receipt_digest: str

    def __post_init__(self) -> None:
        if self.status != "PASS" or self.algorithm_id != PRODUCTION_FEASIBILITY_ALGORITHM:
            raise ValueError("feasibility receipt must be a passing frozen algorithm result")
        if self.candidate_count != FINAL_TARGET_CASES:
            raise ValueError("feasibility receipt must bind exactly 434 commitments")
        if self.target_counts != PROSPECTIVE_SPLIT_COUNTS:
            raise ValueError("feasibility receipt must bind exact 260/87/87 targets")
        if self.atomic_cluster_count < 1:
            raise ValueError("feasibility receipt requires atomic clusters")
        if (
            sum(count for _size, count in self.cluster_size_distribution)
            != self.atomic_cluster_count
        ):
            raise ValueError("feasibility cluster distribution does not sum to its count")
        for name, values, expected in (
            ("cell", self.hard_cell_count_by_split, 87),
            (
                "tag",
                self.adversarial_tag_count_by_split,
                sum(len(row.adversarial_tags) for row in COVERAGE_MATRIX),
            ),
            (
                "error",
                self.reachable_error_count_by_split,
                sum(len(row.error_classes) for row in COVERAGE_MATRIX),
            ),
            (
                "critical error",
                self.protected_critical_error_count_by_split,
                len(CRITICAL_ERROR_CLASSES),
            ),
            ("answerable", self.answerable_case_count_by_split, None),
            ("C18 refusal", self.c18_refusal_cell_count_by_split, 14),
        ):
            split_names = tuple(split for split, _count in values)
            required_splits = (
                (SplitName.FROZEN_VALIDATION, SplitName.HIDDEN_FINAL)
                if name == "critical error"
                else tuple(split for split, _count in PROSPECTIVE_SPLIT_COUNTS)
            )
            if split_names != required_splits:
                raise ValueError(f"feasibility {name} counts have incorrect split coverage")
            if (
                name in {"cell", "tag", "error", "C18 refusal"}
                and expected is not None
                and any(count != expected for _split, count in values)
            ):
                raise ValueError(f"feasibility {name} counts differ from the frozen obligation")
            if (
                name == "critical error"
                and expected is not None
                and any(count < expected for _split, count in values)
            ):
                raise ValueError("protected split critical-error eligibility is incomplete")
            if name == "answerable" and any(count < 1 for _split, count in values):
                raise ValueError("each split requires at least one answerable candidate")
        for name in (
            "commitments_digest",
            "feasibility_witness_digest",
            "receipt_digest",
        ):
            if _SHA256.fullmatch(getattr(self, name)) is None:
                raise ValueError(f"{name} must be a SHA-256 digest")


def production_feasibility_receipt_digest(receipt: ProductionFeasibilityReceiptV1) -> str:
    return canonical_hash(
        {
            item.name: getattr(receipt, item.name)
            for item in fields(receipt)
            if item.name != "receipt_digest"
        }
    )


def bind_production_feasibility_receipt(
    receipt: ProductionFeasibilityReceiptV1,
) -> ProductionFeasibilityReceiptV1:
    return replace(receipt, receipt_digest=production_feasibility_receipt_digest(receipt))


def validate_production_feasibility_receipt(receipt: ProductionFeasibilityReceiptV1) -> None:
    if receipt.receipt_digest != production_feasibility_receipt_digest(receipt):
        raise ValueError("production feasibility receipt digest mismatch")


def _row_by_capability(capability_id: str) -> CoverageRow:
    return next(row for row in COVERAGE_MATRIX if row.capability_id == capability_id)


def _validate_feasibility_item(item: ProductionAuthoringPlanItemV1) -> None:
    row = _row_by_capability(item.capability_id)
    if item.benchmark_family not in row.benchmark_families:
        raise ProductionFeasibilityBlocked(
            "commitment is outside its frozen capability/family cell"
        )
    if item.practitioner_question_class not in question_classes_for_cell(
        item.capability_id, item.benchmark_family
    ):
        raise ProductionFeasibilityBlocked("commitment has an unauthorized question class")
    if item.origin_class not in row.case_origins:
        raise ProductionFeasibilityBlocked("commitment origin is not permitted for its cell")
    if item.scoring_profile not in row.scorer_profiles:
        raise ProductionFeasibilityBlocked("commitment scorer is not permitted for its cell")
    if not set(item.authority_kinds).intersection(
        row.answer_authorities
    ) or item.authority_class not in _authority_classes(row.answer_authorities):
        raise ProductionFeasibilityBlocked("commitment authority is not permitted for its cell")
    if not set(item.adversarial_tags).issubset(row.adversarial_tags) or not item.adversarial_tags:
        raise ProductionFeasibilityBlocked("commitment adversarial tags exceed or omit its row")
    if (
        not set(item.reachable_error_classes).issubset(row.error_classes)
        or not item.reachable_error_classes
    ):
        raise ProductionFeasibilityBlocked("commitment reachable errors exceed or omit its row")
    if item.refusal_decision is RefusalDecision.REQUIRED and (
        item.expected_answer_kind is not ExpectedAnswerKind.REFUSAL or not item.safe_partial_support
    ):
        raise ProductionFeasibilityBlocked(
            "required-refusal commitment must preserve safe partial guidance"
        )


def _feasibility_clusters(
    commitments: tuple[ProductionCandidateCommitmentV1, ...],
) -> tuple[_FeasibilityCluster, ...]:
    grouped: dict[str, list[ProductionAuthoringPlanItemV1]] = defaultdict(list)
    for commitment in commitments:
        grouped[commitment.item.isolation_cluster_id].append(commitment.item)
    clusters: list[_FeasibilityCluster] = []
    for cluster_id, raw_items in grouped.items():
        items = tuple(sorted(raw_items, key=lambda item: item.candidate_id.encode("utf-8")))
        locked_splits = {
            parse_production_seed_namespace(item.seed_namespace).split_name
            for item in items
            if item.origin_class is CaseOrigin.DETERMINISTIC_SYNTHETIC
            and item.seed_namespace is not None
        }
        if len(locked_splits) > 1:
            raise ProductionFeasibilityBlocked(
                "one atomic cluster has incompatible synthetic seed split constraints"
            )
        cluster_key = canonical_hash(
            {
                "isolation_cluster_id": cluster_id,
                "candidate_ids": tuple(item.candidate_id for item in items),
            }
        ).removeprefix("sha256:")
        clusters.append(
            _FeasibilityCluster(
                isolation_cluster_id=cluster_id,
                items=items,
                cluster_key=cluster_key,
                preferred_rank=int(cluster_key, 16) % 3,
                locked_rank=(
                    tuple(split for split, _count in PROSPECTIVE_SPLIT_COUNTS).index(
                        next(iter(locked_splits))
                    )
                    if locked_splits
                    else None
                ),
            )
        )
    return tuple(
        sorted(
            clusters,
            key=lambda cluster: (
                cluster.cluster_key.encode("utf-8"),
                cluster.isolation_cluster_id.encode("utf-8"),
            ),
        )
    )


def _feasibility_row_eligible(item: ProductionAuthoringPlanItemV1, row: CoverageRow) -> bool:
    return (
        item.capability_id == row.capability_id
        and item.origin_class in row.case_origins
        and item.scoring_profile in row.scorer_profiles
        and item.authority_class in _authority_classes(row.answer_authorities)
        and bool(set(item.authority_kinds).intersection(row.answer_authorities))
    )


def _cluster_has_cell_obligation(
    cluster: _FeasibilityCluster,
    row: CoverageRow,
    family: str,
) -> bool:
    return any(
        item.benchmark_family == family
        and _feasibility_row_eligible(item, row)
        and bool(set(item.adversarial_tags).intersection(row.adversarial_tags))
        and bool(set(item.reachable_error_classes).intersection(row.error_classes))
        for item in cluster.items
    )


def _cluster_has_c18_refusal(
    cluster: _FeasibilityCluster,
    family: str,
) -> bool:
    row = _row_by_capability("C18")
    return any(
        item.capability_id == "C18"
        and item.benchmark_family == family
        and _feasibility_row_eligible(item, row)
        and item.refusal_decision is RefusalDecision.REQUIRED
        and item.expected_answer_kind is ExpectedAnswerKind.REFUSAL
        and item.safe_partial_support
        for item in cluster.items
    )


def _anchor_feasibility_coverage(
    clusters: tuple[_FeasibilityCluster, ...],
) -> dict[int, int]:
    targets = tuple(count for _split, count in PROSPECTIVE_SPLIT_COUNTS)
    assignments: dict[int, int] = {}
    counts = [0, 0, 0]
    requirements = [
        (rank, row, family)
        for rank in range(3)
        for row in COVERAGE_MATRIX
        for family in row.benchmark_families
    ]
    requirements.sort(
        key=lambda requirement: (
            sum(
                _cluster_has_cell_obligation(cluster, requirement[1], requirement[2])
                and (cluster.locked_rank is None or cluster.locked_rank == requirement[0])
                for cluster in clusters
            ),
            requirement[0],
            requirement[1].capability_id,
            requirement[2],
        )
    )

    for rank, row, family in requirements:
        if any(
            assigned_rank == rank and _cluster_has_cell_obligation(clusters[index], row, family)
            for index, assigned_rank in assignments.items()
        ):
            continue
        options = [
            index
            for index, cluster in enumerate(clusters)
            if index not in assignments
            and (cluster.locked_rank is None or cluster.locked_rank == rank)
            and counts[rank] + cluster.size <= targets[rank]
            and _cluster_has_cell_obligation(cluster, row, family)
        ]
        if not options:
            raise ProductionFeasibilityBlocked(
                f"no eligible atomic cluster for {row.capability_id}x{family} in "
                f"{PROSPECTIVE_SPLIT_COUNTS[rank][0].value}"
            )
        selected = min(
            options,
            key=lambda index: (
                -sum(
                    _cluster_has_cell_obligation(clusters[index], other_row, other_family)
                    for other_row in COVERAGE_MATRIX
                    for other_family in other_row.benchmark_families
                ),
                clusters[index].size,
                0 if clusters[index].preferred_rank == rank else 1,
                clusters[index].cluster_key.encode("utf-8"),
            ),
        )
        assignments[selected] = rank
        counts[rank] += clusters[selected].size

    # C18 declares explicit refusal behavior for every frozen family in D/V/H.
    for rank, (split, _target) in enumerate(PROSPECTIVE_SPLIT_COUNTS):
        for family in _row_by_capability("C18").benchmark_families:
            if any(
                assigned_rank == rank and _cluster_has_c18_refusal(clusters[index], family)
                for index, assigned_rank in assignments.items()
            ):
                continue
            options = [
                index
                for index, cluster in enumerate(clusters)
                if index not in assignments
                and (cluster.locked_rank is None or cluster.locked_rank == rank)
                and counts[rank] + cluster.size <= targets[rank]
                and _cluster_has_c18_refusal(cluster, family)
            ]
            if not options:
                raise ProductionFeasibilityBlocked(
                    f"no eligible atomic refusal candidate for C18x{family} in {split.value}"
                )
            selected = min(
                options,
                key=lambda index: (
                    clusters[index].size,
                    0 if clusters[index].preferred_rank == rank else 1,
                    clusters[index].cluster_key.encode("utf-8"),
                ),
            )
            assignments[selected] = rank
            counts[rank] += clusters[selected].size

    for rank, (split, _target) in enumerate(PROSPECTIVE_SPLIT_COUNTS):
        if any(
            chosen_rank == rank
            and any(
                item.refusal_decision is not RefusalDecision.REQUIRED
                and item.expected_answer_kind is not ExpectedAnswerKind.REFUSAL
                for item in clusters[index].items
            )
            for index, chosen_rank in assignments.items()
        ):
            continue
        options = [
            index
            for index, cluster in enumerate(clusters)
            if index not in assignments
            and (cluster.locked_rank is None or cluster.locked_rank == rank)
            and counts[rank] + cluster.size <= targets[rank]
            and any(
                item.refusal_decision is not RefusalDecision.REQUIRED
                and item.expected_answer_kind is not ExpectedAnswerKind.REFUSAL
                for item in cluster.items
            )
        ]
        if not options:
            raise ProductionFeasibilityBlocked(
                f"no answerable candidate can be assigned to {split.value}"
            )
        selected = min(
            options,
            key=lambda index: (
                clusters[index].size,
                0 if clusters[index].preferred_rank == rank else 1,
                clusters[index].cluster_key.encode("utf-8"),
            ),
        )
        assignments[selected] = rank
        counts[rank] += clusters[selected].size

    # The row-level tag/error obligations are separate from the cell intersection.
    for rank, (split, _target) in enumerate(PROSPECTIVE_SPLIT_COUNTS):
        for row in COVERAGE_MATRIX:
            relevant = tuple(
                item
                for cluster_index, chosen_rank in assignments.items()
                if chosen_rank == rank
                for item in clusters[cluster_index].items
                if _feasibility_row_eligible(item, row)
            )
            represented_tags = {tag for item in relevant for tag in item.adversarial_tags}
            represented_errors = {
                error for item in relevant for error in item.reachable_error_classes
            }
            missing = [("tag", tag) for tag in row.adversarial_tags if tag not in represented_tags]
            missing.extend(
                ("error", error) for error in row.error_classes if error not in represented_errors
            )
            for feature_kind, feature in missing:
                if (
                    feature in represented_tags
                    if feature_kind == "tag"
                    else feature in represented_errors
                ):
                    continue
                options = [
                    index
                    for index, cluster in enumerate(clusters)
                    if index not in assignments
                    and (cluster.locked_rank is None or cluster.locked_rank == rank)
                    and counts[rank] + cluster.size <= targets[rank]
                    and any(
                        _feasibility_row_eligible(item, row)
                        and (
                            feature in item.adversarial_tags
                            if feature_kind == "tag"
                            else feature in item.reachable_error_classes
                        )
                        for item in cluster.items
                    )
                ]
                if not options:
                    raise ProductionFeasibilityBlocked(
                        f"no eligible atomic cluster for {row.capability_id} {feature_kind} "
                        f"coverage in {split.value}"
                    )
                selected = min(
                    options,
                    key=lambda index: (
                        clusters[index].size,
                        0 if clusters[index].preferred_rank == rank else 1,
                        clusters[index].cluster_key.encode("utf-8"),
                    ),
                )
                assignments[selected] = rank
                counts[rank] += clusters[selected].size
                for item in clusters[selected].items:
                    if _feasibility_row_eligible(item, row):
                        represented_tags.update(item.adversarial_tags)
                        represented_errors.update(item.reachable_error_classes)

    for rank in (1, 2):
        for error_class in CRITICAL_ERROR_CLASSES:
            if any(
                chosen_rank == rank
                and any(
                    _feasibility_row_eligible(item, _row_by_capability(item.capability_id))
                    and error_class in item.reachable_error_classes
                    for item in clusters[index].items
                )
                for index, chosen_rank in assignments.items()
            ):
                continue
            options = [
                index
                for index, cluster in enumerate(clusters)
                if index not in assignments
                and (cluster.locked_rank is None or cluster.locked_rank == rank)
                and counts[rank] + cluster.size <= targets[rank]
                and any(
                    error_class in item.reachable_error_classes
                    and _feasibility_row_eligible(item, _row_by_capability(item.capability_id))
                    for item in cluster.items
                )
            ]
            if not options:
                raise ProductionFeasibilityBlocked(
                    f"critical error {error_class.value} is unavailable in "
                    f"{PROSPECTIVE_SPLIT_COUNTS[rank][0].value}"
                )
            selected = min(
                options,
                key=lambda index: (
                    clusters[index].size,
                    0 if clusters[index].preferred_rank == rank else 1,
                    clusters[index].cluster_key.encode("utf-8"),
                ),
            )
            assignments[selected] = rank
            counts[rank] += clusters[selected].size
    return assignments


def _fill_feasibility_counts(
    clusters: tuple[_FeasibilityCluster, ...], anchored: dict[int, int]
) -> tuple[int, ...]:
    targets = tuple(count for _split, count in PROSPECTIVE_SPLIT_COUNTS)
    anchored_counts = [0, 0, 0]
    for index, rank in anchored.items():
        anchored_counts[rank] += clusters[index].size
    if any(count > target for count, target in zip(anchored_counts, targets, strict=True)):
        raise ProductionFeasibilityBlocked("coverage anchors exceed exact split targets")
    remaining = tuple(index for index in range(len(clusters)) if index not in anchored)
    deficits = tuple(target - count for target, count in zip(targets, anchored_counts, strict=True))
    if sum(deficits) != sum(clusters[index].size for index in remaining):
        raise ProductionFeasibilityBlocked("coverage anchors do not leave exact remaining capacity")
    if all(clusters[index].size == 1 for index in remaining):
        assignments = dict(anchored)
        left = list(deficits)
        ordered = tuple(
            index for index in remaining if clusters[index].locked_rank is not None
        ) + tuple(index for index in remaining if clusters[index].locked_rank is None)
        for index in ordered:
            cluster = clusters[index]
            ranks = (
                (cluster.locked_rank,)
                if cluster.locked_rank is not None
                else tuple(
                    sorted(
                        range(3),
                        key=lambda rank: (0 if rank == cluster.preferred_rank else 1, rank),
                    )
                )
            )
            selected = next((rank for rank in ranks if left[rank] > 0), None)
            if selected is None:
                raise ProductionFeasibilityBlocked("singleton clusters cannot fill exact counts")
            assignments[index] = selected
            left[selected] -= 1
        if any(left):
            raise ProductionFeasibilityBlocked("singleton clusters leave an exact-count deficit")
        return tuple(assignments[index] for index in range(len(clusters)))

    states: dict[tuple[int, int], tuple[tuple[int, int] | None, int | None]] = {
        (0, 0): (None, None)
    }
    layers: list[dict[tuple[int, int], tuple[tuple[int, int] | None, int | None]]] = [states]
    processed = 0
    for index in remaining:
        cluster = clusters[index]
        processed += cluster.size
        next_states: dict[tuple[int, int], tuple[tuple[int, int] | None, int | None]] = {}
        ranks = (
            (cluster.locked_rank,)
            if cluster.locked_rank is not None
            else tuple(
                sorted(
                    range(3), key=lambda rank: (0 if rank == cluster.preferred_rank else 1, rank)
                )
            )
        )
        for public_count, validation_count in sorted(states):
            for rank in ranks:
                public = public_count + (cluster.size if rank == 0 else 0)
                validation = validation_count + (cluster.size if rank == 1 else 0)
                hidden = processed - public - validation
                if public <= deficits[0] and validation <= deficits[1] and hidden <= deficits[2]:
                    next_states.setdefault(
                        (public, validation), ((public_count, validation_count), rank)
                    )
        if not next_states:
            raise ProductionFeasibilityBlocked("no exact atomic-cluster fill remains")
        if len(next_states) > 250_000:
            raise ProductionFeasibilityBlocked(
                "bounded deterministic feasibility state budget exceeded"
            )
        states = next_states
        layers.append(states)
    state = (deficits[0], deficits[1])
    if state not in states:
        raise ProductionFeasibilityBlocked("atomic clusters cannot fill exact 260/87/87 targets")
    assignments = dict(anchored)
    for layer_index in range(len(remaining), 0, -1):
        prior, chosen_rank = layers[layer_index][state]
        assert prior is not None and chosen_rank is not None
        assignments[remaining[layer_index - 1]] = chosen_rank
        state = prior
    return tuple(assignments[index] for index in range(len(clusters)))


def validate_production_hard_feasibility(
    commitments: tuple[ProductionCandidateCommitmentV1, ...],
) -> ProductionFeasibilityReceiptV1:
    """Prove a legal 260/87/87 allocation using pre-review commitments only."""

    if len(commitments) != FINAL_TARGET_CASES:
        raise ProductionFeasibilityBlocked(
            "production feasibility requires exactly 434 commitments"
        )
    if any(not isinstance(item, ProductionCandidateCommitmentV1) for item in commitments):
        raise TypeError("feasibility input must contain only production candidate commitments")
    commitments = tuple(sorted(commitments, key=lambda item: item.candidate_id.encode("utf-8")))
    candidate_ids = tuple(item.candidate_id for item in commitments)
    payload_hashes = tuple(item.candidate_payload_hash for item in commitments)
    if (
        len(set(candidate_ids)) != FINAL_TARGET_CASES
        or len(set(payload_hashes)) != FINAL_TARGET_CASES
    ):
        raise ProductionFeasibilityBlocked(
            "production commitments require unique IDs and payload hashes"
        )
    for commitment in commitments:
        _validate_feasibility_item(commitment.item)
    validate_production_isolation(commitments)
    clusters = _feasibility_clusters(commitments)
    targets = tuple(count for _split, count in PROSPECTIVE_SPLIT_COUNTS)
    for cluster in clusters:
        if cluster.size > max(targets):
            raise ProductionFeasibilityBlocked(
                "atomic isolation cluster exceeds every split capacity"
            )
        if cluster.locked_rank is not None and cluster.size > targets[cluster.locked_rank]:
            raise ProductionFeasibilityBlocked(
                "synthetic seed lock exceeds its target split capacity"
            )
    anchors = _anchor_feasibility_coverage(clusters)
    ranks = _fill_feasibility_counts(clusters, anchors)

    cell_count_by_rank = [0, 0, 0]
    tag_count_by_rank = [0, 0, 0]
    error_count_by_rank = [0, 0, 0]
    critical_count_by_rank = [0, 0, 0]
    answerable_count_by_rank = [0, 0, 0]
    c18_refusal_count_by_rank = [0, 0, 0]
    actual_counts = [0, 0, 0]
    for cluster, rank in zip(clusters, ranks, strict=True):
        actual_counts[rank] += cluster.size
    for rank in range(3):
        assigned_clusters = tuple(
            cluster
            for cluster, assigned_rank in zip(clusters, ranks, strict=True)
            if assigned_rank == rank
        )
        assigned_items = tuple(item for cluster in assigned_clusters for item in cluster.items)
        answerable_count_by_rank[rank] = sum(
            item.refusal_decision is not RefusalDecision.REQUIRED
            and item.expected_answer_kind is not ExpectedAnswerKind.REFUSAL
            for item in assigned_items
        )
        for row in COVERAGE_MATRIX:
            for family in row.benchmark_families:
                if any(
                    _cluster_has_cell_obligation(cluster, row, family)
                    for cluster in assigned_clusters
                ):
                    cell_count_by_rank[rank] += 1
            relevant = tuple(
                item for item in assigned_items if _feasibility_row_eligible(item, row)
            )
            tag_count_by_rank[rank] += len(
                {tag for item in relevant for tag in item.adversarial_tags}.intersection(
                    row.adversarial_tags
                )
            )
            error_count_by_rank[rank] += len(
                {error for item in relevant for error in item.reachable_error_classes}.intersection(
                    row.error_classes
                )
            )
        critical_count_by_rank[rank] = len(
            {
                error
                for item in assigned_items
                if _feasibility_row_eligible(item, _row_by_capability(item.capability_id))
                for error in item.reachable_error_classes
                if error in CRITICAL_ERROR_CLASSES
            }
        )
        c18_refusal_count_by_rank[rank] = sum(
            any(_cluster_has_c18_refusal(cluster, family) for cluster in assigned_clusters)
            for family in _row_by_capability("C18").benchmark_families
        )
    if tuple(actual_counts) != targets:
        raise ProductionFeasibilityBlocked("feasibility witness does not match exact split counts")
    if any(count != 87 for count in cell_count_by_rank):
        raise ProductionFeasibilityBlocked(
            "feasibility witness misses a D/V/H capability-family cell"
        )
    expected_tags = sum(len(row.adversarial_tags) for row in COVERAGE_MATRIX)
    expected_errors = sum(len(row.error_classes) for row in COVERAGE_MATRIX)
    if any(count != expected_tags for count in tag_count_by_rank):
        raise ProductionFeasibilityBlocked("feasibility witness misses a row-level adversarial tag")
    if any(count != expected_errors for count in error_count_by_rank):
        raise ProductionFeasibilityBlocked("feasibility witness misses a row-level reachable error")
    critical_count = len(CRITICAL_ERROR_CLASSES)
    if any(critical_count_by_rank[rank] < critical_count for rank in (1, 2)):
        raise ProductionFeasibilityBlocked("protected split lacks critical-error eligibility")
    if any(count < 1 for count in answerable_count_by_rank):
        raise ProductionFeasibilityBlocked("a split lacks an answerable candidate")
    if any(count != 14 for count in c18_refusal_count_by_rank):
        raise ProductionFeasibilityBlocked("a split lacks explicit C18 refusal-family coverage")

    size_counts: dict[int, int] = defaultdict(int)
    for cluster in clusters:
        size_counts[cluster.size] += 1
    witness_digest = canonical_hash(
        tuple(
            (cluster.cluster_key, PROSPECTIVE_SPLIT_COUNTS[rank][0])
            for cluster, rank in zip(clusters, ranks, strict=True)
        )
    )
    provisional = ProductionFeasibilityReceiptV1(
        status="PASS",
        algorithm_id=PRODUCTION_FEASIBILITY_ALGORITHM,
        candidate_count=FINAL_TARGET_CASES,
        target_counts=PROSPECTIVE_SPLIT_COUNTS,
        atomic_cluster_count=len(clusters),
        cluster_size_distribution=tuple(sorted(size_counts.items())),
        hard_cell_count_by_split=tuple(
            (split, cell_count_by_rank[rank])
            for rank, (split, _count) in enumerate(PROSPECTIVE_SPLIT_COUNTS)
        ),
        adversarial_tag_count_by_split=tuple(
            (split, tag_count_by_rank[rank])
            for rank, (split, _count) in enumerate(PROSPECTIVE_SPLIT_COUNTS)
        ),
        reachable_error_count_by_split=tuple(
            (split, error_count_by_rank[rank])
            for rank, (split, _count) in enumerate(PROSPECTIVE_SPLIT_COUNTS)
        ),
        protected_critical_error_count_by_split=tuple(
            (PROSPECTIVE_SPLIT_COUNTS[rank][0], critical_count_by_rank[rank]) for rank in (1, 2)
        ),
        answerable_case_count_by_split=tuple(
            (split, answerable_count_by_rank[rank])
            for rank, (split, _count) in enumerate(PROSPECTIVE_SPLIT_COUNTS)
        ),
        c18_refusal_cell_count_by_split=tuple(
            (split, c18_refusal_count_by_rank[rank])
            for rank, (split, _count) in enumerate(PROSPECTIVE_SPLIT_COUNTS)
        ),
        commitments_digest=canonical_hash(commitments),
        feasibility_witness_digest=witness_digest,
        receipt_digest="sha256:" + "0" * 64,
    )
    return bind_production_feasibility_receipt(provisional)


@register_serializable_type
@dataclass(frozen=True, slots=True)
class ProductionCandidateStoreReceiptV1:
    batch_id: str
    store_relative_path: str
    candidate_file_digests: tuple[tuple[str, str], ...]
    candidate_count: int
    total_bytes: int
    authoring_plan_digest: str
    artifact_inventory_digest: str
    receipt_digest: str

    def __post_init__(self) -> None:
        if self.batch_id != PRODUCTION_BATCH_ID:
            raise ValueError("candidate store receipt must bind the 001C production batch")
        path = PurePosixPath(self.store_relative_path)
        if (
            path.is_absolute()
            or ".." in path.parts
            or len(path.parts) != 3
            or path.parts[:2] != ("production", "candidates")
        ):
            raise ValueError("production candidate store must remain under production/candidates/")
        if self.candidate_count != FINAL_TARGET_CASES or self.total_bytes < 1:
            raise ValueError("production candidate store must contain exactly 434 packets")
        for name in (
            "authoring_plan_digest",
            "artifact_inventory_digest",
            "receipt_digest",
        ):
            if _SHA256.fullmatch(getattr(self, name)) is None:
                raise ValueError(f"{name} must be a SHA-256 digest")
        ids = tuple(candidate_id for candidate_id, _digest in self.candidate_file_digests)
        if len(ids) != FINAL_TARGET_CASES or ids != tuple(
            sorted(set(ids), key=lambda item: item.encode("utf-8"))
        ):
            raise ValueError("production store receipt must bind 434 ordered candidate packets")
        if any(_CANDIDATE_ID.fullmatch(candidate_id) is None for candidate_id in ids):
            raise ValueError("production store receipt contains a non-production candidate ID")
        if any(
            _SHA256.fullmatch(digest) is None
            for _candidate_id, digest in self.candidate_file_digests
        ):
            raise ValueError("production candidate file digest is malformed")


def production_candidate_store_receipt_digest(receipt: ProductionCandidateStoreReceiptV1) -> str:
    return canonical_hash(
        {
            item.name: getattr(receipt, item.name)
            for item in fields(receipt)
            if item.name != "receipt_digest"
        }
    )


def bind_production_candidate_store_receipt(
    receipt: ProductionCandidateStoreReceiptV1,
) -> ProductionCandidateStoreReceiptV1:
    return replace(receipt, receipt_digest=production_candidate_store_receipt_digest(receipt))


def validate_production_candidate_store_receipt(receipt: ProductionCandidateStoreReceiptV1) -> None:
    if receipt.receipt_digest != production_candidate_store_receipt_digest(receipt):
        raise ValueError("production candidate store receipt digest mismatch")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class ProductionBatchManifestV1:
    batch_id: str
    manifest_version: str
    authoring_process_id: str
    authoring_plan_digest: str
    candidate_store_receipt_digest: str
    qualification_exclusion_digest: str
    feasibility_receipt_digest: str
    candidate_count: int
    human_approval_count: int
    final_case_count: int
    split_assignment_count: int
    protected_store_count: int
    manifest_digest: str

    def __post_init__(self) -> None:
        if self.batch_id != PRODUCTION_BATCH_ID:
            raise ValueError("production manifest must use the 001C batch identity")
        if self.manifest_version != PRODUCTION_BATCH_MANIFEST_VERSION:
            raise ValueError("unsupported production batch manifest version")
        if self.authoring_process_id != PRODUCTION_AUTHORING_PROCESS_ID:
            raise ValueError("production manifest process identity mismatch")
        if self.candidate_count != FINAL_TARGET_CASES:
            raise ValueError("production manifest must bind exactly 434 candidate packets")
        if any(
            value != 0
            for value in (
                self.human_approval_count,
                self.final_case_count,
                self.split_assignment_count,
                self.protected_store_count,
            )
        ):
            raise ValueError("production candidate manifest cannot imply approval or finalization")
        for name in (
            "authoring_plan_digest",
            "candidate_store_receipt_digest",
            "qualification_exclusion_digest",
            "feasibility_receipt_digest",
            "manifest_digest",
        ):
            if _SHA256.fullmatch(getattr(self, name)) is None:
                raise ValueError(f"{name} must be a SHA-256 digest")


def production_batch_manifest_digest(manifest: ProductionBatchManifestV1) -> str:
    return canonical_hash(
        {
            item.name: getattr(manifest, item.name)
            for item in fields(manifest)
            if item.name != "manifest_digest"
        }
    )


def bind_production_batch_manifest(
    manifest: ProductionBatchManifestV1,
) -> ProductionBatchManifestV1:
    return replace(manifest, manifest_digest=production_batch_manifest_digest(manifest))


def validate_production_batch_manifest(manifest: ProductionBatchManifestV1) -> None:
    if manifest.manifest_digest != production_batch_manifest_digest(manifest):
        raise ValueError("production batch manifest digest mismatch")


def validate_production_candidate_set(
    packets: tuple[CandidateReviewPacket, ...],
    *,
    source_resolver: SourceArtifactResolver | None = None,
) -> tuple[ProductionCandidateCommitmentV1, ...]:
    """Validate exact production IDs and pending packets, then bind commitments."""

    if len(packets) != FINAL_TARGET_CASES:
        raise ValueError("production candidate set must contain exactly 434 packets")
    if any(
        not packet.candidate_id.startswith(PRODUCTION_CANDIDATE_ID_PREFIX) for packet in packets
    ):
        raise ValueError("production candidate set contains a non-production ID")
    for packet in packets:
        validate_production_candidate_packet(packet, source_resolver=source_resolver)
    validate_candidate_set(packets, source_resolver=source_resolver)
    commitments = tuple(
        sorted(
            (
                ProductionCandidateCommitmentV1(
                    production_plan_item_from_packet(packet), packet.candidate_payload_hash
                )
                for packet in packets
            ),
            key=lambda item: item.candidate_id.encode("utf-8"),
        )
    )
    validate_production_isolation(commitments)
    return commitments


__all__ = [
    "FINAL_TARGET_CASES",
    "PRODUCTION_AUTHORING_PLAN_VERSION",
    "PRODUCTION_AUTHORING_PROCESS_ID",
    "PRODUCTION_BATCH_ID",
    "PRODUCTION_BATCH_MANIFEST_VERSION",
    "PRODUCTION_CANDIDATE_ID_PREFIX",
    "PRODUCTION_FEASIBILITY_ALGORITHM",
    "PROSPECTIVE_SPLIT_COUNTS",
    "ProductionAuthoringPlanItemV1",
    "ProductionAuthoringPlanV1",
    "ProductionBatchManifestV1",
    "ProductionCandidateCommitmentV1",
    "ProductionCandidateStoreReceiptV1",
    "ProductionFeasibilityBlocked",
    "ProductionFeasibilityReceiptV1",
    "ProductionIsolationValidationV1",
    "bind_production_authoring_plan",
    "bind_production_batch_manifest",
    "bind_production_candidate_store_receipt",
    "bind_production_feasibility_receipt",
    "build_production_candidate_commitment",
    "production_authoring_plan_digest",
    "production_batch_manifest_digest",
    "production_candidate_store_receipt_digest",
    "production_feasibility_receipt_digest",
    "production_plan_item_from_packet",
    "validate_production_authoring_plan",
    "validate_production_batch_manifest",
    "validate_production_candidate_packet",
    "validate_production_candidate_set",
    "validate_production_candidate_store_receipt",
    "validate_production_feasibility_receipt",
    "validate_production_hard_feasibility",
    "validate_production_isolation",
]
