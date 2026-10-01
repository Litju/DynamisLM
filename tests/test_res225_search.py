from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
import scripts.res225_repair as res225_search
from pysat.solvers import Solver  # type: ignore[import-untyped]
from scripts.res225_repair import (
    _append_unique_core,
    _apply_cost2_closure_result,
    _block_hitman_repair,
    _candidate_model_fallback,
    _checkpoint_bind,
    _core_hit_set_is_sat,
    _cost2_closure_receipt,
    _decode_candidate_sat_repair,
    _emit_iteration,
    _enforce_variant_cap,
    _exact_state,
    _exact_variant_exclusion_record,
    _exact_variant_nogood_clause,
    _hitman_from_cores,
    _hitman_solution,
    _independent_minimum_crosscheck,
    _make_materialization_plan,
    _minimum_hit_cost,
    _optimality_gap,
    _read_checkpoint,
    _release_cost_cap_clauses,
    _repair_primary_cost,
    _repair_score,
    _RepairSearchBlockedError,
    _RepairSearchPausedError,
    _replay_exact_exclusions,
    _require_abstract_feasible,
    _solver_core_ids,
    _validate_checkpoint,
    _write_checkpoint,
)

from dynamislm.benchmark import res225_repair as repair_oracle
from dynamislm.benchmark.constants import CaseOrigin
from dynamislm.benchmark.production import (
    ProductionCandidateCommitmentV1,
    _canonical_split_ranks_glucose,
    _ExactConstraint,
)
from dynamislm.benchmark.res225_repair import (
    CoreModel,
    CoreSolveTimeoutError,
    PreservationAssumption,
    RepairAction,
    shrink_unsat_core,
    solve_assumptions_limited,
)
from dynamislm.serialization import canonical_hash


def test_semantic_core_extraction_and_shrinking_are_deterministic() -> None:
    model = SimpleNamespace(
        assumption_literals={"KEEP:A": 1, "KEEP:B": 2, "KEEP:C": 3},
        release_variables={"A": 4},
    )
    with Solver(name="g4", bootstrap_with=[[-1, -2]]) as solver:
        assert not solver.solve(assumptions=[1, 2, 3])
        typed_model = cast(CoreModel, model)
        assert _solver_core_ids(solver, typed_model) == ("KEEP:A", "KEEP:B")
        first = shrink_unsat_core(
            solver,
            typed_model,
            ("KEEP:C", "KEEP:B", "KEEP:A"),
            deadline=time.monotonic() + 5,
        )
        second = shrink_unsat_core(
            solver,
            typed_model,
            ("KEEP:A", "KEEP:B", "KEEP:C"),
            deadline=time.monotonic() + 5,
        )
    assert first == second == ("KEEP:A", "KEEP:B")


def test_core_shrinking_is_bounded_and_keeps_a_valid_unsat_core() -> None:
    assumptions = {f"KEEP:{index:02d}": index + 1 for index in range(20)}
    model = cast(CoreModel, SimpleNamespace(assumption_literals=assumptions))
    with Solver(name="g4", bootstrap_with=[[-1, -2]]) as solver:
        reduced = shrink_unsat_core(
            solver,
            model,
            tuple(assumptions),
            max_checks=3,
            deadline=time.monotonic() + 5,
        )
        assert not solver.solve(assumptions=[assumptions[item] for item in reduced])
    assert len(reduced) == 19


def test_assumption_solver_timeout_fails_closed() -> None:
    with Solver(name="g4") as solver:
        with pytest.raises(CoreSolveTimeoutError):
            solve_assumptions_limited(solver, (), deadline=time.monotonic() - 1)


def test_glucose_canonical_self_reduction_matches_fixed_rank() -> None:
    constraints = (_ExactConstraint("FIX_RANK_TWO", terms=((0, 2, 1),), lower=1, upper=1),)
    progress: list[tuple[int, int, str]] = []
    status, ranks, trace = _canonical_split_ranks_glucose(
        1,
        constraints,
        progress_callback=lambda done, total, state: progress.append((done, total, state)),
    )
    assert (status, ranks) == ("PASS", (2,))
    assert trace == ((0, 0, "INFEASIBLE"), (0, 1, "INFEASIBLE"), (0, 2, "FEASIBLE"))
    assert progress == [(1, 1, "FEASIBLE")]


def test_incremental_solver_reuses_model_for_exact_variant_no_good() -> None:
    model = SimpleNamespace(
        release_variables={"a": 1, "b": 2},
        target_variables={"a": {"x": 3, "y": 4}},
    )
    clause = _exact_variant_nogood_clause(cast(CoreModel, model), ("a",), {"a": "x"})
    with Solver(name="g4", bootstrap_with=[[3, 4], [-3, -4]]) as solver:
        solver_id = id(solver)
        assert solver.solve(assumptions=[1, -2, 3])
        solver.add_clause(list(clause))
        assert id(solver) == solver_id
        assert not solver.solve(assumptions=[1, -2, 3])
        assert solver.solve(assumptions=[1, -2, 4])
        assert solver.solve(assumptions=[-1, 2, 3])


def test_global_primary_cost_cap_is_encoded_as_a_weighted_pb_bound() -> None:
    model = cast(
        CoreModel,
        SimpleNamespace(
            clauses=(),
            max_variable=2,
            release_variables={"a": 1, "b": 2},
        ),
    )
    clauses, maximum_variable = _release_cost_cap_clauses(model, {"a": 2, "b": 1}, 2)
    assert clauses
    assert maximum_variable >= 2
    with Solver(name="g4", bootstrap_with=clauses) as solver:
        assert not solver.solve(assumptions=[1, 2])
        assert solver.solve(assumptions=[1, -2])
        assert solver.solve(assumptions=[-1, 2])


def test_global_sat_repair_decoding_returns_actions_targets_and_allocation() -> None:
    model = cast(
        CoreModel,
        SimpleNamespace(
            release_variables={"a": 1, "b": 2},
            target_variables={"a": {"parent-a": 3, "parent-b": 4}},
            candidate_ids=("candidate-a", "candidate-b"),
            assignment_variables=((5, 6, 7), (8, 9, 10)),
        ),
    )
    assert _decode_candidate_sat_repair(model, (1, -2, 3, -4, 5, -6, -7, -8, 9, -10)) == (
        ("a",),
        {"a": "parent-a"},
        {"candidate-a": 0, "candidate-b": 1},
    )


def test_certified_cost2_unsat_promotes_only_global_primary_bound() -> None:
    checkpoint = {
        "LOWER_BOUND": 2,
        "GLOBAL_PRIMARY_LOWER_BOUND": 2,
        "UPPER_BOUND": None,
        "upper_bound": None,
        "OPTIMALITY_GAP": None,
    }
    promoted = _apply_cost2_closure_result(
        checkpoint,
        {"status": "UNSAT", "proof_check_status": "PASS"},
    )
    assert promoted["LOWER_BOUND"] == 2
    assert promoted["GLOBAL_PRIMARY_LOWER_BOUND"] == 3
    assert promoted["upper_bound"] is None
    with pytest.raises(ValueError, match="checked proof"):
        _apply_cost2_closure_result(
            checkpoint,
            {"status": "UNSAT", "proof_check_status": "NOT_RUN"},
        )


def test_terminal_cost2_unsat_receipt_preserves_promoted_bound() -> None:
    receipt = _cost2_closure_receipt(
        {
            "CHECKPOINT_DIGEST": "sha256:" + "d" * 64,
            "LOWER_BOUND": 2,
            "GLOBAL_PRIMARY_LOWER_BOUND": 3,
            "UPPER_BOUND": None,
        },
        {
            "status": "UNSAT",
            "proof_check_status": "PASS",
            "repairs_tested_total": 0,
            "exact_variant_nogoods": 0,
            "abstract_base_status": "NOT_RUN",
            "abstract_colocation_status": "NOT_RUN",
        },
    )
    assert receipt["LOWER_BOUND_AFTER"] == 3
    assert receipt["UPPER_BOUND_AFTER"] == "NONE"
    assert receipt["NEXT"] == "RESUME_COST3_SEARCH"


def test_cost2_unknown_preserves_global_primary_lower_bound() -> None:
    checkpoint = {
        "LOWER_BOUND": 2,
        "GLOBAL_PRIMARY_LOWER_BOUND": 2,
        "UPPER_BOUND": None,
        "upper_bound": None,
        "OPTIMALITY_GAP": None,
    }
    updated = _apply_cost2_closure_result(
        checkpoint,
        {"status": "UNKNOWN", "proof_check_status": "NOT_RUN"},
    )
    assert updated["LOWER_BOUND"] == 2
    assert updated["GLOBAL_PRIMARY_LOWER_BOUND"] == 2


def test_exact_unknown_is_not_feasible_or_infeasible() -> None:
    receipt = SimpleNamespace(
        base_status="FEASIBLE",
        colocation_status="FEASIBLE",
        status="BLOCKED",
    )
    assert _exact_state(receipt) == "UNKNOWN"


def test_candidate_model_returns_one_sat_split_hint() -> None:
    clauses = (
        (1, 2, 3),
        (-1, -2),
        (-1, -3),
        (-2, -3),
        (4, 5, 6),
        (-4, -5),
        (-4, -6),
        (-5, -6),
    )
    model = SimpleNamespace(
        clauses=clauses,
        assumption_literals={"KEEP:c1": 8},
        assumption_action_ids={"KEEP:c1": "a"},
        release_variables={"a": 7},
        target_variables={},
        candidate_ids=("c1", "c2"),
        assignment_variables=((1, 2, 3), (4, 5, 6)),
    )
    with Solver(name="g4", bootstrap_with=clauses) as solver:
        result = _core_hit_set_is_sat(
            solver,
            cast(CoreModel, model),
            ("a",),
            time_budget_seconds=5,
        )
    status, _core, target_map, rank_hint, _raw_size, _min_size, _seconds = result
    assert status == "SAT"
    assert target_map == {}
    assert set(rank_hint) == {"c1", "c2"}
    assert all(rank in range(3) for rank in rank_hint.values())


def test_target_parent_assignment_uses_one_sat_witness_not_cartesian_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clauses = ((2, 3), (-2, -3), (4, 5, 6), (-4, -5), (-4, -6), (-5, -6))
    model = SimpleNamespace(
        clauses=clauses,
        assumption_literals={},
        assumption_action_ids={},
        release_variables={"action": 1},
        target_variables={"action": {"parent-a": 2, "parent-b": 3}},
        candidate_ids=("candidate",),
        assignment_variables=((4, 5, 6),),
    )
    calls = 0
    original = solve_assumptions_limited

    def counted(*args: Any, **kwargs: Any) -> bool:
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(res225_search, "solve_assumptions_limited", counted)
    with Solver(name="g4", bootstrap_with=clauses) as solver:
        result = _core_hit_set_is_sat(
            solver,
            cast(CoreModel, model),
            ("action",),
            time_budget_seconds=5,
        )
    assert result[0] == "SAT"
    assert result[2]["action"] in {"parent-a", "parent-b"}
    assert calls == 1


def test_independent_candidate_sat_fallback_returns_validated_assignment() -> None:
    clauses = ((2, 3), (-2, -3), (4, 5, 6), (-4, -5), (-4, -6), (-5, -6))
    model = cast(
        CoreModel,
        SimpleNamespace(
            clauses=clauses,
            assumption_literals={},
            assumption_action_ids={},
            release_variables={"action": 1},
            target_variables={"action": {"parent-a": 2, "parent-b": 3}},
            candidate_ids=("candidate",),
            assignment_variables=((4, 5, 6),),
        ),
    )
    status, _core, target_map, rank_hint, *_rest = _candidate_model_fallback(
        model,
        ("action",),
        extra_clauses=(),
        time_budget_seconds=5,
    )
    assert status == "SAT"
    assert target_map["action"] in {"parent-a", "parent-b"}
    assert set(rank_hint) == {"candidate"}


def test_exact_variant_checks_only_the_sat_selected_target_map(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    @dataclass(frozen=True)
    class Receipt:
        status: str
        base_status: str
        colocation_status: str
        canonical_self_reduction_status: str
        canonical_witness_digest: str | None
        receipt_digest: str = "sha256:" + "0" * 64
        hard_cell_count_by_split: tuple[Any, ...] = ()
        adversarial_tag_count_by_split: tuple[Any, ...] = ()
        reachable_error_count_by_split: tuple[Any, ...] = ()
        protected_critical_error_count_by_split: tuple[Any, ...] = ()
        answerable_case_count_by_split: tuple[Any, ...] = ()
        c18_refusal_cell_count_by_split: tuple[Any, ...] = ()

    calls: list[dict[str, object]] = []
    feasible_receipt = Receipt("FEASIBLE", "FEASIBLE", "FEASIBLE", "NOT_RUN", None)

    def fake_exact(
        _commitments: tuple[object, ...],
        _pairs: tuple[tuple[str, str], ...],
        **kwargs: Any,
    ) -> Any:
        calls.append(kwargs)
        return feasible_receipt

    monkeypatch.setattr(res225_search, "make_abstract_design", lambda *args, **kwargs: ((), ()))
    monkeypatch.setattr(res225_search, "run_exact_abstract_oracle", fake_exact)
    result = res225_search._exact_repair_variant(
        (),
        (),
        (),
        (),
        target_parent_by_action={},
        candidate_rank_hint={},
        time_budget_seconds=10,
    )
    assert result[0] == "FEASIBLE"
    assert len(calls) == 1
    assert calls[0]["time_budget_seconds"] == 10
    assert calls[0]["canonicalize"] is False
    assert calls[0]["canonical_progress_callback"] is None

    calls.clear()

    def fake_unknown(
        _commitments: tuple[object, ...],
        _pairs: tuple[tuple[str, str], ...],
        **kwargs: Any,
    ) -> Any:
        calls.append(kwargs)
        return Receipt("BLOCKED", "UNKNOWN", "UNKNOWN", "NOT_RUN", None)

    monkeypatch.setattr(
        res225_search,
        "run_exact_abstract_oracle",
        fake_unknown,
    )
    blocked = res225_search._exact_repair_variant(
        (),
        (),
        (),
        (),
        target_parent_by_action={},
        candidate_rank_hint={},
        time_budget_seconds=10,
    )
    assert blocked[0] == "UNKNOWN"
    assert len(calls) == 1


def test_cp_sat_unknown_falls_back_to_independent_sat_pb(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    @dataclass(frozen=True)
    class Receipt:
        status: str
        base_status: str
        colocation_status: str
        canonical_self_reduction_status: str
        canonical_witness_digest: str | None
        receipt_digest: str = "sha256:" + "0" * 64
        hard_cell_count_by_split: tuple[Any, ...] = ()
        adversarial_tag_count_by_split: tuple[Any, ...] = ()
        reachable_error_count_by_split: tuple[Any, ...] = ()
        protected_critical_error_count_by_split: tuple[Any, ...] = ()
        answerable_case_count_by_split: tuple[Any, ...] = ()
        c18_refusal_cell_count_by_split: tuple[Any, ...] = ()

    monkeypatch.setattr(res225_search, "make_abstract_design", lambda *args, **kwargs: ((), ()))
    monkeypatch.setattr(
        res225_search,
        "run_exact_abstract_oracle",
        lambda *args, **kwargs: Receipt("BLOCKED", "UNKNOWN", "UNKNOWN", "NOT_RUN", None),
    )
    monkeypatch.setattr(
        res225_search,
        "_independent_abstract_fallback",
        lambda *args, **kwargs: (
            {"BASE": "FEASIBLE", "COLOCATION": "FEASIBLE"},
            {
                "BASE": {
                    "result": "SAT",
                    "witness_independently_validated": True,
                    "witness_digest": "base-witness",
                },
                "COLOCATION": {
                    "result": "SAT",
                    "witness_independently_validated": True,
                    "witness_digest": "colocation-witness",
                },
            },
        ),
    )
    monkeypatch.setattr(
        res225_search, "bind_production_exact_feasibility_receipt", lambda value: value
    )

    state, receipt, *_rest, evidence = res225_search._exact_repair_variant(
        (),
        (),
        (),
        (),
        target_parent_by_action={},
        candidate_rank_hint=None,
        time_budget_seconds=5,
    )
    assert state == "FEASIBLE"
    assert receipt.base_status == receipt.colocation_status == "FEASIBLE"
    assert receipt.canonical_self_reduction_status == "NOT_RUN"
    assert receipt.canonical_witness_digest is None
    assert evidence is not None
    assert evidence["witness_digests"] == {
        "BASE": "base-witness",
        "COLOCATION": "colocation-witness",
    }


def test_feasible_repair_requires_independent_base_and_colocation_witnesses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt = SimpleNamespace(
        status="FEASIBLE",
        base_status="FEASIBLE",
        colocation_status="FEASIBLE",
        canonical_self_reduction_status="NOT_RUN",
        canonical_witness_digest=None,
    )
    monkeypatch.setattr(res225_search, "make_abstract_design", lambda *args, **kwargs: ((), ()))
    monkeypatch.setattr(res225_search, "run_exact_abstract_oracle", lambda *args, **kwargs: receipt)
    monkeypatch.setattr(
        res225_search,
        "_independent_abstract_fallback",
        lambda *args, **kwargs: (
            {"BASE": "FEASIBLE", "COLOCATION": "FEASIBLE"},
            {
                mode: {
                    "result": "SAT",
                    "witness_independently_validated": True,
                    "witness_digest": f"{mode.lower()}-witness",
                }
                for mode in ("BASE", "COLOCATION")
            },
        ),
    )

    state, _receipt, _commitments, _pairs, _seconds, evidence = res225_search._exact_repair_variant(
        (),
        (),
        (),
        (),
        target_parent_by_action={},
        candidate_rank_hint=None,
        time_budget_seconds=5,
        independent_validate=True,
        production_root=Path("/private"),
    )
    assert state == "FEASIBLE"
    assert evidence is not None
    assert evidence["witness_digests"] == {
        "BASE": "base-witness",
        "COLOCATION": "colocation-witness",
    }


def test_independent_witnesses_must_cover_both_exact_models() -> None:
    records = {
        "BASE": {
            "result": "SAT",
            "witness_independently_validated": True,
            "witness_digest": "base-witness",
        }
    }
    witnesses = res225_search._independent_witness_digests(records)
    assert witnesses == {"BASE": "base-witness"}
    assert len(witnesses) != 2


def test_incumbent_metadata_lists_released_slots_and_origin_counts() -> None:
    actions = {"action-a": SimpleNamespace(affected_candidate_ids=("candidate-b", "candidate-a"))}
    commitments = cast(
        tuple[ProductionCandidateCommitmentV1, ...],
        (
            SimpleNamespace(item=SimpleNamespace(origin_class=CaseOrigin.EXPERT_AUTHORED_SEMANTIC)),
            SimpleNamespace(item=SimpleNamespace(origin_class=CaseOrigin.DETERMINISTIC_SYNTHETIC)),
        ),
    )
    assert res225_search._released_candidate_ids(
        ("action-a",), cast(dict[str, RepairAction], actions)
    ) == (
        "candidate-a",
        "candidate-b",
    )
    assert res225_search._origin_counts(commitments) == (
        (CaseOrigin.DETERMINISTIC_SYNTHETIC.value, 1),
        (CaseOrigin.EXPERT_AUTHORED_SEMANTIC.value, 1),
    )


def test_repair_search_oracle_disables_canonical_self_reduction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        repair_oracle,
        "validate_production_exact_feasibility",
        lambda *args, **kwargs: (captured.update(kwargs) or SimpleNamespace(receipt=object())),
    )
    repair_oracle.run_exact_abstract_oracle((), (), time_budget_seconds=2)
    assert captured["run_canonical_self_reduction"] is False
    assert captured["canonical_progress_callback"] is None


def test_primary_repair_objective_is_released_slot_cardinality() -> None:
    actions = {
        "one-slot": SimpleNamespace(content_replacement_count=1),
        "three-slots": SimpleNamespace(content_replacement_count=3),
    }
    cores = [{"action_ids": ("one-slot", "three-slots")}]
    weights = {key: item.content_replacement_count for key, item in actions.items()}
    hitman = _hitman_from_cores(cores, weights)
    selected = _hitman_solution(hitman, weights)
    rc2_selected, rc2_cost = res225_search._rc2_optimum(tuple(actions), cores, weights)
    typed_actions = cast(dict[str, RepairAction], actions)
    assert _repair_primary_cost(selected, typed_actions) == 1
    assert rc2_cost == _repair_primary_cost(rc2_selected, typed_actions) == 1


def test_exhausted_family_block_preserves_larger_repair_supersets() -> None:
    weights = {"a": 1, "b": 5, "c": 1}
    hitman = _hitman_from_cores([{"action_ids": ("a", "b")}], weights)
    _block_hitman_repair(hitman, tuple(weights), ("a",), weights)
    selected = _hitman_solution(hitman, weights)
    assert set(selected) == {"a", "c"}


def test_known_cores_define_lower_bound_and_feasible_repair_defines_gap() -> None:
    cores = [
        {"action_ids": ("a", "b")},
        {"action_ids": ("b", "c")},
    ]
    assert _minimum_hit_cost(cores, {"a": 1, "b": 5, "c": 1}) == 2
    assert _optimality_gap(2, None) is None
    assert _optimality_gap(2, 3) == 1
    with pytest.raises(ValueError, match="bounds"):
        _optimality_gap(4, 3)


def test_variant_cap_checkpoints_without_marking_family_infeasible() -> None:
    checkpoint_phases: list[str] = []
    family_state = {"status": "SEARCHING"}

    def block() -> None:
        checkpoint_phases.append("BLOCKED_EXACT_VARIANT_LIMIT")
        raise _RepairSearchBlockedError("variant family was not exhausted")

    with pytest.raises(_RepairSearchBlockedError, match="not exhausted"):
        _enforce_variant_cap(4, 4, block)
    assert checkpoint_phases == ["BLOCKED_EXACT_VARIANT_LIMIT"]
    assert family_state["status"] == "SEARCHING"


def test_secondary_criteria_are_lexicographic_after_primary_cost() -> None:
    def commitment(
        *,
        origin: CaseOrigin = CaseOrigin.EXPERT_AUTHORED_SEMANTIC,
        capability: str = "C01",
        family: str = "F01",
    ) -> SimpleNamespace:
        return SimpleNamespace(
            candidate_id="candidate",
            item=SimpleNamespace(
                origin_class=origin,
                capability_id=capability,
                benchmark_family=family,
                practitioner_question_class="Q1",
                scoring_profile="S1",
                difficulty="D1",
                parent_candidate_id=None,
                source_document_ids=(),
                source_artifact_ids=(),
                construct_test_identity_ids=(),
                provider_export_ids=(),
            ),
        )

    before = (commitment(),)
    profile_low = {
        "minimum_cell_eligible_component_count": 1,
        "total_cell_eligible_component_count": 1,
        "colocation_component_count": 1,
        "base_component_count": 1,
    }
    profile_high = {
        "minimum_cell_eligible_component_count": 10,
        "total_cell_eligible_component_count": 10,
        "colocation_component_count": 10,
        "base_component_count": 10,
    }
    no_origin_change = (commitment(capability="C02", family="F02"),)
    with_origin_change = (commitment(origin=CaseOrigin.DETERMINISTIC_SYNTHETIC),)
    typed_before = cast(tuple[ProductionCandidateCommitmentV1, ...], before)
    no_origin_score = _repair_score(
        ("same",),
        {},
        profile_low,
        {},
        typed_before,
        cast(tuple[ProductionCandidateCommitmentV1, ...], no_origin_change),
    )
    origin_change_score = _repair_score(
        ("same",),
        {},
        profile_high,
        {},
        typed_before,
        cast(tuple[ProductionCandidateCommitmentV1, ...], with_origin_change),
    )
    assert no_origin_score < origin_change_score


def test_duplicate_core_is_a_no_progress_error() -> None:
    core: dict[str, Any] = {"action_core_digest": "same-core", "action_ids": ("a",)}
    cores: list[dict[str, Any]] = []
    _append_unique_core(cores, core)
    with pytest.raises(RuntimeError, match="without progress"):
        _append_unique_core(cores, core)


def test_checkpoint_resume_replays_cores_and_exact_no_goods(tmp_path: Path) -> None:
    fingerprints = {"entry_head": "head", "models": "models"}
    core = {"action_core_digest": "core-digest", "action_ids": ("a", "b")}
    cores: list[dict[str, Any]] = [core]
    weights = {"a": 1, "b": 1}
    first_hitman = _hitman_from_cores(cores, weights)
    selected_before_restart = _hitman_solution(first_hitman, weights)

    model = SimpleNamespace(
        release_variables={"a": 1, "b": 2},
        target_variables={"a": {"x": 3, "y": 4}},
    )
    exclusion = _exact_variant_exclusion_record(
        {"BASE": cast(CoreModel, model), "COLOCATION": cast(CoreModel, model)},
        ("a",),
        {"a": "x"},
        SimpleNamespace(
            base_status="INFEASIBLE",
            colocation_status="INFEASIBLE",
            receipt_digest="receipt-digest",
        ),
    )
    state = {
        "fingerprints": fingerprints,
        "preservation_registry": (
            PreservationAssumption(
                assumption_id="KEEP:A",
                assumption_class="CANDIDATE_SLOT",
                candidate_ids=("candidate-a",),
                current_origin="EXPERT_AUTHORED_SEMANTIC",
                current_cell="C01:F01",
                component_key="component-a",
                scientific_authority_dependencies=("authority-a",),
                release_requires_new_content=True,
                release_affects_mutation_descendants=False,
                action_id="action-a",
            ),
        ),
        "action_registry": (),
        "cores": cores,
        "initial_core_count": 0,
        "iteration_records": [{"iteration": 3}],
        "exact_core_evidence": [],
        "excluded_exact_designs": [exclusion],
        "excluded_repair_families": [],
        "tested_repairs": [
            {
                "action_ids": ("a",),
                "target_parent_by_action": {"a": "x"},
                "status": "EXACT_INFEASIBLE_VARIANT",
                "receipt_digest": "receipt-digest",
            }
        ],
        "equality_records": [],
        "variant_counts": {"repair-a": 1},
        "iteration": 3,
        "elapsed_seconds": 12.5,
        "oracle_calls": 5,
        "oracle_status_counts": {"SAT": 2, "UNSAT": 3},
        "phase": "CORE_ADDED",
        "lower_bound": 1,
        "upper_bound": 2,
        "GLOBAL_PRIMARY_LOWER_BOUND": 1,
        "global_primary_lower_bound": 1,
        "optimality_gap": 1,
        "no_goods": 1,
        "current_hitting_set_size": 1,
        "LOWER_BOUND": 1,
        "UPPER_BOUND": 2,
        "OPTIMALITY_GAP": 1,
        "BEST_REPAIR_CARDINALITY": 2,
        "NO_GOODS": 1,
        "ITERATION": 3,
        "ELAPSED": 12.5,
        "CORES_DISCOVERED": 1,
        "LAST_CORE_SIZE": None,
        "LAST_MINIMIZED_CORE_SIZE": None,
        "CURRENT_HITTING_SET_SIZE": 1,
        "ORACLE_CALLS": 5,
        "LAST_ORACLE_STATUS": "UNSAT",
        "LAST_ORACLE_SECONDS": 0.25,
        "CURRENT_PHASE": "CORE_ADDED",
        "cost2_closure": {
            "schema": "RES-225-COST2-CLOSURE@1.0.0",
            "status": "UNKNOWN",
            "terminal": True,
            "primary_cost_cap": 2,
            "proof_check_status": "NOT_RUN",
        },
        "best_repair_cardinality": 2,
        "incumbent": {
            "action_ids": ("b",),
            "target_parent_by_action": {},
            "cardinality": 2,
            "repair_digest": "repair-b",
            "secondary_profile": {},
        },
    }
    production_root = tmp_path / "external"
    production_root.mkdir()
    _write_checkpoint(production_root, state)
    restored, digest, _file_digest = _read_checkpoint(
        production_root,
        expected_fingerprints=fingerprints,
    )
    restored_cores = cast(list[dict[str, Any]], restored["cores"])
    assert restored["LOWER_BOUND"] == 1
    assert restored["GLOBAL_PRIMARY_LOWER_BOUND"] == 1
    assert restored["UPPER_BOUND"] == 2
    assert restored["OPTIMALITY_GAP"] == 1
    assert restored["NO_GOODS"] == len(restored["excluded_exact_designs"]) == 1
    assert restored["variant_counts"] == {"repair-a": 1}
    assert restored["incumbent"]["action_ids"] == ["b"]
    assert restored["incumbent"]["cardinality"] == 2
    assert restored["incumbent"]["target_parent_by_action"] == {}
    assert restored["preservation_registry"][0]["assumption_id"] == "KEEP:A"
    assert "split_membership" not in restored
    assert restored["CHECKPOINT_DIGEST"] == digest
    assert restored["cost2_closure"]["status"] == "UNKNOWN"
    second_hitman = _hitman_from_cores(restored_cores, weights)
    assert _hitman_solution(second_hitman, weights) == selected_before_restart

    base_model = cast(CoreModel, SimpleNamespace(**model.__dict__))
    colocation_model = cast(CoreModel, SimpleNamespace(**model.__dict__))
    with (
        Solver(name="g4", bootstrap_with=[[3, 4], [-3, -4]]) as base,
        Solver(name="g4", bootstrap_with=[[3, 4], [-3, -4]]) as colocation,
    ):
        assert base.solve(assumptions=[1, -2, 3])
        _replay_exact_exclusions(
            cast(list[dict[str, Any]], restored["excluded_exact_designs"]),
            {"BASE": base_model, "COLOCATION": colocation_model},
            {"BASE": base, "COLOCATION": colocation},
        )
        assert not base.solve(assumptions=[1, -2, 3])
        assert base.solve(assumptions=[1, -2, 4])


def test_checkpoint_rejects_stale_inputs() -> None:
    state = {
        "schema": "RES-225-REPAIR-CHECKPOINT@1.1.0",
        "fingerprints": {"entry_head": "old"},
        "cores": [],
        "iteration_records": [],
        "exact_core_evidence": [],
        "excluded_exact_designs": [],
        "tested_repairs": [],
        "equality_records": [],
        "iteration": 0,
        "elapsed_seconds": 0.0,
        "oracle_calls": 0,
        "oracle_status_counts": {},
        "phase": "START",
    }
    with pytest.raises(ValueError, match="stale"):
        _validate_checkpoint(_checkpoint_bind(state), expected_fingerprints={"entry_head": "new"})


def test_global_wall_budget_writes_checkpoint_before_clean_pause(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = tmp_path / "external"
    root.mkdir()
    input_digest = "sha256:" + "a" * 64
    model_digests = {"BASE": "base-model", "COLOCATION": "colocation-model"}
    monkeypatch.setattr(res225_search, "_capture_current_design", lambda _root: ((), (), ()))
    monkeypatch.setattr(
        res225_search,
        "read_external_production_json",
        lambda *args, **kwargs: (SimpleNamespace(mutation_lineages=()), input_digest, 0),
    )
    monkeypatch.setattr(
        res225_search, "build_preservation_registry", lambda *args, **kwargs: ((), ())
    )
    monkeypatch.setattr(
        res225_search,
        "build_core_model",
        lambda *args, mode, **kwargs: SimpleNamespace(
            mode=mode,
            model_digest=model_digests[mode],
            clauses=(),
        ),
    )
    with pytest.raises(_RepairSearchPausedError):
        res225_search.run(root, max_wall_seconds=1e-9)
    monkeypatch.undo()

    fingerprints = {
        "entry_head": res225_search._ENTRY_HEAD,
        "private_input_digest": input_digest,
        "preservation_registry_digest": canonical_hash(()),
        "action_registry_digest": canonical_hash(()),
        "base_model_digest": model_digests["BASE"],
        "colocation_model_digest": model_digests["COLOCATION"],
        "candidate_count": "434",
        "retained_shingle_pair_count": "0",
    }
    checkpoint, _digest, _file_digest = _read_checkpoint(root, expected_fingerprints=fingerprints)
    assert checkpoint["phase"] == "PAUSED_WALL_TIME"
    assert checkpoint["LOWER_BOUND"] == 0
    assert checkpoint["UPPER_BOUND"] is None
    assert checkpoint["CORES_DISCOVERED"] == 0
    assert checkpoint["NO_GOODS"] == 0
    progress = capsys.readouterr().err
    for field in (
        "LOWER_BOUND=0",
        "UPPER_BOUND=NONE",
        "OPTIMALITY_GAP=NONE",
        "CURRENT_PHASE=PAUSED_WALL_TIME",
        "CHECKPOINT_DIGEST=",
    ):
        assert field in progress


def test_bounded_smoke_cli_keeps_materialization_disabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: dict[str, Any] = {}

    def fake_run(_root: Path, **kwargs: Any) -> tuple[dict[str, object], int]:
        calls.update(kwargs)
        return {"STATUS": "ABSTRACT_MINIMUM_READY"}, 434

    monkeypatch.setattr(res225_search, "run", fake_run)
    code = res225_search.main(
        [
            "--production-root",
            str(tmp_path / "external"),
            "--oracle-timeout-seconds",
            "60",
            "--max-iterations",
            "20",
            "--max-exact-variants-per-repair",
            "4",
            "--max-wall-seconds",
            "600",
        ]
    )
    assert code == 0
    assert calls["max_wall_seconds"] == 600
    assert calls["materialize"] is False
    assert "STATUS=ABSTRACT_MINIMUM_READY" in capsys.readouterr().out


def test_paused_search_has_a_clean_cli_exit(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def paused(*args: Any, **kwargs: Any) -> Any:
        raise _RepairSearchPausedError("wall budget reached")

    monkeypatch.setattr(res225_search, "run", paused)
    assert res225_search.main(["--max-wall-seconds", "600"]) == 0
    output = capsys.readouterr().out
    assert "STATUS=PAUSED" in output
    assert "CHECKPOINT=" in output


def test_progress_telemetry_contains_required_fields(capsys: pytest.CaptureFixture[str]) -> None:
    _emit_iteration(
        iteration=2,
        elapsed_seconds=3.5,
        cores_discovered=4,
        last_core_size=7,
        last_minimized_core_size=3,
        hitting_set_size=2,
        lower_bound=2,
        upper_bound=5,
        no_goods=7,
        best_repair_cardinality=None,
        oracle_calls=9,
        last_oracle_status="UNSAT",
        last_oracle_seconds=0.25,
        phase="CORE_GUIDED",
        checkpoint_digest="sha256:" + "f" * 64,
    )
    output = capsys.readouterr().err
    for field in (
        "ITERATION=2",
        "ELAPSED=3.500",
        "CORES_DISCOVERED=4",
        "LAST_CORE_SIZE=7",
        "LAST_MINIMIZED_CORE_SIZE=3",
        "CURRENT_HITTING_SET_SIZE=2",
        "LOWER_BOUND=2",
        "UPPER_BOUND=5",
        "OPTIMALITY_GAP=3",
        "BEST_REPAIR_CARDINALITY=NONE",
        "ORACLE_CALLS=9",
        "NO_GOODS=7",
        "LAST_ORACLE_STATUS=UNSAT",
        "LAST_ORACLE_SECONDS=0.250",
        "CURRENT_PHASE=CORE_GUIDED",
        "CHECKPOINT_DIGEST=sha256:" + "f" * 64,
    ):
        assert field in output


def test_lower_cardinality_crosscheck_rejects_under_cost_model() -> None:
    model = cast(
        CoreModel,
        SimpleNamespace(
            clauses=((1, 2),),
            release_variables={"a": 1, "b": 2},
            max_variable=2,
            model_digest="sha256:" + "0" * 64,
        ),
    )
    result, _digest = _independent_minimum_crosscheck(
        model,
        ("a", "b"),
        {"a": 1, "b": 1},
        1,
    )
    assert result["status"] == "INFEASIBLE"
    assert result["maximum_content_replacements"] == 0


def test_materialization_requires_abstract_base_and_colocation_feasible(tmp_path: Path) -> None:
    blocked_receipt = SimpleNamespace(
        base_status="FEASIBLE",
        colocation_status="INFEASIBLE",
        status="BLOCKED",
        canonical_self_reduction_status="NOT_RUN",
        canonical_witness_digest=None,
    )
    with pytest.raises(_RepairSearchBlockedError, match="abstract"):
        _require_abstract_feasible(blocked_receipt)
    with pytest.raises(_RepairSearchBlockedError, match="abstract"):
        _make_materialization_plan(
            production_root=tmp_path / "external",
            selected_action_ids=(),
            actions=(),
            assumptions=(),
            target_parent_by_action={},
            abstract_receipt=blocked_receipt,
            selected_repair_digest="repair",
            minimum_evidence_digest="minimum",
            iteration=1,
        )
