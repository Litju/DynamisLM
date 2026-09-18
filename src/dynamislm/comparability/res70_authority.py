"""Deterministic pairwise RES-70 comparability and bridge execution authority."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace

from dynamislm.comparability import res70_registry as _res70_registry
from dynamislm.comparability.models import (
    ComparabilityDecisionSource,
    ComparabilityReasonCode,
    ComparabilityRequest,
    ComparabilityResult,
    ComparabilityState,
    TransformationRequest,
)
from dynamislm.comparability.res70_models import (
    BridgeApplicationRequest,
    BridgeAuthorityOrigin,
    BridgeExecutionResult,
    BridgeExecutionStatus,
    BridgeMode,
    BridgeRegistration,
    ClaimContext,
    ComparabilityDimension,
    CrossSourceComparabilityDecision,
    CrossSourceComparabilityRequest,
    DimensionFinding,
    DimensionFindingStatus,
    SemanticIdentityKey,
)
from dynamislm.comparability.res70_registry import (
    RES70_AFFINE_BRIDGE_OPERATION,
    RES70_COMPARABILITY_RULE_REGISTRY,
    RES70_CROSS_SOURCE_COMPARABILITY_RULE,
    RES70_SOFTWARE_VERSION,
    BridgeOperationRegistry,
    BridgeRegistry,
    ComparabilityRuleRegistry,
    canonical_registry_hash,
)
from dynamislm.comparability.res70_validation import (
    RES70ValidationError,
    build_res70_refusal,
    validate_bridge_execution,
    validate_bridge_registry,
    validate_cross_source_request,
)
from dynamislm.football.models import (
    FootballWorldContext,
    MatchSession,
    TestingSession,
    TrainingSession,
)
from dynamislm.football.validation import validate_football_world_context
from dynamislm.measurement.identity import (
    InstanceIdentifier,
    MetadataEntry,
    RegistryReference,
)
from dynamislm.measurement.observation import ScientificMeasurementObservation
from dynamislm.measurement.result import ScalarValue
from dynamislm.measurement.taxonomy import ScientificClassification, ValueOrigin
from dynamislm.provenance.models import (
    EvidenceReference,
    LineageEdge,
    LineageRelation,
    ProcessingRun,
    Provenance,
)
from dynamislm.refusal.models import RefusalClass, RefusalResult
from dynamislm.serialization import canonical_hash


class ComparabilityAuthorityError(ValueError):
    """Raised when canonical RES-70 authority cannot be resolved safely."""


def _canonical_value(value: object) -> str | None:
    return None if value is None else canonical_hash(value)


def _metadata_text(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return canonical_hash(value)


def _football_context_signature(context: FootballWorldContext) -> str:
    validate_football_world_context(context)
    session = context.session
    session_kind = type(session).__name__
    session_details: tuple[tuple[str, object], ...] = ()
    if isinstance(session, MatchSession):
        session_details = (
            ("competition_kind", session.competition_context.competition_kind.value),
            ("venue_role", session.venue_role.value),
        )
    elif isinstance(session, TrainingSession):
        session_details = (
            ("training_type", session.training_type.stable_id if session.training_type else None),
        )
    elif isinstance(session, TestingSession):
        session_details = (
            ("test_type", session.test_type.stable_id if session.test_type else None),
        )
    exposure = context.exposure
    exposure_signature = (
        (
            type(exposure).__name__,
            exposure.participation_state.value,
            exposure.observed_duration_seconds,
        )
        if exposure is not None
        else None
    )
    return canonical_hash(
        {
            "session_kind": session_kind,
            "session_details": session_details,
            "exposure": exposure_signature,
            "microcycle_present": context.microcycle_context is not None,
        }
    )


def _context_candidates(
    observation: ScientificMeasurementObservation,
    football_contexts: Mapping[object, object] | Sequence[object] | None,
) -> tuple[FootballWorldContext, ...]:
    if football_contexts is None:
        return ()
    values = (
        tuple(football_contexts.values())
        if isinstance(football_contexts, Mapping)
        else tuple(football_contexts)
    )
    candidates: list[FootballWorldContext] = []
    for value in values:
        if not isinstance(value, FootballWorldContext):
            raise ComparabilityAuthorityError(
                "football context resolver must contain typed FootballWorldContext values"
            )
        if value.observation_context_id == observation.context.context_id or (
            value.athlete.athlete_id == observation.context.athlete_id
            and value.session.session_id == observation.context.session_id
        ):
            if value not in candidates:
                candidates.append(value)
    return tuple(candidates)


def _context_for_observation(
    observation: ScientificMeasurementObservation,
    football_contexts: Mapping[object, object] | Sequence[object] | None,
) -> FootballWorldContext | None:
    candidates = _context_candidates(observation, football_contexts)
    if len(candidates) != 1:
        return None
    return candidates[0]


def _dimension_values(
    observation: ScientificMeasurementObservation,
    *,
    claim_context: ClaimContext | None,
    football_context: FootballWorldContext | None,
) -> dict[ComparabilityDimension, str | None]:
    identity = observation.identity
    semantic = identity.semantic
    acquisition = identity.acquisition
    processing = identity.processing
    version = identity.version
    context = observation.context
    result = observation.result
    parameters = {item.key: item.value for item in processing.method_parameters}
    requested_world_context = (
        claim_context.football_world_context if claim_context is not None else None
    )
    exposure_value = (
        _football_context_signature(football_context)
        if football_context is not None and requested_world_context is not None
        else None
    )
    return {
        ComparabilityDimension.CONSTRUCT: semantic.construct.stable_id,
        ComparabilityDimension.TEST_FAMILY: semantic.test_family.stable_id,
        ComparabilityDimension.MEASURAND: semantic.measurand.stable_id,
        ComparabilityDimension.METRIC_DEFINITION: semantic.metric_definition.stable_id,
        ComparabilityDimension.PROTOCOL: (
            semantic.protocol.stable_id if semantic.protocol is not None else None
        ),
        ComparabilityDimension.EVENT_DEFINITION: _canonical_value(processing.event_definitions),
        ComparabilityDimension.PHASE_DEFINITION: _canonical_value(processing.phase_definitions),
        ComparabilityDimension.UNIT: _canonical_value(result.unit or processing.unit),
        ComparabilityDimension.NORMALIZATION: _canonical_value(processing.normalization),
        ComparabilityDimension.ESTIMATOR: (
            processing.estimator.stable_id if processing.estimator is not None else None
        ),
        ComparabilityDimension.REGISTERED_PROCESSING_OPERATION: (
            processing.registered_operation.stable_id
            if processing.registered_operation is not None
            else None
        ),
        ComparabilityDimension.PROCESSING_PARAMETERS: _canonical_value(
            processing.method_parameters
        ),
        ComparabilityDimension.FILTERING_SMOOTHING_RESAMPLING: _canonical_value(
            processing.filtering
        ),
        ComparabilityDimension.SAMPLING_AND_TIMEBASE: _canonical_value(acquisition.sampling),
        ComparabilityDimension.CALIBRATION_REFERENCE: (
            acquisition.calibration_reference.stable_id
            if acquisition.calibration_reference is not None
            else None
        ),
        ComparabilityDimension.DEVICE_MEASURING_SYSTEM: (
            acquisition.device.stable_id if acquisition.device is not None else None
        ),
        ComparabilityDimension.PROVIDER: _metadata_text(parameters.get("provider")),
        ComparabilityDimension.SOFTWARE_ALGORITHM_VERSION: version.software_version,
        ComparabilityDimension.HARDWARE_FIRMWARE_VERSION: (
            version.hardware_firmware.stable_id if version.hardware_firmware is not None else None
        ),
        ComparabilityDimension.SIGN_CONVENTION_AND_REFERENCE_FRAME: _canonical_value(
            processing.sign_convention
        ),
        ComparabilityDimension.THRESHOLD_IDENTITY: _canonical_value(
            tuple(item for item in processing.method_parameters if "threshold" in item.key.lower())
        ),
        ComparabilityDimension.TRIAL_SELECTION_POLICY: (
            processing.trial_selection.stable_id if processing.trial_selection is not None else None
        ),
        ComparabilityDimension.AGGREGATION_POLICY: (
            processing.aggregation.stable_id if processing.aggregation is not None else None
        ),
        ComparabilityDimension.SESSION_SEGMENTATION: _metadata_text(
            parameters.get("session_segmentation")
        ),
        ComparabilityDimension.ACQUISITION_CONTEXT: _canonical_value(
            (context.environment, context.context_metadata)
        ),
        ComparabilityDimension.EXPOSURE_CONTEXT_MATCH_OR_TRAINING: (exposure_value),
        ComparabilityDimension.VALUE_ORIGIN: result.classification.value_origin.value,
        ComparabilityDimension.UNCERTAINTY_ERROR_MODEL: _canonical_value(result.uncertainty),
        ComparabilityDimension.POPULATION_APPLICABILITY: context.population_context,
        ComparabilityDimension.EVIDENCE_APPLICABILITY: _canonical_value(
            observation.provenance.evidence_references
        ),
        ComparabilityDimension.FOOTBALL_WORLD_CONTEXT: (
            _football_context_signature(football_context)
            if football_context is not None and requested_world_context is not None
            else None
        ),
    }


_IRRECONCILABLE_DIMENSIONS = {
    ComparabilityDimension.CONSTRUCT,
    ComparabilityDimension.TEST_FAMILY,
    ComparabilityDimension.MEASURAND,
    ComparabilityDimension.METRIC_DEFINITION,
    ComparabilityDimension.PROTOCOL,
    ComparabilityDimension.VALUE_ORIGIN,
}
_TRANSFORMATION_DIMENSIONS = {
    ComparabilityDimension.UNIT,
}
_OPTIONAL_NOT_APPLICABLE_DIMENSIONS = {
    ComparabilityDimension.NORMALIZATION,
    ComparabilityDimension.REGISTERED_PROCESSING_OPERATION,
    ComparabilityDimension.SAMPLING_AND_TIMEBASE,
    ComparabilityDimension.CALIBRATION_REFERENCE,
    ComparabilityDimension.DEVICE_MEASURING_SYSTEM,
    ComparabilityDimension.PROVIDER,
    ComparabilityDimension.HARDWARE_FIRMWARE_VERSION,
    ComparabilityDimension.SIGN_CONVENTION_AND_REFERENCE_FRAME,
    ComparabilityDimension.TRIAL_SELECTION_POLICY,
    ComparabilityDimension.AGGREGATION_POLICY,
    ComparabilityDimension.SESSION_SEGMENTATION,
}


def _reason_for_dimension(dimension: ComparabilityDimension) -> str:
    mapping = {
        ComparabilityDimension.METRIC_DEFINITION: (
            ComparabilityReasonCode.METRIC_DEFINITION_MISMATCH
        ),
        ComparabilityDimension.MEASURAND: ComparabilityReasonCode.MEASURAND_MISMATCH,
        ComparabilityDimension.PROTOCOL: ComparabilityReasonCode.PROTOCOL_MISMATCH,
        ComparabilityDimension.DEVICE_MEASURING_SYSTEM: ComparabilityReasonCode.DEVICE_MISMATCH,
        ComparabilityDimension.UNIT: ComparabilityReasonCode.UNIT_OR_NORMALIZATION_MISMATCH,
        ComparabilityDimension.NORMALIZATION: ComparabilityReasonCode.NORMALIZATION_MISMATCH,
        ComparabilityDimension.ESTIMATOR: ComparabilityReasonCode.ESTIMATOR_MISMATCH,
        ComparabilityDimension.THRESHOLD_IDENTITY: ComparabilityReasonCode.THRESHOLD_VALUE_MISMATCH,
        ComparabilityDimension.EXPOSURE_CONTEXT_MATCH_OR_TRAINING: (
            ComparabilityReasonCode.EXPOSURE_CONTEXT_MISMATCH
        ),
        ComparabilityDimension.ACQUISITION_CONTEXT: ComparabilityReasonCode.ARRANGEMENT_MISMATCH,
        ComparabilityDimension.POPULATION_APPLICABILITY: ComparabilityReasonCode.IDENTITY_MISMATCH,
        ComparabilityDimension.VALUE_ORIGIN: ComparabilityReasonCode.VALUE_ORIGIN_MISMATCH,
    }
    return mapping.get(dimension, ComparabilityReasonCode.METHOD_MISMATCH).value


def _findings(
    left: ScientificMeasurementObservation,
    right: ScientificMeasurementObservation,
    *,
    claim_context: ClaimContext | None,
    football_contexts: Mapping[object, object] | Sequence[object] | None,
) -> tuple[DimensionFinding, ...]:
    left_context = _context_for_observation(left, football_contexts)
    right_context = _context_for_observation(right, football_contexts)
    left_values = _dimension_values(
        left,
        claim_context=claim_context,
        football_context=left_context,
    )
    right_values = _dimension_values(
        right,
        claim_context=claim_context,
        football_context=right_context,
    )
    requested_context_value = (
        _football_context_signature(claim_context.football_world_context)
        if claim_context is not None and claim_context.football_world_context is not None
        else None
    )
    findings: list[DimensionFinding] = []
    for dimension in ComparabilityDimension:
        left_value = left_values[dimension]
        right_value = right_values[dimension]
        if (
            dimension
            in {
                ComparabilityDimension.FOOTBALL_WORLD_CONTEXT,
                ComparabilityDimension.EXPOSURE_CONTEXT_MATCH_OR_TRAINING,
            }
            and claim_context is None
        ):
            status = DimensionFindingStatus.NOT_APPLICABLE
            reason_codes: tuple[str, ...] = ()
        elif (
            dimension
            in {
                ComparabilityDimension.FOOTBALL_WORLD_CONTEXT,
                ComparabilityDimension.EXPOSURE_CONTEXT_MATCH_OR_TRAINING,
            }
            and requested_context_value is not None
            and (left_value is None or right_value is None)
        ):
            status = DimensionFindingStatus.UNKNOWN
            reason_codes = ("MISSING_TYPED_CONTEXT",)
        elif (
            dimension
            in {
                ComparabilityDimension.FOOTBALL_WORLD_CONTEXT,
                ComparabilityDimension.EXPOSURE_CONTEXT_MATCH_OR_TRAINING,
            }
            and requested_context_value is not None
            and (left_value != requested_context_value or right_value != requested_context_value)
        ):
            status = DimensionFindingStatus.MISMATCH
            reason_codes = (_reason_for_dimension(dimension),)
        elif (
            left_value is None
            and right_value is None
            and dimension in _OPTIONAL_NOT_APPLICABLE_DIMENSIONS
        ):
            status = DimensionFindingStatus.NOT_APPLICABLE
            reason_codes = ()
        elif left_value is None and right_value is None:
            status = DimensionFindingStatus.UNKNOWN
            reason_codes = ("MISSING_METADATA",)
        elif left_value is None or right_value is None:
            status = DimensionFindingStatus.UNKNOWN
            reason_codes = ("MISSING_METADATA",)
        elif left_value == right_value:
            status = DimensionFindingStatus.MATCH
            reason_codes = ()
        else:
            status = DimensionFindingStatus.MISMATCH
            reason_codes = (_reason_for_dimension(dimension),)
        findings.append(
            DimensionFinding(
                dimension=dimension,
                status=status,
                left_value=left_value,
                right_value=right_value,
                reason_codes=reason_codes,
            )
        )
    return tuple(findings)


def _leaf_result(
    request: CrossSourceComparabilityRequest,
    *,
    state: ComparabilityState,
    reasons: tuple[str, ...],
    conditions: tuple[str, ...],
    transformations: tuple[TransformationRequest, ...],
    missing: tuple[str, ...],
    evidence: tuple[RegistryReference, ...],
) -> ComparabilityResult:
    leaf_request = ComparabilityRequest(
        request_id=InstanceIdentifier(
            "comparability-request",
            f"res70:{request.request_hash.removeprefix('sha256:')[:40]}",
        ),
        left_observation_id=request.left_observation.observation_id,
        right_observation_id=request.right_observation.observation_id,
        claim=request.claim_intent.stable_id,
        requested_transformations=transformations,
        material_dimensions=tuple(item.value for item in ComparabilityDimension),
    )
    return ComparabilityResult(
        result_id=InstanceIdentifier(
            "comparability-result",
            f"res70:{request.request_hash.removeprefix('sha256:')[:40]}:{state.value.lower()}",
        ),
        request_id=leaf_request.request_id,
        state=state,
        reason_codes=reasons,
        conditions=conditions,
        transformations_required=transformations,
        missing_information=missing,
        rule_reference=RES70_CROSS_SOURCE_COMPARABILITY_RULE,
        evidence_references=evidence,
        decided_by=ComparabilityDecisionSource.DETERMINISTIC_RULE,
    )


def _bridge_for_request(
    request: CrossSourceComparabilityRequest,
    left: ScientificMeasurementObservation,
    right: ScientificMeasurementObservation,
    bridge_registry: BridgeRegistry,
) -> BridgeRegistration | None:
    left_key = SemanticIdentityKey.from_identity(left.identity)
    right_key = SemanticIdentityKey.from_identity(right.identity)
    candidates = tuple(
        entry
        for entry in bridge_registry.entries
        if entry.source_semantic_key == left_key
        and entry.target_semantic_key == right_key
        and any(item.stable_id == request.claim_intent.stable_id for item in entry.claim_scope)
    )
    if len(candidates) > 1:
        raise ComparabilityAuthorityError("multiple bridges match one pairwise request")
    return candidates[0] if candidates else None


def assess_cross_source_comparability(
    request: CrossSourceComparabilityRequest,
    observations: Mapping[object, ScientificMeasurementObservation]
    | Sequence[ScientificMeasurementObservation],
    *,
    bridge_registry: BridgeRegistry | None = None,
    rule_registry: ComparabilityRuleRegistry = RES70_COMPARABILITY_RULE_REGISTRY,
    bridge_execution: BridgeExecutionResult | None = None,
    bridge_request: BridgeApplicationRequest | None = None,
    football_contexts: Mapping[object, object] | Sequence[object] | None = None,
    family_result: ComparabilityResult | None = None,
) -> CrossSourceComparabilityDecision:
    """Adjudicate one pair without label matching or transitive closure."""

    if not isinstance(request, CrossSourceComparabilityRequest):
        raise ComparabilityAuthorityError("request must be a CrossSourceComparabilityRequest")
    if bridge_registry is None:
        bridge_registry = _res70_registry.CANONICAL_BRIDGE_REGISTRY
    try:
        validate_bridge_registry(bridge_registry, require_canonical=True)
        left, right = validate_cross_source_request(request, observations)
    except RES70ValidationError as exc:
        raise ComparabilityAuthorityError(str(exc)) from exc
    if not rule_registry.contains(RES70_CROSS_SOURCE_COMPARABILITY_RULE):
        raise ComparabilityAuthorityError("RES70 comparability rule is not registered")
    if family_result is not None and family_result.state not in (
        ComparabilityState.COMPARABLE,
        ComparabilityState.COMPARABLE_WITH_CONDITIONS,
    ):
        state = family_result.state
        reasons = tuple(family_result.reason_codes)
        conditions = tuple(family_result.conditions)
        transformations = tuple(family_result.transformations_required)
        missing = tuple(family_result.missing_information)
        evidence = tuple(family_result.evidence_references)
        findings = _findings(
            left,
            right,
            claim_context=request.claim_context,
            football_contexts=football_contexts,
        )
        leaf = family_result
        return CrossSourceComparabilityDecision.create(
            request_hash=request.request_hash,
            state=state,
            dimension_findings=findings,
            conditions=conditions,
            transformations_required=transformations,
            bridge_application_reference=None,
            rule_reference=RES70_CROSS_SOURCE_COMPARABILITY_RULE,
            evidence_references=evidence,
            registry_version=rule_registry.registry_version,
            registry_hash=canonical_registry_hash(
                bridge_registry=bridge_registry,
                rule_registry=rule_registry,
            ),
            left_observation=request.left_observation,
            right_observation=request.right_observation,
            reason_codes=reasons,
            missing_information=missing,
            leaf_result=leaf,
            bridge_execution_hash=None,
        )

    effective_left = left
    effective_right = right
    bridge: BridgeRegistration | None = None
    bridge_reference: RegistryReference | None = None
    bridge_conditions: tuple[str, ...] = ()
    bridge_evidence: tuple[RegistryReference, ...] = ()
    bridge_applied = False
    if bridge_execution is not None:
        if bridge_execution.status is not BridgeExecutionStatus.EXECUTED:
            raise ComparabilityAuthorityError(
                "only executed bridge transformations may support values"
            )
        try:
            if bridge_execution.source_observation == request.left_observation:
                validate_bridge_execution(
                    bridge_execution,
                    bridge_request.request_hash
                    if bridge_request is not None
                    else bridge_execution.request_hash,
                    left,
                    bridge_registry=bridge_registry,
                    bridge_request=bridge_request,
                    target_identity=right.identity,
                )
                if bridge_execution.transformed_observation is None:
                    raise ComparabilityAuthorityError(
                        "executed bridge has no transformed observation"
                    )
                effective_left = bridge_execution.transformed_observation
            elif bridge_execution.source_observation == request.right_observation:
                validate_bridge_execution(
                    bridge_execution,
                    bridge_request.request_hash
                    if bridge_request is not None
                    else bridge_execution.request_hash,
                    right,
                    bridge_registry=bridge_registry,
                    bridge_request=bridge_request,
                    target_identity=left.identity,
                )
                if bridge_execution.transformed_observation is None:
                    raise ComparabilityAuthorityError(
                        "executed bridge has no transformed observation"
                    )
                effective_right = bridge_execution.transformed_observation
            else:
                raise ComparabilityAuthorityError("bridge execution is not bound to this pair")
        except RES70ValidationError as exc:
            raise ComparabilityAuthorityError(str(exc)) from exc
        bridge = bridge_registry.resolve(bridge_execution.bridge_reference)
        if bridge is None:
            raise ComparabilityAuthorityError("bridge execution references an unregistered bridge")
        bridge_reference = bridge.bridge_reference
        bridge_conditions = ("registered transformation executed",)
        bridge_evidence = bridge.evidence_references
        bridge_applied = True

    findings = _findings(
        effective_left,
        effective_right,
        claim_context=request.claim_context,
        football_contexts=football_contexts,
    )
    unknown = tuple(
        finding for finding in findings if finding.status is DimensionFindingStatus.UNKNOWN
    )
    mismatches = tuple(
        finding for finding in findings if finding.status is DimensionFindingStatus.MISMATCH
    )
    reasons = tuple(
        dict.fromkeys(reason for finding in mismatches for reason in finding.reason_codes)
    )
    missing = tuple(
        f"{finding.dimension.value.lower()} identity or applicability metadata"
        for finding in unknown
    )
    transformations = request.requested_transformations
    state = ComparabilityState.COMPARABLE
    conditions = bridge_conditions
    evidence = bridge_evidence

    if unknown:
        state = ComparabilityState.INSUFFICIENT_INFORMATION
        reasons = tuple(dict.fromkeys(("RES70_UNRESOLVED_IDENTITY", *reasons)))
    elif any(
        finding.dimension in _IRRECONCILABLE_DIMENSIONS
        and not (bridge_applied and finding.dimension is ComparabilityDimension.VALUE_ORIGIN)
        for finding in mismatches
    ):
        state = ComparabilityState.NOT_COMPARABLE
    elif any(finding.dimension in _TRANSFORMATION_DIMENSIONS for finding in mismatches):
        if not transformations:
            transformations = (
                TransformationRequest(
                    operation=RegistryReference(
                        RES70_AFFINE_BRIDGE_OPERATION.identifier,
                        RES70_AFFINE_BRIDGE_OPERATION.display_label,
                    ),
                    parameters=(),
                ),
            )
        if bridge_applied:
            state = ComparabilityState.COMPARABLE_WITH_CONDITIONS
        else:
            state = ComparabilityState.REQUIRES_TRANSFORMATION
            reasons = tuple(dict.fromkeys(("RES70_BRIDGE_NOT_EXECUTED", *reasons)))
    elif mismatches:
        if bridge is None:
            bridge = _bridge_for_request(request, left, right, bridge_registry)
        if bridge is None:
            state = ComparabilityState.BRIDGE_VALIDATION_REQUIRED
            reasons = tuple(dict.fromkeys(("RES70_BRIDGE_REQUIRED", *reasons)))
            conditions = ("a registered claim-scoped bridge",)
        elif bridge.authority_origin is not BridgeAuthorityOrigin.PRODUCTION:
            state = ComparabilityState.INSUFFICIENT_INFORMATION
            reasons = tuple(dict.fromkeys(("RES70_REGISTRY_INTEGRITY_FAILURE", *reasons)))
            missing = ("canonical production bridge registry",)
        elif bridge.bridge_mode is BridgeMode.DECLARATIVE_EQUIVALENCE:
            state = ComparabilityState.COMPARABLE_WITH_CONDITIONS
            bridge_reference = bridge.bridge_reference
            conditions = tuple(
                f"{item.key}={item.value}" for item in bridge.applicability_conditions
            )
            evidence = bridge.evidence_references
            for index, finding in enumerate(findings):
                if finding.status is DimensionFindingStatus.MISMATCH:
                    findings = (
                        *findings[:index],
                        replace(finding, status=DimensionFindingStatus.BRIDGED),
                        *findings[index + 1 :],
                    )
        elif bridge_applied:
            state = ComparabilityState.COMPARABLE_WITH_CONDITIONS
            bridge_reference = bridge.bridge_reference
            evidence = bridge.evidence_references
        else:
            state = ComparabilityState.REQUIRES_TRANSFORMATION
            bridge_reference = bridge.bridge_reference
            conditions = ("registered numerical transformation must be executed",)
            reasons = tuple(dict.fromkeys(("RES70_BRIDGE_NOT_EXECUTED", *reasons)))
            if bridge.transformation_operation is not None and not transformations:
                transformations = (
                    TransformationRequest(bridge.transformation_operation, bridge.fixed_parameters),
                )
    elif bridge_applied:
        state = ComparabilityState.COMPARABLE_WITH_CONDITIONS
    else:
        state = ComparabilityState.COMPARABLE

    leaf = _leaf_result(
        request,
        state=state,
        reasons=reasons,
        conditions=conditions,
        transformations=transformations,
        missing=missing,
        evidence=evidence,
    )
    return CrossSourceComparabilityDecision.create(
        request_hash=request.request_hash,
        state=state,
        dimension_findings=findings,
        conditions=conditions,
        transformations_required=transformations,
        bridge_application_reference=bridge_reference,
        rule_reference=RES70_CROSS_SOURCE_COMPARABILITY_RULE,
        evidence_references=evidence,
        registry_version=rule_registry.registry_version,
        registry_hash=canonical_registry_hash(
            bridge_registry=bridge_registry,
            rule_registry=rule_registry,
        ),
        left_observation=request.left_observation,
        right_observation=request.right_observation,
        reason_codes=reasons,
        missing_information=missing,
        leaf_result=leaf,
        bridge_execution_hash=(
            bridge_execution.canonical_execution_hash
            if bridge_applied and bridge_execution is not None
            else None
        ),
    )


def _domain_allows(
    value: float,
    constraints: tuple[MetadataEntry, ...],
) -> bool:
    values = {item.key: item.value for item in constraints}
    minimum = values.get("min")
    maximum = values.get("max")
    if minimum is not None and (isinstance(minimum, bool) or not isinstance(minimum, int | float)):
        raise ValueError("bridge min domain constraint must be numeric")
    if maximum is not None and (isinstance(maximum, bool) or not isinstance(maximum, int | float)):
        raise ValueError("bridge max domain constraint must be numeric")
    return not (
        (minimum is not None and value < float(minimum))
        or (maximum is not None and value > float(maximum))
    )


def _make_bridge_provenance(
    source: ScientificMeasurementObservation,
    processing_run: ProcessingRun,
    bridge: BridgeRegistration,
) -> Provenance:
    evidence = tuple(
        dict.fromkeys(
            (
                *source.provenance.evidence_references,
                *(EvidenceReference(item) for item in bridge.evidence_references),
            )
        )
    )
    edges = (
        *source.provenance.lineage_edges,
        LineageEdge(
            source.observation_id.qualified,
            processing_run.processing_run_id.qualified,
            LineageRelation.DERIVED_FROM,
        ),
        LineageEdge(
            processing_run.processing_run_id.qualified,
            processing_run.output_entity_id.qualified,
            LineageRelation.PRODUCED,
        ),
    )
    return Provenance(
        provenance_id=InstanceIdentifier("provenance", processing_run.output_entity_id.value),
        source_artifacts=source.provenance.source_artifacts,
        acquisitions=source.provenance.acquisitions,
        processing_runs=(*source.provenance.processing_runs, processing_run),
        lineage_edges=edges,
        evidence_references=evidence,
        metrological_traceability=source.provenance.metrological_traceability,
        recorded_at=source.provenance.recorded_at,
    )


def execute_registered_bridge(
    request: BridgeApplicationRequest,
    source_observation: ScientificMeasurementObservation,
    *,
    bridge_registry: BridgeRegistry | None = None,
    operation_registry: BridgeOperationRegistry | None = None,
) -> BridgeExecutionResult | RefusalResult:
    """Resolve the canonical bridge and execute it without caller authority."""

    observation_id = source_observation.observation_id
    if bridge_registry is None:
        bridge_registry = _res70_registry.CANONICAL_BRIDGE_REGISTRY
    if operation_registry is None:
        operation_registry = _res70_registry.CANONICAL_BRIDGE_OPERATION_REGISTRY
    try:
        request.source_observation.validate_observation(source_observation)
    except ValueError as exc:
        return build_res70_refusal(
            "registered bridge execution",
            "RES70_UNRESOLVED_IDENTITY",
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
            missing_information=(str(exc),),
            observation_ids=(observation_id,),
        )
    try:
        validate_bridge_registry(bridge_registry, require_canonical=True)
    except RES70ValidationError as exc:
        return build_res70_refusal(
            "registered bridge execution",
            "RES70_REGISTRY_INTEGRITY_FAILURE",
            refusal_class=RefusalClass.COMPUTATION_NOT_REGISTERED,
            missing_information=(str(exc),),
            observation_ids=(observation_id,),
        )
    if operation_registry is not _res70_registry.CANONICAL_BRIDGE_OPERATION_REGISTRY:
        return build_res70_refusal(
            "registered bridge execution",
            "RES70_REGISTRY_INTEGRITY_FAILURE",
            refusal_class=RefusalClass.COMPUTATION_NOT_REGISTERED,
            missing_information=("canonical production bridge operation registry",),
            observation_ids=(observation_id,),
        )
    bridge = bridge_registry.resolve(request.bridge_reference)
    if bridge is None:
        return build_res70_refusal(
            "registered bridge execution",
            "RES70_BRIDGE_REQUIRED",
            refusal_class=RefusalClass.COMPARABILITY_UNESTABLISHED,
            missing_information=("canonical registered bridge declaration",),
            observation_ids=(observation_id,),
        )
    if bridge.authority_origin is not BridgeAuthorityOrigin.PRODUCTION:
        return build_res70_refusal(
            "registered bridge execution",
            "RES70_REGISTRY_INTEGRITY_FAILURE",
            refusal_class=RefusalClass.COMPUTATION_NOT_REGISTERED,
            missing_information=("production bridge authority",),
            observation_ids=(observation_id,),
        )
    if not any(item.stable_id == request.claim_intent.stable_id for item in bridge.claim_scope):
        return build_res70_refusal(
            "registered bridge execution",
            "RES70_BRIDGE_CONDITIONS_UNSATISFIED",
            refusal_class=RefusalClass.COMPARABILITY_UNESTABLISHED,
            missing_information=("bridge applicability for the requested claim",),
            observation_ids=(observation_id,),
        )
    if SemanticIdentityKey.from_identity(source_observation.identity) != bridge.source_semantic_key:
        return build_res70_refusal(
            "registered bridge execution",
            "RES70_UNRESOLVED_IDENTITY",
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
            missing_information=("exact bridge source semantic identity",),
            observation_ids=(observation_id,),
        )
    if request.requested_parameters and request.requested_parameters != bridge.fixed_parameters:
        return build_res70_refusal(
            "registered bridge execution",
            "RES70_REGISTRY_INTEGRITY_FAILURE",
            refusal_class=RefusalClass.COMPUTATION_NOT_REGISTERED,
            missing_information=("caller parameters cannot replace registered bridge parameters",),
            observation_ids=(observation_id,),
        )
    if bridge.bridge_mode is BridgeMode.DECLARATIVE_EQUIVALENCE:
        execution_content = {
            "request_hash": request.request_hash,
            "bridge_reference": bridge.bridge_reference,
            "bridge_hash": bridge.canonical_bridge_hash,
            "source_observation": request.source_observation,
            "transformed_observation": None,
            "processing_run": None,
            "provenance": None,
            "output_observation_hash": None,
            "uncertainty_model": bridge.uncertainty_model,
            "lossiness_description": bridge.lossiness_description,
            "method_version": bridge.method_version,
            "provenance_rule": bridge.provenance_rule,
            "status": BridgeExecutionStatus.DECLARATIVE_APPLIED,
        }
        execution_hash = canonical_hash(execution_content)
        result = BridgeExecutionResult(
            execution_id=InstanceIdentifier(
                "bridge-execution", execution_hash.removeprefix("sha256:")
            ),
            status=BridgeExecutionStatus.DECLARATIVE_APPLIED,
            request_hash=request.request_hash,
            bridge_reference=bridge.bridge_reference,
            bridge_hash=bridge.canonical_bridge_hash,
            source_observation=request.source_observation,
            transformed_observation=None,
            processing_run=None,
            provenance=None,
            output_observation_hash=None,
            uncertainty_model=bridge.uncertainty_model,
            lossiness_description=bridge.lossiness_description,
            execution_hash=execution_hash,
            method_version=bridge.method_version,
            provenance_rule=bridge.provenance_rule,
        )
        return result
    if request.target_identity is None:
        return build_res70_refusal(
            "registered numerical bridge execution",
            "RES70_BRIDGE_EXECUTION_FAILED",
            refusal_class=RefusalClass.DATA_ADEQUACY_INSUFFICIENT,
            missing_information=("exact target measurement identity",),
            observation_ids=(observation_id,),
        )
    if SemanticIdentityKey.from_identity(request.target_identity) != bridge.target_semantic_key:
        return build_res70_refusal(
            "registered numerical bridge execution",
            "RES70_UNRESOLVED_IDENTITY",
            refusal_class=RefusalClass.IDENTITY_UNRESOLVED,
            missing_information=("exact bridge target semantic identity",),
            observation_ids=(observation_id,),
        )
    if bridge.transformation_operation is None:
        return build_res70_refusal(
            "registered numerical bridge execution",
            "COMPUTATION_NOT_REGISTERED",
            refusal_class=RefusalClass.COMPUTATION_NOT_REGISTERED,
            missing_information=("registered deterministic bridge operation",),
            observation_ids=(observation_id,),
        )
    operation = operation_registry.resolve(bridge.transformation_operation)
    if operation is None:
        return build_res70_refusal(
            "registered numerical bridge execution",
            "COMPUTATION_NOT_REGISTERED",
            refusal_class=RefusalClass.COMPUTATION_NOT_REGISTERED,
            missing_information=("canonical bridge operation implementation",),
            observation_ids=(observation_id,),
        )
    if (
        not isinstance(source_observation.result.value, ScalarValue)
        or isinstance(source_observation.result.value.value, bool)
        or not isinstance(source_observation.result.value.value, int | float)
    ):
        return build_res70_refusal(
            "registered numerical bridge execution",
            "RES70_BRIDGE_EXECUTION_FAILED",
            refusal_class=RefusalClass.DATA_ADEQUACY_INSUFFICIENT,
            missing_information=("finite numeric scalar source result",),
            observation_ids=(observation_id,),
        )
    value = float(source_observation.result.value.value)
    try:
        if not _domain_allows(value, bridge.domain_constraints):
            raise ValueError("source value is outside the registered bridge domain")
        transformed_value = operation.execute(value, bridge.fixed_parameters)
        if not _domain_allows(transformed_value, bridge.domain_constraints):
            raise ValueError("transformed value is outside the registered bridge domain")
    except (TypeError, ValueError) as exc:
        return build_res70_refusal(
            "registered numerical bridge execution",
            "RES70_BRIDGE_EXECUTION_FAILED",
            refusal_class=RefusalClass.DATA_ADEQUACY_INSUFFICIENT,
            missing_information=(str(exc),),
            observation_ids=(observation_id,),
        )
    output_payload = {
        "source_observation": request.source_observation,
        "bridge_reference": bridge.bridge_reference,
        "bridge_hash": bridge.canonical_bridge_hash,
        "target_identity": request.target_identity,
        "value": transformed_value,
        "operation": bridge.transformation_operation,
        "parameters": bridge.fixed_parameters,
        "software_version": RES70_SOFTWARE_VERSION,
    }
    digest = canonical_hash(output_payload).removeprefix("sha256:")
    output_observation_id = InstanceIdentifier("observation", f"bridge:{digest}")
    output_result = replace(
        source_observation.result,
        result_id=InstanceIdentifier("result", f"bridge:{digest}"),
        value=ScalarValue(transformed_value),
        unit=request.target_identity.processing.unit or source_observation.result.unit,
        classification=ScientificClassification(
            ValueOrigin.DYNAMISLM_DERIVED,
            source_observation.result.classification.scientific_roles,
        ),
    )
    processing_run = ProcessingRun(
        processing_run_id=InstanceIdentifier("processing-run", f"bridge:{digest}"),
        source_artifact_ids=tuple(
            item.artifact_id for item in source_observation.provenance.source_artifacts
        ),
        method=bridge.transformation_operation,
        parameters=bridge.fixed_parameters,
        software_version=RES70_SOFTWARE_VERSION,
        output_entity_id=output_observation_id,
    )
    provenance = _make_bridge_provenance(source_observation, processing_run, bridge)
    transformed = ScientificMeasurementObservation(
        observation_id=output_observation_id,
        context=source_observation.context,
        identity=request.target_identity,
        result=output_result,
        provenance=provenance,
    )
    execution_content = {
        "request_hash": request.request_hash,
        "bridge_reference": bridge.bridge_reference,
        "bridge_hash": bridge.canonical_bridge_hash,
        "source_observation": request.source_observation,
        "transformed_observation": transformed,
        "processing_run": processing_run,
        "provenance": provenance,
        "output_observation_hash": canonical_hash(transformed),
        "uncertainty_model": bridge.uncertainty_model,
        "lossiness_description": bridge.lossiness_description,
        "method_version": bridge.method_version,
        "provenance_rule": bridge.provenance_rule,
        "status": BridgeExecutionStatus.EXECUTED,
    }
    execution_hash = canonical_hash(execution_content)
    result = BridgeExecutionResult(
        execution_id=InstanceIdentifier("bridge-execution", execution_hash.removeprefix("sha256:")),
        status=BridgeExecutionStatus.EXECUTED,
        request_hash=request.request_hash,
        bridge_reference=bridge.bridge_reference,
        bridge_hash=bridge.canonical_bridge_hash,
        source_observation=request.source_observation,
        transformed_observation=transformed,
        processing_run=processing_run,
        provenance=provenance,
        output_observation_hash=canonical_hash(transformed),
        uncertainty_model=bridge.uncertainty_model,
        lossiness_description=bridge.lossiness_description,
        execution_hash=execution_hash,
        method_version=bridge.method_version,
        provenance_rule=bridge.provenance_rule,
    )
    try:
        validate_bridge_execution(
            result,
            request.request_hash,
            source_observation,
            bridge_registry=bridge_registry,
            operation_registry=operation_registry,
            bridge_request=request,
            target_identity=request.target_identity,
        )
    except RES70ValidationError as exc:
        return build_res70_refusal(
            "registered numerical bridge execution",
            "RES70_BRIDGE_EXECUTION_FAILED",
            refusal_class=RefusalClass.COMPUTATION_NOT_REGISTERED,
            missing_information=(str(exc),),
            observation_ids=(observation_id,),
        )
    return result


__all__ = [
    "ComparabilityAuthorityError",
    "assess_cross_source_comparability",
    "execute_registered_bridge",
]
