"""Pool-first PSE V1 candidate authoring: individual recipes -> variable plan -> packets.

RES258-DR-001 makes the pre-review pool variable (``N >= 434``) and limits every earlier
production topology to historical evidence. This module is the modern authoring boundary:

``ProductionCandidateRecipeV1`` (one individually authorized candidate recipe)
    -> ``VariablePoolAuthoringPlanV1`` (an explicit, variable set of recipes)
    -> ``ProductionAuthoringCandidatePoolV1`` (materialized pending review packets)

A recipe may be reused from the historical production authoring input, but only as an
individual recipe that must pass every current packet, source, exclusion, contamination
and isolation gate. The historical input's collective topology -- its fixed 434 slots,
origin vector, batch geometry, mutation lineage geometry, repair plans, and feasibility
receipts -- is never authority here and is never read by this path.
"""

from __future__ import annotations

import enum
import re
from collections import Counter
from dataclasses import dataclass

from dynamislm.benchmark.constants import CaseOrigin, SplitName
from dynamislm.benchmark.coverage import COVERAGE_MATRIX
from dynamislm.benchmark.pre_review import CandidateReviewPacket, CandidateReviewStatus
from dynamislm.benchmark.production import (
    PRODUCTION_CANDIDATE_ID_PREFIX,
    PRODUCTION_SYNTHETIC_QUESTION_SURFACE_VARIANTS,
)
from dynamislm.benchmark.production_authoring import (
    PRODUCTION_SYNTHETIC_GENERATORS,
    ProductionExpertBatchV1,
    ProductionSourceSelectionV1,
)
from dynamislm.benchmark.selection_constraints import FINAL_CASE_COUNT
from dynamislm.serialization import canonical_hash, register_serializable_type

_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
CANDIDATE_RECIPE_SCHEMA = "PSE-V1-CANDIDATE-RECIPE@1.0.0"
VARIABLE_POOL_AUTHORING_PLAN_SCHEMA = "PSE-V1-VARIABLE-POOL-AUTHORING-PLAN@1.0.0"
PRODUCTION_CANDIDATE_POOL_SCHEMA = "PSE-V1-MATERIALIZED-CANDIDATE-POOL@2.0.0"
# RES258-DR-001: the pre-review pool must contain at least the final selection count.
# This is a lower bound for pool qualification, never a target pool size.
PRE_REVIEW_POOL_MINIMUM = FINAL_CASE_COUNT
ENGINE_RECIPE_CAPABILITIES = frozenset({"C08", "C16", "C18"})
HISTORICAL_RECIPE_AUTHORITY_REF = (
    "historical production authoring input, reused as one individual recipe; "
    "its collective topology is not authority (RES258-SUPERSESSION-MAP)"
)
_CELLS = frozenset(
    (row.capability_id, family) for row in COVERAGE_MATRIX for family in row.benchmark_families
)
_SYNTHETIC_FAMILIES = frozenset(
    family for family, _variant in PRODUCTION_SYNTHETIC_QUESTION_SURFACE_VARIANTS
)
_GENERATOR_SPLIT = {
    generator.generator_family: split
    for generator in PRODUCTION_SYNTHETIC_GENERATORS
    for split in SplitName
    if generator.generator_family == f"pse-v1-synthetic-refusal-{split.value.lower()}"
}


class RecipeAuthorityBasis(enum.StrEnum):
    """Why one recipe may be authored; neither basis implies any collective topology."""

    HISTORICAL_INDIVIDUAL_RECIPE = "HISTORICAL_INDIVIDUAL_RECIPE"
    GOVERNED_SUPPLY_LANE = "GOVERNED_SUPPLY_LANE"


def _sha(value: str | None) -> bool:
    return value is not None and _SHA256.fullmatch(value) is not None


@register_serializable_type
@dataclass(frozen=True, slots=True)
class ProductionCandidateRecipeV1:
    """One individually authorized candidate recipe with origin-specific authority."""

    candidate_id: str
    origin_class: CaseOrigin
    capability_id: str
    benchmark_family: str
    authority_basis: RecipeAuthorityBasis
    authority_ref: str
    authority_digest: str
    lane_id: str | None = None
    slot_index: int | None = None
    scenario_seed: str | None = None
    expert_batch: ProductionExpertBatchV1 | None = None
    source_record: ProductionSourceSelectionV1 | None = None
    generator_family: str | None = None
    split_lock: SplitName | None = None
    seed_block: str | None = None
    mutation_parent_candidate_id: str | None = None
    mutation_lineage_id: str | None = None
    mutation_operator_id: str | None = None
    mutation_stage: int | None = None
    recipe_digest: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "origin_class", CaseOrigin(self.origin_class))
        object.__setattr__(self, "authority_basis", RecipeAuthorityBasis(self.authority_basis))
        if self.split_lock is not None:
            object.__setattr__(self, "split_lock", SplitName(self.split_lock))
        if (
            not self.candidate_id.startswith(PRODUCTION_CANDIDATE_ID_PREFIX)
            or (self.capability_id, self.benchmark_family) not in _CELLS
            or not self.authority_ref.strip()
            or not _sha(self.authority_digest)
        ):
            raise ValueError("candidate recipe requires a production identity, cell, and authority")
        governed = self.authority_basis is RecipeAuthorityBasis.GOVERNED_SUPPLY_LANE
        if governed != bool(self.lane_id and self.lane_id.strip()):
            raise ValueError("only governed supply-lane recipes bind a supply lane")
        payload = {
            "slot_index": self.slot_index is not None,
            "scenario_seed": bool(self.scenario_seed),
            "expert_batch": self.expert_batch is not None,
            "source_record": self.source_record is not None,
            "generator_family": self.generator_family is not None,
            "split_lock": self.split_lock is not None,
            "seed_block": bool(self.seed_block),
            "mutation": any(
                value is not None
                for value in (
                    self.mutation_parent_candidate_id,
                    self.mutation_lineage_id,
                    self.mutation_operator_id,
                    self.mutation_stage,
                )
            ),
        }
        required = {
            CaseOrigin.EXPERT_AUTHORED_SEMANTIC: {"slot_index", "scenario_seed", "expert_batch"},
            CaseOrigin.DETERMINISTIC_ENGINE_DERIVED: {"slot_index", "scenario_seed"},
            CaseOrigin.DETERMINISTIC_SYNTHETIC: {"generator_family", "split_lock", "seed_block"},
            CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION: {"source_record"},
            CaseOrigin.ADVERSARIAL_MUTATION: {"mutation", "seed_block"},
        }[self.origin_class]
        if {name for name, present in payload.items() if present} != required:
            raise ValueError(f"{self.origin_class.value} recipe has an invalid authority payload")
        if self.slot_index is not None and self.slot_index < 0:
            raise ValueError("recipe slot index selects a question class and cannot be negative")
        if self.origin_class is CaseOrigin.EXPERT_AUTHORED_SEMANTIC:
            assert self.expert_batch is not None
            if self.expert_batch.candidate_ids != (self.candidate_id,):
                raise ValueError("expert recipe binds only its own batch identity, not membership")
        elif self.origin_class is CaseOrigin.DETERMINISTIC_ENGINE_DERIVED:
            if self.capability_id not in ENGINE_RECIPE_CAPABILITIES:
                raise ValueError("engine recipe capability has no registered RES-71 adapter")
        elif self.origin_class is CaseOrigin.DETERMINISTIC_SYNTHETIC:
            if (
                self.capability_id != "C08"
                or self.benchmark_family not in _SYNTHETIC_FAMILIES
                or _GENERATOR_SPLIT.get(self.generator_family or "") is not self.split_lock
            ):
                raise ValueError("synthetic recipe must bind a registered generator split family")
        elif self.origin_class is CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION:
            record = self.source_record
            assert record is not None
            if record.candidate_id != self.candidate_id or (
                record.capability_id,
                record.benchmark_family,
            ) != (self.capability_id, self.benchmark_family):
                raise ValueError("source recipe must bind its exact source selection record")
        elif (
            not self.mutation_parent_candidate_id
            or not self.mutation_lineage_id
            or not self.mutation_operator_id
            or self.mutation_stage is None
            or self.mutation_stage < 1
            or self.mutation_parent_candidate_id == self.candidate_id
        ):
            raise ValueError("mutation recipe must bind its parent, lineage, operator, and stage")
        computed = candidate_recipe_digest(self)
        if self.recipe_digest and self.recipe_digest != computed:
            raise ValueError("candidate recipe digest does not match its authority payload")
        object.__setattr__(self, "recipe_digest", computed)


def candidate_recipe_digest(recipe: ProductionCandidateRecipeV1) -> str:
    return canonical_hash(
        {
            "schema": CANDIDATE_RECIPE_SCHEMA,
            "candidate_id": recipe.candidate_id,
            "origin_class": recipe.origin_class,
            "cell": (recipe.capability_id, recipe.benchmark_family),
            "authority_basis": recipe.authority_basis,
            "authority_ref": recipe.authority_ref,
            "authority_digest": recipe.authority_digest,
            "lane_id": recipe.lane_id,
            "slot_index": recipe.slot_index,
            "scenario_seed": recipe.scenario_seed,
            "expert_batch": recipe.expert_batch,
            "source_record": recipe.source_record,
            "generator_family": recipe.generator_family,
            "split_lock": recipe.split_lock,
            "seed_block": recipe.seed_block,
            "mutation_parent_candidate_id": recipe.mutation_parent_candidate_id,
            "mutation_lineage_id": recipe.mutation_lineage_id,
            "mutation_operator_id": recipe.mutation_operator_id,
            "mutation_stage": recipe.mutation_stage,
        }
    )


@register_serializable_type
@dataclass(frozen=True, slots=True)
class VariablePoolAuthoringPlanV1:
    """An explicit variable recipe set; it carries no count, composition, or topology target."""

    supply_inventory_digest: str
    qualification_exclusion_digest: str
    recipes: tuple[ProductionCandidateRecipeV1, ...]
    plan_schema: str = VARIABLE_POOL_AUTHORING_PLAN_SCHEMA
    plan_digest: str = ""

    def __post_init__(self) -> None:
        if self.plan_schema != VARIABLE_POOL_AUTHORING_PLAN_SCHEMA:
            raise ValueError("unknown variable pool authoring plan schema")
        if not _sha(self.supply_inventory_digest) or not _sha(self.qualification_exclusion_digest):
            raise ValueError("variable pool plan must bind supply and exclusion authority")
        ids = tuple(item.candidate_id for item in self.recipes)
        if not ids or ids != tuple(sorted(set(ids), key=str.encode)):
            raise ValueError(
                "variable pool recipes must be non-empty, unique, and candidate ordered"
            )
        by_id = {item.candidate_id: item for item in self.recipes}
        for recipe in self.recipes:
            # Pool materialization needs the exact parent packet to bind parent provenance.
            # This is a pre-review authoring dependency, not a final co-selection rule.
            seen = {recipe.candidate_id}
            parent_id = recipe.mutation_parent_candidate_id
            while parent_id is not None:
                if parent_id in seen or parent_id not in by_id:
                    raise ValueError("mutation recipe parent must resolve acyclically in the plan")
                seen.add(parent_id)
                parent_id = by_id[parent_id].mutation_parent_candidate_id
        computed = variable_pool_authoring_plan_digest(self)
        if self.plan_digest and self.plan_digest != computed:
            raise ValueError("variable pool authoring plan digest mismatch")
        object.__setattr__(self, "plan_digest", computed)

    @property
    def candidate_count(self) -> int:
        return len(self.recipes)

    @property
    def origin_counts(self) -> tuple[tuple[CaseOrigin, int], ...]:
        """Report-only composition; no gate on this path compares it to a target."""

        counts = Counter(item.origin_class for item in self.recipes)
        return tuple(sorted(counts.items(), key=lambda item: item[0].value.encode()))


def variable_pool_authoring_plan_digest(plan: VariablePoolAuthoringPlanV1) -> str:
    return canonical_hash(
        {
            "schema": plan.plan_schema,
            "supply_inventory_digest": plan.supply_inventory_digest,
            "qualification_exclusion_digest": plan.qualification_exclusion_digest,
            "recipe_digests": tuple(
                (item.candidate_id, item.recipe_digest) for item in plan.recipes
            ),
        }
    )


@register_serializable_type
@dataclass(frozen=True, slots=True)
class ProductionAuthoringCandidatePoolV1:
    """Materialized pending-review packets bound to the exact plan that authored them."""

    authoring_plan_digest: str
    packets: tuple[CandidateReviewPacket, ...]
    pool_schema: str = PRODUCTION_CANDIDATE_POOL_SCHEMA
    pool_digest: str = ""

    def __post_init__(self) -> None:
        if self.pool_schema != PRODUCTION_CANDIDATE_POOL_SCHEMA:
            raise ValueError("unknown materialized candidate pool schema")
        if not _sha(self.authoring_plan_digest) or not self.packets:
            raise ValueError("materialized pool requires packets and its authoring plan binding")
        ids = tuple(packet.candidate_id for packet in self.packets)
        if ids != tuple(sorted(set(ids), key=str.encode)):
            raise ValueError("materialized pool packets must be unique and candidate ordered")
        if any(
            packet.review_status is not CandidateReviewStatus.PENDING_HUMAN_REVIEW
            for packet in self.packets
        ):
            raise ValueError("materialized pre-review pool must preserve pending review state")
        computed = production_authoring_candidate_pool_digest(self)
        if self.pool_digest and self.pool_digest != computed:
            raise ValueError("materialized candidate pool digest mismatch")
        object.__setattr__(self, "pool_digest", computed)

    @property
    def candidate_count(self) -> int:
        return len(self.packets)


def production_authoring_candidate_pool_digest(pool: ProductionAuthoringCandidatePoolV1) -> str:
    return canonical_hash(
        {
            "schema": pool.pool_schema,
            "authoring_plan_digest": pool.authoring_plan_digest,
            "candidate_bindings": tuple(
                (packet.candidate_id, packet.candidate_payload_hash) for packet in pool.packets
            ),
        }
    )


def require_pre_review_pool_minimum(pool: ProductionAuthoringCandidatePoolV1) -> None:
    """Fail closed below the RES258 lower bound; larger pools carry no ceiling or target."""

    if pool.candidate_count < PRE_REVIEW_POOL_MINIMUM:
        raise ValueError(
            f"pre-review pool has {pool.candidate_count} candidates; RES258 requires at least "
            f"{PRE_REVIEW_POOL_MINIMUM}"
        )


__all__ = [
    "CANDIDATE_RECIPE_SCHEMA",
    "ENGINE_RECIPE_CAPABILITIES",
    "HISTORICAL_RECIPE_AUTHORITY_REF",
    "PRE_REVIEW_POOL_MINIMUM",
    "PRODUCTION_CANDIDATE_POOL_SCHEMA",
    "VARIABLE_POOL_AUTHORING_PLAN_SCHEMA",
    "ProductionAuthoringCandidatePoolV1",
    "ProductionCandidateRecipeV1",
    "RecipeAuthorityBasis",
    "VariablePoolAuthoringPlanV1",
    "candidate_recipe_digest",
    "production_authoring_candidate_pool_digest",
    "require_pre_review_pool_minimum",
    "variable_pool_authoring_plan_digest",
]
