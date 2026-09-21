"""Immutable contracts used by the RES-71 qualification harness.

These records describe authority that already exists in the scientific engine;
they do not add a numerical dispatch layer or accept caller-supplied formulas.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from dynamislm.serialization import register_serializable_type


class OperationDisposition(StrEnum):
    """Qualification status of a registered scientific operation."""

    IMPLEMENTED = "IMPLEMENTED"
    HISTORICAL_REPLAY_ONLY = "HISTORICAL_REPLAY_ONLY"
    REPRESENT_BUT_DO_NOT_COMPUTE = "REPRESENT_BUT_DO_NOT_COMPUTE"
    DEFERRED = "DEFERRED"
    REJECTED = "REJECTED"


class CoverageStatus(StrEnum):
    """Status of a V2 scientific-family coverage row."""

    QUALIFIED = "QUALIFIED"
    QUALIFIED_WITH_EXPLICIT_DEFERRED = "QUALIFIED_WITH_EXPLICIT_DEFERRED"


class GateComponentStatus(StrEnum):
    """Machine-readable component result used by the RES-71 receipt."""

    PASS = "PASS"
    FAIL = "FAIL"


class ReferenceCaseStatus(StrEnum):
    """Expected outcome class for a verifier-ready deterministic case."""

    VALUE = "VALUE"
    REFUSAL = "REFUSAL"
    COMPARABILITY = "COMPARABILITY"
    CLAIM_AUTHORITY = "CLAIM_AUTHORITY"


@register_serializable_type
@dataclass(frozen=True, slots=True)
class RegisteredOperationInventoryEntry:
    """Complete qualification record for one registered-operation identity."""

    operation_id: str
    label: str
    method_version: str
    scientific_family: str
    disposition: OperationDisposition
    implementation: tuple[str, ...]
    input_contract: str
    output_contract: str
    provenance_contract: str
    refusal_path: tuple[str, ...]
    test_coverage: tuple[str, ...]
    authority_references: tuple[str, ...]
    tolerance_contract: str

    def __post_init__(self) -> None:
        for field_name in (
            "operation_id",
            "label",
            "method_version",
            "scientific_family",
            "input_contract",
            "output_contract",
            "provenance_contract",
            "tolerance_contract",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be non-empty")
        if "@" not in self.operation_id:
            raise ValueError("operation_id must include an explicit version")
        if self.operation_id.rsplit("@", 1)[1] != self.method_version:
            raise ValueError("method_version must match operation_id")
        for field_name in (
            "implementation",
            "refusal_path",
            "test_coverage",
            "authority_references",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, tuple) or any(
                not isinstance(item, str) or not item.strip() for item in value
            ):
                raise ValueError(f"{field_name} must be a tuple of non-empty strings")
        if (
            self.disposition
            in {
                OperationDisposition.IMPLEMENTED,
                OperationDisposition.HISTORICAL_REPLAY_ONLY,
            }
            and not self.implementation
        ):
            raise ValueError("implemented operation must identify an implementation")
        if self.disposition is not OperationDisposition.IMPLEMENTED and not self.refusal_path:
            raise ValueError("non-computing operation must identify a refusal/representation path")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class CoverageRow:
    """One required V2 domain in the qualification coverage matrix."""

    domain: str
    status: CoverageStatus
    authoritative_surfaces: tuple[str, ...]
    registered_operations: tuple[str, ...]
    unresolved_capabilities: tuple[str, ...]
    provenance_boundary: str
    comparability_boundary: str
    claim_boundary: str
    test_coverage: tuple[str, ...]
    authority_references: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.domain.strip():
            raise ValueError("coverage domain must be non-empty")
        for field_name in (
            "authoritative_surfaces",
            "registered_operations",
            "unresolved_capabilities",
            "test_coverage",
            "authority_references",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, tuple) or any(
                not isinstance(item, str) or not item.strip() for item in value
            ):
                raise ValueError(f"{field_name} must be a tuple of non-empty strings")
        for field_name in ("provenance_boundary", "comparability_boundary", "claim_boundary"):
            if not getattr(self, field_name).strip():
                raise ValueError(f"{field_name} must be non-empty")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class UnresolvedComputation:
    """Explicit non-authoritative representation of an unsupported computation."""

    capability: str
    registered_operation_id: str | None
    disposition: OperationDisposition
    reason: str
    refusal_path: tuple[str, ...]
    expected_refusal_class: str
    safe_description: str
    test_coverage: tuple[str, ...]
    authority_references: tuple[str, ...]
    expected_reason_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name in (
            "capability",
            "reason",
            "expected_refusal_class",
            "safe_description",
        ):
            if not getattr(self, field_name).strip():
                raise ValueError(f"{field_name} must be non-empty")
        if not isinstance(self.refusal_path, tuple) or not self.refusal_path:
            raise ValueError("refusal_path must be non-empty")
        for field_name in (
            "refusal_path",
            "test_coverage",
            "authority_references",
            "expected_reason_codes",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, tuple) or any(
                not isinstance(item, str) or not item.strip() for item in value
            ):
                raise ValueError(f"{field_name} must contain non-empty strings")
        if not self.expected_reason_codes:
            raise ValueError("expected_reason_codes must be non-empty")
        if self.disposition is OperationDisposition.IMPLEMENTED:
            raise ValueError("unresolved computation cannot be implemented")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class ReferenceValue:
    """A scalar expected value in a verifier-ready reference case."""

    name: str
    value: bool | float | int | str
    unit: str | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("reference value name must be non-empty")
        if isinstance(self.value, float) and not __import__("math").isfinite(self.value):
            raise ValueError("reference values must be finite")
        if self.unit is not None and not self.unit.strip():
            raise ValueError("reference value unit must be non-empty when supplied")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class ReferenceCase:
    """Machine-readable case contract for later verifier construction."""

    case_id: str
    case_version: str
    family: str
    operation_id: str | None
    status: ReferenceCaseStatus
    synthetic_input: tuple[ReferenceValue, ...]
    expected_values: tuple[ReferenceValue, ...]
    expected_refusal_class: str | None
    expected_reason_codes: tuple[str, ...]
    expected_comparability_state: str | None
    expected_claim_level: str | None
    tolerance_absolute: float | None
    tolerance_relative: float | None
    required_provenance_fields: tuple[str, ...]
    authority_references: tuple[str, ...]

    def __post_init__(self) -> None:
        for field_name in ("case_id", "case_version", "family"):
            if not getattr(self, field_name).strip():
                raise ValueError(f"{field_name} must be non-empty")
        if not isinstance(self.synthetic_input, tuple) or not isinstance(
            self.expected_values, tuple
        ):
            raise ValueError("reference values must be immutable tuples")
        if any(not isinstance(item, ReferenceValue) for item in self.synthetic_input):
            raise ValueError("synthetic_input must contain ReferenceValue values")
        if any(not isinstance(item, ReferenceValue) for item in self.expected_values):
            raise ValueError("expected_values must contain ReferenceValue values")
        if self.status is ReferenceCaseStatus.VALUE:
            if not self.operation_id or not self.expected_values:
                raise ValueError("value case requires operation and expected values")
            if self.expected_refusal_class or self.expected_comparability_state:
                raise ValueError("value case cannot carry refusal/comparability state")
        if self.status is ReferenceCaseStatus.REFUSAL:
            if not self.expected_refusal_class or not self.expected_reason_codes:
                raise ValueError("refusal case requires class and reason codes")
        if (
            self.status is ReferenceCaseStatus.COMPARABILITY
            and not self.expected_comparability_state
        ):
            raise ValueError("comparability case requires a state")
        if self.status is ReferenceCaseStatus.CLAIM_AUTHORITY and not self.expected_claim_level:
            raise ValueError("claim-authority case requires a claim level")
        for name in ("tolerance_absolute", "tolerance_relative"):
            value = getattr(self, name)
            if value is not None and (value < 0 or not __import__("math").isfinite(value)):
                raise ValueError(f"{name} must be finite and non-negative")
        for field_name in (
            "expected_reason_codes",
            "required_provenance_fields",
            "authority_references",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, tuple) or any(
                not isinstance(item, str) or not item.strip() for item in value
            ):
                raise ValueError(f"{field_name} must be a tuple of non-empty strings")
