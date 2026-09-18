"""Fail-closed validation for RES-70 comparability and bridge decisions."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from dynamislm.comparability.res70_models import (
    BridgeExecutionResult,
    BridgeRegistration,
    CrossSourceComparabilityDecision,
    CrossSourceComparabilityRequest,
    ObservationAuthorityReference,
)
from dynamislm.comparability.res70_registry import (
    RES70_CROSS_SOURCE_COMPARABILITY_RULE,
    BridgeOperationRegistry,
    BridgeRegistry,
    ComparabilityRuleRegistry,
    canonical_registry_hash,
    is_canonical_bridge_registry,
    is_canonical_operation_registry,
)
from dynamislm.measurement.identity import InstanceIdentifier, RegistryReference
from dynamislm.measurement.observation import ScientificMeasurementObservation
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
    for entry in registry.entries:
        validate_bridge_registration(entry)
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


def validate_bridge_execution(
    result: BridgeExecutionResult,
    request_hash: str | None,
    source_observation: ScientificMeasurementObservation,
) -> None:
    if not isinstance(result, BridgeExecutionResult):
        raise RES70ValidationError("result must be a BridgeExecutionResult")
    if request_hash is not None and result.request_hash != request_hash:
        raise RES70ValidationError("bridge execution request hash does not match request")
    expected_source = ObservationAuthorityReference.from_observation(source_observation)
    if result.source_observation != expected_source:
        raise RES70ValidationError("bridge execution source reference does not match observation")
    if result.transformed_observation is not None:
        if result.processing_run is None or result.provenance is None:
            raise RES70ValidationError("transformed bridge output must carry processing provenance")
        if result.processing_run.output_entity_id != result.transformed_observation.observation_id:
            raise RES70ValidationError(
                "bridge processing output does not match transformed observation"
            )
        if result.output_observation_hash != canonical_hash(result.transformed_observation):
            raise RES70ValidationError("bridge output hash does not match transformed observation")


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
    "validate_cross_source_request",
    "validate_pairwise_decisions",
]
