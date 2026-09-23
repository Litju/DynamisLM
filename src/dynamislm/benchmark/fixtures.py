"""Small synthetic/reference fixtures for qualifying benchmark infrastructure.

This module intentionally does not generate the complete V1 benchmark.
"""

from __future__ import annotations

import datetime as datetime_module
import hashlib
from dataclasses import replace

from dynamislm.benchmark.authority import (
    bind_res71_operation,
    build_res71_runtime_binding,
)
from dynamislm.benchmark.constants import (
    BENCHMARK_SEMANTIC_VERSION,
    CASE_SCHEMA_VERSION,
    CaseOrigin,
    DifficultyLevel,
    ErrorClass,
    EvidenceKind,
    ExpectedAnswerKind,
    InputModality,
    PractitionerQuestionClass,
    RefusalDecision,
    ScoringProfile,
    SplitName,
)
from dynamislm.benchmark.contamination import (
    ContaminationArtifact,
    ExclusionRegistry,
    exact_shingle_digest,
    fuzzy_fingerprint,
    normalized_text_sha256,
    required_exclusion_artifact_ids,
)
from dynamislm.benchmark.contracts import (
    AuthorityBinding,
    BenchmarkCaseV1,
    CaseProvenance,
    ClaimContract,
    ComparabilityContract,
    ContaminationBinding,
    DeterministicResultView,
    DifficultyBinding,
    DocumentIdentity,
    EvidenceExcerpt,
    EvidenceReference,
    EvidenceSpanIdentity,
    ExpectedStructuredAnswer,
    ExpertReviewMetadata,
    InputContract,
    ManifestBundleV1,
    ProvenanceEdge,
    RefusalExpectation,
    ScoringContract,
    SourceArtifactIdentity,
    SplitBinding,
    ToleranceContract,
)
from dynamislm.benchmark.hashing import bind_case_payload, build_manifest_bundle
from dynamislm.benchmark.split import SplitAllocationResult, allocate_splits
from dynamislm.refusal.models import RefusalClass
from dynamislm.serialization import canonical_hash

_ZERO_DIGEST = "sha256:" + "0" * 64
_FIXTURE_TIME = datetime_module.datetime(2026, 1, 1, tzinfo=datetime_module.UTC)


def _review(label: str) -> ExpertReviewMetadata:
    return ExpertReviewMetadata(
        author_id=f"fixture-author-{label}",
        reviewer_id=f"fixture-reviewer-{label}",
        reviewer_expertise=("performance-science", "benchmark-contracts"),
        approval_status="APPROVED",
        approved_at=_FIXTURE_TIME,
        rubric_digest=canonical_hash({"fixture": label, "version": "1.0.0"}),
        review_scope="synthetic infrastructure fixture only",
    )


def _contamination(case_id: str, question: str, family: str) -> ContaminationBinding:
    return ContaminationBinding(
        source_artifact_ids=(),
        document_ids=(),
        source_family_id=family,
        provider_export_id=None,
        protocol_template_id=f"fixture-template-{case_id}",
        expert_author_batch_id=f"fixture-batch-{case_id}",
        artifact_ids=(f"artifact-{case_id}",),
        source_content_sha256=None,
        normalized_text_sha256=normalized_text_sha256(question),
        exact_shingle_digest=exact_shingle_digest(question),
        fuzzy_fingerprint=fuzzy_fingerprint(question),
        semantic_cluster_id=None,
        generator_namespace=None,
        generator_seed_block=None,
        benchmark_artifact_ids=(
            f"case:{case_id}",
            f"prompt:{case_id}",
            f"answer:{case_id}",
            f"split:{case_id}",
            f"artifact-{case_id}",
        ),
        training_exclusion_ids=(f"exclude-{case_id}",),
    )


def _base_case(
    *,
    case_id: str,
    capability_id: str,
    family: str,
    question_class: PractitionerQuestionClass,
    question: str,
    origin: CaseOrigin,
    expected_answer: ExpectedStructuredAnswer,
    refusal: RefusalExpectation,
    scoring: ScoringContract,
    tolerance: ToleranceContract | None,
    authorities: tuple[AuthorityBinding, ...],
    provenance: CaseProvenance,
    source_refs: tuple[EvidenceReference, ...] = (),
    modalities: tuple[InputModality, ...] = (InputModality.TEXT,),
    structured_context: dict[str, object] | None = None,
    deterministic_results: tuple[DeterministicResultView, ...] = (),
    evidence_excerpts: tuple[EvidenceExcerpt, ...] = (),
    tags: tuple[str, ...] = ("FIXTURE",),
) -> BenchmarkCaseV1:
    return BenchmarkCaseV1(
        benchmark_version=BENCHMARK_SEMANTIC_VERSION,
        schema_version=CASE_SCHEMA_VERSION,
        case_id=case_id,
        case_version="1.0.0",
        capability_id=capability_id,
        benchmark_family=family,
        practitioner_question_class=question_class,
        question=question,
        input=InputContract(
            modality=modalities,
            question_text=question,
            structured_context=structured_context or {"fixture": True},
            deterministic_results=deterministic_results,
            evidence_excerpts=evidence_excerpts,
        ),
        source_evidence_refs=source_refs,
        expected_answer=expected_answer,
        authority=authorities,
        refusal_expectation=refusal,
        claim_contract=ClaimContract(
            requested_claim="fixture claim",
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
        scoring_contract=scoring,
        tolerance_contract=tolerance,
        provenance=provenance,
        split=SplitBinding(
            split_name=None,
            split_manifest_version=None,
            split_manifest_hash=None,
            allocation_stratum=f"{capability_id}:{family}",
            isolation_cluster_id=f"cluster-{case_id}",
            membership_digest=None,
        ),
        contamination=_contamination(case_id, question, f"fixture-source-family-{case_id}"),
        difficulty=DifficultyBinding(
            DifficultyLevel.EASY, "small deterministic infrastructure fixture"
        ),
        adversarial_tags=tags,
        case_payload_hash=_ZERO_DIGEST,
    )


def _engine_case() -> BenchmarkCaseV1:
    operation_id = "dynamislm:registered-operation:unit-normalization@1.0.0"
    operation = bind_res71_operation(operation_id, reference_case_id="res71-external-unit-km-to-m")
    reference_digest = operation.reference_case_digest
    assert reference_digest is not None
    runtime = operation.runtime_binding
    authorities = (
        AuthorityBinding(
            "RES71_RUNTIME",
            "res71-reference-interface",
            runtime.interface_version,
            runtime.sealed_reference_digest,
            ("authority", "expected_answer", "input.deterministic_results"),
        ),
        AuthorityBinding(
            "RES71_OPERATION",
            operation.operation_id,
            operation.method_version,
            operation.operation_inventory_digest,
            ("expected_answer", "tolerance_contract", "input.deterministic_results"),
        ),
        AuthorityBinding(
            "RES71_REFERENCE_CASE",
            "res71-external-unit-km-to-m",
            "1.0.0",
            reference_digest,
            ("expected_answer", "input.deterministic_results"),
        ),
    )
    question = "Interpret the registered distance normalization result without recomputing it."
    result_view = DeterministicResultView(
        result_reference_id="fixture-result-res71-unit-normalization",
        operation_id=operation.operation_id,
        method_version=operation.method_version,
        output_unit="m",
        result_or_refusal_digest=reference_digest,
        authority_reference="res71-external-unit-km-to-m",
        values={"value": 1000.0},
    )
    provenance = CaseProvenance(
        origin_class=CaseOrigin.DETERMINISTIC_ENGINE_DERIVED,
        review=_review("engine"),
        authority_lineage=("res71-reference-interface", "res71-external-unit-km-to-m"),
        population_scope="TRAINED_OR_COMPETITIVE_ADULT_TEAM_SPORT_ATHLETES_NON_CLINICAL",
        derivation_status="ENGINE_REFERENCE_BOUND",
        derivation_edges=(
            ProvenanceEdge(
                "res71-external-unit-km-to-m",
                "fixture-result-res71-unit-normalization",
                "REFERENCE_OUTPUT",
            ),
        ),
        generator_family=None,
        engine_operation_id=operation.operation_id,
        engine_method_version=operation.method_version,
        engine_reference_case_id="res71-external-unit-km-to-m",
        engine_reference_digest=reference_digest,
        engine_registry_digest=operation.operation_inventory_digest,
    )
    case = _base_case(
        case_id="fixture-engine-unit-normalization",
        capability_id="C08",
        family="F05",
        question_class=PractitionerQuestionClass.METHOD_AND_ANALYSIS_REASONING,
        question=question,
        origin=CaseOrigin.DETERMINISTIC_ENGINE_DERIVED,
        expected_answer=ExpectedStructuredAnswer(
            kind=ExpectedAnswerKind.NUMERIC_RESULT,
            required_field_ids=("value",),
            expected_fields={"value": 1000.0},
            reference_case_id="res71-external-unit-km-to-m",
            expected_operation_id=operation.operation_id,
        ),
        refusal=RefusalExpectation(RefusalDecision.PROHIBITED, None, None, (), (), ()),
        scoring=ScoringContract(
            ScoringProfile.NUMERIC_TOLERANCE_V1,
            "1.0.0",
            ("value",),
            ("value",),
            ("exact-registered-unit",),
            (ErrorClass.INVENTED_NUMERICAL_SCIENCE, ErrorClass.OVER_REFUSAL),
            "critical_numeric_failure_is_FAIL",
            (
                ("value", ErrorClass.INVENTED_NUMERICAL_SCIENCE),
                ("__over_refusal__", ErrorClass.OVER_REFUSAL),
            ),
        ),
        tolerance=ToleranceContract(("value",), "m", 0.0, 0.0),
        authorities=authorities,
        provenance=provenance,
        modalities=(InputModality.TEXT, InputModality.STRUCTURED_MEASUREMENT_RECORD),
        structured_context={"input_value": 1.0, "input_unit": "kilometer", "output_unit": "meter"},
        deterministic_results=(result_view,),
        tags=("FIXTURE", "ENGINE_REFERENCE"),
    )
    return bind_case_payload(case)


def _semantic_case() -> BenchmarkCaseV1:
    question = (
        "The label 'power' is present but the registered operation is unavailable. "
        "What is safe to claim?"
    )
    rubric_digest = _review("semantic").rubric_digest
    authorities = (
        AuthorityBinding(
            "EXPERT_RUBRIC",
            "fixture-rubric-refusal",
            "1.0.0",
            rubric_digest,
            ("expected_answer", "refusal_expectation", "claim_contract"),
        ),
    )
    provenance = CaseProvenance(
        origin_class=CaseOrigin.EXPERT_AUTHORED_SEMANTIC,
        review=_review("semantic"),
        authority_lineage=("fixture-rubric-refusal", "RES-68"),
        population_scope="TRAINED_OR_COMPETITIVE_ADULT_TEAM_SPORT_ATHLETES_NON_CLINICAL",
        derivation_status="EXPERT_RUBRIC_BOUND",
        derivation_edges=(),
    )
    case = _base_case(
        case_id="fixture-expert-refusal",
        capability_id="C18",
        family="F14",
        question_class=PractitionerQuestionClass.ANSWERABILITY_AND_REFUSAL,
        question=question,
        origin=CaseOrigin.EXPERT_AUTHORED_SEMANTIC,
        expected_answer=ExpectedStructuredAnswer(
            kind=ExpectedAnswerKind.REFUSAL,
            required_field_ids=(
                "refusal_class",
                "reason_codes",
                "blocked_claim",
                "missing_information",
                "safe_description",
            ),
            expected_fields={
                "refusal_class": RefusalClass.COMPUTATION_NOT_REGISTERED.value,
                "reason_codes": ("NO_REGISTERED_OPERATION",),
                "blocked_claim": "compute generic power from an unregistered test label",
                "missing_information": ("registered deterministic operation",),
                "safe_description": (
                    "the observed test label and its source value remain describable",
                ),
            },
            prohibited_claims=("generic power",),
        ),
        refusal=RefusalExpectation(
            RefusalDecision.REQUIRED,
            "compute generic power from an unregistered test label",
            RefusalClass.COMPUTATION_NOT_REGISTERED,
            ("NO_REGISTERED_OPERATION",),
            ("registered deterministic operation",),
            ("the observed test label and its source value remain describable",),
            "OBSERVED_VALUE",
        ),
        scoring=ScoringContract(
            ScoringProfile.REFUSAL_V1,
            "1.0.0",
            (
                "refusal_class",
                "reason_codes",
                "blocked_claim",
                "missing_information",
                "safe_description",
            ),
            ("refusal_class", "blocked_claim"),
            ("registered-refusal-taxonomy",),
            (
                ErrorClass.FALSE_SCIENTIFIC_ACCEPTANCE,
                ErrorClass.UNDER_SPECIFIED_REFUSAL,
                ErrorClass.CAUSAL_OVERCLAIM,
            ),
            "refusal-contract-completeness",
            (
                ("refusal_class", ErrorClass.UNDER_SPECIFIED_REFUSAL),
                ("reason_codes", ErrorClass.UNDER_SPECIFIED_REFUSAL),
                ("blocked_claim", ErrorClass.UNDER_SPECIFIED_REFUSAL),
                ("missing_information", ErrorClass.UNDER_SPECIFIED_REFUSAL),
                ("safe_description", ErrorClass.UNDER_SPECIFIED_REFUSAL),
                ("__decision__", ErrorClass.FALSE_SCIENTIFIC_ACCEPTANCE),
                ("__refusal__", ErrorClass.UNDER_SPECIFIED_REFUSAL),
                ("__prohibited_claim__", ErrorClass.CAUSAL_OVERCLAIM),
            ),
        ),
        tolerance=None,
        authorities=authorities,
        provenance=provenance,
        tags=("FIXTURE", "REFUSAL", "UNREGISTERED_OPERATION"),
    )
    return bind_case_payload(case)


def _source_case() -> BenchmarkCaseV1:
    question = (
        "Extract the exact supported population statement from the supplied evidence excerpt."
    )
    document_id = "doi:10.0000/pse-v1-fixture-source"
    artifact_id = "fixture-source-artifact-pdf-v1"
    document_digest = canonical_hash({"document": document_id, "version": "1.0.0"})
    artifact_digest = (
        "sha256:" + hashlib.sha256(b"synthetic fixture stored source artifact bytes").hexdigest()
    )
    excerpt_text = "Synthetic evidence excerpt for infrastructure qualification."
    excerpt_scope = "fixture-only"
    excerpt_applicability = "fixture-only; not empirical evidence"
    locator = "p.1;span:1-2"
    document = DocumentIdentity(
        document_id=document_id,
        version="1.0.0",
        content_digest=document_digest,
        doi="10.0000/pse-v1-fixture-source",
    )
    source_artifact = SourceArtifactIdentity(
        artifact_id=artifact_id,
        document_id=document_id,
        document_version="1.0.0",
        artifact_version="pdf-v1",
        content_digest=artifact_digest,
    )
    span = EvidenceSpanIdentity(
        span_id="fixture-excerpt-population",
        document_id=document_id,
        document_version="1.0.0",
        source_artifact_id=artifact_id,
        source_artifact_digest=artifact_digest,
        locator=locator,
        span_digest="sha256:" + hashlib.sha256(excerpt_text.encode("utf-8")).hexdigest(),
    )
    excerpt = EvidenceExcerpt(
        document_identity=document,
        source_artifact_identity=source_artifact,
        span_identity=span,
        text=excerpt_text,
        scope=excerpt_scope,
        applicability=excerpt_applicability,
    )
    source_ref = EvidenceReference(
        EvidenceKind.SOURCE,
        document_id,
        "1.0.0",
        document_digest,
        excerpt.locator,
        excerpt.scope,
        excerpt.applicability,
        document_identity=document,
    )
    authorities = (
        AuthorityBinding(
            "SOURCE_EVIDENCE_SPAN",
            excerpt.excerpt_id,
            "1.0.0",
            span.span_digest,
            ("input.evidence_excerpts", "expected_answer"),
        ),
        AuthorityBinding(
            "SOURCE_DOCUMENT",
            document.document_id,
            document.version,
            document.identity_digest,
            ("expected_answer",),
        ),
    )
    provenance = CaseProvenance(
        origin_class=CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION,
        review=_review("source"),
        authority_lineage=(document.document_id, excerpt.excerpt_id),
        population_scope="fixture-only; synthetic source-backed test material",
        derivation_status="SOURCE_SPAN_BOUND",
        derivation_edges=(
            ProvenanceEdge(excerpt.excerpt_id, "fixture-source-extraction", "EXACT_SPAN"),
        ),
        source_artifact_ids=(artifact_id,),
        source_content_digests=(artifact_digest,),
        evidence_span_refs=(excerpt.excerpt_id,),
    )
    case = _base_case(
        case_id="fixture-source-evidence-extraction",
        capability_id="C13",
        family="F11",
        question_class=PractitionerQuestionClass.MEASUREMENT_IDENTITY_AND_PROVENANCE,
        question=question,
        origin=CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION,
        expected_answer=ExpectedStructuredAnswer(
            kind=ExpectedAnswerKind.EVIDENCE_EXTRACTION,
            required_field_ids=("source_span", "scope", "applicability"),
            expected_fields={
                "source_span": excerpt.text,
                "scope": excerpt.scope,
                "applicability": excerpt.applicability,
            },
        ),
        refusal=RefusalExpectation(RefusalDecision.PROHIBITED, None, None, (), (), ()),
        scoring=ScoringContract(
            ScoringProfile.EVIDENCE_SPAN_V1,
            "1.0.0",
            ("source_span", "scope", "applicability"),
            ("source_span",),
            ("registered-source-span",),
            (
                ErrorClass.FALSE_SCIENTIFIC_ACCEPTANCE,
                ErrorClass.WRONG_MEASUREMENT_IDENTITY,
                ErrorClass.OVER_REFUSAL,
            ),
            "evidence-scope-required",
            (
                ("source_span", ErrorClass.WRONG_MEASUREMENT_IDENTITY),
                ("scope", ErrorClass.FALSE_SCIENTIFIC_ACCEPTANCE),
                ("applicability", ErrorClass.FALSE_SCIENTIFIC_ACCEPTANCE),
                ("__over_refusal__", ErrorClass.OVER_REFUSAL),
            ),
        ),
        tolerance=None,
        authorities=authorities,
        provenance=provenance,
        source_refs=(source_ref,),
        modalities=(InputModality.TEXT, InputModality.EVIDENCE_EXCERPT),
        evidence_excerpts=(excerpt,),
        tags=("FIXTURE", "SOURCE_BACKED", "SYNTHETIC_SOURCE_MATERIAL"),
    )
    case = replace(
        case,
        contamination=replace(
            case.contamination,
            source_artifact_ids=(artifact_id,),
            document_ids=(document_id,),
            source_content_sha256=artifact_digest,
        ),
    )
    return bind_case_payload(case)


def _synthetic_case() -> BenchmarkCaseV1:
    question = "Which registered construct does this deterministic synthetic label represent?"
    generator_digest = canonical_hash(
        {"generator": "fixture-construct-generator", "version": "1.0.0"}
    )
    authorities = (
        AuthorityBinding(
            "GENERATOR",
            "fixture-construct-generator",
            "1.0.0",
            generator_digest,
            ("input.structured_context", "expected_answer"),
        ),
    )
    provenance = CaseProvenance(
        origin_class=CaseOrigin.DETERMINISTIC_SYNTHETIC,
        review=_review("synthetic"),
        authority_lineage=("fixture-construct-generator",),
        population_scope="synthetic infrastructure fixture; no empirical population claim",
        derivation_status="DETERMINISTIC_GENERATOR_BOUND",
        derivation_edges=(),
        generator_id="fixture-construct-generator",
        generator_version="1.0.0",
        generator_family="fixture-construct-generator-family",
        seed_namespace="PSE-V1/fixture/fixture-construct-generator",
        seed_block="seed-0001",
        generator_registry_digest=generator_digest,
    )
    case = _base_case(
        case_id="fixture-deterministic-synthetic-construct",
        capability_id="C03",
        family="F03",
        question_class=PractitionerQuestionClass.CONSTRUCT_AND_CLAIM_INTERPRETATION,
        question=question,
        origin=CaseOrigin.DETERMINISTIC_SYNTHETIC,
        expected_answer=ExpectedStructuredAnswer(
            kind=ExpectedAnswerKind.ANSWER,
            required_field_ids=("construct",),
            expected_fields={"construct": "VERTICAL_JUMP"},
        ),
        refusal=RefusalExpectation(RefusalDecision.PROHIBITED, None, None, (), (), ()),
        scoring=ScoringContract(
            ScoringProfile.CLASSIFICATION_V1,
            "1.0.0",
            ("construct",),
            ("construct",),
            ("registered-label-only",),
            (ErrorClass.WRONG_MEASUREMENT_IDENTITY, ErrorClass.OVER_REFUSAL),
            "exact-controlled-label",
            (
                ("construct", ErrorClass.WRONG_MEASUREMENT_IDENTITY),
                ("__over_refusal__", ErrorClass.OVER_REFUSAL),
            ),
        ),
        tolerance=None,
        authorities=authorities,
        provenance=provenance,
        structured_context={
            "display_label": "vertical jump height",
            "registered_construct": "VERTICAL_JUMP",
        },
        tags=("FIXTURE", "DETERMINISTIC_SYNTHETIC"),
    )
    case = replace(
        case,
        contamination=replace(
            case.contamination,
            source_family_id="fixture-source-family-synthetic",
            protocol_template_id="fixture-template-synthetic",
            expert_author_batch_id="fixture-batch-synthetic",
            generator_namespace=provenance.seed_namespace,
            generator_seed_block=provenance.seed_block,
        ),
    )
    return bind_case_payload(case)


def _mutation_case(parent: BenchmarkCaseV1) -> BenchmarkCaseV1:
    question = (
        "MUTATED: The label 'power' is present but the registered operation is unavailable. "
        "What is safe to claim?"
    )
    review = _review("mutation")
    provenance = replace(
        parent.provenance,
        origin_class=CaseOrigin.ADVERSARIAL_MUTATION,
        review=review,
        derivation_status="ADVERSARIAL_MUTATION_REVALIDATED",
        mutation_lineage_id="fixture-mutation-lineage",
        parent_case_hash=parent.case_payload_hash,
        mutation_operator="prepend-marker",
        mutation_version="1.0.0",
        mutation_seed=17,
        changed_fields=("case_id", "input", "question", "provenance", "contamination"),
        parent_origin_class=parent.provenance.origin_class,
        derivation_edges=(
            ProvenanceEdge(
                parent.case_payload_hash, "fixture-adversarial-refusal-mutation", "MUTATION"
            ),
        ),
    )
    mutated = replace(
        parent,
        case_id="fixture-adversarial-refusal-mutation",
        question=question,
        input=replace(parent.input, question_text=question),
        provenance=provenance,
        split=replace(parent.split, isolation_cluster_id="cluster-fixture-mutation"),
        contamination=replace(
            _contamination(
                "fixture-adversarial-refusal-mutation",
                question,
                "fixture-source-family-mutation",
            ),
            source_family_id="fixture-source-family-mutation",
            protocol_template_id="fixture-template-mutation",
            expert_author_batch_id="fixture-batch-mutation",
        ),
        case_payload_hash=_ZERO_DIGEST,
    )
    return bind_case_payload(mutated)


def build_synthetic_reference_fixture_cases() -> tuple[BenchmarkCaseV1, ...]:
    """Return a deliberately small, non-final fixture set."""

    engine = _engine_case()
    semantic = _semantic_case()
    source = _source_case()
    mutation = _mutation_case(semantic)
    synthetic = _synthetic_case()
    # A second semantic case keeps the allocator useful without pretending to cover V1.
    second = replace(
        semantic,
        case_id="fixture-expert-identity",
        question="Identify the registered construct without treating a display alias as identity.",
        input=replace(
            semantic.input,
            question_text=(
                "Identify the registered construct without treating a display alias as identity."
            ),
        ),
        split=replace(semantic.split, isolation_cluster_id="cluster-fixture-expert-identity"),
        contamination=replace(
            _contamination(
                "fixture-expert-identity",
                "Identify the registered construct without treating a display alias as identity.",
                "fixture-source-family-identity",
            ),
            protocol_template_id="fixture-template-identity",
            expert_author_batch_id="fixture-batch-identity",
        ),
        provenance=replace(
            semantic.provenance,
            review=_review("identity"),
            authority_lineage=("fixture-rubric-refusal", "RES-70"),
        ),
        authority=(
            replace(
                semantic.authority[0],
                digest=_review("identity").rubric_digest,
            ),
        ),
        case_payload_hash=_ZERO_DIGEST,
    )
    second = bind_case_payload(second)
    return (engine, semantic, mutation, source, second, synthetic)


def build_fixture_allocation() -> SplitAllocationResult:
    return allocate_splits(build_synthetic_reference_fixture_cases(), require_full_coverage=False)


def build_fixture_exclusion_registry(
    allocation: SplitAllocationResult | None = None,
) -> ExclusionRegistry:
    result = allocation or build_fixture_allocation()
    associated_cases: dict[str, list[BenchmarkCaseV1]] = {}
    for case in result.cases:
        if case.split.split_name is None:
            raise ValueError("fixture exclusion registry requires allocated cases")
        for artifact_id in required_exclusion_artifact_ids(case):
            associated_cases.setdefault(artifact_id, []).append(case)
    artifacts: list[ContaminationArtifact] = []
    for artifact_id, unsorted_cases in associated_cases.items():
        cases = tuple(sorted(unsorted_cases, key=lambda item: item.case_id.encode("utf-8")))
        source_families = {case.contamination.source_family_id for case in cases}
        source_family_id = (
            next(iter(source_families))
            if len(source_families) == 1
            else f"shared-fixture-artifact:{artifact_id}"
        )
        split_names = tuple(
            split for split in SplitName if any(case.split.split_name is split for case in cases)
        )
        case_ids = tuple(case.case_id for case in cases)
        case_hashes = tuple(case.case_payload_hash for case in cases)
        membership_digests = (
            tuple(
                case.split.membership_digest
                for case in cases
                if case.split.membership_digest is not None
            )
            if all(case.split.membership_digest is not None for case in cases)
            else ()
        )
        document_id = (
            artifact_id.removeprefix("document:") if artifact_id.startswith("document:") else None
        )
        source_artifact_id = (
            artifact_id.removeprefix("source:") if artifact_id.startswith("source:") else None
        )
        document_content_digest = None
        source_artifact_digest = None
        identity_excerpts = tuple(
            excerpt
            for case in cases
            for excerpt in case.input.evidence_excerpts
            if excerpt.source_artifact_identity.artifact_id == source_artifact_id
        )
        if source_artifact_id is not None and identity_excerpts:
            excerpt = identity_excerpts[0]
            document_id = excerpt.document_identity.document_id
            document_content_digest = excerpt.document_identity.content_digest
            source_artifact_digest = excerpt.source_artifact_identity.content_digest
            normalized_doi = excerpt.document_identity.doi
        else:
            document_excerpts = tuple(
                excerpt
                for case in cases
                for excerpt in case.input.evidence_excerpts
                if excerpt.document_identity.document_id == document_id
            )
            normalized_doi = (
                document_excerpts[0].document_identity.doi if document_excerpts else None
            )
            document_content_digest = (
                document_excerpts[0].document_identity.content_digest if document_excerpts else None
            )
        artifacts.append(
            ContaminationArtifact(
                artifact_id=artifact_id,
                document_id=document_id,
                document_content_digest=document_content_digest,
                source_artifact_id=source_artifact_id,
                source_artifact_digest=source_artifact_digest,
                text=(
                    f"{artifact_id} "
                    + " ".join(f"{case.case_id} {case.case_payload_hash}" for case in cases)
                    + f" {artifact_id}"
                ),
                source_family_id=source_family_id,
                normalized_doi=normalized_doi,
                split_name=split_names[0],
                benchmark_case_ids=case_ids,
                benchmark_case_hashes=case_hashes,
                membership_digests=membership_digests,
                benchmark_split_names=split_names,
            )
        )
    manifest_ids = (
        "manifest:benchmark",
        "manifest:authority",
        "manifest:scorer",
        "manifest:exclusion",
        *(f"manifest:split:{split.value}" for split in SplitName),
    )
    for artifact_id in manifest_ids:
        manifest_split = next(
            (split for split in SplitName if artifact_id == f"manifest:split:{split.value}"),
            SplitName.PUBLIC_DEVELOPMENT,
        )
        artifacts.append(
            ContaminationArtifact(
                artifact_id=artifact_id,
                document_id=None,
                document_content_digest=None,
                source_artifact_id=None,
                source_artifact_digest=None,
                text=f"{artifact_id}|PSE-V1 fixture manifest artifact",
                source_family_id="fixture-manifest",
                split_name=manifest_split,
                benchmark_split_names=(manifest_split,),
            )
        )
    return ExclusionRegistry.from_artifacts(tuple(artifacts))


def build_fixture_manifest_bundle() -> ManifestBundleV1:
    allocation = build_fixture_allocation()
    from dynamislm.benchmark.hashing import build_split_manifests

    bound_cases, _ = build_split_manifests(allocation.cases, allocation.target_counts)
    bound_allocation = replace(allocation, cases=bound_cases)
    registry = build_fixture_exclusion_registry(bound_allocation)
    return build_manifest_bundle(
        bound_cases,
        registry.entries,
        build_res71_runtime_binding(),
    )


__all__ = [
    "build_fixture_allocation",
    "build_fixture_exclusion_registry",
    "build_fixture_manifest_bundle",
    "build_synthetic_reference_fixture_cases",
]
