"""Hash and boundary validation for RES-70 claim decisions."""

from __future__ import annotations

from dynamislm.claims.authority import authorize_claim
from dynamislm.claims.models import ClaimAuthorityResult, ClaimIntent
from dynamislm.claims.registry import (
    CANONICAL_CLAIM_POLICY_REGISTRY,
    ClaimPolicyRegistry,
    is_canonical_claim_registry,
)
from dynamislm.evidence.res70 import validate_claim_evidence_authority
from dynamislm.serialization import canonical_hash


def validate_claim_authority(
    result: ClaimAuthorityResult,
    intent: ClaimIntent,
    *,
    registry: ClaimPolicyRegistry = CANONICAL_CLAIM_POLICY_REGISTRY,
) -> None:
    if not isinstance(result, ClaimAuthorityResult):
        raise ValueError("result must be a ClaimAuthorityResult")
    if not isinstance(intent, ClaimIntent):
        raise ValueError("intent must be a ClaimIntent")
    if not is_canonical_claim_registry(registry):
        raise ValueError("caller-supplied claim registries cannot authorize claims")
    if result.claim_intent_reference != intent.claim_reference:
        raise ValueError("claim result reference does not match claim intent")
    if result.claim_intent_hash != intent.intent_hash:
        raise ValueError("claim result intent hash does not match claim intent")
    if intent.evidence_applicability is not None:
        validate_claim_evidence_authority(intent.evidence_applicability)
        if result.evidence_applicability_hash != (
            intent.evidence_applicability.canonical_applicability_hash
        ):
            raise ValueError("claim result evidence hash does not match applicability bundle")
    expected_hash = canonical_hash(
        {
            "status": result.status,
            "claim_intent_reference": result.claim_intent_reference,
            "claim_intent_hash": result.claim_intent_hash,
            "allowed_measurement_levels": result.allowed_measurement_levels,
            "allowed_relationship_levels": result.allowed_relationship_levels,
            "prediction_status": result.prediction_status,
            "blocked_claims": result.blocked_claims,
            "first_blocking_prerequisite": result.first_blocking_prerequisite,
            "reason_codes": result.reason_codes,
            "missing_information": result.missing_information,
            "safe_descriptions": result.safe_descriptions,
            "support_hashes": result.support_hashes,
            "analysis_hashes": result.analysis_hashes,
            "comparability_hashes": result.comparability_hashes,
            "bridge_hashes": result.bridge_hashes,
            "evidence_applicability_hash": result.evidence_applicability_hash,
            "registry_version": result.registry_version,
            "software_version": result.software_version,
            "refusal_result": result.refusal_result,
        }
    )
    if result.canonical_decision_hash != expected_hash:
        raise ValueError("claim decision hash does not match immutable content")
    expected = authorize_claim(intent, registry=registry)
    if expected != result:
        raise ValueError("claim decision does not recompute from canonical authority")


__all__ = ["validate_claim_authority"]
