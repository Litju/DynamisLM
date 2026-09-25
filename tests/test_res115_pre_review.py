from __future__ import annotations

import datetime as datetime_module
import gzip
import hashlib
import json
from dataclasses import fields, replace
from pathlib import Path

import pytest

from dynamislm.benchmark import (
    CandidateIsolationMetadata,
    CandidateParentBinding,
    CandidateReviewPacket,
    CasePromotionReceipt,
    HumanApprovalRecord,
    HumanReviewDecision,
    ParentPromotionEvidence,
    PhaseASourceArtifactResolver,
    PromotionResult,
    ProposedCaseProvenance,
    bind_candidate_review_packet,
    bind_human_approval_record,
    candidate_payload_hash,
    candidate_scientific_projection,
    promote_to_benchmark_case,
    promote_with_receipt,
    promotion_receipt_digest,
    topological_candidate_promotion_order,
    validate_candidate_review_packet,
    validate_candidate_set,
    validate_case,
    validate_promotion_result,
)
from dynamislm.benchmark.constants import AuthorityKind, CaseOrigin
from dynamislm.benchmark.contracts import (
    AuthorityBinding,
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


def _mutation_candidate(parent: CandidateReviewPacket) -> CandidateReviewPacket:
    from dynamislm.benchmark.contamination import (
        exact_shingle_digest,
        fuzzy_fingerprint,
        normalized_text_sha256,
    )

    child_id = f"{parent.candidate_id}-mutation"
    question = f"MUTATED: {parent.question}"
    lineage_id = "fixture-mutation-lineage-res115"
    parent_binding = CandidateParentBinding(
        parent_candidate_id=parent.candidate_id,
        parent_candidate_version=parent.candidate_version,
        parent_candidate_payload_hash=parent.candidate_payload_hash,
        parent_origin_class=parent.proposed_provenance.origin_class,
        mutation_lineage_id=lineage_id,
    )
    mutation_authority = AuthorityBinding(
        authority_kind=AuthorityKind.MUTATION_PARENT.value,
        source_reference_id=parent.candidate_id,
        version=parent.candidate_version,
        digest=parent.candidate_payload_hash,
        governed_field_ids=("provenance.parent_case_hash",),
    )
    contamination = replace(
        parent.contamination,
        normalized_text_sha256=normalized_text_sha256(question),
        exact_shingle_digest=exact_shingle_digest(question),
        fuzzy_fingerprint=fuzzy_fingerprint(question),
    )
    provenance = replace(
        parent.proposed_provenance,
        origin_class=CaseOrigin.ADVERSARIAL_MUTATION,
        derivation_status="ADVERSARIAL_MUTATION_REVALIDATED",
        mutation_lineage_id=lineage_id,
        parent_case_hash=None,
        mutation_operator="prepend-marker",
        mutation_version="1.0.0",
        mutation_seed=1701,
        changed_fields=("provenance",),
        parent_origin_class=parent.proposed_provenance.origin_class,
        derivation_edges=tuple(
            edge
            for edge in parent.proposed_provenance.derivation_edges
            if edge.relation != "MUTATION"
        ),
    )
    child = replace(
        parent,
        candidate_id=child_id,
        question=question,
        input=replace(parent.input, question_text=question),
        authority=(*parent.authority, mutation_authority),
        proposed_provenance=provenance,
        contamination=contamination,
        parent_candidate_binding=parent_binding,
    )
    child = replace(
        child,
        proposed_provenance=replace(
            child.proposed_provenance,
            changed_fields=tuple(
                sorted(
                    (
                        field_name
                        for field_name, value in candidate_scientific_projection(parent).items()
                        if value != candidate_scientific_projection(child)[field_name]
                    ),
                    key=lambda item: item.encode("utf-8"),
                )
            ),
        ),
    )
    return bind_candidate_review_packet(child)


def _digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def test_phase_a_span_digest_derives_exact_structural_jats_locator() -> None:
    from dynamislm.benchmark.source_artifacts import (
        _extract_jats_text,
        derive_unique_jats_paragraph_locator,
    )

    jats = (
        b"<article><body><sec><title>Methods</title>"
        b"<p>Exact <italic>support</italic> bytes.</p></sec></body></article>"
    )
    span_digest = _digest(b"Exact support bytes.")

    locator = derive_unique_jats_paragraph_locator(jats, span_digest)

    assert locator == "jats-text-v1:/article[1]/body[1]/sec[1]/p[1]"
    assert _extract_jats_text(jats, locator) == "Exact support bytes."


def test_phase_a_span_digest_with_ambiguous_or_missing_jats_match_blocks() -> None:
    from dynamislm.benchmark.source_artifacts import derive_unique_jats_paragraph_locator

    duplicated = (
        b"<article><body><p>Repeated exact span.</p><p>Repeated exact span.</p></body></article>"
    )
    missing = b"<article><body><p>Different span.</p></body></article>"
    digest = _digest(b"Repeated exact span.")

    with pytest.raises(ValueError, match="matches multiple JATS paragraphs"):
        derive_unique_jats_paragraph_locator(duplicated, digest)
    with pytest.raises(ValueError, match="absent from retained JATS paragraphs"):
        derive_unique_jats_paragraph_locator(missing, digest)


def _controlled_source_candidate(
    tmp_path: Path,
    *,
    multi_reference: bool = False,
) -> tuple[CandidateReviewPacket, PhaseASourceArtifactResolver, Path]:
    source_case = next(
        item
        for item in build_synthetic_reference_fixture_cases()
        if item.provenance.origin_class is CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION
    )
    family_id = "PSE-SOURCE-FAMILY:fixture-9000001"
    family_digest = _digest(b"synthetic fixture source-family identity")
    registry_version = "performance-science-eval-source-record@1.2.0"
    store_root = tmp_path / "source-store"
    registry_root = tmp_path / "registry"
    registry_root.mkdir()
    document_inputs = [
        ("PMC9000001", "We enrolled trained adult team-sport athletes."),
    ]
    if multi_reference:
        document_inputs.append(("PMC9000002", "Participants completed supervised field testing."))
    source_rows: list[dict[str, object]] = []
    checksum_rows: list[dict[str, object]] = []
    evidence_records: list[tuple[DocumentIdentity, SourceArtifactIdentity, str, str, str]] = []
    artifact_paths: list[Path] = []
    for index, (pmcid, source_text) in enumerate(document_inputs, start=1):
        jats_bytes = (
            b'<?xml version="1.0" encoding="UTF-8"?>'
            b'<article><body><sec id="population"><title>Population</title><p>'
            + source_text.encode("utf-8")
            + b"</p></sec></body></article>"
        )
        compressed_bytes = gzip.compress(jats_bytes, mtime=0)
        document_version = f"{pmcid}.1"
        document_id = f"PSE-DOCUMENT:{pmcid}"
        artifact_id = f"PSE-JATS-GZIP:{pmcid}"
        doi = f"10.0000/synthetic-res115-source-{index}"
        relative_path = f"sources/accepted/{pmcid}/article.xml.gz"
        metadata_digest = _digest(f"synthetic fixture metadata {pmcid}".encode())
        compressed_digest = _digest(compressed_bytes)
        document_digest = _digest(jats_bytes)
        artifact_path = store_root / pmcid / "article.xml.gz"
        artifact_path.parent.mkdir(parents=True)
        artifact_path.write_bytes(compressed_bytes)
        artifact_paths.append(artifact_path)
        source_rows.append(
            {
                "schema_version": registry_version,
                "disposition": "ACCEPTED",
                "pmcid": pmcid,
                "doi": doi,
                "document_content_sha256": document_digest,
                "source_artifact_sha256": compressed_digest,
                "source_metadata_sha256": metadata_digest,
                "retained_source_artifact": {
                    "document_identity_id": document_id,
                    "source_artifact_id": artifact_id,
                    "relative_path": relative_path,
                    "format": "JATS XML",
                    "compression": "gzip",
                    "compressed_byte_count": len(compressed_bytes),
                    "compressed_sha256": compressed_digest,
                    "uncompressed_jats_byte_count": len(jats_bytes),
                    "uncompressed_jats_sha256": document_digest,
                },
                "pmc_article_version_identity": {"pmcid_version_ids": [document_version]},
                "source_family_identity": {
                    "source_family_id": family_id,
                    "family_digest": family_digest,
                    "family_resolution_status": "MULTI_DOCUMENT_FAMILY"
                    if multi_reference
                    else "SINGLE_DOCUMENT_FAMILY",
                    "future_split_rule": (
                        "Synthetic fixture source family remains one isolation unit."
                    ),
                },
            }
        )
        checksum_rows.append(
            {
                "artifact_role": "RETAINED_JATS_GZIP",
                "pmcid": pmcid,
                "relative_path": relative_path,
                "byte_count": len(compressed_bytes),
                "sha256": compressed_digest,
                "uncompressed_jats_byte_count": len(jats_bytes),
                "uncompressed_jats_sha256": document_digest,
                "metadata_sha256": metadata_digest,
                "identity_binding": {"pmcid": pmcid, "pmcid_version_ids": [document_version]},
            }
        )
        document = DocumentIdentity(
            document_id=document_id,
            version=document_version,
            content_digest=document_digest,
            doi=doi,
        )
        artifact = SourceArtifactIdentity(
            artifact_id=artifact_id,
            document_id=document_id,
            document_version=document_version,
            artifact_version=document_version,
            content_digest=compressed_digest,
        )
        evidence_records.append(
            (
                document,
                artifact,
                source_text,
                document_id,
                f"proposed-source-span-fixture-{index:03d}",
            )
        )
    accepted_registry = registry_root / "accepted.jsonl"
    accepted_registry.write_text(
        "".join(json.dumps(row) + "\n" for row in source_rows), encoding="utf-8"
    )
    checksum_registry = registry_root / "checksums.jsonl"
    checksum_registry.write_text(
        "".join(json.dumps(row) + "\n" for row in checksum_rows), encoding="utf-8"
    )
    schema_path = registry_root / "registry.schema.json"
    schema_path.write_text(json.dumps({"schema_version": registry_version}), encoding="utf-8")
    resolver = PhaseASourceArtifactResolver(
        accepted_registry_path=accepted_registry,
        checksum_registry_path=checksum_registry,
        registry_schema_path=schema_path,
        retained_source_root=store_root,
    )

    fixture_excerpt = source_case.input.evidence_excerpts[0]
    locator = "jats-text-v1:/article[1]/body[1]/sec[1]/p[1]"
    excerpts: list[EvidenceExcerpt] = []
    references = []
    document_authorities = []
    span_authorities = []
    for document, artifact, source_text, _, span_id in evidence_records:
        span = EvidenceSpanIdentity(
            span_id=span_id,
            document_id=document.document_id,
            document_version=document.version,
            source_artifact_id=artifact.artifact_id,
            source_artifact_digest=artifact.content_digest,
            locator=locator,
            span_digest=_digest(source_text.encode("utf-8")),
        )
        excerpts.append(
            EvidenceExcerpt(
                document_identity=document,
                source_artifact_identity=artifact,
                span_identity=span,
                text=source_text,
                scope=fixture_excerpt.scope,
                applicability=fixture_excerpt.applicability,
            )
        )
        references.append(
            replace(
                source_case.source_evidence_refs[0],
                source_reference_id=document.document_id,
                version=document.version,
                digest=document.content_digest,
                locator=locator,
                document_identity=document,
            )
        )
        document_authorities.append(
            AuthorityBinding(
                authority_kind=AuthorityKind.SOURCE_DOCUMENT.value,
                source_reference_id=document.document_id,
                version=document.version,
                digest=document.identity_digest,
                governed_field_ids=("expected_answer",),
            )
        )
        span_authorities.append(
            AuthorityBinding(
                authority_kind=AuthorityKind.SOURCE_EVIDENCE_SPAN.value,
                source_reference_id=span.span_id,
                version=span.document_version,
                digest=span.span_digest,
                governed_field_ids=("input.evidence_excerpts", "expected_answer"),
            )
        )
    excerpts_tuple = tuple(excerpts)
    references_tuple = tuple(references)
    artifacts = tuple(record[1] for record in evidence_records)
    spans = tuple(excerpt.span_identity for excerpt in excerpts_tuple)
    artifact_ids = tuple(
        sorted(
            (item.artifact_id for item in artifacts),
            key=lambda value: value.encode("utf-8"),
        )
    )
    artifact_digests = tuple(
        digest
        for _, digest in sorted(
            ((item.artifact_id, item.content_digest) for item in artifacts),
            key=lambda item: item[0].encode("utf-8"),
        )
    )
    document_ids = tuple(sorted(item.document_identity.document_id for item in excerpts_tuple))
    span_ids = tuple(item.span_id for item in spans)
    authorities = (
        tuple(
            binding
            for binding in source_case.authority
            if binding.authority_kind
            not in {AuthorityKind.SOURCE_DOCUMENT.value, AuthorityKind.SOURCE_EVIDENCE_SPAN.value}
        )
        + tuple(document_authorities)
        + tuple(span_authorities)
    )
    provenance = replace(
        source_case.provenance,
        authority_lineage=(*document_ids, *span_ids),
        source_artifact_ids=artifact_ids,
        source_content_digests=artifact_digests,
        evidence_span_refs=span_ids,
    )
    contamination = replace(
        source_case.contamination,
        source_artifact_ids=artifact_ids,
        document_ids=document_ids,
        source_family_id=family_id,
        source_content_sha256=artifact_digests[0],
    )
    source_case = replace(
        source_case,
        input=replace(source_case.input, evidence_excerpts=excerpts_tuple),
        source_evidence_refs=references_tuple,
        authority=authorities,
        provenance=provenance,
        contamination=contamination,
        split=replace(
            source_case.split,
            isolation_cluster_id=family_id,
        ),
    )
    packet = _candidate_from_case(source_case)
    packet = bind_candidate_review_packet(
        replace(
            packet,
            isolation=replace(
                packet.isolation,
                source_family_id=family_id,
                isolation_cluster_id=family_id,
                source_family_digest=family_digest,
            ),
            contamination=replace(packet.contamination, source_family_id=family_id),
        )
    )
    return packet, resolver, artifact_paths[0]


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

    result = promote_to_benchmark_case(packet, approval)

    assert isinstance(result, PromotionResult)
    case = result.case
    assert isinstance(result.receipt, CasePromotionReceipt)
    assert isinstance(case, BenchmarkCaseV1)
    assert case.provenance.review.reviewer_id == approval.reviewer_id
    assert case.provenance.review.approval_status == "APPROVED"
    assert case.provenance.review.approved_at == _TIME
    assert case.split.split_name is None
    validate_case(case)
    validate_promotion_result(packet, approval, result)


def test_promotion_receipt_is_canonical_and_binds_all_three_artifacts() -> None:
    packet = _semantic_candidate()
    approval = _approved_record(packet)

    result = promote_with_receipt(packet, approval)
    receipt = result.receipt

    assert receipt.candidate_payload_hash == packet.candidate_payload_hash
    assert receipt.reviewed_packet_digest == packet.proposed_approval_digest
    assert receipt.approval_record_id == approval.approval_record_id
    assert receipt.approval_record_digest == approval.approval_record_digest
    assert receipt.final_case_payload_hash == result.case.case_payload_hash
    assert receipt.receipt_digest == promotion_receipt_digest(receipt)
    assert result.case.split.split_name is None
    restored = from_canonical_json(canonical_json(result), PromotionResult)
    assert restored == result


def test_mutating_any_promotion_chain_link_invalidates_receipt() -> None:
    packet = _semantic_candidate()
    approval = _approved_record(packet)
    result = promote_with_receipt(packet, approval)

    changed_candidate_question = "Mutated candidate question."
    mutated_packet = bind_candidate_review_packet(
        replace(
            packet,
            question=changed_candidate_question,
            input=replace(packet.input, question_text=changed_candidate_question),
        )
    )
    with pytest.raises(ValueError):
        validate_promotion_result(mutated_packet, approval, result)

    mutated_approval = bind_human_approval_record(
        replace(approval, reviewer_expertise=("different expertise",))
    )
    with pytest.raises(ValueError, match="promotion receipt|final case payload"):
        validate_promotion_result(packet, mutated_approval, result)

    from dynamislm.benchmark.hashing import bind_case_payload

    changed_question = "Mutated final case question."
    changed_case = bind_case_payload(
        replace(
            result.case,
            question=changed_question,
            input=replace(result.case.input, question_text=changed_question),
        )
    )
    validate_case(changed_case)
    with pytest.raises(ValueError, match="promotion receipt|final case payload"):
        validate_promotion_result(packet, approval, replace(result, case=changed_case))


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


def test_mutation_candidate_binds_exact_parent_candidate_and_orders_parent_first() -> None:
    parent = _semantic_candidate()
    child = _mutation_candidate(parent)

    validate_candidate_review_packet(child)
    validate_candidate_set((child, parent))
    order = topological_candidate_promotion_order((child, parent))

    assert tuple(item.candidate_id for item in order) == (parent.candidate_id, child.candidate_id)
    assert child.parent_candidate_binding is not None
    assert (
        child.parent_candidate_binding.parent_candidate_payload_hash
        == parent.candidate_payload_hash
    )
    assert (
        candidate_payload_hash(
            replace(
                child,
                parent_candidate_binding=replace(
                    child.parent_candidate_binding,
                    mutation_lineage_id="different-lineage",
                ),
            )
        )
        != child.candidate_payload_hash
    )
    assert from_canonical_json(canonical_json(child), CandidateReviewPacket) == child


def test_mutation_candidate_rejects_forged_parent_candidate_hash() -> None:
    parent = _semantic_candidate()
    child = _mutation_candidate(parent)
    assert child.parent_candidate_binding is not None
    forged_hash = "sha256:" + "f" * 64
    mutation_authority = next(
        item
        for item in child.authority
        if item.authority_kind == AuthorityKind.MUTATION_PARENT.value
    )
    forged = bind_candidate_review_packet(
        replace(
            child,
            parent_candidate_binding=replace(
                child.parent_candidate_binding,
                parent_candidate_payload_hash=forged_hash,
            ),
            authority=tuple(
                replace(item, digest=forged_hash) if item == mutation_authority else item
                for item in child.authority
            ),
        )
    )

    with pytest.raises(ValueError, match="ID/version/hash does not match exactly"):
        validate_candidate_set((parent, forged))


def test_mutation_candidate_rejects_missing_parent_candidate() -> None:
    child = _mutation_candidate(_semantic_candidate())

    with pytest.raises(ValueError, match="parent candidate is not present"):
        validate_candidate_set((child,))


def test_mutation_candidate_rejects_self_parent() -> None:
    parent = _semantic_candidate()
    child = _mutation_candidate(parent)
    assert child.parent_candidate_binding is not None
    mutation_authority = next(
        item
        for item in child.authority
        if item.authority_kind == AuthorityKind.MUTATION_PARENT.value
    )
    self_parent = bind_candidate_review_packet(
        replace(
            child,
            parent_candidate_binding=replace(
                child.parent_candidate_binding,
                parent_candidate_id=child.candidate_id,
                parent_candidate_version=child.candidate_version,
            ),
            authority=tuple(
                replace(
                    item,
                    source_reference_id=child.candidate_id,
                    version=child.candidate_version,
                )
                if item == mutation_authority
                else item
                for item in child.authority
            ),
        )
    )

    with pytest.raises(ValueError, match="self-parent"):
        validate_candidate_set((parent, self_parent))


def test_mutation_candidate_cycle_is_rejected_before_hash_resolution() -> None:
    parent = _semantic_candidate()
    first = _mutation_candidate(parent)
    second = replace(_mutation_candidate(parent), candidate_id="other-mutation")
    second = bind_candidate_review_packet(second)

    def point_to(
        child: CandidateReviewPacket, target: CandidateReviewPacket
    ) -> CandidateReviewPacket:
        assert child.parent_candidate_binding is not None
        parent_authority = next(
            item
            for item in child.authority
            if item.authority_kind == AuthorityKind.MUTATION_PARENT.value
        )
        return bind_candidate_review_packet(
            replace(
                child,
                parent_candidate_binding=replace(
                    child.parent_candidate_binding,
                    parent_candidate_id=target.candidate_id,
                    parent_candidate_version=target.candidate_version,
                    parent_candidate_payload_hash=target.candidate_payload_hash,
                    parent_origin_class=CaseOrigin.ADVERSARIAL_MUTATION,
                ),
                authority=tuple(
                    replace(
                        item,
                        source_reference_id=target.candidate_id,
                        version=target.candidate_version,
                        digest=target.candidate_payload_hash,
                    )
                    if item == parent_authority
                    else item
                    for item in child.authority
                ),
                proposed_provenance=replace(
                    child.proposed_provenance,
                    parent_origin_class=CaseOrigin.ADVERSARIAL_MUTATION,
                ),
            )
        )

    first_cycle = point_to(first, second)
    second_cycle = point_to(second, first)
    with pytest.raises(ValueError, match="cycle"):
        validate_candidate_set((first_cycle, second_cycle))


@pytest.mark.parametrize("declared", [("provenance",), None])
def test_mutation_changed_fields_must_match_candidate_scientific_projection(
    declared: tuple[str, ...] | None,
) -> None:
    parent = _semantic_candidate()
    child = _mutation_candidate(parent)
    changed = list(child.proposed_provenance.changed_fields)
    if declared is not None:
        changed = list(declared)
    else:
        changed.append("difficulty")
    invalid = bind_candidate_review_packet(
        replace(
            child,
            proposed_provenance=replace(
                child.proposed_provenance,
                changed_fields=tuple(sorted(set(changed), key=lambda item: item.encode("utf-8"))),
            ),
        )
    )

    with pytest.raises(ValueError, match="changed_fields"):
        validate_candidate_set((parent, invalid))


def test_mutation_candidate_cannot_drop_parent_primary_authority() -> None:
    parent = _semantic_candidate()
    child = _mutation_candidate(parent)
    child_without_primary = bind_candidate_review_packet(
        replace(
            child,
            authority=tuple(
                item
                for item in child.authority
                if item.authority_kind != AuthorityKind.EXPERT_RUBRIC.value
            ),
        )
    )

    with pytest.raises(ValueError):
        validate_candidate_set((parent, child_without_primary))


def test_mutation_candidate_must_preserve_parent_isolation_metadata() -> None:
    parent = _semantic_candidate()
    child = _mutation_candidate(parent)
    isolated_child = bind_candidate_review_packet(
        replace(
            child,
            isolation=replace(child.isolation, isolation_cluster_id="different-cluster"),
        )
    )

    with pytest.raises(ValueError, match="preserve parent isolation metadata"):
        validate_candidate_set((parent, isolated_child))


def test_mutation_candidate_allows_another_allocation_stratum_in_same_cluster() -> None:
    parent = _semantic_candidate()
    child = _mutation_candidate(parent)
    other_stratum = next(
        case.split.allocation_stratum
        for case in build_synthetic_reference_fixture_cases()
        if case.split.allocation_stratum != parent.isolation.allocation_stratum
    )
    cross_stratum_child = bind_candidate_review_packet(
        replace(
            child,
            isolation=replace(child.isolation, allocation_stratum=other_stratum),
        )
    )

    validate_candidate_set((cross_stratum_child, parent))

    assert cross_stratum_child.parent_candidate_binding is not None
    assert cross_stratum_child.proposed_provenance.mutation_lineage_id == (
        cross_stratum_child.parent_candidate_binding.mutation_lineage_id
    )
    assert cross_stratum_child.isolation.isolation_cluster_id == (
        parent.isolation.isolation_cluster_id
    )
    assert cross_stratum_child.isolation.allocation_stratum != (parent.isolation.allocation_stratum)


def test_mutation_candidate_requires_explicit_operator_version_and_seed() -> None:
    parent = _semantic_candidate()
    child = _mutation_candidate(parent)
    invalid = bind_candidate_review_packet(
        replace(
            child,
            proposed_provenance=replace(
                child.proposed_provenance,
                mutation_operator=None,
            ),
        )
    )

    with pytest.raises(ValueError, match="complete pre-review mutation provenance"):
        validate_candidate_review_packet(invalid)


def test_mutation_promotion_requires_parent_and_rebinds_final_parent_identity() -> None:
    parent_packet = _semantic_candidate()
    child_packet = _mutation_candidate(parent_packet)
    parent_approval = _approved_record(parent_packet)
    child_approval = _approved_record(
        child_packet,
        approval_record_id="linear-review:issue-approval-child",
        reviewer_id="linear-user:reviewer-child-0001",
        approval_timestamp=_TIME.replace(minute=1),
    )

    with pytest.raises(ValueError, match="already promoted parent candidate"):
        promote_with_receipt(child_packet, child_approval)

    parent_result = promote_with_receipt(parent_packet, parent_approval)
    parent_evidence = ParentPromotionEvidence(
        packet=parent_packet,
        approval=parent_approval,
        result=parent_result,
    )
    child_result = promote_with_receipt(
        child_packet,
        child_approval,
        parent_promotion_evidence=parent_evidence,
    )
    child_case = child_result.case
    mutation_authority = next(
        item
        for item in child_case.authority
        if item.authority_kind == AuthorityKind.MUTATION_PARENT.value
    )

    assert child_case.provenance.parent_case_hash == parent_result.case.case_payload_hash
    assert mutation_authority.digest == parent_result.case.case_payload_hash
    assert any(
        edge.upstream_id == parent_result.case.case_payload_hash
        and edge.downstream_id == child_case.case_id
        and edge.relation == "MUTATION"
        for edge in child_case.provenance.derivation_edges
    )
    assert child_result.receipt.mutation_promotion_link is not None
    assert (
        child_result.receipt.mutation_promotion_link.parent_promotion_receipt_digest
        == parent_result.receipt.receipt_digest
    )
    validate_case(parent_result.case)
    validate_case(child_case)
    from dynamislm.benchmark import validate_case_set

    validate_case_set((parent_result.case, child_case))
    from dynamislm.benchmark.hashing import bind_case_payload

    bad_parent_authority_case = bind_case_payload(
        replace(
            child_case,
            authority=tuple(
                replace(item, digest="sha256:" + "b" * 64)
                if item.authority_kind == AuthorityKind.MUTATION_PARENT.value
                else item
                for item in child_case.authority
            ),
        )
    )
    with pytest.raises(ValueError, match="exact parent case hash"):
        validate_case(bad_parent_authority_case)
    validate_promotion_result(
        child_packet,
        child_approval,
        child_result,
        parent_promotion_evidence=parent_evidence,
    )
    assert from_canonical_json(canonical_json(child_result), PromotionResult) == child_result


@pytest.mark.parametrize(
    ("field_name", "forged_value"),
    (("source_reference_id", "forged-parent-id"), ("version", "9.9.9")),
)
def test_final_mutation_parent_authority_requires_exact_id_and_version(
    field_name: str,
    forged_value: str,
) -> None:
    parent_packet = _semantic_candidate()
    child_packet = _mutation_candidate(parent_packet)
    parent_approval = _approved_record(parent_packet)
    child_approval = _approved_record(
        child_packet,
        approval_record_id=f"linear-review:identity-forgery-{field_name}",
        reviewer_id=f"linear-user:identity-forgery-{field_name}",
    )
    parent_result = promote_with_receipt(parent_packet, parent_approval)
    child_result = promote_with_receipt(
        child_packet,
        child_approval,
        parent_promotion_evidence=ParentPromotionEvidence(
            packet=parent_packet,
            approval=parent_approval,
            result=parent_result,
        ),
    )
    from dynamislm.benchmark import validate_case_set
    from dynamislm.benchmark.hashing import bind_case_payload

    forged_child = bind_case_payload(
        replace(
            child_result.case,
            authority=tuple(
                (
                    replace(binding, source_reference_id=forged_value)
                    if field_name == "source_reference_id"
                    else replace(binding, version=forged_value)
                )
                if binding.authority_kind == AuthorityKind.MUTATION_PARENT.value
                else binding
                for binding in child_result.case.authority
            ),
        )
    )

    validate_case(forged_child)
    with pytest.raises(ValueError, match="exact final parent case"):
        validate_case_set((parent_result.case, forged_child))


def test_mutation_promotion_rejects_parent_promotion_identity_mismatch() -> None:
    parent_packet = _semantic_candidate()
    other_parent_packet = _candidate_from_case(
        next(
            item
            for item in build_synthetic_reference_fixture_cases()
            if item.provenance.origin_class is CaseOrigin.DETERMINISTIC_ENGINE_DERIVED
        )
    )
    child_packet = _mutation_candidate(parent_packet)
    other_approval = _approved_record(other_parent_packet)
    child_approval = _approved_record(
        child_packet,
        approval_record_id="linear-review:issue-approval-mismatch-child",
        reviewer_id="linear-user:reviewer-mismatch-0001",
    )
    other_result = promote_with_receipt(other_parent_packet, other_approval)

    with pytest.raises(ValueError, match="exact reviewed parent candidate"):
        promote_with_receipt(
            child_packet,
            child_approval,
            parent_promotion_evidence=ParentPromotionEvidence(
                packet=other_parent_packet,
                approval=other_approval,
                result=other_result,
            ),
        )


def test_mutation_promotion_rejects_parent_receipt_case_hash_mismatch() -> None:
    parent_packet = _semantic_candidate()
    child_packet = _mutation_candidate(parent_packet)
    parent_approval = _approved_record(parent_packet)
    child_approval = _approved_record(
        child_packet,
        approval_record_id="linear-review:issue-approval-hash-mismatch-child",
        reviewer_id="linear-user:reviewer-hash-mismatch-0001",
    )
    parent_result = promote_with_receipt(parent_packet, parent_approval)
    wrong_receipt = replace(
        parent_result.receipt,
        final_case_payload_hash="sha256:" + "a" * 64,
    )
    from dynamislm.benchmark.pre_review import _bind_promotion_receipt

    forged_parent = replace(
        parent_result,
        receipt=_bind_promotion_receipt(wrong_receipt),
    )

    with pytest.raises(ValueError, match="promotion receipt"):
        promote_with_receipt(
            child_packet,
            child_approval,
            parent_promotion_evidence=ParentPromotionEvidence(
                packet=parent_packet,
                approval=parent_approval,
                result=forged_parent,
            ),
        )


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


def test_review_event_reference_is_included_in_approval_hash() -> None:
    packet = _semantic_candidate()
    approval = _approved_record(packet)
    event_referenced = bind_human_approval_record(
        replace(approval, review_event_reference="opaque-test-event-reference")
    )

    assert event_referenced.approval_record_digest != approval.approval_record_digest


def test_forged_res71_binding_and_source_identity_are_rejected(tmp_path: Path) -> None:
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

    registered_source, source_resolver, _ = _controlled_source_candidate(tmp_path)
    validate_candidate_review_packet(registered_source, source_resolver=source_resolver)

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
        validate_candidate_review_packet(forged_identity, source_resolver=source_resolver)


def test_exact_jats_derived_source_span_passes(tmp_path: Path) -> None:
    packet, source_resolver, _ = _controlled_source_candidate(tmp_path)

    validate_candidate_review_packet(packet, source_resolver=source_resolver)


def test_phase_a_source_applicability_escalation_is_rejected(tmp_path: Path) -> None:
    from dynamislm.benchmark.res115_authoring import validate_res115_source_applicability

    packet, _, _ = _controlled_source_candidate(tmp_path)
    excerpt = packet.input.evidence_excerpts[0]
    scope = "INDIRECT_MEASUREMENT_EVIDENCE"
    registered_scopes = {excerpt.document_identity.document_id: scope}
    updated_excerpt = replace(excerpt, applicability=scope)
    updated_reference = replace(packet.source_evidence_refs[0], applicability=scope)
    fields = dict(packet.proposed_expected_answer.expected_fields.items())
    fields.update(
        {
            "source_spans": (updated_excerpt.text,),
            "source_scopes": (updated_excerpt.scope,),
            "applicability_scopes": (scope,),
            "target_population_use": ("METHOD_OR_MEASUREMENT_ONLY",),
        }
    )
    valid_packet = bind_candidate_review_packet(
        replace(
            packet,
            input=replace(packet.input, evidence_excerpts=(updated_excerpt,)),
            source_evidence_refs=(updated_reference,),
            proposed_expected_answer=replace(
                packet.proposed_expected_answer,
                expected_fields=fields,
            ),
        )
    )

    validate_res115_source_applicability(valid_packet, source_scopes=registered_scopes)

    escalated_fields = dict(valid_packet.proposed_expected_answer.expected_fields.items())
    escalated_fields["target_population_use"] = ("CANONICAL_TARGET_THRESHOLD",)
    escalated = bind_candidate_review_packet(
        replace(
            valid_packet,
            proposed_expected_answer=replace(
                valid_packet.proposed_expected_answer,
                expected_fields=escalated_fields,
            ),
        )
    )
    with pytest.raises(ValueError, match="cannot be escalated into target norms or thresholds"):
        validate_res115_source_applicability(escalated, source_scopes=registered_scopes)


def test_multi_reference_same_family_checks_each_document_and_span_authority(
    tmp_path: Path,
) -> None:
    packet, source_resolver, _ = _controlled_source_candidate(tmp_path, multi_reference=True)

    assert len(packet.source_evidence_refs) == 2
    assert len(packet.input.evidence_excerpts) == 2
    validate_candidate_review_packet(packet, source_resolver=source_resolver)

    for binding in tuple(packet.authority):
        if binding.authority_kind not in {
            AuthorityKind.SOURCE_DOCUMENT.value,
            AuthorityKind.SOURCE_EVIDENCE_SPAN.value,
        }:
            continue
        candidate_without_one_binding = bind_candidate_review_packet(
            replace(
                packet,
                authority=tuple(item for item in packet.authority if item != binding),
            )
        )
        with pytest.raises(
            ValueError,
            match="SOURCE_DOCUMENT authority|SOURCE_EVIDENCE_SPAN authority",
        ):
            validate_candidate_review_packet(
                candidate_without_one_binding,
                source_resolver=source_resolver,
            )


def test_source_backed_candidate_requires_an_explicit_resolver(tmp_path: Path) -> None:
    packet, _, _ = _controlled_source_candidate(tmp_path)

    with pytest.raises(ValueError, match="requires an explicit source resolver"):
        validate_candidate_review_packet(packet)


def test_accepted_registry_identity_with_fabricated_excerpt_is_rejected(tmp_path: Path) -> None:
    packet, source_resolver, _ = _controlled_source_candidate(tmp_path)
    excerpt = packet.input.evidence_excerpts[0]
    fabricated_text = "Fabricated text with a self-consistent excerpt digest."
    fabricated_span = replace(
        excerpt.span_identity,
        span_digest=_digest(fabricated_text.encode("utf-8")),
    )
    fabricated_excerpt = replace(excerpt, text=fabricated_text, span_identity=fabricated_span)
    authority = tuple(
        replace(binding, digest=fabricated_span.span_digest)
        if binding.authority_kind == AuthorityKind.SOURCE_EVIDENCE_SPAN.value
        else binding
        for binding in packet.authority
    )
    fabricated_packet = bind_candidate_review_packet(
        replace(
            packet,
            input=replace(packet.input, evidence_excerpts=(fabricated_excerpt,)),
            authority=authority,
        )
    )

    with pytest.raises(ValueError, match="differs from the exact JATS locator extraction"):
        validate_candidate_review_packet(fabricated_packet, source_resolver=source_resolver)


def test_wrong_structural_jats_locator_is_rejected(tmp_path: Path) -> None:
    packet, source_resolver, _ = _controlled_source_candidate(tmp_path)
    excerpt = packet.input.evidence_excerpts[0]
    wrong_locator = "jats-text-v1:/article[1]/body[1]/sec[9]/p[1]"
    wrong_span = replace(excerpt.span_identity, locator=wrong_locator)
    wrong_excerpt = replace(excerpt, span_identity=wrong_span)
    wrong_reference = replace(packet.source_evidence_refs[0], locator=wrong_locator)
    wrong_packet = bind_candidate_review_packet(
        replace(
            packet,
            input=replace(packet.input, evidence_excerpts=(wrong_excerpt,)),
            source_evidence_refs=(wrong_reference,),
        )
    )

    with pytest.raises(ValueError, match="does not resolve in retained article"):
        validate_candidate_review_packet(wrong_packet, source_resolver=source_resolver)


def test_retained_artifact_hash_mismatch_is_rejected(tmp_path: Path) -> None:
    packet, source_resolver, artifact_path = _controlled_source_candidate(tmp_path)
    wrong_bytes = gzip.compress(b"<article><body>wrong bytes</body></article>", mtime=0)
    artifact_path.write_bytes(wrong_bytes)

    with pytest.raises(ValueError, match="do not match the Phase-A SHA-256"):
        validate_candidate_review_packet(packet, source_resolver=source_resolver)


def test_source_backed_candidate_without_source_references_is_rejected(tmp_path: Path) -> None:
    packet, source_resolver, _ = _controlled_source_candidate(tmp_path)
    no_refs = bind_candidate_review_packet(replace(packet, source_evidence_refs=()))

    with pytest.raises(ValueError, match="both exact excerpts and typed references"):
        validate_candidate_review_packet(no_refs, source_resolver=source_resolver)


def test_source_backed_candidate_without_evidence_excerpts_is_rejected(tmp_path: Path) -> None:
    packet, source_resolver, _ = _controlled_source_candidate(tmp_path)
    no_excerpts = bind_candidate_review_packet(
        replace(packet, input=replace(packet.input, evidence_excerpts=()))
    )

    with pytest.raises(ValueError, match="both exact excerpts and typed references"):
        validate_candidate_review_packet(no_excerpts, source_resolver=source_resolver)


def test_source_backed_fake_provenance_only_span_ids_are_rejected(tmp_path: Path) -> None:
    packet, source_resolver, _ = _controlled_source_candidate(tmp_path)
    no_evidence = bind_candidate_review_packet(
        replace(
            packet,
            source_evidence_refs=(),
            input=replace(packet.input, evidence_excerpts=()),
        )
    )

    with pytest.raises(ValueError, match="requires source evidence references and exact excerpts"):
        validate_candidate_review_packet(no_evidence, source_resolver=source_resolver)


@pytest.mark.parametrize(
    "missing_authority_kind",
    (AuthorityKind.SOURCE_DOCUMENT.value, AuthorityKind.SOURCE_EVIDENCE_SPAN.value),
)
def test_source_backed_candidate_requires_both_source_authorities(
    tmp_path: Path, missing_authority_kind: str
) -> None:
    packet, source_resolver, _ = _controlled_source_candidate(tmp_path)
    without_document_authority = bind_candidate_review_packet(
        replace(
            packet,
            authority=tuple(
                binding
                for binding in packet.authority
                if binding.authority_kind != missing_authority_kind
            ),
        )
    )

    with pytest.raises(ValueError, match="SOURCE_DOCUMENT and SOURCE_EVIDENCE_SPAN"):
        validate_candidate_review_packet(
            without_document_authority,
            source_resolver=source_resolver,
        )
