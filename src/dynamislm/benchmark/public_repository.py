"""Deterministic public-repository leak guard for protected PSE-V1 splits."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import subprocess
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, cast

from dynamislm.benchmark.constants import SplitName
from dynamislm.benchmark.contracts import BenchmarkCaseV1, BenchmarkManifestV1
from dynamislm.serialization import canonical_data, canonical_hash, canonical_json

if TYPE_CHECKING:
    from dynamislm.benchmark.authoring import AuthoringPlanV1
    from dynamislm.benchmark.pre_review import CandidateReviewPacket

_PROTECTED_SPLITS = frozenset({SplitName.FROZEN_VALIDATION, SplitName.HIDDEN_FINAL})
_FORBIDDEN_CASE_FIELDS = frozenset(
    {
        "answer",
        "answers",
        "case_payload",
        "expected_answer",
        "input",
        "payload",
        "prompt",
        "question",
        "question_text",
    }
)
_ALLOWED_PROTECTED_METADATA_FIELDS = frozenset(
    {
        "answer_fingerprint",
        "answer_hash",
        "benchmark_manifest_hash",
        "case_id",
        "case_ids",
        "case_payload_hash",
        "case_hashes",
        "credential_namespace",
        "exact_shingle_digest",
        "fingerprints",
        "fuzzy_fingerprint",
        "manifest_commitment",
        "manifest_hash",
        "membership_digest",
        "normalized_text_sha256",
        "payload_fingerprint",
        "payload_hash",
        "protected_case_ids",
        "protected_case_hashes",
        "protected_split",
        "split",
        "split_manifest_hash",
        "split_membership_digest",
        "split_name",
        "store_id",
        "store_version",
    }
)
_CASE_ID_LIST_FIELDS = ("case_ids", "protected_case_ids", "validation_case_ids", "hidden_case_ids")
_CASE_HASH_FIELDS = ("case_hashes", "protected_case_hashes", "hidden_case_hashes")
_SENSITIVE_PATH_PARTS = ("answer", "input", "payload", "prompt", "question")
_DIGEST_METADATA_FIELDS = frozenset(
    {
        "answer_fingerprint",
        "answer_hash",
        "benchmark_manifest_hash",
        "case_payload_hash",
        "exact_shingle_digest",
        "fuzzy_fingerprint",
        "manifest_commitment",
        "manifest_hash",
        "membership_digest",
        "normalized_text_sha256",
        "payload_fingerprint",
        "payload_hash",
        "split_manifest_hash",
        "split_membership_digest",
    }
)


@dataclass(frozen=True, slots=True)
class ProtectedPublicCaseCommitmentV1:
    protected_split: SplitName
    case_id: str
    case_payload_hash: str
    payload_hash: str
    answer_hash: str
    normalized_text_sha256: str
    exact_shingle_digest: str
    fuzzy_fingerprint: str
    split_manifest_hash: str
    benchmark_manifest_hash: str


@dataclass(frozen=True, slots=True)
class ProtectedRepositoryLeakGuardV1:
    repository_head: str
    protected_case_hashes: tuple[tuple[str, str], ...]
    artifact_count: int
    repository_artifact_digest: str
    status: str = "PASS"

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[0-9a-f]{40,64}", self.repository_head):
            raise ValueError("repository leak evidence must bind a Git HEAD")
        if not self.protected_case_hashes:
            raise ValueError("repository leak evidence must bind protected cases")
        if self.artifact_count < 1:
            raise ValueError("repository leak evidence must inspect public artifacts")
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", self.repository_artifact_digest):
            raise ValueError("repository leak evidence must bind the scanned artifact inventory")
        if self.status != "PASS":
            raise ValueError("repository leak evidence can only be constructed after PASS")


@dataclass(frozen=True, slots=True)
class QualificationRepositoryLeakGuardV1:
    """Public-safe leak-scan receipt for a private qualification batch."""

    qualification_batch_id: str
    repository_head: str
    candidate_count: int
    source_span_count: int
    history_blob_count: int
    index_artifact_count: int
    worktree_artifact_count: int
    external_artifact_digest: str
    repository_artifact_digest: str
    status: str = "PASS"

    def __post_init__(self) -> None:
        if not self.qualification_batch_id.startswith("PSE-V1-QUALIFICATION/"):
            raise ValueError("leak evidence must bind the qualification-only batch namespace")
        if not re.fullmatch(r"[0-9a-f]{40,64}", self.repository_head):
            raise ValueError("qualification leak evidence must bind a Git HEAD")
        if (
            min(
                self.candidate_count,
                self.source_span_count,
                self.history_blob_count,
                self.index_artifact_count,
                self.worktree_artifact_count,
            )
            < 0
        ):
            raise ValueError("qualification leak evidence counts cannot be negative")
        for digest in (self.external_artifact_digest, self.repository_artifact_digest):
            if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
                raise ValueError("qualification leak evidence requires SHA-256 inventory digests")
        if self.status != "PASS":
            raise ValueError("qualification leak evidence can only be constructed after PASS")


@dataclass(frozen=True, slots=True)
class ProductionRepositoryLeakGuardV1:
    repository_head: str
    candidate_count: int
    private_pattern_count: int
    history_blob_count: int
    index_artifact_count: int
    worktree_artifact_count: int
    repository_artifact_digest: str
    status: str = "PASS"

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[0-9a-f]{40,64}", self.repository_head):
            raise ValueError("production leak evidence must bind a Git HEAD")
        if (
            min(
                self.candidate_count,
                self.private_pattern_count,
                self.history_blob_count,
                self.index_artifact_count,
                self.worktree_artifact_count,
            )
            < 0
        ):
            raise ValueError("production leak evidence counts cannot be negative")
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", self.repository_artifact_digest):
            raise ValueError("production leak evidence requires an artifact inventory digest")
        if self.status != "PASS":
            raise ValueError("production leak evidence can only be constructed after PASS")


def public_protected_case_commitments(
    cases: Iterable[BenchmarkCaseV1], benchmark_manifest: BenchmarkManifestV1
) -> tuple[ProtectedPublicCaseCommitmentV1, ...]:
    """Return the exact metadata allowed for public protected-split manifests."""

    protected_cases = tuple(case for case in cases if case.split.split_name in _PROTECTED_SPLITS)
    if not protected_cases:
        raise ValueError("protected public commitments require protected cases")
    manifest_hash = benchmark_manifest.benchmark_manifest_hash
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", manifest_hash):
        raise ValueError("protected public commitments require a bound benchmark manifest")
    commitments = tuple(
        ProtectedPublicCaseCommitmentV1(
            protected_split=_require_protected_split(case),
            case_id=case.case_id,
            case_payload_hash=case.case_payload_hash,
            payload_hash=canonical_hash({"question": case.question, "input": case.input}),
            answer_hash=canonical_hash(case.expected_answer),
            normalized_text_sha256=_required_normalized_text_fingerprint(case),
            exact_shingle_digest=case.contamination.exact_shingle_digest,
            fuzzy_fingerprint=case.contamination.fuzzy_fingerprint,
            split_manifest_hash=case.split.split_manifest_hash or "",
            benchmark_manifest_hash=manifest_hash,
        )
        for case in sorted(protected_cases, key=lambda item: item.case_id.encode("utf-8"))
    )
    if any(not commitment.split_manifest_hash for commitment in commitments):
        raise ValueError("protected public commitments require split-manifest bindings")
    return commitments


def validate_protected_repository_boundary(
    cases: Iterable[BenchmarkCaseV1],
    *,
    repository_root: str | Path,
    benchmark_manifest_hash: str | None = None,
) -> ProtectedRepositoryLeakGuardV1:
    """Scan current HEAD, the Git index, and working files for protected bytes."""

    protected_cases = tuple(case for case in cases if case.split.split_name in _PROTECTED_SPLITS)
    if not protected_cases:
        raise ValueError("protected repository guard requires validation/hidden cases")
    protected_cases = tuple(sorted(protected_cases, key=lambda item: item.case_id.encode("utf-8")))
    case_hashes = tuple((case.case_id, case.case_payload_hash) for case in protected_cases)
    root = Path(repository_root).resolve()
    repository_head = _git(root, "rev-parse", "HEAD").decode("ascii").strip()
    artifact_inventory: dict[tuple[str, str], str] = {}
    contents: list[tuple[str, str, bytes]] = []

    for object_id, relative_path in _head_blobs(root):
        data = _git(root, "cat-file", "blob", object_id)
        path = f"{relative_path}"
        artifact_inventory[("HEAD", path)] = _bytes_sha256(data)
        contents.append(("HEAD", path, data))
    for object_id, relative_path in _index_blobs(root):
        data = _git(root, "cat-file", "blob", object_id)
        artifact_inventory[("INDEX", relative_path)] = _bytes_sha256(data)
        contents.append(("INDEX", relative_path, data))
    for relative_path in _working_paths(root):
        full_path = root / PurePosixPath(relative_path)
        if full_path.is_symlink():
            data = os.fsencode(os.readlink(full_path))
        elif full_path.is_file():
            data = full_path.read_bytes()
        else:
            continue
        artifact_inventory[("WORKTREE", relative_path)] = _bytes_sha256(data)
        contents.append(("WORKTREE", relative_path, data))

    _reject_protected_material(
        protected_cases,
        contents,
        benchmark_manifest_hash=benchmark_manifest_hash,
    )
    inventory_digest = canonical_hash(
        tuple(
            (source, path, digest)
            for (source, path), digest in sorted(
                artifact_inventory.items(),
                key=lambda item: (item[0][0], item[0][1].encode("utf-8")),
            )
        )
    )
    return ProtectedRepositoryLeakGuardV1(
        repository_head=repository_head,
        protected_case_hashes=case_hashes,
        artifact_count=len(artifact_inventory),
        repository_artifact_digest=inventory_digest,
    )


def validate_qualification_repository_boundary(
    packets: Iterable[object],
    plan: object,
    store_receipt: object,
    *,
    repository_root: str | Path,
    qualification_root: str | Path,
) -> QualificationRepositoryLeakGuardV1:
    """Scan all Git objects, the index, and the worktree against external material.

    Candidate packet bytes, exact model-visible questions, expected-answer JSON,
    JATS excerpts, private seed blocks, and the exact authoring plan remain
    external. Qualification IDs and hashes may appear in public reports.
    """

    from dynamislm.benchmark.authoring import (
        AuthoringPlanV1,
        CandidateStoreReceiptV1,
        validate_authoring_plan,
        validate_candidate_store_receipt,
    )
    from dynamislm.benchmark.pre_review import CandidateReviewPacket
    from dynamislm.benchmark.qualification_store import (
        read_external_qualification_json,
        read_qualification_store,
    )
    from dynamislm.qualification.res115_authoring import QualificationSeedInputV1

    if not isinstance(plan, AuthoringPlanV1):
        raise TypeError("plan must be AuthoringPlanV1")
    if not isinstance(store_receipt, CandidateStoreReceiptV1):
        raise TypeError("store_receipt must be CandidateStoreReceiptV1")
    materialized_packets = tuple(packets)
    if not materialized_packets or any(
        not isinstance(packet, CandidateReviewPacket) for packet in materialized_packets
    ):
        raise ValueError("qualification leak scan requires typed candidate packets")
    typed_packets = cast(tuple[CandidateReviewPacket, ...], materialized_packets)
    validate_authoring_plan(plan, require_all_cells=False)
    validate_candidate_store_receipt(store_receipt)
    if store_receipt.authoring_plan_digest != plan.plan_digest:
        raise ValueError("external candidate store is bound to a different authoring plan")
    if store_receipt.candidate_count != len(typed_packets):
        raise ValueError("external candidate store has a different packet count")

    root = Path(repository_root).resolve()
    external_root = Path(qualification_root).resolve()
    if external_root.is_relative_to(root):
        raise ValueError("qualification payloads must remain outside the public repository")
    key = hashlib.sha256(store_receipt.batch_id.encode("utf-8")).hexdigest()[:24]
    plan_relative = f"qualification/authoring_plan/{key}.json"
    receipt_relative = f"qualification/receipts/{key}.json"
    seed_input_path = (
        external_root / "qualification" / "authoring_plan" / "private_seed_inputs.json"
    )
    external_plan, _plan_digest, _plan_size = read_external_qualification_json(
        plan_relative,
        AuthoringPlanV1,
        repository_root=root,
        qualification_root=external_root,
    )
    external_store_receipt, _receipt_digest, _receipt_size = read_external_qualification_json(
        receipt_relative,
        CandidateStoreReceiptV1,
        repository_root=root,
        qualification_root=external_root,
    )
    if external_plan != plan:
        raise ValueError("external authoring plan bytes differ from the bound plan")
    if external_store_receipt != store_receipt:
        raise ValueError("external candidate-store receipt bytes differ from its commitment")
    external_plan_bytes = (canonical_json(external_plan) + "\n").encode("utf-8")
    external_receipt_bytes = (canonical_json(external_store_receipt) + "\n").encode("utf-8")
    external_seed_input_bytes: bytes | None = None
    seed_input_digest: str | None = None
    if seed_input_path.exists():
        seed_input, seed_input_digest, _seed_size = read_external_qualification_json(
            "qualification/authoring_plan/private_seed_inputs.json",
            QualificationSeedInputV1,
            repository_root=root,
            qualification_root=external_root,
        )
        if seed_input.batch_id != store_receipt.batch_id:
            raise ValueError("private qualification seed input belongs to a different batch")
        plan_seed_blocks = tuple(
            sorted(
                (
                    (item.engine_reference_case_id, item.seed_block)
                    for item in plan.items
                    if item.seed_block is not None
                ),
                key=lambda item: str(item[0]).encode("utf-8"),
            )
        )
        if plan_seed_blocks != seed_input.seed_blocks:
            raise ValueError("private seed input differs from the external authoring plan")
        external_seed_input_bytes = (canonical_json(seed_input) + "\n").encode("utf-8")
    restored_packets = read_qualification_store(
        store_receipt,
        repository_root=root,
        qualification_root=external_root,
    )
    expected_packets = tuple(
        sorted(typed_packets, key=lambda packet: packet.candidate_id.encode("utf-8"))
    )
    if restored_packets != expected_packets:
        raise ValueError("external packet store differs from the leak-scan candidate set")

    external_packet_bytes: dict[str, bytes] = {}
    for packet in typed_packets:
        external_packet_bytes[packet.candidate_id] = (canonical_json(packet) + "\n").encode("utf-8")

    repository_head = _git(root, "rev-parse", "HEAD").decode("ascii").strip()
    artifact_inventory: dict[tuple[str, str], str] = {}
    contents: list[tuple[str, str, bytes]] = []
    history_blob_count = 0
    for object_id, data in _all_history_blobs(root):
        path = f"object:{object_id}"
        artifact_inventory[("HISTORY", path)] = _bytes_sha256(data)
        contents.append(("HISTORY", path, data))
        history_blob_count += 1
    for object_id, relative_path in _index_blobs(root):
        data = _git(root, "cat-file", "blob", object_id)
        artifact_inventory[("INDEX", relative_path)] = _bytes_sha256(data)
        contents.append(("INDEX", relative_path, data))
    for relative_path in _working_paths(root):
        full_path = root / PurePosixPath(relative_path)
        if full_path.is_symlink():
            data = os.fsencode(os.readlink(full_path))
        elif full_path.is_file():
            data = full_path.read_bytes()
        else:
            continue
        artifact_inventory[("WORKTREE", relative_path)] = _bytes_sha256(data)
        contents.append(("WORKTREE", relative_path, data))

    _reject_qualification_material(
        typed_packets,
        plan,
        external_plan_bytes,
        external_packet_bytes,
        external_seed_input_bytes,
        contents,
    )
    repository_inventory_digest = canonical_hash(
        tuple(
            (source, path, digest)
            for (source, path), digest in sorted(
                artifact_inventory.items(),
                key=lambda item: (item[0][0], item[0][1].encode("utf-8")),
            )
        )
    )
    external_inventory_digest = canonical_hash(
        {
            "plan": _bytes_sha256(external_plan_bytes),
            "receipt": _bytes_sha256(external_receipt_bytes),
            "private_seed_input": seed_input_digest,
            "packets": tuple(
                (
                    candidate_id,
                    _bytes_sha256(data),
                )
                for candidate_id, data in sorted(
                    external_packet_bytes.items(),
                    key=lambda item: item[0].encode("utf-8"),
                )
            ),
        }
    )
    return QualificationRepositoryLeakGuardV1(
        qualification_batch_id=store_receipt.batch_id,
        repository_head=repository_head,
        candidate_count=len(typed_packets),
        source_span_count=len(
            tuple(excerpt for packet in typed_packets for excerpt in packet.input.evidence_excerpts)
        ),
        history_blob_count=history_blob_count,
        index_artifact_count=len(
            tuple(path for (source, path) in artifact_inventory if source == "INDEX")
        ),
        worktree_artifact_count=len(
            tuple(path for (source, path) in artifact_inventory if source == "WORKTREE")
        ),
        external_artifact_digest=external_inventory_digest,
        repository_artifact_digest=repository_inventory_digest,
    )


def _git(root: Path, *args: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
    )
    return result.stdout


def _all_history_blobs(root: Path) -> Iterator[tuple[str, bytes]]:
    """Read every blob object, including unreachable objects left in Git history."""

    inventory = _git(
        root,
        "cat-file",
        "--batch-all-objects",
        "--batch-check=%(objectname) %(objecttype)",
    )
    object_ids = tuple(
        line.split(b" ", maxsplit=1)[0].decode("ascii")
        for line in inventory.splitlines()
        if line.endswith(b" blob")
    )
    if not object_ids:
        return
    result = subprocess.run(
        ["git", "-C", str(root), "cat-file", "--batch"],
        input=("\n".join(object_ids) + "\n").encode("ascii"),
        check=True,
        capture_output=True,
    ).stdout
    position = 0
    for expected_id in object_ids:
        header_end = result.find(b"\n", position)
        if header_end < 0:
            raise ValueError("Git batch blob output ended before a complete object header")
        header = result[position:header_end].decode("ascii").split(" ")
        if len(header) != 3 or header[0] != expected_id or header[1] != "blob":
            raise ValueError("Git batch blob output does not match the object inventory")
        byte_count = int(header[2])
        content_start = header_end + 1
        content_end = content_start + byte_count
        if content_end >= len(result) or result[content_end : content_end + 1] != b"\n":
            raise ValueError("Git batch blob output has an invalid object boundary")
        yield expected_id, result[content_start:content_end]
        position = content_end + 1


def _reject_qualification_material(
    packets: tuple[CandidateReviewPacket, ...],
    plan: AuthoringPlanV1,
    external_plan_bytes: bytes,
    external_packet_bytes: dict[str, bytes],
    external_seed_input_bytes: bytes | None,
    contents: list[tuple[str, str, bytes]],
) -> None:
    patterns: dict[bytes, str] = {}
    candidate_ids = {packet.candidate_id for packet in packets}
    protected_answers: list[object] = []
    private_packet_fields = frozenset(
        {
            "question",
            "input",
            "proposed_expected_answer",
            "expected_answer",
            "source_evidence_refs",
            "evidence_excerpts",
            "proposed_provenance",
            "refusal_contract",
            "claim_contract",
            "comparability_contract",
            "scoring_contract",
            "contamination",
        }
    )
    private_plan_fields = frozenset(
        {
            "authoring_rationale",
            "engine_operation_id",
            "parent_candidate_id",
            "recipe_id",
            "seed_block",
            "seed_namespace",
            "source_reference_ids",
            "source_search_strata",
        }
    )
    for candidate_id, packet_bytes in external_packet_bytes.items():
        _add_pattern(patterns, packet_bytes, f"external qualification packet {candidate_id}")
        _add_pattern(
            patterns,
            packet_bytes.rstrip(b"\n"),
            f"external qualification packet {candidate_id}",
        )
    _add_pattern(patterns, external_plan_bytes, "private external authoring plan")
    _add_pattern(patterns, external_plan_bytes.rstrip(b"\n"), "private external authoring plan")
    if external_seed_input_bytes is not None:
        _add_pattern(
            patterns,
            external_seed_input_bytes,
            "private external qualification seed input",
        )
        _add_pattern(
            patterns,
            external_seed_input_bytes.rstrip(b"\n"),
            "private external qualification seed input",
        )
    plan_payload = canonical_data(plan)
    protected_answers.append(plan_payload)
    for packet in packets:
        question = packet.question
        _add_pattern(patterns, question.encode("utf-8"), "qualification question")
        answer = packet.proposed_expected_answer
        answer_payload = canonical_data(answer)
        protected_answers.append(answer_payload)
        _add_pattern(
            patterns,
            canonical_json(answer).encode("utf-8"),
            "proposed qualification answer payload",
        )
        input_contract = packet.input
        for excerpt in input_contract.evidence_excerpts:
            _add_pattern(
                patterns,
                excerpt.text.encode("utf-8"),
                "exact retained-JATS qualification excerpt",
            )
    for item in plan.items:
        for field_name in ("seed_block", "authoring_rationale"):
            value = getattr(item, field_name)
            if isinstance(value, str) and value:
                _add_pattern(patterns, value.encode("utf-8"), f"private plan field {field_name}")

    for source, path, data in contents:
        for pattern, label in patterns.items():
            if pattern and pattern in data:
                raise ValueError(f"{label} found in public Git {source} artifact {path}")
        for document in _public_structures(data, path):
            for value in _walk_json(document):
                if any(value == answer for answer in protected_answers):
                    raise ValueError(
                        f"protected qualification answer or plan object found in {source}:{path}"
                    )
                if not isinstance(value, dict):
                    continue
                referenced_ids = set()
                direct_candidate_id = value.get("candidate_id")
                if isinstance(direct_candidate_id, str):
                    referenced_ids.add(direct_candidate_id)
                for key in _CASE_ID_LIST_FIELDS:
                    ids = value.get(key)
                    if isinstance(ids, list):
                        referenced_ids.update(item for item in ids if isinstance(item, str))
                matched_candidate_ids = referenced_ids.intersection(candidate_ids)
                if not matched_candidate_ids:
                    continue
                fields = set(value)
                if fields.intersection(private_packet_fields):
                    candidate_id = min(matched_candidate_ids, key=lambda item: item.encode("utf-8"))
                    raise ValueError(
                        "public qualification record exposes packet fields for "
                        f"{candidate_id} in {source}:{path}"
                    )
                if fields.intersection(private_plan_fields):
                    candidate_id = min(matched_candidate_ids, key=lambda item: item.encode("utf-8"))
                    raise ValueError(
                        "public qualification record exposes private plan fields for "
                        f"{candidate_id} in {source}:{path}"
                    )


def _head_blobs(root: Path) -> Iterator[tuple[str, str]]:
    output = _git(root, "ls-tree", "-r", "-z", "HEAD")
    for record in output.split(b"\0"):
        if not record:
            continue
        header, path_bytes = record.split(b"\t", 1)
        mode, kind, object_id = header.decode("ascii").split(" ", 2)
        if kind == "blob" and mode != "160000":
            yield object_id, os.fsdecode(path_bytes)


def _index_blobs(root: Path) -> Iterator[tuple[str, str]]:
    output = _git(root, "ls-files", "--stage", "-z")
    for record in output.split(b"\0"):
        if not record:
            continue
        header, path_bytes = record.split(b"\t", 1)
        _mode, object_id, stage = header.decode("ascii").split(" ", 2)
        if stage == "0":
            yield object_id, os.fsdecode(path_bytes)


def _working_paths(root: Path) -> Iterator[str]:
    # Include ignored worktree files too: candidate bytes can leak under an
    # ignored scratch path even when they never enter the index.
    output = _git(root, "ls-files", "-z", "--cached", "--others")
    for path_bytes in output.split(b"\0"):
        if path_bytes:
            yield os.fsdecode(path_bytes)


def validate_production_private_material_absent(
    private_material: Iterable[tuple[str, str | bytes]],
    *,
    repository_root: str | Path,
    candidate_count: int = 0,
) -> ProductionRepositoryLeakGuardV1:
    """Scan history, index, and worktree for exact production private bytes."""

    root = Path(repository_root).resolve()
    repository_head = _git(root, "rev-parse", "HEAD").decode("ascii").strip()
    patterns: dict[bytes, str] = {}
    for label, value in private_material:
        payload = value if isinstance(value, bytes) else value.encode("utf-8")
        _add_pattern(patterns, payload, label)

    artifact_inventory: dict[tuple[str, str], str] = {}
    history_blob_count = 0
    index_artifact_count = 0
    worktree_artifact_count = 0
    contents: list[tuple[str, str, bytes]] = []
    for object_id, data in _all_history_blobs(root):
        artifact_inventory[("HISTORY", object_id)] = _bytes_sha256(data)
        contents.append(("HISTORY", object_id, data))
        history_blob_count += 1
    for object_id, relative_path in _index_blobs(root):
        data = _git(root, "cat-file", "blob", object_id)
        artifact_inventory[("INDEX", relative_path)] = _bytes_sha256(data)
        contents.append(("INDEX", relative_path, data))
        index_artifact_count += 1
    for relative_path in _working_paths(root):
        working_path = root / PurePosixPath(relative_path)
        if working_path.is_symlink():
            data = os.fsencode(os.readlink(working_path))
        elif working_path.is_file():
            data = working_path.read_bytes()
        else:
            continue
        artifact_inventory[("WORKTREE", relative_path)] = _bytes_sha256(data)
        contents.append(("WORKTREE", relative_path, data))
        worktree_artifact_count += 1
    for source, artifact_path, data in contents:
        for pattern, label in patterns.items():
            if pattern in data:
                raise ValueError(f"{label} found in public Git {source} artifact {artifact_path}")
    inventory_digest = canonical_hash(
        tuple(
            (source, path, digest)
            for (source, path), digest in sorted(
                artifact_inventory.items(),
                key=lambda item: (item[0][0], item[0][1].encode("utf-8")),
            )
        )
    )
    return ProductionRepositoryLeakGuardV1(
        repository_head=repository_head,
        candidate_count=candidate_count,
        private_pattern_count=len(patterns),
        history_blob_count=history_blob_count,
        index_artifact_count=index_artifact_count,
        worktree_artifact_count=worktree_artifact_count,
        repository_artifact_digest=inventory_digest,
    )


def validate_production_repository_boundary(
    packets: Iterable[object],
    plan: object,
    store_receipt: object,
    qualification_exclusions: object,
    *,
    repository_root: str | Path,
    production_root: str | Path,
    private_material: Iterable[tuple[str, str | bytes]] = (),
) -> ProductionRepositoryLeakGuardV1:
    """Verify an external production store and scan its private bytes against Git."""

    from dynamislm.benchmark.pre_review import CandidateReviewPacket
    from dynamislm.benchmark.production import (
        ProductionAuthoringPlanV1,
        ProductionCandidateStoreReceiptV1,
        validate_production_authoring_plan,
    )
    from dynamislm.benchmark.production_exclusions import (
        QualificationExclusionCommitmentV1,
        validate_qualification_exclusion_commitment,
    )
    from dynamislm.benchmark.production_store import read_production_candidate_store

    if not isinstance(plan, ProductionAuthoringPlanV1):
        raise TypeError("plan must be ProductionAuthoringPlanV1")
    if not isinstance(store_receipt, ProductionCandidateStoreReceiptV1):
        raise TypeError("store_receipt must be ProductionCandidateStoreReceiptV1")
    if not isinstance(qualification_exclusions, QualificationExclusionCommitmentV1):
        raise TypeError("qualification exclusions must be typed")
    materialized_packets = tuple(packets)
    if len(materialized_packets) != plan.target_case_count or any(
        not isinstance(packet, CandidateReviewPacket) for packet in materialized_packets
    ):
        raise ValueError("production leak scan requires the exact typed candidate batch")
    typed_packets = cast(tuple[CandidateReviewPacket, ...], materialized_packets)
    validate_production_authoring_plan(plan)
    validate_qualification_exclusion_commitment(qualification_exclusions)
    if (
        store_receipt.authoring_plan_digest != plan.plan_digest
        or plan.qualification_exclusion_digest != qualification_exclusions.commitment_digest
    ):
        raise ValueError("production leak scan bindings do not match the external batch")
    restored = read_production_candidate_store(
        store_receipt,
        repository_root=repository_root,
        production_root=production_root,
        qualification_exclusions=qualification_exclusions,
    )
    expected = tuple(sorted(typed_packets, key=lambda item: item.candidate_id.encode("utf-8")))
    if restored != expected:
        raise ValueError("external production candidate store differs from the leak-scan set")

    from dynamislm.benchmark.pre_review import candidate_payload_hash

    private = list(private_material)
    private.append(("private production authoring plan", canonical_json(plan)))
    for packet in typed_packets:
        if candidate_payload_hash(packet) != packet.candidate_payload_hash:
            raise ValueError("production packet payload hash changed before leak scanning")
        private.extend(
            (
                ("private production packet JSON", canonical_json(packet)),
                ("production candidate question", packet.question),
                (
                    "private production expected answer",
                    canonical_json(packet.proposed_expected_answer),
                ),
                ("private production input parameters", canonical_json(packet.input)),
            )
        )
        for excerpt in packet.input.evidence_excerpts:
            private.append(("private production evidence excerpt", excerpt.text))
        provenance = packet.proposed_provenance
        for name in ("seed_namespace", "seed_block"):
            value = getattr(provenance, name)
            if value is not None:
                private.append((f"private production {name}", value))
        if provenance.mutation_seed is not None:
            private.append(("private production mutation seed", str(provenance.mutation_seed)))
    return validate_production_private_material_absent(
        private,
        repository_root=repository_root,
        candidate_count=len(typed_packets),
    )


def _bytes_sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _reject_protected_material(
    protected_cases: tuple[BenchmarkCaseV1, ...],
    contents: list[tuple[str, str, bytes]],
    *,
    benchmark_manifest_hash: str | None,
) -> None:
    case_by_id = {case.case_id: case for case in protected_cases}
    case_metadata = {case.case_id: _case_public_metadata(case) for case in protected_cases}
    case_splits = {case.case_id: _require_protected_split(case).value for case in protected_cases}
    patterns: dict[bytes, str] = {}
    expected_json_values: list[object] = []
    prompt_texts: set[str] = set()
    answer_json_texts: set[str] = set()
    for case in protected_cases:
        prompt_texts.update((case.question, case.input.question_text))
        _add_pattern(patterns, case.question.encode("utf-8"), f"{case.split.split_name} prompt")
        _add_pattern(
            patterns,
            case.input.question_text.encode("utf-8"),
            f"{case.split.split_name} prompt",
        )
        expected_json_values.extend(
            (canonical_data(case.input), canonical_data(case.expected_answer))
        )
        answer_json_texts.add(
            json.dumps(
                canonical_data(case.expected_answer),
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            )
        )
        answer_json_texts.add(canonical_json(case.expected_answer))

    for source, path, data in contents:
        normalized_path = path.casefold()
        path_case_ids = tuple(case_id for case_id in case_by_id if case_id in path)
        if path_case_ids and any(part in normalized_path for part in _SENSITIVE_PATH_PARTS):
            case_id = min(path_case_ids, key=lambda item: item.encode("utf-8"))
            raise ValueError(
                f"protected case artifact path exposes prompt/input/answer bytes for {case_id} "
                f"in {source}:{path}"
            )
        for pattern, label in patterns.items():
            if pattern in data:
                raise ValueError(
                    f"protected {label} bytes found in public repository artifact {source}:{path}"
                )
        for document in _public_structures(data, path):
            for value in _walk_json(document):
                if isinstance(value, str) and value in prompt_texts:
                    raise ValueError(
                        f"protected prompt text found in public repository artifact {source}:{path}"
                    )
                if isinstance(value, str) and value in answer_json_texts:
                    raise ValueError(
                        "protected answer bytes found in public repository artifact "
                        f"{source}:{path}"
                    )
                if value in expected_json_values:
                    raise ValueError(
                        "protected payload/answer object found in public repository artifact "
                        f"{source}:{path}"
                    )
                if isinstance(value, dict):
                    referenced_ids = set()
                    direct_case_id = value.get("case_id")
                    if isinstance(direct_case_id, str):
                        referenced_ids.add(direct_case_id)
                    for key in _CASE_ID_LIST_FIELDS:
                        ids = value.get(key)
                        if isinstance(ids, list):
                            referenced_ids.update(item for item in ids if isinstance(item, str))
                    for key in _CASE_HASH_FIELDS:
                        pairs = value.get(key)
                        if isinstance(pairs, list):
                            referenced_ids.update(
                                item[0]
                                for item in pairs
                                if isinstance(item, list)
                                and len(item) == 2
                                and isinstance(item[0], str)
                            )
                    protected_ids = referenced_ids.intersection(case_by_id)
                    if protected_ids:
                        forbidden = set(value).intersection(_FORBIDDEN_CASE_FIELDS)
                        nested_fields = {
                            key
                            for nested in _walk_json(value)
                            if isinstance(nested, dict)
                            for key in nested
                        }
                        unexpected = nested_fields.difference(_ALLOWED_PROTECTED_METADATA_FIELDS)
                        if forbidden or unexpected:
                            case_id = min(protected_ids, key=lambda item: item.encode("utf-8"))
                            fields = sorted(forbidden or unexpected)
                            raise ValueError(
                                "public protected-split record exposes payload fields for "
                                f"{case_id} in {source}:{path}: {', '.join(fields)}"
                            )
                        _validate_metadata_values(
                            value,
                            protected_ids=protected_ids,
                            case_metadata=case_metadata,
                            case_splits=case_splits,
                            benchmark_manifest_hash=benchmark_manifest_hash,
                        )


def _case_public_metadata(case: BenchmarkCaseV1) -> dict[str, str | None]:
    return {
        "case_payload_hash": case.case_payload_hash,
        "payload_hash": canonical_hash({"question": case.question, "input": case.input}),
        "answer_hash": canonical_hash(case.expected_answer),
        "protected_split": _require_protected_split(case).value,
        "normalized_text_sha256": case.contamination.normalized_text_sha256,
        "exact_shingle_digest": case.contamination.exact_shingle_digest,
        "fuzzy_fingerprint": case.contamination.fuzzy_fingerprint,
        "membership_digest": case.split.membership_digest,
        "split_membership_digest": case.split.membership_digest,
        "split_manifest_hash": case.split.split_manifest_hash,
    }


def _require_protected_split(case: BenchmarkCaseV1) -> SplitName:
    split = case.split.split_name
    if split not in _PROTECTED_SPLITS:
        raise ValueError(f"case is not in a protected split: {case.case_id}")
    return split


def _required_normalized_text_fingerprint(case: BenchmarkCaseV1) -> str:
    fingerprint = case.contamination.normalized_text_sha256
    if fingerprint is None:
        raise ValueError(f"protected case lacks its normalized-text fingerprint: {case.case_id}")
    return fingerprint


def _validate_metadata_values(
    record: dict[str, object],
    *,
    protected_ids: set[str],
    case_metadata: dict[str, dict[str, str | None]],
    case_splits: dict[str, str],
    benchmark_manifest_hash: str | None,
) -> None:
    for nested in _walk_json(record):
        if not isinstance(nested, dict):
            continue
        for key, value in nested.items():
            if key in _DIGEST_METADATA_FIELDS:
                if not isinstance(value, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", value):
                    raise ValueError(
                        f"public protected metadata field {key} must contain a SHA-256 digest"
                    )
                if key == "benchmark_manifest_hash" and benchmark_manifest_hash is not None:
                    if value != benchmark_manifest_hash:
                        raise ValueError(
                            "public protected record has a stale benchmark manifest hash"
                        )
                elif key in {"manifest_hash", "manifest_commitment"}:
                    continue
                elif key in {"payload_fingerprint", "answer_fingerprint"}:
                    expected_fingerprints = {
                        digest
                        for case_id in protected_ids
                        for digest in case_metadata[case_id].values()
                        if digest is not None
                    }
                    if value not in expected_fingerprints:
                        raise ValueError(f"public protected record has an unregistered {key}")
                elif key in case_metadata[next(iter(protected_ids))]:
                    expected_values = {case_metadata[case_id].get(key) for case_id in protected_ids}
                    if value not in expected_values:
                        raise ValueError(f"public protected record has a stale or wrong {key}")
            elif key == "case_id":
                if not isinstance(value, str) or value not in case_metadata:
                    raise ValueError("public protected record has an unknown case ID")
            elif key in _CASE_ID_LIST_FIELDS and isinstance(value, list):
                if any(not isinstance(item, str) or item not in case_metadata for item in value):
                    raise ValueError("public protected record has an unknown protected case ID")
            elif key in _CASE_HASH_FIELDS and isinstance(value, list):
                for pair in value:
                    if not (
                        isinstance(pair, list)
                        and len(pair) == 2
                        and isinstance(pair[0], str)
                        and isinstance(pair[1], str)
                        and pair[0] in case_metadata
                        and pair[1] == case_metadata[pair[0]]["case_payload_hash"]
                    ):
                        raise ValueError("public protected record has a stale or wrong case hash")
            elif key in {"split", "protected_split", "split_name"}:
                expected_splits = {case_splits[case_id] for case_id in protected_ids}
                if isinstance(value, str) and value not in expected_splits:
                    raise ValueError("public protected record has a wrong split label")
                if not isinstance(value, str | dict):
                    raise ValueError("public protected split metadata is malformed")


def _public_structures(data: bytes, path: str) -> Iterator[object]:
    try:
        decoded = data.decode("utf-8")
    except UnicodeDecodeError:
        return
    suffix = PurePosixPath(path).suffix.casefold()
    if suffix in {".csv", ".tsv"}:
        delimiter = "\t" if suffix == ".tsv" else ","
        reader = csv.DictReader(io.StringIO(decoded), delimiter=delimiter)
        yield from reader
        return
    try:
        yield json.loads(decoded)
        return
    except json.JSONDecodeError:
        if suffix not in {".jsonl", ".ndjson"}:
            return
    for line in decoded.splitlines():
        if not line.strip():
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            continue


def _add_pattern(patterns: dict[bytes, str], pattern: bytes, label: str) -> None:
    if pattern:
        patterns.setdefault(pattern, label)


def _walk_json(value: object) -> Iterator[object]:
    yield value
    if isinstance(value, dict):
        for item in value.values():
            yield from _walk_json(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_json(item)


__all__ = [
    "ProtectedPublicCaseCommitmentV1",
    "ProtectedRepositoryLeakGuardV1",
    "QualificationRepositoryLeakGuardV1",
    "public_protected_case_commitments",
    "validate_protected_repository_boundary",
    "validate_qualification_repository_boundary",
]
