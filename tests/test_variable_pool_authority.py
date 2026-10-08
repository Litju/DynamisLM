"""Adversarial authority binding for the modern variable-pool materialization boundary."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from dynamislm.benchmark import production as production_contracts
from dynamislm.benchmark import (
    production_authoring,
    res223_topology,
    selection_pool,
    selection_solver,
    variable_pool,
)
from dynamislm.benchmark.authority_supply import (
    AUTHORITY_SUPPLY_SCHEMA,
    AUTHORITY_SUPPLY_SCHEMA_V1_2,
    HISTORICAL_RECIPE_INPUT_BINDING,
    AuthoritySupplyInventoryV1,
    LaneCapacityStatus,
    ReserveCandidateLaneV1,
    _opaque_id,
)
from dynamislm.benchmark.constants import CaseOrigin, SplitName
from dynamislm.benchmark.production_authoring import (
    PRODUCTION_SYNTHETIC_GENERATORS,
    ProductionAuthoringInputsV1,
    ProductionExpertBatchV1,
    ProductionSourceSelectionV1,
    production_authoring_input_digest,
)
from dynamislm.benchmark.variable_pool import (
    ProductionCandidateRecipeV1,
    RecipeAuthorityBasis,
    VariablePoolAuthoringPlanV1,
    build_initial_variable_pool_authoring_plan,
    historical_recipes_from_authoring_inputs,
    materialize_variable_pool,
    production_engine_reference_case_id,
)
from dynamislm.qualification.res115_authoring import SourceCellSelectionV1
from dynamislm.serialization import canonical_hash
from test_variable_pool_materialization import (
    _ENGINE,
    _MUT_1,
    _MUT_2,
    _SEM_A,
    _SEM_B,
    _SYNTH,
    _exclusion,
    _historical_inputs,
    _seed,
)

_FORGED = "sha256:" + "e" * 64
_SOURCE_ID = "PSE-V1-CANDIDATE:SOURCE:synthetictest0000001"
_GOVERNED = RecipeAuthorityBasis.GOVERNED_SUPPLY_LANE


def _source_record(
    candidate_id: str = _SOURCE_ID,
    *,
    document_id: str = "document:synthetic-a",
    family_id: str = "family:synthetic-a",
    cell: tuple[str, str] = ("C01", "F01"),
) -> ProductionSourceSelectionV1:
    return ProductionSourceSelectionV1(
        candidate_id=candidate_id,
        capability_id=cell[0],
        benchmark_family=cell[1],
        pmcid="PMC-SYNTHETIC-TEST",
        document_id=document_id,
        source_family_id=family_id,
        applicability_scope="INDIRECT_MEASUREMENT_EVIDENCE",
        span_digests=(canonical_hash("synthetic span"),),
        search_strata=("synthetic-stratum",),
        direct_target_document=False,
    )


def _inputs_with_source() -> ProductionAuthoringInputsV1:
    inputs = replace(_historical_inputs(), source_selections=(_source_record(),))
    return replace(inputs, input_digest=production_authoring_input_digest(inputs))


def _inventory(
    lanes: tuple[ReserveCandidateLaneV1, ...] = (),
    *,
    inputs: ProductionAuthoringInputsV1 | None = None,
    schema: str = AUTHORITY_SUPPLY_SCHEMA,
) -> AuthoritySupplyInventoryV1:
    bound = inputs or _historical_inputs()
    return AuthoritySupplyInventoryV1(
        schema_version=schema,
        atoms=(),
        reserve_candidate_lanes=tuple(sorted(lanes, key=lambda item: item.lane_id.encode())),
        planned_origin_counts=(),
        planned_mutation_lineage_count=0,
        materialized_candidate_count=0,
        evidence_bindings=((HISTORICAL_RECIPE_INPUT_BINDING, bound.input_digest),),
        authority_inventory_complete=True,
        capacity_scope_complete=False,
    )


def _inventory_for_plan(
    exclusion: Any,
    lanes: tuple[ReserveCandidateLaneV1, ...] = (),
    *,
    inputs: ProductionAuthoringInputsV1 | None = None,
) -> AuthoritySupplyInventoryV1:
    inventory = _inventory(lanes, inputs=inputs)
    return replace(
        inventory,
        evidence_bindings=tuple(
            sorted(
                (
                    *inventory.evidence_bindings,
                    ("QUALIFICATION_EXCLUSION_COMMITMENT", exclusion.commitment_digest),
                ),
                key=lambda item: item[0].encode(),
            )
        ),
        inventory_digest="",
    )


def _materialize(
    recipes: tuple[ProductionCandidateRecipeV1, ...],
    *,
    inventory: AuthoritySupplyInventoryV1 | None = None,
    inputs: ProductionAuthoringInputsV1 | None = None,
    **kwargs: Any,
) -> variable_pool.ProductionAuthoringCandidatePoolV1:
    inventory = inventory or _inventory()
    plan = VariablePoolAuthoringPlanV1(
        supply_inventory_digest=inventory.inventory_digest,
        qualification_exclusion_digest=_exclusion().commitment_digest,
        recipes=tuple(sorted(recipes, key=lambda item: item.candidate_id.encode())),
    )
    kwargs.setdefault("source_resolver", None)
    return materialize_variable_pool(
        plan,
        supply_inventory=inventory,
        exclusion=_exclusion(),
        historical_inputs=inputs,
        **kwargs,
    )


def _canonical(inputs: ProductionAuthoringInputsV1 | None = None) -> dict[str, Any]:
    return {
        item.candidate_id: item
        for item in historical_recipes_from_authoring_inputs(inputs or _historical_inputs())
    }


def _forge(recipe: ProductionCandidateRecipeV1, **changes: Any) -> ProductionCandidateRecipeV1:
    return replace(recipe, recipe_digest="", **changes)


def _batch(batch: ProductionExpertBatchV1 | None, **changes: Any) -> ProductionExpertBatchV1:
    assert batch is not None
    return replace(batch, **changes)


_HISTORICAL_FORGERIES: dict[str, tuple[str, Callable[[ProductionCandidateRecipeV1], Any]]] = {
    "seed": (_SEM_A, lambda item: _forge(item, scenario_seed=_seed("forged"))),
    "slot_index": (_ENGINE, lambda item: _forge(item, slot_index=1)),
    "cell": (_SEM_B, lambda item: _forge(item, benchmark_family="F01")),
    "expert_batch": (
        _SEM_A,
        lambda item: _forge(
            item,
            expert_batch=_batch(item.expert_batch, author_batch_id="PSE-V1-EXPERT-BATCH:forged"),
        ),
    ),
    "expert_template": (
        _SEM_A,
        lambda item: _forge(
            item,
            expert_batch=_batch(
                item.expert_batch, protocol_template_id="PSE-V1-PROTOCOL-TEMPLATE:forged"
            ),
        ),
    ),
    "expert_cluster": (
        _SEM_A,
        lambda item: _forge(
            item,
            expert_batch=_batch(
                item.expert_batch, isolation_cluster_id="PSE-V1-SEMANTIC-CLUSTER:forged"
            ),
        ),
    ),
    "synthetic_seed": (_SYNTH, lambda item: _forge(item, seed_block=_seed("forged"))),
    "generator_split": (
        _SYNTH,
        lambda item: _forge(
            item,
            generator_family="pse-v1-synthetic-refusal-public_development",
            split_lock=SplitName.PUBLIC_DEVELOPMENT,
        ),
    ),
    "mutation_parent": (_MUT_2, lambda item: _forge(item, mutation_parent_candidate_id=_SEM_A)),
    "mutation_lineage": (
        _MUT_1,
        lambda item: _forge(item, mutation_lineage_id="PSE-V1-MUTATION-LINEAGE:forged"),
    ),
    "mutation_operator": (_MUT_1, lambda item: _forge(item, mutation_operator_id="forged-op")),
    "mutation_stage": (_MUT_2, lambda item: _forge(item, mutation_stage=3)),
    "mutation_seed": (_MUT_1, lambda item: _forge(item, seed_block=_seed("forged"))),
    "authority_digest": (_ENGINE, lambda item: _forge(item, authority_digest=_FORGED)),
    "authority_ref": (_ENGINE, lambda item: _forge(item, authority_ref="forged reference")),
}


@pytest.mark.parametrize("field", sorted(_HISTORICAL_FORGERIES))
def test_modified_historical_recipe_cannot_materialize(field: str) -> None:
    candidate_id, forge = _HISTORICAL_FORGERIES[field]
    recipes = _canonical()
    recipes[candidate_id] = forge(recipes[candidate_id])
    with pytest.raises(ValueError, match="differs from its canonical historical recipe"):
        _materialize(tuple(recipes.values()), inputs=_historical_inputs())


def test_modified_historical_source_record_cannot_materialize() -> None:
    inputs = _inputs_with_source()
    recipe = _canonical(inputs)[_SOURCE_ID]
    for record in (
        replace(recipe.source_record, document_id="document:forged"),
        replace(recipe.source_record, source_family_id="family:forged"),
        replace(recipe.source_record, span_digests=(_FORGED,)),
    ):
        with pytest.raises(ValueError, match="differs from its canonical historical recipe"):
            _materialize(
                (_forge(recipe, source_record=record),),
                inventory=_inventory(inputs=inputs),
                inputs=inputs,
                source_resolver=object(),
            )


def test_invented_historical_recipe_cannot_materialize() -> None:
    invented = ProductionCandidateRecipeV1(
        candidate_id="PSE-V1-CANDIDATE:ENGINE:C16:F05:09",
        origin_class=CaseOrigin.DETERMINISTIC_ENGINE_DERIVED,
        capability_id="C16",
        benchmark_family="F05",
        authority_basis=RecipeAuthorityBasis.HISTORICAL_INDIVIDUAL_RECIPE,
        authority_ref="claimed historical recipe",
        authority_digest=_FORGED,
        slot_index=9,
        scenario_seed=_seed("invented"),
    )
    with pytest.raises(ValueError, match="differs from its canonical historical recipe"):
        _materialize((invented,), inputs=_historical_inputs())


def test_historical_recipes_require_the_inventory_bound_input() -> None:
    recipes = tuple(_canonical().values())
    with pytest.raises(ValueError, match="require their exact historical authoring input"):
        _materialize(recipes)
    other = _inputs_with_source()
    with pytest.raises(ValueError, match="not the one bound by the supply inventory"):
        _materialize(recipes, inputs=other)
    unbound = replace(_inventory(), evidence_bindings=(), inventory_digest="")
    with pytest.raises(ValueError, match="not the one bound by the supply inventory"):
        _materialize(recipes, inventory=unbound, inputs=_historical_inputs())
    tampered = replace(_historical_inputs(), scenario_seeds=())
    with pytest.raises(ValueError, match="digest does not match"):
        _materialize(recipes, inventory=_inventory(inputs=tampered), inputs=tampered)


def test_historical_subsets_materialize_without_collective_topology() -> None:
    recipes = _canonical()
    pool = _materialize((recipes[_SEM_B], recipes[_SYNTH]), inputs=_historical_inputs())
    assert {packet.candidate_id for packet in pool.packets} == {_SEM_B, _SYNTH}


def _generator_lane(split: SplitName) -> ReserveCandidateLaneV1:
    generator = next(
        item
        for item in PRODUCTION_SYNTHETIC_GENERATORS
        if item.generator_family == f"pse-v1-synthetic-refusal-{split.value.lower()}"
    )
    return ReserveCandidateLaneV1(
        lane_id="synthetic:" + generator.generator_family,
        origin_class=CaseOrigin.DETERMINISTIC_SYNTHETIC,
        authority_ref="registered split-family synthetic generator",
        authority_digest=canonical_hash(generator),
        capacity_unit="unique split-locked synthetic seed block",
        existing_planned_capacity=0,
        available_capacity=None,
        capacity_status=LaneCapacityStatus.RULE_GOVERNED,
        capacity_rule="registered generator and split-family seed-block namespace",
        supported_cells=(("C08", "F05"),),
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


def _governed_synthetic(
    lane: ReserveCandidateLaneV1,
    *,
    suffix: str = "0001",
    split: SplitName = SplitName.HIDDEN_FINAL,
    seed_block: str | None = None,
) -> ProductionCandidateRecipeV1:
    return ProductionCandidateRecipeV1(
        candidate_id=f"PSE-V1-CANDIDATE:SYNTH:C08:F05:GOVERNED-{suffix}",
        origin_class=CaseOrigin.DETERMINISTIC_SYNTHETIC,
        capability_id="C08",
        benchmark_family="F05",
        authority_basis=_GOVERNED,
        authority_ref=lane.authority_ref,
        authority_digest=lane.authority_digest,
        lane_id=lane.lane_id,
        generator_family=f"pse-v1-synthetic-refusal-{split.value.lower()}",
        split_lock=split,
        seed_block=seed_block or _seed(f"governed-{suffix}"),
    )


def test_governed_synthetic_recipe_binds_exact_generator_and_split_lane() -> None:
    hidden = _generator_lane(SplitName.HIDDEN_FINAL)
    public = _generator_lane(SplitName.PUBLIC_DEVELOPMENT)
    inventory = _inventory((hidden, public))
    pool = _materialize((_governed_synthetic(hidden),), inventory=inventory)
    assert pool.candidate_count == 1

    # A public-split recipe may not borrow the hidden lane's ID and digest.
    borrowed = replace(
        _governed_synthetic(public, split=SplitName.PUBLIC_DEVELOPMENT),
        lane_id=hidden.lane_id,
        authority_digest=hidden.authority_digest,
        recipe_digest="",
    )
    # A lane whose split identity was substituted cannot authorize either split.
    swapped = replace(
        hidden,
        isolation_identity_digests=public.isolation_identity_digests,
        lane_digest="",
    )
    for recipes, lanes in (
        ((borrowed,), (hidden, public)),
        ((_governed_synthetic(swapped),), (swapped,)),
    ):
        with pytest.raises(ValueError, match="authorable supply lane"):
            _materialize(recipes, inventory=_inventory(lanes))


def test_governed_synthetic_seed_blocks_are_unique_and_namespaced() -> None:
    lane = _generator_lane(SplitName.HIDDEN_FINAL)
    inventory = _inventory((lane,))
    duplicate = (
        _governed_synthetic(lane, suffix="0001", seed_block=_seed("same")),
        _governed_synthetic(lane, suffix="0002", seed_block=_seed("same")),
    )
    with pytest.raises(ValueError, match="unique split-locked seed blocks"):
        _materialize(duplicate, inventory=inventory)
    with pytest.raises(ValueError, match="seed namespace"):
        _materialize(
            (_governed_synthetic(lane, seed_block="not a seed block"),), inventory=inventory
        )


def _source_lane(
    *,
    document_id: str = "document:synthetic-a",
    family_id: str = "family:synthetic-a",
    capacity: int = 1,
    cells: tuple[tuple[str, str], ...] = (("C01", "F01"),),
) -> ReserveCandidateLaneV1:
    return ReserveCandidateLaneV1(
        lane_id=_opaque_id("source", document_id),
        origin_class=CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION,
        authority_ref="Phase-A accepted document with retained support evidence",
        authority_digest=canonical_hash(("synthetic source authority", document_id)),
        capacity_unit="source-document-backed-candidate-slot",
        existing_planned_capacity=0,
        available_capacity=capacity,
        capacity_status=LaneCapacityStatus.AVAILABLE,
        supported_cells=cells,
        isolation_identity_digests=tuple(
            sorted(
                {
                    canonical_hash(("SOURCE_DOCUMENT", document_id)),
                    canonical_hash(("SOURCE_FAMILY", family_id)),
                }
            )
        ),
    )


def _governed_source(
    lane: ReserveCandidateLaneV1,
    record: ProductionSourceSelectionV1,
) -> ProductionCandidateRecipeV1:
    return ProductionCandidateRecipeV1(
        candidate_id=record.candidate_id,
        origin_class=CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION,
        capability_id=record.capability_id,
        benchmark_family=record.benchmark_family,
        authority_basis=_GOVERNED,
        authority_ref=lane.authority_ref,
        authority_digest=lane.authority_digest,
        lane_id=lane.lane_id,
        source_record=record,
    )


@pytest.mark.parametrize(
    "record",
    [
        _source_record(document_id="document:synthetic-b"),
        _source_record(family_id="family:synthetic-b"),
    ],
    ids=["document", "family"],
)
def test_governed_source_recipe_cannot_substitute_document_or_family(
    record: ProductionSourceSelectionV1,
) -> None:
    lane = _source_lane()
    with pytest.raises(ValueError, match="authorable supply lane"):
        _materialize(
            (_governed_source(lane, record),),
            inventory=_inventory((lane,)),
            source_resolver=object(),
        )


def test_governed_source_recipe_requires_the_current_source_universe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lane = _source_lane()
    recipe = _governed_source(lane, _source_record())
    inventory = _inventory((lane,))
    with pytest.raises(ValueError, match="require the external production root"):
        _materialize((recipe,), inventory=inventory, source_resolver=object())

    calls: list[Path] = []

    def universe(_exclusion: object, *, external_root: Path) -> tuple[()]:
        calls.append(external_root)
        return ()

    monkeypatch.setattr(variable_pool, "production_source_selection_universe", universe)
    # Even a caller selection that reproduces the exact record cannot stand in for the
    # governed universe; it may only reproduce historical recipes.
    monkeypatch.setattr(
        variable_pool,
        "_source_authoring_records",
        lambda selections: tuple(_source_record() for _ in selections),
    )
    with pytest.raises(ValueError, match="exact current source authority cell"):
        _materialize(
            (recipe,),
            inventory=inventory,
            source_resolver=object(),
            source_selections=("caller-selection",),
            external_root=Path("/nonexistent"),
        )
    assert calls == [Path("/nonexistent")]


def test_governed_source_lane_capacity_uses_additional_authorable_capacity() -> None:
    cells = (("C01", "F01"), ("C01", "F03"))
    lane = _source_lane(cells=cells)
    recipes = (
        _governed_source(lane, _source_record()),
        _governed_source(
            lane,
            _source_record("PSE-V1-CANDIDATE:SOURCE:synthetictest0000002", cell=("C01", "F03")),
        ),
    )
    with pytest.raises(ValueError, match="exceed their supply lane capacity"):
        _materialize(recipes, inventory=_inventory((lane,)), source_resolver=object())


def test_initial_variable_plan_uses_all_historical_recipes_without_solver_or_legacy_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("initial variable plan reached selection or legacy topology machinery")

    for module, names in (
        (selection_pool, ("plan_variable_pool",)),
        (selection_solver, ("solve_selection_feasibility", "solve_final_selection")),
        (
            production_authoring,
            (
                "build_production_authoring_draft",
                "_choose_supported_sources",
                "_validate_res128_feasibility_baseline",
                "_read_res225_materialization_plan",
                "_apply_res225_materialization",
                "_mutation_lineage_specs",
                "_semantic_slot_specs",
                "_engine_slot_specs",
                "_synthetic_slot_specs",
            ),
        ),
        (
            res223_topology,
            ("read_repair_plan", "apply_repair_actions", "validate_topology_only_packet_change"),
        ),
        (
            production_contracts,
            ("validate_production_exact_feasibility", "validate_production_hard_feasibility"),
        ),
    ):
        for name in names:
            if hasattr(module, name):
                monkeypatch.setattr(module, name, forbidden)
    monkeypatch.setattr(
        variable_pool,
        "production_source_selection_universe",
        lambda *_args, **_kwargs: pytest.fail("source universe is unnecessary for these lanes"),
    )

    inputs = _historical_inputs()
    exclusion = _exclusion()
    inventory = _inventory_for_plan(exclusion, inputs=inputs)
    plan = build_initial_variable_pool_authoring_plan(
        inputs,
        inventory,
        exclusion,
        external_root=Path("/unused-for-source-free-plan"),
    )

    assert plan.recipes == historical_recipes_from_authoring_inputs(inputs)
    assert plan.supply_inventory_digest == inventory.inventory_digest
    assert plan.qualification_exclusion_digest == exclusion.commitment_digest


def test_initial_variable_plan_selects_current_source_cells_by_canonical_order_and_capacity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document_id = "document:synthetic-current"
    family_id = "family:synthetic-current"
    lane = _source_lane(
        document_id=document_id,
        family_id=family_id,
        capacity=1,
        cells=(("C01", "F01"), ("C01", "F03")),
    )
    selections = (
        SourceCellSelectionV1(
            pmcid="PMC-SYNTHETIC-CURRENT",
            capability_id="C01",
            benchmark_family="F03",
            applicability_scope="INDIRECT_MEASUREMENT_EVIDENCE",
            source_family_id=family_id,
            source_family_digest=_FORGED,
            search_strata=("stratum-a",),
            spans=(),
            population_clause_values=(),
        ),
        SourceCellSelectionV1(
            pmcid="PMC-SYNTHETIC-CURRENT",
            capability_id="C01",
            benchmark_family="F01",
            applicability_scope="INDIRECT_MEASUREMENT_EVIDENCE",
            source_family_id=family_id,
            source_family_digest=_FORGED,
            search_strata=("stratum-a",),
            spans=(),
            population_clause_values=(),
        ),
    )
    records = {
        "F03": _source_record(
            "PSE-V1-CANDIDATE:SOURCE:synthetic-current-02",
            document_id=document_id,
            family_id=family_id,
            cell=("C01", "F03"),
        ),
        "F01": _source_record(
            "PSE-V1-CANDIDATE:SOURCE:synthetic-current-01",
            document_id=document_id,
            family_id=family_id,
            cell=("C01", "F01"),
        ),
    }
    universe = list(selections)
    monkeypatch.setattr(
        variable_pool,
        "production_source_selection_universe",
        lambda *_args, **_kwargs: tuple(universe),
    )
    monkeypatch.setattr(
        variable_pool,
        "_source_authoring_records",
        lambda values: (records[values[0].benchmark_family],),
    )
    inputs = _historical_inputs()
    exclusion = _exclusion()
    inventory = _inventory_for_plan(exclusion, (lane,), inputs=inputs)

    first = build_initial_variable_pool_authoring_plan(
        inputs, inventory, exclusion, external_root=Path("/phase-a")
    )
    universe.reverse()
    second = build_initial_variable_pool_authoring_plan(
        inputs, inventory, exclusion, external_root=Path("/phase-a")
    )
    additions = tuple(
        item
        for item in first.recipes
        if item.authority_basis is RecipeAuthorityBasis.GOVERNED_SUPPLY_LANE
    )
    assert len(additions) == 1
    assert additions[0].candidate_id == "PSE-V1-CANDIDATE:SOURCE:synthetic-current-01"
    assert additions[0].lane_id == lane.lane_id
    assert first == second


def test_initial_variable_plan_requires_exact_current_source_for_historical_source_recipe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = _inputs_with_source()
    exclusion = _exclusion()
    inventory = _inventory_for_plan(exclusion, inputs=inputs)
    monkeypatch.setattr(variable_pool, "production_source_selection_universe", lambda *_a, **_k: ())
    with pytest.raises(ValueError, match="exact current Phase-A authority"):
        build_initial_variable_pool_authoring_plan(
            inputs,
            inventory,
            exclusion,
            external_root=Path("/phase-a"),
        )


def _expert_lane(status: LaneCapacityStatus) -> ReserveCandidateLaneV1:
    batch = _canonical()[_SEM_A].expert_batch
    assert batch is not None
    return ReserveCandidateLaneV1(
        lane_id=_opaque_id("expert-batch", batch.author_batch_id),
        origin_class=CaseOrigin.EXPERT_AUTHORED_SEMANTIC,
        authority_ref="expert batch/template/isolation identity with individual recipes",
        authority_digest=canonical_hash(
            (
                "EXPERT_BATCH_IDENTITY",
                batch.author_batch_id,
                batch.protocol_template_id,
                batch.isolation_cluster_id,
            )
        ),
        capacity_unit="individually authorized expert-semantic recipe",
        existing_planned_capacity=0,
        available_capacity=2,
        capacity_status=status,
        capacity_rule="test",
        supported_cells=(("C01", "F01"),),
        isolation_identity_digests=tuple(
            sorted(
                {
                    canonical_hash(("EXPERT_BATCH", batch.author_batch_id)),
                    canonical_hash(("PROTOCOL_TEMPLATE", batch.protocol_template_id)),
                    canonical_hash(("EXPERT_ISOLATION_CLUSTER", batch.isolation_cluster_id)),
                }
            )
        ),
    )


def _engine_lane(status: LaneCapacityStatus, reference_id: str) -> ReserveCandidateLaneV1:
    return ReserveCandidateLaneV1(
        lane_id=f"engine:C16:F05:{reference_id}",
        origin_class=CaseOrigin.DETERMINISTIC_ENGINE_DERIVED,
        authority_ref="RES-71 reference, operation, and individually authorized recipes",
        authority_digest=canonical_hash(("engine lane", reference_id)),
        capacity_unit="individually authorized RES-71 engine recipe",
        existing_planned_capacity=0,
        available_capacity=2,
        capacity_status=status,
        capacity_rule="test",
        supported_cells=(("C16", "F05"),),
        isolation_identity_digests=(canonical_hash(("RES71_ENGINE_REFERENCE_CASE", reference_id)),),
    )


def _as_governed(
    recipe: ProductionCandidateRecipeV1, lane: ReserveCandidateLaneV1, **changes: Any
) -> ProductionCandidateRecipeV1:
    return _forge(
        recipe,
        candidate_id=recipe.candidate_id[:-2] + "77",
        authority_basis=_GOVERNED,
        lane_id=lane.lane_id,
        authority_digest=lane.authority_digest,
        **changes,
    )


def test_engine_and_expert_existing_recipe_inventory_is_not_authorable() -> None:
    reference = production_engine_reference_case_id("C16", "F05", 0)
    for lane, source in (
        (_engine_lane(LaneCapacityStatus.EXISTING_RECIPE_INVENTORY, reference), _ENGINE),
        (_expert_lane(LaneCapacityStatus.EXISTING_RECIPE_INVENTORY), _SEM_A),
    ):
        recipe = _canonical()[source]
        governed = _as_governed(
            recipe,
            lane,
            expert_batch=(
                None
                if recipe.expert_batch is None
                else replace(recipe.expert_batch, candidate_ids=(recipe.candidate_id[:-2] + "77",))
            ),
        )
        with pytest.raises(ValueError, match="authorable supply lane"):
            _materialize((governed,), inventory=_inventory((lane,)))


def test_engine_and_expert_lanes_bind_exact_reference_and_batch_identity() -> None:
    reference = production_engine_reference_case_id("C16", "F05", 0)
    engine_lane = _engine_lane(LaneCapacityStatus.AVAILABLE, reference)
    engine = _canonical()[_ENGINE]
    other_slot = next(
        slot
        for slot in range(1, 32)
        if production_engine_reference_case_id("C16", "F05", slot) != reference
    )
    with pytest.raises(ValueError, match="authorable supply lane"):
        _materialize(
            (_as_governed(engine, engine_lane, slot_index=other_slot),),
            inventory=_inventory((engine_lane,)),
        )

    expert_lane = _expert_lane(LaneCapacityStatus.AVAILABLE)
    semantic = _canonical()[_SEM_A]
    new_id = semantic.candidate_id[:-2] + "77"
    assert semantic.expert_batch is not None
    forged_batch = replace(
        semantic.expert_batch,
        isolation_cluster_id="PSE-V1-SEMANTIC-CLUSTER:forged",
        candidate_ids=(new_id,),
    )
    with pytest.raises(ValueError, match="authorable supply lane"):
        _materialize(
            (_as_governed(semantic, expert_lane, expert_batch=forged_batch),),
            inventory=_inventory((expert_lane,)),
        )


def test_historical_v12_inventory_cannot_authorize_materialization() -> None:
    lane = _generator_lane(SplitName.HIDDEN_FINAL)
    inventory = _inventory((lane,), schema=AUTHORITY_SUPPLY_SCHEMA_V1_2)
    with pytest.raises(ValueError, match="decode-only evidence"):
        _materialize((_governed_synthetic(lane),), inventory=inventory)
    with pytest.raises(ValueError, match="decode-only evidence"):
        _materialize(tuple(_canonical().values()), inventory=inventory, inputs=_historical_inputs())
