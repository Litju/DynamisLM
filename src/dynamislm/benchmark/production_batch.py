"""Cross-bind and reload the complete external 001C production batch."""

from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict

from dynamislm.benchmark.authoring import ACTIVE_SCORERS
from dynamislm.benchmark.constants import (
    CAPABILITY_IDS,
    FAMILY_IDS,
    AuthorityKind,
    CaseOrigin,
    DifficultyLevel,
    ErrorClass,
    ExpectedAnswerKind,
    PractitionerQuestionClass,
    RefusalDecision,
)
from dynamislm.benchmark.coverage import COVERAGE_MATRIX
from dynamislm.benchmark.pre_review import CandidateReviewPacket
from dynamislm.benchmark.production import (
    FINAL_TARGET_CASES,
    PRODUCTION_BATCH_ID,
    PRODUCTION_CANDIDATE_ID_PREFIX,
    PROSPECTIVE_SPLIT_COUNTS,
    ProductionAuthoringPlanV1,
    ProductionBatchManifestV1,
    ProductionCandidateCommitmentV1,
    ProductionCandidateStoreReceiptV1,
    ProductionDuplicationAuditV1,
    ProductionFeasibilityReceiptV1,
    ProductionReviewQueueV1,
    audit_production_duplicates,
    validate_production_authoring_plan,
    validate_production_batch_manifest,
    validate_production_batch_manifest_bindings,
    validate_production_candidate_set,
    validate_production_candidate_store_receipt,
    validate_production_feasibility_receipt,
    validate_production_hard_feasibility,
    validate_production_review_queue,
)
from dynamislm.benchmark.production_exclusions import (
    QualificationExclusionCommitmentV1,
    validate_production_candidate_set_against_qualification_exclusion,
    validate_qualification_exclusion_commitment,
)
from dynamislm.benchmark.production_store import (
    DEFAULT_PRODUCTION_ROOT,
    read_external_production_json,
    read_production_candidate_store,
)
from dynamislm.benchmark.res115_authoring import (
    build_res115_source_artifact_resolver,
    validate_res115_candidate_for_authoring,
)
from dynamislm.benchmark.source_artifacts import SourceArtifactResolver
from dynamislm.serialization import canonical_hash


def production_batch_key() -> str:
    return hashlib.sha256(PRODUCTION_BATCH_ID.encode("utf-8")).hexdigest()[:24]


@dataclass(frozen=True, slots=True)
class ProductionBatchValidationV1:
    status: str
    candidate_count: int
    production_plan_digest: str
    production_store_receipt_digest: str
    production_feasibility_receipt_digest: str
    production_manifest_digest: str
    qualification_exclusion_digest: str
    review_queue_digest: str
    duplication_audit_digest: str
    candidate_counts_by_origin: tuple[tuple[str, int], ...]
    capability_count: int
    family_count: int
    cell_count: int
    question_class_count: int
    scorer_count: int
    error_class_count: int
    required_refusal_count: int
    answerable_count: int
    safe_partial_count: int
    source_backed_count: int
    source_family_count: int
    exact_source_span_count: int
    direct_target_document_count: int
    source_stratum_count: int
    engine_derived_count: int
    represented_reference_count: int
    deterministic_synthetic_count: int
    mutation_count: int
    mutation_lineage_count: int
    difficulty_counts: tuple[tuple[str, int], ...]
    cluster_size_distribution: tuple[tuple[int, int], ...]
    review_batch_size_distribution: tuple[tuple[int, int], ...]


class _ProductionQuality(TypedDict):
    origin_counts: tuple[tuple[str, int], ...]
    capability_count: int
    family_count: int
    cell_count: int
    question_class_count: int
    scorer_count: int
    error_class_count: int
    required_refusal_count: int
    answerable_count: int
    safe_partial_count: int
    source_count: int
    source_family_count: int
    exact_span_count: int
    source_stratum_count: int
    engine_count: int
    reference_count: int
    synthetic_count: int
    mutation_count: int
    mutation_lineage_count: int
    difficulty_counts: tuple[tuple[str, int], ...]
    cluster_size_distribution: tuple[tuple[int, int], ...]
    review_batch_size_distribution: tuple[tuple[int, int], ...]


def _phase_a_source_coverage(
    packets: tuple[CandidateReviewPacket, ...],
    source_resolver: SourceArtifactResolver,
) -> tuple[int, int, int, int]:
    from dynamislm.qualification.res115_authoring import (
        PHASE_A_SEARCH_STRATA,
        _mapping,
        _phase_a_source_inputs,
        _string,
    )

    accepted, _support, direct_rows, strata_by_pmcid = _phase_a_source_inputs()
    accepted_by_document = {
        _string(
            _mapping(row.get("retained_source_artifact"), field="retained source artifact").get(
                "document_identity_id"
            ),
            field="document identity ID",
        ): row
        for row in accepted
    }
    direct_pmcids = {
        _string(row.get("pmcid"), field="direct-target PMCID")
        for row in direct_rows
        if row.get("applicability_scope") == "DIRECT_TARGET_POPULATION_EVIDENCE"
    }
    if len(direct_pmcids) != 5:
        raise ValueError("sealed Phase-A direct-target source set is not exactly five documents")
    direct_document_ids = {
        _string(
            _mapping(row.get("retained_source_artifact"), field="retained source artifact").get(
                "document_identity_id"
            ),
            field="document identity ID",
        )
        for row in accepted
        if _string(row.get("pmcid"), field="accepted PMCID") in direct_pmcids
    }
    source_packets = tuple(
        packet
        for packet in packets
        if packet.proposed_provenance.origin_class is CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION
    )
    observed_document_ids = {
        excerpt.document_identity.document_id
        for packet in source_packets
        for excerpt in packet.input.evidence_excerpts
    }
    if not direct_document_ids.issubset(observed_document_ids):
        raise ValueError("production source lane misses a direct-target Phase-A document")
    observed_strata: set[str] = set()
    for document_id in observed_document_ids:
        row = accepted_by_document.get(document_id)
        if row is None:
            raise ValueError("production source packet cites a document outside Phase-A")
        observed_strata.update(
            strata_by_pmcid.get(_string(row.get("pmcid"), field="accepted PMCID"), ())
        )
    if not set(PHASE_A_SEARCH_STRATA).issubset(observed_strata):
        raise ValueError("production source lane misses one or more Phase-A evidence strata")
    scopes = {
        excerpt.applicability
        for packet in source_packets
        for excerpt in packet.input.evidence_excerpts
    }
    expected_scopes = {
        "DIRECT_TARGET_POPULATION_EVIDENCE",
        "INDIRECT_MEASUREMENT_EVIDENCE",
        "NONCANONICAL_CONTEXT_ONLY",
    }
    if not expected_scopes.issubset(scopes):
        raise ValueError("production source lane lacks a Phase-A applicability boundary")
    source_families = {packet.isolation.source_family_id for packet in source_packets}
    if len(source_packets) < 40 or len(source_families) < 25:
        raise ValueError("production source lane misses its case/family minimum")
    span_count = sum(len(packet.input.evidence_excerpts) for packet in source_packets)
    return len(source_packets), len(source_families), span_count, len(PHASE_A_SEARCH_STRATA)


def _validate_quality(
    packets: tuple[CandidateReviewPacket, ...],
    commitments: tuple[ProductionCandidateCommitmentV1, ...],
    source_resolver: SourceArtifactResolver,
    feasibility: ProductionFeasibilityReceiptV1,
    queue: ProductionReviewQueueV1,
) -> _ProductionQuality:
    if len(packets) != FINAL_TARGET_CASES:
        raise ValueError("production batch must contain exactly 434 packets")
    if any(packet.review_status.value != "PENDING_HUMAN_REVIEW" for packet in packets):
        raise ValueError("every production candidate must remain pending human review")
    if any(
        not packet.candidate_id.startswith(PRODUCTION_CANDIDATE_ID_PREFIX) for packet in packets
    ):
        raise ValueError("production batch contains a non-production candidate ID")

    cells = {(packet.capability_id, packet.benchmark_family) for packet in packets}
    required_cells = {
        (row.capability_id, family) for row in COVERAGE_MATRIX for family in row.benchmark_families
    }
    if cells != required_cells:
        raise ValueError("production batch does not represent every frozen capability-family cell")
    clusters_by_cell: dict[tuple[str, str], set[str]] = defaultdict(set)
    for commitment in commitments:
        item = commitment.item
        clusters_by_cell[(item.capability_id, item.benchmark_family)].add(item.isolation_cluster_id)
    if any(len(clusters_by_cell[cell]) < 3 for cell in required_cells):
        raise ValueError("each frozen capability-family cell requires three independent clusters")

    origin_counts = Counter(packet.proposed_provenance.origin_class.value for packet in packets)
    origin_requirements = {
        CaseOrigin.EXPERT_AUTHORED_SEMANTIC.value: (0, 240),
        CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION.value: (40, FINAL_TARGET_CASES),
        CaseOrigin.DETERMINISTIC_ENGINE_DERIVED.value: (30, FINAL_TARGET_CASES),
        CaseOrigin.DETERMINISTIC_SYNTHETIC.value: (12, FINAL_TARGET_CASES),
        CaseOrigin.ADVERSARIAL_MUTATION.value: (60, FINAL_TARGET_CASES),
    }
    if set(origin_counts) != set(origin_requirements):
        raise ValueError("production batch must contain exactly the five frozen origins")
    for origin, (minimum, maximum) in origin_requirements.items():
        if not minimum <= origin_counts[origin] <= maximum:
            raise ValueError(f"production origin count violates its frozen bound: {origin}")

    question_classes = {packet.practitioner_question_class for packet in packets}
    scorers = {packet.scoring_contract.profile_id for packet in packets}
    reachable_errors = {
        error for item in commitments for error in item.item.reachable_error_classes
    }
    if len({packet.capability_id for packet in packets}) != len(CAPABILITY_IDS):
        raise ValueError("production batch misses a frozen capability")
    if len({packet.benchmark_family for packet in packets}) != len(FAMILY_IDS):
        raise ValueError("production batch misses a frozen benchmark family")
    if len(question_classes) != len(PractitionerQuestionClass):
        raise ValueError("production batch misses a frozen practitioner question class")
    if scorers != set(ACTIVE_SCORERS):
        raise ValueError("production batch misses an active scorer")
    if reachable_errors != set(ErrorClass):
        raise ValueError("production batch misses a reachable frozen error class")

    required_refusals = sum(
        packet.refusal_contract.decision is RefusalDecision.REQUIRED for packet in packets
    )
    answerable = sum(
        packet.refusal_contract.decision is not RefusalDecision.REQUIRED
        and packet.proposed_expected_answer.kind is not ExpectedAnswerKind.REFUSAL
        for packet in packets
    )
    safe_partial = sum(
        bool(packet.refusal_contract.what_can_still_be_safely_described)
        and bool(
            packet.refusal_contract.safe_lower_claim_level is not None
            or packet.claim_contract.safe_lower_claim_levels
            or packet.proposed_expected_answer.safe_lower_level_descriptions
        )
        for packet in packets
    )
    if required_refusals < 60 or answerable < 1:
        raise ValueError("production batch misses refusal or answerable-case coverage")
    if {packet.difficulty.level for packet in packets} != set(DifficultyLevel):
        raise ValueError("production batch must represent EASY, MEDIUM, and HARD")

    c17_families = {packet.benchmark_family for packet in packets if packet.capability_id == "C17"}
    c17_packets = tuple(packet for packet in packets if packet.capability_id == "C17")
    if c17_families != set(FAMILY_IDS) or any(
        packet.proposed_provenance.origin_class is CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION
        or packet.proposed_expected_answer.expected_fields.get("error_class")
        not in {item.value for item in ErrorClass}
        for packet in c17_packets
    ):
        raise ValueError("C17 requires F01-F14 explicit error cases without forced source tags")
    if {packet.benchmark_family for packet in packets if packet.capability_id == "C18"} != set(
        FAMILY_IDS
    ):
        raise ValueError("C18 requires F01-F14 refusal/insufficient-information coverage")

    source_count, source_family_count, exact_span_count, source_stratum_count = (
        _phase_a_source_coverage(packets, source_resolver)
    )
    for packet in packets:
        if packet.source_evidence_refs:
            validate_res115_candidate_for_authoring(packet)

    from dynamislm.qualification.res115_authoring import (
        _RES71_REFERENCES,
        validate_res115_reference_candidate,
    )

    reference_ids = {
        binding.source_reference_id
        for packet in packets
        for binding in packet.authority
        if binding.authority_kind == AuthorityKind.RES71_REFERENCE_CASE.value
    }
    if reference_ids != {item.case_id for item in _RES71_REFERENCES}:
        raise ValueError("production batch does not represent all twelve sealed RES-71 cases")
    for packet in packets:
        if any(
            binding.authority_kind == AuthorityKind.RES71_REFERENCE_CASE.value
            for binding in packet.authority
        ):
            validate_res115_reference_candidate(packet)
    engine_count = origin_counts[CaseOrigin.DETERMINISTIC_ENGINE_DERIVED.value]
    if engine_count < 30:
        raise ValueError("production batch requires at least 30 engine-derived candidates")
    synthetic_packets = tuple(
        packet
        for packet in packets
        if packet.proposed_provenance.origin_class is CaseOrigin.DETERMINISTIC_SYNTHETIC
    )
    from dynamislm.benchmark.authoring import (
        parse_production_seed_namespace,
        validate_split_qualified_seed_namespace,
    )

    expected_synthetic_families = {"F05", "F06", "F13", "F14"}
    synthetic_splits: dict[tuple[str, str], int] = Counter()
    for packet in synthetic_packets:
        provenance = packet.proposed_provenance
        parsed = parse_production_seed_namespace(provenance.seed_namespace or "")
        parsed = validate_split_qualified_seed_namespace(
            provenance.seed_namespace or "",
            split_name=parsed.split_name,
            generator_id=provenance.generator_id or "",
            generator_version=provenance.generator_version or "",
            seed_block=provenance.seed_block or "",
        )
        if (
            packet.capability_id != "C08"
            or packet.benchmark_family not in expected_synthetic_families
        ):
            raise ValueError("deterministic-synthetic lane must be C08 x F05/F06/F13/F14")
        if packet.proposed_expected_answer.kind is ExpectedAnswerKind.NUMERIC_RESULT:
            raise ValueError("deterministic-synthetic candidates cannot invent numerical gold")
        synthetic_splits[(packet.benchmark_family, parsed.split_name.value)] += 1
    if set(synthetic_splits) != {
        (family, split.value)
        for family in expected_synthetic_families
        for split, _count in PROSPECTIVE_SPLIT_COUNTS
    } or any(count < 1 for count in synthetic_splits.values()):
        raise ValueError("synthetic C08 coverage must span four families and all three splits")

    mutation_packets = tuple(
        packet
        for packet in packets
        if packet.proposed_provenance.origin_class is CaseOrigin.ADVERSARIAL_MUTATION
    )
    mutation_lineages = {
        packet.proposed_provenance.mutation_lineage_id for packet in mutation_packets
    }
    if len(mutation_packets) < 60 or len(mutation_lineages) < 20:
        raise ValueError("production mutation lane misses its case/lineage minimum")
    if not any(
        packet.parent_candidate_binding is not None
        and packet.parent_candidate_binding.parent_origin_class
        is not CaseOrigin.ADVERSARIAL_MUTATION
        for packet in mutation_packets
    ) or not any(
        packet.parent_candidate_binding is not None
        and packet.parent_candidate_binding.parent_origin_class is CaseOrigin.ADVERSARIAL_MUTATION
        for packet in mutation_packets
    ):
        raise ValueError("mutation lane must contain ordinary parents and descendants")
    if not any(
        packet.refusal_contract.decision is RefusalDecision.REQUIRED
        and packet.refusal_contract.what_can_still_be_safely_described
        for packet in mutation_packets
    ):
        raise ValueError("mutation lane requires safe-partial/refusal cases")
    if not any(
        packet.capability_id in {"C01", "C03", "C04"} for packet in mutation_packets
    ) or not any(packet.capability_id in {"C07", "C09", "C15"} for packet in mutation_packets):
        raise ValueError(
            "mutation lane misses measurement-identity and claim/comparability failures"
        )

    validate_production_review_queue(queue, packets)
    queue_sizes = Counter(item.review_batch_id for item in queue.entries)
    if any(size > 15 for size in queue_sizes.values()):
        raise ValueError("Phase-C review batches must remain human-manageable (maximum 15)")
    commitments_digest = canonical_hash(commitments)
    if feasibility.commitments_digest != commitments_digest:
        raise ValueError("feasibility receipt is stale against current candidate commitments")

    cluster_sizes = Counter(item.item.isolation_cluster_id for item in commitments)
    return {
        "origin_counts": tuple(sorted(origin_counts.items())),
        "capability_count": len({packet.capability_id for packet in packets}),
        "family_count": len({packet.benchmark_family for packet in packets}),
        "cell_count": len(cells),
        "question_class_count": len(question_classes),
        "scorer_count": len(scorers),
        "error_class_count": len(reachable_errors),
        "required_refusal_count": required_refusals,
        "answerable_count": answerable,
        "safe_partial_count": safe_partial,
        "source_count": source_count,
        "source_family_count": source_family_count,
        "exact_span_count": exact_span_count,
        "source_stratum_count": source_stratum_count,
        "engine_count": engine_count,
        "reference_count": len(reference_ids),
        "synthetic_count": len(synthetic_packets),
        "mutation_count": len(mutation_packets),
        "mutation_lineage_count": len(mutation_lineages),
        "difficulty_counts": tuple(
            sorted(
                (
                    level.value,
                    sum(packet.difficulty.level is level for packet in packets),
                )
                for level in DifficultyLevel
            )
        ),
        "cluster_size_distribution": tuple(sorted(Counter(cluster_sizes.values()).items())),
        "review_batch_size_distribution": tuple(sorted(Counter(queue_sizes.values()).items())),
    }


def validate_production_batch(
    *,
    plan: ProductionAuthoringPlanV1,
    packets: tuple[CandidateReviewPacket, ...],
    candidate_store_receipt: ProductionCandidateStoreReceiptV1,
    qualification_exclusions: QualificationExclusionCommitmentV1,
    feasibility_receipt: ProductionFeasibilityReceiptV1,
    manifest: ProductionBatchManifestV1,
    source_resolver: SourceArtifactResolver,
    review_queue: ProductionReviewQueueV1,
    duplication_audit: ProductionDuplicationAuditV1,
    repository_root: str | Path,
    production_root: str | Path = DEFAULT_PRODUCTION_ROOT,
) -> ProductionBatchValidationV1:
    """Reload and cross-bind every production artifact before Phase-C review."""

    from dynamislm.benchmark.production import (
        production_duplication_audit_digest,
    )

    key = production_batch_key()
    root_args = {"repository_root": repository_root, "production_root": production_root}
    paths_and_types = (
        (f"production/authoring_plan/{key}.json", ProductionAuthoringPlanV1, plan),
        (
            f"production/receipts/{key}.json",
            ProductionCandidateStoreReceiptV1,
            candidate_store_receipt,
        ),
        (
            f"production/receipts/{key}-feasibility.json",
            ProductionFeasibilityReceiptV1,
            feasibility_receipt,
        ),
        (f"production/manifests/{key}.json", ProductionBatchManifestV1, manifest),
        (f"production/review/{key}.json", ProductionReviewQueueV1, review_queue),
        (
            f"production/exclusions/{key}-duplication-audit.json",
            ProductionDuplicationAuditV1,
            duplication_audit,
        ),
    )
    for relative, expected_type, expected in paths_and_types:
        persisted, _file_digest, _size = read_external_production_json(
            relative, expected_type, **root_args
        )
        if persisted != expected:
            raise ValueError(
                f"external production artifact differs from supplied value: {relative}"
            )
    persisted_exclusions, _exclusion_file_digest, _exclusion_size = read_external_production_json(
        "production/exclusions/qualification-001B-private.json",
        QualificationExclusionCommitmentV1,
        **root_args,
    )
    if persisted_exclusions != qualification_exclusions:
        raise ValueError(
            "supplied qualification exclusion differs from the sealed external artifact"
        )

    if source_resolver != build_res115_source_artifact_resolver():
        raise ValueError("production batch requires the sealed Phase-A source resolver")
    validate_production_authoring_plan(plan)
    validate_production_candidate_store_receipt(candidate_store_receipt)
    validate_qualification_exclusion_commitment(qualification_exclusions)
    validate_production_feasibility_receipt(feasibility_receipt)
    validate_production_batch_manifest(manifest)
    validate_production_candidate_set_against_qualification_exclusion(
        packets, qualification_exclusions, source_resolver=source_resolver
    )
    commitments = validate_production_candidate_set(packets, source_resolver=source_resolver)
    if (
        tuple(item.candidate_id for item in plan.items)
        != tuple(item.candidate_id for item in commitments)
        or tuple(item.item for item in commitments) != plan.items
    ):
        raise ValueError("production plan IDs/metadata differ from exact packet commitments")
    if (
        plan.plan_digest != candidate_store_receipt.authoring_plan_digest
        or plan.qualification_exclusion_digest != qualification_exclusions.commitment_digest
        or manifest.candidate_count != FINAL_TARGET_CASES
        or any(
            value != 0
            for value in (
                manifest.human_approval_count,
                manifest.final_case_count,
                manifest.split_assignment_count,
                manifest.protected_store_count,
            )
        )
    ):
        raise ValueError("production manifest component digests or lifecycle counts are stale")
    validate_production_batch_manifest_bindings(
        manifest,
        authoring_plan_digest=plan.plan_digest,
        candidate_store_receipt_digest=candidate_store_receipt.receipt_digest,
        qualification_exclusion_digest=qualification_exclusions.commitment_digest,
        feasibility_receipt_digest=feasibility_receipt.receipt_digest,
    )
    if candidate_store_receipt.candidate_count != FINAL_TARGET_CASES:
        raise ValueError("candidate store receipt must bind exactly 434 files")
    if feasibility_receipt.candidate_count != FINAL_TARGET_CASES or (
        feasibility_receipt.target_counts != PROSPECTIVE_SPLIT_COUNTS
    ):
        raise ValueError("feasibility receipt does not bind exact 260/87/87 targets")
    stored_packets = read_production_candidate_store(
        candidate_store_receipt,
        source_resolver=source_resolver,
        qualification_exclusions=qualification_exclusions,
        **root_args,
    )
    if stored_packets != tuple(sorted(packets, key=lambda item: item.candidate_id.encode("utf-8"))):
        raise ValueError("reloaded production packets differ from the supplied in-memory set")
    computed_audit = audit_production_duplicates(packets)
    computed_feasibility = validate_production_hard_feasibility(
        commitments,
        exact_shingle_colocation_pairs=computed_audit.exact_shingle_colocation_pairs,
    )
    if computed_feasibility != feasibility_receipt:
        raise ValueError("feasibility receipt differs from exact current commitments")
    if (
        computed_audit != duplication_audit
        or duplication_audit.audit_digest != production_duplication_audit_digest(duplication_audit)
    ):
        raise ValueError("intra-production duplication audit is stale")
    computed_queue = review_queue
    validate_production_review_queue(computed_queue, packets)

    quality = _validate_quality(
        stored_packets,
        commitments,
        source_resolver,
        feasibility_receipt,
        review_queue,
    )
    return ProductionBatchValidationV1(
        status="PASS",
        candidate_count=FINAL_TARGET_CASES,
        production_plan_digest=plan.plan_digest,
        production_store_receipt_digest=candidate_store_receipt.receipt_digest,
        production_feasibility_receipt_digest=feasibility_receipt.receipt_digest,
        production_manifest_digest=manifest.manifest_digest,
        qualification_exclusion_digest=qualification_exclusions.commitment_digest,
        review_queue_digest=review_queue.queue_digest,
        duplication_audit_digest=duplication_audit.audit_digest,
        candidate_counts_by_origin=quality["origin_counts"],
        capability_count=quality["capability_count"],
        family_count=quality["family_count"],
        cell_count=quality["cell_count"],
        question_class_count=quality["question_class_count"],
        scorer_count=quality["scorer_count"],
        error_class_count=quality["error_class_count"],
        required_refusal_count=quality["required_refusal_count"],
        answerable_count=quality["answerable_count"],
        safe_partial_count=quality["safe_partial_count"],
        source_backed_count=quality["source_count"],
        source_family_count=quality["source_family_count"],
        exact_source_span_count=quality["exact_span_count"],
        direct_target_document_count=5,
        source_stratum_count=quality["source_stratum_count"],
        engine_derived_count=quality["engine_count"],
        represented_reference_count=quality["reference_count"],
        deterministic_synthetic_count=quality["synthetic_count"],
        mutation_count=quality["mutation_count"],
        mutation_lineage_count=quality["mutation_lineage_count"],
        difficulty_counts=quality["difficulty_counts"],
        cluster_size_distribution=quality["cluster_size_distribution"],
        review_batch_size_distribution=quality["review_batch_size_distribution"],
    )


__all__ = ["ProductionBatchValidationV1", "production_batch_key", "validate_production_batch"]
