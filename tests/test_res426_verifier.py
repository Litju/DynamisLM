from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest
from scripts.res426_verifier import (
    ReferenceOutcome,
    generate_verifier_cases,
    verify_reference_outcome,
)

from dynamislm.external_load.metrics import (
    convert_external_load_value,
    duration_normalized_distance,
)
from dynamislm.external_load.registry import (
    EXTERNAL_LOAD_KILOMETER,
    EXTERNAL_LOAD_METER,
    EXTERNAL_LOAD_MINUTE,
    EXTERNAL_LOAD_REGISTRY_VERSION,
)
from dynamislm.qualification.contracts import ReferenceCase, ReferenceValue
from dynamislm.serialization import canonical_json


def _outcome(case: ReferenceCase, **changes: object) -> ReferenceOutcome:
    known = {
        "operation_id": case.operation_id,
        "unit": case.expected_values[0].unit if case.expected_values else None,
        "method_registry_version": EXTERNAL_LOAD_REGISTRY_VERSION,
        "reason_codes": canonical_json(case.expected_reason_codes),
        "refusal_reasons": canonical_json(case.expected_reason_codes),
        "resolved_level": case.expected_claim_level,
    }
    fields: dict[str, Any] = {
        "status": case.status,
        "operation_id": case.operation_id,
        "values": case.expected_values,
        "refusal_class": case.expected_refusal_class,
        "reason_codes": case.expected_reason_codes,
        "comparability_state": case.expected_comparability_state,
        "claim_level": case.expected_claim_level,
        "provenance": tuple(
            (name, known.get(name) or f"synthetic:{name}")
            for name in case.required_provenance_fields
        ),
    }
    fields.update(changes)
    return ReferenceOutcome(**fields)


def test_registered_unit_conversion_output_verifies_and_hashes_reproducibly() -> None:
    generated = generate_verifier_cases(("res71-external-unit-km-to-m",))[0]
    value = convert_external_load_value(1.0, EXTERNAL_LOAD_KILOMETER, EXTERNAL_LOAD_METER)
    outcome = _outcome(
        generated.case,
        values=(ReferenceValue("value", value, "m"),),
    )

    first = verify_reference_outcome(generated, outcome)
    second = verify_reference_outcome(generated, outcome)

    assert first == second
    assert first.verified is True
    assert first.failure_codes == ()
    assert first.outcome_digest.startswith("sha256:")


def test_registered_relative_distance_output_verifies_without_recomputing_the_formula() -> None:
    generated = generate_verifier_cases(("res71-external-relative-distance",))[0]
    value = duration_normalized_distance(
        600.0,
        10.0,
        distance_unit=EXTERNAL_LOAD_METER,
        duration_unit=EXTERNAL_LOAD_MINUTE,
    )
    outcome = _outcome(
        generated.case,
        values=(ReferenceValue("relative_distance", value, "m/min"),),
    )

    result = verify_reference_outcome(generated, outcome)

    assert result.verified is True
    assert result.failure_codes == ()


def test_numeric_tolerance_is_applied_but_wrong_units_and_values_fail() -> None:
    generated = generate_verifier_cases(("res71-cmj-flight-time-v2-gold",))[0]
    case = generated.case
    expected = case.expected_values[0]
    close = replace(
        _outcome(case),
        values=(ReferenceValue(expected.name, float(expected.value) + 1e-13, expected.unit),),
    )
    wrong_unit = replace(
        _outcome(case),
        values=(ReferenceValue(expected.name, float(expected.value), "cm"),),
    )
    wrong_value = replace(
        _outcome(case),
        values=(ReferenceValue(expected.name, float(expected.value) + 1e-4, expected.unit),),
    )

    assert verify_reference_outcome(generated, close).verified is True
    assert (
        "VALUE_MISMATCH:jump_height_m"
        in verify_reference_outcome(generated, wrong_unit).failure_codes
    )
    assert (
        "VALUE_MISMATCH:jump_height_m"
        in verify_reference_outcome(generated, wrong_value).failure_codes
    )


def test_refusal_reason_sets_are_exact_and_claim_comparability_states_are_checked() -> None:
    refusal = generate_verifier_cases(("res71-nonfinite-unit-refusal",))[0]
    extra_reason = replace(
        _outcome(refusal.case),
        reason_codes=(*refusal.case.expected_reason_codes, "UNRELATED_REASON"),
    )
    comparison = generate_verifier_cases(("res71-same-label-different-method",))[0]
    wrong_comparison = replace(_outcome(comparison.case), comparability_state="COMPARABLE")
    claim = generate_verifier_cases(("res71-causal-overclaim-refusal",))[0]
    wrong_claim = replace(_outcome(claim.case), claim_level="CAUSAL_CLAIM")

    assert verify_reference_outcome(refusal, _outcome(refusal.case)).verified is True
    assert "REASON_CODES_MISMATCH" in verify_reference_outcome(refusal, extra_reason).failure_codes
    assert (
        "COMPARABILITY_STATE_MISMATCH"
        in verify_reference_outcome(comparison, wrong_comparison).failure_codes
    )
    assert "CLAIM_LEVEL_MISMATCH" in verify_reference_outcome(claim, wrong_claim).failure_codes


def test_unregistered_operations_missing_provenance_and_stale_cases_fail_closed() -> None:
    generated = generate_verifier_cases(("res71-external-unit-km-to-m",))[0]
    unknown_operation = replace(
        _outcome(generated.case),
        operation_id="dynamislm:registered-operation:unreviewed-formula@1.0.0",
    )
    missing_provenance = replace(_outcome(generated.case), provenance=())
    stale_source = replace(generated, source_digest="sha256:" + "0" * 64)
    changed_case = replace(
        generated,
        case=replace(
            generated.case,
            expected_values=(ReferenceValue("value", 999.0, "m"),),
        ),
    )

    unregistered = verify_reference_outcome(generated, unknown_operation)
    assert "OBSERVED_OPERATION_UNREGISTERED" in unregistered.failure_codes
    assert "OPERATION_ID_MISMATCH" in unregistered.failure_codes
    assert any(
        code.startswith("MISSING_PROVENANCE:")
        for code in verify_reference_outcome(generated, missing_provenance).failure_codes
    )
    assert (
        "SOURCE_DIGEST_MISMATCH"
        in verify_reference_outcome(stale_source, _outcome(generated.case)).failure_codes
    )
    assert (
        "REFERENCE_CASE_MISMATCH"
        in verify_reference_outcome(changed_case, _outcome(generated.case)).failure_codes
    )


@pytest.mark.parametrize("generated", generate_verifier_cases(), ids=lambda task: task.case.case_id)
def test_all_sealed_outcomes_verify_with_authoritative_provenance(generated: Any) -> None:
    assert verify_reference_outcome(generated, _outcome(generated.case)).verified


@pytest.mark.parametrize(
    ("case_id", "field"),
    [
        ("res71-external-unit-km-to-m", "operation_id"),
        ("res71-external-unit-km-to-m", "unit"),
        ("res71-external-unit-km-to-m", "method_registry_version"),
        ("res71-longitudinal-absolute-change", "operation_id"),
        ("res71-cmj-flight-time-v2-gold", "operation_id"),
        ("res71-nonfinite-unit-refusal", "reason_codes"),
        ("res71-between-to-within-refusal", "resolved_level"),
        ("res71-between-to-within-refusal", "refusal_reasons"),
    ],
)
def test_tampered_provenance_values_fail_even_when_typed_output_is_correct(
    case_id: str, field: str
) -> None:
    generated = generate_verifier_cases((case_id,))[0]
    correct = _outcome(generated.case)
    tampered = replace(
        correct,
        provenance=tuple(
            (name, "forged" if name == field else value) for name, value in correct.provenance
        ),
    )
    result = verify_reference_outcome(generated, tampered)
    assert result.verified is False
    assert result.failure_codes == (f"PROVENANCE_VALUE_MISMATCH:{field}",)
