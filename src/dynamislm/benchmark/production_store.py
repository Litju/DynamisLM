"""External-only storage for real PSE-V1 production candidates."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import tempfile
from dataclasses import dataclass, fields, replace
from pathlib import Path, PurePosixPath

from dynamislm.benchmark.pre_review import CandidateReviewPacket
from dynamislm.benchmark.production import (
    PRODUCTION_BATCH_ID,
    ProductionAuthoringPlanV1,
    ProductionCandidateStoreReceiptV1,
    audit_production_duplicates,
    bind_production_candidate_store_receipt,
    production_candidate_store_receipt_digest,
    validate_production_authoring_plan,
    validate_production_candidate_set,
    validate_production_candidate_store_receipt,
    validate_production_exact_feasibility,
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
from dynamislm.serialization import (
    canonical_hash,
    canonical_json,
    from_canonical_json,
    register_serializable_type,
)

DEFAULT_PRODUCTION_ROOT = Path("/mnt/e/Data/Datasets/DynamisLM/PerformanceScienceEval")


def _batch_key(batch_id: str) -> str:
    return hashlib.sha256(batch_id.encode("utf-8")).hexdigest()[:24]


def _candidate_filename(candidate_id: str) -> str:
    return hashlib.sha256(candidate_id.encode("utf-8")).hexdigest() + ".json"


@register_serializable_type
@dataclass(frozen=True, slots=True)
class _ProductionStagingBindingV1:
    batch_id: str
    authoring_plan_digest: str
    qualification_exclusion_digest: str
    plan_file_digest: str
    packet_input_digest: str
    candidate_file_digests: tuple[tuple[str, str], ...]
    candidate_count: int
    binding_digest: str

    def __post_init__(self) -> None:
        if self.batch_id != PRODUCTION_BATCH_ID or self.candidate_count != 434:
            raise ValueError("production staging binding has the wrong batch/count")
        for name in (
            "authoring_plan_digest",
            "qualification_exclusion_digest",
            "plan_file_digest",
            "packet_input_digest",
            "binding_digest",
        ):
            if re.fullmatch(r"sha256:[0-9a-f]{64}", getattr(self, name)) is None:
                raise ValueError(f"staging {name} must be a SHA-256 digest")
        ids = tuple(candidate_id for candidate_id, _digest in self.candidate_file_digests)
        if len(ids) != 434 or ids != tuple(sorted(set(ids))):
            raise ValueError("production staging binding must list 434 ordered candidates")
        if any(
            re.fullmatch(r"sha256:[0-9a-f]{64}", digest) is None
            for _candidate_id, digest in self.candidate_file_digests
        ):
            raise ValueError("staged candidate file digest is malformed")


def _staging_binding_digest(binding: _ProductionStagingBindingV1) -> str:
    return canonical_hash(
        {
            item.name: getattr(binding, item.name)
            for item in fields(binding)
            if item.name != "binding_digest"
        }
    )


def _sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _fsync_directory(path: Path) -> None:
    directory_fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


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


def replace_external_production_json(
    value: object,
    relative_path: str,
    *,
    expected_digest: str,
    repository_root: str | Path,
    production_root: str | Path = DEFAULT_PRODUCTION_ROOT,
) -> tuple[str, str, int]:
    """Atomically replace one external JSON file only when its preimage is unchanged."""

    relative = _safe_relative_path(relative_path)
    root, _repo = _safe_external_root(Path(production_root), Path(repository_root))
    path = _external_output_path(root, relative)
    if path.is_symlink() or not path.is_file():
        raise ValueError("external production replacement target is not a regular file")
    before = path.read_bytes()
    before_digest = "sha256:" + hashlib.sha256(before).hexdigest()
    if before_digest != expected_digest:
        raise ValueError("external production replacement preimage digest mismatch")
    payload = (canonical_json(value) + "\n").encode("utf-8")
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(payload)
            temporary.flush()
            os.fsync(temporary.fileno())
        if path.is_symlink() or hashlib.sha256(
            path.read_bytes()
        ).hexdigest() != before_digest.removeprefix("sha256:"):
            raise ValueError("external production replacement target changed during update")
        os.replace(temporary_path, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()
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
    """Stage, validate, then atomically promote the exact immutable candidate directory."""

    validate_production_authoring_plan(plan)
    validate_qualification_exclusion_commitment(qualification_exclusions)
    if plan.qualification_exclusion_digest != qualification_exclusions.commitment_digest:
        raise ValueError("production plan is not bound to the sealed qualification exclusion")
    validate_production_candidate_set_against_qualification_exclusion(
        packets,
        qualification_exclusions,
        source_resolver=source_resolver,
    )
    commitments = validate_production_candidate_set(
        packets,
        source_resolver=source_resolver,
        defer_split_lock_conflicts=True,
        enforce_public_capacity=False,
    )
    duplication = audit_production_duplicates(packets)
    exact_feasibility = validate_production_exact_feasibility(
        commitments,
        exact_shingle_colocation_pairs=duplication.exact_shingle_colocation_pairs,
    ).receipt
    if exact_feasibility.status != "FEASIBLE":
        raise ValueError(f"exact production feasibility is {exact_feasibility.status}")
    write_external_production_json(
        exact_feasibility,
        f"production/receipts/{_batch_key(PRODUCTION_BATCH_ID)}-exact-feasibility-v2.json",
        repository_root=repository_root,
        production_root=production_root,
    )
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
    staging_relative = PurePosixPath("production/staging") / key
    stage_directory = root / Path(*staging_relative.parts)
    staged_candidates = stage_directory / "candidates" / key
    final_candidates = root / Path(*candidate_relative.parts)
    plan_bytes = (canonical_json(plan) + "\n").encode("utf-8")
    ordered_packets = tuple(sorted(packets, key=lambda item: item.candidate_id.encode("utf-8")))
    packet_records = tuple(
        (
            packet,
            (canonical_json(packet) + "\n").encode("utf-8"),
        )
        for packet in ordered_packets
    )
    candidate_file_digests = tuple(
        (packet.candidate_id, _sha256(packet_bytes)) for packet, packet_bytes in packet_records
    )
    plan_path = _external_output_path(root, plan_relative)
    receipt_path = _external_output_path(root, receipt_relative)
    if plan_path.exists() and plan_path.read_bytes() != plan_bytes:
        raise ValueError("conflicting production authoring plan bytes")
    if receipt_path.exists():
        persisted_receipt, _digest, _size = read_external_production_json(
            receipt_relative.as_posix(),
            ProductionCandidateStoreReceiptV1,
            repository_root=repo,
            production_root=root,
        )
        if (
            persisted_receipt.store_relative_path != candidate_relative.as_posix()
            or persisted_receipt.authoring_plan_digest != plan.plan_digest
            or persisted_receipt.candidate_file_digests != candidate_file_digests
        ):
            raise ValueError("completed production batch conflicts with the exact rerun")
        restored = read_production_candidate_store(
            persisted_receipt,
            repository_root=repo,
            production_root=root,
            source_resolver=source_resolver,
            qualification_exclusions=qualification_exclusions,
        )
        if restored != ordered_packets:
            raise ValueError("completed production store differs from the exact rerun")
        if stage_directory.exists():
            if stage_directory.is_symlink():
                raise ValueError("production staging directory cannot be a symlink")
            shutil.rmtree(stage_directory)
            _fsync_directory(stage_directory.parent)
        return persisted_receipt
    provisional_binding = _ProductionStagingBindingV1(
        batch_id=PRODUCTION_BATCH_ID,
        authoring_plan_digest=plan.plan_digest,
        qualification_exclusion_digest=qualification_exclusions.commitment_digest,
        plan_file_digest=_sha256(plan_bytes),
        packet_input_digest=canonical_hash(
            tuple(
                (packet.candidate_id, packet.candidate_payload_hash) for packet in ordered_packets
            )
        ),
        candidate_file_digests=candidate_file_digests,
        candidate_count=len(ordered_packets),
        binding_digest="sha256:" + "0" * 64,
    )
    binding = replace(
        provisional_binding,
        binding_digest=_staging_binding_digest(provisional_binding),
    )
    binding_relative = staging_relative / "binding.json"
    binding_path = _external_output_path(root, binding_relative)
    if stage_directory.is_symlink():
        raise ValueError("production staging directory cannot be a symlink")
    if stage_directory.exists() and not binding_path.exists():
        if any(path.is_file() or path.is_symlink() for path in stage_directory.rglob("*")):
            raise ValueError("unbound production staging bytes cannot be resumed safely")
        shutil.rmtree(stage_directory)
    _atomic_write_bytes(binding_path, (canonical_json(binding) + "\n").encode("utf-8"))
    persisted_binding, _binding_file_digest, _binding_size = read_external_production_json(
        binding_relative.as_posix(),
        _ProductionStagingBindingV1,
        repository_root=repo,
        production_root=root,
    )
    if persisted_binding != binding or binding.binding_digest != _staging_binding_digest(binding):
        raise ValueError("conflicting production staging plan or packet inputs")

    staged_plan_path = _external_output_path(root, staging_relative / "authoring-plan.json")
    _atomic_write_bytes(staged_plan_path, plan_bytes)
    staged_candidates.mkdir(parents=True, exist_ok=True)
    if staged_candidates.is_symlink() or not staged_candidates.resolve().is_relative_to(root):
        raise ValueError("production staging candidate directory escapes its external root")
    for packet, packet_bytes in packet_records:
        staged_path = _external_output_path(
            root,
            staging_relative / "candidates" / key / _candidate_filename(packet.candidate_id),
        )
        _atomic_write_bytes(staged_path, packet_bytes)
    staged_candidates = root / Path(*staging_relative.parts) / "candidates" / key
    expected_names = {_candidate_filename(packet.candidate_id) for packet in ordered_packets}
    if (
        staged_candidates.is_symlink()
        or {path.name for path in staged_candidates.iterdir()} != expected_names
    ):
        raise ValueError("production staging does not contain exactly the bound 434 packet files")
    for packet, packet_bytes in packet_records:
        staged_path = staged_candidates / _candidate_filename(packet.candidate_id)
        if staged_path.is_symlink() or staged_path.read_bytes() != packet_bytes:
            raise ValueError("conflicting production staging packet bytes")

    if final_candidates.exists():
        if final_candidates.is_symlink() or not final_candidates.is_dir():
            raise ValueError("production candidate destination is not a safe directory")
        if {path.name for path in final_candidates.iterdir()} != expected_names:
            raise ValueError("promoted production candidate directory is incomplete or conflicting")
        for packet, packet_bytes in packet_records:
            final_path = final_candidates / _candidate_filename(packet.candidate_id)
            if (
                final_path.is_symlink()
                or not final_path.is_file()
                or final_path.read_bytes() != packet_bytes
            ):
                raise ValueError("promoted production bytes differ from the exact rerun")
    else:
        final_candidates.parent.mkdir(parents=True, exist_ok=True)
        if not final_candidates.parent.resolve().is_relative_to(root):
            raise ValueError("production candidate directory escapes its external root")
        os.replace(staged_candidates, final_candidates)
        _fsync_directory(final_candidates.parent)

    _atomic_write_bytes(plan_path, plan_bytes)
    inventory: list[tuple[str, str, int]] = [
        (plan_relative.as_posix(), _sha256(plan_bytes), len(plan_bytes))
    ]
    total_bytes = len(plan_bytes)
    for packet, packet_bytes in packet_records:
        relative = candidate_relative / _candidate_filename(packet.candidate_id)
        digest = _sha256(packet_bytes)
        inventory.append((relative.as_posix(), digest, len(packet_bytes)))
        total_bytes += len(packet_bytes)
    provisional = ProductionCandidateStoreReceiptV1(
        batch_id=PRODUCTION_BATCH_ID,
        store_relative_path=candidate_relative.as_posix(),
        candidate_file_digests=candidate_file_digests,
        candidate_count=len(packets),
        total_bytes=total_bytes,
        authoring_plan_digest=plan.plan_digest,
        artifact_inventory_digest=canonical_hash(tuple(sorted(inventory))),
        receipt_digest="sha256:" + "0" * 64,
    )
    receipt = bind_production_candidate_store_receipt(provisional)
    validate_production_candidate_store_receipt(receipt)
    restored = read_production_candidate_store(
        receipt,
        repository_root=repo,
        production_root=root,
        source_resolver=source_resolver,
        qualification_exclusions=qualification_exclusions,
    )
    if restored != ordered_packets:
        raise ValueError("promoted production candidate directory failed its round trip")
    _atomic_write_bytes(receipt_path, (canonical_json(receipt) + "\n").encode("utf-8"))
    persisted_receipt, _receipt_file_digest, _receipt_size = read_external_production_json(
        receipt_relative.as_posix(),
        ProductionCandidateStoreReceiptV1,
        repository_root=repo,
        production_root=root,
    )
    if (
        persisted_receipt != receipt
        or production_candidate_store_receipt_digest(persisted_receipt) != receipt.receipt_digest
    ):
        raise ValueError("production candidate store receipt round trip failed")
    if (
        read_production_candidate_store(
            persisted_receipt,
            repository_root=repo,
            production_root=root,
            source_resolver=source_resolver,
            qualification_exclusions=qualification_exclusions,
        )
        != ordered_packets
    ):
        raise ValueError("external production candidate store round trip failed")
    if stage_directory.exists():
        shutil.rmtree(stage_directory)
        _fsync_directory(stage_directory.parent)
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
    key = _batch_key(PRODUCTION_BATCH_ID)
    expected_relative = PurePosixPath("production/candidates") / key
    if relative != expected_relative:
        raise ValueError("production candidate store path differs from the immutable batch key")
    directory = _external_input_path(root, relative)
    expected_names = {
        _candidate_filename(candidate_id)
        for candidate_id, _digest in receipt.candidate_file_digests
    }
    if (
        not directory.is_dir()
        or directory.is_symlink()
        or {path.name for path in directory.iterdir()} != expected_names
        or any(path.is_symlink() or not path.is_file() for path in directory.iterdir())
    ):
        raise ValueError(
            "production candidate directory does not contain exactly the receipt files"
        )
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
    commitments = validate_production_candidate_set(
        restored,
        source_resolver=source_resolver,
        defer_split_lock_conflicts=True,
        enforce_public_capacity=False,
    )
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
