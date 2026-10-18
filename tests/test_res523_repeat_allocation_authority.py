from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import FrozenInstanceError, fields, replace
from pathlib import Path
from typing import Any, cast

import pytest
from scripts import res523_repeat_allocation_authority as authority

from dynamislm.benchmark.production import _candidate_id
from dynamislm.qualification.repeat_allocation import (
    RepeatAllocationApprovalReceipt,
    RepeatAllocationPlan,
    RepeatAllocationProtocol,
    RepeatApprovalStatus,
    RepeatOrdinalFailureError,
    derive_planned_seed_block_identity,
    derive_repeat_candidate_id,
    fail_closed_on_ordinal,
    repeat_collision_policy,
    validate_repeat_allocation_approval,
)
from dynamislm.serialization import canonical_hash


def _report() -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(authority.REPORT_PATH.read_text(encoding="utf-8")))


def _replacement_report() -> dict[str, Any]:
    return cast(
        dict[str, Any],
        json.loads(authority.REPLACEMENT_REPORT_PATH.read_text(encoding="utf-8")),
    )


def _typed_protocol(report: dict[str, Any]) -> RepeatAllocationProtocol:
    record = dict(report["repeat_protocol"])
    record["approval_status"] = RepeatApprovalStatus(record["approval_status"])
    return RepeatAllocationProtocol(**record)


def _typed_plan(report: dict[str, Any]) -> RepeatAllocationPlan:
    record = dict(report["allocation_plan"])
    record["authorized_ordinals"] = tuple(record["authorized_ordinals"])
    record["owner_approval_status"] = RepeatApprovalStatus(record["owner_approval_status"])
    return RepeatAllocationPlan(**record)


def _typed_receipt(report: dict[str, Any]) -> RepeatAllocationApprovalReceipt:
    record = dict(report["approval_receipt"])
    record["owner_approval_status"] = RepeatApprovalStatus(record["owner_approval_status"])
    return RepeatAllocationApprovalReceipt(**record)


def test_protocol_is_generic_and_defaults_to_pending_approval() -> None:
    report = _report()
    source = dict(report["repeat_protocol"])
    expected_digest = source.pop("authority_digest")
    source.pop("approval_required")
    source.pop("approval_status")

    protocol = RepeatAllocationProtocol(**source)

    assert protocol.approval_required is True
    assert protocol.approval_status is RepeatApprovalStatus.PENDING
    assert protocol.authority_digest == expected_digest
    assert "requested_count" not in {item.name for item in fields(RepeatAllocationProtocol)}
    assert "authorized_ordinals" not in {item.name for item in fields(RepeatAllocationProtocol)}
    with pytest.raises(ValueError, match="authority digest does not match"):
        replace(protocol, generator_version="2.0.0")


def test_plan_binds_exact_res407_structural_proof_and_ordinal_inventory() -> None:
    report = _report()
    plan = _typed_plan(report)

    assert plan.status == "PROPOSED"
    assert plan.lane_id == authority.LANE_ID
    assert (plan.capability, plan.family, plan.locked_split) == ("C08", "F05", "PUBLIC_DEVELOPMENT")
    assert plan.requested_count == 48
    assert plan.authorized_ordinals == tuple(range(48))
    assert plan.structural_status == "FEASIBLE"
    assert plan.structural_min_additions == 48
    assert plan.cardinality_optimality == "PROVEN"
    assert (plan.k_minus_1, plan.k_minus_1_status) == (47, "INFEASIBLE")
    assert (plan.k, plan.k_status) == (48, "FEASIBLE")
    assert report["allocation_plan_digest"] == plan.allocation_plan_digest
    assert canonical_hash(plan.plan_payload()) == plan.allocation_plan_digest
    with pytest.raises(FrozenInstanceError):
        plan.status = "FROZEN"  # type: ignore[misc]
    with pytest.raises(ValueError, match="digest does not match"):
        replace(plan, family="F06")


def test_ordinal_derivations_are_unique_order_independent_and_repeatable_across_processes() -> None:
    report = authority.build_report()
    protocol = _typed_protocol(report)
    plan = _typed_plan(report)

    def derive(ordinals: tuple[int, ...]) -> tuple[dict[int, str], dict[int, str]]:
        seeds: dict[int, str] = {}
        candidates: dict[int, str] = {}
        for ordinal in ordinals:
            seeds[ordinal] = derive_planned_seed_block_identity(
                protocol,
                plan.allocation_authority_digest,
                lane_id=plan.lane_id,
                capability=plan.capability,
                family=plan.family,
                locked_split=plan.locked_split,
                ordinal=ordinal,
            )
            candidates[ordinal] = derive_repeat_candidate_id(
                protocol,
                plan,
                seed_block_identity=seeds[ordinal],
                ordinal=ordinal,
            )
        return seeds, candidates

    forward = derive(plan.authorized_ordinals)
    reverse = derive(tuple(reversed(plan.authorized_ordinals)))
    assert forward == reverse
    assert len(set(forward[0].values())) == 48
    assert len(set(forward[1].values())) == 48
    assert (
        canonical_hash(tuple(forward[0][i] for i in range(48)))
        == report["seed_block_identity_inventory_digest"]
    )
    assert (
        canonical_hash(tuple(forward[1][i] for i in range(48)))
        == report["candidate_id_inventory_digest"]
    )
    with pytest.raises(ValueError, match="scope differs"):
        derive_planned_seed_block_identity(
            protocol,
            plan.allocation_authority_digest,
            lane_id="wrong-lane",
            capability=plan.capability,
            family=plan.family,
            locked_split=plan.locked_split,
            ordinal=0,
        )
    with pytest.raises(ValueError, match="scope differs"):
        derive_repeat_candidate_id(
            protocol,
            plan,
            seed_block_identity=forward[0][0],
            ordinal=48,
        )

    process = subprocess.run(
        [
            sys.executable,
            "-c",
            "from scripts.res523_repeat_allocation_authority import build_report; "
            "print(build_report()['report_digest'])",
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        check=True,
        text=True,
    )
    assert process.stdout.strip() == report["report_digest"]


def test_candidate_namespace_does_not_collide_with_historical_ids() -> None:
    report = authority.build_report()
    protocol = _typed_protocol(report)
    plan = _typed_plan(report)
    candidate_ids = tuple(
        derive_repeat_candidate_id(
            protocol,
            plan,
            seed_block_identity=derive_planned_seed_block_identity(
                protocol,
                plan.allocation_authority_digest,
                lane_id=plan.lane_id,
                capability=plan.capability,
                family=plan.family,
                locked_split=plan.locked_split,
                ordinal=ordinal,
            ),
            ordinal=ordinal,
        )
        for ordinal in plan.authorized_ordinals
    )
    historical = set(authority._historical_candidate_ids())
    historical.add(f"{authority.HISTORICAL_CANDIDATE_ID_PREFIX}C08:F05:PUBLIC_DEVELOPMENT")

    assert all(item.startswith(authority.NEW_CANDIDATE_ID_PREFIX) for item in candidate_ids)
    assert all(
        not item.startswith(authority.HISTORICAL_CANDIDATE_ID_PREFIX) for item in candidate_ids
    )
    assert not set(candidate_ids).intersection(historical)
    assert report["historical_namespace_collisions"] == 0
    assert report["historical_namespace_check"]["namespace_prefixes_disjoint"] is True


def test_failed_ordinal_stops_without_substitution() -> None:
    plan = _typed_plan(_report())
    with pytest.raises(RepeatOrdinalFailureError, match="ordinal 17 failed") as error:
        fail_closed_on_ordinal(17, "exact-shingle conflict")

    assert "do not substitute an ordinal" in str(error.value)
    assert "new versioned allocation decision" in str(error.value)
    assert plan.authorized_ordinals == tuple(range(48))
    assert 48 not in plan.authorized_ordinals


def test_owner_approval_freezes_and_binds_only_the_exact_approved_plan() -> None:
    report = _report()
    plan = report["allocation_plan"]
    receipt = report["approval_receipt"]
    typed_receipt = _typed_receipt(report)

    assert report["allocation_plan_status"] == "FROZEN"
    assert report["owner_approval_required"] is True
    assert report["owner_approval_status"] == "APPROVED"
    assert report["allocation_plan_digest"] == authority.APPROVED_PLAN_DIGEST
    assert report["repeat_protocol_digest"] == authority.APPROVED_PROTOCOL_DIGEST
    assert report["collision_policy_digest"] == authority.APPROVED_COLLISION_POLICY_DIGEST
    assert report["allocation_plan_count"] == 48
    assert report["allocation_ordinal_range"] == "0..47"
    assert plan["authorized_ordinals"] == list(range(48))
    assert plan["status"] == "PROPOSED"
    assert plan["owner_approval_status"] == "PENDING"
    assert canonical_hash(
        {key: value for key, value in plan.items() if key != "allocation_plan_digest"}
    ) == (authority.APPROVED_PLAN_DIGEST)
    assert receipt["allocation_plan_status"] == "FROZEN"
    assert receipt["owner_approval_status"] == "APPROVED"
    assert receipt["reviewed_allocation_plan_digest"] == authority.APPROVED_PLAN_DIGEST
    assert receipt["reviewed_repeat_protocol_digest"] == authority.APPROVED_PROTOCOL_DIGEST
    assert receipt["approval_receipt_digest"] == report["approval_receipt_digest"]
    assert receipt["approval_receipt_digest"] == canonical_hash(
        {key: value for key, value in receipt.items() if key != "approval_receipt_digest"}
    )
    assert receipt["owner_identity"] is None
    assert receipt["approval_timestamp"] is None
    assert receipt["cryptographic_signature"] is None
    validate_repeat_allocation_approval(
        typed_receipt,
        allocation_plan_digest=authority.APPROVED_PLAN_DIGEST,
        repeat_protocol_digest=authority.APPROVED_PROTOCOL_DIGEST,
    )
    with pytest.raises(ValueError, match="does not bind this allocation plan digest"):
        validate_repeat_allocation_approval(
            typed_receipt,
            allocation_plan_digest="sha256:" + "0" * 64,
            repeat_protocol_digest=authority.APPROVED_PROTOCOL_DIGEST,
        )
    with pytest.raises(ValueError, match="does not bind this repeat protocol digest"):
        validate_repeat_allocation_approval(
            typed_receipt,
            allocation_plan_digest=authority.APPROVED_PLAN_DIGEST,
            repeat_protocol_digest="sha256:" + "0" * 64,
        )


def test_collision_policy_fails_closed_for_every_materialization_conflict() -> None:
    policy = repeat_collision_policy()
    checks = cast(dict[str, str], policy["checks"])

    assert set(checks.values()) == {"STOP"}
    assert policy["failure_action"] == "STOP_AND_INVALIDATE_THE_WHOLE_MATERIALIZATION_ATTEMPT"
    assert cast(str, policy["ordinal_replacement"]).startswith("FORBIDDEN;")
    assert canonical_hash(policy) == _report()["collision_policy_digest"]


def test_approval_is_recorded_without_materializing_candidates_or_seeds() -> None:
    report = _report()

    assert report["repeat_protocol"]["approval_status"] == "PENDING"
    assert report["allocation_plan"]["owner_approval_status"] == "PENDING"
    assert report["owner_approval_required"] is True
    assert report["owner_approval_status"] == "APPROVED"
    assert report["ready_for_owner_approval"] is False
    assert report["candidate_materialization_invoked"] is False
    assert report["concrete_candidates_generated"] == 0
    assert report["seeds_materialized"] == 0
    assert report["ready_for_materialization"] is True
    assert "candidate_ids" not in report and "seed_blocks" not in report
    serialized = json.dumps(report, sort_keys=True)
    assert "pse-repeat-block-" not in serialized
    assert not re.search(r"PSE-V1-REPEAT-CANDIDATE:[0-9a-f]{64}", serialized)


def test_replacement_uses_production_valid_ids_and_remains_pending() -> None:
    report = authority.build_replacement_report()
    persisted = _replacement_report()
    identities = report["planned_identities"]
    candidate_ids = tuple(item["candidate_id"] for item in identities)
    plan = _typed_plan(report)

    assert report == persisted
    assert report["report_digest"] == canonical_hash(
        {key: value for key, value in report.items() if key != "report_digest"}
    )
    assert report["allocation_plan_digest"] == plan.allocation_plan_digest
    assert report["candidate_id_derivation_version"] == "PSE-REPEAT-CANDIDATE-ID@2.0.0"
    assert all(item.startswith(authority.REPLACEMENT_CANDIDATE_ID_PREFIX) for item in candidate_ids)
    assert all(
        len(item) <= report["production_validation"]["maximum_id_length"] for item in candidate_ids
    )
    for candidate_id in candidate_ids:
        _candidate_id(candidate_id)
    assert report["production_validation"]["identity_valid_count"] == 48
    assert report["production_validation"]["recipe_valid_count"] == 48
    assert report["historical_collision_check"]["historical_id_collisions"] == 0
    assert report["supersession"]["original_ids_rejected_by_production_identity_validator"] == 48
    assert report["supersession"]["replacement_supersedes_original_for_execution"] is True
    assert report["supersession"]["approval_transfer"].startswith("NONE;")
    assert (plan.status, plan.owner_approval_status) == ("PROPOSED", RepeatApprovalStatus.PENDING)
    assert report["owner_approval_status"] == "PENDING"
    assert report["ready_for_owner_approval"] is True
    assert report["ready_for_materialization"] is False
    assert report["concrete_candidates_generated"] == 0
    assert report["seeds_materialized"] == 0
    assert report["structural_compatibility"]["selection_features_preserved"] is True
    assert report["structural_compatibility"]["structural_proof_assumptions_preserved"] is True
    assert report["digest_dependency_check"]["circular_dependency"] is False
    assert _report()["allocation_plan_digest"] == authority.APPROVED_PLAN_DIGEST
    assert _report()["report_digest"] == authority.ORIGINAL_REPORT_DIGEST


def test_persisted_report_is_digest_bound_and_matches_the_deterministic_builder() -> None:
    report = _report()

    assert report == authority.build_report()
    assert report["report_digest"] == canonical_hash(
        {key: value for key, value in report.items() if key != "report_digest"}
    )
