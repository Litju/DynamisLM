from __future__ import annotations

from pathlib import Path

RECEIPT = (
    Path(__file__).resolve().parents[1]
    / "docs/qualification/PSE-POST-AUDIT-EXECUTION-BASELINE-RECEIPT.md"
)


def _fields() -> dict[str, str]:
    lines = RECEIPT.read_text(encoding="utf-8").splitlines()
    fields: dict[str, str] = {}
    in_text_block = False
    for line in lines:
        if line == "```text":
            in_text_block = True
        elif line == "```" and in_text_block:
            in_text_block = False
        elif in_text_block and "=" in line:
            name, value = line.split("=", 1)
            fields.setdefault(name, value)
    return fields


def test_receipt_seals_superseded_res383_conclusions_and_execution_authority() -> None:
    fields = _fields()
    assert fields["REQUIRED_ENTRY_HEAD"] == "b13932c23d8d5c2071dcdbb3260083650fd0002a"
    assert fields["RECOVERY_ANCHOR"] == "c689d5d057da0d5281d718cb25a7b33d26d2530b"
    assert fields["ACTIVE_SUPPLY_SCHEMA"] == "PSE-V1-AUTHORITY-SUPPLY-INVENTORY@1.3.0"
    assert fields["HISTORICAL_RECIPE_INVENTORY"] == "INVENTORY_ONLY"
    assert fields["EXISTING_AUTHORIZED_RECIPE_COUNT"] == "INVENTORY_ONLY"
    assert fields["ADDITIONAL_AUTHORABLE_CAPACITY"] == "SEPARATE_TYPED_VALUE"
    assert fields["CAPACITY_STATUS"] == "PER_LANE_TYPED"
    assert fields["FINAL_SELECTION_BOUND"] == "434_FINAL_SELECTION_ONLY"
    assert fields["RES383_V1_2_INVENTORY"] == "HISTORICAL_PRESERVED"
    assert fields["RES383_V1_2_POOL_FLOOR_436"] == "SUPERSEDED"
    assert fields["RES383_V1_2_SOURCE_PLUS_SYNTHETIC_BACKFILL"] == "SUPERSEDED"
    assert fields["STRUCTURAL_POOL_FLOOR"] == "NOT_DERIVED"
    assert fields["STRUCTURAL_BACKFILL_REQUESTS"] == "NONE"
    assert fields["POOL_N"] == "NOT_DERIVED"
    assert fields["EXISTING_RECIPE_COUNT_IS_NOT_POOL_TARGET"] == "YES"
    assert fields["EXISTING_RECIPE_COUNT_IS_NOT_CAPACITY_CAP"] == "YES"
    assert fields["FINAL_SELECTION_BOUNDS_APPLY_ONLY_TO_FINAL_SELECTION"] == "YES"
    assert fields["SOURCE_EXISTING_RECIPE_LANES"] == "40"
    assert fields["SOURCE_ADDITIONAL_AUTHORABLE_LANES"] == "15"
    assert fields["SOURCE_EXHAUSTED_LANES"] == "49"
    assert "SOURCE_LANES" not in fields
    assert fields["REMOTE_PUSH_AT_BASELINE_SEAL"] == "NO"
    assert "REMOTE_PUSH" not in fields


def test_receipt_forbids_unresolved_base_sweeps_and_unconditional_backfill() -> None:
    fields = _fields()
    assert fields["BASE_INFEASIBLE_REMOVAL_SWEEP"] == "FORBIDDEN"
    assert fields["BASE_UNKNOWN_REMOVAL_SWEEP"] == "FORBIDDEN"
    assert fields["BACKFILL_WITHOUT_TYPED_DEFICIT"] == "FORBIDDEN"
    assert fields["BACKFILL_WITHOUT_FEASIBILITY_EVIDENCE"] == "FORBIDDEN"


def test_receipt_records_document_only_roadmap_and_no_finalization() -> None:
    fields = _fields()
    assert fields["RES126_EXECUTION_SCOPE"] == "SUPERSEDED"
    assert fields["PROPOSED_NEW_LINEAR_ROOT"] == "RES-115"
    assert fields["HUMAN_REVIEW_RUN"] == "NO"
    assert fields["PROTECTED_MEMBERSHIP_PERSISTED"] == "NO"
    assert fields["BENCHMARK_FROZEN"] == "NO"
    assert fields["BASELINE_READY_FOR_PR"] == "YES"
    assert fields["SOLVER_RUNS"] == "UNIT_TEST_FIXTURES_ONLY"
    assert fields["PRODUCTION_POOL_MATERIALIZATION"] == "NOT_RUN"
    assert fields["PRODUCTION_POOL_QUALIFICATION"] == "NOT_RUN"
    assert fields["PRODUCTION_ALL_REMOVAL_QUALIFICATION"] == "NOT_RUN"
    assert fields["FULL_CI"] == (
        "PASS (./scripts/ci.sh at 8fcf670; 1273 passed in 811.70s; wall 815.70s)"
    )
    assert fields["PYTEST"] == "PASS (1273 passed)"
    assert fields["TEST_COUNT"] == "1273"
    assert fields["QA_TRACKED_MUTATION"] == "NONE"
    text = RECEIPT.read_text(encoding="utf-8")
    assert "RES-126 = `CANCEL_SUPERSEDED`" in text
    assert "A2b is created or activated only when A2 emits an actual typed deficit" in text
    assert "Integrate completed PSE V1 into the main/default release line" in text


def test_receipt_records_pr38_review_authority_fixes() -> None:
    fields = _fields()
    assert fields["HISTORICAL_RECIPE_AUTHORITY_BINDING"] == (
        "EXACT_CANONICAL_RECIPE_FROM_INVENTORY_BOUND_INPUT"
    )
    assert fields["GOVERNED_LANE_AUTHORITY_BINDING"] == "EXACT_ORIGIN_SPECIFIC_IDENTITY"
    assert fields["GOVERNED_SOURCE_SELECTION"] == "CURRENT_PRODUCTION_SOURCE_UNIVERSE_ONLY"
    assert fields["V1_2_SUPPLY_EXECUTION_AUTHORITY"] == "REJECTED"
    assert fields["POOL_RECEIPT_STATUS_INVARIANTS"] == "SEALED"
