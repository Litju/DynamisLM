"""RES-70 analysis-capability and level-of-analysis contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from dynamislm.comparability.models import ComparabilityState
from dynamislm.comparability.res70_models import (
    BridgeApplicationRequest,
    BridgeExecutionResult,
    CrossSourceComparabilityDecision,
    CrossSourceComparabilityRequest,
)
from dynamislm.evidence.res70 import ClaimEvidenceApplicability
from dynamislm.longitudinal.statistics.models import (
    MeasurementScaleSemantics,
    MethodComparisonDesignAuthority,
    ReliabilityAssumptionAssessment,
    ReliabilityDesignAuthority,
    StatisticalSupport,
)
from dynamislm.measurement.identity import (
    InstanceIdentifier,
    MetadataEntry,
    RegistryReference,
    ScientificIdentifier,
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


class AnalysisClass(StrEnum):
    SCALAR_ABSOLUTE_CHANGE = "SCALAR_ABSOLUTE_CHANGE"
    SCALAR_RELATIVE_CHANGE = "SCALAR_RELATIVE_CHANGE"
    SCALAR_LOG_CHANGE = "SCALAR_LOG_CHANGE"
    BASELINE_REFERENCE_WINDOW_DEVIATION = "BASELINE_REFERENCE_WINDOW_DEVIATION"
    RELIABILITY_RANDOM_ERROR_COMPARISON = "RELIABILITY_RANDOM_ERROR_COMPARISON"
    METHOD_AGREEMENT_SUMMARY = "METHOD_AGREEMENT_SUMMARY"
    WITHIN_ATHLETE_ASSOCIATION = "WITHIN_ATHLETE_ASSOCIATION"
    BETWEEN_ATHLETE_ASSOCIATION = "BETWEEN_ATHLETE_ASSOCIATION"
    REPEATED_MEASURES_ANALYSIS = "REPEATED_MEASURES_ANALYSIS"
    MIXED_EFFECTS_ANALYSIS = "MIXED_EFFECTS_ANALYSIS"
    CROSS_TEST_ASSOCIATION = "CROSS_TEST_ASSOCIATION"


class AnalysisCapabilityDisposition(StrEnum):
    IMPLEMENTED = "IMPLEMENTED"
    REPRESENT_ONLY = "REPRESENT_ONLY"
    DEFERRED = "DEFERRED"
    REJECTED = "REJECTED"


class AnalysisUnitOfAnalysis(StrEnum):
    TRIAL = "TRIAL"
    TEST_INSTANCE = "TEST_INSTANCE"
    SESSION = "SESSION"
    ATHLETE = "ATHLETE"
    GROUP = "GROUP"


class AnalysisEstimandLevel(StrEnum):
    WITHIN_ATHLETE = "WITHIN_ATHLETE"
    BETWEEN_ATHLETE = "BETWEEN_ATHLETE"
    JOINT_MULTILEVEL = "JOINT_MULTILEVEL"
    GROUP = "GROUP"

    # Stable terminology used by the design's level-of-analysis vocabulary.
    ATHLETE_WITHIN = "WITHIN_ATHLETE"
    ATHLETE_BETWEEN = "BETWEEN_ATHLETE"
    GROUP_OR_SQUAD = "GROUP"


class AnalysisAuthorizationStatus(StrEnum):
    AUTHORIZED = "AUTHORIZED"
    REFUSED = "REFUSED"


AnalysisUnit = AnalysisUnitOfAnalysis
EstimandLevel = AnalysisEstimandLevel

AnalysisKey = str | InstanceIdentifier | ScientificIdentifier | RegistryReference


@register_serializable_type
@dataclass(frozen=True, slots=True)
class AnalysisLevelIdentity:
    """Explicit unit, clustering, pooling, and estimand identity."""

    unit_of_analysis: AnalysisUnitOfAnalysis
    estimand_level: AnalysisEstimandLevel
    subject_key: AnalysisKey
    clustering_keys: tuple[AnalysisKey, ...] = ()
    grouping_keys: tuple[AnalysisKey, ...] = ()
    temporal_order_policy: RegistryReference | None = None
    pooling_policy: RegistryReference | None = None

    def __post_init__(self) -> None:
        _require_enum(self.unit_of_analysis, AnalysisUnitOfAnalysis, "unit_of_analysis")
        _require_enum(self.estimand_level, AnalysisEstimandLevel, "estimand_level")
        if not isinstance(
            self.subject_key,
            str | InstanceIdentifier | ScientificIdentifier | RegistryReference,
        ):
            raise ValueError("subject_key must be a typed analysis key")
        if isinstance(self.subject_key, str) and not self.subject_key.strip():
            raise ValueError("subject_key must not be empty")
        for field_name, value in (
            ("clustering_keys", self.clustering_keys),
            ("grouping_keys", self.grouping_keys),
        ):
            require_tuple(value, field_name)
            if any(
                not isinstance(
                    item,
                    str | InstanceIdentifier | ScientificIdentifier | RegistryReference,
                )
                for item in value
            ):
                raise ValueError(f"{field_name} must contain typed analysis keys")
        _require_optional_instance(
            self.temporal_order_policy,
            RegistryReference,
            "temporal_order_policy",
        )
        _require_optional_instance(self.pooling_policy, RegistryReference, "pooling_policy")

    @property
    def level_key(self) -> str:
        return f"{self.unit_of_analysis.value}:{self.estimand_level.value}"


@register_serializable_type
@dataclass(frozen=True, slots=True)
class AnalysisCapability:
    """One immutable entry in the RES-70 capability matrix."""

    capability_reference: RegistryReference
    analysis_class: AnalysisClass
    registered_operation_reference: RegistryReference | None
    estimator_reference: RegistryReference | None
    disposition: AnalysisCapabilityDisposition
    required_support_shape: tuple[str, ...]
    required_identity_dimensions: tuple[str, ...]
    required_comparability_states: tuple[ComparabilityState, ...]
    required_bridge_execution: bool
    required_level_of_analysis: tuple[AnalysisEstimandLevel, ...]
    required_statistical_authority: tuple[RegistryReference, ...]
    required_evidence_axes: tuple[str, ...]
    required_context: tuple[str, ...]
    output_claim_floor: str | None
    registry_version: str
    capability_hash: str | None = None

    def __post_init__(self) -> None:
        _require_instance(self.capability_reference, RegistryReference, "capability_reference")
        if self.capability_reference.identifier.object_type != "analysis-capability":
            raise ValueError("capability_reference must identify an analysis capability")
        _require_enum(self.analysis_class, AnalysisClass, "analysis_class")
        _require_optional_instance(
            self.registered_operation_reference,
            RegistryReference,
            "registered_operation_reference",
        )
        _require_optional_instance(
            self.estimator_reference, RegistryReference, "estimator_reference"
        )
        _require_enum(self.disposition, AnalysisCapabilityDisposition, "disposition")
        _require_string_tuple(self.required_support_shape, "required_support_shape")
        _require_string_tuple(self.required_identity_dimensions, "required_identity_dimensions")
        require_tuple(self.required_comparability_states, "required_comparability_states")
        if any(
            not isinstance(item, ComparabilityState) for item in self.required_comparability_states
        ):
            raise ValueError("required_comparability_states must contain ComparabilityState values")
        if not isinstance(self.required_bridge_execution, bool):
            raise ValueError("required_bridge_execution must be a boolean")
        require_tuple(self.required_level_of_analysis, "required_level_of_analysis")
        if any(
            not isinstance(item, AnalysisEstimandLevel) for item in self.required_level_of_analysis
        ):
            raise ValueError("required_level_of_analysis must contain AnalysisEstimandLevel values")
        _require_tuple_items(
            self.required_statistical_authority,
            RegistryReference,
            "required_statistical_authority",
        )
        _require_string_tuple(self.required_evidence_axes, "required_evidence_axes")
        _require_string_tuple(self.required_context, "required_context")
        if self.output_claim_floor is not None:
            _require_text(self.output_claim_floor, "output_claim_floor")
        _require_text(self.registry_version, "registry_version")
        expected_hash = canonical_hash(
            {
                "capability_reference": self.capability_reference,
                "analysis_class": self.analysis_class,
                "registered_operation_reference": self.registered_operation_reference,
                "estimator_reference": self.estimator_reference,
                "disposition": self.disposition,
                "required_support_shape": self.required_support_shape,
                "required_identity_dimensions": self.required_identity_dimensions,
                "required_comparability_states": self.required_comparability_states,
                "required_bridge_execution": self.required_bridge_execution,
                "required_level_of_analysis": self.required_level_of_analysis,
                "required_statistical_authority": self.required_statistical_authority,
                "required_evidence_axes": self.required_evidence_axes,
                "required_context": self.required_context,
                "output_claim_floor": self.output_claim_floor,
                "registry_version": self.registry_version,
            }
        )
        if self.capability_hash is None:
            object.__setattr__(self, "capability_hash", expected_hash)
        elif self.capability_hash != expected_hash:
            raise ValueError("capability_hash does not match immutable capability content")

    @property
    def canonical_capability_hash(self) -> str:
        assert self.capability_hash is not None
        return self.capability_hash


@register_serializable_type
@dataclass(frozen=True, slots=True)
class AnalysisAuthorizationRequest:
    """Typed request proposed by a caller and adjudicated by Python."""

    request_id: InstanceIdentifier
    analysis_class: AnalysisClass
    support: StatisticalSupport | None
    support_reference: RegistryReference | None
    observations: tuple[ScientificMeasurementObservation, ...]
    identity_hashes: tuple[str, ...]
    comparability_decisions: tuple[CrossSourceComparabilityDecision, ...]
    requested_level: AnalysisLevelIdentity
    evidence_applicability: ClaimEvidenceApplicability | None
    context_references: tuple[RegistryReference, ...]
    comparability_requests: tuple[CrossSourceComparabilityRequest, ...] = ()
    bridge_requests: tuple[BridgeApplicationRequest, ...] = ()
    bridge_executions: tuple[BridgeExecutionResult, ...] = ()
    requested_parameters: tuple[MetadataEntry, ...] = ()
    reliability_authority: ReliabilityDesignAuthority | None = None
    reliability_assessment: ReliabilityAssumptionAssessment | None = None
    method_comparison_authority: MethodComparisonDesignAuthority | None = None
    scale_semantics: MeasurementScaleSemantics | None = None

    def __post_init__(self) -> None:
        _require_instance(self.request_id, InstanceIdentifier, "request_id")
        if self.request_id.instance_type != "analysis-authorization-request":
            raise ValueError("request_id must identify an analysis-authorization-request")
        _require_enum(self.analysis_class, AnalysisClass, "analysis_class")
        _require_optional_instance(self.support, StatisticalSupport, "support")
        _require_optional_instance(self.support_reference, RegistryReference, "support_reference")
        # An empty support slot is a valid request shape for a fail-closed
        # refusal: the authority, not dataclass construction, reports the
        # missing prerequisite to the caller/LM.
        _require_tuple_items(self.observations, ScientificMeasurementObservation, "observations")
        _require_string_tuple(self.identity_hashes, "identity_hashes")
        for item in self.identity_hashes:
            _require_hash(item, "identity_hashes item")
        _require_tuple_items(
            self.comparability_decisions,
            CrossSourceComparabilityDecision,
            "comparability_decisions",
        )
        _require_instance(self.requested_level, AnalysisLevelIdentity, "requested_level")
        _require_optional_instance(
            self.evidence_applicability,
            ClaimEvidenceApplicability,
            "evidence_applicability",
        )
        _require_tuple_items(self.context_references, RegistryReference, "context_references")
        _require_tuple_items(
            self.comparability_requests,
            CrossSourceComparabilityRequest,
            "comparability_requests",
        )
        _require_tuple_items(self.bridge_requests, BridgeApplicationRequest, "bridge_requests")
        _require_tuple_items(
            self.bridge_executions,
            BridgeExecutionResult,
            "bridge_executions",
        )
        _require_tuple_items(self.requested_parameters, MetadataEntry, "requested_parameters")
        _require_optional_instance(
            self.reliability_authority,
            ReliabilityDesignAuthority,
            "reliability_authority",
        )
        _require_optional_instance(
            self.reliability_assessment,
            ReliabilityAssumptionAssessment,
            "reliability_assessment",
        )
        _require_optional_instance(
            self.method_comparison_authority,
            MethodComparisonDesignAuthority,
            "method_comparison_authority",
        )
        _require_optional_instance(
            self.scale_semantics,
            MeasurementScaleSemantics,
            "scale_semantics",
        )

    @property
    def request_hash(self) -> str:
        return canonical_hash(self)

    @property
    def support_hashes(self) -> tuple[str, ...]:
        if self.support is None:
            return ()
        return (self.support.canonical_support_hash,)


@register_serializable_type
@dataclass(frozen=True, slots=True)
class AnalysisAuthorization:
    """Reproducible authorized/refused analysis-capability decision."""

    authorization_id: InstanceIdentifier
    status: AnalysisAuthorizationStatus
    request_id: InstanceIdentifier
    analysis_class: AnalysisClass
    capability_reference: RegistryReference
    capability_hash: str
    operation_reference: RegistryReference | None
    estimator_reference: RegistryReference | None
    support_hashes: tuple[str, ...]
    identity_hashes: tuple[str, ...]
    comparability_hashes: tuple[str, ...]
    statistical_authority_hashes: tuple[str, ...]
    resolved_level: AnalysisLevelIdentity
    registry_version: str
    software_version: str
    reason_codes: tuple[str, ...]
    missing_information: tuple[str, ...]
    safe_descriptions: tuple[str, ...]
    request_hash: str | None = None
    refusal_result: RefusalResult | None = None
    authorization_hash: str | None = None

    def __post_init__(self) -> None:
        _require_instance(self.authorization_id, InstanceIdentifier, "authorization_id")
        if self.authorization_id.instance_type != "analysis-authorization":
            raise ValueError("authorization_id must identify an analysis authorization")
        _require_enum(self.status, AnalysisAuthorizationStatus, "status")
        _require_instance(self.request_id, InstanceIdentifier, "request_id")
        if self.request_id.instance_type != "analysis-authorization-request":
            raise ValueError("request_id must identify an analysis authorization request")
        _require_enum(self.analysis_class, AnalysisClass, "analysis_class")
        _require_instance(self.capability_reference, RegistryReference, "capability_reference")
        _require_hash(self.capability_hash, "capability_hash")
        _require_optional_instance(
            self.operation_reference, RegistryReference, "operation_reference"
        )
        _require_optional_instance(
            self.estimator_reference, RegistryReference, "estimator_reference"
        )
        for field_name, values in (
            ("support_hashes", self.support_hashes),
            ("identity_hashes", self.identity_hashes),
            ("comparability_hashes", self.comparability_hashes),
            ("statistical_authority_hashes", self.statistical_authority_hashes),
        ):
            require_tuple(values, field_name)
            for item in values:
                _require_hash(item, f"{field_name} item")
        _require_instance(self.resolved_level, AnalysisLevelIdentity, "resolved_level")
        _require_text(self.registry_version, "registry_version")
        _require_text(self.software_version, "software_version")
        _require_string_tuple(self.reason_codes, "reason_codes")
        _require_string_tuple(self.missing_information, "missing_information")
        _require_string_tuple(self.safe_descriptions, "safe_descriptions")
        if self.request_hash is not None:
            _require_hash(self.request_hash, "request_hash")
        _require_optional_instance(self.refusal_result, RefusalResult, "refusal_result")
        if (
            self.status is AnalysisAuthorizationStatus.AUTHORIZED
            and self.refusal_result is not None
        ):
            raise ValueError("authorized analysis cannot contain a refusal result")
        if self.status is AnalysisAuthorizationStatus.REFUSED and self.refusal_result is None:
            raise ValueError("refused analysis must retain its structured refusal result")
        expected_hash = canonical_hash(
            {
                "status": self.status,
                "request_id": self.request_id,
                "analysis_class": self.analysis_class,
                "capability_reference": self.capability_reference,
                "capability_hash": self.capability_hash,
                "operation_reference": self.operation_reference,
                "estimator_reference": self.estimator_reference,
                "support_hashes": self.support_hashes,
                "identity_hashes": self.identity_hashes,
                "comparability_hashes": self.comparability_hashes,
                "statistical_authority_hashes": self.statistical_authority_hashes,
                "resolved_level": self.resolved_level,
                "registry_version": self.registry_version,
                "software_version": self.software_version,
                "reason_codes": self.reason_codes,
                "missing_information": self.missing_information,
                "safe_descriptions": self.safe_descriptions,
                "request_hash": self.request_hash,
                "refusal_result": self.refusal_result,
            }
        )
        if self.authorization_hash is None:
            object.__setattr__(self, "authorization_hash", expected_hash)
        elif self.authorization_hash != expected_hash:
            raise ValueError("authorization_hash does not match immutable authorization content")
        expected_id = InstanceIdentifier(
            "analysis-authorization", expected_hash.removeprefix(_SHA256_PREFIX)
        )
        if self.authorization_id != expected_id:
            raise ValueError("authorization_id does not match immutable authorization content")

    @classmethod
    def create(
        cls,
        *,
        status: AnalysisAuthorizationStatus,
        request_id: InstanceIdentifier,
        analysis_class: AnalysisClass,
        capability_reference: RegistryReference,
        capability_hash: str,
        operation_reference: RegistryReference | None,
        estimator_reference: RegistryReference | None,
        support_hashes: tuple[str, ...],
        identity_hashes: tuple[str, ...],
        comparability_hashes: tuple[str, ...],
        statistical_authority_hashes: tuple[str, ...],
        resolved_level: AnalysisLevelIdentity,
        registry_version: str,
        software_version: str,
        reason_codes: tuple[str, ...],
        missing_information: tuple[str, ...],
        safe_descriptions: tuple[str, ...],
        request_hash: str | None = None,
        refusal_result: RefusalResult | None = None,
    ) -> AnalysisAuthorization:
        content = {
            "status": status,
            "request_id": request_id,
            "analysis_class": analysis_class,
            "capability_reference": capability_reference,
            "capability_hash": capability_hash,
            "operation_reference": operation_reference,
            "estimator_reference": estimator_reference,
            "support_hashes": support_hashes,
            "identity_hashes": identity_hashes,
            "comparability_hashes": comparability_hashes,
            "statistical_authority_hashes": statistical_authority_hashes,
            "resolved_level": resolved_level,
            "registry_version": registry_version,
            "software_version": software_version,
            "reason_codes": reason_codes,
            "missing_information": missing_information,
            "safe_descriptions": safe_descriptions,
            "request_hash": request_hash,
            "refusal_result": refusal_result,
        }
        authorization_hash = canonical_hash(content)
        return cls(
            authorization_id=InstanceIdentifier(
                "analysis-authorization", authorization_hash.removeprefix(_SHA256_PREFIX)
            ),
            status=status,
            request_id=request_id,
            analysis_class=analysis_class,
            capability_reference=capability_reference,
            capability_hash=capability_hash,
            operation_reference=operation_reference,
            estimator_reference=estimator_reference,
            support_hashes=support_hashes,
            identity_hashes=identity_hashes,
            comparability_hashes=comparability_hashes,
            statistical_authority_hashes=statistical_authority_hashes,
            resolved_level=resolved_level,
            registry_version=registry_version,
            software_version=software_version,
            reason_codes=reason_codes,
            missing_information=missing_information,
            safe_descriptions=safe_descriptions,
            request_hash=request_hash,
            refusal_result=refusal_result,
            authorization_hash=authorization_hash,
        )

    @property
    def canonical_authorization_hash(self) -> str:
        assert self.authorization_hash is not None
        return self.authorization_hash


__all__ = [
    "AnalysisAuthorization",
    "AnalysisAuthorizationRequest",
    "AnalysisAuthorizationStatus",
    "AnalysisCapability",
    "AnalysisCapabilityDisposition",
    "AnalysisClass",
    "AnalysisEstimandLevel",
    "AnalysisKey",
    "AnalysisLevelIdentity",
    "AnalysisUnit",
    "AnalysisUnitOfAnalysis",
    "EstimandLevel",
]
