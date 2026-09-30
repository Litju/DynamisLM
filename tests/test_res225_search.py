from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
import scripts.res225_repair as res225_search
from pysat.solvers import Solver  # type: ignore[import-untyped]
from scripts.res225_repair import (
    _append_unique_core,
    _checkpoint_bind,
    _core_hit_set_is_sat,
    _emit_iteration,
    _exact_state,
    _exact_variant_exclusion_record,
    _exact_variant_nogood_clause,
    _hitman_from_cores,
    _hitman_solution,
    _independent_minimum_crosscheck,
    _make_materialization_plan,
    _read_checkpoint,
    _RepairSearchBlockedError,
    _replay_exact_exclusions,
    _require_abstract_feasible,
    _solver_core_ids,
    _validate_checkpoint,
    _write_checkpoint,
)

from dynamislm.benchmark.production import _canonical_split_ranks_glucose, _ExactConstraint
from dynamislm.benchmark.res225_repair import (
    CoreModel,
    CoreSolveTimeoutError,
    shrink_unsat_core,
    solve_assumptions_limited,
)


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


def test_exact_variant_checks_only_the_sat_selected_target_map(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []
    feasible_receipt = SimpleNamespace(
        status="FEASIBLE",
        base_status="FEASIBLE",
        colocation_status="FEASIBLE",
        canonical_self_reduction_status="PASS",
        canonical_witness_digest="sha256:" + "1" * 64,
    )

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

    calls.clear()

    def fake_unknown(
        _commitments: tuple[object, ...],
        _pairs: tuple[tuple[str, str], ...],
        **kwargs: Any,
    ) -> Any:
        calls.append(kwargs)
        return SimpleNamespace(
            status="BLOCKED",
            base_status="UNKNOWN",
            colocation_status="UNKNOWN",
        )

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
        "cores": cores,
        "initial_core_count": 0,
        "iteration_records": [{"iteration": 3}],
        "exact_core_evidence": [],
        "excluded_exact_designs": [exclusion],
        "tested_repairs": [],
        "equality_records": [],
        "variant_counts": {},
        "iteration": 3,
        "elapsed_seconds": 12.5,
        "oracle_calls": 5,
        "oracle_status_counts": {"SAT": 2, "UNSAT": 3},
        "phase": "CORE_ADDED",
    }
    production_root = tmp_path / "external"
    production_root.mkdir()
    _write_checkpoint(production_root, state)
    restored, _digest = _read_checkpoint(
        production_root,
        expected_fingerprints=fingerprints,
    )
    restored_cores = cast(list[dict[str, Any]], restored["cores"])
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
        "schema": "RES-225-REPAIR-CHECKPOINT@1.0.0",
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


def test_progress_telemetry_contains_required_fields(capsys: pytest.CaptureFixture[str]) -> None:
    _emit_iteration(
        iteration=2,
        elapsed_seconds=3.5,
        cores_discovered=4,
        last_core_size=7,
        last_minimized_core_size=3,
        hitting_set_size=2,
        best_repair_cardinality=None,
        oracle_calls=9,
        last_oracle_status="UNSAT",
        last_oracle_seconds=0.25,
        phase="CORE_GUIDED",
    )
    output = capsys.readouterr().err
    for field in (
        "ITERATION=2",
        "ELAPSED=3.500",
        "CORES_DISCOVERED=4",
        "LAST_CORE_SIZE=7",
        "LAST_MINIMIZED_CORE_SIZE=3",
        "CURRENT_HITTING_SET_SIZE=2",
        "BEST_REPAIR_CARDINALITY=NONE",
        "ORACLE_CALLS=9",
        "LAST_ORACLE_STATUS=UNSAT",
        "LAST_ORACLE_SECONDS=0.250",
        "CURRENT_PHASE=CORE_GUIDED",
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
