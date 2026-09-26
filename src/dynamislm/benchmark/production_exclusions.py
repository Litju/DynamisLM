"""Qualification material exclusion commitments for the separate production lane."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, fields, replace
from pathlib import Path, PurePosixPath
from typing import Any

from dynamislm.benchmark.authoring import (
    QUALIFICATION_CANDIDATE_ID_PREFIX,
    AuthoringPlanV1,
    CandidateStoreReceiptV1,
    QualificationBatchManifestV1,
    validate_authoring_plan,
    validate_candidate_store_receipt,
    validate_qualification_batch_manifest,
)
from dynamislm.benchmark.constants import SplitName
from dynamislm.benchmark.contamination import (
    ContaminationArtifact,
    ExclusionRegistry,
    _build_contamination_match_index,
    audit_contamination,
    exact_13_token_shingles,
    fuzzy_fingerprint,
    normalized_text_sha256,
)
from dynamislm.benchmark.pre_review import (
    CandidateReviewPacket,
)
from dynamislm.benchmark.production import (
    PRODUCTION_CANDIDATE_ID_PREFIX,
    validate_production_candidate_packet,
)
from dynamislm.benchmark.source_artifacts import SourceArtifactResolver
from dynamislm.serialization import canonical_hash, register_serializable_type

QUALIFICATION_001B_BATCH_ID = "PSE-V1-QUALIFICATION/RES-115-CASE-AUTHORING-001B"
QUALIFICATION_EXCLUSION_VERSION = "pse-qualification-exclusion@1.0.0"
QUALIFICATION_TRAINING_EXCLUSION_VERSION = "pse-qualification-training-exclusion@1.0.0"
QUALIFICATION_PRIVATE_EXCLUSION_PATH = "production/exclusions/qualification-001B-private.json"
QUALIFICATION_TRAINING_EXCLUSION_PATH = (
    "reports/performance_science_eval/qualification_training_exclusions.json"
)
_SHA256 = re.compile(r"sha256:[0-9a-f]{64}\Z")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class QualificationExclusionCandidateV1:
    candidate_id: str
    candidate_payload_hash: str
    question_text: str
    exact_question_sha256: str
    normalized_question_sha256: str
    question_13_token_shingle_hashes: tuple[str, ...]
    seed_blocks: tuple[str, ...]
    seed_namespaces: tuple[str, ...]
    generator_seed_identities: tuple[tuple[str, str, str, str], ...]
    mutation_lineage_ids: tuple[str, ...]
    mutation_seed_values: tuple[int, ...]
    evidence_span_identities: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        if not self.candidate_id.startswith(QUALIFICATION_CANDIDATE_ID_PREFIX):
            raise ValueError(
                "qualification exclusion ID must remain in the qualification namespace"
            )
        if not _SHA256.fullmatch(self.candidate_payload_hash):
            raise ValueError("qualification exclusion payload hash is malformed")
        if not self.question_text:
            raise ValueError("qualification exclusion requires the exact canonical question")
        for name in ("exact_question_sha256", "normalized_question_sha256"):
            if not _SHA256.fullmatch(getattr(self, name)):
                raise ValueError(f"{name} is malformed")
        if self.exact_question_sha256 != (
            "sha256:" + hashlib.sha256(self.question_text.encode("utf-8")).hexdigest()
        ) or self.normalized_question_sha256 != normalized_text_sha256(self.question_text):
            raise ValueError("qualification question fingerprints differ from exact private text")
        if self.question_13_token_shingle_hashes != tuple(
            sorted(exact_13_token_shingles(self.question_text))
        ):
            raise ValueError("qualification question shingle set differs from exact private text")
        if tuple(sorted(set(self.question_13_token_shingle_hashes))) != (
            self.question_13_token_shingle_hashes
        ):
            raise ValueError("qualification shingle hashes must be unique and canonical")
        for name in ("seed_blocks", "seed_namespaces", "mutation_lineage_ids"):
            values = getattr(self, name)
            if values != tuple(sorted(set(values), key=lambda item: item.encode("utf-8"))):
                raise ValueError(f"{name} must use unique canonical ordering")
        for generator_id, version, namespace, seed_block in self.generator_seed_identities:
            if not all((generator_id, version, namespace, seed_block)):
                raise ValueError("qualification generator seed identities must be complete")
        if self.generator_seed_identities != tuple(sorted(set(self.generator_seed_identities))):
            raise ValueError("qualification generator seed identities must be unique and ordered")
        for span_id, span_digest in self.evidence_span_identities:
            if not span_id or not _SHA256.fullmatch(span_digest):
                raise ValueError("qualification evidence span identity is malformed")
        if self.evidence_span_identities != tuple(
            sorted(set(self.evidence_span_identities), key=lambda item: item[0].encode("utf-8"))
        ):
            raise ValueError("qualification evidence spans must use unique canonical ID ordering")
        if any(
            isinstance(seed, bool) or not isinstance(seed, int) or seed < 0
            for seed in self.mutation_seed_values
        ):
            raise ValueError("qualification mutation seed values must be non-negative integers")
        if self.mutation_seed_values != tuple(sorted(set(self.mutation_seed_values))):
            raise ValueError("qualification mutation seed values must be unique and ordered")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class QualificationExclusionCommitmentV1:
    batch_id: str
    version: str
    qualification_manifest_digest: str
    qualification_store_receipt_digest: str
    authoring_plan_digest: str
    seed_input_digest: str
    candidate_count: int
    entries: tuple[QualificationExclusionCandidateV1, ...]
    commitment_digest: str

    def __post_init__(self) -> None:
        if self.batch_id != QUALIFICATION_001B_BATCH_ID:
            raise ValueError("qualification exclusion must bind the sealed 001B corpus")
        if self.version != QUALIFICATION_EXCLUSION_VERSION:
            raise ValueError("unsupported qualification exclusion version")
        if self.candidate_count != len(self.entries) or not self.entries:
            raise ValueError("qualification exclusion candidate count mismatch")
        for name in (
            "qualification_manifest_digest",
            "qualification_store_receipt_digest",
            "authoring_plan_digest",
            "seed_input_digest",
            "commitment_digest",
        ):
            if not _SHA256.fullmatch(getattr(self, name)):
                raise ValueError(f"{name} must be a SHA-256 digest")
        ids = tuple(item.candidate_id for item in self.entries)
        hashes = tuple(item.candidate_payload_hash for item in self.entries)
        if len(set(ids)) != len(ids) or len(set(hashes)) != len(hashes):
            raise ValueError("qualification exclusion IDs and payload hashes must be unique")
        if ids != tuple(sorted(ids, key=lambda item: item.encode("utf-8"))):
            raise ValueError("qualification exclusion entries must use canonical ID ordering")


def qualification_exclusion_commitment_digest(
    commitment: QualificationExclusionCommitmentV1,
) -> str:
    return canonical_hash(
        {
            item.name: getattr(commitment, item.name)
            for item in fields(commitment)
            if item.name != "commitment_digest"
        }
    )


def bind_qualification_exclusion_commitment(
    commitment: QualificationExclusionCommitmentV1,
) -> QualificationExclusionCommitmentV1:
    return replace(
        commitment,
        commitment_digest=qualification_exclusion_commitment_digest(commitment),
    )


def validate_qualification_exclusion_commitment(
    commitment: QualificationExclusionCommitmentV1,
) -> None:
    if commitment.commitment_digest != qualification_exclusion_commitment_digest(commitment):
        raise ValueError("qualification exclusion commitment digest mismatch")


def build_qualification_exclusion_commitment(
    manifest: QualificationBatchManifestV1,
    store_receipt: CandidateStoreReceiptV1,
    plan: AuthoringPlanV1,
    packets: tuple[CandidateReviewPacket, ...],
    *,
    seed_input_digest: str,
    seed_blocks: tuple[tuple[str, str], ...],
) -> QualificationExclusionCommitmentV1:
    """Bind exact private 001B prompts, seed IDs, lineage, and evidence spans."""

    validate_qualification_batch_manifest(manifest)
    validate_candidate_store_receipt(store_receipt)
    validate_authoring_plan(plan)
    if (
        manifest.batch_id != QUALIFICATION_001B_BATCH_ID
        or store_receipt.batch_id != manifest.batch_id
    ):
        raise ValueError("qualification exclusion source is not the sealed 001B batch")
    if (
        manifest.authoring_plan_digest != plan.plan_digest
        or manifest.candidate_store_receipt_digest != store_receipt.receipt_digest
        or store_receipt.authoring_plan_digest != plan.plan_digest
    ):
        raise ValueError("qualification exclusion source bindings do not agree")
    if manifest.final_v1_eligible or not manifest.qualification_only:
        raise ValueError("qualification source cannot be final V1 material")
    if len(packets) != 101 or store_receipt.candidate_count != 101:
        raise ValueError("sealed 001B qualification exclusion requires exactly 101 packets")
    if not _SHA256.fullmatch(seed_input_digest):
        raise ValueError("qualification private seed input digest is malformed")
    by_plan = {item.candidate_id: item for item in plan.items}
    manifest_hashes = {
        item.candidate_id: item.candidate_payload_hash for item in manifest.candidate_entries
    }
    if set(by_plan) != set(manifest_hashes) or set(by_plan) != {
        item.candidate_id for item in packets
    }:
        raise ValueError("qualification plan, manifest, and store candidate IDs differ")
    seed_by_reference = dict(seed_blocks)
    planned_seed_blocks = tuple(
        sorted(
            (
                (item.engine_reference_case_id, item.seed_block)
                for item in plan.items
                if item.seed_block is not None
            ),
            key=lambda pair: str(pair[0]).encode("utf-8"),
        )
    )
    if planned_seed_blocks != tuple(sorted(seed_blocks, key=lambda pair: pair[0].encode("utf-8"))):
        raise ValueError("private qualification seed input differs from its plan")

    ordered_packets = tuple(sorted(packets, key=lambda item: item.candidate_id.encode("utf-8")))
    entries: list[QualificationExclusionCandidateV1] = []
    for packet in ordered_packets:
        item = by_plan[packet.candidate_id]
        provenance = packet.proposed_provenance
        if (
            packet.candidate_payload_hash != item.candidate_payload_hash
            or manifest_hashes[packet.candidate_id] != packet.candidate_payload_hash
        ):
            raise ValueError("qualification packet hash differs from its sealed plan/manifest")
        reference_seed = (
            seed_by_reference.get(item.engine_reference_case_id)
            if item.engine_reference_case_id is not None
            else None
        )
        seed_values = {
            value
            for value in (item.seed_block, provenance.seed_block, reference_seed)
            if value is not None
        }
        if len(seed_values) > 1:
            raise ValueError("qualification packet and generator seed block identities differ")
        namespaces = {
            value
            for value in (
                item.seed_namespace,
                provenance.seed_namespace,
                packet.contamination.generator_namespace,
            )
            if value is not None
        }
        generator_records: tuple[tuple[str, str, str, str], ...] = ()
        if provenance.generator_id is not None:
            if (
                provenance.generator_version is None
                or provenance.seed_namespace is None
                or provenance.seed_block is None
            ):
                raise ValueError("qualification synthetic seed provenance is incomplete")
            generator_records = (
                (
                    provenance.generator_id,
                    provenance.generator_version,
                    provenance.seed_namespace,
                    provenance.seed_block,
                ),
            )
            if (item.generator_id, item.seed_namespace, item.seed_block) != (
                provenance.generator_id,
                provenance.seed_namespace,
                provenance.seed_block,
            ):
                raise ValueError("qualification plan and packet generator identities differ")
        spans = tuple(
            sorted(
                {
                    (excerpt.span_identity.span_id, excerpt.span_identity.span_digest)
                    for excerpt in packet.input.evidence_excerpts
                },
                key=lambda pair: pair[0].encode("utf-8"),
            )
        )
        question_bytes = packet.question.encode("utf-8")
        entries.append(
            QualificationExclusionCandidateV1(
                candidate_id=packet.candidate_id,
                candidate_payload_hash=packet.candidate_payload_hash,
                question_text=packet.question,
                exact_question_sha256="sha256:" + hashlib.sha256(question_bytes).hexdigest(),
                normalized_question_sha256=normalized_text_sha256(packet.question),
                question_13_token_shingle_hashes=tuple(
                    sorted(exact_13_token_shingles(packet.question))
                ),
                seed_blocks=tuple(sorted(seed_values, key=lambda value: value.encode("utf-8"))),
                seed_namespaces=tuple(sorted(namespaces, key=lambda value: value.encode("utf-8"))),
                generator_seed_identities=generator_records,
                mutation_lineage_ids=(
                    (provenance.mutation_lineage_id,)
                    if provenance.mutation_lineage_id is not None
                    else ()
                ),
                mutation_seed_values=(
                    (provenance.mutation_seed,) if provenance.mutation_seed is not None else ()
                ),
                evidence_span_identities=spans,
            )
        )
    provisional = QualificationExclusionCommitmentV1(
        batch_id=manifest.batch_id,
        version=QUALIFICATION_EXCLUSION_VERSION,
        qualification_manifest_digest=manifest.manifest_digest,
        qualification_store_receipt_digest=store_receipt.receipt_digest,
        authoring_plan_digest=plan.plan_digest,
        seed_input_digest=seed_input_digest,
        candidate_count=len(entries),
        entries=tuple(entries),
        commitment_digest="sha256:" + "0" * 64,
    )
    return bind_qualification_exclusion_commitment(provisional)


@register_serializable_type
@dataclass(frozen=True, slots=True)
class QualificationTrainingExclusionEntryV1:
    candidate_id: str
    candidate_payload_hash: str
    exact_question_sha256: str
    normalized_question_sha256: str
    question_13_token_shingle_hashes: tuple[str, ...]
    fuzzy_fingerprint: str
    seed_block_digests: tuple[str, ...]
    seed_namespace_digests: tuple[str, ...]
    mutation_lineage_digests: tuple[str, ...]
    mutation_seed_digests: tuple[str, ...]
    evidence_span_identities: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        for name in (
            "candidate_payload_hash",
            "exact_question_sha256",
            "normalized_question_sha256",
            "fuzzy_fingerprint",
        ):
            if not _SHA256.fullmatch(getattr(self, name)):
                raise ValueError(f"{name} must be a SHA-256 digest")
        for name in (
            "seed_block_digests",
            "seed_namespace_digests",
            "mutation_lineage_digests",
            "mutation_seed_digests",
        ):
            values = getattr(self, name)
            if values != tuple(sorted(set(values))):
                raise ValueError(f"{name} must be unique and canonically ordered")
        if any(not _SHA256.fullmatch(item) for item in self.question_13_token_shingle_hashes):
            raise ValueError("public exact question shingles must be SHA-256 values")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class QualificationTrainingExclusionManifestV1:
    version: str
    qualification_batch_id: str
    qualification_manifest_digest: str
    qualification_exclusion_digest: str
    private_index_relative_path: str
    private_index_digest: str
    candidate_count: int
    entries: tuple[QualificationTrainingExclusionEntryV1, ...]
    manifest_digest: str

    def __post_init__(self) -> None:
        if self.version != QUALIFICATION_TRAINING_EXCLUSION_VERSION:
            raise ValueError("unsupported qualification training-exclusion version")
        if self.qualification_batch_id != QUALIFICATION_001B_BATCH_ID:
            raise ValueError("training exclusion must bind the 001B qualification corpus")
        if self.candidate_count != len(self.entries) or self.candidate_count != 101:
            raise ValueError("training exclusion must bind all 101 qualification candidates")
        path = PurePosixPath(self.private_index_relative_path)
        if (
            path.is_absolute()
            or ".." in path.parts
            or path.parts[:2] != ("production", "exclusions")
            or path.suffix != ".json"
        ):
            raise ValueError(
                "private exclusion index path must remain under production/exclusions/"
            )
        for name in (
            "qualification_manifest_digest",
            "qualification_exclusion_digest",
            "private_index_digest",
            "manifest_digest",
        ):
            if not _SHA256.fullmatch(getattr(self, name)):
                raise ValueError(f"{name} must be a SHA-256 digest")
        ids = tuple(item.candidate_id for item in self.entries)
        if ids != tuple(sorted(set(ids), key=lambda item: item.encode("utf-8"))):
            raise ValueError("training exclusion entries must use unique canonical candidate order")


def qualification_training_exclusion_manifest_digest(
    manifest: QualificationTrainingExclusionManifestV1,
) -> str:
    return canonical_hash(
        {
            item.name: getattr(manifest, item.name)
            for item in fields(manifest)
            if item.name != "manifest_digest"
        }
    )


def bind_qualification_training_exclusion_manifest(
    manifest: QualificationTrainingExclusionManifestV1,
) -> QualificationTrainingExclusionManifestV1:
    return replace(
        manifest,
        manifest_digest=qualification_training_exclusion_manifest_digest(manifest),
    )


def build_qualification_training_exclusion_manifest(
    commitment: QualificationExclusionCommitmentV1,
    *,
    private_index_relative_path: str,
    private_index_digest: str,
) -> QualificationTrainingExclusionManifestV1:
    validate_qualification_exclusion_commitment(commitment)
    if len(commitment.entries) != 101:
        raise ValueError("public training exclusion requires the full sealed 001B corpus")
    entries = tuple(
        QualificationTrainingExclusionEntryV1(
            candidate_id=item.candidate_id,
            candidate_payload_hash=item.candidate_payload_hash,
            exact_question_sha256=item.exact_question_sha256,
            normalized_question_sha256=item.normalized_question_sha256,
            question_13_token_shingle_hashes=tuple(
                f"sha256:{value}" for value in item.question_13_token_shingle_hashes
            ),
            fuzzy_fingerprint=fuzzy_fingerprint(item.question_text),
            seed_block_digests=tuple(sorted(canonical_hash(value) for value in item.seed_blocks)),
            seed_namespace_digests=tuple(
                sorted(canonical_hash(value) for value in item.seed_namespaces)
            ),
            mutation_lineage_digests=tuple(
                sorted(canonical_hash(value) for value in item.mutation_lineage_ids)
            ),
            mutation_seed_digests=tuple(
                sorted(canonical_hash(value) for value in item.mutation_seed_values)
            ),
            evidence_span_identities=item.evidence_span_identities,
        )
        for item in commitment.entries
    )
    provisional = QualificationTrainingExclusionManifestV1(
        version=QUALIFICATION_TRAINING_EXCLUSION_VERSION,
        qualification_batch_id=commitment.batch_id,
        qualification_manifest_digest=commitment.qualification_manifest_digest,
        qualification_exclusion_digest=commitment.commitment_digest,
        private_index_relative_path=private_index_relative_path,
        private_index_digest=private_index_digest,
        candidate_count=len(entries),
        entries=entries,
        manifest_digest="sha256:" + "0" * 64,
    )
    return bind_qualification_training_exclusion_manifest(provisional)


def _qualification_prompt_registry(
    commitment: QualificationExclusionCommitmentV1,
) -> tuple[ExclusionRegistry, Any]:
    artifacts = tuple(
        ContaminationArtifact(
            artifact_id=f"qualification-question:{entry.candidate_id}",
            document_id=None,
            document_content_digest=None,
            source_artifact_id=None,
            source_artifact_digest=None,
            text=entry.question_text,
            source_family_id=f"qualification-question:{entry.candidate_id}",
            split_name=SplitName.PUBLIC_DEVELOPMENT,
        )
        for entry in commitment.entries
    )
    registry = ExclusionRegistry.from_artifacts(artifacts)
    return registry, _build_contamination_match_index(registry)


def validate_production_exclusion_identity(
    *,
    candidate_id: str,
    candidate_payload_hash: str,
    question: str,
    seed_blocks: tuple[str, ...],
    seed_namespaces: tuple[str, ...],
    mutation_lineage_ids: tuple[str, ...],
    mutation_seed_values: tuple[int, ...],
    evidence_span_identities: tuple[tuple[str, str], ...],
    commitment: QualificationExclusionCommitmentV1,
) -> None:
    """Reject exact 001B identities before the frozen text-overlap scan."""

    validate_qualification_exclusion_commitment(commitment)
    if not candidate_id.startswith(PRODUCTION_CANDIDATE_ID_PREFIX):
        raise ValueError("qualification IDs cannot enter the production lane")
    entries = commitment.entries
    if any(item.candidate_id == candidate_id for item in entries):
        raise ValueError("qualification candidate ID cannot be used for production")
    if any(item.candidate_payload_hash == candidate_payload_hash for item in entries):
        raise ValueError("qualification candidate payload cannot be reused in production")
    exact_question_sha256 = "sha256:" + hashlib.sha256(question.encode("utf-8")).hexdigest()
    if any(
        question == item.question_text
        or exact_question_sha256 == item.exact_question_sha256
        or normalized_text_sha256(question) == item.normalized_question_sha256
        for item in entries
    ):
        raise ValueError("qualification canonical or normalized question cannot be reused")
    blocked_seed_blocks = {value for item in entries for value in item.seed_blocks}
    blocked_seed_namespaces = {value for item in entries for value in item.seed_namespaces}
    if set(seed_blocks).intersection(blocked_seed_blocks) or set(seed_namespaces).intersection(
        blocked_seed_namespaces
    ):
        raise ValueError("qualification generator seed or seed block cannot be reused")
    blocked_lineages = {value for item in entries for value in item.mutation_lineage_ids}
    if set(mutation_lineage_ids).intersection(blocked_lineages):
        raise ValueError("qualification mutation lineage cannot be reused")
    blocked_mutation_seeds = {value for item in entries for value in item.mutation_seed_values}
    if set(mutation_seed_values).intersection(blocked_mutation_seeds):
        raise ValueError("qualification mutation seed cannot be reused")
    blocked_span_ids = {
        span_id for item in entries for span_id, _digest in item.evidence_span_identities
    }
    blocked_span_digests = {
        digest for item in entries for _span_id, digest in item.evidence_span_identities
    }
    if any(
        span_id in blocked_span_ids or digest in blocked_span_digests
        for span_id, digest in evidence_span_identities
    ):
        raise ValueError("qualification evidence-span identity or digest cannot be reused")


def validate_production_candidate_against_qualification_exclusion(
    packet: CandidateReviewPacket,
    commitment: QualificationExclusionCommitmentV1,
    *,
    source_resolver: SourceArtifactResolver | None = None,
    _prompt_index: tuple[ExclusionRegistry, Any] | None = None,
) -> None:
    """Reject 001B reuse while allowing other spans from a shared Phase-A paper."""

    validate_qualification_exclusion_commitment(commitment)
    validate_production_candidate_packet(packet, source_resolver=source_resolver)
    provenance = packet.proposed_provenance
    candidate_seed_values = {
        value
        for value in (provenance.seed_block, packet.contamination.generator_seed_block)
        if value is not None
    }
    candidate_seed_namespaces = {
        value
        for value in (provenance.seed_namespace, packet.contamination.generator_namespace)
        if value is not None
    }
    candidate_spans = tuple(
        (excerpt.span_identity.span_id, excerpt.span_identity.span_digest)
        for excerpt in packet.input.evidence_excerpts
    )
    validate_production_exclusion_identity(
        candidate_id=packet.candidate_id,
        candidate_payload_hash=packet.candidate_payload_hash,
        question=packet.question,
        seed_blocks=tuple(sorted(candidate_seed_values)),
        seed_namespaces=tuple(sorted(candidate_seed_namespaces)),
        mutation_lineage_ids=(
            (provenance.mutation_lineage_id,) if provenance.mutation_lineage_id is not None else ()
        ),
        mutation_seed_values=(
            (provenance.mutation_seed,) if provenance.mutation_seed is not None else ()
        ),
        evidence_span_identities=candidate_spans,
        commitment=commitment,
    )
    registry, match_index = _prompt_index or _qualification_prompt_registry(commitment)
    candidate_artifact = ContaminationArtifact(
        artifact_id=f"production-question:{packet.candidate_id}",
        document_id=None,
        document_content_digest=None,
        source_artifact_id=None,
        source_artifact_digest=None,
        text=packet.question,
        source_family_id=f"production-question:{packet.candidate_id}",
        split_name=SplitName.PUBLIC_DEVELOPMENT,
    )
    audit = audit_contamination(candidate_artifact, registry, _match_index=match_index)
    if audit.status != "PASS":
        raise ValueError(
            "qualification question has frozen exact-shingle or blocking fuzzy overlap"
        )


def validate_production_candidate_set_against_qualification_exclusion(
    packets: tuple[CandidateReviewPacket, ...],
    commitment: QualificationExclusionCommitmentV1,
    *,
    source_resolver: SourceArtifactResolver | None = None,
) -> None:
    """Check the complete batch against one cached frozen 001B text index."""

    prompt_index = _qualification_prompt_registry(commitment)
    for packet in packets:
        validate_production_candidate_against_qualification_exclusion(
            packet,
            commitment,
            source_resolver=source_resolver,
            _prompt_index=prompt_index,
        )


def load_sealed_qualification_exclusion_source(
    *,
    repository_root: str | Path,
    qualification_root: str | Path,
    source_resolver: SourceArtifactResolver,
) -> tuple[
    QualificationBatchManifestV1,
    CandidateStoreReceiptV1,
    AuthoringPlanV1,
    tuple[CandidateReviewPacket, ...],
    str,
    tuple[tuple[str, str], ...],
]:
    """Read and verify the external sealed 001B batch and its private seeds."""

    import hashlib

    from dynamislm.benchmark.pre_review import validate_candidate_set
    from dynamislm.benchmark.qualification_store import (
        read_external_qualification_json,
        read_qualification_store,
    )
    from dynamislm.benchmark.res115_authoring import validate_res115_source_applicability
    from dynamislm.qualification.res115_authoring import QualificationSeedInputV1

    batch_key = hashlib.sha256(QUALIFICATION_001B_BATCH_ID.encode("utf-8")).hexdigest()[:24]
    plan, _plan_digest, _plan_size = read_external_qualification_json(
        f"qualification/authoring_plan/{batch_key}.json",
        AuthoringPlanV1,
        repository_root=repository_root,
        qualification_root=qualification_root,
    )
    receipt, _receipt_digest, _receipt_size = read_external_qualification_json(
        f"qualification/receipts/{batch_key}.json",
        CandidateStoreReceiptV1,
        repository_root=repository_root,
        qualification_root=qualification_root,
    )
    manifest, _manifest_file_digest, _manifest_size = read_external_qualification_json(
        f"qualification/manifests/{batch_key}.json",
        QualificationBatchManifestV1,
        repository_root=repository_root,
        qualification_root=qualification_root,
    )
    seed_input, seed_input_digest, _seed_input_size = read_external_qualification_json(
        "qualification/authoring_plan/private_seed_inputs.json",
        QualificationSeedInputV1,
        repository_root=repository_root,
        qualification_root=qualification_root,
    )
    if seed_input.batch_id != QUALIFICATION_001B_BATCH_ID:
        raise ValueError("private seed input is not bound to the sealed 001B batch")
    packets = read_qualification_store(
        receipt,
        repository_root=repository_root,
        qualification_root=qualification_root,
    )
    validate_candidate_set(packets, source_resolver=source_resolver)
    for packet in packets:
        if packet.source_evidence_refs or packet.input.evidence_excerpts:
            validate_res115_source_applicability(packet)
    return manifest, receipt, plan, packets, seed_input_digest, seed_input.seed_blocks


__all__ = [
    "QUALIFICATION_001B_BATCH_ID",
    "QUALIFICATION_EXCLUSION_VERSION",
    "QUALIFICATION_PRIVATE_EXCLUSION_PATH",
    "QUALIFICATION_TRAINING_EXCLUSION_PATH",
    "QUALIFICATION_TRAINING_EXCLUSION_VERSION",
    "QualificationExclusionCandidateV1",
    "QualificationExclusionCommitmentV1",
    "QualificationTrainingExclusionEntryV1",
    "QualificationTrainingExclusionManifestV1",
    "bind_qualification_exclusion_commitment",
    "bind_qualification_training_exclusion_manifest",
    "build_qualification_exclusion_commitment",
    "build_qualification_training_exclusion_manifest",
    "load_sealed_qualification_exclusion_source",
    "qualification_exclusion_commitment_digest",
    "qualification_training_exclusion_manifest_digest",
    "validate_production_candidate_against_qualification_exclusion",
    "validate_production_candidate_set_against_qualification_exclusion",
    "validate_qualification_exclusion_commitment",
]
