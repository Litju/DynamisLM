"""Payload-free, hash-bound inventory of current authority and reserve lanes."""

from __future__ import annotations

import enum
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from dynamislm.benchmark.constants import CAPABILITY_IDS, FAMILY_IDS, CaseOrigin, SplitName
from dynamislm.benchmark.selection_contracts import FeatureKind
from dynamislm.serialization import canonical_hash, register_serializable_type

_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
AUTHORITY_SUPPLY_SCHEMA = "PSE-V1-AUTHORITY-SUPPLY-INVENTORY@1.1.0"
AUTHORITY_SUPPLY_INVENTORY_PATH = "qualification/RES-383/authority-supply-inventory.v1.1.json"


class AuthoritySupplyKind(enum.StrEnum):
    RES71_REFERENCE_CASE = "RES71_REFERENCE_CASE"
    RES71_OPERATION = "RES71_OPERATION"
    SOURCE_DOCUMENT = "SOURCE_DOCUMENT"
    SOURCE_FAMILY = "SOURCE_FAMILY"
    SYNTHETIC_GENERATOR = "SYNTHETIC_GENERATOR"
    EXPERT_BATCH = "EXPERT_BATCH"
    MUTATION_LINEAGE = "MUTATION_LINEAGE"
    AUTHORING_SEED_BLOCK = "AUTHORING_SEED_BLOCK"


class LaneCapacityStatus(enum.StrEnum):
    AVAILABLE = "AVAILABLE"
    RULE_GOVERNED = "RULE_GOVERNED"
    METADATA_REQUIRED = "METADATA_REQUIRED"
    EXHAUSTED = "EXHAUSTED"


class ReserveDeficitKind(enum.StrEnum):
    STRUCTURAL_COUNT = "STRUCTURAL_COUNT"
    EXACT_BASELINE_INFEASIBLE = "EXACT_BASELINE_INFEASIBLE"
    EXACT_REMOVAL_INFEASIBLE = "EXACT_REMOVAL_INFEASIBLE"
    EXACT_ORACLE_UNKNOWN = "EXACT_ORACLE_UNKNOWN"
    METADATA_UNRESOLVED = "METADATA_UNRESOLVED"


class BackfillRequestKind(enum.StrEnum):
    CONSTRAINT_MINIMUM = "CONSTRAINT_MINIMUM"
    EXACT_SELECTION_INTERACTION = "EXACT_SELECTION_INTERACTION"
    CANDIDATE_METADATA = "CANDIDATE_METADATA"


@register_serializable_type
@dataclass(frozen=True, slots=True)
class ReserveDeficitV1:
    deficit_kind: ReserveDeficitKind
    constraint_id: str | None = None
    scenario_digest: str | None = None
    removed_candidate_digest: str | None = None
    required_count: int | None = None
    observed_count: int | None = None
    affected_constraint_ids: tuple[str, ...] = ()
    deficit_digest: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "deficit_kind", ReserveDeficitKind(self.deficit_kind))
        for digest in (self.scenario_digest, self.removed_candidate_digest):
            if digest is not None and _SHA256.fullmatch(digest) is None:
                raise ValueError("reserve deficit contains a malformed scenario digest")
        if self.constraint_id is not None and not self.constraint_id.strip():
            raise ValueError("reserve deficit constraint ID cannot be blank")
        if (self.required_count is None) != (self.observed_count is None):
            raise ValueError("reserve deficit counts must be supplied together")
        if any(
            value is not None and value < 0 for value in (self.required_count, self.observed_count)
        ):
            raise ValueError("reserve deficit counts must be non-negative")
        if self.affected_constraint_ids != tuple(
            sorted(set(self.affected_constraint_ids), key=str.encode)
        ):
            raise ValueError("affected constraint IDs must be unique and canonical")
        computed = canonical_hash(
            {
                "deficit_kind": self.deficit_kind,
                "constraint_id": self.constraint_id,
                "scenario_digest": self.scenario_digest,
                "removed_candidate_digest": self.removed_candidate_digest,
                "required_count": self.required_count,
                "observed_count": self.observed_count,
                "affected_constraint_ids": self.affected_constraint_ids,
            }
        )
        if self.deficit_digest and self.deficit_digest != computed:
            raise ValueError("reserve deficit digest does not match its evidence")
        object.__setattr__(self, "deficit_digest", computed)


@register_serializable_type
@dataclass(frozen=True, slots=True)
class BackfillRequestV1:
    request_kind: BackfillRequestKind
    deficit_digest: str
    lane_ids: tuple[str, ...]
    requested_capacity: int | None
    required_origin: CaseOrigin | None = None
    constraint_id: str | None = None
    split: SplitName | None = None
    feature_kind: FeatureKind | None = None
    feature_key: tuple[str, ...] = ()
    scenario_digest: str | None = None
    requires_candidate_metadata: bool = False
    request_digest: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "request_kind", BackfillRequestKind(self.request_kind))
        if self.required_origin is not None:
            object.__setattr__(self, "required_origin", CaseOrigin(self.required_origin))
        if self.split is not None:
            object.__setattr__(self, "split", SplitName(self.split))
        if self.feature_kind is not None:
            object.__setattr__(self, "feature_kind", FeatureKind(self.feature_kind))
        if _SHA256.fullmatch(self.deficit_digest) is None:
            raise ValueError("backfill request must bind a typed reserve deficit")
        if self.requested_capacity is not None and self.requested_capacity < 1:
            raise ValueError("backfill request capacity must be positive when quantified")
        if self.lane_ids != tuple(sorted(set(self.lane_ids), key=str.encode)):
            raise ValueError("backfill request lanes must be unique and canonical")
        if self.scenario_digest is not None and _SHA256.fullmatch(self.scenario_digest) is None:
            raise ValueError("backfill request contains a malformed scenario digest")
        computed = canonical_hash(
            {
                "request_kind": self.request_kind,
                "deficit_digest": self.deficit_digest,
                "lane_ids": self.lane_ids,
                "requested_capacity": self.requested_capacity,
                "required_origin": self.required_origin,
                "constraint_id": self.constraint_id,
                "split": self.split,
                "feature_kind": self.feature_kind,
                "feature_key": self.feature_key,
                "scenario_digest": self.scenario_digest,
                "requires_candidate_metadata": self.requires_candidate_metadata,
            }
        )
        if self.request_digest and self.request_digest != computed:
            raise ValueError("backfill request digest does not match its scope")
        object.__setattr__(self, "request_digest", computed)


class SupplyAssessmentStatus(enum.StrEnum):
    BACKFILL_REQUIRED = "BACKFILL_REQUIRED"
    METADATA_REQUIRED = "METADATA_REQUIRED"
    AUTHORITY_EXPANSION_REQUIRED = "AUTHORITY_EXPANSION_REQUIRED"


@register_serializable_type
@dataclass(frozen=True, slots=True)
class AuthoritySupplyAssessmentV1:
    assessment_version: str
    status: SupplyAssessmentStatus
    inventory_digest: str
    planned_candidate_count: int
    materialized_candidate_count: int
    usable_reserve_capacity_count: int
    final_target_count: int
    known_structural_pool_floor: int
    derived_pool_n: int | None
    backfill_requests: tuple[BackfillRequestV1, ...]
    unresolved_deficits: tuple[ReserveDeficitV1, ...]
    exact_qualification_status: SupplyAssessmentStatus
    authority_inventory_complete: bool
    capacity_scope_complete: bool
    assessment_digest: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", SupplyAssessmentStatus(self.status))
        object.__setattr__(
            self,
            "exact_qualification_status",
            SupplyAssessmentStatus(self.exact_qualification_status),
        )
        if _SHA256.fullmatch(self.inventory_digest) is None:
            raise ValueError("supply assessment must bind an authority inventory")
        counts = (
            self.planned_candidate_count,
            self.materialized_candidate_count,
            self.usable_reserve_capacity_count,
            self.final_target_count,
            self.known_structural_pool_floor,
        )
        if any(value < 0 for value in counts):
            raise ValueError("supply assessment counts must be non-negative")
        if self.derived_pool_n is not None and self.derived_pool_n < self.final_target_count:
            raise ValueError("derived pool size cannot be below the final target")
        if self.status is SupplyAssessmentStatus.AUTHORITY_EXPANSION_REQUIRED and (
            not self.authority_inventory_complete
            or not self.capacity_scope_complete
            or not any(not request.lane_ids for request in self.backfill_requests)
        ):
            raise ValueError(
                "authority expansion requires complete proof of exhausted governed lanes"
            )
        computed = canonical_hash(
            {
                "assessment_version": self.assessment_version,
                "status": self.status,
                "inventory_digest": self.inventory_digest,
                "planned_candidate_count": self.planned_candidate_count,
                "materialized_candidate_count": self.materialized_candidate_count,
                "usable_reserve_capacity_count": self.usable_reserve_capacity_count,
                "final_target_count": self.final_target_count,
                "known_structural_pool_floor": self.known_structural_pool_floor,
                "derived_pool_n": self.derived_pool_n,
                "backfill_requests": self.backfill_requests,
                "unresolved_deficits": self.unresolved_deficits,
                "exact_qualification_status": self.exact_qualification_status,
                "authority_inventory_complete": self.authority_inventory_complete,
                "capacity_scope_complete": self.capacity_scope_complete,
            }
        )
        if self.assessment_digest and self.assessment_digest != computed:
            raise ValueError("supply assessment digest does not match its contents")
        object.__setattr__(self, "assessment_digest", computed)


@register_serializable_type
@dataclass(frozen=True, slots=True)
class AuthoritySupplyAtomV1:
    atom_id: str
    authority_kind: AuthoritySupplyKind
    authority_ref: str
    authority_digest: str
    atom_digest: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "authority_kind", AuthoritySupplyKind(self.authority_kind))
        if not self.atom_id.strip() or not self.authority_ref.strip():
            raise ValueError("authority supply atoms require stable IDs and named authority")
        if _SHA256.fullmatch(self.authority_digest) is None:
            raise ValueError("authority supply atom has a malformed authority digest")
        computed = canonical_hash(
            (self.atom_id, self.authority_kind, self.authority_ref, self.authority_digest)
        )
        if self.atom_digest and self.atom_digest != computed:
            raise ValueError("authority supply atom digest does not match its binding")
        object.__setattr__(self, "atom_digest", computed)


@register_serializable_type
@dataclass(frozen=True, slots=True)
class ReserveCandidateLaneV1:
    lane_id: str
    origin_class: CaseOrigin
    authority_ref: str
    authority_digest: str
    capacity_unit: str
    existing_planned_capacity: int
    available_capacity: int | None
    capacity_status: LaneCapacityStatus
    capacity_rule: str | None = None
    supported_cells: tuple[tuple[str, str], ...] = ()
    isolation_identity_digests: tuple[str, ...] = ()
    lane_digest: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "origin_class", CaseOrigin(self.origin_class))
        object.__setattr__(self, "capacity_status", LaneCapacityStatus(self.capacity_status))
        if not all((self.lane_id.strip(), self.authority_ref.strip(), self.capacity_unit.strip())):
            raise ValueError("reserve lanes require stable IDs, authority, and a capacity unit")
        if _SHA256.fullmatch(self.authority_digest) is None:
            raise ValueError("reserve lane has a malformed authority digest")
        if self.existing_planned_capacity < 0:
            raise ValueError("reserve lane planned capacity must be non-negative")
        if self.capacity_status is LaneCapacityStatus.AVAILABLE:
            if self.available_capacity is None or self.available_capacity < 1:
                raise ValueError("available lane requires positive quantified capacity")
        elif self.capacity_status is LaneCapacityStatus.EXHAUSTED:
            if self.available_capacity != 0:
                raise ValueError("exhausted lane must have zero available capacity")
        elif self.available_capacity is not None or not (self.capacity_rule or "").strip():
            raise ValueError("unquantified lane requires a governing rule and no numeric capacity")
        if (
            not self.supported_cells and self.capacity_status is not LaneCapacityStatus.EXHAUSTED
        ) or any(
            not isinstance(cell, tuple)
            or len(cell) != 2
            or cell[0] not in CAPABILITY_IDS
            or cell[1] not in FAMILY_IDS
            for cell in self.supported_cells
        ):
            raise ValueError("available reserve lanes require exact frozen capability-family cells")
        if self.supported_cells != tuple(sorted(set(self.supported_cells))):
            raise ValueError("supported_cells must use unique canonical ordering")
        if self.isolation_identity_digests != tuple(sorted(set(self.isolation_identity_digests))):
            raise ValueError("lane isolation identities must be unique and canonical")
        if any(_SHA256.fullmatch(value) is None for value in self.isolation_identity_digests):
            raise ValueError("lane isolation identity digest is malformed")
        computed = canonical_hash(
            {
                "lane_id": self.lane_id,
                "origin_class": self.origin_class,
                "authority_ref": self.authority_ref,
                "authority_digest": self.authority_digest,
                "capacity_unit": self.capacity_unit,
                "existing_planned_capacity": self.existing_planned_capacity,
                "available_capacity": self.available_capacity,
                "capacity_status": self.capacity_status,
                "capacity_rule": self.capacity_rule,
                "supported_cells": self.supported_cells,
                "isolation_identity_digests": self.isolation_identity_digests,
            }
        )
        if self.lane_digest and self.lane_digest != computed:
            raise ValueError("reserve lane digest does not match its authority and capacity")
        object.__setattr__(self, "lane_digest", computed)

    @property
    def may_author_backfill(self) -> bool:
        return self.capacity_status is not LaneCapacityStatus.EXHAUSTED


@register_serializable_type
@dataclass(frozen=True, slots=True)
class AuthoritySupplyInventoryV1:
    schema_version: str
    atoms: tuple[AuthoritySupplyAtomV1, ...]
    reserve_candidate_lanes: tuple[ReserveCandidateLaneV1, ...]
    planned_origin_counts: tuple[tuple[CaseOrigin, int], ...]
    planned_mutation_lineage_count: int
    materialized_candidate_count: int
    evidence_bindings: tuple[tuple[str, str], ...]
    authority_inventory_complete: bool
    capacity_scope_complete: bool
    inventory_digest: str = ""

    def __post_init__(self) -> None:
        if self.schema_version != AUTHORITY_SUPPLY_SCHEMA:
            raise ValueError("unknown authority supply inventory schema")
        atom_ids = tuple(item.atom_id for item in self.atoms)
        lane_ids = tuple(item.lane_id for item in self.reserve_candidate_lanes)
        if atom_ids != tuple(sorted(set(atom_ids), key=str.encode)):
            raise ValueError("authority supply atoms must be unique and canonically ordered")
        if lane_ids != tuple(sorted(set(lane_ids), key=str.encode)):
            raise ValueError("reserve candidate lanes must be unique and canonically ordered")
        counts = tuple((CaseOrigin(origin), count) for origin, count in self.planned_origin_counts)
        if counts != tuple(sorted(counts, key=lambda item: item[0].value.encode())):
            raise ValueError("planned origin counts must use canonical origin order")
        if len({origin for origin, _count in counts}) != len(counts) or any(
            count < 0 for _origin, count in counts
        ):
            raise ValueError("planned origin counts must be unique and non-negative")
        object.__setattr__(self, "planned_origin_counts", counts)
        if self.planned_mutation_lineage_count < 0 or self.materialized_candidate_count < 0:
            raise ValueError("inventory counts must be non-negative")
        bindings = tuple(sorted(self.evidence_bindings, key=lambda item: item[0].encode()))
        if bindings != self.evidence_bindings or len({name for name, _ in bindings}) != len(
            bindings
        ):
            raise ValueError("inventory evidence bindings must be unique and canonical")
        if any(not name.strip() or _SHA256.fullmatch(digest) is None for name, digest in bindings):
            raise ValueError("inventory evidence bindings contain a malformed digest")
        computed = canonical_hash(
            {
                "schema_version": self.schema_version,
                "atoms": self.atoms,
                "reserve_candidate_lanes": self.reserve_candidate_lanes,
                "planned_origin_counts": self.planned_origin_counts,
                "planned_mutation_lineage_count": self.planned_mutation_lineage_count,
                "materialized_candidate_count": self.materialized_candidate_count,
                "evidence_bindings": self.evidence_bindings,
                "authority_inventory_complete": self.authority_inventory_complete,
                "capacity_scope_complete": self.capacity_scope_complete,
            }
        )
        if self.inventory_digest and self.inventory_digest != computed:
            raise ValueError("authority supply inventory digest does not match its contents")
        object.__setattr__(self, "inventory_digest", computed)

    @property
    def planned_candidate_count(self) -> int:
        return sum(count for _origin, count in self.planned_origin_counts)


def _opaque_id(kind: str, value: str) -> str:
    return f"{kind}:{hashlib.sha256(value.encode('utf-8')).hexdigest()}"


def _jsonl_rows(payload: bytes, name: str) -> tuple[dict[str, object], ...]:
    try:
        rows = tuple(json.loads(line) for line in payload.decode("utf-8").splitlines() if line)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"authority inventory manifest is invalid: {name}") from exc
    if any(not isinstance(row, dict) for row in rows):
        raise ValueError(f"authority inventory manifest rows must be objects: {name}")
    return rows


def build_live_authority_supply_inventory(
    *,
    repository_root: str | Path,
    production_root: str | Path,
) -> AuthoritySupplyInventoryV1:
    """Inventory actual authority inputs without reading or creating candidate prose."""

    import hashlib as _hashlib
    from collections import Counter

    from dynamislm.benchmark.constants import CaseOrigin, SplitName
    from dynamislm.benchmark.production_authoring import (
        PRODUCTION_SYNTHETIC_GENERATOR_DIGEST,
        PRODUCTION_SYNTHETIC_GENERATORS,
        ProductionAuthoringInputsV1,
        _engine_slot_specs,
        _semantic_slot_specs,
        _synthetic_slot_specs,
        production_authoring_input_digest,
    )
    from dynamislm.benchmark.production_store import (
        DEFAULT_PRODUCTION_ROOT,
        read_external_production_json,
    )
    from dynamislm.qualification import (
        RES71_SEALED_REFERENCE_DIGEST,
        ReferenceCaseStatus,
        build_registered_operation_inventory,
        get_reference_cases,
        reference_case_digest,
        validate_reference_cases,
        validate_registered_operation_inventory,
    )
    from dynamislm.qualification.res115_authoring import _production_authoring_engine_references

    repository = Path(repository_root).resolve()
    root = Path(production_root or DEFAULT_PRODUCTION_ROOT).resolve()
    if root.is_relative_to(repository):
        raise ValueError("authority supply inventory inputs must remain outside Git")
    inputs, input_file_digest, _size = read_external_production_json(
        "production/authoring_plan/private_inputs.json",
        ProductionAuthoringInputsV1,
        repository_root=repository,
        production_root=root,
    )
    if (
        inputs.input_digest != production_authoring_input_digest(inputs)
        or inputs.synthetic_generator_registry_digest != PRODUCTION_SYNTHETIC_GENERATOR_DIGEST
    ):
        raise ValueError("production authoring inputs do not bind the live generator authority")

    manifest_names = (
        "manifests/accepted.jsonl",
        "manifests/source_families_001.jsonl",
        "manifests/source_tag_support_evidence_001.jsonl",
    )
    manifest_bytes: dict[str, bytes] = {}
    manifest_rows: dict[str, tuple[dict[str, object], ...]] = {}
    for name in manifest_names:
        path = root / name
        if path.is_symlink() or not path.resolve().is_relative_to(root) or not path.is_file():
            raise ValueError(f"authority inventory manifest is unavailable: {name}")
        payload = path.read_bytes()
        manifest_bytes[name] = payload
        manifest_rows[name] = _jsonl_rows(payload, name)

    accepted_name, family_name, support_name = manifest_names
    accepted = manifest_rows[accepted_name]
    families = manifest_rows[family_name]
    support_rows = manifest_rows[support_name]
    family_ids = {row.get("family_id") for row in families}
    if len(family_ids) != len(families) or None in family_ids:
        raise ValueError("source-family inventory has missing or duplicate IDs")
    support_by_pmcid: dict[str, dict[str, object]] = {}
    for row in support_rows:
        pmcid = row.get("pmcid")
        if not isinstance(pmcid, str) or pmcid in support_by_pmcid:
            raise ValueError("source support inventory has a missing or duplicate PMCID")
        support_by_pmcid[pmcid] = row
    if set(support_by_pmcid) != {row.get("pmcid") for row in accepted}:
        raise ValueError("source-tag support rows do not exactly cover accepted source documents")
    accepted_by_document: dict[str, dict[str, object]] = {}
    for row in accepted:
        retained = row.get("retained_source_artifact")
        family = row.get("source_family_identity")
        if (
            row.get("disposition") != "ACCEPTED"
            or not isinstance(retained, dict)
            or not isinstance(family, dict)
            or family.get("source_family_id") not in family_ids
            or family.get("family_resolution_status") in {"UNRESOLVED", "AMBIGUOUS", "UNKNOWN"}
        ):
            raise ValueError("accepted-source inventory contains an unresolved authority row")
        document_id = retained.get("document_identity_id")
        pmcid = row.get("pmcid")
        if not isinstance(document_id, str) or document_id in accepted_by_document:
            raise ValueError("accepted-source inventory has a missing or duplicate document ID")
        if not isinstance(pmcid, str) or pmcid not in support_by_pmcid:
            raise ValueError("accepted source is missing its source-tag support row")
        accepted_by_document[document_id] = row

    selected_documents = {item.document_id for item in inputs.source_selections}
    if (
        len(inputs.source_selections) != 40
        or not selected_documents.issubset(accepted_by_document)
        or len(selected_documents) != len(inputs.source_selections)
    ):
        raise ValueError("current source authoring inputs do not bind 40 unique accepted documents")
    for selection in inputs.source_selections:
        retained = accepted_by_document[selection.document_id]["source_family_identity"]
        assert isinstance(retained, dict)
        if retained.get("source_family_id") != selection.source_family_id:
            raise ValueError("production source selection has a stale source-family binding")

    semantic_ids = {item[0] for item in _semantic_slot_specs()}
    engine_slots = _engine_slot_specs()
    engine_ids = {item[0] for item in engine_slots}
    synthetic_slots = _synthetic_slot_specs()
    synthetic_ids = {item[0] for item in synthetic_slots}
    mutation_ids = {
        child_id for lineage in inputs.mutation_lineages for child_id in lineage.child_candidate_ids
    }
    scenario_ids = {candidate_id for candidate_id, _seed in inputs.scenario_seeds}
    if (
        scenario_ids != semantic_ids | engine_ids
        or set(candidate_id for candidate_id, _seed in inputs.synthetic_seed_blocks)
        != synthetic_ids
        or set(candidate_id for candidate_id, _seed in inputs.mutation_seed_blocks) != mutation_ids
    ):
        raise ValueError("production seed inputs differ from the live authoring-slot registries")
    if set().union(semantic_ids, engine_ids, synthetic_ids, mutation_ids) & selected_documents:
        raise ValueError("production lane identities overlap across authority classes")

    references = get_reference_cases()
    validate_reference_cases(references)
    operations = build_registered_operation_inventory()
    validate_registered_operation_inventory(operations)
    reference_digest = reference_case_digest(references)
    if reference_digest != RES71_SEALED_REFERENCE_DIGEST:
        raise ValueError("RES-71 reference inventory differs from its sealed digest")

    atoms: list[AuthoritySupplyAtomV1] = []

    def atom(kind: AuthoritySupplyKind, stable_id: str, authority_ref: str, digest: str) -> None:
        atoms.append(
            AuthoritySupplyAtomV1(
                atom_id=_opaque_id(kind.value.lower(), stable_id),
                authority_kind=kind,
                authority_ref=authority_ref,
                authority_digest=digest,
            )
        )

    for reference in references:
        atom(
            AuthoritySupplyKind.RES71_REFERENCE_CASE,
            reference.case_id,
            "RES-71 sealed reference inventory",
            canonical_hash(reference),
        )
    for operation in operations:
        atom(
            AuthoritySupplyKind.RES71_OPERATION,
            operation.operation_id,
            "RES-71 registered-operation inventory",
            canonical_hash(operation),
        )

    accepted_manifest_digest = (
        "sha256:" + _hashlib.sha256(manifest_bytes[accepted_name]).hexdigest()
    )
    support_manifest_digest = "sha256:" + _hashlib.sha256(manifest_bytes[support_name]).hexdigest()
    family_manifest_digest = "sha256:" + _hashlib.sha256(manifest_bytes[family_name]).hexdigest()
    for family in families:
        atom(
            AuthoritySupplyKind.SOURCE_FAMILY,
            str(family["family_id"]),
            "Phase-A resolved source-family registry",
            canonical_hash((family_manifest_digest, family)),
        )
    source_lanes: list[ReserveCandidateLaneV1] = []
    for document_id, row in accepted_by_document.items():
        source_digest = canonical_hash(
            (accepted_manifest_digest, row, support_by_pmcid[str(row["pmcid"])])
        )
        atom(
            AuthoritySupplyKind.SOURCE_DOCUMENT,
            document_id,
            "Phase-A accepted-source and support registries",
            source_digest,
        )
        if document_id in selected_documents:
            continue
        support = support_by_pmcid[str(row["pmcid"])]
        capabilities = support.get("candidate_capabilities_retained")
        families_retained = support.get("candidate_benchmark_families_retained")
        if not isinstance(capabilities, list) or not isinstance(families_retained, list):
            raise ValueError("source support row has malformed retained applicability")
        family = row["source_family_identity"]
        assert isinstance(family, dict)
        family_id = family.get("source_family_id")
        if not isinstance(family_id, str):
            raise ValueError("accepted source is missing its resolved family identity")
        lane = ReserveCandidateLaneV1(
            lane_id=_opaque_id("source", document_id),
            origin_class=CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION,
            authority_ref="Phase-A accepted document with retained support evidence",
            authority_digest=source_digest,
            capacity_unit="source-document-backed-candidate-slot",
            existing_planned_capacity=0,
            available_capacity=1 if capabilities and families_retained else 0,
            capacity_status=(
                LaneCapacityStatus.AVAILABLE
                if capabilities and families_retained
                else LaneCapacityStatus.EXHAUSTED
            ),
            supported_cells=tuple(
                sorted(
                    {
                        (capability, family)
                        for capability in capabilities
                        for family in families_retained
                    }
                )
            ),
            isolation_identity_digests=tuple(
                sorted(
                    {
                        canonical_hash(("SOURCE_DOCUMENT", document_id)),
                        canonical_hash(("SOURCE_FAMILY", family_id)),
                    }
                )
            ),
        )
        source_lanes.append(lane)

    generator_lanes: list[ReserveCandidateLaneV1] = []
    split_by_slot = {candidate_id: split for candidate_id, _family, split in synthetic_slots}
    for generator in PRODUCTION_SYNTHETIC_GENERATORS:
        generator_digest = canonical_hash(generator)
        atom(
            AuthoritySupplyKind.SYNTHETIC_GENERATOR,
            generator.generator_id + "@" + generator.version + ":" + generator.generator_family,
            "registered production synthetic-generator registry",
            generator_digest,
        )
        split = next(
            (item for item in SplitName if generator.generator_family.endswith(item.value.lower())),
            None,
        )
        if split is None:
            raise ValueError("registered synthetic generator has an unknown split family")
        current_blocks = sum(
            split_by_slot[candidate_id] is split
            for candidate_id, _seed in inputs.synthetic_seed_blocks
        )
        generator_lanes.append(
            ReserveCandidateLaneV1(
                lane_id="synthetic:" + generator.generator_family,
                origin_class=CaseOrigin.DETERMINISTIC_SYNTHETIC,
                authority_ref="registered split-family synthetic generator",
                authority_digest=generator_digest,
                capacity_unit="unique split-locked synthetic seed block",
                existing_planned_capacity=current_blocks,
                available_capacity=None,
                capacity_status=LaneCapacityStatus.RULE_GOVERNED,
                capacity_rule="registered generator and split-family seed-block namespace",
                supported_cells=tuple(
                    sorted(
                        {
                            ("C08", family)
                            for _candidate_id, family, slot_split in synthetic_slots
                            if slot_split is split
                        }
                    )
                ),
                isolation_identity_digests=tuple(
                    sorted(
                        {
                            canonical_hash(
                                ("SYNTHETIC_GENERATOR", generator.generator_id, generator.version)
                            ),
                            canonical_hash(("GENERATOR_FAMILY", generator.generator_family)),
                            canonical_hash(("SYNTHETIC_SPLIT_LOCK", split)),
                        }
                    )
                ),
            )
        )

    reference_by_id = {item.case_id: item for item in references}
    engine_value_reference = _production_authoring_engine_references()[0]
    value_references = tuple(
        item for item in references if item.status is ReferenceCaseStatus.VALUE
    )
    engine_slots_by_lane: dict[tuple[str, str, str], list[str]] = {}
    for candidate_id, capability, family, slot in engine_slots:
        if capability == "C18":
            reference_id = (
                "res71-nonfinite-unit-refusal" if family == "F06" else "res71-bpt-mpv-refusal"
            )
        elif capability == "C08":
            reference_id = engine_value_reference.case_id
        else:
            value_index = (slot + (0 if family == "F05" else 1)) % len(value_references)
            reference_id = value_references[value_index].case_id
        reference = reference_by_id[reference_id]
        if capability != "C18" and reference.operation_id is None:
            raise ValueError("numeric engine slot has no registered RES-71 operation")
        engine_slots_by_lane.setdefault((capability, family, reference_id), []).append(candidate_id)
    engine_lanes = []
    for (capability, family, reference_id), slot_ids in engine_slots_by_lane.items():
        if not set(slot_ids).issubset(scenario_ids):
            raise ValueError("engine reference lane differs from current private seed slots")
        reference = reference_by_id[reference_id]
        lane_digest = canonical_hash(
            (
                reference_digest,
                canonical_hash(reference),
                capability,
                family,
                tuple(sorted(slot_ids, key=str.encode)),
            )
        )
        engine_lanes.append(
            ReserveCandidateLaneV1(
                lane_id=f"engine:{capability}:{family}:{reference_id}",
                origin_class=CaseOrigin.DETERMINISTIC_ENGINE_DERIVED,
                authority_ref="RES-71 reference, operation, and frozen production cell mapping",
                authority_digest=lane_digest,
                capacity_unit="planned RES-71 engine candidate slot",
                existing_planned_capacity=len(slot_ids),
                available_capacity=0,
                capacity_status=LaneCapacityStatus.EXHAUSTED,
                supported_cells=((capability, family),),
                isolation_identity_digests=(
                    canonical_hash(("RES71_ENGINE_REFERENCE_CASE", reference_id)),
                ),
            )
        )

    expert_lanes: list[ReserveCandidateLaneV1] = []
    semantic_cell_by_id = {
        candidate_id: (capability, family)
        for candidate_id, capability, family, _slot in _semantic_slot_specs()
    }
    for batch in inputs.expert_batches:
        batch_digest = canonical_hash(batch)
        atom(
            AuthoritySupplyKind.EXPERT_BATCH,
            batch.author_batch_id,
            "production expert batch and template registry",
            batch_digest,
        )
        expert_lanes.append(
            ReserveCandidateLaneV1(
                lane_id=_opaque_id("expert-batch", batch.author_batch_id),
                origin_class=CaseOrigin.EXPERT_AUTHORED_SEMANTIC,
                authority_ref="existing bounded expert batch/template/isolation authority",
                authority_digest=batch_digest,
                capacity_unit="planned expert-semantic slot",
                existing_planned_capacity=len(batch.candidate_ids),
                available_capacity=0,
                capacity_status=LaneCapacityStatus.EXHAUSTED,
                supported_cells=tuple(
                    sorted(
                        {semantic_cell_by_id[candidate_id] for candidate_id in batch.candidate_ids}
                    )
                ),
                isolation_identity_digests=tuple(
                    sorted(
                        {
                            canonical_hash(("EXPERT_BATCH", batch.author_batch_id)),
                            canonical_hash(("PROTOCOL_TEMPLATE", batch.protocol_template_id)),
                            canonical_hash(
                                ("EXPERT_ISOLATION_CLUSTER", batch.isolation_cluster_id)
                            ),
                        }
                    )
                ),
            )
        )

    mutation_lanes: list[ReserveCandidateLaneV1] = []
    parent_cell_by_id = semantic_cell_by_id
    mutation_seed_ids = {candidate_id for candidate_id, _seed in inputs.mutation_seed_blocks}
    for lineage in inputs.mutation_lineages:
        lineage_digest = canonical_hash(lineage)
        atom(
            AuthoritySupplyKind.MUTATION_LINEAGE,
            lineage.lineage_id,
            "existing mutation root/operator/lineage authority",
            lineage_digest,
        )
        child_seed_count = len(mutation_seed_ids.intersection(lineage.child_candidate_ids))
        parent_cell = parent_cell_by_id.get(lineage.parent_candidate_id)
        if parent_cell is None:
            raise ValueError("mutation parent does not resolve to a frozen PSE cell")
        mutation_lanes.append(
            ReserveCandidateLaneV1(
                lane_id=_opaque_id("mutation-lineage", lineage.lineage_id),
                origin_class=CaseOrigin.ADVERSARIAL_MUTATION,
                authority_ref="existing mutation parent, operator, and lineage authority",
                authority_digest=lineage_digest,
                capacity_unit="mutation child seed block",
                existing_planned_capacity=child_seed_count,
                available_capacity=None,
                capacity_status=LaneCapacityStatus.METADATA_REQUIRED,
                capacity_rule=(
                    "additional child capacity requires candidate-level parent and cell metadata"
                ),
                isolation_identity_digests=tuple(
                    sorted(
                        {
                            canonical_hash(("MUTATION_PARENT", lineage.parent_candidate_id)),
                            canonical_hash(("MUTATION_LINEAGE", lineage.lineage_id)),
                        }
                    )
                ),
                supported_cells=(parent_cell,),
            )
        )

    for candidate_id, seed in (
        *inputs.scenario_seeds,
        *inputs.synthetic_seed_blocks,
        *inputs.mutation_seed_blocks,
    ):
        atom(
            AuthoritySupplyKind.AUTHORING_SEED_BLOCK,
            candidate_id,
            "current private production authoring seed inputs",
            canonical_hash((inputs.batch_id, candidate_id, seed)),
        )

    counts = Counter(
        {
            CaseOrigin.EXPERT_AUTHORED_SEMANTIC: len(semantic_ids),
            CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION: len(inputs.source_selections),
            CaseOrigin.DETERMINISTIC_ENGINE_DERIVED: len(engine_ids),
            CaseOrigin.DETERMINISTIC_SYNTHETIC: len(inputs.synthetic_seed_blocks),
            CaseOrigin.ADVERSARIAL_MUTATION: len(inputs.mutation_seed_blocks),
        }
    )
    planned_counts = tuple(sorted(counts.items(), key=lambda item: item[0].value.encode()))
    candidate_key = hashlib.sha256(inputs.batch_id.encode("utf-8")).hexdigest()[:24]
    candidate_directory = root / "production" / "candidates" / candidate_key
    if candidate_directory.is_symlink():
        raise ValueError("production candidate directory cannot be a symlink")
    materialized_count = (
        sum(path.is_file() for path in candidate_directory.iterdir())
        if candidate_directory.is_dir()
        else 0
    )

    bindings = {
        "RES71_REFERENCE_INVENTORY": reference_digest,
        "RES71_OPERATION_INVENTORY": canonical_hash(operations),
        "PHASE_A_ACCEPTED_SOURCE_MANIFEST": accepted_manifest_digest,
        "PHASE_A_SOURCE_FAMILY_MANIFEST": family_manifest_digest,
        "PHASE_A_SOURCE_SUPPORT_MANIFEST": support_manifest_digest,
        "PRODUCTION_AUTHORING_INPUT_FILE": input_file_digest,
        "PRODUCTION_AUTHORING_INPUT_CONTENT": inputs.input_digest,
        "SYNTHETIC_GENERATOR_REGISTRY": PRODUCTION_SYNTHETIC_GENERATOR_DIGEST,
    }
    return AuthoritySupplyInventoryV1(
        schema_version=AUTHORITY_SUPPLY_SCHEMA,
        atoms=tuple(sorted(atoms, key=lambda item: item.atom_id.encode())),
        reserve_candidate_lanes=tuple(
            sorted(
                (
                    *source_lanes,
                    *generator_lanes,
                    *engine_lanes,
                    *expert_lanes,
                    *mutation_lanes,
                ),
                key=lambda item: item.lane_id.encode(),
            )
        ),
        planned_origin_counts=planned_counts,
        planned_mutation_lineage_count=len(inputs.mutation_lineages),
        materialized_candidate_count=materialized_count,
        evidence_bindings=tuple(sorted(bindings.items(), key=lambda item: item[0].encode())),
        authority_inventory_complete=True,
        capacity_scope_complete=False,
    )


def write_live_authority_supply_inventory(
    inventory: AuthoritySupplyInventoryV1,
    *,
    repository_root: str | Path,
    production_root: str | Path,
) -> tuple[str, str, int]:
    """Persist the typed inventory only in external qualification storage."""

    from dynamislm.benchmark.qualification_store import write_external_qualification_json

    return write_external_qualification_json(
        inventory,
        AUTHORITY_SUPPLY_INVENTORY_PATH,
        repository_root=repository_root,
        qualification_root=production_root,
    )


__all__ = [
    "AUTHORITY_SUPPLY_INVENTORY_PATH",
    "AUTHORITY_SUPPLY_SCHEMA",
    "AuthoritySupplyAssessmentV1",
    "AuthoritySupplyAtomV1",
    "AuthoritySupplyInventoryV1",
    "AuthoritySupplyKind",
    "BackfillRequestKind",
    "BackfillRequestV1",
    "LaneCapacityStatus",
    "ReserveCandidateLaneV1",
    "ReserveDeficitKind",
    "ReserveDeficitV1",
    "SupplyAssessmentStatus",
    "build_live_authority_supply_inventory",
    "write_live_authority_supply_inventory",
]
