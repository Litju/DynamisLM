"""Immutable pre-review packets and the human-approval promotion gate.

Candidate packets are deliberately not ``BenchmarkCaseV1`` instances.  Their
payload is reviewable and hash-bound, but they contain no reviewer, approval
timestamp, or final split.  Only a separately supplied HumanApprovalRecord can
promote one into the unchanged final case contract.
"""

from __future__ import annotations

import datetime as datetime_module
import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass, fields, replace
from enum import StrEnum
from types import SimpleNamespace
from typing import cast

from dynamislm.benchmark.authority import validate_authority_bindings
from dynamislm.benchmark.constants import (
    BENCHMARK_SEMANTIC_VERSION,
    CAPABILITY_IDS,
    CASE_SCHEMA_VERSION,
    FAMILY_IDS,
    MEASUREMENT_CLAIM_LEVELS,
    RELATIONSHIP_CLAIM_LEVELS,
    SERIALIZATION_V3,
    AuthorityKind,
    CaseOrigin,
    EvidenceKind,
    ExpectedAnswerKind,
    PractitionerQuestionClass,
    ScoringProfile,
)
from dynamislm.benchmark.contracts import (
    AuthorityBinding,
    BenchmarkCaseV1,
    CaseProvenance,
    ClaimContract,
    ComparabilityContract,
    ContaminationBinding,
    DifficultyBinding,
    EvidenceExcerpt,
    EvidenceReference,
    ExpectedStructuredAnswer,
    ExpertReviewMetadata,
    InputContract,
    ProvenanceEdge,
    RefusalExpectation,
    ScoringContract,
    SplitBinding,
    ToleranceContract,
)
from dynamislm.benchmark.coverage import COVERAGE_MATRIX
from dynamislm.benchmark.source_artifacts import (
    SourceArtifactResolver,
)
from dynamislm.benchmark.validation import (
    _validate_answer_contract,
    _validate_finite_expected_answer,
    _walk_numbers,
    validate_case,
)
from dynamislm.claims.models import PredictionStatus
from dynamislm.qualification import get_reference_case
from dynamislm.serialization import canonical_hash, register_serializable_type

_ZERO_SHA256 = "sha256:" + "0" * 64
_SHA256_PATTERN = re.compile(r"sha256:[0-9a-f]{64}\Z")
_SEMVER_PATTERN = re.compile(
    r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?\Z"
)
_REGISTERED_ADVERSARIAL_TAGS = frozenset(
    tag for row in COVERAGE_MATRIX for tag in row.adversarial_tags
)
_REQUIRED_REVIEW_CHECKLIST = (
    "AUTHORITY_BINDINGS_RESOLVE",
    "EXPECTED_ANSWER_MATCHES_AUTHORITY",
    "CLAIM_REFUSAL_AND_COMPARABILITY_ARE_BOUNDED",
    "SCORING_ERROR_ATTRIBUTION_AND_TOLERANCE_ARE_VALID",
    "SOURCE_IDENTITY_AND_EXACT_SPANS_ARE_VERIFIED_WHEN_APPLICABLE",
    "CONTAMINATION_SOURCE_FAMILY_AND_ISOLATION_ARE_VALID",
    "DIFFICULTY_AND_ADVERSARIAL_TAGS_ARE_JUSTIFIED",
)
_FORBIDDEN_PRE_REVIEW_KEYS = frozenset(
    {
        "approval",
        "approval_record",
        "approval_record_digest",
        "approval_status",
        "approved_at",
        "approval_timestamp",
        "reviewer",
        "reviewer_id",
        "reviewer_identity",
        "reviewer_expertise",
        "split",
        "split_name",
        "split_manifest_version",
        "split_manifest_hash",
        "membership_digest",
    }
)


class CandidateReviewStatus(StrEnum):
    """The sole status permitted on a Phase-B packet."""

    PENDING_HUMAN_REVIEW = "PENDING_HUMAN_REVIEW"


class HumanReviewDecision(StrEnum):
    """A recorded human decision; only APPROVED records can promote."""

    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class CandidateReviewChecklistItem(StrEnum):
    """Frozen Phase-C checklist sent with every proposed packet."""

    AUTHORITY_BINDINGS_RESOLVE = "AUTHORITY_BINDINGS_RESOLVE"
    EXPECTED_ANSWER_MATCHES_AUTHORITY = "EXPECTED_ANSWER_MATCHES_AUTHORITY"
    CLAIM_REFUSAL_AND_COMPARABILITY_ARE_BOUNDED = "CLAIM_REFUSAL_AND_COMPARABILITY_ARE_BOUNDED"
    SCORING_ERROR_ATTRIBUTION_AND_TOLERANCE_ARE_VALID = (
        "SCORING_ERROR_ATTRIBUTION_AND_TOLERANCE_ARE_VALID"
    )
    SOURCE_IDENTITY_AND_EXACT_SPANS_ARE_VERIFIED_WHEN_APPLICABLE = (
        "SOURCE_IDENTITY_AND_EXACT_SPANS_ARE_VERIFIED_WHEN_APPLICABLE"
    )
    CONTAMINATION_SOURCE_FAMILY_AND_ISOLATION_ARE_VALID = (
        "CONTAMINATION_SOURCE_FAMILY_AND_ISOLATION_ARE_VALID"
    )
    DIFFICULTY_AND_ADVERSARIAL_TAGS_ARE_JUSTIFIED = "DIFFICULTY_AND_ADVERSARIAL_TAGS_ARE_JUSTIFIED"


def _require_text(value: object, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")


def _require_sha256(value: object, field_name: str) -> None:
    if not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be a canonical SHA-256 digest")


def _require_optional_sha256(value: object, field_name: str) -> None:
    if value is not None:
        _require_sha256(value, field_name)


def _require_tuple(value: object, field_name: str) -> tuple[object, ...]:
    if not isinstance(value, tuple):
        raise ValueError(f"{field_name} must be an immutable tuple")
    return value


def _require_strings(
    value: object, field_name: str, *, allow_empty: bool = False
) -> tuple[str, ...]:
    values = _require_tuple(value, field_name)
    if not allow_empty and not values:
        raise ValueError(f"{field_name} must not be empty")
    for item in values:
        _require_text(item, f"{field_name} item")
    return cast(tuple[str, ...], values)


def _require_aware_timestamp(value: object, field_name: str) -> None:
    if not isinstance(value, datetime_module.datetime):
        raise ValueError(f"{field_name} must be a timezone-aware datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include an explicit timezone")


def _require_enum[T: StrEnum](value: object, enum_type: type[T], field_name: str) -> T:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} is outside its controlled vocabulary")
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} is outside its controlled vocabulary") from exc


@register_serializable_type
@dataclass(frozen=True, slots=True)
class ProposedCaseProvenance:
    """Case provenance before review, with authorship but no reviewer evidence."""

    author_id: str
    rubric_digest: str
    review_scope: str
    origin_class: CaseOrigin
    authority_lineage: tuple[str, ...]
    population_scope: str
    derivation_status: str
    derivation_edges: tuple[ProvenanceEdge, ...]
    source_artifact_ids: tuple[str, ...] = ()
    source_content_digests: tuple[str, ...] = ()
    evidence_span_refs: tuple[str, ...] = ()
    generator_id: str | None = None
    generator_version: str | None = None
    generator_family: str | None = None
    seed_namespace: str | None = None
    seed_block: str | None = None
    generator_registry_digest: str | None = None
    mutation_lineage_id: str | None = None
    parent_case_hash: str | None = None
    mutation_operator: str | None = None
    mutation_version: str | None = None
    mutation_seed: int | None = None
    changed_fields: tuple[str, ...] = ()
    parent_origin_class: CaseOrigin | None = None
    engine_operation_id: str | None = None
    engine_method_version: str | None = None
    engine_reference_case_id: str | None = None
    engine_reference_digest: str | None = None
    engine_registry_digest: str | None = None
    serialization_version: int = SERIALIZATION_V3

    def __post_init__(self) -> None:
        for name in ("author_id", "review_scope", "population_scope", "derivation_status"):
            _require_text(getattr(self, name), name)
        _require_sha256(self.rubric_digest, "rubric_digest")
        object.__setattr__(
            self, "origin_class", _require_enum(self.origin_class, CaseOrigin, "origin_class")
        )
        if self.parent_origin_class is not None:
            object.__setattr__(
                self,
                "parent_origin_class",
                _require_enum(self.parent_origin_class, CaseOrigin, "parent_origin_class"),
            )
        _require_strings(self.authority_lineage, "authority_lineage")
        edges = _require_tuple(self.derivation_edges, "derivation_edges")
        if any(not isinstance(item, ProvenanceEdge) for item in edges):
            raise ValueError("derivation_edges must contain ProvenanceEdge values")
        for name in (
            "source_artifact_ids",
            "evidence_span_refs",
            "changed_fields",
        ):
            _require_strings(getattr(self, name), name, allow_empty=True)
        digests = _require_strings(
            self.source_content_digests, "source_content_digests", allow_empty=True
        )
        for digest in digests:
            _require_sha256(digest, "source_content_digests item")
        for name in (
            "generator_id",
            "generator_version",
            "generator_family",
            "seed_namespace",
            "seed_block",
            "mutation_lineage_id",
            "mutation_operator",
            "mutation_version",
            "engine_operation_id",
            "engine_method_version",
            "engine_reference_case_id",
        ):
            value = getattr(self, name)
            if value is not None:
                _require_text(value, name)
        for name in (
            "generator_registry_digest",
            "parent_case_hash",
            "engine_reference_digest",
            "engine_registry_digest",
        ):
            _require_optional_sha256(getattr(self, name), name)
        if self.mutation_seed is not None and (
            isinstance(self.mutation_seed, bool)
            or not isinstance(self.mutation_seed, int)
            or self.mutation_seed < 0
        ):
            raise ValueError("mutation_seed must be a non-negative integer")
        if self.serialization_version != SERIALIZATION_V3:
            raise ValueError("candidate provenance must use Serialization V3")

    def _to_case_provenance(self, review: ExpertReviewMetadata) -> CaseProvenance:
        """Internal conversion called only by the validated promotion gate."""

        return CaseProvenance(
            origin_class=self.origin_class,
            review=review,
            authority_lineage=self.authority_lineage,
            population_scope=self.population_scope,
            derivation_status=self.derivation_status,
            derivation_edges=self.derivation_edges,
            source_artifact_ids=self.source_artifact_ids,
            source_content_digests=self.source_content_digests,
            evidence_span_refs=self.evidence_span_refs,
            generator_id=self.generator_id,
            generator_version=self.generator_version,
            generator_family=self.generator_family,
            seed_namespace=self.seed_namespace,
            seed_block=self.seed_block,
            generator_registry_digest=self.generator_registry_digest,
            mutation_lineage_id=self.mutation_lineage_id,
            parent_case_hash=self.parent_case_hash,
            mutation_operator=self.mutation_operator,
            mutation_version=self.mutation_version,
            mutation_seed=self.mutation_seed,
            changed_fields=self.changed_fields,
            parent_origin_class=self.parent_origin_class,
            engine_operation_id=self.engine_operation_id,
            engine_method_version=self.engine_method_version,
            engine_reference_case_id=self.engine_reference_case_id,
            engine_reference_digest=self.engine_reference_digest,
            engine_registry_digest=self.engine_registry_digest,
            serialization_version=self.serialization_version,
        )


@register_serializable_type
@dataclass(frozen=True, slots=True)
class CandidateIsolationMetadata:
    """Source-family and allocation-cluster hints without a final split."""

    source_family_id: str
    isolation_cluster_id: str
    allocation_stratum: str
    source_family_digest: str | None = None

    def __post_init__(self) -> None:
        for name in ("source_family_id", "isolation_cluster_id", "allocation_stratum"):
            _require_text(getattr(self, name), name)
        _require_optional_sha256(self.source_family_digest, "source_family_digest")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class CandidateParentBinding:
    """Exact pre-review commitment to the candidate being mutated."""

    parent_candidate_id: str
    parent_candidate_version: str
    parent_candidate_payload_hash: str
    parent_origin_class: CaseOrigin
    mutation_lineage_id: str

    def __post_init__(self) -> None:
        _require_text(self.parent_candidate_id, "parent_candidate_id")
        if self.parent_candidate_id.startswith("sha256:"):
            raise ValueError("parent_candidate_id is an identity, not a content hash")
        if _SEMVER_PATTERN.fullmatch(self.parent_candidate_version) is None:
            raise ValueError("parent_candidate_version must be a semantic version")
        _require_sha256(self.parent_candidate_payload_hash, "parent_candidate_payload_hash")
        object.__setattr__(
            self,
            "parent_origin_class",
            _require_enum(self.parent_origin_class, CaseOrigin, "parent_origin_class"),
        )
        _require_text(self.mutation_lineage_id, "mutation_lineage_id")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class CandidateReviewPacket:
    """Immutable Phase-B candidate; it cannot represent final approval/split."""

    benchmark_version: str
    schema_version: str
    candidate_id: str
    candidate_version: str
    capability_id: str
    benchmark_family: str
    practitioner_question_class: PractitionerQuestionClass
    question: str
    input: InputContract
    source_evidence_refs: tuple[EvidenceReference, ...]
    proposed_expected_answer: ExpectedStructuredAnswer
    authority: tuple[AuthorityBinding, ...]
    refusal_contract: RefusalExpectation
    claim_contract: ClaimContract
    comparability_contract: ComparabilityContract
    scoring_contract: ScoringContract
    tolerance_contract: ToleranceContract | None
    proposed_provenance: ProposedCaseProvenance
    contamination: ContaminationBinding
    isolation: CandidateIsolationMetadata
    difficulty: DifficultyBinding
    adversarial_tags: tuple[str, ...]
    parent_candidate_binding: CandidateParentBinding | None = None
    review_status: CandidateReviewStatus = CandidateReviewStatus.PENDING_HUMAN_REVIEW
    reviewer_checklist: tuple[CandidateReviewChecklistItem, ...] = tuple(
        CandidateReviewChecklistItem(item) for item in _REQUIRED_REVIEW_CHECKLIST
    )
    candidate_payload_hash: str = _ZERO_SHA256
    proposed_approval_digest: str = _ZERO_SHA256

    def __post_init__(self) -> None:
        if self.benchmark_version != BENCHMARK_SEMANTIC_VERSION:
            raise ValueError("unsupported benchmark target version")
        if self.schema_version != CASE_SCHEMA_VERSION:
            raise ValueError("unsupported case schema target version")
        for name in ("candidate_id", "candidate_version", "question"):
            _require_text(getattr(self, name), name)
        if self.candidate_id.startswith("sha256:"):
            raise ValueError("candidate_id is an identity, not a content hash")
        if _SEMVER_PATTERN.fullmatch(self.candidate_version) is None:
            raise ValueError("candidate_version must be a semantic version")
        if self.capability_id not in CAPABILITY_IDS:
            raise ValueError("unknown capability_id")
        if self.benchmark_family not in FAMILY_IDS:
            raise ValueError("unknown benchmark_family")
        object.__setattr__(
            self,
            "practitioner_question_class",
            _require_enum(
                self.practitioner_question_class,
                PractitionerQuestionClass,
                "practitioner_question_class",
            ),
        )
        if not isinstance(self.input, InputContract):
            raise ValueError("input must be InputContract")
        if self.input.question_text != self.question:
            raise ValueError("input.question_text must equal the canonical candidate question")
        if not isinstance(self.proposed_expected_answer, ExpectedStructuredAnswer):
            raise ValueError("proposed_expected_answer must be ExpectedStructuredAnswer")
        if not isinstance(self.refusal_contract, RefusalExpectation):
            raise ValueError("refusal_contract must be RefusalExpectation")
        if not isinstance(self.claim_contract, ClaimContract):
            raise ValueError("claim_contract must be ClaimContract")
        if not isinstance(self.comparability_contract, ComparabilityContract):
            raise ValueError("comparability_contract must be ComparabilityContract")
        if not isinstance(self.scoring_contract, ScoringContract):
            raise ValueError("scoring_contract must be ScoringContract")
        if self.tolerance_contract is not None and not isinstance(
            self.tolerance_contract, ToleranceContract
        ):
            raise ValueError("tolerance_contract must be ToleranceContract or None")
        if not isinstance(self.proposed_provenance, ProposedCaseProvenance):
            raise ValueError("proposed_provenance must be ProposedCaseProvenance")
        if not isinstance(self.contamination, ContaminationBinding):
            raise ValueError("contamination must be ContaminationBinding")
        if not isinstance(self.isolation, CandidateIsolationMetadata):
            raise ValueError("isolation must be CandidateIsolationMetadata")
        if not isinstance(self.difficulty, DifficultyBinding):
            raise ValueError("difficulty must be DifficultyBinding")
        if self.parent_candidate_binding is not None and not isinstance(
            self.parent_candidate_binding, CandidateParentBinding
        ):
            raise ValueError("parent_candidate_binding must be CandidateParentBinding or None")
        refs = _require_tuple(self.source_evidence_refs, "source_evidence_refs")
        if any(not isinstance(item, EvidenceReference) for item in refs):
            raise ValueError("source_evidence_refs must contain EvidenceReference values")
        authorities = _require_tuple(self.authority, "authority")
        if not authorities or any(not isinstance(item, AuthorityBinding) for item in authorities):
            raise ValueError("candidate requires typed authority bindings")
        typed_authorities = cast(tuple[AuthorityBinding, ...], authorities)
        authority_ids = tuple(
            (item.authority_kind, item.source_reference_id) for item in typed_authorities
        )
        if len(set(authority_ids)) != len(typed_authorities):
            raise ValueError("candidate authority bindings cannot repeat an identity")
        tags = _require_strings(self.adversarial_tags, "adversarial_tags")
        if len(tags) != len(set(tags)):
            raise ValueError("adversarial_tags cannot contain duplicates")
        unknown_tags = set(tags) - _REGISTERED_ADVERSARIAL_TAGS
        if unknown_tags:
            raise ValueError(f"unregistered adversarial tags: {sorted(unknown_tags)}")
        status = _require_enum(self.review_status, CandidateReviewStatus, "review_status")
        if status is not CandidateReviewStatus.PENDING_HUMAN_REVIEW:
            raise ValueError("candidate review status must remain PENDING_HUMAN_REVIEW")
        object.__setattr__(self, "review_status", status)
        checklist = tuple(
            _require_enum(item, CandidateReviewChecklistItem, "reviewer_checklist")
            for item in _require_tuple(self.reviewer_checklist, "reviewer_checklist")
        )
        expected_checklist = tuple(
            CandidateReviewChecklistItem(item) for item in _REQUIRED_REVIEW_CHECKLIST
        )
        if checklist != expected_checklist:
            raise ValueError("reviewer checklist must contain the complete frozen checklist")
        object.__setattr__(self, "reviewer_checklist", checklist)
        if self.isolation.source_family_id != self.contamination.source_family_id:
            raise ValueError("source-family identity must agree across isolation and contamination")
        _require_sha256(self.candidate_payload_hash, "candidate_payload_hash")
        _require_sha256(self.proposed_approval_digest, "proposed_approval_digest")
        _validate_no_final_state(self)

    @property
    def review_packet_digest(self) -> str:
        """The digest a human approval record must explicitly bind."""

        return self.proposed_approval_digest


@register_serializable_type
@dataclass(frozen=True, slots=True)
class HumanApprovalRecord:
    """Immutable review-decision record; its digest proves integrity, not authenticity."""

    approval_record_id: str
    candidate_id: str
    candidate_version: str
    candidate_payload_hash: str
    reviewed_packet_digest: str
    decision: HumanReviewDecision
    reviewer_id: str
    reviewer_expertise: tuple[str, ...]
    approval_timestamp: datetime_module.datetime
    review_event_reference: str | None = None
    approval_record_digest: str = _ZERO_SHA256

    def __post_init__(self) -> None:
        for name in ("approval_record_id", "candidate_id", "candidate_version", "reviewer_id"):
            _require_text(getattr(self, name), name)
        if self.reviewer_id != self.reviewer_id.strip():
            raise ValueError("reviewer_id must be a canonical stable identity")
        if _SEMVER_PATTERN.fullmatch(self.candidate_version) is None:
            raise ValueError("candidate_version must be a semantic version")
        if self.candidate_id.startswith("sha256:"):
            raise ValueError("candidate_id is an identity, not a content hash")
        if self.reviewer_id.strip().casefold() in {
            "unknown",
            "anonymous",
            "agent",
            "assistant",
            "model",
            "system",
        }:
            raise ValueError("reviewer_id must identify a human reviewer")
        _require_sha256(self.candidate_payload_hash, "candidate_payload_hash")
        _require_sha256(self.reviewed_packet_digest, "reviewed_packet_digest")
        object.__setattr__(
            self,
            "decision",
            _require_enum(self.decision, HumanReviewDecision, "decision"),
        )
        _require_strings(self.reviewer_expertise, "reviewer_expertise")
        _require_aware_timestamp(self.approval_timestamp, "approval_timestamp")
        if self.review_event_reference is not None:
            _require_text(self.review_event_reference, "review_event_reference")
        _require_sha256(self.approval_record_digest, "approval_record_digest")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class MutationPromotionLink:
    """Identity substitution from a reviewed parent candidate to its promoted case."""

    parent_candidate_binding: CandidateParentBinding
    parent_case_payload_hash: str
    parent_promotion_receipt_digest: str

    def __post_init__(self) -> None:
        if not isinstance(self.parent_candidate_binding, CandidateParentBinding):
            raise ValueError("parent_candidate_binding must be CandidateParentBinding")
        _require_sha256(self.parent_case_payload_hash, "parent_case_payload_hash")
        _require_sha256(self.parent_promotion_receipt_digest, "parent_promotion_receipt_digest")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class CasePromotionReceipt:
    """Canonical receipt binding one candidate, decision record, and final case."""

    candidate_id: str
    candidate_version: str
    candidate_payload_hash: str
    reviewed_packet_digest: str
    approval_record_id: str
    approval_record_digest: str
    final_case_id: str
    final_case_version: str
    final_case_payload_hash: str
    reviewer_id: str
    approval_timestamp: datetime_module.datetime
    mutation_promotion_link: MutationPromotionLink | None = None
    receipt_digest: str = _ZERO_SHA256

    def __post_init__(self) -> None:
        for name in (
            "candidate_id",
            "candidate_version",
            "approval_record_id",
            "final_case_id",
            "final_case_version",
            "reviewer_id",
        ):
            _require_text(getattr(self, name), name)
        if _SEMVER_PATTERN.fullmatch(self.candidate_version) is None:
            raise ValueError("receipt candidate_version must be a semantic version")
        if _SEMVER_PATTERN.fullmatch(self.final_case_version) is None:
            raise ValueError("receipt final_case_version must be a semantic version")
        for name in (
            "candidate_payload_hash",
            "reviewed_packet_digest",
            "approval_record_digest",
            "final_case_payload_hash",
            "receipt_digest",
        ):
            _require_sha256(getattr(self, name), name)
        _require_aware_timestamp(self.approval_timestamp, "approval_timestamp")
        if self.mutation_promotion_link is not None and not isinstance(
            self.mutation_promotion_link, MutationPromotionLink
        ):
            raise ValueError("mutation_promotion_link must be MutationPromotionLink or None")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class PromotionResult:
    """Durable promotion output; the final case and its hash-chain receipt travel together."""

    case: BenchmarkCaseV1
    receipt: CasePromotionReceipt

    def __post_init__(self) -> None:
        if not isinstance(self.case, BenchmarkCaseV1):
            raise ValueError("promotion result case must be BenchmarkCaseV1")
        if not isinstance(self.receipt, CasePromotionReceipt):
            raise ValueError("promotion result receipt must be CasePromotionReceipt")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class ParentPromotionEvidence:
    """Immutable reviewed packet, approval, and promotion evidence for a mutation parent."""

    packet: CandidateReviewPacket
    approval: HumanApprovalRecord
    result: PromotionResult
    parent_promotion_evidence: ParentPromotionEvidence | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.packet, CandidateReviewPacket):
            raise ValueError("parent evidence packet must be CandidateReviewPacket")
        if not isinstance(self.approval, HumanApprovalRecord):
            raise ValueError("parent evidence approval must be HumanApprovalRecord")
        if not isinstance(self.result, PromotionResult):
            raise ValueError("parent evidence result must be PromotionResult")
        if self.parent_promotion_evidence is not None and not isinstance(
            self.parent_promotion_evidence, ParentPromotionEvidence
        ):
            raise ValueError("parent_promotion_evidence must be ParentPromotionEvidence or None")


def _reject_final_state_in_context(value: object) -> None:
    if isinstance(value, Mapping):
        forbidden = {str(key).casefold() for key in value} & _FORBIDDEN_PRE_REVIEW_KEYS
        if forbidden:
            raise ValueError(
                "pre-review candidate cannot carry reviewer approval or final split fields: "
                + ", ".join(sorted(forbidden))
            )
        for item in value.values():
            _reject_final_state_in_context(item)
    elif isinstance(value, tuple | list):
        for item in value:
            _reject_final_state_in_context(item)


def _validate_no_final_state(packet: CandidateReviewPacket) -> None:
    _reject_final_state_in_context(packet.input.structured_context)
    _reject_final_state_in_context(packet.proposed_expected_answer.expected_fields)
    for observation in packet.input.observations:
        for value in (
            observation.context,
            observation.identity,
            observation.result,
            observation.provenance,
        ):
            _reject_final_state_in_context(value)
    for result in packet.input.deterministic_results:
        _reject_final_state_in_context(result.values)
        if result.refusal is not None:
            _reject_final_state_in_context(result.refusal)


def candidate_payload_projection(packet: CandidateReviewPacket) -> dict[str, object]:
    """Return the canonical, pre-review scientific-content projection."""

    if not isinstance(packet, CandidateReviewPacket):
        raise TypeError("packet must be CandidateReviewPacket")
    return {
        "benchmark_version": packet.benchmark_version,
        "schema_version": packet.schema_version,
        "candidate_id": packet.candidate_id,
        "candidate_version": packet.candidate_version,
        "capability_id": packet.capability_id,
        "benchmark_family": packet.benchmark_family,
        "practitioner_question_class": packet.practitioner_question_class,
        "question": packet.question,
        "input": packet.input,
        "source_evidence_refs": packet.source_evidence_refs,
        "proposed_expected_answer": packet.proposed_expected_answer,
        "authority": packet.authority,
        "refusal_contract": packet.refusal_contract,
        "claim_contract": packet.claim_contract,
        "comparability_contract": packet.comparability_contract,
        "scoring_contract": packet.scoring_contract,
        "tolerance_contract": packet.tolerance_contract,
        "proposed_provenance": packet.proposed_provenance,
        "contamination": packet.contamination,
        "isolation": packet.isolation,
        "difficulty": packet.difficulty,
        "adversarial_tags": packet.adversarial_tags,
        "parent_candidate_binding": packet.parent_candidate_binding,
    }


def candidate_scientific_projection(packet: CandidateReviewPacket) -> dict[str, object]:
    """Map candidate meaning to final V1 content keys for mutation comparisons."""

    if not isinstance(packet, CandidateReviewPacket):
        raise TypeError("packet must be CandidateReviewPacket")
    return {
        "benchmark_version": packet.benchmark_version,
        "schema_version": packet.schema_version,
        "case_id": packet.candidate_id,
        "case_version": packet.candidate_version,
        "capability_id": packet.capability_id,
        "benchmark_family": packet.benchmark_family,
        "practitioner_question_class": packet.practitioner_question_class,
        "question": packet.question,
        "input": packet.input,
        "source_evidence_refs": packet.source_evidence_refs,
        "expected_answer": packet.proposed_expected_answer,
        "authority": packet.authority,
        "refusal_expectation": packet.refusal_contract,
        "claim_contract": packet.claim_contract,
        "comparability_contract": packet.comparability_contract,
        "scoring_contract": packet.scoring_contract,
        "tolerance_contract": packet.tolerance_contract,
        "provenance": packet.proposed_provenance,
        "contamination": packet.contamination,
        "difficulty": packet.difficulty,
        "adversarial_tags": packet.adversarial_tags,
    }


def _changed_candidate_projection_fields(
    parent: CandidateReviewPacket, child: CandidateReviewPacket
) -> tuple[str, ...]:
    parent_projection = candidate_scientific_projection(parent)
    child_projection = candidate_scientific_projection(child)
    return tuple(
        sorted(
            (
                field_name
                for field_name in parent_projection
                if parent_projection[field_name] != child_projection[field_name]
            ),
            key=lambda item: item.encode("utf-8"),
        )
    )


def candidate_payload_hash(packet: CandidateReviewPacket) -> str:
    """Hash candidate meaning without review workflow fields or a final split."""

    return canonical_hash(candidate_payload_projection(packet))


def proposed_approval_digest(packet: CandidateReviewPacket) -> str:
    """Hash the candidate payload and complete review checklist/status envelope."""

    if not isinstance(packet, CandidateReviewPacket):
        raise TypeError("packet must be CandidateReviewPacket")
    return canonical_hash(
        {
            "candidate_id": packet.candidate_id,
            "candidate_version": packet.candidate_version,
            "candidate_payload_hash": candidate_payload_hash(packet),
            "review_status": packet.review_status,
            "reviewer_checklist": packet.reviewer_checklist,
        }
    )


def bind_candidate_review_packet(packet: CandidateReviewPacket) -> CandidateReviewPacket:
    """Return a packet with both deterministic digests bound in order."""

    if not isinstance(packet, CandidateReviewPacket):
        raise TypeError("packet must be CandidateReviewPacket")
    packet = replace(packet, candidate_payload_hash=candidate_payload_hash(packet))
    return replace(packet, proposed_approval_digest=proposed_approval_digest(packet))


def _validate_source_evidence(
    packet: CandidateReviewPacket, source_resolver: SourceArtifactResolver | None
) -> None:
    excerpts = packet.input.evidence_excerpts
    references = packet.source_evidence_refs
    if not excerpts or not references:
        raise ValueError("source evidence requires both exact excerpts and typed references")
    if source_resolver is None:
        raise ValueError("source-backed candidate validation requires an explicit source resolver")
    if any(reference.reference_kind is not EvidenceKind.SOURCE for reference in references):
        raise ValueError("source-backed candidate references must be SOURCE references")
    if len({excerpt.span_identity.span_id for excerpt in excerpts}) != len(excerpts):
        raise ValueError("candidate source evidence cannot repeat span identities")
    source_families = set()
    artifact_pairs = set()
    span_ids = set()
    documents = set()
    for excerpt in excerpts:
        if not isinstance(excerpt, EvidenceExcerpt):
            raise ValueError("candidate evidence excerpts must be EvidenceExcerpt values")
        document = excerpt.document_identity
        artifact = excerpt.source_artifact_identity
        span = excerpt.span_identity
        _require_text(excerpt.text, "evidence excerpt text")
        expected_span_digest = "sha256:" + hashlib.sha256(excerpt.text.encode("utf-8")).hexdigest()
        if span.span_digest != expected_span_digest:
            raise ValueError("evidence span digest does not match exact excerpt bytes")
        if (artifact.document_id, artifact.document_version) != (
            document.document_id,
            document.version,
        ):
            raise ValueError("source artifact does not bind its exact document version")
        if (span.document_id, span.document_version) != (document.document_id, document.version):
            raise ValueError("evidence span does not bind its exact document version")
        if (span.source_artifact_id, span.source_artifact_digest) != (
            artifact.artifact_id,
            artifact.content_digest,
        ):
            raise ValueError("evidence span does not bind exact source artifact bytes")
        matching_references = tuple(
            reference
            for reference in references
            if reference.document_identity == document
            and reference.source_reference_id == document.document_id
            and reference.version == document.version
            and reference.digest == document.content_digest
            and reference.locator == span.locator
            and reference.scope == excerpt.scope
            and reference.applicability == excerpt.applicability
        )
        if not matching_references:
            raise ValueError("source reference does not bind the exact evidence span")
        resolved = source_resolver.resolve(excerpt)
        if resolved.extracted_text.encode("utf-8") != excerpt.text.encode("utf-8"):
            raise ValueError("evidence excerpt text differs from the exact JATS locator extraction")
        derived_span_digest = (
            "sha256:" + hashlib.sha256(resolved.extracted_text.encode("utf-8")).hexdigest()
        )
        if span.span_digest != derived_span_digest:
            raise ValueError("evidence span digest does not match the exact JATS-derived text")
        family_id, family_digest = resolved.source_family_id, resolved.source_family_digest
        source_families.add((family_id, family_digest))
        artifact_pairs.add((artifact.artifact_id, artifact.content_digest))
        span_ids.add(span.span_id)
        documents.add(document.document_id)
    if len(source_families) != 1:
        raise ValueError("one candidate must resolve to exactly one source-family isolation unit")
    family_id, family_digest = next(iter(source_families))
    if (
        packet.isolation.source_family_id != family_id
        or packet.isolation.source_family_digest != family_digest
        or packet.isolation.isolation_cluster_id != family_id
        or packet.contamination.source_family_id != family_id
    ):
        raise ValueError("candidate source-family/isolation metadata is not registry-bound")
    provenance = packet.proposed_provenance
    if (
        tuple(sorted(artifact_id for artifact_id, _ in artifact_pairs))
        != provenance.source_artifact_ids
    ):
        raise ValueError("provenance source artifact IDs are not canonical registry identities")
    expected_digests = tuple(
        digest for _, digest in sorted(artifact_pairs, key=lambda item: item[0].encode("utf-8"))
    )
    if expected_digests != provenance.source_content_digests:
        raise ValueError("provenance source digests do not bind registered artifact bytes")
    if tuple(sorted(packet.contamination.source_artifact_ids)) != tuple(
        sorted(artifact_id for artifact_id, _ in artifact_pairs)
    ):
        raise ValueError("contamination source artifact IDs do not match evidence identities")
    if set(packet.contamination.document_ids) != documents:
        raise ValueError("contamination document IDs do not match evidence identities")
    if (
        len(provenance.evidence_span_refs) != len(set(provenance.evidence_span_refs))
        or set(provenance.evidence_span_refs) != span_ids
    ):
        raise ValueError("provenance must bind every exact evidence span")
    if (
        packet.contamination.source_content_sha256 is not None
        and packet.contamination.source_content_sha256 not in expected_digests
    ):
        raise ValueError(
            "contamination source digest is absent from registered artifact identities"
        )
    source_authorities = tuple(
        binding
        for binding in packet.authority
        if binding.authority_kind
        in {AuthorityKind.SOURCE_DOCUMENT.value, AuthorityKind.SOURCE_EVIDENCE_SPAN.value}
    )
    authority_kinds = {binding.authority_kind for binding in source_authorities}
    if authority_kinds != {
        AuthorityKind.SOURCE_DOCUMENT.value,
        AuthorityKind.SOURCE_EVIDENCE_SPAN.value,
    }:
        raise ValueError(
            "source-backed candidate requires SOURCE_DOCUMENT and SOURCE_EVIDENCE_SPAN authority"
        )
    for binding in source_authorities:
        if binding.authority_kind == AuthorityKind.SOURCE_DOCUMENT.value:
            matched = any(
                binding.source_reference_id == reference.document_identity.document_id
                and binding.version == reference.document_identity.version
                and binding.digest == reference.document_identity.identity_digest
                for reference in references
                if reference.document_identity is not None
            )
        else:
            matched = any(
                binding.source_reference_id == excerpt.span_identity.span_id
                and binding.version == excerpt.span_identity.document_version
                and binding.digest == excerpt.span_identity.span_digest
                for excerpt in excerpts
            )
        if not matched:
            raise ValueError("source authority binding does not resolve to exact registry evidence")
    for reference in references:
        if not any(
            item.document_identity == reference.document_identity
            and item.span_identity.locator == reference.locator
            and item.scope == reference.scope
            and item.applicability == reference.applicability
            for item in excerpts
        ):
            raise ValueError("source reference has no matching exact evidence span")
        if reference.document_identity is None or not any(
            binding.authority_kind == AuthorityKind.SOURCE_DOCUMENT.value
            and binding.source_reference_id == reference.document_identity.document_id
            and binding.version == reference.document_identity.version
            and binding.digest == reference.document_identity.identity_digest
            for binding in source_authorities
        ):
            raise ValueError("SOURCE_DOCUMENT authority must cover every cited source document")
    for excerpt in excerpts:
        span = excerpt.span_identity
        if not any(
            binding.authority_kind == AuthorityKind.SOURCE_EVIDENCE_SPAN.value
            and binding.source_reference_id == span.span_id
            and binding.version == span.document_version
            and binding.digest == span.span_digest
            for binding in source_authorities
        ):
            raise ValueError("SOURCE_EVIDENCE_SPAN authority must cover every exact evidence span")


def _validate_candidate_origin(
    packet: CandidateReviewPacket, source_resolver: SourceArtifactResolver | None
) -> None:
    provenance = packet.proposed_provenance
    contamination = packet.contamination
    origin = provenance.origin_class
    source_present = bool(packet.source_evidence_refs or packet.input.evidence_excerpts)
    if source_present:
        _validate_source_evidence(packet, source_resolver)
    if origin is CaseOrigin.DETERMINISTIC_SYNTHETIC:
        required = (
            provenance.generator_id,
            provenance.generator_version,
            provenance.generator_family,
            provenance.seed_namespace,
            provenance.seed_block,
            contamination.generator_namespace,
            contamination.generator_seed_block,
        )
        if any(value is None for value in required):
            raise ValueError("deterministic synthetic candidate requires generator/seed metadata")
        if (
            contamination.generator_namespace != provenance.seed_namespace
            or contamination.generator_seed_block != provenance.seed_block
        ):
            raise ValueError("synthetic generator and seed bindings must agree")
        if provenance.generator_registry_digest is None:
            raise ValueError("synthetic candidate requires a generator registry digest")
        if provenance.source_artifact_ids or provenance.source_content_digests or source_present:
            raise ValueError("source/synthetic provenance mixing is not allowed")
        if not any(
            binding.authority_kind == AuthorityKind.GENERATOR.value for binding in packet.authority
        ):
            raise ValueError("deterministic synthetic candidate requires generator authority")
        if any(
            binding.digest != provenance.generator_registry_digest
            for binding in packet.authority
            if binding.authority_kind == AuthorityKind.GENERATOR.value
        ):
            raise ValueError("generator authority does not match proposed provenance")
    elif origin is CaseOrigin.DETERMINISTIC_ENGINE_DERIVED:
        if not provenance.engine_operation_id or not provenance.engine_reference_case_id:
            raise ValueError("engine-derived candidate requires operation and reference identity")
        if provenance.engine_reference_digest is None or provenance.engine_registry_digest is None:
            raise ValueError("engine-derived candidate requires reference and registry digests")
        operation = next(
            (
                binding
                for binding in packet.authority
                if binding.authority_kind == AuthorityKind.RES71_OPERATION.value
                and binding.source_reference_id == provenance.engine_operation_id
            ),
            None,
        )
        reference = next(
            (
                binding
                for binding in packet.authority
                if binding.authority_kind == AuthorityKind.RES71_REFERENCE_CASE.value
                and binding.source_reference_id == provenance.engine_reference_case_id
            ),
            None,
        )
        if operation is None or reference is None:
            raise ValueError(
                "engine-derived candidate requires live RES-71 operation/reference bindings"
            )
        if (
            provenance.engine_method_version != operation.version
            or provenance.engine_registry_digest != operation.digest
            or provenance.engine_reference_digest != reference.digest
            or packet.proposed_expected_answer.reference_case_id
            != provenance.engine_reference_case_id
            or packet.proposed_expected_answer.expected_operation_id
            != provenance.engine_operation_id
        ):
            raise ValueError("engine result, answer, and RES-71 provenance bindings disagree")
        reference_case = get_reference_case(provenance.engine_reference_case_id)
        if reference_case.operation_id != provenance.engine_operation_id:
            raise ValueError("RES-71 reference case does not resolve to the proposed operation")
        if not packet.input.deterministic_results:
            raise ValueError("engine-derived candidate requires a deterministic result view")
        for result in packet.input.deterministic_results:
            if (
                result.operation_id != provenance.engine_operation_id
                or result.method_version != provenance.engine_method_version
                or result.authority_reference != provenance.engine_reference_case_id
                or result.result_or_refusal_digest != provenance.engine_reference_digest
            ):
                raise ValueError("deterministic result view does not match RES-71 provenance")
    elif origin is CaseOrigin.EXPERT_AUTHORED_SEMANTIC:
        if not provenance.authority_lineage:
            raise ValueError("expert semantic candidate requires authority lineage")
        rubric_bindings = tuple(
            binding
            for binding in packet.authority
            if binding.authority_kind == AuthorityKind.EXPERT_RUBRIC.value
        )
        if not rubric_bindings or any(
            binding.digest != provenance.rubric_digest for binding in rubric_bindings
        ):
            raise ValueError("expert semantic candidate requires its exact rubric authority")
    elif origin is CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION:
        if not packet.source_evidence_refs or not packet.input.evidence_excerpts:
            raise ValueError(
                "source-backed candidate requires source evidence references and exact excerpts"
            )
        if source_resolver is None:
            raise ValueError(
                "source-backed candidate validation requires an explicit source resolver"
            )
        if not provenance.source_artifact_ids or not provenance.evidence_span_refs:
            raise ValueError(
                "source-backed candidate requires artifact and evidence-span provenance"
            )
        if (
            provenance.generator_id
            or provenance.seed_namespace
            or contamination.generator_namespace
        ):
            raise ValueError("source-backed candidate cannot carry synthetic generator provenance")
        if packet.proposed_expected_answer.kind is not ExpectedAnswerKind.EVIDENCE_EXTRACTION:
            raise ValueError("source-backed candidate must use EVIDENCE_EXTRACTION answer form")
    elif origin is CaseOrigin.ADVERSARIAL_MUTATION:
        parent_binding = packet.parent_candidate_binding
        if (
            provenance.parent_case_hash is not None
            or parent_binding is None
            or provenance.mutation_operator is None
            or provenance.mutation_version is None
            or provenance.mutation_seed is None
            or not provenance.changed_fields
            or provenance.parent_origin_class is None
            or provenance.mutation_lineage_id is None
        ):
            raise ValueError(
                "adversarial candidate requires a parent-candidate binding and complete "
                "pre-review mutation provenance"
            )
        if _SEMVER_PATTERN.fullmatch(provenance.mutation_version) is None:
            raise ValueError("mutation_version must be a semantic version")
        if (parent_binding.parent_candidate_id, parent_binding.parent_candidate_version) == (
            packet.candidate_id,
            packet.candidate_version,
        ):
            raise ValueError("mutation candidate cannot self-parent")
        if (
            parent_binding.parent_origin_class is not provenance.parent_origin_class
            or parent_binding.mutation_lineage_id != provenance.mutation_lineage_id
        ):
            raise ValueError("mutation parent origin and lineage metadata must agree")
        if any(edge.relation == "MUTATION" for edge in provenance.derivation_edges):
            raise ValueError(
                "pre-review mutation cannot contain a final parent-case derivation edge"
            )
        parent_bindings = tuple(
            binding
            for binding in packet.authority
            if binding.authority_kind == AuthorityKind.MUTATION_PARENT.value
        )
        if len(parent_bindings) != 1:
            raise ValueError("mutation candidate requires exactly one MUTATION_PARENT authority")
        parent_authority = parent_bindings[0]
        if (
            parent_authority.source_reference_id != parent_binding.parent_candidate_id
            or parent_authority.version != parent_binding.parent_candidate_version
            or parent_authority.digest != parent_binding.parent_candidate_payload_hash
        ):
            raise ValueError(
                "MUTATION_PARENT authority must bind the exact parent candidate identity and hash"
            )
    elif packet.parent_candidate_binding is not None:
        raise ValueError("only ADVERSARIAL_MUTATION candidates may bind a parent candidate")


def _candidate_validation_view(packet: CandidateReviewPacket) -> SimpleNamespace:
    """Expose the same answer/scoring fields without constructing a final case."""

    return SimpleNamespace(
        expected_answer=packet.proposed_expected_answer,
        authority=packet.authority,
        refusal_expectation=packet.refusal_contract,
        claim_contract=packet.claim_contract,
        comparability_contract=packet.comparability_contract,
        scoring_contract=packet.scoring_contract,
        tolerance_contract=packet.tolerance_contract,
        provenance=packet.proposed_provenance,
        input=packet.input,
        contamination=packet.contamination,
        source_evidence_refs=packet.source_evidence_refs,
    )


def _validate_candidate_contamination(packet: CandidateReviewPacket) -> None:
    contamination = packet.contamination
    if packet.isolation.source_family_id != contamination.source_family_id:
        raise ValueError("candidate isolation must retain its contamination source family")
    if not contamination.source_family_id or not packet.isolation.isolation_cluster_id:
        raise ValueError("source-family and isolation-cluster identities are required")
    from dynamislm.benchmark.contamination import (
        exact_shingle_digest,
        fuzzy_fingerprint,
        normalized_text_sha256,
    )

    if contamination.normalized_text_sha256 != normalized_text_sha256(packet.question):
        raise ValueError("candidate contamination text digest does not match canonical question")
    if contamination.exact_shingle_digest != exact_shingle_digest(packet.question):
        raise ValueError("candidate contamination shingle digest does not match canonical question")
    if contamination.fuzzy_fingerprint != fuzzy_fingerprint(packet.question):
        raise ValueError("candidate contamination fingerprint does not match canonical question")
    if packet.input.evidence_excerpts and not packet.source_evidence_refs:
        raise ValueError("candidate evidence excerpts require typed source references")


def _validate_res71_numeric_expectations(packet: CandidateReviewPacket) -> None:
    answer = packet.proposed_expected_answer
    numeric_values = _walk_numbers(answer.expected_fields)
    numeric_answer = answer.kind is ExpectedAnswerKind.NUMERIC_RESULT
    if not numeric_values and not numeric_answer:
        return
    if packet.proposed_provenance.origin_class is not CaseOrigin.DETERMINISTIC_ENGINE_DERIVED:
        raise ValueError("numeric expected values require deterministic engine-derived provenance")
    if answer.reference_case_id is None or answer.expected_operation_id is None:
        raise ValueError("numeric expected values require exact RES-71 reference bindings")
    reference_case = get_reference_case(answer.reference_case_id)
    if reference_case.operation_id != answer.expected_operation_id:
        raise ValueError("RES-71 reference output belongs to a different operation")
    if reference_case.status.value != "VALUE":
        raise ValueError("numeric expected values require a RES-71 VALUE reference case")
    registered_values = {value.name: value.value for value in reference_case.expected_values}
    if not registered_values:
        raise ValueError("RES-71 reference case has no registered numeric outputs")
    expected_values = dict(answer.expected_fields.items())
    numeric_fields = {path.split(".", maxsplit=1)[0] for path, _ in numeric_values}
    if any("." in path for path, _ in numeric_values):
        raise ValueError("numeric expected fields must map to registered RES-71 output fields")
    for field_id in numeric_fields:
        if field_id not in registered_values or canonical_hash(
            expected_values[field_id]
        ) != canonical_hash(registered_values[field_id]):
            raise ValueError("numeric expected answer differs from exact RES-71 reference output")
    if numeric_answer and expected_values != registered_values:
        raise ValueError("numeric expected answer differs from exact RES-71 reference output")
    if (
        numeric_answer
        and packet.scoring_contract.profile_id is not ScoringProfile.NUMERIC_TOLERANCE_V1
    ):
        raise ValueError("RES-71 numeric answer requires the numeric tolerance scorer")
    operation_binding = next(
        (
            binding
            for binding in packet.authority
            if binding.authority_kind == AuthorityKind.RES71_OPERATION.value
            and binding.source_reference_id == answer.expected_operation_id
        ),
        None,
    )
    reference_binding = next(
        (
            binding
            for binding in packet.authority
            if binding.authority_kind == AuthorityKind.RES71_REFERENCE_CASE.value
            and binding.source_reference_id == answer.reference_case_id
        ),
        None,
    )
    if operation_binding is None or reference_binding is None:
        raise ValueError("numeric answer requires live RES-71 operation and reference bindings")
    if not packet.input.deterministic_results:
        raise ValueError("numeric expected values require a deterministic result view")
    if any(
        result.operation_id != answer.expected_operation_id
        or result.method_version != operation_binding.version
        or result.authority_reference != answer.reference_case_id
        or result.result_or_refusal_digest != reference_binding.digest
        or canonical_hash(dict(result.values.items())) != canonical_hash(registered_values)
        or result.refusal is not None
        for result in packet.input.deterministic_results
    ):
        raise ValueError("deterministic result view differs from exact RES-71 reference output")
    tolerance = packet.tolerance_contract
    if tolerance is None:
        raise ValueError("numeric expected values require an engine-owned tolerance contract")
    if not numeric_fields.issubset(tolerance.field_ids):
        raise ValueError("numeric tolerance fields do not cover expected RES-71 values")
    if (
        tolerance.absolute_tolerance != reference_case.tolerance_absolute
        or tolerance.relative_tolerance != reference_case.tolerance_relative
    ):
        raise ValueError("numeric tolerance differs from exact RES-71 reference tolerance")
    numeric_units = {
        value.unit
        for value in reference_case.expected_values
        if value.name in numeric_fields and value.unit
    }
    if len(numeric_units) > 1:
        raise ValueError("numeric output fields with different units require separate tolerances")
    if len(numeric_units) == 1:
        unit = next(iter(numeric_units))
        if tolerance.unit != unit or any(
            result.output_unit != unit for result in packet.input.deterministic_results
        ):
            raise ValueError("numeric tolerance/result unit differs from RES-71 output unit")


def _validate_claim_vocabularies(contract: ClaimContract) -> None:
    allowed = set(MEASUREMENT_CLAIM_LEVELS) | set(RELATIONSHIP_CLAIM_LEVELS)
    axis = (
        set(MEASUREMENT_CLAIM_LEVELS)
        if contract.measurement_claim_level is not None
        else set(RELATIONSHIP_CLAIM_LEVELS)
        if contract.relationship_claim_level is not None
        else allowed
    )
    if contract.maximum_supported_claim_level is not None:
        if contract.maximum_supported_claim_level not in allowed:
            raise ValueError("maximum supported claim level is outside the registered vocabulary")
        if contract.maximum_supported_claim_level not in axis:
            raise ValueError("maximum supported claim level crosses the declared claim axis")
    unknown_safe_levels = set(contract.safe_lower_claim_levels) - allowed
    if unknown_safe_levels:
        raise ValueError(
            "safe lower claim levels are outside the registered vocabulary: "
            + ", ".join(sorted(unknown_safe_levels))
        )
    cross_axis_levels = set(contract.safe_lower_claim_levels) - axis
    if cross_axis_levels:
        raise ValueError(
            "safe lower claim levels cross the declared claim axis: "
            + ", ".join(sorted(cross_axis_levels))
        )
    if contract.prediction_status is not None:
        try:
            PredictionStatus(contract.prediction_status)
        except ValueError as exc:
            raise ValueError("prediction status is outside the registered vocabulary") from exc


def validate_candidate_review_packet(
    packet: CandidateReviewPacket,
    *,
    source_resolver: SourceArtifactResolver | None = None,
) -> None:
    """Prove candidate schema, live authority, content hashes, and pre-review state."""

    if not isinstance(packet, CandidateReviewPacket):
        raise TypeError("packet must be CandidateReviewPacket")
    if packet.review_status is not CandidateReviewStatus.PENDING_HUMAN_REVIEW:
        raise ValueError("candidate must remain PENDING_HUMAN_REVIEW")
    if packet.candidate_payload_hash != candidate_payload_hash(packet):
        raise ValueError("candidate payload hash mismatch")
    if packet.proposed_approval_digest != proposed_approval_digest(packet):
        raise ValueError("proposed approval/content digest mismatch")
    if packet.isolation.source_family_id != packet.contamination.source_family_id:
        raise ValueError("candidate source-family/isolation metadata is inconsistent")
    _validate_claim_vocabularies(packet.claim_contract)
    validate_authority_bindings(packet.authority)
    _validate_candidate_origin(packet, source_resolver)
    _validate_candidate_contamination(packet)
    _validate_res71_numeric_expectations(packet)
    view = cast(BenchmarkCaseV1, _candidate_validation_view(packet))
    _validate_answer_contract(view)
    _validate_finite_expected_answer(view)


def _candidate_identity(packet: CandidateReviewPacket) -> tuple[str, str]:
    return packet.candidate_id, packet.candidate_version


def _primary_candidate_authority(packet: CandidateReviewPacket) -> tuple[AuthorityBinding, ...]:
    return tuple(
        binding
        for binding in packet.authority
        if any(
            governed in {"expected_answer", "refusal_expectation", "claim_contract"}
            or governed.startswith("expected_answer.")
            for governed in binding.governed_field_ids
        )
    )


def _candidate_parent_graph(
    packets: tuple[CandidateReviewPacket, ...],
) -> tuple[
    dict[tuple[str, str], CandidateReviewPacket],
    dict[tuple[str, str], tuple[str, str]],
]:
    if not packets:
        raise ValueError("candidate set must be non-empty")
    if any(not isinstance(packet, CandidateReviewPacket) for packet in packets):
        raise TypeError("candidate set must contain CandidateReviewPacket values")
    identities = tuple(_candidate_identity(packet) for packet in packets)
    if len(set(identities)) != len(identities):
        raise ValueError("candidate IDs and versions must be unique in a candidate set")
    if len({packet.candidate_id for packet in packets}) != len(packets):
        raise ValueError("candidate IDs must be unique in a candidate set")
    by_identity = {_candidate_identity(packet): packet for packet in packets}
    parents: dict[tuple[str, str], tuple[str, str]] = {}
    for packet in packets:
        binding = packet.parent_candidate_binding
        is_mutation = packet.proposed_provenance.origin_class is CaseOrigin.ADVERSARIAL_MUTATION
        if is_mutation and binding is None:
            raise ValueError("adversarial mutation candidate is missing its parent candidate")
        if not is_mutation and binding is not None:
            raise ValueError("only mutation candidates may declare a parent candidate")
        if binding is None:
            continue
        identity = _candidate_identity(packet)
        parent_identity = (binding.parent_candidate_id, binding.parent_candidate_version)
        if identity == parent_identity:
            raise ValueError("mutation candidate cannot self-parent")
        if parent_identity not in by_identity:
            raise ValueError("mutation parent candidate is not present in the candidate set")
        parents[identity] = parent_identity

    # Detect graph cycles before hash resolution, so a forged cyclic declaration fails as
    # a cycle even though mutually committed candidate hashes cannot form a valid DAG.
    state: dict[tuple[str, str], int] = {}

    def visit(identity: tuple[str, str]) -> None:
        status = state.get(identity, 0)
        if status == 1:
            raise ValueError("mutation candidate cycle is not allowed")
        if status == 2:
            return
        state[identity] = 1
        parent = parents.get(identity)
        if parent is not None:
            visit(parent)
        state[identity] = 2

    for identity in sorted(by_identity, key=lambda value: (value[0].encode("utf-8"), value[1])):
        visit(identity)
    return by_identity, parents


def validate_candidate_set(
    packets: tuple[CandidateReviewPacket, ...],
    *,
    source_resolver: SourceArtifactResolver | None = None,
) -> None:
    """Validate exact mutation parent commitments, scientific deltas, and isolation."""

    by_identity, parents = _candidate_parent_graph(packets)
    for packet in packets:
        validate_candidate_review_packet(packet, source_resolver=source_resolver)

    lineage_clusters: dict[str, str] = {}
    for identity, parent_identity in parents.items():
        child = by_identity[identity]
        parent = by_identity[parent_identity]
        binding = child.parent_candidate_binding
        assert binding is not None
        provenance = child.proposed_provenance
        if (
            binding.parent_candidate_id != parent.candidate_id
            or binding.parent_candidate_version != parent.candidate_version
            or binding.parent_candidate_payload_hash != parent.candidate_payload_hash
        ):
            raise ValueError("mutation parent candidate ID/version/hash does not match exactly")
        if binding.parent_origin_class is not parent.proposed_provenance.origin_class:
            raise ValueError("mutation parent origin class is not preserved")
        if provenance.parent_origin_class is not parent.proposed_provenance.origin_class:
            raise ValueError("mutation provenance does not preserve the parent origin class")
        if provenance.mutation_lineage_id != binding.mutation_lineage_id:
            raise ValueError("mutation lineage ID disagrees with its parent-candidate binding")
        if parent.proposed_provenance.origin_class is CaseOrigin.ADVERSARIAL_MUTATION:
            if provenance.mutation_lineage_id != parent.proposed_provenance.mutation_lineage_id:
                raise ValueError("mutation descendants must preserve their parent's lineage ID")
        if (
            child.isolation != parent.isolation
            or child.contamination.source_family_id != parent.contamination.source_family_id
        ):
            raise ValueError("mutation lineage must preserve parent isolation metadata")
        prior_cluster = lineage_clusters.setdefault(
            provenance.mutation_lineage_id or "", child.isolation.isolation_cluster_id
        )
        if prior_cluster != child.isolation.isolation_cluster_id:
            raise ValueError("one mutation lineage cannot cross isolation clusters")

        parent_primary_authority = _primary_candidate_authority(parent)
        if not parent_primary_authority:
            raise ValueError("mutation parent has no primary scientific authority")
        if any(binding not in child.authority for binding in parent_primary_authority):
            raise ValueError("mutation candidate dropped parent primary scientific authority")
        validate_authority_bindings(parent.authority)

        actual_changed_fields = _changed_candidate_projection_fields(parent, child)
        declared_changed_fields = tuple(
            sorted(provenance.changed_fields, key=lambda item: item.encode("utf-8"))
        )
        if declared_changed_fields != actual_changed_fields:
            raise ValueError(
                "mutation changed_fields do not match the canonical parent-to-child "
                "candidate scientific projection"
            )


def topological_candidate_promotion_order(
    packets: tuple[CandidateReviewPacket, ...],
    *,
    source_resolver: SourceArtifactResolver | None = None,
) -> tuple[CandidateReviewPacket, ...]:
    """Return a deterministic parent-before-child order for validated candidates."""

    validate_candidate_set(packets, source_resolver=source_resolver)
    by_identity, parents = _candidate_parent_graph(packets)
    ordered: list[CandidateReviewPacket] = []
    emitted: set[tuple[str, str]] = set()

    def emit(identity: tuple[str, str]) -> None:
        if identity in emitted:
            return
        parent = parents.get(identity)
        if parent is not None:
            emit(parent)
        emitted.add(identity)
        ordered.append(by_identity[identity])

    for identity in sorted(by_identity, key=lambda value: (value[0].encode("utf-8"), value[1])):
        emit(identity)
    return tuple(ordered)


def human_approval_record_digest(record: HumanApprovalRecord) -> str:
    """Hash every human-decision field, excluding only its stored digest."""

    if not isinstance(record, HumanApprovalRecord):
        raise TypeError("record must be HumanApprovalRecord")
    return canonical_hash(
        {
            item.name: getattr(record, item.name)
            for item in fields(record)
            if item.name != "approval_record_digest"
        }
    )


def bind_human_approval_record(record: HumanApprovalRecord) -> HumanApprovalRecord:
    """Bind an externally supplied human decision to its immutable record fields."""

    if not isinstance(record, HumanApprovalRecord):
        raise TypeError("record must be HumanApprovalRecord")
    return replace(record, approval_record_digest=human_approval_record_digest(record))


def validate_human_approval_record(record: HumanApprovalRecord) -> None:
    """Validate record integrity and required metadata, not the reviewer's authenticity."""

    if not isinstance(record, HumanApprovalRecord):
        raise TypeError("record must be HumanApprovalRecord")
    if not record.reviewer_id.strip() or record.reviewer_id.casefold() in {
        "unknown",
        "anonymous",
        "agent",
        "assistant",
        "model",
        "system",
    }:
        raise ValueError("human approval record requires a reviewer identity")
    if not record.reviewer_expertise:
        raise ValueError("human approval record requires reviewer expertise metadata")
    _require_aware_timestamp(record.approval_timestamp, "approval_timestamp")
    if record.approval_record_digest != human_approval_record_digest(record):
        raise ValueError("human approval record digest mismatch")


def promotion_receipt_digest(receipt: CasePromotionReceipt) -> str:
    """Hash every receipt link except the stored receipt digest."""

    if not isinstance(receipt, CasePromotionReceipt):
        raise TypeError("receipt must be CasePromotionReceipt")
    return canonical_hash(
        {
            item.name: getattr(receipt, item.name)
            for item in fields(receipt)
            if item.name != "receipt_digest"
        }
    )


def _bind_promotion_receipt(receipt: CasePromotionReceipt) -> CasePromotionReceipt:
    return replace(receipt, receipt_digest=promotion_receipt_digest(receipt))


def _validate_approval_binding(
    packet: CandidateReviewPacket, approval: HumanApprovalRecord
) -> None:
    validate_human_approval_record(approval)
    if approval.decision is not HumanReviewDecision.APPROVED:
        raise ValueError("candidate promotion requires an APPROVED human decision")
    if (
        approval.candidate_id != packet.candidate_id
        or approval.candidate_version != packet.candidate_version
    ):
        raise ValueError("human approval record identifies a different candidate")
    if approval.candidate_payload_hash != packet.candidate_payload_hash:
        raise ValueError("human approval record binds a different candidate hash")
    if approval.reviewed_packet_digest != packet.proposed_approval_digest:
        raise ValueError("human approval record did not review this exact packet digest")
    if approval.reviewer_id == packet.proposed_provenance.author_id:
        raise ValueError("reviewer must be independent of the candidate author")


def _promotion_evidence_chain(
    evidence: ParentPromotionEvidence,
) -> tuple[ParentPromotionEvidence, ...]:
    chain: list[ParentPromotionEvidence] = []
    current: ParentPromotionEvidence | None = evidence
    while current is not None:
        chain.append(current)
        current = current.parent_promotion_evidence
    return tuple(reversed(chain))


def _validated_mutation_promotion_link(
    packet: CandidateReviewPacket,
    evidence: ParentPromotionEvidence | None,
    *,
    source_resolver: SourceArtifactResolver | None = None,
) -> MutationPromotionLink | None:
    is_mutation = packet.proposed_provenance.origin_class is CaseOrigin.ADVERSARIAL_MUTATION
    if not is_mutation:
        if evidence is not None:
            raise ValueError("non-mutation promotion cannot receive parent-promotion evidence")
        return None
    if evidence is None:
        raise ValueError("mutation promotion requires an already promoted parent candidate")
    binding = packet.parent_candidate_binding
    if binding is None:
        raise ValueError("mutation candidate is missing its exact parent-candidate binding")
    validate_promotion_result(
        evidence.packet,
        evidence.approval,
        evidence.result,
        parent_promotion_evidence=evidence.parent_promotion_evidence,
        source_resolver=source_resolver,
    )
    parent_packet = evidence.packet
    parent_case = evidence.result.case
    if (
        binding.parent_candidate_id != parent_packet.candidate_id
        or binding.parent_candidate_version != parent_packet.candidate_version
        or binding.parent_candidate_payload_hash != parent_packet.candidate_payload_hash
        or binding.parent_origin_class is not parent_packet.proposed_provenance.origin_class
        or binding.parent_origin_class is not parent_case.provenance.origin_class
    ):
        raise ValueError("parent promotion does not match the exact reviewed parent candidate")
    lineage_packets = tuple(item.packet for item in _promotion_evidence_chain(evidence))
    validate_candidate_set((*lineage_packets, packet), source_resolver=source_resolver)
    if evidence.result.receipt.final_case_payload_hash != parent_case.case_payload_hash:
        raise ValueError("parent promotion receipt hash does not match its final parent case")
    return MutationPromotionLink(
        parent_candidate_binding=binding,
        parent_case_payload_hash=parent_case.case_payload_hash,
        parent_promotion_receipt_digest=evidence.result.receipt.receipt_digest,
    )


def _build_final_case(
    packet: CandidateReviewPacket,
    approval: HumanApprovalRecord,
    *,
    mutation_promotion_link: MutationPromotionLink | None = None,
) -> BenchmarkCaseV1:
    review = ExpertReviewMetadata(
        author_id=packet.proposed_provenance.author_id,
        reviewer_id=approval.reviewer_id,
        reviewer_expertise=approval.reviewer_expertise,
        approval_status=HumanReviewDecision.APPROVED.value,
        approved_at=approval.approval_timestamp,
        rubric_digest=packet.proposed_provenance.rubric_digest,
        review_scope=packet.proposed_provenance.review_scope,
    )
    provenance = packet.proposed_provenance._to_case_provenance(review)
    authority = packet.authority
    if packet.proposed_provenance.origin_class is CaseOrigin.ADVERSARIAL_MUTATION:
        if mutation_promotion_link is None:
            raise ValueError("mutation promotion requires an exact final parent-case identity")
        parent_hash = mutation_promotion_link.parent_case_payload_hash
        parent_binding = mutation_promotion_link.parent_candidate_binding
        provenance = replace(
            provenance,
            parent_case_hash=parent_hash,
            parent_origin_class=parent_binding.parent_origin_class,
            derivation_edges=(
                *provenance.derivation_edges,
                ProvenanceEdge(parent_hash, packet.candidate_id, "MUTATION"),
            ),
        )
        authority = tuple(
            replace(
                binding,
                version=parent_binding.parent_candidate_version,
                digest=parent_hash,
            )
            if binding.authority_kind == AuthorityKind.MUTATION_PARENT.value
            else binding
            for binding in authority
        )
    case = BenchmarkCaseV1(
        benchmark_version=packet.benchmark_version,
        schema_version=packet.schema_version,
        case_id=packet.candidate_id,
        case_version=packet.candidate_version,
        capability_id=packet.capability_id,
        benchmark_family=packet.benchmark_family,
        practitioner_question_class=packet.practitioner_question_class,
        question=packet.question,
        input=packet.input,
        source_evidence_refs=packet.source_evidence_refs,
        expected_answer=packet.proposed_expected_answer,
        authority=authority,
        refusal_expectation=packet.refusal_contract,
        claim_contract=packet.claim_contract,
        comparability_contract=packet.comparability_contract,
        scoring_contract=packet.scoring_contract,
        tolerance_contract=packet.tolerance_contract,
        provenance=provenance,
        split=SplitBinding(
            split_name=None,
            split_manifest_version=None,
            split_manifest_hash=None,
            allocation_stratum=packet.isolation.allocation_stratum,
            isolation_cluster_id=packet.isolation.isolation_cluster_id,
            membership_digest=None,
        ),
        contamination=packet.contamination,
        difficulty=packet.difficulty,
        adversarial_tags=packet.adversarial_tags,
        case_payload_hash=_ZERO_SHA256,
    )
    from dynamislm.benchmark.hashing import bind_case_payload

    case = bind_case_payload(case)
    validate_case(case)
    return case


def validate_promotion_result(
    packet: CandidateReviewPacket,
    approval: HumanApprovalRecord,
    result: PromotionResult,
    *,
    parent_promotion_evidence: ParentPromotionEvidence | None = None,
    source_resolver: SourceArtifactResolver | None = None,
) -> None:
    """Validate every link from candidate packet through approval to final case."""

    if not isinstance(result, PromotionResult):
        raise TypeError("result must be PromotionResult")
    validate_candidate_review_packet(packet, source_resolver=source_resolver)
    _validate_approval_binding(packet, approval)
    mutation_link = _validated_mutation_promotion_link(
        packet,
        parent_promotion_evidence,
        source_resolver=source_resolver,
    )
    validate_case(result.case)
    expected_case = _build_final_case(packet, approval, mutation_promotion_link=mutation_link)
    if result.case != expected_case:
        raise ValueError("final case payload is not the exact promoted candidate and approval")
    receipt = result.receipt
    if receipt.receipt_digest != promotion_receipt_digest(receipt):
        raise ValueError("promotion receipt digest mismatch")
    expected_links = {
        "candidate_id": packet.candidate_id,
        "candidate_version": packet.candidate_version,
        "candidate_payload_hash": packet.candidate_payload_hash,
        "reviewed_packet_digest": packet.proposed_approval_digest,
        "approval_record_id": approval.approval_record_id,
        "approval_record_digest": approval.approval_record_digest,
        "final_case_id": result.case.case_id,
        "final_case_version": result.case.case_version,
        "final_case_payload_hash": result.case.case_payload_hash,
        "reviewer_id": approval.reviewer_id,
        "approval_timestamp": approval.approval_timestamp,
        "mutation_promotion_link": mutation_link,
    }
    if any(getattr(receipt, name) != value for name, value in expected_links.items()):
        raise ValueError("promotion receipt does not bind the exact candidate, approval, and case")
    if (
        result.case.case_id != packet.candidate_id
        or result.case.case_version != packet.candidate_version
        or result.case.provenance.review.reviewer_id != approval.reviewer_id
        or result.case.provenance.review.approved_at != approval.approval_timestamp
    ):
        raise ValueError("final case does not preserve the candidate and approval identity links")


def promote_with_receipt(
    packet: CandidateReviewPacket,
    approval: HumanApprovalRecord,
    *,
    parent_promotion_evidence: ParentPromotionEvidence | None = None,
    source_resolver: SourceArtifactResolver | None = None,
) -> PromotionResult:
    """Promote a candidate and return its canonical immutable hash-chain receipt.

    The approval record's hash proves only record integrity. This boundary does
    not authenticate the reviewer or attest that a human performed the review.
    """

    validate_candidate_review_packet(packet, source_resolver=source_resolver)
    _validate_approval_binding(packet, approval)
    mutation_link = _validated_mutation_promotion_link(
        packet,
        parent_promotion_evidence,
        source_resolver=source_resolver,
    )
    case = _build_final_case(packet, approval, mutation_promotion_link=mutation_link)
    receipt = _bind_promotion_receipt(
        CasePromotionReceipt(
            candidate_id=packet.candidate_id,
            candidate_version=packet.candidate_version,
            candidate_payload_hash=packet.candidate_payload_hash,
            reviewed_packet_digest=packet.proposed_approval_digest,
            approval_record_id=approval.approval_record_id,
            approval_record_digest=approval.approval_record_digest,
            final_case_id=case.case_id,
            final_case_version=case.case_version,
            final_case_payload_hash=case.case_payload_hash,
            reviewer_id=approval.reviewer_id,
            approval_timestamp=approval.approval_timestamp,
            mutation_promotion_link=mutation_link,
        )
    )
    result = PromotionResult(case=case, receipt=receipt)
    validate_promotion_result(
        packet,
        approval,
        result,
        parent_promotion_evidence=parent_promotion_evidence,
        source_resolver=source_resolver,
    )
    return result


def promote_to_benchmark_case(
    packet: CandidateReviewPacket,
    approval: HumanApprovalRecord,
    *,
    parent_promotion_evidence: ParentPromotionEvidence | None = None,
    source_resolver: SourceArtifactResolver | None = None,
) -> PromotionResult:
    """Compatibility-named boundary returning both the case and receipt."""

    return promote_with_receipt(
        packet,
        approval,
        parent_promotion_evidence=parent_promotion_evidence,
        source_resolver=source_resolver,
    )


__all__ = [
    "CandidateIsolationMetadata",
    "CandidateParentBinding",
    "CandidateReviewChecklistItem",
    "CandidateReviewPacket",
    "CandidateReviewStatus",
    "CasePromotionReceipt",
    "HumanApprovalRecord",
    "HumanReviewDecision",
    "MutationPromotionLink",
    "ParentPromotionEvidence",
    "PromotionResult",
    "ProposedCaseProvenance",
    "bind_candidate_review_packet",
    "bind_human_approval_record",
    "candidate_payload_hash",
    "candidate_payload_projection",
    "candidate_scientific_projection",
    "human_approval_record_digest",
    "promote_to_benchmark_case",
    "promote_with_receipt",
    "promotion_receipt_digest",
    "proposed_approval_digest",
    "topological_candidate_promotion_order",
    "validate_candidate_review_packet",
    "validate_candidate_set",
    "validate_human_approval_record",
    "validate_promotion_result",
]
