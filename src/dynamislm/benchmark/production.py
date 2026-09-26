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
from dynamislm.benchmark.coverage import COVERAGE_MATRIX, coverage_manifest_digest
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
    "PROSPECTIVE_SPLIT_COUNTS",
    "ProductionAuthoringPlanItemV1",
    "ProductionAuthoringPlanV1",
    "ProductionBatchManifestV1",
    "ProductionCandidateCommitmentV1",
    "ProductionCandidateStoreReceiptV1",
    "ProductionIsolationValidationV1",
    "bind_production_authoring_plan",
    "bind_production_batch_manifest",
    "bind_production_candidate_store_receipt",
    "build_production_candidate_commitment",
    "production_authoring_plan_digest",
    "production_batch_manifest_digest",
    "production_candidate_store_receipt_digest",
    "production_plan_item_from_packet",
    "validate_production_authoring_plan",
    "validate_production_batch_manifest",
    "validate_production_candidate_packet",
    "validate_production_candidate_set",
    "validate_production_candidate_store_receipt",
    "validate_production_isolation",
]
