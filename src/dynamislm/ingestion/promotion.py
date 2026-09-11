"""RES-63 typed promotion authority and bounded canonical replay writers."""

from __future__ import annotations

import datetime as datetime_module
import hashlib
import json
import math
import os
import re
from collections.abc import Iterable, Iterator
from pathlib import Path, PurePosixPath
from typing import Any, cast

from dynamislm.ingestion.acquisition import (
    _receipt_path,
    _safe_slug,
    verify_registered_artifact,
)
from dynamislm.ingestion.contracts import (
    ArtifactAcquisitionReceipt,
    CanonicalEmpiricalArtifactReceipt,
    CanonicalEmpiricalRecord,
    CanonicalFootballContext,
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
    SourceVariableRegistryEntry,
    VariableResolutionStatus,
    _promotion_decision_material,
    stable_source_variable_id,
)
from dynamislm.ingestion.registry import (
    CommittedDatasetRegistry,
    committed_qualification_receipt_identity,
    dataset_license_identity,
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
from dynamislm.measurement.identity import (
    InstanceIdentifier,
    ScientificIdentifier,
)
from dynamislm.population.models import CompetitionIdentity, SeasonIdentity
from dynamislm.serialization import (
    SERIALIZATION_VERSION,
    canonical_hash,
    canonical_json,
    from_canonical_json,
    type_identifier,
)

MAPPING_VERSION_PREFIX = "mapping@"
CANONICAL_JSONL_NEWLINE = "\n"
_EXTERNAL_DATA_ROOT_COMPONENTS = frozenset(
    {"objects", "metadata", "receipts", "canonical", "quarantine"}
)
_CANONICAL_RECORD_PAYLOAD_KEYS = frozenset(
    {
        "source_id",
        "source_persistent_identifier",
        "source_version",
        "version_persistent_identifier",
        "raw_artifact_sha256",
        "source_row_number",
        "natural_source_key",
        "athlete_id",
        "session_id",
        "observed_date",
        "competition_identity",
        "season_identity",
        "position",
        "session_kind",
        "source_variable_id",
        "source_reported_value",
        "population_decision_id",
        "source_decision_id",
        "mapping_version",
        "lineage",
    }
)
_CANONICAL_ENVELOPE_KEYS = frozenset({"payload", "serialization_version", "type"})
_LINEAGE_PREFIXES = (
    "dataset-source:",
    "dataset-version:",
    "verified-raw-artifact:",
    "acquisition-receipt:",
    "source-schema:",
    "source-row:",
    "mapping-version:",
    "canonical-record:",
)
_SHA256_HEX_RE = re.compile(r"^[0-9a-fA-F]{64}$")


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


def _lineage_has_required_prefixes(lineage: tuple[str, ...]) -> bool:
    return len(lineage) == len(_LINEAGE_PREFIXES) and all(
        value.startswith(prefix) for value, prefix in zip(lineage, _LINEAGE_PREFIXES, strict=True)
    )


def _lineage_is_complete(record: CanonicalEmpiricalRecord) -> bool:
    return _lineage_has_required_prefixes(record.lineage)


def _canonical_validation_semantic_bytes(
    lineage: tuple[str, ...],
    football_context: CanonicalFootballContext,
) -> tuple[bytes, bytes]:
    """Return the exact lineage/context bytes used by every validator."""

    return (
        (canonical_json(lineage) + CANONICAL_JSONL_NEWLINE).encode("utf-8"),
        (canonical_json(football_context) + CANONICAL_JSONL_NEWLINE).encode("utf-8"),
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
        lineage_bytes, context_bytes = _canonical_validation_semantic_bytes(
            record.lineage,
            record.football_context,
        )
        lineage_digest.update(lineage_bytes)
        context_digest.update(context_bytes)
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


def _reject_duplicate_json_keys(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"canonical JSON contains duplicate key: {key}")
        result[key] = value
    return result


def _reject_nonfinite_json_constant(value: str) -> object:
    raise ValueError(f"canonical JSON contains non-finite number: {value}")


def _parse_persisted_canonical_line(line: bytes, *, line_number: int) -> dict[str, object]:
    if not line.endswith(b"\n") or line.endswith(b"\r\n") or line == b"\n":
        raise ValueError(f"canonical JSONL line {line_number} must end in one LF and contain data")
    body = line[:-1]
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"canonical JSONL line {line_number} is not UTF-8") from exc
    try:
        decoded = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_json_keys,
            parse_constant=_reject_nonfinite_json_constant,
        )
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"canonical JSONL line {line_number} is not deterministic JSON") from exc
    if not isinstance(decoded, dict):
        raise ValueError(f"canonical JSONL line {line_number} envelope is not an object")
    envelope = cast(dict[str, object], decoded)
    if set(envelope) != _CANONICAL_ENVELOPE_KEYS:
        raise ValueError(f"canonical JSONL line {line_number} envelope fields are invalid")
    serialization_version = envelope["serialization_version"]
    if (
        isinstance(serialization_version, bool)
        or not isinstance(serialization_version, int)
        or serialization_version != SERIALIZATION_VERSION
    ):
        raise ValueError(
            f"canonical JSONL line {line_number} has an unsupported serialization version"
        )
    if envelope["type"] != type_identifier(dict):
        raise ValueError(f"canonical JSONL line {line_number} has an invalid envelope type")
    payload_value = envelope["payload"]
    if not isinstance(payload_value, dict):
        raise ValueError(f"canonical JSONL line {line_number} payload is not an object")
    payload = cast(dict[str, object], payload_value)
    if set(payload) != _CANONICAL_RECORD_PAYLOAD_KEYS:
        raise ValueError(f"canonical JSONL line {line_number} payload fields are invalid")
    try:
        canonical_body = json.dumps(
            envelope,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError(f"canonical JSONL line {line_number} is not canonically encoded") from exc
    if canonical_body != body:
        raise ValueError(f"canonical JSONL line {line_number} is not canonically encoded")
    return payload


def _persisted_payload_text(payload: dict[str, object], field_name: str) -> str:
    value = payload[field_name]
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"canonical payload field {field_name!r} must be non-empty text")
    return value


def _persisted_payload_optional_text(payload: dict[str, object], field_name: str) -> str | None:
    value = payload[field_name]
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"canonical payload field {field_name!r} must be non-empty text or null")
    return value


def _persisted_payload_instance_identifier(
    payload: dict[str, object],
    field_name: str,
    instance_type: str,
) -> InstanceIdentifier:
    qualified = _persisted_payload_text(payload, field_name)
    prefix = f"{instance_type}:"
    if not qualified.startswith(prefix) or qualified == prefix:
        raise ValueError(f"canonical payload field {field_name!r} has an invalid instance identity")
    return InstanceIdentifier(instance_type, qualified.removeprefix(prefix))


def _persisted_scientific_identifier(value: object, *, field_name: str) -> ScientificIdentifier:
    if not isinstance(value, dict):
        raise ValueError(f"canonical context field {field_name!r} identifier is not an object")
    identity = cast(dict[str, object], value)
    expected_keys = {"__type__", "namespace", "object_type", "key", "version"}
    if set(identity) != expected_keys or identity.get("__type__") != type_identifier(
        ScientificIdentifier
    ):
        raise ValueError(f"canonical context field {field_name!r} identifier is invalid")
    return ScientificIdentifier(
        namespace=_persisted_nested_text(identity, "namespace", field_name),
        object_type=_persisted_nested_text(identity, "object_type", field_name),
        key=_persisted_nested_text(identity, "key", field_name),
        version=_persisted_nested_text(identity, "version", field_name),
    )


def _persisted_nested_text(
    value: dict[str, object],
    field_name: str,
    parent_field_name: str,
) -> str:
    nested = value[field_name]
    if not isinstance(nested, str) or not nested.strip():
        raise ValueError(
            f"canonical context field {parent_field_name!r} {field_name!r} must be non-empty text"
        )
    return nested


def _persisted_context_reference_parts(
    value: object,
    *,
    field_name: str,
    expected_type: str,
) -> tuple[ScientificIdentifier, str] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError(f"canonical context field {field_name!r} must be an object or null")
    reference = cast(dict[str, object], value)
    if set(reference) != {"__type__", "identifier", "display_label"}:
        raise ValueError(f"canonical context field {field_name!r} has invalid fields")
    if reference.get("__type__") != expected_type:
        raise ValueError(f"canonical context field {field_name!r} has an invalid type")
    identifier = _persisted_scientific_identifier(
        reference["identifier"],
        field_name=field_name,
    )
    display_label = _persisted_nested_text(reference, "display_label", field_name)
    return identifier, display_label


def _persisted_football_context(payload: dict[str, object]) -> CanonicalFootballContext:
    observed_date_text = _persisted_payload_text(payload, "observed_date")
    try:
        observed_date = datetime_module.date.fromisoformat(observed_date_text)
    except ValueError as exc:
        raise ValueError("canonical payload observed_date is not an ISO calendar date") from exc
    competition_parts = _persisted_context_reference_parts(
        payload["competition_identity"],
        field_name="competition_identity",
        expected_type=type_identifier(CompetitionIdentity),
    )
    season_parts = _persisted_context_reference_parts(
        payload["season_identity"],
        field_name="season_identity",
        expected_type=type_identifier(SeasonIdentity),
    )
    position = _persisted_payload_optional_text(payload, "position")
    session_kind = _persisted_payload_text(payload, "session_kind")
    return CanonicalFootballContext(
        athlete_id=_persisted_payload_instance_identifier(payload, "athlete_id", "athlete"),
        session_id=_persisted_payload_instance_identifier(payload, "session_id", "session"),
        observed_date=observed_date,
        competition_identity=(
            CompetitionIdentity(*competition_parts) if competition_parts is not None else None
        ),
        season_identity=SeasonIdentity(*season_parts) if season_parts is not None else None,
        position=position,
        session_kind=session_kind,
    )


def _normalise_persisted_digest(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"canonical payload field {field_name!r} must be a SHA-256 digest")
    digest = value.removeprefix("sha256:")
    if _SHA256_HEX_RE.fullmatch(digest) is None:
        raise ValueError(f"canonical payload field {field_name!r} must be a SHA-256 digest")
    return f"sha256:{digest.lower()}"


def _validate_persisted_lineage(
    lineage_value: object,
    *,
    source_id: str,
    source_version: str,
    raw_source_sha256: str,
    source_row_number: int,
    mapping_version: str,
    original_column_name: str,
) -> tuple[str, ...]:
    if not isinstance(lineage_value, list) or len(lineage_value) != len(_LINEAGE_PREFIXES):
        raise ValueError("canonical record lineage must contain the complete eight-step chain")
    if any(not isinstance(value, str) for value in lineage_value):
        raise ValueError("canonical record lineage must contain only strings")
    lineage = tuple(cast(str, value) for value in lineage_value)
    if not _lineage_has_required_prefixes(lineage):
        raise ValueError("canonical record lineage is incomplete")
    if lineage[0] != f"dataset-source:{source_id}":
        raise ValueError("canonical record lineage source ID is inconsistent")
    if lineage[1] != f"dataset-version:{source_id}@{source_version}":
        raise ValueError("canonical record lineage source version is inconsistent")
    if lineage[2] != f"verified-raw-artifact:{raw_source_sha256}":
        raise ValueError("canonical record lineage raw artifact is inconsistent")
    acquisition_identity = lineage[3].removeprefix("acquisition-receipt:")
    if not acquisition_identity or any(character.isspace() for character in acquisition_identity):
        raise ValueError("canonical record lineage acquisition receipt is malformed")
    schema_digest = lineage[4].removeprefix("source-schema:")
    if _SHA256_HEX_RE.fullmatch(schema_digest.removeprefix("sha256:")) is None:
        raise ValueError("canonical record lineage source schema is malformed")
    if lineage[5] != f"source-row:{source_row_number}":
        raise ValueError("canonical record lineage source row is inconsistent")
    if lineage[6] != f"mapping-version:{mapping_version}":
        raise ValueError("canonical record lineage mapping is inconsistent")
    expected_canonical_id = (
        f"{source_id}:{source_version}:{source_row_number}:{original_column_name}"
    )
    if lineage[7] != f"canonical-record:{expected_canonical_id}":
        raise ValueError("canonical record lineage canonical-record identity is inconsistent")
    return lineage


def _validate_persisted_payload(
    payload: dict[str, object],
    *,
    source_id: str,
    source_version: str,
    raw_source_sha256: str,
    mapping_version: str,
    variable_entries: dict[str, SourceVariableRegistryEntry],
) -> tuple[int, str, tuple[str, ...], CanonicalFootballContext]:
    if _persisted_payload_text(payload, "source_id") != source_id:
        raise ValueError("canonical record source ID does not match committed source")
    if _persisted_payload_text(payload, "source_version") != source_version:
        raise ValueError("canonical record source version does not match committed source")
    if (
        _normalise_persisted_digest(
            payload["raw_artifact_sha256"],
            field_name="raw_artifact_sha256",
        )
        != raw_source_sha256
    ):
        raise ValueError("canonical record raw artifact does not match committed source")
    if _persisted_payload_text(payload, "mapping_version") != mapping_version:
        raise ValueError("canonical record mapping version does not match committed mapping")
    source_row_number = payload["source_row_number"]
    if isinstance(source_row_number, bool) or not isinstance(source_row_number, int):
        raise ValueError("canonical record source row number must be an integer")
    if source_row_number < 1:
        raise ValueError("canonical record source row number must be positive")
    natural_source_key = payload["natural_source_key"]
    if natural_source_key is not None and (
        not isinstance(natural_source_key, str) or not natural_source_key.strip()
    ):
        raise ValueError("canonical record natural source key must be non-empty text or null")
    source_reported_value = payload["source_reported_value"]
    if source_reported_value is not None and not isinstance(
        source_reported_value,
        str | int | float | bool,
    ):
        raise ValueError("canonical record source-reported value must be a JSON scalar")
    if isinstance(source_reported_value, float) and not math.isfinite(source_reported_value):
        raise ValueError("canonical record source-reported value must be finite")
    _persisted_payload_text(payload, "source_persistent_identifier")
    _persisted_payload_optional_text(payload, "version_persistent_identifier")
    _persisted_payload_text(payload, "population_decision_id")
    _persisted_payload_text(payload, "source_decision_id")
    variable_id = _persisted_payload_text(payload, "source_variable_id")
    entry = variable_entries.get(variable_id)
    if entry is None:
        raise ValueError(
            "canonical record source variable is not in the verified variable registry"
        )
    if entry.identity.resolution_status in (
        VariableResolutionStatus.UNRESOLVED,
        VariableResolutionStatus.QUARANTINED,
    ):
        raise ValueError("canonical record source variable is not resolved in the registry")
    lineage = _validate_persisted_lineage(
        payload["lineage"],
        source_id=source_id,
        source_version=source_version,
        raw_source_sha256=raw_source_sha256,
        source_row_number=source_row_number,
        mapping_version=mapping_version,
        original_column_name=entry.identity.original_column_name,
    )
    context = _persisted_football_context(payload)
    return source_row_number, variable_id, lineage, context


def validate_persisted_canonical_artifact(
    path: Path,
    *,
    variable_registry: SourceVariableRegistry,
    source_id: str,
    source_version: str,
    raw_source_sha256: str,
    mapping_version: str,
) -> CanonicalValidationReceipt:
    """Stream persisted canonical JSONL and recompute all validation semantics."""

    if path.is_symlink() or not path.is_file():
        raise ValueError("persisted canonical artifact is missing or is not a regular file")
    normalized_raw_source_sha256 = _normalise_persisted_digest(
        raw_source_sha256,
        field_name="raw_source_sha256",
    )
    if (
        variable_registry.source_id != source_id
        or variable_registry.source_version != source_version
        or variable_registry.mapping_version != mapping_version
    ):
        raise ValueError("verified variable registry is not bound to canonical validation inputs")
    variable_entries: dict[str, SourceVariableRegistryEntry] = {
        entry.variable_id: entry for entry in variable_registry.entries
    }
    digest = hashlib.sha256()
    lineage_digest = hashlib.sha256()
    context_digest = hashlib.sha256()
    count = 0
    included: list[str] = []
    included_set: set[str] = set()
    previous_key: tuple[int, int | str] | None = None
    variable_order = _ordered_variable_index(variable_registry)
    try:
        with path.open("rb") as artifact:
            for line_number, line in enumerate(artifact, start=1):
                payload = _parse_persisted_canonical_line(line, line_number=line_number)
                source_row_number, variable_id, lineage, context = _validate_persisted_payload(
                    payload,
                    source_id=source_id,
                    source_version=source_version,
                    raw_source_sha256=normalized_raw_source_sha256,
                    mapping_version=mapping_version,
                    variable_entries=variable_entries,
                )
                order_value: int | str = variable_order[variable_id]
                key = (source_row_number, order_value)
                if previous_key is not None and key < previous_key:
                    raise ValueError(
                        "persisted canonical record stream is not in monotonic source order"
                    )
                previous_key = key
                digest.update(line)
                lineage_bytes, context_bytes = _canonical_validation_semantic_bytes(
                    lineage,
                    context,
                )
                lineage_digest.update(lineage_bytes)
                context_digest.update(context_bytes)
                if variable_id not in included_set:
                    included_set.add(variable_id)
                    included.append(variable_id)
                count += 1
    except OSError as exc:
        raise ValueError(f"could not read persisted canonical artifact: {path}") from exc
    return CanonicalValidationReceipt(
        source_id=source_id,
        source_version=source_version,
        raw_source_sha256=normalized_raw_source_sha256,
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


def _read_external_typed_with_digest[T](
    data_root: Path,
    relative_path: str,
    expected_type: type[T],
    *,
    label: str,
    expected_sha256: str | None = None,
) -> tuple[T, str]:
    """Read one external typed object once, binding its bytes and decoded value."""

    path = _external_regular_file(data_root, relative_path, label=label)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ValueError(f"{label} is unreadable: {relative_path}") from exc
    digest = f"sha256:{hashlib.sha256(raw).hexdigest()}"
    if expected_sha256 is not None and digest != expected_sha256:
        raise ValueError(
            "QUALIFICATION_RECEIPT_ROOT_BINDING: external receipt digest differs from HEAD"
        )
    try:
        text = raw.decode("utf-8")
        value = from_canonical_json(text, expected_type)
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValueError(f"{label} is not a valid typed canonical object") from exc
    return value, digest


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
    committed_license = dataset_license_identity(committed.document)
    if evidence.license_identity != committed_license:
        raise ValueError("COMMITTED_LICENSE_AUTHORITY: evidence license differs from HEAD")
    if evidence.qualification.license_identity != committed_license:
        raise ValueError("COMMITTED_LICENSE_AUTHORITY: qualification license differs from HEAD")
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

    qualification_identity = committed_qualification_receipt_identity(committed.document)
    persisted_qualification, _ = _read_external_typed_with_digest(
        data_root,
        qualification_identity.relative_path,
        DatasetQualificationReceipt,
        label="qualification receipt",
        expected_sha256=qualification_identity.sha256,
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
    canonical_path = _external_regular_file(
        data_root,
        canonical_relative_path,
        label="canonical artifact",
    )
    try:
        recomputed_validation = validate_persisted_canonical_artifact(
            canonical_path,
            variable_registry=variable_registry,
            source_id=registered.source_id,
            source_version=registered.source_version,
            raw_source_sha256=registered.expected_sha256,
            mapping_version=mapping_version,
        )
    except (OSError, ValueError) as exc:
        raise ValueError("PERSISTED_CANONICAL_VALIDATION=FAIL") from exc
    if recomputed_validation != validation:
        raise ValueError(
            "CANONICAL_VALIDATION_RECOMPUTED_FROM_BYTES: persisted semantics differ from evidence"
        )
    if (
        recomputed_validation.canonical_artifact_sha256 != canonical_sha256
        or recomputed_validation.canonical_record_count != canonical_record_count
    ):
        raise ValueError("actual canonical artifact differs from committed registry")


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
    "validate_persisted_canonical_artifact",
    "verify_canonical_artifact",
    "write_canonical_jsonl",
]
