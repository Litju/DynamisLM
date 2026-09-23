"""Immutable PerformanceScience-Eval V1 contracts.

These contracts describe benchmark artifacts only.  They do not implement a
scientific operation and deliberately keep deterministic numerical authority
in the RES-71 runtime.
"""

from __future__ import annotations

import datetime as datetime_module
import enum
import hashlib
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, cast

from dynamislm.benchmark._immutable import FrozenMap, freeze_data, freeze_mapping
from dynamislm.benchmark.constants import (
    BENCHMARK_SEMANTIC_VERSION,
    CAPABILITY_IDS,
    CASE_SCHEMA_VERSION,
    EXCLUSION_REGISTRY_VERSION,
    FAMILY_IDS,
    SERIALIZATION_V3,
    SPLIT_MANIFEST_VERSION,
    SPLIT_ORDER,
    CaseOrigin,
    DifficultyLevel,
    ErrorClass,
    EvidenceKind,
    ExpectedAnswerKind,
    FieldScoreStatus,
    InputModality,
    PractitionerQuestionClass,
    RefusalDecision,
    ScoringProfile,
    SplitName,
    TaskOutcome,
)
from dynamislm.claims.models import MeasurementClaimLevel, RelationshipClaimLevel
from dynamislm.comparability.models import ComparabilityState
from dynamislm.refusal.models import RefusalClass
from dynamislm.serialization import canonical_hash, register_serializable_type

_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_HEX_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _text(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")


def _sha(value: str, field_name: str, *, prefixed: bool = True) -> None:
    pattern = _SHA256_RE if prefixed else _HEX_SHA256_RE
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        prefix = "sha256:..." if prefixed else "64 lowercase hexadecimal characters"
        raise ValueError(f"{field_name} must be {prefix}")


def _optional_sha(value: str | None, field_name: str, *, prefixed: bool = True) -> None:
    if value is not None:
        _sha(value, field_name, prefixed=prefixed)


def _strings(values: tuple[str, ...], field_name: str, *, allow_empty: bool = False) -> None:
    if not isinstance(values, tuple):
        raise ValueError(f"{field_name} must be an immutable tuple")
    if not allow_empty and not values:
        raise ValueError(f"{field_name} must not be empty")
    if any(not isinstance(item, str) or not item.strip() for item in values):
        raise ValueError(f"{field_name} must contain non-empty strings")


def _enum[T: enum.Enum](value: T | str, enum_type: type[T], field_name: str) -> T:
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        allowed = tuple(item.value for item in cast(Any, enum_type))
        raise ValueError(f"{field_name} must be one of {allowed}") from exc


def _tuple_of[T](value: tuple[T, ...], field_name: str) -> None:
    if not isinstance(value, tuple):
        raise ValueError(f"{field_name} must be an immutable tuple")


def _aware_timestamp(value: datetime_module.datetime, field_name: str) -> None:
    if not isinstance(value, datetime_module.datetime):
        raise ValueError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include an explicit timezone")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class DocumentIdentity:
    """Bibliographic identity and version of a cited source document."""

    document_id: str
    version: str
    content_digest: str
    doi: str | None = None

    def __post_init__(self) -> None:
        _text(self.document_id, "document_id")
        _text(self.version, "document version")
        _sha(self.content_digest, "document content_digest")
        if self.doi is not None:
            _text(self.doi, "doi")

    @property
    def identity_digest(self) -> str:
        """Hash the complete bibliographic and byte identity binding."""

        return canonical_hash(
            {
                "document_id": self.document_id,
                "version": self.version,
                "content_digest": self.content_digest,
                "doi": self.doi,
            }
        )


@register_serializable_type
@dataclass(frozen=True, slots=True)
class SourceArtifactIdentity:
    """Stored source bytes mapped to the cited document/version."""

    artifact_id: str
    document_id: str
    document_version: str
    artifact_version: str
    content_digest: str

    def __post_init__(self) -> None:
        for name in ("artifact_id", "document_id", "document_version", "artifact_version"):
            _text(getattr(self, name), name)
        _sha(self.content_digest, "source artifact content_digest")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class EvidenceSpanIdentity:
    """Exact span identity and its locator within one source artifact."""

    span_id: str
    document_id: str
    document_version: str
    source_artifact_id: str
    source_artifact_digest: str
    locator: str
    span_digest: str

    def __post_init__(self) -> None:
        for name in (
            "span_id",
            "document_id",
            "document_version",
            "source_artifact_id",
            "locator",
        ):
            _text(getattr(self, name), name)
        _sha(self.source_artifact_digest, "source_artifact_digest")
        _sha(self.span_digest, "span_digest")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class EvidenceReference:
    """A typed source, authority, engine, rubric, or span reference."""

    reference_kind: EvidenceKind
    source_reference_id: str
    version: str
    digest: str
    locator: str
    scope: str
    applicability: str
    document_identity: DocumentIdentity | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "reference_kind", _enum(self.reference_kind, EvidenceKind, "reference_kind")
        )
        for name in ("source_reference_id", "version", "locator", "scope", "applicability"):
            _text(getattr(self, name), name)
        _sha(self.digest, "digest")
        if self.reference_kind is EvidenceKind.SOURCE:
            identity = self.document_identity
            if not isinstance(identity, DocumentIdentity):
                raise ValueError("SOURCE reference requires a typed DocumentIdentity")
            if (
                self.source_reference_id != identity.document_id
                or self.version != identity.version
                or self.digest != identity.content_digest
            ):
                raise ValueError("SOURCE reference must bind its exact document identity")
        elif self.document_identity is not None:
            raise ValueError("non-SOURCE reference cannot carry a DocumentIdentity")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class AuthorityBinding:
    """A case-local binding to an existing scientific authority surface."""

    authority_kind: str
    source_reference_id: str
    version: str
    digest: str
    governed_field_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _text(self.authority_kind, "authority_kind")
        _text(self.source_reference_id, "source_reference_id")
        _text(self.version, "version")
        _sha(self.digest, "digest")
        _strings(self.governed_field_ids, "governed_field_ids")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class ExpertReviewMetadata:
    """Independent expert approval metadata for semantic/rubric content."""

    author_id: str
    reviewer_id: str
    reviewer_expertise: tuple[str, ...]
    approval_status: str
    approved_at: datetime_module.datetime
    rubric_digest: str
    review_scope: str

    def __post_init__(self) -> None:
        for name in ("author_id", "reviewer_id", "approval_status", "review_scope"):
            _text(getattr(self, name), name)
        if self.author_id == self.reviewer_id:
            raise ValueError("expert review must be independent of the author")
        _strings(self.reviewer_expertise, "reviewer_expertise")
        if self.approval_status != "APPROVED":
            raise ValueError("expert review must be APPROVED")
        _aware_timestamp(self.approved_at, "approved_at")
        _sha(self.rubric_digest, "rubric_digest")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class ObservationView:
    """Model-visible observation view preserving identity/result/provenance axes."""

    observation_id: str
    context: Mapping[str, object]
    identity: Mapping[str, object]
    result: Mapping[str, object]
    provenance: Mapping[str, object]

    def __post_init__(self) -> None:
        _text(self.observation_id, "observation_id")
        for name in ("context", "identity", "result", "provenance"):
            frozen = freeze_mapping(getattr(self, name), name)
            object.__setattr__(self, name, frozen)
        if any(key in self.identity for key in ("value", "observed_value", "result")):
            raise ValueError("measurement identity cannot contain an observed result value")
        if not self.result:
            raise ValueError("measurement result view must not be empty")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class DeterministicResultView:
    """A typed RES-71 result/refusal reference exposed to a model."""

    result_reference_id: str
    operation_id: str
    method_version: str
    output_unit: str | None
    result_or_refusal_digest: str
    authority_reference: str
    values: Mapping[str, object]
    refusal: Mapping[str, object] | None = None

    def __post_init__(self) -> None:
        for name in (
            "result_reference_id",
            "operation_id",
            "method_version",
            "authority_reference",
        ):
            _text(getattr(self, name), name)
        if "@" not in self.operation_id:
            raise ValueError("operation_id must include its registered version")
        if self.operation_id.rsplit("@", 1)[1] != self.method_version:
            raise ValueError("method_version must match operation_id")
        if self.output_unit is not None:
            _text(self.output_unit, "output_unit")
        _sha(self.result_or_refusal_digest, "result_or_refusal_digest")
        object.__setattr__(self, "values", freeze_mapping(self.values, "values"))
        if self.refusal is not None:
            object.__setattr__(self, "refusal", freeze_mapping(self.refusal, "refusal"))


@register_serializable_type
@dataclass(frozen=True, slots=True)
class EvidenceExcerpt:
    """An exact excerpt mapped through document, source artifact, and span IDs."""

    document_identity: DocumentIdentity
    source_artifact_identity: SourceArtifactIdentity
    span_identity: EvidenceSpanIdentity
    text: str
    scope: str
    applicability: str

    def __post_init__(self) -> None:
        if not isinstance(self.document_identity, DocumentIdentity):
            raise ValueError("evidence excerpt requires DocumentIdentity")
        if not isinstance(self.source_artifact_identity, SourceArtifactIdentity):
            raise ValueError("evidence excerpt requires SourceArtifactIdentity")
        if not isinstance(self.span_identity, EvidenceSpanIdentity):
            raise ValueError("evidence excerpt requires EvidenceSpanIdentity")
        for name in ("text", "scope", "applicability"):
            _text(getattr(self, name), name)
        document = self.document_identity
        artifact = self.source_artifact_identity
        span = self.span_identity
        if (artifact.document_id, artifact.document_version) != (
            document.document_id,
            document.version,
        ):
            raise ValueError("source artifact must map to its exact document version")
        if (span.document_id, span.document_version) != (document.document_id, document.version):
            raise ValueError("evidence span must map to its exact document version")
        if (span.source_artifact_id, span.source_artifact_digest) != (
            artifact.artifact_id,
            artifact.content_digest,
        ):
            raise ValueError("evidence span must map to its exact source artifact bytes")
        expected_span_digest = "sha256:" + hashlib.sha256(self.text.encode("utf-8")).hexdigest()
        if span.span_digest != expected_span_digest:
            raise ValueError("evidence span digest must hash the exact excerpt text bytes")

    @property
    def excerpt_id(self) -> str:
        """Compatibility read-only alias for the exact span identity."""

        return self.span_identity.span_id

    @property
    def locator(self) -> str:
        return self.span_identity.locator


@register_serializable_type
@dataclass(frozen=True, slots=True)
class InputContract:
    """Canonical model-visible input envelope."""

    modality: tuple[InputModality | str, ...]
    question_text: str
    structured_context: Mapping[str, object]
    observations: tuple[ObservationView, ...] = ()
    deterministic_results: tuple[DeterministicResultView, ...] = ()
    evidence_excerpts: tuple[EvidenceExcerpt, ...] = ()
    missing_information: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        modalities = tuple(_enum(item, InputModality, "modality") for item in self.modality)
        object.__setattr__(self, "modality", modalities)
        if not modalities:
            raise ValueError("input modality must not be empty")
        _text(self.question_text, "question_text")
        object.__setattr__(
            self,
            "structured_context",
            freeze_mapping(self.structured_context, "structured_context"),
        )
        _tuple_of(self.observations, "observations")
        _tuple_of(self.deterministic_results, "deterministic_results")
        _tuple_of(self.evidence_excerpts, "evidence_excerpts")
        _strings(self.missing_information, "missing_information", allow_empty=True)
        if any(not isinstance(item, ObservationView) for item in self.observations):
            raise ValueError("observations must contain ObservationView values")
        if any(
            not isinstance(item, DeterministicResultView) for item in self.deterministic_results
        ):
            raise ValueError("deterministic_results must contain DeterministicResultView values")
        if any(not isinstance(item, EvidenceExcerpt) for item in self.evidence_excerpts):
            raise ValueError("evidence_excerpts must contain EvidenceExcerpt values")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class RefusalExpectation:
    """Claim-specific refusal expectation, including safe fallback detail."""

    decision: RefusalDecision
    blocked_claim: str | None
    refusal_class: RefusalClass | None
    reason_codes: tuple[str, ...]
    missing_information: tuple[str, ...]
    what_can_still_be_safely_described: tuple[str, ...]
    safe_lower_claim_level: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "decision", _enum(self.decision, RefusalDecision, "decision"))
        if self.refusal_class is not None:
            object.__setattr__(
                self, "refusal_class", _enum(self.refusal_class, RefusalClass, "refusal_class")
            )
        if self.blocked_claim is not None:
            _text(self.blocked_claim, "blocked_claim")
        _strings(self.reason_codes, "reason_codes", allow_empty=True)
        _strings(self.missing_information, "missing_information", allow_empty=True)
        _strings(
            self.what_can_still_be_safely_described,
            "what_can_still_be_safely_described",
            allow_empty=True,
        )
        if self.decision is RefusalDecision.REQUIRED:
            if self.blocked_claim is None or self.refusal_class is None:
                raise ValueError("required refusal must identify blocked claim and refusal class")
            if not self.reason_codes:
                raise ValueError("required refusal must include reason codes")
            if not self.what_can_still_be_safely_described:
                raise ValueError("required refusal must preserve safe lower-level descriptions")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class ExpectedStructuredAnswer:
    """Discriminated structured answer; prose alone is never ground truth."""

    kind: ExpectedAnswerKind
    required_field_ids: tuple[str, ...]
    expected_fields: Mapping[str, object]
    accepted_aliases: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    prohibited_claims: tuple[str, ...] = ()
    safe_lower_level_descriptions: tuple[str, ...] = ()
    reference_case_id: str | None = None
    expected_operation_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", _enum(self.kind, ExpectedAnswerKind, "kind"))
        _strings(self.required_field_ids, "required_field_ids")
        object.__setattr__(
            self, "expected_fields", freeze_mapping(self.expected_fields, "expected_fields")
        )
        aliases = dict(self.accepted_aliases.items())
        for field_id, values in aliases.items():
            _text(field_id, "accepted_aliases field")
            if not isinstance(values, tuple):
                raise ValueError("accepted alias values must be immutable tuples")
            _strings(values, "accepted_aliases values", allow_empty=True)
        object.__setattr__(
            self,
            "accepted_aliases",
            FrozenMap({key: tuple(values) for key, values in aliases.items()}),
        )
        _strings(self.prohibited_claims, "prohibited_claims", allow_empty=True)
        _strings(
            self.safe_lower_level_descriptions,
            "safe_lower_level_descriptions",
            allow_empty=True,
        )
        if self.reference_case_id is not None:
            _text(self.reference_case_id, "reference_case_id")
        if self.expected_operation_id is not None:
            _text(self.expected_operation_id, "expected_operation_id")
        if self.kind is ExpectedAnswerKind.NUMERIC_RESULT:
            if self.reference_case_id is None or self.expected_operation_id is None:
                raise ValueError("numeric answer must bind a RES-71 reference case and operation")
        if self.kind is ExpectedAnswerKind.REFUSAL and not self.prohibited_claims:
            raise ValueError("refusal answer must identify prohibited claim boundary")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class ClaimContract:
    """Axis-specific requested and maximum claim contract."""

    requested_claim: str
    maximum_supported_claim_level: str | None
    safe_lower_claim_levels: tuple[str, ...]
    prohibited_escalation: tuple[str, ...]
    measurement_claim_level: MeasurementClaimLevel | None = None
    relationship_claim_level: RelationshipClaimLevel | None = None
    prediction_status: str | None = None

    def __post_init__(self) -> None:
        _text(self.requested_claim, "requested_claim")
        if self.maximum_supported_claim_level is not None:
            _text(self.maximum_supported_claim_level, "maximum_supported_claim_level")
        _strings(self.safe_lower_claim_levels, "safe_lower_claim_levels", allow_empty=True)
        _strings(self.prohibited_escalation, "prohibited_escalation", allow_empty=True)
        if self.measurement_claim_level is not None:
            object.__setattr__(
                self,
                "measurement_claim_level",
                _enum(
                    self.measurement_claim_level, MeasurementClaimLevel, "measurement_claim_level"
                ),
            )
        if self.relationship_claim_level is not None:
            object.__setattr__(
                self,
                "relationship_claim_level",
                _enum(
                    self.relationship_claim_level,
                    RelationshipClaimLevel,
                    "relationship_claim_level",
                ),
            )
        if self.measurement_claim_level is not None and self.relationship_claim_level is not None:
            raise ValueError("claim contract cannot mix measurement and relationship axes")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class ComparabilityContract:
    """Claim-relative pairwise comparability expectation."""

    requested_state: ComparabilityState | None
    material_dimensions: tuple[str, ...]
    dimension_findings: Mapping[str, object]
    conditions: tuple[str, ...]
    transformations_required: tuple[str, ...]
    not_applicable: bool = False
    rule_reference: str | None = None

    def __post_init__(self) -> None:
        if self.requested_state is not None:
            object.__setattr__(
                self,
                "requested_state",
                _enum(self.requested_state, ComparabilityState, "requested_state"),
            )
        _strings(self.material_dimensions, "material_dimensions", allow_empty=True)
        object.__setattr__(
            self,
            "dimension_findings",
            freeze_mapping(self.dimension_findings, "dimension_findings"),
        )
        _strings(self.conditions, "conditions", allow_empty=True)
        _strings(self.transformations_required, "transformations_required", allow_empty=True)
        if self.rule_reference is not None:
            _text(self.rule_reference, "rule_reference")
        if self.not_applicable and self.requested_state is not None:
            raise ValueError("not-applicable comparability cannot carry a requested state")
        if not self.not_applicable and self.requested_state is None:
            raise ValueError("comparability contract needs a state or explicit not-applicable flag")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class ScoringContract:
    """Case-local scorer profile and required structured fields."""

    profile_id: ScoringProfile
    profile_version: str
    required_output_fields: tuple[str, ...]
    critical_fields: tuple[str, ...]
    accepted_normalization: tuple[str, ...]
    error_class_rules: tuple[ErrorClass, ...]
    task_status_policy: str
    error_attribution: tuple[tuple[str, ErrorClass], ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "profile_id", _enum(self.profile_id, ScoringProfile, "profile_id"))
        _text(self.profile_version, "profile_version")
        _strings(self.required_output_fields, "required_output_fields")
        _strings(self.critical_fields, "critical_fields", allow_empty=True)
        if any(item not in self.required_output_fields for item in self.critical_fields):
            raise ValueError("critical scoring fields must be required output fields")
        _strings(self.accepted_normalization, "accepted_normalization", allow_empty=True)
        errors = tuple(
            _enum(item, ErrorClass, "error_class_rules") for item in self.error_class_rules
        )
        object.__setattr__(self, "error_class_rules", errors)
        _text(self.task_status_policy, "task_status_policy")
        raw_attribution = self.error_attribution
        if isinstance(raw_attribution, Mapping):
            raw_attribution = tuple(raw_attribution.items())
        _tuple_of(raw_attribution, "error_attribution")
        attribution: list[tuple[str, ErrorClass]] = []
        for item in raw_attribution:
            if not isinstance(item, tuple) or len(item) != 2:
                raise ValueError("error_attribution entries must be (field_id, error_class) tuples")
            field_id, error_class = item
            _text(field_id, "error_attribution field_id")
            attribution.append((field_id, _enum(error_class, ErrorClass, "error_attribution")))
        if len({field_id for field_id, _ in attribution}) != len(attribution):
            raise ValueError("error_attribution cannot contain duplicate field IDs")
        if any(error_class not in errors for _, error_class in attribution):
            raise ValueError("error_attribution may only use declared error_class_rules")
        object.__setattr__(self, "error_attribution", tuple(attribution))


@register_serializable_type
@dataclass(frozen=True, slots=True)
class ToleranceContract:
    """Engine-owned numeric tolerance; expected-zero uses absolute tolerance only."""

    field_ids: tuple[str, ...]
    unit: str
    absolute_tolerance: float
    relative_tolerance: float
    finite_value_rule: str = "FINITE_ONLY"
    comparison_rule: str = "ABS_OR_RELATIVE_EXCEPT_ZERO"

    def __post_init__(self) -> None:
        _strings(self.field_ids, "field_ids")
        _text(self.unit, "unit")
        for name in ("absolute_tolerance", "relative_tolerance"):
            value = getattr(self, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, int | float)
                or not math.isfinite(value)
            ):
                raise ValueError(f"{name} must be finite")
            if value < 0:
                raise ValueError(f"{name} must be non-negative")
        if self.finite_value_rule != "FINITE_ONLY":
            raise ValueError("unsupported finite-value rule")
        if self.comparison_rule != "ABS_OR_RELATIVE_EXCEPT_ZERO":
            raise ValueError("unsupported numeric comparison rule")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class ProvenanceEdge:
    """One explicit dependency edge in a case derivation graph."""

    upstream_id: str
    downstream_id: str
    relation: str

    def __post_init__(self) -> None:
        _text(self.upstream_id, "upstream_id")
        _text(self.downstream_id, "downstream_id")
        _text(self.relation, "relation")
        if self.upstream_id == self.downstream_id:
            raise ValueError("provenance edge cannot be self-referential")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class CaseProvenance:
    """Case-local provenance and origin metadata."""

    origin_class: CaseOrigin
    review: ExpertReviewMetadata
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
        object.__setattr__(
            self, "origin_class", _enum(self.origin_class, CaseOrigin, "origin_class")
        )
        if self.parent_origin_class is not None:
            object.__setattr__(
                self,
                "parent_origin_class",
                _enum(self.parent_origin_class, CaseOrigin, "parent_origin_class"),
            )
        if not isinstance(self.review, ExpertReviewMetadata):
            raise ValueError("provenance review must be ExpertReviewMetadata")
        _strings(self.authority_lineage, "authority_lineage")
        _text(self.population_scope, "population_scope")
        _text(self.derivation_status, "derivation_status")
        _tuple_of(self.derivation_edges, "derivation_edges")
        if any(not isinstance(item, ProvenanceEdge) for item in self.derivation_edges):
            raise ValueError("derivation_edges must contain ProvenanceEdge values")
        for field_name, values in (
            ("source_artifact_ids", self.source_artifact_ids),
            ("source_content_digests", self.source_content_digests),
            ("evidence_span_refs", self.evidence_span_refs),
            ("changed_fields", self.changed_fields),
        ):
            _strings(values, field_name, allow_empty=True)
        for digest in self.source_content_digests:
            _sha(digest, "source_content_digests item")
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
                _text(value, name)
        _optional_sha(self.parent_case_hash, "parent_case_hash")
        _optional_sha(self.engine_reference_digest, "engine_reference_digest")
        _optional_sha(self.engine_registry_digest, "engine_registry_digest")
        _optional_sha(self.generator_registry_digest, "generator_registry_digest")
        if self.mutation_seed is not None and (
            isinstance(self.mutation_seed, bool) or self.mutation_seed < 0
        ):
            raise ValueError("mutation_seed must be a non-negative integer")
        if self.serialization_version != SERIALIZATION_V3:
            raise ValueError("benchmark provenance must use Serialization V3")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class SplitBinding:
    """Split metadata attached after case-content hashing."""

    split_name: SplitName | None
    split_manifest_version: str | None
    split_manifest_hash: str | None
    allocation_stratum: str
    isolation_cluster_id: str
    membership_digest: str | None

    def __post_init__(self) -> None:
        if self.split_name is not None:
            object.__setattr__(self, "split_name", _enum(self.split_name, SplitName, "split_name"))
        _text(self.allocation_stratum, "allocation_stratum")
        _text(self.isolation_cluster_id, "isolation_cluster_id")
        if self.split_name is None:
            if any(
                value is not None
                for value in (
                    self.split_manifest_version,
                    self.split_manifest_hash,
                    self.membership_digest,
                )
            ):
                raise ValueError("unassigned split cannot carry aggregate bindings")
        else:
            provisional = (
                self.split_manifest_version is None
                and self.split_manifest_hash is None
                and self.membership_digest is None
            )
            if not provisional:
                if self.split_manifest_version != SPLIT_MANIFEST_VERSION:
                    raise ValueError("assigned case must use split-manifest@1.0.0")
                _sha(cast(str, self.split_manifest_hash), "split_manifest_hash")
                _sha(cast(str, self.membership_digest), "membership_digest")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class ContaminationBinding:
    """Case-local fingerprints and typed source/document isolation identities."""

    source_artifact_ids: tuple[str, ...]
    document_ids: tuple[str, ...]
    source_family_id: str
    provider_export_id: str | None
    protocol_template_id: str | None
    expert_author_batch_id: str | None
    artifact_ids: tuple[str, ...]
    source_content_sha256: str | None
    normalized_text_sha256: str | None
    exact_shingle_digest: str
    fuzzy_fingerprint: str
    semantic_cluster_id: str | None
    generator_namespace: str | None
    generator_seed_block: str | None
    benchmark_artifact_ids: tuple[str, ...]
    training_exclusion_ids: tuple[str, ...]
    construct_test_identity_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name, values in (
            ("source_artifact_ids", self.source_artifact_ids),
            ("document_ids", self.document_ids),
            ("artifact_ids", self.artifact_ids),
            ("benchmark_artifact_ids", self.benchmark_artifact_ids),
            ("training_exclusion_ids", self.training_exclusion_ids),
            ("construct_test_identity_ids", self.construct_test_identity_ids),
        ):
            _strings(values, name, allow_empty=True)
        _text(self.source_family_id, "source_family_id")
        for name in (
            "provider_export_id",
            "protocol_template_id",
            "expert_author_batch_id",
            "semantic_cluster_id",
            "generator_namespace",
            "generator_seed_block",
        ):
            value = getattr(self, name)
            if value is not None:
                _text(value, name)
        _optional_sha(self.source_content_sha256, "source_content_sha256")
        _optional_sha(self.normalized_text_sha256, "normalized_text_sha256")
        _sha(self.exact_shingle_digest, "exact_shingle_digest")
        _sha(self.fuzzy_fingerprint, "fuzzy_fingerprint")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class DifficultyBinding:
    level: DifficultyLevel
    rationale: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "level", _enum(self.level, DifficultyLevel, "level"))
        _text(self.rationale, "rationale")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class RES71RuntimeBinding:
    """Exact V1 binding to the qualified RES-71 reference interface."""

    interface_id: str
    interface_version: str
    interface_binding: str
    sealed_reference_digest: str
    serialization_version: int
    qualified_content_head: str
    gate_receipt: str
    gate_runtime_validator: str
    gate_validation: str

    def __post_init__(self) -> None:
        for name in (
            "interface_id",
            "interface_version",
            "interface_binding",
            "gate_receipt",
            "gate_runtime_validator",
            "gate_validation",
        ):
            _text(getattr(self, name), name)
        _sha(self.sealed_reference_digest, "sealed_reference_digest")
        if self.serialization_version != SERIALIZATION_V3:
            raise ValueError("RES-71 binding must use Serialization V3")
        if not re.fullmatch(r"[0-9a-f]{40}", self.qualified_content_head):
            raise ValueError("qualified_content_head must be a full lowercase SHA")
        if self.gate_validation != "PASS":
            raise ValueError("RES-71 gate validation must be PASS")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class RES71OperationBinding:
    """Live inventory/reference binding for an engine-derived case."""

    operation_id: str
    method_version: str
    scientific_family: str
    disposition: str
    operation_inventory_digest: str
    input_contract: str
    output_contract: str
    provenance_contract: str
    refusal_path: tuple[str, ...]
    tolerance_contract: str
    authority_references: tuple[str, ...]
    runtime_binding: RES71RuntimeBinding
    reference_case_id: str | None
    reference_case_digest: str | None

    def __post_init__(self) -> None:
        for name in (
            "operation_id",
            "method_version",
            "scientific_family",
            "disposition",
            "input_contract",
            "output_contract",
            "provenance_contract",
            "tolerance_contract",
        ):
            _text(getattr(self, name), name)
        if (
            "@" not in self.operation_id
            or self.operation_id.rsplit("@", 1)[1] != self.method_version
        ):
            raise ValueError("RES-71 operation and method versions must agree")
        _sha(self.operation_inventory_digest, "operation_inventory_digest")
        _strings(self.refusal_path, "refusal_path")
        _strings(self.authority_references, "authority_references")
        if not isinstance(self.runtime_binding, RES71RuntimeBinding):
            raise ValueError("runtime_binding must be RES71RuntimeBinding")
        if self.reference_case_id is None:
            if self.reference_case_digest is not None:
                raise ValueError("reference_case_digest requires reference_case_id")
        else:
            _text(self.reference_case_id, "reference_case_id")
            _sha(cast(str, self.reference_case_digest), "reference_case_digest")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class RES71RefusalBinding:
    """Binding to a canonical RES-71 unresolved computation/refusal route."""

    capability: str
    registered_operation_id: str | None
    disposition: str
    expected_refusal_class: str
    expected_reason_codes: tuple[str, ...]
    safe_description: str
    unresolved_inventory_digest: str
    refusal_path: tuple[str, ...]
    authority_references: tuple[str, ...]
    runtime_binding: RES71RuntimeBinding

    def __post_init__(self) -> None:
        for name in ("capability", "disposition", "expected_refusal_class", "safe_description"):
            _text(getattr(self, name), name)
        if self.registered_operation_id is not None:
            _text(self.registered_operation_id, "registered_operation_id")
        _strings(self.expected_reason_codes, "expected_reason_codes")
        _sha(self.unresolved_inventory_digest, "unresolved_inventory_digest")
        _strings(self.refusal_path, "refusal_path")
        _strings(self.authority_references, "authority_references")
        if not isinstance(self.runtime_binding, RES71RuntimeBinding):
            raise ValueError("runtime_binding must be RES71RuntimeBinding")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class BenchmarkCaseV1:
    """The immutable, hash-addressed V1 benchmark case."""

    benchmark_version: str
    schema_version: str
    case_id: str
    case_version: str
    capability_id: str
    benchmark_family: str
    practitioner_question_class: PractitionerQuestionClass
    question: str
    input: InputContract
    source_evidence_refs: tuple[EvidenceReference, ...]
    expected_answer: ExpectedStructuredAnswer
    authority: tuple[AuthorityBinding, ...]
    refusal_expectation: RefusalExpectation
    claim_contract: ClaimContract
    comparability_contract: ComparabilityContract
    scoring_contract: ScoringContract
    tolerance_contract: ToleranceContract | None
    provenance: CaseProvenance
    split: SplitBinding
    contamination: ContaminationBinding
    difficulty: DifficultyBinding
    adversarial_tags: tuple[str, ...]
    case_payload_hash: str

    def __post_init__(self) -> None:
        if self.benchmark_version != BENCHMARK_SEMANTIC_VERSION:
            raise ValueError("unsupported benchmark semantic version")
        if self.schema_version != CASE_SCHEMA_VERSION:
            raise ValueError("unsupported case schema version")
        for name in ("case_id", "case_version"):
            _text(getattr(self, name), name)
        if self.case_id.startswith("sha256:"):
            raise ValueError("case_id is an identity, not a content hash")
        if self.capability_id not in CAPABILITY_IDS:
            raise ValueError("unknown capability_id")
        if self.benchmark_family not in FAMILY_IDS:
            raise ValueError("unknown benchmark_family")
        object.__setattr__(
            self,
            "practitioner_question_class",
            _enum(
                self.practitioner_question_class,
                PractitionerQuestionClass,
                "practitioner_question_class",
            ),
        )
        _text(self.question, "question")
        if self.input.question_text != self.question:
            raise ValueError("input.question_text must equal the canonical case question")
        for name in (
            "source_evidence_refs",
            "authority",
            "adversarial_tags",
        ):
            _tuple_of(getattr(self, name), name)
        if any(not isinstance(item, EvidenceReference) for item in self.source_evidence_refs):
            raise ValueError("source_evidence_refs must contain EvidenceReference values")
        if not self.authority or any(
            not isinstance(item, AuthorityBinding) for item in self.authority
        ):
            raise ValueError("case requires typed authority bindings")
        _strings(self.adversarial_tags, "adversarial_tags")
        for name in (
            "input",
            "expected_answer",
            "refusal_expectation",
            "claim_contract",
            "comparability_contract",
            "scoring_contract",
            "provenance",
            "split",
            "contamination",
            "difficulty",
        ):
            if getattr(self, name) is None:
                raise ValueError(f"{name} is required")
        _sha(self.case_payload_hash, "case_payload_hash")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class SplitMembershipRecordV1:
    benchmark_version: str
    split_manifest_version: str
    split_name: SplitName
    case_id: str
    case_payload_hash: str
    allocation_stratum: str
    isolation_cluster_id: str

    def __post_init__(self) -> None:
        if self.benchmark_version != BENCHMARK_SEMANTIC_VERSION:
            raise ValueError("split record benchmark version mismatch")
        if self.split_manifest_version != SPLIT_MANIFEST_VERSION:
            raise ValueError("split record manifest version mismatch")
        object.__setattr__(self, "split_name", _enum(self.split_name, SplitName, "split_name"))
        for name in ("case_id", "allocation_stratum", "isolation_cluster_id"):
            _text(getattr(self, name), name)
        _sha(self.case_payload_hash, "case_payload_hash")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class SplitManifestV1:
    benchmark_version: str
    split_manifest_version: str
    split_name: SplitName
    target_case_count: int
    membership_records: tuple[SplitMembershipRecordV1, ...]
    split_manifest_hash: str

    def __post_init__(self) -> None:
        if self.benchmark_version != BENCHMARK_SEMANTIC_VERSION:
            raise ValueError("split manifest benchmark version mismatch")
        if self.split_manifest_version != SPLIT_MANIFEST_VERSION:
            raise ValueError("split manifest version mismatch")
        object.__setattr__(self, "split_name", _enum(self.split_name, SplitName, "split_name"))
        if isinstance(self.target_case_count, bool) or self.target_case_count < 0:
            raise ValueError("target_case_count must be a non-negative integer")
        _tuple_of(self.membership_records, "membership_records")
        if any(not isinstance(item, SplitMembershipRecordV1) for item in self.membership_records):
            raise ValueError("membership_records must be typed")
        if self.target_case_count != len(self.membership_records):
            raise ValueError("split target count must equal membership count")
        _sha(self.split_manifest_hash, "split_manifest_hash")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class AuthorityManifestEntry:
    case_id: str
    bindings: tuple[AuthorityBinding, ...]

    def __post_init__(self) -> None:
        _text(self.case_id, "case_id")
        _tuple_of(self.bindings, "bindings")
        if not self.bindings or any(
            not isinstance(item, AuthorityBinding) for item in self.bindings
        ):
            raise ValueError("authority manifest entry needs typed bindings")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class AuthorityManifestV1:
    benchmark_version: str
    entries: tuple[AuthorityManifestEntry, ...]
    runtime_binding: RES71RuntimeBinding
    authority_manifest_hash: str

    def __post_init__(self) -> None:
        if self.benchmark_version != BENCHMARK_SEMANTIC_VERSION:
            raise ValueError("authority manifest benchmark version mismatch")
        _tuple_of(self.entries, "authority manifest entries")
        if any(not isinstance(item, AuthorityManifestEntry) for item in self.entries):
            raise ValueError("authority manifest entries must be typed")
        if not isinstance(self.runtime_binding, RES71RuntimeBinding):
            raise ValueError("authority manifest needs RES-71 runtime binding")
        _sha(self.authority_manifest_hash, "authority_manifest_hash")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class ScorerManifestEntry:
    case_id: str
    contract: ScoringContract
    profile_definition_digest: str

    def __post_init__(self) -> None:
        _text(self.case_id, "case_id")
        if not isinstance(self.contract, ScoringContract):
            raise ValueError("scorer manifest contract must be typed")
        _sha(self.profile_definition_digest, "profile_definition_digest")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class ScorerManifestV1:
    benchmark_version: str
    entries: tuple[ScorerManifestEntry, ...]
    scorer_manifest_hash: str

    def __post_init__(self) -> None:
        if self.benchmark_version != BENCHMARK_SEMANTIC_VERSION:
            raise ValueError("scorer manifest benchmark version mismatch")
        _tuple_of(self.entries, "scorer manifest entries")
        if any(not isinstance(item, ScorerManifestEntry) for item in self.entries):
            raise ValueError("scorer manifest entries must be typed")
        _sha(self.scorer_manifest_hash, "scorer_manifest_hash")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class ExclusionEntry:
    """Manifest record for one artifact plus its optional typed source mapping."""

    artifact_id: str
    document_id: str | None
    document_content_digest: str | None
    source_artifact_id: str | None
    source_artifact_digest: str | None
    normalized_doi: str | None
    canonical_url: str | None
    source_family_id: str
    source_content_sha256: str | None
    normalized_text_sha256: str | None
    exact_shingle_digest: str
    fuzzy_fingerprint: str
    semantic_cluster_id: str | None
    benchmark_case_ids: tuple[str, ...]
    benchmark_case_hashes: tuple[str, ...]
    split_names: tuple[SplitName, ...]
    exclusion_reason: str
    membership_digests: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("artifact_id", "source_family_id", "exclusion_reason"):
            _text(getattr(self, name), name)
        for name in (
            "document_id",
            "document_content_digest",
            "source_artifact_id",
            "source_artifact_digest",
            "normalized_doi",
            "canonical_url",
            "semantic_cluster_id",
        ):
            value = getattr(self, name)
            if value is not None:
                _text(value, name)
        _optional_sha(self.document_content_digest, "document_content_digest")
        _optional_sha(self.source_artifact_digest, "source_artifact_digest")
        if self.document_content_digest is not None and self.document_id is None:
            raise ValueError("document digest requires a document identity")
        if self.normalized_doi is not None and self.document_id is None:
            raise ValueError("DOI requires a document identity")
        if (self.source_artifact_id is None) != (self.source_artifact_digest is None):
            raise ValueError("source artifact identity and stored-byte digest must align")
        if self.artifact_id.startswith("document:"):
            expected_document_id = self.artifact_id.removeprefix("document:")
            if self.document_id != expected_document_id:
                raise ValueError("document exclusion artifact ID must map to its document ID")
        if self.artifact_id.startswith("source:"):
            expected_source_artifact_id = self.artifact_id.removeprefix("source:")
            if self.source_artifact_id != expected_source_artifact_id:
                raise ValueError("source exclusion artifact ID must map to its source artifact ID")
        _optional_sha(self.source_content_sha256, "source_content_sha256")
        _optional_sha(self.normalized_text_sha256, "normalized_text_sha256")
        _sha(self.exact_shingle_digest, "exact_shingle_digest")
        _sha(self.fuzzy_fingerprint, "fuzzy_fingerprint")
        _strings(self.benchmark_case_ids, "benchmark_case_ids", allow_empty=True)
        if len(set(self.benchmark_case_ids)) != len(self.benchmark_case_ids):
            raise ValueError("an exclusion artifact cannot associate the same case more than once")
        if self.benchmark_case_ids != tuple(
            sorted(self.benchmark_case_ids, key=lambda item: item.encode("utf-8"))
        ):
            raise ValueError("exclusion case associations must use canonical case-ID ordering")
        for item in self.benchmark_case_hashes:
            _sha(item, "benchmark_case_hashes item")
        if len(self.benchmark_case_ids) != len(self.benchmark_case_hashes):
            raise ValueError("benchmark case IDs and hashes must align")
        splits = tuple(_enum(item, SplitName, "split_names") for item in self.split_names)
        if len(set(splits)) != len(splits):
            raise ValueError("exclusion split associations cannot contain duplicates")
        if splits != tuple(split for split in SPLIT_ORDER if split in splits):
            raise ValueError("exclusion split associations must use canonical split ordering")
        object.__setattr__(self, "split_names", splits)
        _strings(self.membership_digests, "membership_digests", allow_empty=True)
        for item in self.membership_digests:
            _sha(item, "membership_digests item")
        if self.membership_digests and len(self.membership_digests) != len(self.benchmark_case_ids):
            raise ValueError("membership digests and benchmark case IDs must align")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class ExclusionManifestV1:
    registry_version: str
    entries: tuple[ExclusionEntry, ...]
    normalization_policy: str
    detector_policy: str
    semantic_diagnostic_policy: str
    manifest_digest: str

    def __post_init__(self) -> None:
        if self.registry_version != EXCLUSION_REGISTRY_VERSION:
            raise ValueError("unsupported exclusion registry version")
        _tuple_of(self.entries, "exclusion entries")
        if any(not isinstance(item, ExclusionEntry) for item in self.entries):
            raise ValueError("exclusion entries must be typed")
        artifact_ids = tuple(item.artifact_id for item in self.entries)
        if artifact_ids != tuple(sorted(artifact_ids, key=lambda item: item.encode("utf-8"))):
            raise ValueError("exclusion manifest entries must use canonical artifact-ID ordering")
        if len(set(artifact_ids)) != len(artifact_ids):
            raise ValueError("exclusion manifest cannot contain duplicate artifact IDs")
        for name in ("normalization_policy", "detector_policy", "semantic_diagnostic_policy"):
            _text(getattr(self, name), name)
        _sha(self.manifest_digest, "manifest_digest")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class BenchmarkManifestV1:
    benchmark_semantic_version: str
    case_schema_version: str
    case_entries: tuple[tuple[str, str], ...]
    split_manifests: tuple[tuple[SplitName, str, str], ...]
    authority_manifest_hash: str
    scorer_manifest_hash: str
    contamination_exclusion_manifest_hash: str
    benchmark_manifest_hash: str

    def __post_init__(self) -> None:
        if self.benchmark_semantic_version != BENCHMARK_SEMANTIC_VERSION:
            raise ValueError("benchmark manifest semantic version mismatch")
        if self.case_schema_version != CASE_SCHEMA_VERSION:
            raise ValueError("benchmark manifest schema version mismatch")
        _tuple_of(self.case_entries, "case_entries")
        for case_id, digest in self.case_entries:
            _text(case_id, "case_entries case_id")
            _sha(digest, "case_entries case_payload_hash")
        _tuple_of(self.split_manifests, "split_manifests")
        normalized_splits: list[tuple[SplitName, str, str]] = []
        for split_name, version, digest in self.split_manifests:
            normalized_splits.append(
                (
                    _enum(split_name, SplitName, "split_manifests split_name"),
                    version,
                    digest,
                )
            )
            if version != SPLIT_MANIFEST_VERSION:
                raise ValueError("split manifest version mismatch")
            _sha(digest, "split manifest hash")
        object.__setattr__(self, "split_manifests", tuple(normalized_splits))
        for name in (
            "authority_manifest_hash",
            "scorer_manifest_hash",
            "contamination_exclusion_manifest_hash",
            "benchmark_manifest_hash",
        ):
            _sha(getattr(self, name), name)


@register_serializable_type
@dataclass(frozen=True, slots=True)
class ManifestBundleV1:
    cases: tuple[BenchmarkCaseV1, ...]
    split_manifests: tuple[SplitManifestV1, ...]
    authority_manifest: AuthorityManifestV1
    scorer_manifest: ScorerManifestV1
    exclusion_manifest: ExclusionManifestV1
    benchmark_manifest: BenchmarkManifestV1

    def __post_init__(self) -> None:
        _tuple_of(self.cases, "cases")
        _tuple_of(self.split_manifests, "split_manifests")
        if any(not isinstance(item, BenchmarkCaseV1) for item in self.cases):
            raise ValueError("manifest cases must be typed")
        if any(not isinstance(item, SplitManifestV1) for item in self.split_manifests):
            raise ValueError("manifest split manifests must be typed")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class FieldScore:
    field_id: str
    status: FieldScoreStatus
    expected: object
    actual: object | None
    reason: str

    def __post_init__(self) -> None:
        _text(self.field_id, "field_id")
        object.__setattr__(self, "status", _enum(self.status, FieldScoreStatus, "status"))
        _text(self.reason, "reason")
        object.__setattr__(self, "expected", freeze_data(self.expected))
        object.__setattr__(self, "actual", freeze_data(self.actual))


@register_serializable_type
@dataclass(frozen=True, slots=True)
class ErrorEvent:
    case_id: str
    error_class: ErrorClass
    severity: str
    field_id: str | None
    evidence: str

    def __post_init__(self) -> None:
        _text(self.case_id, "case_id")
        object.__setattr__(self, "error_class", _enum(self.error_class, ErrorClass, "error_class"))
        if self.severity not in {"CRITICAL", "HIGH", "BEHAVIOR"}:
            raise ValueError("unknown error severity")
        if self.field_id is not None:
            _text(self.field_id, "field_id")
        _text(self.evidence, "evidence")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class ScoreResult:
    case_id: str
    outcome: TaskOutcome
    field_scores: tuple[FieldScore, ...]
    error_events: tuple[ErrorEvent, ...]
    primary_decision_correct: bool
    refusal_decision_correct: bool

    def __post_init__(self) -> None:
        _text(self.case_id, "case_id")
        object.__setattr__(self, "outcome", _enum(self.outcome, TaskOutcome, "outcome"))
        _tuple_of(self.field_scores, "field_scores")
        _tuple_of(self.error_events, "error_events")
        if any(not isinstance(item, FieldScore) for item in self.field_scores):
            raise ValueError("field_scores must be typed")
        if any(not isinstance(item, ErrorEvent) for item in self.error_events):
            raise ValueError("error_events must be typed")
        if not isinstance(self.primary_decision_correct, bool):
            raise ValueError("primary_decision_correct must be boolean")
        if not isinstance(self.refusal_decision_correct, bool):
            raise ValueError("refusal_decision_correct must be boolean")


__all__ = [
    "AuthorityBinding",
    "AuthorityManifestEntry",
    "AuthorityManifestV1",
    "BenchmarkCaseV1",
    "BenchmarkManifestV1",
    "CaseProvenance",
    "ClaimContract",
    "ComparabilityContract",
    "ContaminationBinding",
    "DeterministicResultView",
    "DifficultyBinding",
    "DocumentIdentity",
    "ErrorEvent",
    "EvidenceExcerpt",
    "EvidenceReference",
    "EvidenceSpanIdentity",
    "ExclusionEntry",
    "ExclusionManifestV1",
    "ExpectedStructuredAnswer",
    "ExpertReviewMetadata",
    "FieldScore",
    "InputContract",
    "ManifestBundleV1",
    "ObservationView",
    "ProvenanceEdge",
    "RES71OperationBinding",
    "RES71RefusalBinding",
    "RES71RuntimeBinding",
    "RefusalExpectation",
    "ScoreResult",
    "ScorerManifestEntry",
    "ScorerManifestV1",
    "ScoringContract",
    "SourceArtifactIdentity",
    "SplitBinding",
    "SplitManifestV1",
    "SplitMembershipRecordV1",
    "ToleranceContract",
]
