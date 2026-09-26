from __future__ import annotations

import hashlib
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from dynamislm.benchmark.authoring import (
    AUTHORING_RECIPE_REGISTRY,
    production_seed_namespace,
    question_classes_for_cell,
)
from dynamislm.benchmark.constants import (
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
from dynamislm.benchmark.pre_review import bind_candidate_review_packet
from dynamislm.benchmark.production import (
    PRODUCTION_AUTHORING_PROCESS_ID,
    PRODUCTION_BATCH_ID,
    PRODUCTION_BATCH_MANIFEST_VERSION,
    ProductionAuthoringPlanItemV1,
    ProductionBatchManifestV1,
    ProductionCandidateCommitmentV1,
    ProductionFeasibilityBlocked,
    ProductionFeasibilityReceiptV1,
    bind_production_batch_manifest,
    validate_production_batch_manifest,
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
from dynamislm.serialization import canonical_json

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


def _production_packet(question: str, *, candidate_id: str = "PSE-V1-CANDIDATE:test"):
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
    check = validate_production_exclusion_identity
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
            check(**(identity | change))


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
