"""Fail-closed validation for RES-70 comparability and bridge decisions."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from dynamislm.comparability.res70_models import (
    BridgeApplicationRequest,
    BridgeExecutionResult,
    BridgeExecutionStatus,
    BridgeRegistration,
    CrossSourceComparabilityDecision,
    CrossSourceComparabilityRequest,
    ObservationAuthorityReference,
    SemanticIdentityKey,
)
from dynamislm.comparability.res70_registry import (
    RES70_CROSS_SOURCE_COMPARABILITY_RULE,
    RES70_SOFTWARE_VERSION,
    BridgeOperationRegistry,
    BridgeRegistry,
    ComparabilityRuleRegistry,
    canonical_registry_hash,
    is_canonical_bridge_registry,
    is_canonical_operation_registry,
)
from dynamislm.measurement.identity import (
    InstanceIdentifier,
    MeasurementIdentity,
    RegistryReference,
)
from dynamislm.measurement.observation import ScientificMeasurementObservation
from dynamislm.measurement.result import ScalarValue
from dynamislm.measurement.taxonomy import ValueOrigin
from dynamislm.provenance.models import EvidenceReference
from dynamislm.refusal.models import RefusalClass, RefusalResult, RefusalStatus
from dynamislm.serialization import canonical_hash


class RES70ValidationError(ValueError):
    """Raised when a supplied RES-70 authority record is forged or inconsistent."""


def build_res70_refusal(
    blocked_claim: str,
    reason_code: str,
    *,
    refusal_class: RefusalClass,
    missing_information: tuple[str, ...] = (),
    safe_descriptions: tuple[str, ...] = (
        "the exact source observations remain independently describable under their own identity",
    ),
    evidence_references: tuple[RegistryReference, ...] = (),
    observation_ids: tuple[InstanceIdentifier, ...] = (),
) -> RefusalResult:
    """Build the repository-native refusal envelope with RES-70 provenance."""

    payload = {
        "blocked_claim": blocked_claim,
        "reason_codes": (reason_code,),
        "missing_information": missing_information,
        "safe_descriptions": safe_descriptions,
        "evidence_references": evidence_references,
        "observation_ids": observation_ids,
    }
    refusal_id = InstanceIdentifier(
        "refusal",
        f"res70:{canonical_hash(payload).removeprefix('sha256:')}",
    )
    return RefusalResult(
        refusal_id=refusal_id,
        status=RefusalStatus.PARTIALLY_REFUSED if observation_ids else RefusalStatus.REFUSED,
        refusal_class=refusal_class,
        blocked_claim=blocked_claim,
        reason_codes=(reason_code,),
        missing_information=missing_information,
        what_can_still_be_safely_described=safe_descriptions,
        evidence_references=evidence_references,
        observation_ids=observation_ids,
    )


def _observation_lookup(
    observations: Mapping[object, ScientificMeasurementObservation]
    | Sequence[ScientificMeasurementObservation],
) -> dict[str, ScientificMeasurementObservation]:
    if isinstance(observations, Mapping):
        values = tuple(observations.values())
    else:
        values = tuple(observations)
    result: dict[str, ScientificMeasurementObservation] = {}
    for observation in values:
        if not isinstance(observation, ScientificMeasurementObservation):
            raise RES70ValidationError("observations must contain typed scientific observations")
        key = observation.observation_id.qualified
        if key in result and result[key] != observation:
            raise RES70ValidationError(
                "observation resolver contains conflicting observation content"
            )
        result[key] = observation
    return result


def resolve_observation_reference(
    reference: ObservationAuthorityReference,
    observations: Mapping[object, ScientificMeasurementObservation]
    | Sequence[ScientificMeasurementObservation],
) -> ScientificMeasurementObservation:
    """Resolve and hash-check one exact observation reference."""

    lookup = _observation_lookup(observations)
    observation = lookup.get(reference.observation_id.qualified)
    if observation is None:
        raise RES70ValidationError(
            f"observation {reference.observation_id.qualified!r} is absent from the resolver"
        )
    try:
        reference.validate_observation(observation)
    except ValueError as exc:
        raise RES70ValidationError(str(exc)) from exc
    return observation


def validate_cross_source_request(
    request: CrossSourceComparabilityRequest,
    observations: Mapping[object, ScientificMeasurementObservation]
    | Sequence[ScientificMeasurementObservation],
) -> tuple[ScientificMeasurementObservation, ScientificMeasurementObservation]:
    if not isinstance(request, CrossSourceComparabilityRequest):
        raise RES70ValidationError("request must be a CrossSourceComparabilityRequest")
    left = resolve_observation_reference(request.left_observation, observations)
    right = resolve_observation_reference(request.right_observation, observations)
    if left.observation_id == right.observation_id:
        raise RES70ValidationError("cross-source request must remain pairwise")
    return left, right


def validate_bridge_registration(
    registration: BridgeRegistration,
    *,
    operation_registry: BridgeOperationRegistry | None = None,
) -> None:
    if not isinstance(registration, BridgeRegistration):
        raise RES70ValidationError("registration must be a BridgeRegistration")
    if operation_registry is not None:
        if not is_canonical_operation_registry(operation_registry):
            raise RES70ValidationError(
                "caller-supplied bridge operation registries cannot authorize a bridge"
            )
        if (
            registration.transformation_operation is not None
            and operation_registry.resolve(registration.transformation_operation) is None
        ):
            raise RES70ValidationError("bridge transformation operation is not registered")
    if registration.bridge_mode.value == "NUMERICAL_TRANSFORMATION":
        if registration.transformation_operation is None:
            raise RES70ValidationError("numerical bridge is missing its registered operation")
    elif registration.transformation_operation is not None:
        raise RES70ValidationError(
            "declarative bridge cannot carry a numerical transformation operation"
        )


def validate_bridge_registry(
    registry: BridgeRegistry,
    *,
    require_canonical: bool = True,
) -> None:
    if not isinstance(registry, BridgeRegistry):
        raise RES70ValidationError("registry must be a BridgeRegistry")
    if require_canonical and not is_canonical_bridge_registry(registry):
        raise RES70ValidationError(
            "caller-supplied bridge registries cannot authorize production bridges"
        )
    from dynamislm.comparability.res70_registry import CANONICAL_BRIDGE_OPERATION_REGISTRY

    for entry in registry.entries:
        validate_bridge_registration(entry, operation_registry=CANONICAL_BRIDGE_OPERATION_REGISTRY)
    expected = canonical_hash(
        {
            "entries": registry.entries,
            "registry_version": registry.registry_version,
            "authority_origin": registry.authority_origin,
        }
    )
    if registry.canonical_hash != expected:
        raise RES70ValidationError("bridge registry hash does not match its entries")


def validate_cross_source_decision(
    decision: CrossSourceComparabilityDecision,
    request: CrossSourceComparabilityRequest,
    *,
    bridge_registry: BridgeRegistry,
    rule_registry: ComparabilityRuleRegistry,
    observations: Mapping[object, ScientificMeasurementObservation]
    | Sequence[ScientificMeasurementObservation]
    | None = None,
    bridge_request: BridgeApplicationRequest | None = None,
    bridge_execution: BridgeExecutionResult | None = None,
    football_contexts: Mapping[object, object] | Sequence[object] | None = None,
) -> None:
    if not isinstance(decision, CrossSourceComparabilityDecision):
        raise RES70ValidationError("decision must be a CrossSourceComparabilityDecision")
    if not isinstance(request, CrossSourceComparabilityRequest):
        raise RES70ValidationError("request must be a CrossSourceComparabilityRequest")
    if decision.request_hash != request.request_hash:
        raise RES70ValidationError("decision request hash does not match request")
    if decision.left_observation != request.left_observation:
        raise RES70ValidationError("decision left observation reference was changed")
    if decision.right_observation != request.right_observation:
        raise RES70ValidationError("decision right observation reference was changed")
    if decision.registry_version != rule_registry.registry_version:
        raise RES70ValidationError("decision registry version does not match rule registry")
    if decision.registry_hash != canonical_registry_hash(
        bridge_registry=bridge_registry,
        rule_registry=rule_registry,
    ):
        raise RES70ValidationError("decision registry hash does not match canonical registries")
    if decision.rule_reference != RES70_CROSS_SOURCE_COMPARABILITY_RULE:
        raise RES70ValidationError(
            "decision must identify the registered RES-70 comparability rule"
        )
    if len({item.dimension for item in decision.dimension_findings}) != len(
        decision.dimension_findings
    ):
        raise RES70ValidationError("decision cannot contain duplicate dimension findings")
    if decision.state.value == "COMPARABLE" and decision.bridge_application_reference is not None:
        raise RES70ValidationError("direct comparability cannot carry bridge application")
    if decision.state.value == "COMPARABLE_WITH_CONDITIONS" and (
        decision.bridge_application_reference is None and not decision.conditions
    ):
        raise RES70ValidationError("conditional comparability requires conditions or a bridge")
    if decision.canonical_decision_hash != decision._content_hash():
        raise RES70ValidationError("decision hash does not match immutable decision content")
    if decision.bridge_execution_hash is not None:
        if bridge_execution is None:
            raise RES70ValidationError(
                "decision bridge execution hash cannot be verified without its execution"
            )
        if decision.bridge_execution_hash != bridge_execution.canonical_execution_hash:
            raise RES70ValidationError("decision bridge execution hash does not match execution")
    elif bridge_execution is not None:
        raise RES70ValidationError("decision is missing its supplied bridge execution binding")

    if observations is not None:
        _recompute_cross_source_decision(
            decision,
            request,
            observations,
            bridge_request=bridge_request,
            bridge_execution=bridge_execution,
            football_contexts=football_contexts,
            bridge_registry=bridge_registry,
            rule_registry=rule_registry,
        )


def validate_bridge_execution(
    result: BridgeExecutionResult,
    request_hash: str | None,
    source_observation: ScientificMeasurementObservation,
    *,
    bridge_registry: BridgeRegistry | None = None,
    operation_registry: BridgeOperationRegistry | None = None,
    bridge_request: BridgeApplicationRequest | None = None,
    target_identity: MeasurementIdentity | None = None,
) -> None:
    if not isinstance(result, BridgeExecutionResult):
        raise RES70ValidationError("result must be a BridgeExecutionResult")
    if request_hash is None:
        raise RES70ValidationError(
            "bridge execution authority requires an exact bridge request hash"
        )
    if result.request_hash != request_hash:
        raise RES70ValidationError("bridge execution request hash does not match request")
    if bridge_registry is None:
        from dynamislm.comparability.res70_registry import CANONICAL_BRIDGE_REGISTRY

        bridge_registry = CANONICAL_BRIDGE_REGISTRY
    if operation_registry is None:
        from dynamislm.comparability.res70_registry import CANONICAL_BRIDGE_OPERATION_REGISTRY

        operation_registry = CANONICAL_BRIDGE_OPERATION_REGISTRY
    validate_bridge_registry(bridge_registry, require_canonical=True)
    if not is_canonical_operation_registry(operation_registry):
        raise RES70ValidationError(
            "caller-supplied bridge operation registries cannot authorize execution"
        )
    bridge = bridge_registry.resolve(result.bridge_reference)
    if bridge is None:
        raise RES70ValidationError("bridge execution references an unregistered bridge")
    if result.bridge_hash != bridge.canonical_bridge_hash:
        raise RES70ValidationError("bridge execution hash does not match canonical registration")
    if bridge_request is not None:
        if not isinstance(bridge_request, BridgeApplicationRequest):
            raise RES70ValidationError("bridge_request must be a BridgeApplicationRequest")
        if bridge_request.request_hash != result.request_hash:
            raise RES70ValidationError("bridge execution request hash does not match exact request")
        if bridge_request.source_observation != result.source_observation:
            raise RES70ValidationError("bridge request source does not match execution")
        if bridge_request.bridge_reference != result.bridge_reference:
            raise RES70ValidationError("bridge request bridge does not match execution")
        if bridge_request.requested_parameters not in ((), bridge.fixed_parameters):
            raise RES70ValidationError(
                "bridge request parameters do not match registered fixed parameters"
            )
        target_identity = bridge_request.target_identity
    expected_source = ObservationAuthorityReference.from_observation(source_observation)
    if result.source_observation != expected_source:
        raise RES70ValidationError("bridge execution source reference does not match observation")
    if SemanticIdentityKey.from_identity(source_observation.identity) != bridge.source_semantic_key:
        raise RES70ValidationError("bridge source semantic key does not match registration")
    if result.status is not BridgeExecutionStatus.EXECUTED:
        return
    if result.transformed_observation is not None:
        if result.processing_run is None or result.provenance is None:
            raise RES70ValidationError("transformed bridge output must carry processing provenance")
        transformed = result.transformed_observation
        if SemanticIdentityKey.from_identity(transformed.identity) != bridge.target_semantic_key:
            raise RES70ValidationError("bridge target semantic key does not match registration")
        if target_identity is not None and transformed.identity != target_identity:
            raise RES70ValidationError(
                "bridge output identity does not match exact target identity"
            )
        if bridge.transformation_operation is None:
            raise RES70ValidationError("executed bridge has no registered transformation operation")
        operation = operation_registry.resolve(bridge.transformation_operation)
        if operation is None:
            raise RES70ValidationError("bridge transformation operation is not registered")
        if result.processing_run.method != bridge.transformation_operation:
            raise RES70ValidationError("processing method does not match bridge registration")
        if result.processing_run.parameters != bridge.fixed_parameters:
            raise RES70ValidationError("processing parameters do not match bridge registration")
        if result.processing_run.software_version != RES70_SOFTWARE_VERSION:
            raise RES70ValidationError("bridge processing software version is not canonical")
        if result.method_version != bridge.method_version:
            raise RES70ValidationError("bridge method version is not bound to provenance")
        if result.provenance_rule != bridge.provenance_rule:
            raise RES70ValidationError("bridge provenance rule is not bound to execution")
        expected_evidence = tuple(EvidenceReference(item) for item in bridge.evidence_references)
        if not all(item in result.provenance.evidence_references for item in expected_evidence):
            raise RES70ValidationError(
                "bridge provenance is missing registered evidence references"
            )
        if not all(
            run == result.processing_run
            for run in result.provenance.processing_runs
            if run.processing_run_id == result.processing_run.processing_run_id
        ):
            raise RES70ValidationError("bridge provenance processing run is not exact")
        if not isinstance(source_observation.result.value, ScalarValue):
            raise RES70ValidationError("executed bridge source result must be scalar")
        if not isinstance(transformed.result.value, ScalarValue):
            raise RES70ValidationError("executed bridge output result must be scalar")
        source_value = source_observation.result.value.value
        output_value = transformed.result.value.value
        if isinstance(source_value, bool) or not isinstance(source_value, int | float):
            raise RES70ValidationError("executed bridge source result must be numeric")
        if isinstance(output_value, bool) or not isinstance(output_value, int | float):
            raise RES70ValidationError("executed bridge output result must be numeric")
        expected_value = operation.execute(float(source_value), bridge.fixed_parameters)
        if float(output_value) != expected_value:
            raise RES70ValidationError(
                "bridge output value does not match deterministic re-execution"
            )
        if transformed.result.classification.value_origin is not ValueOrigin.DYNAMISLM_DERIVED:
            raise RES70ValidationError("bridge output must be classified as derived")
        if result.processing_run.output_entity_id != result.transformed_observation.observation_id:
            raise RES70ValidationError(
                "bridge processing output does not match transformed observation"
            )
        if result.output_observation_hash != canonical_hash(result.transformed_observation):
            raise RES70ValidationError("bridge output hash does not match transformed observation")


def _recompute_cross_source_decision(
    decision: CrossSourceComparabilityDecision,
    request: CrossSourceComparabilityRequest,
    observations: Mapping[object, ScientificMeasurementObservation]
    | Sequence[ScientificMeasurementObservation],
    *,
    bridge_request: BridgeApplicationRequest | None,
    bridge_execution: BridgeExecutionResult | None,
    football_contexts: Mapping[object, object] | Sequence[object] | None,
    bridge_registry: BridgeRegistry,
    rule_registry: ComparabilityRuleRegistry,
) -> None:
    left, right = validate_cross_source_request(request, observations)
    if bridge_execution is not None:
        validate_bridge_execution(
            bridge_execution,
            (
                bridge_request.request_hash
                if bridge_request is not None
                else bridge_execution.request_hash
            ),
            left if bridge_execution.source_observation == request.left_observation else right,
            bridge_registry=bridge_registry,
            bridge_request=bridge_request,
        )
    from dynamislm.comparability.res70_authority import assess_cross_source_comparability

    expected = assess_cross_source_comparability(
        request,
        observations,
        bridge_registry=bridge_registry,
        rule_registry=rule_registry,
        bridge_execution=bridge_execution,
        bridge_request=bridge_request,
        football_contexts=football_contexts,
    )
    if expected != decision:
        raise RES70ValidationError(
            "comparability decision does not recompute from exact observations, request, "
            "and registries"
        )


def validate_cross_source_decision_set(
    decisions: tuple[CrossSourceComparabilityDecision, ...],
    requests: tuple[CrossSourceComparabilityRequest, ...],
    observations: Mapping[object, ScientificMeasurementObservation]
    | Sequence[ScientificMeasurementObservation],
    *,
    bridge_requests: tuple[BridgeApplicationRequest, ...] = (),
    bridge_executions: tuple[BridgeExecutionResult, ...] = (),
    football_contexts: Mapping[object, object] | Sequence[object] | None = None,
    bridge_registry: BridgeRegistry | None = None,
    rule_registry: ComparabilityRuleRegistry | None = None,
) -> None:
    """Recompute every supplied decision from its exact canonical inputs."""

    if bridge_registry is None:
        from dynamislm.comparability.res70_registry import CANONICAL_BRIDGE_REGISTRY

        bridge_registry = CANONICAL_BRIDGE_REGISTRY
    if rule_registry is None:
        from dynamislm.comparability.res70_registry import RES70_COMPARABILITY_RULE_REGISTRY

        rule_registry = RES70_COMPARABILITY_RULE_REGISTRY
    validate_pairwise_decisions(decisions)
    request_by_pair = {
        frozenset(item.qualified for item in request.observation_ids): request
        for request in requests
    }
    if len(request_by_pair) != len(requests):
        raise RES70ValidationError("comparability requests cannot contain duplicate pairs")
    execution_by_hash = {item.canonical_execution_hash: item for item in bridge_executions}
    bridge_request_by_hash = {item.request_hash: item for item in bridge_requests}
    for decision in decisions:
        request = request_by_pair.get(decision.pair_key)
        if request is None:
            raise RES70ValidationError("comparability decision has no exact originating request")
        execution = (
            execution_by_hash.get(decision.bridge_execution_hash)
            if decision.bridge_execution_hash is not None
            else None
        )
        bridge_request = (
            bridge_request_by_hash.get(execution.request_hash) if execution is not None else None
        )
        validate_cross_source_decision(
            decision,
            request,
            bridge_registry=bridge_registry,
            rule_registry=rule_registry,
            observations=observations,
            bridge_request=bridge_request,
            bridge_execution=execution,
            football_contexts=football_contexts,
        )


def validate_pairwise_decisions(
    decisions: tuple[CrossSourceComparabilityDecision, ...],
) -> None:
    """Validate pair uniqueness without offering any transitive closure operation."""

    pairs = tuple(decision.pair_key for decision in decisions)
    if len(set(pairs)) != len(pairs):
        raise RES70ValidationError("pairwise decision collection contains duplicate pairs")
    # Deliberately no graph traversal or reachable/comparable inference exists here.


__all__ = [
    "RES70ValidationError",
    "build_res70_refusal",
    "resolve_observation_reference",
    "validate_bridge_execution",
    "validate_bridge_registration",
    "validate_bridge_registry",
    "validate_cross_source_decision",
    "validate_cross_source_decision_set",
    "validate_cross_source_request",
    "validate_pairwise_decisions",
]
