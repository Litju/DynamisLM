from __future__ import annotations

import hashlib
import subprocess
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Literal, cast

import pytest

from dynamislm.benchmark.authoring import (
    AUTHORING_RECIPE_REGISTRY,
    production_seed_namespace,
    question_classes_for_cell,
)
from dynamislm.benchmark.constants import (
    CRITICAL_ERROR_CLASSES,
    CaseOrigin,
    DifficultyLevel,
    ErrorClass,
    ExpectedAnswerKind,
    RefusalDecision,
    SplitName,
)
from dynamislm.benchmark.contamination import (
    exact_13_token_shingles,
    exact_shingle_digest,
    fuzzy_fingerprint,
    normalized_text_sha256,
)
from dynamislm.benchmark.coverage import COVERAGE_MATRIX
from dynamislm.benchmark.pre_review import CandidateReviewPacket, bind_candidate_review_packet
from dynamislm.benchmark.production import (
    PRODUCTION_AUTHORING_PROCESS_ID,
    PRODUCTION_BATCH_ID,
    PRODUCTION_BATCH_MANIFEST_VERSION,
    ProductionAuthoringPlanItemV1,
    ProductionAuthoringPlanV1,
    ProductionBatchManifestV1,
    ProductionCandidateCommitmentV1,
    ProductionExactFeasibilityReceiptV2,
    ProductionFeasibilityBlocked,
    ProductionFeasibilityReceiptV1,
    bind_production_batch_manifest,
    validate_production_batch_manifest,
    validate_production_exact_feasibility,
    validate_production_exact_feasibility_receipt,
    validate_production_hard_feasibility,
    validate_production_isolation,
)
from dynamislm.benchmark.production_exclusions import (
    QUALIFICATION_001B_BATCH_ID,
    QUALIFICATION_EXCLUSION_VERSION,
    QualificationExclusionCandidateV1,
    QualificationExclusionCommitmentV1,
    QualificationTrainingExclusionManifestV1,
    bind_qualification_exclusion_commitment,
    build_qualification_training_exclusion_manifest,
    validate_production_candidate_against_qualification_exclusion,
    validate_production_exclusion_identity,
)
from dynamislm.benchmark.production_store import (
    read_external_production_json,
    write_external_production_json,
)
from dynamislm.benchmark.public_repository import validate_production_private_material_absent
from dynamislm.benchmark.transient_storage import (
    DEFAULT_TRANSIENT_CACHE_ROOT,
    TRANSIENT_CACHE_MAX_BYTES,
    TransientCacheCheckpointV1,
    TransientCacheMeasurementV1,
    TransientCachePeakTracker,
    _enforce_transient_cache_limit,
    measure_transient_cache_bytes,
)
from dynamislm.qualification.res115_authoring import _semantic_cell_candidate
from dynamislm.serialization import canonical_hash, canonical_json

_SHA = "sha256:" + "a" * 64


def _item(
    candidate_id: str,
    *,
    capability_id: str = "C01",
    benchmark_family: str = "F01",
    cluster: str | None = None,
    source_family: str | None = None,
    author_batch: str = "expert-batch:001C-test-a",
    template: str = "protocol-template:001C-test-a",
    origin: CaseOrigin | None = CaseOrigin.EXPERT_AUTHORED_SEMANTIC,
    mutation_lineage: str | None = None,
    parent_candidate_id: str | None = None,
    generator_family: str | None = None,
    seed_split: SplitName = SplitName.PUBLIC_DEVELOPMENT,
    refusal_decision: RefusalDecision = RefusalDecision.PROHIBITED,
    answer_kind: ExpectedAnswerKind = ExpectedAnswerKind.ANSWER,
    safe_partial_support: bool = False,
    global_batch: bool = False,
    omitted_error: ErrorClass | None = None,
) -> ProductionAuthoringPlanItemV1:
    row = next(item for item in COVERAGE_MATRIX if item.capability_id == capability_id)
    recipe = next(
        item
        for item in AUTHORING_RECIPE_REGISTRY
        if (item.capability_id, item.benchmark_family) == (capability_id, benchmark_family)
    )
    if origin is None:
        origin = (
            CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION
            if CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION in row.case_origins
            else row.case_origins[0]
        )
    if global_batch and CaseOrigin.EXPERT_AUTHORED_SEMANTIC in row.case_origins:
        origin = CaseOrigin.EXPERT_AUTHORED_SEMANTIC
    if origin is CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION:
        authority_kind, authority_class = "SOURCE_EVIDENCE_SPAN", "PHASE_A_SOURCE"
    elif origin is CaseOrigin.DETERMINISTIC_ENGINE_DERIVED:
        authority_kind, authority_class = "RES71_REFERENCE_CASE", "RES71_REFERENCE"
    elif origin is CaseOrigin.DETERMINISTIC_SYNTHETIC:
        authority_kind, authority_class = "GENERATOR", "DETERMINISTIC_GENERATOR"
    elif origin is CaseOrigin.ADVERSARIAL_MUTATION:
        authority_kind, authority_class = "EXPERT_RUBRIC", "EXPERT_SEMANTIC"
    else:
        authority_kind, authority_class = "EXPERT_RUBRIC", "EXPERT_SEMANTIC"
    authority_kind = next(
        (kind for kind in row.answer_authorities if kind == authority_kind),
        next(
            kind
            for kind in row.answer_authorities
            if kind
            in {
                "EXPERT_RUBRIC",
                "SOURCE_EVIDENCE_SPAN",
                "RES71_REFERENCE_CASE",
                "GENERATOR",
            }
        ),
    )
    authority_class = {
        "EXPERT_RUBRIC": "EXPERT_SEMANTIC",
        "SOURCE_EVIDENCE_SPAN": "PHASE_A_SOURCE",
        "SOURCE_DOCUMENT": "PHASE_A_SOURCE",
        "RES71_REFERENCE_CASE": "RES71_REFERENCE",
        "RES71_OPERATION": "RES71_REFERENCE",
        "RES71_UNRESOLVED": "RES71_REFERENCE",
        "GENERATOR": "DETERMINISTIC_GENERATOR",
    }[authority_kind]
    is_source = origin is CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION
    is_semantic = origin is CaseOrigin.EXPERT_AUTHORED_SEMANTIC
    is_synthetic = origin is CaseOrigin.DETERMINISTIC_SYNTHETIC
    batch_id = "expert-batch:001C-global" if global_batch else author_batch
    template_id = "protocol-template:001C-global" if global_batch else template
    if is_semantic:
        cluster = cluster or ("cluster:global-author-batch" if global_batch else None)
    if is_synthetic and generator_family is None:
        generator_family = f"generator-family:{candidate_id}"
    seed_block = f"block-{candidate_id.rsplit(':', 1)[-1]}" if is_synthetic else None
    source_doc = f"document:{candidate_id}"
    source_artifact = f"source-artifact:{candidate_id}"
    return ProductionAuthoringPlanItemV1(
        candidate_id=candidate_id,
        recipe_id=recipe.recipe_id,
        recipe_version=recipe.recipe_version,
        capability_id=capability_id,
        benchmark_family=benchmark_family,
        practitioner_question_class=question_classes_for_cell(capability_id, benchmark_family)[0],
        origin_class=origin,
        scoring_profile=recipe.scorers[0],
        authority_class=authority_class,
        authority_kinds=(authority_kind,),
        reachable_error_classes=tuple(
            sorted(
                (error for error in row.error_classes if error is not omitted_error),
                key=lambda item: item.value.encode("utf-8"),
            )
        ),
        adversarial_tags=tuple(sorted(row.adversarial_tags)),
        source_family_id=source_family or f"source-family:{candidate_id}",
        source_document_ids=(source_doc,) if is_source else (),
        source_artifact_ids=(source_artifact,) if is_source else (),
        construct_test_identity_ids=(),
        provider_export_ids=(),
        protocol_template_ids=(template_id,) if is_semantic else (),
        expert_author_batch_id=batch_id if is_semantic else None,
        author_id=PRODUCTION_AUTHORING_PROCESS_ID,
        generator_id="test-generator" if is_synthetic else None,
        generator_version="1.0.0" if is_synthetic else None,
        generator_family=generator_family,
        seed_block=seed_block,
        seed_namespace=(
            production_seed_namespace(
                seed_split,
                "test-generator",
                "1.0.0",
                seed_block or "",
            )
            if is_synthetic
            else None
        ),
        mutation_lineage_id=mutation_lineage,
        parent_candidate_id=parent_candidate_id,
        isolation_cluster_id=cluster or f"cluster:{candidate_id}",
        allocation_stratum=f"{capability_id}:{benchmark_family}",
        refusal_decision=refusal_decision,
        expected_answer_kind=answer_kind,
        safe_partial_support=safe_partial_support,
        difficulty=DifficultyLevel.EASY,
        engine_reference_case_id=(
            f"res71-reference:{candidate_id}"
            if origin is CaseOrigin.DETERMINISTIC_ENGINE_DERIVED
            else None
        ),
    )


def _commitment(
    item: ProductionAuthoringPlanItemV1, suffix: str = "a"
) -> ProductionCandidateCommitmentV1:
    payload_hash = hashlib.sha256(f"{item.candidate_id}:{suffix}".encode()).hexdigest()
    return ProductionCandidateCommitmentV1(item, "sha256:" + payload_hash)


def _feasibility_fixture(
    *,
    missing_cell: tuple[str, str] | None = None,
    global_author_batch: bool = False,
    paired_clusters: bool = False,
    locked_synthetic_cell: tuple[str, str] | None = None,
    omitted_error: ErrorClass | None = None,
) -> tuple[ProductionCandidateCommitmentV1, ...]:
    items: list[ProductionAuthoringPlanItemV1] = []
    for row in COVERAGE_MATRIX:
        for family in row.benchmark_families:
            requested_cell = (row.capability_id, family)
            actual_cell = ("C01", "F01") if requested_cell == missing_cell else requested_cell
            for replica in range(3):
                candidate_id = f"PSE-V1-CANDIDATE:fixture:{row.capability_id}:{family}:{replica}"
                if requested_cell == locked_synthetic_cell:
                    item = _item(
                        candidate_id,
                        capability_id=actual_cell[0],
                        benchmark_family=actual_cell[1],
                        origin=CaseOrigin.DETERMINISTIC_SYNTHETIC,
                        generator_family=f"fixture-generator:{requested_cell}",
                        cluster=f"fixture-locked:{requested_cell}",
                        seed_split=SplitName.PUBLIC_DEVELOPMENT,
                    )
                else:
                    refusal = actual_cell[0] == "C18"
                    item = _item(
                        candidate_id,
                        capability_id=actual_cell[0],
                        benchmark_family=actual_cell[1],
                        origin=None,
                        global_batch=global_author_batch,
                        refusal_decision=(
                            RefusalDecision.REQUIRED if refusal else RefusalDecision.PROHIBITED
                        ),
                        answer_kind=(
                            ExpectedAnswerKind.REFUSAL if refusal else ExpectedAnswerKind.ANSWER
                        ),
                        safe_partial_support=refusal,
                        omitted_error=omitted_error,
                    )
                items.append(item)
    for replica in range(173):
        candidate_id = f"PSE-V1-CANDIDATE:fixture:fill:{replica:03d}"
        items.append(
            _item(
                candidate_id,
                capability_id="C01",
                benchmark_family="F01",
                origin=None,
                global_batch=global_author_batch,
                omitted_error=omitted_error,
            )
        )
    if paired_clusters:
        items = [
            replace(item, isolation_cluster_id=f"fixture-pair:{index // 2:03d}")
            for index, item in enumerate(items)
        ]
    return tuple(_commitment(item) for item in items)


def _cross_cell_exact_shingle_pairs(
    commitments: tuple[ProductionCandidateCommitmentV1, ...],
) -> tuple[tuple[str, str], ...]:
    by_cell: dict[tuple[str, str], list[str]] = {}
    for commitment in commitments:
        item = commitment.item
        by_cell.setdefault((item.capability_id, item.benchmark_family), []).append(
            item.candidate_id
        )
    cells = sorted(by_cell)
    pairs = tuple(
        sorted(
            (
                min(by_cell[cells[index]][replica], by_cell[cells[index + 1]][replica]),
                max(by_cell[cells[index]][replica], by_cell[cells[index + 1]][replica]),
            )
            for index in range(0, 54, 2)
            for replica in range(3)
        )
    )
    return pairs


def test_production_candidate_namespace_rejects_qualification_ids() -> None:
    with pytest.raises(ValueError, match="PSE-V1-CANDIDATE"):
        _item("PSE-V1-QUALIFICATION:copy")


def test_bounded_shared_expert_batch_and_template_remain_one_cluster() -> None:
    items = (
        _item("PSE-V1-CANDIDATE:one", cluster="cluster:bounded"),
        _item("PSE-V1-CANDIDATE:two", cluster="cluster:bounded"),
    )
    validation = validate_production_isolation((_commitment(items[0]), _commitment(items[1], "b")))
    assert validation.atomic_cluster_count == 1
    assert validation.cluster_size_distribution == ((2, 1),)


def test_shared_template_cannot_be_fragmented_into_per_case_batches() -> None:
    one = _item("PSE-V1-CANDIDATE:one", cluster="cluster:shared", author_batch="batch:one")
    two = _item("PSE-V1-CANDIDATE:two", cluster="cluster:shared", author_batch="batch:two")
    with pytest.raises(ValueError, match="fragmented across expert batches"):
        validate_production_isolation((_commitment(one), _commitment(two, "b")))


def test_same_source_family_cannot_be_declared_as_independent_clusters() -> None:
    one = _item("PSE-V1-CANDIDATE:one", source_family="phase-a-family:shared")
    two = _item(
        "PSE-V1-CANDIDATE:two",
        source_family="phase-a-family:shared",
        cluster="cluster:other",
        author_batch="expert-batch:001C-test-b",
        template="protocol-template:001C-test-b",
    )
    with pytest.raises(ValueError, match="source-family fragmented"):
        validate_production_isolation((_commitment(one), _commitment(two, "b")))


def test_mutation_lineage_cannot_be_fragmented_from_parent_cluster() -> None:
    first = _item(
        "PSE-V1-CANDIDATE:mutation-one",
        cluster="cluster:mutation-one",
        origin=CaseOrigin.ADVERSARIAL_MUTATION,
        mutation_lineage="lineage:shared",
        parent_candidate_id="PSE-V1-CANDIDATE:parent",
        template="",
    )
    second = _item(
        "PSE-V1-CANDIDATE:mutation-two",
        cluster="cluster:mutation-two",
        origin=CaseOrigin.ADVERSARIAL_MUTATION,
        mutation_lineage="lineage:shared",
        parent_candidate_id="PSE-V1-CANDIDATE:parent",
        template="",
    )
    with pytest.raises(ValueError, match="mutation-lineage fragmented"):
        validate_production_isolation((_commitment(first), _commitment(second, "b")))


def test_generator_family_must_match_locked_seed_split() -> None:
    one = _item(
        "PSE-V1-CANDIDATE:seed-one",
        origin=CaseOrigin.DETERMINISTIC_SYNTHETIC,
        generator_family="generator-family:split-aware",
        seed_split=SplitName.PUBLIC_DEVELOPMENT,
        template="",
    )
    two = _item(
        "PSE-V1-CANDIDATE:seed-two",
        origin=CaseOrigin.DETERMINISTIC_SYNTHETIC,
        generator_family="generator-family:split-aware",
        seed_split=SplitName.HIDDEN_FINAL,
        template="",
    )
    with pytest.raises(ValueError):
        validate_production_isolation((_commitment(one), _commitment(two, "b")))


def test_exact_n434_feasibility_returns_aggregate_receipt_without_membership() -> None:
    receipt = validate_production_hard_feasibility(_feasibility_fixture())

    assert isinstance(receipt, ProductionFeasibilityReceiptV1)
    assert receipt.candidate_count == 434
    assert receipt.target_counts == (
        (SplitName.PUBLIC_DEVELOPMENT, 260),
        (SplitName.FROZEN_VALIDATION, 87),
        (SplitName.HIDDEN_FINAL, 87),
    )
    assert receipt.hard_cell_count_by_split == tuple(
        (split, 87) for split, _ in receipt.target_counts
    )
    assert not hasattr(receipt, "membership_map")


def test_v1_feasibility_receipt_cannot_be_reloaded_as_exact_v2(tmp_path: Path) -> None:
    receipt = validate_production_hard_feasibility(_feasibility_fixture())
    repository = tmp_path / "repo"
    repository.mkdir()
    production_root = tmp_path / "external"
    write_external_production_json(
        receipt,
        "production/receipts/legacy-feasibility.json",
        repository_root=repository,
        production_root=production_root,
    )

    with pytest.raises(ValueError, match="external production JSON"):
        read_external_production_json(
            "production/receipts/legacy-feasibility.json",
            ProductionExactFeasibilityReceiptV2,
            repository_root=repository,
            production_root=production_root,
        )


def test_exact_shingle_colocation_edges_bind_same_split_feasibility() -> None:
    commitments = _feasibility_fixture()
    left, right = commitments[0], commitments[1]
    assert left.item.isolation_cluster_id != right.item.isolation_cluster_id
    edge = (min(left.candidate_id, right.candidate_id), max(left.candidate_id, right.candidate_id))
    base = validate_production_hard_feasibility(commitments)
    constrained = validate_production_hard_feasibility(
        commitments,
        exact_shingle_colocation_pairs=(edge,),
    )

    assert constrained.atomic_cluster_count == base.atomic_cluster_count - 1
    assert constrained.exact_shingle_colocation_pair_count == 1
    assert constrained.exact_shingle_colocation_digest == canonical_hash((edge,))
    assert not hasattr(constrained, "membership_map")


def test_exact_shingle_colocation_rejects_conflicting_split_qualified_seed_locks() -> None:
    commitments = list(_feasibility_fixture())
    original_ids = {
        "PSE-V1-CANDIDATE:fixture:C08:F05:0",
        "PSE-V1-CANDIDATE:fixture:C08:F06:0",
    }
    commitments = [item for item in commitments if item.candidate_id not in original_ids]
    left = _item(
        "PSE-V1-CANDIDATE:fixture:co-location-lock-a",
        capability_id="C08",
        benchmark_family="F05",
        origin=CaseOrigin.DETERMINISTIC_SYNTHETIC,
        generator_family="fixture-generator:lock-a",
        cluster="fixture-lock:a",
        seed_split=SplitName.PUBLIC_DEVELOPMENT,
    )
    right = _item(
        "PSE-V1-CANDIDATE:fixture:co-location-lock-b",
        capability_id="C08",
        benchmark_family="F06",
        origin=CaseOrigin.DETERMINISTIC_SYNTHETIC,
        generator_family="fixture-generator:lock-b",
        cluster="fixture-lock:b",
        seed_split=SplitName.HIDDEN_FINAL,
    )
    commitments.extend((_commitment(left), _commitment(right)))
    edge = (min(left.candidate_id, right.candidate_id), max(left.candidate_id, right.candidate_id))

    with pytest.raises(ProductionFeasibilityBlocked, match="incompatible synthetic seed"):
        validate_production_hard_feasibility(
            tuple(commitments),
            exact_shingle_colocation_pairs=(edge,),
        )


@pytest.mark.parametrize("delta", (-1, 1))
def test_hard_feasibility_rejects_candidate_count_other_than_434(delta: int) -> None:
    commitments = _feasibility_fixture()
    invalid = commitments[:-1] if delta < 0 else (*commitments, commitments[0])
    with pytest.raises(ProductionFeasibilityBlocked, match="exactly 434"):
        validate_production_hard_feasibility(invalid)


def test_hard_feasibility_rejects_a_missing_d_v_h_capability_family_cell() -> None:
    with pytest.raises(ProductionFeasibilityBlocked):
        validate_production_hard_feasibility(_feasibility_fixture(missing_cell=("C18", "F14")))


def test_hard_feasibility_rejects_global_author_batch_and_seed_locked_coverage() -> None:
    with pytest.raises(ValueError, match="exceeds the public target capacity"):
        validate_production_hard_feasibility(_feasibility_fixture(global_author_batch=True))
    with pytest.raises(ProductionFeasibilityBlocked, match="FROZEN_VALIDATION"):
        validate_production_hard_feasibility(
            _feasibility_fixture(locked_synthetic_cell=("C08", "F05"))
        )


def test_hard_feasibility_rejects_unreachable_critical_error_protection_and_exact_fill() -> None:
    with pytest.raises(ProductionFeasibilityBlocked):
        validate_production_hard_feasibility(
            _feasibility_fixture(omitted_error=ErrorClass.BETWEEN_TO_WITHIN_MISINFERENCE)
        )
    with pytest.raises(ProductionFeasibilityBlocked):
        validate_production_hard_feasibility(_feasibility_fixture(paired_clusters=True))


def test_exact_oracle_survives_legacy_c03_f04_block_and_covers_frozen_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import dynamislm.benchmark.production as production

    commitments = _feasibility_fixture()
    pairs = _cross_cell_exact_shingle_pairs(commitments)
    legacy = production.validate_production_legacy_feasibility

    def block_legacy_base(
        values: tuple[ProductionCandidateCommitmentV1, ...],
        *,
        exact_shingle_colocation_pairs: tuple[tuple[str, str], ...] = (),
        diagnostic_anchor_requirements: dict[int, str] | None = None,
        diagnostic_component_ranks: dict[str, int] | None = None,
    ) -> ProductionFeasibilityReceiptV1:
        if not exact_shingle_colocation_pairs:
            raise ProductionFeasibilityBlocked(
                "no eligible atomic cluster for C03xF04 in PUBLIC_DEVELOPMENT"
            )
        return legacy(
            values,
            exact_shingle_colocation_pairs=exact_shingle_colocation_pairs,
            diagnostic_anchor_requirements=diagnostic_anchor_requirements,
            diagnostic_component_ranks=diagnostic_component_ranks,
        )

    monkeypatch.setattr(production, "validate_production_legacy_feasibility", block_legacy_base)
    result = validate_production_exact_feasibility(
        commitments,
        exact_shingle_colocation_pairs=pairs,
    )
    receipt = result.receipt

    assert isinstance(receipt, ProductionExactFeasibilityReceiptV2)
    assert receipt.status == "FEASIBLE"
    assert receipt.legacy_base_status == "BLOCKED"
    assert receipt.base_status == receipt.colocation_status == "FEASIBLE"
    assert receipt.exact_shingle_colocation_pair_count == 81
    assert receipt.exact_shingle_colocation_digest == canonical_hash(pairs)
    assert receipt.base_component_count == 434
    assert receipt.co_location_component_count == 353
    assert receipt.co_location_component_size_distribution == ((1, 272), (2, 81))
    assert receipt.c03_f04_eligible_component_count == 3
    assert receipt.c03_f04_public_feasible_component_count == 3
    assert receipt.canonical_self_reduction_status == "PASS"
    assert receipt.canonical_witness_digest is not None
    assert receipt.hard_cell_count_by_split == tuple(
        (split, 87) for split, _ in receipt.target_counts
    )
    assert receipt.c18_refusal_cell_count_by_split == tuple(
        (split, 14) for split, _ in receipt.target_counts
    )
    assert receipt.protected_critical_error_count_by_split == tuple(
        (split, len(CRITICAL_ERROR_CLASSES)) for split, _ in receipt.target_counts[1:]
    )
    assert receipt.feasibility_membership_persisted is False
    assert not hasattr(receipt, "membership_map")
    validate_production_exact_feasibility_receipt(receipt)
    from dynamislm.benchmark.production import bind_production_exact_feasibility_receipt
    from dynamislm.benchmark.production_batch import _validate_exact_feasibility_match

    forged = replace(receipt, base_model_digest="sha256:" + "0" * 64)
    with pytest.raises(ValueError, match="receipt digest mismatch"):
        validate_production_exact_feasibility_receipt(forged)
    stale = bind_production_exact_feasibility_receipt(
        replace(receipt, base_model_digest="sha256:" + "1" * 64)
    )
    with pytest.raises(ValueError, match="stale against current commitments"):
        _validate_exact_feasibility_match(stale, receipt)

    trace = result.private_diagnostic["c03_f04_trace"]
    assert isinstance(trace, tuple)
    assert len(trace) == 3
    assert all(
        {
            "component_key",
            "scientific_isolation_cluster_ids",
            "candidate_ids",
            "component_size",
            "expert_author_batch_ids",
            "protocol_template_ids",
            "partner_capability_family_cells",
            "mutation_descendants",
            "mutation_lineage_ids",
            "split_locks",
            "legacy_preferred_rank",
            "legacy_greedy_assigned",
            "legacy_assigned_for",
        }.issubset(entry)
        for entry in trace
    )
    assert result.private_diagnostic["c03_f04_greedy_false_negative"] is True


def test_exact_feasibility_can_skip_canonical_self_reduction() -> None:
    commitments = _feasibility_fixture()
    receipt = validate_production_exact_feasibility(
        commitments,
        exact_shingle_colocation_pairs=_cross_cell_exact_shingle_pairs(commitments),
        defer_colocation_conflict_reduction=True,
        use_legacy_hint=False,
        run_c03_f04_diagnostic=False,
        run_canonical_self_reduction=False,
    ).receipt

    assert receipt.status == "FEASIBLE"
    assert receipt.base_status == receipt.colocation_status == "FEASIBLE"
    assert receipt.canonical_self_reduction_status == "NOT_RUN"
    assert receipt.canonical_witness_digest is None
    assert not receipt.hard_cell_count_by_split
    validate_production_exact_feasibility_receipt(receipt)


def test_exact_canonical_self_reduction_ignores_arbitrary_solver_assignments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import dynamislm.benchmark.production as production

    solutions = ((0, 1), (0, 2), (1, 0))

    def run(
        ordered_solutions: tuple[tuple[int, ...], ...],
    ) -> tuple[tuple[str, tuple[int, ...] | None], list[tuple[int, ...]]]:
        observed: list[tuple[int, ...]] = []

        def fake_solve(
            _component_count: int,
            _constraints: tuple[object, ...],
            *,
            fixed: dict[int, int] | None = None,
            hint: tuple[int, ...] | None = None,
            solved_ranks: list[int] | None = None,
            **_kwargs: object,
        ) -> str:
            del hint
            assignment = next(
                (
                    candidate
                    for candidate in ordered_solutions
                    if all(candidate[index] == rank for index, rank in (fixed or {}).items())
                ),
                None,
            )
            if assignment is None:
                return "INFEASIBLE"
            observed.append(assignment)
            if solved_ranks is not None:
                solved_ranks.extend(assignment)
            return "FEASIBLE"

        monkeypatch.setattr(production, "_exact_completion_status", fake_solve)
        return production._canonical_split_ranks(2, (), (2, 2)), observed

    first, first_assignments = run(solutions)
    second, second_assignments = run(tuple(reversed(solutions)))
    assert first == second == ("PASS", (0, 1))
    assert first_assignments[0] != second_assignments[0]


def test_unknown_exact_completion_is_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    import dynamislm.benchmark.production as production

    monkeypatch.setattr(production, "_exact_completion_status", lambda *_args, **_kwargs: "UNKNOWN")
    assert production._canonical_split_ranks(1, (), (0,)) == ("BLOCKED", None)


def test_exact_unknown_status_stays_blocked_and_base_colocation_are_independent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import dynamislm.benchmark.production as production

    commitments = _feasibility_fixture()
    pairs = _cross_cell_exact_shingle_pairs(commitments)
    calls = 0

    def unknown_status(*_args: object, **_kwargs: object) -> str:
        nonlocal calls
        calls += 1
        return "UNKNOWN"

    monkeypatch.setattr(production, "_exact_completion_status", unknown_status)
    receipt = validate_production_exact_feasibility(
        commitments,
        exact_shingle_colocation_pairs=pairs,
    ).receipt

    assert receipt.status == "BLOCKED"
    assert receipt.base_status == receipt.colocation_status == "UNKNOWN"
    assert receipt.canonical_self_reduction_status == "NOT_RUN"
    assert receipt.canonical_witness_digest is None
    assert calls == 2 + receipt.c03_f04_eligible_component_count


def test_base_infeasible_with_feasible_colocation_is_an_implementation_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import dynamislm.benchmark.production as production

    commitments = _feasibility_fixture()
    pairs = _cross_cell_exact_shingle_pairs(commitments)
    statuses = iter(("INFEASIBLE", "FEASIBLE"))
    monkeypatch.setattr(
        production,
        "_exact_completion_status",
        lambda *_args, **_kwargs: next(statuses),
    )

    with pytest.raises(RuntimeError, match="base model is infeasible"):
        validate_production_exact_feasibility(
            commitments,
            exact_shingle_colocation_pairs=pairs,
        )


def test_exact_conflict_reduction_is_deterministic_and_rechecked() -> None:
    from dynamislm.benchmark.production import _ExactConstraint, _reduce_exact_conflict

    conflict = _ExactConstraint(
        "SYNTHETIC_LOCK:component",
        terms=((0, 0, 1), (0, 2, 1)),
        lower=2,
        upper=2,
    )
    assert _reduce_exact_conflict(
        1,
        (conflict,),
        structural_group_ids=("COLOCATION:component-a:component-b",),
    ) == ("COLOCATION:component-a:component-b", "SYNTHETIC_LOCK:component")


def test_exact_model_names_each_frozen_coverage_requirement() -> None:
    from dynamislm.benchmark.production import (
        PROSPECTIVE_SPLIT_COUNTS,
        _exact_requirement_constraints,
        _feasibility_clusters,
    )

    commitments = _feasibility_fixture()
    components = _feasibility_clusters(commitments)
    constraints = _exact_requirement_constraints(components, components)
    by_id = {item.group_id: item for item in constraints}
    row = next(item for item in COVERAGE_MATRIX if item.capability_id == "C03")
    tag = row.adversarial_tags[0]
    error = row.error_classes[0]

    assert len([group for group in constraints if group.group_id.startswith("CELL:")]) == 87 * 3
    assert (
        len([group for group in constraints if group.group_id.startswith("C18_REFUSAL:")]) == 14 * 3
    )
    assert f"CELL:C03:F04:{SplitName.PUBLIC_DEVELOPMENT.value}" in by_id
    assert f"ROW_TAG:C03:{tag}:{SplitName.FROZEN_VALIDATION.value}" in by_id
    assert f"ROW_ERROR:C03:{error.value}:{SplitName.HIDDEN_FINAL.value}" in by_id
    assert f"ANSWERABLE:{SplitName.PUBLIC_DEVELOPMENT.value}" in by_id
    critical = next(
        group
        for group in constraints
        if group.group_id.startswith(f"CRITICAL:{CRITICAL_ERROR_CLASSES[0].value}:")
    )
    assert critical.lower == 2
    assert len(critical.terms) >= 2
    assert tuple(
        group.group_id for group in constraints if group.group_id.startswith("COUNT:")
    ) == tuple(sorted(f"COUNT:{split.value}={count}" for split, count in PROSPECTIVE_SPLIT_COUNTS))


def test_incompatible_synthetic_locks_are_exactly_infeasible() -> None:
    from dynamislm.benchmark.production import (
        _exact_completion_status,
        _exact_requirement_constraints,
        _feasibility_clusters,
    )

    commitments = list(_feasibility_fixture())
    excluded = {
        "PSE-V1-CANDIDATE:fixture:C08:F05:0",
        "PSE-V1-CANDIDATE:fixture:C08:F06:0",
    }
    commitments = [item for item in commitments if item.candidate_id not in excluded]
    left = _item(
        "PSE-V1-CANDIDATE:fixture:exact-lock-a",
        capability_id="C08",
        benchmark_family="F05",
        origin=CaseOrigin.DETERMINISTIC_SYNTHETIC,
        generator_family="fixture-generator:exact-lock-a",
        cluster="fixture-exact-lock:a",
        seed_split=SplitName.PUBLIC_DEVELOPMENT,
    )
    right = _item(
        "PSE-V1-CANDIDATE:fixture:exact-lock-b",
        capability_id="C08",
        benchmark_family="F06",
        origin=CaseOrigin.DETERMINISTIC_SYNTHETIC,
        generator_family="fixture-generator:exact-lock-b",
        cluster="fixture-exact-lock:b",
        seed_split=SplitName.HIDDEN_FINAL,
    )
    commitments.extend((_commitment(left), _commitment(right)))
    edge = (min(left.candidate_id, right.candidate_id), max(left.candidate_id, right.candidate_id))
    components = _feasibility_clusters(
        tuple(commitments),
        exact_shingle_colocation_pairs=(edge,),
        allow_incompatible_locks=True,
    )
    constraints = _exact_requirement_constraints(components, components)
    lock = next(
        item
        for item in constraints
        if item.group_id.startswith("SYNTHETIC_LOCK:") and item.lower == 2
    )

    assert lock.lower == lock.upper == 2
    assert _exact_completion_status(len(components), (lock,)) == "INFEASIBLE"


def test_production_receipts_write_only_under_external_production_root(tmp_path: Path) -> None:
    receipt = bind_production_batch_manifest(
        ProductionBatchManifestV1(
            batch_id=PRODUCTION_BATCH_ID,
            manifest_version=PRODUCTION_BATCH_MANIFEST_VERSION,
            authoring_process_id=PRODUCTION_AUTHORING_PROCESS_ID,
            authoring_plan_digest=_SHA,
            candidate_store_receipt_digest=_SHA,
            qualification_exclusion_digest=_SHA,
            feasibility_receipt_digest=_SHA,
            candidate_count=434,
            human_approval_count=0,
            final_case_count=0,
            split_assignment_count=0,
            protected_store_count=0,
            manifest_digest=_SHA,
        )
    )
    validate_production_batch_manifest(receipt)
    repository_root = Path(__file__).resolve().parents[1]
    production_root = tmp_path / "external"
    path, _digest, _size = write_external_production_json(
        receipt,
        "production/exclusions/test.json",
        repository_root=repository_root,
        production_root=production_root,
    )
    restored, _read_digest, _read_size = read_external_production_json(
        path,
        ProductionBatchManifestV1,
        repository_root=repository_root,
        production_root=production_root,
    )
    assert restored == receipt
    with pytest.raises(ValueError, match="safe .json path"):
        write_external_production_json(
            receipt,
            "production/../candidate.json",
            repository_root=repository_root,
            production_root=production_root,
        )
    with pytest.raises(ValueError, match="outside the public Git repository"):
        write_external_production_json(
            receipt,
            "production/exclusions/inside.json",
            repository_root=repository_root,
            production_root=repository_root,
        )


def _production_packet(
    question: str, *, candidate_id: str = "PSE-V1-CANDIDATE:test"
) -> CandidateReviewPacket:
    source = _semantic_cell_candidate("C01", "F01")
    contamination = replace(
        source.contamination,
        protocol_template_id="test-protocol-template:001C",
        expert_author_batch_id="test-expert-batch:001C",
        normalized_text_sha256=normalized_text_sha256(question),
        exact_shingle_digest=exact_shingle_digest(question),
        fuzzy_fingerprint=fuzzy_fingerprint(question),
    )
    packet = replace(
        source,
        candidate_id=candidate_id,
        question=question,
        input=replace(source.input, question_text=question),
        proposed_provenance=replace(
            source.proposed_provenance,
            author_id=PRODUCTION_AUTHORING_PROCESS_ID,
        ),
        contamination=contamination,
        isolation=replace(
            source.isolation,
            source_family_id=contamination.source_family_id,
            isolation_cluster_id="test-isolation-cluster:001C",
        ),
        candidate_payload_hash="sha256:" + "0" * 64,
        proposed_approval_digest="sha256:" + "0" * 64,
    )
    return bind_candidate_review_packet(packet)


def _qualification_exclusion(
    question: str,
    *,
    candidate_id: str = "PSE-V1-QUALIFICATION:TEST:ORIGINAL",
    payload_hash: str = "sha256:" + "b" * 64,
    seed_blocks: tuple[str, ...] = (),
    seed_namespaces: tuple[str, ...] = (),
    mutation_lineage_ids: tuple[str, ...] = (),
    mutation_seed_values: tuple[int, ...] = (),
    evidence_spans: tuple[tuple[str, str], ...] = (),
) -> QualificationExclusionCommitmentV1:
    entry = QualificationExclusionCandidateV1(
        candidate_id=candidate_id,
        candidate_payload_hash=payload_hash,
        question_text=question,
        exact_question_sha256="sha256:" + hashlib.sha256(question.encode()).hexdigest(),
        normalized_question_sha256=normalized_text_sha256(question),
        question_13_token_shingle_hashes=tuple(sorted(exact_13_token_shingles(question))),
        seed_blocks=seed_blocks,
        seed_namespaces=seed_namespaces,
        generator_seed_identities=(),
        mutation_lineage_ids=mutation_lineage_ids,
        mutation_seed_values=mutation_seed_values,
        evidence_span_identities=evidence_spans,
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


def _run_exclusion_identity(values: dict[str, object]) -> None:
    validate_production_exclusion_identity(
        candidate_id=cast(str, values["candidate_id"]),
        candidate_payload_hash=cast(str, values["candidate_payload_hash"]),
        question=cast(str, values["question"]),
        seed_blocks=cast(tuple[str, ...], values["seed_blocks"]),
        seed_namespaces=cast(tuple[str, ...], values["seed_namespaces"]),
        mutation_lineage_ids=cast(tuple[str, ...], values["mutation_lineage_ids"]),
        mutation_seed_values=cast(tuple[int, ...], values["mutation_seed_values"]),
        evidence_span_identities=cast(
            tuple[tuple[str, str], ...], values["evidence_span_identities"]
        ),
        commitment=cast(QualificationExclusionCommitmentV1, values["commitment"]),
    )


def test_qualification_candidate_id_payload_seed_lineage_and_span_reuse_reject() -> None:
    exclusion = _qualification_exclusion(
        "private original question with enough synthetic text to test matching",
        payload_hash="sha256:" + "c" * 64,
        seed_blocks=("opaque-seed-block",),
        seed_namespaces=("PSE-V1-QUALIFICATION/generator/opaque-seed-block",),
        mutation_lineage_ids=("qualification-mutation-lineage",),
        mutation_seed_values=(17,),
        evidence_spans=(("qualification-span:001", _SHA),),
    )
    identity = {
        "candidate_id": "PSE-V1-CANDIDATE:synthetic-test",
        "candidate_payload_hash": "sha256:" + "d" * 64,
        "question": "independent question material for exclusion test",
        "seed_blocks": (),
        "seed_namespaces": (),
        "mutation_lineage_ids": (),
        "mutation_seed_values": (),
        "evidence_span_identities": (),
        "commitment": exclusion,
    }
    for change, message in (
        ({"candidate_id": "PSE-V1-QUALIFICATION:TEST:ORIGINAL"}, "qualification IDs"),
        ({"candidate_payload_hash": "sha256:" + "c" * 64}, "payload"),
        ({"seed_blocks": ("opaque-seed-block",)}, "seed block"),
        (
            {"seed_namespaces": ("PSE-V1-QUALIFICATION/generator/opaque-seed-block",)},
            "seed block",
        ),
        ({"mutation_lineage_ids": ("qualification-mutation-lineage",)}, "lineage"),
        ({"mutation_seed_values": (17,)}, "mutation seed"),
        ({"evidence_span_identities": (("qualification-span:001", _SHA),)}, "evidence-span"),
        ({"evidence_span_identities": (("other-span", _SHA),)}, "evidence-span"),
    ):
        with pytest.raises(ValueError, match=message):
            _run_exclusion_identity(identity | change)
    different_span = ("different-span-from-same-paper", "sha256:" + "e" * 64)
    _run_exclusion_identity(identity | {"evidence_span_identities": (different_span,)})


def test_production_question_exclusion_rejects_exact_normalized_and_shingle_clones() -> None:
    original = (
        "synthetic lock test: alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu"
    )
    for question, excluded_question in (
        (original, original),
        (
            "  SYNTHETIC lock test: alpha beta gamma delta epsilon zeta eta theta "
            "iota kappa lambda mu  ",
            original,
        ),
    ):
        packet = _production_packet(question)
        with pytest.raises(ValueError, match="canonical or normalized question"):
            validate_production_candidate_against_qualification_exclusion(
                packet,
                _qualification_exclusion(excluded_question),
            )

    phrase = "one two three four five six seven eight nine ten eleven twelve thirteen fourteen"
    packet = _production_packet(f"current prompt {phrase} current end")
    with pytest.raises(ValueError, match="exact-shingle"):
        validate_production_candidate_against_qualification_exclusion(
            packet,
            _qualification_exclusion(f"historical prompt {phrase} historical end"),
        )


def test_production_question_exclusion_uses_frozen_blocking_fuzzy_threshold() -> None:
    tokens = [f"term{index:03d}" for index in range(104)]
    changed = [
        token.replace("term", "xerm") if index % 12 == 0 else token
        for index, token in enumerate(tokens)
    ]
    original = " ".join(tokens)
    near_clone = " ".join(changed)
    assert not (exact_13_token_shingles(original) & exact_13_token_shingles(near_clone))
    packet = _production_packet(near_clone)
    with pytest.raises(ValueError, match="blocking fuzzy overlap"):
        validate_production_candidate_against_qualification_exclusion(
            packet,
            _qualification_exclusion(original),
        )


def test_public_training_exclusion_has_digests_and_no_question_or_seed_text() -> None:
    entries = tuple(
        QualificationExclusionCandidateV1(
            candidate_id=f"PSE-V1-QUALIFICATION:TEST:{index:03d}",
            candidate_payload_hash="sha256:" + hashlib.sha256(str(index).encode()).hexdigest(),
            question_text=f"synthetic private training exclusion question {index:03d}",
            exact_question_sha256=(
                "sha256:"
                + hashlib.sha256(
                    f"synthetic private training exclusion question {index:03d}".encode()
                ).hexdigest()
            ),
            normalized_question_sha256=normalized_text_sha256(
                f"synthetic private training exclusion question {index:03d}"
            ),
            question_13_token_shingle_hashes=(),
            seed_blocks=(f"private-seed-block-{index:03d}",),
            seed_namespaces=(f"private-seed-namespace-{index:03d}",),
            generator_seed_identities=(),
            mutation_lineage_ids=(),
            mutation_seed_values=(),
            evidence_span_identities=(),
        )
        for index in range(101)
    )
    commitment = bind_qualification_exclusion_commitment(
        QualificationExclusionCommitmentV1(
            batch_id=QUALIFICATION_001B_BATCH_ID,
            version=QUALIFICATION_EXCLUSION_VERSION,
            qualification_manifest_digest=_SHA,
            qualification_store_receipt_digest=_SHA,
            authoring_plan_digest=_SHA,
            seed_input_digest=_SHA,
            candidate_count=101,
            entries=entries,
            commitment_digest="sha256:" + "0" * 64,
        )
    )
    public = build_qualification_training_exclusion_manifest(
        commitment,
        private_index_relative_path="production/exclusions/qualification-001B-private.json",
        private_index_digest=_SHA,
    )
    serialized = canonical_json(public)
    assert isinstance(public, QualificationTrainingExclusionManifestV1)
    assert public.candidate_count == 101
    assert "synthetic private training exclusion question" not in serialized
    assert "private-seed-block" not in serialized
    assert all(item.candidate_id.startswith("PSE-V1-QUALIFICATION:") for item in public.entries)


@pytest.mark.parametrize(
    ("field", "secret"),
    (
        ("production candidate question", "Synthetic private question phrase 001C"),
        ("private production expected answer", "SYNTHETIC_EXPECTED_GOLD_001C"),
        ("private production seed", "private-seed-value-001C"),
    ),
)
def test_production_repository_leak_guard_rejects_question_answer_and_seed(
    tmp_path: Path, field: str, secret: str
) -> None:
    repository = tmp_path / "public-repository"
    repository.mkdir()
    subprocess.run(("git", "init", str(repository)), check=True, capture_output=True)
    subprocess.run(
        ("git", "-C", str(repository), "config", "user.email", "test@example.com"), check=True
    )
    subprocess.run(("git", "-C", str(repository), "config", "user.name", "test"), check=True)
    readme = repository / "README.md"
    readme.write_text("synthetic leak guard fixture\n", encoding="utf-8")
    subprocess.run(("git", "-C", str(repository), "add", "README.md"), check=True)
    subprocess.run(
        ("git", "-C", str(repository), "commit", "-m", "fixture"), check=True, capture_output=True
    )
    report = repository / "production-report.json"
    report.write_text(f'{{"private":"{secret}"}}\n', encoding="utf-8")

    with pytest.raises(ValueError, match=field):
        validate_production_private_material_absent(
            ((field, secret),),
            repository_root=repository,
        )


def test_transient_cache_bytes_and_process_rss_are_separate_metrics(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    nested = cache / "nested"
    nested.mkdir(parents=True)
    (cache / "first.bin").write_bytes(b"abc")
    (nested / "second.bin").write_bytes(b"12345")
    tracker = TransientCachePeakTracker(cache)
    checkpoint = tracker.checkpoint("after-fixture-write")
    assert checkpoint.transient_cache_bytes == measure_transient_cache_bytes(cache) == 8
    with pytest.raises(ValueError, match="unique non-empty"):
        tracker.checkpoint("after-fixture-write")
    with pytest.raises(ValueError, match="2 GB hard limit"):
        _enforce_transient_cache_limit(TRANSIENT_CACHE_MAX_BYTES + 1)

    receipt = TransientCacheMeasurementV1(
        cache_root=DEFAULT_TRANSIENT_CACHE_ROOT.as_posix(),
        hard_limit_bytes=TRANSIENT_CACHE_MAX_BYTES,
        checkpoints=(TransientCacheCheckpointV1("synthetic-metric-fixture", 8, 321.0),),
        transient_cache_peak_bytes=8,
        process_peak_rss_mb=321.0,
    )
    metrics = receipt.public_metrics()
    assert metrics["TRANSIENT_CACHE_PEAK_MB"] == 0.000008
    assert metrics["PROCESS_PEAK_RSS_MB"] == 321.0
    assert metrics["TRANSIENT_CACHE_PEAK_MB"] != metrics["PROCESS_PEAK_RSS_MB"]
    assert metrics["PROCESS_RSS_REPORTED_SEPARATELY"] == "YES"


def _store_roundtrip_fixture() -> tuple[
    tuple[CandidateReviewPacket, ...],
    QualificationExclusionCommitmentV1,
    ProductionAuthoringPlanV1,
]:
    from dynamislm.benchmark.authoring import authoring_recipe_registry_digest
    from dynamislm.benchmark.coverage import coverage_manifest_digest
    from dynamislm.benchmark.production import (
        PRODUCTION_AUTHORING_PLAN_VERSION,
        ProductionAuthoringPlanV1,
        bind_production_authoring_plan,
        production_plan_item_from_packet,
    )

    exclusion = _qualification_exclusion("synthetic storage exclusion fixture")
    packets = tuple(
        _production_packet(
            " ".join(
                hashlib.sha256(f"storage-fixture:{candidate}:{word}".encode()).hexdigest()[:10]
                for word in range(18)
            ),
            candidate_id=f"PSE-V1-CANDIDATE:store:{candidate:03d}",
        )
        for candidate in range(434)
    )
    items = tuple(production_plan_item_from_packet(packet) for packet in packets)
    return (
        packets,
        exclusion,
        bind_production_authoring_plan(
            ProductionAuthoringPlanV1(
                batch_id=PRODUCTION_BATCH_ID,
                plan_version=PRODUCTION_AUTHORING_PLAN_VERSION,
                authoring_process_id=PRODUCTION_AUTHORING_PROCESS_ID,
                target_case_count=434,
                coverage_matrix_digest=coverage_manifest_digest(),
                recipe_registry_digest=authoring_recipe_registry_digest(),
                qualification_exclusion_digest=exclusion.commitment_digest,
                items=items,
                plan_digest="sha256:" + "0" * 64,
            )
        ),
    )


def _bounded_semantic_packet_fixture(
    packets: tuple[CandidateReviewPacket, ...],
) -> tuple[CandidateReviewPacket, ...]:
    clustered = []
    for index, packet in enumerate(packets):
        batch = index // 2
        family_id = f"fixture-source-family:{packet.candidate_id}"
        clustered.append(
            bind_candidate_review_packet(
                replace(
                    packet,
                    contamination=replace(
                        packet.contamination,
                        source_family_id=family_id,
                        expert_author_batch_id=f"fixture-bounded-batch:{batch:03d}",
                        protocol_template_id=f"fixture-template:{batch:03d}",
                    ),
                    isolation=replace(
                        packet.isolation,
                        source_family_id=family_id,
                        isolation_cluster_id=f"fixture-semantic-cluster:{batch:03d}",
                    ),
                    candidate_payload_hash="sha256:" + "0" * 64,
                    proposed_approval_digest="sha256:" + "0" * 64,
                )
            )
        )
    return tuple(clustered)


def _stub_production_store_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    import dynamislm.benchmark.production_store as store
    from dynamislm.benchmark.production import (
        ProductionCandidateCommitmentV1,
        production_plan_item_from_packet,
    )

    monkeypatch.setattr(store, "validate_production_authoring_plan", lambda _plan: None)
    monkeypatch.setattr(store, "validate_qualification_exclusion_commitment", lambda _item: None)
    monkeypatch.setattr(
        store,
        "validate_production_candidate_set_against_qualification_exclusion",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        store,
        "validate_production_exact_feasibility",
        lambda _items, **_kwargs: SimpleNamespace(receipt=SimpleNamespace(status="FEASIBLE")),
    )
    monkeypatch.setattr(
        store,
        "write_external_production_json",
        lambda *_args, **_kwargs: ("", _SHA, 0),
    )
    monkeypatch.setattr(
        store,
        "validate_production_candidate_set",
        lambda packets, **_kwargs: tuple(
            sorted(
                (
                    ProductionCandidateCommitmentV1(
                        production_plan_item_from_packet(packet),
                        packet.candidate_payload_hash,
                    )
                    for packet in packets
                ),
                key=lambda item: item.candidate_id.encode("utf-8"),
            )
        ),
    )


def test_production_manifest_rejects_forged_self_consistent_component_digest() -> None:
    from dataclasses import replace as dataclass_replace

    from dynamislm.benchmark.production import (
        PRODUCTION_BATCH_MANIFEST_VERSION,
        ProductionBatchManifestV1,
        bind_production_batch_manifest,
        validate_production_batch_manifest_bindings,
    )

    manifest = bind_production_batch_manifest(
        ProductionBatchManifestV1(
            batch_id=PRODUCTION_BATCH_ID,
            manifest_version=PRODUCTION_BATCH_MANIFEST_VERSION,
            authoring_process_id=PRODUCTION_AUTHORING_PROCESS_ID,
            authoring_plan_digest=_SHA,
            candidate_store_receipt_digest=_SHA,
            qualification_exclusion_digest=_SHA,
            feasibility_receipt_digest=_SHA,
            candidate_count=434,
            human_approval_count=0,
            final_case_count=0,
            split_assignment_count=0,
            protected_store_count=0,
            manifest_digest="sha256:" + "0" * 64,
        )
    )
    validate_production_batch_manifest_bindings(
        manifest,
        authoring_plan_digest=_SHA,
        candidate_store_receipt_digest=_SHA,
        qualification_exclusion_digest=_SHA,
        feasibility_receipt_digest=_SHA,
    )
    forged = bind_production_batch_manifest(
        dataclass_replace(
            manifest,
            candidate_store_receipt_digest="sha256:" + "c" * 64,
            manifest_digest="sha256:" + "0" * 64,
        )
    )
    with pytest.raises(ValueError, match="exact artifact"):
        validate_production_batch_manifest_bindings(
            forged,
            authoring_plan_digest=_SHA,
            candidate_store_receipt_digest=_SHA,
            qualification_exclusion_digest=_SHA,
            feasibility_receipt_digest=_SHA,
        )


def test_production_review_queue_is_decision_free_and_deterministic() -> None:
    from dataclasses import fields as dataclass_fields

    from dynamislm.benchmark.production import (
        ProductionReviewQueueEntryV1,
        build_production_review_queue,
        validate_production_review_queue,
    )

    packets, _exclusion, _plan = _store_roundtrip_fixture()
    queue = build_production_review_queue(packets)
    validate_production_review_queue(queue, packets)
    assert len(queue.entries) == 434
    assert not {
        "reviewer_id",
        "reviewer_identity",
        "approval_timestamp",
        "decision",
    }.intersection(item.name for item in dataclass_fields(ProductionReviewQueueEntryV1))
    assert queue == build_production_review_queue(packets)


def test_production_candidate_store_refuses_blocked_exact_feasibility(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import dynamislm.benchmark.production_store as store

    packets, exclusion, plan = _store_roundtrip_fixture()
    _stub_production_store_validation(monkeypatch)
    monkeypatch.setattr(
        store,
        "validate_production_exact_feasibility",
        lambda _items, **_kwargs: SimpleNamespace(receipt=SimpleNamespace(status="BLOCKED")),
    )
    repository = tmp_path / "repo"
    repository.mkdir()
    production_root = tmp_path / "external"

    with pytest.raises(ValueError, match="exact production feasibility is BLOCKED"):
        store.write_production_candidate_store(
            packets,
            plan,
            repository_root=repository,
            production_root=production_root,
            qualification_exclusions=exclusion,
        )
    assert not production_root.exists()


def test_production_candidate_store_recovers_staging_and_roundtrips_434_packets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import dynamislm.benchmark.production_store as store

    packets, exclusion, plan = _store_roundtrip_fixture()
    _stub_production_store_validation(monkeypatch)
    repository = tmp_path / "repo"
    repository.mkdir()
    production_root = tmp_path / "external"
    batch_key = hashlib.sha256(PRODUCTION_BATCH_ID.encode()).hexdigest()[:24]
    final_store = production_root / "production" / "candidates" / batch_key
    receipt_path = production_root / "production" / "receipts" / f"{batch_key}.json"

    def fixture_write_bytes(path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def interrupt_after_plan(path: Path, data: bytes) -> None:
        fixture_write_bytes(path, data)
        if path.name == "authoring-plan.json":
            raise RuntimeError("synthetic interrupted staging")

    monkeypatch.setattr(store, "_atomic_write_bytes", interrupt_after_plan)
    with pytest.raises(RuntimeError, match="interrupted staging"):
        store.write_production_candidate_store(
            packets,
            plan,
            repository_root=repository,
            production_root=production_root,
            qualification_exclusions=exclusion,
        )
    assert not final_store.exists()
    assert not receipt_path.exists()

    monkeypatch.setattr(store, "_atomic_write_bytes", fixture_write_bytes)
    receipt = store.write_production_candidate_store(
        packets,
        plan,
        repository_root=repository,
        production_root=production_root,
        qualification_exclusions=exclusion,
    )
    restored = store.read_production_candidate_store(
        receipt,
        repository_root=repository,
        production_root=production_root,
        qualification_exclusions=exclusion,
    )
    assert len(restored) == 434
    assert restored == packets
    assert (
        store.write_production_candidate_store(
            packets,
            plan,
            repository_root=repository,
            production_root=production_root,
            qualification_exclusions=exclusion,
        )
        == receipt
    )
    assert not (production_root / "production" / "staging" / batch_key).exists()


def test_production_candidate_store_rejects_conflicting_completed_rerun(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dataclasses import replace as dataclass_replace

    import dynamislm.benchmark.production_store as store
    from dynamislm.benchmark.authoring import authoring_recipe_registry_digest
    from dynamislm.benchmark.coverage import coverage_manifest_digest
    from dynamislm.benchmark.pre_review import bind_candidate_review_packet
    from dynamislm.benchmark.production import (
        PRODUCTION_AUTHORING_PLAN_VERSION,
        ProductionAuthoringPlanV1,
        bind_production_authoring_plan,
        production_plan_item_from_packet,
    )

    packets, exclusion, plan = _store_roundtrip_fixture()
    _stub_production_store_validation(monkeypatch)
    repository = tmp_path / "repo"
    repository.mkdir()
    production_root = tmp_path / "external"
    receipt = store.write_production_candidate_store(
        packets,
        plan,
        repository_root=repository,
        production_root=production_root,
        qualification_exclusions=exclusion,
    )
    altered_packet = packets[0]
    altered_packet = bind_candidate_review_packet(
        dataclass_replace(
            altered_packet,
            question=altered_packet.question + " changed metadata",
            input=dataclass_replace(
                altered_packet.input,
                question_text=altered_packet.question + " changed metadata",
            ),
            candidate_payload_hash="sha256:" + "0" * 64,
            proposed_approval_digest="sha256:" + "0" * 64,
        )
    )
    altered_packets = tuple(sorted((altered_packet, *packets[1:]), key=lambda p: p.candidate_id))
    altered_plan = bind_production_authoring_plan(
        ProductionAuthoringPlanV1(
            batch_id=PRODUCTION_BATCH_ID,
            plan_version=PRODUCTION_AUTHORING_PLAN_VERSION,
            authoring_process_id=PRODUCTION_AUTHORING_PROCESS_ID,
            target_case_count=434,
            coverage_matrix_digest=coverage_manifest_digest(),
            recipe_registry_digest=authoring_recipe_registry_digest(),
            qualification_exclusion_digest=exclusion.commitment_digest,
            items=tuple(production_plan_item_from_packet(packet) for packet in altered_packets),
            plan_digest="sha256:" + "0" * 64,
        )
    )
    with pytest.raises(ValueError, match="conflicts with the exact rerun"):
        store.write_production_candidate_store(
            altered_packets,
            altered_plan,
            repository_root=repository,
            production_root=production_root,
            qualification_exclusions=exclusion,
        )
    assert (
        store.read_production_candidate_store(
            receipt,
            repository_root=repository,
            production_root=production_root,
            qualification_exclusions=exclusion,
        )
        == packets
    )


@pytest.mark.parametrize(
    ("first", "second"),
    (
        (
            "alpha bravo charlie delta echo foxtrot golf hotel india juliet "
            "kilo lima mike november oscar",
            "alpha bravo charlie delta echo foxtrot golf hotel india juliet "
            "kilo lima mike november oscar",
        ),
        (
            "Alpha bravo charlie delta echo foxtrot golf hotel india juliet "
            "kilo lima mike november oscar",
            "alpha  bravo charlie delta echo foxtrot golf hotel india juliet "
            "kilo lima mike november oscar",
        ),
    ),
    ids=("exact-question", "normalized-question"),
)
def test_production_duplication_audit_rejects_exact_question_duplicates(
    first: str, second: str
) -> None:
    from dynamislm.benchmark.production import audit_production_duplicates

    packets, _exclusion, _plan = _store_roundtrip_fixture()
    packets = (
        _production_packet(first, candidate_id=packets[0].candidate_id),
        _production_packet(second, candidate_id=packets[1].candidate_id),
        *packets[2:],
    )
    with pytest.raises(ValueError, match="duplication audit"):
        audit_production_duplicates(packets)


def test_production_duplication_audit_rejects_exact_payload_duplicates() -> None:
    from dynamislm.benchmark.production import audit_production_duplicates

    packets, _exclusion, _plan = _store_roundtrip_fixture()
    left = _production_packet("unrelated first payload", candidate_id=packets[0].candidate_id)
    right = _production_packet("unrelated second payload", candidate_id=packets[1].candidate_id)
    right = replace(right, candidate_payload_hash=left.candidate_payload_hash)
    with pytest.raises(ValueError, match="duplication audit"):
        audit_production_duplicates((left, right, *packets[2:]))


def test_exact_13_token_only_overlap_is_pending_and_not_fuzzy_blocked() -> None:
    from dynamislm.benchmark.production import audit_production_duplicates

    packets, _exclusion, _plan = _store_roundtrip_fixture()
    shared = (
        "copper moon cedar field amber track silver gate teal runner "
        "violet marker cobalt shift jade signal coral phase"
    )
    left = _production_packet(f"{shared} left marker", candidate_id=packets[0].candidate_id)
    right = _production_packet(f"{shared} right marker", candidate_id=packets[1].candidate_id)
    audit = audit_production_duplicates((left, right, *packets[2:]))

    edge = tuple(sorted((left.candidate_id, right.candidate_id)))
    assert audit.exact_payload_duplicate_pairs == 0
    assert audit.exact_question_duplicate_pairs == 0
    assert audit.normalized_question_duplicate_pairs == 0
    assert audit.exact_13_token_overlap_pairs == 1
    assert audit.blocking_fuzzy_overlap_pairs == 0
    assert audit.unrelated_blocking_overlaps == 0
    assert audit.exact_shingle_colocation_pairs == (edge,)


def test_same_template_batch_origin_and_cluster_do_not_authorize_fuzzy_overlap() -> None:
    from dynamislm.benchmark.production import audit_production_duplicates

    packets, _exclusion, _plan = _store_roundtrip_fixture()
    first = "alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo lima"
    second = "alpha bravo charlie delta echo foxtrot golf hotel india julliet kilo lima"
    left = _production_packet(first, candidate_id=packets[0].candidate_id)
    right = _production_packet(second, candidate_id=packets[1].candidate_id)
    assert left.proposed_provenance.origin_class is right.proposed_provenance.origin_class
    assert left.contamination.expert_author_batch_id == right.contamination.expert_author_batch_id
    assert left.contamination.protocol_template_id == right.contamination.protocol_template_id
    assert left.isolation.isolation_cluster_id == right.isolation.isolation_cluster_id
    with pytest.raises(ValueError, match="duplication audit"):
        audit_production_duplicates((left, right, *packets[2:]))


def test_frozen_fuzzy_thresholds_block_token_character_and_edit_only_matches() -> None:
    import re
    from random import Random

    from dynamislm.benchmark.contamination import (
        normalize_text,
        normalized_edit_similarity_at_least,
    )
    from dynamislm.benchmark.production import _token_grams, audit_production_duplicates

    def token_surface(seed: int) -> str:
        rng = Random(seed)
        return " ".join(rng.choice(("alpha", "bravo")) for _ in range(100))

    token_pair = (token_surface(0), token_surface(3))
    character_pair = (
        "copper_moon cedar_field amber_track silver_gate teal_runner violet_marker "
        "cobalt_shift jade_signal coral_phase indigo_test saffron_frame graphite_device "
        "force_plate",
        "copper_moon cedar_field amber_track silver_gate teal_runner violet_marker "
        "cobalt_shift jade_signal coral_phase indigo_test saffron_frame graphite_devicx "
        "force_plate",
    )
    edit_tokens = [f"term{index:03d}" for index in range(104)]
    edit_pair = (
        " ".join(edit_tokens),
        " ".join(
            token.replace("term", "xerm") if index % 12 == 0 else token
            for index, token in enumerate(edit_tokens)
        ),
    )

    def token_jaccard(left: str, right: str) -> float:
        def tokenize(value: str) -> tuple[str, ...]:
            return tuple(re.findall(r"\w+|[^\w\s]", normalize_text(value), flags=re.UNICODE))

        first, second = _token_grams(tokenize(left)), _token_grams(tokenize(right))
        union = first | second
        return len(first & second) / len(union) if union else 1.0

    def character_jaccard(left: str, right: str) -> float:
        first_text, second_text = normalize_text(left), normalize_text(right)
        first = {first_text[index : index + 5] for index in range(max(0, len(first_text) - 4))}
        second = {second_text[index : index + 5] for index in range(max(0, len(second_text) - 4))}
        union = first | second
        return len(first & second) / len(union) if union else 1.0

    assert token_jaccard(*token_pair) >= 0.85
    assert not exact_13_token_shingles(token_pair[0]) & exact_13_token_shingles(token_pair[1])
    assert character_jaccard(*character_pair) >= 0.85
    assert not exact_13_token_shingles(character_pair[0]) & exact_13_token_shingles(
        character_pair[1]
    )
    assert normalized_edit_similarity_at_least(
        normalize_text(edit_pair[0]), normalize_text(edit_pair[1]), 0.90
    )
    assert not exact_13_token_shingles(edit_pair[0]) & exact_13_token_shingles(edit_pair[1])

    packets, _exclusion, _plan = _store_roundtrip_fixture()
    replaced = []
    for index, question in enumerate((*token_pair, *character_pair, *edit_pair)):
        replaced.append(_production_packet(question, candidate_id=packets[index].candidate_id))
    with pytest.raises(ValueError, match="duplication audit"):
        audit_production_duplicates((*replaced, *packets[6:]))


def _declared_mutation_fixture(
    parent: CandidateReviewPacket, child_id: str
) -> CandidateReviewPacket:
    from dynamislm.benchmark.constants import AuthorityKind
    from dynamislm.benchmark.contracts import AuthorityBinding
    from dynamislm.benchmark.pre_review import (
        CandidateParentBinding,
        candidate_scientific_projection,
    )

    child_question = parent.question + " bravo sentinel"
    lineage = "PSE-V1-LINEAGE:synthetic-review-fixture"
    parent_binding = CandidateParentBinding(
        parent_candidate_id=parent.candidate_id,
        parent_candidate_version=parent.candidate_version,
        parent_candidate_payload_hash=parent.candidate_payload_hash,
        parent_origin_class=parent.proposed_provenance.origin_class,
        mutation_lineage_id=lineage,
    )
    parent_authority = AuthorityBinding(
        authority_kind=AuthorityKind.MUTATION_PARENT.value,
        source_reference_id=parent.candidate_id,
        version=parent.candidate_version,
        digest=parent.candidate_payload_hash,
        governed_field_ids=("provenance.parent_case_hash",),
    )
    child = _production_packet(child_question, candidate_id=child_id)
    child = replace(
        child,
        input=replace(child.input, question_text=child_question),
        authority=(*child.authority, parent_authority),
        parent_candidate_binding=parent_binding,
        proposed_provenance=replace(
            child.proposed_provenance,
            origin_class=CaseOrigin.ADVERSARIAL_MUTATION,
            mutation_lineage_id=lineage,
            parent_origin_class=parent.proposed_provenance.origin_class,
            mutation_operator="synthetic-fixture-question-extension",
            mutation_version="1.0.0",
            mutation_seed=4096,
            changed_fields=(),
            authority_lineage=tuple(
                sorted({*child.proposed_provenance.authority_lineage, parent.candidate_id})
            ),
        ),
        contamination=replace(
            child.contamination,
            source_family_id=parent.contamination.source_family_id,
            expert_author_batch_id=parent.contamination.expert_author_batch_id,
            protocol_template_id=parent.contamination.protocol_template_id,
        ),
        isolation=parent.isolation,
        candidate_payload_hash="sha256:" + "0" * 64,
        proposed_approval_digest="sha256:" + "0" * 64,
    )
    parent_projection = candidate_scientific_projection(parent)
    child_projection = candidate_scientific_projection(child)
    changed_fields = tuple(
        sorted(
            (
                name
                for name in parent_projection
                if parent_projection[name] != child_projection[name]
            ),
            key=lambda value: value.encode("utf-8"),
        )
    )
    child = replace(
        child,
        proposed_provenance=replace(
            child.proposed_provenance,
            changed_fields=changed_fields,
        ),
    )
    return bind_candidate_review_packet(child)


def test_declared_parent_child_overlap_is_allowed_and_queued_parent_first() -> None:
    from dataclasses import fields as dataclass_fields

    from dynamislm.benchmark.production import (
        ProductionReviewQueueEntryV1,
        audit_production_duplicates,
        build_production_review_queue,
    )

    packets, _exclusion, _plan = _store_roundtrip_fixture()
    parent_question = (
        "alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo lima "
        "mike november oscar papa quebec romeo sierra tango"
    )
    parent = _production_packet(parent_question, candidate_id=packets[0].candidate_id)
    child = _declared_mutation_fixture(parent, packets[1].candidate_id)
    packets = (parent, child, *packets[2:])
    audit = audit_production_duplicates(packets)
    queue = build_production_review_queue(packets)
    queue_entries = {item.candidate_id: item for item in queue.entries}

    assert audit.unrelated_blocking_overlaps == 0
    assert (
        queue_entries[parent.candidate_id].deterministic_order
        < queue_entries[child.candidate_id].deterministic_order
    )
    assert queue_entries[child.candidate_id].mutation_parent_dependency == parent.candidate_id
    assert not {
        "reviewer_id",
        "approval_timestamp",
        "decision",
    }.intersection(item.name for item in dataclass_fields(ProductionReviewQueueEntryV1))


def test_valid_mutation_descendant_overlap_is_classified_as_authorized_lineage() -> None:
    from dynamislm.benchmark.production import audit_production_duplicates

    packets, _exclusion, _plan = _store_roundtrip_fixture()
    root = _production_packet(
        "alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo lima "
        "mike november oscar papa quebec romeo sierra tango",
        candidate_id=packets[0].candidate_id,
    )
    child = _declared_mutation_fixture(root, packets[1].candidate_id)
    grandchild = _declared_mutation_fixture(child, packets[2].candidate_id)

    audit = audit_production_duplicates((root, child, grandchild, *packets[3:]))

    assert audit.unrelated_blocking_overlaps == 0
    assert audit.exact_13_token_overlap_pairs == 0


def test_forged_mutation_lineage_binding_is_rejected() -> None:
    from dynamislm.benchmark.pre_review import bind_candidate_review_packet
    from dynamislm.benchmark.production import audit_production_duplicates

    packets, _exclusion, _plan = _store_roundtrip_fixture()
    parent = _production_packet(
        "alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo lima "
        "mike november oscar papa quebec romeo sierra tango",
        candidate_id=packets[0].candidate_id,
    )
    child = _declared_mutation_fixture(parent, packets[1].candidate_id)
    assert child.parent_candidate_binding is not None
    forged = replace(
        child,
        parent_candidate_binding=replace(
            child.parent_candidate_binding,
            mutation_lineage_id="PSE-V1-LINEAGE:forged",
        ),
        candidate_payload_hash="sha256:" + "0" * 64,
        proposed_approval_digest="sha256:" + "0" * 64,
    )
    forged = bind_candidate_review_packet(forged)

    with pytest.raises(ValueError, match="invalid parent/cluster binding"):
        audit_production_duplicates((parent, forged, *packets[2:]))


def test_banded_edit_threshold_matches_frozen_exact_similarity() -> None:
    from random import Random

    from dynamislm.benchmark.contamination import (
        normalized_edit_similarity,
        normalized_edit_similarity_at_least,
    )

    rng = Random(126)
    alphabet = "abcdef ghijklm nopqrstuvwxyz"
    for length in (8, 9, 10, 19, 20, 63, 128):
        for _ in range(20):
            left = "".join(rng.choice(alphabet) for _ in range(length))
            chars = list(left)
            for _edit in range(max(1, length // 12)):
                position = rng.randrange(len(chars))
                chars[position] = rng.choice(alphabet)
            right = "".join(chars)
            assert normalized_edit_similarity_at_least(left, right, 0.90) == (
                normalized_edit_similarity(left, right) >= 0.90
            )


@pytest.mark.parametrize(
    "origin",
    (
        CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION,
        CaseOrigin.DETERMINISTIC_ENGINE_DERIVED,
        CaseOrigin.DETERMINISTIC_SYNTHETIC,
    ),
)
def test_nonsemantic_production_origins_reject_legacy_author_batch(origin: CaseOrigin) -> None:
    from dynamislm.benchmark.production import validate_production_candidate_packet

    packet = _production_packet("origin scoped metadata fixture")
    invalid = bind_candidate_review_packet(
        replace(
            packet,
            proposed_provenance=replace(packet.proposed_provenance, origin_class=origin),
            contamination=replace(
                packet.contamination,
                expert_author_batch_id="agent-process:codex:RES-115-CASE-AUTHORING-001B",
            ),
            candidate_payload_hash="sha256:" + "0" * 64,
            proposed_approval_digest="sha256:" + "0" * 64,
        )
    )
    with pytest.raises(ValueError, match="expert author batch"):
        validate_production_candidate_packet(invalid)


def test_semantic_production_packet_requires_bounded_batch_not_process_identity() -> None:
    from dynamislm.benchmark.production import validate_production_candidate_packet

    packet = _production_packet("bounded semantic metadata fixture")
    validate_production_candidate_packet(packet)
    for global_id in (
        PRODUCTION_AUTHORING_PROCESS_ID,
        "agent-process:codex:RES-115-CASE-AUTHORING-001B",
    ):
        invalid = bind_candidate_review_packet(
            replace(
                packet,
                contamination=replace(
                    packet.contamination,
                    expert_author_batch_id=global_id,
                ),
                candidate_payload_hash="sha256:" + "0" * 64,
                proposed_approval_digest="sha256:" + "0" * 64,
            )
        )
        with pytest.raises(ValueError, match="global authoring process identity"):
            validate_production_candidate_packet(invalid)


def test_author_id_does_not_create_a_shared_source_or_engine_isolation_cluster() -> None:
    source = _item(
        "PSE-V1-CANDIDATE:shared-author-source",
        capability_id="C13",
        benchmark_family="F01",
        origin=CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION,
        cluster="cluster:source",
    )
    engine = _item(
        "PSE-V1-CANDIDATE:shared-author-engine",
        capability_id="C16",
        benchmark_family="F05",
        origin=CaseOrigin.DETERMINISTIC_ENGINE_DERIVED,
        cluster="cluster:engine",
    )

    assert source.author_id == engine.author_id
    assert (
        validate_production_isolation(
            (_commitment(source), _commitment(engine))
        ).atomic_cluster_count
        == 2
    )


def test_shared_semantic_batch_cannot_cross_declared_clusters() -> None:
    one = _item("PSE-V1-CANDIDATE:batch-one", cluster="cluster:one")
    two = _item("PSE-V1-CANDIDATE:batch-two", cluster="cluster:two")

    with pytest.raises(ValueError, match="expert-author-batch fragmented"):
        validate_production_isolation((_commitment(one), _commitment(two, "b")))


def test_semantic_mutation_inherits_parent_batch_and_template() -> None:
    from dynamislm.benchmark.production import validate_production_candidate_set

    packets, _exclusion, _plan = _store_roundtrip_fixture()
    packets = _bounded_semantic_packet_fixture(packets)
    parent = packets[0]
    child = _declared_mutation_fixture(parent, packets[1].candidate_id)
    commitments = validate_production_candidate_set((parent, child, *packets[2:]))

    assert len(commitments) == 434
    assert child.contamination.expert_author_batch_id == parent.contamination.expert_author_batch_id
    assert child.contamination.protocol_template_id == parent.contamination.protocol_template_id


@pytest.mark.parametrize("field", ("expert_author_batch_id", "protocol_template_id"))
def test_semantic_mutation_cannot_change_parent_batch_or_template(
    field: Literal["expert_author_batch_id", "protocol_template_id"],
) -> None:
    from dynamislm.benchmark.production import validate_production_candidate_set

    packets, _exclusion, _plan = _store_roundtrip_fixture()
    packets = _bounded_semantic_packet_fixture(packets)
    parent = packets[0]
    child = _declared_mutation_fixture(parent, packets[1].candidate_id)
    contamination = (
        replace(
            child.contamination,
            expert_author_batch_id=f"different-{field}:001C",
        )
        if field == "expert_author_batch_id"
        else replace(
            child.contamination,
            protocol_template_id=f"different-{field}:001C",
        )
    )
    child = bind_candidate_review_packet(
        replace(
            child,
            contamination=contamination,
            candidate_payload_hash="sha256:" + "0" * 64,
            proposed_approval_digest="sha256:" + "0" * 64,
        )
    )

    with pytest.raises(ValueError, match="preserve parent expert-author batch and template"):
        validate_production_candidate_set((parent, child, *packets[2:]))


def test_nonsemantic_mutation_does_not_invent_an_expert_batch() -> None:
    from dynamislm.benchmark.production import _validate_production_mutation_isolation_metadata

    parent = _production_packet("synthetic parent isolation fixture")
    parent = bind_candidate_review_packet(
        replace(
            parent,
            proposed_provenance=replace(
                parent.proposed_provenance,
                origin_class=CaseOrigin.DETERMINISTIC_ENGINE_DERIVED,
            ),
            contamination=replace(
                parent.contamination,
                expert_author_batch_id=None,
                protocol_template_id=None,
            ),
            candidate_payload_hash="sha256:" + "0" * 64,
            proposed_approval_digest="sha256:" + "0" * 64,
        )
    )
    child = _declared_mutation_fixture(parent, "PSE-V1-CANDIDATE:mutation-no-batch")

    _validate_production_mutation_isolation_metadata((parent, child))
    assert child.contamination.expert_author_batch_id is None
    assert child.contamination.protocol_template_id is None


def test_repaired_434_packet_set_passes_production_isolation() -> None:
    from dynamislm.benchmark.production import (
        validate_production_candidate_set,
        validate_production_isolation,
    )

    packets, _exclusion, _plan = _store_roundtrip_fixture()
    packets = _bounded_semantic_packet_fixture(packets)
    commitments = validate_production_candidate_set(packets)
    validation = validate_production_isolation(commitments)
    assert validation.candidate_count == 434
    assert validation.status == "PASS"


def test_res224_private_telemetry_is_serializable_without_membership() -> None:
    import json

    from dynamislm.benchmark.production import _exact_completion_status, _ExactConstraint

    telemetry: dict[str, object] = {}
    log: list[str] = []
    status = _exact_completion_status(
        1,
        (_ExactConstraint("CELL:C01:F01:PUBLIC_DEVELOPMENT", ((0, 0, 1),), lower=1),),
        active_group_ids=frozenset({"CELL:C01:F01:PUBLIC_DEVELOPMENT"}),
        telemetry=telemetry,
        solve_log=log,
        solve_label="RES224_TELEMETRY_TEST",
        max_time_in_seconds=5,
        log_search_progress=True,
    )

    serialized = json.dumps(telemetry, sort_keys=True)
    assert status == "FEASIBLE"
    assert telemetry["status"] in {"FEASIBLE", "OPTIMAL"}
    assert telemetry["presolved_variable_count"] == 0
    log_digest = telemetry["solve_log_digest"]
    assert isinstance(log_digest, str) and log_digest.startswith("sha256:")
    assert log and "Presolved satisfaction model" in log[0]
    assert "candidate_ids" not in serialized
    assert "split_membership" not in serialized
    assert "rank_assignment" not in serialized


def test_res224_canonical_model_proto_digest_is_stable() -> None:
    from dynamislm.benchmark.production import (
        _build_exact_cp_model,
        _exact_cp_model_proto,
        _ExactConstraint,
    )

    constraints = (_ExactConstraint("CELL:C01:F01:PUBLIC_DEVELOPMENT", ((0, 0, 1),), lower=1),)
    first, _ = _build_exact_cp_model(1, constraints)
    second, _ = _build_exact_cp_model(1, constraints)
    assert _exact_cp_model_proto(first) == _exact_cp_model_proto(second)


def test_res224_constraint_ladder_and_hint_ablation_keep_hard_model_identity() -> None:
    from dynamislm.benchmark.production import (
        _build_exact_cp_model,
        _exact_completion_status,
        _exact_cp_model_proto,
        _ExactConstraint,
    )

    constraints = (
        _ExactConstraint("CELL:C01:F01:PUBLIC_DEVELOPMENT", ((0, 0, 1),), lower=1),
        _ExactConstraint("COUNT:PUBLIC_DEVELOPMENT=1", ((0, 0, 1),), lower=1, upper=1),
    )
    ladder_digests = []
    for active in (
        frozenset({"CELL:C01:F01:PUBLIC_DEVELOPMENT"}),
        frozenset({"CELL:C01:F01:PUBLIC_DEVELOPMENT", "COUNT:PUBLIC_DEVELOPMENT=1"}),
    ):
        model, _ = _build_exact_cp_model(1, constraints, active_group_ids=active)
        ladder_digests.append(hashlib.sha256(_exact_cp_model_proto(model)).hexdigest())
    assert ladder_digests[0] != ladder_digests[1]

    no_hint: dict[str, object] = {}
    with_hint: dict[str, object] = {}
    _exact_completion_status(1, constraints, telemetry=no_hint, max_time_in_seconds=5)
    _exact_completion_status(
        1,
        constraints,
        hint=(0,),
        telemetry=with_hint,
        max_time_in_seconds=5,
    )
    assert no_hint["constraint_set_digest"] == with_hint["constraint_set_digest"]
    assert no_hint["model_proto_digest"] != with_hint["model_proto_digest"]


def test_res224_multiworker_witness_is_independently_checked() -> None:
    from scripts.res224_probes import _check_rank_assignment

    from dynamislm.benchmark.production import _exact_completion_status, _ExactConstraint

    constraints = (
        _ExactConstraint("CELL:C01:F01:PUBLIC_DEVELOPMENT", ((0, 0, 1),), lower=1),
        _ExactConstraint("COUNT:PUBLIC_DEVELOPMENT=1", ((0, 0, 1),), lower=1, upper=1),
    )
    ranks: list[int] = []
    status = _exact_completion_status(
        1,
        constraints,
        solved_ranks=ranks,
        max_time_in_seconds=5,
        num_search_workers=8,
        default_search=True,
    )
    assert status == "FEASIBLE"
    _check_rank_assignment(tuple(ranks), 1, constraints)
    with pytest.raises(ValueError, match="lower bound"):
        _check_rank_assignment((1,), 1, constraints)
    with pytest.raises(ValueError, match="component ranks"):
        _check_rank_assignment((3,), 1, constraints)


def test_res224_proof_import_rejects_model_or_proof_digest_mismatch() -> None:
    from scripts.res224_probes import _sha256, _validate_artifact_binding

    model = b"p cnf 1 1\n1 0\n"
    proof = b"-1 0\n0\n"
    _validate_artifact_binding(model, _sha256(model), proof, _sha256(proof))
    with pytest.raises(ValueError, match="different or empty model"):
        _validate_artifact_binding(model, _sha256(b"different"), proof, _sha256(proof))
    with pytest.raises(ValueError, match="proof artifact digest"):
        _validate_artifact_binding(model, _sha256(model), proof, _sha256(b"different"))


def test_res224_exchangeability_signatures_partition_real_components() -> None:
    from scripts.res224_probes import _exchangeability_classes

    from dynamislm.benchmark.production import (
        _exact_requirement_constraints,
        _feasibility_clusters,
    )

    commitments = _feasibility_fixture()
    pairs = _cross_cell_exact_shingle_pairs(commitments)
    base = _feasibility_clusters(commitments, allow_incompatible_locks=True)
    colocated = _feasibility_clusters(
        commitments,
        exact_shingle_colocation_pairs=pairs,
        allow_incompatible_locks=True,
    )
    constraints = _exact_requirement_constraints(colocated, colocated)
    classes, summary, signatures = _exchangeability_classes(base, colocated, constraints, pairs)

    assert len(signatures) == len(colocated)
    assert sorted(index for group in classes for index in group) == list(range(len(colocated)))
    assert summary["exchangeability_class_count"] == len(classes)
    assert summary["largest_exchangeability_class"] == max(map(len, classes))


def test_res224_symmetry_breaker_rejects_nonexchangeable_components() -> None:
    from scripts.res224_probes import _validate_symmetry_breaker

    from dynamislm.benchmark.production import _ExactConstraint

    with pytest.raises(ValueError, match="nonexchangeable"):
        _validate_symmetry_breaker(((0, 1),), ("sha256:a", "sha256:b"), ())
    with pytest.raises(ValueError, match="co-location equality"):
        _validate_symmetry_breaker(
            ((0, 1),),
            ("sha256:a", "sha256:a"),
            (_ExactConstraint("COLOCATION:a:b", equalities=((0, 1),)),),
        )


def test_res224_exact_three_cell_strengthening_is_exhaustively_equivalent() -> None:
    from scripts.res224_probes import _exact_three_equivalence

    equivalent, digest = _exact_three_equivalence()
    assert equivalent
    assert digest.startswith("sha256:")


def test_res224_receipt_head_provenance_is_explicit() -> None:
    receipt = Path("docs/qualification/RES-223-ACCEPTANCE-RECEIPT.md").read_text()
    assert "IMPLEMENTATION_HEAD=79904ed1da9c0f5f351330b878b4570d035c8a48" in receipt
    assert "RECEIPT_BINDING_HEAD=7cfbb7a73a91090c86d728d68c0614224f60cf9e" in receipt
    assert "FINAL_HEAD=" not in receipt
