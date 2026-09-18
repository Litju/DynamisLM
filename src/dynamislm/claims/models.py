"""RES-70 two-axis claim-authority contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from dynamislm.analysis.models import AnalysisAuthorization
from dynamislm.comparability.res70_models import CrossSourceComparabilityDecision
from dynamislm.evidence.res70 import ClaimEvidenceApplicability
from dynamislm.longitudinal.statistics.models import StatisticalResult
from dynamislm.measurement.identity import (
    InstanceIdentifier,
    RegistryReference,
    _require_enum,
    _require_instance,
    _require_optional_instance,
    _require_text,
    _require_tuple_items,
    require_tuple,
)
from dynamislm.measurement.observation import ScientificMeasurementObservation
from dynamislm.refusal.models import RefusalResult
from dynamislm.serialization import canonical_hash, register_serializable_type

_SHA256_PREFIX = "sha256:"


def _require_hash(value: str, field_name: str) -> None:
    _require_text(value, field_name)
    digest = value.removeprefix(_SHA256_PREFIX)
    if (
        not value.startswith(_SHA256_PREFIX)
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise ValueError(f"{field_name} must be a canonical sha256 hash")


def _require_string_tuple(value: object, field_name: str) -> None:
    require_tuple(value, field_name)
    assert isinstance(value, tuple)
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError(f"{field_name} must contain non-empty strings")


class MeasurementClaimLevel(StrEnum):
    OBSERVED_VALUE = "OBSERVED_VALUE"
    NUMERICAL_CHANGE = "NUMERICAL_CHANGE"
    COMPARABLE_CHANGE = "COMPARABLE_CHANGE"
    CHANGE_RELATIVE_TO_MEASUREMENT_ERROR = "CHANGE_RELATIVE_TO_MEASUREMENT_ERROR"
    PRACTICAL_OR_DECISION_MEANINGFULNESS = "PRACTICAL_OR_DECISION_MEANINGFULNESS"


class RelationshipClaimLevel(StrEnum):
    OBSERVATION = "OBSERVATION"
    DESCRIPTIVE_CHANGE = "DESCRIPTIVE_CHANGE"
    ASSOCIATION = "ASSOCIATION"
    TEMPORAL_ASSOCIATION = "TEMPORAL_ASSOCIATION"
    MECHANISTIC_HYPOTHESIS = "MECHANISTIC_HYPOTHESIS"
    CAUSAL_EVIDENCE = "CAUSAL_EVIDENCE"


class ClaimTarget(StrEnum):
    INDIVIDUAL = "INDIVIDUAL"
    ATHLETE_WITHIN = "ATHLETE_WITHIN"
    ATHLETE_BETWEEN = "ATHLETE_BETWEEN"
    GROUP = "GROUP"
    POPULATION = "POPULATION"


class PredictionStatus(StrEnum):
    NOT_REQUESTED = "NOT_REQUESTED"
    AUTHORIZED = "AUTHORIZED"
    REFUSED = "REFUSED"


class ClaimAuthorityStatus(StrEnum):
    AUTHORIZED = "AUTHORIZED"
    PARTIALLY_AUTHORIZED = "PARTIALLY_AUTHORIZED"
    REFUSED = "REFUSED"


@register_serializable_type
@dataclass(frozen=True, slots=True)
class ClaimIntent:
    """A typed request for one or both orthogonal claim axes."""

    claim_reference: RegistryReference
    measurement_level: MeasurementClaimLevel | None
    relationship_level: RelationshipClaimLevel | None
    predictive_intent: RegistryReference | None
    target: ClaimTarget
    analysis_reference: RegistryReference | None
    evidence_applicability_reference: RegistryReference | None
    decision_criterion_reference: RegistryReference | None
    observations: tuple[ScientificMeasurementObservation, ...] = ()
    analysis_authorization: AnalysisAuthorization | None = None
    comparability_decisions: tuple[CrossSourceComparabilityDecision, ...] = ()
    statistical_result: StatisticalResult | None = None
    evidence_applicability: ClaimEvidenceApplicability | None = None

    def __post_init__(self) -> None:
        _require_instance(self.claim_reference, RegistryReference, "claim_reference")
        _require_optional_instance(
            self.measurement_level,
            MeasurementClaimLevel,
            "measurement_level",
        )
        _require_optional_instance(
            self.relationship_level,
            RelationshipClaimLevel,
            "relationship_level",
        )
        _require_optional_instance(self.predictive_intent, RegistryReference, "predictive_intent")
        _require_enum(self.target, ClaimTarget, "target")
        _require_optional_instance(self.analysis_reference, RegistryReference, "analysis_reference")
        _require_optional_instance(
            self.evidence_applicability_reference,
            RegistryReference,
            "evidence_applicability_reference",
        )
        _require_optional_instance(
            self.decision_criterion_reference,
            RegistryReference,
            "decision_criterion_reference",
        )
        if (
            self.measurement_level is None
            and self.relationship_level is None
            and self.predictive_intent is None
        ):
            raise ValueError("claim intent must request at least one claim axis")
        _require_tuple_items(self.observations, ScientificMeasurementObservation, "observations")
        _require_optional_instance(
            self.analysis_authorization,
            AnalysisAuthorization,
            "analysis_authorization",
        )
        _require_tuple_items(
            self.comparability_decisions,
            CrossSourceComparabilityDecision,
            "comparability_decisions",
        )
        _require_optional_instance(self.statistical_result, StatisticalResult, "statistical_result")
        _require_optional_instance(
            self.evidence_applicability,
            ClaimEvidenceApplicability,
            "evidence_applicability",
        )
        if self.evidence_applicability is not None:
            if (
                self.evidence_applicability_reference is not None
                and self.evidence_applicability.claim_intent_reference
                != self.evidence_applicability_reference
            ):
                raise ValueError("evidence applicability reference does not match its bundle")
        if self.analysis_authorization is not None and self.analysis_reference is not None:
            if self.analysis_authorization.capability_reference != self.analysis_reference:
                raise ValueError("analysis reference does not match its authorization")

    @property
    def intent_hash(self) -> str:
        return canonical_hash(self)


@register_serializable_type
@dataclass(frozen=True, slots=True)
class ClaimAuthorityResult:
    """Reproducible allowed/blocked claim authority for both axes."""

    decision_id: InstanceIdentifier
    status: ClaimAuthorityStatus
    claim_intent_reference: RegistryReference
    allowed_measurement_levels: tuple[MeasurementClaimLevel, ...]
    allowed_relationship_levels: tuple[RelationshipClaimLevel, ...]
    prediction_status: PredictionStatus
    blocked_claims: tuple[str, ...]
    first_blocking_prerequisite: str | None
    reason_codes: tuple[str, ...]
    missing_information: tuple[str, ...]
    safe_descriptions: tuple[str, ...]
    support_hashes: tuple[str, ...]
    analysis_hashes: tuple[str, ...]
    comparability_hashes: tuple[str, ...]
    bridge_hashes: tuple[str, ...]
    evidence_applicability_hash: str | None
    registry_version: str
    software_version: str
    refusal_result: RefusalResult | None = None
    decision_hash: str | None = None

    def __post_init__(self) -> None:
        _require_instance(self.decision_id, InstanceIdentifier, "decision_id")
        if self.decision_id.instance_type != "claim-authority-decision":
            raise ValueError("decision_id must identify a claim-authority-decision")
        _require_enum(self.status, ClaimAuthorityStatus, "status")
        _require_instance(
            self.claim_intent_reference,
            RegistryReference,
            "claim_intent_reference",
        )
        _require_tuple_items(
            self.allowed_measurement_levels,
            MeasurementClaimLevel,
            "allowed_measurement_levels",
        )
        _require_tuple_items(
            self.allowed_relationship_levels,
            RelationshipClaimLevel,
            "allowed_relationship_levels",
        )
        _require_enum(self.prediction_status, PredictionStatus, "prediction_status")
        _require_string_tuple(self.blocked_claims, "blocked_claims")
        if self.first_blocking_prerequisite is not None:
            _require_text(self.first_blocking_prerequisite, "first_blocking_prerequisite")
        _require_string_tuple(self.reason_codes, "reason_codes")
        _require_string_tuple(self.missing_information, "missing_information")
        _require_string_tuple(self.safe_descriptions, "safe_descriptions")
        for field_name, values in (
            ("support_hashes", self.support_hashes),
            ("analysis_hashes", self.analysis_hashes),
            ("comparability_hashes", self.comparability_hashes),
            ("bridge_hashes", self.bridge_hashes),
        ):
            require_tuple(values, field_name)
            for item in values:
                _require_hash(item, f"{field_name} item")
        if self.evidence_applicability_hash is not None:
            _require_hash(self.evidence_applicability_hash, "evidence_applicability_hash")
        _require_text(self.registry_version, "registry_version")
        _require_text(self.software_version, "software_version")
        _require_optional_instance(self.refusal_result, RefusalResult, "refusal_result")
        if self.status is ClaimAuthorityStatus.AUTHORIZED and self.refusal_result is not None:
            raise ValueError("fully authorized claim cannot contain a refusal result")
        if self.status is not ClaimAuthorityStatus.AUTHORIZED and self.refusal_result is None:
            raise ValueError("blocked claim authority must retain a structured refusal result")
        expected_hash = canonical_hash(
            {
                "status": self.status,
                "claim_intent_reference": self.claim_intent_reference,
                "allowed_measurement_levels": self.allowed_measurement_levels,
                "allowed_relationship_levels": self.allowed_relationship_levels,
                "prediction_status": self.prediction_status,
                "blocked_claims": self.blocked_claims,
                "first_blocking_prerequisite": self.first_blocking_prerequisite,
                "reason_codes": self.reason_codes,
                "missing_information": self.missing_information,
                "safe_descriptions": self.safe_descriptions,
                "support_hashes": self.support_hashes,
                "analysis_hashes": self.analysis_hashes,
                "comparability_hashes": self.comparability_hashes,
                "bridge_hashes": self.bridge_hashes,
                "evidence_applicability_hash": self.evidence_applicability_hash,
                "registry_version": self.registry_version,
                "software_version": self.software_version,
                "refusal_result": self.refusal_result,
            }
        )
        if self.decision_hash is None:
            object.__setattr__(self, "decision_hash", expected_hash)
        elif self.decision_hash != expected_hash:
            raise ValueError("decision_hash does not match immutable claim decision content")
        expected_id = InstanceIdentifier(
            "claim-authority-decision", expected_hash.removeprefix(_SHA256_PREFIX)
        )
        if self.decision_id != expected_id:
            raise ValueError("decision_id does not match immutable claim decision content")

    @property
    def canonical_decision_hash(self) -> str:
        assert self.decision_hash is not None
        return self.decision_hash


__all__ = [
    "ClaimAuthorityResult",
    "ClaimAuthorityStatus",
    "ClaimIntent",
    "ClaimTarget",
    "MeasurementClaimLevel",
    "PredictionStatus",
    "RelationshipClaimLevel",
]
