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
RES71_QUALIFIED_CONTENT_HEAD = "49988aa3cd03e460dc8ae8c60f8afa890e75706e"
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


def _require_field(receipt: Mapping[str, object], key: str, expected: object) -> None:
    actual = receipt.get(key)
    if actual != expected:
        raise ValueError(
            f"RES-71 gate receipt field {key} differs: expected {expected!r}, got {actual!r}"
        )


def validate_gate_receipt(receipt: Mapping[str, object] | None = None) -> GateComponentStatus:
    """Require the checked-in receipt to equal freshly derived runtime evidence."""

    receipt_data = _load_receipt() if receipt is None else receipt
    evidence = build_gate_runtime_evidence()
    _require_field(receipt_data, "STATUS", "PASS")
    _require_field(receipt_data, "SCIENTIFIC_ENGINE_GATE", "PASS")
    for key in (
        "REGISTERED_OPERATION_INVENTORY",
        "COVERAGE_MATRIX",
        "UNRESOLVED_COMPUTATION_INVENTORY",
        "REFERENCE_CASE_VALIDATION",
        "RUNTIME_COUNTS",
        "SERIALIZATION_VERSION",
        "MODEL_INFERENCE",
        "GPU_WORK",
    ):
        _require_field(receipt_data, key, evidence[key])

    if "FINAL_HEAD" in receipt_data or "QUALIFIED_ENGINE_HEAD" in receipt_data:
        raise ValueError("RES-71 gate receipt must not claim a branch FINAL_HEAD")
    qualified_content_head = receipt_data.get("QUALIFIED_CONTENT_HEAD")
    if not isinstance(qualified_content_head, str) or not _SHA_RE.fullmatch(qualified_content_head):
        raise ValueError("RES-71 gate receipt must contain a full QUALIFIED_CONTENT_HEAD SHA")
    if qualified_content_head != RES71_QUALIFIED_CONTENT_HEAD:
        raise ValueError("RES-71 qualified content head differs from the sealed content head")

    for key in receipt_data:
        if (key.startswith("MODEL_") or key.startswith("GPU_")) and key not in {
            *_NON_IMPLEMENTATION_FLAGS,
        }:
            raise ValueError(f"RES-71 gate receipt contains an unapproved model/GPU flag: {key}")
    return GateComponentStatus.PASS


__all__ = [
    "RES71_GATE_RECEIPT_PATH",
    "RES71_QUALIFIED_CONTENT_HEAD",
    "build_gate_runtime_evidence",
    "validate_gate_receipt",
]
