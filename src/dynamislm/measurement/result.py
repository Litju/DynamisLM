"""Tagged result values and quality/uncertainty metadata."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

from dynamislm.measurement.identity import (
    InstanceIdentifier,
    RegistryReference,
    UnitReference,
    _require_enum,
    _require_instance,
    _require_number,
    _require_optional_instance,
    _require_text,
    _require_tuple_items,
    require_tuple,
)
from dynamislm.measurement.taxonomy import ScientificClassification
from dynamislm.serialization import register_serializable_type

type Scalar = float | int | str | bool


def _finite(value: float, field_name: str) -> None:
    if not math.isfinite(value):
        raise ValueError(f"{field_name} cannot be NaN or Infinity")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class ScalarValue:
    value: Scalar

    @property
    def kind(self) -> str:
        return "scalar"

    def __post_init__(self) -> None:
        if not isinstance(self.value, str | int | float | bool):
            raise ValueError("scalar value must be a scalar JSON-compatible value")
        if isinstance(self.value, float):
            _finite(self.value, "scalar value")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class VectorValue:
    values: tuple[float, ...]

    @property
    def kind(self) -> str:
        return "vector"

    def __post_init__(self) -> None:
        require_tuple(self.values, "values")
        for value in self.values:
            if isinstance(value, bool) or not isinstance(value, int | float):
                raise ValueError("vector values must be numeric")
            _finite(float(value), "vector value")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class IntervalValue:
    lower: float
    upper: float
    inclusive_lower: bool = True
    inclusive_upper: bool = True

    @property
    def kind(self) -> str:
        return "interval"

    def __post_init__(self) -> None:
        _require_number(self.lower, "interval lower")
        _require_number(self.upper, "interval upper")
        _finite(float(self.lower), "interval lower")
        _finite(float(self.upper), "interval upper")
        if self.lower > self.upper:
            raise ValueError("interval lower must not exceed upper")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class CategoricalValue:
    category: str
    ordinal: float | int | None = None

    @property
    def kind(self) -> str:
        return "categorical_or_ordinal"

    def __post_init__(self) -> None:
        _require_text(self.category, "category")
        if self.ordinal is not None:
            _require_number(self.ordinal, "ordinal")
            _finite(float(self.ordinal), "ordinal")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class StructuredOutputReference:
    """Reference to a structured/series output without embedding the payload."""

    artifact_id: InstanceIdentifier
    schema: RegistryReference
    uri: str | None = None

    @property
    def kind(self) -> str:
        return "structured_reference"

    def __post_init__(self) -> None:
        _require_instance(self.artifact_id, InstanceIdentifier, "artifact_id")
        _require_instance(self.schema, RegistryReference, "schema")
        if self.uri is not None and not self.uri.strip():
            raise ValueError("uri must not be empty when present")


type ResultValue = (
    ScalarValue | VectorValue | IntervalValue | CategoricalValue | StructuredOutputReference
)


class QualityStatus(StrEnum):
    UNKNOWN = "UNKNOWN"
    ACCEPTED = "ACCEPTED"
    FLAGGED = "FLAGGED"
    REJECTED = "REJECTED"


class UncertaintyStatus(StrEnum):
    NOT_ASSESSED = "NOT_ASSESSED"
    ASSESSED = "ASSESSED"
    LIMITED = "LIMITED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class ResultStatus(StrEnum):
    VALID = "VALID"
    QUESTIONABLE = "QUESTIONABLE"
    INVALID = "INVALID"
    MISSING = "MISSING"


@register_serializable_type
@dataclass(frozen=True, slots=True)
class MeasurementQuality:
    status: QualityStatus = QualityStatus.UNKNOWN
    flags: tuple[str, ...] = ()
    note: str | None = None

    def __post_init__(self) -> None:
        _require_enum(self.status, QualityStatus, "status")
        _require_tuple_items(self.flags, str, "flags")
        if any(not flag.strip() for flag in self.flags):
            raise ValueError("quality flags must not contain empty strings")
        if self.note is not None and not self.note.strip():
            raise ValueError("quality note must not be empty when present")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class UncertaintyMetadata:
    """Uncertainty status/reference placeholder, not an uncertainty model."""

    status: UncertaintyStatus = UncertaintyStatus.NOT_ASSESSED
    model_reference: RegistryReference | None = None
    description: str | None = None

    def __post_init__(self) -> None:
        _require_enum(self.status, UncertaintyStatus, "status")
        _require_optional_instance(self.model_reference, RegistryReference, "model_reference")
        if self.description is not None and not self.description.strip():
            raise ValueError("uncertainty description must not be empty when present")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class MeasurementResult:
    """Observed output with independent origin, explicit roles and status metadata."""

    result_id: InstanceIdentifier
    value: ResultValue
    unit: UnitReference | None
    classification: ScientificClassification
    quality: MeasurementQuality = MeasurementQuality()
    uncertainty: UncertaintyMetadata = UncertaintyMetadata()
    status: ResultStatus = ResultStatus.VALID

    def __post_init__(self) -> None:
        _require_instance(self.result_id, InstanceIdentifier, "result_id")
        if not isinstance(
            self.value,
            ScalarValue
            | VectorValue
            | IntervalValue
            | CategoricalValue
            | StructuredOutputReference,
        ):
            raise ValueError("value must be a registered ResultValue")
        _require_optional_instance(self.unit, UnitReference, "unit")
        _require_instance(self.classification, ScientificClassification, "classification")
        _require_instance(self.quality, MeasurementQuality, "quality")
        _require_instance(self.uncertainty, UncertaintyMetadata, "uncertainty")
        _require_enum(self.status, ResultStatus, "status")
