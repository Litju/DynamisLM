"""Immutable external storage for the variable pre-review candidate pool."""

from __future__ import annotations

import hashlib
import os
import re
from collections import Counter
from dataclasses import dataclass, fields, replace
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import TypeVar

from dynamislm.benchmark.authority_supply import (
    HISTORICAL_RECIPE_INPUT_BINDING,
    AuthoritySupplyInventoryV1,
    require_current_execution_supply_inventory,
)
from dynamislm.benchmark.constants import CaseOrigin
from dynamislm.benchmark.pre_review import CandidateReviewPacket, candidate_payload_hash
from dynamislm.benchmark.production import PRODUCTION_CANDIDATE_ID_PREFIX
from dynamislm.benchmark.production_exclusions import (
    QualificationExclusionCommitmentV1,
    validate_qualification_exclusion_commitment,
)
from dynamislm.benchmark.production_store import DEFAULT_PRODUCTION_ROOT
from dynamislm.benchmark.qualification_store import (
    _atomic_write_bytes,
    _external_input_path,
    _external_output_path,
    _safe_external_root,
)
from dynamislm.benchmark.source_artifacts import SourceArtifactResolver
from dynamislm.benchmark.variable_pool import (
    ProductionAuthoringCandidatePoolV1,
    RecipeAuthorityBasis,
    VariablePoolAuthoringPlanV1,
    production_authoring_candidate_pool_digest,
    validate_variable_pre_review_pool,
    variable_pool_authoring_plan_digest,
)
from dynamislm.serialization import (
    canonical_hash,
    canonical_json,
    from_canonical_json,
    register_serializable_type,
)

DYNAMISLM_EXECUTION_BASELINE = "5b493be3cc72c3c688c0815e3c97e156fb4ad230"
VARIABLE_POOL_STORE_SCHEMA = "PSE-V1-VARIABLE-POOL-STORE-RECEIPT@1.0.0"
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_GIT_HEAD = re.compile(r"^[0-9a-f]{40}$")
_STORE_ROOT = PurePosixPath("production/variable-pools")
_CountEnum = TypeVar("_CountEnum", bound=StrEnum)


def _sha256(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _plan_key(plan_digest: str) -> str:
    if _SHA256.fullmatch(plan_digest) is None:
        raise ValueError("variable pool plan digest is malformed")
    return plan_digest.removeprefix("sha256:")


def _candidate_filename(candidate_id: str) -> str:
    return hashlib.sha256(candidate_id.encode("utf-8")).hexdigest() + ".json"


def _store_relative_path(plan_digest: str) -> PurePosixPath:
    return _STORE_ROOT / _plan_key(plan_digest)


def _counts(
    values: tuple[tuple[_CountEnum, int], ...], enum_type: type[_CountEnum]
) -> tuple[tuple[_CountEnum, int], ...]:
    result = tuple((enum_type(key), count) for key, count in values)
    if (
        result != tuple(sorted(result, key=lambda item: item[0].value.encode("utf-8")))
        or len({key for key, _count in result}) != len(result)
        or any(
            isinstance(count, bool) or not isinstance(count, int) or count < 1
            for _, count in result
        )
    ):
        raise ValueError("variable pool receipt counts must be positive and canonically ordered")
    return result


@register_serializable_type
@dataclass(frozen=True, slots=True)
class VariablePoolStoreReceiptV1:
    schema_version: str
    execution_baseline: str
    materialization_repository_head: str
    variable_pool_authoring_plan_digest: str
    materialized_pool_digest: str
    supply_inventory_digest: str
    historical_input_digest: str
    qualification_exclusion_digest: str
    candidate_count: int
    candidate_file_digests: tuple[tuple[str, str], ...]
    authority_basis_counts: tuple[tuple[RecipeAuthorityBasis, int], ...]
    origin_counts: tuple[tuple[CaseOrigin, int], ...]
    governed_additions_by_origin: tuple[tuple[CaseOrigin, int], ...]
    total_stored_bytes: int
    artifact_inventory_digest: str
    store_relative_path: str
    receipt_digest: str

    def __post_init__(self) -> None:
        if self.schema_version != VARIABLE_POOL_STORE_SCHEMA:
            raise ValueError("unknown variable pool store receipt schema")
        if self.execution_baseline != DYNAMISLM_EXECUTION_BASELINE:
            raise ValueError("variable pool receipt has the wrong execution baseline")
        if not _GIT_HEAD.fullmatch(self.materialization_repository_head):
            raise ValueError("variable pool receipt materialization head must be a Git SHA")
        for name in (
            "variable_pool_authoring_plan_digest",
            "materialized_pool_digest",
            "supply_inventory_digest",
            "historical_input_digest",
            "qualification_exclusion_digest",
            "artifact_inventory_digest",
            "receipt_digest",
        ):
            if _SHA256.fullmatch(getattr(self, name)) is None:
                raise ValueError(f"{name} must be a SHA-256 digest")
        expected_path = _store_relative_path(self.variable_pool_authoring_plan_digest).as_posix()
        if self.store_relative_path != expected_path:
            raise ValueError("variable pool store path must derive from its plan digest")
        if (
            isinstance(self.candidate_count, bool)
            or not isinstance(self.candidate_count, int)
            or self.candidate_count < 1
            or isinstance(self.total_stored_bytes, bool)
            or not isinstance(self.total_stored_bytes, int)
            or self.total_stored_bytes < 1
        ):
            raise ValueError("variable pool receipt counts and byte size must be positive")
        candidate_ids = tuple(candidate_id for candidate_id, _digest in self.candidate_file_digests)
        if (
            len(candidate_ids) != self.candidate_count
            or candidate_ids != tuple(sorted(set(candidate_ids), key=str.encode))
            or any(
                not candidate_id.startswith(PRODUCTION_CANDIDATE_ID_PREFIX)
                for candidate_id in candidate_ids
            )
            or any(
                _SHA256.fullmatch(digest) is None
                for _candidate_id, digest in self.candidate_file_digests
            )
        ):
            raise ValueError("variable pool receipt candidate file commitments are invalid")
        basis_counts = _counts(self.authority_basis_counts, RecipeAuthorityBasis)
        origin_counts = _counts(self.origin_counts, CaseOrigin)
        governed_counts = _counts(self.governed_additions_by_origin, CaseOrigin)
        object.__setattr__(self, "authority_basis_counts", basis_counts)
        object.__setattr__(self, "origin_counts", origin_counts)
        object.__setattr__(self, "governed_additions_by_origin", governed_counts)
        if sum(count for _basis, count in basis_counts) != self.candidate_count:
            raise ValueError("variable pool receipt authority basis counts do not sum to its pool")
        if sum(count for _origin, count in origin_counts) != self.candidate_count:
            raise ValueError("variable pool receipt origin counts do not sum to its pool")
        if sum(count for _origin, count in governed_counts) != dict(basis_counts).get(
            RecipeAuthorityBasis.GOVERNED_SUPPLY_LANE, 0
        ) or any(count > dict(origin_counts).get(origin, 0) for origin, count in governed_counts):
            raise ValueError("variable pool receipt governed counts do not match its authority")


def variable_pool_store_receipt_digest(receipt: VariablePoolStoreReceiptV1) -> str:
    return canonical_hash(
        {
            field.name: getattr(receipt, field.name)
            for field in fields(receipt)
            if field.name != "receipt_digest"
        }
    )


def _bind_receipt(receipt: VariablePoolStoreReceiptV1) -> VariablePoolStoreReceiptV1:
    bound = replace(receipt, receipt_digest=variable_pool_store_receipt_digest(receipt))
    validate_variable_pool_store_receipt(bound)
    return bound


def validate_variable_pool_store_receipt(receipt: VariablePoolStoreReceiptV1) -> None:
    if receipt.receipt_digest != variable_pool_store_receipt_digest(receipt):
        raise ValueError("variable pool store receipt digest mismatch")


def _plan_counts(
    plan: VariablePoolAuthoringPlanV1,
) -> tuple[
    tuple[tuple[RecipeAuthorityBasis, int], ...],
    tuple[tuple[CaseOrigin, int], ...],
    tuple[tuple[CaseOrigin, int], ...],
]:
    bases = Counter(item.authority_basis for item in plan.recipes)
    origins = Counter(item.origin_class for item in plan.recipes)
    governed = Counter(
        item.origin_class
        for item in plan.recipes
        if item.authority_basis is RecipeAuthorityBasis.GOVERNED_SUPPLY_LANE
    )

    def basis_key(item: tuple[RecipeAuthorityBasis, int]) -> bytes:
        return item[0].value.encode("utf-8")

    def origin_key(item: tuple[CaseOrigin, int]) -> bytes:
        return item[0].value.encode("utf-8")

    return (
        tuple(sorted(bases.items(), key=basis_key)),
        tuple(sorted(origins.items(), key=origin_key)),
        tuple(sorted(governed.items(), key=origin_key)),
    )


def _relative_file_inventory(
    store_relative: PurePosixPath,
    plan_bytes: bytes,
    candidates: tuple[tuple[str, bytes], ...],
) -> tuple[tuple[tuple[str, str, int], ...], int]:
    inventory = [
        (
            (store_relative / "authoring-plan.json").as_posix(),
            _sha256(plan_bytes),
            len(plan_bytes),
        )
    ]
    for candidate_id, payload in candidates:
        inventory.append(
            (
                (store_relative / "candidates" / _candidate_filename(candidate_id)).as_posix(),
                _sha256(payload),
                len(payload),
            )
        )
    ordered = tuple(sorted(inventory, key=lambda item: item[0].encode("utf-8")))
    return ordered, sum(size for _path, _digest, size in ordered)


def _ensure_store_directory(root: Path, relative: PurePosixPath) -> Path:
    if root.is_symlink():
        raise ValueError("variable pool external root cannot be a symlink")
    root.mkdir(parents=True, exist_ok=True)
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("variable pool store paths cannot contain symlinks")
        if current.exists() and not current.is_dir():
            raise ValueError("variable pool store path component is not a directory")
        current.mkdir(exist_ok=True)
        if not current.resolve().is_relative_to(root):
            raise ValueError("variable pool store path escapes its external root")
    return current


def _check_store_components(root: Path, relative: PurePosixPath) -> None:
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("variable pool store paths cannot contain symlinks")


def _store_files(directory: Path) -> tuple[set[str], set[str]]:
    files: set[str] = set()
    directories: set[str] = set()
    for parent, child_directories, child_files in os.walk(directory, followlinks=False):
        parent_path = Path(parent)
        for name in child_directories:
            path = parent_path / name
            if path.is_symlink() or not path.is_dir():
                raise ValueError("variable pool store cannot contain symlink directories")
            directories.add(path.relative_to(directory).as_posix())
        for name in child_files:
            path = parent_path / name
            if path.is_symlink() or not path.is_file():
                raise ValueError(
                    "variable pool store files cannot be symlinks or non-regular files"
                )
            files.add(path.relative_to(directory).as_posix())
    return files, directories


def _check_store_tree(
    directory: Path,
    expected_files: set[str],
    *,
    allow_missing: bool,
) -> None:
    files, directories = _store_files(directory)
    if files - expected_files or directories - {"candidates"}:
        raise ValueError("variable pool store contains unexpected artifacts")
    if not allow_missing and files != expected_files:
        raise ValueError("variable pool store file inventory is incomplete")


def _remove_interrupted_atomic_writes(directory: Path, expected_files: set[str]) -> None:
    """Remove only this plan's uncommitted temp files so an interrupted retry can resume."""

    for relative in expected_files:
        target = directory / PurePosixPath(relative)
        if not target.parent.is_dir():
            continue
        for temporary in target.parent.glob(f".{target.name}.*.tmp"):
            if temporary.is_symlink() or not temporary.is_file():
                raise ValueError("variable pool atomic-write temporary is not a regular file")
            temporary.unlink()


def _assert_authority_bindings(
    plan: VariablePoolAuthoringPlanV1,
    pool: ProductionAuthoringCandidatePoolV1,
    *,
    supply_inventory: AuthoritySupplyInventoryV1,
    exclusion: QualificationExclusionCommitmentV1,
    historical_input_digest: str,
) -> None:
    require_current_execution_supply_inventory(supply_inventory)
    validate_qualification_exclusion_commitment(exclusion)
    if (
        plan.plan_digest != variable_pool_authoring_plan_digest(plan)
        or pool.pool_digest != production_authoring_candidate_pool_digest(pool)
        or plan.plan_digest != pool.authoring_plan_digest
        or plan.supply_inventory_digest != supply_inventory.inventory_digest
        or plan.qualification_exclusion_digest != exclusion.commitment_digest
        or supply_inventory.evidence_binding(HISTORICAL_RECIPE_INPUT_BINDING)
        != historical_input_digest
        or supply_inventory.evidence_binding("QUALIFICATION_EXCLUSION_COMMITMENT")
        != exclusion.commitment_digest
        or not _SHA256.fullmatch(historical_input_digest)
        or tuple(item.candidate_id for item in plan.recipes)
        != tuple(packet.candidate_id for packet in pool.packets)
    ):
        raise ValueError("variable pool store authority bindings do not agree")


def write_variable_pool_store(
    plan: VariablePoolAuthoringPlanV1,
    pool: ProductionAuthoringCandidatePoolV1,
    *,
    supply_inventory: AuthoritySupplyInventoryV1,
    exclusion: QualificationExclusionCommitmentV1,
    historical_input_digest: str,
    materialization_repository_head: str,
    repository_root: str | Path,
    production_root: str | Path = DEFAULT_PRODUCTION_ROOT,
    source_resolver: SourceArtifactResolver | None,
) -> VariablePoolStoreReceiptV1:
    """Persist a validated immutable plan and pool, with receipt written as commit marker."""

    _assert_authority_bindings(
        plan,
        pool,
        supply_inventory=supply_inventory,
        exclusion=exclusion,
        historical_input_digest=historical_input_digest,
    )
    validate_variable_pre_review_pool(pool, exclusion=exclusion, source_resolver=source_resolver)
    if not _GIT_HEAD.fullmatch(materialization_repository_head):
        raise ValueError("materialization repository head must be a Git SHA")

    repository = Path(repository_root).resolve()
    root, _repository = _safe_external_root(Path(production_root), repository)
    store_relative = _store_relative_path(plan.plan_digest)
    directory = _ensure_store_directory(root, store_relative)
    candidate_bytes = tuple(
        (packet.candidate_id, (canonical_json(packet) + "\n").encode("utf-8"))
        for packet in pool.packets
    )
    plan_bytes = (canonical_json(plan) + "\n").encode("utf-8")
    expected_files = {
        "authoring-plan.json",
        "receipt.json",
        *(f"candidates/{_candidate_filename(candidate_id)}" for candidate_id, _ in candidate_bytes),
    }
    _ensure_store_directory(root, store_relative / "candidates")
    _remove_interrupted_atomic_writes(directory, expected_files)
    _check_store_tree(directory, expected_files, allow_missing=True)

    plan_path = _external_output_path(root, store_relative / "authoring-plan.json")
    _atomic_write_bytes(plan_path, plan_bytes)
    for candidate_id, payload in candidate_bytes:
        candidate_path = _external_output_path(
            root,
            store_relative / "candidates" / _candidate_filename(candidate_id),
        )
        _atomic_write_bytes(candidate_path, payload)

    _check_store_tree(directory, expected_files, allow_missing=True)
    present_files, _present_directories = _store_files(directory)
    if not (expected_files - {"receipt.json"}).issubset(present_files):
        raise ValueError("variable pool plan and all candidate files must exist before receipt")
    candidate_file_digests = tuple(
        (candidate_id, _sha256(payload)) for candidate_id, payload in candidate_bytes
    )
    inventory, total_bytes = _relative_file_inventory(store_relative, plan_bytes, candidate_bytes)
    basis_counts, origin_counts, governed_counts = _plan_counts(plan)
    provisional = VariablePoolStoreReceiptV1(
        schema_version=VARIABLE_POOL_STORE_SCHEMA,
        execution_baseline=DYNAMISLM_EXECUTION_BASELINE,
        materialization_repository_head=materialization_repository_head,
        variable_pool_authoring_plan_digest=plan.plan_digest,
        materialized_pool_digest=pool.pool_digest,
        supply_inventory_digest=supply_inventory.inventory_digest,
        historical_input_digest=historical_input_digest,
        qualification_exclusion_digest=exclusion.commitment_digest,
        candidate_count=pool.candidate_count,
        candidate_file_digests=candidate_file_digests,
        authority_basis_counts=basis_counts,
        origin_counts=origin_counts,
        governed_additions_by_origin=governed_counts,
        total_stored_bytes=total_bytes,
        artifact_inventory_digest=canonical_hash(inventory),
        store_relative_path=store_relative.as_posix(),
        receipt_digest="sha256:" + "0" * 64,
    )
    receipt = _bind_receipt(provisional)
    receipt_path = _external_output_path(root, store_relative / "receipt.json")
    _atomic_write_bytes(receipt_path, (canonical_json(receipt) + "\n").encode("utf-8"))
    stored_plan, stored_pool = read_variable_pool_store(
        receipt,
        supply_inventory=supply_inventory,
        exclusion=exclusion,
        historical_input_digest=historical_input_digest,
        repository_root=repository,
        production_root=root,
        source_resolver=source_resolver,
    )
    if stored_plan != plan or stored_pool != pool:
        raise ValueError("variable pool store round trip changed canonical contents")
    return receipt


def read_variable_pool_store(
    receipt: VariablePoolStoreReceiptV1,
    *,
    supply_inventory: AuthoritySupplyInventoryV1,
    exclusion: QualificationExclusionCommitmentV1,
    historical_input_digest: str,
    repository_root: str | Path,
    production_root: str | Path = DEFAULT_PRODUCTION_ROOT,
    source_resolver: SourceArtifactResolver | None,
) -> tuple[VariablePoolAuthoringPlanV1, ProductionAuthoringCandidatePoolV1]:
    """Read all committed files and verify exact inventory and authority bindings."""

    validate_variable_pool_store_receipt(receipt)
    repository = Path(repository_root).resolve()
    root, _repository = _safe_external_root(Path(production_root), repository)
    relative = _store_relative_path(receipt.variable_pool_authoring_plan_digest)
    _check_store_components(root, relative)
    directory = _external_input_path(root, relative)
    if not directory.is_dir() or directory.is_symlink():
        raise ValueError("variable pool store directory is unavailable or unsafe")
    expected_files = {
        "authoring-plan.json",
        "receipt.json",
        *(
            f"candidates/{_candidate_filename(candidate_id)}"
            for candidate_id, _digest in receipt.candidate_file_digests
        ),
    }
    _check_store_tree(directory, expected_files, allow_missing=False)

    from dynamislm.benchmark.production_store import read_external_production_json

    receipt_path = (relative / "receipt.json").as_posix()
    stored_receipt, _receipt_file_digest, _receipt_file_size = read_external_production_json(
        receipt_path,
        VariablePoolStoreReceiptV1,
        repository_root=repository,
        production_root=root,
    )
    if stored_receipt != receipt:
        raise ValueError("persisted variable pool receipt differs from the requested receipt")
    plan_path = (relative / "authoring-plan.json").as_posix()
    plan, plan_file_digest, plan_file_size = read_external_production_json(
        plan_path,
        VariablePoolAuthoringPlanV1,
        repository_root=repository,
        production_root=root,
    )
    if (
        plan.plan_digest != receipt.variable_pool_authoring_plan_digest
        or plan.plan_digest != variable_pool_authoring_plan_digest(plan)
        or plan.supply_inventory_digest != receipt.supply_inventory_digest
        or plan.qualification_exclusion_digest != receipt.qualification_exclusion_digest
    ):
        raise ValueError("stored variable pool authoring plan binding mismatch")

    packets = tuple(
        _read_candidate_for_binding(
            receipt,
            candidate_id,
            expected_digest,
            repository,
            root,
        )
        for candidate_id, expected_digest in receipt.candidate_file_digests
    )
    pool = ProductionAuthoringCandidatePoolV1(
        authoring_plan_digest=plan.plan_digest,
        packets=packets,
        pool_digest=receipt.materialized_pool_digest,
    )
    _assert_authority_bindings(
        plan,
        pool,
        supply_inventory=supply_inventory,
        exclusion=exclusion,
        historical_input_digest=historical_input_digest,
    )
    if tuple(item.candidate_id for item in plan.recipes) != tuple(
        packet.candidate_id for packet in packets
    ):
        raise ValueError("stored pool packets do not match the exact authoring plan")
    validate_variable_pre_review_pool(pool, exclusion=exclusion, source_resolver=source_resolver)
    if pool.pool_digest != production_authoring_candidate_pool_digest(pool):
        raise ValueError("stored variable pool digest mismatch")
    basis_counts, origin_counts, governed_counts = _plan_counts(plan)
    if (
        receipt.candidate_count != pool.candidate_count
        or receipt.authority_basis_counts != basis_counts
        or receipt.origin_counts != origin_counts
        or receipt.governed_additions_by_origin != governed_counts
    ):
        raise ValueError("stored variable pool receipt counts differ from the plan")

    candidate_payloads = tuple(
        (
            packet.candidate_id,
            _external_input_path(
                root,
                relative / "candidates" / _candidate_filename(packet.candidate_id),
            ).read_bytes(),
        )
        for packet in packets
    )
    inventory: list[tuple[str, str, int]] = [(plan_path, plan_file_digest, plan_file_size)]
    inventory.extend(
        (
            (relative / "candidates" / _candidate_filename(candidate_id)).as_posix(),
            _sha256(payload),
            len(payload),
        )
        for candidate_id, payload in candidate_payloads
    )
    if (
        sum(size for _path, _digest, size in inventory) != receipt.total_stored_bytes
        or canonical_hash(tuple(sorted(inventory, key=lambda item: item[0].encode("utf-8"))))
        != receipt.artifact_inventory_digest
    ):
        raise ValueError("variable pool store file inventory digest mismatch")
    _check_store_components(root, relative)
    _check_store_tree(directory, expected_files, allow_missing=False)
    return plan, pool


def _read_candidate_for_binding(
    receipt: VariablePoolStoreReceiptV1,
    candidate_id: str,
    expected_digest: str,
    repository_root: str | Path,
    production_root: str | Path,
) -> CandidateReviewPacket:
    root, _repository = _safe_external_root(Path(production_root), Path(repository_root))
    relative = _store_relative_path(receipt.variable_pool_authoring_plan_digest)
    packet_path = _external_input_path(
        root,
        relative / "candidates" / _candidate_filename(candidate_id),
    )
    try:
        payload = packet_path.read_bytes()
        decoded = payload.decode("utf-8")
        packet = from_canonical_json(decoded.rstrip("\n"), CandidateReviewPacket)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise ValueError("stored variable pool candidate is unavailable or invalid") from exc
    if (
        _sha256(payload) != expected_digest
        or canonical_json(packet) + "\n" != decoded
        or packet.candidate_id != candidate_id
        or candidate_payload_hash(packet) != packet.candidate_payload_hash
    ):
        raise ValueError("stored variable pool candidate file or payload digest mismatch")
    return packet


__all__ = [
    "DYNAMISLM_EXECUTION_BASELINE",
    "VARIABLE_POOL_STORE_SCHEMA",
    "VariablePoolStoreReceiptV1",
    "read_variable_pool_store",
    "validate_variable_pool_store_receipt",
    "variable_pool_store_receipt_digest",
    "write_variable_pool_store",
]
