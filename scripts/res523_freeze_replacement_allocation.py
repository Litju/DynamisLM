#!/usr/bin/env python3
"""Record RES-523 owner approval as a separate freeze attestation."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

_REPOSITORY = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(_REPOSITORY), str(_REPOSITORY / "src")]

from dynamislm.benchmark.production import (  # noqa: E402
    PRODUCTION_CANDIDATE_ID_PREFIX,
    _candidate_id,
)
from dynamislm.qualification.repeat_allocation import (  # noqa: E402
    RepeatAllocationApprovalReceipt,
    RepeatApprovalStatus,
    validate_repeat_allocation_approval,
)
from dynamislm.serialization import canonical_hash  # noqa: E402
from scripts import res523_repeat_allocation_authority as authority  # noqa: E402

REPORT_PATH = Path(
    "reports/performance_science_eval/res523_repeat_allocation_freeze_attestation.json"
)
SCHEMA_VERSION = "RES523-REPLACEMENT-FREEZE-ATTESTATION@1.0.0"
REPLACEMENT_PLAN_DIGEST = "sha256:b0c3bc4a07c167a8bb266c082d65854cd50a2f82dbae5f5f18d1e57bb7f53b82"
REPEAT_PROTOCOL_DIGEST = "sha256:a836d62a1aa47aa2c738182282278c9e818a122bac3224ba51b3de922b17ceb4"
APPROVAL_COMMENT_ID = "68ed8414-91bb-4666-b315-d0fa33dd7009"
APPROVAL_CREATED_AT = "2026-10-18T06:44:09.660Z"
APPROVAL_AUTHOR = "Julio Rodriguez"
APPROVAL_BODY = (
    "OWNER APPROVAL — The project owner explicitly approved the RES-523 **replacement** "
    "allocation plan in the conversation on 2026-10-18:\n\n"
    "> I approve RES-523 replacement allocation plan "
    "sha256:b0c3bc4a07c167a8bb266c082d65854cd50a2f82dbae5f5f18d1e57bb7f53b82 for exactly 48 "
    "C08:F05/Public ordinals 0" + "\u2013" + "47 under candidate-ID derivation "
    "PSE-REPEAT-CANDIDATE-ID@2.0.0.\n\n"
    "This approval is exact and finite; it supersedes **only the executable allocation** "
    "previously approved under digest "
    "sha256:240edcc8afe8f44c9d7fbd82b6c46b4e40408e329cf943d949beeabaa90f4398, which remains "
    "preserved as historical evidence. Owner approval authorizes freezing the replacement "
    "plan as specified, **not** changing its digest, count, ordinals, lane, cell, split, or "
    "derivation version. The approval is not a cryptographic signature and must not be "
    "represented as one. Next gate: verify proposal/digest, freeze and commit approval "
    "binding, run tests/CI, review/merge RES-523, then separately execute RES-407 "
    "materialization with fail-closed validation. No candidates or seeds have been generated "
    "as part of this approval."
)


def build_attestation() -> dict[str, Any]:
    path = _REPOSITORY / authority.REPLACEMENT_REPORT_PATH
    proposal: Any = json.loads(path.read_text(encoding="utf-8"))
    recomputed = authority.build_replacement_report()
    candidate_ids = tuple(item["candidate_id"] for item in proposal.get("planned_identities", ()))
    if (
        proposal != recomputed
        or proposal.get("allocation_plan_digest") != REPLACEMENT_PLAN_DIGEST
        or proposal.get("candidate_id_derivation_version") != "PSE-REPEAT-CANDIDATE-ID@2.0.0"
        or proposal.get("repeat_protocol_digest") != REPEAT_PROTOCOL_DIGEST
        or proposal.get("allocation_plan_count") != 48
        or proposal.get("ordinal_inventory") != list(range(48))
        or proposal.get("allocation_plan_status") != "PROPOSED"
        or proposal.get("owner_approval_status") != "PENDING"
        or len(candidate_ids) != 48
        or len(set(candidate_ids)) != 48
        or proposal.get("candidate_id_inventory_digest") != canonical_hash(candidate_ids)
        or proposal.get("historical_collision_check", {}).get("historical_id_collisions") != 0
        or proposal.get("concrete_candidates_generated") != 0
        or proposal.get("seeds_materialized") != 0
        or not all(item.startswith(PRODUCTION_CANDIDATE_ID_PREFIX) for item in candidate_ids)
    ):
        raise ValueError("the exact approved RES-523 replacement proposal failed verification")
    for candidate_id in candidate_ids:
        _candidate_id(candidate_id)

    receipt = RepeatAllocationApprovalReceipt(
        schema_version="RES523-ALLOCATION-APPROVAL-RECEIPT@2.0.0",
        reviewed_allocation_plan_digest=REPLACEMENT_PLAN_DIGEST,
        reviewed_repeat_protocol_digest=REPEAT_PROTOCOL_DIGEST,
        allocation_plan_status="FROZEN",
        owner_approval_required=True,
        owner_approval_status=RepeatApprovalStatus.APPROVED,
        approval_basis=(
            f"Explicit owner approval recorded in Linear RES-523 comment {APPROVAL_COMMENT_ID} "
            f"at {APPROVAL_CREATED_AT}; the exact comment body is preserved in this attestation. "
            "This record is not a cryptographic signature."
        ),
    )
    validate_repeat_allocation_approval(
        receipt,
        allocation_plan_digest=REPLACEMENT_PLAN_DIGEST,
        repeat_protocol_digest=REPEAT_PROTOCOL_DIGEST,
    )
    body: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "mission": "RES-523 freeze approved production-compatible replacement allocation",
        "freeze_status": "FROZEN",
        "owner_approval_required": True,
        "owner_approval_status": RepeatApprovalStatus.APPROVED.value,
        "approval_source": {
            "system": "Linear",
            "issue_identifier": "RES-523",
            "issue_url": "https://linear.app/alignerr-cmj/issue/RES-523/p4a-r2c-freeze-c08-synthetic-repeat-allocation-authority",
            "comment_id": APPROVAL_COMMENT_ID,
            "recorded_at": APPROVAL_CREATED_AT,
            "author_display_name": APPROVAL_AUTHOR,
            "comment_body": APPROVAL_BODY,
            "comment_body_digest": canonical_hash(APPROVAL_BODY),
            "cryptographic_signature": None,
        },
        "approved_allocation": {
            "proposal_ref": authority.REPLACEMENT_REPORT_PATH.as_posix(),
            "proposal_report_digest": proposal["report_digest"],
            "allocation_plan_digest": REPLACEMENT_PLAN_DIGEST,
            "repeat_protocol_digest": REPEAT_PROTOCOL_DIGEST,
            "candidate_id_derivation_version": "PSE-REPEAT-CANDIDATE-ID@2.0.0",
            "candidate_id_inventory_digest": proposal["candidate_id_inventory_digest"],
            "candidate_id_count": len(candidate_ids),
            "candidate_ids_validated_by_production": len(candidate_ids),
            "historical_id_collisions": 0,
            "count": 48,
            "ordinals": list(range(48)),
            "lane_id": proposal["allocation_plan"]["lane_id"],
            "cell": ["C08", "F05"],
            "split": "PUBLIC_DEVELOPMENT",
            "proposal_payload_status": "PROPOSED",
            "proposal_payload_approval_status": "PENDING",
            "digest_bound_plan_content_modified": False,
        },
        "approval_receipt": receipt.to_record(),
        "approval_receipt_digest": receipt.approval_receipt_digest,
        "historical_allocation_preservation": {
            "original_allocation_plan_digest": authority.APPROVED_PLAN_DIGEST,
            "original_report_digest": authority.ORIGINAL_REPORT_DIGEST,
            "preserved_unchanged": True,
            "superseded_for_execution_by": REPLACEMENT_PLAN_DIGEST,
        },
        "execution_gate": {
            "freeze_authority_integrated": False,
            "ready_for_res407_execution": False,
            "materialization_invoked": False,
            "concrete_candidates_generated": 0,
            "seeds_materialized": 0,
            "next_gate": (
                "integrate and verify this freeze authority before RES-407 materialization"
            ),
        },
    }
    return {**body, "attestation_digest": canonical_hash(body)}


def main() -> int:
    attestation = build_attestation()
    path = _REPOSITORY / REPORT_PATH
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if existing != attestation:
            raise ValueError("refusing to overwrite a different freeze attestation")
    else:
        path.write_text(json.dumps(attestation, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"FROZEN_PLAN_DIGEST={attestation['approved_allocation']['allocation_plan_digest']}")
    print(f"ATTESTATION_DIGEST={attestation['attestation_digest']}")
    print("FREEZE_STATUS=FROZEN")
    print("OWNER_APPROVAL_STATUS=APPROVED")
    print("READY_FOR_RES407_EXECUTION=NO; INTEGRATION_AND_VERIFICATION_REQUIRED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
