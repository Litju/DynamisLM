from __future__ import annotations

from dynamislm import (
    ApplicabilityAssessment,
    ApplicabilityAxis,
    ApplicabilityDecision,
    ClaimEvidenceApplicability,
    RegistryReference,
    ScientificIdentifier,
    canonical_json,
    from_canonical_json,
)


def _reference(object_type: str, key: str) -> RegistryReference:
    return RegistryReference(
        ScientificIdentifier("dynamislm", object_type, key, "1.0.0"),
        key,
    )


def _assessment(
    axis: ApplicabilityAxis,
    decision: ApplicabilityDecision,
) -> ApplicabilityAssessment:
    return ApplicabilityAssessment(
        axis=axis,
        decision=decision,
        required_for_claim=True,
        evidence_references=(_reference("evidence", axis.value.lower()),),
        authority_references=(),
        conditions=(),
        rationale=f"assessment for {axis.value}",
    )


def test_evidence_axes_remain_independently_inspectable_and_roundtrip() -> None:
    applicability = ClaimEvidenceApplicability(
        claim_intent_reference=_reference("claim-intent", "practical"),
        assessments=tuple(
            _assessment(axis, ApplicabilityDecision.SUPPORTED) for axis in ApplicabilityAxis
        ),
        registry_version="res70-1.0.0",
    )

    assert (
        applicability.assessment(ApplicabilityAxis.METHOD_VALIDITY).decision
        is ApplicabilityDecision.SUPPORTED
    )
    assert (
        applicability.assessment(ApplicabilityAxis.POPULATION_RELEVANCE).decision
        is ApplicabilityDecision.SUPPORTED
    )
    assert not hasattr(applicability, "confidence_score")
    assert (
        from_canonical_json(canonical_json(applicability), ClaimEvidenceApplicability)
        == applicability
    )


def test_population_limitation_does_not_rewrite_method_validity() -> None:
    assessments = tuple(
        _assessment(
            axis,
            ApplicabilityDecision.UNSUPPORTED
            if axis is ApplicabilityAxis.POPULATION_RELEVANCE
            else ApplicabilityDecision.SUPPORTED,
        )
        for axis in ApplicabilityAxis
    )
    applicability = ClaimEvidenceApplicability(
        claim_intent_reference=_reference("claim-intent", "population-limited"),
        assessments=assessments,
        registry_version="res70-1.0.0",
    )

    assert (
        applicability.assessment(ApplicabilityAxis.METHOD_VALIDITY).decision
        is ApplicabilityDecision.SUPPORTED
    )
    assert (
        applicability.assessment(ApplicabilityAxis.POPULATION_RELEVANCE).decision
        is ApplicabilityDecision.UNSUPPORTED
    )
    assert not applicability.supports_required_axes()


def test_unassessed_required_axis_is_rejected_at_contract_boundary() -> None:
    try:
        _assessment(ApplicabilityAxis.CONTEXTUAL_RELEVANCE, ApplicabilityDecision.UNASSESSED)
    except ValueError as exc:
        assert "unassessed" in str(exc)
    else:
        raise AssertionError("required unassessed applicability axis must be rejected")
