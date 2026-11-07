"""Deterministic RES-426 verifier utilities over the sealed RES-71 reference set."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from dynamislm.external_load.registry import EXTERNAL_LOAD_REGISTRY_VERSION
from dynamislm.qualification.contracts import (
    ReferenceCase,
    ReferenceCaseStatus,
    ReferenceValue,
)
from dynamislm.qualification.inventory import discovered_registered_operation_ids
from dynamislm.qualification.references import get_reference_cases, reference_case_digest
from dynamislm.serialization import canonical_hash, canonical_json

VERIFIER_GENERATOR_SCHEMA = "RES426_VERIFIER_CASES_V1"


@dataclass(frozen=True, slots=True)
class GeneratedVerifierCase:
    """One synthetic verifier task bound to the sealed RES-71 reference set."""

    case: ReferenceCase
    source_digest: str
    generator_schema: str = VERIFIER_GENERATOR_SCHEMA
    synthetic: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.case, ReferenceCase):
            raise ValueError("generated verifier case must retain its typed reference case")
        if not isinstance(self.source_digest, str) or not self.source_digest.startswith("sha256:"):
            raise ValueError("generated verifier case requires a source digest")


def generate_verifier_cases(
    case_ids: tuple[str, ...] | None = None,
) -> tuple[GeneratedVerifierCase, ...]:
    """Generate reproducible synthetic tasks from the immutable RES-71 cases."""
    cases = get_reference_cases()
    digest = reference_case_digest(cases)
    if case_ids is None:
        selected = {case.case_id for case in cases}
    else:
        if not isinstance(case_ids, tuple) or any(
            not isinstance(case_id, str) or not case_id.strip() for case_id in case_ids
        ):
            raise ValueError("case_ids must be a tuple of non-empty case IDs")
        if len(set(case_ids)) != len(case_ids):
            raise ValueError("case_ids must not contain duplicates")
        selected = set(case_ids)
        unknown = selected - {case.case_id for case in cases}
        if unknown:
            raise ValueError(f"unregistered verifier case IDs: {sorted(unknown)}")
    return tuple(
        GeneratedVerifierCase(case=case, source_digest=digest)
        for case in cases
        if case.case_id in selected
    )


@dataclass(frozen=True, slots=True)
class ReferenceOutcome:
    """Structured output produced by the deterministic engine or a candidate under review."""

    status: ReferenceCaseStatus
    operation_id: str | None
    values: tuple[ReferenceValue, ...] = ()
    refusal_class: str | None = None
    reason_codes: tuple[str, ...] = ()
    comparability_state: str | None = None
    claim_level: str | None = None
    provenance: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.status, ReferenceCaseStatus):
            raise ValueError("reference outcome status must be registered")
        if self.operation_id is not None and (
            not isinstance(self.operation_id, str) or not self.operation_id.strip()
        ):
            raise ValueError("reference outcome operation_id must be non-empty or None")
        for field_name in ("refusal_class", "comparability_state", "claim_level"):
            value = getattr(self, field_name)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValueError(f"{field_name} must be non-empty or None")
        if not isinstance(self.values, tuple) or any(
            not isinstance(value, ReferenceValue) for value in self.values
        ):
            raise ValueError("reference outcome values must be immutable ReferenceValue tuples")
        if not isinstance(self.reason_codes, tuple) or any(
            not isinstance(code, str) or not code.strip() for code in self.reason_codes
        ):
            raise ValueError("reference outcome reason codes must be non-empty strings")
        if not isinstance(self.provenance, tuple) or any(
            not isinstance(row, tuple)
            or len(row) != 2
            or any(not isinstance(part, str) or not part.strip() for part in row)
            for row in self.provenance
        ):
            raise ValueError("reference outcome provenance must be immutable name/value pairs")
        if len({name for name, _ in self.provenance}) != len(self.provenance):
            raise ValueError("reference outcome provenance fields must be unique")


@dataclass(frozen=True, slots=True)
class VerificationResult:
    case_id: str
    verified: bool
    failure_codes: tuple[str, ...]
    reference_digest: str
    outcome_digest: str


def _outcome_payload(outcome: ReferenceOutcome) -> dict[str, Any]:
    return {
        "status": outcome.status.value,
        "operation_id": outcome.operation_id,
        "values": [
            {"name": value.name, "value": value.value, "unit": value.unit}
            for value in outcome.values
        ],
        "refusal_class": outcome.refusal_class,
        "reason_codes": outcome.reason_codes,
        "comparability_state": outcome.comparability_state,
        "claim_level": outcome.claim_level,
        "provenance": outcome.provenance,
    }


def _value_matches(
    observed: ReferenceValue, expected: ReferenceValue, *, absolute: float, relative: float
) -> bool:
    if observed.name != expected.name or observed.unit != expected.unit:
        return False
    actual, target = observed.value, expected.value
    if type(target) is bool or isinstance(target, str):
        return type(actual) is type(target) and actual == target
    if type(actual) not in {int, float} or type(target) not in {int, float}:
        return False
    try:
        actual_number, target_number = float(actual), float(target)
        return math.isfinite(actual_number) and math.isclose(
            actual_number,
            target_number,
            rel_tol=relative,
            abs_tol=absolute,
        )
    except (OverflowError, ValueError):
        return False


def _expected_provenance(case: ReferenceCase) -> dict[str, str]:
    """Only identities supplied by sealed references or their registered method authority."""
    expected: dict[str, str] = {}
    if case.operation_id is not None:
        expected["operation_id"] = case.operation_id
    units = {value.unit for value in case.expected_values}
    if len(units) == 1 and None not in units:
        expected["unit"] = next(unit for unit in units if unit is not None)
    if case.family == "external-load":
        expected["method_registry_version"] = EXTERNAL_LOAD_REGISTRY_VERSION
    if case.expected_reason_codes:
        expected["reason_codes"] = canonical_json(case.expected_reason_codes)
        expected["refusal_reasons"] = canonical_json(case.expected_reason_codes)
    if case.expected_claim_level is not None:
        expected["resolved_level"] = case.expected_claim_level
    return expected


def verify_reference_outcome(
    generated: GeneratedVerifierCase, outcome: ReferenceOutcome
) -> VerificationResult:
    """Check sealed expectations; other provenance values are checked for presence only.

    Provenance reason tuples use canonical JSON. No source/support/request hash or
    instance identity is inferred where the reference supplies no expected value.
    """
    if not isinstance(generated, GeneratedVerifierCase) or not isinstance(
        outcome, ReferenceOutcome
    ):
        raise TypeError("generated verifier case and typed reference outcome are required")

    digest = reference_case_digest()
    outcome_digest = canonical_hash(_outcome_payload(outcome))
    reference_by_id = {case.case_id: case for case in get_reference_cases()}
    case = reference_by_id.get(generated.case.case_id)
    if case is None:
        return VerificationResult(
            case_id=generated.case.case_id,
            verified=False,
            failure_codes=("REFERENCE_CASE_NOT_REGISTERED",),
            reference_digest=digest,
            outcome_digest=outcome_digest,
        )

    failures: list[str] = []
    if generated.generator_schema != VERIFIER_GENERATOR_SCHEMA:
        failures.append("GENERATOR_SCHEMA_MISMATCH")
    if generated.synthetic is not True:
        failures.append("NON_SYNTHETIC_TASK")
    if generated.source_digest != digest:
        failures.append("SOURCE_DIGEST_MISMATCH")
    if canonical_hash(generated.case) != canonical_hash(case):
        failures.append("REFERENCE_CASE_MISMATCH")

    live_operations = set(discovered_registered_operation_ids())
    if case.operation_id is not None and case.operation_id not in live_operations:
        failures.append("REFERENCE_OPERATION_UNREGISTERED")
    if outcome.operation_id is not None and outcome.operation_id not in live_operations:
        failures.append("OBSERVED_OPERATION_UNREGISTERED")
    if outcome.operation_id != case.operation_id:
        failures.append("OPERATION_ID_MISMATCH")
    if outcome.status is not case.status:
        failures.append("STATUS_MISMATCH")

    if len(outcome.values) != len(case.expected_values):
        failures.append("VALUE_COUNT_MISMATCH")
    else:
        absolute = case.tolerance_absolute or 0.0
        relative = case.tolerance_relative or 0.0
        failures.extend(
            f"VALUE_MISMATCH:{expected.name}"
            for observed, expected in zip(outcome.values, case.expected_values, strict=True)
            if not _value_matches(observed, expected, absolute=absolute, relative=relative)
        )
    if outcome.refusal_class != case.expected_refusal_class:
        failures.append("REFUSAL_CLASS_MISMATCH")
    if outcome.reason_codes != case.expected_reason_codes:
        failures.append("REASON_CODES_MISMATCH")
    if outcome.comparability_state != case.expected_comparability_state:
        failures.append("COMPARABILITY_STATE_MISMATCH")
    if outcome.claim_level != case.expected_claim_level:
        failures.append("CLAIM_LEVEL_MISMATCH")

    observed_provenance = dict(outcome.provenance)
    failures.extend(
        f"MISSING_PROVENANCE:{field}"
        for field in case.required_provenance_fields
        if field not in observed_provenance
    )
    expected_provenance = _expected_provenance(case)
    failures.extend(
        f"PROVENANCE_VALUE_MISMATCH:{field}"
        for field, value in observed_provenance.items()
        if field in expected_provenance and value != expected_provenance[field]
    )
    return VerificationResult(
        case_id=case.case_id,
        verified=not failures,
        failure_codes=tuple(failures),
        reference_digest=digest,
        outcome_digest=outcome_digest,
    )


__all__ = [
    "VERIFIER_GENERATOR_SCHEMA",
    "GeneratedVerifierCase",
    "ReferenceOutcome",
    "VerificationResult",
    "generate_verifier_cases",
    "verify_reference_outcome",
]
