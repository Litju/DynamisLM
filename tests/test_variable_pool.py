from __future__ import annotations

from dataclasses import replace

import pytest

from dynamislm.benchmark import variable_pool
from dynamislm.benchmark.constants import CaseOrigin, SplitName
from dynamislm.benchmark.production_authoring import (
    ProductionExpertBatchV1,
    ProductionSourceSelectionV1,
)
from dynamislm.benchmark.selection_constraints import FINAL_CASE_COUNT
from dynamislm.benchmark.variable_pool import (
    PRE_REVIEW_POOL_MINIMUM,
    ProductionAuthoringCandidatePoolV1,
    ProductionCandidateRecipeV1,
    RecipeAuthorityBasis,
    VariablePoolAuthoringPlanV1,
    require_pre_review_pool_minimum,
)
from dynamislm.qualification.res115_authoring import _semantic_cell_candidate

_SHA = "sha256:" + "a" * 64
_SUPPLY = "sha256:" + "b" * 64
_EXCLUSION = "sha256:" + "c" * 64
_HISTORICAL = RecipeAuthorityBasis.HISTORICAL_INDIVIDUAL_RECIPE


def _semantic(candidate_id: str = "PSE-V1-CANDIDATE:SEM:C01:F01:00") -> ProductionCandidateRecipeV1:
    return ProductionCandidateRecipeV1(
        candidate_id=candidate_id,
        origin_class=CaseOrigin.EXPERT_AUTHORED_SEMANTIC,
        capability_id="C01",
        benchmark_family="F01",
        authority_basis=_HISTORICAL,
        authority_ref="synthetic test recipe authority",
        authority_digest=_SHA,
        slot_index=0,
        scenario_seed="synthetic-test-seed",
        expert_batch=ProductionExpertBatchV1(
            author_batch_id="test-batch",
            protocol_template_id="test-template",
            isolation_cluster_id="test-cluster",
            candidate_ids=(candidate_id,),
            rationale="synthetic test batch identity",
        ),
    )


def _synthetic(
    candidate_id: str = "PSE-V1-CANDIDATE:SYNTH:C08:F05:TEST",
    split: SplitName = SplitName.HIDDEN_FINAL,
) -> ProductionCandidateRecipeV1:
    return ProductionCandidateRecipeV1(
        candidate_id=candidate_id,
        origin_class=CaseOrigin.DETERMINISTIC_SYNTHETIC,
        capability_id="C08",
        benchmark_family="F05",
        authority_basis=RecipeAuthorityBasis.GOVERNED_SUPPLY_LANE,
        authority_ref="synthetic test generator lane",
        authority_digest=_SHA,
        lane_id="synthetic:pse-v1-synthetic-refusal-" + split.value.lower(),
        generator_family="pse-v1-synthetic-refusal-" + split.value.lower(),
        split_lock=split,
        seed_block="synthetic-test-seed-block",
    )


def _mutation(
    candidate_id: str = "PSE-V1-CANDIDATE:MUT:TEST:01",
    parent_id: str = "PSE-V1-CANDIDATE:SEM:C01:F01:00",
    stage: int = 1,
) -> ProductionCandidateRecipeV1:
    return ProductionCandidateRecipeV1(
        candidate_id=candidate_id,
        origin_class=CaseOrigin.ADVERSARIAL_MUTATION,
        capability_id="C01",
        benchmark_family="F01",
        authority_basis=_HISTORICAL,
        authority_ref="synthetic test mutation authority",
        authority_digest=_SHA,
        seed_block="synthetic-mutation-seed",
        mutation_parent_candidate_id=parent_id,
        mutation_lineage_id="test-lineage",
        mutation_operator_id="measurement-identity-trap",
        mutation_stage=stage,
    )


def _plan(*recipes: ProductionCandidateRecipeV1) -> VariablePoolAuthoringPlanV1:
    return VariablePoolAuthoringPlanV1(
        supply_inventory_digest=_SUPPLY,
        qualification_exclusion_digest=_EXCLUSION,
        recipes=tuple(sorted(recipes, key=lambda item: item.candidate_id.encode())),
    )


def test_recipe_binds_origin_specific_authority_and_digest() -> None:
    recipe = _semantic()

    assert recipe.recipe_digest.startswith("sha256:")
    assert replace(recipe, recipe_digest="").recipe_digest == recipe.recipe_digest
    with pytest.raises(ValueError, match="digest does not match"):
        replace(recipe, recipe_digest="sha256:" + "f" * 64)
    with pytest.raises(ValueError, match="digest does not match"):
        replace(_semantic(), scenario_seed="changed-seed", recipe_digest=recipe.recipe_digest)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda item: replace(item, scenario_seed=None, recipe_digest=""),
        lambda item: replace(item, slot_index=-1, recipe_digest=""),
        lambda item: replace(item, seed_block="extra", recipe_digest=""),
        lambda item: replace(item, capability_id="C99", recipe_digest=""),
        lambda item: replace(item, candidate_id="OTHER:1", recipe_digest=""),
        lambda item: replace(item, authority_digest="not-a-digest", recipe_digest=""),
        lambda item: replace(item, lane_id="lane:unexpected", recipe_digest=""),
        lambda item: replace(
            item,
            expert_batch=replace(
                item.expert_batch,
                candidate_ids=(
                    "PSE-V1-CANDIDATE:SEM:C01:F01:00",
                    "PSE-V1-CANDIDATE:SEM:C01:F01:01",
                ),
            ),
            recipe_digest="",
        ),
    ],
    ids=(
        "missing-seed",
        "negative-slot",
        "foreign-payload",
        "unknown-cell",
        "foreign-id",
        "bad-authority",
        "historical-lane",
        "batch-membership",
    ),
)
def test_semantic_recipe_rejects_invalid_or_topology_bearing_payloads(mutate: object) -> None:
    with pytest.raises(ValueError):
        mutate(_semantic())  # type: ignore[operator]


def test_synthetic_engine_source_and_mutation_recipes_fail_closed() -> None:
    assert _synthetic().split_lock is SplitName.HIDDEN_FINAL
    with pytest.raises(ValueError, match="registered generator split"):
        replace(_synthetic(), split_lock=SplitName.PUBLIC_DEVELOPMENT, recipe_digest="")
    with pytest.raises(ValueError, match="registered generator split"):
        replace(_synthetic(), capability_id="C01", benchmark_family="F01", recipe_digest="")
    with pytest.raises(ValueError, match="bind a supply lane"):
        replace(_synthetic(), lane_id=None, recipe_digest="")
    with pytest.raises(ValueError, match="RES-71 adapter"):
        ProductionCandidateRecipeV1(
            candidate_id="PSE-V1-CANDIDATE:ENGINE:C01:F01:00",
            origin_class=CaseOrigin.DETERMINISTIC_ENGINE_DERIVED,
            capability_id="C01",
            benchmark_family="F01",
            authority_basis=_HISTORICAL,
            authority_ref="synthetic test engine authority",
            authority_digest=_SHA,
            slot_index=0,
            scenario_seed="seed",
        )
    record = ProductionSourceSelectionV1(
        candidate_id="PSE-V1-CANDIDATE:SOURCE:TEST",
        capability_id="C01",
        benchmark_family="F01",
        pmcid="PMC00000001",
        document_id="source-document:test",
        source_family_id="source-family:test",
        applicability_scope="POPULATION_EVIDENCE",
        span_digests=(_SHA,),
        search_strata=(),
        direct_target_document=False,
    )
    source = ProductionCandidateRecipeV1(
        candidate_id=record.candidate_id,
        origin_class=CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION,
        capability_id="C01",
        benchmark_family="F01",
        authority_basis=_HISTORICAL,
        authority_ref="synthetic test source authority",
        authority_digest=_SHA,
        source_record=record,
    )
    with pytest.raises(ValueError, match="exact source selection"):
        replace(source, benchmark_family="F03", recipe_digest="")
    assert _mutation().mutation_stage == 1
    with pytest.raises(ValueError, match="parent, lineage, operator"):
        replace(_mutation(), mutation_stage=0, recipe_digest="")
    with pytest.raises(ValueError, match="parent, lineage, operator"):
        replace(
            _mutation(), mutation_parent_candidate_id=_mutation().candidate_id, recipe_digest=""
        )


def test_variable_plan_has_no_count_composition_or_lineage_geometry_target() -> None:
    synthetic_only = _plan(
        *(_synthetic(f"PSE-V1-CANDIDATE:SYNTH:C08:F05:TEST-{index:03d}") for index in range(5))
    )
    assert synthetic_only.candidate_count == 5
    assert synthetic_only.origin_counts == ((CaseOrigin.DETERMINISTIC_SYNTHETIC, 5),)

    # One parent with a four-stage chain and a second branch: nothing requires 37 x 3.
    chain = (
        _semantic(),
        _mutation("PSE-V1-CANDIDATE:MUT:TEST:01"),
        _mutation("PSE-V1-CANDIDATE:MUT:TEST:02", "PSE-V1-CANDIDATE:MUT:TEST:01", 2),
        _mutation("PSE-V1-CANDIDATE:MUT:TEST:03", "PSE-V1-CANDIDATE:MUT:TEST:02", 3),
        _mutation("PSE-V1-CANDIDATE:MUT:TEST:04", "PSE-V1-CANDIDATE:MUT:TEST:03", 4),
        _mutation("PSE-V1-CANDIDATE:MUT:TEST:05"),
    )
    plan = _plan(*chain)
    assert plan.candidate_count == 6
    assert plan.plan_digest == _plan(*reversed(chain)).plan_digest


def test_variable_plan_rejects_order_duplicates_and_unresolved_or_cyclic_parents() -> None:
    semantic = _semantic()
    with pytest.raises(ValueError, match="candidate ordered"):
        VariablePoolAuthoringPlanV1(
            supply_inventory_digest=_SUPPLY,
            qualification_exclusion_digest=_EXCLUSION,
            recipes=(_synthetic(), semantic),
        )
    with pytest.raises(ValueError, match="candidate ordered"):
        VariablePoolAuthoringPlanV1(
            supply_inventory_digest=_SUPPLY,
            qualification_exclusion_digest=_EXCLUSION,
            recipes=(semantic, semantic),
        )
    with pytest.raises(ValueError, match="non-empty"):
        VariablePoolAuthoringPlanV1(
            supply_inventory_digest=_SUPPLY, qualification_exclusion_digest=_EXCLUSION, recipes=()
        )
    with pytest.raises(ValueError, match="resolve acyclically"):
        _plan(_mutation())
    with pytest.raises(ValueError, match="resolve acyclically"):
        _plan(
            _mutation("PSE-V1-CANDIDATE:MUT:TEST:01", "PSE-V1-CANDIDATE:MUT:TEST:02"),
            _mutation("PSE-V1-CANDIDATE:MUT:TEST:02", "PSE-V1-CANDIDATE:MUT:TEST:01", 2),
        )
    with pytest.raises(ValueError, match="supply and exclusion"):
        replace(_plan(semantic), supply_inventory_digest="missing", plan_digest="")
    with pytest.raises(ValueError, match="digest mismatch"):
        replace(_plan(semantic), plan_digest="sha256:" + "f" * 64)


def test_pool_binds_plan_and_enforces_only_the_res258_lower_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert PRE_REVIEW_POOL_MINIMUM == FINAL_CASE_COUNT == 434
    packets = tuple(
        sorted(
            (_semantic_cell_candidate("C01", "F01"), _semantic_cell_candidate("C02", "F02")),
            key=lambda item: item.candidate_id.encode(),
        )
    )
    pool = ProductionAuthoringCandidatePoolV1(authoring_plan_digest=_SHA, packets=packets)
    assert pool.candidate_count == 2
    with pytest.raises(ValueError, match="at least 434"):
        require_pre_review_pool_minimum(pool)
    monkeypatch.setattr(variable_pool, "PRE_REVIEW_POOL_MINIMUM", 2)
    require_pre_review_pool_minimum(pool)
    with pytest.raises(ValueError, match="candidate ordered"):
        ProductionAuthoringCandidatePoolV1(
            authoring_plan_digest=_SHA, packets=tuple(reversed(packets))
        )
    with pytest.raises(ValueError, match="authoring plan binding"):
        ProductionAuthoringCandidatePoolV1(authoring_plan_digest="missing", packets=packets)
    with pytest.raises(ValueError, match="digest mismatch"):
        ProductionAuthoringCandidatePoolV1(
            authoring_plan_digest=_SHA, packets=packets, pool_digest="sha256:" + "f" * 64
        )
