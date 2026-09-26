from __future__ import annotations

from pathlib import Path

import pytest

from dynamislm.benchmark.authoring import AUTHORING_RECIPE_REGISTRY, production_seed_namespace
from dynamislm.benchmark.constants import (
    CaseOrigin,
    DifficultyLevel,
    ErrorClass,
    ExpectedAnswerKind,
    PractitionerQuestionClass,
    RefusalDecision,
    ScoringProfile,
    SplitName,
)
from dynamislm.benchmark.production import (
    PRODUCTION_AUTHORING_PROCESS_ID,
    PRODUCTION_BATCH_ID,
    PRODUCTION_BATCH_MANIFEST_VERSION,
    ProductionAuthoringPlanItemV1,
    ProductionBatchManifestV1,
    ProductionCandidateCommitmentV1,
    bind_production_batch_manifest,
    validate_production_batch_manifest,
    validate_production_isolation,
)
from dynamislm.benchmark.production_store import (
    read_external_production_json,
    write_external_production_json,
)

_SHA = "sha256:" + "a" * 64


def _item(
    candidate_id: str,
    *,
    cluster: str | None = None,
    source_family: str | None = None,
    author_batch: str = "expert-batch:001C-test-a",
    template: str = "protocol-template:001C-test-a",
    origin: CaseOrigin = CaseOrigin.EXPERT_AUTHORED_SEMANTIC,
    mutation_lineage: str | None = None,
    parent_candidate_id: str | None = None,
    generator_family: str | None = None,
    seed_split: SplitName = SplitName.PUBLIC_DEVELOPMENT,
) -> ProductionAuthoringPlanItemV1:
    recipe = next(item for item in AUTHORING_RECIPE_REGISTRY if item.capability_id == "C01")
    return ProductionAuthoringPlanItemV1(
        candidate_id=candidate_id,
        recipe_id=recipe.recipe_id,
        recipe_version=recipe.recipe_version,
        capability_id="C01",
        benchmark_family=recipe.benchmark_family,
        practitioner_question_class=PractitionerQuestionClass.MEASUREMENT_IDENTITY_AND_PROVENANCE,
        origin_class=origin,
        scoring_profile=ScoringProfile.CLASSIFICATION_V1,
        authority_class="EXPERT_SEMANTIC",
        authority_kinds=("EXPERT_RUBRIC",),
        reachable_error_classes=(ErrorClass.FALSE_SCIENTIFIC_ACCEPTANCE,),
        adversarial_tags=("ALIAS_COLLISION",),
        source_family_id=source_family or f"source-family:{candidate_id}",
        source_document_ids=(),
        source_artifact_ids=(),
        construct_test_identity_ids=(),
        provider_export_ids=(),
        protocol_template_ids=(template,) if template else (),
        expert_author_batch_id=author_batch
        if origin is CaseOrigin.EXPERT_AUTHORED_SEMANTIC
        else None,
        author_id=PRODUCTION_AUTHORING_PROCESS_ID,
        generator_id=("test-generator" if origin is CaseOrigin.DETERMINISTIC_SYNTHETIC else None),
        generator_version=("1.0.0" if origin is CaseOrigin.DETERMINISTIC_SYNTHETIC else None),
        generator_family=generator_family,
        seed_block=(
            f"block-{candidate_id.rsplit(':', 1)[-1]}"
            if origin is CaseOrigin.DETERMINISTIC_SYNTHETIC
            else None
        ),
        seed_namespace=(
            production_seed_namespace(
                seed_split,
                "test-generator",
                "1.0.0",
                f"block-{candidate_id.rsplit(':', 1)[-1]}",
            )
            if origin is CaseOrigin.DETERMINISTIC_SYNTHETIC
            else None
        ),
        mutation_lineage_id=mutation_lineage,
        parent_candidate_id=parent_candidate_id,
        isolation_cluster_id=cluster or f"cluster:{candidate_id}",
        allocation_stratum="C01:F01",
        refusal_decision=RefusalDecision.PROHIBITED,
        expected_answer_kind=ExpectedAnswerKind.ANSWER,
        safe_partial_support=False,
        difficulty=DifficultyLevel.EASY,
    )


def _commitment(
    item: ProductionAuthoringPlanItemV1, suffix: str = "a"
) -> ProductionCandidateCommitmentV1:
    return ProductionCandidateCommitmentV1(item, "sha256:" + suffix * 64)


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
