"""Runtime-bound validation for the checked-in RES-71 gate receipt."""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from dynamislm.qualification.contracts import GateComponentStatus
from dynamislm.qualification.inventory import (
    build_coverage_matrix,
    build_registered_operation_inventory,
    build_unresolved_computation_inventory,
    validate_coverage_matrix,
    validate_registered_operation_inventory,
    validate_unresolved_computation_inventory,
)
from dynamislm.qualification.references import (
    get_reference_cases,
    reference_case_digest,
    validate_reference_cases,
)
from dynamislm.serialization import SERIALIZATION_VERSION

RES71_GATE_RECEIPT_PATH = (
    Path(__file__).resolve().parents[3] / "docs" / "qualification" / "RES71-GATE-RECEIPT.json"
)
RES71_GATE_MISSION = "RES-71-SCIENTIFIC-ENGINE-GATE-001"
RES71_BASE_MAIN = "7508a9025759c2863d163e09b22f325494828602"
RES71_QUALIFIED_CONTENT_HEAD = "0a51127628f1bfc1f0b89064bf92d7fc2703ff39"
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_NON_IMPLEMENTATION_FLAGS = {
    "MODEL_INFERENCE": "NOT_IMPLEMENTED",
    "GPU_WORK": "NOT_IMPLEMENTED",
}


def build_gate_runtime_evidence() -> dict[str, object]:
    """Recompute the deterministic evidence required by the RES-71 gate."""

    operations = build_registered_operation_inventory()
    if validate_registered_operation_inventory(operations) is not GateComponentStatus.PASS:
        raise ValueError("RES-71 registered-operation inventory validation did not pass")

    coverage = build_coverage_matrix()
    if validate_coverage_matrix(coverage) is not GateComponentStatus.PASS:
        raise ValueError("RES-71 coverage-matrix validation did not pass")

    unresolved = build_unresolved_computation_inventory()
    if validate_unresolved_computation_inventory(unresolved) is not GateComponentStatus.PASS:
        raise ValueError("RES-71 unresolved-computation inventory validation did not pass")

    reference_cases = get_reference_cases()
    validate_reference_cases(reference_cases)
    reference_digest = reference_case_digest(reference_cases)

    disposition_counts = Counter(item.disposition.value for item in operations)
    runtime_counts: dict[str, object] = {
        "registered_operations": len(operations),
        "implemented": disposition_counts["IMPLEMENTED"],
        "historical_replay_only": disposition_counts["HISTORICAL_REPLAY_ONLY"],
        "represented_but_do_not_compute": disposition_counts["REPRESENT_BUT_DO_NOT_COMPUTE"],
        "deferred": disposition_counts["DEFERRED"],
        "rejected": disposition_counts["REJECTED"],
        "unresolved_capabilities": len(unresolved),
        "coverage_domains": len(coverage),
        "verifier_reference_cases": len(reference_cases),
        "verifier_reference_digest": reference_digest,
    }
    return {
        "STATUS": "PASS",
        "REGISTERED_OPERATION_INVENTORY": "PASS",
        "COVERAGE_MATRIX": "PASS",
        "UNRESOLVED_COMPUTATION_INVENTORY": "PASS",
        "REFERENCE_CASE_VALIDATION": "PASS",
        "RUNTIME_COUNTS": runtime_counts,
        "SERIALIZATION_VERSION": SERIALIZATION_VERSION,
        **_NON_IMPLEMENTATION_FLAGS,
        "SCIENTIFIC_ENGINE_GATE": "PASS",
    }


def _load_receipt() -> Mapping[str, object]:
    try:
        payload: object = json.loads(RES71_GATE_RECEIPT_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"RES-71 gate receipt is unreadable: {RES71_GATE_RECEIPT_PATH}") from exc
    if not isinstance(payload, dict):
        raise ValueError("RES-71 gate receipt must be a JSON object")
    return cast(Mapping[str, object], payload)


def _strict_equal(actual: object, expected: object) -> bool:
    """Compare receipt values without Python's bool/int equality coercion."""

    if type(actual) is not type(expected):
        return False
    if actual != expected:
        return False
    if isinstance(expected, Mapping):
        actual_mapping = cast(Mapping[object, object], actual)
        expected_mapping = cast(Mapping[object, object], expected)
        if len(actual_mapping) != len(expected_mapping):
            return False
        for expected_key, expected_value in expected_mapping.items():
            matching_keys = tuple(
                key
                for key in actual_mapping
                if type(key) is type(expected_key) and key == expected_key
            )
            if len(matching_keys) != 1:
                return False
            if not _strict_equal(actual_mapping[matching_keys[0]], expected_value):
                return False
        return True
    if isinstance(expected, list | tuple):
        actual_sequence = cast(list[object] | tuple[object, ...], actual)
        expected_sequence = cast(list[object] | tuple[object, ...], expected)
        return len(actual_sequence) == len(expected_sequence) and all(
            _strict_equal(actual_item, expected_item)
            for actual_item, expected_item in zip(actual_sequence, expected_sequence, strict=True)
        )
    return True


def _require_field(receipt: Mapping[str, object], key: str, expected: object) -> None:
    actual = receipt.get(key)
    if not _strict_equal(actual, expected):
        raise ValueError(
            f"RES-71 gate receipt field {key} differs: expected {expected!r}, got {actual!r}"
        )


def validate_gate_receipt(receipt: Mapping[str, object] | None = None) -> GateComponentStatus:
    """Require the checked-in receipt to equal freshly derived runtime evidence."""

    receipt_data = _load_receipt() if receipt is None else receipt
    evidence = build_gate_runtime_evidence()
    expected = {
        "MISSION": RES71_GATE_MISSION,
        "BASE_MAIN": RES71_BASE_MAIN,
        "QUALIFIED_CONTENT_HEAD": RES71_QUALIFIED_CONTENT_HEAD,
        **evidence,
    }
    extra_fields = set(receipt_data) - set(expected)
    missing_fields = set(expected) - set(receipt_data)
    if extra_fields:
        raise ValueError(
            "RES-71 gate receipt contains non-authoritative or unchecked fields: "
            f"{sorted(extra_fields)}"
        )
    if missing_fields:
        raise ValueError(
            f"RES-71 gate receipt is missing authoritative fields: {sorted(missing_fields)}"
        )
    for key, expected_value in expected.items():
        _require_field(receipt_data, key, expected_value)

    qualified_content_head = receipt_data["QUALIFIED_CONTENT_HEAD"]
    if not isinstance(qualified_content_head, str) or not _SHA_RE.fullmatch(qualified_content_head):
        raise ValueError("RES-71 gate receipt must contain a full QUALIFIED_CONTENT_HEAD SHA")

    for key in _NON_IMPLEMENTATION_FLAGS:
        _require_field(receipt_data, key, evidence[key])
    if qualified_content_head != RES71_QUALIFIED_CONTENT_HEAD:
        raise ValueError("RES-71 qualified content head differs from the sealed content head")
    return GateComponentStatus.PASS


__all__ = [
    "RES71_BASE_MAIN",
    "RES71_GATE_MISSION",
    "RES71_GATE_RECEIPT_PATH",
    "RES71_QUALIFIED_CONTENT_HEAD",
    "build_gate_runtime_evidence",
    "validate_gate_receipt",
]
