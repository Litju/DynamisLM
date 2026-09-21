from __future__ import annotations

from dataclasses import replace

import pytest

from dynamislm.comparability import (
    ComparabilityState,
    CrossSourceComparabilityRequest,
    ObservationAuthorityReference,
    assess_cross_source_comparability,
)
from dynamislm.external_load.metrics import (
    ExternalLoadComputationError,
    convert_external_load_value,
    duration_normalized_distance,
)
from dynamislm.external_load.registry import (
    EXTERNAL_LOAD_KILOMETER,
    EXTERNAL_LOAD_METER,
    EXTERNAL_LOAD_MINUTE,
)
from dynamislm.measurement.bench_press_throw.metrics import (
    calculate_bpt_load_times_velocity_power,
    calculate_bpt_mean_propulsive_velocity,
)
from dynamislm.measurement.cmj.metrics import refuse_unregistered_cmj_rfd
from dynamislm.measurement.cmj.registry import METER
from dynamislm.measurement.field_testing.ift import refuse_vift_as_vo2max
from dynamislm.measurement.field_testing.sprint import refuse_sprint_acceleration
from dynamislm.measurement.identity import InstanceIdentifier
from dynamislm.measurement.medicine_ball_throw.metrics import (
    calculate_mbt_distance_as_power,
    calculate_mbt_protocol_independent_normative_score,
)
from dynamislm.qualification import (
    ReferenceCaseStatus,
    build_coverage_matrix,
    build_gate_runtime_evidence,
    build_registered_operation_inventory,
    build_unresolved_computation_inventory,
    discovered_registered_operation_ids,
    get_reference_cases,
    reference_case_digest,
    reference_case_manifest,
    validate_coverage_matrix,
    validate_gate_receipt,
    validate_reference_cases,
    validate_registered_operation_inventory,
    validate_unresolved_computation_inventory,
)
from dynamislm.refusal import RefusalClass, RefusalResult
from dynamislm.serialization import canonical_json, from_canonical_json
from test_kernel import _derived_observation


def test_inventory_covers_every_live_registered_operation() -> None:
    entries = build_registered_operation_inventory()

    assert len(discovered_registered_operation_ids()) == 100
    assert len(entries) == 100
    assert validate_registered_operation_inventory(entries).value == "PASS"
    assert {entry.disposition.value for entry in entries} >= {
        "IMPLEMENTED",
        "HISTORICAL_REPLAY_ONLY",
        "REPRESENT_BUT_DO_NOT_COMPUTE",
        "DEFERRED",
        "REJECTED",
    }


def test_coverage_and_unresolved_contracts_are_complete() -> None:
    coverage = build_coverage_matrix()
    unresolved = build_unresolved_computation_inventory()

    assert len(coverage) == 12
    assert validate_coverage_matrix(coverage).value == "PASS"
    assert validate_unresolved_computation_inventory(unresolved).value == "PASS"
    assert any(item.registered_operation_id is None for item in unresolved)
    assert any(item.registered_operation_id is not None for item in unresolved)


def test_gate_receipt_matches_recomputed_runtime_evidence() -> None:
    evidence = build_gate_runtime_evidence()

    assert validate_gate_receipt().value == "PASS"
    assert evidence["RUNTIME_COUNTS"] == {
        "registered_operations": 100,
        "implemented": 81,
        "historical_replay_only": 1,
        "represented_but_do_not_compute": 7,
        "deferred": 8,
        "rejected": 3,
        "unresolved_capabilities": 23,
        "coverage_domains": 12,
        "verifier_reference_cases": 12,
        "verifier_reference_digest": (
            "sha256:d29d84699b7cf70c2d409d370c5ffd6c7ad7cd704375b14b541527a95fa385e5"
        ),
    }


def test_independent_external_load_gold_values_and_domain_refusals() -> None:
    assert convert_external_load_value(1.0, EXTERNAL_LOAD_KILOMETER, EXTERNAL_LOAD_METER) == 1000.0
    assert (
        duration_normalized_distance(
            600.0,
            10.0,
            distance_unit=EXTERNAL_LOAD_METER,
            duration_unit=EXTERNAL_LOAD_MINUTE,
        )
        == 60.0
    )

    with pytest.raises(ExternalLoadComputationError, match="finite"):
        convert_external_load_value(float("nan"), EXTERNAL_LOAD_METER, EXTERNAL_LOAD_KILOMETER)
    with pytest.raises(ExternalLoadComputationError, match="positive"):
        duration_normalized_distance(
            600.0,
            0.0,
            distance_unit=EXTERNAL_LOAD_METER,
            duration_unit=EXTERNAL_LOAD_MINUTE,
        )


def test_unregistered_numerical_surfaces_fail_closed() -> None:
    results = (
        calculate_bpt_load_times_velocity_power(80.0, 1.2),
        calculate_bpt_mean_propulsive_velocity(),
        calculate_mbt_distance_as_power(),
        calculate_mbt_protocol_independent_normative_score(),
        refuse_unregistered_cmj_rfd(),
        refuse_sprint_acceleration(),
        refuse_vift_as_vo2max(),
    )

    for result in results:
        assert isinstance(result, RefusalResult)
    assert all(result.refusal_class is not None for result in results)
    assert all(
        result.refusal_class is RefusalClass.COMPUTATION_NOT_REGISTERED for result in results[:6]
    )
    assert results[6].refusal_class is RefusalClass.IDENTITY_UNRESOLVED


def test_same_label_different_measurand_is_not_comparable() -> None:
    left = _derived_observation("res71-comparison-left")
    right = _derived_observation("res71-comparison-right")
    left = replace(
        left,
        identity=replace(left.identity, processing=replace(left.identity.processing, unit=METER)),
        result=replace(left.result, unit=METER),
    )
    right = replace(
        right,
        identity=replace(right.identity, processing=replace(right.identity.processing, unit=METER)),
        result=replace(right.result, unit=METER),
    )
    measurand = replace(
        right.identity.semantic.measurand,
        display_label=left.identity.semantic.measurand.display_label,
        identifier=replace(right.identity.semantic.measurand.identifier, key="different-measurand"),
    )
    changed_semantic = replace(
        right.identity.semantic,
        measurand=measurand,
    )
    right = replace(right, identity=replace(right.identity, semantic=changed_semantic))
    request = CrossSourceComparabilityRequest(
        request_id=InstanceIdentifier("cross-source-comparability-request", "res71-comparison"),
        left_observation=ObservationAuthorityReference.from_observation(left),
        right_observation=ObservationAuthorityReference.from_observation(right),
        claim_intent=left.identity.semantic.metric_definition,
    )

    decision = assess_cross_source_comparability(request, (left, right))

    assert decision.state is ComparabilityState.NOT_COMPARABLE
    assert "MEASURAND_MISMATCH" in decision.reason_codes


def test_reference_interface_is_deterministic_and_serializable() -> None:
    cases = get_reference_cases()
    validate_reference_cases(cases)
    assert len(cases) == 12
    assert {case.status for case in cases} == {
        ReferenceCaseStatus.VALUE,
        ReferenceCaseStatus.REFUSAL,
        ReferenceCaseStatus.COMPARABILITY,
        ReferenceCaseStatus.CLAIM_AUTHORITY,
    }
    assert reference_case_digest(cases) == reference_case_digest(cases)
    manifest = reference_case_manifest(cases)
    assert '"case_id":"res71-cmj-flight-time-v2-gold"' in manifest

    restored = from_canonical_json(canonical_json(cases[0]), type(cases[0]))
    assert restored == cases[0]
