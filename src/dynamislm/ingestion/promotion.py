"""RES-63 typed promotion authority and bounded canonical replay writers."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterable, Iterator
from pathlib import Path, PurePosixPath
from typing import Any

from dynamislm.ingestion.acquisition import (
    _receipt_path,
    _safe_slug,
    verify_registered_artifact,
)
from dynamislm.ingestion.contracts import (
    ArtifactAcquisitionReceipt,
    CanonicalEmpiricalArtifactReceipt,
    CanonicalEmpiricalRecord,
    CanonicalValidationReceipt,
    DatasetQualificationReceipt,
    FileRepresentation,
    PromotionDecision,
    PromotionEvidence,
    PromotionStatus,
    RegisteredDatasetFileIdentity,
    SavedOriginalVerificationReceipt,
    SourceVariableIdentity,
    SourceVariableRegistry,
    VariableResolutionStatus,
    _promotion_decision_material,
    stable_source_variable_id,
)
from dynamislm.ingestion.registry import (
    CommittedDatasetRegistry,
    load_committed_dataset_registry,
    registered_dataset_file_identity,
    registry_file_entries,
)
from dynamislm.ingestion.storage import (
    assert_data_path_contained,
    content_addressed_object_path,
    ensure_data_tree,
    file_digest_and_size,
    relative_data_path,
    resolve_data_root,
    resolve_repository_root,
    verify_file,
    write_external_json,
)
from dynamislm.measurement.identity import ScientificIdentifier
from dynamislm.serialization import canonical_hash, canonical_json, from_canonical_json

MAPPING_VERSION_PREFIX = "mapping@"
CANONICAL_JSONL_NEWLINE = "\n"
_EXTERNAL_DATA_ROOT_COMPONENTS = frozenset(
    {"objects", "metadata", "receipts", "canonical", "quarantine"}
)


def build_raw_to_canonical_lineage(
    *,
    source_id: str,
    source_version: str,
    raw_artifact_sha256: str,
    acquisition_receipt_id: str,
    schema_sha256: str,
    source_row_number: int,
    mapping_version: str,
    canonical_record_id: str,
) -> tuple[str, ...]:
    """Build the ordered source-to-record lineage chain required for promotion."""

    return (
        f"dataset-source:{source_id}",
        f"dataset-version:{source_id}@{source_version}",
        f"verified-raw-artifact:{raw_artifact_sha256}",
        f"acquisition-receipt:{acquisition_receipt_id}",
        f"source-schema:{schema_sha256}",
        f"source-row:{source_row_number}",
        f"mapping-version:{mapping_version}",
        f"canonical-record:{canonical_record_id}",
    )


def _lineage_is_complete(record: CanonicalEmpiricalRecord) -> bool:
    required_prefixes = (
        "dataset-source:",
        "dataset-version:",
        "verified-raw-artifact:",
        "acquisition-receipt:",
        "source-schema:",
        "source-row:",
        "mapping-version:",
        "canonical-record:",
    )
    return len(record.lineage) == len(required_prefixes) and all(
        value.startswith(prefix)
        for value, prefix in zip(record.lineage, required_prefixes, strict=True)
    )


def _validate_record(
    record: CanonicalEmpiricalRecord,
    *,
    source_id: str | None = None,
    source_version: str | None = None,
    raw_source_sha256: str | None = None,
    mapping_version: str | None = None,
    variable_registry: SourceVariableRegistry | None = None,
) -> str:
    if not isinstance(record, CanonicalEmpiricalRecord):
        raise ValueError("canonical JSONL records must contain CanonicalEmpiricalRecord values")
    if not record.population_decision.passed or not record.source_decision.passed:
        raise ValueError("non-qualified source or population cannot enter canonical output")
    if not _lineage_is_complete(record):
        raise ValueError("canonical record lineage is incomplete")
    if record.variable_identity.resolution_status in (
        VariableResolutionStatus.UNRESOLVED,
        VariableResolutionStatus.QUARANTINED,
    ):
        raise ValueError("unresolved source variable cannot enter canonical output")
    if source_id is not None and record.source_identity.source_id != source_id:
        raise ValueError("canonical record source ID does not match artifact source ID")
    if source_version is not None and record.version_identity.repository_version != source_version:
        raise ValueError("canonical record version does not match artifact source version")
    if raw_source_sha256 is not None:
        normalized = "sha256:" + raw_source_sha256.removeprefix("sha256:").lower()
        if record.raw_artifact_sha256 != normalized:
            raise ValueError("canonical record raw artifact does not match artifact source")
    if mapping_version is not None and record.mapping_version != mapping_version:
        raise ValueError("canonical record mapping version does not match artifact mapping")
    variable_id = stable_source_variable_id(record.variable_identity)
    if variable_registry is not None:
        variable_registry.entry_for(record.variable_identity)
    return variable_id


def canonical_record_payload(record: CanonicalEmpiricalRecord) -> dict[str, object]:
    """Build one compact canonical payload with a stable variable reference."""

    variable_id = _validate_record(record)
    return {
        "source_id": record.source_identity.source_id,
        "source_persistent_identifier": record.source_identity.persistent_identifier,
        "source_version": record.version_identity.repository_version,
        "version_persistent_identifier": (
            record.version_identity.version_specific_persistent_identifier
        ),
        "raw_artifact_sha256": record.raw_artifact_sha256,
        "source_row_number": record.source_row_number,
        "natural_source_key": record.raw_row_identity.natural_source_key,
        "athlete_id": record.football_context.athlete_id.qualified,
        "session_id": record.football_context.session_id.qualified,
        "observed_date": record.football_context.observed_date,
        "competition_identity": record.football_context.competition_identity,
        "season_identity": record.football_context.season_identity,
        "position": record.football_context.position,
        "session_kind": record.football_context.session_kind,
        "source_variable_id": variable_id,
        "source_reported_value": record.source_reported_value,
        "population_decision_id": record.population_decision.decision_id.stable_id,
        "source_decision_id": record.source_decision.decision_id.stable_id,
        "mapping_version": record.mapping_version,
        "lineage": record.lineage,
    }


def _ordered_variable_index(
    variable_registry: SourceVariableRegistry | None,
) -> dict[str, int]:
    if variable_registry is None:
        return {}
    return {variable_id: index for index, variable_id in enumerate(variable_registry.variable_ids)}


def _stream_lines(
    records: Iterable[CanonicalEmpiricalRecord],
    *,
    variable_registry: SourceVariableRegistry | None,
    source_id: str | None = None,
    source_version: str | None = None,
    raw_source_sha256: str | None = None,
    mapping_version: str | None = None,
    require_monotonic_order: bool = True,
) -> Iterator[tuple[CanonicalEmpiricalRecord, str, str]]:
    variable_order = _ordered_variable_index(variable_registry)
    previous_key: tuple[int, int | str] | None = None
    for record in records:
        variable_id = _validate_record(
            record,
            source_id=source_id,
            source_version=source_version,
            raw_source_sha256=raw_source_sha256,
            mapping_version=mapping_version,
            variable_registry=variable_registry,
        )
        order_value: int | str = variable_order.get(variable_id, variable_id)
        key = (record.source_row_number, order_value)
        if require_monotonic_order and previous_key is not None and key < previous_key:
            raise ValueError("canonical record stream is not in monotonic source order")
        previous_key = key
        yield record, canonical_json(canonical_record_payload(record)), variable_id


def canonical_jsonl_bytes(records: Iterable[CanonicalEmpiricalRecord]) -> bytes:
    """Small-fixture helper; the real artifact writer is streaming."""

    materialized = tuple(records)
    ordered = sorted(
        materialized,
        key=lambda record: (
            record.raw_row_identity.source_row_number,
            record.variable_identity.original_column_name,
            canonical_json(canonical_record_payload(record)),
        ),
    )
    return "".join(
        f"{canonical_json(canonical_record_payload(record))}{CANONICAL_JSONL_NEWLINE}"
        for record in ordered
    ).encode("utf-8")


def _safe_component(value: str) -> str:
    return "".join(
        character if character.isalnum() or character in "._-" else "-" for character in value
    )


def _write_variable_registry(
    data_root: Path,
    variable_registry: SourceVariableRegistry,
    *,
    source_id: str,
    source_version: str,
    mapping_version: str,
) -> str:
    relative_path = (
        f"canonical/{_safe_component(source_id)}-{_safe_component(source_version)}-"
        f"{_safe_component(mapping_version)}-variables.json"
    )
    write_external_json(data_root, relative_path, variable_registry)
    return relative_path


def write_canonical_jsonl(
    records: Iterable[CanonicalEmpiricalRecord],
    *,
    source_id: str,
    source_version: str,
    raw_source_sha256: str,
    mapping_version: str,
    variable_registry: SourceVariableRegistry | None = None,
    metadata_snapshot_sha256: str | None = None,
    data_root: Path | None = None,
    repository_root: Path | None = None,
) -> CanonicalEmpiricalArtifactReceipt:
    """Stream one canonical record at a time into an atomically replaced artifact."""

    resolved_data_root = ensure_data_tree(data_root, repository_root=repository_root)
    inferred_entries: dict[str, SourceVariableIdentity] = {}
    safe_source = _safe_component(source_id)
    safe_mapping = _safe_component(mapping_version)
    relative_path = f"canonical/{safe_source}-{source_version}-{safe_mapping}.jsonl"
    target = assert_data_path_contained(resolved_data_root, resolved_data_root / relative_path)
    assert_data_path_contained(resolved_data_root, target.parent)
    target.parent.mkdir(parents=True, exist_ok=True)
    assert_data_path_contained(resolved_data_root, target.parent)
    assert_data_path_contained(resolved_data_root, target)
    temporary = target.with_name(f".{target.name}.tmp-{os.getpid()}")
    assert_data_path_contained(resolved_data_root, temporary)
    if temporary.exists():
        raise ValueError("canonical artifact temporary path already exists")
    digest = hashlib.sha256()
    record_count = 0
    previous_key: tuple[int, int | str] | None = None
    try:
        with temporary.open("wb") as output:
            variable_order = _ordered_variable_index(variable_registry)
            for record in records:
                variable_id = _validate_record(
                    record,
                    source_id=source_id,
                    source_version=source_version,
                    raw_source_sha256=raw_source_sha256,
                    mapping_version=mapping_version,
                    variable_registry=variable_registry,
                )
                if variable_registry is None:
                    inferred_entries.setdefault(variable_id, record.variable_identity)
                order_value: int | str = variable_order.get(variable_id, variable_id)
                key = (record.source_row_number, order_value)
                if previous_key is not None and key < previous_key:
                    raise ValueError("canonical record stream is not in monotonic source order")
                previous_key = key
                line = (
                    canonical_json(canonical_record_payload(record)) + CANONICAL_JSONL_NEWLINE
                ).encode("utf-8")
                output.write(line)
                digest.update(line)
                record_count += 1
            output.flush()
            os.fsync(output.fileno())
        canonical_digest = f"sha256:{digest.hexdigest()}"
        assert_data_path_contained(resolved_data_root, temporary)
        assert_data_path_contained(resolved_data_root, target.parent)
        assert_data_path_contained(resolved_data_root, target)
        if target.exists():
            existing_digest, _ = file_digest_and_size(target)
            if existing_digest != canonical_digest:
                temporary.unlink()
                raise ValueError("existing canonical path has a different content hash")
            temporary.unlink()
        else:
            os.replace(temporary, target)
            assert_data_path_contained(resolved_data_root, target)

        if variable_registry is None:
            from dynamislm.ingestion.contracts import SourceVariableRegistryEntry

            variable_registry = SourceVariableRegistry(
                source_id=source_id,
                source_version=source_version,
                mapping_version=mapping_version,
                entries=tuple(
                    SourceVariableRegistryEntry(variable_id=variable_id, identity=identity)
                    for variable_id, identity in inferred_entries.items()
                ),
            )
        variable_registry_relative_path = _write_variable_registry(
            resolved_data_root,
            variable_registry,
            source_id=source_id,
            source_version=source_version,
            mapping_version=mapping_version,
        )
        receipt = CanonicalEmpiricalArtifactReceipt(
            source_id=source_id,
            source_version=source_version,
            raw_source_sha256=raw_source_sha256,
            canonical_artifact_sha256=canonical_digest,
            canonical_record_count=record_count,
            mapping_version=mapping_version,
            relative_path=relative_path,
            metadata_snapshot_sha256=metadata_snapshot_sha256,
            variable_registry_sha256=variable_registry.sha256,
            variable_registry_relative_path=variable_registry_relative_path,
        )
        write_external_json(
            resolved_data_root,
            f"receipts/{safe_source}-{source_version}-{safe_mapping}-canonical.json",
            receipt,
        )
        return receipt
    except Exception:
        if temporary.exists():
            temporary.unlink()
        raise


def canonical_replay_digest(
    records: Iterable[CanonicalEmpiricalRecord],
    *,
    variable_registry: SourceVariableRegistry | None = None,
) -> str:
    """Compute a canonical digest from a streamed, already ordered iterator."""

    digest = hashlib.sha256()
    for _, serialized, _ in _stream_lines(
        records,
        variable_registry=variable_registry,
        require_monotonic_order=True,
    ):
        line = (serialized + CANONICAL_JSONL_NEWLINE).encode("utf-8")
        digest.update(line)
    return f"sha256:{digest.hexdigest()}"


def validate_canonical_records(
    records: Iterable[CanonicalEmpiricalRecord],
    *,
    variable_registry: SourceVariableRegistry,
    source_id: str,
    source_version: str,
    raw_source_sha256: str,
    mapping_version: str,
) -> CanonicalValidationReceipt:
    """Derive validation evidence by streaming the exact canonical record iterator."""

    digest = hashlib.sha256()
    lineage_digest = hashlib.sha256()
    context_digest = hashlib.sha256()
    count = 0
    included: list[str] = []
    included_set: set[str] = set()
    for record, serialized, variable_id in _stream_lines(
        records,
        variable_registry=variable_registry,
        source_id=source_id,
        source_version=source_version,
        raw_source_sha256=raw_source_sha256,
        mapping_version=mapping_version,
        require_monotonic_order=True,
    ):
        line = (serialized + CANONICAL_JSONL_NEWLINE).encode("utf-8")
        digest.update(line)
        lineage_digest.update((canonical_json(record.lineage) + "\n").encode("utf-8"))
        context_digest.update((canonical_json(record.football_context) + "\n").encode("utf-8"))
        if variable_id not in included_set:
            included_set.add(variable_id)
            included.append(variable_id)
        count += 1
    return CanonicalValidationReceipt(
        source_id=source_id,
        source_version=source_version,
        raw_source_sha256=raw_source_sha256,
        mapping_version=mapping_version,
        canonical_artifact_sha256=f"sha256:{digest.hexdigest()}",
        canonical_record_count=count,
        variable_registry_sha256=variable_registry.sha256,
        included_variable_ids=tuple(included),
        record_lineage_digest=f"sha256:{lineage_digest.hexdigest()}",
        football_context_digest=f"sha256:{context_digest.hexdigest()}",
    )


def _external_regular_file(data_root: Path, relative_path: str, *, label: str) -> Path:
    if not isinstance(relative_path, str) or not relative_path:
        raise ValueError(f"{label} path must be a non-empty relative POSIX path")
    pure = PurePosixPath(relative_path)
    if (
        "\\" in relative_path
        or pure.is_absolute()
        or pure.as_posix() != relative_path
        or any(part in {".", ".."} for part in pure.parts)
        or not pure.parts
        or pure.parts[0] not in _EXTERNAL_DATA_ROOT_COMPONENTS
    ):
        raise ValueError(f"{label} path is not a controlled DYNAMISLM_DATA_ROOT path")
    target = assert_data_path_contained(data_root, data_root / relative_path)
    current = data_root
    for part in pure.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"{label} path contains a symlink")
    if not target.is_file():
        raise ValueError(f"{label} is missing or is not a regular file: {relative_path}")
    return target


def _read_external_text(data_root: Path, relative_path: str, *, label: str) -> str:
    path = _external_regular_file(data_root, relative_path, label=label)
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"{label} is unreadable: {relative_path}") from exc


def _read_external_typed[T](
    data_root: Path,
    relative_path: str,
    expected_type: type[T],
    *,
    label: str,
) -> T:
    return from_canonical_json(
        _read_external_text(data_root, relative_path, label=label),
        expected_type,
    )


def _read_metadata_snapshot(
    data_root: Path,
    *,
    source_id: str,
    source_version: str,
    expected_sha256: str,
) -> None:
    digest = expected_sha256.removeprefix("sha256:").lower()
    relative_path = f"metadata/{_safe_slug(source_id)}-{_safe_slug(source_version)}-{digest}.json"
    raw = _read_external_text(data_root, relative_path, label="metadata snapshot")
    try:
        metadata = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"metadata snapshot is not valid JSON: {relative_path}") from exc
    if not isinstance(metadata, dict):
        raise ValueError("metadata snapshot must be an object")
    serialized = json.dumps(
        metadata,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    actual_sha256 = f"sha256:{hashlib.sha256(serialized).hexdigest()}"
    if actual_sha256 != f"sha256:{digest}":
        raise ValueError("persisted metadata snapshot digest differs from committed registry")


def _required_registry_text(document: dict[str, Any], key: str) -> str:
    value = document.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"committed registry field {key!r} must be a non-empty string")
    return value


def _normalise_registry_digest(value: object, *, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"committed registry field {field!r} must be a SHA-256 digest")
    digest = value.removeprefix("sha256:").lower()
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise ValueError(f"committed registry field {field!r} must be a SHA-256 digest")
    return f"sha256:{digest}"


def _required_registry_count(document: dict[str, Any], key: str) -> int:
    value = document.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"committed registry field {key!r} must be a non-negative integer")
    return value


def _raw_identity_path(data_root: Path, expected_sha256: str) -> tuple[str, Path]:
    path = content_addressed_object_path(data_root, expected_sha256)
    relative_path = relative_data_path(data_root, path)
    return relative_path, path


def _qualification_receipt_path(source_id: str) -> str:
    return f"receipts/{_safe_slug(source_id)}-qualification.json"


def _verify_persisted_acquisition(
    evidence: PromotionEvidence,
    *,
    registered: RegisteredDatasetFileIdentity,
    registry_entry: dict[str, Any],
    metadata_snapshot_sha256: str,
    raw_relative_path: str,
    data_root: Path,
) -> ArtifactAcquisitionReceipt:
    receipt_relative_path = _receipt_path(
        data_root,
        registered.source_id,
        registered.source_version,
        "acquisition",
    )
    persisted = _read_external_typed(
        data_root,
        receipt_relative_path,
        ArtifactAcquisitionReceipt,
        label="acquisition receipt",
    )
    if persisted != evidence.verified_raw_artifact.acquisition_receipt:
        raise ValueError("persisted acquisition receipt differs from evidence")
    expected_fields: tuple[tuple[str, object], ...] = (
        ("source_id", registered.source_id),
        ("source_version", registered.source_version),
        ("representation", registered.representation),
        ("provider_file_id", registered.provider_file_id),
        ("original_filename", registered.filename),
        ("media_type", registered.media_type),
        ("sha256", registered.expected_sha256),
        ("byte_size", registered.expected_byte_size),
        ("provider_hash", registered.provider_hash),
        ("provider_hash_algorithm", registered.provider_hash_algorithm),
        ("metadata_snapshot_sha256", metadata_snapshot_sha256),
        ("storage_relative_path", raw_relative_path),
    )
    for field_name, expected in expected_fields:
        if getattr(persisted, field_name) != expected:
            raise ValueError(f"persisted acquisition receipt {field_name} differs from registry")
    download_url = registry_entry.get("download_url")
    if download_url is not None and persisted.requested_url != download_url:
        raise ValueError("persisted acquisition receipt URL differs from registry")
    return persisted


def _verify_saved_original_receipt(
    *,
    registered: RegisteredDatasetFileIdentity,
    registry_entry: dict[str, Any],
    registry_document: dict[str, Any],
    metadata_snapshot_sha256: str,
    data_root: Path,
) -> None:
    if registered.provider_hash_representation is not FileRepresentation.SAVED_ORIGINAL:
        return
    audit = registry_document.get("representation_audit")
    if not isinstance(audit, dict):
        raise ValueError("committed registry lacks saved-original representation audit")
    expected_relative_path = _receipt_path(
        data_root,
        registered.source_id,
        registered.source_version,
        "saved-original-verification",
    )
    if audit.get("provider_verification_receipt") != expected_relative_path:
        raise ValueError("committed saved-original receipt path is not deterministic")
    if registered.provider_file_id is None or registered.file_persistent_identifier is None:
        raise ValueError("saved-original registry identity lacks provider file ID or PID")
    if registered.provider_hash is None or registered.provider_hash_algorithm is None:
        raise ValueError("saved-original registry identity lacks provider hash authority")
    persisted = _read_external_typed(
        data_root,
        expected_relative_path,
        SavedOriginalVerificationReceipt,
        label="saved-original verification receipt",
    )
    expected_fields: tuple[tuple[str, object], ...] = (
        ("source_id", registered.source_id),
        ("source_version", registered.source_version),
        ("provider_file_id", registered.provider_file_id),
        ("file_persistent_identifier", registered.file_persistent_identifier),
        ("representation", FileRepresentation.SAVED_ORIGINAL),
        ("provider_hash_algorithm", registered.provider_hash_algorithm),
        ("provider_hash", registered.provider_hash),
        ("observed_md5", registered.provider_hash),
        ("metadata_snapshot_sha256", metadata_snapshot_sha256),
    )
    for field_name, expected in expected_fields:
        actual = getattr(persisted, field_name)
        if field_name in {"provider_hash", "observed_md5"}:
            if not isinstance(actual, str) or not isinstance(expected, str):
                raise ValueError(f"saved-original receipt {field_name} differs from registry")
            if actual.lower() != expected.lower():
                raise ValueError(f"saved-original receipt {field_name} differs from registry")
        elif actual != expected:
            raise ValueError(f"saved-original receipt {field_name} differs from registry")
    saved_original_size = registry_entry.get("saved_original_byte_size")
    if (
        isinstance(saved_original_size, bool)
        or not isinstance(saved_original_size, int)
        or persisted.observed_byte_size != saved_original_size
    ):
        raise ValueError("saved-original receipt byte size differs from registry")
    if audit.get("saved_original_md5") != persisted.observed_md5:
        raise ValueError("saved-original audit MD5 differs from persisted receipt")
    if audit.get("saved_original_byte_size") != persisted.observed_byte_size:
        raise ValueError("saved-original audit byte size differs from persisted receipt")


def _verify_committed_external_authority(
    evidence: PromotionEvidence,
    *,
    committed: CommittedDatasetRegistry,
    data_root: Path,
) -> None:
    if not committed.working_tree_matches_head:
        raise ValueError("WORKTREE_REGISTRY_MATCHES_HEAD=FAIL; promotion is blocked")

    registry_entries = registry_file_entries(committed.document)
    if not registry_entries:
        raise ValueError("committed registry contains no dataset file identity")
    try:
        registered = registered_dataset_file_identity(
            committed.document,
            representation=evidence.registered_file_identity.representation,
        )
    except ValueError as exc:
        raise ValueError(
            "REGISTERED_IDENTITY_SUBSTITUTION: representation is not in committed registry"
        ) from exc
    if evidence.registered_file_identity != registered:
        raise ValueError("REGISTERED_IDENTITY_SUBSTITUTION: evidence identity differs from HEAD")
    if evidence.qualification.source_id != registered.source_id:
        raise ValueError("promotion qualification source does not match committed registry")
    if evidence.qualification.source_version != registered.source_version:
        raise ValueError("promotion qualification version does not match committed registry")
    if evidence.verified_raw_artifact.representation is not registered.representation:
        raise ValueError("promotion artifact representation does not match committed registry")

    registry_entry = next(
        (
            entry
            for entry in registry_entries
            if entry.get("representation") == registered.representation.value
        ),
        None,
    )
    if registry_entry is None:
        raise ValueError("committed registry file entry cannot be selected deterministically")
    metadata_snapshot_sha256 = _normalise_registry_digest(
        committed.document.get("metadata_snapshot_sha256"),
        field="metadata_snapshot_sha256",
    )
    _read_metadata_snapshot(
        data_root,
        source_id=registered.source_id,
        source_version=registered.source_version,
        expected_sha256=metadata_snapshot_sha256,
    )
    raw_relative_path, raw_path = _raw_identity_path(data_root, registered.expected_sha256)
    _external_regular_file(data_root, raw_relative_path, label="raw content-addressed object")
    actual_sha256, actual_byte_size = file_digest_and_size(raw_path)
    if actual_sha256 != registered.expected_sha256:
        raise ValueError("actual raw object SHA-256 differs from committed registry")
    if actual_byte_size != registered.expected_byte_size:
        raise ValueError("actual raw object byte size differs from committed registry")

    persisted_acquisition = _verify_persisted_acquisition(
        evidence,
        registered=registered,
        registry_entry=registry_entry,
        metadata_snapshot_sha256=metadata_snapshot_sha256,
        raw_relative_path=raw_relative_path,
        data_root=data_root,
    )
    artifact = evidence.verified_raw_artifact
    if (
        artifact.sha256 != actual_sha256
        or artifact.byte_size != actual_byte_size
        or artifact.relative_path != raw_relative_path
        or artifact.media_type != registered.media_type
    ):
        raise ValueError("verified raw artifact does not identify the actual committed raw object")
    try:
        source_version_receipt = verify_registered_artifact(
            registered,
            artifact,
            data_root=data_root,
            repository_root=committed.repository_root,
        )
    except (OSError, ValueError) as exc:
        raise ValueError("actual raw bytes failed registered artifact verification") from exc
    if source_version_receipt != evidence.source_version_verification:
        raise ValueError("source-version verification receipt is not derived from actual bytes")
    if persisted_acquisition != artifact.acquisition_receipt:
        raise ValueError("verified artifact acquisition receipt is not persisted authority")

    qualification_relative_path = _qualification_receipt_path(registered.source_id)
    persisted_qualification = _read_external_typed(
        data_root,
        qualification_relative_path,
        DatasetQualificationReceipt,
        label="qualification receipt",
    )
    if persisted_qualification != evidence.qualification:
        raise ValueError("persisted qualification receipt differs from evidence")
    _verify_saved_original_receipt(
        registered=registered,
        registry_entry=registry_entry,
        registry_document=committed.document,
        metadata_snapshot_sha256=metadata_snapshot_sha256,
        data_root=data_root,
    )

    canonical_block = committed.document.get("canonical_artifact")
    if not isinstance(canonical_block, dict):
        raise ValueError("committed registry lacks canonical_artifact identity")
    canonical_relative_path = _required_registry_text(canonical_block, "relative_path")
    canonical_sha256 = _normalise_registry_digest(
        canonical_block.get("sha256"),
        field="canonical_artifact.sha256",
    )
    canonical_record_count = _required_registry_count(canonical_block, "record_count")
    mapping_version = _required_registry_text(canonical_block, "mapping_version")
    variable_registry_sha256 = _normalise_registry_digest(
        canonical_block.get("variable_registry_sha256"),
        field="canonical_artifact.variable_registry_sha256",
    )
    variable_registry_relative_path = _required_registry_text(
        canonical_block,
        "variable_registry_relative_path",
    )
    variable_registry = _read_external_typed(
        data_root,
        variable_registry_relative_path,
        SourceVariableRegistry,
        label="variable registry sidecar",
    )
    if variable_registry != evidence.variable_registry:
        raise ValueError("persisted variable registry sidecar differs from evidence")
    if variable_registry.sha256 != variable_registry_sha256:
        raise ValueError("variable registry SHA-256 differs from committed registry")
    validation = evidence.canonical_validation
    if validation.variable_registry_sha256 != variable_registry.sha256:
        raise ValueError("canonical validation variable registry differs from sidecar")
    if validation.mapping_version != variable_registry.mapping_version:
        raise ValueError("canonical validation mapping differs from sidecar")
    if (
        variable_registry.source_id != registered.source_id
        or variable_registry.source_version != registered.source_version
        or variable_registry.mapping_version != mapping_version
    ):
        raise ValueError("variable registry source/version/mapping is not committed authority")
    if (
        validation.source_id != registered.source_id
        or validation.source_version != registered.source_version
        or validation.raw_source_sha256 != registered.expected_sha256
        or validation.mapping_version != mapping_version
        or validation.canonical_artifact_sha256 != canonical_sha256
        or validation.canonical_record_count != canonical_record_count
    ):
        raise ValueError("canonical validation identity differs from committed artifact")

    canonical_receipt_relative_path = _receipt_path(
        data_root,
        registered.source_id,
        registered.source_version,
        f"{_safe_slug(mapping_version)}-canonical",
    )
    persisted_canonical_receipt = _read_external_typed(
        data_root,
        canonical_receipt_relative_path,
        CanonicalEmpiricalArtifactReceipt,
        label="canonical artifact receipt",
    )
    expected_canonical_receipt = CanonicalEmpiricalArtifactReceipt(
        source_id=registered.source_id,
        source_version=registered.source_version,
        raw_source_sha256=registered.expected_sha256,
        canonical_artifact_sha256=canonical_sha256,
        canonical_record_count=canonical_record_count,
        mapping_version=mapping_version,
        relative_path=canonical_relative_path,
        metadata_snapshot_sha256=metadata_snapshot_sha256,
        variable_registry_sha256=variable_registry_sha256,
        variable_registry_relative_path=variable_registry_relative_path,
    )
    if persisted_canonical_receipt != expected_canonical_receipt:
        raise ValueError("persisted canonical artifact receipt differs from committed registry")
    _external_regular_file(data_root, canonical_relative_path, label="canonical artifact")
    try:
        verify_canonical_artifact(
            data_root / canonical_relative_path,
            expected_sha256=canonical_sha256,
            expected_record_count=canonical_record_count,
        )
    except (OSError, ValueError) as exc:
        raise ValueError("actual canonical artifact differs from committed registry") from exc


def _promotion_decision_from_validated_evidence(evidence: PromotionEvidence) -> PromotionDecision:
    """Build a descriptive decision after operational authority checks have passed."""

    from dynamislm.ingestion.contracts import promotion_gate_results

    gates = promotion_gate_results(evidence)
    reasons = tuple(f"{name}_FAILED" for name, value in gates if not value)
    decision_key = canonical_hash(
        {"evidence": _promotion_decision_material(evidence), "gates": gates}
    ).removeprefix("sha256:")
    decision_id = ScientificIdentifier(
        "dynamislm",
        "promotion-decision",
        decision_key,
        "1.1.0",
    )
    return PromotionDecision(
        decision_id=decision_id,
        status=PromotionStatus.PROMOTED
        if all(value for _, value in gates)
        else PromotionStatus.QUARANTINED,
        reason_codes=reasons,
        evidence=evidence,
    )


def promotion_from_evidence(
    evidence: PromotionEvidence,
    *,
    repository_root: Path,
    data_root: Path,
) -> PromotionDecision:
    """Authorize promotion only after re-verifying Git and external evidence.

    ``PromotionEvidence`` and ``PromotionDecision`` are immutable descriptive
    records.  This function is the operational authorization boundary: it
    derives the current committed registry from Git ``HEAD`` and independently
    verifies the persisted evidence and content-addressed bytes before it
    constructs a decision.
    """

    if not isinstance(evidence, PromotionEvidence):
        raise ValueError("evidence must be a PromotionEvidence")
    resolved_repository_root = resolve_repository_root(repository_root)
    resolved_data_root = resolve_data_root(
        data_root,
        repository_root=resolved_repository_root,
    )
    committed = load_committed_dataset_registry(
        evidence.registered_file_identity.source_id,
        repository_root=resolved_repository_root,
    )
    _verify_committed_external_authority(
        evidence,
        committed=committed,
        data_root=resolved_data_root,
    )
    return _promotion_decision_from_validated_evidence(evidence)


def verify_canonical_artifact(
    path: Path,
    *,
    expected_sha256: str,
    expected_record_count: int,
) -> None:
    """Verify an existing JSONL artifact without loading it into memory."""

    verify_file(path, expected_sha256=expected_sha256)
    if (
        isinstance(expected_record_count, bool)
        or not isinstance(expected_record_count, int)
        or expected_record_count < 0
    ):
        raise ValueError("expected_record_count must be a non-negative integer")
    with path.open("rb") as artifact:
        record_count = sum(1 for line in artifact if line.rstrip(b"\r\n"))
    if record_count != expected_record_count:
        raise ValueError("canonical artifact record count does not match its receipt")


def validate_canonical_replay(
    first: Iterable[CanonicalEmpiricalRecord],
    second: Iterable[CanonicalEmpiricalRecord],
    *,
    variable_registry: SourceVariableRegistry | None = None,
) -> None:
    """Fail closed when two streamed canonicalizations diverge."""

    first_digest = canonical_replay_digest(first, variable_registry=variable_registry)
    second_digest = canonical_replay_digest(second, variable_registry=variable_registry)
    if first_digest != second_digest:
        raise ValueError("canonical replay digests differ")


__all__ = [
    "CANONICAL_JSONL_NEWLINE",
    "MAPPING_VERSION_PREFIX",
    "build_raw_to_canonical_lineage",
    "canonical_jsonl_bytes",
    "canonical_record_payload",
    "canonical_replay_digest",
    "promotion_from_evidence",
    "validate_canonical_records",
    "validate_canonical_replay",
    "verify_canonical_artifact",
    "write_canonical_jsonl",
]
