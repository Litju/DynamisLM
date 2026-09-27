from __future__ import annotations

import hashlib
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from dynamislm.benchmark.authoring import (
    ACTIVE_SCORERS,
    AUTHORING_RECIPE_REGISTRY,
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
    parse_production_seed_namespace,
    production_seed_namespace,
    question_classes_for_cell,
    validate_authoring_plan,
    validate_authoring_recipe_registry,
    validate_production_seed_namespace,
    validate_qualification_batch_manifest,
    validate_qualification_commitment_coverage,
    validate_split_qualified_seed_namespace,
)
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
from dynamislm.benchmark.contamination import (
    exact_13_token_shingles,
    exact_shingle_digest,
    fuzzy_fingerprint,
    normalized_text_sha256,
)
from dynamislm.benchmark.contracts import (
    AuthorityBinding,
    ClaimContract,
    ComparabilityContract,
    ContaminationBinding,
    DeterministicResultView,
    DifficultyBinding,
    ExpectedStructuredAnswer,
    InputContract,
    RefusalExpectation,
    ScoringContract,
)
from dynamislm.benchmark.coverage import COVERAGE_MATRIX, coverage_manifest_digest
from dynamislm.benchmark.pre_review import (
    CandidateIsolationMetadata,
    CandidateReviewPacket,
    ProposedCaseProvenance,
    bind_candidate_review_packet,
    validate_candidate_review_packet,
    validate_candidate_set,
)
from dynamislm.benchmark.public_repository import validate_qualification_repository_boundary
from dynamislm.benchmark.qualification_store import (
    read_external_qualification_json,
    read_qualification_store,
    write_external_qualification_json,
    write_qualification_store,
)
from dynamislm.qualification import ReferenceCaseStatus, get_reference_cases
from dynamislm.qualification.res115_authoring import (
    _BASE_SEMANTIC_CITATIONS,
    _CAPABILITY_AUTHORITY_CITATIONS,
    AUTHORING_PROCESS_ID,
    PHASE_A_SEARCH_STRATA,
    QUALIFICATION_BATCH_ID,
    RES115_SYNTHETIC_GENERATOR_DIGEST,
    QualificationSeedInputV1,
    _semantic_cell_candidate,
    build_res115_qualification_draft,
    build_res115_qualification_manifest,
    build_res115_reference_lane,
    generate_synthetic_unregistered_operation_context,
    validate_res115_qualification_batch,
    validate_res115_reference_candidate,
    validate_res115_reference_lane,
)
from dynamislm.serialization import canonical_hash

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


def _test_seed_input(
    *,
    batch_id: str = QUALIFICATION_BATCH_ID,
    seed_prefix: str = "test-seed",
) -> QualificationSeedInputV1:
    seed_cases = tuple(
        sorted(
            (
                item.case_id
                for item in get_reference_cases()
                if item.status is ReferenceCaseStatus.REFUSAL and item.operation_id is None
            ),
            key=lambda value: value.encode("utf-8"),
        )
    )
    return QualificationSeedInputV1(
        batch_id=batch_id,
        generator_registry_digest=RES115_SYNTHETIC_GENERATOR_DIGEST,
        seed_blocks=tuple(
            (case_id, f"{seed_prefix}-{index:02d}") for index, case_id in enumerate(seed_cases)
        ),
    )


def _store_roundtrip_fixture() -> tuple[CandidateReviewPacket, AuthoringPlanV1]:
    candidate_id = "PSE-V1-QUALIFICATION:TEST:STORE-ROUNDTRIP"
    question = "Read the synthetic test identity field and return its exact value."
    rubric_digest = _digest("synthetic test rubric")
    expected = ExpectedStructuredAnswer(
        kind=ExpectedAnswerKind.ANSWER,
        required_field_ids=("identity_field",),
        expected_fields={"identity_field": "VERTICAL_JUMP"},
    )
    refusal = RefusalExpectation(
        decision=RefusalDecision.PROHIBITED,
        blocked_claim=None,
        refusal_class=None,
        reason_codes=(),
        missing_information=(),
        what_can_still_be_safely_described=(),
    )
    authority = AuthorityBinding(
        "EXPERT_RUBRIC",
        "TEST-RUBRIC:STORE-ROUNDTRIP",
        "1.0.0",
        rubric_digest,
        ("expected_answer", "claim_contract", "refusal_expectation"),
    )
    contamination = ContaminationBinding(
        source_artifact_ids=(),
        document_ids=(),
        source_family_id="PSE-QUALIFICATION-TEST-FAMILY:STORE",
        provider_export_id=None,
        protocol_template_id=None,
        expert_author_batch_id="test-authoring-process",
        artifact_ids=(),
        source_content_sha256=None,
        normalized_text_sha256=normalized_text_sha256(question),
        exact_shingle_digest=exact_shingle_digest(question),
        fuzzy_fingerprint=fuzzy_fingerprint(question),
        semantic_cluster_id=None,
        generator_namespace=None,
        generator_seed_block=None,
        benchmark_artifact_ids=(),
        training_exclusion_ids=(),
    )
    packet = bind_candidate_review_packet(
        CandidateReviewPacket(
            benchmark_version="PerformanceScience-Eval@1.0.0",
            schema_version="pse-case-schema@1.1.0",
            candidate_id=candidate_id,
            candidate_version="1.0.0",
            capability_id="C03",
            benchmark_family="F03",
            practitioner_question_class=(
                PractitionerQuestionClass.MEASUREMENT_IDENTITY_AND_PROVENANCE
            ),
            question=question,
            input=InputContract(
                modality=("TEXT", "STRUCTURED_MEASUREMENT_RECORD"),
                question_text=question,
                structured_context={
                    "fixture_kind": "SYNTHETIC_QUALIFICATION_TEST_ONLY",
                    "display_label": "vertical jump height",
                },
            ),
            source_evidence_refs=(),
            proposed_expected_answer=expected,
            authority=(authority,),
            refusal_contract=refusal,
            claim_contract=ClaimContract(
                requested_claim="identify the supplied test label",
                maximum_supported_claim_level="OBSERVED_VALUE",
                safe_lower_claim_levels=("OBSERVED_VALUE",),
                prohibited_escalation=("CAUSAL_EVIDENCE",),
            ),
            comparability_contract=ComparabilityContract(
                requested_state=None,
                material_dimensions=(),
                dimension_findings={},
                conditions=(),
                transformations_required=(),
                not_applicable=True,
            ),
            scoring_contract=ScoringContract(
                profile_id=ScoringProfile.CLASSIFICATION_V1,
                profile_version="1.0.0",
                required_output_fields=("identity_field",),
                critical_fields=("identity_field",),
                accepted_normalization=("exact-controlled-label",),
                error_class_rules=(
                    ErrorClass.FALSE_SCIENTIFIC_ACCEPTANCE,
                    ErrorClass.OVER_REFUSAL,
                ),
                task_status_policy="critical-field-failure-is-fail",
                error_attribution=(
                    ("identity_field", ErrorClass.FALSE_SCIENTIFIC_ACCEPTANCE),
                    ("__over_refusal__", ErrorClass.OVER_REFUSAL),
                ),
            ),
            tolerance_contract=None,
            proposed_provenance=ProposedCaseProvenance(
                author_id="test-authoring-process",
                rubric_digest=rubric_digest,
                review_scope="synthetic storage round-trip test only",
                origin_class=CaseOrigin.EXPERT_AUTHORED_SEMANTIC,
                authority_lineage=("TEST-RUBRIC:STORE-ROUNDTRIP",),
                population_scope="synthetic test fixture; no empirical population claim",
                derivation_status="TEST_RUBRIC_BOUND",
                derivation_edges=(),
            ),
            contamination=contamination,
            isolation=CandidateIsolationMetadata(
                source_family_id=contamination.source_family_id,
                isolation_cluster_id="PSE-QUALIFICATION-TEST-CLUSTER:STORE",
                allocation_stratum="C03:F03",
            ),
            difficulty=DifficultyBinding(DifficultyLevel.EASY, "synthetic storage test"),
            adversarial_tags=("SAME_LABEL_DIFFERENT_MEASURAND",),
        )
    )
    recipe = next(
        item
        for item in AUTHORING_RECIPE_REGISTRY
        if (item.capability_id, item.benchmark_family) == ("C03", "F03")
    )
    item = AuthoringPlanItemV1(
        recipe_id=recipe.recipe_id,
        recipe_version=recipe.recipe_version,
        coverage_role="CELL",
        supplement_reason=None,
        capability_id="C03",
        benchmark_family="F03",
        practitioner_question_class=packet.practitioner_question_class,
        origin_class=CaseOrigin.EXPERT_AUTHORED_SEMANTIC,
        scoring_profile=ScoringProfile.CLASSIFICATION_V1,
        authority_class="EXPERT_SEMANTIC",
        authority_kinds=("EXPERT_RUBRIC",),
        source_reference_ids=("TEST-RUBRIC:STORE-ROUNDTRIP",),
        source_search_strata=(),
        parent_candidate_id=None,
        engine_reference_case_id=None,
        engine_operation_id=None,
        generator_id=None,
        generator_registry_digest=None,
        seed_namespace=None,
        seed_block=None,
        difficulty=DifficultyLevel.EASY,
        adversarial_tags=packet.adversarial_tags,
        authoring_rationale="Synthetic test packet proves external canonical round trip.",
        candidate_id=packet.candidate_id,
        candidate_payload_hash=packet.candidate_payload_hash,
    )
    plan = bind_authoring_plan(
        AuthoringPlanV1(
            plan_id="PSE-V1-QUALIFICATION/TEST-STORE-PLAN",
            plan_version="pse-authoring-plan@1.0.0",
            coverage_matrix_digest=coverage_manifest_digest(),
            recipe_registry_digest=authoring_recipe_registry_digest(),
            items=(item,),
            plan_digest=_ZERO_SHA,
        )
    )
    return packet, plan


def test_authoring_recipe_registry_has_a_real_operator_for_all_87_cells() -> None:
    validate_authoring_recipe_registry()

    assert len(AUTHORING_RECIPE_REGISTRY) == 87
    assert all(recipe.operator_id for recipe in AUTHORING_RECIPE_REGISTRY)
    assert question_classes_for_cell("C17", "F13")
    assert question_classes_for_cell("C18", "F14")
    assert question_classes_for_cell("C99", "F99") == ()


def test_generic_semantic_operators_validate_each_supported_cell() -> None:
    semantic_recipes = tuple(
        item
        for item in AUTHORING_RECIPE_REGISTRY
        if item.capability_id not in {"C08", "C13", "C16"}
    )

    for recipe in semantic_recipes:
        packet = _semantic_cell_candidate(recipe.capability_id, recipe.benchmark_family)
        validate_candidate_review_packet(packet)
        expected_citations = (
            *_BASE_SEMANTIC_CITATIONS,
            *_CAPABILITY_AUTHORITY_CITATIONS.get(recipe.capability_id, ()),
        )
        assert packet.proposed_provenance.author_id == AUTHORING_PROCESS_ID
        assert set(expected_citations).issubset(packet.proposed_provenance.authority_lineage)


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


def test_production_seed_namespace_binds_split_generator_version_and_block() -> None:
    namespace = production_seed_namespace(
        SplitName.HIDDEN_FINAL,
        "res115.synthetic-refusal",
        "1.0.0",
        "block-001",
    )
    assert namespace == ("PSE-V1/HIDDEN_FINAL/res115.synthetic-refusal:1.0.0@block-001")
    assert parse_production_seed_namespace(namespace).split_name is SplitName.HIDDEN_FINAL
    validate_split_qualified_seed_namespace(
        namespace,
        split_name=SplitName.HIDDEN_FINAL,
        generator_id="res115.synthetic-refusal",
        generator_version="1.0.0",
        seed_block="block-001",
    )
    for malformed in (
        "PSE-V1-QUALIFICATION/generator/block-1",
        "PSE-V1/PRODUCTION/generator@block-1",
        "PSE-V1/HIDDEN_FINAL/generator/1.0.0@block-1",
        "PSE-V1/HIDDEN_FINAL/generator:1.0.0@",
    ):
        with pytest.raises(ValueError):
            parse_production_seed_namespace(malformed)
    with pytest.raises(ValueError, match="differs"):
        validate_split_qualified_seed_namespace(
            namespace,
            split_name=SplitName.HIDDEN_FINAL,
            generator_id="another-generator",
            generator_version="1.0.0",
            seed_block="block-001",
        )
    with pytest.raises(ValueError, match="differs"):
        validate_split_qualified_seed_namespace(
            namespace,
            split_name=SplitName.HIDDEN_FINAL,
            generator_id="res115.synthetic-refusal",
            generator_version="1.0.0",
            seed_block="block-002",
        )


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


def test_private_qualification_seed_input_is_complete_unique_and_version_bound() -> None:
    seed_input = _test_seed_input()

    assert seed_input.generator_registry_digest == RES115_SYNTHETIC_GENERATOR_DIGEST
    assert len(seed_input.seed_blocks) == 2
    with pytest.raises(ValueError, match="cannot collide"):
        replace(
            seed_input,
            seed_blocks=(
                seed_input.seed_blocks[0],
                (seed_input.seed_blocks[1][0], seed_input.seed_blocks[0][1]),
            ),
        )
    with pytest.raises(ValueError, match="every synthetic RES-71 refusal"):
        replace(seed_input, seed_blocks=seed_input.seed_blocks[:-1])


def test_pure_synthetic_refusal_generator_is_versioned_and_non_numeric() -> None:
    seed_input = _test_seed_input()
    reference = next(
        item for item in get_reference_cases() if item.case_id == seed_input.seed_blocks[0][0]
    )
    seed_block = seed_input.seed_blocks[0][1]

    generated = generate_synthetic_unregistered_operation_context(
        reference,
        seed_block=seed_block,
    )

    assert generated == generate_synthetic_unregistered_operation_context(
        reference,
        seed_block=seed_block,
    )
    assert generated["fixture_scope"] == "QUALIFICATION_ONLY"
    assert generated["numeric_gold_generated"] is False


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


def test_external_candidate_store_round_trip_and_packet_file_integrity(
    tmp_path: Path,
) -> None:
    packet, plan = _store_roundtrip_fixture()
    validate_candidate_review_packet(packet)

    receipt = write_qualification_store(
        (packet,),
        plan,
        batch_id="PSE-V1-QUALIFICATION/TEST-STORE-ROUNDTRIP",
        repository_root=tmp_path / "public-repo",
        qualification_root=tmp_path / "outside-git-store",
        require_all_cells=False,
    )

    restored = read_qualification_store(
        receipt,
        repository_root=tmp_path / "public-repo",
        qualification_root=tmp_path / "outside-git-store",
    )
    assert restored == (packet,)
    assert receipt.candidate_count == 1
    assert receipt.total_bytes > 0
    assert not (tmp_path / "public-repo" / receipt.store_relative_path).exists()

    seed_input = _test_seed_input()
    relative_path, seed_digest, seed_size = write_external_qualification_json(
        seed_input,
        "qualification/authoring_plan/private_seed_inputs.json",
        repository_root=tmp_path / "public-repo",
        qualification_root=tmp_path / "outside-git-store",
    )
    restored_seed_input, restored_digest, restored_size = read_external_qualification_json(
        relative_path,
        QualificationSeedInputV1,
        repository_root=tmp_path / "public-repo",
        qualification_root=tmp_path / "outside-git-store",
    )
    assert restored_seed_input == seed_input
    assert restored_digest == seed_digest
    assert restored_size == seed_size


def test_external_qualification_writer_rejects_symlink_escape(tmp_path: Path) -> None:
    repository = tmp_path / "public-repo"
    repository.mkdir()
    external_root = tmp_path / "external-store"
    external_root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (external_root / "qualification").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="escapes its canonical root"):
        write_external_qualification_json(
            _test_seed_input(),
            "qualification/authoring_plan/private_seed_inputs.json",
            repository_root=repository,
            qualification_root=external_root,
        )
    assert not tuple(outside.rglob("*.json"))


def test_live_res71_reference_lane_uses_all_twelve_cases_without_formula_gold() -> None:
    packets = build_res115_reference_lane(_test_seed_input())
    ids = validate_res115_reference_lane(packets)

    assert len(ids) == 12
    assert len(packets) == 12
    assert len({packet.candidate_payload_hash for packet in packets}) == 12
    assert {reference.status for reference in get_reference_cases()} == set(ReferenceCaseStatus)
    validate_candidate_set(packets)


def test_production_synthetic_question_surface_is_deterministic_and_scenario_specific() -> None:
    from dynamislm.benchmark.production import PRODUCTION_SYNTHETIC_QUESTION_SURFACE_VARIANTS
    from dynamislm.benchmark.production_authoring import (
        _production_synthetic_question,
        _scenario_ids,
    )

    questions = []
    for family, _variant_id in PRODUCTION_SYNTHETIC_QUESTION_SURFACE_VARIANTS:
        for index in range(3):
            seed = hashlib.sha256(
                f"RES-128-synthetic-scenario:{family}:{index}".encode()
            ).hexdigest()
            question = _production_synthetic_question(
                _scenario_ids(seed),
                family=family,
            )
            rerun = _production_synthetic_question(
                _scenario_ids(seed),
                family=family,
            )
            assert question.encode("utf-8") == rerun.encode("utf-8")
            questions.append(question)

    for index, question in enumerate(questions):
        for other in questions[index + 1 :]:
            assert not exact_13_token_shingles(question).intersection(
                exact_13_token_shingles(other)
            )


def test_c07_comparability_surface_is_deterministic_and_scenario_specific() -> None:
    from dynamislm.benchmark.production_authoring import (
        _c07_mutation_question,
        _c07_semantic_question,
        _semantic_facts,
    )

    questions = []
    for family in ("F04", "F06", "F13", "F14"):
        for index in range(3):
            seed = hashlib.sha256(f"RES-128-C07-scenario:{family}:{index}".encode()).hexdigest()
            facts = _semantic_facts("C07", family, seed)
            question = _c07_semantic_question(facts)
            rerun = _c07_semantic_question(_semantic_facts("C07", family, seed))
            assert question.encode("utf-8") == rerun.encode("utf-8")
            questions.append(question)
            for stage in (1, 2, 3):
                token = "MUTX" + hashlib.sha256(f"{seed}:{stage}".encode()).hexdigest()[:10].upper()
                mutation_question = _c07_mutation_question(
                    facts,
                    token=token,
                    stage=stage,
                )
                assert mutation_question.encode("utf-8") == _c07_mutation_question(
                    _semantic_facts("C07", family, seed),
                    token=token,
                    stage=stage,
                ).encode("utf-8")
                questions.append(mutation_question)

    for index, question in enumerate(questions):
        for other in questions[index + 1 :]:
            assert not exact_13_token_shingles(question).intersection(
                exact_13_token_shingles(other)
            )


def test_c01_c03_identity_surfaces_are_deterministic_and_scenario_specific() -> None:
    from dynamislm.benchmark.production_authoring import (
        _c01_semantic_question,
        _c03_semantic_question,
        _semantic_facts,
    )

    questions = []
    for capability_id in ("C01", "C03"):
        row = next(row for row in COVERAGE_MATRIX if row.capability_id == capability_id)
        question_builder = (
            _c01_semantic_question if capability_id == "C01" else _c03_semantic_question
        )
        for family in row.benchmark_families:
            for index in range(3):
                seed = hashlib.sha256(
                    f"RES-128-{capability_id}-scenario:{family}:{index}".encode()
                ).hexdigest()
                facts = _semantic_facts(capability_id, family, seed)
                question = question_builder(facts)
                rerun = question_builder(_semantic_facts(capability_id, family, seed))
                assert question.encode("utf-8") == rerun.encode("utf-8")
                questions.append(question)

    for index, question in enumerate(questions):
        for other in questions[index + 1 :]:
            assert not exact_13_token_shingles(question).intersection(
                exact_13_token_shingles(other)
            )


def test_c09_claim_surfaces_are_deterministic_and_scenario_specific() -> None:
    from dynamislm.benchmark.production_authoring import (
        _c09_mutation_question,
        _c09_semantic_question,
        _semantic_facts,
    )

    families = next(row.benchmark_families for row in COVERAGE_MATRIX if row.capability_id == "C09")
    questions = []
    for family in families:
        for index in range(3):
            seed = hashlib.sha256(f"RES-128-C09-scenario:{family}:{index}".encode()).hexdigest()
            facts = _semantic_facts("C09", family, seed)
            semantic_question = _c09_semantic_question(facts)
            assert semantic_question.encode("utf-8") == _c09_semantic_question(
                _semantic_facts("C09", family, seed)
            ).encode("utf-8")
            questions.append(semantic_question)
            for stage in (1, 2, 3):
                token = "MUTX" + hashlib.sha256(f"{seed}:{stage}".encode()).hexdigest()[:10].upper()
                mutation_question = _c09_mutation_question(facts, token=token, stage=stage)
                assert mutation_question.encode("utf-8") == _c09_mutation_question(
                    _semantic_facts("C09", family, seed), token=token, stage=stage
                ).encode("utf-8")
                questions.append(mutation_question)

    for index, question in enumerate(questions):
        for other in questions[index + 1 :]:
            assert not exact_13_token_shingles(question).intersection(
                exact_13_token_shingles(other)
            )


def test_c15_causal_mutation_surface_is_deterministic_and_scenario_specific() -> None:
    from dynamislm.benchmark.production_authoring import (
        _c15_mutation_question,
        _semantic_facts,
    )

    families = next(row.benchmark_families for row in COVERAGE_MATRIX if row.capability_id == "C15")
    questions = []
    for family in families:
        for index in range(3):
            seed = hashlib.sha256(f"RES-128-C15-mutation:{family}:{index}".encode()).hexdigest()
            context = _semantic_facts("C15", family, seed)
            for stage in (1, 2, 3):
                token = "MUTX" + hashlib.sha256(f"{seed}:{stage}".encode()).hexdigest()[:10].upper()
                question = _c15_mutation_question(context, token=token, stage=stage)
                assert question.encode("utf-8") == _c15_mutation_question(
                    _semantic_facts("C15", family, seed),
                    token=token,
                    stage=stage,
                ).encode("utf-8")
                questions.append(question)

    for index, question in enumerate(questions):
        for other in questions[index + 1 :]:
            assert not exact_13_token_shingles(question).intersection(
                exact_13_token_shingles(other)
            )


def test_engine_question_surfaces_are_deterministic_and_scenario_specific() -> None:
    from dynamislm.benchmark.production_authoring import (
        _production_engine_numeric_question,
        _production_engine_refusal_question,
        _scenario_ids,
    )

    questions = []
    for capability_id, families in (
        ("C08", ("F05",)),
        ("C16", ("F05", "F07", "F10", "F14")),
    ):
        for family in families:
            for index in range(3):
                seed = hashlib.sha256(
                    f"RES-128-engine:{capability_id}:{family}:{index}".encode()
                ).hexdigest()
                facts = _scenario_ids(seed)
                question = _production_engine_numeric_question(
                    facts,
                    capability_id=capability_id,
                    family=family,
                    reference_case_id=f"res71-engine-{family}",
                    operation_id=f"operation-{family}",
                )
                assert question.encode("utf-8") == _production_engine_numeric_question(
                    _scenario_ids(seed),
                    capability_id=capability_id,
                    family=family,
                    reference_case_id=f"res71-engine-{family}",
                    operation_id=f"operation-{family}",
                ).encode("utf-8")
                questions.append(question)
    for family in ("F05", "F06"):
        for index in range(3):
            seed = hashlib.sha256(f"RES-128-engine-refusal:{family}:{index}".encode()).hexdigest()
            question = _production_engine_refusal_question(
                _scenario_ids(seed),
                family=family,
                reference_case_id=f"res71-refusal-{family}",
                reference_family=f"refusal-family-{family}",
            )
            assert question.encode("utf-8") == _production_engine_refusal_question(
                _scenario_ids(seed),
                family=family,
                reference_case_id=f"res71-refusal-{family}",
                reference_family=f"refusal-family-{family}",
            ).encode("utf-8")
            questions.append(question)

    for index, question in enumerate(questions):
        for other in questions[index + 1 :]:
            assert not exact_13_token_shingles(question).intersection(
                exact_13_token_shingles(other)
            )


def test_source_question_surface_is_deterministic_and_scenario_specific() -> None:
    from dynamislm.benchmark.production_authoring import _production_source_question
    from dynamislm.qualification.res115_authoring import SourceCellSelectionV1, SourceSpanProposalV1

    questions = []
    for index in range(40):
        capability_id = ("C13", "C14")[index % 2]
        row = next(row for row in COVERAGE_MATRIX if row.capability_id == capability_id)
        family = row.benchmark_families[index % len(row.benchmark_families)]
        span_digest = "sha256:" + hashlib.sha256(f"synthetic-span:{index}".encode()).hexdigest()
        selection = SourceCellSelectionV1(
            pmcid=f"PMC{index % 7:04d}",
            capability_id=capability_id,
            benchmark_family=family,
            applicability_scope=(
                "DIRECT_TARGET_POPULATION_EVIDENCE"
                if index % 2
                else "INDIRECT_MEASUREMENT_EVIDENCE"
            ),
            source_family_id=f"synthetic-source-family:{index:03d}",
            source_family_digest="sha256:" + hashlib.sha256(f"family:{index}".encode()).hexdigest(),
            search_strata=(),
            spans=(
                SourceSpanProposalV1(
                    span_digest=span_digest,
                    locator="synthetic fixture span",
                    text="",
                    scope="",
                    support_rules=(),
                    support_tags=(),
                ),
            ),
            population_clause_values=(),
            direct_target=index % 2 == 1,
        )
        candidate_id = f"PSE-V1-CANDIDATE:SOURCE:synthetic:{index:03d}"
        question = _production_source_question(selection, candidate_id)
        assert question.encode("utf-8") == _production_source_question(
            selection, candidate_id
        ).encode("utf-8")
        questions.append(question)

    for index, question in enumerate(questions):
        for other in questions[index + 1 :]:
            assert not exact_13_token_shingles(question).intersection(
                exact_13_token_shingles(other)
            )


def test_c18_refusal_surfaces_are_deterministic_and_scenario_specific() -> None:
    from dynamislm.benchmark.production_authoring import (
        _c18_mutation_question,
        _c18_semantic_question,
        _semantic_facts,
    )

    families = next(row.benchmark_families for row in COVERAGE_MATRIX if row.capability_id == "C18")
    questions = []
    for family in families:
        for index in range(3):
            seed = hashlib.sha256(f"RES-128-C18-scenario:{family}:{index}".encode()).hexdigest()
            required_refusal = family == "F01"
            facts = _semantic_facts("C18", family, seed, required_refusal=required_refusal)
            semantic_question = _c18_semantic_question(
                facts,
                family=family,
                required_refusal=required_refusal,
            )
            assert semantic_question.encode("utf-8") == _c18_semantic_question(
                _semantic_facts("C18", family, seed, required_refusal=required_refusal),
                family=family,
                required_refusal=required_refusal,
            ).encode("utf-8")
            questions.append(semantic_question)
            if family != "F01":
                for stage in (1, 2, 3):
                    token = (
                        "MUTX" + hashlib.sha256(f"{seed}:{stage}".encode()).hexdigest()[:10].upper()
                    )
                    mutation_question = _c18_mutation_question(
                        facts,
                        family=family,
                        token=token,
                        stage=stage,
                    )
                    assert mutation_question.encode("utf-8") == _c18_mutation_question(
                        _semantic_facts("C18", family, seed, required_refusal=required_refusal),
                        family=family,
                        token=token,
                        stage=stage,
                    ).encode("utf-8")
                    questions.append(mutation_question)

    for index, question in enumerate(questions):
        for other in questions[index + 1 :]:
            assert not exact_13_token_shingles(question).intersection(
                exact_13_token_shingles(other)
            )


def test_c17_error_surfaces_are_deterministic_and_scenario_specific() -> None:
    from dynamislm.benchmark.production_authoring import (
        _c17_mutation_question,
        _c17_semantic_question,
        _semantic_facts,
    )

    families = next(row.benchmark_families for row in COVERAGE_MATRIX if row.capability_id == "C17")
    questions = []
    for family in families:
        for index in range(3):
            seed = hashlib.sha256(f"RES-128-C17-scenario:{family}:{index}".encode()).hexdigest()
            facts = _semantic_facts("C17", family, seed)
            candidate = _semantic_cell_candidate("C17", family)
            facts["unsafe_response_claim"] = dict(candidate.input.structured_context.items())[
                "unsafe_response_claim"
            ]
            semantic_question = _c17_semantic_question(facts)
            assert semantic_question.encode("utf-8") == _c17_semantic_question(facts).encode(
                "utf-8"
            )
            questions.append(((family, index), semantic_question))
            for stage in (1, 2, 3):
                token = "MUTX" + hashlib.sha256(f"{seed}:{stage}".encode()).hexdigest()[:10].upper()
                mutation_question = _c17_mutation_question(facts, token=token, stage=stage)
                assert mutation_question.encode("utf-8") == _c17_mutation_question(
                    facts,
                    token=token,
                    stage=stage,
                ).encode("utf-8")
                questions.append(((family, index), mutation_question))

    for index, (left_identity, question) in enumerate(questions):
        for right_identity, other in questions[index + 1 :]:
            if left_identity == right_identity:
                continue  # Parent/descendant mutation overlap is an authorized lineage edge.
            assert not exact_13_token_shingles(question).intersection(
                exact_13_token_shingles(other)
            )


def test_identity_mutation_surface_is_deterministic_and_scenario_specific() -> None:
    from dynamislm.benchmark.production_authoring import (
        _identity_mutation_question,
        _semantic_facts,
    )

    questions = []
    for capability_id in ("C01", "C03", "C04"):
        row = next(row for row in COVERAGE_MATRIX if row.capability_id == capability_id)
        for family in row.benchmark_families:
            for index in range(3):
                seed = hashlib.sha256(
                    f"RES-128-identity-mutation:{capability_id}:{family}:{index}".encode()
                ).hexdigest()
                facts = _semantic_facts(capability_id, family, seed)
                for stage in (1, 2, 3):
                    token = (
                        "MUTX" + hashlib.sha256(f"{seed}:{stage}".encode()).hexdigest()[:10].upper()
                    )
                    question = _identity_mutation_question(
                        facts,
                        capability_id=capability_id,
                        token=token,
                        stage=stage,
                    )
                    rerun = _identity_mutation_question(
                        _semantic_facts(capability_id, family, seed),
                        capability_id=capability_id,
                        token=token,
                        stage=stage,
                    )
                    assert question.encode("utf-8") == rerun.encode("utf-8")
                    questions.append(question)

    for index, question in enumerate(questions):
        for other in questions[index + 1 :]:
            assert not exact_13_token_shingles(question).intersection(
                exact_13_token_shingles(other)
            )


def test_all_semantic_question_surfaces_have_deterministic_scenario_variation() -> None:
    from dynamislm.benchmark.production_authoring import (
        _apply_adversarial_tag_focus,
        _production_adversarial_tags,
        _semantic_facts,
        _semantic_question,
        _semantic_slot_specs,
    )

    packet_by_cell = {}
    questions = []
    for candidate_id, capability_id, family, slot in _semantic_slot_specs():
        key = (capability_id, family)
        if key not in packet_by_cell:
            packet_by_cell[key] = _semantic_cell_candidate(*key)
        packet = packet_by_cell[key]
        seed = hashlib.sha256(f"RES-128-semantic-surface:{candidate_id}".encode()).hexdigest()
        required_refusal = capability_id == "C18" and family == "F01" and slot < 3
        facts = _semantic_facts(
            capability_id,
            family,
            seed,
            required_refusal=required_refusal,
        )
        tags = _production_adversarial_tags(capability_id, family, slot=slot)
        if capability_id == "C02":
            facts["missing_protocol_fields"] = (
                "device_identity",
                "event_definition",
                "phase_definition",
                "threshold_definition",
            )
        if capability_id == "C17":
            facts["unsafe_response_claim"] = dict(packet.input.structured_context.items())[
                "unsafe_response_claim"
            ]
        question = _apply_adversarial_tag_focus(
            _semantic_question(packet, facts),
            tags,
            scenario_id=str(facts["record"]),
        )
        assert question.encode("utf-8") == _apply_adversarial_tag_focus(
            _semantic_question(packet, facts),
            tags,
            scenario_id=str(facts["record"]),
        ).encode("utf-8")
        questions.append(question)

    for index, question in enumerate(questions):
        for other in questions[index + 1 :]:
            assert not exact_13_token_shingles(question).intersection(
                exact_13_token_shingles(other)
            )


def test_forged_res71_result_view_is_rejected() -> None:
    packet = next(
        item
        for item in build_res115_reference_lane(_test_seed_input())
        if item.candidate_id.endswith("res71-external-unit-km-to-m")
    )
    result = packet.input.deterministic_results[0]
    forged_result = DeterministicResultView(
        result_reference_id=result.result_reference_id,
        operation_id=result.operation_id,
        method_version=result.method_version,
        output_unit=result.output_unit,
        result_or_refusal_digest=result.result_or_refusal_digest,
        authority_reference=result.authority_reference,
        values={"value": 1001.0},
        refusal=None,
    )
    forged_packet = bind_candidate_review_packet(
        replace(
            packet,
            input=replace(packet.input, deterministic_results=(forged_result,)),
        )
    )

    with pytest.raises(ValueError, match="deterministic result view differs"):
        validate_candidate_review_packet(forged_packet)
    with pytest.raises(ValueError, match="deterministic result view differs"):
        validate_res115_reference_candidate(forged_packet)


@pytest.mark.skipif(
    not Path(
        "/mnt/e/Data/Datasets/DynamisLM/PerformanceScienceEval/manifests/accepted.jsonl"
    ).is_file(),
    reason="sealed Phase-A artifacts are required for the real qualification integration proof",
)
def test_real_qualification_draft_validates_all_cells_and_phase_a_lanes() -> None:
    draft = build_res115_qualification_draft(seed_input=_test_seed_input())
    receipt_entries = tuple(
        (packet.candidate_id, _digest(packet.candidate_id)) for packet in draft.packets
    )
    receipt = bind_candidate_store_receipt(
        CandidateStoreReceiptV1(
            batch_id=draft.batch_id,
            store_relative_path="qualification/candidates/ephemeral-preflight",
            candidate_file_digests=receipt_entries,
            candidate_count=len(draft.packets),
            total_bytes=1,
            authoring_plan_digest=draft.plan.plan_digest,
            artifact_inventory_digest=canonical_hash(receipt_entries),
            receipt_digest=_ZERO_SHA,
        )
    )
    manifest = build_res115_qualification_manifest(draft, receipt)

    validation = validate_res115_qualification_batch(draft, manifest, receipt)

    assert len(draft.packets) == 101
    assert validation.candidate_validation.represented_cells == 87
    assert validation.candidate_validation.represented_capabilities == 18
    assert validation.candidate_validation.represented_families == 14
    assert validation.candidate_validation.represented_question_classes == 8
    assert validation.candidate_validation.represented_origins == 5
    assert validation.candidate_validation.represented_scorers == 7
    assert validation.candidate_validation.represented_error_classes == len(ErrorClass)
    assert validation.candidate_validation.multi_stratum_mutation
    assert len(validation.reference_case_ids) == 12
    assert validation.source_validation.direct_target_document_count == 5
    assert validation.source_validation.evidence_strata_count == 10
    assert validation.source_validation.source_family_count >= 10


@pytest.mark.parametrize("location", ("history", "index", "worktree", "ignored_worktree"))
def test_qualification_packet_copied_into_git_fails_leak_guard(
    tmp_path: Path,
    location: str,
) -> None:
    packet, plan = _store_roundtrip_fixture()
    repository = tmp_path / "public-repo"
    repository.mkdir()
    subprocess.run(("git", "init", "-q", str(repository)), check=True)
    subprocess.run(
        ("git", "-C", str(repository), "config", "user.name", "Qualification test"),
        check=True,
    )
    subprocess.run(
        (
            "git",
            "-C",
            str(repository),
            "config",
            "user.email",
            "qualification-test@example.invalid",
        ),
        check=True,
    )
    (repository / "README.md").write_text("empty synthetic leak-guard fixture\n", encoding="utf-8")
    subprocess.run(("git", "-C", str(repository), "add", "README.md"), check=True)
    subprocess.run(
        ("git", "-C", str(repository), "commit", "-q", "-m", "fixture baseline"),
        check=True,
    )
    external_root = tmp_path / "external-store"
    receipt = write_qualification_store(
        (packet,),
        plan,
        batch_id="PSE-V1-QUALIFICATION/TEST-LEAK-GUARD",
        repository_root=repository,
        qualification_root=external_root,
        require_all_cells=False,
    )
    if location == "ignored_worktree":
        (repository / ".gitignore").write_text(
            "qualification-leak.json\n",
            encoding="utf-8",
        )
    copied_packet = (
        external_root
        / receipt.store_relative_path
        / (hashlib.sha256(packet.candidate_id.encode("utf-8")).hexdigest() + ".json")
    ).read_bytes()
    (repository / "qualification-leak.json").write_bytes(copied_packet)
    if location in {"history", "index"}:
        subprocess.run(("git", "-C", str(repository), "add", "qualification-leak.json"), check=True)
    if location == "history":
        subprocess.run(
            ("git", "-C", str(repository), "commit", "-q", "-m", "leaked fixture packet"),
            check=True,
        )

    with pytest.raises(ValueError, match="external qualification packet"):
        validate_qualification_repository_boundary(
            (packet,),
            plan,
            receipt,
            repository_root=repository,
            qualification_root=external_root,
        )
