"""Production-candidate contracts, kept separate from qualification batches."""

from __future__ import annotations

import hashlib
import heapq
import itertools
import re
import tempfile
import threading
import time
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass, fields, replace
from pathlib import Path, PurePosixPath
from typing import Any, TypedDict

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
from dynamislm.benchmark.contamination import (
    exact_13_token_shingles,
    normalize_text,
    normalized_edit_similarity_at_least,
    normalized_text_sha256,
)
from dynamislm.benchmark.coverage import (
    COVERAGE_MATRIX,
    CoverageRow,
    coverage_manifest_digest,
)
from dynamislm.benchmark.pre_review import (
    CandidateReviewPacket,
    candidate_scientific_projection,
    validate_candidate_review_packet,
    validate_candidate_set,
)
from dynamislm.benchmark.scoring_paths import reachable_error_classes
from dynamislm.benchmark.source_artifacts import SourceArtifactResolver
from dynamislm.serialization import canonical_hash, register_serializable_type

PRODUCTION_CANDIDATE_ID_PREFIX = "PSE-V1-CANDIDATE:"
PRODUCTION_BATCH_ID = "PSE-V1-PRODUCTION/RES-115-CASE-AUTHORING-001C"
PRODUCTION_AUTHORING_PROCESS_ID = "agent-process:codex:RES-115-CASE-AUTHORING-001C"
_QUALIFICATION_AUTHORING_PROCESS_ID = "agent-process:codex:RES-115-CASE-AUTHORING-001B"
PRODUCTION_AUTHORING_PLAN_VERSION = "pse-production-authoring-plan@1.1.0"
PRODUCTION_BATCH_MANIFEST_VERSION = "pse-production-batch@1.0.0"
PRODUCTION_SYNTHETIC_QUESTION_SURFACE_VARIANTS = (
    ("F05", "PSE-V1-C08-REFUSAL-SURFACE@1.0.0:UNSUPPORTED_VS_ZERO"),
    ("F06", "PSE-V1-C08-REFUSAL-SURFACE@1.0.0:METHOD_EXECUTABILITY"),
    ("F13", "PSE-V1-C08-REFUSAL-SURFACE@1.0.0:INPUT_APPLICABILITY"),
    ("F14", "PSE-V1-C08-REFUSAL-SURFACE@1.0.0:SAFE_PARTIAL_ACTION"),
)
_SYNTHETIC_QUESTION_VARIANT_BY_FAMILY = dict(PRODUCTION_SYNTHETIC_QUESTION_SURFACE_VARIANTS)
PRODUCTION_C01_QUESTION_SURFACE_VARIANT_ID = "PSE-V1-C01-MEASURAND-IDENTITY-SURFACE@1.0.0"
PRODUCTION_C02_QUESTION_SURFACE_VARIANT_ID = "PSE-V1-C02-PROTOCOL-EXTRACTION-SURFACE@1.0.0"
PRODUCTION_C03_QUESTION_SURFACE_VARIANT_ID = "PSE-V1-C03-DISPLAY-LABEL-SURFACE@1.0.0"
PRODUCTION_C04_QUESTION_SURFACE_VARIANT_ID = "PSE-V1-C04-VALUE-ORIGIN-SURFACE@1.0.0"
PRODUCTION_C05_QUESTION_SURFACE_VARIANT_ID = "PSE-V1-C05-UNIT-PROVENANCE-SURFACE@1.0.0"
PRODUCTION_C06_QUESTION_SURFACE_VARIANT_ID = "PSE-V1-C06-FRAME-EVENT-SURFACE@1.0.0"
PRODUCTION_C09_QUESTION_SURFACE_VARIANT_ID = "PSE-V1-C09-CHANGE-CLAIM-SURFACE@1.0.0"
PRODUCTION_C10_QUESTION_SURFACE_VARIANT_ID = "PSE-V1-C10-ANALYSIS-SUPPORT-SURFACE@1.0.0"
PRODUCTION_C11_QUESTION_SURFACE_VARIANT_ID = "PSE-V1-C11-LEVEL-OF-ANALYSIS-SURFACE@1.0.0"
PRODUCTION_C12_QUESTION_SURFACE_VARIANT_ID = "PSE-V1-C12-RELIABILITY-UNCERTAINTY-SURFACE@1.0.0"
PRODUCTION_C17_QUESTION_SURFACE_VARIANT_ID = "PSE-V1-C17-ERROR-CLASSIFICATION-SURFACE@1.0.0"
PRODUCTION_C14_QUESTION_SURFACE_VARIANT_ID = "PSE-V1-C14-EVIDENCE-APPLICABILITY-SURFACE@1.0.0"
PRODUCTION_C15_QUESTION_SURFACE_VARIANT_ID = "PSE-V1-C15-CAUSAL-BOUNDARY-SURFACE@1.0.0"
PRODUCTION_C15_MUTATION_QUESTION_SURFACE_VARIANT_ID = "PSE-V1-C15-CAUSAL-MUTATION-SURFACE@1.0.0"
PRODUCTION_ENGINE_QUESTION_SURFACE_VARIANT_ID = "PSE-V1-ENGINE-QUESTION-SURFACE@1.0.0"
PRODUCTION_SOURCE_QUESTION_SURFACE_VARIANT_ID = "PSE-V1-SOURCE-QUESTION-SURFACE@1.0.0"
PRODUCTION_ADVERSARIAL_TAG_FOCUS_SURFACE_VERSION = "PSE-V1-ADVERSARIAL-TAG-FOCUS@1.0.0"
PRODUCTION_IDENTITY_MUTATION_QUESTION_SURFACE_VARIANT_ID = "PSE-V1-IDENTITY-MUTATION-SURFACE@1.0.0"
PRODUCTION_C07_QUESTION_SURFACE_VARIANT_ID = "PSE-V1-C07-COMPARABILITY-SURFACE@1.0.0"
PRODUCTION_C07_MUTATION_QUESTION_SURFACE_VARIANT_ID = (
    "PSE-V1-C07-COMPARABILITY-MUTATION-SURFACE@1.0.0"
)
PRODUCTION_C17_MUTATION_QUESTION_SURFACE_VARIANT_ID = "PSE-V1-C17-ERROR-MUTATION-SURFACE@1.0.0"
PRODUCTION_C09_MUTATION_QUESTION_SURFACE_VARIANT_ID = "PSE-V1-C09-CLAIM-MUTATION-SURFACE@1.0.0"
PRODUCTION_C18_QUESTION_SURFACE_VARIANT_ID = "PSE-V1-C18-REFUSAL-SURFACE@1.0.0"
PRODUCTION_C18_MUTATION_QUESTION_SURFACE_VARIANT_ID = "PSE-V1-C18-REFUSAL-MUTATION-SURFACE@1.0.0"
_SEMANTIC_QUESTION_VARIANT_BY_CAPABILITY = {
    "C01": PRODUCTION_C01_QUESTION_SURFACE_VARIANT_ID,
    "C02": PRODUCTION_C02_QUESTION_SURFACE_VARIANT_ID,
    "C03": PRODUCTION_C03_QUESTION_SURFACE_VARIANT_ID,
    "C04": PRODUCTION_C04_QUESTION_SURFACE_VARIANT_ID,
    "C05": PRODUCTION_C05_QUESTION_SURFACE_VARIANT_ID,
    "C06": PRODUCTION_C06_QUESTION_SURFACE_VARIANT_ID,
    "C09": PRODUCTION_C09_QUESTION_SURFACE_VARIANT_ID,
    "C10": PRODUCTION_C10_QUESTION_SURFACE_VARIANT_ID,
    "C11": PRODUCTION_C11_QUESTION_SURFACE_VARIANT_ID,
    "C12": PRODUCTION_C12_QUESTION_SURFACE_VARIANT_ID,
    "C17": PRODUCTION_C17_QUESTION_SURFACE_VARIANT_ID,
    "C07": PRODUCTION_C07_QUESTION_SURFACE_VARIANT_ID,
    "C14": PRODUCTION_C14_QUESTION_SURFACE_VARIANT_ID,
    "C15": PRODUCTION_C15_QUESTION_SURFACE_VARIANT_ID,
}


def _production_question_surface_variant_id(
    origin: CaseOrigin, capability_id: str, family: str
) -> str | None:
    surface_id: str | None = None
    if origin is CaseOrigin.DETERMINISTIC_SYNTHETIC and capability_id == "C08":
        surface_id = _SYNTHETIC_QUESTION_VARIANT_BY_FAMILY.get(family)
    elif origin is CaseOrigin.ADVERSARIAL_MUTATION:
        surface_id = {
            "C01": PRODUCTION_IDENTITY_MUTATION_QUESTION_SURFACE_VARIANT_ID,
            "C03": PRODUCTION_IDENTITY_MUTATION_QUESTION_SURFACE_VARIANT_ID,
            "C04": PRODUCTION_IDENTITY_MUTATION_QUESTION_SURFACE_VARIANT_ID,
            "C07": PRODUCTION_C07_MUTATION_QUESTION_SURFACE_VARIANT_ID,
            "C09": PRODUCTION_C09_MUTATION_QUESTION_SURFACE_VARIANT_ID,
            "C15": PRODUCTION_C15_MUTATION_QUESTION_SURFACE_VARIANT_ID,
            "C17": PRODUCTION_C17_MUTATION_QUESTION_SURFACE_VARIANT_ID,
            "C18": PRODUCTION_C18_MUTATION_QUESTION_SURFACE_VARIANT_ID,
        }.get(capability_id)
    elif origin is CaseOrigin.DETERMINISTIC_ENGINE_DERIVED:
        surface_id = PRODUCTION_ENGINE_QUESTION_SURFACE_VARIANT_ID
    elif origin is CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION:
        surface_id = PRODUCTION_SOURCE_QUESTION_SURFACE_VARIANT_ID
    elif origin is CaseOrigin.EXPERT_AUTHORED_SEMANTIC:
        if capability_id == "C18":
            surface_id = PRODUCTION_C18_QUESTION_SURFACE_VARIANT_ID
        else:
            surface_id = _SEMANTIC_QUESTION_VARIANT_BY_CAPABILITY.get(capability_id)
    return (
        f"{surface_id}:{PRODUCTION_ADVERSARIAL_TAG_FOCUS_SURFACE_VERSION}"
        if surface_id is not None
        else None
    )


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
    question_surface_variant_id: str | None = None
    engine_reference_case_id: str | None = None

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
            "question_surface_variant_id",
            "engine_reference_case_id",
        ):
            _optional_text(getattr(self, name), name)
        if self.expert_author_batch_id in {
            PRODUCTION_AUTHORING_PROCESS_ID,
            _QUALIFICATION_AUTHORING_PROCESS_ID,
        }:
            raise ValueError("global authoring process identity cannot be an expert author batch")
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
            if not self.protocol_template_ids:
                raise ValueError("template-driven semantic candidate requires protocol/template ID")
        elif (
            self.origin_class
            in {
                CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION,
                CaseOrigin.DETERMINISTIC_ENGINE_DERIVED,
                CaseOrigin.DETERMINISTIC_SYNTHETIC,
            }
            and self.expert_author_batch_id is not None
        ):
            raise ValueError(
                "non-semantic production candidate cannot carry an expert author batch"
            )
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
        if self.origin_class is CaseOrigin.DETERMINISTIC_ENGINE_DERIVED:
            if self.engine_reference_case_id is None:
                raise ValueError(
                    "engine-derived production candidate requires a RES-71 reference ID"
                )
        elif self.engine_reference_case_id is not None:
            raise ValueError(
                "only engine-derived production candidates may carry a RES-71 reference ID"
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
        expected_surface_variant = _production_question_surface_variant_id(
            item.origin_class,
            item.capability_id,
            item.benchmark_family,
        )
        if item.question_surface_variant_id != expected_surface_variant:
            raise ValueError("production plan question surface variant is stale or unauthorized")
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
    recipes = {
        (item.capability_id, item.benchmark_family): item for item in AUTHORING_RECIPE_REGISTRY
    }
    recipe = recipes.get((packet.capability_id, packet.benchmark_family))
    if recipe is None:
        raise ValueError("production candidate cell has no frozen authoring recipe")
    allowed_authority_classes = _authority_classes(recipe.authority_kinds)
    eligible_authority_classes = authority_class_candidates.intersection(allowed_authority_classes)
    if not eligible_authority_classes:
        raise ValueError("production candidate has no authority class permitted for its cell")
    authority_class = sorted(eligible_authority_classes, key=lambda item: item.encode("utf-8"))[0]
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
        question_surface_variant_id=_production_question_surface_variant_id(
            provenance.origin_class,
            packet.capability_id,
            packet.benchmark_family,
        ),
        engine_reference_case_id=provenance.engine_reference_case_id,
    )


def validate_production_origin_isolation_metadata(packet: CandidateReviewPacket) -> None:
    """Validate production authorship and origin-scoped isolation identities."""

    origin = packet.proposed_provenance.origin_class
    contamination = packet.contamination
    batch_id = contamination.expert_author_batch_id
    if batch_id in {PRODUCTION_AUTHORING_PROCESS_ID, _QUALIFICATION_AUTHORING_PROCESS_ID}:
        raise ValueError("global authoring process identity cannot be an expert author batch")
    if (
        origin
        in {
            CaseOrigin.EXPERT_AUTHORED_SEMANTIC,
            CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION,
        }
        and packet.proposed_provenance.author_id != PRODUCTION_AUTHORING_PROCESS_ID
    ):
        raise ValueError("production semantic/source material must remain agent-authored")
    if origin is CaseOrigin.EXPERT_AUTHORED_SEMANTIC:
        if batch_id is None:
            raise ValueError("expert semantic candidate requires a bounded author batch")
        if contamination.protocol_template_id is None:
            raise ValueError("template-driven semantic candidate requires protocol/template ID")
    elif (
        origin
        in {
            CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION,
            CaseOrigin.DETERMINISTIC_ENGINE_DERIVED,
            CaseOrigin.DETERMINISTIC_SYNTHETIC,
        }
        and batch_id is not None
    ):
        raise ValueError(f"{origin.value} production candidate cannot carry an expert author batch")


def _validate_production_mutation_isolation_metadata(
    packets: tuple[CandidateReviewPacket, ...],
) -> None:
    by_id = {packet.candidate_id: packet for packet in packets}
    for child in packets:
        binding = child.parent_candidate_binding
        if binding is None:
            continue
        parent = by_id.get(binding.parent_candidate_id)
        if parent is None:
            continue  # Candidate-set validation reports the missing parent first.
        if (
            child.contamination.expert_author_batch_id
            != parent.contamination.expert_author_batch_id
            or child.contamination.protocol_template_id != parent.contamination.protocol_template_id
        ):
            raise ValueError(
                "mutation must preserve parent expert-author batch and template metadata"
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
    validate_production_origin_isolation_metadata(packet)
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
    *,
    defer_split_lock_conflicts: bool = False,
    enforce_public_capacity: bool = True,
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
    if not defer_split_lock_conflicts and any(
        len(splits) > 1 for splits in generator_locks.values()
    ):
        raise ValueError("generator family conflicts with split-qualified seed namespaces")
    for cluster_id, members in cluster_members.items():
        if enforce_public_capacity and len(members) > 260:
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


PRODUCTION_FEASIBILITY_ALGORITHM = "PSE-V1-PRE-REVIEW-FEASIBILITY@1.1.0"


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
    exact_shingle_colocation_pair_count: int
    exact_shingle_colocation_digest: str
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
        if self.exact_shingle_colocation_pair_count < 0:
            raise ValueError("exact-shingle co-location pair count cannot be negative")
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
            "exact_shingle_colocation_digest",
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


PRODUCTION_EXACT_FEASIBILITY_ALGORITHM = "PSE-V1-PRE-REVIEW-EXACT-FEASIBILITY@2.0.0"
PRODUCTION_EXACT_SOLVER_FAMILY = "CP-SAT"
PRODUCTION_EXACT_SOLVER_VERSION = "9.15.6755"


class _ProductionExactSolverConfig(TypedDict):
    max_time_in_seconds: float
    num_search_workers: int
    random_seed: int
    cp_model_presolve: bool
    randomize_search: bool


PRODUCTION_EXACT_SOLVER_CONFIG: _ProductionExactSolverConfig = {
    "max_time_in_seconds": 60.0,
    "num_search_workers": 1,
    "random_seed": 0,
    "cp_model_presolve": True,
    "randomize_search": False,
}


@register_serializable_type
@dataclass(frozen=True, slots=True)
class ProductionExactFeasibilityReceiptV2:
    status: str
    algorithm_id: str
    candidate_count: int
    target_counts: tuple[tuple[SplitName, int], ...]
    base_component_count: int
    base_component_inventory_digest: str
    co_location_component_count: int
    co_location_component_inventory_digest: str
    co_location_component_size_distribution: tuple[tuple[int, int], ...]
    exact_shingle_colocation_pair_count: int
    exact_shingle_colocation_digest: str
    commitments_digest: str
    solver_family: str
    solver_version: str
    solver_config_digest: str
    base_model_digest: str
    colocation_model_digest: str
    base_status: str
    colocation_status: str
    legacy_base_status: str
    canonical_self_reduction_status: str
    canonical_witness_digest: str | None
    hard_cell_count_by_split: tuple[tuple[SplitName, int], ...]
    adversarial_tag_count_by_split: tuple[tuple[SplitName, int], ...]
    reachable_error_count_by_split: tuple[tuple[SplitName, int], ...]
    protected_critical_error_count_by_split: tuple[tuple[SplitName, int], ...]
    answerable_case_count_by_split: tuple[tuple[SplitName, int], ...]
    c18_refusal_cell_count_by_split: tuple[tuple[SplitName, int], ...]
    c03_f04_eligible_component_count: int
    c03_f04_public_feasible_component_count: int
    c03_f04_diagnostic_digest: str
    feasibility_membership_persisted: bool
    receipt_digest: str

    def __post_init__(self) -> None:
        if self.status not in {"FEASIBLE", "INFEASIBLE", "BLOCKED"}:
            raise ValueError("exact feasibility status is invalid")
        if self.algorithm_id != PRODUCTION_EXACT_FEASIBILITY_ALGORITHM:
            raise ValueError("exact feasibility receipt has the wrong algorithm ID")
        if (
            self.candidate_count != FINAL_TARGET_CASES
            or self.target_counts != PROSPECTIVE_SPLIT_COUNTS
        ):
            raise ValueError("exact feasibility receipt must bind the frozen 434-case targets")
        if self.base_component_count < 1 or self.co_location_component_count < 1:
            raise ValueError("exact feasibility receipt requires allocation components")
        if self.exact_shingle_colocation_pair_count < 0:
            raise ValueError("exact-shingle co-location pair count cannot be negative")
        if (
            sum(count for _size, count in self.co_location_component_size_distribution)
            != self.co_location_component_count
            or sum(size * count for size, count in self.co_location_component_size_distribution)
            != FINAL_TARGET_CASES
        ):
            raise ValueError("co-location component distribution is inconsistent")
        if self.solver_family != PRODUCTION_EXACT_SOLVER_FAMILY:
            raise ValueError("exact feasibility receipt has the wrong solver family")
        if self.solver_version != PRODUCTION_EXACT_SOLVER_VERSION:
            raise ValueError("exact feasibility receipt has the wrong solver version")
        if self.base_status not in {"FEASIBLE", "INFEASIBLE", "UNKNOWN"} or (
            self.colocation_status not in {"FEASIBLE", "INFEASIBLE", "UNKNOWN"}
        ):
            raise ValueError("exact feasibility solver status is invalid")
        if self.legacy_base_status not in {"PASS", "BLOCKED"}:
            raise ValueError("legacy diagnostic status is invalid")
        if self.canonical_self_reduction_status not in {"PASS", "NOT_RUN"}:
            raise ValueError("canonical self-reduction status is invalid")
        if self.c03_f04_eligible_component_count < 0 or not (
            0
            <= self.c03_f04_public_feasible_component_count
            <= self.c03_f04_eligible_component_count
        ):
            raise ValueError("C03xF04 diagnostic counts are invalid")
        if self.feasibility_membership_persisted:
            raise ValueError("exact feasibility must not persist split membership")
        for name in (
            "base_component_inventory_digest",
            "co_location_component_inventory_digest",
            "exact_shingle_colocation_digest",
            "commitments_digest",
            "solver_config_digest",
            "base_model_digest",
            "colocation_model_digest",
            "c03_f04_diagnostic_digest",
            "receipt_digest",
        ):
            if _SHA256.fullmatch(getattr(self, name)) is None:
                raise ValueError(f"{name} must be a SHA-256 digest")
        if (
            self.canonical_witness_digest is not None
            and _SHA256.fullmatch(self.canonical_witness_digest) is None
        ):
            raise ValueError("canonical witness digest must be a SHA-256 digest")
        if self.status != "FEASIBLE" and self.canonical_witness_digest is not None:
            raise ValueError("non-feasible exact receipt cannot contain a canonical witness")
        if self.status == "FEASIBLE":
            if self.base_status != "FEASIBLE" or self.colocation_status != "FEASIBLE":
                raise ValueError("feasible exact receipt lacks both exact solver results")
            if self.canonical_self_reduction_status == "PASS" and self.canonical_witness_digest:
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
                    ("answerable", self.answerable_case_count_by_split, None),
                    ("C18 refusal", self.c18_refusal_cell_count_by_split, 14),
                ):
                    if tuple(split for split, _ in values) != tuple(
                        split for split, _ in PROSPECTIVE_SPLIT_COUNTS
                    ):
                        raise ValueError(
                            f"exact feasibility {name} counts have wrong split coverage"
                        )
                    if expected is not None and any(count != expected for _split, count in values):
                        raise ValueError(
                            f"exact feasibility {name} counts violate the frozen target"
                        )
                    if name == "answerable" and any(count < 1 for _split, count in values):
                        raise ValueError("exact feasibility answerability coverage is incomplete")
                if tuple(split for split, _ in self.protected_critical_error_count_by_split) != (
                    SplitName.FROZEN_VALIDATION,
                    SplitName.HIDDEN_FINAL,
                ) or any(
                    count != len(CRITICAL_ERROR_CLASSES)
                    for _split, count in self.protected_critical_error_count_by_split
                ):
                    raise ValueError("protected critical-error coverage is incomplete")
            elif self.canonical_self_reduction_status == "NOT_RUN" and (
                self.canonical_witness_digest is not None
                or any(
                    (
                        self.hard_cell_count_by_split,
                        self.adversarial_tag_count_by_split,
                        self.reachable_error_count_by_split,
                        self.protected_critical_error_count_by_split,
                        self.answerable_case_count_by_split,
                        self.c18_refusal_cell_count_by_split,
                    )
                )
            ):
                raise ValueError("feasibility-only receipt contains canonical allocation evidence")
            elif self.canonical_self_reduction_status != "NOT_RUN":
                raise ValueError("feasible exact receipt has inconsistent canonical evidence")
        elif self.status == "INFEASIBLE" and "INFEASIBLE" not in {
            self.base_status,
            self.colocation_status,
        }:
            raise ValueError("infeasible receipt lacks an exact infeasibility result")


def production_exact_feasibility_receipt_digest(
    receipt: ProductionExactFeasibilityReceiptV2,
) -> str:
    return canonical_hash(
        {
            item.name: getattr(receipt, item.name)
            for item in fields(receipt)
            if item.name != "receipt_digest"
        }
    )


def bind_production_exact_feasibility_receipt(
    receipt: ProductionExactFeasibilityReceiptV2,
) -> ProductionExactFeasibilityReceiptV2:
    return replace(receipt, receipt_digest=production_exact_feasibility_receipt_digest(receipt))


def validate_production_exact_feasibility_receipt(
    receipt: ProductionExactFeasibilityReceiptV2,
) -> None:
    if receipt.receipt_digest != production_exact_feasibility_receipt_digest(receipt):
        raise ValueError("exact production feasibility receipt digest mismatch")


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
    *,
    exact_shingle_colocation_pairs: tuple[tuple[str, str], ...] = (),
    allow_incompatible_locks: bool = False,
) -> tuple[_FeasibilityCluster, ...]:
    items_by_id = {item.candidate_id: item for item in (c.item for c in commitments)}
    parent = {candidate_id: candidate_id for candidate_id in items_by_id}

    def find(candidate_id: str) -> str:
        root = candidate_id
        while parent[root] != root:
            root = parent[root]
        while parent[candidate_id] != candidate_id:
            next_id = parent[candidate_id]
            parent[candidate_id] = root
            candidate_id = next_id
        return root

    def union(left: str, right: str) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            first, second = sorted((left_root, right_root), key=lambda value: value.encode("utf-8"))
            parent[second] = first

    by_isolation_cluster: dict[str, list[str]] = defaultdict(list)
    for commitment in commitments:
        by_isolation_cluster[commitment.item.isolation_cluster_id].append(commitment.candidate_id)
    for candidate_ids in by_isolation_cluster.values():
        for candidate_id in candidate_ids[1:]:
            union(candidate_ids[0], candidate_id)
    for left, right in exact_shingle_colocation_pairs:
        union(left, right)

    grouped: dict[str, list[ProductionAuthoringPlanItemV1]] = defaultdict(list)
    for candidate_id, item in items_by_id.items():
        grouped[find(candidate_id)].append(item)
    clusters: list[_FeasibilityCluster] = []
    for raw_items in grouped.values():
        items = tuple(sorted(raw_items, key=lambda item: item.candidate_id.encode("utf-8")))
        isolation_cluster_ids = tuple(
            sorted(
                {item.isolation_cluster_id for item in items},
                key=lambda value: value.encode("utf-8"),
            )
        )
        locked_splits = {
            parse_production_seed_namespace(item.seed_namespace).split_name
            for item in items
            if item.origin_class is CaseOrigin.DETERMINISTIC_SYNTHETIC
            and item.seed_namespace is not None
        }
        if len(locked_splits) > 1 and not allow_incompatible_locks:
            raise ProductionFeasibilityBlocked(
                "one atomic cluster has incompatible synthetic seed split constraints"
            )
        cluster_key_payload = (
            {
                "isolation_cluster_id": isolation_cluster_ids[0],
                "candidate_ids": tuple(item.candidate_id for item in items),
            }
            if len(isolation_cluster_ids) == 1
            else {
                "co_located_isolation_cluster_ids": isolation_cluster_ids,
                "candidate_ids": tuple(item.candidate_id for item in items),
            }
        )
        cluster_key = canonical_hash(cluster_key_payload).removeprefix("sha256:")
        cluster_id = (
            isolation_cluster_ids[0]
            if len(isolation_cluster_ids) == 1
            else "co-located:" + canonical_hash(isolation_cluster_ids).removeprefix("sha256:")
        )
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
                    if len(locked_splits) == 1
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
    *,
    selected_requirements: dict[int, str] | None = None,
) -> dict[int, int]:
    targets = tuple(count for _split, count in PROSPECTIVE_SPLIT_COUNTS)
    assignments: dict[int, int] = {
        index: cluster.locked_rank
        for index, cluster in enumerate(clusters)
        if cluster.locked_rank is not None
    }
    used = [0, 0, 0]
    for index, rank in assignments.items():
        used[rank] += clusters[index].size
    if any(used[rank] > targets[rank] for rank in range(3)):
        raise ProductionFeasibilityBlocked("split-locked clusters exceed an exact split capacity")

    requirements: list[tuple[int, str, CoverageRow | None, str | None, object | None, int]] = []
    for rank in range(3):
        for row in COVERAGE_MATRIX:
            requirements.extend(
                (rank, "cell", row, family, None, 1) for family in row.benchmark_families
            )
        requirements.extend(
            (rank, "c18", _row_by_capability("C18"), family, None, 1)
            for family in _row_by_capability("C18").benchmark_families
        )
        requirements.append((rank, "answerable", None, None, None, 1))
        requirements.extend(
            (rank, "tag", row, None, tag, 1)
            for row in COVERAGE_MATRIX
            for tag in row.adversarial_tags
        )
        requirements.extend(
            (rank, "error", row, None, error, 1)
            for row in COVERAGE_MATRIX
            for error in row.error_classes
        )
    requirements.extend(
        (rank, "critical", None, None, error, 2)
        for rank in (1, 2)
        for error in CRITICAL_ERROR_CLASSES
    )

    def covers(
        cluster: _FeasibilityCluster,
        requirement: tuple[int, str, CoverageRow | None, str | None, object | None, int],
    ) -> bool:
        _rank, kind, row, family, feature, _demand = requirement
        if kind == "cell":
            assert row is not None and family is not None
            return _cluster_has_cell_obligation(cluster, row, family)
        if kind == "c18":
            assert family is not None
            return _cluster_has_c18_refusal(cluster, family)
        if kind == "answerable":
            return any(
                item.refusal_decision is not RefusalDecision.REQUIRED
                and item.expected_answer_kind is not ExpectedAnswerKind.REFUSAL
                for item in cluster.items
            )
        if kind == "tag":
            assert row is not None
            return any(
                _feasibility_row_eligible(item, row) and feature in item.adversarial_tags
                for item in cluster.items
            )
        if kind == "error":
            assert row is not None
            return any(
                _feasibility_row_eligible(item, row) and feature in item.reachable_error_classes
                for item in cluster.items
            )
        assert kind == "critical" and isinstance(feature, ErrorClass)
        return any(
            _feasibility_row_eligible(item, _row_by_capability(item.capability_id))
            and feature in item.reachable_error_classes
            for item in cluster.items
        )

    def failure_message(
        requirement: tuple[int, str, CoverageRow | None, str | None, object | None, int],
    ) -> str:
        rank, kind, row, family, feature, _demand = requirement
        split = PROSPECTIVE_SPLIT_COUNTS[rank][0].value
        if kind == "cell":
            assert row is not None and family is not None
            return f"no eligible atomic cluster for {row.capability_id}x{family} in {split}"
        if kind == "c18":
            assert family is not None
            return f"no eligible atomic refusal candidate for C18x{family} in {split}"
        if kind == "answerable":
            return f"no answerable candidate can be assigned to {split}"
        if kind in {"tag", "error"}:
            assert row is not None
            return f"no eligible atomic cluster for {row.capability_id} {kind} coverage in {split}"
        return f"critical error {getattr(feature, 'value', feature)} is unavailable in {split}"

    candidates_by_requirement = tuple(
        (
            requirement,
            tuple(index for index, cluster in enumerate(clusters) if covers(cluster, requirement)),
        )
        for requirement in requirements
    )
    if any(
        len(candidates) < requirement[5] for requirement, candidates in candidates_by_requirement
    ):
        requirement = next(
            requirement
            for requirement, candidates in candidates_by_requirement
            if len(candidates) < requirement[5]
        )
        raise ProductionFeasibilityBlocked(failure_message(requirement))

    split_priority = {1: 0, 2: 1, 0: 2}
    kind_priority = {"cell": 0, "c18": 1, "critical": 2, "tag": 3, "error": 4, "answerable": 5}
    failures: list[str] = []
    seen: set[tuple[tuple[int, int], ...]] = set()
    attempts = 0

    def search(current: dict[int, int], counts: list[int]) -> dict[int, int] | None:
        nonlocal attempts
        attempts += 1
        # ponytail: bounded deterministic search; raise the cap if the frozen batch grows.
        if attempts > 250_000:
            raise ProductionFeasibilityBlocked(
                "bounded deterministic feasibility anchor search state budget exceeded"
            )
        state = tuple(sorted(current.items()))
        if state in seen:
            return None
        seen.add(state)

        choices = []
        for requirement, candidates in candidates_by_requirement:
            rank, kind, row, family, feature, demand = requirement
            covered = sum(
                assigned_rank == rank and index in candidates
                for index, assigned_rank in current.items()
            )
            need = demand - covered
            if need <= 0:
                continue
            options = tuple(
                index
                for index in candidates
                if index not in current
                and (clusters[index].locked_rank is None or clusters[index].locked_rank == rank)
                and counts[rank] + clusters[index].size <= targets[rank]
            )
            if len(options) < need:
                failures.append(failure_message(requirement))
                return None
            slack = len(options) - need
            choices.append(
                (
                    (
                        slack,
                        len(options),
                        split_priority[rank],
                        kind_priority[kind],
                        row.capability_id if row is not None else "",
                        family or "",
                        str(getattr(feature, "value", feature) or ""),
                    ),
                    requirement,
                    options,
                )
            )

        if not choices:
            try:
                _fill_feasibility_counts(clusters, current)
            except ProductionFeasibilityBlocked as exc:
                failures.append(str(exc))
                return None
            return current

        _key, requirement, options = min(choices, key=lambda item: item[0])
        rank = requirement[0]
        other_options = tuple(
            (other_requirement, indices)
            for _other_key, other_requirement, indices in choices
            if other_requirement[0] == rank
        )
        ordered_options = sorted(
            options,
            key=lambda index: (
                -sum(index in indices for _other_requirement, indices in other_options),
                clusters[index].size,
                0 if clusters[index].preferred_rank == rank else 1,
                clusters[index].cluster_key.encode("utf-8"),
            ),
        )
        for index in ordered_options:
            next_current = dict(current)
            next_current[index] = rank
            if selected_requirements is not None:
                selected_requirements.setdefault(index, _feasibility_requirement_id(requirement))
            next_counts = counts.copy()
            next_counts[rank] += clusters[index].size
            result = search(next_current, next_counts)
            if result is not None:
                return result
        return None

    result = search(assignments, used)
    if result is None:
        raise ProductionFeasibilityBlocked(
            failures[-1] if failures else "coverage anchors have no exact-capacity witness"
        )
    return result


def _feasibility_requirement_id(
    requirement: tuple[int, str, CoverageRow | None, str | None, object | None, int],
) -> str:
    rank, kind, row, family, feature, _demand = requirement
    split = PROSPECTIVE_SPLIT_COUNTS[rank][0].value
    if kind == "cell":
        assert row is not None and family is not None
        return f"CELL:{row.capability_id}:{family}:{split}"
    if kind == "c18":
        assert family is not None
        return f"C18_REFUSAL:{family}:{split}"
    if kind in {"tag", "error"}:
        assert row is not None
        prefix = "ROW_TAG" if kind == "tag" else "ROW_ERROR"
        value = str(getattr(feature, "value", feature))
        return f"{prefix}:{row.capability_id}:{value}:{split}"
    if kind == "critical":
        return f"CRITICAL:{getattr(feature, 'value', feature)}:{split}"
    return f"ANSWERABLE:{split}"


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


def validate_production_legacy_feasibility(
    commitments: tuple[ProductionCandidateCommitmentV1, ...],
    *,
    exact_shingle_colocation_pairs: tuple[tuple[str, str], ...] = (),
    diagnostic_anchor_requirements: dict[int, str] | None = None,
    diagnostic_component_ranks: dict[str, int] | None = None,
) -> ProductionFeasibilityReceiptV1:
    """Run the frozen V1 greedy-anchor/DP comparator for diagnostics only."""

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
    candidate_id_set = set(candidate_ids)
    if not isinstance(exact_shingle_colocation_pairs, tuple) or any(
        not isinstance(pair, tuple)
        or len(pair) != 2
        or any(not isinstance(candidate_id, str) for candidate_id in pair)
        for pair in exact_shingle_colocation_pairs
    ):
        raise ProductionFeasibilityBlocked("exact-shingle co-location constraints are malformed")
    if any(
        left == right
        or left.encode("utf-8") >= right.encode("utf-8")
        or left not in candidate_id_set
        or right not in candidate_id_set
        for left, right in exact_shingle_colocation_pairs
    ) or exact_shingle_colocation_pairs != tuple(
        sorted(
            set(exact_shingle_colocation_pairs),
            key=lambda pair: (pair[0].encode("utf-8"), pair[1].encode("utf-8")),
        )
    ):
        raise ProductionFeasibilityBlocked(
            "exact-shingle co-location constraints are not canonical"
        )
    for commitment in commitments:
        _validate_feasibility_item(commitment.item)
    validate_production_isolation(commitments)
    clusters = _feasibility_clusters(
        commitments,
        exact_shingle_colocation_pairs=exact_shingle_colocation_pairs,
    )
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
    anchors = _anchor_feasibility_coverage(
        clusters,
        selected_requirements=diagnostic_anchor_requirements,
    )
    ranks = _fill_feasibility_counts(clusters, anchors)
    if diagnostic_component_ranks is not None:
        diagnostic_component_ranks.update(
            (cluster.cluster_key, rank) for cluster, rank in zip(clusters, ranks, strict=True)
        )

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
        if rank in (1, 2):
            for error in CRITICAL_ERROR_CLASSES:
                eligible_clusters = sum(
                    any(
                        error in item.reachable_error_classes
                        and _feasibility_row_eligible(item, _row_by_capability(item.capability_id))
                        for item in cluster.items
                    )
                    for cluster in assigned_clusters
                )
                if eligible_clusters < 2:
                    raise ProductionFeasibilityBlocked(
                        "protected split requires two independent clusters for every critical error"
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
        exact_shingle_colocation_pair_count=len(exact_shingle_colocation_pairs),
        exact_shingle_colocation_digest=canonical_hash(exact_shingle_colocation_pairs),
        feasibility_witness_digest=witness_digest,
        receipt_digest="sha256:" + "0" * 64,
    )
    return bind_production_feasibility_receipt(provisional)


def validate_production_hard_feasibility(
    commitments: tuple[ProductionCandidateCommitmentV1, ...],
    *,
    exact_shingle_colocation_pairs: tuple[tuple[str, str], ...] = (),
) -> ProductionFeasibilityReceiptV1:
    """Compatibility name for the legacy V1 diagnostic allocator."""

    return validate_production_legacy_feasibility(
        commitments,
        exact_shingle_colocation_pairs=exact_shingle_colocation_pairs,
    )


@dataclass(frozen=True, slots=True)
class _ExactConstraint:
    group_id: str
    terms: tuple[tuple[int, int, int], ...] = ()
    lower: int | None = None
    upper: int | None = None
    equalities: tuple[tuple[int, int], ...] = ()


@dataclass(frozen=True, slots=True)
class _ExactFeasibilityResult:
    receipt: ProductionExactFeasibilityReceiptV2
    private_diagnostic: dict[str, object]


def _split_lock_ranks(cluster: _FeasibilityCluster) -> tuple[int, ...]:
    split_order = tuple(split for split, _count in PROSPECTIVE_SPLIT_COUNTS)
    locks = {
        parse_production_seed_namespace(item.seed_namespace).split_name
        for item in cluster.items
        if item.origin_class is CaseOrigin.DETERMINISTIC_SYNTHETIC
        and item.seed_namespace is not None
    }
    return tuple(rank for rank, split in enumerate(split_order) if split in locks)


def _exact_requirement_constraints(
    base_components: tuple[_FeasibilityCluster, ...],
    independent_components: tuple[_FeasibilityCluster, ...],
) -> tuple[_ExactConstraint, ...]:
    constraints: list[_ExactConstraint] = []

    def at_least_one(group_id: str, indices: tuple[int, ...], rank: int, demand: int = 1) -> None:
        constraints.append(
            _ExactConstraint(
                group_id=group_id,
                terms=tuple((index, rank, 1) for index in indices),
                lower=demand,
            )
        )

    for rank, (split, target) in enumerate(PROSPECTIVE_SPLIT_COUNTS):
        constraints.append(
            _ExactConstraint(
                group_id=f"COUNT:{split.value}={target}",
                terms=tuple(
                    (index, rank, component.size) for index, component in enumerate(base_components)
                ),
                lower=target,
                upper=target,
            )
        )
        at_least_one(
            f"ANSWERABLE:{split.value}",
            tuple(
                index
                for index, component in enumerate(base_components)
                if any(
                    item.refusal_decision is not RefusalDecision.REQUIRED
                    and item.expected_answer_kind is not ExpectedAnswerKind.REFUSAL
                    for item in component.items
                )
            ),
            rank,
        )
        for row in COVERAGE_MATRIX:
            for family in row.benchmark_families:
                at_least_one(
                    f"CELL:{row.capability_id}:{family}:{split.value}",
                    tuple(
                        index
                        for index, component in enumerate(base_components)
                        if _cluster_has_cell_obligation(component, row, family)
                    ),
                    rank,
                )
            for tag in row.adversarial_tags:
                at_least_one(
                    f"ROW_TAG:{row.capability_id}:{tag}:{split.value}",
                    tuple(
                        index
                        for index, component in enumerate(base_components)
                        if any(
                            _feasibility_row_eligible(item, row) and tag in item.adversarial_tags
                            for item in component.items
                        )
                    ),
                    rank,
                )
            for error in row.error_classes:
                at_least_one(
                    f"ROW_ERROR:{row.capability_id}:{error.value}:{split.value}",
                    tuple(
                        index
                        for index, component in enumerate(base_components)
                        if any(
                            _feasibility_row_eligible(item, row)
                            and error in item.reachable_error_classes
                            for item in component.items
                        )
                    ),
                    rank,
                )
        for family in _row_by_capability("C18").benchmark_families:
            at_least_one(
                f"C18_REFUSAL:{family}:{split.value}",
                tuple(
                    index
                    for index, component in enumerate(base_components)
                    if _cluster_has_c18_refusal(component, family)
                ),
                rank,
            )

    base_index_by_candidate = {
        item.candidate_id: index
        for index, component in enumerate(base_components)
        for item in component.items
    }
    split_order = tuple(split for split, _count in PROSPECTIVE_SPLIT_COUNTS)
    for component_index, component in enumerate(base_components):
        locks = _split_lock_ranks(component)
        if locks:
            constraints.append(
                _ExactConstraint(
                    group_id=f"SYNTHETIC_LOCK:{component.cluster_key}",
                    terms=tuple((component_index, rank, 1) for rank in locks),
                    lower=len(locks),
                    upper=len(locks),
                )
            )

    for rank in range(3):
        for error in CRITICAL_ERROR_CLASSES:
            qualifying: list[int] = []
            for independent_component in independent_components:
                base_indices = tuple(
                    sorted(
                        {
                            base_index_by_candidate[item.candidate_id]
                            for item in independent_component.items
                        }
                    )
                )
                if any(
                    _feasibility_row_eligible(item, _row_by_capability(item.capability_id))
                    and error in item.reachable_error_classes
                    for item in independent_component.items
                ):
                    # Co-location equalities make every member share this split.
                    qualifying.append(base_indices[0])
            if rank in (1, 2):
                at_least_one(
                    f"CRITICAL:{error.value}:{split_order[rank].value}",
                    tuple(qualifying),
                    rank,
                    demand=2,
                )

    return tuple(sorted(constraints, key=lambda item: item.group_id.encode("utf-8")))


def _exact_colocation_constraints(
    base_components: tuple[_FeasibilityCluster, ...],
    pairs: tuple[tuple[str, str], ...],
) -> tuple[_ExactConstraint, ...]:
    index_by_candidate = {
        item.candidate_id: index
        for index, component in enumerate(base_components)
        for item in component.items
    }
    paired_components: dict[tuple[int, int], set[tuple[int, int]]] = defaultdict(set)
    for left_id, right_id in pairs:
        left, right = index_by_candidate[left_id], index_by_candidate[right_id]
        if left != right:
            paired_components[(min(left, right), max(left, right))].add((left, right))
    return tuple(
        _ExactConstraint(
            group_id=(
                f"COLOCATION:{base_components[left].cluster_key}:"
                f"{base_components[right].cluster_key}"
            ),
            equalities=tuple(sorted(edges)),
        )
        for (left, right), edges in sorted(
            paired_components.items(),
            key=lambda item: (
                base_components[item[0][0]].cluster_key,
                base_components[item[0][1]].cluster_key,
            ),
        )
    )


def _exact_colocation_group_ids(
    base_components: tuple[_FeasibilityCluster, ...],
    pairs: tuple[tuple[str, str], ...],
) -> tuple[str, ...]:
    return tuple(
        constraint.group_id for constraint in _exact_colocation_constraints(base_components, pairs)
    )


def _exact_model_digest(
    commitments_digest: str,
    components: tuple[_FeasibilityCluster, ...],
    constraints: tuple[_ExactConstraint, ...],
    *,
    edge_digest: str,
) -> str:
    return canonical_hash(
        {
            "algorithm_id": PRODUCTION_EXACT_FEASIBILITY_ALGORITHM,
            "commitments_digest": commitments_digest,
            "component_inventory": tuple((item.cluster_key, item.size) for item in components),
            "constraints": tuple(
                (item.group_id, item.terms, item.lower, item.upper, item.equalities)
                for item in constraints
            ),
            "co_location_edge_digest": edge_digest,
            "co_location_edge_reason": "RETAINED_EXACT_SHINGLE",
            "solver_config_digest": canonical_hash(PRODUCTION_EXACT_SOLVER_CONFIG),
            "solver_family": PRODUCTION_EXACT_SOLVER_FAMILY,
            "solver_version": PRODUCTION_EXACT_SOLVER_VERSION,
        }
    )


def _exact_completion_status(
    component_count: int,
    constraints: tuple[_ExactConstraint, ...],
    *,
    active_group_ids: frozenset[str] | None = None,
    fixed: dict[int, int] | None = None,
    hint: tuple[int, ...] | None = None,
    solved_ranks: list[int] | None = None,
    max_time_in_seconds: float | None = None,
    num_search_workers: int | None = None,
    random_seed: int | None = None,
    cp_model_presolve: bool | None = None,
    randomize_search: bool | None = None,
    log_search_progress: bool = False,
    solve_label: str = "EXACT_COMPLETION",
    telemetry: dict[str, object] | None = None,
    solve_log: list[str] | None = None,
    strengthen_cell_groups: frozenset[str] = frozenset(),
    symmetry_classes: tuple[tuple[int, ...], ...] = (),
    default_search: bool = False,
) -> str:
    try:
        from importlib.metadata import version

        from ortools.sat.python import cp_model
    except ImportError as exc:
        raise ProductionFeasibilityBlocked(
            "exact production feasibility requires the pinned OR-Tools benchmark dependency"
        ) from exc
    if not hasattr(cp_model, "CpModel") or not hasattr(cp_model, "CpSolver"):
        raise ProductionFeasibilityBlocked("OR-Tools CP-SAT API is unavailable")
    if version("ortools") != PRODUCTION_EXACT_SOLVER_VERSION:
        raise RuntimeError(
            f"exact production feasibility requires OR-Tools {PRODUCTION_EXACT_SOLVER_VERSION}"
        )

    model, variables = _build_exact_cp_model(
        component_count,
        constraints,
        active_group_ids=active_group_ids,
        fixed=fixed,
        hint=hint,
        strengthen_cell_groups=strengthen_cell_groups,
        symmetry_classes=symmetry_classes,
    )
    status_name, solver, details, log_text = _solve_exact_cp_model(
        model,
        max_time_in_seconds=max_time_in_seconds,
        num_search_workers=num_search_workers,
        random_seed=random_seed,
        cp_model_presolve=cp_model_presolve,
        randomize_search=randomize_search,
        log_search_progress=log_search_progress,
        solve_label=solve_label,
        constraints=constraints,
        active_group_ids=active_group_ids,
        fixed=fixed,
        strengthen_cell_groups=strengthen_cell_groups,
        symmetry_classes=symmetry_classes,
        default_search=default_search,
    )
    if telemetry is not None:
        telemetry.update(details)
    if solve_log is not None:
        solve_log.append(log_text)
    if status_name in {"FEASIBLE", "OPTIMAL"}:
        if solved_ranks is not None:
            solved_ranks.extend(
                next(rank for rank in range(3) if solver.value(variables[index][rank]))
                for index in range(component_count)
            )
        return "FEASIBLE"
    if status_name == "INFEASIBLE":
        return "INFEASIBLE"
    if status_name == "UNKNOWN":
        return "UNKNOWN"
    raise RuntimeError(f"CP-SAT returned unexpected status {status_name}")


def _validate_exact_rank_assignment(
    component_count: int,
    constraints: tuple[_ExactConstraint, ...],
    ranks: list[int],
) -> None:
    if len(ranks) != component_count or any(rank not in range(3) for rank in ranks):
        raise RuntimeError("CP-SAT feasible result has an incomplete split assignment")
    for constraint in constraints:
        if constraint.equalities:
            if any(ranks[left] != ranks[right] for left, right in constraint.equalities):
                raise RuntimeError("CP-SAT split assignment violates an exact equality")
            continue
        value = sum(
            coefficient for index, rank, coefficient in constraint.terms if ranks[index] == rank
        )
        if (constraint.lower is not None and value < constraint.lower) or (
            constraint.upper is not None and value > constraint.upper
        ):
            raise RuntimeError("CP-SAT split assignment violates an exact bound")


def _build_exact_cp_model(
    component_count: int,
    constraints: tuple[_ExactConstraint, ...],
    *,
    active_group_ids: frozenset[str] | None = None,
    fixed: dict[int, int] | None = None,
    hint: tuple[int, ...] | None = None,
    strengthen_cell_groups: frozenset[str] = frozenset(),
    symmetry_classes: tuple[tuple[int, ...], ...] = (),
) -> tuple[Any, tuple[tuple[Any, ...], ...]]:
    from ortools.sat.python import cp_model

    model = cp_model.CpModel()
    variables = tuple(
        tuple(model.new_bool_var(f"x_{index}_{rank}") for rank in range(3))
        for index in range(component_count)
    )
    for row in variables:
        model.add_exactly_one(row)
    for constraint in constraints:
        if active_group_ids is not None and constraint.group_id not in active_group_ids:
            continue
        if constraint.equalities:
            for left, right in constraint.equalities:
                for rank in range(3):
                    model.add(variables[left][rank] == variables[right][rank])
            continue
        if not constraint.terms:
            model.add_bool_or([])
            continue
        expression = sum(
            coefficient * variables[index][rank] for index, rank, coefficient in constraint.terms
        )
        if constraint.group_id in strengthen_cell_groups:
            if not constraint.group_id.startswith("CELL:") or constraint.lower != 1:
                raise ValueError("exact-three strengthening only supports cell coverage rows")
            model.add(expression == 1)
        elif constraint.lower is not None and constraint.upper == constraint.lower:
            model.add(expression == constraint.lower)
        else:
            if constraint.lower is not None:
                model.add(expression >= constraint.lower)
            if constraint.upper is not None:
                model.add(expression <= constraint.upper)
    for index, rank in (fixed or {}).items():
        if not 0 <= index < component_count or rank not in range(3):
            raise ValueError("fixed exact split assignment is out of range")
        model.add(variables[index][rank] == 1)
    if hint is not None:
        if len(hint) != component_count or any(rank not in range(3) for rank in hint):
            raise ValueError("exact solver hint is not a complete split assignment")
        hinted = list(hint)
        for index, rank in (fixed or {}).items():
            hinted[index] = rank
        for index, rank in enumerate(hinted):
            for split_rank in range(3):
                model.add_hint(variables[index][split_rank], int(split_rank == rank))
    for component_class in symmetry_classes:
        if len(component_class) < 2 or tuple(sorted(set(component_class))) != component_class:
            raise ValueError("symmetry classes must be ordered unique component indices")
        if component_class[-1] >= component_count:
            raise ValueError("symmetry class component index is out of range")
        for left, right in itertools.pairwise(component_class):
            left_rank = sum(rank * variables[left][rank] for rank in range(3))
            right_rank = sum(rank * variables[right][rank] for rank in range(3))
            model.add(left_rank <= right_rank)
    return model, variables


def _exact_cp_model_proto(model: Any) -> bytes:
    with tempfile.TemporaryDirectory(prefix="dynamislm-cpsat-") as temp_dir:
        path = Path(temp_dir) / "model.pb"
        if not model.export_to_file(str(path)):
            raise OSError("OR-Tools failed to export the canonical CP-SAT model proto")
        return path.read_bytes()


def _solve_exact_cp_model(
    model: Any,
    *,
    max_time_in_seconds: float | None = None,
    num_search_workers: int | None = None,
    random_seed: int | None = None,
    cp_model_presolve: bool | None = None,
    randomize_search: bool | None = None,
    log_search_progress: bool = False,
    solve_label: str,
    constraints: tuple[_ExactConstraint, ...],
    active_group_ids: frozenset[str] | None = None,
    fixed: dict[int, int] | None = None,
    strengthen_cell_groups: frozenset[str] = frozenset(),
    symmetry_classes: tuple[tuple[int, ...], ...] = (),
    default_search: bool = False,
) -> tuple[str, Any, dict[str, object], str]:
    from importlib.metadata import version

    from ortools.sat.python import cp_model

    if version("ortools") != PRODUCTION_EXACT_SOLVER_VERSION:
        raise RuntimeError(
            f"exact production feasibility requires OR-Tools {PRODUCTION_EXACT_SOLVER_VERSION}"
        )
    configured: dict[str, object] = {}
    if not default_search:
        configured.update(PRODUCTION_EXACT_SOLVER_CONFIG)
    parameter_values: tuple[tuple[str, object | None], ...] = (
        ("max_time_in_seconds", max_time_in_seconds),
        ("num_search_workers", num_search_workers),
        ("random_seed", random_seed),
        ("cp_model_presolve", cp_model_presolve),
        ("randomize_search", randomize_search),
    )
    for name, value in parameter_values:
        if value is not None:
            configured[name] = value
    configured["log_search_progress"] = log_search_progress
    solver: Any = cp_model.CpSolver()
    for name, value in configured.items():
        setattr(solver.parameters, name, value)
    log_chunks: list[str] = []
    if log_search_progress:
        solver.parameters.log_to_stdout = False
        solver.log_callback = log_chunks.append
    raw_status = solver.solve(model)
    status_name = solver.status_name(raw_status)
    log_text = "".join(log_chunks)
    proto_bytes = _exact_cp_model_proto(model)
    active_constraints = tuple(
        item
        for item in constraints
        if active_group_ids is None or item.group_id in active_group_ids
    )
    constraint_set_digest = canonical_hash(
        {
            "component_count": len(model.proto.variables) // 3,
            "constraints": tuple(
                (item.group_id, item.terms, item.lower, item.upper, item.equalities)
                for item in active_constraints
            ),
            "fixed": tuple(sorted((fixed or {}).items())),
            "strengthen_cell_groups": tuple(sorted(strengthen_cell_groups)),
            "symmetry_classes": symmetry_classes,
        }
    )
    response = solver.response_proto
    log_lines = log_text.splitlines()
    search_start = next(
        (index for index, line in enumerate(log_lines) if "Starting search at" in line),
        len(log_lines),
    )
    presolve_log = "\n".join(log_lines[:search_start])
    search_log = "\n".join(log_lines[search_start:])
    symmetry_lines = tuple(
        line
        for line in log_lines
        if "[Symmetry]" in line or "orbit" in line.lower() or "orbitope" in line.lower()
    )
    presolve_counts = next(
        (
            (int(match.group(1)), int(match.group(2)))
            for line in log_lines
            if (match := re.search(r"Presolved .*?:\s*(\d+) variables,\s*(\d+) constraints", line))
        ),
        (None, None),
    )
    presolved_start = next(
        (
            index + 1
            for index, line in reversed(tuple(enumerate(log_lines[:search_start])))
            if "Presolved satisfaction model" in line
        ),
        0,
    )
    presolved_section = log_lines[presolved_start:search_start]
    presolved_variables = next(
        (
            int(match.group(1))
            for line in presolved_section
            if (match := re.match(r"#Variables:\s*(\d+)", line))
        ),
        presolve_counts[0],
    )
    presolved_constraints = sum(
        int(match.group(1))
        for line in presolved_section
        if (match := re.match(r"#k[^:]+:\s*(\d+)", line))
    )
    if not presolved_constraints and presolve_counts[1] is not None:
        presolved_constraints = presolve_counts[1]
    details: dict[str, object] = {
        "schema": "RES-224-PRIVATE-SOLVER-TELEMETRY@1.0.0",
        "solve_label": solve_label,
        "status": status_name,
        "model_proto_digest": "sha256:" + hashlib.sha256(proto_bytes).hexdigest(),
        "constraint_set_digest": constraint_set_digest,
        "solver_config_digest": canonical_hash(
            {
                "ortools_version": PRODUCTION_EXACT_SOLVER_VERSION,
                "default_search": default_search,
                "explicit_parameters": configured,
                "parameters_text": str(solver.parameters),
            }
        ),
        "configured": {**configured, "default_search": default_search},
        "presolved_variable_count": presolved_variables,
        "presolved_constraint_count": presolved_constraints,
        "num_booleans": getattr(response, "num_booleans", None),
        "num_conflicts": getattr(response, "num_conflicts", None),
        "num_branches": getattr(response, "num_branches", None),
        "num_binary_propagations": getattr(response, "num_binary_propagations", None),
        "num_integer_propagations": getattr(response, "num_integer_propagations", None),
        "num_restarts": getattr(response, "num_restarts", None),
        "num_lp_iterations": getattr(response, "num_lp_iterations", None),
        "wall_time": getattr(response, "wall_time", None),
        "user_time": getattr(response, "user_time", None),
        "deterministic_time": getattr(response, "deterministic_time", None),
        "solution_info": getattr(response, "solution_info", ""),
        "presolve_log_digest": "sha256:" + hashlib.sha256(presolve_log.encode("utf-8")).hexdigest(),
        "search_log_digest": "sha256:" + hashlib.sha256(search_log.encode("utf-8")).hexdigest(),
        "solver_symmetry_log_digest": "sha256:"
        + hashlib.sha256("\n".join(symmetry_lines).encode("utf-8")).hexdigest(),
        "solver_symmetry_log_lines": symmetry_lines,
        "solve_log_digest": "sha256:" + hashlib.sha256(log_text.encode("utf-8")).hexdigest(),
    }
    return status_name, solver, details, log_text


def _reduce_exact_conflict(
    component_count: int,
    constraints: tuple[_ExactConstraint, ...],
    *,
    structural_group_ids: tuple[str, ...] = (),
) -> tuple[str, ...]:
    remaining = {item.group_id for item in constraints}
    changed = True
    while changed:
        changed = False
        for group_id in sorted(remaining, key=str.encode):
            trial = remaining - {group_id}
            status = _exact_completion_status(
                component_count,
                constraints,
                active_group_ids=frozenset(trial),
            )
            if status == "INFEASIBLE":
                remaining = trial
                changed = True
    report = tuple(sorted(remaining, key=str.encode))
    if (
        _exact_completion_status(
            component_count,
            constraints,
            active_group_ids=frozenset(report),
        )
        != "INFEASIBLE"
    ):
        raise RuntimeError("reduced exact-feasibility conflict did not recheck as infeasible")
    return tuple(sorted((*report, *structural_group_ids), key=str.encode))


def _canonical_split_ranks(
    component_count: int,
    constraints: tuple[_ExactConstraint, ...],
    initial_hint: tuple[int, ...],
    *,
    solve_trace: list[dict[str, object]] | None = None,
    solve_log_sink: Callable[[str, str], None] | None = None,
    log_search_progress: bool = False,
    deadline: float | None = None,
) -> tuple[str, tuple[int, ...] | None]:
    fixed: dict[int, int] = {}
    selected: list[int] = []
    hint = initial_hint
    for index in range(component_count):
        for rank in range(3):
            trial = {**fixed, index: rank}
            solved_ranks: list[int] = []
            telemetry: dict[str, object] = {}
            solve_log: list[str] = []
            solve_label = f"CANONICAL_SELF_REDUCTION_{index:04d}_{rank}"
            max_time = None
            if deadline is not None:
                max_time = max(
                    0.001,
                    min(
                        PRODUCTION_EXACT_SOLVER_CONFIG["max_time_in_seconds"],
                        deadline - time.monotonic(),
                    ),
                )
            status = _exact_completion_status(
                component_count,
                constraints,
                fixed=trial,
                hint=hint,
                solved_ranks=solved_ranks,
                telemetry=telemetry,
                solve_log=solve_log,
                solve_label=solve_label,
                log_search_progress=log_search_progress,
                max_time_in_seconds=max_time,
            )
            if solve_trace is not None:
                solve_trace.append({**telemetry, "oracle_status": status})
            if solve_log_sink is not None and solve_log:
                solve_log_sink(solve_label, solve_log[0])
            if status == "UNKNOWN":
                return "BLOCKED", None
            if status == "FEASIBLE":
                fixed = trial
                selected.append(rank)
                hint = tuple(solved_ranks)
                break
        else:
            raise RuntimeError("canonical self-reduction lost a proven feasible completion")
    return "PASS", tuple(selected)


def _canonical_split_ranks_glucose(
    component_count: int,
    constraints: tuple[_ExactConstraint, ...],
    progress_callback: Callable[[int, int, str], None] | None = None,
    deadline: float | None = None,
) -> tuple[str, tuple[int, ...] | None, tuple[tuple[int, int, str], ...]]:
    from pysat.pb import EncType, PBEnc  # type: ignore[import-untyped]
    from pysat.solvers import Solver  # type: ignore[import-untyped]

    variables = tuple(
        tuple(3 * index + rank + 1 for rank in range(3)) for index in range(component_count)
    )
    clauses: list[list[int]] = []
    top_id = 3 * component_count
    for row in variables:
        clauses.append(list(row))
        clauses.extend([-left, -right] for left, right in itertools.combinations(row, 2))

    def add_bound(
        *, lower: int | None, upper: int | None, literals: list[int], weights: list[int]
    ) -> None:
        nonlocal top_id
        for encoder, bound in ((PBEnc.geq, lower), (PBEnc.leq, upper)):
            if bound is None:
                continue
            encoded = encoder(
                lits=literals,
                weights=weights,
                bound=bound,
                top_id=top_id,
                encoding=EncType.bdd,
            )
            clauses.extend(list(clause) for clause in encoded.clauses)
            top_id = max(top_id, encoded.nv)

    for constraint in constraints:
        if constraint.equalities:
            for left, right in constraint.equalities:
                for rank in range(3):
                    left_var, right_var = variables[left][rank], variables[right][rank]
                    clauses.extend(([-left_var, right_var], [left_var, -right_var]))
            continue
        if not constraint.terms:
            clauses.append([])
            continue
        literals = [variables[index][rank] for index, rank, _weight in constraint.terms]
        weights = [weight for _index, _rank, weight in constraint.terms]
        add_bound(
            lower=constraint.lower,
            upper=constraint.upper,
            literals=literals,
            weights=weights,
        )

    trace: list[tuple[int, int, str]] = []
    selected_literals: list[int] = []

    def solve_limited(solver: Any, assumptions: list[int]) -> bool | None:
        timeout = None if deadline is None else deadline - time.monotonic()
        if timeout is not None and timeout <= 0:
            return None
        timer = None if timeout is None else threading.Timer(timeout, solver.interrupt)
        if timer is not None:
            timer.daemon = True
            timer.start()
        try:
            if timeout is None:
                return bool(solver.solve(assumptions=assumptions))
            result = solver.solve_limited(assumptions=assumptions, expect_interrupt=True)
            return None if result is None else bool(result)
        finally:
            if timer is not None:
                timer.cancel()
                solver.clear_interrupt()

    selected_ranks: list[int] = []
    with Solver(name="g4", bootstrap_with=clauses) as solver:
        initial = solve_limited(solver, [])
        if initial is None:
            return "BLOCKED", None, ()
        if not initial:
            return "BLOCKED", None, ()
        for index, row in enumerate(variables):
            for rank, literal in enumerate(row):
                result = solve_limited(solver, [*selected_literals, literal])
                if result is None:
                    trace.append((index, rank, "UNKNOWN"))
                    if progress_callback is not None:
                        progress_callback(index, component_count, "UNKNOWN")
                    return "BLOCKED", None, tuple(trace)
                state = "FEASIBLE" if result else "INFEASIBLE"
                trace.append((index, rank, state))
                if result:
                    selected_literals.append(literal)
                    selected_ranks.append(rank)
                    if progress_callback is not None and (
                        (index + 1) % 25 == 0 or index + 1 == component_count
                    ):
                        progress_callback(index + 1, component_count, "FEASIBLE")
                    break
            else:
                if progress_callback is not None:
                    progress_callback(index + 1, component_count, "BLOCKED")
                return "BLOCKED", None, tuple(trace)
    return "PASS", tuple(selected_ranks), tuple(trace)


def _exact_aggregate_evidence(
    base_components: tuple[_FeasibilityCluster, ...],
    independent_components: tuple[_FeasibilityCluster, ...],
    base_ranks: tuple[int, ...],
) -> dict[str, tuple[tuple[SplitName, int], ...]]:
    targets = tuple(count for _split, count in PROSPECTIVE_SPLIT_COUNTS)
    actual_counts = [0, 0, 0]
    for component, rank in zip(base_components, base_ranks, strict=True):
        actual_counts[rank] += component.size
    if tuple(actual_counts) != targets:
        raise RuntimeError("CP-SAT canonical witness violates exact split counts")

    cells = [0, 0, 0]
    tags = [0, 0, 0]
    errors = [0, 0, 0]
    critical = [0, 0, 0]
    answerable = [0, 0, 0]
    c18 = [0, 0, 0]
    rank_by_candidate = {
        item.candidate_id: rank
        for component, rank in zip(base_components, base_ranks, strict=True)
        for item in component.items
    }
    for rank in range(3):
        assigned = tuple(
            component
            for index, component in enumerate(base_components)
            if base_ranks[index] == rank
        )
        assigned_items = tuple(item for component in assigned for item in component.items)
        answerable[rank] = sum(
            item.refusal_decision is not RefusalDecision.REQUIRED
            and item.expected_answer_kind is not ExpectedAnswerKind.REFUSAL
            for item in assigned_items
        )
        for row in COVERAGE_MATRIX:
            for family in row.benchmark_families:
                cells[rank] += any(
                    _cluster_has_cell_obligation(component, row, family) for component in assigned
                )
            eligible = tuple(
                item for item in assigned_items if _feasibility_row_eligible(item, row)
            )
            tags[rank] += len(
                {tag for item in eligible for tag in item.adversarial_tags}.intersection(
                    row.adversarial_tags
                )
            )
            errors[rank] += len(
                {error for item in eligible for error in item.reachable_error_classes}.intersection(
                    row.error_classes
                )
            )
        for error in CRITICAL_ERROR_CLASSES:
            independent_count = sum(
                any(
                    rank_by_candidate[item.candidate_id] == rank
                    and _feasibility_row_eligible(item, _row_by_capability(item.capability_id))
                    and error in item.reachable_error_classes
                    for item in component.items
                )
                for component in independent_components
            )
            if rank in (1, 2) and independent_count < 2:
                raise RuntimeError("canonical witness misses critical-error component redundancy")
            critical[rank] += independent_count > 0
        c18[rank] = sum(
            any(_cluster_has_c18_refusal(component, family) for component in assigned)
            for family in _row_by_capability("C18").benchmark_families
        )

    def split_pairs(
        values: list[int], ranks: tuple[int, ...] = (0, 1, 2)
    ) -> tuple[tuple[SplitName, int], ...]:
        return tuple((PROSPECTIVE_SPLIT_COUNTS[rank][0], values[rank]) for rank in ranks)

    expected_tags = sum(len(row.adversarial_tags) for row in COVERAGE_MATRIX)
    expected_errors = sum(len(row.error_classes) for row in COVERAGE_MATRIX)
    if (
        any(count != 87 for count in cells)
        or any(count != expected_tags for count in tags)
        or any(count != expected_errors for count in errors)
        or any(count < 1 for count in answerable)
        or any(count != 14 for count in c18)
    ):
        raise RuntimeError("CP-SAT canonical witness misses a frozen coverage obligation")
    return {
        "hard_cell_count_by_split": split_pairs(cells),
        "adversarial_tag_count_by_split": split_pairs(tags),
        "reachable_error_count_by_split": split_pairs(errors),
        "protected_critical_error_count_by_split": split_pairs(critical, (1, 2)),
        "answerable_case_count_by_split": split_pairs(answerable),
        "c18_refusal_cell_count_by_split": split_pairs(c18),
    }


def validate_production_exact_feasibility(
    commitments: tuple[ProductionCandidateCommitmentV1, ...],
    *,
    exact_shingle_colocation_pairs: tuple[tuple[str, str], ...],
    defer_colocation_conflict_reduction: bool = False,
    use_legacy_hint: bool = True,
    hint_search_seconds: float | None = None,
    run_c03_f04_diagnostic: bool = True,
    candidate_rank_hint: dict[str, int] | None = None,
    canonical_self_reduction_backend: str = "CP-SAT",
    run_canonical_self_reduction: bool = True,
    canonical_progress_callback: Callable[[int, int, str], None] | None = None,
    oracle_time_limit_seconds: float | None = None,
) -> _ExactFeasibilityResult:
    """Check BASE/COLOCATION feasibility and optionally canonicalize the witness."""

    if len(commitments) != FINAL_TARGET_CASES:
        raise ProductionFeasibilityBlocked("exact feasibility requires exactly 434 commitments")
    if canonical_self_reduction_backend not in {"CP-SAT", "GLUCOSE"}:
        raise ValueError("canonical self-reduction backend is invalid")
    if oracle_time_limit_seconds is not None and oracle_time_limit_seconds <= 0:
        raise ValueError("exact feasibility oracle time limit must be positive")
    oracle_started = time.monotonic()
    oracle_deadline = (
        None if oracle_time_limit_seconds is None else oracle_started + oracle_time_limit_seconds
    )

    def solver_time_budget(requested: float | None = None) -> float | None:
        if oracle_deadline is None:
            return requested
        remaining = max(0.001, oracle_deadline - time.monotonic())
        configured = PRODUCTION_EXACT_SOLVER_CONFIG["max_time_in_seconds"]
        return min(remaining, configured if requested is None else requested)

    if any(not isinstance(item, ProductionCandidateCommitmentV1) for item in commitments):
        raise TypeError("exact feasibility input must contain production commitments")
    commitments = tuple(sorted(commitments, key=lambda item: item.candidate_id.encode("utf-8")))
    candidate_ids = tuple(item.candidate_id for item in commitments)
    if (
        len(set(candidate_ids)) != FINAL_TARGET_CASES
        or len({item.candidate_payload_hash for item in commitments}) != FINAL_TARGET_CASES
    ):
        raise ProductionFeasibilityBlocked("exact feasibility commitments are not unique")
    candidate_id_set = set(candidate_ids)
    if (
        not isinstance(exact_shingle_colocation_pairs, tuple)
        or any(
            not isinstance(pair, tuple)
            or len(pair) != 2
            or any(not isinstance(candidate_id, str) for candidate_id in pair)
            for pair in exact_shingle_colocation_pairs
        )
        or any(
            left == right
            or left.encode("utf-8") >= right.encode("utf-8")
            or left not in candidate_id_set
            or right not in candidate_id_set
            for left, right in exact_shingle_colocation_pairs
        )
        or exact_shingle_colocation_pairs
        != tuple(
            sorted(
                set(exact_shingle_colocation_pairs),
                key=lambda pair: (pair[0].encode("utf-8"), pair[1].encode("utf-8")),
            )
        )
    ):
        raise ProductionFeasibilityBlocked(
            "exact feasibility requires the 81 canonical retained co-location pairs"
        )
    if candidate_rank_hint is not None and (
        set(candidate_rank_hint) != candidate_id_set
        or any(rank not in range(3) for rank in candidate_rank_hint.values())
    ):
        raise ValueError("candidate-level exact-solver hint must cover all candidates and ranks")
    for commitment in commitments:
        _validate_feasibility_item(commitment.item)
    validate_production_isolation(
        commitments,
        defer_split_lock_conflicts=True,
        enforce_public_capacity=False,
    )
    base_components = _feasibility_clusters(
        commitments,
        allow_incompatible_locks=True,
    )
    colocation_components = _feasibility_clusters(
        commitments,
        exact_shingle_colocation_pairs=exact_shingle_colocation_pairs,
        allow_incompatible_locks=True,
    )
    base_index_by_candidate = {
        item.candidate_id: index
        for index, component in enumerate(base_components)
        for item in component.items
    }
    base_indices_by_colocation_component = tuple(
        tuple(sorted({base_index_by_candidate[item.candidate_id] for item in component.items}))
        for component in colocation_components
    )
    base_constraints = _exact_requirement_constraints(base_components, base_components)
    colocation_constraints = _exact_requirement_constraints(
        colocation_components,
        colocation_components,
    )
    commitments_digest = canonical_hash(commitments)
    edge_digest = canonical_hash(exact_shingle_colocation_pairs)
    base_inventory_digest = canonical_hash(
        tuple((component.cluster_key, component.size) for component in base_components)
    )
    colocation_inventory_digest = canonical_hash(
        tuple((component.cluster_key, component.size) for component in colocation_components)
    )
    base_model_digest = _exact_model_digest(
        commitments_digest,
        base_components,
        base_constraints,
        edge_digest=canonical_hash(()),
    )
    colocation_model_digest = _exact_model_digest(
        commitments_digest,
        colocation_components,
        colocation_constraints,
        edge_digest=edge_digest,
    )
    legacy_selected: dict[int, str] = {}
    legacy_ranks_by_key: dict[str, int] = {}
    legacy_failure: str | None = None
    if use_legacy_hint:
        try:
            validate_production_legacy_feasibility(
                commitments,
                diagnostic_anchor_requirements=legacy_selected,
                diagnostic_component_ranks=legacy_ranks_by_key,
            )
            legacy_status = "PASS"
        except ValueError as exc:
            legacy_status = "BLOCKED"
            legacy_failure = str(exc)
        legacy_hint = (
            tuple(legacy_ranks_by_key[component.cluster_key] for component in base_components)
            if legacy_status == "PASS" and len(legacy_ranks_by_key) == len(base_components)
            else None
        )
        colocation_legacy_ranks: dict[str, int] = {}
        try:
            validate_production_legacy_feasibility(
                commitments,
                exact_shingle_colocation_pairs=exact_shingle_colocation_pairs,
                diagnostic_component_ranks=colocation_legacy_ranks,
            )
            colocation_legacy_status = "PASS"
        except ValueError:
            colocation_legacy_status = "BLOCKED"
        if legacy_hint is None and colocation_legacy_status == "PASS":
            colocated_rank_by_candidate = {
                item.candidate_id: colocation_legacy_ranks[component.cluster_key]
                for component in colocation_components
                for item in component.items
            }
            legacy_hint = tuple(
                colocated_rank_by_candidate[component.items[0].candidate_id]
                for component in base_components
            )
    else:
        legacy_status = "BLOCKED"
        legacy_failure = (
            "legacy search omitted; deterministic component ranks are CP-SAT hints only"
        )
        colocation_legacy_status = "BLOCKED"
        legacy_hint = tuple(component.preferred_rank for component in base_components)
        colocation_legacy_ranks = {}
    colocation_hint = (
        tuple(colocation_legacy_ranks[component.cluster_key] for component in colocation_components)
        if use_legacy_hint
        and colocation_legacy_status == "PASS"
        and len(colocation_legacy_ranks) == len(colocation_components)
        else tuple(component.preferred_rank for component in colocation_components)
    )
    if candidate_rank_hint is not None:

        def component_rank_hint(
            components: tuple[_FeasibilityCluster, ...],
        ) -> tuple[int, ...]:
            ranks = tuple(
                {candidate_rank_hint[item.candidate_id] for item in component.items}
                for component in components
            )
            if any(len(component_ranks) != 1 for component_ranks in ranks):
                raise ValueError("candidate-level rank hint splits an exact isolation component")
            return tuple(next(iter(component_ranks)) for component_ranks in ranks)

        legacy_hint = component_rank_hint(base_components)
        colocation_hint = component_rank_hint(colocation_components)
        legacy_status = "BLOCKED"
        legacy_failure = (
            "legacy search omitted; candidate-level SAT rank assignment is a CP-SAT hint"
        )
        colocation_legacy_status = "BLOCKED"
    hint_generation_status = "NOT_RUN"
    hint_generation_model = "NOT_RUN"
    base_hint_status = "NOT_RUN"
    colocation_hint_status = "NOT_RUN"
    colocation_count_cell_status = "NOT_RUN"
    if hint_search_seconds is not None:
        if hint_search_seconds <= 0:
            raise ValueError("exact feasibility hint-search time must be positive")
        base_hint_ranks: list[int] = []
        base_hint_constraints = tuple(
            constraint for constraint in base_constraints if constraint.group_id.startswith("CELL:")
        )
        base_hint_status = _exact_completion_status(
            len(base_components),
            base_hint_constraints,
            hint=legacy_hint,
            solved_ranks=base_hint_ranks,
            max_time_in_seconds=solver_time_budget(hint_search_seconds),
        )
        if base_hint_status == "FEASIBLE":
            legacy_hint = tuple(base_hint_ranks)
            colocation_hint = tuple(
                max(
                    range(3),
                    key=lambda rank: (
                        sum(base_hint_ranks[index] == rank for index in indices),
                        -rank,
                    ),
                )
                for indices in base_indices_by_colocation_component
            )
        colocation_hint_ranks: list[int] = []
        colocation_hint_constraints = tuple(
            constraint
            for constraint in colocation_constraints
            if constraint.group_id.startswith("CELL:")
        )
        colocation_hint_status = _exact_completion_status(
            len(colocation_components),
            colocation_hint_constraints,
            hint=colocation_hint,
            solved_ranks=colocation_hint_ranks,
            max_time_in_seconds=solver_time_budget(hint_search_seconds),
        )
        if colocation_hint_status == "FEASIBLE":
            colocation_hint = tuple(colocation_hint_ranks)
            rank_by_candidate = {
                item.candidate_id: rank
                for component, rank in zip(
                    colocation_components,
                    colocation_hint_ranks,
                    strict=True,
                )
                for item in component.items
            }
            legacy_hint = tuple(
                rank_by_candidate[component.items[0].candidate_id] for component in base_components
            )
        colocation_count_cell_ranks: list[int] = []
        colocation_count_cell_constraints = tuple(
            constraint
            for constraint in colocation_constraints
            if constraint.group_id.startswith(("COUNT:", "CELL:", "SYNTHETIC_LOCK:"))
        )
        colocation_count_cell_status = _exact_completion_status(
            len(colocation_components),
            colocation_count_cell_constraints,
            hint=colocation_hint,
            solved_ranks=colocation_count_cell_ranks,
            max_time_in_seconds=solver_time_budget(hint_search_seconds),
        )
        if colocation_count_cell_status == "FEASIBLE":
            colocation_hint = tuple(colocation_count_cell_ranks)
            rank_by_candidate = {
                item.candidate_id: rank
                for component, rank in zip(
                    colocation_components,
                    colocation_count_cell_ranks,
                    strict=True,
                )
                for item in component.items
            }
            legacy_hint = tuple(
                rank_by_candidate[component.items[0].candidate_id] for component in base_components
            )
        colocation_count_ranks: list[int] = []
        colocation_count_constraints = tuple(
            constraint
            for constraint in colocation_constraints
            if constraint.group_id.startswith(("COUNT:", "SYNTHETIC_LOCK:"))
        )
        colocation_count_status = _exact_completion_status(
            len(colocation_components),
            colocation_count_constraints,
            hint=colocation_hint,
            solved_ranks=colocation_count_ranks,
            max_time_in_seconds=solver_time_budget(hint_search_seconds),
        )
        if colocation_count_status == "FEASIBLE":
            colocation_hint = tuple(colocation_count_ranks)
            rank_by_candidate = {
                item.candidate_id: rank
                for component, rank in zip(
                    colocation_components,
                    colocation_count_ranks,
                    strict=True,
                )
                for item in component.items
            }
            legacy_hint = tuple(
                rank_by_candidate[component.items[0].candidate_id] for component in base_components
            )
        colocation_noncritical_ranks: list[int] = []
        colocation_noncritical_constraints = tuple(
            constraint
            for constraint in colocation_constraints
            if not constraint.group_id.startswith("CRITICAL:")
        )
        colocation_noncritical_status = _exact_completion_status(
            len(colocation_components),
            colocation_noncritical_constraints,
            hint=colocation_hint,
            solved_ranks=colocation_noncritical_ranks,
            max_time_in_seconds=solver_time_budget(hint_search_seconds),
        )
        if colocation_noncritical_status == "FEASIBLE":
            colocation_hint = tuple(colocation_noncritical_ranks)
            rank_by_candidate = {
                item.candidate_id: rank
                for component, rank in zip(
                    colocation_components,
                    colocation_noncritical_ranks,
                    strict=True,
                )
                for item in component.items
            }
            legacy_hint = tuple(
                rank_by_candidate[component.items[0].candidate_id] for component in base_components
            )
        hint_generation_model = "PROGRESSIVE_COLOCATION_RELAXATIONS_HINT_ONLY"
        hint_generation_status = (
            f"BASE_CELLS={base_hint_status};COLOCATION_CELLS={colocation_hint_status};"
            f"COLOCATION_COUNTS_CELLS={colocation_count_cell_status};"
            f"COLOCATION_COUNTS={colocation_count_status};"
            f"COLOCATION_NONCRITICAL={colocation_noncritical_status}"
        )
    base_solution: list[int] = []
    base_status = _exact_completion_status(
        len(base_components),
        base_constraints,
        hint=legacy_hint,
        solved_ranks=base_solution,
        max_time_in_seconds=solver_time_budget(),
    )
    if base_status == "FEASIBLE" and (
        (
            hint_search_seconds is not None
            and colocation_hint_status != "FEASIBLE"
            and colocation_count_cell_status != "FEASIBLE"
        )
        or (hint_search_seconds is None and colocation_legacy_status != "PASS")
    ):
        co_location_source = tuple(base_solution)
        hinted_ranks: list[int] = []
        for indices in base_indices_by_colocation_component:
            counts = Counter(co_location_source[index] for index in indices)
            rank = max(
                range(3), key=lambda candidate_rank: (counts[candidate_rank], -candidate_rank)
            )
            hinted_ranks.append(rank)
        colocation_hint = tuple(hinted_ranks)
    colocation_solution: list[int] = []
    colocation_status = _exact_completion_status(
        len(colocation_components),
        colocation_constraints,
        hint=colocation_hint,
        solved_ranks=colocation_solution,
        max_time_in_seconds=solver_time_budget(),
    )
    if base_status == "INFEASIBLE" and colocation_status == "FEASIBLE":
        raise RuntimeError("co-location exact model is feasible while its base model is infeasible")
    if base_status == "FEASIBLE":
        _validate_exact_rank_assignment(len(base_components), base_constraints, base_solution)
    if colocation_status == "FEASIBLE":
        _validate_exact_rank_assignment(
            len(colocation_components), colocation_constraints, colocation_solution
        )

    c03_row = _row_by_capability("C03")
    split_order = tuple(split for split, _count in PROSPECTIVE_SPLIT_COUNTS)
    c03_f04_trace: list[dict[str, object]] = []
    c03_public_feasible = 0
    c03_unknown = False
    for index, component in enumerate(base_components) if run_c03_f04_diagnostic else ():
        if not _cluster_has_cell_obligation(component, c03_row, "F04"):
            continue
        forced_status = _exact_completion_status(
            len(base_components),
            base_constraints,
            fixed={index: 0},
            hint=tuple(base_solution) if base_status == "FEASIBLE" else legacy_hint,
            max_time_in_seconds=solver_time_budget(),
        )
        c03_public_feasible += forced_status == "FEASIBLE"
        c03_unknown |= forced_status == "UNKNOWN"
        c03_f04_trace.append(
            {
                "component_key": component.cluster_key,
                "scientific_isolation_cluster_ids": tuple(
                    sorted({item.isolation_cluster_id for item in component.items})
                ),
                "candidate_ids": tuple(item.candidate_id for item in component.items),
                "component_size": component.size,
                "expert_author_batch_ids": tuple(
                    sorted(
                        {
                            item.expert_author_batch_id
                            for item in component.items
                            if item.expert_author_batch_id
                        }
                    )
                ),
                "protocol_template_ids": tuple(
                    sorted(
                        {entry for item in component.items for entry in item.protocol_template_ids}
                    )
                ),
                "partner_capability_family_cells": tuple(
                    sorted(
                        {
                            (item.capability_id, item.benchmark_family)
                            for item in component.items
                            if (item.capability_id, item.benchmark_family) != ("C03", "F04")
                        }
                    )
                ),
                "mutation_descendants": tuple(
                    item.candidate_id
                    for item in component.items
                    if item.parent_candidate_id is not None
                ),
                "mutation_lineage_ids": tuple(
                    sorted(
                        {
                            item.mutation_lineage_id
                            for item in component.items
                            if item.mutation_lineage_id
                        }
                    )
                ),
                "split_locks": tuple(
                    split_order[rank].value for rank in _split_lock_ranks(component)
                ),
                "legacy_preferred_rank": component.preferred_rank,
                "legacy_greedy_assigned": index in legacy_selected,
                "legacy_assigned_for": legacy_selected.get(index),
                "exact_base_public_completion_status": forced_status,
            }
        )

    c03_digest = canonical_hash(tuple(c03_f04_trace))
    base_conflicts = (
        _reduce_exact_conflict(len(base_components), base_constraints)
        if base_status == "INFEASIBLE" and not defer_colocation_conflict_reduction
        else ()
    )
    colocation_reduction_deferred = (
        defer_colocation_conflict_reduction
        and base_status == "INFEASIBLE"
        and colocation_status == "INFEASIBLE"
    )
    colocation_conflicts = (
        _reduce_exact_conflict(
            len(colocation_components),
            colocation_constraints,
            structural_group_ids=_exact_colocation_group_ids(
                base_components,
                exact_shingle_colocation_pairs,
            ),
        )
        if colocation_status == "INFEASIBLE" and not colocation_reduction_deferred
        else ()
    )
    overall_status = (
        "INFEASIBLE"
        if "INFEASIBLE" in {base_status, colocation_status}
        else "BLOCKED"
        if "UNKNOWN" in {base_status, colocation_status} or c03_unknown
        else "FEASIBLE"
    )
    canonical_status = "NOT_RUN"
    witness_digest: str | None = None
    canonical_trace: tuple[tuple[int, int, str], ...] = ()
    aggregates: dict[str, tuple[tuple[SplitName, int], ...]] = {
        "hard_cell_count_by_split": (),
        "adversarial_tag_count_by_split": (),
        "reachable_error_count_by_split": (),
        "protected_critical_error_count_by_split": (),
        "answerable_case_count_by_split": (),
        "c18_refusal_cell_count_by_split": (),
    }
    if overall_status == "FEASIBLE" and run_canonical_self_reduction:
        if canonical_self_reduction_backend == "GLUCOSE":
            self_reduction_status, canonical_ranks, canonical_trace = (
                _canonical_split_ranks_glucose(
                    len(colocation_components),
                    colocation_constraints,
                    progress_callback=canonical_progress_callback,
                    deadline=oracle_deadline,
                )
            )
        else:
            self_reduction_status, canonical_ranks = _canonical_split_ranks(
                len(colocation_components),
                colocation_constraints,
                tuple(colocation_solution),
                deadline=oracle_deadline,
            )
        if self_reduction_status == "PASS" and canonical_ranks is not None:
            canonical_status = "PASS"
            witness_digest = canonical_hash(
                tuple(
                    (component.cluster_key, PROSPECTIVE_SPLIT_COUNTS[rank][0])
                    for component, rank in zip(
                        colocation_components,
                        canonical_ranks,
                        strict=True,
                    )
                )
            )
            aggregates = _exact_aggregate_evidence(
                colocation_components,
                colocation_components,
                canonical_ranks,
            )
        else:
            canonical_status = "NOT_RUN"
            overall_status = "BLOCKED"

    provisional = ProductionExactFeasibilityReceiptV2(
        status=overall_status,
        algorithm_id=PRODUCTION_EXACT_FEASIBILITY_ALGORITHM,
        candidate_count=FINAL_TARGET_CASES,
        target_counts=PROSPECTIVE_SPLIT_COUNTS,
        base_component_count=len(base_components),
        base_component_inventory_digest=base_inventory_digest,
        co_location_component_count=len(colocation_components),
        co_location_component_inventory_digest=colocation_inventory_digest,
        co_location_component_size_distribution=tuple(
            sorted(Counter(component.size for component in colocation_components).items())
        ),
        exact_shingle_colocation_pair_count=len(exact_shingle_colocation_pairs),
        exact_shingle_colocation_digest=edge_digest,
        commitments_digest=commitments_digest,
        solver_family=PRODUCTION_EXACT_SOLVER_FAMILY,
        solver_version=PRODUCTION_EXACT_SOLVER_VERSION,
        solver_config_digest=canonical_hash(PRODUCTION_EXACT_SOLVER_CONFIG),
        base_model_digest=base_model_digest,
        colocation_model_digest=colocation_model_digest,
        base_status=base_status,
        colocation_status=colocation_status,
        legacy_base_status=legacy_status,
        canonical_self_reduction_status=canonical_status,
        canonical_witness_digest=witness_digest,
        c03_f04_eligible_component_count=len(c03_f04_trace),
        c03_f04_public_feasible_component_count=c03_public_feasible,
        c03_f04_diagnostic_digest=c03_digest,
        feasibility_membership_persisted=False,
        receipt_digest="sha256:" + "0" * 64,
        **aggregates,
    )
    receipt = bind_production_exact_feasibility_receipt(provisional)
    diagnostic: dict[str, object] = {
        "algorithm_id": PRODUCTION_EXACT_FEASIBILITY_ALGORITHM,
        "base_status": base_status,
        "colocation_status": colocation_status,
        "legacy_base_status": legacy_status,
        "legacy_failure": legacy_failure,
        "legacy_colocation_status": colocation_legacy_status,
        "base_model_digest": base_model_digest,
        "colocation_model_digest": colocation_model_digest,
        "base_conflict_groups": base_conflicts,
        "colocation_conflict_groups": colocation_conflicts,
        "colocation_conflict_reduction_deferred": colocation_reduction_deferred,
        "hint_generation_status": hint_generation_status,
        "hint_generation_model": hint_generation_model,
        "canonical_self_reduction_backend": canonical_self_reduction_backend,
        "canonical_self_reduction_trace": canonical_trace,
        "canonical_self_reduction_trace_digest": canonical_hash(canonical_trace),
        "colocation_edge_reason": "RETAINED_EXACT_SHINGLE",
        "colocation_structural_group_ids": _exact_colocation_group_ids(
            base_components,
            exact_shingle_colocation_pairs,
        ),
        "c03_f04_greedy_false_negative": c03_public_feasible > 0,
        "c03_f04_trace": tuple(c03_f04_trace),
        "receipt_digest": receipt.receipt_digest,
    }
    return _ExactFeasibilityResult(receipt=receipt, private_diagnostic=diagnostic)


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


def validate_production_batch_manifest_bindings(
    manifest: ProductionBatchManifestV1,
    *,
    authoring_plan_digest: str,
    candidate_store_receipt_digest: str,
    qualification_exclusion_digest: str,
    feasibility_receipt_digest: str,
) -> None:
    """Reject self-consistent manifests whose component digests name other artifacts."""

    validate_production_batch_manifest(manifest)
    expected = (
        authoring_plan_digest,
        candidate_store_receipt_digest,
        qualification_exclusion_digest,
        feasibility_receipt_digest,
    )
    observed = (
        manifest.authoring_plan_digest,
        manifest.candidate_store_receipt_digest,
        manifest.qualification_exclusion_digest,
        manifest.feasibility_receipt_digest,
    )
    if observed != expected:
        raise ValueError("production manifest component digest differs from its exact artifact")


_REVIEW_EXPERTISE_BY_CAPABILITY = {
    "C01": "MEASUREMENT_IDENTITY",
    "C02": "PROTOCOL_EXTRACTION",
    "C03": "MEASUREMENT_IDENTITY",
    "C04": "VALUE_PROVENANCE",
    "C05": "UNITS_AND_NORMALIZATION",
    "C06": "FRAME_AND_EVENT_DEFINITIONS",
    "C07": "COMPARABILITY",
    "C08": "ENGINE_OUTPUTS",
    "C09": "LONGITUDINAL_CLAIMS",
    "C10": "STATISTICAL_DESIGN",
    "C11": "POPULATION_STRUCTURE",
    "C12": "RELIABILITY_AND_UNCERTAINTY",
    "C13": "SOURCE_EVIDENCE",
    "C14": "EVIDENCE_APPLICABILITY",
    "C15": "CAUSAL_INFERENCE",
    "C16": "ENGINE_BOUNDARIES",
    "C17": "SCIENTIFIC_ERROR_TAXONOMY",
    "C18": "REFUSAL_AND_SAFE_PARTIAL",
}


@register_serializable_type
@dataclass(frozen=True, slots=True)
class ProductionReviewQueueEntryV1:
    candidate_id: str
    candidate_payload_hash: str
    proposed_approval_digest: str
    review_batch_id: str
    deterministic_order: int
    required_reviewer_expertise_category: str
    mutation_parent_dependency: str | None

    def __post_init__(self) -> None:
        _candidate_id(self.candidate_id)
        for name in ("candidate_payload_hash", "proposed_approval_digest"):
            if _SHA256.fullmatch(getattr(self, name)) is None:
                raise ValueError(f"{name} must be a SHA-256 digest")
        if not self.review_batch_id.startswith("PSE-V1-REVIEW-BATCH:"):
            raise ValueError("review batch ID must use the production review namespace")
        if self.deterministic_order < 1:
            raise ValueError("review order must be a positive one-based index")
        if self.required_reviewer_expertise_category not in set(
            _REVIEW_EXPERTISE_BY_CAPABILITY.values()
        ):
            raise ValueError("review queue has an unknown expertise category")
        if self.mutation_parent_dependency is not None:
            _candidate_id(self.mutation_parent_dependency)


@register_serializable_type
@dataclass(frozen=True, slots=True)
class ProductionReviewQueueV1:
    batch_id: str
    candidate_count: int
    entries: tuple[ProductionReviewQueueEntryV1, ...]
    queue_digest: str

    def __post_init__(self) -> None:
        if self.batch_id != PRODUCTION_BATCH_ID:
            raise ValueError("review queue must bind the 001C production batch")
        if self.candidate_count != FINAL_TARGET_CASES or len(self.entries) != FINAL_TARGET_CASES:
            raise ValueError("review queue must contain exactly 434 candidates")
        if any(not isinstance(item, ProductionReviewQueueEntryV1) for item in self.entries):
            raise ValueError("review queue requires typed entries")
        ids = tuple(item.candidate_id for item in self.entries)
        if len(set(ids)) != FINAL_TARGET_CASES:
            raise ValueError("review queue candidate IDs must be unique")
        if tuple(item.deterministic_order for item in self.entries) != tuple(
            range(1, FINAL_TARGET_CASES + 1)
        ):
            raise ValueError("review queue order must be contiguous and deterministic")
        if _SHA256.fullmatch(self.queue_digest) is None:
            raise ValueError("review queue digest must be a SHA-256 digest")


def production_review_queue_digest(queue: ProductionReviewQueueV1) -> str:
    return canonical_hash(
        {
            item.name: getattr(queue, item.name)
            for item in fields(queue)
            if item.name != "queue_digest"
        }
    )


def bind_production_review_queue(queue: ProductionReviewQueueV1) -> ProductionReviewQueueV1:
    return replace(queue, queue_digest=production_review_queue_digest(queue))


def _review_group_key(
    packet: CandidateReviewPacket,
    item: ProductionAuthoringPlanItemV1,
) -> tuple[str, ...]:
    expertise = _REVIEW_EXPERTISE_BY_CAPABILITY[packet.capability_id]
    provenance = packet.proposed_provenance
    if provenance.origin_class is CaseOrigin.ADVERSARIAL_MUTATION:
        kind, value = "mutation-lineage", provenance.mutation_lineage_id or ""
    elif provenance.origin_class is CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION:
        kind, value = "source-family", item.source_family_id
    elif provenance.origin_class is CaseOrigin.EXPERT_AUTHORED_SEMANTIC:
        kind, value = "author-batch", item.expert_author_batch_id or ""
    elif provenance.origin_class is CaseOrigin.DETERMINISTIC_ENGINE_DERIVED:
        kind, value = "reference-case", provenance.engine_reference_case_id or ""
    else:
        kind, value = "generator", provenance.generator_family or ""
    return expertise, item.authority_class, kind, value


def _review_batch_id(group_key: tuple[str, ...]) -> str:
    return "PSE-V1-REVIEW-BATCH:" + canonical_hash(group_key).removeprefix("sha256:")[:20]


MAX_REVIEW_BATCH_SIZE = 12


def build_production_review_queue(
    packets: tuple[CandidateReviewPacket, ...],
) -> ProductionReviewQueueV1:
    """Build a deterministic, decision-free queue with parent-before-child ordering."""

    if len(packets) != FINAL_TARGET_CASES:
        raise ValueError("review queue requires exactly 434 candidate packets")
    by_id = {packet.candidate_id: packet for packet in packets}
    if len(by_id) != FINAL_TARGET_CASES:
        raise ValueError("review queue candidate IDs must be unique")
    items = {packet.candidate_id: production_plan_item_from_packet(packet) for packet in packets}
    parent_by_child = {
        packet.candidate_id: packet.parent_candidate_binding.parent_candidate_id
        for packet in packets
        if packet.parent_candidate_binding is not None
    }
    grouped = {
        candidate_id: _review_group_key(packet, items[candidate_id])
        for candidate_id, packet in by_id.items()
    }
    grouped_members: dict[tuple[str, ...], list[str]] = defaultdict(list)
    for candidate_id, group_key in grouped.items():
        grouped_members[group_key].append(candidate_id)
    batch_by_id: dict[str, str] = {}
    for group_key, member_ids in grouped_members.items():
        ordered_members = sorted(member_ids, key=lambda value: value.encode("utf-8"))
        for chunk_index, offset in enumerate(range(0, len(ordered_members), MAX_REVIEW_BATCH_SIZE)):
            batch_id = _review_batch_id((*group_key, f"chunk:{chunk_index:03d}"))
            for candidate_id in ordered_members[offset : offset + MAX_REVIEW_BATCH_SIZE]:
                batch_by_id[candidate_id] = batch_id
    children: dict[str, list[str]] = defaultdict(list)
    indegree = dict.fromkeys(by_id, 0)
    for child_id, parent_id in parent_by_child.items():
        if parent_id not in by_id:
            raise ValueError("review queue mutation parent is absent from the production batch")
        children[parent_id].append(child_id)
        indegree[child_id] += 1

    ready = [
        (batch_by_id[candidate_id], candidate_id)
        for candidate_id, degree in indegree.items()
        if degree == 0
    ]
    heapq.heapify(ready)
    ordered: list[str] = []
    while ready:
        _batch, candidate_id = heapq.heappop(ready)
        ordered.append(candidate_id)
        for child_id in sorted(children[candidate_id], key=lambda value: value.encode("utf-8")):
            indegree[child_id] -= 1
            if indegree[child_id] == 0:
                heapq.heappush(ready, (batch_by_id[child_id], child_id))
    if len(ordered) != FINAL_TARGET_CASES:
        raise ValueError("review queue mutation dependencies contain a cycle")

    entries = tuple(
        ProductionReviewQueueEntryV1(
            candidate_id=candidate_id,
            candidate_payload_hash=by_id[candidate_id].candidate_payload_hash,
            proposed_approval_digest=by_id[candidate_id].proposed_approval_digest,
            review_batch_id=batch_by_id[candidate_id],
            deterministic_order=order,
            required_reviewer_expertise_category=_REVIEW_EXPERTISE_BY_CAPABILITY[
                by_id[candidate_id].capability_id
            ],
            mutation_parent_dependency=parent_by_child.get(candidate_id),
        )
        for order, candidate_id in enumerate(ordered, start=1)
    )
    return bind_production_review_queue(
        ProductionReviewQueueV1(
            batch_id=PRODUCTION_BATCH_ID,
            candidate_count=FINAL_TARGET_CASES,
            entries=entries,
            queue_digest="sha256:" + "0" * 64,
        )
    )


def validate_production_review_queue(
    queue: ProductionReviewQueueV1,
    packets: tuple[CandidateReviewPacket, ...],
) -> None:
    if queue.queue_digest != production_review_queue_digest(queue):
        raise ValueError("production review queue digest mismatch")
    if queue != build_production_review_queue(packets):
        raise ValueError("production review queue differs from deterministic packet bindings")
    by_id = {item.candidate_id: item for item in queue.entries}
    for item in queue.entries:
        parent = item.mutation_parent_dependency
        if parent is not None and by_id[parent].deterministic_order >= item.deterministic_order:
            raise ValueError("mutation review queue child must follow its parent")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class ProductionDuplicationAuditV1:
    algorithm_id: str
    candidate_count: int
    candidate_set_digest: str
    exact_payload_duplicate_pairs: int
    exact_question_duplicate_pairs: int
    normalized_question_duplicate_pairs: int
    exact_13_token_overlap_pairs: int
    blocking_fuzzy_overlap_pairs: int
    unrelated_blocking_overlaps: int
    audit_digest: str
    exact_shingle_colocation_pairs: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if self.algorithm_id != "PSE-V1-INTRA-DUPLICATION-AUDIT@1.1.0":
            raise ValueError("unsupported production duplication audit algorithm")
        if self.candidate_count < 1:
            raise ValueError("duplication audit must bind a non-empty candidate pool")
        if any(
            value != 0
            for value in (
                self.exact_payload_duplicate_pairs,
                self.exact_question_duplicate_pairs,
                self.normalized_question_duplicate_pairs,
                self.blocking_fuzzy_overlap_pairs,
                self.unrelated_blocking_overlaps,
            )
        ):
            raise ValueError("production duplication audit cannot contain blocking overlaps")
        if self.exact_13_token_overlap_pairs != len(self.exact_shingle_colocation_pairs):
            raise ValueError("exact-shingle count differs from pending co-location constraints")
        if any(
            not isinstance(pair, tuple)
            or len(pair) != 2
            or any(not isinstance(candidate_id, str) for candidate_id in pair)
            for pair in self.exact_shingle_colocation_pairs
        ):
            raise ValueError("exact-shingle co-location pairs are malformed")
        if any(
            left == right or left.encode("utf-8") >= right.encode("utf-8")
            for left, right in self.exact_shingle_colocation_pairs
        ) or self.exact_shingle_colocation_pairs != tuple(
            sorted(
                set(self.exact_shingle_colocation_pairs),
                key=lambda pair: (pair[0].encode("utf-8"), pair[1].encode("utf-8")),
            )
        ):
            raise ValueError("exact-shingle co-location pairs must be unique and canonical")
        for name in ("candidate_set_digest", "audit_digest"):
            if _SHA256.fullmatch(getattr(self, name)) is None:
                raise ValueError(f"{name} must be a SHA-256 digest")


def production_duplication_audit_digest(audit: ProductionDuplicationAuditV1) -> str:
    return canonical_hash(
        {
            item.name: getattr(audit, item.name)
            for item in fields(audit)
            if item.name != "audit_digest"
        }
    )


def _token_grams(tokens: tuple[str, ...], width: int = 5) -> frozenset[tuple[str, ...]]:
    return frozenset(
        tuple(tokens[index : index + width]) for index in range(max(0, len(tokens) - width + 1))
    )


def audit_production_duplicates(
    packets: tuple[CandidateReviewPacket, ...],
) -> ProductionDuplicationAuditV1:
    """Reject exact duplicates and fuzzy-only overlaps; retain exact-shingle constraints."""

    if not packets or len({item.candidate_id for item in packets}) != len(packets):
        raise ValueError("production duplication audit requires unique packets")
    by_id = {item.candidate_id: item for item in packets}
    parent_by_child: dict[str, str] = {}
    lineage_clusters: dict[str, str] = {}
    for child in packets:
        binding = child.parent_candidate_binding
        if binding is None:
            if child.proposed_provenance.origin_class is CaseOrigin.ADVERSARIAL_MUTATION:
                raise ValueError("mutation overlap exemption requires a declared exact parent")
            continue
        parent = by_id.get(binding.parent_candidate_id)
        provenance = child.proposed_provenance
        if (
            parent is None
            or provenance.origin_class is not CaseOrigin.ADVERSARIAL_MUTATION
            or binding.parent_candidate_version != parent.candidate_version
            or binding.parent_candidate_payload_hash != parent.candidate_payload_hash
            or binding.parent_origin_class is not parent.proposed_provenance.origin_class
            or provenance.parent_origin_class is not parent.proposed_provenance.origin_class
            or binding.mutation_lineage_id != provenance.mutation_lineage_id
            or (
                parent.proposed_provenance.origin_class is CaseOrigin.ADVERSARIAL_MUTATION
                and provenance.mutation_lineage_id != parent.proposed_provenance.mutation_lineage_id
            )
            or parent.isolation
            != replace(child.isolation, allocation_stratum=parent.isolation.allocation_stratum)
            or parent.contamination.source_family_id != child.contamination.source_family_id
        ):
            raise ValueError("mutation overlap exemption has an invalid parent/cluster binding")
        parent_authority = tuple(
            item
            for item in parent.authority
            if any(
                governed in {"expected_answer", "refusal_expectation", "claim_contract"}
                or governed.startswith("expected_answer.")
                for governed in item.governed_field_ids
            )
        )
        if not parent_authority or any(item not in child.authority for item in parent_authority):
            raise ValueError("mutation overlap exemption dropped primary parent authority")
        parent_authority_bindings = tuple(
            item for item in child.authority if item.authority_kind == "MUTATION_PARENT"
        )
        if (
            len(parent_authority_bindings) != 1
            or parent_authority_bindings[0].source_reference_id != parent.candidate_id
            or parent_authority_bindings[0].version != parent.candidate_version
            or parent_authority_bindings[0].digest != parent.candidate_payload_hash
        ):
            raise ValueError("mutation overlap exemption lacks exact parent authority")
        parent_projection = candidate_scientific_projection(parent)
        child_projection = candidate_scientific_projection(child)
        changed_fields = tuple(
            sorted(
                (
                    field
                    for field in parent_projection
                    if parent_projection[field] != child_projection[field]
                ),
                key=lambda value: value.encode("utf-8"),
            )
        )
        if not changed_fields or provenance.changed_fields != changed_fields:
            raise ValueError("mutation overlap exemption has an invalid scientific delta")
        lineage = provenance.mutation_lineage_id or ""
        cluster = lineage_clusters.setdefault(lineage, child.isolation.isolation_cluster_id)
        if cluster != child.isolation.isolation_cluster_id:
            raise ValueError("mutation overlap exemption fragments its lineage cluster")
        parent_by_child[child.candidate_id] = parent.candidate_id

    visitation: dict[str, int] = {}

    def visit(candidate_id: str) -> None:
        state = visitation.get(candidate_id, 0)
        if state == 1:
            raise ValueError("mutation duplicate-audit graph contains a cycle")
        if state == 2:
            return
        visitation[candidate_id] = 1
        parent_id = parent_by_child.get(candidate_id)
        if parent_id is not None:
            visit(parent_id)
        visitation[candidate_id] = 2

    for candidate_id in by_id:
        visit(candidate_id)

    def is_lineage_ancestor(ancestor_id: str, descendant_id: str) -> bool:
        current = descendant_id
        lineage_ids: set[str] = set()
        while current in parent_by_child:
            child = by_id[current]
            lineage_id = child.proposed_provenance.mutation_lineage_id
            if lineage_id is None:
                return False
            lineage_ids.add(lineage_id)
            current = parent_by_child[current]
            if current == ancestor_id:
                ancestor = by_id[ancestor_id]
                return (
                    len(lineage_ids) == 1
                    and ancestor.isolation.isolation_cluster_id
                    == child.isolation.isolation_cluster_id
                    and ancestor.contamination.source_family_id
                    == child.contamination.source_family_id
                )
        return False

    def is_authorized_mutation_pair(left_id: str, right_id: str) -> bool:
        return is_lineage_ancestor(left_id, right_id) or is_lineage_ancestor(right_id, left_id)

    exact_payload = exact_question = normalized = shingles = fuzzy = blocking = 0
    exact_shingle_colocation_pairs: list[tuple[str, str]] = []
    ordered = tuple(sorted(packets, key=lambda item: item.candidate_id.encode("utf-8")))
    source_span_candidates: dict[tuple[str, str], list[CandidateReviewPacket]] = defaultdict(list)
    for packet in ordered:
        for excerpt in packet.input.evidence_excerpts:
            source_span_candidates[
                (excerpt.document_identity.document_id, excerpt.span_identity.span_digest)
            ].append(packet)
    for span_packets in source_span_candidates.values():
        if len(span_packets) < 2:
            continue
        for index, left in enumerate(span_packets):
            for right in span_packets[index + 1 :]:
                if not is_authorized_mutation_pair(left.candidate_id, right.candidate_id):
                    raise ValueError("unrelated production candidates reuse an exact source span")
    metrics = {}
    for packet in ordered:
        question = packet.question
        normalized_text = normalize_text(question)
        tokens = tuple(re.findall(r"\w+|[^\w\s]", normalized_text, flags=re.UNICODE))
        char_grams = frozenset(
            normalized_text[index : index + 5] for index in range(max(0, len(normalized_text) - 4))
        )
        metrics[packet.candidate_id] = (
            normalized_text_sha256(question),
            exact_13_token_shingles(question),
            _token_grams(tokens),
            char_grams,
            normalized_text,
        )
    # ponytail: O(n^2) is bounded at 434 records; use an inverted index if the batch grows.
    for index, left in enumerate(ordered):
        left_normalized, left_shingles, left_token_grams, left_char_grams, left_text = metrics[
            left.candidate_id
        ]
        for right in ordered[index + 1 :]:
            if is_authorized_mutation_pair(left.candidate_id, right.candidate_id):
                continue
            right_normalized, right_shingles, right_token_grams, right_char_grams, right_text = (
                metrics[right.candidate_id]
            )
            exact_payload_duplicate = left.candidate_payload_hash == right.candidate_payload_hash
            exact_question_duplicate = left.question == right.question
            normalized_question_duplicate = left_normalized == right_normalized
            exact_shingle_overlap = bool(left_shingles.intersection(right_shingles))
            if exact_payload_duplicate:
                exact_payload += 1
            if exact_question_duplicate:
                exact_question += 1
            if normalized_question_duplicate:
                normalized += 1
            if exact_payload_duplicate or exact_question_duplicate or normalized_question_duplicate:
                blocking += 1
                continue
            if exact_shingle_overlap:
                shingles += 1
                exact_shingle_colocation_pairs.append((left.candidate_id, right.candidate_id))
                continue
            token_union = left_token_grams | right_token_grams
            token_similarity = (
                len(left_token_grams & right_token_grams) / len(token_union) if token_union else 1.0
            )
            char_union = left_char_grams | right_char_grams
            char_similarity = (
                len(left_char_grams & right_char_grams) / len(char_union) if char_union else 1.0
            )
            if (
                token_similarity >= 0.85
                or char_similarity >= 0.85
                or normalized_edit_similarity_at_least(left_text, right_text, 0.90)
            ):
                fuzzy += 1
                blocking += 1
    if blocking:
        raise ValueError(f"unrelated production duplication audit found {blocking} blocking pairs")
    candidate_set_digest = canonical_hash(
        tuple((item.candidate_id, item.candidate_payload_hash) for item in ordered)
    )
    provisional = ProductionDuplicationAuditV1(
        algorithm_id="PSE-V1-INTRA-DUPLICATION-AUDIT@1.1.0",
        candidate_count=len(ordered),
        candidate_set_digest=candidate_set_digest,
        exact_payload_duplicate_pairs=exact_payload,
        exact_question_duplicate_pairs=exact_question,
        normalized_question_duplicate_pairs=normalized,
        exact_13_token_overlap_pairs=shingles,
        blocking_fuzzy_overlap_pairs=fuzzy,
        unrelated_blocking_overlaps=blocking,
        audit_digest="sha256:" + "0" * 64,
        exact_shingle_colocation_pairs=tuple(exact_shingle_colocation_pairs),
    )
    return replace(provisional, audit_digest=production_duplication_audit_digest(provisional))


def _validate_production_candidate_set_and_commitments(
    packets: tuple[CandidateReviewPacket, ...],
    *,
    source_resolver: SourceArtifactResolver | None = None,
    expected_count: int | None = FINAL_TARGET_CASES,
) -> tuple[ProductionCandidateCommitmentV1, ...]:
    """Validate packets/topology and derive commitments before the isolation gate.

    ``expected_count=None`` validates a variable pre-review pool (RES258-DR-001); the
    historical exact-434 production batch keeps its default count.
    """

    if not packets:
        raise ValueError("production candidate pool must be non-empty")
    if expected_count is not None and len(packets) != expected_count:
        raise ValueError(f"production candidate set must contain exactly {expected_count} packets")
    if any(
        not packet.candidate_id.startswith(PRODUCTION_CANDIDATE_ID_PREFIX) for packet in packets
    ):
        raise ValueError("production candidate set contains a non-production ID")
    for packet in packets:
        validate_production_candidate_packet(packet, source_resolver=source_resolver)
    validate_candidate_set(packets, source_resolver=source_resolver)
    _validate_production_mutation_isolation_metadata(packets)
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
    return commitments


def validate_production_candidate_set(
    packets: tuple[CandidateReviewPacket, ...],
    *,
    source_resolver: SourceArtifactResolver | None = None,
    defer_split_lock_conflicts: bool = False,
    enforce_public_capacity: bool = True,
) -> tuple[ProductionCandidateCommitmentV1, ...]:
    """Validate the exact production set, including split-isolation dependencies."""

    commitments = _validate_production_candidate_set_and_commitments(
        packets,
        source_resolver=source_resolver,
    )
    validate_production_isolation(
        commitments,
        defer_split_lock_conflicts=defer_split_lock_conflicts,
        enforce_public_capacity=enforce_public_capacity,
    )
    return commitments


def validate_production_candidate_pool(
    packets: tuple[CandidateReviewPacket, ...],
    *,
    source_resolver: SourceArtifactResolver | None = None,
) -> tuple[tuple[ProductionCandidateCommitmentV1, ...], ProductionDuplicationAuditV1]:
    """Apply packet, set, isolation, and duplication gates to a variable pre-review pool.

    Split-lock conflicts and Public capacity are allocation questions for joint final
    selection, so they are deferred exactly as in pre-review production qualification.
    """

    commitments = _validate_production_candidate_set_and_commitments(
        packets,
        source_resolver=source_resolver,
        expected_count=None,
    )
    validate_production_isolation(
        commitments,
        defer_split_lock_conflicts=True,
        enforce_public_capacity=False,
    )
    return commitments, audit_production_duplicates(packets)


__all__ = [
    "FINAL_TARGET_CASES",
    "PRODUCTION_AUTHORING_PLAN_VERSION",
    "PRODUCTION_AUTHORING_PROCESS_ID",
    "PRODUCTION_BATCH_ID",
    "PRODUCTION_BATCH_MANIFEST_VERSION",
    "PRODUCTION_CANDIDATE_ID_PREFIX",
    "PRODUCTION_EXACT_FEASIBILITY_ALGORITHM",
    "PRODUCTION_EXACT_SOLVER_CONFIG",
    "PRODUCTION_EXACT_SOLVER_FAMILY",
    "PRODUCTION_EXACT_SOLVER_VERSION",
    "PRODUCTION_FEASIBILITY_ALGORITHM",
    "PROSPECTIVE_SPLIT_COUNTS",
    "ProductionAuthoringPlanItemV1",
    "ProductionAuthoringPlanV1",
    "ProductionBatchManifestV1",
    "ProductionCandidateCommitmentV1",
    "ProductionCandidateStoreReceiptV1",
    "ProductionDuplicationAuditV1",
    "ProductionExactFeasibilityReceiptV2",
    "ProductionFeasibilityBlocked",
    "ProductionFeasibilityReceiptV1",
    "ProductionIsolationValidationV1",
    "ProductionReviewQueueEntryV1",
    "ProductionReviewQueueV1",
    "audit_production_duplicates",
    "bind_production_authoring_plan",
    "bind_production_batch_manifest",
    "bind_production_candidate_store_receipt",
    "bind_production_exact_feasibility_receipt",
    "bind_production_feasibility_receipt",
    "bind_production_review_queue",
    "build_production_candidate_commitment",
    "build_production_review_queue",
    "production_authoring_plan_digest",
    "production_batch_manifest_digest",
    "production_candidate_store_receipt_digest",
    "production_duplication_audit_digest",
    "production_exact_feasibility_receipt_digest",
    "production_feasibility_receipt_digest",
    "production_plan_item_from_packet",
    "production_review_queue_digest",
    "validate_production_authoring_plan",
    "validate_production_batch_manifest",
    "validate_production_batch_manifest_bindings",
    "validate_production_candidate_packet",
    "validate_production_candidate_pool",
    "validate_production_candidate_set",
    "validate_production_candidate_store_receipt",
    "validate_production_exact_feasibility",
    "validate_production_exact_feasibility_receipt",
    "validate_production_feasibility_receipt",
    "validate_production_hard_feasibility",
    "validate_production_isolation",
    "validate_production_legacy_feasibility",
    "validate_production_origin_isolation_metadata",
    "validate_production_review_queue",
]
