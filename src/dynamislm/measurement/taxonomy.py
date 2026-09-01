"""Independent value-origin and scientific-role taxonomies."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

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
    """Independent axes describing numerical origin and interpretive role."""

    value_origin: ValueOrigin
    scientific_role: ScientificRole
