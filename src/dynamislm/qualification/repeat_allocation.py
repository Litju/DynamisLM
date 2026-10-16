"""Immutable contracts for versioned, approval-gated repeat allocations."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import NoReturn

from dynamislm.serialization import canonical_hash, register_serializable_type

_SHA256 = re.compile(r"sha256:[0-9a-f]{64}\Z")


class RepeatApprovalStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


def _require_text(name: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be non-empty")


def _require_digest(name: str, value: str) -> None:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError(f"{name} must be a canonical SHA-256 digest")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class RepeatAllocationProtocol:
    """Versioned repeat rules; campaign count belongs to a separate plan."""

    schema_version: str
    protocol_version: str
    parent_lane_id: str
    parent_lane_authority_ref: str
    parent_lane_authority_digest: str
    parent_lane_digest: str
    parent_archetype_digest: str
    generator_id: str
    generator_family: str
    generator_version: str
    allowed_capability: str
    allowed_family: str
    allowed_locked_split: str
    ordinal_semantics_version: str
    seed_block_derivation_version: str
    candidate_id_derivation_version: str
    collision_policy_version: str
    approval_required: bool = True
    approval_status: RepeatApprovalStatus = RepeatApprovalStatus.PENDING
    authority_digest: str = ""

    def authority_payload(self) -> dict[str, object]:
        return {key: value for key, value in asdict(self).items() if key != "authority_digest"}

    def to_record(self) -> dict[str, object]:
        return asdict(self)

    def __post_init__(self) -> None:
        if not self.authority_digest:
            object.__setattr__(self, "authority_digest", canonical_hash(self.authority_payload()))
        for name in (
            "schema_version",
            "protocol_version",
            "parent_lane_id",
            "parent_lane_authority_ref",
            "generator_id",
            "generator_family",
            "generator_version",
            "allowed_capability",
            "allowed_family",
            "allowed_locked_split",
            "ordinal_semantics_version",
            "seed_block_derivation_version",
            "candidate_id_derivation_version",
            "collision_policy_version",
        ):
            _require_text(name, getattr(self, name))
        for name in (
            "parent_lane_authority_digest",
            "parent_lane_digest",
            "parent_archetype_digest",
            "authority_digest",
        ):
            _require_digest(name, getattr(self, name))
        if type(self.approval_required) is not bool or not self.approval_required:
            raise ValueError("repeat allocation requires owner approval")
        if not isinstance(self.approval_status, RepeatApprovalStatus):
            raise ValueError("approval_status must be a RepeatApprovalStatus")
        if canonical_hash(self.authority_payload()) != self.authority_digest:
            raise ValueError("repeat protocol authority digest does not match its payload")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class RepeatAllocationPlan:
    """One exact immutable plan with output identities represented by commitments."""

    schema_version: str
    status: str
    lane_id: str
    capability: str
    family: str
    locked_split: str
    requested_count: int
    authorized_ordinals: tuple[int, ...]
    structural_comparison_ref: str
    structural_comparison_report_digest: str
    structural_result_ref: str
    structural_report_digest: str
    generator_qualification_ref: str
    generator_qualification_report_digest: str
    prior_repeat_authority_ref: str
    prior_repeat_authority_report_digest: str
    prior_repeat_authority_status: str
    structural_status: str
    structural_min_additions: int
    cardinality_optimality: str
    k_minus_1: int
    k_minus_1_status: str
    k_minus_1_trial_digest: str
    k: int
    k_status: str
    k_trial_digest: str
    parent_lane_authority_ref: str
    parent_lane_authority_digest: str
    parent_lane_digest: str
    parent_archetype_digest: str
    generator_id: str
    generator_family: str
    generator_version: str
    repeat_protocol_digest: str
    ordinal_semantics_version: str
    seed_block_derivation_version: str
    candidate_id_derivation_version: str
    collision_policy_version: str
    collision_policy_digest: str
    historical_candidate_id_inventory_digest: str
    historical_candidate_id_count: int
    historical_namespace_collision_count: int
    allocation_authority_digest: str
    seed_block_identity_inventory_digest: str
    owner_approval_required: bool
    owner_approval_status: RepeatApprovalStatus
    allocation_plan_digest: str

    def authority_payload(self) -> dict[str, object]:
        record = asdict(self)
        return {
            key: value
            for key, value in record.items()
            if key
            not in {
                "allocation_authority_digest",
                "seed_block_identity_inventory_digest",
                "allocation_plan_digest",
            }
        }

    def plan_payload(self) -> dict[str, object]:
        return {
            key: value for key, value in asdict(self).items() if key != "allocation_plan_digest"
        }

    def to_record(self) -> dict[str, object]:
        record = asdict(self)
        record["authorized_ordinals"] = list(self.authorized_ordinals)
        return record

    def __post_init__(self) -> None:
        for name in (
            "schema_version",
            "status",
            "lane_id",
            "capability",
            "family",
            "locked_split",
            "structural_comparison_ref",
            "structural_result_ref",
            "generator_qualification_ref",
            "prior_repeat_authority_ref",
            "prior_repeat_authority_status",
            "structural_status",
            "cardinality_optimality",
            "k_minus_1_status",
            "k_status",
            "parent_lane_authority_ref",
            "generator_id",
            "generator_family",
            "generator_version",
            "ordinal_semantics_version",
            "seed_block_derivation_version",
            "candidate_id_derivation_version",
            "collision_policy_version",
        ):
            _require_text(name, getattr(self, name))
        for name in (
            "structural_comparison_report_digest",
            "structural_report_digest",
            "generator_qualification_report_digest",
            "prior_repeat_authority_report_digest",
            "k_minus_1_trial_digest",
            "k_trial_digest",
            "parent_lane_authority_digest",
            "parent_lane_digest",
            "parent_archetype_digest",
            "repeat_protocol_digest",
            "collision_policy_digest",
            "historical_candidate_id_inventory_digest",
            "allocation_authority_digest",
            "seed_block_identity_inventory_digest",
            "allocation_plan_digest",
        ):
            _require_digest(name, getattr(self, name))
        if self.status != "PROPOSED":
            raise ValueError("a repeat allocation plan must remain PROPOSED")
        if self.prior_repeat_authority_status != "UNKNOWN":
            raise ValueError("the parent RES-407 repeat authority must remain UNKNOWN")
        if (
            type(self.requested_count) is not int
            or self.requested_count < 1
            or not isinstance(self.authorized_ordinals, tuple)
            or any(type(ordinal) is not int for ordinal in self.authorized_ordinals)
            or self.authorized_ordinals != tuple(range(self.requested_count))
        ):
            raise ValueError("authorized_ordinals must be the zero-based requested inventory")
        if (
            type(self.structural_min_additions) is not int
            or type(self.k_minus_1) is not int
            or type(self.k) is not int
            or self.structural_min_additions != self.requested_count
            or self.k_minus_1 != self.requested_count - 1
            or self.k != self.requested_count
            or self.structural_status != "FEASIBLE"
            or self.cardinality_optimality != "PROVEN"
            or self.k_minus_1_status != "INFEASIBLE"
            or self.k_status != "FEASIBLE"
        ):
            raise ValueError("structural proof does not establish the requested minimum")
        if (
            type(self.historical_candidate_id_count) is not int
            or self.historical_candidate_id_count < 0
            or type(self.historical_namespace_collision_count) is not int
            or self.historical_namespace_collision_count != 0
        ):
            raise ValueError("historical namespace check must be complete and collision-free")
        if type(self.owner_approval_required) is not bool or not self.owner_approval_required:
            raise ValueError("repeat allocation requires owner approval")
        if self.owner_approval_status is not RepeatApprovalStatus.PENDING:
            raise ValueError("a proposed repeat allocation must have approval status PENDING")
        if canonical_hash(self.authority_payload()) != self.allocation_authority_digest:
            raise ValueError("allocation authority digest does not match its payload")
        if canonical_hash(self.plan_payload()) != self.allocation_plan_digest:
            raise ValueError("allocation plan digest does not match its payload")


class RepeatOrdinalFailureError(ValueError):
    """A planned ordinal failed a frozen materialization check."""


def repeat_collision_policy() -> dict[str, object]:
    return {
        "schema_version": "PSE-REPEAT-COLLISION-POLICY@1.0.0",
        "checks": {
            "candidate_id_collision": "STOP",
            "seed_block_collision": "STOP",
            "duplicate_payload_where_prohibited": "STOP",
            "exact_shingle_conflict": "STOP",
            "contamination_conflict": "STOP",
            "wrong_feature_vector": "STOP",
            "unexpected_colocation_or_relation_behavior": "STOP",
            "invalid_generator_result": "STOP",
        },
        "failure_action": "STOP_AND_INVALIDATE_THE_WHOLE_MATERIALIZATION_ATTEMPT",
        "ordinal_replacement": "FORBIDDEN; requires a new versioned allocation decision",
    }


def fail_closed_on_ordinal(ordinal: int, reason: str) -> NoReturn:
    if type(ordinal) is not int or ordinal < 0:
        raise ValueError("failed ordinal must be a non-negative integer")
    _require_text("failure reason", reason)
    raise RepeatOrdinalFailureError(
        f"ordinal {ordinal} failed ({reason}); stop the attempt, do not substitute an ordinal, "
        "and require a new versioned allocation decision"
    )


def derive_planned_seed_block_identity(
    protocol: RepeatAllocationProtocol,
    allocation_authority_digest: str,
    *,
    lane_id: str,
    capability: str,
    family: str,
    locked_split: str,
    ordinal: int,
) -> str:
    _require_digest("allocation_authority_digest", allocation_authority_digest)
    if (lane_id, capability, family, locked_split) != (
        protocol.parent_lane_id,
        protocol.allowed_capability,
        protocol.allowed_family,
        protocol.allowed_locked_split,
    ):
        raise ValueError("planned seed-block scope differs from the repeat protocol")
    if type(ordinal) is not int or ordinal < 0:
        raise ValueError("ordinal must be a non-negative integer")
    basis = {
        "derivation_version": protocol.seed_block_derivation_version,
        "repeat_protocol_digest": protocol.authority_digest,
        "allocation_authority_digest": allocation_authority_digest,
        "lane_id": lane_id,
        "cell": (capability, family),
        "locked_split": locked_split,
        "generator_version": protocol.generator_version,
        "ordinal_semantics_version": protocol.ordinal_semantics_version,
        "ordinal": ordinal,
    }
    return f"pse-repeat-block-{canonical_hash(basis).removeprefix('sha256:')}"


def derive_repeat_candidate_id(
    protocol: RepeatAllocationProtocol,
    plan: RepeatAllocationPlan,
    *,
    seed_block_identity: str,
    ordinal: int,
) -> str:
    _require_text("seed_block_identity", seed_block_identity)
    if (
        plan.repeat_protocol_digest != protocol.authority_digest
        or (
            plan.lane_id,
            plan.capability,
            plan.family,
            plan.locked_split,
            plan.generator_id,
            plan.generator_family,
            plan.generator_version,
        )
        != (
            protocol.parent_lane_id,
            protocol.allowed_capability,
            protocol.allowed_family,
            protocol.allowed_locked_split,
            protocol.generator_id,
            protocol.generator_family,
            protocol.generator_version,
        )
        or type(ordinal) is not int
        or ordinal not in plan.authorized_ordinals
    ):
        raise ValueError("candidate identity scope differs from the repeat allocation plan")
    basis = {
        "derivation_version": plan.candidate_id_derivation_version,
        "repeat_protocol_digest": protocol.authority_digest,
        "allocation_plan_digest": plan.allocation_plan_digest,
        "lane_id": plan.lane_id,
        "cell": (plan.capability, plan.family),
        "locked_split": plan.locked_split,
        "ordinal": ordinal,
        "seed_block_identity": seed_block_identity,
        "generator_id": plan.generator_id,
        "generator_family": plan.generator_family,
        "generator_version": plan.generator_version,
    }
    return f"PSE-V1-REPEAT-CANDIDATE:{canonical_hash(basis).removeprefix('sha256:')}"
