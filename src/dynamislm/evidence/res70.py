"""RES-70 claim-relative evidence applicability vector."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

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

if TYPE_CHECKING:
    from dynamislm.football.models import FootballWorldContext
    from dynamislm.longitudinal.statistics.models import StatisticalSupport
    from dynamislm.population.models import (
        CanonicalPopulationDecision,
        CanonicalSourceDecision,
        V2EvidenceApplicability,
    )


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
class ApplicabilityAuthorityProvenance:
    """Typed source authority that can support one applicability judgment."""

    source_decisions: tuple[CanonicalSourceDecision, ...] = ()
    population_decisions: tuple[CanonicalPopulationDecision, ...] = ()
    evidence_applicabilities: tuple[V2EvidenceApplicability, ...] = ()
    statistical_support: StatisticalSupport | None = None
    statistical_authority_hashes: tuple[str, ...] = ()
    football_contexts: tuple[FootballWorldContext, ...] = ()

    def __post_init__(self) -> None:
        from dynamislm.football.models import FootballWorldContext
        from dynamislm.longitudinal.statistics.models import StatisticalSupport
        from dynamislm.population.models import (
            CanonicalPopulationDecision,
            CanonicalSourceDecision,
            V2EvidenceApplicability,
        )

        _require_tuple_items(self.source_decisions, CanonicalSourceDecision, "source_decisions")
        _require_tuple_items(
            self.population_decisions,
            CanonicalPopulationDecision,
            "population_decisions",
        )
        _require_tuple_items(
            self.evidence_applicabilities,
            V2EvidenceApplicability,
            "evidence_applicabilities",
        )
        if self.statistical_support is not None and not isinstance(
            self.statistical_support,
            StatisticalSupport,
        ):
            raise ValueError("statistical_support must be a StatisticalSupport")
        _require_string_tuple(self.statistical_authority_hashes, "statistical_authority_hashes")
        _require_tuple_items(self.football_contexts, FootballWorldContext, "football_contexts")

    @property
    def canonical_provenance_hash(self) -> str:
        return canonical_hash(self)


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
    authority_provenance: ApplicabilityAuthorityProvenance | None = None

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
        if self.authority_provenance is not None and not isinstance(
            self.authority_provenance,
            ApplicabilityAuthorityProvenance,
        ):
            raise ValueError("authority_provenance must be an ApplicabilityAuthorityProvenance")
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
    """Recompute the applicability hash and reject structural tampering."""

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


def _validate_source_authority(
    decisions: tuple[CanonicalSourceDecision, ...],
) -> None:
    from dynamislm.population.models import CanonicalSourceStatus
    from dynamislm.population.qualification import qualify_canonical_source

    if not decisions:
        raise ValueError("affirmative applicability requires canonical source authority")
    for decision in decisions:
        if qualify_canonical_source(decision.source) != decision:
            raise ValueError("source applicability authority does not recompute canonically")
        if decision.status is not CanonicalSourceStatus.CANONICAL_EMPIRICAL_TARGET:
            raise ValueError("source applicability authority is not an affirmative source decision")


def _validate_population_authority(
    decisions: tuple[CanonicalPopulationDecision, ...],
) -> None:
    from dynamislm.population.models import CanonicalPopulationStatus
    from dynamislm.population.qualification import qualify_canonical_population

    if not decisions:
        raise ValueError("affirmative applicability requires canonical population authority")
    for decision in decisions:
        if qualify_canonical_population(decision.population) != decision:
            raise ValueError("population applicability authority does not recompute canonically")
        if decision.status is not CanonicalPopulationStatus.PASS:
            raise ValueError(
                "population applicability authority is not an affirmative population decision"
            )


def _validate_evidence_authority(
    provenance: ApplicabilityAuthorityProvenance,
) -> None:
    from dynamislm.population.models import EvidenceClass

    if not provenance.evidence_applicabilities:
        raise ValueError("affirmative method applicability requires canonical evidence authority")
    if not provenance.source_decisions:
        raise ValueError("evidence applicability must be bound to canonical source decisions")
    source_ids = {item.source.source_id.identifier for item in provenance.source_decisions}
    for evidence in provenance.evidence_applicabilities:
        if evidence.source_id not in source_ids:
            raise ValueError("evidence applicability source is not canonically qualified")
        if evidence.decision not in (
            ApplicabilityDecision.SUPPORTED,
            ApplicabilityDecision.LIMITED,
        ):
            raise ValueError("evidence applicability is not affirmative")
        if evidence.evidence_class is EvidenceClass.REJECTED_OR_UNRESOLVED:
            raise ValueError("rejected evidence cannot support affirmative applicability")


def _validate_context_authority(
    provenance: ApplicabilityAuthorityProvenance,
) -> None:
    from dynamislm.football.validation import validate_football_world_context

    if not provenance.football_contexts:
        raise ValueError("contextual applicability requires typed football-world contexts")
    for context in provenance.football_contexts:
        validate_football_world_context(context)


def _validate_statistical_authority(
    provenance: ApplicabilityAuthorityProvenance,
) -> None:
    from dynamislm.longitudinal.statistics.support import validate_statistical_support

    if provenance.statistical_support is None:
        raise ValueError("statistical applicability requires exact statistical support")
    validate_statistical_support(provenance.statistical_support)
    if provenance.statistical_support.canonical_support_hash not in set(
        provenance.statistical_authority_hashes
    ):
        raise ValueError("statistical applicability authority must bind the exact support hash")


def _validate_assessment_authority(assessment: ApplicabilityAssessment) -> None:
    if assessment.decision not in (
        ApplicabilityDecision.SUPPORTED,
        ApplicabilityDecision.LIMITED,
    ):
        return
    provenance = assessment.authority_provenance
    if provenance is None:
        raise ValueError(
            "caller-supplied affirmative applicability has no verifiable authority provenance"
        )
    if not assessment.authority_references:
        raise ValueError("affirmative applicability requires authority references")
    if assessment.axis is ApplicabilityAxis.METHOD_VALIDITY:
        _validate_evidence_authority(provenance)
    elif assessment.axis is ApplicabilityAxis.SOURCE_QUALITY:
        _validate_source_authority(provenance.source_decisions)
    elif assessment.axis is ApplicabilityAxis.POPULATION_RELEVANCE:
        _validate_population_authority(provenance.population_decisions)
    elif assessment.axis is ApplicabilityAxis.CONTEXTUAL_RELEVANCE:
        _validate_context_authority(provenance)
    elif assessment.axis is ApplicabilityAxis.STATISTICAL_ADEQUACY:
        _validate_statistical_authority(provenance)


def validate_claim_evidence_authority(value: ClaimEvidenceApplicability) -> None:
    """Require canonical provenance for every affirmative applicability axis."""

    validate_claim_evidence_applicability(value)
    for assessment in value.assessments:
        _validate_assessment_authority(assessment)


__all__ = [
    "ApplicabilityAssessment",
    "ApplicabilityAuthorityProvenance",
    "ApplicabilityAxis",
    "ClaimEvidenceApplicability",
    "build_claim_evidence_applicability",
    "validate_claim_evidence_applicability",
    "validate_claim_evidence_authority",
]
