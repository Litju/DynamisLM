from __future__ import annotations

import datetime as datetime_module
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from dynamislm.benchmark import (
    CandidateAnswer,
    ContaminationAudit,
    ContaminationGateEvidence,
    ErrorClass,
    ExclusionRegistry,
    HiddenAccessRequest,
    HiddenStoreDescriptor,
    Principal,
    ProtectedEvaluationStoreDescriptor,
    ProtectedStoreAccessEvidenceV1,
    ProtectedStoreAccessGrantV1,
    ProtectedStoreAccessRequest,
    SplitName,
    TaskOutcome,
    allocate_splits,
    audit_contamination,
    bind_case_payload,
    bind_res71_operation,
    bind_res71_refusal,
    build_contamination_gate_evidence,
    build_contamination_report,
    build_error_event_report,
    build_fixture_allocation,
    build_fixture_exclusion_registry,
    build_fixture_manifest_bundle,
    build_hidden_access_evidence,
    build_manifest_bundle,
    build_overlap_disposition,
    build_protected_access_evidence,
    build_res71_runtime_binding,
    build_synthetic_reference_fixture_cases,
    capability_family_lower_bound_case_count,
    coverage_manifest_digest,
    coverage_obligation_count,
    executable_full_coverage_minimum_case_count,
    make_authority_binding,
    minimum_full_coverage_case_count,
    preflight_hidden_access,
    preflight_protected_store_access,
    preflight_public_development_distribution,
    preflight_training_exclusion,
    public_protected_case_commitments,
    score_case,
    target_counts,
    validate_authority_binding,
    validate_case,
    validate_case_coverage,
    validate_case_payload_hash,
    validate_case_set,
    validate_coverage_matrix,
    validate_final_v1_freeze,
    validate_manifest_bundle,
    validate_protected_access_evidence,
    validate_protected_repository_boundary,
    validate_protected_store_namespace_isolation,
    validate_res71_operation_binding,
    validate_res71_refusal_binding,
    validate_res71_runtime_binding,
    validate_split_assignment,
)
from dynamislm.benchmark.constants import (
    AuthorityKind,
    CaseOrigin,
    OverlapDecision,
    PreflightStatus,
    ScoringProfile,
)
from dynamislm.benchmark.contracts import BenchmarkCaseV1
from dynamislm.serialization import canonical_json, from_canonical_json


def _protected_grants(
    *,
    credential_principal: Principal = Principal.EVALUATION_SERVICE,
    read_principal: Principal = Principal.EVALUATION_SERVICE,
) -> tuple[ProtectedStoreAccessGrantV1, ...]:
    return tuple(
        sorted(
            (
                ProtectedStoreAccessGrantV1(
                    principal=principal,
                    artifact_kind=artifact_kind,
                    credential_present=principal is credential_principal,
                    read_allowed=principal is read_principal,
                )
                for principal in Principal
                for artifact_kind in ("PAYLOAD", "ANSWER")
            ),
            key=lambda grant: (
                Principal(grant.principal).value.encode("utf-8"),
                grant.artifact_kind.encode("utf-8"),
            ),
        )
    )


def test_frozen_coverage_matrix_proves_all_capabilities_and_families() -> None:
    result = validate_coverage_matrix()

    assert result.status == "PASS"
    assert len(result.represented_capabilities) == 18
    assert len(result.represented_families) == 14
    assert coverage_manifest_digest().startswith("sha256:")
    assert validate_case_coverage(build_synthetic_reference_fixture_cases()).status == "BLOCKED"


def test_case_hash_is_content_only_and_round_trips_with_serialization_v3() -> None:
    case = build_synthetic_reference_fixture_cases()[0]

    validate_case_payload_hash(case)
    restored = from_canonical_json(canonical_json(case), BenchmarkCaseV1)
    assert restored == case

    split_mutation = replace(
        case,
        split=replace(
            case.split,
            split_name=SplitName.HIDDEN_FINAL,
            split_manifest_version=None,
            split_manifest_hash=None,
            membership_digest=None,
        ),
    )
    assert split_mutation.case_payload_hash == case.case_payload_hash
    with pytest.raises(ValueError, match="payload hash mismatch"):
        validate_case_payload_hash(
            replace(
                case,
                question="mutated question",
                input=replace(case.input, question_text="mutated question"),
            )
        )
    with pytest.raises(TypeError):
        case.input.structured_context["mutation"] = True  # type: ignore[index]


def test_res71_runtime_reference_operation_and_refusal_bindings_are_live() -> None:
    runtime = build_res71_runtime_binding()
    validate_res71_runtime_binding(runtime)

    operation = bind_res71_operation(
        "dynamislm:registered-operation:unit-normalization@1.0.0",
        reference_case_id="res71-external-unit-km-to-m",
    )
    validate_res71_operation_binding(operation)
    refusal = bind_res71_refusal("CMJ RFD")
    validate_res71_refusal_binding(refusal)

    with pytest.raises(ValueError):
        validate_res71_runtime_binding(
            replace(runtime, sealed_reference_digest="sha256:" + "0" * 64)
        )
    with pytest.raises(ValueError):
        bind_res71_operation(
            "dynamislm:registered-operation:unit-normalization@1.0.0",
            reference_case_id="res71-causal-overclaim-refusal",
        )


def test_authority_and_provenance_fail_closed() -> None:
    cases = build_synthetic_reference_fixture_cases()
    for case in cases:
        validate_case(case)
    validate_case_set(cases)

    engine = cases[0]
    with pytest.raises(ValueError):
        validate_case(
            replace(
                engine,
                authority=(
                    replace(engine.authority[0], digest="sha256:" + "0" * 64),
                    *engine.authority[1:],
                ),
            )
        )


def test_res60_res62_res69_bindings_reject_cross_authority_forgery() -> None:
    population = make_authority_binding(
        AuthorityKind.RES60_POPULATION,
        governed_field_ids=("expected_answer",),
    )
    provenance = make_authority_binding(
        AuthorityKind.RES62_PROVENANCE,
        governed_field_ids=("expected_answer",),
    )
    statistics = make_authority_binding(
        AuthorityKind.RES69_STATISTICS,
        governed_field_ids=("expected_answer",),
    )
    for binding in (population, provenance, statistics):
        validate_authority_binding(binding)
    with pytest.raises(ValueError):
        validate_authority_binding(replace(population, digest=provenance.digest))
    with pytest.raises(ValueError):
        validate_authority_binding(replace(provenance, version="0.0.0"))
    with pytest.raises(ValueError):
        make_authority_binding(
            AuthorityKind.RES69_STATISTICS,
            source_reference_id=population.source_reference_id,
            governed_field_ids=("expected_answer",),
        )


def test_ground_truth_and_mutation_contracts_reject_forged_metadata() -> None:
    cases = build_synthetic_reference_fixture_cases()
    engine = cases[0]
    missing_expected = bind_case_payload(
        replace(
            engine,
            expected_answer=replace(
                engine.expected_answer,
                required_field_ids=("value", "missing"),
            ),
            case_payload_hash="sha256:" + "0" * 64,
        )
    )
    with pytest.raises(ValueError, match="absent from expected_fields"):
        validate_case(missing_expected)
    missing_authority = bind_case_payload(
        replace(
            engine,
            authority=tuple(
                replace(binding, governed_field_ids=("input.deterministic_results",))
                for binding in engine.authority
            ),
            case_payload_hash="sha256:" + "0" * 64,
        )
    )
    with pytest.raises(ValueError, match="not covered"):
        validate_case(missing_authority)
    mutation = next(
        case for case in cases if case.provenance.origin_class is CaseOrigin.ADVERSARIAL_MUTATION
    )
    forged_mutation = bind_case_payload(
        replace(
            mutation,
            provenance=replace(mutation.provenance, changed_fields=("question",)),
            case_payload_hash="sha256:" + "0" * 64,
        )
    )
    with pytest.raises(ValueError, match="changed_fields"):
        validate_case_set(tuple(forged_mutation if case is mutation else case for case in cases))
    with pytest.raises(ValueError):
        replace(engine.provenance.review, approval_status="PENDING")

    source = next(
        case
        for case in cases
        if case.provenance.origin_class.value == "SOURCE_BACKED_EVIDENCE_EXTRACTION"
    )
    with pytest.raises(ValueError):
        validate_case(
            replace(
                source,
                provenance=replace(
                    source.provenance,
                    origin_class=CaseOrigin.DETERMINISTIC_SYNTHETIC,
                ),
            )
        )


def test_declared_error_classes_need_a_reachable_scorer_path() -> None:
    case = next(
        item
        for item in build_synthetic_reference_fixture_cases()
        if item.case_id == "fixture-expert-refusal"
    )
    unreachable = ErrorClass.DIRECT_DERIVED_COLLAPSE
    forged = bind_case_payload(
        replace(
            case,
            scoring_contract=replace(
                case.scoring_contract,
                error_class_rules=(*case.scoring_contract.error_class_rules, unreachable),
            ),
            case_payload_hash="sha256:" + "0" * 64,
        )
    )
    with pytest.raises(ValueError, match="no reachable scorer path"):
        validate_case(forged)

    report = build_error_event_report((), (forged,))
    assert report.eligible_denominators[unreachable.value] == 0
    assert report.eligible_denominators[ErrorClass.UNDER_SPECIFIED_REFUSAL.value] == 1


def test_source_authority_must_bind_typed_source_and_exact_span_identity() -> None:
    source = next(
        case
        for case in build_synthetic_reference_fixture_cases()
        if case.provenance.origin_class is CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION
    )
    source_binding = source.authority[0]
    source_reference = source.source_evidence_refs[0]
    document = source_reference.document_identity
    assert document is not None
    span = source.input.evidence_excerpts[0].span_identity
    assert source.provenance.source_artifact_ids == (
        source.input.evidence_excerpts[0].source_artifact_identity.artifact_id,
    )
    assert source.provenance.source_artifact_ids[0] != document.document_id
    assert document.content_digest != source.provenance.source_content_digests[0]
    assert source.provenance.source_content_digests == (
        source.input.evidence_excerpts[0].source_artifact_identity.content_digest,
    )
    assert source.contamination.source_artifact_ids == source.provenance.source_artifact_ids
    assert source.contamination.document_ids == (document.document_id,)
    assert source_binding.source_reference_id == span.span_id
    assert source_binding.digest == span.span_digest
    assert from_canonical_json(canonical_json(source), BenchmarkCaseV1) == source
    with pytest.raises(ValueError, match="exact document identity"):
        replace(
            source_reference,
            source_reference_id=source.provenance.source_artifact_ids[0],
        )
    with pytest.raises(ValueError, match="exact excerpt text bytes"):
        replace(
            source.input.evidence_excerpts[0],
            span_identity=replace(span, span_digest="sha256:" + "0" * 64),
        )
    source_excerpt = source.input.evidence_excerpts[0]
    with pytest.raises(ValueError, match="exact source artifact bytes"):
        replace(
            source_excerpt,
            source_artifact_identity=replace(
                source_excerpt.source_artifact_identity,
                content_digest="sha256:" + "f" * 64,
            ),
        )

    wrong_span_identity = bind_case_payload(
        replace(
            source,
            authority=(replace(source_binding, source_reference_id="fixture-source"),),
            case_payload_hash="sha256:" + "0" * 64,
        )
    )
    with pytest.raises(ValueError, match="source-evidence-span authority identity"):
        validate_case(wrong_span_identity)

    wrong_span_digest = bind_case_payload(
        replace(
            source,
            authority=(replace(source_binding, digest="sha256:" + "0" * 64),),
            case_payload_hash="sha256:" + "0" * 64,
        )
    )
    with pytest.raises(ValueError, match="source-evidence-span authority identity"):
        validate_case(wrong_span_digest)

    caller_minted_artifact = bind_case_payload(
        replace(
            source,
            provenance=replace(source.provenance, source_artifact_ids=("caller-source",)),
            case_payload_hash="sha256:" + "0" * 64,
        )
    )
    with pytest.raises(ValueError, match="source artifact identity/digest"):
        validate_case(caller_minted_artifact)

    caller_minted_artifact_digest = bind_case_payload(
        replace(
            source,
            provenance=replace(
                source.provenance,
                source_content_digests=("sha256:" + "f" * 64,),
            ),
            case_payload_hash="sha256:" + "0" * 64,
        )
    )
    with pytest.raises(ValueError, match="source artifact identity/digest"):
        validate_case(caller_minted_artifact_digest)

    caller_minted_document = bind_case_payload(
        replace(
            source,
            contamination=replace(source.contamination, document_ids=("caller-document",)),
            case_payload_hash="sha256:" + "0" * 64,
        )
    )
    with pytest.raises(ValueError, match="contamination document identity"):
        validate_case(caller_minted_document)

    caller_minted_contamination_artifact = bind_case_payload(
        replace(
            source,
            contamination=replace(
                source.contamination,
                source_artifact_ids=("caller-source-artifact",),
            ),
            case_payload_hash="sha256:" + "0" * 64,
        )
    )
    with pytest.raises(ValueError, match="contamination source artifact IDs"):
        validate_case(caller_minted_contamination_artifact)

    source_document_authority = replace(
        source_binding,
        authority_kind=AuthorityKind.SOURCE_DOCUMENT.value,
        source_reference_id=document.document_id,
        version=document.version,
        digest=document.identity_digest,
        governed_field_ids=("expected_answer",),
    )
    document_bound = bind_case_payload(
        replace(
            source,
            authority=(*source.authority, source_document_authority),
            case_payload_hash="sha256:" + "0" * 64,
        )
    )
    validate_case(document_bound)

    excerpt = document_bound.input.evidence_excerpts[0]
    changed_document = replace(document, doi="10.0000/different-document")
    changed_excerpt = replace(excerpt, document_identity=changed_document)
    changed_source_reference = replace(
        source_reference,
        document_identity=changed_document,
    )
    changed_identity = bind_case_payload(
        replace(
            document_bound,
            source_evidence_refs=(changed_source_reference,),
            input=replace(document_bound.input, evidence_excerpts=(changed_excerpt,)),
            case_payload_hash="sha256:" + "0" * 64,
        )
    )
    with pytest.raises(ValueError, match="source-document authority identity"):
        validate_case(changed_identity)

    wrong_document_identity = bind_case_payload(
        replace(
            document_bound,
            authority=(
                source_binding,
                replace(
                    source_document_authority,
                    source_reference_id=source.provenance.source_artifact_ids[0],
                ),
            ),
            case_payload_hash="sha256:" + "0" * 64,
        )
    )
    with pytest.raises(ValueError, match="source-document authority identity"):
        validate_case(wrong_document_identity)


def test_split_allocator_is_deterministic_exact_and_lineage_atomic() -> None:
    from dynamislm.benchmark.split import allocate_splits

    cases = build_synthetic_reference_fixture_cases()
    first = allocate_splits(cases)
    second = allocate_splits(cases)

    assert first.cases == second.cases
    assert first.target_counts == {
        SplitName.PUBLIC_DEVELOPMENT: 4,
        SplitName.FROZEN_VALIDATION: 1,
        SplitName.HIDDEN_FINAL: 1,
    }
    parent = next(case for case in first.cases if case.case_id == "fixture-expert-refusal")
    mutation = next(
        case for case in first.cases if case.case_id == "fixture-adversarial-refusal-mutation"
    )
    assert parent.split.split_name is mutation.split.split_name

    allocated = first.cases
    # The case set is provisional until manifests bind split hashes.
    with pytest.raises(ValueError, match="missing split manifest"):
        validate_split_assignment(allocated)


def _build_full_coverage_qualification_cases() -> tuple[BenchmarkCaseV1, ...]:
    from dynamislm.benchmark.coverage import COVERAGE_MATRIX
    from dynamislm.benchmark.hashing import bind_case_payload
    from dynamislm.benchmark.scoring_paths import reachable_error_classes
    from dynamislm.serialization import canonical_hash

    fixtures = build_synthetic_reference_fixture_cases()
    expert_template = next(
        case
        for case in fixtures
        if case.provenance.origin_class is CaseOrigin.EXPERT_AUTHORED_SEMANTIC
    )
    engine_template = next(
        case
        for case in fixtures
        if case.provenance.origin_class is CaseOrigin.DETERMINISTIC_ENGINE_DERIVED
    )

    def non_v1_template(template: BenchmarkCaseV1) -> BenchmarkCaseV1:
        context = {
            key: value
            for key, value in template.input.structured_context.items()
            if key != "fixture"
        }
        review_digest = canonical_hash({"rubric": "non-v1-synthetic-qualification"})
        review = replace(
            template.provenance.review,
            author_id="qualification-expert-author",
            reviewer_id="qualification-independent-reviewer",
            review_scope="synthetic in-memory qualification only",
            rubric_digest=review_digest,
        )
        authority = tuple(
            replace(
                binding,
                source_reference_id="qualification-expert-rubric-v1",
                digest=review_digest,
            )
            if binding.authority_kind == "EXPERT_RUBRIC"
            else binding
            for binding in template.authority
        )
        result_id_map = {
            result.result_reference_id: result.result_reference_id.replace(
                "fixture-", "qualification-"
            )
            for result in template.input.deterministic_results
        }
        return bind_case_payload(
            replace(
                template,
                input=replace(
                    template.input,
                    structured_context=context,
                    deterministic_results=tuple(
                        replace(
                            result,
                            result_reference_id=result_id_map[result.result_reference_id],
                        )
                        for result in template.input.deterministic_results
                    ),
                ),
                authority=authority,
                claim_contract=replace(
                    template.claim_contract,
                    requested_claim="synthetic qualification-only interpretation",
                ),
                provenance=replace(
                    template.provenance,
                    authority_lineage=(
                        ("qualification-expert-rubric-v1", "RES-70")
                        if template.provenance.origin_class is CaseOrigin.EXPERT_AUTHORED_SEMANTIC
                        else template.provenance.authority_lineage
                    ),
                    derivation_edges=tuple(
                        replace(
                            edge,
                            downstream_id=result_id_map.get(edge.downstream_id, edge.downstream_id),
                        )
                        for edge in template.provenance.derivation_edges
                    ),
                    population_scope="NON_V1_SYNTHETIC_QUALIFICATION",
                    review=review,
                ),
                difficulty=replace(
                    template.difficulty,
                    rationale="Synthetic in-memory full-coverage qualification only.",
                ),
                case_payload_hash="sha256:" + "0" * 64,
            )
        )

    expert_template = non_v1_template(expert_template)
    engine_template = non_v1_template(engine_template)
    scale_cases: list[BenchmarkCaseV1] = []

    def reachable_attribution(
        template: BenchmarkCaseV1, errors: tuple[ErrorClass, ...]
    ) -> tuple[tuple[str, ErrorClass], ...]:
        keys = list(template.scoring_contract.required_output_fields)
        if template.refusal_expectation.decision.value == "REQUIRED":
            keys.extend(("__decision__", "__refusal__"))
        elif template.refusal_expectation.decision.value == "ALLOWED":
            keys.append("__refusal__")
        else:
            keys.append("__over_refusal__")
        if template.expected_answer.prohibited_claims:
            keys.append("__prohibited_claim__")
        assert len(errors) <= len(keys)
        return tuple((key, errors[index % len(errors)]) for index, key in enumerate(keys))

    for row in COVERAGE_MATRIX:
        template = engine_template if row.capability_id in {"C08", "C16"} else expert_template
        if row.capability_id == "C16":
            c16_fields = ("value", "result_provenance", "claim_scope")
            c16_answer = replace(
                template.expected_answer,
                required_field_ids=c16_fields,
                expected_fields={
                    **template.expected_answer.expected_fields,
                    "result_provenance": "registered-result",
                    "claim_scope": "descriptive",
                },
            )
            template = bind_case_payload(
                replace(
                    template,
                    expected_answer=c16_answer,
                    scoring_contract=replace(
                        template.scoring_contract,
                        profile_id=ScoringProfile.STRUCTURED_FIELDS_V1,
                        required_output_fields=c16_fields,
                        critical_fields=c16_fields,
                    ),
                    case_payload_hash="sha256:" + "0" * 64,
                )
            )
        profile = (
            ScoringProfile.NUMERIC_TOLERANCE_V1
            if row.capability_id == "C08"
            else ScoringProfile.STRUCTURED_FIELDS_V1
            if row.capability_id == "C16"
            else next(
                item
                for item in (
                    ScoringProfile.CLASSIFICATION_V1,
                    ScoringProfile.STRUCTURED_FIELDS_V1,
                    ScoringProfile.REFUSAL_V1,
                )
                if item in row.scorer_profiles
            )
        )
        assert profile in row.scorer_profiles
        for family in row.benchmark_families:
            if row.capability_id == "C17":
                family_index = row.benchmark_families.index(family)
                errors = (
                    tuple(row.error_classes[:8])
                    if family_index % 2 == 0
                    else tuple(row.error_classes[4:])
                )
            else:
                errors = tuple(row.error_classes)
            for replica in range(3):
                index = len(scale_cases)
                case_id = f"scale-qualification-{row.capability_id}-{family}-{replica}"
                attribution = reachable_attribution(template, errors)
                question = f"In-memory scale qualification case {case_id}."
                scale_cases.append(
                    bind_case_payload(
                        replace(
                            template,
                            case_id=case_id,
                            capability_id=row.capability_id,
                            benchmark_family=family,
                            question=question,
                            input=replace(template.input, question_text=question),
                            scoring_contract=replace(
                                template.scoring_contract,
                                profile_id=profile,
                                error_class_rules=errors,
                                error_attribution=attribution,
                            ),
                            adversarial_tags=tuple(row.adversarial_tags),
                            split=replace(
                                template.split,
                                isolation_cluster_id=f"scale-cluster-{index:03d}",
                            ),
                            contamination=replace(
                                template.contamination,
                                source_family_id=f"scale-source-{index:03d}",
                                document_ids=(),
                                construct_test_identity_ids=(f"scale-construct-test-{index:03d}",),
                                provider_export_id=f"scale-provider-{index:03d}",
                                protocol_template_id=f"scale-template-{index:03d}",
                                expert_author_batch_id=f"scale-batch-{index:03d}",
                                artifact_ids=(f"scale-artifact-{index:03d}",),
                                benchmark_artifact_ids=(f"scale-artifact-{index:03d}",),
                                training_exclusion_ids=(f"scale-exclusion-{index:03d}",),
                            ),
                            case_payload_hash="sha256:" + "0" * 64,
                        )
                    )
                )

    # Add 173 unique, already-covered cases so N=434 has exact 260/87/87 targets.
    for replica in range(173):
        row = COVERAGE_MATRIX[0]
        template = expert_template
        errors = tuple(row.error_classes)
        attribution = reachable_attribution(template, errors)
        index = len(scale_cases)
        case_id = f"scale-qualification-fill-{replica:03d}"
        question = f"In-memory scale qualification fill case {case_id}."
        scale_cases.append(
            bind_case_payload(
                replace(
                    template,
                    case_id=case_id,
                    capability_id=row.capability_id,
                    benchmark_family=row.benchmark_families[0],
                    question=question,
                    input=replace(template.input, question_text=question),
                    scoring_contract=replace(
                        template.scoring_contract,
                        profile_id=ScoringProfile.CLASSIFICATION_V1,
                        error_class_rules=errors,
                        error_attribution=attribution,
                    ),
                    adversarial_tags=tuple(row.adversarial_tags),
                    split=replace(
                        template.split,
                        isolation_cluster_id=f"scale-cluster-{index:03d}",
                    ),
                    contamination=replace(
                        template.contamination,
                        source_family_id=f"scale-source-{index:03d}",
                        document_ids=(),
                        construct_test_identity_ids=(f"scale-construct-test-{index:03d}",),
                        provider_export_id=f"scale-provider-{index:03d}",
                        protocol_template_id=f"scale-template-{index:03d}",
                        expert_author_batch_id=f"scale-batch-{index:03d}",
                        artifact_ids=(f"scale-artifact-{index:03d}",),
                        benchmark_artifact_ids=(f"scale-artifact-{index:03d}",),
                        training_exclusion_ids=(f"scale-exclusion-{index:03d}",),
                    ),
                    case_payload_hash="sha256:" + "0" * 64,
                )
            )
        )
    cases = tuple(scale_cases)
    assert len(cases) == 434
    for case in cases:
        reachable = reachable_error_classes(
            case.scoring_contract,
            refusal_decision=case.refusal_expectation.decision,
            prohibited_claims=case.expected_answer.prohibited_claims,
        )
        assert reachable == set(case.scoring_contract.error_class_rules)
    return cases


def test_split_allocator_qualifies_the_frozen_benchmark_scale() -> None:
    """Requalify reachable errors at the exact executable minimum."""

    assert coverage_obligation_count() == 87
    assert capability_family_lower_bound_case_count() == 434
    assert executable_full_coverage_minimum_case_count() == 434
    assert minimum_full_coverage_case_count() == 434
    assert min(target_counts(433).values()) == 86
    assert target_counts(434) == {
        SplitName.PUBLIC_DEVELOPMENT: 260,
        SplitName.FROZEN_VALIDATION: 87,
        SplitName.HIDDEN_FINAL: 87,
    }
    cases = _build_full_coverage_qualification_cases()
    first = allocate_splits(cases, require_full_coverage=True)
    second = allocate_splits(cases, require_full_coverage=True)
    assert first.cases == second.cases
    assert first.target_counts == target_counts(434)
    assert tuple(first.target_counts[split] for split in SplitName) == (260, 87, 87)
    assert validate_case_coverage(first.cases, require_all_splits=True).status == "PASS"


@pytest.mark.parametrize(
    ("identity_field", "identity_value", "expected_kind"),
    (
        (
            "source_artifact_ids",
            ("shared-source-artifact",),
            "source-artifact-identity",
        ),
        ("document_ids", ("shared-document",), "document-identity"),
        (
            "construct_test_identity_ids",
            ("CMJ:countermovement-jump:test-v1",),
            "construct-test-identity",
        ),
    ),
)
def test_split_isolation_clusters_and_rejects_shared_identity_attacks(
    identity_field: str, identity_value: tuple[str, ...], expected_kind: str
) -> None:
    from dynamislm.benchmark.contamination import validate_source_family_isolation
    from dynamislm.benchmark.split import _union_find_clusters

    engine, semantic = build_synthetic_reference_fixture_cases()[:2]
    if identity_field == "document_ids":
        engine_contamination = replace(engine.contamination, document_ids=identity_value)
        semantic_contamination = replace(semantic.contamination, document_ids=identity_value)
    elif identity_field == "source_artifact_ids":
        engine_contamination = replace(engine.contamination, source_artifact_ids=identity_value)
        semantic_contamination = replace(semantic.contamination, source_artifact_ids=identity_value)
    else:
        engine_contamination = replace(
            engine.contamination, construct_test_identity_ids=identity_value
        )
        semantic_contamination = replace(
            semantic.contamination, construct_test_identity_ids=identity_value
        )
    paired = (
        replace(engine, contamination=engine_contamination),
        replace(semantic, contamination=semantic_contamination),
    )
    assert len(_union_find_clusters(paired)) == 1

    cross_split = (
        replace(
            paired[0],
            split=replace(paired[0].split, split_name=SplitName.PUBLIC_DEVELOPMENT),
        ),
        replace(
            paired[1],
            split=replace(paired[1].split, split_name=SplitName.FROZEN_VALIDATION),
        ),
    )
    with pytest.raises(ValueError, match=expected_kind):
        validate_source_family_isolation(cross_split)


def test_split_isolation_enforces_all_recorded_generator_seed_keys() -> None:
    from dynamislm.benchmark.contamination import validate_source_family_isolation
    from dynamislm.benchmark.split import _union_find_clusters

    template = next(
        case
        for case in build_synthetic_reference_fixture_cases()
        if case.provenance.origin_class is CaseOrigin.DETERMINISTIC_SYNTHETIC
    )
    cases = []
    for index in range(2):
        case_id = f"seed-isolation-{index}"
        cases.append(
            replace(
                template,
                case_id=case_id,
                split=replace(template.split, isolation_cluster_id=f"seed-cluster-{index}"),
                provenance=replace(
                    template.provenance,
                    generator_family=f"seed-generator-family-{index}",
                    seed_namespace=f"provenance-namespace-{index}",
                    seed_block=f"provenance-block-{index}",
                ),
                contamination=replace(
                    template.contamination,
                    source_family_id=f"seed-source-family-{index}",
                    artifact_ids=(f"artifact-seed-{index}",),
                    benchmark_artifact_ids=(f"benchmark-seed-{index}",),
                    training_exclusion_ids=(f"exclude-seed-{index}",),
                    protocol_template_id=f"seed-template-{index}",
                    expert_author_batch_id=f"seed-batch-{index}",
                    generator_namespace="shared-contamination-namespace",
                    generator_seed_block="shared-contamination-block",
                ),
            )
        )
    clusters = _union_find_clusters(tuple(cases))
    assert len(clusters) == 1
    assert clusters[0].generator_seed_blocks == (
        "provenance-block-0",
        "provenance-block-1",
        "shared-contamination-block",
    )
    cross_split = (
        replace(
            cases[0],
            split=replace(cases[0].split, split_name=SplitName.PUBLIC_DEVELOPMENT),
        ),
        replace(
            cases[1],
            split=replace(cases[1].split, split_name=SplitName.FROZEN_VALIDATION),
        ),
    )
    with pytest.raises(ValueError, match="seed-block crosses split boundary"):
        validate_source_family_isolation(cross_split)


def test_contamination_registry_runs_exact_and_fuzzy_mandatory_checks() -> None:
    allocation = build_fixture_allocation()
    registry = build_fixture_exclusion_registry(allocation)
    reference = replace(
        registry.artifacts[0],
        text="alpha bravo charlie delta echo foxtrot golf hotel",
    )
    exact_candidate = replace(
        reference,
        artifact_id="candidate-exact",
        source_family_id="new-family",
        benchmark_case_ids=(),
        benchmark_case_hashes=(),
        membership_digests=(),
        benchmark_split_names=(),
    )
    pair_registry = ExclusionRegistry.from_artifacts((reference,))
    exact_audit = audit_contamination(exact_candidate, pair_registry)
    assert exact_audit.status == "BLOCKED"
    assert reference.artifact_id in exact_audit.exact_matches

    fuzzy_candidate = replace(
        exact_candidate,
        artifact_id="candidate-fuzzy",
        text=reference.text.replace("hotel", "hotels"),
    )
    fuzzy_audit = audit_contamination(fuzzy_candidate, pair_registry)
    assert fuzzy_audit.status == "BLOCKED"
    assert reference.artifact_id in fuzzy_audit.fuzzy_matches
    with pytest.raises(ValueError, match="only a currently identified exact overlap"):
        build_overlap_disposition(
            fuzzy_candidate,
            reference.artifact_id,
            pair_registry,
            decision=OverlapDecision.APPROVED,
            rationale="Fuzzy-only evidence cannot be adjudicated.",
            reviewer_id="reviewer-contamination-fuzzy",
            reviewed_at=datetime_module.datetime(2026, 9, 23, tzinfo=datetime_module.UTC),
        )

    review_time = datetime_module.datetime(2026, 9, 23, tzinfo=datetime_module.UTC)
    approved_disposition = build_overlap_disposition(
        exact_candidate,
        reference.artifact_id,
        pair_registry,
        decision=OverlapDecision.APPROVED,
        rationale="Identical same-split source text is an expected synthetic qualification pair.",
        reviewer_id="reviewer-contamination-001",
        reviewed_at=review_time,
    )
    approved = audit_contamination(
        exact_candidate, pair_registry, dispositions=(approved_disposition,)
    )
    assert approved.status == "PASS"
    forged_review = replace(approved_disposition, rationale="altered after review")
    with pytest.raises(ValueError, match="hash is stale or forged"):
        audit_contamination(exact_candidate, pair_registry, dispositions=(forged_review,))
    gate_evidence = ContaminationGateEvidence(
        benchmark_manifest_hash="sha256:" + "1" * 64,
        exclusion_manifest_hash="sha256:" + "2" * 64,
        audits=(approved,),
        dispositions=(approved_disposition,),
    )
    assert gate_evidence.resolved
    assert gate_evidence.disposition_manifest_digest.startswith("sha256:")
    rejected_disposition = build_overlap_disposition(
        exact_candidate,
        reference.artifact_id,
        pair_registry,
        decision=OverlapDecision.REJECTED,
        rationale="Reject this exact overlap for the synthetic policy check.",
        reviewer_id="reviewer-contamination-002",
        reviewed_at=review_time,
    )
    rejected = audit_contamination(
        exact_candidate, pair_registry, dispositions=(rejected_disposition,)
    )
    assert rejected.status == "BLOCKED"
    no_private_index = ExclusionRegistry(entries=pair_registry.entries)
    blocked_without_private_text = audit_contamination(exact_candidate, no_private_index)
    assert blocked_without_private_text.status == "BLOCKED"
    report = build_contamination_report(approved)
    assert report.audit_label == "PSE_V1_CONTAMINATION_AUDIT=PASS"
    assert report.pretraining_exposure == "UNKNOWN"

    other_split = next(split for split in SplitName if split is not reference.split_name)
    cross_split_candidate = replace(
        exact_candidate,
        split_name=other_split,
        benchmark_split_names=(other_split,),
    )
    with pytest.raises(ValueError, match="can never be approved"):
        build_overlap_disposition(
            cross_split_candidate,
            reference.artifact_id,
            pair_registry,
            decision=OverlapDecision.APPROVED,
            rationale="An exact cross-split match remains prohibited.",
            reviewer_id="reviewer-contamination-003",
            reviewed_at=review_time,
        )


def test_parent_adversarial_mutation_exact_overlap_requires_pair_review() -> None:
    allocation = build_fixture_allocation()
    registry = build_fixture_exclusion_registry(allocation)
    mutation = next(
        case
        for case in allocation.cases
        if case.provenance.origin_class is CaseOrigin.ADVERSARIAL_MUTATION
    )
    assert mutation.provenance.parent_case_hash is not None
    parent = next(
        case
        for case in allocation.cases
        if case.case_payload_hash == mutation.provenance.parent_case_hash
    )
    assert parent.split.split_name is mutation.split.split_name
    parent_artifact = next(
        artifact
        for artifact in registry.artifacts
        if artifact.artifact_id == f"case:{parent.case_id}"
    )
    mutation_parent_artifact = next(
        artifact
        for artifact in registry.artifacts
        if artifact.artifact_id == f"mutation-parent:{parent.case_payload_hash}"
    )
    shared_parent_text = "Synthetic exact parent identity payload for lineage qualification."
    reviewed_registry = ExclusionRegistry.from_artifacts(
        (
            replace(parent_artifact, text=shared_parent_text),
            replace(mutation_parent_artifact, text=shared_parent_text),
        )
    )
    review_time = datetime_module.datetime(2026, 9, 23, tzinfo=datetime_module.UTC)
    parent_disposition = build_overlap_disposition(
        replace(parent_artifact, text=shared_parent_text),
        mutation_parent_artifact.artifact_id,
        reviewed_registry,
        decision=OverlapDecision.APPROVED,
        rationale="The exact overlap identifies a parent-child mutation within one split.",
        reviewer_id="reviewer-lineage-001",
        reviewed_at=review_time,
    )
    mutation_disposition = build_overlap_disposition(
        replace(mutation_parent_artifact, text=shared_parent_text),
        parent_artifact.artifact_id,
        reviewed_registry,
        decision=OverlapDecision.APPROVED,
        rationale="The exact overlap identifies a parent-child mutation within one split.",
        reviewer_id="reviewer-lineage-001",
        reviewed_at=review_time,
    )
    assert parent_disposition.lineage_relation.value == "PARENT_CHILD"
    assert mutation_disposition.lineage_relation.value == "PARENT_CHILD"
    parent_audit = audit_contamination(
        replace(parent_artifact, text=shared_parent_text),
        reviewed_registry,
        dispositions=(parent_disposition,),
    )
    mutation_audit = audit_contamination(
        replace(mutation_parent_artifact, text=shared_parent_text),
        reviewed_registry,
        dispositions=(mutation_disposition,),
    )
    assert parent_audit.status == "PASS"
    assert mutation_audit.status == "PASS"
    assert parent_disposition.split_relation.value == "SAME_SPLIT"
    assert parent_disposition.match_kind.value == "RAW_CONTENT_SHA256"

    cross_split_parent = replace(
        parent_artifact,
        text=shared_parent_text,
        split_name=next(split for split in SplitName if split is not parent.split.split_name),
        benchmark_split_names=(
            next(split for split in SplitName if split is not parent.split.split_name),
        ),
    )
    with pytest.raises(ValueError, match="can never be approved"):
        build_overlap_disposition(
            cross_split_parent,
            mutation_parent_artifact.artifact_id,
            reviewed_registry,
            decision=OverlapDecision.APPROVED,
            rationale="Cross-split lineage overlap cannot be approved.",
            reviewer_id="reviewer-lineage-002",
            reviewed_at=review_time,
        )


def test_shared_exclusion_artifacts_bind_many_cases_canonically() -> None:
    from dynamislm.benchmark.contamination import validate_exclusion_completeness
    from dynamislm.benchmark.fixtures import build_fixture_exclusion_registry
    from dynamislm.benchmark.hashing import build_manifest_bundle, build_split_manifests
    from dynamislm.benchmark.split import SplitAllocationResult

    source_cases = build_synthetic_reference_fixture_cases()
    split_by_case = {
        source_cases[0].case_id: SplitName.PUBLIC_DEVELOPMENT,
        source_cases[1].case_id: SplitName.PUBLIC_DEVELOPMENT,
        source_cases[2].case_id: SplitName.PUBLIC_DEVELOPMENT,
        source_cases[3].case_id: SplitName.FROZEN_VALIDATION,
        source_cases[4].case_id: SplitName.HIDDEN_FINAL,
        source_cases[5].case_id: SplitName.PUBLIC_DEVELOPMENT,
    }
    cases = []
    for case in source_cases:
        contamination = case.contamination
        if case.case_id in {source_cases[0].case_id, source_cases[5].case_id}:
            contamination = replace(
                contamination,
                source_family_id="fixture-shared-document-family",
                document_ids=("fixture-shared-document",),
            )
        cases.append(
            bind_case_payload(
                replace(
                    case,
                    contamination=contamination,
                    split=replace(
                        case.split,
                        split_name=split_by_case[case.case_id],
                        split_manifest_version=None,
                        split_manifest_hash=None,
                        membership_digest=None,
                    ),
                    case_payload_hash="sha256:" + "0" * 64,
                )
            )
        )
    bound_cases, _ = build_split_manifests(tuple(cases), target_counts(6))
    allocation = SplitAllocationResult(
        cases=bound_cases,
        target_counts=target_counts(6),
        balance_cost=0,
        hash_preference_cost=0,
        cluster_assignments=(),
    )
    registry = build_fixture_exclusion_registry(allocation)
    bundle = build_manifest_bundle(
        bound_cases,
        registry.entries,
        build_res71_runtime_binding(),
    )

    shared = next(
        entry
        for entry in bundle.exclusion_manifest.entries
        if entry.artifact_id == "document:fixture-shared-document"
    )
    assert shared.benchmark_case_ids == tuple(
        sorted((source_cases[0].case_id, source_cases[5].case_id))
    )
    assert shared.benchmark_case_hashes == tuple(
        next(case.case_payload_hash for case in bound_cases if case.case_id == case_id)
        for case_id in shared.benchmark_case_ids
    )
    assert shared.split_names == (SplitName.PUBLIC_DEVELOPMENT,)
    assert len(shared.membership_digests) == 2
    validate_exclusion_completeness(bound_cases, bundle.exclusion_manifest.entries)

    source_artifact_entry = next(
        entry
        for entry in bundle.exclusion_manifest.entries
        if entry.artifact_id == "source:fixture-source-artifact-pdf-v1"
    )
    source_bound_case = next(
        case
        for case in bundle.cases
        if case.provenance.origin_class is CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION
    )
    assert source_artifact_entry.source_artifact_id == "fixture-source-artifact-pdf-v1"
    assert source_artifact_entry.document_id == "doi:10.0000/pse-v1-fixture-source"
    assert (
        source_artifact_entry.source_artifact_digest
        == (source_bound_case.provenance.source_content_digests[0])
    )
    assert source_artifact_entry.document_content_digest == (
        source_bound_case.input.evidence_excerpts[0].document_identity.content_digest
    )
    source_document_entry = next(
        entry
        for entry in bundle.exclusion_manifest.entries
        if entry.artifact_id == "document:doi:10.0000/pse-v1-fixture-source"
    )
    assert source_document_entry.document_id == "doi:10.0000/pse-v1-fixture-source"
    assert source_document_entry.source_artifact_id is None

    incomplete = tuple(
        replace(
            entry,
            benchmark_case_ids=entry.benchmark_case_ids[:1],
            benchmark_case_hashes=entry.benchmark_case_hashes[:1],
            membership_digests=entry.membership_digests[:1],
        )
        if entry.artifact_id == shared.artifact_id
        else entry
        for entry in bundle.exclusion_manifest.entries
    )
    with pytest.raises(ValueError, match="incomplete case associations"):
        validate_exclusion_completeness(bound_cases, incomplete)
    with pytest.raises(ValueError, match="same case more than once"):
        replace(
            shared,
            benchmark_case_ids=(shared.benchmark_case_ids[0],) * 2,
            benchmark_case_hashes=(shared.benchmark_case_hashes[0],) * 2,
        )


def test_manifest_bundle_rejects_stale_bindings_and_hidden_training_access() -> None:
    bundle = build_fixture_manifest_bundle()
    validate_manifest_bundle(bundle)
    stale = replace(
        bundle,
        benchmark_manifest=replace(
            bundle.benchmark_manifest,
            authority_manifest_hash="sha256:" + "0" * 64,
        ),
    )
    with pytest.raises(ValueError):
        validate_manifest_bundle(stale)

    hidden_case = next(
        case for case in bundle.cases if case.split.split_name is SplitName.HIDDEN_FINAL
    )
    store = HiddenStoreDescriptor(
        store_id="fixture-hidden-store",
        store_version="1.0.0",
        benchmark_manifest_hash=bundle.benchmark_manifest.benchmark_manifest_hash,
        hidden_case_ids=(hidden_case.case_id,),
        payloads_available=True,
        answers_available=True,
        storage_boundary="EXTERNAL_PRIVATE",
        credential_namespace="pse-v1-evaluation-service-test",
        hidden_case_hashes=((hidden_case.case_id, hidden_case.case_payload_hash),),
    )
    with pytest.raises(ValueError, match="EXTERNAL_PRIVATE"):
        replace(store, storage_boundary="PUBLIC_REPOSITORY")
    request = HiddenAccessRequest(Principal.TRAINING, hidden_case.case_id, "PAYLOAD", "training")
    access_evidence = build_hidden_access_evidence(
        store_id=store.store_id,
        store_version=store.store_version,
        credential_namespace=store.credential_namespace,
        benchmark_manifest_hash=bundle.benchmark_manifest.benchmark_manifest_hash,
        hidden_case_hashes=store.hidden_case_hashes,
        control_plane_id="synthetic-hidden-control-plane",
        probe_id="synthetic-hidden-access-probe",
        checked_at=datetime_module.datetime.now(datetime_module.UTC),
        grants=_protected_grants(),
    )
    blocked = preflight_hidden_access(
        request,
        case=hidden_case,
        benchmark_manifest=bundle.benchmark_manifest,
        store=store,
        access_evidence=access_evidence,
    )
    assert blocked.status is PreflightStatus.BLOCKED
    allowed = preflight_hidden_access(
        replace(request, principal=Principal.EVALUATION_SERVICE),
        case=hidden_case,
        benchmark_manifest=bundle.benchmark_manifest,
        store=store,
        access_evidence=access_evidence,
    )
    assert allowed.status is PreflightStatus.PASS

    validation_case = next(
        case for case in bundle.cases if case.split.split_name is SplitName.FROZEN_VALIDATION
    )
    validation_store = ProtectedEvaluationStoreDescriptor(
        store_id="fixture-validation-store",
        store_version="1.0.0",
        protected_split=SplitName.FROZEN_VALIDATION,
        benchmark_manifest_hash=bundle.benchmark_manifest.benchmark_manifest_hash,
        case_ids=(validation_case.case_id,),
        case_hashes=((validation_case.case_id, validation_case.case_payload_hash),),
        payloads_available=True,
        answers_available=True,
        storage_boundary="EXTERNAL_PRIVATE",
        credential_namespace="pse-v1-validation-test",
    )
    validation_evidence = build_protected_access_evidence(
        protected_split=SplitName.FROZEN_VALIDATION,
        store_id=validation_store.store_id,
        store_version=validation_store.store_version,
        credential_namespace=validation_store.credential_namespace,
        benchmark_manifest_hash=bundle.benchmark_manifest.benchmark_manifest_hash,
        case_hashes=validation_store.case_hashes,
        control_plane_id="synthetic-validation-control-plane",
        probe_id="synthetic-validation-access-probe",
        checked_at=datetime_module.datetime.now(datetime_module.UTC),
        grants=_protected_grants(),
    )
    assert (
        preflight_protected_store_access(
            ProtectedStoreAccessRequest(
                Principal.EVALUATION_SERVICE, validation_case.case_id, "PAYLOAD", "evaluation"
            ),
            case=validation_case,
            benchmark_manifest=bundle.benchmark_manifest,
            store=validation_store,
            access_evidence=validation_evidence,
        ).status
        is PreflightStatus.PASS
    )
    assert (
        preflight_protected_store_access(
            ProtectedStoreAccessRequest(
                Principal.MODEL_DEVELOPMENT, validation_case.case_id, "ANSWER", "model-dev"
            ),
            case=validation_case,
            benchmark_manifest=bundle.benchmark_manifest,
            store=validation_store,
            access_evidence=validation_evidence,
        ).status
        is PreflightStatus.BLOCKED
    )
    assert (
        preflight_public_development_distribution(
            next(
                case
                for case in bundle.cases
                if case.split.split_name is SplitName.PUBLIC_DEVELOPMENT
            ),
            "PAYLOAD",
        ).status
        is PreflightStatus.PASS
    )

    assert (
        preflight_training_exclusion(
            bundle.exclusion_manifest,
            expected_manifest_hash=bundle.exclusion_manifest.manifest_digest,
        ).status
        is PreflightStatus.PASS
    )
    assert (
        preflight_training_exclusion(None, expected_manifest_hash=None).status
        is PreflightStatus.BLOCKED
    )


@pytest.mark.parametrize(
    "principal", (Principal.TRAINING, Principal.DATA_PIPELINE, Principal.MODEL_DEVELOPMENT)
)
def test_protected_acl_rejects_direct_credential_for_non_evaluation_principals(
    principal: Principal,
) -> None:
    bundle = build_fixture_manifest_bundle()
    validation_case = next(
        case for case in bundle.cases if case.split.split_name is SplitName.FROZEN_VALIDATION
    )
    store = ProtectedEvaluationStoreDescriptor(
        store_id="fixture-validation-acl-store",
        store_version="1.0.0",
        protected_split=SplitName.FROZEN_VALIDATION,
        benchmark_manifest_hash=bundle.benchmark_manifest.benchmark_manifest_hash,
        case_ids=(validation_case.case_id,),
        case_hashes=((validation_case.case_id, validation_case.case_payload_hash),),
        payloads_available=True,
        answers_available=True,
        storage_boundary="EXTERNAL_PRIVATE",
        credential_namespace="fixture-validation-acl-namespace",
    )
    with pytest.raises(ValueError, match="only EVALUATION_SERVICE"):
        build_protected_access_evidence(
            protected_split=SplitName.FROZEN_VALIDATION,
            store_id=store.store_id,
            store_version=store.store_version,
            credential_namespace=store.credential_namespace,
            benchmark_manifest_hash=bundle.benchmark_manifest.benchmark_manifest_hash,
            case_hashes=store.case_hashes,
            control_plane_id="synthetic-acl-test-control-plane",
            probe_id=f"synthetic-{principal.value.casefold()}-acl-probe",
            checked_at=datetime_module.datetime.now(datetime_module.UTC),
            grants=_protected_grants(credential_principal=principal, read_principal=principal),
        )


def test_final_v1_freeze_rejects_infrastructure_fixture_bundle() -> None:
    bundle = build_fixture_manifest_bundle()
    from dynamislm.benchmark.split import SplitAllocationResult

    registry = build_fixture_exclusion_registry(
        SplitAllocationResult(
            cases=bundle.cases,
            target_counts=target_counts(len(bundle.cases)),
            balance_cost=0,
            hash_preference_cost=0,
            cluster_assignments=(),
        )
    )
    audit_ids = tuple(
        sorted(
            entry.artifact_id
            for entry in bundle.exclusion_manifest.entries
            if entry.benchmark_case_ids
        )
    )
    gate = ContaminationGateEvidence(
        benchmark_manifest_hash=bundle.benchmark_manifest.benchmark_manifest_hash,
        exclusion_manifest_hash=bundle.exclusion_manifest.manifest_digest,
        audits=tuple(
            ContaminationAudit(
                "PASS", artifact_id, (), (), (), "NOT_APPLICABLE", "in-memory gate fixture"
            )
            for artifact_id in audit_ids
        ),
    )
    protected_stores = {
        split: ProtectedEvaluationStoreDescriptor(
            store_id=f"fixture-{split.value.casefold()}-store",
            store_version="1.0.0",
            protected_split=split,
            benchmark_manifest_hash=bundle.benchmark_manifest.benchmark_manifest_hash,
            case_ids=tuple(
                sorted(
                    (case.case_id for case in bundle.cases if case.split.split_name is split),
                    key=lambda item: item.encode("utf-8"),
                )
            ),
            payloads_available=True,
            answers_available=True,
            storage_boundary="EXTERNAL_PRIVATE",
            credential_namespace=f"fixture-{split.value.casefold()}-namespace",
            case_hashes=tuple(
                sorted(
                    (
                        (case.case_id, case.case_payload_hash)
                        for case in bundle.cases
                        if case.split.split_name is split
                    ),
                    key=lambda item: item[0].encode("utf-8"),
                )
            ),
        )
        for split in (SplitName.FROZEN_VALIDATION, SplitName.HIDDEN_FINAL)
    }

    with pytest.raises(ValueError, match="fixture-only cases"):
        validate_final_v1_freeze(
            bundle,
            exclusion_registry=registry,
            contamination_gate=gate,
            protected_stores=protected_stores,
            protected_access_probe=None,
            repository_root=Path(__file__).resolve().parents[1],
        )


def test_final_v1_freeze_positive_non_v1_in_memory_qualification() -> None:
    from dynamislm.benchmark.contracts import BenchmarkManifestV1
    from dynamislm.benchmark.hashing import build_split_manifests

    qualification_cases = _build_full_coverage_qualification_cases()
    allocation = allocate_splits(qualification_cases, require_full_coverage=True)
    assert allocation.target_counts == target_counts(434)
    assert tuple(allocation.target_counts[split] for split in SplitName) == (260, 87, 87)
    assert validate_case_coverage(allocation.cases, require_all_splits=True).status == "PASS"

    bound_cases, _ = build_split_manifests(allocation.cases, allocation.target_counts)
    bound_allocation = replace(allocation, cases=bound_cases)
    base_registry = build_fixture_exclusion_registry(bound_allocation)
    cases_by_split: dict[SplitName, list[str]] = {split: [] for split in SplitName}
    for case in bound_cases:
        if case.split.split_name is not None:
            cases_by_split[case.split.split_name].append(case.case_id)
    reviewed_case_ids = tuple(
        sorted(
            cases_by_split[SplitName.PUBLIC_DEVELOPMENT][:2],
            key=lambda item: item.encode("utf-8"),
        )
    )
    overlap_artifact_ids = tuple(f"case:{case_id}" for case_id in reviewed_case_ids)
    overlap_text = "synthetic same-split exact overlap qualification"
    registry_artifacts = tuple(
        replace(
            artifact,
            text=(
                overlap_text
                if artifact.artifact_id in overlap_artifact_ids
                else "".join(chr(0xE000 + index + offset) for offset in range(5))
            ),
        )
        for index, artifact in enumerate(base_registry.artifacts)
    )
    registry = ExclusionRegistry.from_artifacts(registry_artifacts)
    bundle = build_manifest_bundle(
        bound_cases,
        registry.entries,
        build_res71_runtime_binding(),
    )

    review_time = datetime_module.datetime.now(datetime_module.UTC)
    reviewed_artifacts = tuple(
        next(artifact for artifact in registry.artifacts if artifact.artifact_id == artifact_id)
        for artifact_id in overlap_artifact_ids
    )
    left_overlap = build_overlap_disposition(
        reviewed_artifacts[0],
        reviewed_artifacts[1].artifact_id,
        registry,
        decision=OverlapDecision.APPROVED,
        rationale="Reviewed same-split exact overlap is synthetic qualification evidence.",
        reviewer_id="qualification-contamination-reviewer",
        reviewed_at=review_time,
    )
    right_overlap = build_overlap_disposition(
        reviewed_artifacts[1],
        reviewed_artifacts[0].artifact_id,
        registry,
        decision=OverlapDecision.APPROVED,
        rationale="Reviewed same-split exact overlap is synthetic qualification evidence.",
        reviewer_id="qualification-contamination-reviewer",
        reviewed_at=review_time,
    )
    dispositions = (left_overlap, right_overlap)
    unresolved_gate = build_contamination_gate_evidence(bundle, registry)
    assert not unresolved_gate.resolved
    gate = build_contamination_gate_evidence(
        bundle,
        registry,
        dispositions=dispositions,
    )
    assert gate.resolved
    assert len(gate.dispositions) == 2

    protected_splits = (SplitName.FROZEN_VALIDATION, SplitName.HIDDEN_FINAL)
    protected_cases_by_split = {
        split: tuple(
            sorted(
                (case for case in bundle.cases if case.split.split_name is split),
                key=lambda case: case.case_id.encode("utf-8"),
            )
        )
        for split in protected_splits
    }
    protected_stores = {
        split: ProtectedEvaluationStoreDescriptor(
            store_id=f"qualification-private-{split.value.casefold()}-store",
            store_version="1.0.0",
            protected_split=split,
            benchmark_manifest_hash=bundle.benchmark_manifest.benchmark_manifest_hash,
            case_ids=tuple(case.case_id for case in protected_cases_by_split[split]),
            case_hashes=tuple(
                (case.case_id, case.case_payload_hash) for case in protected_cases_by_split[split]
            ),
            payloads_available=True,
            answers_available=True,
            storage_boundary="EXTERNAL_PRIVATE",
            credential_namespace=f"qualification-{split.value.casefold()}-namespace",
        )
        for split in protected_splits
    }
    hidden_cases = protected_cases_by_split[SplitName.HIDDEN_FINAL]
    validation_store = protected_stores[SplitName.FROZEN_VALIDATION]
    hidden_store = protected_stores[SplitName.HIDDEN_FINAL]

    class InMemoryAccessProbe:
        def __init__(self) -> None:
            self.calls = 0
            self.evidence_by_split: dict[SplitName, ProtectedStoreAccessEvidenceV1] = {}

        def probe_access(
            self,
            *,
            store: ProtectedEvaluationStoreDescriptor,
            benchmark_manifest: BenchmarkManifestV1,
            protected_cases: tuple[BenchmarkCaseV1, ...],
        ) -> ProtectedStoreAccessEvidenceV1:
            self.calls += 1
            case_hashes = tuple(
                sorted(
                    ((case.case_id, case.case_payload_hash) for case in protected_cases),
                    key=lambda item: item[0].encode("utf-8"),
                )
            )
            evidence = build_protected_access_evidence(
                protected_split=store.protected_split,
                store_id=store.store_id,
                store_version=store.store_version,
                credential_namespace=store.credential_namespace,
                benchmark_manifest_hash=benchmark_manifest.benchmark_manifest_hash,
                case_hashes=case_hashes,
                control_plane_id="synthetic-in-memory-control-plane",
                probe_id=f"qualification-live-{store.protected_split.value.casefold()}-probe",
                checked_at=review_time,
                grants=_protected_grants(),
            )
            self.evidence_by_split[store.protected_split] = evidence
            return evidence

    with pytest.raises(ValueError, match="unresolved or stale contamination gate"):
        validate_final_v1_freeze(
            bundle,
            exclusion_registry=registry,
            contamination_gate=unresolved_gate,
            protected_stores=protected_stores,
            protected_access_probe=None,
            repository_root=Path(__file__).resolve().parents[1],
        )
    with pytest.raises(ValueError, match="requires live protected-store access probes"):
        validate_final_v1_freeze(
            bundle,
            exclusion_registry=registry,
            contamination_gate=gate,
            protected_stores=protected_stores,
            protected_access_probe=None,
            repository_root=Path(__file__).resolve().parents[1],
        )

    access_probe = InMemoryAccessProbe()
    result = validate_final_v1_freeze(
        bundle,
        exclusion_registry=registry,
        contamination_gate=gate,
        protected_stores=protected_stores,
        protected_access_probe=access_probe,
        repository_root=Path(__file__).resolve().parents[1],
    )
    assert result.status == "PASS"
    assert result.split_counts == tuple(zip(SplitName, (260, 87, 87), strict=True))
    assert result.case_count == 434
    assert result.contamination_dispositions == gate.dispositions
    assert result.contamination_disposition_digest == gate.disposition_manifest_digest
    assert result.protected_access_evidence == tuple(
        (split, access_probe.evidence_by_split[split]) for split in protected_splits
    )
    assert result.public_repository_guard.status == "PASS"
    assert result.public_repository_guard.protected_case_hashes == tuple(
        sorted(
            (
                (case.case_id, case.case_payload_hash)
                for split in protected_splits
                for case in protected_cases_by_split[split]
            ),
            key=lambda item: item[0].encode("utf-8"),
        )
    )
    assert access_probe.calls == 2
    assert set(access_probe.evidence_by_split) == set(protected_splits)
    for split in protected_splits:
        access_evidence = access_probe.evidence_by_split[split]
        assert access_evidence is not None
        training_payload_grant = next(
            grant
            for grant in access_evidence.grants
            if Principal(grant.principal) is Principal.TRAINING and grant.artifact_kind == "PAYLOAD"
        )
        forged_grants = tuple(
            replace(grant, credential_present=True, read_allowed=True)
            if grant is training_payload_grant
            else grant
            for grant in access_evidence.grants
        )
        store = protected_stores[split]
        with pytest.raises(ValueError, match="only EVALUATION_SERVICE"):
            build_protected_access_evidence(
                protected_split=split,
                store_id=store.store_id,
                store_version=store.store_version,
                credential_namespace=store.credential_namespace,
                benchmark_manifest_hash=bundle.benchmark_manifest.benchmark_manifest_hash,
                case_hashes=store.case_hashes,
                control_plane_id="synthetic-in-memory-control-plane",
                probe_id=f"qualification-forged-{split.value.casefold()}-probe",
                checked_at=review_time,
                grants=forged_grants,
            )
        with pytest.raises(ValueError, match="stale or from the future"):
            validate_protected_access_evidence(
                access_evidence,
                store=store,
                benchmark_manifest=bundle.benchmark_manifest,
                protected_cases=protected_cases_by_split[split],
                now=review_time + datetime_module.timedelta(seconds=301),
            )

    assert all(
        preflight_public_development_distribution(case, artifact_kind).status
        is PreflightStatus.PASS
        for case in bundle.cases
        if case.split.split_name is SplitName.PUBLIC_DEVELOPMENT
        for artifact_kind in ("PAYLOAD", "ANSWER")
    )
    public_commitments = public_protected_case_commitments(bundle.cases, bundle.benchmark_manifest)
    assert len(public_commitments) == 174
    assert all(
        commitment.protected_split in protected_splits
        and commitment.case_payload_hash.startswith("sha256:")
        and commitment.payload_hash.startswith("sha256:")
        and commitment.answer_hash.startswith("sha256:")
        and commitment.benchmark_manifest_hash == bundle.benchmark_manifest.benchmark_manifest_hash
        for commitment in public_commitments
    )
    assert (
        preflight_training_exclusion(
            bundle.exclusion_manifest,
            expected_manifest_hash=bundle.exclusion_manifest.manifest_digest,
            cases=bundle.cases,
            benchmark_manifest=bundle.benchmark_manifest,
            private_audit_index=registry,
            private_text_material_required=True,
        ).status
        is PreflightStatus.PASS
    )
    validate_protected_store_namespace_isolation(protected_stores)
    assert (
        validation_store.credential_namespace.casefold()
        != hidden_store.credential_namespace.casefold()
    )
    reused_namespace_stores = {
        **protected_stores,
        SplitName.HIDDEN_FINAL: replace(
            hidden_store,
            credential_namespace=validation_store.credential_namespace.upper(),
        ),
    }
    with pytest.raises(ValueError, match="namespaces must be distinct"):
        validate_protected_store_namespace_isolation(reused_namespace_stores)

    hidden_example = hidden_cases[0]
    hidden_store = protected_stores[SplitName.HIDDEN_FINAL]
    stale_hashes = (
        (hidden_example.case_id, "sha256:" + "0" * 64),
        *hidden_store.case_hashes[1:],
    )
    stale_store = replace(hidden_store, case_hashes=stale_hashes)
    with pytest.raises(ValueError, match="bound to different cases"):
        validate_protected_access_evidence(
            access_probe.evidence_by_split[SplitName.HIDDEN_FINAL],
            store=stale_store,
            benchmark_manifest=bundle.benchmark_manifest,
            protected_cases=hidden_cases,
        )


def _temporary_git_repository(root: Path) -> Path:
    root.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "PSE test"], check=True)
    subprocess.run(
        ["git", "-C", str(root), "config", "user.email", "pse-test@example.invalid"], check=True
    )
    (root / "README.md").write_text("Synthetic protected-store leak test.\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-qm", "fixture"], check=True)
    return root


@pytest.mark.parametrize(
    ("split", "artifact_kind"),
    [
        (SplitName.FROZEN_VALIDATION, "prompt"),
        (SplitName.FROZEN_VALIDATION, "answer"),
        (SplitName.HIDDEN_FINAL, "prompt"),
        (SplitName.HIDDEN_FINAL, "answer"),
    ],
)
def test_public_repository_leak_guard_rejects_protected_prompt_or_answer_commit(
    tmp_path: Path, split: SplitName, artifact_kind: str
) -> None:
    source_case = build_synthetic_reference_fixture_cases()[0]
    case = replace(
        source_case,
        split=replace(
            source_case.split,
            split_name=split,
            split_manifest_version=None,
            split_manifest_hash=None,
            membership_digest=None,
        ),
    )
    repository = _temporary_git_repository(tmp_path / f"{split.value.lower()}-{artifact_kind}")
    artifact = repository / "materialized" / f"{case.case_id}-{artifact_kind}.json"
    artifact.parent.mkdir()
    content = case.question if artifact_kind == "prompt" else canonical_json(case.expected_answer)
    artifact.write_text(content, encoding="utf-8")
    subprocess.run(["git", "-C", str(repository), "add", str(artifact)], check=True)
    subprocess.run(
        ["git", "-C", str(repository), "commit", "-qm", "protected artifact"], check=True
    )

    with pytest.raises(ValueError, match="protected"):
        validate_protected_repository_boundary((case,), repository_root=repository)


def test_contamination_gate_rejects_pass_status_with_unresolved_findings() -> None:
    with pytest.raises(ValueError, match="PASS contamination audit lacks resolved findings"):
        ContaminationAudit(
            "PASS",
            "case:case-1",
            ("prompt:other-case",),
            (),
            (),
            "NOT_APPLICABLE",
            "inconsistent pass receipt",
        )
    gate = ContaminationGateEvidence(
        benchmark_manifest_hash="sha256:" + "1" * 64,
        exclusion_manifest_hash="sha256:" + "2" * 64,
        audits=(
            ContaminationAudit(
                "BLOCKED",
                "case:case-1",
                ("prompt:other-case",),
                (),
                (),
                "NOT_APPLICABLE",
                "inconsistent pass receipt",
            ),
        ),
    )
    assert not gate.resolved


def test_exclusion_preflight_rejects_incomplete_artifact_inventory() -> None:
    bundle = build_fixture_manifest_bundle()
    incomplete = replace(
        bundle.exclusion_manifest,
        entries=bundle.exclusion_manifest.entries[1:],
    )
    from dynamislm.benchmark.hashing import bind_exclusion_manifest

    incomplete = bind_exclusion_manifest(incomplete)
    result = preflight_training_exclusion(
        incomplete,
        expected_manifest_hash=incomplete.manifest_digest,
    )
    assert result.status is PreflightStatus.BLOCKED


def test_exclusion_preflight_rejects_conflicting_case_hashes_without_private_cases() -> None:
    from dynamislm.benchmark.hashing import bind_exclusion_manifest

    bundle = build_fixture_manifest_bundle()
    case_id = bundle.cases[0].case_id
    entries = tuple(
        replace(
            entry,
            benchmark_case_hashes=("sha256:" + "f" * 64,),
        )
        if entry.artifact_id == f"prompt:{case_id}"
        else entry
        for entry in bundle.exclusion_manifest.entries
    )
    conflicting = bind_exclusion_manifest(
        replace(bundle.exclusion_manifest, entries=entries, manifest_digest="sha256:" + "0" * 64)
    )

    result = preflight_training_exclusion(
        conflicting,
        expected_manifest_hash=conflicting.manifest_digest,
    )
    assert result.status is PreflightStatus.BLOCKED
    assert "conflicting hashes for case" in result.reason


def test_error_reports_fail_closed_for_positive_events_without_denominators() -> None:
    bundle = build_fixture_manifest_bundle()
    engine = next(case for case in bundle.cases if case.capability_id == "C08")
    result = score_case(engine, {"fields": {"value": 999.0}, "unit": "m"})
    with pytest.raises(ValueError, match="no eligible case denominator"):
        build_error_event_report((result,), cases=())


def test_calibration_profile_is_explicitly_not_scored_until_runner_support() -> None:
    engine = next(
        case
        for case in build_synthetic_reference_fixture_cases()
        if case.provenance.origin_class is CaseOrigin.DETERMINISTIC_ENGINE_DERIVED
    )
    calibration = bind_case_payload(
        replace(
            engine,
            expected_answer=replace(
                engine.expected_answer,
                required_field_ids=("probabilities",),
                expected_fields={"probabilities": ("PASS", "FAIL")},
            ),
            scoring_contract=replace(
                engine.scoring_contract,
                profile_id=ScoringProfile.CALIBRATION_V1,
                required_output_fields=("probabilities",),
                critical_fields=("probabilities",),
                error_class_rules=(),
                error_attribution=(),
            ),
            case_payload_hash="sha256:" + "0" * 64,
        )
    )
    calibration_score = score_case(
        calibration,
        {"fields": {"probabilities": {"PASS": 1.0}}},
    )
    assert calibration_score.outcome is TaskOutcome.NOT_SCORED


def test_scorers_apply_exact_unit_zero_tolerance_and_refusal_contract() -> None:
    bundle = build_fixture_manifest_bundle()
    engine = next(case for case in bundle.cases if case.capability_id == "C08")
    assert (
        score_case(engine, {"fields": {"value": 1000.0}, "unit": "m"}).outcome is TaskOutcome.PASS
    )
    assert (
        score_case(engine, {"fields": {"value": 1000.0}, "unit": "km"}).outcome is TaskOutcome.FAIL
    )
    assert score_case(engine, {"fields": {"value": 1000.0}}).outcome is TaskOutcome.FAIL

    refusal = next(case for case in bundle.cases if case.case_id == "fixture-expert-refusal")
    expected = refusal.refusal_expectation
    assert expected.refusal_class is not None
    correct = score_case(
        refusal,
        CandidateAnswer(
            decision="REFUSE",
            fields={},
            refusal={
                "blocked_claim": expected.blocked_claim,
                "refusal_class": expected.refusal_class.value,
                "reason_codes": expected.reason_codes,
                "missing_information": expected.missing_information,
                "safe_description": expected.what_can_still_be_safely_described,
            },
        ),
    )
    assert correct.outcome is TaskOutcome.REFUSAL_CORRECT
    incorrect = score_case(refusal, {"decision": "ANSWER", "fields": {}})
    assert incorrect.outcome is TaskOutcome.REFUSAL_INCORRECT
    assert any(
        event.error_class is ErrorClass.FALSE_SCIENTIFIC_ACCEPTANCE
        for event in incorrect.error_events
    )
