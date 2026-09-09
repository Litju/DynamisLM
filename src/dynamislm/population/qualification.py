"""Deterministic RES-60 population and canonical-source qualification."""

from __future__ import annotations

from dynamislm.population._authority import (
    ExpectedPopulationAuthority,
    ExpectedSourceAuthority,
    compute_population_authority,
    compute_source_authority,
)
from dynamislm.population.models import (
    CanonicalPopulationDecision,
    CanonicalPopulationStatus,
    CanonicalSource,
    CanonicalSourceDecision,
    CanonicalSourceStatus,
    ClauseStatus,
    EvidenceClass,
    PopulationClauseDecision,
    PopulationDimension,
    PopulationIdentity,
    SourceQualificationProvenance,
    SourceRequirement,
    SourceRequirementDecision,
)


def _population_decision(
    population: PopulationIdentity,
    expected: ExpectedPopulationAuthority,
) -> CanonicalPopulationDecision:
    return CanonicalPopulationDecision(
        decision_id=expected.decision_id,
        population=population,
        status=CanonicalPopulationStatus(expected.status),
        clauses=tuple(
            PopulationClauseDecision(
                dimension=PopulationDimension(clause.dimension),
                expected_value=clause.expected_value,
                observed_value=clause.observed_value,
                status=ClauseStatus(clause.status),
                reason_codes=clause.reason_codes,
                evidence_references=clause.evidence_references,
                missing_information=clause.missing_information,
            )
            for clause in expected.clauses
        ),
        failed_clauses=tuple(PopulationDimension(item) for item in expected.failed_clauses),
        unresolved_clauses=tuple(PopulationDimension(item) for item in expected.unresolved_clauses),
        missing_information=expected.missing_information,
        supporting_evidence=expected.supporting_evidence,
        method_reference=expected.method_reference,
        reason_codes=expected.reason_codes,
    )


def _source_decision(
    source: CanonicalSource,
    expected: ExpectedSourceAuthority,
) -> CanonicalSourceDecision:
    population_decision = _population_decision(source.population, expected.population_decision)
    return CanonicalSourceDecision(
        decision_id=expected.decision_id,
        source=source,
        population_decision=population_decision,
        status=CanonicalSourceStatus(expected.status),
        evidence_class=EvidenceClass(expected.evidence_class),
        requirements=tuple(
            SourceRequirementDecision(
                requirement=SourceRequirement(item.requirement),
                status=ClauseStatus(item.status),
                reason_codes=item.reason_codes,
                supporting_evidence=item.supporting_evidence,
                missing_information=item.missing_information,
            )
            for item in expected.requirements
        ),
        failed_requirements=tuple(SourceRequirement(item) for item in expected.failed_requirements),
        unresolved_requirements=tuple(
            SourceRequirement(item) for item in expected.unresolved_requirements
        ),
        missing_information=expected.missing_information,
        supporting_evidence=expected.supporting_evidence,
        method_reference=expected.method_reference,
        qualification_provenance=SourceQualificationProvenance(
            source_references=expected.qualification_provenance.source_references,
            evidence_references=expected.qualification_provenance.evidence_references,
            subgroup_provenance_references=(
                expected.qualification_provenance.subgroup_provenance_references
            ),
        ),
        license_reuse=expected.license_reuse,
        reason_codes=expected.reason_codes,
    )


def qualify_canonical_population(population: PopulationIdentity) -> CanonicalPopulationDecision:
    """Qualify one typed population against the exact six V2 clauses."""

    return _population_decision(population, compute_population_authority(population))


def qualify_canonical_source(source: CanonicalSource) -> CanonicalSourceDecision:
    """Qualify a source without changing its independent license/reuse status."""

    return _source_decision(source, compute_source_authority(source))


__all__ = [
    "qualify_canonical_population",
    "qualify_canonical_source",
]
