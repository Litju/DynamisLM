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
import hashlib
import re
from collections import Counter
from dataclasses import dataclass, replace
from pathlib import Path

from dynamislm.benchmark.authoring import production_seed_namespace
from dynamislm.benchmark.authority_supply import (
    HISTORICAL_RECIPE_INPUT_BINDING,
    AdditionalCapacityStatus,
    AuthoritySupplyInventoryV1,
    ReserveCandidateLaneV1,
    _opaque_id,
    require_current_execution_supply_inventory,
)
from dynamislm.benchmark.constants import CaseOrigin, SplitName
from dynamislm.benchmark.coverage import COVERAGE_MATRIX
from dynamislm.benchmark.pre_review import CandidateReviewPacket, CandidateReviewStatus
from dynamislm.benchmark.production import (
    PRODUCTION_BATCH_ID,
    PRODUCTION_CANDIDATE_ID_PREFIX,
    PRODUCTION_SYNTHETIC_QUESTION_SURFACE_VARIANTS,
    validate_production_candidate_pool,
)
from dynamislm.benchmark.production_authoring import (
    PRODUCTION_SYNTHETIC_GENERATOR_DIGEST,
    PRODUCTION_SYNTHETIC_GENERATORS,
    ProductionAuthoringInputsV1,
    ProductionExpertBatchV1,
    ProductionSourceSelectionV1,
    _author_engine_packets,
    _author_semantic_packets,
    _author_source_packets,
    _author_synthetic_packets,
    _direct_target_source_selections,
    _mutation_child,
    _scope_production_author_batch,
    _source_authoring_records,
    eligible_production_source_selections,
    production_authoring_input_digest,
)
from dynamislm.benchmark.production_exclusions import (
    QualificationExclusionCommitmentV1,
    validate_production_candidate_set_against_qualification_exclusion,
    validate_qualification_exclusion_commitment,
)
from dynamislm.benchmark.selection_constraints import (
    FINAL_CASE_COUNT,
    selection_candidate_from_commitment,
)
from dynamislm.benchmark.selection_contracts import FinalSelectionCandidate
from dynamislm.benchmark.source_artifacts import SourceArtifactResolver
from dynamislm.qualification.res115_authoring import SourceCellSelectionV1
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


_SEMANTIC_ID = re.compile(r"^PSE-V1-CANDIDATE:SEM:(C\d{2}):(F\d{2}):(\d+)$")
_ENGINE_ID = re.compile(r"^PSE-V1-CANDIDATE:ENGINE:(C\d{2}):(F\d{2}):(\d+)$")
_SYNTHETIC_ID = re.compile(
    r"^PSE-V1-CANDIDATE:SYNTH:C08:(F\d{2}):(PUBLIC_DEVELOPMENT|FROZEN_VALIDATION|HIDDEN_FINAL)$"
)


def production_engine_reference_case_id(capability_id: str, family: str, slot_index: int) -> str:
    """Return the sealed RES-71 reference the production engine builder binds to one recipe."""

    from dynamislm.qualification import ReferenceCaseStatus, get_reference_cases
    from dynamislm.qualification.res115_authoring import _production_authoring_engine_references

    if capability_id == "C18":
        return "res71-nonfinite-unit-refusal" if family == "F06" else "res71-bpt-mpv-refusal"
    if capability_id == "C08":
        return _production_authoring_engine_references()[0].case_id
    if capability_id not in ENGINE_RECIPE_CAPABILITIES:
        raise ValueError("engine recipe capability has no registered RES-71 adapter")
    values = tuple(
        item for item in get_reference_cases() if item.status is ReferenceCaseStatus.VALUE
    )
    return values[(slot_index + (0 if family == "F05" else 1)) % len(values)].case_id


def _historical_authority(inputs: ProductionAuthoringInputsV1, candidate_id: str) -> str:
    return canonical_hash(
        (RecipeAuthorityBasis.HISTORICAL_INDIVIDUAL_RECIPE, inputs.input_digest, candidate_id)
    )


def historical_recipes_from_authoring_inputs(
    inputs: ProductionAuthoringInputsV1,
) -> tuple[ProductionCandidateRecipeV1, ...]:
    """Decompose historical production inputs into individual recipes, discarding topology.

    Every recipe is reconstructed from its own seed, cell, and authority identity. Expert
    batch membership, slot totals, origin counts, and lineage sizes are not carried
    forward; each recipe must still pass every current materialization gate.
    """

    if inputs.input_digest != production_authoring_input_digest(inputs):
        raise ValueError("historical authoring input digest does not match its contents")
    if inputs.synthetic_generator_registry_digest != PRODUCTION_SYNTHETIC_GENERATOR_DIGEST:
        raise ValueError("historical synthetic seeds do not bind the live generator registry")
    batch_by_id = {
        candidate_id: batch
        for batch in inputs.expert_batches
        for candidate_id in batch.candidate_ids
    }
    recipes: dict[str, ProductionCandidateRecipeV1] = {}

    def add(recipe: ProductionCandidateRecipeV1) -> None:
        if recipe.candidate_id in recipes:
            raise ValueError("historical authoring input repeats a candidate recipe")
        recipes[recipe.candidate_id] = recipe

    for candidate_id, seed in inputs.scenario_seeds:
        semantic = _SEMANTIC_ID.fullmatch(candidate_id)
        engine = _ENGINE_ID.fullmatch(candidate_id)
        match = semantic or engine
        if match is None:
            raise ValueError("historical scenario seed does not name a recipe identity")
        batch = batch_by_id.get(candidate_id)
        if (batch is not None) != (semantic is not None):
            raise ValueError("historical expert batch identity differs from recipe origin")
        add(
            ProductionCandidateRecipeV1(
                candidate_id=candidate_id,
                origin_class=(
                    CaseOrigin.EXPERT_AUTHORED_SEMANTIC
                    if semantic
                    else CaseOrigin.DETERMINISTIC_ENGINE_DERIVED
                ),
                capability_id=match.group(1),
                benchmark_family=match.group(2),
                authority_basis=RecipeAuthorityBasis.HISTORICAL_INDIVIDUAL_RECIPE,
                authority_ref=HISTORICAL_RECIPE_AUTHORITY_REF,
                authority_digest=_historical_authority(inputs, candidate_id),
                slot_index=int(match.group(3)),
                scenario_seed=seed,
                expert_batch=(
                    None
                    if batch is None
                    else ProductionExpertBatchV1(
                        author_batch_id=batch.author_batch_id,
                        protocol_template_id=batch.protocol_template_id,
                        isolation_cluster_id=batch.isolation_cluster_id,
                        candidate_ids=(candidate_id,),
                        rationale=batch.rationale,
                    )
                ),
            )
        )
    if set(batch_by_id) - set(recipes):
        raise ValueError("historical expert batch names a candidate without a scenario seed")
    for candidate_id, seed_block in inputs.synthetic_seed_blocks:
        synthetic = _SYNTHETIC_ID.fullmatch(candidate_id)
        if synthetic is None:
            raise ValueError("historical synthetic seed does not name a recipe identity")
        split = SplitName(synthetic.group(2))
        add(
            ProductionCandidateRecipeV1(
                candidate_id=candidate_id,
                origin_class=CaseOrigin.DETERMINISTIC_SYNTHETIC,
                capability_id="C08",
                benchmark_family=synthetic.group(1),
                authority_basis=RecipeAuthorityBasis.HISTORICAL_INDIVIDUAL_RECIPE,
                authority_ref=HISTORICAL_RECIPE_AUTHORITY_REF,
                authority_digest=_historical_authority(inputs, candidate_id),
                generator_family=f"pse-v1-synthetic-refusal-{split.value.lower()}",
                split_lock=split,
                seed_block=seed_block,
            )
        )
    for record in inputs.source_selections:
        add(
            ProductionCandidateRecipeV1(
                candidate_id=record.candidate_id,
                origin_class=CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION,
                capability_id=record.capability_id,
                benchmark_family=record.benchmark_family,
                authority_basis=RecipeAuthorityBasis.HISTORICAL_INDIVIDUAL_RECIPE,
                authority_ref=HISTORICAL_RECIPE_AUTHORITY_REF,
                authority_digest=_historical_authority(inputs, record.candidate_id),
                source_record=record,
            )
        )
    mutation_seeds = dict(inputs.mutation_seed_blocks)
    lineage_children = [
        child for lineage in inputs.mutation_lineages for child in lineage.child_candidate_ids
    ]
    if sorted(lineage_children) != sorted(mutation_seeds):
        raise ValueError("historical mutation seeds differ from their parent/operator chains")
    for lineage in inputs.mutation_lineages:
        root = recipes.get(lineage.parent_candidate_id)
        if root is None:
            raise ValueError("historical mutation parent is not an individual recipe")
        parent_id = lineage.parent_candidate_id
        for stage, child_id in enumerate(lineage.child_candidate_ids, start=1):
            add(
                ProductionCandidateRecipeV1(
                    candidate_id=child_id,
                    origin_class=CaseOrigin.ADVERSARIAL_MUTATION,
                    capability_id=root.capability_id,
                    benchmark_family=root.benchmark_family,
                    authority_basis=RecipeAuthorityBasis.HISTORICAL_INDIVIDUAL_RECIPE,
                    authority_ref=HISTORICAL_RECIPE_AUTHORITY_REF,
                    authority_digest=_historical_authority(inputs, child_id),
                    seed_block=mutation_seeds[child_id],
                    mutation_parent_candidate_id=parent_id,
                    mutation_lineage_id=lineage.lineage_id,
                    mutation_operator_id=lineage.operator_id,
                    mutation_stage=stage,
                )
            )
            parent_id = child_id
    return tuple(recipes[candidate_id] for candidate_id in sorted(recipes, key=str.encode))


def production_source_selection_universe(
    exclusion: QualificationExclusionCommitmentV1,
    *,
    external_root: Path,
) -> tuple[SourceCellSelectionV1, ...]:
    """Every exact source cell current authority may author: eligible plus direct-target."""

    selections: dict[str, SourceCellSelectionV1] = {}
    for selection in (
        *eligible_production_source_selections(exclusion, external_root=external_root),
        *_direct_target_source_selections(exclusion, external_root=external_root),
    ):
        candidate_id = _source_authoring_records((selection,))[0].candidate_id
        if selections.setdefault(candidate_id, selection) != selection:
            raise ValueError("source authority yields conflicting selections for one recipe")
    return tuple(selections[item] for item in sorted(selections, key=str.encode))


def _recipe_authority_payload_digest(recipe: ProductionCandidateRecipeV1) -> str:
    """Identify recipe authority without treating a second candidate ID as new authority."""

    batch = recipe.expert_batch
    source = recipe.source_record
    return canonical_hash(
        (
            recipe.origin_class,
            recipe.capability_id,
            recipe.benchmark_family,
            recipe.authority_basis,
            recipe.authority_ref,
            recipe.authority_digest,
            recipe.lane_id,
            recipe.slot_index,
            recipe.scenario_seed,
            (
                None
                if batch is None
                else (
                    batch.author_batch_id,
                    batch.protocol_template_id,
                    batch.isolation_cluster_id,
                    batch.rationale,
                )
            ),
            (
                None
                if source is None
                else (
                    source.capability_id,
                    source.benchmark_family,
                    source.pmcid,
                    source.document_id,
                    source.source_family_id,
                    source.applicability_scope,
                    source.span_digests,
                    source.search_strata,
                    source.direct_target_document,
                )
            ),
            recipe.generator_family,
            recipe.split_lock,
            recipe.seed_block,
            recipe.mutation_parent_candidate_id,
            recipe.mutation_lineage_id,
            recipe.mutation_operator_id,
            recipe.mutation_stage,
        )
    )


def build_initial_variable_pool_authoring_plan(
    historical_inputs: ProductionAuthoringInputsV1,
    supply_inventory: AuthoritySupplyInventoryV1,
    exclusion: QualificationExclusionCommitmentV1,
    *,
    external_root: Path,
) -> VariablePoolAuthoringPlanV1:
    """Build the current-authority variable pool without applying selection constraints."""

    require_current_execution_supply_inventory(supply_inventory)
    validate_qualification_exclusion_commitment(exclusion)
    if (
        supply_inventory.evidence_binding("QUALIFICATION_EXCLUSION_COMMITMENT")
        != exclusion.commitment_digest
    ):
        raise ValueError("qualification exclusion is not the one bound by the supply inventory")

    historical = historical_recipes_from_authoring_inputs(historical_inputs)
    _validate_historical_recipes(historical, supply_inventory, historical_inputs)
    current_selections: dict[ProductionSourceSelectionV1, SourceCellSelectionV1] = {}
    if any(recipe.source_record is not None for recipe in historical) or any(
        lane.origin_class is CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION
        and lane.additional_capacity_status is AdditionalCapacityStatus.AVAILABLE
        and lane.additional_authorable_capacity is not None
        and lane.additional_authorable_capacity > 0
        for lane in supply_inventory.reserve_candidate_lanes
    ):
        for selection in production_source_selection_universe(
            exclusion, external_root=external_root
        ):
            record = _source_authoring_records((selection,))[0]
            previous = current_selections.setdefault(record, selection)
            if previous != selection:
                raise ValueError("current source universe repeats a conflicting source recipe")
    for recipe in historical:
        if recipe.source_record is not None and recipe.source_record not in current_selections:
            raise ValueError(
                "historical source recipe does not resolve to exact current Phase-A authority"
            )

    additions: list[ProductionCandidateRecipeV1] = []
    lanes = tuple(
        lane
        for lane in supply_inventory.reserve_candidate_lanes
        if lane.origin_class is CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION
        and lane.additional_capacity_status is AdditionalCapacityStatus.AVAILABLE
        and lane.additional_authorable_capacity is not None
        and lane.additional_authorable_capacity > 0
    )
    for lane in lanes:
        options = [
            (record, selection)
            for record, selection in current_selections.items()
            if _opaque_id("source", record.document_id) == lane.lane_id
            and (record.capability_id, record.benchmark_family) in lane.supported_cells
        ]
        options.sort(
            key=lambda item: (
                item[0].candidate_id.encode("utf-8"),
                item[0].capability_id.encode("utf-8"),
                item[0].benchmark_family.encode("utf-8"),
                item[0].span_digests,
            )
        )
        if not options:
            raise ValueError("finite current source lane has no exact Phase-A source selection")
        capacity = lane.additional_authorable_capacity
        assert capacity is not None
        for record, _selection in options[:capacity]:
            additions.append(
                ProductionCandidateRecipeV1(
                    candidate_id=record.candidate_id,
                    origin_class=CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION,
                    capability_id=record.capability_id,
                    benchmark_family=record.benchmark_family,
                    authority_basis=RecipeAuthorityBasis.GOVERNED_SUPPLY_LANE,
                    authority_ref=lane.authority_ref,
                    authority_digest=lane.authority_digest,
                    lane_id=lane.lane_id,
                    source_record=record,
                )
            )

    recipes = tuple(
        sorted((*historical, *additions), key=lambda item: item.candidate_id.encode("utf-8"))
    )
    candidate_ids = tuple(item.candidate_id for item in recipes)
    if len(candidate_ids) != len(set(candidate_ids)):
        raise ValueError("initial variable pool repeats a candidate identity")
    payload_authorities = tuple(_recipe_authority_payload_digest(item) for item in recipes)
    if len(payload_authorities) != len(set(payload_authorities)):
        raise ValueError("initial variable pool repeats candidate payload authority")

    plan = VariablePoolAuthoringPlanV1(
        supply_inventory_digest=supply_inventory.inventory_digest,
        qualification_exclusion_digest=exclusion.commitment_digest,
        recipes=recipes,
    )
    _governed_recipe_check(plan.recipes, supply_inventory)
    return plan


def _validate_historical_recipes(
    recipes: tuple[ProductionCandidateRecipeV1, ...],
    supply_inventory: AuthoritySupplyInventoryV1,
    historical_inputs: ProductionAuthoringInputsV1 | None,
) -> None:
    """Prove each historical recipe is the exact recipe decomposed from bound inputs.

    Subsets are allowed; only individual recipe identity is proven. The historical
    collective topology is never compared or required.
    """

    historical = tuple(
        item
        for item in recipes
        if item.authority_basis is RecipeAuthorityBasis.HISTORICAL_INDIVIDUAL_RECIPE
    )
    if not historical:
        return
    if historical_inputs is None:
        raise ValueError("historical recipes require their exact historical authoring input")
    bound = supply_inventory.evidence_binding(HISTORICAL_RECIPE_INPUT_BINDING)
    if bound is None or bound != historical_inputs.input_digest:
        raise ValueError("historical authoring input is not the one bound by the supply inventory")
    canonical = {
        item.candidate_id: item
        for item in historical_recipes_from_authoring_inputs(historical_inputs)
    }
    for recipe in historical:
        expected = canonical.get(recipe.candidate_id)
        if expected is None or expected != recipe or expected.recipe_digest != recipe.recipe_digest:
            raise ValueError("historical recipe differs from its canonical historical recipe")


def _mutation_root_parent(
    recipe: ProductionCandidateRecipeV1,
    by_id: dict[str, ProductionCandidateRecipeV1],
) -> str:
    current = recipe
    while current.mutation_stage != 1:
        parent = by_id[current.mutation_parent_candidate_id or ""]
        if (
            parent.origin_class is not CaseOrigin.ADVERSARIAL_MUTATION
            or parent.mutation_lineage_id != recipe.mutation_lineage_id
            or parent.mutation_stage != (current.mutation_stage or 0) - 1
        ):
            raise ValueError("mutation recipe stage does not follow its lineage chain")
        current = parent
    return current.mutation_parent_candidate_id or ""


def _lane_identity_matches(
    recipe: ProductionCandidateRecipeV1,
    lane: ReserveCandidateLaneV1,
    by_id: dict[str, ProductionCandidateRecipeV1],
) -> bool:
    """Bind the recipe payload to the exact origin-specific authority its lane represents."""

    identities = set(lane.isolation_identity_digests)
    if recipe.origin_class is CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION:
        record = recipe.source_record
        assert record is not None
        return (
            lane.lane_id == _opaque_id("source", record.document_id)
            and {
                canonical_hash(("SOURCE_DOCUMENT", record.document_id)),
                canonical_hash(("SOURCE_FAMILY", record.source_family_id)),
            }
            == identities
        )
    if recipe.origin_class is CaseOrigin.DETERMINISTIC_SYNTHETIC:
        generator = next(
            (
                item
                for item in PRODUCTION_SYNTHETIC_GENERATORS
                if item.generator_family == recipe.generator_family
            ),
            None,
        )
        if generator is None or recipe.split_lock is None:
            return False
        # Fails closed unless the seed block forms a strict split-qualified namespace.
        production_seed_namespace(
            recipe.split_lock, generator.generator_id, generator.version, recipe.seed_block or ""
        )
        return (
            lane.lane_id == "synthetic:" + generator.generator_family
            and lane.authority_digest == canonical_hash(generator)
            and {
                canonical_hash(("SYNTHETIC_GENERATOR", generator.generator_id, generator.version)),
                canonical_hash(("GENERATOR_FAMILY", generator.generator_family)),
                canonical_hash(("SYNTHETIC_SPLIT_LOCK", recipe.split_lock)),
            }
            == identities
        )
    if recipe.origin_class is CaseOrigin.DETERMINISTIC_ENGINE_DERIVED:
        reference_id = production_engine_reference_case_id(
            recipe.capability_id, recipe.benchmark_family, recipe.slot_index or 0
        )
        return lane.lane_id == (
            f"engine:{recipe.capability_id}:{recipe.benchmark_family}:{reference_id}"
        ) and identities == {canonical_hash(("RES71_ENGINE_REFERENCE_CASE", reference_id))}
    if recipe.origin_class is CaseOrigin.EXPERT_AUTHORED_SEMANTIC:
        batch = recipe.expert_batch
        assert batch is not None
        return (
            lane.lane_id == _opaque_id("expert-batch", batch.author_batch_id)
            and lane.authority_digest
            == canonical_hash(
                (
                    "EXPERT_BATCH_IDENTITY",
                    batch.author_batch_id,
                    batch.protocol_template_id,
                    batch.isolation_cluster_id,
                )
            )
            and {
                canonical_hash(("EXPERT_BATCH", batch.author_batch_id)),
                canonical_hash(("PROTOCOL_TEMPLATE", batch.protocol_template_id)),
                canonical_hash(("EXPERT_ISOLATION_CLUSTER", batch.isolation_cluster_id)),
            }
            == identities
        )
    lineage_id = recipe.mutation_lineage_id or ""
    root_parent = _mutation_root_parent(recipe, by_id)
    return (
        lane.lane_id == _opaque_id("mutation-lineage", lineage_id)
        and lane.authority_digest
        == canonical_hash(
            ("MUTATION_LINEAGE_AUTHORITY", lineage_id, root_parent, recipe.mutation_operator_id)
        )
        and {
            canonical_hash(("MUTATION_PARENT", root_parent)),
            canonical_hash(("MUTATION_LINEAGE", lineage_id)),
        }
        == identities
    )


def _governed_recipe_check(
    recipes: tuple[ProductionCandidateRecipeV1, ...],
    supply_inventory: AuthoritySupplyInventoryV1,
) -> None:
    lanes = {lane.lane_id: lane for lane in supply_inventory.reserve_candidate_lanes}
    by_id = {item.candidate_id: item for item in recipes}
    uses: Counter[str] = Counter()
    for recipe in recipes:
        if recipe.authority_basis is not RecipeAuthorityBasis.GOVERNED_SUPPLY_LANE:
            continue
        lane = lanes.get(recipe.lane_id or "")
        if (
            lane is None
            or not lane.may_author_backfill
            or lane.origin_class is not recipe.origin_class
            or lane.authority_digest != recipe.authority_digest
            or (recipe.capability_id, recipe.benchmark_family) not in lane.supported_cells
            or not _lane_identity_matches(recipe, lane, by_id)
        ):
            raise ValueError("governed recipe does not match an authorable supply lane")
        uses[lane.lane_id] += 1
        capacity = lane.additional_authorable_capacity
        if capacity is not None and uses[lane.lane_id] > capacity:
            raise ValueError("governed recipes exceed their supply lane capacity")
    seeds = [
        item.seed_block
        for item in recipes
        if item.origin_class is CaseOrigin.DETERMINISTIC_SYNTHETIC and item.seed_block
    ]
    if len(seeds) != len(set(seeds)):
        raise ValueError("synthetic recipes must use unique split-locked seed blocks")


def _recipe_inputs(recipes: tuple[ProductionCandidateRecipeV1, ...]) -> ProductionAuthoringInputsV1:
    """Adapter carrying only these recipes' seeds into the existing per-recipe builders."""

    scenario = tuple(
        (item.candidate_id, item.scenario_seed or "")
        for item in recipes
        if item.scenario_seed is not None
    )
    synthetic = tuple(
        (item.candidate_id, item.seed_block or "")
        for item in recipes
        if item.origin_class is CaseOrigin.DETERMINISTIC_SYNTHETIC
    )
    provisional = ProductionAuthoringInputsV1(
        batch_id=PRODUCTION_BATCH_ID,
        synthetic_generator_registry_digest=PRODUCTION_SYNTHETIC_GENERATOR_DIGEST,
        scenario_seeds=scenario,
        synthetic_seed_blocks=synthetic,
        mutation_seed_blocks=(),
        source_selections=(),
        expert_batches=tuple(
            item.expert_batch for item in recipes if item.expert_batch is not None
        ),
        mutation_lineages=(),
        input_digest="sha256:" + "0" * 64,
    )
    return replace(provisional, input_digest=production_authoring_input_digest(provisional))


def materialize_variable_pool(
    plan: VariablePoolAuthoringPlanV1,
    *,
    supply_inventory: AuthoritySupplyInventoryV1,
    exclusion: QualificationExclusionCommitmentV1,
    source_resolver: SourceArtifactResolver | None,
    historical_inputs: ProductionAuthoringInputsV1 | None = None,
    source_selections: tuple[SourceCellSelectionV1, ...] = (),
    external_root: Path | None = None,
) -> ProductionAuthoringCandidatePoolV1:
    """Author every planned recipe with the production builders and current validators.

    No fixed count, origin vector, lineage geometry, historical repair plan, historical
    candidate-set digest, or legacy exact-feasibility receipt participates. The returned
    pool is unqualified: reserve qualification and human review remain separate gates.

    Historical recipes must equal the recipes decomposed from ``historical_inputs``, whose
    digest the current supply inventory binds. ``source_selections`` may only reproduce
    historical source records exactly; governed source recipes are resolved solely from
    ``production_source_selection_universe`` under ``external_root``.
    """

    require_current_execution_supply_inventory(supply_inventory)
    if (
        plan.supply_inventory_digest != supply_inventory.inventory_digest
        or plan.qualification_exclusion_digest != exclusion.commitment_digest
    ):
        raise ValueError("variable pool plan binds a different supply or exclusion authority")
    _validate_historical_recipes(plan.recipes, supply_inventory, historical_inputs)
    _governed_recipe_check(plan.recipes, supply_inventory)
    by_origin: dict[CaseOrigin, tuple[ProductionCandidateRecipeV1, ...]] = {
        origin: tuple(item for item in plan.recipes if item.origin_class is origin)
        for origin in CaseOrigin
    }
    inputs = _recipe_inputs(plan.recipes)
    authored: list[CandidateReviewPacket] = [
        *_author_semantic_packets(
            tuple(
                (item.candidate_id, item.capability_id, item.benchmark_family, item.slot_index or 0)
                for item in by_origin[CaseOrigin.EXPERT_AUTHORED_SEMANTIC]
            ),
            inputs,
        ),
        *_author_engine_packets(
            tuple(
                (item.candidate_id, item.capability_id, item.benchmark_family, item.slot_index or 0)
                for item in by_origin[CaseOrigin.DETERMINISTIC_ENGINE_DERIVED]
            ),
            inputs,
        ),
        *_author_synthetic_packets(
            tuple(
                (
                    item.candidate_id,
                    item.benchmark_family,
                    item.split_lock or SplitName.HIDDEN_FINAL,
                )
                for item in by_origin[CaseOrigin.DETERMINISTIC_SYNTHETIC]
            ),
            inputs,
        ),
    ]
    source_recipes = by_origin[CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION]
    if source_recipes:
        if source_resolver is None:
            raise ValueError("source recipes require the canonical source artifact resolver")
        if external_root is None:
            raise ValueError("source recipes require the external production root")
        source_universe = production_source_selection_universe(
            exclusion, external_root=external_root
        )
        if any(selection not in source_universe for selection in source_selections):
            raise ValueError("source selection is not an exact current source authority cell")
        selection_by_record: dict[ProductionSourceSelectionV1, SourceCellSelectionV1] = {}
        for selection in source_universe:
            record = _source_authoring_records((selection,))[0]
            if selection_by_record.setdefault(record, selection) != selection:
                raise ValueError("current source universe repeats a conflicting source recipe")
        chosen = []
        for recipe in source_recipes:
            assert recipe.source_record is not None
            resolved_selection = selection_by_record.get(recipe.source_record)
            if resolved_selection is None:
                raise ValueError("source recipe is not an exact current source authority cell")
            chosen.append(resolved_selection)
        authored.extend(_author_source_packets(tuple(chosen), source_resolver=source_resolver))

    built = {packet.candidate_id: _scope_production_author_batch(packet) for packet in authored}
    pending = list(by_origin[CaseOrigin.ADVERSARIAL_MUTATION])
    while pending:
        ready = [item for item in pending if item.mutation_parent_candidate_id in built]
        if not ready:
            raise ValueError("mutation recipe parent could not be materialized")
        for recipe in ready:
            child = _mutation_child(
                built[recipe.mutation_parent_candidate_id or ""],
                candidate_id=recipe.candidate_id,
                lineage_id=recipe.mutation_lineage_id or "",
                operator_id=recipe.mutation_operator_id or "",
                stage=recipe.mutation_stage or 0,
                mutation_seed=int(
                    hashlib.sha256((recipe.seed_block or "").encode("ascii")).hexdigest()[:15], 16
                ),
            )
            built[recipe.candidate_id] = _scope_production_author_batch(child)
            pending.remove(recipe)

    recipe_by_id = {item.candidate_id: item for item in plan.recipes}
    if set(built) != set(recipe_by_id):
        raise ValueError("materialization did not author exactly the planned recipes")
    for candidate_id, packet in built.items():
        recipe = recipe_by_id[candidate_id]
        if packet.proposed_provenance.origin_class is not recipe.origin_class or (
            packet.capability_id,
            packet.benchmark_family,
        ) != (recipe.capability_id, recipe.benchmark_family):
            raise ValueError("materialized packet differs from its recipe origin or cell")
    packets = tuple(built[candidate_id] for candidate_id in sorted(built, key=str.encode))
    validate_production_candidate_pool(packets, source_resolver=source_resolver)
    validate_production_candidate_set_against_qualification_exclusion(
        packets, exclusion, source_resolver=source_resolver
    )
    return ProductionAuthoringCandidatePoolV1(
        authoring_plan_digest=plan.plan_digest,
        packets=packets,
    )


def project_variable_pool_selection_candidates(
    pool: ProductionAuthoringCandidatePoolV1,
    *,
    source_resolver: SourceArtifactResolver | None,
) -> tuple[FinalSelectionCandidate, ...]:
    """Project materialized packets into the unchanged RES-369 selection vocabulary."""

    commitments, _audit = validate_production_candidate_pool(
        pool.packets, source_resolver=source_resolver
    )
    packet_by_id = {packet.candidate_id: packet for packet in pool.packets}
    candidates = []
    for commitment in commitments:
        packet = packet_by_id[commitment.candidate_id]
        parent = packet.parent_candidate_binding
        candidates.append(
            selection_candidate_from_commitment(
                commitment,
                review_eligibility=packet.review_status,
                contamination=packet.contamination,
                question_text=packet.question,
                mutation_parent_payload_hash=(
                    None if parent is None else parent.parent_candidate_payload_hash
                ),
            )
        )
    return tuple(candidates)


def validate_variable_pre_review_pool(
    pool: ProductionAuthoringCandidatePoolV1,
    *,
    exclusion: QualificationExclusionCommitmentV1,
    source_resolver: SourceArtifactResolver | None,
) -> None:
    """Gate a materialized pool for reserve qualification: N>=434 plus every packet gate."""

    require_pre_review_pool_minimum(pool)
    validate_production_candidate_pool(pool.packets, source_resolver=source_resolver)
    validate_production_candidate_set_against_qualification_exclusion(
        pool.packets, exclusion, source_resolver=source_resolver
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
    "build_initial_variable_pool_authoring_plan",
    "candidate_recipe_digest",
    "historical_recipes_from_authoring_inputs",
    "materialize_variable_pool",
    "production_authoring_candidate_pool_digest",
    "production_engine_reference_case_id",
    "production_source_selection_universe",
    "project_variable_pool_selection_candidates",
    "require_pre_review_pool_minimum",
    "validate_variable_pre_review_pool",
    "variable_pool_authoring_plan_digest",
]
