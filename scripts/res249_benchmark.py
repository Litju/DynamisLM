"""Run the private RES-249 abstract A/B/C redesign benchmark.

Every phase writes canonical private artifacts outside Git and can resume. The
repository receives only aggregate metrics and digests. No candidate content is
authored, no split membership is persisted, and production authoring inputs are
read-only (their hashes are re-checked around the baseline capture).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import resource
import shutil
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict
from functools import partial
from pathlib import Path
from typing import Any

from dynamislm.benchmark import res249_redesign as redesign
from dynamislm.benchmark.production import _FeasibilityCluster
from dynamislm.benchmark.production_store import DEFAULT_PRODUCTION_ROOT
from dynamislm.benchmark.res249_redesign import (
    AbstractProductionDesign,
    ExactModel,
    SealedRedesignInputs,
    build_exact_models,
    build_redesign,
    edit_surface,
    protected_capacity,
    protected_split_ranks,
    scientific_gate,
    solve_exact,
    validate_witness,
)
from dynamislm.serialization import canonical_hash, canonical_json, from_canonical_json
from scripts.res224_probes import _pb_model_bytes

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
ENTRY_HEAD = "30851a3b57458ef856584625fac8bb45f24ec7eb"
PRIVATE_DIR = "production/diagnostics/RES-249"
SEALED_PATH = f"{PRIVATE_DIR}/sealed-baseline.private.json"
BENCHMARK_RUNS = 5
SAT_TIME_LIMIT_SECONDS = 600.0
PROBE_TIME_LIMIT_SECONDS = 60.0
RUN_SAT_TIME_LIMIT_SECONDS = 60.0
DESIGNS: tuple[redesign.Strategy, ...] = redesign.STRATEGIES
WATCHED_PRIVATE_INPUTS = (
    "production/authoring_plan/private_inputs.json",
    "production/diagnostics/RES-223-repair-plan.private.json",
)
BASELINE_EXPECTED_R1_VIOLATIONS = 14
RES224_BASE_CNF_DIGEST = "sha256:c9f420c2dc04b8f032ddfcc80a6b38ce0340b4847637657176b2df3844cb691b"
RES224_COLOCATION_CNF_DIGEST = (
    "sha256:6691fd2c3fff42f61248275deaa0f3edece6e883326e7e7acbb35940b810b920"
)


def _progress(message: str) -> None:
    print(f"[RES-249 {time.strftime('%H:%M:%S')}] {message}", file=sys.stderr, flush=True)


def _sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _write_private(path: Path, content: bytes) -> str:
    """Atomic 0600 write; returns the file digest."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return _sha256(content)


def _write_record(root: Path, relative: str, record: dict[str, Any]) -> str:
    _assert_no_membership(record)
    payload = (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode()
    return _write_private(root / relative, payload)


def _read_record(root: Path, relative: str) -> dict[str, Any] | None:
    path = root / relative
    if not path.exists():
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"RES-249 private record {relative} is malformed")
    return value


_MEMBERSHIP_KEYS = frozenset({"ranks", "split_ranks", "split_membership", "assignment", "witness"})


def _assert_no_membership(value: object) -> None:
    """Fail closed if a private record would persist split membership."""

    if isinstance(value, dict):
        for key, item in value.items():
            if key in _MEMBERSHIP_KEYS:
                raise ValueError("RES-249 refuses to persist split membership")
            _assert_no_membership(item)
    elif isinstance(value, list | tuple):
        for item in value:
            _assert_no_membership(item)


def _peak_rss_mb() -> float:
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0, 1)


# ---------------------------------------------------------------------------
# Phase 0: sealed baseline
# ---------------------------------------------------------------------------


def capture_sealed_baseline(production_root: Path) -> SealedRedesignInputs:
    from scripts.res225_repair import _capture_current_design

    before = {
        path: _sha256((production_root / path).read_bytes()) for path in WATCHED_PRIVATE_INPUTS
    }
    _packets, commitments, pairs = _capture_current_design(production_root)
    after = {
        path: _sha256((production_root / path).read_bytes()) for path in WATCHED_PRIVATE_INPUTS
    }
    if before != after:
        raise RuntimeError("RES-249 baseline capture changed private authoring inputs")
    return redesign.seal_redesign_inputs(tuple(commitments), tuple(pairs))


def load_or_seal(production_root: Path, *, expected: str | None = None) -> SealedRedesignInputs:
    path = production_root / SEALED_PATH
    if path.exists():
        sealed = from_canonical_json(path.read_text(encoding="utf-8"), SealedRedesignInputs)
        rebuilt = redesign.seal_redesign_inputs(sealed.commitments, sealed.colocation_pairs)
        if rebuilt.authority_fingerprint != sealed.authority_fingerprint:
            raise ValueError("RES-249 private sealed baseline fingerprint does not recheck")
    else:
        _progress("capturing sealed baseline from production authoring (read-only)")
        sealed = capture_sealed_baseline(production_root)
        _write_private(path, canonical_json(sealed).encode("utf-8"))
    if expected is not None and sealed.authority_fingerprint != expected:
        raise ValueError("RES-249 sealed authority fingerprint is stale")
    return sealed


# ---------------------------------------------------------------------------
# Independent PB/CNF + Glucose crosscheck
# ---------------------------------------------------------------------------


def _drat_trim() -> str | None:
    for candidate in (
        shutil.which("drat-trim"),
        "/tmp/dynamislm-drat-trim/drat-trim",
        "/tmp/res225-drat-trim/drat-trim",
    ):
        if candidate and Path(candidate).is_file() and os.access(candidate, os.X_OK):
            return candidate
    return None


def independent_sat(
    model: ExactModel,
    *,
    witness: tuple[int, ...] | None = None,
    time_limit: float | None = None,
    proof_dir: Path | None = None,
    label: str = "",
) -> dict[str, Any]:
    """Independent PB/CNF (RES-224 encoder) + Glucose 4 evidence for one model.

    ``witness_model_check`` asserts a CP-SAT split assignment as assumptions on
    the independently encoded CNF; SAT certifies the assignment is a model of
    the independent encoding. ``result`` is a blind Glucose search that never
    sees the witness; UNSAT results are DRAT-checked when ``proof_dir`` is set.
    """

    from pysat.solvers import Solver  # type: ignore[import-untyped]

    limit = SAT_TIME_LIMIT_SECONDS if time_limit is None else time_limit
    started = time.monotonic()
    cnf_bytes, variable_map, clauses, max_var = _pb_model_bytes(
        len(model.components), model.constraints
    )
    record: dict[str, Any] = {
        "model_kind": model.kind,
        "semantic_model_digest": model.model_digest,
        "cnf_digest": _sha256(cnf_bytes),
        "cnf_variables": max_var,
        "cnf_clauses": len(clauses),
        "cnf_bytes": len(cnf_bytes),
        "encode_seconds": round(time.monotonic() - started, 4),
        "blind_time_limit_seconds": limit,
    }
    if witness is not None:
        check_started = time.monotonic()
        validate_witness(model, witness)
        with Solver(name="g4", bootstrap_with=clauses) as checker:
            accepted = checker.solve(
                assumptions=[variable_map[index][rank] for index, rank in enumerate(witness)]
            )
        record["witness_model_check"] = "SAT" if accepted else "UNSAT"
        record["witness_check_seconds"] = round(time.monotonic() - check_started, 4)
        record["witness_digest"] = canonical_hash(("RES-249-WITNESS", model.model_digest, witness))
    solve_started = time.monotonic()
    with Solver(name="g4", bootstrap_with=clauses, with_proof=proof_dir is not None) as solver:
        timer = threading.Timer(limit, solver.interrupt)
        timer.daemon = True
        timer.start()
        try:
            result = solver.solve_limited(expect_interrupt=True)
        finally:
            timer.cancel()
        record["sat_seconds"] = round(time.monotonic() - solve_started, 4)
        if result is True:
            positive = {literal for literal in solver.get_model() or () if literal > 0}
            ranks = []
            for row in variable_map:
                chosen = [rank for rank, variable in enumerate(row) if variable in positive]
                if len(chosen) != 1:
                    raise RuntimeError("independent SAT witness is not a complete assignment")
                ranks.append(chosen[0])
            validate_witness(model, tuple(ranks))
            record["result"] = "SAT"
            record["blind_witness_validated"] = True
        elif result is False:
            record["result"] = "UNSAT"
            record["proof_check"] = "NOT_REQUESTED"
            if proof_dir is not None:
                proof = solver.get_proof() or []
                proof_bytes = ("\n".join(proof) + "\n").encode("ascii")
                cnf_path = proof_dir / f"{label}.cnf"
                proof_path = proof_dir / f"{label}.drup"
                _write_private(cnf_path, cnf_bytes)
                record["proof_digest"] = _write_private(proof_path, proof_bytes)
                checker_path = _drat_trim()
                if checker_path is None:
                    record["proof_check"] = "CHECKER_UNAVAILABLE"
                else:
                    checked = subprocess.run(
                        [checker_path, str(cnf_path), str(proof_path)],
                        check=False,
                        capture_output=True,
                        timeout=max(limit, 1800.0),
                    )
                    verified = b"s VERIFIED" in checked.stdout
                    record["proof_check"] = (
                        "PASS" if checked.returncode == 0 and verified else "FAIL"
                    )
                    record["proof_checker_digest"] = _sha256(Path(checker_path).read_bytes())
        else:
            record["result"] = "UNKNOWN"
    return record


def crosscheck(cp_status: str, sat: dict[str, Any]) -> str:
    """PASS iff the decisive result is independently certified and nothing disagrees."""

    blind = sat["result"]
    if cp_status == "FEASIBLE":
        if blind == "UNSAT" or sat.get("witness_model_check") != "SAT":
            return "FAIL"
        return "PASS"
    if blind == "SAT":
        return "FAIL" if cp_status == "INFEASIBLE" else "UNKNOWN"
    if blind == "UNSAT":
        return "PASS" if sat.get("proof_check") == "PASS" else "UNVERIFIED"
    return "UNKNOWN"


def exact_status(cp_status: str, sat: dict[str, Any]) -> str:
    if crosscheck(cp_status, sat) == "PASS":
        return "FEASIBLE" if cp_status == "FEASIBLE" else "INFEASIBLE"
    if cp_status == "INFEASIBLE" and sat["result"] != "SAT":
        return "INFEASIBLE"
    return "UNKNOWN"


# ---------------------------------------------------------------------------
# Common validator (one code path for every design)
# ---------------------------------------------------------------------------


def _component_sizes(components: tuple[_FeasibilityCluster, ...]) -> dict[str, int]:
    counts = Counter(component.size for component in components)
    return {str(size): counts[size] for size in sorted(counts)}


def _mutation_block_sizes(design: AbstractProductionDesign, model: ExactModel) -> dict[str, int]:
    roots = {lineage.root_candidate_id for lineage in design.lineages}
    sizes = Counter(
        component.size
        for component in model.components
        if roots & {item.candidate_id for item in component.items}
    )
    return {str(size): sizes[size] for size in sorted(sizes)}


def _capacity_summary(report: redesign.CapacityReport) -> dict[str, Any]:
    values = sorted(item.vh_eligible_components for item in report.cells)
    return {
        "r1_violating_cells": [":".join(cell) for cell in report.violating_cells],
        "r1_violation_count": len(report.violating_cells),
        "min_vh_eligible_components": values[0],
        "median_vh_eligible_components": statistics.median(values),
        "max_vh_eligible_components": values[-1],
        "cells_with_exactly_2": sum(value == 2 for value in values),
        "cells_with_ge_3": sum(value >= 3 for value in values),
        "capacity_matrix_digest": report.matrix_digest,
        "violations": [
            {
                "cell": ":".join(item.cell),
                "vh_eligible_components": item.vh_eligible_components,
                "protected_matching": item.protected_matching,
                "covering_components": item.covering_components,
                "eligible_component_keys": list(item.component_keys),
                "blocking_root_ids": list(item.blocking_root_ids),
            }
            for item in report.cells
            if item.cell in report.violating_cells
        ],
    }


def validate_design(
    sealed: SealedRedesignInputs,
    design: AbstractProductionDesign,
    *,
    proof_dir: Path | None,
) -> dict[str, Any]:
    """Identical gates for CURRENT, A, B, and C."""

    timings: dict[str, float] = {}
    gate = scientific_gate(sealed, design)
    roots = {lineage.root_candidate_id for lineage in design.lineages}
    base_capacity = protected_capacity(design.commitments, root_ids=roots)
    colocation_capacity = protected_capacity(
        design.commitments, design.colocation_pairs, root_ids=roots
    )
    base, colocation = build_exact_models(design.commitments, design.colocation_pairs)
    record: dict[str, Any] = {
        "strategy": design.strategy,
        "design_digest": design.design_digest,
        "commitments_digest": design.commitments_digest,
        "authority_fingerprint": design.authority_fingerprint,
        "scientific_gate": gate.status,
        "scientific_failures": list(gate.failures),
        "origin_counts": dict(redesign.origin_counts(design.commitments)),
        "lineages": len(design.lineages),
        "children_per_lineage": sorted({len(item.child_candidate_ids) for item in design.lineages}),
        "operator_counts": dict(Counter(item.operator_id for item in design.lineages)),
        "edit_surface": asdict(edit_surface(sealed, design)),
        "r1_base": _capacity_summary(base_capacity),
        "r1_colocation": _capacity_summary(colocation_capacity),
        "r1_gate": "PASS"
        if not base_capacity.violating_cells and not colocation_capacity.violating_cells
        else "FAIL",
        "objective_trace": [list(item) for item in design.objective_trace],
    }
    for model in (base, colocation):
        key = model.kind.lower()
        record[f"{key}_components"] = len(model.components)
        record[f"{key}_component_sizes"] = _component_sizes(model.components)
        record[f"{key}_max_component_size"] = max(item.size for item in model.components)
        record[f"{key}_mutation_block_sizes"] = _mutation_block_sizes(design, model)
        record[f"{key}_model_digest"] = model.model_digest
        cp = solve_exact(model)
        timings[f"{key}_cpsat_seconds"] = cp.wall_seconds
        record[f"{key}_cpsat"] = {
            "status": cp.status,
            "wall_seconds": round(cp.wall_seconds, 4),
            "deterministic_time": round(cp.deterministic_time, 4),
            "model_variables": cp.variables,
            "model_constraints": cp.constraints,
            "witness_digest": cp.witness_digest,
        }
        sat = independent_sat(
            model,
            witness=cp.ranks,
            proof_dir=proof_dir if cp.status != "FEASIBLE" else None,
            label=f"{design.strategy}-{model.kind}",
        )
        record[f"{key}_independent"] = sat
        record[f"{key}_crosscheck"] = crosscheck(cp.status, sat)
        record[f"{key}_status"] = exact_status(cp.status, sat)
    record["independent_crosscheck"] = (
        "PASS"
        if record["base_crosscheck"] == "PASS" and record["colocation_crosscheck"] == "PASS"
        else "FAIL"
    )
    record["hard_gates_pass"] = bool(
        gate.status == "PASS"
        and record["r1_gate"] == "PASS"
        and record["base_status"] == "FEASIBLE"
        and record["colocation_status"] == "FEASIBLE"
        and record["independent_crosscheck"] == "PASS"
    )
    return record


# ---------------------------------------------------------------------------
# Repeated deterministic runs (each in a fresh subprocess)
# ---------------------------------------------------------------------------


def run_once(sealed: SealedRedesignInputs, strategy: redesign.Strategy) -> dict[str, Any]:
    started = time.monotonic()
    design = build_redesign(strategy, sealed, expected_fingerprint=sealed.authority_fingerprint)
    build_seconds = time.monotonic() - started
    if design is None:
        return {"strategy": strategy, "status": "NO_DESIGN", "build_seconds": build_seconds}
    base, colocation = build_exact_models(design.commitments, design.colocation_pairs)
    record: dict[str, Any] = {
        "strategy": strategy,
        "status": "BUILT",
        "build_seconds": round(build_seconds, 4),
        "design_digest": design.design_digest,
        "selection_digest": canonical_hash(design.plan),
        "commitment_inventory_digest": design.commitments_digest,
        "base_model_digest": base.model_digest,
        "colocation_model_digest": colocation.model_digest,
    }
    for model in (base, colocation):
        key = model.kind.lower()
        cp = solve_exact(model)
        sat = independent_sat(model, witness=cp.ranks, time_limit=RUN_SAT_TIME_LIMIT_SECONDS)
        record[f"{key}_status"] = cp.status
        record[f"{key}_seconds"] = round(cp.wall_seconds, 4)
        record[f"{key}_deterministic_time"] = round(cp.deterministic_time, 4)
        record[f"{key}_pb_encode_seconds"] = sat["encode_seconds"]
        record[f"{key}_sat_seconds"] = sat["sat_seconds"]
        record[f"{key}_sat_result"] = sat["result"]
        record[f"{key}_cnf_digest"] = sat["cnf_digest"]
        record[f"{key}_witness_result"] = sat.get("witness_model_check", "NO_WITNESS")
        record[f"{key}_witness_check_seconds"] = sat.get("witness_check_seconds", 0.0)
        record[f"{key}_crosscheck"] = crosscheck(cp.status, sat)
    record["end_to_end_seconds"] = round(time.monotonic() - started, 4)
    record["peak_rss_mb"] = _peak_rss_mb()
    return record


def _spawn_runs(
    production_root: Path, strategy: str, fingerprint: str, runs: int
) -> dict[str, Any]:
    return {"runs": [_spawn_run(production_root, strategy, fingerprint) for _ in range(runs)]}


def _repeated_component_probes(model: ExactModel) -> dict[str, Any]:
    return {"first": component_probes(model), "second": component_probes(model)}


def _spawn_run(production_root: Path, strategy: str, fingerprint: str) -> dict[str, Any]:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.res249_benchmark",
            "--production-root",
            str(production_root),
            "--worker",
            strategy,
            "--expected-fingerprint",
            fingerprint,
        ],
        cwd=_REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    record: dict[str, Any] = json.loads(completed.stdout.strip().splitlines()[-1])
    return record


def _summary(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    return {
        "min": round(ordered[0], 4),
        "median": round(statistics.median(ordered), 4),
        "max": round(ordered[-1], 4),
    }


# ---------------------------------------------------------------------------
# Resilience and perturbations on the COLOCATION model (forced-split CP-SAT)
# ---------------------------------------------------------------------------


class ForcingOracle:
    """Feasibility of one exact model under forced/forbidden splits, with witness reuse.

    Every query uses the common CP-SAT configuration; each witness is validated
    in memory and only its digest is retained.
    """

    def __init__(self, model: ExactModel) -> None:
        self.model = model
        self.witnesses: dict[str, tuple[int, ...]] = {}
        self.queries = 0

    def query(
        self,
        fixed: dict[int, int] | None = None,
        forbidden: dict[int, tuple[int, ...]] | None = None,
    ) -> str:
        self.queries += 1
        result = solve_exact(self.model, fixed=fixed, forbidden=forbidden)
        if result.ranks is not None:
            self.witnesses.setdefault(canonical_hash(result.ranks), result.ranks)
        return result.status

    def forced(self, index: int, rank: int) -> str:
        if any(witness[index] == rank for witness in self.witnesses.values()):
            return "FEASIBLE"
        return self.query(fixed={index: rank})

    def excluded_from_protected(self, index: int) -> str:
        if any(witness[index] == 0 for witness in self.witnesses.values()):
            return "FEASIBLE"
        return self.query(fixed={index: 0})

    def close(self) -> None:
        self.witnesses.clear()


def _cell_components(model: ExactModel) -> dict[tuple[str, str], list[int]]:
    eligible: dict[tuple[str, str], list[int]] = {}
    for index, component in enumerate(model.components):
        if not protected_split_ranks(component):
            continue
        for item in component.items:
            if redesign.item_covers_own_cell(item):
                eligible.setdefault((item.capability_id, item.benchmark_family), []).append(index)
    return eligible


def resilience(model: ExactModel) -> dict[str, Any]:
    oracle = ForcingOracle(model)
    try:
        if oracle.query() != "FEASIBLE":
            return {"status": "NOT_FEASIBLE"}
        by_cell = _cell_components(model)
        matrix: list[tuple[str, int, int, int]] = []
        unknown = 0
        for cell in redesign.all_cells():
            for rank in redesign.PROTECTED_RANKS:
                forceable = 0
                for index in by_cell.get(cell, []):
                    if rank not in protected_split_ranks(model.components[index]):
                        continue
                    status = oracle.forced(index, rank)
                    forceable += status == "FEASIBLE"
                    unknown += status == "UNKNOWN"
                matrix.append((":".join(cell), rank, len(by_cell.get(cell, [])), forceable))
        counts = sorted(item[3] for item in matrix)
        failure_fatal: list[str] = []
        eligible_indices = sorted({index for values in by_cell.values() for index in values})
        for index in eligible_indices:
            status = oracle.excluded_from_protected(index)
            if status != "FEASIBLE":
                failure_fatal.append(model.components[index].cluster_key)
        quartiles = statistics.quantiles(counts, n=4, method="inclusive")
        low = sorted({item[0] for item in matrix if item[3] <= 2})
        return {
            "status": "COMPLETE" if unknown == 0 else "PARTIAL_UNKNOWN",
            "forceable_min": counts[0],
            "forceable_p25": quartiles[0],
            "forceable_median": quartiles[1],
            "forceable_p75": quartiles[2],
            "forceable_max": counts[-1],
            "forceable_eq1": sum(value == 1 for value in counts),
            "forceable_eq2": sum(value == 2 for value in counts),
            "forceable_ge3": sum(value >= 3 for value in counts),
            "forceable_eq0": sum(value == 0 for value in counts),
            "unknown_queries": unknown,
            "matrix_digest": canonical_hash(tuple(matrix)),
            "distinct_witnesses": len(oracle.witnesses),
            "oracle_queries": oracle.queries,
            "single_component_failure_fatal_count": len(failure_fatal),
            "single_component_failure_fatal_digest": canonical_hash(tuple(failure_fatal)),
            "low_redundancy_cells": low,
            "eligible_components_probed": len(eligible_indices),
        }
    finally:
        oracle.close()


def component_probes(model: ExactModel) -> dict[str, Any]:
    """Perturbations 1 and 4 as forced splits on the abstract model; no data changes."""

    oracle = ForcingOracle(model)
    try:
        if oracle.query() != "FEASIBLE":
            return {"status": "NOT_FEASIBLE"}
        by_cell = _cell_components(model)
        lowest = min(
            redesign.all_cells(),
            key=lambda cell: (len(by_cell.get(cell, [])), cell),
        )
        candidates = sorted(by_cell.get(lowest, []), key=lambda i: model.components[i].cluster_key)
        removed = candidates[0]
        removal = oracle.query(fixed={removed: 0})
        forced_rank = 1
        forced = oracle.query(fixed={removed: forced_rank})
        return {
            "status": "COMPLETE",
            "lowest_redundancy_cell": ":".join(lowest),
            "lowest_redundancy_eligible_components": len(candidates),
            "remove_low_redundancy_component": removal,
            "removed_component_key": model.components[removed].cluster_key,
            "force_protected_split_choice": forced,
            "forced_split": "FROZEN_VALIDATION",
        }
    finally:
        oracle.close()


# ---------------------------------------------------------------------------
# Engineering complexity (objective counts)
# ---------------------------------------------------------------------------


def complexity(
    strategy: str,
    sealed: SealedRedesignInputs,
    design: AbstractProductionDesign | None,
) -> dict[str, Any]:
    """Objective implementation metrics for eventually materializing a design."""

    families: set[str] = set()
    if design is not None:
        surface = edit_surface(sealed, design)
        if surface.semantic_root_identities_changed:
            families.add("ROOT_RESELECTION")
        if surface.semantic_slots_reassigned:
            families.add("SEMANTIC_CELL_REASSIGNMENT")
        if surface.semantic_slots_rebound:
            families.add("SEMANTIC_TEMPLATE_REBIND")
        if surface.root_contents_replaced:
            families.add("ROOT_CONTENT_REPLACEMENT")
    # Materialization touch-points per family in the production authoring path.
    touch_points = {
        "ROOT_RESELECTION": ("production_authoring._mutation_lineage_specs",),
        "SEMANTIC_CELL_REASSIGNMENT": (
            "production_authoring._semantic_slot_specs",
            "production_authoring._expert_batch_records",
            "production_authoring._author_semantic_packets",
        ),
        "SEMANTIC_TEMPLATE_REBIND": ("production_authoring._expert_batch_records",),
        "ROOT_CONTENT_REPLACEMENT": (
            "production_authoring._expert_batch_records",
            "production_authoring._author_mutation_packets",
        ),
    }
    touched = sorted({item for family in families for item in touch_points[family]})
    solver_models = {"CURRENT": 0, "A": 1, "B": 1, "C": 2}[strategy]
    new_ids = "SEMANTIC_CELL_REASSIGNMENT" in families
    if strategy == "CURRENT":
        level = "NOT_APPLICABLE"
    elif len(families) <= 1 and solver_models <= 1 and not new_ids:
        level = "LOW"
    elif len(families) <= 2 and solver_models <= 2:
        level = "MEDIUM"
    else:
        level = "HIGH"
    return {
        "action_families_used": sorted(families),
        "action_family_count": len(families),
        "production_functions_touched": touched,
        "production_touch_points": len(touched),
        "solver_models": solver_models,
        "mutable_lifecycle_states": len(families),
        "new_semantic_candidate_ids": new_ids,
        "operational_complexity": level,
    }


# ---------------------------------------------------------------------------
# Strict selection hierarchy (no weighted score)
# ---------------------------------------------------------------------------

_COMPLEXITY_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}


def _compare(left: tuple[float, ...], right: tuple[float, ...]) -> str:
    """Pareto comparison where larger is better in every coordinate."""

    if left == right:
        return "EQUAL"
    if all(a >= b for a, b in zip(left, right, strict=True)):
        return "LEFT"
    if all(b >= a for a, b in zip(left, right, strict=True)):
        return "RIGHT"
    return "TRADE_OFF"


def criterion_vectors(row: dict[str, Any]) -> list[tuple[str, tuple[float, ...]]]:
    res = row.get("resilience") or {}
    return [
        ("4_LOWER_SCIENTIFIC_EDIT_SURFACE", (-row["total_content_changes"],)),
        (
            "5_STRONGER_ALLOCATION_RESILIENCE",
            (
                res.get("forceable_min", -1),
                res.get("forceable_median", -1),
                -res.get("forceable_eq1", 10**6),
                -res.get("single_component_failure_fatal_count", 10**6),
            ),
        ),
        (
            "6_STRONGER_DETERMINISM_RESTART_RELIABILITY",
            (float(row["determinism_pass"]), float(row["restart_idempotent"])),
        ),
        (
            "7_LOWER_RUNTIME_RESOURCE_COST",
            (-row["end_to_end_median_seconds"], -row["peak_rss_mb"]),
        ),
        (
            "8_LOWER_IMPLEMENTATION_COMPLEXITY",
            (-_COMPLEXITY_ORDER.get(row["engineering_complexity"], 3),),
        ),
    ]


def select_design(rows: dict[str, dict[str, Any]]) -> tuple[str, str, list[str]]:
    trace: list[str] = []
    passing = []
    for name in ("A", "B", "C"):
        row = rows[name]
        failed = [
            label
            for label, ok in (
                ("1_SCIENTIFIC_CORRECTNESS", row["scientific_gate"] == "PASS"),
                ("2_STRUCTURAL_R1", row["r1_gate"] == "PASS"),
                (
                    "3_BASE_COLOCATION_CROSSCHECK",
                    row["base_status"] == "FEASIBLE"
                    and row["colocation_status"] == "FEASIBLE"
                    and row["independent_crosscheck"] == "PASS",
                ),
            )
            if not ok
        ]
        if failed:
            trace.append(f"{name}:ELIMINATED_AT={failed[0]}")
        else:
            passing.append(name)
    if not passing:
        return "HUMAN_DECISION_REQUIRED", "NO_DESIGN_PASSES_HARD_GATES_1_TO_3", trace
    if len(passing) == 1:
        return passing[0], f"ONLY_{passing[0]}_PASSES_HARD_GATES_1_TO_3;" + ";".join(trace), trace
    remaining = passing
    for criterion, _vector in criterion_vectors(rows[remaining[0]]):
        vectors = {name: dict(criterion_vectors(rows[name]))[criterion] for name in remaining}
        best = [
            name
            for name in remaining
            if all(
                _compare(vectors[name], vectors[other]) in {"LEFT", "EQUAL"} for other in remaining
            )
        ]
        if not best:
            trace.append(f"{criterion}:TRADE_OFF:{','.join(remaining)}")
            return "HUMAN_DECISION_REQUIRED", f"TRADE_OFF_AT_{criterion}", trace
        if len(best) < len(remaining):
            trace.append(f"{criterion}:DOMINATES:{','.join(best)}")
        remaining = best
        if len(remaining) == 1:
            dominated = sorted(set(passing) - set(remaining))
            return (
                remaining[0],
                f"{remaining[0]}_PASSES_GATES_1_TO_3_AND_DOMINATES_"
                f"{'_'.join(dominated)}_AT_{criterion}",
                trace,
            )
        trace.append(f"{criterion}:EQUAL:{','.join(remaining)}")
    return "HUMAN_DECISION_REQUIRED", "EQUAL_ON_ALL_CRITERIA", trace


# ---------------------------------------------------------------------------
# Phase driver
# ---------------------------------------------------------------------------


class _Phases:
    def __init__(self, production_root: Path) -> None:
        self.root = production_root
        self.private = production_root / PRIVATE_DIR
        self.private.mkdir(parents=True, exist_ok=True)
        self.sealed = load_or_seal(production_root)
        self.fingerprint = self.sealed.authority_fingerprint

    def cached(self, name: str, compute: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        relative = f"{PRIVATE_DIR}/{name}.private.json"
        existing = _read_record(self.root, relative)
        if existing is not None and existing.get("authority_fingerprint") == self.fingerprint:
            _progress(f"resume: {name}")
            return existing
        _progress(f"compute: {name}")
        record = compute()
        record["authority_fingerprint"] = self.fingerprint
        _write_record(self.root, relative, record)
        return record

    def design(self, strategy: redesign.Strategy) -> AbstractProductionDesign | None:
        path = self.private / f"design-{strategy}.private.json"
        if path.exists():
            design = from_canonical_json(path.read_text(encoding="utf-8"), AbstractProductionDesign)
            if design.authority_fingerprint != self.fingerprint:
                raise ValueError("RES-249 private design binds a stale authority fingerprint")
            return design
        built = build_redesign(
            strategy, self.sealed, expected_fingerprint=self.fingerprint, progress=_progress
        )
        if built is not None:
            _write_private(path, canonical_json(built).encode("utf-8"))
        return built


def _baseline_record(phases: _Phases) -> dict[str, Any]:
    from dynamislm.benchmark.production_authoring import (
        _mutation_lineage_specs,
        _semantic_slot_specs,
    )

    sealed = phases.sealed
    prefix_roots = sorted(
        item.parent_candidate_id for item in _mutation_lineage_specs(_semantic_slot_specs())
    )
    capacity = protected_capacity(
        sealed.commitments, sealed.colocation_pairs, root_ids=sealed.root_ids
    )
    base, colocation = build_exact_models(sealed.commitments, sealed.colocation_pairs)
    base_cnf = _sha256(_pb_model_bytes(len(base.components), base.constraints)[0])
    colocation_cnf = _sha256(_pb_model_bytes(len(colocation.components), colocation.constraints)[0])
    return {
        "origin_vector": dict(redesign.origin_counts(sealed.commitments)),
        "mutation_lineages": len(sealed.lineages),
        "root_count": len(sealed.root_ids),
        "root_ids_digest": canonical_hash(tuple(sorted(sealed.root_ids))),
        "prefix_selector_reproduces_roots": sorted(sealed.root_ids) == prefix_roots,
        "r1_violating_cells": [":".join(cell) for cell in capacity.violating_cells],
        "r1_violation_count": len(capacity.violating_cells),
        "r1_matches_audit_count": len(capacity.violating_cells) == BASELINE_EXPECTED_R1_VIOLATIONS,
        "colocation_pairs": len(sealed.colocation_pairs),
        "base_cnf_digest": base_cnf,
        "colocation_cnf_digest": colocation_cnf,
        "base_cnf_matches_res224": base_cnf == RES224_BASE_CNF_DIGEST,
        "colocation_cnf_matches_res224": colocation_cnf == RES224_COLOCATION_CNF_DIGEST,
        "comparability_root_upper_bound": redesign.operator_root_upper_bounds(sealed),
    }


def _reliability(phases: _Phases, strategy: redesign.Strategy) -> dict[str, Any]:
    sealed = phases.sealed
    record: dict[str, Any] = {}
    try:
        build_redesign(strategy, sealed, expected_fingerprint="sha256:" + "0" * 64)
        record["stale_fingerprint_rejected"] = False
    except ValueError:
        record["stale_fingerprint_rejected"] = True

    def interrupt(message: str) -> None:
        if ":optimize:" in message:
            raise redesign.RedesignInterruptedError(message)

    try:
        build_redesign(strategy, sealed, progress=interrupt)
        record["interruption_observed"] = strategy == "CURRENT"
    except redesign.RedesignInterruptedError:
        record["interruption_observed"] = True
    restarted = build_redesign(strategy, sealed)
    stored = phases.design(strategy)
    record["restart_digest_unchanged"] = (
        restarted is not None
        and stored is not None
        and restarted.design_digest == stored.design_digest
    )
    if stored is not None:
        _base, colocation = build_exact_models(stored.commitments, stored.colocation_pairs)
        bounded = solve_exact(colocation, deterministic_time=1e-6)
        record["bounded_timeout_status"] = bounded.status
        record["bounded_timeout_fails_closed"] = bounded.status != "FEASIBLE" or (
            bounded.witness_digest is not None
        )
        record["bounded_timeout_never_feasible_without_witness"] = not (
            bounded.status == "FEASIBLE" and bounded.witness_digest is None
        )
    return record


def run(production_root: Path, *, runs: int = BENCHMARK_RUNS) -> dict[str, Any]:
    phases = _Phases(production_root)
    baseline = phases.cached("baseline", lambda: _baseline_record(phases))
    rows: dict[str, dict[str, Any]] = {}
    for strategy in DESIGNS:
        build_started = time.monotonic()
        design = phases.design(strategy)
        _progress(f"{strategy}: design ready in {time.monotonic() - build_started:.1f}s")
        if design is None:
            raise RuntimeError(f"RES-249 strategy {strategy} produced no abstract design")
        validation = phases.cached(
            f"validation-{strategy}",
            partial(validate_design, phases.sealed, design, proof_dir=phases.private / "proofs"),
        )
        repeated = phases.cached(
            f"runs-{strategy}",
            partial(_spawn_runs, production_root, strategy, phases.fingerprint, runs),
        )
        feasible = validation["colocation_status"] == "FEASIBLE"
        _base, colocation = build_exact_models(design.commitments, design.colocation_pairs)
        res = (
            phases.cached(f"resilience-{strategy}", partial(resilience, colocation))
            if feasible
            else {"status": "NOT_FEASIBLE"}
        )
        probes = (
            phases.cached(
                f"component-probes-{strategy}",
                partial(_repeated_component_probes, colocation),
            )
            if feasible
            else {"first": {"status": "NOT_FEASIBLE"}, "second": {"status": "NOT_FEASIBLE"}}
        )
        canonical = (
            phases.cached(
                f"canonical-{strategy}",
                partial(_canonical_once, colocation),
            )
            if feasible
            else {"status": "NOT_RUN_INFEASIBLE"}
        )
        rebuild = (
            phases.cached(
                f"rebuild-perturbations-{strategy}",
                partial(_rebuild_perturbations, phases, strategy, design),
            )
            if strategy != "CURRENT"
            else {}
        )
        reliability = phases.cached(
            f"reliability-{strategy}", partial(_reliability, phases, strategy)
        )
        rows[strategy] = _row(
            phases,
            strategy,
            design,
            validation,
            repeated["runs"],
            res,
            probes,
            canonical,
            rebuild,
            reliability,
        )
    selected, basis, trace = select_design(rows)
    matrix: dict[str, Any] = {
        "schema": "RES-249-ABC-BENCHMARK-MATRIX@1.0.0",
        "entry_head": ENTRY_HEAD,
        "baseline": baseline,
        "rows": rows,
        "selection_trace": trace,
        "selected_design": selected,
        "selection_basis": basis,
    }
    matrix["abc_benchmark_digest"] = canonical_hash(
        json.loads(json.dumps(matrix, sort_keys=True, default=str))
    )
    _write_record(production_root, f"{PRIVATE_DIR}/benchmark-matrix.private.json", matrix)
    membership_clean = _private_tree_membership_free(phases.private)
    matrix["no_split_membership_persisted"] = membership_clean
    return matrix


def _canonical_once(model: ExactModel) -> dict[str, Any]:
    """Lexicographically smallest split vector by self-reduction (run once)."""

    started = time.monotonic()
    first = solve_exact(model)
    if first.ranks is None:
        return {"status": first.status, "seconds": round(time.monotonic() - started, 4)}
    current = first.ranks
    fixed: dict[int, int] = {}
    solves = 1
    for index in range(len(model.components)):
        for rank in range(current[index]):
            solves += 1
            trial = solve_exact(model, fixed={**fixed, index: rank})
            if trial.status == "UNKNOWN":
                return {"status": "UNKNOWN", "seconds": round(time.monotonic() - started, 4)}
            if trial.ranks is not None:
                current = trial.ranks
                break
        fixed[index] = current[index]
    validate_witness(model, current)
    return {
        "status": "PASS",
        "seconds": round(time.monotonic() - started, 4),
        "solves": solves,
        "canonical_witness_digest": canonical_hash(
            ("RES-249-CANONICAL", model.model_digest, current)
        ),
    }


def _rebuild_perturbations(
    phases: _Phases, strategy: redesign.Strategy, design: AbstractProductionDesign
) -> dict[str, Any]:
    """Perturbations 2 and 3: rebuild the strategy on a perturbed abstract copy."""

    sealed = phases.sealed
    current_roots = sorted(sealed.root_ids)
    kept = [
        lineage.root_candidate_id
        for lineage in design.lineages
        if lineage.root_candidate_id in sealed.root_ids
    ]
    rejected = sorted(kept)[0] if kept else current_roots[0]
    new_parents = sorted(
        lineage.root_candidate_id
        for lineage in design.lineages
        if lineage.root_candidate_id not in sealed.root_ids
    )
    if new_parents:
        removed = new_parents[0]
        removed_kind = "NEWLY_SELECTED_TARGET_PARENT"
    else:
        removed = redesign.first_unused_compatible_parent(sealed, design)
        removed_kind = "FIRST_UNUSED_COMPATIBLE_TARGET_PARENT"
    outcomes: dict[str, Any] = {}
    for label, rejected_roots, removed_targets in (
        ("reject_one_root", frozenset({rejected}), frozenset[str]()),
        ("remove_one_target_parent", frozenset[str](), frozenset({removed})),
    ):
        repeats: list[dict[str, Any]] = []
        for _repeat in range(2):
            built = build_redesign(
                strategy,
                sealed,
                rejected_roots=rejected_roots,
                removed_targets=removed_targets,
            )
            if built is None:
                repeats.append({"status": "NO_DESIGN"})
                continue
            base, colocation = build_exact_models(built.commitments, built.colocation_pairs)
            statuses = {}
            for model in (base, colocation):
                cp = solve_exact(model)
                sat = independent_sat(
                    model, witness=cp.ranks, time_limit=RUN_SAT_TIME_LIMIT_SECONDS
                )
                statuses[model.kind] = exact_status(cp.status, sat)
            capacity = protected_capacity(
                built.commitments,
                built.colocation_pairs,
                root_ids={item.root_candidate_id for item in built.lineages},
            )
            repeats.append(
                {
                    "status": "BUILT",
                    "design_digest": built.design_digest,
                    "r1_violations": len(capacity.violating_cells),
                    "base_status": statuses["BASE"],
                    "colocation_status": statuses["COLOCATION"],
                    "content_changes": edit_surface(sealed, built).total_content_changes,
                }
            )
        outcomes[label] = {
            **repeats[0],
            "deterministic": repeats[0] == repeats[1],
            "survives": repeats[0].get("base_status") == "FEASIBLE"
            and repeats[0].get("colocation_status") == "FEASIBLE"
            and repeats[0].get("r1_violations") == 0,
        }
    outcomes["reject_one_root"]["rejected_root_digest"] = canonical_hash(rejected)
    outcomes["remove_one_target_parent"]["removed_parent_digest"] = canonical_hash(removed)
    outcomes["remove_one_target_parent"]["removed_parent_kind"] = removed_kind
    return outcomes


def _private_tree_membership_free(directory: Path) -> bool:
    for path in directory.rglob("*.private.json"):
        if path.name.startswith(("sealed-baseline", "design-")):
            continue
        _assert_no_membership(json.loads(path.read_text(encoding="utf-8")))
    return True


def _row(
    phases: _Phases,
    strategy: str,
    design: AbstractProductionDesign,
    validation: dict[str, Any],
    runs: list[dict[str, Any]],
    res: dict[str, Any],
    probes: dict[str, Any],
    canonical: dict[str, Any],
    rebuild: dict[str, Any],
    reliability: dict[str, Any],
) -> dict[str, Any]:
    surface = validation["edit_surface"]
    digests = {
        key: {run.get(key) for run in runs}
        for key in (
            "design_digest",
            "selection_digest",
            "commitment_inventory_digest",
            "base_model_digest",
            "colocation_model_digest",
            "base_witness_result",
            "colocation_witness_result",
            "base_status",
            "colocation_status",
        )
    }
    determinism = all(len(values) == 1 for values in digests.values()) and digests[
        "design_digest"
    ] == {design.design_digest}

    def series(key: str) -> dict[str, float]:
        return _summary([float(run[key]) for run in runs])

    end_to_end = series("end_to_end_seconds")
    first_probe = probes.get("first", {})
    return {
        "strategy": strategy,
        "design_digest": design.design_digest,
        "scientific_gate": validation["scientific_gate"],
        "scientific_failures": validation["scientific_failures"],
        "origin_counts": validation["origin_counts"],
        "lineages": validation["lineages"],
        "children_per_lineage": validation["children_per_lineage"],
        "r1_gate": validation["r1_gate"],
        "r1_violating_cells": validation["r1_colocation"]["r1_violating_cells"],
        "r1_violation_count": validation["r1_colocation"]["r1_violation_count"],
        "r1_base_violation_count": validation["r1_base"]["r1_violation_count"],
        "min_vh_eligible_components": validation["r1_colocation"]["min_vh_eligible_components"],
        "median_vh_eligible_components": validation["r1_colocation"][
            "median_vh_eligible_components"
        ],
        "max_vh_eligible_components": validation["r1_colocation"]["max_vh_eligible_components"],
        "cells_with_exactly_2": validation["r1_colocation"]["cells_with_exactly_2"],
        "cells_with_ge_3": validation["r1_colocation"]["cells_with_ge_3"],
        "capacity_matrix_digest": validation["r1_colocation"]["capacity_matrix_digest"],
        "base_status": validation["base_status"],
        "colocation_status": validation["colocation_status"],
        "base_crosscheck": validation["base_crosscheck"],
        "colocation_crosscheck": validation["colocation_crosscheck"],
        "independent_crosscheck": validation["independent_crosscheck"],
        "base_cpsat_status": validation["base_cpsat"]["status"],
        "colocation_cpsat_status": validation["colocation_cpsat"]["status"],
        "base_independent_result": validation["base_independent"]["result"],
        "colocation_independent_result": validation["colocation_independent"]["result"],
        "base_proof_check": validation["base_independent"].get("proof_check", "NOT_APPLICABLE"),
        "colocation_proof_check": validation["colocation_independent"].get(
            "proof_check", "NOT_APPLICABLE"
        ),
        **{key: surface[key] for key in surface if key != "changed_candidate_ids_digest"},
        "changed_candidate_ids_digest": surface["changed_candidate_ids_digest"],
        "atomic_components": validation["colocation_components"],
        "base_components": validation["base_components"],
        "component_size_distribution": validation["colocation_component_sizes"],
        "max_component_size": validation["colocation_max_component_size"],
        "mutation_block_sizes": validation["colocation_mutation_block_sizes"],
        "resilience": res,
        "component_probes": first_probe,
        "component_probes_deterministic": probes.get("first") == probes.get("second"),
        "canonical_self_reduction": canonical,
        "rebuild_perturbations": rebuild,
        "build_time": series("build_seconds"),
        "base_time": series("base_seconds"),
        "colocation_time": series("colocation_seconds"),
        "base_deterministic_time": series("base_deterministic_time"),
        "colocation_deterministic_time": series("colocation_deterministic_time"),
        "pb_encode_time": _summary(
            [
                float(r["base_pb_encode_seconds"]) + float(r["colocation_pb_encode_seconds"])
                for r in runs
            ]
        ),
        "sat_time": _summary(
            [float(r["base_sat_seconds"]) + float(r["colocation_sat_seconds"]) for r in runs]
        ),
        "end_to_end_time": end_to_end,
        "end_to_end_median_seconds": end_to_end["median"],
        "peak_rss_mb": max(float(run["peak_rss_mb"]) for run in runs),
        "base_model_variables": validation["base_cpsat"]["model_variables"],
        "base_model_constraints": validation["base_cpsat"]["model_constraints"],
        "colocation_model_variables": validation["colocation_cpsat"]["model_variables"],
        "colocation_model_constraints": validation["colocation_cpsat"]["model_constraints"],
        "base_cnf_variables": validation["base_independent"]["cnf_variables"],
        "base_cnf_clauses": validation["base_independent"]["cnf_clauses"],
        "colocation_cnf_variables": validation["colocation_independent"]["cnf_variables"],
        "colocation_cnf_clauses": validation["colocation_independent"]["cnf_clauses"],
        "private_artifact_bytes": sum(
            path.stat().st_size for path in phases.private.rglob(f"*{strategy}*") if path.is_file()
        ),
        "determinism_runs": len(runs),
        "determinism_pass": determinism,
        "restart_idempotent": bool(
            reliability.get("restart_digest_unchanged")
            and reliability.get("stale_fingerprint_rejected")
            and reliability.get("bounded_timeout_fails_closed", True)
        ),
        "reliability": reliability,
        "engineering": complexity(strategy, phases.sealed, design),
        "engineering_complexity": complexity(strategy, phases.sealed, design)[
            "operational_complexity"
        ],
        "objective_trace": validation["objective_trace"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--production-root", type=Path, default=DEFAULT_PRODUCTION_ROOT)
    parser.add_argument("--worker", choices=DESIGNS)
    parser.add_argument("--expected-fingerprint")
    parser.add_argument("--runs", type=int, default=BENCHMARK_RUNS)
    args = parser.parse_args(argv)
    if args.worker is not None:
        sealed = load_or_seal(args.production_root, expected=args.expected_fingerprint)
        print(json.dumps(run_once(sealed, args.worker), sort_keys=True))
        return 0
    matrix = run(args.production_root, runs=args.runs)
    print(
        json.dumps(
            {
                "selected_design": matrix["selected_design"],
                "selection_basis": matrix["selection_basis"],
                "abc_benchmark_digest": matrix["abc_benchmark_digest"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
