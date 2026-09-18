"""Deterministic two-axis RES-70 claim-authority adjudication."""

from __future__ import annotations

from typing import cast

from dynamislm.analysis.models import AnalysisAuthorizationStatus
from dynamislm.claims.models import (
    ClaimAuthorityResult,
    ClaimAuthorityStatus,
    ClaimIntent,
    ClaimTarget,
    MeasurementClaimLevel,
    PredictionStatus,
    RelationshipClaimLevel,
)
from dynamislm.claims.registry import (
    CANONICAL_CLAIM_POLICY_REGISTRY,
    ClaimAxis,
    ClaimPolicy,
    ClaimPolicyRegistry,
    is_canonical_claim_registry,
)
from dynamislm.comparability.res70_validation import build_res70_refusal
from dynamislm.evidence.models import ApplicabilityDecision
from dynamislm.evidence.res70 import validate_claim_evidence_applicability
from dynamislm.measurement.identity import InstanceIdentifier
from dynamislm.measurement.result import ResultStatus
from dynamislm.refusal.models import RefusalClass, RefusalResult
from dynamislm.serialization import canonical_hash

_MEASUREMENT_LEVELS = (
    MeasurementClaimLevel.OBSERVED_VALUE,
    MeasurementClaimLevel.NUMERICAL_CHANGE,
    MeasurementClaimLevel.COMPARABLE_CHANGE,
    MeasurementClaimLevel.CHANGE_RELATIVE_TO_MEASUREMENT_ERROR,
    MeasurementClaimLevel.PRACTICAL_OR_DECISION_MEANINGFULNESS,
)
_RELATIONSHIP_LEVELS = (
    RelationshipClaimLevel.OBSERVATION,
    RelationshipClaimLevel.DESCRIPTIVE_CHANGE,
    RelationshipClaimLevel.ASSOCIATION,
    RelationshipClaimLevel.TEMPORAL_ASSOCIATION,
    RelationshipClaimLevel.MECHANISTIC_HYPOTHESIS,
    RelationshipClaimLevel.CAUSAL_EVIDENCE,
)


def _observation_ids(intent: ClaimIntent) -> tuple[InstanceIdentifier, ...]:
    if intent.observations:
        return tuple(item.observation_id for item in intent.observations)
    if intent.statistical_result is not None and intent.statistical_result.support is not None:
        return intent.statistical_result.support.source_observation_ids
    return ()


def _support_hashes(intent: ClaimIntent) -> tuple[str, ...]:
    if intent.statistical_result is not None and intent.statistical_result.support is not None:
        return (intent.statistical_result.support.canonical_support_hash,)
    if intent.analysis_authorization is not None:
        return intent.analysis_authorization.support_hashes
    return ()


def _analysis_hashes(intent: ClaimIntent) -> tuple[str, ...]:
    if intent.analysis_authorization is None:
        return ()
    return (intent.analysis_authorization.canonical_authorization_hash,)


def _comparability_hashes(intent: ClaimIntent) -> tuple[str, ...]:
    return tuple(item.canonical_decision_hash for item in intent.comparability_decisions)


def _bridge_hashes(intent: ClaimIntent) -> tuple[str, ...]:
    return tuple(
        canonical_hash(item.bridge_application_reference)
        for item in intent.comparability_decisions
        if item.bridge_application_reference is not None
    )


def _safe_observation(intent: ClaimIntent) -> bool:
    if intent.observations:
        return all(item.result.status is ResultStatus.VALID for item in intent.observations)
    return intent.statistical_result is not None and intent.statistical_result.support is not None


def _analysis_matches(
    intent: ClaimIntent,
    level: object,
) -> tuple[bool, str | None, tuple[str, ...]]:
    auth = intent.analysis_authorization
    if auth is None or auth.status is not AnalysisAuthorizationStatus.AUTHORIZED:
        if level is MeasurementClaimLevel.CHANGE_RELATIVE_TO_MEASUREMENT_ERROR:
            return (
                False,
                "a registered source-bound measurement-error authority",
                ("RES70_STATISTICAL_AUTHORITY_INSUFFICIENT",),
            )
        return (
            False,
            "a registered authorized deterministic analysis",
            ("COMPUTATION_NOT_REGISTERED",),
        )
    if (
        intent.analysis_reference is not None
        and auth.capability_reference != intent.analysis_reference
    ):
        return (
            False,
            "analysis reference bound to the claim intent",
            ("RES70_REGISTRY_INTEGRITY_FAILURE",),
        )
    if isinstance(level, MeasurementClaimLevel):
        allowed = {
            MeasurementClaimLevel.NUMERICAL_CHANGE: {
                "SCALAR_ABSOLUTE_CHANGE",
                "SCALAR_RELATIVE_CHANGE",
                "SCALAR_LOG_CHANGE",
                "BASELINE_REFERENCE_WINDOW_DEVIATION",
            },
            MeasurementClaimLevel.COMPARABLE_CHANGE: {
                "SCALAR_ABSOLUTE_CHANGE",
                "SCALAR_RELATIVE_CHANGE",
                "SCALAR_LOG_CHANGE",
                "BASELINE_REFERENCE_WINDOW_DEVIATION",
            },
            MeasurementClaimLevel.CHANGE_RELATIVE_TO_MEASUREMENT_ERROR: {
                "RELIABILITY_RANDOM_ERROR_COMPARISON",
            },
            MeasurementClaimLevel.PRACTICAL_OR_DECISION_MEANINGFULNESS: {
                "RELIABILITY_RANDOM_ERROR_COMPARISON",
            },
        }
        if level is MeasurementClaimLevel.OBSERVED_VALUE:
            return True, None, ()
        if auth.analysis_class.value not in allowed.get(level, set()):
            return (
                False,
                ("analysis operation semantically supports the requested measurement level"),
                ("RES70_UNSUPPORTED_CLAIM_ESCALATION",),
            )
        if (
            level is MeasurementClaimLevel.CHANGE_RELATIVE_TO_MEASUREMENT_ERROR
            and not auth.statistical_authority_hashes
        ):
            return (
                False,
                "registered source-bound measurement-error authority",
                ("RES70_STATISTICAL_AUTHORITY_INSUFFICIENT",),
            )
    else:
        if level is RelationshipClaimLevel.OBSERVATION:
            return True, None, ()
        if level is RelationshipClaimLevel.DESCRIPTIVE_CHANGE:
            if auth.analysis_class.value not in {
                "SCALAR_ABSOLUTE_CHANGE",
                "SCALAR_RELATIVE_CHANGE",
                "SCALAR_LOG_CHANGE",
                "BASELINE_REFERENCE_WINDOW_DEVIATION",
            }:
                return (
                    False,
                    "registered descriptive change analysis",
                    ("RES70_UNSUPPORTED_CLAIM_ESCALATION",),
                )
        elif level is RelationshipClaimLevel.ASSOCIATION:
            if "ASSOCIATION" not in auth.analysis_class.value:
                return (
                    False,
                    "registered association analysis",
                    ("RES70_UNSUPPORTED_CLAIM_ESCALATION",),
                )
        elif level is RelationshipClaimLevel.TEMPORAL_ASSOCIATION:
            return (
                False,
                "registered temporal association estimator",
                ("COMPUTATION_NOT_REGISTERED",),
            )
        elif level is RelationshipClaimLevel.MECHANISTIC_HYPOTHESIS:
            if "ASSOCIATION" not in auth.analysis_class.value:
                return (
                    False,
                    "association result supporting a bounded mechanism hypothesis",
                    ("RES70_UNSUPPORTED_CLAIM_ESCALATION",),
                )
        elif level is RelationshipClaimLevel.CAUSAL_EVIDENCE:
            return (
                False,
                "registered causal estimand and identification strategy",
                ("RES70_UNSUPPORTED_CAUSAL_CLAIM",),
            )
    return True, None, ()


def _evidence_supports(
    intent: ClaimIntent,
    policy: ClaimPolicy,
) -> tuple[bool, str | None, tuple[str, ...]]:
    if not policy.required_evidence_axes:
        return True, None, ()
    bundle = intent.evidence_applicability
    if bundle is None:
        return (
            False,
            "claim-relative evidence-applicability vector",
            ("RES70_APPLICABILITY_AXIS_UNASSESSED",),
        )
    try:
        validate_claim_evidence_applicability(bundle)
    except ValueError:
        return (
            False,
            "untampered claim-relative evidence-applicability vector",
            ("RES70_REGISTRY_INTEGRITY_FAILURE",),
        )
    blocked: list[str] = []
    for axis in policy.required_evidence_axes:
        try:
            assessment = bundle.assessment(axis)
        except KeyError:
            blocked.append(axis.value)
            continue
        if assessment.decision in (
            ApplicabilityDecision.UNSUPPORTED,
            ApplicabilityDecision.UNASSESSED,
        ):
            blocked.append(axis.value)
        if (
            policy.requires_decision_criterion
            and assessment.decision is not ApplicabilityDecision.SUPPORTED
        ):
            blocked.append(axis.value)
    if blocked:
        return (
            False,
            "affirmative applicability for every required evidence axis",
            ("RES70_INSUFFICIENT_EVIDENCE_APPLICABILITY",),
        )
    return True, None, ()


def _comparability_supports(intent: ClaimIntent) -> tuple[bool, str | None, tuple[str, ...]]:
    if not intent.comparability_decisions:
        return (
            False,
            "affirmative direct pairwise comparability decisions",
            ("RES70_COMPARABILITY_AUTHORITY_MISSING",),
        )
    for decision in intent.comparability_decisions:
        if decision.state.value in {"REQUIRES_TRANSFORMATION", "BRIDGE_VALIDATION_REQUIRED"}:
            return (
                False,
                "executed registered bridge or affirmative comparability",
                ("RES70_BRIDGE_NOT_EXECUTED",),
            )
        if decision.state.value not in {"COMPARABLE", "COMPARABLE_WITH_CONDITIONS"}:
            return (
                False,
                "affirmative pairwise comparability",
                ("RES70_COMPARABILITY_AUTHORITY_MISSING",),
            )
    return True, None, ()


def _target_level_supports(intent: ClaimIntent) -> tuple[bool, str | None, tuple[str, ...]]:
    auth = intent.analysis_authorization
    if auth is None:
        return True, None, ()
    level = auth.resolved_level.estimand_level.value
    if intent.target is ClaimTarget.ATHLETE_WITHIN and level != "WITHIN_ATHLETE":
        return False, "within-athlete analysis level", ("RES70_WRONG_LEVEL_OF_ANALYSIS",)
    if intent.target is ClaimTarget.ATHLETE_BETWEEN and level != "BETWEEN_ATHLETE":
        return False, "between-athlete analysis level", ("RES70_WRONG_LEVEL_OF_ANALYSIS",)
    if intent.target in (ClaimTarget.GROUP, ClaimTarget.POPULATION) and level not in {
        "BETWEEN_ATHLETE",
        "GROUP",
        "JOINT_MULTILEVEL",
    }:
        return False, "group/population estimand level", ("RES70_WRONG_LEVEL_OF_ANALYSIS",)
    return True, None, ()


def _policy_result(
    intent: ClaimIntent,
    policy: ClaimPolicy,
) -> tuple[bool, str | None, tuple[str, ...], tuple[str, ...]]:
    if not _safe_observation(intent):
        return (
            False,
            "exact valid observations or a result-bound support",
            ("RES70_UNRESOLVED_IDENTITY",),
            ("exact typed observations",),
        )
    if policy.causal_operation_required:
        return (
            False,
            "registered causal operation",
            ("RES70_UNSUPPORTED_CAUSAL_CLAIM",),
            ("causal estimand and identification strategy",),
        )
    if policy.requires_decision_criterion and intent.decision_criterion_reference is None:
        return (
            False,
            "registered claim-specific decision/utility criterion",
            ("RES70_UNSUPPORTED_CLAIM_ESCALATION",),
            ("decision_criterion_reference",),
        )
    if policy.requires_measurement_error_authority:
        if (
            intent.analysis_authorization is None
            or not intent.analysis_authorization.statistical_authority_hashes
        ):
            return (
                False,
                "source-bound measurement-error authority",
                ("RES70_STATISTICAL_AUTHORITY_INSUFFICIENT",),
                ("source-bound measurement-error authority",),
            )
    if policy.requires_comparability:
        ok, missing, reasons = _comparability_supports(intent)
        if not ok:
            return False, missing, reasons, (missing or "pairwise comparability",)
    if policy.requires_analysis:
        ok, missing, reasons = _analysis_matches(intent, policy.level)
        if not ok:
            return False, missing, reasons, (missing or "registered analysis",)
    if policy.requires_statistical_result and intent.statistical_result is None:
        return (
            False,
            "exact deterministic statistical result",
            ("RES70_STATISTICAL_AUTHORITY_INSUFFICIENT",),
            ("StatisticalResult",),
        )
    ok, missing, reasons = _evidence_supports(intent, policy)
    if not ok:
        return False, missing, reasons, (missing or "evidence applicability",)
    ok, missing, reasons = _target_level_supports(intent)
    if not ok:
        return False, missing, reasons, (missing or "level-of-analysis identity",)
    return True, None, (), ()


def _evaluate_axis(
    intent: ClaimIntent,
    levels: tuple[MeasurementClaimLevel, ...] | tuple[RelationshipClaimLevel, ...],
    axis: ClaimAxis,
    registry: ClaimPolicyRegistry,
) -> tuple[
    tuple[object, ...],
    tuple[str, ...],
    tuple[str, ...],
    tuple[str, ...],
    str | None,
]:
    requested = (
        intent.measurement_level
        if axis is ClaimAxis.MEASUREMENT_CHANGE
        else intent.relationship_level
    )
    if requested is None:
        return (), (), (), (), None
    allowed: list[MeasurementClaimLevel | RelationshipClaimLevel] = []
    blocked: list[str] = []
    reasons: list[str] = []
    missing: list[str] = []
    first: str | None = None
    lower_failure: tuple[str | None, tuple[str, ...], tuple[str, ...]] | None = None
    for level in levels:
        policy = registry.resolve(axis, level)
        if policy is None:
            blocked.append(level.value)
            reasons.append("RES70_REGISTRY_INTEGRITY_FAILURE")
            first = first or "canonical claim policy"
            break
        ok, missing_item, reason_codes, missing_items = _policy_result(intent, policy)
        if ok:
            allowed.append(level)
            if level is requested:
                break
        else:
            if level is not requested:
                blocked.append(level.value)
                lower_failure = (missing_item, reason_codes, missing_items)
                continue
            blocked.append(level.value)
            if lower_failure is not None and not reason_codes:
                missing_item, reason_codes, missing_items = lower_failure
            reasons.extend(reason_codes)
            missing.extend(missing_items)
            first = first or missing_item
            break
    return (
        tuple(allowed),
        tuple(blocked),
        tuple(dict.fromkeys(reasons)),
        tuple(dict.fromkeys(missing)),
        first,
    )


def authorize_claim(
    intent: ClaimIntent,
    *,
    registry: ClaimPolicyRegistry = CANONICAL_CLAIM_POLICY_REGISTRY,
) -> ClaimAuthorityResult:
    """Authorize claims independently on measurement/change and relationship axes."""

    if not is_canonical_claim_registry(registry):
        registry_reasons = ("RES70_REGISTRY_INTEGRITY_FAILURE",)
        blocked = tuple(
            item.value
            for item in (intent.measurement_level, intent.relationship_level)
            if item is not None
        )
        registry_refusal = build_res70_refusal(
            "claim authority",
            registry_reasons[0],
            refusal_class=RefusalClass.COMPUTATION_NOT_REGISTERED,
            missing_information=("canonical claim policy registry",),
            observation_ids=_observation_ids(intent),
        )
        return ClaimAuthorityResult.create(
            status=ClaimAuthorityStatus.REFUSED,
            claim_intent_reference=intent.claim_reference,
            claim_intent_hash=intent.intent_hash,
            allowed_measurement_levels=(),
            allowed_relationship_levels=(),
            prediction_status=PredictionStatus.REFUSED
            if intent.predictive_intent is not None
            else PredictionStatus.NOT_REQUESTED,
            blocked_claims=blocked,
            first_blocking_prerequisite="canonical claim policy registry",
            reason_codes=registry_reasons,
            missing_information=("canonical claim policy registry",),
            safe_descriptions=("exact observations remain independently describable",),
            support_hashes=_support_hashes(intent),
            analysis_hashes=_analysis_hashes(intent),
            comparability_hashes=_comparability_hashes(intent),
            bridge_hashes=_bridge_hashes(intent),
            evidence_applicability_hash=(
                intent.evidence_applicability.canonical_applicability_hash
                if intent.evidence_applicability is not None
                else None
            ),
            registry_version=registry.registry_version,
            software_version="dynamislm-res70-1.0.0",
            refusal_result=registry_refusal,
        )

    (
        allowed_measurement,
        blocked_measurement,
        measurement_reasons,
        measurement_missing,
        measurement_first,
    ) = _evaluate_axis(intent, _MEASUREMENT_LEVELS, ClaimAxis.MEASUREMENT_CHANGE, registry)
    (
        allowed_relationship,
        blocked_relationship,
        relationship_reasons,
        relationship_missing,
        relationship_first,
    ) = _evaluate_axis(intent, _RELATIONSHIP_LEVELS, ClaimAxis.RELATIONSHIP_CAUSAL, registry)
    allowed_measurement = cast(tuple[MeasurementClaimLevel, ...], allowed_measurement)
    allowed_relationship = cast(tuple[RelationshipClaimLevel, ...], allowed_relationship)
    reasons: tuple[str, ...] = tuple(dict.fromkeys((*measurement_reasons, *relationship_reasons)))
    missing: tuple[str, ...] = tuple(dict.fromkeys((*measurement_missing, *relationship_missing)))
    first = measurement_first or relationship_first
    prediction_status = PredictionStatus.NOT_REQUESTED
    if intent.predictive_intent is not None:
        prediction_status = PredictionStatus.REFUSED
        reasons = tuple(dict.fromkeys((*reasons, "COMPUTATION_NOT_REGISTERED")))
        missing = (*missing, "registered predictive-validity contract")
        first = first or "registered predictive-validity contract"
    requested_axes = (
        int(intent.measurement_level is not None)
        + int(intent.relationship_level is not None)
        + int(intent.predictive_intent is not None)
    )
    authorized_axes = int(
        intent.measurement_level is not None and intent.measurement_level in allowed_measurement
    ) + int(
        intent.relationship_level is not None and intent.relationship_level in allowed_relationship
    )
    if (
        intent.predictive_intent is not None
        and prediction_status is not PredictionStatus.AUTHORIZED
    ):
        authorized_axes = max(0, authorized_axes - 1)
    blocked_claims: tuple[str, ...] = (*blocked_measurement, *blocked_relationship)
    if intent.predictive_intent is not None:
        blocked_claims = (*blocked_claims, intent.predictive_intent.stable_id)
    refusal: RefusalResult | None
    if not blocked_claims and authorized_axes == requested_axes:
        status = ClaimAuthorityStatus.AUTHORIZED
        refusal = None
    elif allowed_measurement or allowed_relationship:
        status = ClaimAuthorityStatus.PARTIALLY_AUTHORIZED
        refusal = build_res70_refusal(
            "claim authority escalation",
            reasons[0] if reasons else "RES70_UNSUPPORTED_CLAIM_ESCALATION",
            refusal_class=(
                RefusalClass.CAUSAL_IDENTIFICATION_UNSUPPORTED
                if "RES70_UNSUPPORTED_CAUSAL_CLAIM" in reasons
                else RefusalClass.UNCERTAINTY_LIMITS_CLAIM
            ),
            missing_information=missing,
            observation_ids=_observation_ids(intent),
        )
    else:
        status = ClaimAuthorityStatus.REFUSED
        refusal = build_res70_refusal(
            "claim authority",
            reasons[0] if reasons else "RES70_UNSUPPORTED_CLAIM_ESCALATION",
            refusal_class=(
                RefusalClass.CAUSAL_IDENTIFICATION_UNSUPPORTED
                if "RES70_UNSUPPORTED_CAUSAL_CLAIM" in reasons
                else RefusalClass.UNCERTAINTY_LIMITS_CLAIM
            ),
            missing_information=missing,
            observation_ids=_observation_ids(intent),
        )
    safe_descriptions: tuple[str, ...] = (
        "exact valid observations remain safely describable under their recorded identity",
    )
    if status is ClaimAuthorityStatus.PARTIALLY_AUTHORIZED:
        safe_descriptions = (
            *safe_descriptions,
            "authorized lower claim levels remain available without implying the blocked level",
        )
    return ClaimAuthorityResult.create(
        status=status,
        claim_intent_reference=intent.claim_reference,
        claim_intent_hash=intent.intent_hash,
        allowed_measurement_levels=allowed_measurement,
        allowed_relationship_levels=allowed_relationship,
        prediction_status=prediction_status,
        blocked_claims=blocked_claims,
        first_blocking_prerequisite=first,
        reason_codes=reasons,
        missing_information=missing,
        safe_descriptions=safe_descriptions,
        support_hashes=_support_hashes(intent),
        analysis_hashes=_analysis_hashes(intent),
        comparability_hashes=_comparability_hashes(intent),
        bridge_hashes=_bridge_hashes(intent),
        evidence_applicability_hash=(
            intent.evidence_applicability.canonical_applicability_hash
            if intent.evidence_applicability is not None
            else None
        ),
        registry_version=registry.registry_version,
        software_version="dynamislm-res70-1.0.0",
        refusal_result=refusal,
    )


__all__ = ["authorize_claim"]
