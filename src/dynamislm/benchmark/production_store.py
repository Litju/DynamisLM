"""External-only storage for real PSE-V1 production candidates."""

from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath

from dynamislm.benchmark.pre_review import CandidateReviewPacket
from dynamislm.benchmark.production import (
    PRODUCTION_BATCH_ID,
    ProductionAuthoringPlanV1,
    ProductionCandidateStoreReceiptV1,
    bind_production_candidate_store_receipt,
    production_candidate_store_receipt_digest,
    validate_production_authoring_plan,
    validate_production_candidate_set,
    validate_production_candidate_store_receipt,
)
from dynamislm.benchmark.production_exclusions import (
    QualificationExclusionCommitmentV1,
    validate_production_candidate_set_against_qualification_exclusion,
    validate_qualification_exclusion_commitment,
)
from dynamislm.benchmark.qualification_store import (
    _atomic_write_bytes,
    _external_input_path,
    _external_output_path,
    _safe_external_root,
)
from dynamislm.benchmark.source_artifacts import SourceArtifactResolver
from dynamislm.serialization import canonical_hash, canonical_json, from_canonical_json

DEFAULT_PRODUCTION_ROOT = Path("/mnt/e/Data/Datasets/DynamisLM/PerformanceScienceEval")


def _batch_key(batch_id: str) -> str:
    return hashlib.sha256(batch_id.encode("utf-8")).hexdigest()[:24]


def _candidate_filename(candidate_id: str) -> str:
    return hashlib.sha256(candidate_id.encode("utf-8")).hexdigest() + ".json"


def _safe_relative_path(relative_path: str) -> PurePosixPath:
    relative = PurePosixPath(relative_path)
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or not relative.parts
        or relative.parts[0] != "production"
        or relative.suffix != ".json"
    ):
        raise ValueError("production JSON must remain under production/ as a safe .json path")
    return relative


def write_external_production_json(
    value: object,
    relative_path: str,
    *,
    repository_root: str | Path,
    production_root: str | Path = DEFAULT_PRODUCTION_ROOT,
) -> tuple[str, str, int]:
    relative = _safe_relative_path(relative_path)
    root, _repo = _safe_external_root(Path(production_root), Path(repository_root))
    path = _external_output_path(root, relative)
    payload = (canonical_json(value) + "\n").encode("utf-8")
    _atomic_write_bytes(path, payload)
    digest = "sha256:" + hashlib.sha256(payload).hexdigest()
    return relative.as_posix(), digest, len(payload)


def read_external_production_json[T](
    relative_path: str,
    expected_type: type[T],
    *,
    repository_root: str | Path,
    production_root: str | Path = DEFAULT_PRODUCTION_ROOT,
) -> tuple[T, str, int]:
    relative = _safe_relative_path(relative_path)
    root, _repo = _safe_external_root(Path(production_root), Path(repository_root))
    path = _external_input_path(root, relative)
    try:
        payload = path.read_bytes()
        decoded = payload.decode("utf-8")
        value = from_canonical_json(decoded.rstrip("\n"), expected_type)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise ValueError("external production JSON is unavailable or invalid") from exc
    if canonical_json(value) + "\n" != decoded:
        raise ValueError("external production JSON is not canonical")
    digest = "sha256:" + hashlib.sha256(payload).hexdigest()
    return value, digest, len(payload)


def write_production_candidate_store(
    packets: tuple[CandidateReviewPacket, ...],
    plan: ProductionAuthoringPlanV1,
    *,
    repository_root: str | Path,
    production_root: str | Path = DEFAULT_PRODUCTION_ROOT,
    source_resolver: SourceArtifactResolver | None = None,
    qualification_exclusions: QualificationExclusionCommitmentV1,
) -> ProductionCandidateStoreReceiptV1:
    """Persist one exactly 434-packet batch outside Git using immutable bytes."""

    validate_production_authoring_plan(plan)
    validate_qualification_exclusion_commitment(qualification_exclusions)
    if plan.qualification_exclusion_digest != qualification_exclusions.commitment_digest:
        raise ValueError("production plan is not bound to the sealed qualification exclusion")
    validate_production_candidate_set_against_qualification_exclusion(
        packets,
        qualification_exclusions,
        source_resolver=source_resolver,
    )
    commitments = validate_production_candidate_set(packets, source_resolver=source_resolver)
    by_id = {item.candidate_id: item for item in commitments}
    if tuple(item.candidate_id for item in plan.items) != tuple(sorted(by_id)):
        raise ValueError("production plan and candidate packets have different candidate IDs")
    if any(item != by_id[item.candidate_id].item for item in plan.items):
        raise ValueError("production plan metadata differs from candidate packet commitments")

    root, repo = _safe_external_root(Path(production_root), Path(repository_root))
    key = _batch_key(PRODUCTION_BATCH_ID)
    plan_relative = PurePosixPath("production/authoring_plan") / f"{key}.json"
    candidate_relative = PurePosixPath("production/candidates") / key
    receipt_relative = PurePosixPath("production/receipts") / f"{key}.json"
    plan_path = _external_output_path(root, plan_relative)
    candidate_directory = root / Path(*candidate_relative.parts)
    candidate_directory.mkdir(parents=True, exist_ok=True)
    if not candidate_directory.resolve().is_relative_to(root) or candidate_directory.is_symlink():
        raise ValueError("production candidate directory escapes its external root")

    plan_bytes = (canonical_json(plan) + "\n").encode("utf-8")
    _atomic_write_bytes(plan_path, plan_bytes)
    inventory: list[tuple[str, str, int]] = [
        (
            plan_relative.as_posix(),
            "sha256:" + hashlib.sha256(plan_bytes).hexdigest(),
            len(plan_bytes),
        )
    ]
    packet_digests: list[tuple[str, str]] = []
    total_bytes = len(plan_bytes)
    for packet in sorted(packets, key=lambda item: item.candidate_id.encode("utf-8")):
        packet_bytes = (canonical_json(packet) + "\n").encode("utf-8")
        relative = candidate_relative / _candidate_filename(packet.candidate_id)
        packet_path = _external_output_path(root, relative)
        _atomic_write_bytes(packet_path, packet_bytes)
        digest = "sha256:" + hashlib.sha256(packet_bytes).hexdigest()
        packet_digests.append((packet.candidate_id, digest))
        inventory.append((relative.as_posix(), digest, len(packet_bytes)))
        total_bytes += len(packet_bytes)
    provisional = ProductionCandidateStoreReceiptV1(
        batch_id=PRODUCTION_BATCH_ID,
        store_relative_path=candidate_relative.as_posix(),
        candidate_file_digests=tuple(packet_digests),
        candidate_count=len(packets),
        total_bytes=total_bytes,
        authoring_plan_digest=plan.plan_digest,
        artifact_inventory_digest=canonical_hash(tuple(sorted(inventory))),
        receipt_digest="sha256:" + "0" * 64,
    )
    receipt = bind_production_candidate_store_receipt(provisional)
    receipt_bytes = (canonical_json(receipt) + "\n").encode("utf-8")
    _atomic_write_bytes(_external_output_path(root, receipt_relative), receipt_bytes)
    validate_production_candidate_store_receipt(receipt)
    restored, _digest, _size = read_external_production_json(
        receipt_relative.as_posix(),
        ProductionCandidateStoreReceiptV1,
        repository_root=repo,
        production_root=root,
    )
    if (
        restored != receipt
        or production_candidate_store_receipt_digest(restored) != receipt.receipt_digest
    ):
        raise ValueError("production candidate store receipt round trip failed")
    if read_production_candidate_store(
        receipt,
        repository_root=repo,
        production_root=root,
        source_resolver=source_resolver,
        qualification_exclusions=qualification_exclusions,
    ) != tuple(sorted(packets, key=lambda item: item.candidate_id.encode("utf-8"))):
        raise ValueError("external production candidate store round trip failed")
    return receipt


def read_production_candidate_store(
    receipt: ProductionCandidateStoreReceiptV1,
    *,
    repository_root: str | Path,
    production_root: str | Path = DEFAULT_PRODUCTION_ROOT,
    source_resolver: SourceArtifactResolver | None = None,
    qualification_exclusions: QualificationExclusionCommitmentV1,
) -> tuple[CandidateReviewPacket, ...]:
    validate_production_candidate_store_receipt(receipt)
    validate_qualification_exclusion_commitment(qualification_exclusions)
    root, _repo = _safe_external_root(Path(production_root), Path(repository_root))
    relative = PurePosixPath(receipt.store_relative_path)
    directory = _external_input_path(root, relative)
    plan_relative = f"production/authoring_plan/{_batch_key(receipt.batch_id)}.json"
    plan, plan_file_digest, plan_bytes = read_external_production_json(
        plan_relative,
        ProductionAuthoringPlanV1,
        repository_root=repository_root,
        production_root=root,
    )
    validate_production_authoring_plan(plan)
    if plan.plan_digest != receipt.authoring_plan_digest:
        raise ValueError("production candidate store is bound to a different authoring plan")
    if plan.qualification_exclusion_digest != qualification_exclusions.commitment_digest:
        raise ValueError("production plan is not bound to the sealed qualification exclusion")
    inventory: list[tuple[str, str, int]] = [(plan_relative, plan_file_digest, plan_bytes)]
    packets: list[CandidateReviewPacket] = []
    for candidate_id, expected_digest in receipt.candidate_file_digests:
        packet_relative = relative / _candidate_filename(candidate_id)
        path = _external_input_path(root, packet_relative)
        try:
            payload = path.read_bytes()
        except OSError as exc:
            raise ValueError("external production candidate is unavailable") from exc
        actual_digest = "sha256:" + hashlib.sha256(payload).hexdigest()
        if actual_digest != expected_digest:
            raise ValueError("external production candidate file digest mismatch")
        try:
            decoded = payload.decode("utf-8")
            packet = from_canonical_json(decoded.rstrip("\n"), CandidateReviewPacket)
        except (UnicodeDecodeError, ValueError) as exc:
            raise ValueError("external production candidate is not canonical typed JSON") from exc
        if canonical_json(packet) + "\n" != decoded or packet.candidate_id != candidate_id:
            raise ValueError("external production packet bytes differ from the receipt identity")
        packets.append(packet)
        inventory.append((packet_relative.as_posix(), actual_digest, len(payload)))
    restored = tuple(packets)
    validate_production_candidate_set_against_qualification_exclusion(
        restored,
        qualification_exclusions,
        source_resolver=source_resolver,
    )
    commitments = validate_production_candidate_set(restored, source_resolver=source_resolver)
    if tuple(item.item for item in commitments) != plan.items:
        raise ValueError("external production plan differs from candidate packet metadata")
    if (
        sum(size for _path, _digest, size in inventory) != receipt.total_bytes
        or canonical_hash(tuple(sorted(inventory))) != receipt.artifact_inventory_digest
        or directory.is_symlink()
    ):
        raise ValueError("production candidate store inventory differs from its receipt")
    return restored


__all__ = [
    "DEFAULT_PRODUCTION_ROOT",
    "read_external_production_json",
    "read_production_candidate_store",
    "write_external_production_json",
    "write_production_candidate_store",
]
