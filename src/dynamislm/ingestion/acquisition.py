"""Deterministic streamed acquisition and metadata-snapshot operations."""

from __future__ import annotations

import datetime as datetime_module
import hashlib
import json
import os
import re
import tempfile
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from dynamislm.ingestion.contracts import (
    ArtifactAcquisitionReceipt,
    DatasetSourceIdentity,
    DatasetVersionIdentity,
    FileRepresentation,
    RegisteredDatasetFileIdentity,
    SavedOriginalVerificationReceipt,
    SourceVersionConflict,
    SourceVersionVerificationReceipt,
    VerifiedRawArtifact,
)
from dynamislm.ingestion.storage import (
    assert_data_path_contained,
    ensure_data_tree,
    relative_data_path,
    resolve_data_root,
    store_verified_temporary_file,
    verify_file,
    write_external_json,
)
from dynamislm.measurement.identity import InstanceIdentifier


class AcquisitionError(ValueError):
    """Raised when a public acquisition cannot be verified and stored."""


_SAFE_SLUG_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_slug(value: str) -> str:
    slug = _SAFE_SLUG_RE.sub("-", value).strip("-")
    return slug or "artifact"


def _normalise_digest(value: str) -> str:
    digest = value.removeprefix("sha256:").lower()
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise AcquisitionError("expected_sha256 must be a SHA-256 hexadecimal value")
    return f"sha256:{digest}"


def _timeout(timeout: float) -> float:
    if isinstance(timeout, bool) or not isinstance(timeout, int | float) or timeout <= 0:
        raise AcquisitionError("timeout must be finite and positive")
    if not float(timeout) < float("inf"):
        raise AcquisitionError("timeout must be finite and positive")
    return float(timeout)


def _header_value(headers: Any, name: str) -> str | None:
    value = headers.get(name)
    return str(value) if value is not None else None


def _content_type(headers: Any, fallback: str) -> str:
    try:
        value = headers.get_content_type()
    except AttributeError:
        value = None
    if value:
        return str(value)
    return fallback


def _filename_from_url(url: str) -> str:
    filename = Path(urllib.parse.unquote(urllib.parse.urlparse(url).path)).name
    return filename or "downloaded-artifact"


def _receipt_path(data_root: Path, source_id: str, source_version: str, suffix: str) -> str:
    return f"receipts/{_safe_slug(source_id)}-{_safe_slug(source_version)}-{suffix}.json"


def _record_source_version_conflict(
    data_root: Path,
    source: DatasetSourceIdentity,
    version: DatasetVersionIdentity,
    expected_sha256: str,
    actual_sha256: str,
    expected_byte_size: int | None,
    actual_byte_size: int,
) -> SourceVersionConflict:
    conflict = SourceVersionConflict(
        source_id=source.source_id,
        source_version=version.repository_version,
        expected_sha256=expected_sha256,
        actual_sha256=actual_sha256,
        expected_byte_size=expected_byte_size,
        actual_byte_size=actual_byte_size,
    )
    write_external_json(
        data_root,
        _receipt_path(data_root, source.source_id, version.repository_version, "version-conflict"),
        conflict,
    )
    return conflict


def _store_acquisition(
    chunks: Iterable[bytes],
    *,
    source: DatasetSourceIdentity,
    version: DatasetVersionIdentity,
    requested_url: str,
    resolved_url: str,
    original_filename: str,
    media_type: str,
    provider_hash: str | None,
    provider_hash_algorithm: str | None,
    etag: str | None,
    last_modified: str | None,
    metadata_snapshot_sha256: str | None,
    expected_sha256: str | None,
    expected_byte_size: int | None,
    registered_file_identity: RegisteredDatasetFileIdentity | None,
    representation: FileRepresentation,
    provider_file_id: str | int | None,
    data_root: Path,
    repository_root: Path | None,
) -> VerifiedRawArtifact:
    resolved_data_root = ensure_data_tree(data_root, repository_root=repository_root)
    if registered_file_identity is not None:
        if source.source_id != registered_file_identity.source_id:
            raise AcquisitionError("source does not match registered file identity")
        if version.repository_version != registered_file_identity.source_version:
            raise AcquisitionError("version does not match registered file identity")
        if representation is not registered_file_identity.representation:
            raise AcquisitionError("representation does not match registered file identity")
        if expected_sha256 is not None and _normalise_digest(expected_sha256) != (
            registered_file_identity.expected_sha256
        ):
            raise AcquisitionError("caller expected SHA-256 differs from registry authority")
        if expected_byte_size is not None and expected_byte_size != (
            registered_file_identity.expected_byte_size
        ):
            raise AcquisitionError("caller expected byte size differs from registry authority")
        expected_sha256 = registered_file_identity.expected_sha256
        expected_byte_size = registered_file_identity.expected_byte_size
        if original_filename != registered_file_identity.filename:
            raise AcquisitionError("download filename differs from registered file identity")
        if media_type != registered_file_identity.media_type:
            raise AcquisitionError("download media type differs from registered file identity")
    expected_digest = _normalise_digest(expected_sha256) if expected_sha256 is not None else None
    if expected_byte_size is not None:
        if isinstance(expected_byte_size, bool) or not isinstance(expected_byte_size, int):
            raise AcquisitionError("expected_byte_size must be an integer when present")
        if expected_byte_size < 0:
            raise AcquisitionError("expected_byte_size must not be negative")

    temporary_path: Path | None = None
    digest = hashlib.sha256()
    byte_size = 0
    temp_directory = resolved_data_root / "tmp" / "acquisition"
    if not temp_directory.is_dir():
        raise AcquisitionError("temporary acquisition directory is not a directory")
    try:
        assert_data_path_contained(resolved_data_root, temp_directory)
    except ValueError as exc:
        raise AcquisitionError("temporary acquisition directory escaped data root") from exc
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=temp_directory,
            prefix=".download-",
            suffix=".part",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            for chunk in chunks:
                if not isinstance(chunk, bytes):
                    raise AcquisitionError("acquisition stream must yield bytes")
                temporary.write(chunk)
                digest.update(chunk)
                byte_size += len(chunk)
            temporary.flush()
            os.fsync(temporary.fileno())

        actual_digest = f"sha256:{digest.hexdigest()}"
        if expected_digest is not None and actual_digest != expected_digest:
            _record_source_version_conflict(
                resolved_data_root,
                source,
                version,
                expected_digest,
                actual_digest,
                expected_byte_size,
                byte_size,
            )
            raise AcquisitionError("downloaded bytes conflict with the registered source version")
        if expected_byte_size is not None and byte_size != expected_byte_size:
            raise AcquisitionError("downloaded byte count does not match the registered size")

        object_path = store_verified_temporary_file(
            temporary_path,
            data_root=resolved_data_root,
            expected_sha256=actual_digest,
            expected_byte_size=byte_size,
        )
        temporary_path = None
        receipt = ArtifactAcquisitionReceipt(
            source_id=source.source_id,
            source_version=version.repository_version,
            requested_url=requested_url,
            resolved_url=resolved_url,
            original_filename=original_filename,
            media_type=media_type,
            byte_size=byte_size,
            sha256=actual_digest,
            retrieved_at=datetime_module.datetime.now(datetime_module.UTC),
            provider_hash=provider_hash,
            provider_hash_algorithm=provider_hash_algorithm,
            etag=etag,
            last_modified=last_modified,
            metadata_snapshot_sha256=metadata_snapshot_sha256,
            storage_relative_path=relative_data_path(resolved_data_root, object_path),
            representation=representation,
            provider_file_id=provider_file_id,
        )
        receipt_path = write_external_json(
            resolved_data_root,
            _receipt_path(
                resolved_data_root,
                source.source_id,
                version.repository_version,
                "acquisition",
            ),
            receipt,
        )
        artifact = VerifiedRawArtifact(
            artifact_id=InstanceIdentifier("artifact", actual_digest),
            sha256=actual_digest,
            byte_size=byte_size,
            media_type=media_type,
            relative_path=relative_data_path(resolved_data_root, object_path),
            acquisition_receipt=receipt,
            representation=representation,
        )
        # The receipt itself is the committed/external evidence; keep the path
        # construction above deterministic without adding it to semantic data.
        if not receipt_path.is_file():
            raise AcquisitionError("acquisition receipt was not stored")
        return artifact
    except Exception:
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass
        raise


def acquire_url(
    source: DatasetSourceIdentity,
    version: DatasetVersionIdentity,
    url: str,
    *,
    expected_sha256: str | None = None,
    expected_byte_size: int | None = None,
    registered_file_identity: RegisteredDatasetFileIdentity | None = None,
    representation: FileRepresentation = FileRepresentation.PROVIDER_FILE,
    provider_file_id: str | int | None = None,
    provider_hash: str | None = None,
    provider_hash_algorithm: str | None = None,
    provider_hash_representation: FileRepresentation | None = None,
    metadata_snapshot_sha256: str | None = None,
    original_filename: str | None = None,
    media_type: str = "application/octet-stream",
    timeout: float = 30.0,
    data_root: Path | None = None,
    repository_root: Path | None = None,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> VerifiedRawArtifact:
    """Acquire one HTTPS URL by streaming and verifying its exact bytes."""

    if not isinstance(source, DatasetSourceIdentity):
        raise AcquisitionError("source must be a DatasetSourceIdentity")
    if not isinstance(version, DatasetVersionIdentity):
        raise AcquisitionError("version must be a DatasetVersionIdentity")
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise AcquisitionError("public acquisition requires an HTTPS URL")
    request_timeout = _timeout(timeout)
    resolved_data_root = ensure_data_tree(data_root, repository_root=repository_root)
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "DynamisLM-RES63/1.0"},
    )
    chosen_filename = original_filename or _filename_from_url(url)
    with opener(request, timeout=request_timeout) as response:
        resolved_url = response.geturl()
        if urllib.parse.urlparse(resolved_url).scheme != "https":
            raise AcquisitionError("resolved acquisition URL must remain HTTPS")
        response_headers = response.headers
        chunks = iter(lambda: response.read(1024 * 1024), b"")
        observed_media_type = _content_type(response_headers, media_type)
        chosen_media_type = (
            media_type if media_type != "application/octet-stream" else observed_media_type
        )
        return _store_acquisition(
            chunks,
            source=source,
            version=version,
            requested_url=url,
            resolved_url=resolved_url,
            original_filename=chosen_filename,
            media_type=chosen_media_type,
            provider_hash=provider_hash,
            provider_hash_algorithm=provider_hash_algorithm,
            etag=_header_value(response_headers, "ETag"),
            last_modified=_header_value(response_headers, "Last-Modified"),
            metadata_snapshot_sha256=metadata_snapshot_sha256,
            expected_sha256=expected_sha256,
            expected_byte_size=expected_byte_size,
            registered_file_identity=registered_file_identity,
            representation=representation,
            provider_file_id=provider_file_id,
            data_root=resolved_data_root,
            repository_root=repository_root,
        )


def acquire_bytes(
    source: DatasetSourceIdentity,
    version: DatasetVersionIdentity,
    content: bytes,
    *,
    requested_url: str = "https://synthetic.invalid/artifact",
    resolved_url: str | None = None,
    original_filename: str = "synthetic-artifact",
    media_type: str = "application/octet-stream",
    expected_sha256: str | None = None,
    expected_byte_size: int | None = None,
    registered_file_identity: RegisteredDatasetFileIdentity | None = None,
    representation: FileRepresentation = FileRepresentation.PROVIDER_FILE,
    provider_file_id: str | int | None = None,
    provider_hash: str | None = None,
    provider_hash_algorithm: str | None = None,
    provider_hash_representation: FileRepresentation | None = None,
    metadata_snapshot_sha256: str | None = None,
    data_root: Path | None = None,
    repository_root: Path | None = None,
) -> VerifiedRawArtifact:
    """Acquire in-memory bytes for deterministic tests and local fixtures."""

    if not isinstance(content, bytes):
        raise AcquisitionError("content must be bytes")
    parsed = urllib.parse.urlparse(requested_url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise AcquisitionError("synthetic acquisition URL must be HTTPS")
    if resolved_url is not None:
        resolved_parsed = urllib.parse.urlparse(resolved_url)
        if resolved_parsed.scheme != "https" or not resolved_parsed.netloc:
            raise AcquisitionError("synthetic resolved acquisition URL must be HTTPS")
    return _store_acquisition(
        (content,),
        source=source,
        version=version,
        requested_url=requested_url,
        resolved_url=resolved_url or requested_url,
        original_filename=original_filename,
        media_type=media_type,
        provider_hash=provider_hash,
        provider_hash_algorithm=provider_hash_algorithm,
        etag=None,
        last_modified=None,
        metadata_snapshot_sha256=metadata_snapshot_sha256,
        expected_sha256=expected_sha256,
        expected_byte_size=expected_byte_size,
        registered_file_identity=registered_file_identity,
        representation=representation,
        provider_file_id=provider_file_id,
        data_root=data_root or resolve_data_root(repository_root=repository_root),
        repository_root=repository_root,
    )


def verify_saved_original_url(
    source: DatasetSourceIdentity,
    version: DatasetVersionIdentity,
    url: str,
    *,
    registered_file_identity: RegisteredDatasetFileIdentity,
    file_persistent_identifier: str,
    provider_file_id: str | int,
    expected_byte_size: int,
    metadata_snapshot_sha256: str,
    data_root: Path | None = None,
    repository_root: Path | None = None,
    timeout: float = 45.0,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> SavedOriginalVerificationReceipt:
    """Stream a provider's saved-original bytes and persist only observations."""

    if not isinstance(source, DatasetSourceIdentity):
        raise AcquisitionError("source must be a DatasetSourceIdentity")
    if not isinstance(version, DatasetVersionIdentity):
        raise AcquisitionError("version must be a DatasetVersionIdentity")
    if not isinstance(registered_file_identity, RegisteredDatasetFileIdentity):
        raise AcquisitionError("registered_file_identity must be a RegisteredDatasetFileIdentity")
    registered = registered_file_identity
    if source.source_id != registered.source_id:
        raise AcquisitionError("saved-original source does not match registered identity")
    if version.repository_version != registered.source_version:
        raise AcquisitionError("saved-original version does not match registered identity")
    if registered.provider_hash is None:
        raise AcquisitionError("registered saved-original provider hash is missing")
    if (
        registered.provider_hash_algorithm is None
        or registered.provider_hash_algorithm.lower() != "md5"
    ):
        raise AcquisitionError("registered saved-original provider hash algorithm must be md5")
    if registered.provider_hash_representation is not FileRepresentation.SAVED_ORIGINAL:
        raise AcquisitionError("registered provider hash is not for SAVED_ORIGINAL")
    if registered.provider_file_id != provider_file_id:
        raise AcquisitionError("saved-original provider file ID does not match registry")
    if registered.file_persistent_identifier != file_persistent_identifier:
        raise AcquisitionError("saved-original file PID does not match registry")
    if not isinstance(expected_byte_size, int) or isinstance(expected_byte_size, bool):
        raise AcquisitionError("saved-original expected byte size must be an integer")
    if expected_byte_size < 0:
        raise AcquisitionError("saved-original expected byte size must not be negative")
    if not isinstance(metadata_snapshot_sha256, str) or not metadata_snapshot_sha256.strip():
        raise AcquisitionError("saved-original metadata snapshot digest is required")
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise AcquisitionError("saved-original acquisition requires an HTTPS URL")
    if parsed.path.rstrip("/").split("/")[-1] != str(provider_file_id):
        raise AcquisitionError("saved-original URL is not bound to the registered file ID")
    query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
    if query.get("format") != ["original"]:
        raise AcquisitionError("saved-original acquisition URL must request format=original")
    request_timeout = _timeout(timeout)
    resolved_data_root = ensure_data_tree(data_root, repository_root=repository_root)
    request = urllib.request.Request(url, headers={"User-Agent": "DynamisLM-RES63/1.0"})
    observed_md5 = hashlib.md5()
    observed_sha256 = hashlib.sha256()
    observed_byte_size = 0
    with opener(request, timeout=request_timeout) as response:
        resolved_url = response.geturl()
        if urllib.parse.urlparse(resolved_url).scheme != "https":
            raise AcquisitionError("saved-original resolved URL must remain HTTPS")
        while chunk := response.read(1024 * 1024):
            if not isinstance(chunk, bytes):
                raise AcquisitionError("saved-original stream must yield bytes")
            observed_md5.update(chunk)
            observed_sha256.update(chunk)
            observed_byte_size += len(chunk)
    observed_md5_hex = observed_md5.hexdigest()
    if observed_md5_hex.lower() != registered.provider_hash.lower():
        raise AcquisitionError("saved-original bytes do not match the registered provider MD5")
    if observed_byte_size != expected_byte_size:
        raise AcquisitionError("saved-original byte count does not match the registered size")
    receipt = SavedOriginalVerificationReceipt(
        source_id=source.source_id,
        source_version=version.repository_version,
        provider_file_id=provider_file_id,
        file_persistent_identifier=file_persistent_identifier,
        representation=FileRepresentation.SAVED_ORIGINAL,
        provider_hash_algorithm="md5",
        provider_hash=registered.provider_hash,
        observed_md5=observed_md5_hex,
        observed_sha256=f"sha256:{observed_sha256.hexdigest()}",
        observed_byte_size=observed_byte_size,
        metadata_snapshot_sha256=metadata_snapshot_sha256,
    )
    write_external_json(
        resolved_data_root,
        _receipt_path(
            resolved_data_root,
            source.source_id,
            version.repository_version,
            "saved-original-verification",
        ),
        receipt,
    )
    return receipt


def verify_registered_artifact(
    registered_file_identity: RegisteredDatasetFileIdentity,
    verified_artifact: VerifiedRawArtifact,
    *,
    data_root: Path | None = None,
    repository_root: Path | None = None,
) -> SourceVersionVerificationReceipt:
    """Return a receipt only after registry/artifact identity comparisons pass."""

    try:
        resolved_data_root = resolve_data_root(data_root, repository_root=repository_root)
        artifact_path = assert_data_path_contained(
            resolved_data_root,
            resolved_data_root / verified_artifact.relative_path,
        )
        verify_file(
            artifact_path,
            expected_sha256=registered_file_identity.expected_sha256,
            expected_byte_size=registered_file_identity.expected_byte_size,
        )
        return SourceVersionVerificationReceipt(registered_file_identity, verified_artifact)
    except ValueError as exc:
        raise AcquisitionError(
            "verified artifact does not match registered source identity"
        ) from exc


def capture_metadata_snapshot(
    source: DatasetSourceIdentity,
    version: DatasetVersionIdentity,
    metadata: object,
    *,
    data_root: Path | None = None,
    repository_root: Path | None = None,
) -> str:
    """Canonicalize and store provider metadata, returning its distinct digest."""

    if not isinstance(source, DatasetSourceIdentity):
        raise AcquisitionError("source must be a DatasetSourceIdentity")
    if not isinstance(version, DatasetVersionIdentity):
        raise AcquisitionError("version must be a DatasetVersionIdentity")
    resolved_data_root = ensure_data_tree(data_root, repository_root=repository_root)
    serialized = json.dumps(
        metadata,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    digest = f"sha256:{hashlib.sha256(serialized.encode('utf-8')).hexdigest()}"
    relative_path = (
        f"metadata/{_safe_slug(source.source_id)}-{_safe_slug(version.repository_version)}-"
        f"{digest.removeprefix('sha256:')}.json"
    )
    write_external_json(resolved_data_root, relative_path, metadata)
    return digest


__all__ = [
    "AcquisitionError",
    "acquire_bytes",
    "acquire_url",
    "capture_metadata_snapshot",
    "verify_registered_artifact",
    "verify_saved_original_url",
]
