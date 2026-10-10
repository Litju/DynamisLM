from __future__ import annotations

from types import SimpleNamespace

import pytest
from scripts import res407_governed_backfill as res407

from dynamislm.benchmark.authority_supply import (
    LaneCapacityStatus,
    ReserveCandidateLaneV1,
)
from dynamislm.benchmark.constants import CaseOrigin, SplitName
from dynamislm.benchmark.production_authoring import PRODUCTION_SYNTHETIC_GENERATORS
from dynamislm.benchmark.variable_pool import (
    ProductionCandidateRecipeV1,
    RecipeAuthorityBasis,
    VariablePoolAuthoringPlanV1,
)
from dynamislm.serialization import canonical_hash

_SHA = "sha256:" + "1" * 64


def _source_lane() -> ReserveCandidateLaneV1:
    return ReserveCandidateLaneV1(
        lane_id="source:test",
        origin_class=CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION,
        authority_ref="test source authority",
        authority_digest=_SHA,
        capacity_unit="source candidate",
        existing_planned_capacity=0,
        available_capacity=1,
        capacity_status=LaneCapacityStatus.AVAILABLE,
        supported_cells=(("C13", "F02"),),
        isolation_identity_digests=(_SHA,),
    )


def _synthetic_plan() -> VariablePoolAuthoringPlanV1:
    generator = next(
        item
        for item in PRODUCTION_SYNTHETIC_GENERATORS
        if item.generator_family.endswith("public_development")
    )
    recipe = ProductionCandidateRecipeV1(
        candidate_id="PSE-V1-CANDIDATE:SYNTH:C08:F14:PUBLIC_DEVELOPMENT",
        origin_class=CaseOrigin.DETERMINISTIC_SYNTHETIC,
        capability_id="C08",
        benchmark_family="F14",
        authority_basis=RecipeAuthorityBasis.HISTORICAL_INDIVIDUAL_RECIPE,
        authority_ref="historical recipe authority",
        authority_digest=_SHA,
        generator_family=generator.generator_family,
        split_lock=SplitName.PUBLIC_DEVELOPMENT,
        seed_block="historical-seed",
    )
    return VariablePoolAuthoringPlanV1(
        supply_inventory_digest=_SHA,
        qualification_exclusion_digest=_SHA,
        recipes=(recipe,),
    )


def _synthetic_lane(cell: tuple[str, str] = ("C08", "F05")) -> ReserveCandidateLaneV1:
    generator = next(
        item
        for item in PRODUCTION_SYNTHETIC_GENERATORS
        if item.generator_family.endswith("public_development")
    )
    return ReserveCandidateLaneV1(
        lane_id=f"synthetic:{generator.generator_family}",
        origin_class=CaseOrigin.DETERMINISTIC_SYNTHETIC,
        authority_ref="registered split-family synthetic generator",
        authority_digest=canonical_hash(generator),
        capacity_unit="unique split-locked synthetic seed block",
        existing_planned_capacity=0,
        available_capacity=None,
        capacity_status=LaneCapacityStatus.RULE_GOVERNED,
        capacity_rule="registered generator and split-family seed-block namespace",
        supported_cells=(cell,),
        isolation_identity_digests=tuple(
            sorted(
                (
                    canonical_hash(
                        ("SYNTHETIC_GENERATOR", generator.generator_id, generator.version)
                    ),
                    canonical_hash(("GENERATOR_FAMILY", generator.generator_family)),
                    canonical_hash(("SYNTHETIC_SPLIT_LOCK", SplitName.PUBLIC_DEVELOPMENT)),
                )
            )
        ),
    )


def _option(digest: str) -> dict[str, str]:
    return {"candidate_digest": f"sha256:{digest * 64}"}


def test_finite_lane_capacity_already_used_by_res405_is_not_reused() -> None:
    assert res407._lane_remaining(_source_lane(), consumed=1) == 0
    assert res407._lane_remaining(_source_lane(), consumed=0) == 1


def test_option_builder_skips_unsupported_lanes_and_binds_generator_authority() -> None:
    demand = {"conflict_set_digest": res407.RES451_CONFLICT_SET_DIGEST}
    plan = _synthetic_plan()
    assert res407._synthetic_option_recipes(demand, (_source_lane(),), plan) == ()

    lane = _synthetic_lane()
    recipes = res407._synthetic_option_recipes(demand, (lane,), plan)
    assert len(recipes) == 1
    assert recipes[0].lane_id == lane.lane_id
    assert recipes[0].authority_ref == lane.authority_ref
    assert recipes[0].authority_digest == lane.authority_digest
    assert recipes[0].split_lock is SplitName.PUBLIC_DEVELOPMENT

    forged = ReserveCandidateLaneV1(
        lane_id=lane.lane_id,
        origin_class=lane.origin_class,
        authority_ref=lane.authority_ref,
        authority_digest=_SHA,
        capacity_unit=lane.capacity_unit,
        existing_planned_capacity=lane.existing_planned_capacity,
        available_capacity=None,
        capacity_status=lane.capacity_status,
        capacity_rule=lane.capacity_rule,
        supported_cells=lane.supported_cells,
        isolation_identity_digests=lane.isolation_identity_digests,
    )
    with pytest.raises(ValueError, match="no exact registered materializer"):
        res407._synthetic_option_recipes(demand, (forged,), plan)


def test_candidate_option_and_addition_set_order_is_deterministic() -> None:
    options = (_option("b"), _option("a"))
    ordered = res407._option_order(options)
    assert [item["candidate_digest"] for item in ordered] == sorted(
        item["candidate_digest"] for item in options
    )
    assert [
        tuple(item["candidate_digest"] for item in group)
        for group in res407._addition_sets(options)
    ] == [
        (ordered[0]["candidate_digest"],),
        (ordered[1]["candidate_digest"],),
        tuple(item["candidate_digest"] for item in ordered),
    ]


def test_search_prefers_smallest_exact_qualified_addition_set() -> None:
    options = (_option("a"), _option("b"), _option("c"))
    evaluated: list[tuple[str, ...]] = []

    def evaluate(selected: tuple[dict[str, str], ...]) -> dict[str, str]:
        key = tuple(item["candidate_digest"] for item in selected)
        evaluated.append(key)
        return {
            "qualification_status": (
                "QUALIFIED"
                if len(selected) == 2
                and key
                == tuple(item["candidate_digest"] for item in res407._option_order(options)[:2])
                else "INFEASIBLE"
            )
        }

    selected, status, _receipts = res407._search_repair_sets(options, evaluate)
    assert status == "QUALIFIED"
    assert selected is not None and len(selected) == 2
    assert len(evaluated[0]) == 1 and len(evaluated[1]) == 1
    assert evaluated[-1] == tuple(item["candidate_digest"] for item in selected)


def test_redundant_additions_are_removed_and_unknown_stops_minimization() -> None:
    options = tuple(_option(char) for char in "abc")
    ordered = res407._option_order(options)
    statuses = {
        (ordered[1]["candidate_digest"], ordered[2]["candidate_digest"]): "FEASIBLE",
        (ordered[2]["candidate_digest"],): "FEASIBLE",
        (): "INFEASIBLE",
    }
    reduced, minimality = res407._minimize_repair_set(
        options,
        lambda values: statuses[tuple(item["candidate_digest"] for item in values)],
    )
    assert tuple(item["candidate_digest"] for item in reduced) == (ordered[2]["candidate_digest"],)
    assert minimality == "INCLUSION_MINIMAL_PROVEN"
    unknown, status = res407._minimize_repair_set(options, lambda _values: "UNKNOWN")
    assert len(unknown) == len(options)
    assert status == "UNKNOWN"


def test_unknown_solver_case_never_authorizes_a_repair() -> None:
    options = (_option("a"), _option("b"))
    calls = 0

    def evaluate(_selected: tuple[dict[str, str], ...]) -> dict[str, str]:
        nonlocal calls
        calls += 1
        return {"qualification_status": "UNKNOWN"}

    selected, status, _results = res407._search_repair_sets(options, evaluate)
    assert selected is None
    assert status == "UNKNOWN"
    assert calls == 1


def test_infeasible_full_option_set_prunes_every_subset() -> None:
    options = tuple(_option(char) for char in "abc")
    screen_calls: list[tuple[str, ...]] = []
    evaluated: list[tuple[str, ...]] = []

    def screen(values: tuple[dict[str, str], ...]) -> dict[str, str]:
        screen_calls.append(tuple(item["candidate_digest"] for item in values))
        return {"qualification_status": "INFEASIBLE"}

    def evaluate(values: tuple[dict[str, str], ...]) -> dict[str, str]:
        evaluated.append(tuple(item["candidate_digest"] for item in values))
        return {"qualification_status": "INFEASIBLE"}

    selected, status, outcomes = res407._search_repair_sets(
        options, evaluate, superset_screen=screen
    )
    assert selected is None
    assert status == "NO_FEASIBLE_SET_IN_BOUNDED_OPTIONS"
    assert len(screen_calls) == 1 and len(screen_calls[0]) == len(options)
    assert evaluated == []
    assert len(outcomes) == 1


def test_unknown_full_option_screen_stops_without_searching_subsets() -> None:
    options = tuple(_option(char) for char in "abc")
    evaluated = False

    def evaluate(_values: tuple[dict[str, str], ...]) -> dict[str, str]:
        nonlocal evaluated
        evaluated = True
        return {"qualification_status": "QUALIFIED"}

    selected, status, _outcomes = res407._search_repair_sets(
        options,
        evaluate,
        superset_screen=lambda _values: {"qualification_status": "UNKNOWN"},
    )
    assert selected is None
    assert status == "UNKNOWN"
    assert not evaluated


def test_new_plan_uses_a_new_content_addressed_pool_path_and_original_is_immutable() -> None:
    original = _synthetic_plan()
    addition = res407._synthetic_option_recipes(
        {"conflict_set_digest": res407.RES451_CONFLICT_SET_DIGEST},
        (_synthetic_lane(),),
        original,
    )[0]
    derived = VariablePoolAuthoringPlanV1(
        supply_inventory_digest=original.supply_inventory_digest,
        qualification_exclusion_digest=original.qualification_exclusion_digest,
        recipes=tuple(sorted((*original.recipes, addition), key=lambda item: item.candidate_id)),
    )
    assert derived.plan_digest != original.plan_digest
    assert res407._pool_store_relative_path(
        derived.plan_digest
    ) != res407._pool_store_relative_path(original.plan_digest)
    res407._assert_original_store_unchanged(_SHA, _SHA)
    with pytest.raises(ValueError, match="RES-405 immutable pool/store changed"):
        res407._assert_original_store_unchanged(_SHA, "sha256:" + "2" * 64)


def test_full_removal_and_critical_reserve_are_required_for_qualification() -> None:
    assert (
        res407._qualification_status(
            checked=3,
            candidate_count=3,
            feasible=3,
            infeasible=0,
            unknown=0,
            critical_status="PASS",
            backfill_needs=(),
        )
        == "QUALIFIED"
    )
    assert (
        res407._qualification_status(
            checked=2,
            candidate_count=3,
            feasible=2,
            infeasible=0,
            unknown=0,
            critical_status="PASS",
            backfill_needs=(),
        )
        == "NOT_QUALIFIED"
    )
    assert (
        res407._qualification_status(
            checked=3,
            candidate_count=3,
            feasible=2,
            infeasible=1,
            unknown=0,
            critical_status="DEFICIT",
            backfill_needs=(),
        )
        == "NOT_QUALIFIED"
    )
    assert (
        res407._qualification_status(
            checked=1,
            candidate_count=3,
            feasible=0,
            infeasible=0,
            unknown=1,
            critical_status="UNKNOWN",
            backfill_needs=(),
        )
        == "UNKNOWN"
    )


def test_authority_expansion_requires_complete_inventory_and_capacity_scope() -> None:
    inventory = SimpleNamespace(
        authority_inventory_complete=True,
        capacity_scope_complete=False,
    )
    assert not res407._authority_exhaustion_proven(inventory, True, 0, 0)
    inventory.capacity_scope_complete = True
    assert res407._authority_exhaustion_proven(inventory, True, 0, 0)
    assert not res407._authority_exhaustion_proven(inventory, False, 0, 0)
    assert not res407._authority_exhaustion_proven(inventory, True, 1, 0)


def test_public_payload_does_not_expose_candidate_content_or_private_identity() -> None:
    receipt = {
        "repair_demand_digest": _SHA,
        "authorable_lane_count": 1,
        "materializable_lane_count": 1,
        "candidate_option_count": 1,
        "candidate_option_origin_counts": {"DETERMINISTIC_SYNTHETIC": 1},
        "candidate_option_cell_counts": {"C08:F05": 1},
        "original_origin_counts": {"SOURCE_BACKED_EVIDENCE_EXTRACTION": 1},
        "original_cell_counts": {"C13:F02": 1},
        "repaired_origin_counts": None,
        "repaired_cell_counts": None,
        "repair_trial_count": 1,
        "repair_set_digest": _SHA,
        "retained_addition_count": 0,
        "repair_minimality_status": "NOT_PROVEN",
        "repaired_plan_digest": None,
        "repaired_pool_digest": None,
        "repaired_pool_count": None,
        "repaired_base_problem_digest": None,
        "repaired_base_status": None,
        "checked_removals": 0,
        "feasible_removals": 0,
        "infeasible_removals": 0,
        "unknown_removals": 0,
        "critical_obligation_count": None,
        "critical_with_structural_reserve": None,
        "critical_reserve_status": "NOT_EVALUATED",
        "authority_exhaustion_category": "CAPACITY_SCOPE_INCOMPLETE",
        "authority_exhaustion_proven": False,
        "outcome": "UNKNOWN",
        "next": "STOP",
        "artifact_inventory_digest": _SHA,
        "receipt_digest": _SHA,
        "fresh_process_confirmation": "PASS",
        "public_leak_guard": "PASS",
        "post_write_public_leak_guard": "PASS",
        "candidate_id": "private-candidate-id",
        "candidate_question": "private question text",
    }
    public = res407._public_payload(receipt)
    encoded = str(public)
    assert "private-candidate-id" not in encoded
    assert "private question text" not in encoded
    assert "candidate_id" not in public
