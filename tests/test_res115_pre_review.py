from __future__ import annotations

import datetime as datetime_module
import json
from dataclasses import fields, replace
from pathlib import Path

import pytest

from dynamislm.benchmark import (
    CandidateIsolationMetadata,
    CandidateReviewPacket,
    HumanApprovalRecord,
    HumanReviewDecision,
    ProposedCaseProvenance,
    bind_candidate_review_packet,
    bind_human_approval_record,
    promote_to_benchmark_case,
    validate_candidate_review_packet,
    validate_case,
)
from dynamislm.benchmark.constants import AuthorityKind, CaseOrigin
from dynamislm.benchmark.contracts import (
    BenchmarkCaseV1,
    DocumentIdentity,
    EvidenceExcerpt,
    EvidenceSpanIdentity,
    SourceArtifactIdentity,
)
from dynamislm.benchmark.fixtures import build_synthetic_reference_fixture_cases
from dynamislm.serialization import canonical_json, from_canonical_json

_TIME = datetime_module.datetime(2026, 9, 24, 12, 0, tzinfo=datetime_module.UTC)
_ZERO_SHA = "sha256:" + "0" * 64


def _candidate_from_case(case: BenchmarkCaseV1) -> CandidateReviewPacket:
    provenance = case.provenance
    packet = CandidateReviewPacket(
        benchmark_version=case.benchmark_version,
        schema_version=case.schema_version,
        candidate_id=case.case_id,
        candidate_version=case.case_version,
        capability_id=case.capability_id,
        benchmark_family=case.benchmark_family,
        practitioner_question_class=case.practitioner_question_class,
        question=case.question,
        input=case.input,
        source_evidence_refs=case.source_evidence_refs,
        proposed_expected_answer=case.expected_answer,
        authority=case.authority,
        refusal_contract=case.refusal_expectation,
        claim_contract=case.claim_contract,
        comparability_contract=case.comparability_contract,
        scoring_contract=case.scoring_contract,
        tolerance_contract=case.tolerance_contract,
        proposed_provenance=ProposedCaseProvenance(
            author_id=provenance.review.author_id,
            rubric_digest=provenance.review.rubric_digest,
            review_scope=provenance.review.review_scope,
            origin_class=provenance.origin_class,
            authority_lineage=provenance.authority_lineage,
            population_scope=provenance.population_scope,
            derivation_status=provenance.derivation_status,
            derivation_edges=provenance.derivation_edges,
            source_artifact_ids=provenance.source_artifact_ids,
            source_content_digests=provenance.source_content_digests,
            evidence_span_refs=provenance.evidence_span_refs,
            generator_id=provenance.generator_id,
            generator_version=provenance.generator_version,
            generator_family=provenance.generator_family,
            seed_namespace=provenance.seed_namespace,
            seed_block=provenance.seed_block,
            generator_registry_digest=provenance.generator_registry_digest,
            mutation_lineage_id=provenance.mutation_lineage_id,
            parent_case_hash=provenance.parent_case_hash,
            mutation_operator=provenance.mutation_operator,
            mutation_version=provenance.mutation_version,
            mutation_seed=provenance.mutation_seed,
            changed_fields=provenance.changed_fields,
            parent_origin_class=provenance.parent_origin_class,
            engine_operation_id=provenance.engine_operation_id,
            engine_method_version=provenance.engine_method_version,
            engine_reference_case_id=provenance.engine_reference_case_id,
            engine_reference_digest=provenance.engine_reference_digest,
            engine_registry_digest=provenance.engine_registry_digest,
        ),
        contamination=case.contamination,
        isolation=CandidateIsolationMetadata(
            source_family_id=case.contamination.source_family_id,
            isolation_cluster_id=case.split.isolation_cluster_id,
            allocation_stratum=case.split.allocation_stratum,
        ),
        difficulty=case.difficulty,
        adversarial_tags=("MISSING_METADATA",),
    )
    return bind_candidate_review_packet(packet)


def _approved_record(packet: CandidateReviewPacket, **overrides: object) -> HumanApprovalRecord:
    values: dict[str, object] = {
        "approval_record_id": "linear-review:issue-approval-0001",
        "candidate_id": packet.candidate_id,
        "candidate_version": packet.candidate_version,
        "candidate_payload_hash": packet.candidate_payload_hash,
        "reviewed_packet_digest": packet.proposed_approval_digest,
        "decision": HumanReviewDecision.APPROVED,
        "reviewer_id": "linear-user:3bf53bf5-df9c-4634-bb43-d0079f29ae64",
        "reviewer_expertise": ("performance-science", "scientific-benchmark-review"),
        "approval_timestamp": _TIME,
    }
    values.update(overrides)
    return bind_human_approval_record(HumanApprovalRecord(**values))  # type: ignore[arg-type]


def _semantic_candidate() -> CandidateReviewPacket:
    case = next(
        item
        for item in build_synthetic_reference_fixture_cases()
        if item.provenance.origin_class is CaseOrigin.EXPERT_AUTHORED_SEMANTIC
    )
    return _candidate_from_case(case)


def _registered_source_candidate() -> CandidateReviewPacket:
    source_case = next(
        item
        for item in build_synthetic_reference_fixture_cases()
        if item.provenance.origin_class is CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION
    )
    repo_root = Path(__file__).resolve().parents[1]
    source = json.loads(
        (repo_root / "registries/performance_science_eval/accepted.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[0]
    )
    artifact_record = source["retained_source_artifact"]
    family_record = source["source_family_identity"]
    document_version = source["pmc_article_version_identity"]["pmcid_version_ids"][0]
    document = DocumentIdentity(
        document_id=artifact_record["document_identity_id"],
        version=document_version,
        content_digest=source["document_content_sha256"],
        doi=source["doi"],
    )
    artifact = SourceArtifactIdentity(
        artifact_id=artifact_record["source_artifact_id"],
        document_id=document.document_id,
        document_version=document_version,
        artifact_version=document_version,
        content_digest=artifact_record["compressed_sha256"],
    )
    fixture_excerpt = source_case.input.evidence_excerpts[0]
    span = EvidenceSpanIdentity(
        span_id="proposed-source-span-fixture-001",
        document_id=document.document_id,
        document_version=document_version,
        source_artifact_id=artifact.artifact_id,
        source_artifact_digest=artifact.content_digest,
        locator=fixture_excerpt.locator,
        span_digest=fixture_excerpt.span_identity.span_digest,
    )
    excerpt = EvidenceExcerpt(
        document_identity=document,
        source_artifact_identity=artifact,
        span_identity=span,
        text=fixture_excerpt.text,
        scope=fixture_excerpt.scope,
        applicability=fixture_excerpt.applicability,
    )
    reference = replace(
        source_case.source_evidence_refs[0],
        source_reference_id=document.document_id,
        version=document.version,
        digest=document.content_digest,
        document_identity=document,
    )
    authorities = tuple(
        replace(
            binding,
            source_reference_id=document.document_id,
            version=document.version,
            digest=document.identity_digest,
        )
        if binding.authority_kind == AuthorityKind.SOURCE_DOCUMENT.value
        else replace(
            binding,
            source_reference_id=span.span_id,
            version=span.document_version,
            digest=span.span_digest,
        )
        if binding.authority_kind == AuthorityKind.SOURCE_EVIDENCE_SPAN.value
        else binding
        for binding in source_case.authority
    )
    provenance = replace(
        source_case.provenance,
        authority_lineage=(document.document_id, span.span_id),
        source_artifact_ids=(artifact.artifact_id,),
        source_content_digests=(artifact.content_digest,),
        evidence_span_refs=(span.span_id,),
    )
    contamination = replace(
        source_case.contamination,
        source_artifact_ids=(artifact.artifact_id,),
        document_ids=(document.document_id,),
        source_family_id=family_record["source_family_id"],
        source_content_sha256=artifact.content_digest,
    )
    source_case = replace(
        source_case,
        input=replace(source_case.input, evidence_excerpts=(excerpt,)),
        source_evidence_refs=(reference,),
        authority=authorities,
        provenance=provenance,
        contamination=contamination,
        split=replace(
            source_case.split,
            isolation_cluster_id=family_record["source_family_id"],
        ),
    )
    packet = _candidate_from_case(source_case)
    return bind_candidate_review_packet(
        replace(
            packet,
            isolation=replace(
                packet.isolation,
                source_family_id=family_record["source_family_id"],
                isolation_cluster_id=family_record["source_family_id"],
                source_family_digest=family_record["family_digest"],
            ),
            contamination=replace(
                packet.contamination,
                source_family_id=family_record["source_family_id"],
            ),
        )
    )


def test_candidate_packet_is_immutable_hash_bound_and_distinct_from_final_case() -> None:
    packet = _semantic_candidate()

    validate_candidate_review_packet(packet)
    restored = from_canonical_json(canonical_json(packet), CandidateReviewPacket)
    assert restored == packet
    assert packet.review_status.value == "PENDING_HUMAN_REVIEW"
    assert not isinstance(packet, BenchmarkCaseV1)
    assert not hasattr(packet, "split")
    assert not hasattr(packet, "reviewer_id")
    assert not hasattr(packet, "approval_timestamp")

    with pytest.raises(TypeError, match="case must be BenchmarkCaseV1"):
        validate_case(packet)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        BenchmarkCaseV1(**{item.name: getattr(packet, item.name) for item in fields(packet)})
    with pytest.raises(TypeError):
        replace(packet, split=packet.isolation)  # type: ignore[call-arg]
    with pytest.raises(ValueError, match="final split"):
        replace(
            packet,
            input=replace(
                packet.input,
                structured_context={**packet.input.structured_context, "split": "HIDDEN_FINAL"},
            ),
        )
    with pytest.raises(ValueError, match="reviewer approval"):
        replace(
            packet,
            input=replace(
                packet.input,
                structured_context={**packet.input.structured_context, "reviewer_id": "reviewer"},
            ),
        )
    with pytest.raises(TypeError):
        packet.input.structured_context["mutation"] = True  # type: ignore[index]


def test_fake_approved_candidate_status_is_rejected() -> None:
    packet = _semantic_candidate()

    with pytest.raises(ValueError, match="review_status"):
        replace(packet, review_status="APPROVED")  # type: ignore[arg-type]


def test_promotion_requires_independent_hashed_human_approval() -> None:
    packet = _semantic_candidate()
    approval = _approved_record(packet)

    case = promote_to_benchmark_case(packet, approval)

    assert isinstance(case, BenchmarkCaseV1)
    assert case.provenance.review.reviewer_id == approval.reviewer_id
    assert case.provenance.review.approval_status == "APPROVED"
    assert case.provenance.review.approved_at == _TIME
    assert case.split.split_name is None
    validate_case(case)


def test_promotion_rejects_reviewer_equal_to_author() -> None:
    packet = _semantic_candidate()
    approval = _approved_record(packet, reviewer_id=packet.proposed_provenance.author_id)

    with pytest.raises(ValueError, match="independent"):
        promote_to_benchmark_case(packet, approval)


def test_promotion_rejects_wrong_candidate_hash_and_reviewed_packet_digest() -> None:
    packet = _semantic_candidate()
    wrong_hash = _approved_record(packet, candidate_payload_hash=_ZERO_SHA)
    with pytest.raises(ValueError, match="different candidate hash"):
        promote_to_benchmark_case(packet, wrong_hash)

    wrong_packet = _approved_record(packet, reviewed_packet_digest=_ZERO_SHA)
    with pytest.raises(ValueError, match="exact packet digest"):
        promote_to_benchmark_case(packet, wrong_packet)


def test_promotion_rejects_candidate_mutated_after_review() -> None:
    packet = _semantic_candidate()
    approval = _approved_record(packet)
    mutated = bind_candidate_review_packet(replace(packet, benchmark_family="F01"))

    with pytest.raises(ValueError, match="different candidate hash"):
        promote_to_benchmark_case(mutated, approval)
    with pytest.raises(ValueError, match="candidate payload hash mismatch"):
        validate_candidate_review_packet(replace(packet, benchmark_family="F01"))


def test_human_record_requires_timestamp_identity_expertise_and_approval_decision() -> None:
    packet = _semantic_candidate()
    approval = _approved_record(packet)

    with pytest.raises(ValueError, match="timezone-aware datetime"):
        replace(approval, approval_timestamp=None)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="human reviewer"):
        replace(approval, reviewer_id="unknown")
    with pytest.raises(ValueError, match="reviewer_expertise"):
        replace(approval, reviewer_expertise=())

    rejected = _approved_record(packet, decision=HumanReviewDecision.REJECTED)
    with pytest.raises(ValueError, match="APPROVED"):
        promote_to_benchmark_case(packet, rejected)


def test_forged_res71_binding_and_source_identity_are_rejected() -> None:
    packet = _semantic_candidate()
    rubric_binding = next(
        item
        for item in packet.authority
        if item.authority_kind == AuthorityKind.EXPERT_RUBRIC.value
    )
    forged_authority = tuple(
        replace(item, digest=_ZERO_SHA) if item == rubric_binding else item
        for item in packet.authority
    )
    forged_authority_packet = bind_candidate_review_packet(
        replace(packet, authority=forged_authority)
    )
    with pytest.raises(ValueError, match="exact rubric authority"):
        validate_candidate_review_packet(forged_authority_packet)

    engine_case = next(
        item
        for item in build_synthetic_reference_fixture_cases()
        if item.provenance.origin_class is CaseOrigin.DETERMINISTIC_ENGINE_DERIVED
    )
    engine_packet = _candidate_from_case(engine_case)
    operation_binding = next(
        item
        for item in engine_packet.authority
        if item.authority_kind == AuthorityKind.RES71_OPERATION.value
    )
    forged_engine_packet = bind_candidate_review_packet(
        replace(
            engine_packet,
            authority=tuple(
                replace(item, digest=_ZERO_SHA) if item == operation_binding else item
                for item in engine_packet.authority
            ),
        )
    )
    with pytest.raises(ValueError, match="stale or caller-minted"):
        validate_candidate_review_packet(forged_engine_packet)

    forged_numeric_output = bind_candidate_review_packet(
        replace(
            engine_packet,
            proposed_expected_answer=replace(
                engine_packet.proposed_expected_answer,
                expected_fields={"value": 999.0},
            ),
        )
    )
    with pytest.raises(ValueError, match="exact RES-71 reference output"):
        validate_candidate_review_packet(forged_numeric_output)

    semantic_packet = _semantic_candidate()
    rubric_binding = next(
        item
        for item in semantic_packet.authority
        if item.authority_kind == AuthorityKind.EXPERT_RUBRIC.value
    )
    misattributed_numeric = bind_candidate_review_packet(
        replace(
            engine_packet,
            authority=(*engine_packet.authority, rubric_binding),
            proposed_provenance=replace(
                engine_packet.proposed_provenance,
                origin_class=CaseOrigin.EXPERT_AUTHORED_SEMANTIC,
                authority_lineage=("fixture-numeric-rubric",),
                rubric_digest=semantic_packet.proposed_provenance.rubric_digest,
                review_scope=semantic_packet.proposed_provenance.review_scope,
            ),
        )
    )
    with pytest.raises(ValueError, match="deterministic engine-derived provenance"):
        validate_candidate_review_packet(misattributed_numeric)

    assert engine_packet.tolerance_contract is not None
    forged_tolerance = bind_candidate_review_packet(
        replace(
            engine_packet,
            tolerance_contract=replace(
                engine_packet.tolerance_contract,
                absolute_tolerance=1.0,
            ),
        )
    )
    with pytest.raises(ValueError, match="exact RES-71 reference tolerance"):
        validate_candidate_review_packet(forged_tolerance)

    scoring = replace(
        semantic_packet.scoring_contract,
        error_attribution=(
            *semantic_packet.scoring_contract.error_attribution,
            ("unreachable_field", semantic_packet.scoring_contract.error_class_rules[0]),
        ),
    )
    forged_scoring = bind_candidate_review_packet(
        replace(semantic_packet, scoring_contract=scoring)
    )
    with pytest.raises(ValueError, match="error attribution keys have no reachable scorer path"):
        validate_candidate_review_packet(forged_scoring)

    registered_source = _registered_source_candidate()
    validate_candidate_review_packet(registered_source)

    excerpt = registered_source.input.evidence_excerpts[0]
    fake_document = replace(excerpt.document_identity, content_digest=_ZERO_SHA)
    fake_excerpt = replace(excerpt, document_identity=fake_document)
    fake_reference = replace(
        registered_source.source_evidence_refs[0],
        digest=fake_document.content_digest,
        document_identity=fake_document,
    )
    fake_authority = tuple(
        replace(item, digest=fake_document.identity_digest)
        if item.authority_kind == AuthorityKind.SOURCE_DOCUMENT.value
        else item
        for item in registered_source.authority
    )
    forged_identity = bind_candidate_review_packet(
        replace(
            registered_source,
            input=replace(registered_source.input, evidence_excerpts=(fake_excerpt,)),
            source_evidence_refs=(fake_reference,),
            authority=fake_authority,
        )
    )
    with pytest.raises(ValueError, match="document identity/version/digest"):
        validate_candidate_review_packet(forged_identity)
