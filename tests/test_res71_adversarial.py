from __future__ import annotations

import math

from dynamislm.qualification import (
    ReferenceCaseStatus,
    build_registered_operation_inventory,
    get_reference_cases,
)


def test_gold_reference_values_reproduce_from_independent_equations() -> None:
    cases = {case.case_id: case for case in get_reference_cases()}

    flight_time = 0.5
    gravity = 9.81
    expected_jump_height = gravity * flight_time**2 / 8.0
    recorded_jump_height = cases["res71-cmj-flight-time-v2-gold"].expected_values[0].value
    assert isinstance(recorded_jump_height, int | float)
    assert math.isclose(expected_jump_height, recorded_jump_height, rel_tol=1e-12, abs_tol=1e-12)

    repetition_times = (1.0, 1.1, 1.2)
    expected_s_dec = 100.0 * (
        sum(repetition_times) / (min(repetition_times) * len(repetition_times)) - 1.0
    )
    recorded_s_dec = cases["res71-rsa-mechanical-percent-decrement"].expected_values[0].value
    assert isinstance(recorded_s_dec, int | float)
    assert math.isclose(expected_s_dec, recorded_s_dec, rel_tol=1e-12, abs_tol=1e-12)

    expected_relative_distance = 600.0 / 10.0
    recorded_relative_distance = cases["res71-external-relative-distance"].expected_values[0].value
    assert recorded_relative_distance == expected_relative_distance


def test_value_cases_bind_outputs_to_method_and_lineage_contracts() -> None:
    operation_ids = {entry.operation_id for entry in build_registered_operation_inventory()}

    for case in get_reference_cases():
        if case.status is not ReferenceCaseStatus.VALUE:
            continue
        assert case.operation_id in operation_ids
        assert "operation_id" in case.required_provenance_fields
        assert case.expected_values
        assert case.tolerance_absolute is not None
        assert case.tolerance_relative is not None


def test_historical_method_identity_is_not_current_method_identity() -> None:
    entries = {entry.operation_id: entry for entry in build_registered_operation_inventory()}
    historical = entries[
        "dynamislm:registered-operation:cmj-flight-time-ballistic-jump-height-v1@1.0.0"
    ]
    current = entries[
        "dynamislm:registered-operation:cmj-flight-time-ballistic-jump-height-v2@2.0.0"
    ]

    assert historical.disposition.value == "HISTORICAL_REPLAY_ONLY"
    assert current.disposition.value == "IMPLEMENTED"
    assert historical.operation_id != current.operation_id
    assert historical.method_version != current.method_version


def test_claim_and_comparability_cases_preserve_safe_refusal_states() -> None:
    cases = {case.case_id: case for case in get_reference_cases()}
    comparison = cases["res71-same-label-different-method"]
    causal = cases["res71-causal-overclaim-refusal"]
    between = cases["res71-between-to-within-refusal"]

    assert comparison.status is ReferenceCaseStatus.COMPARABILITY
    assert comparison.expected_comparability_state == "NOT_COMPARABLE"
    assert comparison.expected_reason_codes
    assert causal.status is ReferenceCaseStatus.CLAIM_AUTHORITY
    assert causal.expected_refusal_class == "CAUSAL_IDENTIFICATION_UNSUPPORTED"
    assert causal.expected_claim_level == "OBSERVED_VALUE_ONLY"
    assert between.expected_refusal_class == "ANALYSIS_DESIGN_MISMATCH"
    assert between.expected_claim_level == "BETWEEN_ATHLETE_NOT_WITHIN_ATHLETE"
