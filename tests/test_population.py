from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import replace
from typing import Any, cast

import pytest

from dynamislm import (
    ApplicabilityDecision,
    CanonicalPopulationStatus,
    CanonicalSource,
    CanonicalSourceStatus,
    ClauseStatus,
    CohortScope,
    CohortScopeType,
    CompetitionIdentity,
    CompetitionTier,
    DataGranularity,
    EvidenceApplicabilityRole,
    EvidenceApplicabilityV2,
    EvidenceClass,
    LicenseReuseMetadata,
    PopulationDimension,
    PopulationEvidenceBinding,
    PopulationEvidenceStatus,
    PopulationIdentity,
    ProfessionalStatus,
    ReuseStatus,
    SeasonIdentity,
    Sex,
    SourceDataOrigin,
    SourceRequirement,
    Sport,
    SquadLevel,
    SubgroupSeparability,
    canonical_hash,
    canonical_json,
    from_canonical_json,
    qualify_canonical_population,
    qualify_canonical_source,
)
from dynamislm.measurement.identity import RegistryReference, ScientificIdentifier
from dynamislm.population import AgeClass, PopulationResolutionStatus
from dynamislm.refusal import RefusalReasonCode


def _reference(object_type: str, key: str, label: str) -> RegistryReference:
    return RegistryReference(
        ScientificIdentifier("test", object_type, key, "1.0.0"),
        label,
    )


def _identifier(object_type: str, key: str) -> ScientificIdentifier:
    return ScientificIdentifier("test", object_type, key, "1.0.0")


def _population(
    *,
    sex: Sex = Sex.MALE,
    age_class: AgeClass = AgeClass.SENIOR,
    sport: Sport = Sport.ASSOCIATION_FOOTBALL,
    professional_status: ProfessionalStatus = ProfessionalStatus.PROFESSIONAL,
    squad_level: SquadLevel = SquadLevel.FIRST_TEAM,
    competition_tier: CompetitionTier = CompetitionTier.TOP_DOMESTIC_DIVISION,
    evidence_bindings: tuple[PopulationEvidenceBinding, ...] | None = None,
    resolution_status: PopulationResolutionStatus = PopulationResolutionStatus.RESOLVED,
) -> PopulationIdentity:
    values = (
        (PopulationDimension.SEX, sex),
        (PopulationDimension.AGE_CLASS, age_class),
        (PopulationDimension.SPORT, sport),
        (PopulationDimension.PROFESSIONAL_STATUS, professional_status),
        (PopulationDimension.SQUAD_LEVEL, squad_level),
        (PopulationDimension.COMPETITION_TIER, competition_tier),
    )
    bindings = (
        tuple(
            PopulationEvidenceBinding(
                dimension=dimension,
                value=value,
                evidence_reference=_reference("evidence", dimension.value.lower(), dimension.value),
            )
            for dimension, value in values
        )
        if evidence_bindings is None
        else evidence_bindings
    )
    return PopulationIdentity(
        sex=sex,
        age_class=age_class,
        sport=sport,
        professional_status=professional_status,
        squad_level=squad_level,
        competition_tier=competition_tier,
        competition_identity=CompetitionIdentity(
            _identifier("competition", "top-flight-1"), "Example top domestic division"
        ),
        season=SeasonIdentity(_identifier("season", "2025-26"), "2025/26"),
        evidence_bindings=bindings,
        resolution_status=resolution_status,
    )


def _exact_scope() -> CohortScope:
    return CohortScope(
        scope_type=CohortScopeType.WHOLE_COHORT,
        separability=SubgroupSeparability.EXACT_TARGET_COHORT,
        scope_id=_identifier("cohort", "exact-target"),
    )


def _source(
    population: PopulationIdentity,
    *,
    data_origin: SourceDataOrigin = SourceDataOrigin.ACTUAL_OBSERVED_MEASURED,
    data_granularity: DataGranularity = DataGranularity.ATHLETE_LEVEL,
    cohort_scope: CohortScope | None = None,
    reuse_status: ReuseStatus = ReuseStatus.UNKNOWN,
) -> CanonicalSource:
    return CanonicalSource(
        source_id=_reference("source", "example-source", "Example source"),
        source_revision="revision-1",
        population=population,
        cohort_scope=cohort_scope or _exact_scope(),
        data_origin=data_origin,
        data_granularity=data_granularity,
        publication_reference=_reference("study", "example-study", "Example study"),
        license_reuse=LicenseReuseMetadata(
            reuse_status=reuse_status,
            license_reference=_reference("license", "example", "Example license"),
            conditions=("use only under the source terms",)
            if reuse_status is ReuseStatus.RESTRICTED
            else (),
        ),
    )


def test_exact_target_population_and_source_pass() -> None:
    source = _source(_population(), reuse_status=ReuseStatus.RESTRICTED)

    population_decision = qualify_canonical_population(source.population)
    source_decision = qualify_canonical_source(source)

    assert population_decision.status is CanonicalPopulationStatus.PASS
    assert all(clause.status.value == "PASS" for clause in population_decision.clauses)
    assert source_decision.status is CanonicalSourceStatus.CANONICAL_EMPIRICAL_TARGET
    assert source_decision.evidence_class is EvidenceClass.CANONICAL_EMPIRICAL_TARGET
    assert source_decision.license_reuse.reuse_status is ReuseStatus.RESTRICTED
    assert source_decision.method_reference.identifier.object_type == "registered-operation"


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    (
        ("sex", Sex.FEMALE, RefusalReasonCode.SEX_OUTSIDE_CANONICAL_TARGET),
        ("age_class", AgeClass.U23, RefusalReasonCode.AGE_CLASS_OUTSIDE_CANONICAL_TARGET),
        ("sport", Sport.FUTSAL, RefusalReasonCode.SPORT_OUTSIDE_CANONICAL_TARGET),
        (
            "professional_status",
            ProfessionalStatus.SEMI_PROFESSIONAL,
            RefusalReasonCode.PROFESSIONAL_STATUS_MISMATCH,
        ),
        ("squad_level", SquadLevel.U23, RefusalReasonCode.SQUAD_LEVEL_MISMATCH),
        (
            "competition_tier",
            CompetitionTier.LOWER_DOMESTIC_DIVISION,
            RefusalReasonCode.COMPETITION_TIER_MISMATCH,
        ),
    ),
)
def test_each_noncanonical_dimension_fails_closed(
    field: str, value: object, reason: RefusalReasonCode
) -> None:
    kwargs: dict[str, object] = {field: value}
    population = _population(**kwargs)  # type: ignore[arg-type]
    decision = qualify_canonical_population(population)
    source_decision = qualify_canonical_source(_source(population))

    assert decision.status is CanonicalPopulationStatus.NONCANONICAL
    assert reason in decision.reason_codes
    assert source_decision.status is CanonicalSourceStatus.CANONICAL_ELIGIBILITY_FAILED
    assert source_decision.evidence_class is EvidenceClass.REJECTED_OR_UNRESOLVED


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("squad_level", SquadLevel.UNKNOWN),
        ("competition_tier", CompetitionTier.UNKNOWN),
    ),
)
def test_unknown_required_dimension_is_quarantined(field: str, value: object) -> None:
    population = _population(**{field: value})  # type: ignore[arg-type]
    decision = qualify_canonical_population(population)

    assert decision.status is CanonicalPopulationStatus.UNRESOLVED
    assert decision.unresolved_clauses
    assert decision.failed_clauses == ()
    assert RefusalReasonCode.REQUIRED_POPULATION_EVIDENCE_MISSING in decision.reason_codes
    assert qualify_canonical_source(_source(population)).status is CanonicalSourceStatus.UNRESOLVED


def test_vague_elite_without_typed_evidence_is_unresolved() -> None:
    population = _population(evidence_bindings=())
    decision = qualify_canonical_population(population)

    assert decision.status is CanonicalPopulationStatus.UNRESOLVED
    assert len(decision.unresolved_clauses) == 6
    assert RefusalReasonCode.REQUIRED_POPULATION_EVIDENCE_MISSING in decision.reason_codes


def test_mixed_unsplit_cohort_fails_source_gate() -> None:
    scope = CohortScope(
        scope_type=CohortScopeType.MIXED_PARENT_COHORT,
        separability=SubgroupSeparability.NOT_SEPARABLE,
        parent_cohort_id=_identifier("cohort", "mixed-parent"),
    )
    decision = qualify_canonical_source(_source(_population(), cohort_scope=scope))

    assert decision.population_decision.status is CanonicalPopulationStatus.PASS
    assert decision.status is CanonicalSourceStatus.CANONICAL_ELIGIBILITY_FAILED
    assert decision.failed_requirements
    assert RefusalReasonCode.TARGET_SUBGROUP_NOT_SEPARABLE in decision.reason_codes


def test_separated_target_subgroup_can_pass_with_extraction_provenance() -> None:
    extraction = _reference("extraction", "target-subgroup", "Target subgroup extraction")
    provenance = _reference("provenance", "target-subgroup", "Target subgroup provenance")
    scope = CohortScope(
        scope_type=CohortScopeType.MIXED_PARENT_COHORT,
        separability=SubgroupSeparability.SEPARABLE,
        parent_cohort_id=_identifier("cohort", "mixed-parent"),
        evaluated_subgroup_id=_identifier("subgroup", "target-subgroup"),
        extraction_evidence=(extraction,),
        provenance_references=(provenance,),
    )

    decision = qualify_canonical_source(_source(_population(), cohort_scope=scope))

    assert decision.status is CanonicalSourceStatus.CANONICAL_EMPIRICAL_TARGET
    assert decision.qualification_provenance.subgroup_provenance_references == (
        extraction,
        provenance,
    )


@pytest.mark.parametrize(
    "origin",
    (
        SourceDataOrigin.SYNTHETIC,
        SourceDataOrigin.SIMULATED,
        SourceDataOrigin.LITERATURE_ONLY,
    ),
)
def test_synthetic_simulated_or_literature_origin_cannot_be_canonical(
    origin: SourceDataOrigin,
) -> None:
    decision = qualify_canonical_source(_source(_population(), data_origin=origin))

    assert decision.status is CanonicalSourceStatus.CANONICAL_ELIGIBILITY_FAILED
    assert decision.evidence_class is EvidenceClass.REJECTED_OR_UNRESOLVED
    assert RefusalReasonCode.EMPIRICAL_ORIGIN_NOT_ACTUAL_OBSERVED in decision.reason_codes


def test_failed_canonical_source_does_not_become_indirect_evidence() -> None:
    source = _source(_population(sex=Sex.FEMALE))
    source_decision = qualify_canonical_source(source)
    applicability = EvidenceApplicabilityV2(
        applicability_id=_identifier("evidence-applicability", "indirect-method"),
        source_id=source.source_id.identifier,
        claim="validate a population-independent event detector",
        evidence_class=EvidenceClass.INDIRECT_MEASUREMENT_EVIDENCE,
        role=EvidenceApplicabilityRole.INDIRECT_MEASUREMENT_METHOD,
        decision=ApplicabilityDecision.SUPPORTED,
        rationale="The explicit method claim is independent of target-population norms.",
        evidence_references=(source.source_id,),
    )

    assert source_decision.evidence_class is EvidenceClass.REJECTED_OR_UNRESOLVED
    assert applicability.evidence_class is EvidenceClass.INDIRECT_MEASUREMENT_EVIDENCE
    assert applicability.population_decision is None


def test_v2_applicability_rejects_noncanonical_population_as_target_evidence() -> None:
    noncanonical_population = qualify_canonical_population(_population(sex=Sex.FEMALE))

    with pytest.raises(ValueError, match="target-population evidence requires"):
        EvidenceApplicabilityV2(
            applicability_id=_identifier("evidence-applicability", "canonical-forged"),
            source_id=_identifier("source", "example-source"),
            claim="claim requiring canonical target evidence",
            evidence_class=EvidenceClass.CANONICAL_EMPIRICAL_TARGET,
            role=EvidenceApplicabilityRole.TARGET_WORLD_EMPIRICAL,
            decision=ApplicabilityDecision.SUPPORTED,
            rationale="The embedded population decision is not canonical.",
            population_decision=noncanonical_population,
        )


def test_v2_applicability_rejects_target_world_rejected_class() -> None:
    with pytest.raises(ValueError, match="evidence class and applicability role"):
        EvidenceApplicabilityV2(
            applicability_id=_identifier("evidence-applicability", "rejected-target-world"),
            source_id=_identifier("source", "example-source"),
            claim="claim with rejected evidence",
            evidence_class=EvidenceClass.REJECTED_OR_UNRESOLVED,
            role=EvidenceApplicabilityRole.TARGET_WORLD_EMPIRICAL,
            decision=ApplicabilityDecision.UNSUPPORTED,
            rationale="Rejected evidence cannot be target-world empirical.",
        )


def test_conflicting_dimension_evidence_is_unresolved() -> None:
    conflict = PopulationEvidenceBinding(
        dimension=PopulationDimension.SQUAD_LEVEL,
        value=SquadLevel.ACADEMY_OR_YOUTH,
        evidence_reference=_reference("evidence", "academy", "Academy evidence"),
    )
    population = _population(
        evidence_bindings=(*_population().evidence_bindings, conflict),
    )
    decision = qualify_canonical_population(population)

    assert decision.status is CanonicalPopulationStatus.UNRESOLVED
    assert PopulationDimension.SQUAD_LEVEL in decision.unresolved_clauses
    assert RefusalReasonCode.POPULATION_METADATA_CONFLICTING in decision.reason_codes


def test_unresolved_binding_status_is_not_a_pass() -> None:
    bindings = list(_population().evidence_bindings)
    bindings[4] = PopulationEvidenceBinding(
        dimension=PopulationDimension.SQUAD_LEVEL,
        value=None,
        evidence_reference=_reference("evidence", "missing-squad", "Missing squad evidence"),
        status=PopulationEvidenceStatus.MISSING,
        missing_information=("first-team status",),
    )

    decision = qualify_canonical_population(
        _population(
            evidence_bindings=tuple(bindings), resolution_status=PopulationResolutionStatus.RESOLVED
        )
    )

    assert decision.status is CanonicalPopulationStatus.UNRESOLVED
    assert "first-team status" in decision.missing_information


def test_v3_roundtrip_and_hash_for_population_and_source_decisions() -> None:
    source_decision = qualify_canonical_source(_source(_population()))
    population_decision = source_decision.population_decision

    for value, value_type in (
        (population_decision, type(population_decision)),
        (source_decision, type(source_decision)),
    ):
        serialized = canonical_json(value)
        restored = from_canonical_json(serialized, value_type)
        assert restored == value
        assert canonical_json(restored) == serialized
        assert canonical_hash(restored) == canonical_hash(value)


def test_decision_wire_shapes_reject_missing_and_unexpected_fields() -> None:
    decision = qualify_canonical_source(_source(_population()))
    envelope = json.loads(canonical_json(decision))

    missing = json.loads(json.dumps(envelope))
    del missing["payload"]["requirements"]
    with pytest.raises(ValueError, match="missing fields"):
        from_canonical_json(json.dumps(missing), type(decision))

    unexpected = json.loads(json.dumps(envelope))
    unexpected["payload"]["unexpected"] = True
    with pytest.raises(ValueError, match="unexpected fields"):
        from_canonical_json(json.dumps(unexpected), type(decision))


def test_population_contracts_are_immutable_and_reject_mutable_tuples() -> None:
    population = _population()
    with pytest.raises(ValueError, match="immutable tuple"):
        replace(population, evidence_bindings=list(population.evidence_bindings))  # type: ignore[arg-type]


def test_population_decision_rejects_embedded_female_population_tamper() -> None:
    decision = qualify_canonical_population(_population())
    female_population = replace(decision.population, sex=Sex.FEMALE)

    with pytest.raises(ValueError, match="population authority does not match"):
        replace(decision, population=female_population)


def test_population_decision_rejects_embedded_lower_tier_population_tamper() -> None:
    decision = qualify_canonical_population(_population())
    lower_tier_population = replace(
        decision.population,
        competition_tier=CompetitionTier.LOWER_DOMESTIC_DIVISION,
    )

    with pytest.raises(ValueError, match="population authority does not match"):
        replace(decision, population=lower_tier_population)


def test_population_decision_rejects_semantically_tampered_clause() -> None:
    decision = qualify_canonical_population(_population())
    tampered_clause = replace(decision.clauses[0], observed_value=Sex.FEMALE.value)

    with pytest.raises(ValueError, match="population clause authority does not match"):
        replace(decision, clauses=(tampered_clause, *decision.clauses[1:]))


def test_population_decision_rejects_tampered_clause_status_with_consistent_summary() -> None:
    decision = qualify_canonical_population(_population())
    tampered_clause = replace(decision.clauses[0], status=ClauseStatus.FAIL)

    with pytest.raises(ValueError, match="population clause authority does not match"):
        replace(
            decision,
            clauses=(tampered_clause, *decision.clauses[1:]),
            status=CanonicalPopulationStatus.NONCANONICAL,
            failed_clauses=(PopulationDimension.SEX,),
        )


def test_population_decision_rejects_arbitrary_method_reference() -> None:
    decision = qualify_canonical_population(_population())

    with pytest.raises(ValueError, match="population method reference"):
        replace(
            decision,
            method_reference=_reference(
                "registered-operation", "forged-population-method", "Forged method"
            ),
        )


def test_population_decision_rejects_arbitrary_decision_id() -> None:
    decision = qualify_canonical_population(_population())

    with pytest.raises(ValueError, match="population decision_id"):
        replace(decision, decision_id=_identifier("canonical-population-decision", "forged"))


def test_source_decision_rejects_synthetic_source_tamper() -> None:
    decision = qualify_canonical_source(_source(_population()))
    synthetic_source = replace(
        decision.source,
        data_origin=SourceDataOrigin.SYNTHETIC,
    )

    with pytest.raises(ValueError, match="source authority does not match"):
        replace(decision, source=synthetic_source)


def test_source_decision_rejects_semantically_tampered_requirement() -> None:
    decision = qualify_canonical_source(_source(_population()))
    tampered_requirement = replace(
        decision.requirements[1],
        status=ClauseStatus.FAIL,
    )
    requirements = (decision.requirements[0], tampered_requirement, *decision.requirements[2:])

    with pytest.raises(ValueError, match="source requirement authority does not match"):
        replace(
            decision,
            requirements=requirements,
            status=CanonicalSourceStatus.CANONICAL_ELIGIBILITY_FAILED,
            evidence_class=EvidenceClass.REJECTED_OR_UNRESOLVED,
            failed_requirements=(SourceRequirement.ACTUAL_OBSERVED_DATA,),
        )


def test_source_decision_rejects_arbitrary_method_reference() -> None:
    decision = qualify_canonical_source(_source(_population()))

    with pytest.raises(ValueError, match="source method reference"):
        replace(
            decision,
            method_reference=_reference(
                "registered-operation", "forged-source-method", "Forged method"
            ),
        )


def test_source_decision_rejects_arbitrary_decision_id() -> None:
    decision = qualify_canonical_source(_source(_population()))

    with pytest.raises(ValueError, match="source decision_id"):
        replace(decision, decision_id=_identifier("canonical-source-decision", "forged"))


def _tamper_source_requirement(payload: dict[str, Any]) -> None:
    payload["requirements"][1]["status"] = ClauseStatus.FAIL.value
    payload["failed_requirements"] = [SourceRequirement.ACTUAL_OBSERVED_DATA.value]
    payload["status"] = CanonicalSourceStatus.CANONICAL_ELIGIBILITY_FAILED.value
    payload["evidence_class"] = EvidenceClass.REJECTED_OR_UNRESOLVED.value


def _tamper_population_clause_status(payload: dict[str, Any]) -> None:
    payload["clauses"][0]["status"] = ClauseStatus.FAIL.value
    payload["failed_clauses"] = [PopulationDimension.SEX.value]
    payload["status"] = CanonicalPopulationStatus.NONCANONICAL.value


def test_v3_population_wire_tampering_rejects_female_clause_method_and_id() -> None:
    decision = qualify_canonical_population(_population())

    mutations: tuple[tuple[str, Callable[[dict[str, Any]], object]], ...] = (
        (
            "female population",
            lambda payload: payload["population"].__setitem__("sex", Sex.FEMALE.value),
        ),
        (
            "tampered clause",
            lambda payload: payload["clauses"][0].__setitem__("observed_value", Sex.FEMALE.value),
        ),
        (
            "tampered clause status",
            _tamper_population_clause_status,
        ),
        (
            "tampered method reference",
            lambda payload: payload["method_reference"].__setitem__(
                "display_label", "Forged method"
            ),
        ),
        (
            "tampered decision id",
            lambda payload: payload["decision_id"].__setitem__("key", "forged"),
        ),
    )

    for _label, mutate in mutations:
        envelope = json.loads(canonical_json(decision))
        mutate(cast(dict[str, Any], envelope["payload"]))
        with pytest.raises(ValueError, match="invalid dynamislm.population.models"):
            from_canonical_json(json.dumps(envelope), type(decision))


def test_v3_source_wire_tampering_rejects_synthetic_requirement_method_and_id() -> None:
    decision = qualify_canonical_source(_source(_population()))

    mutations: tuple[tuple[str, Callable[[dict[str, Any]], object]], ...] = (
        (
            "synthetic source",
            lambda payload: payload["source"].__setitem__(
                "data_origin", SourceDataOrigin.SYNTHETIC.value
            ),
        ),
        (
            "tampered requirement",
            _tamper_source_requirement,
        ),
        (
            "tampered method reference",
            lambda payload: payload["method_reference"].__setitem__(
                "display_label", "Forged method"
            ),
        ),
        (
            "tampered decision id",
            lambda payload: payload["decision_id"].__setitem__("key", "forged"),
        ),
    )

    for _label, mutate in mutations:
        envelope = json.loads(canonical_json(decision))
        mutate(cast(dict[str, Any], envelope["payload"]))
        with pytest.raises(ValueError, match="invalid dynamislm.population.models"):
            from_canonical_json(json.dumps(envelope), type(decision))


def test_v3_source_wire_population_tamper_rejects_female_and_lower_tier() -> None:
    decision = qualify_canonical_source(_source(_population()))

    for field, value in (
        ("sex", Sex.FEMALE.value),
        ("competition_tier", CompetitionTier.LOWER_DOMESTIC_DIVISION.value),
    ):
        envelope = json.loads(canonical_json(decision))
        envelope["payload"]["source"]["population"][field] = value
        envelope["payload"]["population_decision"]["population"][field] = value
        with pytest.raises(ValueError, match="invalid dynamislm.population.models"):
            from_canonical_json(json.dumps(envelope), type(decision))
