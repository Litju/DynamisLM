from __future__ import annotations

import copy
import importlib
import json
import math
from collections.abc import Callable
from dataclasses import replace
from typing import cast

import pytest

from dynamislm.qualification import (
    RES71_GATE_RECEIPT_PATH,
    ReferenceCaseStatus,
    build_registered_operation_inventory,
    build_unresolved_computation_inventory,
    get_reference_cases,
    reference_case_digest,
    reference_case_manifest,
    validate_coverage_matrix,
    validate_gate_receipt,
    validate_reference_cases,
    validate_registered_operation_inventory,
    validate_unresolved_computation_inventory,
)
from dynamislm.refusal.models import RefusalResult


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


def test_empty_qualification_inputs_are_not_replaced_by_defaults() -> None:
    with pytest.raises(ValueError):
        validate_registered_operation_inventory(())
    with pytest.raises(ValueError):
        validate_coverage_matrix(())
    with pytest.raises(ValueError):
        validate_unresolved_computation_inventory(())
    with pytest.raises(ValueError):
        validate_reference_cases(())
    with pytest.raises(ValueError):
        reference_case_manifest(())
    with pytest.raises(ValueError):
        reference_case_digest(())


def test_stale_inventory_routes_are_rejected() -> None:
    operation = build_registered_operation_inventory()[0]
    stale_implementation = replace(
        operation,
        implementation=("dynamislm.qualification.inventory:missing_implementation",),
    )
    with pytest.raises(ValueError, match="implementation route is stale"):
        validate_registered_operation_inventory(
            (stale_implementation, *build_registered_operation_inventory()[1:])
        )

    stale_refusal = replace(
        operation,
        refusal_path=("dynamislm.qualification.inventory:missing_refusal",),
    )
    with pytest.raises(ValueError, match="refusal route is stale"):
        validate_registered_operation_inventory(
            (stale_refusal, *build_registered_operation_inventory()[1:])
        )

    unresolved = build_unresolved_computation_inventory()
    stale_unresolved = replace(
        unresolved[0],
        refusal_path=("dynamislm.qualification.inventory:missing_unresolved_route",),
    )
    with pytest.raises(ValueError, match="refusal route is stale"):
        validate_unresolved_computation_inventory((stale_unresolved, *unresolved[1:]))


def test_manually_listed_unresolved_routes_bind_to_actual_refusals() -> None:
    unresolved = tuple(
        item
        for item in build_unresolved_computation_inventory()
        if item.registered_operation_id is None
    )

    for item in unresolved:
        for path in item.refusal_path:
            module_name, attribute_path = path.split(":", 1)
            route = importlib.import_module(module_name)
            producer = route
            for attribute in attribute_path.split("."):
                producer = getattr(producer, attribute)
            result = cast(Callable[[], RefusalResult], producer)()
            assert isinstance(result, RefusalResult)
            assert result.refusal_class.value == item.expected_refusal_class
            assert result.reason_codes == item.expected_reason_codes


def test_gate_receipt_rejects_stale_or_self_referential_edits() -> None:
    receipt = json.loads(RES71_GATE_RECEIPT_PATH.read_text(encoding="utf-8"))
    mutations: list[dict[str, object]] = []

    stale_counts = copy.deepcopy(receipt)
    stale_counts["RUNTIME_COUNTS"]["unresolved_capabilities"] = 22
    mutations.append(stale_counts)

    stale_digest = copy.deepcopy(receipt)
    stale_digest["RUNTIME_COUNTS"]["verifier_reference_digest"] = "sha256:" + "0" * 64
    mutations.append(stale_digest)

    self_referential = copy.deepcopy(receipt)
    self_referential["FINAL_HEAD"] = receipt["QUALIFIED_CONTENT_HEAD"]
    mutations.append(self_referential)

    model_flag = copy.deepcopy(receipt)
    model_flag["MODEL_IMPLEMENTATION"] = "IMPLEMENTED"
    mutations.append(model_flag)

    stale_head = copy.deepcopy(receipt)
    stale_head["QUALIFIED_CONTENT_HEAD"] = "0" * 40
    mutations.append(stale_head)

    for mutated in mutations:
        with pytest.raises(ValueError):
            validate_gate_receipt(mutated)
