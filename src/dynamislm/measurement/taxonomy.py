"""Independent value-origin and scientific-role taxonomies."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from dynamislm.measurement.identity import require_tuple
from dynamislm.serialization import register_serializable_type


class ValueOrigin(StrEnum):
    DIRECT_MEASUREMENT = "DIRECT_MEASUREMENT"
    DERIVED_MECHANICAL_QUANTITY = "DERIVED_MECHANICAL_QUANTITY"
    MODEL_ESTIMATE = "MODEL_ESTIMATE"


class ScientificRole(StrEnum):
    PERFORMANCE_OUTCOME = "PERFORMANCE_OUTCOME"
    LATENT_CONSTRUCT_INTERPRETATION = "LATENT_CONSTRUCT_INTERPRETATION"
    PHYSIOLOGICAL_INFERENCE = "PHYSIOLOGICAL_INFERENCE"


@register_serializable_type
@dataclass(frozen=True, slots=True)
class ScientificClassification:
    """Independent axes describing numerical origin and explicit role tags."""

    value_origin: ValueOrigin
    scientific_roles: tuple[ScientificRole, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.value_origin, ValueOrigin):
            raise ValueError("value_origin must be a ValueOrigin")
        require_tuple(self.scientific_roles, "scientific_roles")
        if any(not isinstance(role, ScientificRole) for role in self.scientific_roles):
            raise ValueError("scientific_roles must contain ScientificRole values")
        if len(set(self.scientific_roles)) != len(self.scientific_roles):
            raise ValueError("scientific_roles must not contain duplicates")
        object.__setattr__(
            self,
            "scientific_roles",
            tuple(sorted(self.scientific_roles, key=lambda role: role.value)),
        )
