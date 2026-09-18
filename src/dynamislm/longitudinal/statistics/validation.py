"""Fail-closed validation and result/refusal factories for RES-69."""

from __future__ import annotations

from dynamislm.longitudinal.lineage import build_multi_source_provenance_graph
from dynamislm.longitudinal.record import build_multi_source_processing_run
from dynamislm.longitudinal.statistics.models import (
    MeasurementScaleSemanticKeyV1,
    MeasurementScaleSemantics,
    RES69ReasonCode,
    ScaleAuthorityOrigin,
    StatisticalAnalysisRun,
    StatisticalEstimate,
    StatisticalNonComputable,
    StatisticalResult,
    StatisticalSupport,
    StatisticalUnitReference,
)
from dynamislm.longitudinal.statistics.registry import (
    RES69_METHOD_COMPARISON_DESIGN_OPERATION,
    RES69_OPERATION_REGISTRY,
    RES69_REGISTRY_VERSION,
    RES69_SCALE_REGISTRY,
    RES69_SOFTWARE_VERSION,
)
from dynamislm.longitudinal.statistics.support import (
    StatisticalConstraintError,
    exact_common_unit,
    validate_statistical_support,
)
from dynamislm.measurement.identity import (
    InstanceIdentifier,
    MetadataEntry,
    RegistryReference,
    UnitReference,
)
from dynamislm.provenance.models import EvidenceReference
from dynamislm.refusal.models import (
    RefusalClass,
    RefusalResult,
    RefusalStatus,
)
from dynamislm.serialization import canonical_hash


def _reason_value(code: RES69ReasonCode | str) -> str:
    return code.value if isinstance(code, RES69ReasonCode) else code


def _default_refusal_class(code: str) -> RefusalClass:
    if code in {
        RES69ReasonCode.IDENTITY_UNRESOLVED.value,
    }:
        return RefusalClass.IDENTITY_UNRESOLVED
    if code in {
        RES69ReasonCode.COMPARABILITY_UNESTABLISHED.value,
        RES69ReasonCode.UNIT_MISMATCH.value,
        RES69ReasonCode.UNIT_CONVERSION_NOT_REGISTERED.value,
    }:
        return RefusalClass.COMPARABILITY_UNESTABLISHED
    if code in {
        RES69ReasonCode.RELIABILITY_AUTHORITY_REQUIRED.value,
        RES69ReasonCode.METHOD_COMPARISON_AUTHORITY_REQUIRED.value,
    }:
        return RefusalClass.EVIDENCE_SCOPE_UNSUPPORTED
    if code in {
        RES69ReasonCode.SCALE_SEMANTICS_UNREGISTERED.value,
        RES69ReasonCode.SCALE_OPERATION_NOT_AUTHORIZED.value,
        RES69ReasonCode.OPERATION_NOT_REGISTERED.value,
        RES69ReasonCode.CLASSICAL_LOA_DEFERRED.value,
    }:
        return RefusalClass.COMPUTATION_NOT_REGISTERED
    if code in {
        RES69ReasonCode.ANALYSIS_DESIGN_MISMATCH.value,
        RES69ReasonCode.SUPPORT_MISMATCH.value,
        RES69ReasonCode.INCOMPLETE_PAIR.value,
        RES69ReasonCode.UNBALANCED_RELIABILITY_SUPPORT.value,
        RES69ReasonCode.ZERO_REFERENCE_SD.value,
        RES69ReasonCode.DUPLICATE_TIMESTAMP.value,
    }:
        return RefusalClass.ANALYSIS_DESIGN_MISMATCH
    if code == RES69ReasonCode.INTERPRETATION_NOT_AUTHORIZED.value:
        return RefusalClass.UNCERTAINTY_LIMITS_CLAIM
    return RefusalClass.DATA_ADEQUACY_INSUFFICIENT


def refusal(
    blocked_claim: str,
    code: RES69ReasonCode | str,
    *,
    support: StatisticalSupport | None = None,
    missing_information: tuple[str, ...] = (),
    safe_descriptions: tuple[str, ...] = (),
    refusal_class: RefusalClass | None = None,
    evidence_references: tuple[RegistryReference, ...] = (),
    additional_reason_codes: tuple[str, ...] = (),
) -> RefusalResult:
    """Build a deterministic claim-specific refusal while retaining observations."""

    reason = _reason_value(code)
    reasons = tuple(dict.fromkeys((reason, *additional_reason_codes)))
    observation_ids = (
        support.source_observation_ids if isinstance(support, StatisticalSupport) else ()
    )
    safe = safe_descriptions or (
        "the exact source observations remain independently describable under their own identity",
    )
    normalized_missing = tuple(dict.fromkeys(missing_information))
    normalized_evidence = tuple(dict.fromkeys(evidence_references))
    payload = {
        "blocked_claim": blocked_claim,
        "reason_codes": reasons,
        "missing_information": normalized_missing,
        "observation_ids": observation_ids,
        "evidence_references": normalized_evidence,
    }
    refusal_id = InstanceIdentifier(
        "refusal",
        f"res69:{canonical_hash(payload).removeprefix('sha256:')}",
    )
    return RefusalResult(
        refusal_id=refusal_id,
        status=RefusalStatus.PARTIALLY_REFUSED if observation_ids else RefusalStatus.REFUSED,
        refusal_class=refusal_class or _default_refusal_class(reason),
        blocked_claim=blocked_claim,
        reason_codes=reasons,
        missing_information=normalized_missing,
        what_can_still_be_safely_described=safe,
        evidence_references=normalized_evidence,
        observation_ids=observation_ids,
    )


def refusal_for_exception(
    blocked_claim: str,
    exc: Exception,
    *,
    support: StatisticalSupport | None = None,
    fallback_code: RES69ReasonCode = RES69ReasonCode.DATA_ADEQUACY_INSUFFICIENT,
) -> RefusalResult:
    if isinstance(exc, StatisticalConstraintError):
        code = exc.code
        missing = exc.missing_information
    else:
        code = fallback_code.value
        missing = (str(exc),) if str(exc) else ()
    additional = (
        (RES69ReasonCode.UNIT_CONVERSION_NOT_REGISTERED.value,)
        if code == RES69ReasonCode.UNIT_MISMATCH.value
        else ()
    )
    return refusal(
        blocked_claim,
        code,
        support=support,
        missing_information=missing,
        additional_reason_codes=additional,
    )


def build_analysis_run(
    support: StatisticalSupport,
    *,
    operation: RegistryReference,
    estimator: RegistryReference,
    parameters: tuple[MetadataEntry, ...] = (),
    evidence_references: tuple[EvidenceReference, ...] = (),
    scale_semantic_key: MeasurementScaleSemanticKeyV1 | None = None,
    scale_semantics_authority: RegistryReference | None = None,
    scale_semantics_hash: str | None = None,
    authority_hashes: tuple[str, ...] = (),
    registry_version: str = RES69_REGISTRY_VERSION,
) -> StatisticalAnalysisRun:
    """Create one immutable statistical run and one RES-62 graph per input."""

    validate_statistical_support(support)
    registered = RES69_OPERATION_REGISTRY.get(operation)
    if registered is None or registered.disposition.value != "IMPLEMENTED":
        raise StatisticalConstraintError(
            "requested statistical operation is not registered as implemented",
            RES69ReasonCode.OPERATION_NOT_REGISTERED.value,
        )
    processing_runs = tuple(
        build_multi_source_processing_run(
            analysis_input,
            method=operation,
            parameters=parameters,
            software_version=RES69_SOFTWARE_VERSION,
        )
        for analysis_input in support.analysis_inputs
    )
    graphs = tuple(
        build_multi_source_provenance_graph(analysis_input, processing_run)
        for analysis_input, processing_run in zip(
            support.analysis_inputs,
            processing_runs,
            strict=True,
        )
    )
    evidence = tuple(evidence_references)
    return StatisticalAnalysisRun(
        analysis_inputs=support.analysis_inputs,
        support_id=support.canonical_support_id,
        support_hash=support.canonical_support_hash,
        operation=operation,
        estimator=estimator,
        parameters=parameters,
        software_version=RES69_SOFTWARE_VERSION,
        registry_version=registry_version,
        processing_runs=processing_runs,
        provenance_graphs=graphs,
        source_records=support.source_records,
        evidence_references=evidence,
        support=support,
        scale_semantic_key=scale_semantic_key,
        scale_semantics_authority=scale_semantics_authority,
        scale_semantics_hash=scale_semantics_hash,
        authority_hashes=authority_hashes,
    )


def make_estimate(
    *,
    estimand: RegistryReference,
    value: float,
    unit: StatisticalUnitReference,
    estimator: RegistryReference,
    parameters: tuple[MetadataEntry, ...] = (),
) -> StatisticalEstimate:
    estimate_id = InstanceIdentifier(
        "statistical-estimate",
        canonical_hash(
            {
                "estimand": estimand,
                "value": value,
                "unit": unit,
                "estimator": estimator,
                "parameters": parameters,
            }
        ).removeprefix("sha256:"),
    )
    return StatisticalEstimate(
        estimate_id=estimate_id,
        estimand=estimand,
        value=value,
        unit=unit,
        estimator=estimator,
        parameters=parameters,
    )


def make_result(
    support: StatisticalSupport,
    *,
    operation: RegistryReference,
    estimator: RegistryReference,
    estimates: tuple[StatisticalEstimate, ...],
    parameters: tuple[MetadataEntry, ...] = (),
    authority_references: tuple[RegistryReference, ...] = (),
    non_computable: tuple[StatisticalNonComputable, ...] = (),
    evidence_references: tuple[EvidenceReference, ...] = (),
    scale_semantic_key: MeasurementScaleSemanticKeyV1 | None = None,
    scale_semantics_authority: RegistryReference | None = None,
    scale_semantics_hash: str | None = None,
    authority_hashes: tuple[str, ...] = (),
    registry_version: str = RES69_REGISTRY_VERSION,
) -> StatisticalResult:
    if scale_semantic_key is None:
        try:
            unit = exact_common_unit(support.included_entries)
            scale_semantic_key = MeasurementScaleSemanticKeyV1.from_measurement_identity(
                support.included_entries[0].observation.identity,
                unit,
            )
        except (AttributeError, TypeError, ValueError):
            scale_semantic_key = None
    run = build_analysis_run(
        support,
        operation=operation,
        estimator=estimator,
        parameters=parameters,
        evidence_references=evidence_references,
        scale_semantic_key=scale_semantic_key,
        scale_semantics_authority=scale_semantics_authority,
        scale_semantics_hash=scale_semantics_hash,
        authority_hashes=authority_hashes,
        registry_version=registry_version,
    )
    return StatisticalResult(
        analysis_run=run,
        result_kind=operation,
        estimates=estimates,
        non_computable=non_computable,
        authority_references=authority_references,
    )


def resolve_scale_semantics(
    support: StatisticalSupport,
    *,
    registry: object,
) -> tuple[MeasurementScaleSemantics, MeasurementScaleSemanticKeyV1, UnitReference]:
    """Resolve registered scale semantics for the exact first observation."""

    from dynamislm.longitudinal.statistics.models import MeasurementScaleSemanticKeyV1
    from dynamislm.longitudinal.statistics.registry import MeasurementScaleRegistry

    if not isinstance(registry, MeasurementScaleRegistry):
        raise StatisticalConstraintError(
            "scale authority must be supplied through the typed RES-69 registry",
            RES69ReasonCode.SCALE_SEMANTICS_UNREGISTERED.value,
        )
    if registry is not RES69_SCALE_REGISTRY:
        raise StatisticalConstraintError(
            "public scale authority must resolve from the canonical production registry",
            RES69ReasonCode.SCALE_OPERATION_NOT_AUTHORIZED.value,
            missing_information=("canonical RES-69 production scale registry",),
        )
    unit = exact_common_unit(support.included_entries)
    identity = support.included_entries[0].observation.identity
    key = MeasurementScaleSemanticKeyV1.from_measurement_identity(identity, unit)
    try:
        semantics = registry.resolve(key)
    except ValueError as exc:
        raise StatisticalConstraintError(
            "scale registry contains conflicting authority",
            RES69ReasonCode.REGISTRY_INTEGRITY_FAILURE.value,
        ) from exc
    if semantics is None:
        raise StatisticalConstraintError(
            "measurement scale semantics are not registered for this exact semantic key",
            RES69ReasonCode.SCALE_SEMANTICS_UNREGISTERED.value,
            missing_information=(
                "registered MeasurementScaleSemantics for the exact semantic key",
            ),
        )
    if semantics.authority_origin is not ScaleAuthorityOrigin.PRODUCTION:
        raise StatisticalConstraintError(
            "synthetic scale authority cannot authorize a production statistical result",
            RES69ReasonCode.SCALE_OPERATION_NOT_AUTHORIZED.value,
            missing_information=("production scale authority for the exact semantic key",),
        )
    return semantics, key, unit


def validate_reliability_authority(
    authority: object,
    support: StatisticalSupport,
) -> None:
    from dynamislm.longitudinal.statistics.models import ReliabilityDesignAuthority

    if not isinstance(authority, ReliabilityDesignAuthority) or not authority.is_source_bound:
        raise StatisticalConstraintError(
            "source-bound ReliabilityDesignAuthority is required",
            RES69ReasonCode.RELIABILITY_AUTHORITY_REQUIRED.value,
        )
    if (
        authority.support_id != support.canonical_support_id
        or authority.support_hash != support.canonical_support_hash
    ):
        raise StatisticalConstraintError(
            "reliability authority does not match the exact statistical support",
            RES69ReasonCode.SUPPORT_MISMATCH.value,
        )
    if not authority.assumption_assessment.is_source_bound:
        raise StatisticalConstraintError(
            "source-bound ReliabilityAssumptionAssessment is required",
            RES69ReasonCode.RELIABILITY_AUTHORITY_REQUIRED.value,
        )
    if (
        authority.assumption_assessment.support_id != support.canonical_support_id
        or authority.assumption_assessment.support_hash != support.canonical_support_hash
    ):
        raise StatisticalConstraintError(
            "reliability assumption assessment does not match exact support",
            RES69ReasonCode.SUPPORT_MISMATCH.value,
        )


def validate_method_comparison_authority(
    authority: object,
    support: StatisticalSupport,
) -> None:
    from dynamislm.longitudinal.statistics.models import MethodComparisonDesignAuthority

    if not isinstance(authority, MethodComparisonDesignAuthority) or not authority.is_source_bound:
        raise StatisticalConstraintError(
            "source-bound MethodComparisonDesignAuthority is required",
            RES69ReasonCode.METHOD_COMPARISON_AUTHORITY_REQUIRED.value,
        )
    if (
        authority.support_id != support.canonical_support_id
        or authority.support_hash != support.canonical_support_hash
    ):
        raise StatisticalConstraintError(
            "method-comparison authority does not match the exact statistical support",
            RES69ReasonCode.SUPPORT_MISMATCH.value,
        )
    if authority.producing_method != RES69_METHOD_COMPARISON_DESIGN_OPERATION:
        raise StatisticalConstraintError(
            "method-comparison authority must use the registered design-normalization operation",
            RES69ReasonCode.METHOD_COMPARISON_AUTHORITY_REQUIRED.value,
        )


def validate_statistical_result(result: StatisticalResult) -> None:
    if not isinstance(result, StatisticalResult):
        raise ValueError("result must be a StatisticalResult")
    if result.canonical_result_id != InstanceIdentifier(
        "statistical-result", result.canonical_output_hash.removeprefix("sha256:")
    ):
        raise ValueError("statistical result ID does not match output hash")


__all__ = [
    "validate_method_comparison_authority",
    "validate_reliability_authority",
    "validate_statistical_result",
    "validate_statistical_support",
]
