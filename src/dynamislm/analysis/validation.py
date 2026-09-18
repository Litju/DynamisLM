"""Deterministic prerequisite and hash validation for RES-70 analyses."""

from __future__ import annotations

from collections import Counter

from dynamislm.analysis.models import (
    AnalysisAuthorizationRequest,
    AnalysisCapability,
    AnalysisEstimandLevel,
)
from dynamislm.analysis.registry import (
    RES70_ANALYSIS_REGISTRY_VERSION,
    AnalysisCapabilityRegistry,
    is_canonical_analysis_registry,
)
from dynamislm.comparability.models import ComparabilityState
from dynamislm.comparability.res70_models import SemanticIdentityKey
from dynamislm.comparability.res70_validation import validate_pairwise_decisions
from dynamislm.evidence.res70 import ApplicabilityAxis
from dynamislm.longitudinal.statistics.models import StatisticalSupport
from dynamislm.longitudinal.statistics.support import (
    StatisticalConstraintError,
    validate_statistical_support,
)
from dynamislm.measurement.result import ScalarValue
from dynamislm.serialization import canonical_hash


class AnalysisValidationError(ValueError):
    """Raised for a deterministic RES-70 prerequisite failure."""

    def __init__(self, message: str, code: str, missing_information: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.code = code
        self.missing_information = missing_information


def validate_analysis_capability_registry(registry: AnalysisCapabilityRegistry) -> None:
    if not isinstance(registry, AnalysisCapabilityRegistry):
        raise AnalysisValidationError(
            "analysis capability registry must be typed",
            "RES70_REGISTRY_INTEGRITY_FAILURE",
        )
    if not is_canonical_analysis_registry(registry):
        raise AnalysisValidationError(
            "caller-supplied analysis capability registries cannot authorize analysis",
            "RES70_REGISTRY_INTEGRITY_FAILURE",
        )
    if registry.registry_version != RES70_ANALYSIS_REGISTRY_VERSION:
        raise AnalysisValidationError(
            "analysis capability registry version is not canonical",
            "RES70_REGISTRY_INTEGRITY_FAILURE",
        )
    expected = canonical_hash(
        {"entries": registry.entries, "registry_version": registry.registry_version}
    )
    if registry.canonical_hash != expected:
        raise AnalysisValidationError(
            "analysis capability registry hash does not match entries",
            "RES70_REGISTRY_INTEGRITY_FAILURE",
        )


def validate_exact_support(request: AnalysisAuthorizationRequest) -> StatisticalSupport:
    support = request.support
    if support is None:
        raise AnalysisValidationError(
            "an exact StatisticalSupport object is required for RES-70 authorization",
            "RES70_STATISTICAL_AUTHORITY_INSUFFICIENT",
            ("exact StatisticalSupport snapshot",),
        )
    try:
        validate_statistical_support(support)
    except StatisticalConstraintError as exc:
        raise AnalysisValidationError(
            str(exc),
            "RES70_STATISTICAL_AUTHORITY_INSUFFICIENT",
            getattr(exc, "missing_information", ()),
        ) from exc
    if request.support_reference is not None and request.support_reference.stable_id != (
        f"dynamislm:statistical-support:{support.canonical_support_id.value}@1.0.0"
    ):
        raise AnalysisValidationError(
            "support reference does not identify the exact supplied support",
            "RES70_REGISTRY_INTEGRITY_FAILURE",
        )
    return support


def validate_observation_hashes(
    request: AnalysisAuthorizationRequest,
    support: StatisticalSupport,
) -> tuple[str, ...]:
    expected = tuple(
        canonical_hash(entry.observation.identity) for entry in support.included_entries
    )
    if request.identity_hashes and request.identity_hashes != expected:
        raise AnalysisValidationError(
            "analysis request identity hashes do not match exact support",
            "RES70_REGISTRY_INTEGRITY_FAILURE",
        )
    if request.observations:
        expected_ids = tuple(entry.source_observation_id for entry in support.included_entries)
        actual_ids = tuple(item.observation_id for item in request.observations)
        if actual_ids != expected_ids:
            raise AnalysisValidationError(
                "analysis observations do not match exact support ordering",
                "RES70_REGISTRY_INTEGRITY_FAILURE",
            )
        for observation in request.observations:
            if canonical_hash(observation.identity) not in expected:
                raise AnalysisValidationError(
                    "analysis observation identity is not part of exact support",
                    "RES70_REGISTRY_INTEGRITY_FAILURE",
                )
    return expected


def _scalar_entries(support: StatisticalSupport) -> tuple[object, ...]:
    return tuple(
        entry
        for entry in support.included_entries
        if isinstance(entry.observation.result.value, ScalarValue)
        and not isinstance(entry.observation.result.value.value, bool)
        and isinstance(entry.observation.result.value.value, int | float)
    )


def _pair_key(left: object, right: object) -> frozenset[str]:
    return frozenset(
        (
            left.source_observation_id.qualified,  # type: ignore[attr-defined]
            right.source_observation_id.qualified,  # type: ignore[attr-defined]
        )
    )


def validate_level_of_analysis(
    request: AnalysisAuthorizationRequest,
    capability: AnalysisCapability,
    support: StatisticalSupport,
) -> None:
    level = request.requested_level
    if capability.required_level_of_analysis and level.estimand_level not in (
        capability.required_level_of_analysis
    ):
        raise AnalysisValidationError(
            "requested estimand level does not match the registered capability",
            "RES70_WRONG_LEVEL_OF_ANALYSIS",
            ("registered level-of-analysis identity",),
        )
    athlete_ids = tuple(entry.observation.context.athlete_id.qualified for entry in support.entries)
    if level.estimand_level is AnalysisEstimandLevel.WITHIN_ATHLETE:
        if len(set(athlete_ids)) != 1:
            raise AnalysisValidationError(
                "within-athlete analysis cannot pool multiple athletes",
                "RES70_WRONG_LEVEL_OF_ANALYSIS",
                ("one athlete or registered multilevel estimator",),
            )
        if level.subject_key not in ("athlete_id", "athlete"):
            raise AnalysisValidationError(
                "within-athlete analysis must identify athlete as subject",
                "RES70_WRONG_LEVEL_OF_ANALYSIS",
            )
    elif level.estimand_level is AnalysisEstimandLevel.BETWEEN_ATHLETE:
        counts = Counter(athlete_ids)
        if any(count > 1 for count in counts.values()) and not level.clustering_keys:
            raise AnalysisValidationError(
                "pseudoreplication risk: repeated rows cannot be treated as independent "
                "between-athlete subjects",
                "RES70_PSEUDOREPLICATION_RISK",
                ("one independent unit per athlete or a registered clustering model",),
            )
        if level.subject_key not in ("athlete_id", "athlete"):
            raise AnalysisValidationError(
                "between-athlete analysis must identify athlete as subject",
                "RES70_WRONG_LEVEL_OF_ANALYSIS",
            )
    elif level.estimand_level is AnalysisEstimandLevel.JOINT_MULTILEVEL:
        if not level.clustering_keys:
            raise AnalysisValidationError(
                "joint multilevel analysis requires explicit clustering keys",
                "RES70_WRONG_LEVEL_OF_ANALYSIS",
            )


def validate_support_shape(
    request: AnalysisAuthorizationRequest,
    capability: AnalysisCapability,
    support: StatisticalSupport,
) -> None:
    entries = support.entries
    scalar_count = len(_scalar_entries(support))
    for shape in capability.required_support_shape:
        if shape == "exactly-two-scalar-entries" and (len(entries) != 2 or scalar_count != 2):
            raise AnalysisValidationError(
                "registered scalar capability requires exactly two numeric scalar entries",
                "RES70_STATISTICAL_AUTHORITY_INSUFFICIENT",
                ("two valid scalar entries",),
            )
        if shape == "nonzero-denominator" and (
            scalar_count != 2 or float(entries[0].observation.result.value.value) == 0.0  # type: ignore[union-attr]
        ):
            raise AnalysisValidationError(
                "relative change requires a nonzero baseline denominator",
                "RES70_STATISTICAL_AUTHORITY_INSUFFICIENT",
                ("nonzero baseline scalar",),
            )
        if shape == "strictly-positive-values" and (
            scalar_count != len(entries)
            or any(float(entry.observation.result.value.value) <= 0 for entry in entries)  # type: ignore[union-attr]
        ):
            raise AnalysisValidationError(
                "log change requires strictly positive scalar values",
                "RES70_STATISTICAL_AUTHORITY_INSUFFICIENT",
                ("strictly positive ratio-scale values",),
            )
        if shape == "one-current-entry" and support.current_entry_id is None:
            raise AnalysisValidationError(
                "reference-window deviation requires one explicit current entry",
                "RES70_STATISTICAL_AUTHORITY_INSUFFICIENT",
                ("current_entry_id",),
            )
        if shape == "at-least-two-reference-entries" and len(support.reference_entry_ids) < 2:
            raise AnalysisValidationError(
                "reference-window deviation requires at least two reference entries",
                "RES70_STATISTICAL_AUTHORITY_INSUFFICIENT",
                ("two prior reference entries",),
            )
        if shape == "repeated-observations" and len(entries) < 2:
            raise AnalysisValidationError(
                "repeated analysis requires at least two observations",
                "RES70_STATISTICAL_AUTHORITY_INSUFFICIENT",
                ("repeated observations",),
            )
        if shape == "explicit-clustering" and not request.requested_level.clustering_keys:
            raise AnalysisValidationError(
                "repeated analysis requires explicit clustering keys",
                "RES70_WRONG_LEVEL_OF_ANALYSIS",
            )
        if shape == "one-independent-unit-per-athlete":
            counts = Counter(entry.observation.context.athlete_id.qualified for entry in entries)
            if any(count != 1 for count in counts.values()):
                raise AnalysisValidationError(
                    "between-athlete support contains repeated rows per athlete",
                    "RES70_PSEUDOREPLICATION_RISK",
                )
        if shape == "distinct-test-identities":
            keys = {
                SemanticIdentityKey.from_identity(entry.observation.identity) for entry in entries
            }
            if len(keys) < 2:
                raise AnalysisValidationError(
                    "cross-test association requires distinct registered test identities",
                    "RES70_STATISTICAL_AUTHORITY_INSUFFICIENT",
                )


def validate_comparability_authority(
    request: AnalysisAuthorizationRequest,
    capability: AnalysisCapability,
    support: StatisticalSupport,
) -> tuple[str, ...]:
    decisions = request.comparability_decisions
    if decisions:
        validate_pairwise_decisions(decisions)
    entries = support.entries
    required_pairs = tuple(
        (left, right)
        for index, left in enumerate(entries)
        for right in entries[index + 1 :]
        if (
            SemanticIdentityKey.from_identity(left.observation.identity)
            != SemanticIdentityKey.from_identity(right.observation.identity)
            or left.observation.result.unit != right.observation.result.unit
        )
    )
    by_pair = {decision.pair_key: decision for decision in decisions}
    hashes: list[str] = []
    for left, right in required_pairs:
        pair = _pair_key(left, right)
        decision = by_pair.get(pair)
        if decision is None:
            raise AnalysisValidationError(
                "material cross-source differences require a direct RES-70 pair decision",
                "RES70_COMPARABILITY_AUTHORITY_MISSING",
                ("direct pairwise comparability decision",),
            )
        if decision.state is ComparabilityState.REQUIRES_TRANSFORMATION:
            raise AnalysisValidationError(
                "comparison requires a bridge transformation that has not executed",
                "RES70_BRIDGE_NOT_EXECUTED",
                ("executed registered bridge output",),
            )
        if decision.state not in (
            ComparabilityState.COMPARABLE,
            ComparabilityState.COMPARABLE_WITH_CONDITIONS,
        ):
            raise AnalysisValidationError(
                "cross-source comparability is not affirmative",
                "RES70_COMPARABILITY_AUTHORITY_MISSING",
            )
        hashes.append(decision.canonical_decision_hash)
        if capability.required_bridge_execution and decision.bridge_application_reference is None:
            raise AnalysisValidationError(
                "registered capability requires executed bridge authority",
                "RES70_BRIDGE_NOT_EXECUTED",
            )
    return tuple(hashes)


def validate_evidence_applicability(
    request: AnalysisAuthorizationRequest,
    capability: AnalysisCapability,
) -> None:
    if not capability.required_evidence_axes:
        return
    if request.evidence_applicability is None:
        raise AnalysisValidationError(
            "registered analysis requires an evidence-applicability vector",
            "RES70_INSUFFICIENT_EVIDENCE_APPLICABILITY",
            ("ClaimEvidenceApplicability",),
        )
    for axis_name in capability.required_evidence_axes:
        try:
            axis = ApplicabilityAxis(axis_name)
            assessment = request.evidence_applicability.assessment(axis)
        except (KeyError, ValueError) as exc:
            raise AnalysisValidationError(
                "required evidence-applicability axis is absent",
                "RES70_APPLICABILITY_AXIS_UNASSESSED",
                (axis_name,),
            ) from exc
        if not assessment.required_for_claim or assessment.decision.value in {
            "UNSUPPORTED",
            "UNASSESSED",
        }:
            raise AnalysisValidationError(
                "required evidence-applicability axis is not affirmative",
                "RES70_INSUFFICIENT_EVIDENCE_APPLICABILITY",
                (axis_name,),
            )


__all__ = [
    "AnalysisValidationError",
    "validate_analysis_capability_registry",
    "validate_comparability_authority",
    "validate_evidence_applicability",
    "validate_exact_support",
    "validate_level_of_analysis",
    "validate_observation_hashes",
    "validate_support_shape",
]
