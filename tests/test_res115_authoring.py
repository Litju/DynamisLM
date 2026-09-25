from __future__ import annotations

import hashlib
from dataclasses import replace

import pytest

from dynamislm.benchmark.authoring import (
    ACTIVE_SCORERS,
    AUTHORING_RECIPE_REGISTRY,
    PHASE_A_SEARCH_STRATA,
    QUALIFICATION_CANDIDATE_ID_PREFIX,
    QUALIFICATION_MANIFEST_VERSION,
    AuthoringPlanItemV1,
    AuthoringPlanV1,
    CandidateStoreReceiptV1,
    QualificationBatchManifestV1,
    QualificationCandidateCommitmentV1,
    authoring_recipe_registry_digest,
    bind_authoring_plan,
    bind_candidate_store_receipt,
    bind_qualification_batch_manifest,
    question_classes_for_cell,
    validate_authoring_plan,
    validate_authoring_recipe_registry,
    validate_production_seed_namespace,
    validate_qualification_batch_manifest,
    validate_qualification_commitment_coverage,
)
from dynamislm.benchmark.constants import (
    CaseOrigin,
    DifficultyLevel,
    ErrorClass,
    ExpectedAnswerKind,
    PractitionerQuestionClass,
    RefusalDecision,
    ScoringProfile,
)
from dynamislm.benchmark.coverage import COVERAGE_MATRIX, coverage_manifest_digest
from dynamislm.qualification import get_reference_cases

_ZERO_SHA = "sha256:" + "0" * 64


def _digest(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _public_commitments() -> tuple[QualificationCandidateCommitmentV1, ...]:
    entries: list[QualificationCandidateCommitmentV1] = []
    error_classes = tuple(ErrorClass)
    for row in COVERAGE_MATRIX:
        for index, family in enumerate(row.benchmark_families):
            origin = row.case_origins[0]
            if row.capability_id == "C01" and family == "F01":
                origin = CaseOrigin.ADVERSARIAL_MUTATION
            elif row.capability_id == "C08" and family == "F13":
                origin = CaseOrigin.DETERMINISTIC_SYNTHETIC
            elif row.capability_id == "C13" and family == "F11":
                origin = CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION
            if (
                origin is CaseOrigin.EXPERT_AUTHORED_SEMANTIC
                and "EXPERT_RUBRIC" in row.answer_authorities
            ):
                authority_kind = "EXPERT_RUBRIC"
            elif (
                origin is CaseOrigin.DETERMINISTIC_ENGINE_DERIVED
                and "RES71_REFERENCE_CASE" in row.answer_authorities
            ):
                authority_kind = "RES71_REFERENCE_CASE"
            else:
                authority_kind = row.answer_authorities[0]

            scorer = row.scorer_profiles[0]
            question_class = question_classes_for_cell(row.capability_id, family)[0]
            if row.capability_id == "C01" and family == "F01":
                scorer = ScoringProfile.CLASSIFICATION_V1
                question_class = PractitionerQuestionClass.MEASUREMENT_IDENTITY_AND_PROVENANCE
            elif row.capability_id == "C05" and family == "F03":
                scorer = ScoringProfile.NUMERIC_TOLERANCE_V1
            elif row.capability_id == "C02" and family == "F02":
                scorer = ScoringProfile.STRUCTURED_FIELDS_V1
                question_class = PractitionerQuestionClass.METHOD_AND_ANALYSIS_REASONING
            elif row.capability_id == "C13" and family == "F11":
                scorer = ScoringProfile.EVIDENCE_SPAN_V1
            elif row.capability_id == "C07" and family == "F04":
                scorer = ScoringProfile.COMPARABILITY_V1
                question_class = PractitionerQuestionClass.COMPARABILITY_AND_HARMONIZATION
            elif row.capability_id == "C18" and family == "F14":
                scorer = ScoringProfile.REFUSAL_V1
                question_class = PractitionerQuestionClass.ANSWERABILITY_AND_REFUSAL
            elif row.capability_id == "C15" and family == "F12":
                scorer = ScoringProfile.CAUSAL_BOUNDARY_V1
                question_class = PractitionerQuestionClass.INDIVIDUAL_LONGITUDINAL_CHANGE
            elif row.capability_id == "C12" and family == "F08":
                question_class = PractitionerQuestionClass.GROUP_OR_SQUAD_CHANGE
            elif row.capability_id == "C10" and family == "F08":
                question_class = PractitionerQuestionClass.RELATIONSHIP_AND_MULTILEVEL_STRUCTURE
            elif row.capability_id == "C01" and family == "F03":
                question_class = PractitionerQuestionClass.CONSTRUCT_AND_CLAIM_INTERPRETATION

            if row.capability_id == "C18" and family == "F14":
                answer_kind = ExpectedAnswerKind.REFUSAL
                refusal = RefusalDecision.REQUIRED
                safe_partial = True
            else:
                answer_kind = ExpectedAnswerKind.ANSWER
                refusal = RefusalDecision.PROHIBITED
                safe_partial = False

            if row.capability_id == "C17":
                reachable = (error_classes[index % len(error_classes)],)
            else:
                reachable = (row.error_classes[0],)
            authority_kinds = [authority_kind]
            if origin is CaseOrigin.DETERMINISTIC_SYNTHETIC:
                authority_kinds.append("GENERATOR")
            if origin is CaseOrigin.ADVERSARIAL_MUTATION:
                authority_kinds.append("MUTATION_PARENT")
            entries.append(
                QualificationCandidateCommitmentV1(
                    candidate_id=(
                        f"{QUALIFICATION_CANDIDATE_ID_PREFIX}TEST:{row.capability_id}:{family}"
                    ),
                    candidate_payload_hash=_digest(f"{row.capability_id}/{family}"),
                    capability_id=row.capability_id,
                    benchmark_family=family,
                    practitioner_question_class=question_class,
                    origin_class=origin,
                    scoring_profile=scorer,
                    authority_class=(
                        "DETERMINISTIC_GENERATOR"
                        if origin is CaseOrigin.DETERMINISTIC_SYNTHETIC
                        else "CANDIDATE_MUTATION"
                        if origin is CaseOrigin.ADVERSARIAL_MUTATION
                        else "PHASE_A_SOURCE"
                        if origin is CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION
                        else "EXPERT_SEMANTIC"
                        if authority_kind == "EXPERT_RUBRIC"
                        else "RES71_REFERENCE"
                    ),
                    authority_kinds=tuple(authority_kinds),
                    reachable_error_classes=reachable,
                    source_document_ids=(),
                    expected_answer_kind=answer_kind,
                    refusal_decision=refusal,
                    safe_partial_support=safe_partial,
                )
            )
    return tuple(entries)


def _candidate_store_receipt(
    commitments: tuple[QualificationCandidateCommitmentV1, ...],
    plan_digest: str,
) -> CandidateStoreReceiptV1:
    provisional = CandidateStoreReceiptV1(
        batch_id="PSE-V1-QUALIFICATION/TEST-BATCH",
        store_relative_path="qualification/candidates",
        candidate_file_digests=tuple(
            sorted(
                ((entry.candidate_id, entry.candidate_payload_hash) for entry in commitments),
                key=lambda item: item[0].encode("utf-8"),
            )
        ),
        candidate_count=len(commitments),
        total_bytes=1024,
        authoring_plan_digest=plan_digest,
        artifact_inventory_digest=_digest("test-inventory"),
        receipt_digest=_ZERO_SHA,
    )
    return bind_candidate_store_receipt(provisional)


def _synthetic_plan_item(
    *,
    family: str = "F13",
    seed_namespace: str = "PSE-V1-QUALIFICATION/res115-synthetic-refusal/block-1",
    generator_registry_digest: str | None = None,
) -> AuthoringPlanItemV1:
    recipe = next(
        item
        for item in AUTHORING_RECIPE_REGISTRY
        if (item.capability_id, item.benchmark_family) == ("C08", family)
    )
    return AuthoringPlanItemV1(
        recipe_id=recipe.recipe_id,
        recipe_version=recipe.recipe_version,
        coverage_role="CELL",
        supplement_reason=None,
        capability_id="C08",
        benchmark_family=family,
        practitioner_question_class=PractitionerQuestionClass.ANSWERABILITY_AND_REFUSAL,
        origin_class=CaseOrigin.DETERMINISTIC_SYNTHETIC,
        scoring_profile=ScoringProfile.STRUCTURED_FIELDS_V1,
        authority_class="DETERMINISTIC_GENERATOR",
        authority_kinds=("GENERATOR", "RES71_UNRESOLVED"),
        source_reference_ids=("res71-unresolved:generic-power",),
        source_search_strata=(),
        parent_candidate_id=None,
        engine_reference_case_id=None,
        engine_operation_id=None,
        generator_id="res115-synthetic-refusal",
        generator_registry_digest=generator_registry_digest or _digest("generator-registry"),
        seed_namespace=seed_namespace,
        seed_block="block-1",
        difficulty=DifficultyLevel.MEDIUM,
        adversarial_tags=("UNREGISTERED_OPERATION",),
        authoring_rationale=(
            "Synthetic refusal scenario uses a live unresolved computation route."
        ),
        candidate_id=f"PSE-V1-QUALIFICATION:TEST:C08:{family}",
        candidate_payload_hash=_digest(f"C08:{family}"),
    )


def test_authoring_recipe_registry_has_a_real_operator_for_all_87_cells() -> None:
    validate_authoring_recipe_registry()

    assert len(AUTHORING_RECIPE_REGISTRY) == 87
    assert all(recipe.operator_id for recipe in AUTHORING_RECIPE_REGISTRY)
    assert question_classes_for_cell("C17", "F13")
    assert question_classes_for_cell("C18", "F14")
    assert question_classes_for_cell("C99", "F99") == ()


def test_recipe_registry_fails_closed_if_any_obligation_has_no_recipe() -> None:
    incomplete = tuple(
        recipe
        for recipe in AUTHORING_RECIPE_REGISTRY
        if (recipe.capability_id, recipe.benchmark_family) != ("C17", "F13")
    )

    with pytest.raises(ValueError, match="does not cover the frozen cells"):
        validate_authoring_recipe_registry(incomplete)


def test_authoring_plan_binds_recipe_instance_and_seed_namespace() -> None:
    recipe = next(
        item
        for item in AUTHORING_RECIPE_REGISTRY
        if (item.capability_id, item.benchmark_family) == ("C08", "F13")
    )
    item = AuthoringPlanItemV1(
        recipe_id=recipe.recipe_id,
        recipe_version=recipe.recipe_version,
        coverage_role="CELL",
        supplement_reason=None,
        capability_id=recipe.capability_id,
        benchmark_family=recipe.benchmark_family,
        practitioner_question_class=PractitionerQuestionClass.ANSWERABILITY_AND_REFUSAL,
        origin_class=CaseOrigin.DETERMINISTIC_SYNTHETIC,
        scoring_profile=ScoringProfile.STRUCTURED_FIELDS_V1,
        authority_class="DETERMINISTIC_GENERATOR",
        authority_kinds=("GENERATOR", "RES71_UNRESOLVED"),
        source_reference_ids=("res71-unresolved:generic-power",),
        source_search_strata=(),
        parent_candidate_id=None,
        engine_reference_case_id=None,
        engine_operation_id=None,
        generator_id="res115-synthetic-refusal",
        generator_registry_digest=_digest("generator-registry"),
        seed_namespace="PSE-V1-QUALIFICATION/res115-synthetic-refusal/block-1",
        seed_block="block-1",
        difficulty=DifficultyLevel.MEDIUM,
        adversarial_tags=("UNREGISTERED_OPERATION",),
        authoring_rationale="Synthetic refusal scenario uses a live unresolved computation route.",
        candidate_id="PSE-V1-QUALIFICATION:TEST:C08:F13",
        candidate_payload_hash=_digest("synthetic-case"),
    )
    plan = bind_authoring_plan(
        AuthoringPlanV1(
            plan_id="PSE-V1-QUALIFICATION/TEST-PLAN",
            plan_version="pse-authoring-plan@1.0.0",
            coverage_matrix_digest=coverage_manifest_digest(),
            recipe_registry_digest=authoring_recipe_registry_digest(),
            items=(item,),
            plan_digest=_ZERO_SHA,
        )
    )

    validate_authoring_plan(plan, require_all_cells=False)

    forged_plan = replace(plan, plan_digest=_ZERO_SHA)
    with pytest.raises(ValueError, match="plan digest mismatch"):
        validate_authoring_plan(forged_plan, require_all_cells=False)


def test_qualification_seed_is_rejected_at_a_production_boundary() -> None:
    with pytest.raises(ValueError, match="qualification-only seed namespace"):
        validate_production_seed_namespace("PSE-V1-QUALIFICATION/generator/block-1")

    # This mission deliberately does not reserve any future production namespaces.
    validate_production_seed_namespace("PSE-V1-FUTURE-UNRESOLVED/new-generator/block")


def test_generator_seed_collision_is_rejected_by_the_plan_validator() -> None:
    items = tuple(_synthetic_plan_item(family=family) for family in ("F13", "F14"))
    plan = bind_authoring_plan(
        AuthoringPlanV1(
            plan_id="PSE-V1-QUALIFICATION/TEST-SEED-COLLISION",
            plan_version="pse-authoring-plan@1.0.0",
            coverage_matrix_digest=coverage_manifest_digest(),
            recipe_registry_digest=authoring_recipe_registry_digest(),
            items=items,
            plan_digest=_ZERO_SHA,
        )
    )

    with pytest.raises(ValueError, match="seed collision"):
        validate_authoring_plan(plan, require_all_cells=False)


def test_synthetic_plan_rejects_production_namespace_and_missing_generator_digest() -> None:
    with pytest.raises(ValueError, match="non-qualification namespace"):
        replace(_synthetic_plan_item(), seed_namespace="PSE-V1-PUBLIC/block-1")
    with pytest.raises(ValueError, match="generator registry and seed inputs"):
        replace(_synthetic_plan_item(), generator_registry_digest=None)


def test_qualification_commitment_validator_proves_87_cells_and_all_dimensions() -> None:
    commitments = _public_commitments()

    result = validate_qualification_commitment_coverage(commitments)

    assert result.status == "PASS"
    assert result.represented_cells == 87
    assert result.represented_capabilities == 18
    assert result.represented_families == 14
    assert result.represented_question_classes == 8
    assert result.represented_origins == 5
    assert result.represented_scorers == len(ACTIVE_SCORERS) == 7
    assert result.represented_error_classes == len(ErrorClass)

    with pytest.raises(ValueError, match="not 87/87"):
        validate_qualification_commitment_coverage(commitments[:-1])


def test_qualification_manifest_hash_integrity_and_final_status_enforcement() -> None:
    commitments = _public_commitments()
    plan_digest = _digest("plan")
    receipt = _candidate_store_receipt(commitments, plan_digest)
    manifest = bind_qualification_batch_manifest(
        QualificationBatchManifestV1(
            batch_id=receipt.batch_id,
            manifest_version=QUALIFICATION_MANIFEST_VERSION,
            qualification_only=True,
            final_v1_eligible=False,
            authoring_plan_digest=plan_digest,
            candidate_store_receipt_digest=receipt.receipt_digest,
            candidate_entries=commitments,
            res71_reference_case_ids=tuple(item.case_id for item in get_reference_cases()),
            direct_target_document_ids=tuple(f"PSE-DOCUMENT:PMC{i}" for i in range(5)),
            evidence_search_strata=PHASE_A_SEARCH_STRATA,
            source_family_ids=tuple(f"PSE-SOURCE-FAMILY:{i:02d}" for i in range(10)),
            human_approval_count=0,
            final_case_count=0,
            split_assignment_count=0,
            protected_store_count=0,
            manifest_digest=_ZERO_SHA,
        )
    )

    validate_qualification_batch_manifest(manifest)

    with pytest.raises(ValueError, match="manifest digest mismatch"):
        validate_qualification_batch_manifest(replace(manifest, manifest_digest=_ZERO_SHA))
    with pytest.raises(ValueError, match="can never be final V1 eligible"):
        replace(manifest, final_v1_eligible=True)
    with pytest.raises(ValueError, match="cannot contain approvals"):
        replace(manifest, human_approval_count=1)
