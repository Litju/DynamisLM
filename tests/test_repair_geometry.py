"""Synthetic falsification cases and the external, exact RES-407 regression."""

from dataclasses import replace
from types import SimpleNamespace

import pytest

from dynamislm.benchmark.authority_supply import (
    AUTHORITY_SUPPLY_SCHEMA,
    AdditionalCapacityStatus,
    AuthoritySupplyInventoryV1,
    LaneCapacityStatus,
    ReserveCandidateLaneV1,
)
from dynamislm.benchmark.constants import CaseOrigin, SplitName
from dynamislm.benchmark.production_authoring import PRODUCTION_SYNTHETIC_GENERATORS
from dynamislm.benchmark.repair_geometry import (
    ContractCertainty,
    RepairClassification,
    RepairGeometry,
    RepairSignature,
    SplitCapacityCertificate,
    archetype_structural_contracts,
    bind_split_capacity_certificate,
    build_optimistic_c08_signatures,
    classify_archetype_repair,
    compute_split_capacity_envelope,
    derive_governed_archetypes,
    remaining_lane_capacity,
    solve_structural_repair_master,
    structural_bottleneck_evidence,
)
from dynamislm.benchmark.selection_contracts import (
    AssignmentState,
    ConstraintKind,
    RelationKind,
    SelectionConstraint,
    SelectionSolverConfig,
)
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
    lane_id: str | None = None,
    lane_capacity: int | None = None,
    capacity_status: AdditionalCapacityStatus | None = None,
) -> RepairSignature:
    return RepairSignature(
        origin=origin,
        cell=("C01", "F01"),
        guaranteed_features=(),
        split_compatibility=(PUBLIC,),
        relation_behavior="INDEPENDENT_FROM_BASE_AND_OTHER_ADDITIONS",
        isolation_identity_behavior="FRESH_UNIQUE",
        lineage_behavior="NOT_MUTATION",
        lane_id=lane_id,
        lane_capacity=lane_capacity,
        capacity_status=capacity_status,
    )


def test_ideal_master_proves_minimum_structural_cardinality() -> None:
    problem = _toy_problem((_candidate("a"),), ((PUBLIC, 2),))
    result = solve_structural_repair_master(
        RepairGeometry(problem),
        (_repair_signature(CaseOrigin.EXPERT_AUTHORED_SEMANTIC),),
        optimality_scope="toy domain; additions <= FINAL_N",
    )
    assert result.status == "OPTIMAL"
    assert result.minimum_additions == 1
    assert result.objective == "MINIMIZE_TOTAL_ADDED_STRUCTURAL_UNITS"
    assert result.objective_bound == 1
    assert result.repair_vector[0].total_count == 1


def test_exhausted_finite_lane_has_zero_addition_capacity() -> None:
    problem = _toy_problem((_candidate("a"),), ((PUBLIC, 2),))
    signature = _repair_signature(
        CaseOrigin.EXPERT_AUTHORED_SEMANTIC,
        lane_id="source:exhausted",
        lane_capacity=0,
        capacity_status=AdditionalCapacityStatus.EXHAUSTED,
    )
    result = solve_structural_repair_master(
        RepairGeometry(problem),
        (signature,),
        optimality_scope="toy exhausted-lane domain",
    )
    assert result.status == "INFEASIBLE"
    assert result.minimum_additions is None
    assert result.repair_vector == ()


def test_repair_master_order_and_digest_do_not_depend_on_input_order() -> None:
    geometry = RepairGeometry(_toy_problem((_candidate("a"),), ((PUBLIC, 2),)))
    signatures = (
        _repair_signature(CaseOrigin.EXPERT_AUTHORED_SEMANTIC),
        _repair_signature(CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION),
    )
    first = solve_structural_repair_master(
        geometry, signatures, optimality_scope="toy deterministic ordering"
    )
    second = solve_structural_repair_master(
        geometry, tuple(reversed(signatures)), optimality_scope="toy deterministic ordering"
    )
    assert first.repair_vector == second.repair_vector
    assert first.result_digest == second.result_digest
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
    assert signature.relation_behavior == "OPTIMISTICALLY_INDEPENDENT_RELAXATION"
    assert set(archetypes[0].guaranteed_features).issubset(signature.guaranteed_features)


def test_legacy_qualification_cli_is_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts import res407_governed_backfill

    monkeypatch.setattr("sys.argv", ["res407_governed_backfill.py", "qualify"])
    with pytest.raises(ValueError, match="disabled"):
        res407_governed_backfill.main()


def test_exact_external_res407_regression(monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts.res407_repair_geometry import run

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
    result = run(DEFAULT_PRODUCTION_ROOT, replay=False)
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
    assert result["concrete_candidates_materialized"] is False
    assert result["removal_sweep_run"] is False
    assert result["GOVERNED_MASTER_STATUS"] == "UNRESOLVED"
    if result["IDEAL_REPAIR_STATUS"] != "OPTIMAL":
        assert result["IDEAL_MIN_ADDITIONS"] is None
        assert result["MISSING_GOVERNED_CAPABILITIES_STATUS"] == (
            "UNRESOLVED_NO_OPTIMAL_IDEAL_VECTOR"
        )
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
