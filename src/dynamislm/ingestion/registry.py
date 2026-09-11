"""Committed public metadata registry for RES-63 source identities."""

from __future__ import annotations

import datetime as datetime_module
import hashlib
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from dynamislm.ingestion.contracts import (
    DatasetLicenseIdentity,
    DatasetSourceIdentity,
    DatasetVersionIdentity,
    FileRepresentation,
    RegisteredDatasetFileIdentity,
)
from dynamislm.ingestion.storage import resolve_repository_root

REGISTRY_RELATIVE_ROOT = Path("registries") / "datasets"
_FORBIDDEN_REGISTRY_KEYS = frozenset(
    {"raw_rows", "canonical_rows", "athlete_rows", "dob_table", "credentials"}
)


@dataclass(frozen=True, slots=True)
class CommittedDatasetRegistry:
    """Exact registry bytes and Git identity read from the current ``HEAD``.

    This is an in-process authority object, not a serialized evidence record.
    Its document is parsed from the committed Git blob; callers must not replace
    it with a working-tree document or a caller-created identity.
    """

    source_id: str
    document: dict[str, Any]
    repository_root: Path
    repository_head_sha: str
    registry_relative_path: str
    registry_git_blob_oid: str
    registry_blob_sha256: str
    working_tree_matches_head: bool


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[3]


def registry_root(repository_root: Path | None = None) -> Path:
    return (repository_root or _repository_root()) / REGISTRY_RELATIVE_ROOT


def _assert_public_metadata(value: object, key_path: str = "") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).lower() in _FORBIDDEN_REGISTRY_KEYS:
                raise ValueError(f"registry contains forbidden data field: {key_path}{key}")
            _assert_public_metadata(item, f"{key_path}{key}.")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _assert_public_metadata(item, f"{key_path}[{index}].")
    elif isinstance(value, str):
        if value.startswith("/") or value.startswith("~") or value.startswith("\\"):
            raise ValueError("registry must not contain resolved local paths")


def _validate_source_id(source_id: str) -> None:
    if not isinstance(source_id, str) or not source_id.strip():
        raise ValueError("source_id must not be empty")
    if Path(source_id).name != source_id or source_id in {".", ".."}:
        raise ValueError("source_id must be a single registry filename component")


def _registry_candidate_relative_paths(source_id: str) -> tuple[Path, ...]:
    return (
        REGISTRY_RELATIVE_ROOT / f"{source_id}.json",
        REGISTRY_RELATIVE_ROOT / f"{source_id}-v1.json",
    )


def _read_registry_document(blob: bytes, *, source_id: str | None = None) -> dict[str, Any]:
    try:
        document = json.loads(blob.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid dataset registry document in committed Git blob") from exc
    if not isinstance(document, dict):
        raise ValueError("dataset registry document must be an object")
    _assert_public_metadata(document)
    if source_id is not None and document.get("source_id") != source_id:
        raise ValueError("dataset registry source_id does not match filename/request")
    return cast(dict[str, Any], document)


def load_committed_dataset_registry(
    source_id: str,
    *,
    repository_root: Path,
) -> CommittedDatasetRegistry:
    """Load one registry from the exact blob at the repository's current ``HEAD``.

    The working tree is inspected only for an equality diagnostic.  It is never
    used as the source of the returned document or its derived file identity.
    """

    _validate_source_id(source_id)
    real_repository_root = resolve_repository_root(repository_root)
    head_result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=real_repository_root,
        check=True,
        capture_output=True,
        text=True,
    )
    repository_head_sha = head_result.stdout.strip()
    candidates: list[tuple[Path, bytes]] = []
    for relative_path in _registry_candidate_relative_paths(source_id):
        git_path = f"HEAD:{relative_path.as_posix()}"
        exists = subprocess.run(
            ["git", "cat-file", "-e", git_path],
            cwd=real_repository_root,
            check=False,
            capture_output=True,
        )
        if exists.returncode != 0:
            continue
        object_type = subprocess.run(
            ["git", "cat-file", "-t", git_path],
            cwd=real_repository_root,
            check=True,
            capture_output=True,
            text=True,
        )
        if object_type.stdout.strip() != "blob":
            raise ValueError(f"committed dataset registry path is not a blob: {relative_path}")
        blob_result = subprocess.run(
            ["git", "cat-file", "blob", git_path],
            cwd=real_repository_root,
            check=True,
            capture_output=True,
        )
        candidates.append((relative_path, blob_result.stdout))

    if not candidates:
        raise ValueError(f"committed dataset registry was not found in HEAD: {source_id}")
    if len(candidates) > 1:
        paths = ", ".join(path.as_posix() for path, _ in candidates)
        raise ValueError(f"FAIL_AMBIGUOUS_REGISTRY_IDENTITY: {paths}")

    relative_path, blob = candidates[0]
    git_path = f"HEAD:{relative_path.as_posix()}"
    blob_oid_result = subprocess.run(
        ["git", "rev-parse", git_path],
        cwd=real_repository_root,
        check=True,
        capture_output=True,
        text=True,
    )
    registry_git_blob_oid = blob_oid_result.stdout.strip()
    document = _read_registry_document(blob, source_id=source_id)
    registry_blob_sha256 = f"sha256:{hashlib.sha256(blob).hexdigest()}"
    working_tree_path = real_repository_root / relative_path
    try:
        working_tree_matches_head = working_tree_path.read_bytes() == blob
    except OSError:
        working_tree_matches_head = False
    return CommittedDatasetRegistry(
        source_id=source_id,
        document=document,
        repository_root=real_repository_root,
        repository_head_sha=repository_head_sha,
        registry_relative_path=relative_path.as_posix(),
        registry_git_blob_oid=registry_git_blob_oid,
        registry_blob_sha256=registry_blob_sha256,
        working_tree_matches_head=working_tree_matches_head,
    )


def load_dataset_registry(
    source_id: str,
    *,
    repository_root: Path | None = None,
) -> dict[str, Any]:
    """Load one committed source registry record without loading athlete rows."""

    binding = load_committed_dataset_registry(
        source_id,
        repository_root=repository_root or _repository_root(),
    )
    return dict(binding.document)


def load_all_dataset_registries(
    *,
    repository_root: Path | None = None,
) -> tuple[dict[str, Any], ...]:
    """Load all committed registry documents in stable filename order."""

    real_repository_root = resolve_repository_root(repository_root or _repository_root())
    result = subprocess.run(
        [
            "git",
            "ls-tree",
            "-r",
            "--name-only",
            "HEAD",
            "--",
            REGISTRY_RELATIVE_ROOT.as_posix(),
        ],
        cwd=real_repository_root,
        check=True,
        capture_output=True,
        text=True,
    )
    documents: list[dict[str, Any]] = []
    for name in sorted(line for line in result.stdout.splitlines() if line.endswith(".json")):
        blob_result = subprocess.run(
            ["git", "cat-file", "blob", f"HEAD:{name}"],
            cwd=real_repository_root,
            check=True,
            capture_output=True,
        )
        documents.append(_read_registry_document(blob_result.stdout))
    return tuple(documents)


def _mapping(document: dict[str, Any], key: str) -> dict[str, Any]:
    value = document.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"registry field {key!r} must be an object")
    return value


def _required_string(document: dict[str, Any], key: str) -> str:
    value = document.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"registry field {key!r} must be a non-empty string")
    return value


def _optional_string(document: dict[str, Any], key: str) -> str | None:
    value = document.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"registry field {key!r} must be a non-empty string when present")
    return value


def dataset_source_identity(document: dict[str, Any]) -> DatasetSourceIdentity:
    """Build a typed source identity from one registry document."""

    return DatasetSourceIdentity(
        source_id=_required_string(document, "source_id"),
        provider=_required_string(document, "provider"),
        title=_required_string(document, "title"),
        landing_page_uri=_required_string(document, "landing_page_uri"),
        persistent_identifier=_required_string(document, "persistent_identifier"),
    )


def dataset_version_identity(document: dict[str, Any]) -> DatasetVersionIdentity:
    """Build a typed source-version identity from one registry document."""

    version = _mapping(document, "version")
    published_at = version.get("published_at")
    published_value: datetime_module.date | datetime_module.datetime | None
    if isinstance(published_at, str):
        published_value = (
            datetime_module.datetime.fromisoformat(published_at.replace("Z", "+00:00"))
            if "T" in published_at
            else datetime_module.date.fromisoformat(published_at)
        )
    else:
        published_value = None
    return DatasetVersionIdentity(
        repository_version=_required_string(version, "repository_version"),
        version_specific_persistent_identifier=_optional_string(
            version,
            "version_specific_persistent_identifier",
        ),
        published_at=published_value,
    )


def dataset_license_identity(document: dict[str, Any]) -> DatasetLicenseIdentity:
    """Build the deliberately small machine-readable license identity."""

    license_document = _mapping(document, "license")
    attribution_required = license_document.get("attribution_required")
    noncommercial_restriction = license_document.get("noncommercial_restriction")
    if not isinstance(attribution_required, bool) or not isinstance(
        noncommercial_restriction,
        bool,
    ):
        raise ValueError("registry license flags must be booleans")
    return DatasetLicenseIdentity(
        spdx_expression=_required_string(license_document, "spdx_expression"),
        canonical_uri=_required_string(license_document, "canonical_uri"),
        assertion_source_uri=_required_string(license_document, "assertion_source_uri"),
        attribution_required=attribution_required,
        noncommercial_restriction=noncommercial_restriction,
        notes=(
            str(license_document["notes"]) if license_document.get("notes") is not None else None
        ),
    )


def registry_file_entries(document: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    """Return public file identities in the deterministic registry order."""

    files = document.get("files", ())
    if not isinstance(files, list):
        raise ValueError("registry files must be an array")
    entries: list[dict[str, Any]] = []
    for item in files:
        if not isinstance(item, dict):
            raise ValueError("registry file entries must be objects")
        entries.append(cast(dict[str, Any], item))
    return tuple(entries)


def registered_dataset_file_identity(
    document: dict[str, Any],
    *,
    file_index: int = 0,
    representation: FileRepresentation | None = None,
) -> RegisteredDatasetFileIdentity:
    """Build the expected file identity strictly from committed registry data."""

    source_id = _required_string(document, "source_id")
    version = dataset_version_identity(document)
    entries = registry_file_entries(document)
    if isinstance(file_index, bool) or not isinstance(file_index, int) or file_index < 0:
        raise ValueError("file_index must be a non-negative integer")
    if representation is None:
        if len(entries) != 1:
            raise ValueError("representation is required for registries with multiple files")
        selected = entries[file_index] if file_index < len(entries) else None
    else:
        selected = next(
            (entry for entry in entries if entry.get("representation") == representation.value),
            None,
        )
    if selected is None:
        raise ValueError("registered dataset file identity was not found")
    selected_representation = selected.get("representation")
    if not isinstance(selected_representation, str):
        raise ValueError("registry file representation must be explicit")
    try:
        parsed_representation = FileRepresentation(selected_representation)
    except ValueError as exc:
        raise ValueError("registry file representation is unsupported") from exc
    if representation is not None and parsed_representation is not representation:
        raise ValueError("registry file representation does not match request")

    expected_sha256 = selected.get("sha256")
    expected_byte_size = selected.get("byte_size")
    if not isinstance(expected_sha256, str):
        raise ValueError("registry file sha256 is required")
    if isinstance(expected_byte_size, bool) or not isinstance(expected_byte_size, int):
        raise ValueError("registry file byte_size is required")
    provider_declared_byte_size = selected.get("provider_declared_byte_size")
    if provider_declared_byte_size is not None and (
        isinstance(provider_declared_byte_size, bool)
        or not isinstance(provider_declared_byte_size, int)
    ):
        raise ValueError("registry provider_declared_byte_size must be an integer")
    provider_hash_representation_value = selected.get("provider_hash_representation")
    provider_hash_representation = None
    if provider_hash_representation_value is not None:
        try:
            provider_hash_representation = FileRepresentation(provider_hash_representation_value)
        except ValueError as exc:
            raise ValueError("registry provider hash representation is unsupported") from exc
    provider_hash = _optional_string(selected, "provider_hash")
    provider_hash_algorithm = _optional_string(selected, "provider_hash_algorithm")
    saved_original_filename = selected.get("saved_original_filename")
    saved_original_byte_size = selected.get("saved_original_byte_size")
    saved_original_provider_hash = selected.get("saved_original_provider_hash")
    if provider_hash_representation is FileRepresentation.SAVED_ORIGINAL:
        if provider_hash is None or provider_hash_algorithm is None:
            raise ValueError("saved-original registry hash identity is incomplete")
        if provider_hash_algorithm.lower() != "md5":
            raise ValueError("saved-original registry hash algorithm must be md5")
        if not isinstance(saved_original_filename, str) or not saved_original_filename.strip():
            raise ValueError("saved-original registry filename is required")
        if isinstance(saved_original_byte_size, bool) or not isinstance(
            saved_original_byte_size, int
        ):
            raise ValueError("saved-original registry byte size is required")
        if (
            not isinstance(saved_original_provider_hash, str)
            or not saved_original_provider_hash.strip()
        ):
            raise ValueError("saved-original registry provider hash is required")
        if saved_original_provider_hash.lower() != provider_hash.lower():
            raise ValueError("saved-original registry provider hashes differ")
    return RegisteredDatasetFileIdentity(
        source_id=source_id,
        source_version=version.repository_version,
        representation=parsed_representation,
        provider_file_id=selected.get("file_id", selected.get("provider_file_id")),
        file_persistent_identifier=(
            str(selected["file_persistent_identifier"])
            if selected.get("file_persistent_identifier") is not None
            else None
        ),
        filename=_required_string(selected, "filename"),
        media_type=_required_string(selected, "media_type"),
        expected_sha256=expected_sha256,
        expected_byte_size=expected_byte_size,
        provider_hash=provider_hash,
        provider_hash_algorithm=provider_hash_algorithm,
        provider_declared_byte_size=provider_declared_byte_size,
        provider_hash_representation=provider_hash_representation,
    )


def verify_live_provider_file_observation(
    registered: RegisteredDatasetFileIdentity,
    *,
    provider_sha256: str | None = None,
    provider_hash: str | None = None,
    provider_hash_algorithm: str | None = None,
    provider_byte_size: int | None = None,
    provider_file_id: str | int | None = None,
    provider_hash_representation: FileRepresentation | None = None,
) -> None:
    """Compare live metadata to the registry without promoting it to authority."""

    if registered.provider_file_id is not None and provider_file_id is None:
        raise ValueError("SOURCE_VERSION_CONFLICT: live provider file ID is missing")
    if provider_file_id is not None and registered.provider_file_id != provider_file_id:
        raise ValueError("SOURCE_VERSION_CONFLICT: live provider file ID differs from registry")
    if (
        provider_byte_size is not None
        and registered.representation is not FileRepresentation.ARCHIVAL_TAB
    ):
        if provider_byte_size != registered.expected_byte_size:
            raise ValueError(
                "SOURCE_VERSION_CONFLICT: live provider byte size differs from registry"
            )
    if provider_sha256 is not None and provider_sha256.removeprefix("sha256:").lower() != (
        registered.expected_sha256.removeprefix("sha256:").lower()
    ):
        raise ValueError("SOURCE_VERSION_CONFLICT: live provider SHA-256 differs from registry")
    if registered.provider_hash is not None and provider_hash is None:
        raise ValueError("SOURCE_VERSION_CONFLICT: live provider hash is missing")
    if registered.provider_hash is not None and provider_hash is not None:
        if provider_hash.lower() != registered.provider_hash.lower():
            raise ValueError("SOURCE_VERSION_CONFLICT: live provider hash differs from registry")
        if registered.provider_hash_algorithm is not None and provider_hash_algorithm is None:
            raise ValueError("SOURCE_VERSION_CONFLICT: live provider hash algorithm is missing")
        if (
            registered.provider_hash_algorithm is not None
            and provider_hash_algorithm is not None
            and provider_hash_algorithm.lower() != registered.provider_hash_algorithm.lower()
        ):
            raise ValueError("SOURCE_VERSION_CONFLICT: live provider hash algorithm differs")
        if (
            registered.provider_hash_representation is not None
            and provider_hash_representation is not registered.provider_hash_representation
        ):
            raise ValueError("SOURCE_VERSION_CONFLICT: live provider hash representation differs")


# Short aliases used by operational callers.
load_registry = load_dataset_registry
source_identity_from_registry = dataset_source_identity
version_identity_from_registry = dataset_version_identity
license_identity_from_registry = dataset_license_identity
registered_file_identity_from_registry = registered_dataset_file_identity


__all__ = [
    "REGISTRY_RELATIVE_ROOT",
    "CommittedDatasetRegistry",
    "dataset_license_identity",
    "dataset_source_identity",
    "dataset_version_identity",
    "license_identity_from_registry",
    "load_all_dataset_registries",
    "load_committed_dataset_registry",
    "load_dataset_registry",
    "load_registry",
    "registered_dataset_file_identity",
    "registered_file_identity_from_registry",
    "registry_file_entries",
    "registry_root",
    "source_identity_from_registry",
    "verify_live_provider_file_observation",
    "version_identity_from_registry",
]
