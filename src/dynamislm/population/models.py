"""Typed V2 population, source, evidence-role, and qualification contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from dynamislm.evidence.models import ApplicabilityDecision
from dynamislm.measurement.identity import (
    MetadataEntry,
    RegistryReference,
    ScientificIdentifier,
    require_tuple,
)
from dynamislm.population._authority import (
    compute_population_authority,
    compute_source_authority,
    validate_population_decision,
    validate_source_decision,
)
from dynamislm.refusal.models import RefusalClass, RefusalReasonCode
from dynamislm.serialization import register_serializable_type


def _require_text(value: str, field_name: str) -> None:
    if not value or not value.strip():
        raise ValueError(f"{field_name} must not be empty")


def _require_optional_text(value: str | None, field_name: str) -> None:
    if value is not None:
        _require_text(value, field_name)


def _require_string_tuple(values: tuple[str, ...], field_name: str) -> None:
    require_tuple(values, field_name)
    if any(not value.strip() for value in values):
        raise ValueError(f"{field_name} must not contain empty strings")


def _normalise_reason_codes(
    values: tuple[RefusalReasonCode, ...],
) -> tuple[RefusalReasonCode, ...]:
    require_tuple(values, "reason_codes")
    normalised: list[RefusalReasonCode] = []
    for reason in values:
        if isinstance(reason, RefusalReasonCode):
            normalised.append(reason)
        else:
            try:
                normalised.append(RefusalReasonCode(reason))
            except ValueError as exc:
                raise ValueError("reason_codes must contain RefusalReasonCode values") from exc
    return tuple(normalised)


class Sex(StrEnum):
    MALE = "MALE"
    FEMALE = "FEMALE"
    MIXED = "MIXED"
    UNKNOWN = "UNKNOWN"


class AgeClass(StrEnum):
    SENIOR = "SENIOR"
    U23 = "U23"
    YOUTH = "YOUTH"
    MIXED = "MIXED"
    UNKNOWN = "UNKNOWN"


class Sport(StrEnum):
    ASSOCIATION_FOOTBALL = "ASSOCIATION_FOOTBALL"
    FUTSAL = "FUTSAL"
    OTHER = "OTHER"
    MIXED = "MIXED"
    UNKNOWN = "UNKNOWN"


class ProfessionalStatus(StrEnum):
    PROFESSIONAL = "PROFESSIONAL"
    SEMI_PROFESSIONAL = "SEMI_PROFESSIONAL"
    AMATEUR = "AMATEUR"
    MIXED = "MIXED"
    UNKNOWN = "UNKNOWN"


class SquadLevel(StrEnum):
    FIRST_TEAM = "FIRST_TEAM"
    U23 = "U23"
    ACADEMY_OR_YOUTH = "ACADEMY_OR_YOUTH"
    OTHER = "OTHER"
    MIXED = "MIXED"
    UNKNOWN = "UNKNOWN"


class CompetitionTier(StrEnum):
    TOP_DOMESTIC_DIVISION = "TOP_DOMESTIC_DIVISION"
    LOWER_DOMESTIC_DIVISION = "LOWER_DOMESTIC_DIVISION"
    OTHER = "OTHER"
    MIXED = "MIXED"
    UNKNOWN = "UNKNOWN"


class PopulationDimension(StrEnum):
    SEX = "SEX"
    AGE_CLASS = "AGE_CLASS"
    SPORT = "SPORT"
    PROFESSIONAL_STATUS = "PROFESSIONAL_STATUS"
    SQUAD_LEVEL = "SQUAD_LEVEL"
    COMPETITION_TIER = "COMPETITION_TIER"


class PopulationResolutionStatus(StrEnum):
    RESOLVED = "RESOLVED"
    UNRESOLVED = "UNRESOLVED"
    CONFLICTING = "CONFLICTING"


class PopulationEvidenceStatus(StrEnum):
    ESTABLISHED = "ESTABLISHED"
    MISSING = "MISSING"
    UNRESOLVED = "UNRESOLVED"
    CONFLICTING = "CONFLICTING"


class ClauseStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNRESOLVED = "UNRESOLVED"


class CanonicalPopulationStatus(StrEnum):
    PASS = "PASS"
    NONCANONICAL = "NONCANONICAL"
    UNRESOLVED = "UNRESOLVED"
    FAIL = "NONCANONICAL"


class SourceDataOrigin(StrEnum):
    ACTUAL_OBSERVED_MEASURED = "ACTUAL_OBSERVED_MEASURED"
    ACTUAL_OBSERVED = "ACTUAL_OBSERVED_MEASURED"
    SYNTHETIC = "SYNTHETIC"
    SIMULATED = "SIMULATED"
    LITERATURE_ONLY = "LITERATURE_ONLY"
    UNKNOWN = "UNKNOWN"


class CohortScopeType(StrEnum):
    WHOLE_COHORT = "WHOLE_COHORT"
    MIXED_PARENT_COHORT = "MIXED_PARENT_COHORT"
    SEPARATED_SUBGROUP = "SEPARATED_SUBGROUP"
    UNKNOWN = "UNKNOWN"
    MIXED_COHORT = "MIXED_PARENT_COHORT"


class SubgroupSeparability(StrEnum):
    EXACT_TARGET_COHORT = "EXACT_TARGET_COHORT"
    EXACT = "EXACT_TARGET_COHORT"
    SEPARABLE = "SEPARABLE"
    SEPARATED = "SEPARABLE"
    NOT_SEPARABLE = "NOT_SEPARABLE"
    UNKNOWN = "UNKNOWN"


class DataGranularity(StrEnum):
    ATHLETE_LEVEL = "ATHLETE_LEVEL"
    TRIAL_LEVEL = "TRIAL_LEVEL"
    COHORT_SUMMARY = "COHORT_SUMMARY"
    LITERATURE_ONLY = "LITERATURE_ONLY"
    UNKNOWN = "UNKNOWN"


class ReuseStatus(StrEnum):
    UNRESTRICTED = "UNRESTRICTED"
    RESTRICTED = "RESTRICTED"
    CONDITIONAL = "CONDITIONAL"
    PROHIBITED = "PROHIBITED"
    UNKNOWN = "UNKNOWN"


class EvidenceClass(StrEnum):
    CANONICAL_EMPIRICAL_TARGET = "CANONICAL_EMPIRICAL_TARGET"
    DIRECT_TARGET_POPULATION_EVIDENCE = "DIRECT_TARGET_POPULATION_EVIDENCE"
    INDIRECT_MEASUREMENT_EVIDENCE = "INDIRECT_MEASUREMENT_EVIDENCE"
    NONCANONICAL_CONTEXT_ONLY = "NONCANONICAL_CONTEXT_ONLY"
    REJECTED_OR_UNRESOLVED = "REJECTED_OR_UNRESOLVED"


class EvidenceApplicabilityRole(StrEnum):
    TARGET_WORLD_EMPIRICAL = "TARGET_WORLD_EMPIRICAL"
    DIRECT_TARGET_POPULATION_METHOD = "DIRECT_TARGET_POPULATION_METHOD"
    INDIRECT_MEASUREMENT_METHOD = "INDIRECT_MEASUREMENT_METHOD"
    NONCANONICAL_CONTEXT = "NONCANONICAL_CONTEXT"
    REJECTED_OR_UNRESOLVED = "REJECTED_OR_UNRESOLVED"


_EVIDENCE_ROLE_BY_CLASS: dict[EvidenceClass, EvidenceApplicabilityRole] = {
    EvidenceClass.CANONICAL_EMPIRICAL_TARGET: EvidenceApplicabilityRole.TARGET_WORLD_EMPIRICAL,
    EvidenceClass.DIRECT_TARGET_POPULATION_EVIDENCE: (
        EvidenceApplicabilityRole.DIRECT_TARGET_POPULATION_METHOD
    ),
    EvidenceClass.INDIRECT_MEASUREMENT_EVIDENCE: (
        EvidenceApplicabilityRole.INDIRECT_MEASUREMENT_METHOD
    ),
    EvidenceClass.NONCANONICAL_CONTEXT_ONLY: EvidenceApplicabilityRole.NONCANONICAL_CONTEXT,
    EvidenceClass.REJECTED_OR_UNRESOLVED: EvidenceApplicabilityRole.REJECTED_OR_UNRESOLVED,
}


class CanonicalSourceStatus(StrEnum):
    CANONICAL_EMPIRICAL_TARGET = "CANONICAL_EMPIRICAL_TARGET"
    CANONICAL_ELIGIBILITY_FAILED = "CANONICAL_ELIGIBILITY_FAILED"
    UNRESOLVED = "UNRESOLVED"
    FAIL = "CANONICAL_ELIGIBILITY_FAILED"


class SourceRequirement(StrEnum):
    POPULATION_MATCH = "POPULATION_MATCH"
    ACTUAL_OBSERVED_DATA = "ACTUAL_OBSERVED_DATA"
    TARGET_SUBGROUP_SCOPE = "TARGET_SUBGROUP_SCOPE"
    SOURCE_IDENTITY_AND_PROVENANCE = "SOURCE_IDENTITY_AND_PROVENANCE"
    DATA_GRANULARITY = "DATA_GRANULARITY"


CANONICAL_POPULATION_DIMENSIONS = (
    PopulationDimension.SEX,
    PopulationDimension.AGE_CLASS,
    PopulationDimension.SPORT,
    PopulationDimension.PROFESSIONAL_STATUS,
    PopulationDimension.SQUAD_LEVEL,
    PopulationDimension.COMPETITION_TIER,
)

CANONICAL_SOURCE_REQUIREMENTS = (
    SourceRequirement.POPULATION_MATCH,
    SourceRequirement.ACTUAL_OBSERVED_DATA,
    SourceRequirement.TARGET_SUBGROUP_SCOPE,
    SourceRequirement.SOURCE_IDENTITY_AND_PROVENANCE,
    SourceRequirement.DATA_GRANULARITY,
)


_DIMENSION_ENUMS: dict[PopulationDimension, type[StrEnum]] = {
    PopulationDimension.SEX: Sex,
    PopulationDimension.AGE_CLASS: AgeClass,
    PopulationDimension.SPORT: Sport,
    PopulationDimension.PROFESSIONAL_STATUS: ProfessionalStatus,
    PopulationDimension.SQUAD_LEVEL: SquadLevel,
    PopulationDimension.COMPETITION_TIER: CompetitionTier,
}


@register_serializable_type
@dataclass(frozen=True, slots=True)
class CompetitionIdentity:
    """Stable competition reference without defining the RES-61 ontology."""

    identifier: ScientificIdentifier
    display_label: str

    def __post_init__(self) -> None:
        _require_text(self.display_label, "display_label")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class SeasonIdentity:
    """Stable season reference without defining the RES-61 ontology."""

    identifier: ScientificIdentifier
    display_label: str

    def __post_init__(self) -> None:
        _require_text(self.display_label, "display_label")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class PopulationEvidenceBinding:
    """Evidence-backed resolution of one material population dimension."""

    dimension: PopulationDimension
    value: str | None
    evidence_reference: RegistryReference | None
    status: PopulationEvidenceStatus = PopulationEvidenceStatus.ESTABLISHED
    missing_information: tuple[str, ...] = ()
    source_note: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.dimension, PopulationDimension):
            raise ValueError("dimension must be a PopulationDimension")
        if not isinstance(self.status, PopulationEvidenceStatus):
            raise ValueError("status must be a PopulationEvidenceStatus")
        if isinstance(self.value, StrEnum):
            object.__setattr__(self, "value", self.value.value)
        if self.value is not None:
            if not isinstance(self.value, str):
                raise ValueError("population evidence value must be a string or None")
            _require_text(self.value, "value")
            enum_type = _DIMENSION_ENUMS[self.dimension]
            try:
                enum_type(self.value)
            except ValueError as exc:
                raise ValueError(
                    f"value {self.value!r} is not valid for {self.dimension.value}"
                ) from exc
        if self.status is PopulationEvidenceStatus.ESTABLISHED:
            if self.value is None:
                raise ValueError("established population evidence requires a value")
            if self.evidence_reference is None:
                raise ValueError("established population evidence requires an evidence reference")
        require_tuple(self.missing_information, "missing_information")
        _require_string_tuple(self.missing_information, "missing_information")
        _require_optional_text(self.source_note, "source_note")

    @property
    def established_value(self) -> str | None:
        """Compatibility/readability alias for the resolved value."""

        return self.value

    @property
    def typed_value(self) -> StrEnum | None:
        if self.value is None:
            return None
        return _DIMENSION_ENUMS[self.dimension](self.value)


@register_serializable_type
@dataclass(frozen=True, slots=True)
class PopulationIdentity:
    """Typed V2 population identity; free text is not part of this authority."""

    sex: Sex
    age_class: AgeClass
    sport: Sport
    professional_status: ProfessionalStatus
    squad_level: SquadLevel
    competition_tier: CompetitionTier
    competition_identity: CompetitionIdentity | None = None
    season: SeasonIdentity | None = None
    evidence_bindings: tuple[PopulationEvidenceBinding, ...] = ()
    resolution_status: PopulationResolutionStatus = PopulationResolutionStatus.RESOLVED

    def __post_init__(self) -> None:
        enum_fields = (
            ("sex", self.sex, Sex),
            ("age_class", self.age_class, AgeClass),
            ("sport", self.sport, Sport),
            ("professional_status", self.professional_status, ProfessionalStatus),
            ("squad_level", self.squad_level, SquadLevel),
            ("competition_tier", self.competition_tier, CompetitionTier),
        )
        for field_name, value, enum_type in enum_fields:
            if not isinstance(value, enum_type):
                raise ValueError(f"{field_name} must be a {enum_type.__name__}")
        if not isinstance(self.resolution_status, PopulationResolutionStatus):
            raise ValueError("resolution_status must be a PopulationResolutionStatus")
        require_tuple(self.evidence_bindings, "evidence_bindings")
        if any(
            not isinstance(binding, PopulationEvidenceBinding) for binding in self.evidence_bindings
        ):
            raise ValueError("evidence_bindings must contain PopulationEvidenceBinding values")

    def value_for(self, dimension: PopulationDimension) -> StrEnum:
        values: dict[PopulationDimension, StrEnum] = {
            PopulationDimension.SEX: self.sex,
            PopulationDimension.AGE_CLASS: self.age_class,
            PopulationDimension.SPORT: self.sport,
            PopulationDimension.PROFESSIONAL_STATUS: self.professional_status,
            PopulationDimension.SQUAD_LEVEL: self.squad_level,
            PopulationDimension.COMPETITION_TIER: self.competition_tier,
        }
        return values[dimension]


@register_serializable_type
@dataclass(frozen=True, slots=True)
class PopulationClauseDecision:
    """Deterministic result for one of the six canonical population clauses."""

    dimension: PopulationDimension
    expected_value: str
    observed_value: str | None
    status: ClauseStatus
    reason_codes: tuple[RefusalReasonCode, ...]
    evidence_references: tuple[RegistryReference, ...]
    missing_information: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.dimension, PopulationDimension):
            raise ValueError("dimension must be a PopulationDimension")
        if not isinstance(self.status, ClauseStatus):
            raise ValueError("status must be a ClauseStatus")
        _require_text(self.expected_value, "expected_value")
        _require_optional_text(self.observed_value, "observed_value")
        object.__setattr__(self, "reason_codes", _normalise_reason_codes(self.reason_codes))
        require_tuple(self.evidence_references, "evidence_references")
        require_tuple(self.missing_information, "missing_information")
        _require_string_tuple(self.missing_information, "missing_information")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class CanonicalPopulationDecision:
    """Complete deterministic population-match result, never just a boolean."""

    decision_id: ScientificIdentifier
    population: PopulationIdentity
    status: CanonicalPopulationStatus
    clauses: tuple[PopulationClauseDecision, ...]
    failed_clauses: tuple[PopulationDimension, ...]
    unresolved_clauses: tuple[PopulationDimension, ...]
    missing_information: tuple[str, ...]
    supporting_evidence: tuple[RegistryReference, ...]
    method_reference: RegistryReference
    reason_codes: tuple[RefusalReasonCode, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.decision_id, ScientificIdentifier):
            raise ValueError("decision_id must be a ScientificIdentifier")
        if not isinstance(self.population, PopulationIdentity):
            raise ValueError("population must be a PopulationIdentity")
        if not isinstance(self.status, CanonicalPopulationStatus):
            raise ValueError("status must be a CanonicalPopulationStatus")
        require_tuple(self.clauses, "clauses")
        if any(not isinstance(clause, PopulationClauseDecision) for clause in self.clauses):
            raise ValueError("clauses must contain PopulationClauseDecision values")
        if tuple(clause.dimension for clause in self.clauses) != CANONICAL_POPULATION_DIMENSIONS:
            raise ValueError("clauses must contain the six canonical dimensions in order")
        require_tuple(self.failed_clauses, "failed_clauses")
        require_tuple(self.unresolved_clauses, "unresolved_clauses")
        if any(not isinstance(item, PopulationDimension) for item in self.failed_clauses):
            raise ValueError("failed_clauses must contain PopulationDimension values")
        if any(not isinstance(item, PopulationDimension) for item in self.unresolved_clauses):
            raise ValueError("unresolved_clauses must contain PopulationDimension values")
        require_tuple(self.missing_information, "missing_information")
        _require_string_tuple(self.missing_information, "missing_information")
        require_tuple(self.supporting_evidence, "supporting_evidence")
        if not isinstance(self.method_reference, RegistryReference):
            raise ValueError("method_reference must be a RegistryReference")
        object.__setattr__(self, "reason_codes", _normalise_reason_codes(self.reason_codes))
        validate_population_decision(self, compute_population_authority(self.population))

    @property
    def overall_status(self) -> CanonicalPopulationStatus:
        return self.status

    @property
    def passed(self) -> bool:
        return self.status is CanonicalPopulationStatus.PASS

    @property
    def refusal_class(self) -> RefusalClass | None:
        if self.status is CanonicalPopulationStatus.NONCANONICAL:
            return RefusalClass.CANONICAL_ELIGIBILITY_FAILED
        if self.status is CanonicalPopulationStatus.UNRESOLVED:
            return RefusalClass.POPULATION_SCOPE_UNRESOLVED
        return None


@register_serializable_type
@dataclass(frozen=True, slots=True)
class CohortScope:
    """Typed whole-cohort or subgroup scope, including extraction separability."""

    scope_type: CohortScopeType
    separability: SubgroupSeparability
    scope_id: ScientificIdentifier | None = None
    parent_cohort_id: ScientificIdentifier | None = None
    evaluated_subgroup_id: ScientificIdentifier | None = None
    extraction_evidence: tuple[RegistryReference, ...] = ()
    provenance_references: tuple[RegistryReference, ...] = ()
    description: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.scope_type, CohortScopeType):
            raise ValueError("scope_type must be a CohortScopeType")
        if not isinstance(self.separability, SubgroupSeparability):
            raise ValueError("separability must be a SubgroupSeparability")
        require_tuple(self.extraction_evidence, "extraction_evidence")
        require_tuple(self.provenance_references, "provenance_references")
        _require_optional_text(self.description, "description")

    @property
    def subgroup_separability(self) -> SubgroupSeparability:
        return self.separability


@register_serializable_type
@dataclass(frozen=True, slots=True)
class LicenseReuseMetadata:
    """Reuse permission metadata kept independent from scientific eligibility."""

    reuse_status: ReuseStatus
    license_reference: RegistryReference | None = None
    conditions: tuple[str, ...] = ()
    metadata: tuple[MetadataEntry, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.reuse_status, ReuseStatus):
            raise ValueError("reuse_status must be a ReuseStatus")
        require_tuple(self.conditions, "conditions")
        _require_string_tuple(self.conditions, "conditions")
        require_tuple(self.metadata, "metadata")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class SourceQualificationProvenance:
    """Evidence lineage used to explain a source-level qualification decision."""

    source_references: tuple[RegistryReference, ...]
    evidence_references: tuple[RegistryReference, ...]
    subgroup_provenance_references: tuple[RegistryReference, ...] = ()

    def __post_init__(self) -> None:
        require_tuple(self.source_references, "source_references")
        require_tuple(self.evidence_references, "evidence_references")
        require_tuple(self.subgroup_provenance_references, "subgroup_provenance_references")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class CanonicalSource:
    """A source description evaluated by the V2 canonical empirical source gate."""

    source_id: RegistryReference
    source_revision: str
    population: PopulationIdentity
    cohort_scope: CohortScope = field(
        default_factory=lambda: CohortScope(CohortScopeType.UNKNOWN, SubgroupSeparability.UNKNOWN)
    )
    data_origin: SourceDataOrigin = SourceDataOrigin.UNKNOWN
    data_granularity: DataGranularity = DataGranularity.UNKNOWN
    publication_reference: RegistryReference | None = None
    license_reuse: LicenseReuseMetadata = field(
        default_factory=lambda: LicenseReuseMetadata(ReuseStatus.UNKNOWN)
    )
    provenance_references: tuple[RegistryReference, ...] = ()

    def __post_init__(self) -> None:
        _require_text(self.source_revision, "source_revision")
        if not isinstance(self.data_origin, SourceDataOrigin):
            raise ValueError("data_origin must be a SourceDataOrigin")
        if not isinstance(self.data_granularity, DataGranularity):
            raise ValueError("data_granularity must be a DataGranularity")
        require_tuple(self.provenance_references, "provenance_references")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class SourceRequirementDecision:
    """Deterministic result for one source eligibility requirement."""

    requirement: SourceRequirement
    status: ClauseStatus
    reason_codes: tuple[RefusalReasonCode, ...]
    supporting_evidence: tuple[RegistryReference, ...]
    missing_information: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.requirement, SourceRequirement):
            raise ValueError("requirement must be a SourceRequirement")
        if not isinstance(self.status, ClauseStatus):
            raise ValueError("status must be a ClauseStatus")
        object.__setattr__(self, "reason_codes", _normalise_reason_codes(self.reason_codes))
        require_tuple(self.supporting_evidence, "supporting_evidence")
        require_tuple(self.missing_information, "missing_information")
        _require_string_tuple(self.missing_information, "missing_information")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class CanonicalSourceDecision:
    """Complete source-level decision, including the independent population result."""

    decision_id: ScientificIdentifier
    source: CanonicalSource
    population_decision: CanonicalPopulationDecision
    status: CanonicalSourceStatus
    evidence_class: EvidenceClass
    requirements: tuple[SourceRequirementDecision, ...]
    failed_requirements: tuple[SourceRequirement, ...]
    unresolved_requirements: tuple[SourceRequirement, ...]
    missing_information: tuple[str, ...]
    supporting_evidence: tuple[RegistryReference, ...]
    method_reference: RegistryReference
    qualification_provenance: SourceQualificationProvenance
    license_reuse: LicenseReuseMetadata
    reason_codes: tuple[RefusalReasonCode, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.decision_id, ScientificIdentifier):
            raise ValueError("decision_id must be a ScientificIdentifier")
        if not isinstance(self.source, CanonicalSource):
            raise ValueError("source must be a CanonicalSource")
        if not isinstance(self.population_decision, CanonicalPopulationDecision):
            raise ValueError("population_decision must be a CanonicalPopulationDecision")
        if not isinstance(self.status, CanonicalSourceStatus):
            raise ValueError("status must be a CanonicalSourceStatus")
        if not isinstance(self.evidence_class, EvidenceClass):
            raise ValueError("evidence_class must be an EvidenceClass")
        require_tuple(self.requirements, "requirements")
        if any(not isinstance(item, SourceRequirementDecision) for item in self.requirements):
            raise ValueError("requirements must contain SourceRequirementDecision values")
        if tuple(item.requirement for item in self.requirements) != CANONICAL_SOURCE_REQUIREMENTS:
            raise ValueError("requirements must contain the source requirements in order")
        require_tuple(self.failed_requirements, "failed_requirements")
        require_tuple(self.unresolved_requirements, "unresolved_requirements")
        if any(not isinstance(item, SourceRequirement) for item in self.failed_requirements):
            raise ValueError("failed_requirements must contain SourceRequirement values")
        if any(not isinstance(item, SourceRequirement) for item in self.unresolved_requirements):
            raise ValueError("unresolved_requirements must contain SourceRequirement values")
        require_tuple(self.missing_information, "missing_information")
        _require_string_tuple(self.missing_information, "missing_information")
        require_tuple(self.supporting_evidence, "supporting_evidence")
        if not isinstance(self.method_reference, RegistryReference):
            raise ValueError("method_reference must be a RegistryReference")
        if not isinstance(self.qualification_provenance, SourceQualificationProvenance):
            raise ValueError("qualification_provenance must be a SourceQualificationProvenance")
        if not isinstance(self.license_reuse, LicenseReuseMetadata):
            raise ValueError("license_reuse must be a LicenseReuseMetadata")
        object.__setattr__(self, "reason_codes", _normalise_reason_codes(self.reason_codes))
        validate_source_decision(self, compute_source_authority(self.source))

    @property
    def overall_status(self) -> CanonicalSourceStatus:
        return self.status

    @property
    def passed(self) -> bool:
        return self.status is CanonicalSourceStatus.CANONICAL_EMPIRICAL_TARGET

    @property
    def refusal_class(self) -> RefusalClass | None:
        if self.status is CanonicalSourceStatus.CANONICAL_ELIGIBILITY_FAILED:
            return RefusalClass.CANONICAL_ELIGIBILITY_FAILED
        if self.status is CanonicalSourceStatus.UNRESOLVED:
            return RefusalClass.POPULATION_SCOPE_UNRESOLVED
        return None


@register_serializable_type
@dataclass(frozen=True, slots=True)
class V2EvidenceApplicability:
    """Explicit claim-relative evidence role; never inferred from population failure."""

    applicability_id: ScientificIdentifier
    source_id: ScientificIdentifier
    claim: str
    evidence_class: EvidenceClass
    role: EvidenceApplicabilityRole
    decision: ApplicabilityDecision
    rationale: str
    conditions: tuple[str, ...] = ()
    evidence_references: tuple[RegistryReference, ...] = ()
    population_decision: CanonicalPopulationDecision | None = None

    def __post_init__(self) -> None:
        _require_text(self.claim, "claim")
        _require_text(self.rationale, "rationale")
        if not isinstance(self.evidence_class, EvidenceClass):
            raise ValueError("evidence_class must be an EvidenceClass")
        if not isinstance(self.role, EvidenceApplicabilityRole):
            raise ValueError("role must be an EvidenceApplicabilityRole")
        if not isinstance(self.decision, ApplicabilityDecision):
            raise ValueError("decision must be an ApplicabilityDecision")
        if self.population_decision is not None and not isinstance(
            self.population_decision, CanonicalPopulationDecision
        ):
            raise ValueError("population_decision must be a CanonicalPopulationDecision")
        if _EVIDENCE_ROLE_BY_CLASS[self.evidence_class] is not self.role:
            raise ValueError("evidence class and applicability role are inconsistent")
        if (
            self.population_decision is not None
            and self.evidence_class
            in (
                EvidenceClass.CANONICAL_EMPIRICAL_TARGET,
                EvidenceClass.DIRECT_TARGET_POPULATION_EVIDENCE,
            )
            and self.population_decision.status is not CanonicalPopulationStatus.PASS
        ):
            raise ValueError("target-population evidence requires a passing population decision")
        require_tuple(self.conditions, "conditions")
        _require_string_tuple(self.conditions, "conditions")
        require_tuple(self.evidence_references, "evidence_references")


# Constitution-facing aliases retain the stable terminology without duplicating wire types.
CanonicalFootballPopulationIdentity = PopulationIdentity
Season = SeasonIdentity
EvidenceApplicabilityV2 = V2EvidenceApplicability
