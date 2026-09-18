from __future__ import annotations

from dataclasses import replace

import pytest

from dynamislm import (
    AnalysisClass,
    AnalysisEstimandLevel,
    AnalysisLevelIdentity,
    AnalysisUnitOfAnalysis,
    ApplicabilityAssessment,
    ApplicabilityAxis,
    ApplicabilityDecision,
    ClaimEvidenceApplicability,
    ClaimIntent,
    ClaimTarget,
    InstanceIdentifier,
    MeasurementClaimLevel,
    RegistryReference,
    RelationshipClaimLevel,
    ScientificIdentifier,
    authorize_claim,
)
from dynamislm.analysis.registry import RES70_CAPABILITY_REGISTRY
from dynamislm.analysis.validation import validate_level_of_analysis
from dynamislm.comparability import (
    BridgeRegistry,
    RES70ComparabilityAuthorityError,
    assess_cross_source_comparability,
    validate_pairwise_decisions,
)
from dynamislm.comparability.res70_models import (
    CrossSourceComparabilityDecision,
    CrossSourceComparabilityRequest,
    ObservationAuthorityReference,
)
from dynamislm.evidence.res70 import validate_claim_evidence_applicability
from dynamislm.refusal import RefusalResult
from test_kernel import _derived_observation
from test_longitudinal_statistics import _entries, _support


def _reference(object_type: str, key: str, label: str = "fixture") -> RegistryReference:
    return RegistryReference(ScientificIdentifier("dynamislm", object_type, key, "1.0.0"), label)


def _complete_pair() -> tuple[object, object, CrossSourceComparabilityRequest]:
    left = _derived_observation("res70-adversarial-left")
    right = _derived_observation("res70-adversarial-third")
    unit = _reference("unit", "meter", "m")
    del unit
    request = CrossSourceComparabilityRequest(
        request_id=InstanceIdentifier("cross-source-comparability-request", "adversarial"),
        left_observation=ObservationAuthorityReference.from_observation(left),
        right_observation=ObservationAuthorityReference.from_observation(right),
        claim_intent=_reference("claim-intent", "adversarial"),
    )
    return left, right, request


def test_caller_supplied_empty_registry_cannot_authorize_any_pair() -> None:
    left, right, request = _complete_pair()

    with pytest.raises(RES70ComparabilityAuthorityError, match="caller-supplied"):
        assess_cross_source_comparability(
            request,
            (left, right),  # type: ignore[arg-type]
            bridge_registry=BridgeRegistry(),
        )


def test_pairwise_collection_never_promotes_a_missing_third_pair() -> None:
    left, middle, _ = _complete_pair()
    right = _derived_observation("res70-adversarial-right")
    claim = _reference("claim-intent", "pairwise")

    def decision(a: object, b: object, key: str) -> CrossSourceComparabilityDecision:
        request = CrossSourceComparabilityRequest(
            request_id=InstanceIdentifier("cross-source-comparability-request", key),
            left_observation=ObservationAuthorityReference.from_observation(a),  # type: ignore[arg-type]
            right_observation=ObservationAuthorityReference.from_observation(b),  # type: ignore[arg-type]
            claim_intent=claim,
        )
        return assess_cross_source_comparability(request, (a, b))  # type: ignore[arg-type]

    first = decision(left, middle, "ab")
    second = decision(middle, right, "bc")
    validate_pairwise_decisions((first, second))
    assert frozenset((left.observation_id.qualified, right.observation_id.qualified)) not in {  # type: ignore[attr-defined]
        item.pair_key for item in (first, second)
    }


def test_between_rows_from_one_athlete_are_pseudoreplication_risk() -> None:
    entries = _entries((10.0, 11.0), prefix="res70-pseudorep")
    support = _support(entries)
    request = __import__(
        "dynamislm.analysis.models",
        fromlist=["AnalysisAuthorizationRequest"],
    ).AnalysisAuthorizationRequest(
        request_id=InstanceIdentifier("analysis-authorization-request", "pseudo"),
        analysis_class=AnalysisClass.BETWEEN_ATHLETE_ASSOCIATION,
        support=support,
        support_reference=None,
        observations=tuple(entry.observation for entry in entries),
        identity_hashes=(),
        comparability_decisions=(),
        requested_level=AnalysisLevelIdentity(
            unit_of_analysis=AnalysisUnitOfAnalysis.ATHLETE,
            estimand_level=AnalysisEstimandLevel.BETWEEN_ATHLETE,
            subject_key="athlete_id",
            clustering_keys=(),
            grouping_keys=(),
        ),
        evidence_applicability=None,
        context_references=(),
    )
    capability = RES70_CAPABILITY_REGISTRY.resolve(AnalysisClass.BETWEEN_ATHLETE_ASSOCIATION)
    assert capability is not None

    with pytest.raises(ValueError, match="pseudoreplication"):
        validate_level_of_analysis(request, capability, support)


def test_evidence_axis_limitation_is_not_collapsed_to_method_failure() -> None:
    bundle = ClaimEvidenceApplicability(
        claim_intent_reference=_reference("claim-intent", "axis-limitation"),
        assessments=tuple(
            ApplicabilityAssessment(
                axis=axis,
                decision=(
                    ApplicabilityDecision.UNSUPPORTED
                    if axis is ApplicabilityAxis.POPULATION_RELEVANCE
                    else ApplicabilityDecision.SUPPORTED
                ),
                required_for_claim=True,
                evidence_references=(_reference("evidence", axis.value.lower()),),
                authority_references=(),
                conditions=(),
                rationale=axis.value,
            )
            for axis in ApplicabilityAxis
        ),
        registry_version="res70-1.0.0",
    )

    validate_claim_evidence_applicability(bundle)
    assert (
        bundle.assessment(ApplicabilityAxis.METHOD_VALIDITY).decision
        is ApplicabilityDecision.SUPPORTED
    )
    assert (
        bundle.assessment(ApplicabilityAxis.POPULATION_RELEVANCE).decision
        is ApplicabilityDecision.UNSUPPORTED
    )


def test_tampered_applicability_hash_is_rejected() -> None:
    bundle = ClaimEvidenceApplicability(
        claim_intent_reference=_reference("claim-intent", "tamper"),
        assessments=(
            ApplicabilityAssessment(
                axis=ApplicabilityAxis.METHOD_VALIDITY,
                decision=ApplicabilityDecision.SUPPORTED,
                required_for_claim=True,
                evidence_references=(_reference("evidence", "method"),),
                authority_references=(),
                conditions=(),
                rationale="method",
            ),
        ),
        registry_version="res70-1.0.0",
    )
    with pytest.raises(ValueError, match="hash"):
        replace(bundle, applicability_hash="sha256:" + "0" * 64)


def test_unsupported_practical_and_causal_escalations_are_refused() -> None:
    observation = _derived_observation("res70-escalation")
    practical = ClaimIntent(
        claim_reference=_reference("claim-intent", "practical"),
        measurement_level=MeasurementClaimLevel.PRACTICAL_OR_DECISION_MEANINGFULNESS,
        relationship_level=None,
        predictive_intent=None,
        target=ClaimTarget.INDIVIDUAL,
        analysis_reference=None,
        evidence_applicability_reference=None,
        decision_criterion_reference=None,
        observations=(observation,),
    )
    causal = ClaimIntent(
        claim_reference=_reference("claim-intent", "causal"),
        measurement_level=None,
        relationship_level=RelationshipClaimLevel.CAUSAL_EVIDENCE,
        predictive_intent=None,
        target=ClaimTarget.INDIVIDUAL,
        analysis_reference=None,
        evidence_applicability_reference=None,
        decision_criterion_reference=None,
        observations=(observation,),
    )

    practical_result = authorize_claim(practical)
    causal_result = authorize_claim(causal)

    assert isinstance(practical_result.refusal_result, RefusalResult)
    assert isinstance(causal_result.refusal_result, RefusalResult)
    assert "RES70_UNSUPPORTED_CLAIM_ESCALATION" in practical_result.reason_codes
    assert "RES70_UNSUPPORTED_CAUSAL_CLAIM" in causal_result.reason_codes
