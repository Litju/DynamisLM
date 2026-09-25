"""Atomic external storage for protected RES-115 qualification material."""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path, PurePosixPath

from dynamislm.benchmark.authoring import (
    AuthoringPlanV1,
    CandidateStoreReceiptV1,
    bind_candidate_store_receipt,
    candidate_store_receipt_digest,
    validate_authoring_plan,
    validate_candidate_store_receipt,
)
from dynamislm.benchmark.pre_review import (
    CandidateReviewPacket,
    candidate_payload_hash,
)
from dynamislm.serialization import canonical_hash, canonical_json, from_canonical_json

DEFAULT_QUALIFICATION_ROOT = Path("/mnt/e/Data/Datasets/DynamisLM/PerformanceScienceEval")


def _sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _batch_key(batch_id: str) -> str:
    return hashlib.sha256(batch_id.encode("utf-8")).hexdigest()[:24]


def _candidate_filename(candidate_id: str) -> str:
    return hashlib.sha256(candidate_id.encode("utf-8")).hexdigest() + ".json"


def _safe_external_root(root: Path, repository_root: Path) -> tuple[Path, Path]:
    resolved_root = root.resolve()
    resolved_repository = repository_root.resolve()
    if resolved_root.is_relative_to(resolved_repository):
        raise ValueError("qualification packet store must be outside the public Git repository")
    return resolved_root, resolved_repository


def _external_output_path(root: Path, relative: PurePosixPath) -> Path:
    path = root / Path(*relative.parts)
    path.parent.mkdir(parents=True, exist_ok=True)
    resolved_parent = path.parent.resolve()
    if not resolved_parent.is_relative_to(root) or path.is_symlink():
        raise ValueError("external qualification path escapes its canonical root")
    return resolved_parent / path.name


def _external_output_directory(root: Path, relative: PurePosixPath) -> Path:
    path = root / Path(*relative.parts)
    path.mkdir(parents=True, exist_ok=True)
    resolved = path.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError("external qualification directory escapes its canonical root")
    return resolved


def _external_input_path(root: Path, relative: PurePosixPath) -> Path:
    path = root / Path(*relative.parts)
    if path.is_symlink():
        raise ValueError("external qualification artifacts cannot be symlinks")
    resolved = path.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError("external qualification path escapes its canonical root")
    return resolved


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError("external qualification artifact cannot be a symlink")
    if path.exists():
        if not path.is_file() or path.read_bytes() != data:
            raise ValueError(
                f"external qualification artifact already exists with different bytes: {path}"
            )
        return
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(data)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def _write_receipt_bytes(path: Path, receipt: CandidateStoreReceiptV1) -> None:
    _atomic_write_bytes(path, (canonical_json(receipt) + "\n").encode("utf-8"))


def write_external_qualification_json(
    value: object,
    relative_path: str,
    *,
    repository_root: str | Path,
    qualification_root: str | Path = DEFAULT_QUALIFICATION_ROOT,
) -> tuple[str, str, int]:
    """Atomically write one canonical external receipt/manifest under qualification/."""

    relative = PurePosixPath(relative_path)
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        raise ValueError("external qualification artifact path is not a safe relative path")
    if relative.parts[0] != "qualification" or relative.suffix != ".json":
        raise ValueError("external qualification JSON must remain under qualification/ as .json")
    root, _ = _safe_external_root(Path(qualification_root), Path(repository_root))
    path = _external_output_path(root, relative)
    payload = (canonical_json(value) + "\n").encode("utf-8")
    _atomic_write_bytes(path, payload)
    return relative.as_posix(), _sha256(payload), len(payload)


def read_external_qualification_json[T](
    relative_path: str,
    expected_type: type[T],
    *,
    repository_root: str | Path,
    qualification_root: str | Path = DEFAULT_QUALIFICATION_ROOT,
) -> tuple[T, str, int]:
    """Read and verify one canonical typed JSON artifact outside Git."""

    relative = PurePosixPath(relative_path)
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        raise ValueError("external qualification artifact path is not a safe relative path")
    if relative.parts[0] != "qualification" or relative.suffix != ".json":
        raise ValueError("external qualification JSON must remain under qualification/ as .json")
    root, _ = _safe_external_root(Path(qualification_root), Path(repository_root))
    path = _external_input_path(root, relative)
    if not path.is_file():
        raise ValueError("external qualification JSON is unavailable or escapes its root")
    payload = path.read_bytes()
    try:
        decoded = payload.decode("utf-8")
        value = from_canonical_json(decoded.rstrip("\n"), expected_type)
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValueError("external qualification JSON is not valid canonical typed data") from exc
    if canonical_json(value) + "\n" != decoded:
        raise ValueError("external qualification JSON is not canonical")
    return value, _sha256(payload), len(payload)


def write_qualification_store(
    packets: tuple[CandidateReviewPacket, ...],
    plan: AuthoringPlanV1,
    *,
    batch_id: str,
    repository_root: str | Path,
    qualification_root: str | Path = DEFAULT_QUALIFICATION_ROOT,
    require_all_cells: bool = True,
) -> CandidateStoreReceiptV1:
    """Write a canonical plan and exact packets atomically outside Git.

    The receipt stores only candidate IDs and file digests. The plan and exact
    packet payloads stay under the external ``qualification/`` namespace.
    """

    validate_authoring_plan(plan, require_all_cells=require_all_cells)
    if not batch_id.startswith("PSE-V1-QUALIFICATION/"):
        raise ValueError("candidate-store batch ID must use the qualification namespace")
    if not packets:
        raise ValueError("qualification candidate store must be non-empty")
    packet_by_id = {packet.candidate_id: packet for packet in packets}
    plan_by_id = {item.candidate_id: item for item in plan.items}
    if len(packet_by_id) != len(packets) or set(packet_by_id) != set(plan_by_id):
        raise ValueError("authoring plan and external candidate packets must have identical IDs")
    for candidate_id, packet in packet_by_id.items():
        if packet.candidate_payload_hash != plan_by_id[candidate_id].candidate_payload_hash:
            raise ValueError("candidate-store packet hash differs from authoring plan")
        if candidate_payload_hash(packet) != packet.candidate_payload_hash:
            raise ValueError("candidate-store packet payload hash is invalid")

    root, repo = _safe_external_root(Path(qualification_root), Path(repository_root))
    key = _batch_key(batch_id)
    plan_path = _external_output_path(
        root,
        PurePosixPath("qualification") / "authoring_plan" / f"{key}.json",
    )
    candidate_directory = _external_output_directory(
        root,
        PurePosixPath("qualification") / "candidates" / key,
    )
    receipt_path = _external_output_path(
        root,
        PurePosixPath("qualification") / "receipts" / f"{key}.json",
    )

    plan_bytes = (canonical_json(plan) + "\n").encode("utf-8")
    _atomic_write_bytes(plan_path, plan_bytes)
    candidate_file_digests: list[tuple[str, str]] = []
    inventory: list[tuple[str, str, int]] = [
        (plan_path.relative_to(root).as_posix(), _sha256(plan_bytes), len(plan_bytes))
    ]
    total_bytes = len(plan_bytes)
    for candidate_id in sorted(packet_by_id, key=lambda value: value.encode("utf-8")):
        packet = packet_by_id[candidate_id]
        packet_bytes = (canonical_json(packet) + "\n").encode("utf-8")
        packet_path = _external_output_path(
            root,
            PurePosixPath("qualification") / "candidates" / key / _candidate_filename(candidate_id),
        )
        _atomic_write_bytes(packet_path, packet_bytes)
        packet_digest = _sha256(packet_bytes)
        candidate_file_digests.append((candidate_id, packet_digest))
        inventory.append(
            (packet_path.relative_to(root).as_posix(), packet_digest, len(packet_bytes))
        )
        total_bytes += len(packet_bytes)

    inventory_digest = canonical_hash(
        tuple(
            sorted(
                inventory,
                key=lambda item: item[0].encode("utf-8"),
            )
        )
    )
    provisional = CandidateStoreReceiptV1(
        batch_id=batch_id,
        store_relative_path=candidate_directory.relative_to(root).as_posix(),
        candidate_file_digests=tuple(candidate_file_digests),
        candidate_count=len(packet_by_id),
        total_bytes=total_bytes,
        authoring_plan_digest=plan.plan_digest,
        artifact_inventory_digest=inventory_digest,
        receipt_digest="sha256:" + "0" * 64,
    )
    receipt = bind_candidate_store_receipt(provisional)
    _write_receipt_bytes(receipt_path, receipt)

    stored_plan = _read_plan(plan_path)
    stored_packets = read_qualification_store(
        receipt,
        repository_root=repo,
        qualification_root=root,
    )
    if stored_plan != plan or stored_packets != tuple(
        packet_by_id[key] for key in sorted(packet_by_id, key=lambda value: value.encode("utf-8"))
    ):
        raise ValueError("external qualification store round trip changed canonical contents")
    validate_candidate_store_receipt(receipt)
    stored_receipt = _read_receipt(receipt_path)
    if (
        stored_receipt != receipt
        or candidate_store_receipt_digest(stored_receipt) != receipt.receipt_digest
    ):
        raise ValueError("external candidate-store receipt round trip failed")
    return receipt


def _read_plan(path: Path) -> AuthoringPlanV1:
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise ValueError("external authoring plan is unavailable") from exc
    plan = from_canonical_json(payload.decode("utf-8").rstrip("\n"), AuthoringPlanV1)
    if canonical_json(plan) + "\n" != payload.decode("utf-8"):
        raise ValueError("external authoring plan is not canonical JSON")
    return plan


def _read_receipt(path: Path) -> CandidateStoreReceiptV1:
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise ValueError("external candidate-store receipt is unavailable") from exc
    receipt = from_canonical_json(payload.decode("utf-8").rstrip("\n"), CandidateStoreReceiptV1)
    if canonical_json(receipt) + "\n" != payload.decode("utf-8"):
        raise ValueError("external candidate-store receipt is not canonical JSON")
    return receipt


def read_qualification_store(
    receipt: CandidateStoreReceiptV1,
    *,
    repository_root: str | Path,
    qualification_root: str | Path = DEFAULT_QUALIFICATION_ROOT,
) -> tuple[CandidateReviewPacket, ...]:
    """Read exact packet bytes and verify every external receipt commitment."""

    validate_candidate_store_receipt(receipt)
    root, _ = _safe_external_root(Path(qualification_root), Path(repository_root))
    relative = PurePosixPath(receipt.store_relative_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("candidate-store receipt path escapes qualification storage")
    packet_directory = _external_input_path(root, relative)
    if not packet_directory.is_dir():
        raise ValueError("candidate-store packet directory is unavailable or escapes its root")
    entries = dict(receipt.candidate_file_digests)
    packets: list[CandidateReviewPacket] = []
    for candidate_id in sorted(entries, key=lambda value: value.encode("utf-8")):
        packet_path = _external_input_path(
            root,
            relative / _candidate_filename(candidate_id),
        )
        try:
            packet_bytes = packet_path.read_bytes()
        except OSError as exc:
            raise ValueError("external candidate packet is unavailable") from exc
        if _sha256(packet_bytes) != entries[candidate_id]:
            raise ValueError("external candidate packet file digest mismatch")
        try:
            packet_text = packet_bytes.decode("utf-8").rstrip("\n")
        except UnicodeDecodeError as exc:
            raise ValueError("external candidate packet is not UTF-8") from exc
        packet = from_canonical_json(packet_text, CandidateReviewPacket)
        if canonical_json(packet) + "\n" != packet_bytes.decode("utf-8"):
            raise ValueError("external candidate packet is not canonical JSON")
        if packet.candidate_id != candidate_id:
            raise ValueError("external packet filename commitment identifies a different candidate")
        if candidate_payload_hash(packet) != packet.candidate_payload_hash:
            raise ValueError("external candidate packet payload hash mismatch")
        packets.append(packet)
    return tuple(packets)


__all__ = [
    "DEFAULT_QUALIFICATION_ROOT",
    "read_external_qualification_json",
    "read_qualification_store",
    "write_external_qualification_json",
    "write_qualification_store",
]
