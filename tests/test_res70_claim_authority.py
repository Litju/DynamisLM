from __future__ import annotations

from dynamislm import (
    ClaimAuthorityStatus,
    ClaimIntent,
    ClaimTarget,
    MeasurementClaimLevel,
    RegistryReference,
    RelationshipClaimLevel,
    ScientificIdentifier,
    authorize_claim,
)
from dynamislm.claims.models import PredictionStatus
from dynamislm.refusal import RefusalResult
from test_kernel import _derived_observation


def _reference(object_type: str, key: str, label: str) -> RegistryReference:
    return RegistryReference(ScientificIdentifier("dynamislm", object_type, key, "1.0.0"), label)


def _intent(
    *,
    measurement_level: MeasurementClaimLevel | None = None,
    relationship_level: RelationshipClaimLevel | None = None,
    target: ClaimTarget = ClaimTarget.INDIVIDUAL,
) -> ClaimIntent:
    return ClaimIntent(
        claim_reference=_reference("claim-intent", "res70-test", "RES-70 test claim"),
        measurement_level=measurement_level,
        relationship_level=relationship_level,
        predictive_intent=None,
        target=target,
        analysis_reference=None,
        evidence_applicability_reference=None,
        decision_criterion_reference=None,
        observations=(_derived_observation("res70-claim-observation"),),
    )


def test_observed_value_is_authorized_without_promoting_other_levels() -> None:
    result = authorize_claim(_intent(measurement_level=MeasurementClaimLevel.OBSERVED_VALUE))

    assert result.status is ClaimAuthorityStatus.AUTHORIZED
    assert result.allowed_measurement_levels == (MeasurementClaimLevel.OBSERVED_VALUE,)
    assert result.allowed_relationship_levels == ()
    assert result.prediction_status is PredictionStatus.NOT_REQUESTED
    assert result.blocked_claims == ()


def test_numerical_change_is_not_implicitly_comparable_change() -> None:
    numerical = authorize_claim(_intent(measurement_level=MeasurementClaimLevel.NUMERICAL_CHANGE))
    comparable = authorize_claim(_intent(measurement_level=MeasurementClaimLevel.COMPARABLE_CHANGE))

    assert isinstance(numerical.refusal_result, RefusalResult)
    assert isinstance(comparable.refusal_result, RefusalResult)
    assert "RES70_COMPARABILITY_AUTHORITY_MISSING" in comparable.reason_codes
    assert MeasurementClaimLevel.COMPARABLE_CHANGE not in numerical.allowed_measurement_levels


def test_error_relative_change_and_practical_meaning_are_separate_gates() -> None:
    error_relative = authorize_claim(
        _intent(measurement_level=MeasurementClaimLevel.CHANGE_RELATIVE_TO_MEASUREMENT_ERROR)
    )
    practical = authorize_claim(
        _intent(measurement_level=MeasurementClaimLevel.PRACTICAL_OR_DECISION_MEANINGFULNESS)
    )

    assert "RES70_STATISTICAL_AUTHORITY_INSUFFICIENT" in error_relative.reason_codes
    assert "RES70_UNSUPPORTED_CLAIM_ESCALATION" in practical.reason_codes
    assert practical.status is ClaimAuthorityStatus.PARTIALLY_AUTHORIZED
    assert MeasurementClaimLevel.OBSERVED_VALUE in practical.allowed_measurement_levels


def test_association_is_not_causal_and_causal_claim_is_refused() -> None:
    association = authorize_claim(_intent(relationship_level=RelationshipClaimLevel.ASSOCIATION))
    causal = authorize_claim(_intent(relationship_level=RelationshipClaimLevel.CAUSAL_EVIDENCE))

    assert "COMPUTATION_NOT_REGISTERED" in association.reason_codes
    assert "RES70_UNSUPPORTED_CAUSAL_CLAIM" in causal.reason_codes
    assert RelationshipClaimLevel.CAUSAL_EVIDENCE not in causal.allowed_relationship_levels


def test_prediction_remains_orthogonal_and_unregistered() -> None:
    intent = ClaimIntent(
        claim_reference=_reference("claim-intent", "prediction", "Prediction"),
        measurement_level=MeasurementClaimLevel.OBSERVED_VALUE,
        relationship_level=None,
        predictive_intent=_reference("prediction-intent", "future", "Future prediction"),
        target=ClaimTarget.INDIVIDUAL,
        analysis_reference=None,
        evidence_applicability_reference=None,
        decision_criterion_reference=None,
        observations=(_derived_observation("res70-prediction"),),
    )

    result = authorize_claim(intent)

    assert result.prediction_status is PredictionStatus.REFUSED
    assert "COMPUTATION_NOT_REGISTERED" in result.reason_codes
