from __future__ import annotations

import hashlib
from dataclasses import replace

import pytest

from dynamislm.benchmark import production, production_authoring, res223_topology
from dynamislm.benchmark.authority_supply import (
    AUTHORITY_SUPPLY_SCHEMA,
    AuthoritySupplyInventoryV1,
)
from dynamislm.benchmark.constants import CaseOrigin, SplitName
from dynamislm.benchmark.contamination import exact_13_token_shingles, normalized_text_sha256
from dynamislm.benchmark.production_authoring import (
    PRODUCTION_SYNTHETIC_GENERATOR_DIGEST,
    ProductionAuthoringInputsV1,
    ProductionExpertBatchV1,
    ProductionMutationLineageInputV1,
    _author_engine_packets,
    _author_semantic_packets,
    _author_synthetic_packets,
    _scope_production_author_batch,
    production_authoring_input_digest,
)
from dynamislm.benchmark.production_exclusions import (
    QUALIFICATION_001B_BATCH_ID,
    QUALIFICATION_EXCLUSION_VERSION,
    QualificationExclusionCandidateV1,
    QualificationExclusionCommitmentV1,
    bind_qualification_exclusion_commitment,
)
from dynamislm.benchmark.variable_pool import (
    ProductionCandidateRecipeV1,
    RecipeAuthorityBasis,
    VariablePoolAuthoringPlanV1,
    historical_recipes_from_authoring_inputs,
    materialize_variable_pool,
    production_engine_reference_case_id,
    project_variable_pool_selection_candidates,
    validate_variable_pre_review_pool,
)

_SHA = "sha256:" + "d" * 64
_SEM_A = "PSE-V1-CANDIDATE:SEM:C01:F01:00"
_SEM_B = "PSE-V1-CANDIDATE:SEM:C01:F03:01"
_ENGINE = "PSE-V1-CANDIDATE:ENGINE:C16:F05:00"
_SYNTH = "PSE-V1-CANDIDATE:SYNTH:C08:F05:HIDDEN_FINAL"
_LINEAGE = "PSE-V1-MUTATION-LINEAGE:synthetictest0001"
_MUT_1 = "PSE-V1-CANDIDATE:MUT:synthetictest0001:01"
_MUT_2 = "PSE-V1-CANDIDATE:MUT:synthetictest0001:02"


def _seed(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()[:48]


def _historical_inputs(*, engine_seed: str = _seed("engine")) -> ProductionAuthoringInputsV1:
    provisional = ProductionAuthoringInputsV1(
        batch_id=production.PRODUCTION_BATCH_ID,
        synthetic_generator_registry_digest=PRODUCTION_SYNTHETIC_GENERATOR_DIGEST,
        scenario_seeds=tuple(
            sorted(
                ((_SEM_A, _seed("sem-a")), (_SEM_B, _seed("sem-b")), (_ENGINE, engine_seed)),
                key=lambda item: item[0].encode(),
            )
        ),
        synthetic_seed_blocks=((_SYNTH, _seed("synth")),),
        mutation_seed_blocks=((_MUT_1, _seed("mut-1")), (_MUT_2, _seed("mut-2"))),
        source_selections=(),
        expert_batches=(
            ProductionExpertBatchV1(
                author_batch_id="PSE-V1-EXPERT-BATCH:synthetictest0001",
                protocol_template_id="PSE-V1-PROTOCOL-TEMPLATE:synthetictest0001",
                isolation_cluster_id="PSE-V1-SEMANTIC-CLUSTER:synthetictest0001",
                candidate_ids=(_SEM_A, _SEM_B),
                rationale="Two frozen cells share a bounded synthetic test context.",
            ),
        ),
        mutation_lineages=(
            ProductionMutationLineageInputV1(
                lineage_id=_LINEAGE,
                parent_candidate_id=_SEM_A,
                child_candidate_ids=(_MUT_1, _MUT_2),
                operator_id="measurement-identity-trap",
                rationale="Synthetic test identity-trap chain.",
            ),
        ),
        input_digest="sha256:" + "0" * 64,
    )
    return replace(provisional, input_digest=production_authoring_input_digest(provisional))


def _exclusion() -> QualificationExclusionCommitmentV1:
    question = "unrelated qualification sentinel about rowing ergometer calibration drift notes"
    entry = QualificationExclusionCandidateV1(
        candidate_id="PSE-V1-QUALIFICATION:TEST:VARIABLE-POOL",
        candidate_payload_hash=_SHA,
        question_text=question,
        exact_question_sha256="sha256:" + hashlib.sha256(question.encode()).hexdigest(),
        normalized_question_sha256=normalized_text_sha256(question),
        question_13_token_shingle_hashes=tuple(sorted(exact_13_token_shingles(question))),
        seed_blocks=(),
        seed_namespaces=(),
        generator_seed_identities=(),
        mutation_lineage_ids=(),
        mutation_seed_values=(),
        evidence_span_identities=(),
    )
    return bind_qualification_exclusion_commitment(
        QualificationExclusionCommitmentV1(
            batch_id=QUALIFICATION_001B_BATCH_ID,
            version=QUALIFICATION_EXCLUSION_VERSION,
            qualification_manifest_digest=_SHA,
            qualification_store_receipt_digest=_SHA,
            authoring_plan_digest=_SHA,
            seed_input_digest=_SHA,
            candidate_count=1,
            entries=(entry,),
            commitment_digest="sha256:" + "0" * 64,
        )
    )


def _inventory() -> AuthoritySupplyInventoryV1:
    return AuthoritySupplyInventoryV1(
        schema_version=AUTHORITY_SUPPLY_SCHEMA,
        atoms=(),
        reserve_candidate_lanes=(),
        planned_origin_counts=(),
        planned_mutation_lineage_count=0,
        materialized_candidate_count=0,
        evidence_bindings=(),
        authority_inventory_complete=True,
        capacity_scope_complete=False,
    )


def _plan(
    recipes: tuple[ProductionCandidateRecipeV1, ...],
    *,
    inventory: AuthoritySupplyInventoryV1 | None = None,
) -> VariablePoolAuthoringPlanV1:
    return VariablePoolAuthoringPlanV1(
        supply_inventory_digest=(inventory or _inventory()).inventory_digest,
        qualification_exclusion_digest=_exclusion().commitment_digest,
        recipes=recipes,
    )


def test_historical_inputs_decompose_into_individual_recipes_without_topology() -> None:
    inputs = _historical_inputs()
    recipes = {item.candidate_id: item for item in historical_recipes_from_authoring_inputs(inputs)}

    assert set(recipes) == {_SEM_A, _SEM_B, _ENGINE, _SYNTH, _MUT_1, _MUT_2}
    assert {item.authority_basis for item in recipes.values()} == {
        RecipeAuthorityBasis.HISTORICAL_INDIVIDUAL_RECIPE
    }
    # Batch identity survives per recipe; historical batch membership does not.
    batch_a = recipes[_SEM_A].expert_batch
    batch_b = recipes[_SEM_B].expert_batch
    assert batch_a is not None and batch_b is not None
    assert batch_a.candidate_ids == (_SEM_A,)
    assert batch_b.candidate_ids == (_SEM_B,)
    assert batch_b.author_batch_id == batch_a.author_batch_id
    assert (recipes[_ENGINE].capability_id, recipes[_ENGINE].slot_index) == ("C16", 0)
    assert recipes[_SYNTH].split_lock is SplitName.HIDDEN_FINAL
    assert recipes[_MUT_1].mutation_parent_candidate_id == _SEM_A
    assert recipes[_MUT_2].mutation_parent_candidate_id == _MUT_1
    assert (recipes[_MUT_2].mutation_stage, recipes[_MUT_2].capability_id) == (2, "C01")
    changed = {
        item.candidate_id: item
        for item in historical_recipes_from_authoring_inputs(
            _historical_inputs(engine_seed=_seed("other"))
        )
    }
    assert changed[_SEM_A].authority_digest != recipes[_SEM_A].authority_digest


def test_historical_decomposition_fails_closed_on_untyped_or_inconsistent_inputs() -> None:
    inputs = _historical_inputs()
    unknown = replace(
        inputs,
        scenario_seeds=tuple(
            sorted(
                (*inputs.scenario_seeds, ("PSE-V1-CANDIDATE:OTHER:1", _seed("x"))),
                key=lambda item: item[0].encode(),
            )
        ),
    )
    with pytest.raises(ValueError, match="does not name a recipe identity"):
        historical_recipes_from_authoring_inputs(
            replace(unknown, input_digest=production_authoring_input_digest(unknown))
        )
    with pytest.raises(ValueError, match="digest does not match"):
        historical_recipes_from_authoring_inputs(replace(inputs, input_digest=_SHA))
    orphan = replace(inputs, mutation_seed_blocks=((_MUT_1, _seed("mut-1")),))
    with pytest.raises(ValueError, match="parent/operator chains"):
        historical_recipes_from_authoring_inputs(
            replace(orphan, input_digest=production_authoring_input_digest(orphan))
        )
    engine_batch = replace(
        inputs,
        expert_batches=(
            replace(inputs.expert_batches[0], candidate_ids=tuple(sorted((_SEM_A, _ENGINE)))),
        ),
    )
    with pytest.raises(ValueError, match="differs from recipe origin"):
        historical_recipes_from_authoring_inputs(
            replace(engine_batch, input_digest=production_authoring_input_digest(engine_batch))
        )


def test_individual_recipes_reproduce_historical_builder_packets_exactly() -> None:
    inputs = _historical_inputs()
    recipes = historical_recipes_from_authoring_inputs(inputs)
    pool = materialize_variable_pool(
        _plan(recipes),
        supply_inventory=_inventory(),
        exclusion=_exclusion(),
        source_resolver=None,
    )
    packets = {packet.candidate_id: packet for packet in pool.packets}

    historical = {
        packet.candidate_id: _scope_production_author_batch(packet)
        for packet in (
            *_author_semantic_packets(
                ((_SEM_A, "C01", "F01", 0), (_SEM_B, "C01", "F03", 1)), inputs
            ),
            *_author_engine_packets(((_ENGINE, "C16", "F05", 0),), inputs),
            *_author_synthetic_packets(((_SYNTH, "F05", SplitName.HIDDEN_FINAL),), inputs),
        )
    }
    for candidate_id, packet in historical.items():
        assert packets[candidate_id].candidate_payload_hash == packet.candidate_payload_hash
    stage_two = packets[_MUT_2].parent_candidate_binding
    assert stage_two is not None
    assert stage_two.parent_candidate_payload_hash == packets[_MUT_1].candidate_payload_hash
    assert packets[_ENGINE].proposed_provenance.engine_reference_case_id == (
        production_engine_reference_case_id("C16", "F05", 0)
    )
    projected = project_variable_pool_selection_candidates(pool, source_resolver=None)
    assert {item.candidate_id for item in projected} == set(packets)
    assert all(len(item.exact_shingle_digests) > 1 for item in projected)
    with pytest.raises(ValueError, match="at least 434"):
        validate_variable_pre_review_pool(pool, exclusion=_exclusion(), source_resolver=None)


def test_any_recipe_subset_materializes_without_historical_counts_or_geometry() -> None:
    recipes = {
        item.candidate_id: item
        for item in historical_recipes_from_authoring_inputs(_historical_inputs())
    }
    subset = (recipes[_ENGINE], recipes[_SYNTH])
    pool = materialize_variable_pool(
        _plan(tuple(sorted(subset, key=lambda item: item.candidate_id.encode()))),
        supply_inventory=_inventory(),
        exclusion=_exclusion(),
        source_resolver=None,
    )
    assert {packet.proposed_provenance.origin_class for packet in pool.packets} == {
        CaseOrigin.DETERMINISTIC_ENGINE_DERIVED,
        CaseOrigin.DETERMINISTIC_SYNTHETIC,
    }
    with pytest.raises(ValueError, match="resolve acyclically"):
        _plan((recipes[_MUT_1],))


def test_materialization_rejects_foreign_authority_and_unknown_governed_lanes() -> None:
    recipes = historical_recipes_from_authoring_inputs(_historical_inputs())
    other_inventory = replace(_inventory(), materialized_candidate_count=1, inventory_digest="")
    with pytest.raises(ValueError, match="different supply or exclusion"):
        materialize_variable_pool(
            _plan(recipes, inventory=other_inventory),
            supply_inventory=_inventory(),
            exclusion=_exclusion(),
            source_resolver=None,
        )
    synthetic = next(item for item in recipes if item.candidate_id == _SYNTH)
    governed = replace(
        synthetic,
        candidate_id="PSE-V1-CANDIDATE:SYNTH:C08:F05:GOVERNED-TEST",
        authority_basis=RecipeAuthorityBasis.GOVERNED_SUPPLY_LANE,
        lane_id="synthetic:pse-v1-synthetic-refusal-hidden_final",
        recipe_digest="",
    )
    with pytest.raises(ValueError, match="authorable supply lane"):
        materialize_variable_pool(
            _plan((governed,)),
            supply_inventory=_inventory(),
            exclusion=_exclusion(),
            source_resolver=None,
        )


def test_modern_materialization_never_reaches_superseded_historical_gates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("modern variable pool reached superseded historical authority")

    for module, names in (
        (
            production_authoring,
            (
                "build_production_authoring_draft",
                "_authoring_input_skeleton",
                "_new_or_resume_private_inputs",
                "_validate_res128_feasibility_baseline",
                "_read_res225_materialization_plan",
                "_apply_res225_materialization",
                "_mutation_lineage_specs",
                "_semantic_slot_specs",
                "_engine_slot_specs",
                "_synthetic_slot_specs",
                "_author_mutation_packets",
                "_choose_supported_sources",
                "read_repair_plan",
                "apply_repair_actions",
                "validate_topology_only_packet_change",
            ),
        ),
        (
            res223_topology,
            ("read_repair_plan", "apply_repair_actions", "bind_repair_plan", "write_repair_plan"),
        ),
        (
            production,
            (
                "validate_production_exact_feasibility",
                "validate_production_hard_feasibility",
                "validate_production_candidate_set",
                "bind_production_authoring_plan",
            ),
        ),
    ):
        for name in names:
            monkeypatch.setattr(module, name, forbidden)

    pool = materialize_variable_pool(
        _plan(historical_recipes_from_authoring_inputs(_historical_inputs())),
        supply_inventory=_inventory(),
        exclusion=_exclusion(),
        source_resolver=None,
    )
    assert pool.candidate_count == 6
