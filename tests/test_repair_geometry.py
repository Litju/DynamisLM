"""Synthetic falsification cases and the external, exact RES-407 regression."""

from dataclasses import replace
from importlib.metadata import version
from types import SimpleNamespace

import pytest

import dynamislm.benchmark.repair_geometry as repair_geometry_module
from dynamislm.benchmark.authority_supply import (
    AUTHORITY_SUPPLY_SCHEMA,
    AdditionalCapacityStatus,
    AuthoritySupplyInventoryV1,
    LaneCapacityStatus,
    ReserveCandidateLaneV1,
)
from dynamislm.benchmark.constants import SPLIT_ORDER, CaseOrigin, SplitName
from dynamislm.benchmark.coverage import COVERAGE_MATRIX
from dynamislm.benchmark.production_authoring import PRODUCTION_SYNTHETIC_GENERATORS
from dynamislm.benchmark.repair_geometry import (
    IDEAL_REPAIR_IS_RELAXATION,
    IDEAL_REPAIR_RELAXATION_DEFINITION,
    RES407_STRUCTURAL_REPAIR_MASTER_PROFILE_V1,
    RES407_STRUCTURAL_REPAIR_MASTER_PROFILE_VERSION,
    ContractCertainty,
    RepairArchetype,
    RepairCardinalityTrial,
    RepairClassification,
    RepairGeometry,
    RepairSignature,
    SplitCapacityCertificate,
    _structural_repair_model,
    archetype_structural_contracts,
    bind_split_capacity_certificate,
    build_compact_ideal_repair_signatures,
    build_ideal_repair_signatures,
    build_optimistic_c08_signatures,
    classify_archetype_repair,
    classify_repair_master_unknown,
    compute_split_capacity_envelope,
    derive_archetype_saturation_bounds,
    derive_governed_archetypes,
    remaining_lane_capacity,
    solve_ideal_repair_minimum,
    solve_repair_cardinality_decision,
    structural_bottleneck_evidence,
)
from dynamislm.benchmark.selection_contracts import (
    POOL_FEASIBILITY_SOLVER_PROFILE_VERSION,
    PSE_V1_POOL_FEASIBILITY_SOLVER_PROFILE_V1,
    AssignmentState,
    ConstraintKind,
    FeatureKind,
    RelationKind,
    ReviewEligibility,
    SelectionConstraint,
    SelectionFeature,
    SelectionSolverConfig,
)
from dynamislm.benchmark.selection_solver import _model_for, _solve_once
from dynamislm.serialization import canonical_hash, canonical_json, from_canonical_json
from test_res369_selection import _candidate, _toy_problem

PUBLIC = SplitName.PUBLIC_DEVELOPMENT
VALIDATION = SplitName.FROZEN_VALIDATION


def _geometry() -> RepairGeometry:
    # b connects two hyperedges, but OUT b permits a and c in different splits.
    candidates = (
        _candidate("a"),
        _candidate("b", excluded=True),
        _candidate("c", origin=CaseOrigin.DETERMINISTIC_SYNTHETIC, locked_split=VALIDATION),
    )
    edges = tuple(
        SelectionConstraint(
            f"TEST:EDGE:{i}",
            "synthetic geometry",
            ConstraintKind.CONDITIONAL_COLOCATION,
            candidate_ids=ids,
            relation_kind=RelationKind.ISOLATION_CLUSTER,
        )
        for i, ids in enumerate((("a", "b"), ("b", "c")))
    )
    return RepairGeometry(_toy_problem(candidates, ((PUBLIC, 1), (VALIDATION, 1)), extra=edges))


def test_out_vertex_does_not_collapse_conditional_hyperedges() -> None:
    geometry = _geometry()
    (certificate,) = compute_split_capacity_envelope(geometry, splits=(PUBLIC,))
    assert certificate.maximum == 1
    assert {a.candidate_id: a.state for a in certificate.witness.assignments} == {
        "a": AssignmentState.PUBLIC_DEVELOPMENT,
        "b": AssignmentState.OUT,
        "c": AssignmentState.FROZEN_VALIDATION,
    }
    assert len(geometry.constraints(ConstraintKind.CONDITIONAL_COLOCATION)) == 2
    decoded = from_canonical_json(canonical_json(certificate), SplitCapacityCertificate)
    assert decoded.result_digest == certificate.result_digest


@pytest.mark.parametrize("status", ("UNKNOWN", "FEASIBLE", "INFEASIBLE"))
def test_capacity_requires_optimal_proof(monkeypatch: pytest.MonkeyPatch, status: str) -> None:
    monkeypatch.setattr(
        "dynamislm.benchmark.repair_geometry._solve_once", lambda *_: (None, status, 0)
    )
    with pytest.raises(ValueError, match="OPTIMAL"):
        compute_split_capacity_envelope(_geometry(), splits=(PUBLIC,))


def test_optimal_status_with_wrong_objective_bound_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    solver = SimpleNamespace(value=lambda _: 1, best_objective_bound=2)
    monkeypatch.setattr(
        "dynamislm.benchmark.repair_geometry._solve_once", lambda *_: (solver, "OPTIMAL", 0)
    )
    with pytest.raises(ValueError, match="bound"):
        compute_split_capacity_envelope(_geometry(), splits=(PUBLIC,))


def test_integer_timeout_has_a_stable_certificate_roundtrip() -> None:
    (certificate,) = compute_split_capacity_envelope(
        _geometry(),
        splits=(PUBLIC,),
        solver_config=SelectionSolverConfig(timeout_s=5),
    )
    decoded = from_canonical_json(canonical_json(certificate), SplitCapacityCertificate)
    assert certificate.result_digest == decoded.result_digest


def test_relaxations_are_bound_and_capacity_is_derived() -> None:
    geometry = _geometry()
    (certificate,) = compute_split_capacity_envelope(geometry, splits=(PUBLIC,))
    expected = tuple(
        c.constraint_id
        for c in geometry.problem.constraint_set.constraints
        if c.kind is ConstraintKind.SPLIT_COUNT
    )
    assert certificate.relaxed_constraint_ids == expected
    assert certificate.original_problem_digest == geometry.problem.problem_digest
    assert certificate.active_constraint_inventory_digest != (
        certificate.original_constraint_inventory_digest
    )
    assert replace(certificate, required=2).result_digest != certificate.result_digest
    (relaxed,) = compute_split_capacity_envelope(
        geometry,
        splits=(VALIDATION,),
        ablate=(ConstraintKind.CONDITIONAL_COLOCATION,),
    )
    assert relaxed.maximum == 2
    assert set(expected) < set(relaxed.relaxed_constraint_ids)
    evidence = structural_bottleneck_evidence(geometry, relaxed)
    assert evidence.conditional_colocation_relation_count == 0


def test_capacity_binding_spells_out_retained_constraints_final_n_and_objective() -> None:
    geometry = _geometry()
    (certificate,) = compute_split_capacity_envelope(geometry, splits=(PUBLIC,))
    binding = bind_split_capacity_certificate(geometry, certificate)
    active_ids = tuple(
        sorted(
            c.constraint_id
            for c in geometry.problem.constraint_set.constraints
            if c.kind is not ConstraintKind.SPLIT_COUNT
        )
    )
    assert binding.relaxed_constraint_ids == tuple(
        sorted(
            c.constraint_id
            for c in geometry.problem.constraint_set.constraints
            if c.kind is ConstraintKind.SPLIT_COUNT
        )
    )
    assert binding.retained_constraint_ids == active_ids
    assert binding.final_count == 2
    assert binding.objective == "MAXIMIZE_TARGET_SPLIT_COUNT:PUBLIC_DEVELOPMENT"
    assert binding.objective_value == binding.objective_bound == certificate.maximum
    assert binding.optimality_status == "OPTIMAL"
    assert binding.solver_config == certificate.solver_config
    assert binding.result_digest == certificate.result_digest


def _lane() -> ReserveCandidateLaneV1:
    return ReserveCandidateLaneV1(
        "synthetic:test",
        CaseOrigin.DETERMINISTIC_SYNTHETIC,
        "synthetic test authority",
        canonical_hash("synthetic test"),
        "candidate",
        0,
        1,
        LaneCapacityStatus.AVAILABLE,
        supported_cells=(("C08", "F05"),),
    )


def _inventory(lanes: tuple[ReserveCandidateLaneV1, ...]) -> AuthoritySupplyInventoryV1:
    return AuthoritySupplyInventoryV1(
        AUTHORITY_SUPPLY_SCHEMA,
        (),
        lanes,
        (),
        0,
        0,
        (),
        True,
        False,
    )


def test_consumed_finite_capacity_cannot_reappear() -> None:
    lane = _lane()
    assert remaining_lane_capacity(lane, 1) == 0
    assert derive_governed_archetypes(_inventory((lane,)), ((lane.lane_id, 1),)) == ()
    with pytest.raises(ValueError):
        remaining_lane_capacity(lane, -1)


def test_unknown_identity_stays_unknown_and_derivation_is_deterministic() -> None:
    inventory = _inventory((_lane(),))
    consumption = ((_lane().lane_id, 0),)
    a = derive_governed_archetypes(inventory, consumption)
    assert a == derive_governed_archetypes(inventory, consumption)
    with pytest.raises(ValueError, match="consumption"):
        derive_governed_archetypes(inventory, ())
    assert a[0].fresh_independent_identity_guaranteed is None
    assert a[0].relation_behavior_guarantee is None
    assert a[0].currently_materializable is None
    assert a[0].guaranteed_features == ()


def test_rule_governed_capacity_is_not_infinite_concrete_supply() -> None:
    generator = PRODUCTION_SYNTHETIC_GENERATORS[0]
    lane = replace(
        _lane(),
        lane_id=f"synthetic:{generator.generator_family}",
        authority_digest=canonical_hash(generator),
        lane_digest="",
        available_capacity=None,
        capacity_status=LaneCapacityStatus.RULE_GOVERNED,
        capacity_rule="registered seed namespace",
    )
    (a,) = derive_governed_archetypes(_inventory((lane,)), ((lane.lane_id, 1000),))
    assert a.remaining_finite_capacity is None
    assert a.capacity_rule == lane.capacity_rule
    assert a.fresh_independent_identity_guaranteed is False
    evidence = classify_archetype_repair(_geometry(), (a,))
    assert any("C08 refusal" in reason for reason in evidence.evidence)
    with pytest.raises(ValueError, match="concrete"):
        replace(a, remaining_finite_capacity=1000000)


def test_unknown_behavior_cannot_establish_repair_or_impossibility() -> None:
    lane = _lane()
    archetypes = derive_governed_archetypes(_inventory((lane,)), ((lane.lane_id, 0),))
    evidence = classify_archetype_repair(_geometry(), archetypes)
    assert evidence.classification is RepairClassification.UNRESOLVED
    assert evidence.archetype_inventory_digest == canonical_hash(archetypes)
    assert evidence.potentially_supported_coverage_ids == ()
    assert evidence.unsupported_row_coverage_ids == ()
    assert "unknown" in evidence.evidence[0]


def test_unknown_archetype_contract_fields_remain_unknown() -> None:
    lane = _lane()
    archetypes = derive_governed_archetypes(_inventory((lane,)), ((lane.lane_id, 0),))
    contracts = archetype_structural_contracts(_geometry(), archetypes)
    claims = {claim.field: claim for claim in contracts[0].claims}
    assert claims["exact_feature_vector"].certainty is ContractCertainty.UNKNOWN
    assert claims["contamination_and_shingles"].certainty is ContractCertainty.UNKNOWN
    assert claims["unique_seed_block_identity"].certainty is ContractCertainty.UNKNOWN
    assert archetypes[0].guaranteed_features == ()


def _repair_signature(
    origin: CaseOrigin,
    *,
    cell: tuple[str, str] = ("C01", "F01"),
    features: tuple[SelectionFeature, ...] = (),
    splits: tuple[SplitName, ...] = (PUBLIC,),
    lane_id: str | None = None,
    lane_capacity: int | None = None,
    capacity_status: AdditionalCapacityStatus | None = None,
) -> RepairSignature:
    return RepairSignature(
        origin=origin,
        cell=cell,
        guaranteed_features=features,
        split_compatibility=splits,
        relation_behavior="INDEPENDENT_FROM_BASE_AND_OTHER_ADDITIONS",
        isolation_identity_behavior="FRESH_UNIQUE",
        lineage_behavior="NOT_MUTATION",
        lane_id=lane_id,
        lane_capacity=lane_capacity,
        capacity_status=capacity_status,
    )


def _c08_geometry(
    *,
    final_n: int = 2,
    feature_minimum: int = 1,
    origin_maximum: int | None = None,
    prior_cluster_member: bool = False,
    family: str = "F05",
) -> RepairGeometry:
    feature = SelectionFeature(FeatureKind.CELL, ("C08", family))
    constraints = [
        SelectionConstraint(
            "TEST:C08:FEATURE",
            "synthetic C08 structural fixture",
            ConstraintKind.FEATURE_MINIMUM,
            split=PUBLIC,
            feature=feature,
            minimum=feature_minimum,
        )
    ]
    if origin_maximum is not None:
        constraints.append(
            SelectionConstraint(
                "TEST:C08:ORIGIN_MAXIMUM",
                "synthetic C08 structural fixture",
                ConstraintKind.ORIGIN_BOUNDS,
                origin_class=CaseOrigin.DETERMINISTIC_SYNTHETIC,
                minimum=0,
                maximum=origin_maximum,
            )
        )
    base = _candidate(
        "base",
        origin=(
            CaseOrigin.DETERMINISTIC_SYNTHETIC
            if prior_cluster_member
            else CaseOrigin.EXPERT_AUTHORED_SEMANTIC
        ),
        locked_split=(PUBLIC if prior_cluster_member else None),
        cluster=(f"PSE-V1-SYNTHETIC-CLUSTER:{PUBLIC.value}" if prior_cluster_member else None),
    )
    return RepairGeometry(_toy_problem((base,), ((PUBLIC, final_n),), extra=tuple(constraints)))


def _rule_governed_c08_archetype(
    family: str = "F05",
) -> tuple[ReserveCandidateLaneV1, tuple[RepairArchetype, ...]]:
    generator = next(
        item
        for item in PRODUCTION_SYNTHETIC_GENERATORS
        if item.generator_family.endswith("public_development")
    )
    lane = replace(
        _lane(),
        lane_id=f"synthetic:{generator.generator_family}",
        authority_digest=canonical_hash(generator),
        lane_digest="",
        available_capacity=None,
        capacity_status=LaneCapacityStatus.RULE_GOVERNED,
        capacity_rule="registered generator and split-family seed-block namespace",
        supported_cells=(("C08", family),),
    )
    archetypes = derive_governed_archetypes(_inventory((lane,)), ((lane.lane_id, 0),))
    return lane, archetypes


def test_ideal_master_proves_minimum_structural_cardinality() -> None:
    problem = _toy_problem((_candidate("a"),), ((PUBLIC, 2),))
    result = solve_ideal_repair_minimum(
        RepairGeometry(problem),
        signatures=(_repair_signature(CaseOrigin.EXPERT_AUTHORED_SEMANTIC),),
    )
    assert result.status == "OPTIMAL"
    assert result.minimum_additions == 1
    assert result.repair_vector[0].total_count == 1
    assert result.lower_proof is not None
    assert result.lower_proof.maximum_additions == 0
    assert result.lower_proof.status == "INFEASIBLE"
    assert result.upper_proof is not None
    assert result.upper_proof.maximum_additions == 1
    assert result.upper_proof.status == "FEASIBLE"
    assert result.cardinality_optimality == "PROVEN"
    first_diagnostics = result.trials[0].diagnostics
    final_diagnostics = result.trials[-1].diagnostics
    assert first_diagnostics is not None and final_diagnostics is not None
    assert result.model_variable_count == first_diagnostics.model_variable_count
    assert final_diagnostics.objective_term_count == 0
    assert result.ideal_repair_digest


def test_unknown_master_diagnostics_do_not_promote_incumbents_or_bounds() -> None:
    assert classify_repair_master_unknown("UNKNOWN", False, 0.0) == ("NO_USEFUL_BOUND_OR_INCUMBENT")
    assert classify_repair_master_unknown("UNKNOWN", False, 2.0) == "BOUND_ONLY_NO_INCUMBENT"
    assert classify_repair_master_unknown("UNKNOWN", True, 2.0) == (
        "FEASIBLE_INCUMBENT_NOT_PROVEN_OPTIMAL"
    )
    assert classify_repair_master_unknown("OPTIMAL", True, 1.0) is None


def test_unknown_cardinality_decision_never_claims_a_minimum(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = SimpleNamespace(
        solution=(),
        num_conflicts=0,
        num_branches=0,
        num_restarts=0,
        wall_time=0.1,
        deterministic_time=0.0,
        objective_value=0.0,
        best_objective_bound=0.0,
    )
    solver = SimpleNamespace(response_proto=response)
    monkeypatch.setattr(
        "dynamislm.benchmark.repair_geometry._solve_once",
        lambda *_args, **_kwargs: (solver, "UNKNOWN", 0.0),
    )
    problem = _toy_problem((_candidate("a"),), ((PUBLIC, 2),))
    result = solve_ideal_repair_minimum(
        RepairGeometry(problem),
        signatures=(_repair_signature(CaseOrigin.EXPERT_AUTHORED_SEMANTIC),),
    )
    assert result.status == "UNKNOWN"
    assert result.minimum_additions is None
    assert result.repair_vector == ()
    diagnostics = result.trials[0].diagnostics
    assert diagnostics is not None
    assert diagnostics.unknown_classification == "NO_USEFUL_BOUND_OR_INCUMBENT"
    structural = _structural_repair_model(
        RepairGeometry(problem),
        (_repair_signature(CaseOrigin.EXPERT_AUTHORED_SEMANTIC),),
    )
    unknown_trial = solve_repair_cardinality_decision(structural, 0)
    with pytest.raises(ValueError, match="preceding infeasibility proof"):
        solve_repair_cardinality_decision(
            structural,
            1,
            minimum_additions=1,
            lower_bound_proof=unknown_trial,
        )


def test_compact_ideal_signature_inventory_is_canonical_and_a_relaxation() -> None:
    row = next(item for item in COVERAGE_MATRIX if item.capability_id == "C01")
    cell = (row.capability_id, row.benchmark_families[0])
    cell_feature = SelectionFeature(FeatureKind.CELL, cell)
    answerable = SelectionFeature(FeatureKind.ANSWERABLE)
    obligations = tuple(
        SelectionConstraint(
            f"TEST:FEATURE:{index}",
            "RES-407 synthetic signature fixture",
            ConstraintKind.FEATURE_MINIMUM,
            split=PUBLIC,
            feature=feature,
            minimum=1,
        )
        for index, feature in enumerate((cell_feature, answerable))
    )
    geometry = RepairGeometry(
        _toy_problem(
            (_candidate("a", features=(cell_feature, answerable)),),
            ((PUBLIC, 1),),
            extra=obligations,
        )
    )
    compact = build_compact_ideal_repair_signatures(geometry)
    legacy_domain = build_ideal_repair_signatures(geometry)
    assert compact
    assert compact == tuple(sorted(set(compact), key=lambda item: item.signature_id))
    assert len(compact) < len(legacy_domain)
    assert all(answerable in signature.guaranteed_features for signature in compact)
    assert all(
        signature.relation_behavior == "INDEPENDENT_FROM_BASE_AND_OTHER_ADDITIONS"
        for signature in compact
    )
    assert all(signature.isolation_identity_behavior == "FRESH_UNIQUE" for signature in compact)
    assert IDEAL_REPAIR_IS_RELAXATION is True
    assert "no new colocation" in IDEAL_REPAIR_RELAXATION_DEFINITION


def test_structural_profile_is_separate_from_production_feasibility_profile() -> None:
    assert RES407_STRUCTURAL_REPAIR_MASTER_PROFILE_VERSION == (
        "RES407-STRUCTURAL-REPAIR-MASTER@1.0.0"
    )
    assert RES407_STRUCTURAL_REPAIR_MASTER_PROFILE_V1 != (PSE_V1_POOL_FEASIBILITY_SOLVER_PROFILE_V1)
    assert RES407_STRUCTURAL_REPAIR_MASTER_PROFILE_V1.cp_model_presolve is True
    assert RES407_STRUCTURAL_REPAIR_MASTER_PROFILE_V1.random_seed == 369
    assert RES407_STRUCTURAL_REPAIR_MASTER_PROFILE_V1.workers == 8
    assert PSE_V1_POOL_FEASIBILITY_SOLVER_PROFILE_V1.timeout_s == 120.0


def test_aggregate_model_has_y_and_z_counts_without_repair_candidate_replicas() -> None:
    problem = _toy_problem((_candidate("a"),), ((PUBLIC, 2),))
    signature = _repair_signature(CaseOrigin.EXPERT_AUTHORED_SEMANTIC)
    structural = _structural_repair_model(RepairGeometry(problem), (signature,))
    names = tuple(variable.name for variable in structural.model.proto.variables)
    assert len(structural.additions) == 1
    assert len(structural.recourse) == 3
    assert sum(name.startswith("y[") for name in names) == 1
    assert sum(name.startswith("z[") for name in names) == 3
    assert tuple(name for name in names if name.startswith("a[")) == (
        "a[0,1]",
        "a[0,2]",
        "a[0,3]",
    )
    assert not any("repair_candidate" in name for name in names)

    locked = RepairSignature(
        origin=CaseOrigin.DETERMINISTIC_SYNTHETIC,
        cell=("C08", "F05"),
        guaranteed_features=(),
        split_compatibility=(PUBLIC,),
        relation_behavior="INDEPENDENT_FROM_BASE_AND_OTHER_ADDITIONS",
        isolation_identity_behavior="FRESH_UNIQUE",
        lineage_behavior="NOT_MUTATION",
    )
    locked_model = _structural_repair_model(RepairGeometry(problem), (locked,))
    domains = {var.name: tuple(var.domain) for var in locked_model.model.proto.variables}
    for split in (SplitName.FROZEN_VALIDATION, SplitName.HIDDEN_FINAL):
        name = f"z[{locked.signature_id[:12]},{split.value}]"
        assert domains[name] == (0, 0)


def test_duplicate_relation_compaction_preserves_assignment_feasibility() -> None:
    candidates = (_candidate("a"), _candidate("b"))
    edges = tuple(
        SelectionConstraint(
            constraint_id=f"TEST:COLOCATION:{index}",
            authority_ref="RES-407 synthetic relation fixture",
            kind=ConstraintKind.CONDITIONAL_COLOCATION,
            candidate_ids=("a", "b"),
            relation_kind=kind,
        )
        for index, kind in enumerate((RelationKind.ISOLATION_CLUSTER, RelationKind.EXACT_SHINGLE))
    )
    problem = _toy_problem(candidates, ((PUBLIC, 1), (VALIDATION, 1)), extra=edges)
    full_model, _assignments, _balance, _hash = _model_for(problem, include_objectives=False)
    compact_model, _assignments, _balance, _hash = _model_for(
        problem, include_objectives=False, compact_colocation_indicators=True
    )
    config = SelectionSolverConfig(workers=1, timeout_s=5.0)
    assert _solve_once(full_model, config)[1] == "INFEASIBLE"
    assert _solve_once(compact_model, config)[1] == "INFEASIBLE"
    structural = _structural_repair_model(RepairGeometry(problem), ())
    assert structural.source_relation_constraint_count == 2
    assert structural.unique_relation_member_set_count == 1
    assert (
        structural.source_relation_constraint_count - structural.unique_relation_member_set_count
        == 1
    )


def test_cardinality_decision_is_monotone_and_proves_k_minus_1_then_k() -> None:
    geometry = RepairGeometry(_toy_problem((_candidate("a"),), ((PUBLIC, 2),)))
    signature = _repair_signature(CaseOrigin.EXPERT_AUTHORED_SEMANTIC)
    structural = _structural_repair_model(geometry, (signature,))
    deterministic_config = replace(RES407_STRUCTURAL_REPAIR_MASTER_PROFILE_V1, workers=1)
    zero = solve_repair_cardinality_decision(structural, 0, solver_config=deterministic_config)
    one = solve_repair_cardinality_decision(structural, 1, solver_config=deterministic_config)
    two = solve_repair_cardinality_decision(structural, 2, solver_config=deterministic_config)
    assert zero.status == "INFEASIBLE"
    assert one.status == "FEASIBLE"
    assert two.status == "FEASIBLE"

    result = solve_ideal_repair_minimum(
        geometry, signatures=(signature,), solver_config=deterministic_config
    )
    assert result.status == "OPTIMAL"
    assert result.minimum_additions == 1
    assert result.lower_proof is not None and result.lower_proof.maximum_additions == 0
    assert result.lower_proof.status == "INFEASIBLE"
    assert result.upper_proof is not None and result.upper_proof.maximum_additions == 1
    assert result.upper_proof.status == "FEASIBLE"
    assert result.upper_proof.minimum_additions == 1
    assert result.upper_proof.lower_bound_source_trial_digest == result.lower_proof.trial_digest
    replay = solve_ideal_repair_minimum(
        geometry, signatures=(signature,), solver_config=deterministic_config
    )
    assert replay.repair_vector == result.repair_vector
    assert replay.ideal_repair_digest == result.ideal_repair_digest


def test_feasible_trial_hints_a_smaller_cardinality_decision() -> None:
    geometry = RepairGeometry(_toy_problem((_candidate("a"),), ((PUBLIC, 2),)))
    structural = _structural_repair_model(
        geometry, (_repair_signature(CaseOrigin.EXPERT_AUTHORED_SEMANTIC),)
    )
    assert not hasattr(structural.assignments["a", AssignmentState.OUT], "index")
    assert all(
        hasattr(structural.assignments["a", AssignmentState(split.value)], "index")
        for split in SPLIT_ORDER
    )
    config = replace(RES407_STRUCTURAL_REPAIR_MASTER_PROFILE_V1, workers=1)
    high = solve_repair_cardinality_decision(structural, 2, solver_config=config)
    lower = solve_repair_cardinality_decision(structural, 1, solver_config=config)
    assert high.status == "FEASIBLE"
    assert lower.status == "FEASIBLE"
    assert lower.hint_source_trial_digest == high.trial_digest


def test_structural_master_compaction_reduces_model_and_preserves_decisions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidates = (_candidate("a"), _candidate("b"))
    relation = SelectionConstraint(
        "TEST:STRUCTURAL:COLOCATION",
        "synthetic bounded structural master",
        ConstraintKind.CONDITIONAL_COLOCATION,
        candidate_ids=("a", "b"),
        relation_kind=RelationKind.ISOLATION_CLUSTER,
    )
    geometry = RepairGeometry(
        _toy_problem(
            candidates,
            ((PUBLIC, 1), (VALIDATION, 1)),
            extra=(relation,),
        )
    )
    signature = _repair_signature(
        CaseOrigin.EXPERT_AUTHORED_SEMANTIC,
        splits=(PUBLIC, VALIDATION),
    )
    compact = _structural_repair_model(geometry, (signature,))

    with monkeypatch.context() as patch:
        patch.setattr(
            repair_geometry_module,
            "_model_for",
            lambda problem, **kwargs: _model_for(
                problem, include_objectives=kwargs.get("include_objectives", True)
            ),
        )
        original = _structural_repair_model(geometry, (signature,))

    original_counts = (
        len(original.model.proto.variables),
        len(original.model.proto.constraints),
    )
    compact_counts = (
        len(compact.model.proto.variables),
        len(compact.model.proto.constraints),
    )
    assert original_counts == (15, 19)
    assert compact_counts == (13, 16)

    config = replace(RES407_STRUCTURAL_REPAIR_MASTER_PROFILE_V1, workers=1)
    original_zero = solve_repair_cardinality_decision(original, 0, solver_config=config)
    compact_zero = solve_repair_cardinality_decision(compact, 0, solver_config=config)
    original_one = solve_repair_cardinality_decision(original, 1, solver_config=config)
    compact_one = solve_repair_cardinality_decision(compact, 1, solver_config=config)
    assert (original_zero.status, compact_zero.status) == ("INFEASIBLE", "INFEASIBLE")
    assert (original_one.status, compact_one.status) == ("FEASIBLE", "FEASIBLE")
    assert original_one.diagnostics is not None
    assert compact_one.diagnostics is not None
    assert original_one.diagnostics.incumbent_addition_count == 1
    assert compact_one.diagnostics.incumbent_addition_count == 1


def test_duplicate_colocation_hyperedges_and_reverse_indicators_are_redundant() -> None:
    candidates = (_candidate("a"), _candidate("b"))
    edges = tuple(
        SelectionConstraint(
            constraint_id=f"TEST:RELATION:{index}",
            authority_ref="RES-407 synthetic relation fixture",
            kind=ConstraintKind.CONDITIONAL_COLOCATION,
            candidate_ids=("a", "b"),
            relation_kind=kind,
        )
        for index, kind in enumerate((RelationKind.ISOLATION_CLUSTER, RelationKind.EXACT_SHINGLE))
    )
    problem = _toy_problem(candidates, ((PUBLIC, 1), (VALIDATION, 1)), extra=edges)
    full, _vars, _balance, _hash = _model_for(problem, include_objectives=False)
    compact, _vars, _balance, _hash = _model_for(
        problem, include_objectives=False, compact_colocation_indicators=True
    )
    config = SelectionSolverConfig(workers=1, timeout_s=5.0)
    assert _solve_once(full, config)[1] == "INFEASIBLE"
    assert _solve_once(compact, config)[1] == "INFEASIBLE"
    structural = _structural_repair_model(RepairGeometry(problem), ())
    assert structural.source_relation_constraint_count == 2
    assert structural.unique_relation_member_set_count == 1


def test_relation_superset_subsumes_member_subset_without_changing_feasibility() -> None:
    candidates = (
        _candidate("a"),
        _candidate("b", review=ReviewEligibility.REJECTED),
        _candidate("c"),
    )
    edges = (
        SelectionConstraint(
            constraint_id="TEST:RELATION:SUBSET",
            authority_ref="RES-407 synthetic relation fixture",
            kind=ConstraintKind.CONDITIONAL_COLOCATION,
            candidate_ids=("a", "b"),
            relation_kind=RelationKind.ISOLATION_CLUSTER,
        ),
        SelectionConstraint(
            constraint_id="TEST:RELATION:SUPERSET",
            authority_ref="RES-407 synthetic relation fixture",
            kind=ConstraintKind.CONDITIONAL_COLOCATION,
            candidate_ids=("a", "b", "c"),
            relation_kind=RelationKind.EXACT_SHINGLE,
        ),
    )
    config = SelectionSolverConfig(workers=1, timeout_s=5.0)
    for split_counts, expected in (
        (((PUBLIC, 2),), "FEASIBLE"),
        (((PUBLIC, 1), (VALIDATION, 1)), "INFEASIBLE"),
    ):
        problem = _toy_problem(candidates, split_counts, extra=edges)
        full, _assignments, _balance, _hash = _model_for(problem, include_objectives=False)
        compact = _structural_repair_model(RepairGeometry(problem), ()).model
        assert (
            "FEASIBLE" if _solve_once(full, config)[1] != "INFEASIBLE" else "INFEASIBLE"
        ) == expected
        assert (
            "FEASIBLE" if _solve_once(compact, config)[1] != "INFEASIBLE" else "INFEASIBLE"
        ) == expected
    structural = _structural_repair_model(
        RepairGeometry(_toy_problem(candidates, ((PUBLIC, 2),), extra=edges)), ()
    )
    assert structural.source_relation_constraint_count == 2
    assert structural.unique_relation_member_set_count == 1


def test_inherited_k_zero_proof_is_bound_to_exact_base_receipt() -> None:
    geometry = RepairGeometry(_toy_problem((_candidate("a"),), ((PUBLIC, 2),)))
    signature = _repair_signature(CaseOrigin.EXPERT_AUTHORED_SEMANTIC)
    proof = RepairCardinalityTrial(
        maximum_additions=0,
        status="INFEASIBLE",
        solver_profile_version=POOL_FEASIBILITY_SOLVER_PROFILE_VERSION,
        solver_config=PSE_V1_POOL_FEASIBILITY_SOLVER_PROFILE_V1,
        solver_version=version("ortools"),
        geometry_digest=geometry.geometry_digest,
        signature_inventory_digest=canonical_hash((signature,)),
        diagnostics=None,
        proof_source_schema="RES406-BASE-FEASIBILITY-RECEIPT@1.0.0",
        proof_source_digest=canonical_hash("exact source receipt"),
        proof_source_problem_digest=geometry.problem.problem_digest,
        proof_source_constraint_inventory_digest=geometry.problem.constraint_inventory_digest,
        proof_source_status="INFEASIBLE",
        proof_source_method="EXACT_FEASIBILITY_ORACLE",
    )
    result = solve_ideal_repair_minimum(
        geometry,
        signatures=(signature,),
        zero_addition_infeasibility_proof=proof,
    )
    assert result.status == "OPTIMAL"
    assert result.lower_proof == proof
    assert result.upper_proof is not None and result.upper_proof.maximum_additions == 1


def test_exhausted_finite_lane_has_zero_addition_capacity() -> None:
    problem = _toy_problem((_candidate("a"),), ((PUBLIC, 2),))
    signature = _repair_signature(
        CaseOrigin.EXPERT_AUTHORED_SEMANTIC,
        lane_id="source:exhausted",
        lane_capacity=0,
        capacity_status=AdditionalCapacityStatus.EXHAUSTED,
    )
    structural_model = _structural_repair_model(RepairGeometry(problem), (signature,))
    trial = solve_repair_cardinality_decision(structural_model, 2)
    assert trial.status == "INFEASIBLE"
    assert trial.diagnostics is not None
    assert trial.diagnostics.incumbent_addition_count is None


def test_ideal_witness_order_and_digest_do_not_depend_on_input_order() -> None:
    geometry = RepairGeometry(_toy_problem((_candidate("a"),), ((PUBLIC, 2),)))
    signatures = (
        _repair_signature(CaseOrigin.EXPERT_AUTHORED_SEMANTIC),
        _repair_signature(CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION),
    )
    deterministic_config = replace(RES407_STRUCTURAL_REPAIR_MASTER_PROFILE_V1, workers=1)
    first = solve_ideal_repair_minimum(
        geometry, signatures=signatures, solver_config=deterministic_config
    )
    second = solve_ideal_repair_minimum(
        geometry, signatures=tuple(reversed(signatures)), solver_config=deterministic_config
    )
    assert first.repair_vector == second.repair_vector
    assert first.ideal_repair_digest == second.ideal_repair_digest
    assert tuple(item.signature.signature_id for item in first.repair_vector) == tuple(
        sorted(item.signature.signature_id for item in first.repair_vector)
    )


def test_optimistic_c08_model_only_relaxes_guaranteed_behavior() -> None:
    generator = next(
        item
        for item in PRODUCTION_SYNTHETIC_GENERATORS
        if item.generator_family.endswith("public_development")
    )
    lane = replace(
        _lane(),
        lane_id=f"synthetic:{generator.generator_family}",
        authority_digest=canonical_hash(generator),
        available_capacity=None,
        capacity_status=LaneCapacityStatus.RULE_GOVERNED,
        capacity_rule="registered split-family seed namespace",
        lane_digest="",
    )
    archetypes = derive_governed_archetypes(_inventory((lane,)), ((lane.lane_id, 0),))
    optimistic = build_optimistic_c08_signatures(_geometry(), archetypes)
    assert len(optimistic) == 1
    signature = optimistic[0]
    assert signature.cell == archetypes[0].cell
    assert signature.origin is archetypes[0].origin
    assert signature.split_compatibility == (PUBLIC,)
    assert signature.lane_id == lane.lane_id
    assert signature.capacity_status is AdditionalCapacityStatus.RULE_GOVERNED
    assert signature.relation_behavior == (
        "SHARED_SPLIT_LOCKED_CLUSTER; UNKNOWN_SHINGLE_RELATIONS_RELAXED"
    )
    assert signature.isolation_identity_behavior == "SHARED_SPLIT_AND_GENERATOR_FAMILY"
    assert set(archetypes[0].guaranteed_features).issubset(signature.guaranteed_features)


def test_ideal_vector_decoding_binds_signature_split_counts_and_minimum() -> None:
    from scripts.res407_repair_geometry import _decode_ideal_vector

    geometry = _c08_geometry()
    signatures = build_compact_ideal_repair_signatures(geometry)
    signature = next(
        item
        for item in signatures
        if item.cell == ("C08", "F05")
        and item.origin is CaseOrigin.DETERMINISTIC_SYNTHETIC
        and PUBLIC in item.split_compatibility
    )
    raw = (
        {
            "signature_digest": signature.signature_id,
            "count": 1,
            "split_counts": {PUBLIC.value: 1},
        },
    )
    (decoded,) = _decode_ideal_vector(signatures, raw, 1)
    assert decoded.signature == signature
    assert decoded.split_counts == ((PUBLIC, 1),)
    with pytest.raises(ValueError, match="unknown or duplicate"):
        _decode_ideal_vector(signatures, (*raw, *raw), 2)


def test_ideal_relaxation_dominates_current_governed_behavior_classes() -> None:
    from scripts.res407_repair_geometry import _ideal_relaxation_proof

    geometry = _c08_geometry(prior_cluster_member=True)
    _lane, archetypes = _rule_governed_c08_archetype()
    proof = _ideal_relaxation_proof(
        geometry,
        build_compact_ideal_repair_signatures(geometry),
        archetypes,
    )
    assert proof["status"] == "PASS"
    assert len(proof["mappings"]) == 1
    assert proof["mappings"][0]["locked_split"] == PUBLIC.value
    assert proof["mappings"][0]["ideal_answerable_feature"] is True
    assert "Future authorities are outside this proof scope." in proof["hard_constraint_dominance"]


def test_governed_contract_inventory_keeps_unknowns_unknown() -> None:
    from scripts.res407_repair_geometry import _governed_archetype_contract_inventory

    geometry = _c08_geometry(prior_cluster_member=True)
    _lane, archetypes = _rule_governed_c08_archetype()
    (contract,) = _governed_archetype_contract_inventory(geometry, archetypes)
    properties = {
        item["property"]: item["classification"] for item in contract["structural_property_claims"]
    }
    assert contract["answerability_refusal_semantics"]["certainty"] == "GUARANTEED"
    assert contract["answerability_refusal_semantics"]["value"].startswith(
        "NON_NUMERIC_REFUSAL_CONTEXT"
    )
    assert properties["exact_feature_vector"] == "UNKNOWN"
    assert properties["contamination_and_shingles"] == "UNKNOWN"
    assert properties["interchangeability"] == "UNKNOWN"
    assert contract["repeated_instance_independence_interchangeability"]["certainty"] == ("UNKNOWN")
    assert contract["implemented_recipe_path_multiplicity"]["options_per_lane_cell"] == 1
    assert (
        contract["implemented_recipe_path_multiplicity"]["repeat_ordinal_in_candidate_id"] is False
    )


def test_optimistic_c08_relaxation_preserves_forbidden_behavior_boundaries() -> None:
    from scripts.res407_repair_geometry import _optimistic_c08_relaxation_proof

    geometry = _c08_geometry(prior_cluster_member=True)
    _lane, archetypes = _rule_governed_c08_archetype()
    signatures = build_optimistic_c08_signatures(geometry, archetypes)
    proof = _optimistic_c08_relaxation_proof(geometry, archetypes, signatures)
    assert proof["status"] == "PASS"
    assert proof["claim"] == ("REAL_C08_FEASIBLE_SET_SUBSET_OPTIMISTIC_C08_FEASIBLE_SET")
    assert proof["rows"][0]["numeric_answerability_not_granted"] is True
    assert proof["rows"][0]["prior_matching_cluster_locks_match"] is True

    widened = replace(
        signatures[0],
        isolation_identity_behavior="FRESH_UNIQUE",
        signature_id="",
    )
    invalid = _optimistic_c08_relaxation_proof(geometry, archetypes, (widened,))
    assert invalid["status"] == "PARTIAL"


def test_saturation_bound_comes_from_selection_limits() -> None:
    geometry = _c08_geometry(origin_maximum=1)
    _lane, archetypes = _rule_governed_c08_archetype()
    signatures = build_optimistic_c08_signatures(geometry, archetypes)
    (bound,) = derive_archetype_saturation_bounds(geometry, signatures)
    assert bound.upper_bound == 1
    assert dict(bound.limits)["FINAL_COUNT"] == 2
    assert dict(bound.limits)[f"SPLIT_COUNT:{PUBLIC.value}"] == 2
    assert dict(bound.limits)["ORIGIN_MAXIMUM:DETERMINISTIC_SYNTHETIC"] == 1


def test_governed_cardinality_search_starts_at_ideal_lower_bound_and_is_deterministic() -> None:
    from scripts.res407_repair_geometry import (
        _canonicalize_governed_vector,
        _current_c08_capability,
        _search_optimistic_cardinality,
    )

    geometry = _c08_geometry(final_n=13, feature_minimum=13)
    _lane, archetypes = _rule_governed_c08_archetype()
    (signature,) = build_optimistic_c08_signatures(geometry, archetypes)
    alternate = replace(
        signature,
        lane_id=f"{signature.lane_id}:alternate",
        signature_id="",
    )
    signatures = tuple(sorted((signature, alternate), key=lambda item: item.signature_id))
    bounds = derive_archetype_saturation_bounds(geometry, signatures)
    structural = _structural_repair_model(
        geometry,
        signatures,
        signature_upper_bounds={item.signature_id: item.upper_bound for item in bounds},
    )
    names = tuple(variable.name for variable in structural.model.proto.variables)
    assert sum(name.startswith("y[") for name in names) == len(signatures)
    assert sum(name.startswith("z[") for name in names) == len(signatures) * 3
    assert not any("repair_candidate" in name for name in names)

    config = replace(RES407_STRUCTURAL_REPAIR_MASTER_PROFILE_V1, workers=1, timeout_s=5.0)
    first = _search_optimistic_cardinality(
        structural,
        lower_bound=12,
        saturation_bound=13,
        solver_config=config,
    )
    assert [trial.maximum_additions for trial in first["trials"]] == [12, 13]
    assert [trial.status for trial in first["trials"]] == ["INFEASIBLE", "FEASIBLE"]
    assert first["minimum_additions"] == 13
    assert _current_c08_capability(first) == "UNRESOLVED"
    vector = _canonicalize_governed_vector(
        structural,
        13,
        config,
        first["lower_bound_trial"],
    )
    replay = _canonicalize_governed_vector(
        structural,
        13,
        config,
        first["lower_bound_trial"],
    )
    assert vector == replay
    assert len(vector) == 1
    assert sum(item.total_count for item in vector) == 13
    assert (
        _current_c08_capability({"status": "UNKNOWN", "infeasible_at_saturation": True})
        == "UNRESOLVED"
    )


def test_legacy_qualification_cli_is_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts import res407_governed_backfill

    monkeypatch.setattr("sys.argv", ["res407_governed_backfill.py", "qualify"])
    with pytest.raises(ValueError, match="disabled"):
        res407_governed_backfill.main()


def test_exact_external_res407_regression(monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts.res407_repair_geometry import _run_geometry

    from dynamislm.benchmark.production_store import DEFAULT_PRODUCTION_ROOT

    if not DEFAULT_PRODUCTION_ROOT.exists():
        pytest.skip("exact empirical pool is external and unavailable")
    from scripts import res407_governed_backfill

    def forbidden(*_: object, **__: object) -> None:
        pytest.fail("structural geometry reached concrete authoring or subset search")

    for name in (
        "_addition_sets",
        "_search_repair_sets",
        "_minimize_repair_set",
        "_run_qualification",
        "_repair_option_inventory",
        "_synthetic_option_recipes",
        "materialize_variable_pool",
    ):
        monkeypatch.setattr(res407_governed_backfill, name, forbidden)
    result = _run_geometry(DEFAULT_PRODUCTION_ROOT, replay=False)
    capacities = result["split_capacities"]
    assert capacities[PUBLIC.value]["required"] == 260
    assert capacities[PUBLIC.value]["maximum"] == 212
    assert capacities[PUBLIC.value]["capacity_deficit"] == 48
    assert result["public_max_without_colocation"] == 260
    assert result["public_max_without_feature_minima"] == 426
    assert result["authorable_lane_count"] == 3
    assert result["repair_archetype_count"] == 12
    assert result["old_brute_force_path_reachable"] is False
    assert result["CAPACITY_CERTIFICATE_SEMANTICS"] == "PASS"
    assert result["IDEAL_REPAIR_STATUS"] == "OPTIMAL"
    assert result["IDEAL_MIN_ADDITIONS"] == 12
    assert result["IDEAL_SIGNATURE_COUNT"] == 369
    assert result["IDEAL_CARDINALITY_OPTIMALITY"] == "PROVEN"
    assert result["IDEAL_RELAXATION_PROOF_STATUS"] == "PASS"
    assert result["GOVERNED_ARCHETYPE_COUNT"] == result["repair_archetype_count"]
    assert result["OPTIMISTIC_C08_RELAXATION_PROOF_STATUS"] == "PASS"
    assert result["OPTIMISTIC_C08_STATUS"] == "FEASIBLE"
    assert result["OPTIMISTIC_C08_MIN_ADDITIONS"] == 48
    assert sum(item["count"] for item in result["OPTIMISTIC_C08_VECTOR"]) == 48
    assert all(trial["maximum_additions"] >= 12 for trial in result["CARDINALITY_TRIALS"])
    assert any(
        trial["maximum_additions"] == 47 and trial["status"] == "INFEASIBLE"
        for trial in result["CARDINALITY_TRIALS"]
    )
    assert any(
        trial["maximum_additions"] == 48 and trial["status"] == "FEASIBLE"
        for trial in result["CARDINALITY_TRIALS"]
    )
    assert result["CONCRETE_CANDIDATES_GENERATED"] == 0
    assert result["SEEDS_GENERATED"] == 0
    assert result["concrete_candidates_materialized"] is False
    assert result["removal_sweep_run"] is False
    assert result["GOVERNED_MASTER_STATUS"] == "UNRESOLVED"
    assert result["CURRENT_C08_REPAIR_CAPABILITY"] == "UNRESOLVED"
    assert result["CONCRETE_VECTOR_INSTANTIABILITY"]["status"] == "NOT_ESTABLISHED"
    assert (
        result["CONCRETE_VECTOR_INSTANTIABILITY"]["existing_option_builder_can_emit_vector"]
        is False
    )
    assert result["READY_FOR_MATERIALIZATION"] is False
    assert result["READY_FOR_AUTHORITY_EXPANSION"] is False
    master = res407_governed_backfill._read_record(
        f"{result['external_namespace']}/structural-augmentation-master.json",
        DEFAULT_PRODUCTION_ROOT,
    )
    assert master is not None
    for binding in master[0]["capacity_certificate_bindings"]:
        assert binding["final_count"] == 434
        assert binding["objective"].startswith("MAXIMIZE_TARGET_SPLIT_COUNT:")
        assert binding["optimality_status"] == "OPTIMAL"
        assert binding["objective_bound"] == binding["objective_value"]
        assert len(binding["result_digest"]) == len("sha256:") + 64
        assert (
            len(
                {
                    constraint_id
                    for constraint_id in binding["relaxed_constraint_ids"]
                    if constraint_id.startswith("RES258:SPLIT_COUNT:")
                }
            )
            == 3
        )
        assert not any(
            constraint_id.startswith("RES258:SPLIT_COUNT:")
            for constraint_id in binding["retained_constraint_ids"]
        )


def test_res407_production_runner_rejects_wrong_branch(monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts import res407_governed_backfill
    from scripts.res407_repair_geometry import run

    from dynamislm.benchmark.production_store import DEFAULT_PRODUCTION_ROOT

    def wrong_branch_git(*args: str) -> str:
        if args == ("rev-parse", "HEAD"):
            return "0" * 40
        if args == ("branch", "--show-current"):
            return "unauthorized-branch"
        pytest.fail(f"unexpected git query in branch guard: {args}")

    monkeypatch.setattr(res407_governed_backfill, "_git", wrong_branch_git)
    with pytest.raises(ValueError, match="RES-407 runner is on the wrong branch"):
        run(DEFAULT_PRODUCTION_ROOT)
