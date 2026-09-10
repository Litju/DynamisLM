"""RES-63 typed promotion authority and bounded canonical replay writers."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Iterable, Iterator
from pathlib import Path

from dynamislm.ingestion.contracts import (
    CanonicalEmpiricalArtifactReceipt,
    CanonicalEmpiricalRecord,
    CanonicalValidationReceipt,
    PromotionDecision,
    PromotionEvidence,
    PromotionStatus,
    SourceVariableIdentity,
    SourceVariableRegistry,
    VariableResolutionStatus,
    _promotion_decision_material,
    stable_source_variable_id,
)
from dynamislm.ingestion.storage import (
    ensure_data_tree,
    file_digest_and_size,
    relative_data_path,
    verify_file,
    write_external_json,
)
from dynamislm.measurement.identity import ScientificIdentifier
from dynamislm.serialization import canonical_hash, canonical_json

MAPPING_VERSION_PREFIX = "mapping@"
CANONICAL_JSONL_NEWLINE = "\n"


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
    target = (resolved_data_root / relative_path).resolve(strict=False)
    if relative_data_path(resolved_data_root, target) != relative_path:
        raise ValueError("canonical artifact path escaped DYNAMISLM_DATA_ROOT")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.tmp-{os.getpid()}")
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
        if target.exists():
            existing_digest, _ = file_digest_and_size(target)
            if existing_digest != canonical_digest:
                temporary.unlink()
                raise ValueError("existing canonical path has a different content hash")
            temporary.unlink()
        else:
            os.replace(temporary, target)

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


def promotion_from_evidence(evidence: PromotionEvidence) -> PromotionDecision:
    """Construct the sole promotion decision from validated typed evidence."""

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
