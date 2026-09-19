"""Canonical RES-70 claim prerequisite policies."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from dynamislm.claims.models import MeasurementClaimLevel, RelationshipClaimLevel
from dynamislm.evidence.res70 import ApplicabilityAxis
from dynamislm.measurement.identity import (
    RegistryReference,
    ScientificIdentifier,
    _require_enum,
    _require_instance,
    _require_text,
    _require_tuple_items,
    require_tuple,
)
from dynamislm.serialization import canonical_hash, register_serializable_type

RES70_CLAIM_REGISTRY_VERSION = "1.0.0"


class ClaimAxis(StrEnum):
    MEASUREMENT_CHANGE = "MEASUREMENT_CHANGE"
    RELATIONSHIP_CAUSAL = "RELATIONSHIP_CAUSAL"


ClaimLevel = MeasurementClaimLevel | RelationshipClaimLevel


def _reference(key: str, label: str) -> RegistryReference:
    return RegistryReference(
        ScientificIdentifier("dynamislm", "claim-policy", key, RES70_CLAIM_REGISTRY_VERSION),
        label,
    )


@register_serializable_type
@dataclass(frozen=True, slots=True)
class ClaimPolicy:
    policy_reference: RegistryReference
    axis: ClaimAxis
    level: ClaimLevel
    ordinal: int
    required_lower_level: ClaimLevel | None
    requires_analysis: bool
    requires_statistical_result: bool
    required_evidence_axes: tuple[ApplicabilityAxis, ...]
    requires_comparability: bool
    requires_measurement_error_authority: bool
    requires_decision_criterion: bool
    causal_operation_required: bool

    def __post_init__(self) -> None:
        _require_instance(self.policy_reference, RegistryReference, "policy_reference")
        if self.policy_reference.identifier.object_type != "claim-policy":
            raise ValueError("policy_reference must identify a claim policy")
        _require_enum(self.axis, ClaimAxis, "axis")
        if not isinstance(self.level, MeasurementClaimLevel | RelationshipClaimLevel):
            raise ValueError("level must be a registered claim level")
        if (
            isinstance(self.level, MeasurementClaimLevel)
            and self.axis is not ClaimAxis.MEASUREMENT_CHANGE
        ):
            raise ValueError("measurement level must use the measurement-change axis")
        if (
            isinstance(self.level, RelationshipClaimLevel)
            and self.axis is not ClaimAxis.RELATIONSHIP_CAUSAL
        ):
            raise ValueError("relationship level must use the relationship-causal axis")
        if isinstance(self.required_lower_level, MeasurementClaimLevel | RelationshipClaimLevel):
            if type(self.required_lower_level) is not type(self.level):
                raise ValueError("lower-level prerequisite must use the same claim axis")
        if isinstance(self.required_lower_level, type(None)) is False and not isinstance(
            self.required_lower_level,
            MeasurementClaimLevel | RelationshipClaimLevel,
        ):
            raise ValueError("required_lower_level must be a claim level or None")
        if isinstance(self.ordinal, bool) or self.ordinal < 0:
            raise ValueError("claim policy ordinal must be a non-negative integer")
        for field_name, value in (
            ("requires_analysis", self.requires_analysis),
            ("requires_statistical_result", self.requires_statistical_result),
            ("requires_comparability", self.requires_comparability),
            ("requires_measurement_error_authority", self.requires_measurement_error_authority),
            ("requires_decision_criterion", self.requires_decision_criterion),
            ("causal_operation_required", self.causal_operation_required),
        ):
            if not isinstance(value, bool):
                raise ValueError(f"{field_name} must be a boolean")
        require_tuple(self.required_evidence_axes, "required_evidence_axes")
        if any(not isinstance(item, ApplicabilityAxis) for item in self.required_evidence_axes):
            raise ValueError("required_evidence_axes must contain ApplicabilityAxis values")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class ClaimPolicyRegistry:
    entries: tuple[ClaimPolicy, ...]
    registry_version: str = RES70_CLAIM_REGISTRY_VERSION
    registry_hash: str | None = None

    def __post_init__(self) -> None:
        require_tuple(self.entries, "entries")
        _require_tuple_items(self.entries, ClaimPolicy, "entries")
        _require_text(self.registry_version, "registry_version")
        keys = tuple((item.axis, item.level) for item in self.entries)
        if len(set(keys)) != len(keys):
            raise ValueError("claim policy registry cannot contain duplicate axis/level entries")
        if any(
            item.policy_reference.identifier.version != self.registry_version
            for item in self.entries
        ):
            raise ValueError("claim policy and registry versions must match")
        expected = canonical_hash(
            {"entries": self.entries, "registry_version": self.registry_version}
        )
        if self.registry_hash is None:
            object.__setattr__(self, "registry_hash", expected)
        elif self.registry_hash != expected:
            raise ValueError("claim policy registry hash does not match entries")

    def resolve(self, axis: ClaimAxis, level: ClaimLevel) -> ClaimPolicy | None:
        matches = tuple(item for item in self.entries if item.axis is axis and item.level is level)
        if len(matches) > 1:
            raise ValueError("RES70_REGISTRY_INTEGRITY_FAILURE: duplicate claim policy")
        return matches[0] if matches else None

    @property
    def canonical_hash(self) -> str:
        assert self.registry_hash is not None
        return self.registry_hash


def _measurement_policy(
    level: MeasurementClaimLevel,
    ordinal: int,
    *,
    lower: MeasurementClaimLevel | None = None,
    analysis: bool = False,
    result: bool = False,
    evidence: tuple[ApplicabilityAxis, ...] = (),
    comparable: bool = False,
    error: bool = False,
    criterion: bool = False,
) -> ClaimPolicy:
    return ClaimPolicy(
        policy_reference=_reference(f"measurement-{level.value.lower()}", level.value),
        axis=ClaimAxis.MEASUREMENT_CHANGE,
        level=level,
        ordinal=ordinal,
        required_lower_level=lower,
        requires_analysis=analysis,
        requires_statistical_result=result,
        required_evidence_axes=evidence,
        requires_comparability=comparable,
        requires_measurement_error_authority=error,
        requires_decision_criterion=criterion,
        causal_operation_required=False,
    )


def _relationship_policy(
    level: RelationshipClaimLevel,
    ordinal: int,
    *,
    lower: RelationshipClaimLevel | None = None,
    analysis: bool = False,
    result: bool = False,
    evidence: tuple[ApplicabilityAxis, ...] = (),
    causal: bool = False,
) -> ClaimPolicy:
    return ClaimPolicy(
        policy_reference=_reference(f"relationship-{level.value.lower()}", level.value),
        axis=ClaimAxis.RELATIONSHIP_CAUSAL,
        level=level,
        ordinal=ordinal,
        required_lower_level=lower,
        requires_analysis=analysis,
        requires_statistical_result=result,
        required_evidence_axes=evidence,
        requires_comparability=False,
        requires_measurement_error_authority=False,
        requires_decision_criterion=False,
        causal_operation_required=causal,
    )


RES70_CLAIM_POLICIES = (
    _measurement_policy(MeasurementClaimLevel.OBSERVED_VALUE, 0),
    _measurement_policy(
        MeasurementClaimLevel.NUMERICAL_CHANGE,
        1,
        lower=MeasurementClaimLevel.OBSERVED_VALUE,
        analysis=True,
        result=True,
    ),
    _measurement_policy(
        MeasurementClaimLevel.COMPARABLE_CHANGE,
        2,
        lower=MeasurementClaimLevel.NUMERICAL_CHANGE,
        analysis=True,
        result=True,
        comparable=True,
    ),
    _measurement_policy(
        MeasurementClaimLevel.CHANGE_RELATIVE_TO_MEASUREMENT_ERROR,
        3,
        lower=MeasurementClaimLevel.COMPARABLE_CHANGE,
        analysis=True,
        result=True,
        evidence=(ApplicabilityAxis.METHOD_VALIDITY, ApplicabilityAxis.STATISTICAL_ADEQUACY),
        comparable=True,
        error=True,
    ),
    _measurement_policy(
        MeasurementClaimLevel.PRACTICAL_OR_DECISION_MEANINGFULNESS,
        4,
        lower=MeasurementClaimLevel.CHANGE_RELATIVE_TO_MEASUREMENT_ERROR,
        analysis=True,
        result=True,
        evidence=(
            ApplicabilityAxis.METHOD_VALIDITY,
            ApplicabilityAxis.POPULATION_RELEVANCE,
            ApplicabilityAxis.CONTEXTUAL_RELEVANCE,
            ApplicabilityAxis.STATISTICAL_ADEQUACY,
        ),
        comparable=True,
        error=True,
        criterion=True,
    ),
    _relationship_policy(RelationshipClaimLevel.OBSERVATION, 0),
    _relationship_policy(
        RelationshipClaimLevel.DESCRIPTIVE_CHANGE,
        1,
        lower=RelationshipClaimLevel.OBSERVATION,
        analysis=True,
        result=True,
    ),
    _relationship_policy(
        RelationshipClaimLevel.ASSOCIATION,
        2,
        lower=RelationshipClaimLevel.DESCRIPTIVE_CHANGE,
        analysis=True,
        result=True,
        evidence=(ApplicabilityAxis.STATISTICAL_ADEQUACY,),
    ),
    _relationship_policy(
        RelationshipClaimLevel.TEMPORAL_ASSOCIATION,
        3,
        lower=RelationshipClaimLevel.ASSOCIATION,
        analysis=True,
        result=True,
        evidence=(ApplicabilityAxis.STATISTICAL_ADEQUACY,),
    ),
    _relationship_policy(
        RelationshipClaimLevel.MECHANISTIC_HYPOTHESIS,
        4,
        lower=RelationshipClaimLevel.TEMPORAL_ASSOCIATION,
        analysis=True,
        result=True,
        evidence=(
            ApplicabilityAxis.METHOD_VALIDITY,
            ApplicabilityAxis.POPULATION_RELEVANCE,
            ApplicabilityAxis.CONTEXTUAL_RELEVANCE,
        ),
    ),
    _relationship_policy(
        RelationshipClaimLevel.CAUSAL_EVIDENCE,
        5,
        lower=RelationshipClaimLevel.MECHANISTIC_HYPOTHESIS,
        analysis=True,
        result=True,
        evidence=(
            ApplicabilityAxis.METHOD_VALIDITY,
            ApplicabilityAxis.POPULATION_RELEVANCE,
            ApplicabilityAxis.CONTEXTUAL_RELEVANCE,
            ApplicabilityAxis.STATISTICAL_ADEQUACY,
        ),
        causal=True,
    ),
)

RES70_CLAIM_POLICY_REGISTRY = ClaimPolicyRegistry(entries=RES70_CLAIM_POLICIES)
CANONICAL_CLAIM_POLICY_REGISTRY = RES70_CLAIM_POLICY_REGISTRY


def is_canonical_claim_registry(registry: ClaimPolicyRegistry) -> bool:
    return registry is CANONICAL_CLAIM_POLICY_REGISTRY


__all__ = [
    "CANONICAL_CLAIM_POLICY_REGISTRY",
    "RES70_CLAIM_POLICIES",
    "RES70_CLAIM_POLICY_REGISTRY",
    "RES70_CLAIM_REGISTRY_VERSION",
    "ClaimAxis",
    "ClaimLevel",
    "ClaimPolicy",
    "ClaimPolicyRegistry",
    "is_canonical_claim_registry",
]
