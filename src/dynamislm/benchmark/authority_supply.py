"""Payload-free, hash-bound inventory of current authority and reserve lanes."""

from __future__ import annotations

import enum
import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from dynamislm.benchmark.constants import CAPABILITY_IDS, FAMILY_IDS, CaseOrigin, SplitName
from dynamislm.benchmark.selection_contracts import FeatureKind
from dynamislm.qualification.res115_authoring import SourceCellSelectionV1
from dynamislm.serialization import canonical_hash, register_serializable_type

if TYPE_CHECKING:
    from dynamislm.benchmark.variable_pool import ProductionCandidateRecipeV1

_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
# v1.3.0 inventories record authority and authorable capacity only. v1.2.0 inventories
# encoded the historical 434 authoring slots as planned geometry; they remain readable as
# historical RES-383 evidence but are never produced by the live builder.
AUTHORITY_SUPPLY_SCHEMA = "PSE-V1-AUTHORITY-SUPPLY-INVENTORY@1.3.0"
AUTHORITY_SUPPLY_SCHEMA_V1_2 = "PSE-V1-AUTHORITY-SUPPLY-INVENTORY@1.2.0"
AUTHORITY_SUPPLY_INVENTORY_PATH = "qualification/RES-383/authority-supply-inventory.v1.3.json"
AUTHORITY_SUPPLY_INVENTORY_PATH_V1_2 = "qualification/RES-383/authority-supply-inventory.v1.2.json"


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
    EXISTING_RECIPE_INVENTORY = "EXISTING_RECIPE_INVENTORY"
    RULE_GOVERNED = "RULE_GOVERNED"
    METADATA_REQUIRED = "METADATA_REQUIRED"
    EXHAUSTED = "EXHAUSTED"


class AdditionalCapacityStatus(enum.StrEnum):
    AVAILABLE = "AVAILABLE"
    RULE_GOVERNED = "RULE_GOVERNED"
    GOVERNED_UNRESOLVED = "GOVERNED_UNRESOLVED"
    UNKNOWN = "UNKNOWN"
    EXHAUSTED = "EXHAUSTED"


@dataclass(frozen=True, slots=True)
class SupplyLaneSemanticsV1:
    lane_id: str
    origin_class: CaseOrigin
    existing_authorized_recipe_count: int | None
    additional_authorable_capacity: int | None
    capacity_status: AdditionalCapacityStatus


@dataclass(frozen=True, slots=True)
class AuthoritySupplySemanticsV1:
    """Typed view separating historical recipes, extra capacity, and final bounds."""

    active_supply_schema: str
    inventory_digest: str
    final_selection_bound: int
    historical_recipe_inventory: tuple[SupplyLaneSemanticsV1, ...]
    existing_authorized_recipe_count: tuple[tuple[CaseOrigin, int | None], ...]
    additional_authorable_capacity: tuple[tuple[CaseOrigin, int | None], ...]
    capacity_status: tuple[tuple[CaseOrigin, AdditionalCapacityStatus], ...]

    @property
    def structural_pool_floor(self) -> None:
        return None

    @property
    def structural_backfill_requests(self) -> tuple[()]:
        return ()

    @property
    def pool_n(self) -> None:
        return None


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
    """Legacy serialized shape retained for historical decoding only."""

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
        if self.capacity_status in {
            LaneCapacityStatus.AVAILABLE,
            LaneCapacityStatus.EXISTING_RECIPE_INVENTORY,
        }:
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
    def supply_semantics(self) -> SupplyLaneSemanticsV1:
        """Interpret inventory counts separately from additional authorable capacity."""

        if self.capacity_status is LaneCapacityStatus.EXISTING_RECIPE_INVENTORY:
            return SupplyLaneSemanticsV1(
                self.lane_id,
                self.origin_class,
                self.available_capacity,
                None,
                AdditionalCapacityStatus.GOVERNED_UNRESOLVED,
            )
        if self.capacity_status is LaneCapacityStatus.RULE_GOVERNED:
            return SupplyLaneSemanticsV1(
                self.lane_id,
                self.origin_class,
                None,
                None,
                AdditionalCapacityStatus.RULE_GOVERNED,
            )
        if self.capacity_status is LaneCapacityStatus.METADATA_REQUIRED:
            return SupplyLaneSemanticsV1(
                self.lane_id,
                self.origin_class,
                None,
                None,
                AdditionalCapacityStatus.GOVERNED_UNRESOLVED,
            )
        if self.capacity_status is LaneCapacityStatus.EXHAUSTED:
            return SupplyLaneSemanticsV1(
                self.lane_id,
                self.origin_class,
                0,
                0,
                AdditionalCapacityStatus.EXHAUSTED,
            )
        return SupplyLaneSemanticsV1(
            self.lane_id,
            self.origin_class,
            0,
            self.available_capacity,
            AdditionalCapacityStatus.AVAILABLE,
        )

    @property
    def existing_authorized_recipe_count(self) -> int | None:
        return self.supply_semantics.existing_authorized_recipe_count

    @property
    def additional_authorable_capacity(self) -> int | None:
        return self.supply_semantics.additional_authorable_capacity

    @property
    def additional_capacity_status(self) -> AdditionalCapacityStatus:
        return self.supply_semantics.capacity_status

    @property
    def may_author_backfill(self) -> bool:
        return self.additional_capacity_status in {
            AdditionalCapacityStatus.AVAILABLE,
            AdditionalCapacityStatus.RULE_GOVERNED,
        }


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
        if self.schema_version not in {AUTHORITY_SUPPLY_SCHEMA, AUTHORITY_SUPPLY_SCHEMA_V1_2}:
            raise ValueError("unknown authority supply inventory schema")
        if self.schema_version == AUTHORITY_SUPPLY_SCHEMA and (
            self.planned_origin_counts
            or self.planned_mutation_lineage_count
            or any(lane.existing_planned_capacity for lane in self.reserve_candidate_lanes)
        ):
            raise ValueError("v1.3 authority supply cannot encode planned slot or lineage geometry")
        if self.schema_version == AUTHORITY_SUPPLY_SCHEMA_V1_2 and any(
            lane.capacity_status is LaneCapacityStatus.EXISTING_RECIPE_INVENTORY
            for lane in self.reserve_candidate_lanes
        ):
            raise ValueError("v1.2 authority supply cannot use v1.3 recipe semantics")
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

    @property
    def encodes_planned_geometry(self) -> bool:
        """True only for historical v1.2 inventories built from fixed authoring slots."""

        return self.schema_version == AUTHORITY_SUPPLY_SCHEMA_V1_2

    def semantics(self) -> AuthoritySupplySemanticsV1:
        if self.encodes_planned_geometry:
            raise ValueError(
                "historical v1.2 inventory is preserved, not current execution authority"
            )
        from dynamislm.benchmark.selection_constraints import FINAL_CASE_COUNT

        lanes = tuple(item.supply_semantics for item in self.reserve_candidate_lanes)

        def totals(attribute: str) -> tuple[tuple[CaseOrigin, int | None], ...]:
            result = []
            for origin in CaseOrigin:
                values = [getattr(lane, attribute) for lane in lanes if lane.origin_class is origin]
                total = (
                    sum(value for value in values if value is not None)
                    if values and all(value is not None for value in values)
                    else None
                )
                result.append((origin, total))
            return tuple(sorted(result, key=lambda item: item[0].value.encode()))

        status_by_origin = []
        for origin in CaseOrigin:
            statuses = tuple(lane.capacity_status for lane in lanes if lane.origin_class is origin)
            if not statuses:
                status = AdditionalCapacityStatus.UNKNOWN
            elif AdditionalCapacityStatus.RULE_GOVERNED in statuses:
                status = AdditionalCapacityStatus.RULE_GOVERNED
            elif AdditionalCapacityStatus.GOVERNED_UNRESOLVED in statuses:
                status = AdditionalCapacityStatus.GOVERNED_UNRESOLVED
            elif AdditionalCapacityStatus.UNKNOWN in statuses:
                status = AdditionalCapacityStatus.UNKNOWN
            elif AdditionalCapacityStatus.AVAILABLE in statuses:
                status = AdditionalCapacityStatus.AVAILABLE
            else:
                status = AdditionalCapacityStatus.EXHAUSTED
            status_by_origin.append((origin, status))
        return AuthoritySupplySemanticsV1(
            active_supply_schema=self.schema_version,
            inventory_digest=self.inventory_digest,
            final_selection_bound=FINAL_CASE_COUNT,
            historical_recipe_inventory=lanes,
            existing_authorized_recipe_count=totals("existing_authorized_recipe_count"),
            additional_authorable_capacity=totals("additional_authorable_capacity"),
            capacity_status=tuple(
                sorted(status_by_origin, key=lambda item: item[0].value.encode())
            ),
        )


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


def _source_cells_by_document(
    accepted_by_document: Mapping[str, Mapping[str, object]],
    selections: tuple[SourceCellSelectionV1, ...],
) -> dict[str, tuple[tuple[str, str], ...]]:
    document_by_pmcid: dict[str, tuple[str, str]] = {}
    for document_id, row in accepted_by_document.items():
        pmcid = row.get("pmcid")
        family = row.get("source_family_identity")
        if (
            not isinstance(pmcid, str)
            or not isinstance(family, dict)
            or not isinstance(family.get("source_family_id"), str)
            or pmcid in document_by_pmcid
        ):
            raise ValueError("accepted source identity is missing or duplicated")
        document_by_pmcid[pmcid] = (document_id, family["source_family_id"])

    cells_by_document: dict[str, set[tuple[str, str]]] = {}
    for selection in selections:
        identity = document_by_pmcid.get(selection.pmcid)
        if identity is None or identity[1] != selection.source_family_id:
            raise ValueError("eligible source selection does not resolve to accepted authority")
        cells_by_document.setdefault(identity[0], set()).add(
            (selection.capability_id, selection.benchmark_family)
        )
    return {document_id: tuple(sorted(cells)) for document_id, cells in cells_by_document.items()}


def build_live_authority_supply_inventory(
    *,
    repository_root: str | Path,
    production_root: str | Path,
) -> AuthoritySupplyInventoryV1:
    """Inventory authority and authorable capacity without reading or creating candidate prose.

    The historical production authoring input is read only as a source of individual
    recipes. Its slot totals, origin vector, batch membership, and lineage geometry are not
    planned supply: every lane reports authority plus the recipes or rule that may author
    from it, and ``existing_planned_capacity`` is always zero.
    """

    import hashlib as _hashlib

    from dynamislm.benchmark.constants import CaseOrigin, SplitName
    from dynamislm.benchmark.production import PRODUCTION_SYNTHETIC_QUESTION_SURFACE_VARIANTS
    from dynamislm.benchmark.production_authoring import (
        PRODUCTION_SYNTHETIC_GENERATOR_DIGEST,
        PRODUCTION_SYNTHETIC_GENERATORS,
        ProductionAuthoringInputsV1,
        eligible_production_source_selections,
        production_authoring_input_digest,
    )
    from dynamislm.benchmark.production_exclusions import (
        QUALIFICATION_PRIVATE_EXCLUSION_PATH,
        QualificationExclusionCommitmentV1,
        validate_qualification_exclusion_commitment,
    )
    from dynamislm.benchmark.production_store import (
        DEFAULT_PRODUCTION_ROOT,
        read_external_production_json,
    )
    from dynamislm.benchmark.variable_pool import (
        historical_recipes_from_authoring_inputs,
        production_engine_reference_case_id,
    )
    from dynamislm.qualification import (
        RES71_SEALED_REFERENCE_DIGEST,
        build_registered_operation_inventory,
        get_reference_cases,
        reference_case_digest,
        validate_reference_cases,
        validate_registered_operation_inventory,
    )

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
    qualification_exclusion, _exclusion_file_digest, _exclusion_size = (
        read_external_production_json(
            QUALIFICATION_PRIVATE_EXCLUSION_PATH,
            QualificationExclusionCommitmentV1,
            repository_root=repository,
            production_root=root,
        )
    )
    validate_qualification_exclusion_commitment(qualification_exclusion)
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

    recipes = historical_recipes_from_authoring_inputs(inputs)
    by_origin = {
        origin: tuple(item for item in recipes if item.origin_class is origin)
        for origin in CaseOrigin
    }
    recipe_by_document: dict[str, tuple[str, str]] = {}
    for recipe in by_origin[CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION]:
        record = recipe.source_record
        assert record is not None
        accepted_row = accepted_by_document.get(record.document_id)
        if accepted_row is None:
            raise ValueError("historical source recipe does not resolve to accepted authority")
        family = accepted_row["source_family_identity"]
        assert isinstance(family, dict)
        if family.get("source_family_id") != record.source_family_id:
            raise ValueError("production source selection has a stale source-family binding")
        if record.document_id in recipe_by_document:
            raise ValueError("historical source recipes share one source document")
        recipe_by_document[record.document_id] = (recipe.capability_id, recipe.benchmark_family)

    eligible_source_selections = eligible_production_source_selections(
        qualification_exclusion,
        external_root=root,
    )
    source_cells_by_document = _source_cells_by_document(
        accepted_by_document, eligible_source_selections
    )

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
        family = row["source_family_identity"]
        assert isinstance(family, dict)
        family_id = family.get("source_family_id")
        if not isinstance(family_id, str):
            raise ValueError("accepted source is missing its resolved family identity")
        recipe_cell = recipe_by_document.get(document_id)
        supported_cells = (
            (recipe_cell,) if recipe_cell else source_cells_by_document.get(document_id, ())
        )
        source_lanes.append(
            ReserveCandidateLaneV1(
                lane_id=_opaque_id("source", document_id),
                origin_class=CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION,
                authority_ref=(
                    "Phase-A accepted document carrying one individually authorized recipe"
                    if recipe_cell
                    else "Phase-A accepted document with retained support evidence"
                ),
                authority_digest=source_digest,
                capacity_unit="source-document-backed-candidate-slot",
                existing_planned_capacity=0,
                available_capacity=1 if supported_cells else 0,
                capacity_status=(
                    LaneCapacityStatus.EXISTING_RECIPE_INVENTORY
                    if recipe_cell
                    else (
                        LaneCapacityStatus.AVAILABLE
                        if supported_cells
                        else LaneCapacityStatus.EXHAUSTED
                    )
                ),
                supported_cells=supported_cells,
                isolation_identity_digests=tuple(
                    sorted(
                        {
                            canonical_hash(("SOURCE_DOCUMENT", document_id)),
                            canonical_hash(("SOURCE_FAMILY", family_id)),
                        }
                    )
                ),
            )
        )

    generator_lanes: list[ReserveCandidateLaneV1] = []
    synthetic_cells = tuple(
        sorted(
            {("C08", family) for family, _variant in PRODUCTION_SYNTHETIC_QUESTION_SURFACE_VARIANTS}
        )
    )
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
        generator_lanes.append(
            ReserveCandidateLaneV1(
                lane_id="synthetic:" + generator.generator_family,
                origin_class=CaseOrigin.DETERMINISTIC_SYNTHETIC,
                authority_ref="registered split-family synthetic generator",
                authority_digest=generator_digest,
                capacity_unit="unique split-locked synthetic seed block",
                existing_planned_capacity=0,
                available_capacity=None,
                capacity_status=LaneCapacityStatus.RULE_GOVERNED,
                capacity_rule="registered generator and split-family seed-block namespace",
                supported_cells=synthetic_cells,
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
    engine_recipes_by_lane: dict[tuple[str, str, str], list[str]] = {}
    for recipe in by_origin[CaseOrigin.DETERMINISTIC_ENGINE_DERIVED]:
        reference_id = production_engine_reference_case_id(
            recipe.capability_id, recipe.benchmark_family, recipe.slot_index or 0
        )
        reference = reference_by_id[reference_id]
        if recipe.capability_id != "C18" and reference.operation_id is None:
            raise ValueError("numeric engine recipe has no registered RES-71 operation")
        engine_recipes_by_lane.setdefault(
            (recipe.capability_id, recipe.benchmark_family, reference_id), []
        ).append(recipe.candidate_id)
    engine_lanes = []
    for (capability, family, reference_id), recipe_ids in engine_recipes_by_lane.items():
        reference = reference_by_id[reference_id]
        engine_lanes.append(
            ReserveCandidateLaneV1(
                lane_id=f"engine:{capability}:{family}:{reference_id}",
                origin_class=CaseOrigin.DETERMINISTIC_ENGINE_DERIVED,
                authority_ref="RES-71 reference, operation, and individually authorized recipes",
                authority_digest=canonical_hash(
                    (
                        reference_digest,
                        canonical_hash(reference),
                        capability,
                        family,
                        tuple(sorted(recipe_ids, key=str.encode)),
                    )
                ),
                capacity_unit="individually authorized RES-71 engine recipe",
                existing_planned_capacity=0,
                available_capacity=len(recipe_ids),
                capacity_status=LaneCapacityStatus.EXISTING_RECIPE_INVENTORY,
                capacity_rule=(
                    "lower bound: existing individual recipes; further engine recipes need "
                    "explicit RES-71 authoring authority"
                ),
                supported_cells=((capability, family),),
                isolation_identity_digests=(
                    canonical_hash(("RES71_ENGINE_REFERENCE_CASE", reference_id)),
                ),
            )
        )

    expert_recipes: dict[tuple[str, str, str], list[tuple[str, str]]] = {}
    for recipe in by_origin[CaseOrigin.EXPERT_AUTHORED_SEMANTIC]:
        batch = recipe.expert_batch
        assert batch is not None
        expert_recipes.setdefault(
            (batch.author_batch_id, batch.protocol_template_id, batch.isolation_cluster_id), []
        ).append((recipe.capability_id, recipe.benchmark_family))
    expert_lanes: list[ReserveCandidateLaneV1] = []
    for (batch_id, template_id, cluster_id), cells in expert_recipes.items():
        batch_digest = canonical_hash(("EXPERT_BATCH_IDENTITY", batch_id, template_id, cluster_id))
        atom(
            AuthoritySupplyKind.EXPERT_BATCH,
            batch_id,
            "production expert batch and template identity",
            batch_digest,
        )
        expert_lanes.append(
            ReserveCandidateLaneV1(
                lane_id=_opaque_id("expert-batch", batch_id),
                origin_class=CaseOrigin.EXPERT_AUTHORED_SEMANTIC,
                authority_ref="expert batch/template/isolation identity with individual recipes",
                authority_digest=batch_digest,
                capacity_unit="individually authorized expert-semantic recipe",
                existing_planned_capacity=0,
                available_capacity=len(cells),
                capacity_status=LaneCapacityStatus.EXISTING_RECIPE_INVENTORY,
                capacity_rule=(
                    "lower bound: existing individual recipes; further expert recipes need "
                    "explicit expert authoring authority"
                ),
                supported_cells=tuple(sorted(set(cells))),
                isolation_identity_digests=tuple(
                    sorted(
                        {
                            canonical_hash(("EXPERT_BATCH", batch_id)),
                            canonical_hash(("PROTOCOL_TEMPLATE", template_id)),
                            canonical_hash(("EXPERT_ISOLATION_CLUSTER", cluster_id)),
                        }
                    )
                ),
            )
        )

    mutation_recipes: dict[str, list[ProductionCandidateRecipeV1]] = {}
    for recipe in by_origin[CaseOrigin.ADVERSARIAL_MUTATION]:
        mutation_recipes.setdefault(recipe.mutation_lineage_id or "", []).append(recipe)
    mutation_lanes: list[ReserveCandidateLaneV1] = []
    for lineage_id, children in mutation_recipes.items():
        first_stage = next(item for item in children if item.mutation_stage == 1)
        root_parent = first_stage.mutation_parent_candidate_id or ""
        lineage_digest = canonical_hash(
            (
                "MUTATION_LINEAGE_AUTHORITY",
                lineage_id,
                root_parent,
                first_stage.mutation_operator_id,
            )
        )
        atom(
            AuthoritySupplyKind.MUTATION_LINEAGE,
            lineage_id,
            "mutation root/operator/lineage authority",
            lineage_digest,
        )
        mutation_lanes.append(
            ReserveCandidateLaneV1(
                lane_id=_opaque_id("mutation-lineage", lineage_id),
                origin_class=CaseOrigin.ADVERSARIAL_MUTATION,
                authority_ref="mutation parent, operator, and lineage authority",
                authority_digest=lineage_digest,
                capacity_unit="individually authorized mutation child recipe",
                existing_planned_capacity=0,
                available_capacity=len(children),
                capacity_status=LaneCapacityStatus.EXISTING_RECIPE_INVENTORY,
                capacity_rule=(
                    "lower bound: existing individual child recipes; further children need "
                    "candidate-level parent and cell metadata"
                ),
                isolation_identity_digests=tuple(
                    sorted(
                        {
                            canonical_hash(("MUTATION_PARENT", root_parent)),
                            canonical_hash(("MUTATION_LINEAGE", lineage_id)),
                        }
                    )
                ),
                supported_cells=tuple(
                    sorted({(item.capability_id, item.benchmark_family) for item in children})
                ),
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
            "individual recipe seed from the historical production authoring input",
            canonical_hash((inputs.batch_id, candidate_id, seed)),
        )

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
        "HISTORICAL_RECIPE_INPUT_CONTENT": inputs.input_digest,
        "HISTORICAL_RECIPE_INPUT_FILE": input_file_digest,
        "PHASE_A_ACCEPTED_SOURCE_MANIFEST": accepted_manifest_digest,
        "PHASE_A_SOURCE_FAMILY_MANIFEST": family_manifest_digest,
        "PHASE_A_SOURCE_SUPPORT_MANIFEST": support_manifest_digest,
        "QUALIFICATION_EXCLUSION_COMMITMENT": qualification_exclusion.commitment_digest,
        "RES71_OPERATION_INVENTORY": canonical_hash(operations),
        "RES71_REFERENCE_INVENTORY": reference_digest,
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
        planned_origin_counts=(),
        planned_mutation_lineage_count=0,
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
    "AUTHORITY_SUPPLY_INVENTORY_PATH_V1_2",
    "AUTHORITY_SUPPLY_SCHEMA",
    "AUTHORITY_SUPPLY_SCHEMA_V1_2",
    "AdditionalCapacityStatus",
    "AuthoritySupplyAssessmentV1",
    "AuthoritySupplyAtomV1",
    "AuthoritySupplyInventoryV1",
    "AuthoritySupplyKind",
    "AuthoritySupplySemanticsV1",
    "BackfillRequestKind",
    "BackfillRequestV1",
    "LaneCapacityStatus",
    "ReserveCandidateLaneV1",
    "ReserveDeficitKind",
    "ReserveDeficitV1",
    "SupplyAssessmentStatus",
    "SupplyLaneSemanticsV1",
    "build_live_authority_supply_inventory",
    "write_live_authority_supply_inventory",
]
