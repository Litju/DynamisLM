"""Synthetic falsification cases and the external, exact RES-407 regression."""

from dataclasses import replace
from types import SimpleNamespace

import pytest

from dynamislm.benchmark.authority_supply import (
    AUTHORITY_SUPPLY_SCHEMA,
    AuthoritySupplyInventoryV1,
    LaneCapacityStatus,
    ReserveCandidateLaneV1,
)
from dynamislm.benchmark.constants import CaseOrigin, SplitName
from dynamislm.benchmark.production_authoring import PRODUCTION_SYNTHETIC_GENERATORS
from dynamislm.benchmark.repair_geometry import (
    RepairClassification,
    RepairGeometry,
    SplitCapacityCertificate,
    classify_archetype_repair,
    compute_split_capacity_envelope,
    derive_governed_archetypes,
    remaining_lane_capacity,
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
    result = run(DEFAULT_PRODUCTION_ROOT, replay=True)
    capacities = result["split_capacities"]
    assert capacities[PUBLIC.value]["required"] == 260
    assert capacities[PUBLIC.value]["maximum"] == 212
    assert capacities[PUBLIC.value]["capacity_deficit"] == 48
    assert result["public_max_without_colocation"] == 260
    assert result["public_max_without_feature_minima"] == 426
    assert result["authorable_lane_count"] == 3
    assert result["repair_archetype_count"] == 12
