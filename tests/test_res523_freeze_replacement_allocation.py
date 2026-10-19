from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from scripts import res523_freeze_replacement_allocation as freeze
from scripts import res523_repeat_allocation_authority as authority

from dynamislm.qualification.repeat_allocation import (
    RepeatAllocationApprovalReceipt,
    RepeatApprovalStatus,
    validate_repeat_allocation_approval,
)
from dynamislm.serialization import canonical_hash

_REPOSITORY = Path(__file__).resolve().parents[1]


def _attestation() -> dict[str, Any]:
    path = _REPOSITORY / freeze.REPORT_PATH
    return cast(dict[str, Any], json.loads(path.read_text()))


def test_freeze_attestation_binds_exact_linear_approval_without_rewriting_plan() -> None:
    attestation = freeze.build_attestation()
    saved = _attestation()
    proposal = json.loads((_REPOSITORY / authority.REPLACEMENT_REPORT_PATH).read_text())
    receipt_record = dict(attestation["approval_receipt"])
    receipt_record["owner_approval_status"] = RepeatApprovalStatus(
        receipt_record["owner_approval_status"]
    )
    receipt = RepeatAllocationApprovalReceipt(**receipt_record)

    assert attestation == saved
    assert attestation["attestation_digest"] == canonical_hash(
        {key: value for key, value in attestation.items() if key != "attestation_digest"}
    )
    assert attestation["freeze_status"] == "FROZEN"
    assert attestation["owner_approval_status"] == "APPROVED"
    assert (
        attestation["approved_allocation"]["allocation_plan_digest"]
        == freeze.REPLACEMENT_PLAN_DIGEST
    )
    assert attestation["approved_allocation"]["digest_bound_plan_content_modified"] is False
    assert proposal["allocation_plan_status"] == "PROPOSED"
    assert proposal["owner_approval_status"] == "PENDING"
    assert attestation["approval_source"]["comment_id"] == freeze.APPROVAL_COMMENT_ID
    assert attestation["approval_source"]["comment_body"] == freeze.APPROVAL_BODY
    assert attestation["approval_source"]["cryptographic_signature"] is None
    validate_repeat_allocation_approval(
        receipt,
        allocation_plan_digest=freeze.REPLACEMENT_PLAN_DIGEST,
        repeat_protocol_digest=freeze.REPEAT_PROTOCOL_DIGEST,
    )
    assert attestation["historical_allocation_preservation"]["preserved_unchanged"] is True
    assert attestation["execution_gate"]["ready_for_res407_execution"] is False
    assert attestation["execution_gate"]["concrete_candidates_generated"] == 0
    assert attestation["execution_gate"]["seeds_materialized"] == 0
