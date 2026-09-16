"""Deterministic context authority for RES-66 multi-source results."""

from __future__ import annotations

from dynamislm.measurement.identity import (
    InstanceIdentifier,
    MetadataEntry,
    RegistryReference,
    _require_instance,
    require_tuple,
)
from dynamislm.measurement.observation import ObservationContext, ScientificMeasurementObservation
from dynamislm.serialization import canonical_hash, canonical_json


def build_multisource_analysis_context(
    operation: RegistryReference,
    observations: tuple[ScientificMeasurementObservation, ...],
) -> ObservationContext:
    """Build one context for an operation that consumes multiple observations.

    The operation is allowed to proceed only when the observations share the
    analysis scope and an exact registered observation time.  The resulting
    context is deliberately trial-free and is derived from the complete source
    set rather than inheriting any one source context.
    """

    _require_instance(operation, RegistryReference, "operation")
    require_tuple(observations, "observations")
    if len(observations) < 1:
        raise ValueError("multi-source analysis requires at least one observation")
    if any(not isinstance(item, ScientificMeasurementObservation) for item in observations):
        raise ValueError("multi-source analysis requires scientific observations")
    observation_ids = tuple(item.observation_id for item in observations)
    if len(set(observation_ids)) != len(observation_ids):
        raise ValueError("multi-source analysis observations must be unique")

    first = observations[0].context
    for observation in observations[1:]:
        context = observation.context
        if (
            context.athlete_id != first.athlete_id
            or context.session_id != first.session_id
            or context.test_instance_id != first.test_instance_id
            or context.population_context != first.population_context
            or context.environment != first.environment
            or context.observed_at != first.observed_at
        ):
            raise ValueError(
                "multi-source analysis requires common athlete/session/test/population/"
                "environment and exact observed_at"
            )

    ordered_context_ids = tuple(sorted(item.context.context_id.qualified for item in observations))
    ordered_observation_ids = tuple(sorted(item.observation_id.qualified for item in observations))
    shared_scope = {
        "athlete_id": first.athlete_id,
        "session_id": first.session_id,
        "test_instance_id": first.test_instance_id,
        "population_context": first.population_context,
        "environment": first.environment,
        "observed_at": first.observed_at,
        "source_contexts": tuple(
            sorted(
                (item.context for item in observations),
                key=lambda value: value.context_id.qualified,
            )
        ),
    }
    digest = canonical_hash(
        {
            "operation": operation,
            "source_context_ids": ordered_context_ids,
            "source_observation_ids": ordered_observation_ids,
            "shared_analysis_scope": shared_scope,
        }
    ).removeprefix("sha256:")[:32]
    return ObservationContext(
        context_id=InstanceIdentifier("context", f"res66-multisource:{digest}"),
        athlete_id=first.athlete_id,
        session_id=first.session_id,
        test_instance_id=first.test_instance_id,
        trial_id=None,
        observed_at=first.observed_at,
        population_context=first.population_context,
        environment=first.environment,
        context_metadata=(
            MetadataEntry("analysis_operation", operation.stable_id),
            MetadataEntry("source_context_ids", canonical_json(ordered_context_ids)),
            MetadataEntry("source_observation_ids", canonical_json(ordered_observation_ids)),
        ),
    )


__all__ = ["build_multisource_analysis_context"]
