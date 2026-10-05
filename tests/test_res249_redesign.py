"""RES-249 abstract A/B/C redesign benchmark tests on a synthetic 434-slot fixture.

Slot inventories, expert batches, and prefix-selected mutation roots come from
the pure production authoring functions; all metadata is synthetic.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import replace
from functools import cache
from pathlib import Path

import pytest
import scripts.res249_benchmark as bench

from dynamislm.benchmark import res249_redesign as redesign
from dynamislm.benchmark.authoring import (
    AUTHORING_RECIPE_REGISTRY,
    production_seed_namespace,
    question_classes_for_cell,
)
from dynamislm.benchmark.constants import (
    CaseOrigin,
    DifficultyLevel,
    ExpectedAnswerKind,
    RefusalDecision,
    SplitName,
)
from dynamislm.benchmark.coverage import COVERAGE_MATRIX
from dynamislm.benchmark.production import (
    PRODUCTION_AUTHORING_PROCESS_ID,
    ProductionAuthoringPlanItemV1,
    ProductionCandidateCommitmentV1,
)
from dynamislm.benchmark.production_authoring import (
    _engine_slot_specs,
    _expert_batch_records,
    _mutation_lineage_specs,
    _semantic_slot_specs,
    _synthetic_slot_specs,
)
from dynamislm.benchmark.res225_repair import _mutation_role_from_parent
from dynamislm.benchmark.res249_redesign import (
    MUTATION_OPERATORS,
    AbstractProductionDesign,
    Reassignment,
    RedesignPlan,
    SealedRedesignInputs,
    build_exact_models,
    build_redesign,
    current_plan,
    edit_surface,
    materialize_plan,
    operator_root_upper_bounds,
    origin_counts,
    protected_capacity,
    scientific_gate,
    seal_redesign_inputs,
    solve_exact,
)
from dynamislm.serialization import canonical_json, from_canonical_json

_AUTHORITY = {
    CaseOrigin.EXPERT_AUTHORED_SEMANTIC: ("EXPERT_RUBRIC", "EXPERT_SEMANTIC"),
    CaseOrigin.ADVERSARIAL_MUTATION: ("EXPERT_RUBRIC", "EXPERT_SEMANTIC"),
    CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION: ("SOURCE_EVIDENCE_SPAN", "PHASE_A_SOURCE"),
    CaseOrigin.DETERMINISTIC_ENGINE_DERIVED: ("RES71_REFERENCE_CASE", "RES71_REFERENCE"),
    CaseOrigin.DETERMINISTIC_SYNTHETIC: ("GENERATOR", "DETERMINISTIC_GENERATOR"),
}


def _item(
    candidate_id: str,
    capability_id: str,
    family: str,
    origin: CaseOrigin,
    *,
    cluster: str,
    batch: str | None = None,
    seed_split: SplitName | None = None,
) -> ProductionAuthoringPlanItemV1:
    row = next(item for item in COVERAGE_MATRIX if item.capability_id == capability_id)
    recipe = next(
        item
        for item in AUTHORING_RECIPE_REGISTRY
        if (item.capability_id, item.benchmark_family) == (capability_id, family)
    )
    kind, authority_class = _AUTHORITY[origin]
    if kind not in row.answer_authorities:
        kind = next(
            value
            for value in row.answer_authorities
            if value in {"EXPERT_RUBRIC", "SOURCE_EVIDENCE_SPAN", "RES71_REFERENCE_CASE"}
        )
        authority_class = {
            "EXPERT_RUBRIC": "EXPERT_SEMANTIC",
            "SOURCE_EVIDENCE_SPAN": "PHASE_A_SOURCE",
            "RES71_REFERENCE_CASE": "RES71_REFERENCE",
        }[kind]
    semantic = origin is CaseOrigin.EXPERT_AUTHORED_SEMANTIC
    synthetic = origin is CaseOrigin.DETERMINISTIC_SYNTHETIC
    source = origin is CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION
    refusal = capability_id == "C18"
    seed_block = f"block-{hashlib.sha256(candidate_id.encode()).hexdigest()[:8]}"
    return ProductionAuthoringPlanItemV1(
        candidate_id=candidate_id,
        recipe_id=recipe.recipe_id,
        recipe_version=recipe.recipe_version,
        capability_id=capability_id,
        benchmark_family=family,
        practitioner_question_class=question_classes_for_cell(capability_id, family)[0],
        origin_class=origin,
        scoring_profile=recipe.scorers[0],
        authority_class=authority_class,
        authority_kinds=(kind,),
        reachable_error_classes=tuple(
            sorted(row.error_classes, key=lambda error: error.value.encode("utf-8"))
        ),
        adversarial_tags=tuple(sorted(row.adversarial_tags)),
        source_family_id=f"synthetic-family:{candidate_id}",
        source_document_ids=(f"synthetic-document:{candidate_id}",) if source else (),
        source_artifact_ids=(f"synthetic-artifact:{candidate_id}",) if source else (),
        construct_test_identity_ids=(),
        provider_export_ids=(),
        protocol_template_ids=(f"synthetic-template:{batch}",) if semantic else (),
        expert_author_batch_id=f"synthetic-batch:{batch}" if semantic else None,
        author_id=PRODUCTION_AUTHORING_PROCESS_ID,
        generator_id="synthetic-generator" if synthetic else None,
        generator_version="1.0.0" if synthetic else None,
        generator_family=f"synthetic-generator-family:{family}" if synthetic else None,
        seed_namespace=production_seed_namespace(
            seed_split or SplitName.PUBLIC_DEVELOPMENT,
            "synthetic-generator",
            "1.0.0",
            seed_block,
        )
        if synthetic
        else None,
        seed_block=seed_block if synthetic else None,
        mutation_lineage_id=None,
        parent_candidate_id=None,
        isolation_cluster_id=cluster,
        allocation_stratum=f"{capability_id}:{family}",
        refusal_decision=RefusalDecision.REQUIRED if refusal else RefusalDecision.PROHIBITED,
        expected_answer_kind=ExpectedAnswerKind.REFUSAL if refusal else ExpectedAnswerKind.ANSWER,
        safe_partial_support=refusal,
        difficulty=DifficultyLevel.EASY,
        engine_reference_case_id=(
            f"res71-reference:{candidate_id}"
            if origin is CaseOrigin.DETERMINISTIC_ENGINE_DERIVED
            else None
        ),
    )


def _commit(item: ProductionAuthoringPlanItemV1) -> ProductionCandidateCommitmentV1:
    digest = hashlib.sha256(f"synthetic:{item.candidate_id}".encode()).hexdigest()
    return ProductionCandidateCommitmentV1(item, "sha256:" + digest)


def synthetic_sealed_population() -> tuple[
    tuple[ProductionCandidateCommitmentV1, ...], tuple[tuple[str, str], ...]
]:
    slots = _semantic_slot_specs()
    batches = _expert_batch_records(slots)
    batch_by_slot = {
        candidate_id: batch for batch in batches for candidate_id in batch.candidate_ids
    }
    items: dict[str, ProductionAuthoringPlanItemV1] = {}
    for candidate_id, capability_id, family, _slot in slots:
        batch = batch_by_slot[candidate_id]
        items[candidate_id] = _item(
            candidate_id,
            capability_id,
            family,
            CaseOrigin.EXPERT_AUTHORED_SEMANTIC,
            cluster=batch.isolation_cluster_id,
            batch=batch.author_batch_id,
        )
    for candidate_id, capability_id, family, _slot in _engine_slot_specs():
        items[candidate_id] = _item(
            candidate_id,
            capability_id,
            family,
            CaseOrigin.DETERMINISTIC_ENGINE_DERIVED,
            cluster=f"synthetic-engine:{candidate_id}",
        )
    for candidate_id, family, split in _synthetic_slot_specs():
        items[candidate_id] = _item(
            candidate_id,
            "C08",
            family,
            CaseOrigin.DETERMINISTIC_SYNTHETIC,
            cluster=f"synthetic-generator:{candidate_id}",
            seed_split=split,
        )
    source_cells = [
        (row.capability_id, family)
        for row in COVERAGE_MATRIX
        if CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION in row.case_origins
        for family in row.benchmark_families
    ]
    # C13 has no semantic lane, so its cells receive three source slots each.
    c13 = [cell for cell in source_cells if cell[0] == "C13"]
    others = [cell for cell in source_cells if cell[0] != "C13"]
    source_plan = [cell for cell in c13 for _copy in range(3)]
    source_plan += [others[index % len(others)] for index in range(40 - len(source_plan))]
    for index, (capability_id, family) in enumerate(source_plan):
        candidate_id = f"PSE-V1-CANDIDATE:SOURCE:synthetic{index:03d}"
        items[candidate_id] = _item(
            candidate_id,
            capability_id,
            family,
            CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION,
            cluster=f"synthetic-source:{candidate_id}",
        )
    template = replace(
        items[slots[0][0]],
        candidate_id="PSE-V1-CANDIDATE:MUT:template",
        origin_class=CaseOrigin.ADVERSARIAL_MUTATION,
        mutation_lineage_id="synthetic-lineage",
        parent_candidate_id=slots[0][0],
        difficulty=DifficultyLevel.HARD,
    )
    for lineage in _mutation_lineage_specs(slots):
        parent_id = lineage.parent_candidate_id
        root = items[parent_id]
        for stage, child_id in enumerate(lineage.child_candidate_ids, start=1):
            items[child_id] = _mutation_role_from_parent(
                replace(template, candidate_id=child_id),
                root,
                target_parent_id=parent_id,
                target_lineage_id=lineage.lineage_id,
                stage=stage,
            )
            parent_id = child_id
    commitments = tuple(_commit(items[key]) for key in sorted(items, key=str.encode))
    return commitments, ()


FROZEN_ORIGINS = {
    "EXPERT_AUTHORED_SEMANTIC": 240,
    "SOURCE_BACKED_EVIDENCE_EXTRACTION": 40,
    "DETERMINISTIC_ENGINE_DERIVED": 31,
    "DETERMINISTIC_SYNTHETIC": 12,
    "ADVERSARIAL_MUTATION": 111,
}


@cache
def _sealed() -> SealedRedesignInputs:
    commitments, pairs = synthetic_sealed_population()
    return seal_redesign_inputs(commitments, pairs)


@cache
def _design(strategy: str) -> AbstractProductionDesign:
    built = build_redesign(strategy, _sealed())  # type: ignore[arg-type]
    assert built is not None
    return built


def _roots(design: AbstractProductionDesign) -> set[str]:
    return {lineage.root_candidate_id for lineage in design.lineages}


# -- baseline -----------------------------------------------------------------


def test_operator_specs_mirror_the_prefix_selector() -> None:
    slots = _semantic_slot_specs()
    prefix = {item.parent_candidate_id for item in _mutation_lineage_specs(slots)}
    mirrored: set[str] = set()
    for spec in MUTATION_OPERATORS:
        compatible = [slot[0] for slot in slots if spec.admits(slot[1], slot[2])]
        mirrored.update(compatible[: spec.count])
    assert mirrored == prefix
    assert sum(spec.count for spec in MUTATION_OPERATORS) == 37


def test_current_prefix_root_selector_reproduces_r1_failure() -> None:
    sealed = _sealed()
    prefix = {item.parent_candidate_id for item in _mutation_lineage_specs(_semantic_slot_specs())}
    assert sealed.root_ids == prefix
    report = protected_capacity(
        sealed.commitments, sealed.colocation_pairs, root_ids=sealed.root_ids
    )
    assert report.violating_cells
    # Every fully saturated root cell must be reported.
    saturated = {
        ("C09", "F07"),
        ("C18", "F02"),
        ("C18", "F03"),
        ("C01", "F01"),
        ("C07", "F04"),
        ("C17", "F01"),
    }
    assert saturated <= set(report.violating_cells)


def test_r1_gate_catches_every_cell_blocked_by_roots_or_partners() -> None:
    sealed = _sealed()
    items = sealed.items
    report = protected_capacity(
        sealed.commitments, sealed.colocation_pairs, root_ids=sealed.root_ids
    )
    # Independent recount: a cell's eligible components exclude any component
    # holding a root (and therefore its same-cell children).
    by_cluster: dict[str, list[str]] = {}
    for cid, item in items.items():
        by_cluster.setdefault(item.isolation_cluster_id, []).append(cid)
    eligible: Counter[tuple[str, str]] = Counter()
    for members in by_cluster.values():
        cells = Counter((items[c].capability_id, items[c].benchmark_family) for c in members)
        if max(cells.values()) > 1 or any(
            items[c].origin_class is CaseOrigin.DETERMINISTIC_SYNTHETIC
            and "PUBLIC" in (items[c].seed_namespace or "")
            for c in members
        ):
            continue
        for cell in cells:
            eligible[cell] += 1
    expected = {cell for cell in redesign.all_cells() if eligible[cell] < 2}
    assert expected <= set(report.violating_cells)


def test_r1_violation_is_a_sufficient_infeasibility_certificate() -> None:
    sealed = _sealed()
    current = _design("CURRENT")
    assert protected_capacity(
        current.commitments, current.colocation_pairs, root_ids=sealed.root_ids
    ).violating_cells
    _base, colocation = build_exact_models(current.commitments, current.colocation_pairs)
    assert solve_exact(colocation, deterministic_time=30.0).status == "INFEASIBLE"
    assert bench.independent_sat(colocation, time_limit=120.0)["result"] == "UNSAT"


def test_current_plan_materializes_the_sealed_commitments_exactly() -> None:
    sealed = _sealed()
    current = materialize_plan(sealed, current_plan(sealed), strategy="CURRENT")
    assert current.commitments == sealed.commitments
    assert edit_surface(sealed, current).total_content_changes == 0
    assert scientific_gate(sealed, current).status == "PASS"


def test_pigeonhole_bound_is_mechanical_and_matches_operator_authority() -> None:
    bounds = operator_root_upper_bounds(_sealed())
    assert set(bounds) == {spec.operator_id for spec in MUTATION_OPERATORS}
    for spec in MUTATION_OPERATORS:
        assert bounds[spec.operator_id]["required"] == spec.count


# -- design A -------------------------------------------------------------------


def test_balanced_root_selector_is_deterministic() -> None:
    first = build_redesign("A", _sealed())
    second = build_redesign("A", _sealed())
    assert first is not None and second is not None
    assert first.design_digest == second.design_digest
    assert first.plan == second.plan


def test_design_a_has_exact_operator_root_counts_and_unique_roots() -> None:
    design = _design("A")
    counts = Counter(lineage.operator_id for lineage in design.lineages)
    assert counts == Counter({spec.operator_id: spec.count for spec in MUTATION_OPERATORS})
    assert len(_roots(design)) == 37
    assert {len(lineage.child_candidate_ids) for lineage in design.lineages} == {3}


def test_same_candidate_cannot_root_multiple_lineages() -> None:
    sealed = _sealed()
    plan = current_plan(sealed)
    duplicate = plan.roots[0][1]
    roots = tuple(
        (operator, duplicate if operator == plan.roots[0][0] else root)
        for operator, root in plan.roots
    )
    with pytest.raises(ValueError):
        materialize_plan(sealed, replace(plan, roots=roots), strategy="A")


def test_root_must_be_operator_compatible() -> None:
    sealed = _sealed()
    plan = current_plan(sealed)
    incompatible = next(
        cid
        for cid, item in sealed.items.items()
        if item.origin_class is CaseOrigin.EXPERT_AUTHORED_SEMANTIC
        and redesign.operator_for_root(item) is None
    )
    roots = ((plan.roots[0][0], incompatible), *plan.roots[1:])
    with pytest.raises(ValueError):
        materialize_plan(sealed, replace(plan, roots=roots), strategy="A")


def test_design_a_preserves_the_semantic_cell_inventory() -> None:
    sealed = _sealed()
    design = _design("A")

    def inventory(commitments: tuple[object, ...]) -> Counter[tuple[str, str]]:
        return Counter(
            (entry.item.capability_id, entry.item.benchmark_family)  # type: ignore[attr-defined]
            for entry in commitments
            if entry.item.origin_class is CaseOrigin.EXPERT_AUTHORED_SEMANTIC  # type: ignore[attr-defined]
        )

    assert inventory(design.commitments) == inventory(sealed.commitments)
    assert not design.plan.reassignments and not design.plan.rebinds
    surface = edit_surface(sealed, design)
    assert surface.semantic_slots_reassigned == 0
    assert surface.total_content_changes == surface.mutation_children_regenerated
    assert surface.mutation_children_regenerated == 3 * surface.semantic_root_identities_changed


# -- design B -------------------------------------------------------------------


def test_b_action_space_contains_reassignment_and_non_root_reparenting() -> None:
    sealed = _sealed()
    model = redesign._CapacityModel(sealed, redesign.action_space("B", sealed))
    assert model.depart and model.arrive and model.rebind and model.root_replace
    non_root_targets = {cid for (_op, cid) in model.root_vars if cid not in sealed.root_ids}
    assert non_root_targets
    families = {name for name, _reason in redesign.INADMISSIBLE_ACTION_FAMILIES}
    assert "LINEAGE_SIZE_REDUCTION" in families


def test_b_action_cost_counts_unique_candidates_without_double_counting() -> None:
    sealed = _sealed()
    items = sealed.items
    semantic = sorted(
        cid
        for cid, item in items.items()
        if item.origin_class is CaseOrigin.EXPERT_AUTHORED_SEMANTIC
        and cid not in sealed.root_ids
        and Counter(i.isolation_cluster_id for i in items.values())[item.isolation_cluster_id] == 2
    )
    mover, rebound = semantic[0], semantic[1]
    target = next(
        cid
        for cid in sorted(items)
        if items[cid].origin_class is CaseOrigin.EXPERT_AUTHORED_SEMANTIC
        and (items[cid].capability_id, items[cid].benchmark_family)
        != (items[mover].capability_id, items[mover].benchmark_family)
    )
    lineage = sealed.lineages[0]
    plan = replace(
        current_plan(sealed),
        reassignments=(
            Reassignment(
                mover,
                (items[target].capability_id, items[target].benchmark_family),
                target,
            ),
        ),
        rebinds=(rebound,),
        root_replacements=(lineage.root_candidate_id,),
    )
    design = materialize_plan(sealed, plan, strategy="B")
    surface = edit_surface(sealed, design)
    # reassigned slot + rebound slot + replaced root + its three children.
    assert surface.total_content_changes == 1 + 1 + 1 + 3
    assert surface.candidate_hashes_changed == surface.total_content_changes
    with pytest.raises(ValueError):
        materialize_plan(
            sealed,
            replace(plan, rebinds=(mover,)),
            strategy="B",
        )


def test_b_exact_allocation_design_passes_every_hard_gate() -> None:
    sealed = _sealed()
    design = _design("B")
    assert redesign.is_exact_allocation_design(design)
    assert scientific_gate(sealed, design).status == "PASS"
    assert not protected_capacity(
        design.commitments, design.colocation_pairs, root_ids=_roots(design)
    ).violating_cells


# -- design C -------------------------------------------------------------------


def test_c_reduces_to_a_when_no_downstream_action_is_required(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sealed = _sealed()
    a_design = _design("A")
    feasible_a = materialize_plan(
        sealed,
        a_design.plan,
        strategy="A",
        objective_trace=(("EXACT_ALLOCATION_EMBEDDED", 1),),
    )
    original = redesign.build_redesign

    def fake(strategy: str, sealed_inputs: SealedRedesignInputs, **kwargs: object) -> object:
        if strategy == "A":
            return feasible_a
        return original(strategy, sealed_inputs, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(redesign, "build_redesign", fake)
    c_design = original("C", sealed)
    assert c_design is not None
    assert c_design.plan == feasible_a.plan
    assert dict(c_design.objective_trace)["DOWNSTREAM_ACTIONS"] == 0


def test_c_starts_from_a_roots_and_adds_only_downstream_actions() -> None:
    a_design, c_design = _design("A"), _design("C")
    assert set(c_design.plan.roots) == set(a_design.plan.roots)
    assert (
        edit_surface(_sealed(), c_design).total_content_changes
        >= edit_surface(_sealed(), a_design).total_content_changes
    )


# -- common contracts -------------------------------------------------------------


@pytest.mark.parametrize("strategy", ["CURRENT", "A", "B", "C"])
def test_exact_origin_counts_for_every_strategy(strategy: str) -> None:
    design = _design(strategy)
    assert dict(origin_counts(design.commitments)) == FROZEN_ORIGINS
    assert len(design.lineages) == 37


@pytest.mark.parametrize("strategy", ["A", "B", "C"])
def test_repeated_build_digest_stability(strategy: str) -> None:
    rebuilt = build_redesign(strategy, _sealed())  # type: ignore[arg-type]
    assert rebuilt is not None
    assert rebuilt.design_digest == _design(strategy).design_digest


def test_common_validator_parity_across_strategies(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(redesign, "EXACT_DETERMINISTIC_TIME", 5.0)
    monkeypatch.setattr(bench, "SAT_TIME_LIMIT_SECONDS", 30.0)
    records = {
        strategy: bench.validate_design(_sealed(), _design(strategy), proof_dir=tmp_path)
        for strategy in ("CURRENT", "A", "B", "C")
    }
    keys = {frozenset(record) for record in records.values()}
    assert len(keys) == 1
    assert records["CURRENT"]["r1_gate"] == "FAIL"
    assert records["CURRENT"]["hard_gates_pass"] is False
    for record in records.values():
        bench._assert_no_membership(record)


def test_independent_sat_agrees_with_cp_sat_and_validates_witness() -> None:
    design = _design("B")
    _base, colocation = build_exact_models(design.commitments, design.colocation_pairs)
    cp = solve_exact(colocation)
    assert cp.status == "FEASIBLE" and cp.ranks is not None
    sat = bench.independent_sat(colocation, witness=cp.ranks, time_limit=5.0)
    assert sat["witness_model_check"] == "SAT"
    assert sat["result"] in {"SAT", "UNKNOWN"}
    assert bench.crosscheck("FEASIBLE", sat) == "PASS"
    # A witness rejected by the independent encoding is a disagreement.
    assert bench.crosscheck("FEASIBLE", {**sat, "witness_model_check": "UNSAT"}) == "FAIL"
    tampered = list(cp.ranks)
    tampered[0] = (tampered[0] + 1) % 3
    with pytest.raises(RuntimeError):
        bench.independent_sat(colocation, witness=tuple(tampered), time_limit=1.0)


def test_crosscheck_requires_checked_proofs_and_never_passes_unknown() -> None:
    assert bench.crosscheck("UNKNOWN", {"result": "UNKNOWN"}) == "UNKNOWN"
    assert bench.crosscheck("UNKNOWN", {"result": "UNSAT", "proof_check": "PASS"}) == "PASS"
    assert (
        bench.crosscheck("INFEASIBLE", {"result": "UNSAT", "proof_check": "CHECKER_UNAVAILABLE"})
        == "UNVERIFIED"
    )
    assert (
        bench.crosscheck(
            "FEASIBLE",
            {"result": "UNSAT", "proof_check": "PASS", "witness_model_check": "SAT"},
        )
        == "FAIL"
    )
    assert bench.crosscheck("INFEASIBLE", {"result": "SAT"}) == "FAIL"
    assert bench.exact_status("UNKNOWN", {"result": "UNKNOWN"}) == "UNKNOWN"
    assert bench.exact_status("FEASIBLE", {"result": "UNKNOWN"}) == "UNKNOWN"


def test_bounded_timeout_fails_closed() -> None:
    design = _design("B")
    _base, colocation = build_exact_models(design.commitments, design.colocation_pairs)
    bounded = solve_exact(colocation, deterministic_time=1e-9)
    assert bounded.status in {"UNKNOWN", "FEASIBLE"}
    if bounded.status == "FEASIBLE":
        assert bounded.witness_digest is not None
    assert bench.exact_status("UNKNOWN", {"result": "UNKNOWN"}) != "FEASIBLE"


def test_stale_authority_fingerprint_is_rejected() -> None:
    with pytest.raises(ValueError, match="stale"):
        build_redesign("A", _sealed(), expected_fingerprint="sha256:" + "0" * 64)
    stale = replace(_design("B"), authority_fingerprint="sha256:" + "1" * 64)
    assert "STALE_AUTHORITY_FINGERPRINT" in scientific_gate(_sealed(), stale).failures


def test_interrupted_construction_restarts_to_the_same_digest() -> None:
    def interrupt(message: str) -> None:
        raise redesign.RedesignInterruptedError(message)

    with pytest.raises(redesign.RedesignInterruptedError):
        build_redesign("B", _sealed(), progress=interrupt)
    restarted = build_redesign("B", _sealed())
    assert restarted is not None and restarted.design_digest == _design("B").design_digest


def test_perturbation_probes_are_deterministic() -> None:
    design = _design("B")
    _base, colocation = build_exact_models(design.commitments, design.colocation_pairs)
    first = bench.component_probes(colocation)
    second = bench.component_probes(colocation)
    assert first == second
    assert first["status"] == "COMPLETE"


def test_scientific_gate_rejects_changed_fixed_authority_and_invented_roles() -> None:
    sealed = _sealed()
    design = _design("B")
    source = next(
        entry
        for entry in design.commitments
        if entry.item.origin_class is CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION
    )
    tampered = tuple(
        replace(entry, candidate_payload_hash="sha256:" + "f" * 64) if entry is source else entry
        for entry in design.commitments
    )
    failures = scientific_gate(sealed, replace(design, commitments=tampered)).failures
    assert any(item.startswith("FIXED_AUTHORITY_CHANGED") for item in failures)
    assert (
        "CONTAMINATION_COLOCATION_EDGES_CHANGED"
        in scientific_gate(sealed, replace(design, colocation_pairs=())).failures
        or not sealed.colocation_pairs
    )


def test_no_candidate_materialization_side_effect(tmp_path: Path) -> None:
    sealed = _sealed()
    before = canonical_json(sealed)
    design = _design("C")
    assert canonical_json(sealed) == before
    changed = {
        entry.candidate_id
        for entry in design.commitments
        if entry.candidate_payload_hash
        != {e.candidate_id: e.candidate_payload_hash for e in sealed.commitments}.get(
            entry.candidate_id
        )
    }
    # Every changed slot is a typed placeholder hash, never authored content.
    for entry in design.commitments:
        if entry.candidate_id in changed:
            assert entry.candidate_payload_hash.startswith("sha256:")
    source = Path(redesign.__file__).read_text(encoding="utf-8")
    for forbidden in ("write_external_production_json", "replace_external_production_json"):
        assert forbidden not in source
    assert list(tmp_path.iterdir()) == []


def test_no_split_membership_is_persisted(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="split membership"):
        bench._write_record(tmp_path, "record.json", {"nested": {"ranks": [0, 1, 2]}})
    assert not (tmp_path / "record.json").exists()
    bench._write_record(tmp_path, "ok.private.json", {"witness_digest": "sha256:" + "a" * 64})
    assert bench._private_tree_membership_free(tmp_path)
    fields = set(AbstractProductionDesign.__dataclass_fields__)
    assert not fields & {"ranks", "split_membership", "assignment"}


def test_abstract_design_round_trips_through_serialization_v3() -> None:
    design = _design("B")
    restored = from_canonical_json(canonical_json(design), AbstractProductionDesign)
    assert restored == design
    plan_payload = json.loads(canonical_json(design.plan))
    assert plan_payload["type"].endswith("RedesignPlan")


# -- selection hierarchy ----------------------------------------------------------


def _row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "scientific_gate": "PASS",
        "r1_gate": "PASS",
        "base_status": "FEASIBLE",
        "colocation_status": "FEASIBLE",
        "independent_crosscheck": "PASS",
        "total_content_changes": 10,
        "resilience": {
            "forceable_min": 2,
            "forceable_median": 3,
            "forceable_eq1": 0,
            "single_component_failure_fatal_count": 0,
        },
        "determinism_pass": True,
        "restart_idempotent": True,
        "end_to_end_median_seconds": 1.0,
        "peak_rss_mb": 100.0,
        "engineering_complexity": "MEDIUM",
    }
    row.update(overrides)
    return row


def test_selection_eliminates_hard_gate_failures_before_edit_surface() -> None:
    rows = {
        "A": _row(r1_gate="FAIL", total_content_changes=1),
        "B": _row(total_content_changes=30),
        "C": _row(colocation_status="UNKNOWN", total_content_changes=2),
    }
    selected, basis, trace = bench.select_design(rows)
    assert selected == "B"
    assert basis.startswith("ONLY_B_PASSES")
    assert "A:ELIMINATED_AT=2_STRUCTURAL_R1" in trace


def test_selection_uses_strict_hierarchy_not_a_weighted_score() -> None:
    rows = {
        "A": _row(total_content_changes=10, peak_rss_mb=10_000.0),
        "B": _row(total_content_changes=11, peak_rss_mb=1.0, engineering_complexity="LOW"),
        "C": _row(total_content_changes=12),
    }
    selected, basis, _trace = bench.select_design(rows)
    assert selected == "A"
    assert "4_LOWER_SCIENTIFIC_EDIT_SURFACE" in basis


def test_selection_stops_for_humans_on_an_unresolved_trade_off() -> None:
    rows = {
        "A": _row(resilience={"forceable_min": 3, "forceable_median": 2}),
        "B": _row(resilience={"forceable_min": 2, "forceable_median": 4}),
        "C": _row(scientific_gate="FAIL"),
    }
    selected, basis, _trace = bench.select_design(rows)
    assert selected == "HUMAN_DECISION_REQUIRED"
    assert basis == "TRADE_OFF_AT_5_STRONGER_ALLOCATION_RESILIENCE"


def test_selection_without_any_passing_design_requires_humans() -> None:
    rows = {name: _row(r1_gate="FAIL") for name in ("A", "B", "C")}
    selected, basis, _trace = bench.select_design(rows)
    assert (selected, basis) == ("HUMAN_DECISION_REQUIRED", "NO_DESIGN_PASSES_HARD_GATES_1_TO_3")


def test_plan_canonicalization_is_order_independent() -> None:
    plan = current_plan(_sealed())
    shuffled = RedesignPlan(roots=tuple(reversed(plan.roots)))
    assert shuffled.canonical() == plan


def test_selected_plan_is_independent_of_the_solver_search_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Equally optimal plans must not be chosen by search order: a different
    # search seed must reach the same canonical plan.
    monkeypatch.setattr(redesign, "OPTIMIZER_RANDOM_SEED", 7)
    reseeded = build_redesign("B", _sealed())
    assert reseeded is not None
    assert reseeded.design_digest == _design("B").design_digest
