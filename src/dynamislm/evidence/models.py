"""Evidence references kept separate from measurement identity."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from dynamislm.measurement.identity import RegistryReference, ScientificIdentifier, require_tuple
from dynamislm.serialization import register_serializable_type


def _require_text(value: str, field_name: str) -> None:
    if not value or not value.strip():
        raise ValueError(f"{field_name} must not be empty")


class ApplicabilityDecision(StrEnum):
    SUPPORTED = "SUPPORTED"
    LIMITED = "LIMITED"
    UNSUPPORTED = "UNSUPPORTED"
    UNASSESSED = "UNASSESSED"


@register_serializable_type
@dataclass(frozen=True, slots=True)
class EvidenceApplicability:
    """Versioned evidence applicability that can change independently of identity."""

    applicability_id: ScientificIdentifier
    measurement_identity_id: ScientificIdentifier
    evidence: RegistryReference
    decision: ApplicabilityDecision
    population_scope: str
    conditions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        require_tuple(self.conditions, "conditions")
        _require_text(self.population_scope, "population_scope")
        if any(not condition.strip() for condition in self.conditions):
            raise ValueError("applicability conditions must not contain empty strings")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class EvidenceDecisionRecord:
    """Concise record of a concrete evidence-backed scientific decision."""

    decision_id: ScientificIdentifier
    scientific_question: str
    sources_inspected: tuple[RegistryReference, ...]
    population_method_applicability: str
    adopted_decision: str
    alternatives: tuple[str, ...]
    assumptions: tuple[str, ...]
    limitations: tuple[str, ...]
    method_version: RegistryReference | None
    implementation_references: tuple[str, ...]

    def __post_init__(self) -> None:
        for field_name, tuple_value in (
            ("sources_inspected", self.sources_inspected),
            ("alternatives", self.alternatives),
            ("assumptions", self.assumptions),
            ("limitations", self.limitations),
            ("implementation_references", self.implementation_references),
        ):
            require_tuple(tuple_value, field_name)
        for field_name, text_value in (
            ("scientific_question", self.scientific_question),
            ("population_method_applicability", self.population_method_applicability),
            ("adopted_decision", self.adopted_decision),
        ):
            _require_text(text_value, field_name)
        for field_name, values in (
            ("alternatives", self.alternatives),
            ("assumptions", self.assumptions),
            ("limitations", self.limitations),
            ("implementation_references", self.implementation_references),
        ):
            if any(not value.strip() for value in values):
                raise ValueError(f"{field_name} must not contain empty strings")
