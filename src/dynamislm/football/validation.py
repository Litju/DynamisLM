"""Cross-contract validation for football-world placement."""

from __future__ import annotations

from dynamislm.football.models import FootballWorldContext
from dynamislm.measurement.observation import ObservationContext


def validate_football_world_context(world_context: FootballWorldContext) -> None:
    """Validate an already-constructed football-world context type.

    Construction performs the full invariant check.  This small public
    validator is useful at boundaries where a caller receives a polymorphic
    object and wants an explicit fail-closed type check.
    """

    if not isinstance(world_context, FootballWorldContext):
        raise ValueError("world_context must be a FootballWorldContext")


def validate_observation_football_context(
    observation_context: ObservationContext,
    football_world_context: FootballWorldContext,
) -> None:
    """Ensure historical observation links agree with typed football context.

    ``ObservationContext.population_context`` is intentionally not consulted:
    it remains descriptive V1/V3 metadata and cannot repair or override typed
    athlete/session identity.
    """

    if not isinstance(observation_context, ObservationContext):
        raise ValueError("observation_context must be an ObservationContext")
    validate_football_world_context(football_world_context)
    if observation_context.athlete_id != football_world_context.athlete.athlete_id:
        raise ValueError("observation athlete_id does not match football-world athlete")
    if observation_context.session_id != football_world_context.session.session_id:
        raise ValueError("observation session_id does not match football-world session")
    if football_world_context.observation_context_id is not None:
        if observation_context.context_id != football_world_context.observation_context_id:
            raise ValueError(
                "observation context_id does not match football-world observation_context_id"
            )


# Alias for callers that phrase the relationship in the other direction.
validate_football_context_for_observation = validate_observation_football_context


__all__ = [
    "validate_football_context_for_observation",
    "validate_football_world_context",
    "validate_observation_football_context",
]
