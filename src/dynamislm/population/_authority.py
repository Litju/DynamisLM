"""Pure RES-60 authority derivation and decision integrity checks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from dynamislm.measurement.identity import RegistryReference, ScientificIdentifier
from dynamislm.population.registry import (
    CANONICAL_POPULATION_QUALIFICATION_METHOD,
    CANONICAL_SOURCE_QUALIFICATION_METHOD,
    RES60_REGISTRY_VERSION,
)
from dynamislm.refusal.models import RefusalReasonCode
from dynamislm.serialization import canonical_hash

_CANONICAL_EXPECTED: tuple[tuple[str, str], ...] = (
    ("SEX", "MALE"),
    ("AGE_CLASS", "SENIOR"),
    ("SPORT", "ASSOCIATION_FOOTBALL"),
    ("PROFESSIONAL_STATUS", "PROFESSIONAL"),
    ("SQUAD_LEVEL", "FIRST_TEAM"),
    ("COMPETITION_TIER", "TOP_DOMESTIC_DIVISION"),
)

_DIMENSION_FIELD: dict[str, str] = {
    "SEX": "sex",
    "AGE_CLASS": "age_class",
    "SPORT": "sport",
    "PROFESSIONAL_STATUS": "professional_status",
    "SQUAD_LEVEL": "squad_level",
    "COMPETITION_TIER": "competition_tier",
}

_DIMENSION_REASON: dict[str, RefusalReasonCode] = {
    "SEX": RefusalReasonCode.SEX_OUTSIDE_CANONICAL_TARGET,
    "AGE_CLASS": RefusalReasonCode.AGE_CLASS_OUTSIDE_CANONICAL_TARGET,
    "SPORT": RefusalReasonCode.SPORT_OUTSIDE_CANONICAL_TARGET,
    "PROFESSIONAL_STATUS": RefusalReasonCode.PROFESSIONAL_STATUS_MISMATCH,
    "SQUAD_LEVEL": RefusalReasonCode.SQUAD_LEVEL_MISMATCH,
    "COMPETITION_TIER": RefusalReasonCode.COMPETITION_TIER_MISMATCH,
}

_DIMENSION_LABEL: dict[str, str] = {
    "SEX": "sex",
    "AGE_CLASS": "age class",
    "SPORT": "sport",
    "PROFESSIONAL_STATUS": "professional status",
    "SQUAD_LEVEL": "squad level",
    "COMPETITION_TIER": "competition tier",
}

_CANONICAL_SOURCE_REQUIREMENTS = (
    "POPULATION_MATCH",
    "ACTUAL_OBSERVED_DATA",
    "TARGET_SUBGROUP_SCOPE",
    "SOURCE_IDENTITY_AND_PROVENANCE",
    "DATA_GRANULARITY",
)


def _enum_value(value: Any) -> str:
    candidate = getattr(value, "value", value)
    if not isinstance(candidate, str):
        raise ValueError("RES-60 authority inputs must expose string enum values")
    return candidate


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


@dataclass(frozen=True, slots=True)
class ExpectedPopulationClause:
    dimension: str
    expected_value: str
    observed_value: str | None
    status: str
    reason_codes: tuple[RefusalReasonCode, ...]
    evidence_references: tuple[RegistryReference, ...]
    missing_information: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ExpectedPopulationAuthority:
    decision_id: ScientificIdentifier
    status: str
    clauses: tuple[ExpectedPopulationClause, ...]
    failed_clauses: tuple[str, ...]
    unresolved_clauses: tuple[str, ...]
    missing_information: tuple[str, ...]
    supporting_evidence: tuple[RegistryReference, ...]
    method_reference: RegistryReference
    reason_codes: tuple[RefusalReasonCode, ...]


@dataclass(frozen=True, slots=True)
class ExpectedSourceRequirement:
    requirement: str
    status: str
    reason_codes: tuple[RefusalReasonCode, ...]
    supporting_evidence: tuple[RegistryReference, ...]
    missing_information: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ExpectedSourceQualificationProvenance:
    source_references: tuple[RegistryReference, ...]
    evidence_references: tuple[RegistryReference, ...]
    subgroup_provenance_references: tuple[RegistryReference, ...]


@dataclass(frozen=True, slots=True)
class ExpectedSourceAuthority:
    decision_id: ScientificIdentifier
    population_decision: ExpectedPopulationAuthority
    status: str
    evidence_class: str
    requirements: tuple[ExpectedSourceRequirement, ...]
    failed_requirements: tuple[str, ...]
    unresolved_requirements: tuple[str, ...]
    missing_information: tuple[str, ...]
    supporting_evidence: tuple[RegistryReference, ...]
    method_reference: RegistryReference
    qualification_provenance: ExpectedSourceQualificationProvenance
    license_reuse: Any
    reason_codes: tuple[RefusalReasonCode, ...]


def _clause_for(
    population: Any,
    dimension: str,
    expected_value: str,
) -> ExpectedPopulationClause:
    observed_value = _enum_value(getattr(population, _DIMENSION_FIELD[dimension]))
    bindings = tuple(
        binding
        for binding in population.evidence_bindings
        if _enum_value(binding.dimension) == dimension
    )
    evidence_references = _unique(
        tuple(binding.evidence_reference for binding in bindings if binding.evidence_reference)
    )
    missing_information: list[str] = []
    reason_codes: list[RefusalReasonCode] = []

    if _enum_value(population.resolution_status) in ("UNRESOLVED", "CONFLICTING"):
        missing_information.append(f"resolved population {_DIMENSION_LABEL[dimension]} evidence")
        reason_codes.append(RefusalReasonCode.POPULATION_METADATA_UNRESOLVED)
        return ExpectedPopulationClause(
            dimension,
            expected_value,
            observed_value,
            "UNRESOLVED",
            tuple(reason_codes),
            evidence_references,
            tuple(missing_information),
        )

    has_unresolved_binding = any(
        _enum_value(binding.status) != "ESTABLISHED" for binding in bindings
    )
    established_values = tuple(
        _enum_value(binding.value)
        for binding in bindings
        if _enum_value(binding.status) == "ESTABLISHED" and binding.value is not None
    )

    if not bindings:
        if observed_value == "UNKNOWN" or observed_value == expected_value:
            missing_information.append(
                f"source evidence establishing {_DIMENSION_LABEL[dimension]}"
            )
            reason_codes.append(RefusalReasonCode.REQUIRED_POPULATION_EVIDENCE_MISSING)
            return ExpectedPopulationClause(
                dimension,
                expected_value,
                observed_value,
                "UNRESOLVED",
                tuple(reason_codes),
                evidence_references,
                tuple(missing_information),
            )
        reason_codes.append(_DIMENSION_REASON[dimension])
        return ExpectedPopulationClause(
            dimension,
            expected_value,
            observed_value,
            "FAIL",
            tuple(reason_codes),
            evidence_references,
            tuple(missing_information),
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
            any(_enum_value(binding.status) == "CONFLICTING" for binding in bindings)
            or len(set(established_values)) > 1
        ):
            reason_codes.append(RefusalReasonCode.POPULATION_METADATA_CONFLICTING)
        else:
            reason_codes.append(RefusalReasonCode.REQUIRED_POPULATION_EVIDENCE_MISSING)
        return ExpectedPopulationClause(
            dimension,
            expected_value,
            observed_value,
            "UNRESOLVED",
            tuple(reason_codes),
            evidence_references,
            _unique(missing_information),
        )

    if len(set(established_values)) != 1 or established_values[0] != observed_value:
        return ExpectedPopulationClause(
            dimension,
            expected_value,
            observed_value,
            "UNRESOLVED",
            (RefusalReasonCode.POPULATION_METADATA_CONFLICTING,),
            evidence_references,
            (f"consistent source evidence for {_DIMENSION_LABEL[dimension]}",),
        )

    if observed_value == "UNKNOWN":
        return ExpectedPopulationClause(
            dimension,
            expected_value,
            observed_value,
            "UNRESOLVED",
            (RefusalReasonCode.REQUIRED_POPULATION_EVIDENCE_MISSING,),
            evidence_references,
            (f"resolved source evidence for {_DIMENSION_LABEL[dimension]}",),
        )

    if observed_value == expected_value:
        return ExpectedPopulationClause(
            dimension,
            expected_value,
            observed_value,
            "PASS",
            (),
            evidence_references,
            (),
        )

    return ExpectedPopulationClause(
        dimension,
        expected_value,
        observed_value,
        "FAIL",
        (_DIMENSION_REASON[dimension],),
        evidence_references,
        (),
    )


def compute_population_authority(population: Any) -> ExpectedPopulationAuthority:
    """Derive every population decision field from the typed population input."""

    clauses = tuple(
        _clause_for(population, dimension, expected_value)
        for dimension, expected_value in _CANONICAL_EXPECTED
    )
    failed = tuple(clause.dimension for clause in clauses if clause.status == "FAIL")
    unresolved = tuple(clause.dimension for clause in clauses if clause.status == "UNRESOLVED")
    status = "NONCANONICAL" if failed else "UNRESOLVED" if unresolved else "PASS"
    missing_information = _unique(
        [missing for clause in clauses for missing in clause.missing_information]
    )
    supporting_evidence = _unique(
        [reference for clause in clauses for reference in clause.evidence_references]
    )
    reason_codes = _unique([reason for clause in clauses for reason in clause.reason_codes])
    return ExpectedPopulationAuthority(
        decision_id=_decision_identifier("canonical-population-decision", population),
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
    requirement: str,
    status: str,
    reason_codes: tuple[RefusalReasonCode, ...] = (),
    supporting_evidence: tuple[RegistryReference, ...] = (),
    missing_information: tuple[str, ...] = (),
) -> ExpectedSourceRequirement:
    return ExpectedSourceRequirement(
        requirement,
        status,
        reason_codes,
        supporting_evidence,
        missing_information,
    )


def _population_requirement(
    decision: ExpectedPopulationAuthority,
) -> ExpectedSourceRequirement:
    if decision.status == "PASS":
        return _source_requirement(
            "POPULATION_MATCH",
            "PASS",
            supporting_evidence=decision.supporting_evidence,
        )
    if decision.status == "NONCANONICAL":
        return _source_requirement(
            "POPULATION_MATCH",
            "FAIL",
            reason_codes=_unique(
                list(decision.reason_codes) or [RefusalReasonCode.CANONICAL_POPULATION_MISMATCH]
            ),
            supporting_evidence=decision.supporting_evidence,
        )
    return _source_requirement(
        "POPULATION_MATCH",
        "UNRESOLVED",
        reason_codes=_unique(
            list(decision.reason_codes) or [RefusalReasonCode.POPULATION_METADATA_UNRESOLVED]
        ),
        supporting_evidence=decision.supporting_evidence,
        missing_information=decision.missing_information
        or ("resolved canonical population decision",),
    )


def _origin_requirement(source: Any) -> ExpectedSourceRequirement:
    origin = _enum_value(source.data_origin)
    if origin == "ACTUAL_OBSERVED_MEASURED":
        return _source_requirement("ACTUAL_OBSERVED_DATA", "PASS")
    if origin == "UNKNOWN":
        return _source_requirement(
            "ACTUAL_OBSERVED_DATA",
            "UNRESOLVED",
            reason_codes=(RefusalReasonCode.SOURCE_ORIGIN_UNRESOLVED,),
            missing_information=("actual observed/measured source origin",),
        )
    return _source_requirement(
        "ACTUAL_OBSERVED_DATA",
        "FAIL",
        reason_codes=(RefusalReasonCode.EMPIRICAL_ORIGIN_NOT_ACTUAL_OBSERVED,),
    )


def _scope_requirement(source: Any) -> ExpectedSourceRequirement:
    scope = source.cohort_scope
    scope_type = _enum_value(scope.scope_type)
    separability = _enum_value(scope.separability)
    if scope_type == "WHOLE_COHORT":
        if separability == "EXACT_TARGET_COHORT":
            return _source_requirement("TARGET_SUBGROUP_SCOPE", "PASS")
        if separability == "NOT_SEPARABLE":
            return _source_requirement(
                "TARGET_SUBGROUP_SCOPE",
                "FAIL",
                reason_codes=(RefusalReasonCode.TARGET_SUBGROUP_NOT_SEPARABLE,),
            )
        return _source_requirement(
            "TARGET_SUBGROUP_SCOPE",
            "UNRESOLVED",
            reason_codes=(RefusalReasonCode.SUBGROUP_SEPARABILITY_UNKNOWN,),
            missing_information=("exact target cohort scope",),
        )

    if scope_type in ("MIXED_PARENT_COHORT", "SEPARATED_SUBGROUP"):
        if separability == "NOT_SEPARABLE":
            return _source_requirement(
                "TARGET_SUBGROUP_SCOPE",
                "FAIL",
                reason_codes=(RefusalReasonCode.TARGET_SUBGROUP_NOT_SEPARABLE,),
            )
        if separability == "UNKNOWN":
            return _source_requirement(
                "TARGET_SUBGROUP_SCOPE",
                "UNRESOLVED",
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
                "TARGET_SUBGROUP_SCOPE",
                "UNRESOLVED",
                reason_codes=(RefusalReasonCode.SUBGROUP_PROVENANCE_MISSING,),
                supporting_evidence=scope.extraction_evidence,
                missing_information=tuple(missing),
            )
        return _source_requirement(
            "TARGET_SUBGROUP_SCOPE",
            "PASS",
            supporting_evidence=scope.extraction_evidence + scope.provenance_references,
        )

    return _source_requirement(
        "TARGET_SUBGROUP_SCOPE",
        "UNRESOLVED",
        reason_codes=(RefusalReasonCode.SUBGROUP_SEPARABILITY_UNKNOWN,),
        missing_information=("whole-cohort or explicitly separated target subgroup scope",),
    )


def _identity_requirement(source: Any) -> ExpectedSourceRequirement:
    if not source.source_id.stable_id or not source.source_revision.strip():
        return _source_requirement(
            "SOURCE_IDENTITY_AND_PROVENANCE",
            "UNRESOLVED",
            reason_codes=(RefusalReasonCode.SOURCE_IDENTITY_INADEQUATE,),
            missing_information=("stable source identifier and revision",),
        )
    return _source_requirement(
        "SOURCE_IDENTITY_AND_PROVENANCE",
        "PASS",
        supporting_evidence=source.provenance_references,
    )


def _granularity_requirement(source: Any) -> ExpectedSourceRequirement:
    granularity = _enum_value(source.data_granularity)
    if granularity in ("ATHLETE_LEVEL", "TRIAL_LEVEL"):
        return _source_requirement("DATA_GRANULARITY", "PASS")
    if granularity == "UNKNOWN":
        return _source_requirement(
            "DATA_GRANULARITY",
            "UNRESOLVED",
            reason_codes=(RefusalReasonCode.DATA_GRANULARITY_UNRESOLVED,),
            missing_information=("observed athlete/trial data granularity",),
        )
    return _source_requirement(
        "DATA_GRANULARITY",
        "FAIL",
        reason_codes=(RefusalReasonCode.DATA_GRANULARITY_INSUFFICIENT,),
    )


def _qualification_provenance(
    source: Any,
    population_decision: ExpectedPopulationAuthority,
) -> ExpectedSourceQualificationProvenance:
    source_references = [source.source_id]
    if source.publication_reference is not None:
        source_references.append(source.publication_reference)
    evidence_references = list(population_decision.supporting_evidence)
    evidence_references.extend(source.provenance_references)
    subgroup_provenance = list(source.cohort_scope.extraction_evidence)
    subgroup_provenance.extend(source.cohort_scope.provenance_references)
    return ExpectedSourceQualificationProvenance(
        source_references=_unique(source_references),
        evidence_references=_unique(evidence_references),
        subgroup_provenance_references=_unique(subgroup_provenance),
    )


def compute_source_authority(source: Any) -> ExpectedSourceAuthority:
    """Derive every source decision field from the typed source input."""

    population_decision = compute_population_authority(source.population)
    requirements = (
        _population_requirement(population_decision),
        _origin_requirement(source),
        _scope_requirement(source),
        _identity_requirement(source),
        _granularity_requirement(source),
    )
    failed = tuple(item.requirement for item in requirements if item.status == "FAIL")
    unresolved = tuple(item.requirement for item in requirements if item.status == "UNRESOLVED")
    status = (
        "CANONICAL_ELIGIBILITY_FAILED"
        if failed
        else "UNRESOLVED"
        if unresolved
        else "CANONICAL_EMPIRICAL_TARGET"
    )
    missing_information = _unique(
        [missing for item in requirements for missing in item.missing_information]
    )
    supporting_evidence = _unique(
        [reference for item in requirements for reference in item.supporting_evidence]
    )
    reason_codes = _unique([reason for item in requirements for reason in item.reason_codes])
    return ExpectedSourceAuthority(
        decision_id=_decision_identifier("canonical-source-decision", source),
        population_decision=population_decision,
        status=status,
        evidence_class=(
            "CANONICAL_EMPIRICAL_TARGET"
            if status == "CANONICAL_EMPIRICAL_TARGET"
            else "REJECTED_OR_UNRESOLVED"
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


def _population_mismatch(detail: str) -> ValueError:
    return ValueError(f"population authority does not match: {detail}")


def validate_population_decision(
    decision: Any,
    expected: ExpectedPopulationAuthority,
) -> None:
    """Fail closed when any population-derived field differs from recomputation."""

    if decision.decision_id != expected.decision_id:
        raise _population_mismatch("population decision_id")
    if tuple(_enum_value(clause.dimension) for clause in decision.clauses) != tuple(
        clause.dimension for clause in expected.clauses
    ):
        raise _population_mismatch("clause ordering")

    for actual, expected_clause in zip(decision.clauses, expected.clauses, strict=True):
        if (
            _enum_value(actual.dimension) != expected_clause.dimension
            or actual.expected_value != expected_clause.expected_value
            or actual.observed_value != expected_clause.observed_value
            or _enum_value(actual.status) != expected_clause.status
            or tuple(actual.reason_codes) != expected_clause.reason_codes
            or actual.evidence_references != expected_clause.evidence_references
            or actual.missing_information != expected_clause.missing_information
        ):
            raise _population_mismatch(
                f"population clause authority does not match for {expected_clause.dimension}"
            )

    if _enum_value(decision.status) != expected.status:
        raise _population_mismatch("status")
    if tuple(_enum_value(item) for item in decision.failed_clauses) != expected.failed_clauses:
        raise _population_mismatch("failed_clauses")
    if (
        tuple(_enum_value(item) for item in decision.unresolved_clauses)
        != expected.unresolved_clauses
    ):
        raise _population_mismatch("unresolved_clauses")
    if decision.missing_information != expected.missing_information:
        raise _population_mismatch("missing_information")
    if decision.supporting_evidence != expected.supporting_evidence:
        raise _population_mismatch("supporting_evidence")
    if decision.method_reference != expected.method_reference:
        raise _population_mismatch("population method reference")
    if tuple(decision.reason_codes) != expected.reason_codes:
        raise _population_mismatch("reason_codes")


def validate_source_decision(
    decision: Any,
    expected: ExpectedSourceAuthority,
) -> None:
    """Fail closed when any source-derived field differs from recomputation."""

    if decision.decision_id != expected.decision_id:
        raise ValueError("source authority does not match: source decision_id")
    if decision.population_decision.population != decision.source.population:
        raise ValueError("source population decision does not evaluate source population")
    validate_population_decision(decision.population_decision, expected.population_decision)
    if tuple(_enum_value(item.requirement) for item in decision.requirements) != tuple(
        item.requirement for item in expected.requirements
    ):
        raise ValueError("source authority does not match: requirement ordering")

    for actual, expected_requirement in zip(
        decision.requirements,
        expected.requirements,
        strict=True,
    ):
        if (
            _enum_value(actual.requirement) != expected_requirement.requirement
            or _enum_value(actual.status) != expected_requirement.status
            or tuple(actual.reason_codes) != expected_requirement.reason_codes
            or actual.supporting_evidence != expected_requirement.supporting_evidence
            or actual.missing_information != expected_requirement.missing_information
        ):
            raise ValueError(
                "source requirement authority does not match "
                f"for {expected_requirement.requirement}"
            )

    if _enum_value(decision.status) != expected.status:
        raise ValueError("source authority does not match: status")
    if _enum_value(decision.evidence_class) != expected.evidence_class:
        raise ValueError("source authority does not match: evidence_class")
    if (
        tuple(_enum_value(item) for item in decision.failed_requirements)
        != expected.failed_requirements
    ):
        raise ValueError("source authority does not match: failed_requirements")
    if (
        tuple(_enum_value(item) for item in decision.unresolved_requirements)
        != expected.unresolved_requirements
    ):
        raise ValueError("source authority does not match: unresolved_requirements")
    if decision.missing_information != expected.missing_information:
        raise ValueError("source authority does not match: missing_information")
    if decision.supporting_evidence != expected.supporting_evidence:
        raise ValueError("source authority does not match: supporting_evidence")
    if decision.method_reference != expected.method_reference:
        raise ValueError("source method reference does not match registered authority")
    if (
        decision.qualification_provenance.source_references
        != expected.qualification_provenance.source_references
        or decision.qualification_provenance.evidence_references
        != expected.qualification_provenance.evidence_references
        or decision.qualification_provenance.subgroup_provenance_references
        != expected.qualification_provenance.subgroup_provenance_references
    ):
        raise ValueError("source authority does not match: qualification_provenance")
    if decision.license_reuse != expected.license_reuse:
        raise ValueError("source authority does not match: license_reuse")
    if tuple(decision.reason_codes) != expected.reason_codes:
        raise ValueError("source authority does not match: reason_codes")


__all__ = [
    "ExpectedPopulationAuthority",
    "ExpectedPopulationClause",
    "ExpectedSourceAuthority",
    "ExpectedSourceQualificationProvenance",
    "ExpectedSourceRequirement",
    "compute_population_authority",
    "compute_source_authority",
    "validate_population_decision",
    "validate_source_decision",
]
