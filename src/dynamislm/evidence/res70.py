"""RES-70 claim-relative evidence applicability vector."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from dynamislm.evidence.models import ApplicabilityDecision
from dynamislm.measurement.identity import (
    RegistryReference,
    _require_enum,
    _require_instance,
    _require_text,
    _require_tuple_items,
    require_tuple,
)
from dynamislm.serialization import canonical_hash, register_serializable_type


def _require_string_tuple(value: object, field_name: str) -> None:
    require_tuple(value, field_name)
    assert isinstance(value, tuple)
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError(f"{field_name} must contain non-empty strings")


class ApplicabilityAxis(StrEnum):
    METHOD_VALIDITY = "METHOD_VALIDITY"
    SOURCE_QUALITY = "SOURCE_QUALITY"
    POPULATION_RELEVANCE = "POPULATION_RELEVANCE"
    CONTEXTUAL_RELEVANCE = "CONTEXTUAL_RELEVANCE"
    STATISTICAL_ADEQUACY = "STATISTICAL_ADEQUACY"


@register_serializable_type
@dataclass(frozen=True, slots=True)
class ApplicabilityAssessment:
    """One independent evidence-applicability judgment."""

    axis: ApplicabilityAxis
    decision: ApplicabilityDecision
    required_for_claim: bool
    evidence_references: tuple[RegistryReference, ...]
    authority_references: tuple[RegistryReference, ...]
    conditions: tuple[str, ...]
    rationale: str

    def __post_init__(self) -> None:
        _require_enum(self.axis, ApplicabilityAxis, "axis")
        _require_enum(self.decision, ApplicabilityDecision, "decision")
        if not isinstance(self.required_for_claim, bool):
            raise ValueError("required_for_claim must be a boolean")
        _require_tuple_items(self.evidence_references, RegistryReference, "evidence_references")
        _require_tuple_items(
            self.authority_references,
            RegistryReference,
            "authority_references",
        )
        _require_string_tuple(self.conditions, "conditions")
        _require_text(self.rationale, "rationale")
        if self.required_for_claim and self.decision is ApplicabilityDecision.UNASSESSED:
            raise ValueError("a required applicability axis cannot be unassessed")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class ClaimEvidenceApplicability:
    """Orthogonal method/source/population/context/statistical applicability."""

    claim_intent_reference: RegistryReference
    assessments: tuple[ApplicabilityAssessment, ...]
    registry_version: str
    applicability_hash: str | None = None

    def __post_init__(self) -> None:
        _require_instance(
            self.claim_intent_reference,
            RegistryReference,
            "claim_intent_reference",
        )
        _require_tuple_items(self.assessments, ApplicabilityAssessment, "assessments")
        if not self.assessments:
            raise ValueError("claim evidence applicability requires assessments")
        axes = tuple(item.axis for item in self.assessments)
        if len(set(axes)) != len(axes):
            raise ValueError("claim evidence applicability requires one assessment per axis")
        _require_text(self.registry_version, "registry_version")
        expected_hash = canonical_hash(
            {
                "claim_intent_reference": self.claim_intent_reference,
                "assessments": self.assessments,
                "registry_version": self.registry_version,
            }
        )
        if self.applicability_hash is None:
            object.__setattr__(self, "applicability_hash", expected_hash)
        elif self.applicability_hash != expected_hash:
            raise ValueError("applicability_hash does not match immutable applicability content")

    @property
    def canonical_applicability_hash(self) -> str:
        assert self.applicability_hash is not None
        return self.applicability_hash

    def assessment(self, axis: ApplicabilityAxis) -> ApplicabilityAssessment:
        for item in self.assessments:
            if item.axis is axis:
                return item
        raise KeyError(axis)

    def required_axes(self) -> tuple[ApplicabilityAxis, ...]:
        return tuple(item.axis for item in self.assessments if item.required_for_claim)

    def supports_required_axes(self) -> bool:
        return all(
            item.decision in (ApplicabilityDecision.SUPPORTED, ApplicabilityDecision.LIMITED)
            for item in self.assessments
            if item.required_for_claim
        )


def build_claim_evidence_applicability(
    claim_intent_reference: RegistryReference,
    assessments: tuple[ApplicabilityAssessment, ...],
    *,
    registry_version: str = "res70-1.0.0",
) -> ClaimEvidenceApplicability:
    """Construct the canonical vector without collapsing its dimensions."""

    return ClaimEvidenceApplicability(
        claim_intent_reference=claim_intent_reference,
        assessments=assessments,
        registry_version=registry_version,
    )


def validate_claim_evidence_applicability(value: ClaimEvidenceApplicability) -> None:
    """Recompute the applicability hash and reject tampering."""

    if not isinstance(value, ClaimEvidenceApplicability):
        raise ValueError("value must be a ClaimEvidenceApplicability")
    expected = canonical_hash(
        {
            "claim_intent_reference": value.claim_intent_reference,
            "assessments": value.assessments,
            "registry_version": value.registry_version,
        }
    )
    if value.canonical_applicability_hash != expected:
        raise ValueError("applicability hash does not match immutable content")


__all__ = [
    "ApplicabilityAssessment",
    "ApplicabilityAxis",
    "ClaimEvidenceApplicability",
    "build_claim_evidence_applicability",
    "validate_claim_evidence_applicability",
]
