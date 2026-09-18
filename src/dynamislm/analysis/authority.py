"""Deterministic RES-70 analysis-capability authorization."""

from __future__ import annotations

from dynamislm.analysis.models import (
    AnalysisAuthorization,
    AnalysisAuthorizationRequest,
    AnalysisAuthorizationStatus,
    AnalysisCapability,
)
from dynamislm.analysis.registry import (
    CANONICAL_ANALYSIS_CAPABILITY_REGISTRY,
    AnalysisCapabilityRegistry,
)
from dynamislm.analysis.validation import (
    AnalysisValidationError,
    validate_analysis_capability_registry,
    validate_comparability_authority,
    validate_evidence_applicability,
    validate_exact_support,
    validate_level_of_analysis,
    validate_observation_hashes,
    validate_support_shape,
)
from dynamislm.comparability.res70_validation import build_res70_refusal
from dynamislm.longitudinal.statistics.models import StatisticalOperationDisposition
from dynamislm.longitudinal.statistics.registry import (
    RES69_OPERATION_REGISTRY,
    RES69_SCALE_REGISTRY,
    RES69_SCALE_SEMANTICS_AUTHORITY,
)
from dynamislm.longitudinal.statistics.validation import (
    resolve_scale_semantics,
    validate_method_comparison_authority,
    validate_reliability_authority,
)
from dynamislm.refusal.models import RefusalClass, RefusalResult
from dynamislm.serialization import canonical_hash


def _refusal_class(code: str) -> RefusalClass:
    if code in {
        "RES70_COMPARABILITY_AUTHORITY_MISSING",
        "RES70_BRIDGE_NOT_EXECUTED",
        "RES70_BRIDGE_REQUIRED",
    }:
        return RefusalClass.COMPARABILITY_UNESTABLISHED
    if code in {
        "RES70_INSUFFICIENT_EVIDENCE_APPLICABILITY",
        "RES70_APPLICABILITY_AXIS_UNASSESSED",
    }:
        return RefusalClass.EVIDENCE_SCOPE_UNSUPPORTED
    if code in {
        "RES70_WRONG_LEVEL_OF_ANALYSIS",
        "RES70_PSEUDOREPLICATION_RISK",
    }:
        return RefusalClass.ANALYSIS_DESIGN_MISMATCH
    if code in {"RES70_REGISTRY_INTEGRITY_FAILURE", "COMPUTATION_NOT_REGISTERED"}:
        return RefusalClass.COMPUTATION_NOT_REGISTERED
    return RefusalClass.DATA_ADEQUACY_INSUFFICIENT


def _refuse(
    request: AnalysisAuthorizationRequest,
    code: str,
    message: str,
    *,
    missing_information: tuple[str, ...] = (),
) -> RefusalResult:
    support = request.support
    observation_ids = support.source_observation_ids if support is not None else ()
    return build_res70_refusal(
        f"analysis:{request.analysis_class.value}",
        code,
        refusal_class=_refusal_class(code),
        missing_information=missing_information or (message,),
        safe_descriptions=(
            "the exact source observations remain independently describable under their own "
            "identity",
        ),
        observation_ids=observation_ids,
    )


def _operation_check(capability: AnalysisCapability) -> None:
    operation = capability.registered_operation_reference
    if operation is None:
        raise AnalysisValidationError(
            "analysis capability has no registered RES-69 operation",
            "COMPUTATION_NOT_REGISTERED",
            ("registered deterministic operation",),
        )
    registered = RES69_OPERATION_REGISTRY.get(operation)
    if (
        registered is None
        or registered.disposition is not StatisticalOperationDisposition.IMPLEMENTED
    ):
        raise AnalysisValidationError(
            "requested analysis operation is deferred, represented-only, rejected, or absent",
            "COMPUTATION_NOT_REGISTERED",
            (operation.stable_id,),
        )


def _statistical_authority_check(
    request: AnalysisAuthorizationRequest,
    capability: AnalysisCapability,
    support: object,
) -> tuple[str, ...]:
    from dynamislm.longitudinal.statistics.models import StatisticalSupport

    if not isinstance(support, StatisticalSupport):
        raise AnalysisValidationError(
            "exact StatisticalSupport is required",
            "RES70_STATISTICAL_AUTHORITY_INSUFFICIENT",
        )
    hashes: list[str] = []
    if request.reliability_authority is not None:
        hashes.append(canonical_hash(request.reliability_authority))
    if request.reliability_assessment is not None:
        hashes.append(canonical_hash(request.reliability_assessment))
    if request.method_comparison_authority is not None:
        hashes.append(canonical_hash(request.method_comparison_authority))
    if request.scale_semantics is not None:
        hashes.append(canonical_hash(request.scale_semantics))
    required = {item.stable_id for item in capability.required_statistical_authority}
    if any("reliability-design" in item for item in required):
        if request.reliability_authority is None:
            raise AnalysisValidationError(
                "source-bound reliability design authority is required",
                "RES70_STATISTICAL_AUTHORITY_INSUFFICIENT",
                ("source-bound ReliabilityDesignAuthority",),
            )
        try:
            validate_reliability_authority(request.reliability_authority, support)
        except (TypeError, ValueError) as exc:
            raise AnalysisValidationError(
                str(exc),
                "RES70_STATISTICAL_AUTHORITY_INSUFFICIENT",
            ) from exc
    if any("method-comparison-design" in item for item in required):
        if request.method_comparison_authority is None:
            raise AnalysisValidationError(
                "source-bound method-comparison authority is required",
                "RES70_STATISTICAL_AUTHORITY_INSUFFICIENT",
                ("source-bound MethodComparisonDesignAuthority",),
            )
        try:
            validate_method_comparison_authority(request.method_comparison_authority, support)
        except (TypeError, ValueError) as exc:
            raise AnalysisValidationError(
                str(exc),
                "RES70_STATISTICAL_AUTHORITY_INSUFFICIENT",
            ) from exc
    if any(
        item.stable_id == RES69_SCALE_SEMANTICS_AUTHORITY.stable_id
        for item in capability.required_statistical_authority
    ):
        try:
            resolve_scale_semantics(support, registry=RES69_SCALE_REGISTRY)
        except (TypeError, ValueError) as exc:
            raise AnalysisValidationError(
                str(exc),
                "RES70_STATISTICAL_AUTHORITY_INSUFFICIENT",
                ("canonical production RES-69 scale authority",),
            ) from exc
    return tuple(dict.fromkeys(hashes))


def authorize_analysis(
    request: AnalysisAuthorizationRequest,
    *,
    registry: AnalysisCapabilityRegistry = CANONICAL_ANALYSIS_CAPABILITY_REGISTRY,
) -> AnalysisAuthorization | RefusalResult:
    """Authorize only registered admissible analysis requests."""

    try:
        validate_analysis_capability_registry(registry)
        capability = registry.resolve(request.analysis_class)
        if capability is None:
            raise AnalysisValidationError(
                "analysis class is not present in the canonical capability registry",
                "COMPUTATION_NOT_REGISTERED",
                (request.analysis_class.value,),
            )
        _operation_check(capability)
        support = validate_exact_support(request)
        identity_hashes = validate_observation_hashes(request, support)
        validate_level_of_analysis(request, capability, support)
        validate_support_shape(request, capability, support)
        comparability_hashes = validate_comparability_authority(request, capability, support)
        validate_evidence_applicability(request, capability)
        statistical_authority_hashes = _statistical_authority_check(
            request,
            capability,
            support,
        )
    except AnalysisValidationError as exc:
        return _refuse(
            request,
            exc.code,
            str(exc),
            missing_information=exc.missing_information,
        )

    operation = capability.registered_operation_reference
    estimator = capability.estimator_reference
    assert operation is not None
    return AnalysisAuthorization.create(
        status=AnalysisAuthorizationStatus.AUTHORIZED,
        request_id=request.request_id,
        analysis_class=request.analysis_class,
        capability_reference=capability.capability_reference,
        capability_hash=capability.canonical_capability_hash,
        operation_reference=operation,
        estimator_reference=estimator,
        support_hashes=(support.canonical_support_hash,),
        identity_hashes=identity_hashes,
        comparability_hashes=comparability_hashes,
        statistical_authority_hashes=statistical_authority_hashes,
        resolved_level=request.requested_level,
        registry_version=registry.registry_version,
        software_version="dynamislm-res70-1.0.0",
        reason_codes=(),
        missing_information=(),
        safe_descriptions=(
            "the registered analysis capability is authorized at the requested level of analysis",
        ),
    )


def validate_analysis_authorization(
    authorization: AnalysisAuthorization,
    request: AnalysisAuthorizationRequest,
    *,
    registry: AnalysisCapabilityRegistry = CANONICAL_ANALYSIS_CAPABILITY_REGISTRY,
) -> None:
    if not isinstance(authorization, AnalysisAuthorization):
        raise ValueError("authorization must be an AnalysisAuthorization")
    if authorization.status is not AnalysisAuthorizationStatus.AUTHORIZED:
        raise ValueError("only authorized analysis records may pass validation")
    validate_analysis_capability_registry(registry)
    capability = registry.resolve(request.analysis_class)
    if capability is None:
        raise ValueError("analysis capability is absent from canonical registry")
    if authorization.request_id != request.request_id:
        raise ValueError("authorization request ID does not match request")
    if authorization.capability_hash != capability.canonical_capability_hash:
        raise ValueError("authorization capability hash does not match registry")
    expected_support_hashes = (
        (request.support.canonical_support_hash,) if request.support is not None else ()
    )
    if authorization.support_hashes != expected_support_hashes:
        raise ValueError("authorization support hash does not match request")


__all__ = [
    "authorize_analysis",
    "validate_analysis_authorization",
]
