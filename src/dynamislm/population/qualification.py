"""Deterministic RES-60 population and canonical-source qualification."""

from __future__ import annotations

from enum import StrEnum

from dynamislm.measurement.identity import RegistryReference, ScientificIdentifier
from dynamislm.population.models import (
    AgeClass,
    CanonicalPopulationDecision,
    CanonicalPopulationStatus,
    CanonicalSource,
    CanonicalSourceDecision,
    CanonicalSourceStatus,
    ClauseStatus,
    CohortScopeType,
    CompetitionTier,
    DataGranularity,
    EvidenceClass,
    PopulationClauseDecision,
    PopulationDimension,
    PopulationEvidenceStatus,
    PopulationIdentity,
    PopulationResolutionStatus,
    ProfessionalStatus,
    Sex,
    SourceDataOrigin,
    SourceQualificationProvenance,
    SourceRequirement,
    SourceRequirementDecision,
    Sport,
    SquadLevel,
    SubgroupSeparability,
)
from dynamislm.population.registry import (
    CANONICAL_POPULATION_QUALIFICATION_METHOD,
    CANONICAL_SOURCE_QUALIFICATION_METHOD,
    RES60_REGISTRY_VERSION,
)
from dynamislm.refusal.models import RefusalReasonCode
from dynamislm.serialization import canonical_hash

_CANONICAL_EXPECTED: tuple[tuple[PopulationDimension, StrEnum], ...] = (
    (PopulationDimension.SEX, Sex.MALE),
    (PopulationDimension.AGE_CLASS, AgeClass.SENIOR),
    (PopulationDimension.SPORT, Sport.ASSOCIATION_FOOTBALL),
    (PopulationDimension.PROFESSIONAL_STATUS, ProfessionalStatus.PROFESSIONAL),
    (PopulationDimension.SQUAD_LEVEL, SquadLevel.FIRST_TEAM),
    (PopulationDimension.COMPETITION_TIER, CompetitionTier.TOP_DOMESTIC_DIVISION),
)

_DIMENSION_REASON: dict[PopulationDimension, RefusalReasonCode] = {
    PopulationDimension.SEX: RefusalReasonCode.SEX_OUTSIDE_CANONICAL_TARGET,
    PopulationDimension.AGE_CLASS: RefusalReasonCode.AGE_CLASS_OUTSIDE_CANONICAL_TARGET,
    PopulationDimension.SPORT: RefusalReasonCode.SPORT_OUTSIDE_CANONICAL_TARGET,
    PopulationDimension.PROFESSIONAL_STATUS: RefusalReasonCode.PROFESSIONAL_STATUS_MISMATCH,
    PopulationDimension.SQUAD_LEVEL: RefusalReasonCode.SQUAD_LEVEL_MISMATCH,
    PopulationDimension.COMPETITION_TIER: RefusalReasonCode.COMPETITION_TIER_MISMATCH,
}

_DIMENSION_LABEL: dict[PopulationDimension, str] = {
    PopulationDimension.SEX: "sex",
    PopulationDimension.AGE_CLASS: "age class",
    PopulationDimension.SPORT: "sport",
    PopulationDimension.PROFESSIONAL_STATUS: "professional status",
    PopulationDimension.SQUAD_LEVEL: "squad level",
    PopulationDimension.COMPETITION_TIER: "competition tier",
}


def _unique[T](values: tuple[T, ...] | list[T]) -> tuple[T, ...]:
    result: list[T] = []
    for value in values:
        if value not in result:
            result.append(value)
    return tuple(result)


def _decision_identifier(object_type: str, value: object) -> ScientificIdentifier:
    digest = canonical_hash(value).removeprefix("sha256:")
    return ScientificIdentifier(
        "dynamislm",
        object_type,
        digest,
        RES60_REGISTRY_VERSION,
    )


def _clause_for(
    population: PopulationIdentity,
    dimension: PopulationDimension,
    expected: StrEnum,
) -> PopulationClauseDecision:
    observed = population.value_for(dimension)
    observed_value = observed.value
    bindings = tuple(
        binding for binding in population.evidence_bindings if binding.dimension is dimension
    )
    evidence_references = tuple(
        binding.evidence_reference for binding in bindings if binding.evidence_reference is not None
    )
    evidence_references = _unique(evidence_references)
    missing_information: list[str] = []
    reason_codes: list[RefusalReasonCode] = []

    if population.resolution_status in (
        PopulationResolutionStatus.UNRESOLVED,
        PopulationResolutionStatus.CONFLICTING,
    ):
        missing_information.append(f"resolved population {_DIMENSION_LABEL[dimension]} evidence")
        reason_codes.append(RefusalReasonCode.POPULATION_METADATA_UNRESOLVED)
        return PopulationClauseDecision(
            dimension,
            expected.value,
            observed_value,
            ClauseStatus.UNRESOLVED,
            tuple(reason_codes),
            evidence_references,
            tuple(missing_information),
        )

    has_unresolved_binding = any(
        binding.status is not PopulationEvidenceStatus.ESTABLISHED for binding in bindings
    )
    established_values = tuple(
        binding.value
        for binding in bindings
        if binding.status is PopulationEvidenceStatus.ESTABLISHED and binding.value is not None
    )

    if not bindings:
        if observed_value == "UNKNOWN" or observed_value == expected.value:
            missing_information.append(
                f"source evidence establishing {_DIMENSION_LABEL[dimension]}"
            )
            reason_codes.append(RefusalReasonCode.REQUIRED_POPULATION_EVIDENCE_MISSING)
            return PopulationClauseDecision(
                dimension,
                expected.value,
                observed_value,
                ClauseStatus.UNRESOLVED,
                tuple(reason_codes),
                evidence_references,
                tuple(missing_information),
            )
        reason_codes.append(_DIMENSION_REASON[dimension])
        return PopulationClauseDecision(
            dimension,
            expected.value,
            observed_value,
            ClauseStatus.FAIL,
            tuple(reason_codes),
            evidence_references,
        )

    if has_unresolved_binding:
        missing_information.extend(
            missing for binding in bindings for missing in binding.missing_information
        )
        if not missing_information:
            missing_information.append(
                f"resolved source evidence for {_DIMENSION_LABEL[dimension]}"
            )
        if (
            any(binding.status is PopulationEvidenceStatus.CONFLICTING for binding in bindings)
            or len(set(established_values)) > 1
        ):
            reason_codes.append(RefusalReasonCode.POPULATION_METADATA_CONFLICTING)
        else:
            reason_codes.append(RefusalReasonCode.REQUIRED_POPULATION_EVIDENCE_MISSING)
        return PopulationClauseDecision(
            dimension,
            expected.value,
            observed_value,
            ClauseStatus.UNRESOLVED,
            tuple(reason_codes),
            evidence_references,
            tuple(_unique(missing_information)),
        )

    if len(set(established_values)) != 1 or established_values[0] != observed_value:
        return PopulationClauseDecision(
            dimension,
            expected.value,
            observed_value,
            ClauseStatus.UNRESOLVED,
            (RefusalReasonCode.POPULATION_METADATA_CONFLICTING,),
            evidence_references,
            (f"consistent source evidence for {_DIMENSION_LABEL[dimension]}",),
        )

    if observed_value == "UNKNOWN":
        return PopulationClauseDecision(
            dimension,
            expected.value,
            observed_value,
            ClauseStatus.UNRESOLVED,
            (RefusalReasonCode.REQUIRED_POPULATION_EVIDENCE_MISSING,),
            evidence_references,
            (f"resolved source evidence for {_DIMENSION_LABEL[dimension]}",),
        )

    if observed_value == expected.value:
        return PopulationClauseDecision(
            dimension,
            expected.value,
            observed_value,
            ClauseStatus.PASS,
            (),
            evidence_references,
        )

    return PopulationClauseDecision(
        dimension,
        expected.value,
        observed_value,
        ClauseStatus.FAIL,
        (_DIMENSION_REASON[dimension],),
        evidence_references,
    )


def qualify_canonical_population(
    population: PopulationIdentity,
) -> CanonicalPopulationDecision:
    """Qualify one typed population against the exact six V2 clauses."""

    clauses = tuple(
        _clause_for(population, dimension, expected) for dimension, expected in _CANONICAL_EXPECTED
    )
    failed = tuple(clause.dimension for clause in clauses if clause.status is ClauseStatus.FAIL)
    unresolved = tuple(
        clause.dimension for clause in clauses if clause.status is ClauseStatus.UNRESOLVED
    )
    status = (
        CanonicalPopulationStatus.NONCANONICAL
        if failed
        else CanonicalPopulationStatus.UNRESOLVED
        if unresolved
        else CanonicalPopulationStatus.PASS
    )
    missing_information = _unique(
        [missing for clause in clauses for missing in clause.missing_information]
    )
    supporting_evidence = _unique(
        [reference for clause in clauses for reference in clause.evidence_references]
    )
    reason_codes = _unique([reason for clause in clauses for reason in clause.reason_codes])
    return CanonicalPopulationDecision(
        decision_id=_decision_identifier("canonical-population-decision", population),
        population=population,
        status=status,
        clauses=clauses,
        failed_clauses=failed,
        unresolved_clauses=unresolved,
        missing_information=missing_information,
        supporting_evidence=supporting_evidence,
        method_reference=CANONICAL_POPULATION_QUALIFICATION_METHOD,
        reason_codes=reason_codes,
    )


def _source_requirement(
    requirement: SourceRequirement,
    status: ClauseStatus,
    reason_codes: tuple[RefusalReasonCode, ...] = (),
    supporting_evidence: tuple[RegistryReference, ...] = (),
    missing_information: tuple[str, ...] = (),
) -> SourceRequirementDecision:
    return SourceRequirementDecision(
        requirement=requirement,
        status=status,
        reason_codes=reason_codes,
        supporting_evidence=supporting_evidence,
        missing_information=missing_information,
    )


def _population_requirement(
    decision: CanonicalPopulationDecision,
) -> SourceRequirementDecision:
    if decision.status is CanonicalPopulationStatus.PASS:
        return _source_requirement(
            SourceRequirement.POPULATION_MATCH,
            ClauseStatus.PASS,
            supporting_evidence=decision.supporting_evidence,
        )
    if decision.status is CanonicalPopulationStatus.NONCANONICAL:
        return _source_requirement(
            SourceRequirement.POPULATION_MATCH,
            ClauseStatus.FAIL,
            reason_codes=_unique(
                list(decision.reason_codes) or [RefusalReasonCode.CANONICAL_POPULATION_MISMATCH]
            ),
            supporting_evidence=decision.supporting_evidence,
        )
    return _source_requirement(
        SourceRequirement.POPULATION_MATCH,
        ClauseStatus.UNRESOLVED,
        reason_codes=_unique(
            list(decision.reason_codes) or [RefusalReasonCode.POPULATION_METADATA_UNRESOLVED]
        ),
        supporting_evidence=decision.supporting_evidence,
        missing_information=decision.missing_information
        or ("resolved canonical population decision",),
    )


def _origin_requirement(source: CanonicalSource) -> SourceRequirementDecision:
    if source.data_origin is SourceDataOrigin.ACTUAL_OBSERVED_MEASURED:
        return _source_requirement(SourceRequirement.ACTUAL_OBSERVED_DATA, ClauseStatus.PASS)
    if source.data_origin is SourceDataOrigin.UNKNOWN:
        return _source_requirement(
            SourceRequirement.ACTUAL_OBSERVED_DATA,
            ClauseStatus.UNRESOLVED,
            reason_codes=(RefusalReasonCode.SOURCE_ORIGIN_UNRESOLVED,),
            missing_information=("actual observed/measured source origin",),
        )
    return _source_requirement(
        SourceRequirement.ACTUAL_OBSERVED_DATA,
        ClauseStatus.FAIL,
        reason_codes=(RefusalReasonCode.EMPIRICAL_ORIGIN_NOT_ACTUAL_OBSERVED,),
    )


def _scope_requirement(source: CanonicalSource) -> SourceRequirementDecision:
    scope = source.cohort_scope
    if scope.scope_type is CohortScopeType.WHOLE_COHORT:
        if scope.separability is SubgroupSeparability.EXACT_TARGET_COHORT:
            return _source_requirement(SourceRequirement.TARGET_SUBGROUP_SCOPE, ClauseStatus.PASS)
        if scope.separability is SubgroupSeparability.NOT_SEPARABLE:
            return _source_requirement(
                SourceRequirement.TARGET_SUBGROUP_SCOPE,
                ClauseStatus.FAIL,
                reason_codes=(RefusalReasonCode.TARGET_SUBGROUP_NOT_SEPARABLE,),
            )
        return _source_requirement(
            SourceRequirement.TARGET_SUBGROUP_SCOPE,
            ClauseStatus.UNRESOLVED,
            reason_codes=(RefusalReasonCode.SUBGROUP_SEPARABILITY_UNKNOWN,),
            missing_information=("exact target cohort scope",),
        )

    if scope.scope_type in (
        CohortScopeType.MIXED_PARENT_COHORT,
        CohortScopeType.SEPARATED_SUBGROUP,
    ):
        if scope.separability is SubgroupSeparability.NOT_SEPARABLE:
            return _source_requirement(
                SourceRequirement.TARGET_SUBGROUP_SCOPE,
                ClauseStatus.FAIL,
                reason_codes=(RefusalReasonCode.TARGET_SUBGROUP_NOT_SEPARABLE,),
            )
        if scope.separability is SubgroupSeparability.UNKNOWN:
            return _source_requirement(
                SourceRequirement.TARGET_SUBGROUP_SCOPE,
                ClauseStatus.UNRESOLVED,
                reason_codes=(RefusalReasonCode.SUBGROUP_SEPARABILITY_UNKNOWN,),
                missing_information=("target subgroup separability",),
            )
        missing: list[str] = []
        if scope.parent_cohort_id is None:
            missing.append("parent mixed-cohort identity")
        if scope.evaluated_subgroup_id is None:
            missing.append("evaluated target subgroup identity")
        if not scope.extraction_evidence:
            missing.append("evidence identifying the extracted target subgroup")
        if not scope.provenance_references:
            missing.append("provenance for target subgroup extraction")
        if missing:
            return _source_requirement(
                SourceRequirement.TARGET_SUBGROUP_SCOPE,
                ClauseStatus.UNRESOLVED,
                reason_codes=(RefusalReasonCode.SUBGROUP_PROVENANCE_MISSING,),
                supporting_evidence=scope.extraction_evidence,
                missing_information=tuple(missing),
            )
        return _source_requirement(
            SourceRequirement.TARGET_SUBGROUP_SCOPE,
            ClauseStatus.PASS,
            supporting_evidence=scope.extraction_evidence + scope.provenance_references,
        )

    return _source_requirement(
        SourceRequirement.TARGET_SUBGROUP_SCOPE,
        ClauseStatus.UNRESOLVED,
        reason_codes=(RefusalReasonCode.SUBGROUP_SEPARABILITY_UNKNOWN,),
        missing_information=("whole-cohort or explicitly separated target subgroup scope",),
    )


def _identity_requirement(source: CanonicalSource) -> SourceRequirementDecision:
    # CanonicalSource construction already validates both pieces. The qualification
    # decision still records their authority as a separate source-level requirement.
    if not source.source_id.stable_id or not source.source_revision.strip():
        return _source_requirement(
            SourceRequirement.SOURCE_IDENTITY_AND_PROVENANCE,
            ClauseStatus.UNRESOLVED,
            reason_codes=(RefusalReasonCode.SOURCE_IDENTITY_INADEQUATE,),
            missing_information=("stable source identifier and revision",),
        )
    return _source_requirement(
        SourceRequirement.SOURCE_IDENTITY_AND_PROVENANCE,
        ClauseStatus.PASS,
        supporting_evidence=source.provenance_references,
    )


def _granularity_requirement(source: CanonicalSource) -> SourceRequirementDecision:
    if source.data_granularity in (DataGranularity.ATHLETE_LEVEL, DataGranularity.TRIAL_LEVEL):
        return _source_requirement(SourceRequirement.DATA_GRANULARITY, ClauseStatus.PASS)
    if source.data_granularity is DataGranularity.UNKNOWN:
        return _source_requirement(
            SourceRequirement.DATA_GRANULARITY,
            ClauseStatus.UNRESOLVED,
            reason_codes=(RefusalReasonCode.DATA_GRANULARITY_UNRESOLVED,),
            missing_information=("observed athlete/trial data granularity",),
        )
    return _source_requirement(
        SourceRequirement.DATA_GRANULARITY,
        ClauseStatus.FAIL,
        reason_codes=(RefusalReasonCode.DATA_GRANULARITY_INSUFFICIENT,),
    )


def _qualification_provenance(
    source: CanonicalSource,
    population_decision: CanonicalPopulationDecision,
) -> SourceQualificationProvenance:
    source_references = [source.source_id]
    if source.publication_reference is not None:
        source_references.append(source.publication_reference)
    evidence_references = list(population_decision.supporting_evidence)
    evidence_references.extend(source.provenance_references)
    subgroup_provenance = list(source.cohort_scope.extraction_evidence)
    subgroup_provenance.extend(source.cohort_scope.provenance_references)
    return SourceQualificationProvenance(
        source_references=_unique(source_references),
        evidence_references=_unique(evidence_references),
        subgroup_provenance_references=_unique(subgroup_provenance),
    )


def qualify_canonical_source(source: CanonicalSource) -> CanonicalSourceDecision:
    """Qualify a source without changing its independent license/reuse status."""

    population_decision = qualify_canonical_population(source.population)
    requirements = (
        _population_requirement(population_decision),
        _origin_requirement(source),
        _scope_requirement(source),
        _identity_requirement(source),
        _granularity_requirement(source),
    )
    failed = tuple(item.requirement for item in requirements if item.status is ClauseStatus.FAIL)
    unresolved = tuple(
        item.requirement for item in requirements if item.status is ClauseStatus.UNRESOLVED
    )
    status = (
        CanonicalSourceStatus.CANONICAL_ELIGIBILITY_FAILED
        if failed
        else CanonicalSourceStatus.UNRESOLVED
        if unresolved
        else CanonicalSourceStatus.CANONICAL_EMPIRICAL_TARGET
    )
    missing_information = _unique(
        [missing for item in requirements for missing in item.missing_information]
    )
    supporting_evidence = _unique(
        [reference for item in requirements for reference in item.supporting_evidence]
    )
    reason_codes = _unique([reason for item in requirements for reason in item.reason_codes])
    return CanonicalSourceDecision(
        decision_id=_decision_identifier("canonical-source-decision", source),
        source=source,
        population_decision=population_decision,
        status=status,
        evidence_class=(
            EvidenceClass.CANONICAL_EMPIRICAL_TARGET
            if status is CanonicalSourceStatus.CANONICAL_EMPIRICAL_TARGET
            else EvidenceClass.REJECTED_OR_UNRESOLVED
        ),
        requirements=requirements,
        failed_requirements=failed,
        unresolved_requirements=unresolved,
        missing_information=missing_information,
        supporting_evidence=supporting_evidence,
        method_reference=CANONICAL_SOURCE_QUALIFICATION_METHOD,
        qualification_provenance=_qualification_provenance(source, population_decision),
        license_reuse=source.license_reuse,
        reason_codes=reason_codes,
    )


__all__ = [
    "qualify_canonical_population",
    "qualify_canonical_source",
]
